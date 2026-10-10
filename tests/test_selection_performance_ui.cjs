const assert = require('node:assert/strict');
const test = require('node:test');
const ui = require('../chanlun/report_assets/selection-performance.js');

function observation(id, date, value, options = {}) {
  const outcomes = Object.fromEntries([1, 3, 5, 10, 20, 30].map((n) => [
    `t${n}`, {status: value === null ? 'price_basis_unverified' : 'ready',
      return_pct: value, target_date: `2026-09-${String(n + 1).padStart(2, '0')}`,
      start_close: 100, end_close: value === null ? null : 100 + value}
  ]));
  return {observation_id: id, instrument_id: `SH${id}`, code: id,
    name: options.name || id, report_date: date,
    publication_ref: {report_date: date, snapshot_id: `published-${date}`},
    theme_refs: options.themes || [], strategy_refs: options.strategies || [],
    outcomes};
}

function fixture(rows) {
  return {schema_version: 'selection-performance-v1', dataset_id: 'fixed-fixture',
    report_as_of: '2026-09-30', evaluation_as_of: '2026-09-30T15:20:00+08:00',
    horizons: [1, 3, 5, 10, 20, 30],
    trading_dates: Array.from({length: 65}, (_, i) =>
      `2026-${i < 35 ? '08' : '09'}-${String((i % 30) + 1).padStart(2, '0')}`),
    observations: rows};
}

test('six cycles share the same complete filtered cohort and extrema', () => {
  const rows = [
    observation('600001', '2026-09-01', 10, {themes: [{theme_id: 'ai', name: 'AI'}]}),
    observation('600002', '2026-09-01', -5, {themes: [{theme_id: 'battery', name: '电池'}]}),
    observation('600003', '2026-09-01', 0, {themes: [{theme_id: 'ai', name: 'AI'}, {theme_id: 'battery', name: '电池'}]}),
  ];
  const data = fixture(rows);
  for (const horizon of data.horizons) {
    const all = ui.computeView(data, {horizon, reportStart: '2026-09-01'});
    assert.equal(all.summary.total_observations, 3);
    assert.equal(all.summary.counts.ready, 3);
    assert.equal(all.summary.mean_return_pct, 5 / 3);
    assert.equal(all.summary.best_observations[0].observation_id, '600001');
    assert.equal(all.summary.worst_observations[0].observation_id, '600002');
    assert.equal(all.groups.themes.find((g) => g.id === 'ai').summary.total_observations, 2);
    const aiRow = ui.renderHtml(all).match(/data-sp-theme="ai"[\s\S]*?<\/button>/)[0];
    assert.match(aiRow, /最好.*600001/);
    assert.match(aiRow, /最差.*600003/);
    const battery = ui.computeView(data, {horizon, themeId: 'battery', reportStart: '2026-09-01'});
    assert.equal(battery.summary.total_observations, 2);
    assert.equal(battery.summary.best_observations[0].observation_id, '600003');
    assert.deepEqual(battery.details.map((x) => x.observation_id), ['600002', '600003']);
    assert.match(ui.renderHtml(battery), /当前题材：电池/);
    assert.equal(battery.groups.themes.find((g) => g.id === 'battery').summary.total_observations, 2);
    assert.equal(battery.groups.themes.some((g) => g.id === 'ai' && g.summary.total_observations === 2), false);
  }
});

test('formal selection requires an eligible actionable ref of the same strategy', () => {
  const partial = {strategy_key: 'a', role: 'formal', recommendation_scope: 'published_observation'};
  const research = {strategy_key: 'b', role: 'research', recommendation_scope: 'published_observation'};
  const eligible = {strategy_key: 'a', role: 'formal', recommendation_scope: 'formal_recommendation'};
  const data = fixture([
    observation('600001', '2026-09-01', 10, {strategies: [partial, research]}),
    observation('600002', '2026-09-01', -1, {strategies: [eligible, research]}),
  ]);
  const view = ui.computeView(data, {horizon: 1, role: 'formal', strategyKey: 'a'});
  assert.equal(view.summary.total_observations, 1);
  assert.equal(view.details[0].code, '600002');
  assert.deepEqual(view.groups.strategies.map((group) => group.id), ['a']);
});

test('empty, negative, tied, and one-result cohorts preserve truthful extrema', () => {
  const data = fixture([
    observation('600001', '2026-09-01', -2),
    observation('600002', '2026-09-02', -2),
    observation('600003', '2026-09-03', null),
  ]);
  const all = ui.computeView(data, {horizon: 1});
  assert.equal(all.summary.mean_return_pct, -2);
  assert.equal(all.summary.best_observations.length, 2);
  assert.equal(all.summary.worst_observations.length, 2);
  const single = ui.computeView(data, {horizon: 1, reportStart: '2026-09-02', reportEnd: '2026-09-02'});
  assert.equal(single.summary.best_observations[0].observation_id, single.summary.worst_observations[0].observation_id);
  const empty = ui.computeView(data, {horizon: 1, reportStart: '2026-09-03'});
  assert.equal(empty.summary.mean_return_pct, null);
  assert.equal(empty.summary.counts.price_basis_unverified, 1);
  assert.match(ui.renderHtml(empty), /价基未核验/);
  assert.doesNotMatch(ui.renderHtml(empty), /0\.00%/);
});

test('detail pagination never changes complete cohort summary and hostile text is escaped', () => {
  const rows = Array.from({length: 25}, (_, i) => observation(String(600001 + i), '2026-09-01', i,
    {name: i === 0 ? '<img src=x onerror=alert(1)>' : i === 1 ? '/private/secret/token' : `证券${i}`}));
  const data = fixture(rows);
  const first = ui.computeView(data, {horizon: 1, page: 0, pageSize: 10});
  const last = ui.computeView(data, {horizon: 1, page: 2, pageSize: 10});
  assert.equal(first.summary.total_observations, 25);
  assert.equal(last.summary.total_observations, 25);
  assert.equal(last.summary.best_observations[0].code, '600025');
  assert.equal(last.details.length, 5);
  const html = ui.renderHtml(first);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(!html.includes('<img src=x'));
  assert.ok(!html.includes('/private/'));
});

test('loader rejects stale response and retains prior dated result after update failure', async () => {
  const pending = [];
  const loader = ui.createLoader((url) => new Promise((resolve, reject) => pending.push({url, resolve, reject})));
  const a = loader.load('2026-09-29', 'data/selection-performance/2026-09-29.json');
  const b = loader.load('2026-09-30', 'data/selection-performance/2026-09-30.json');
  pending[1].resolve(fixture([observation('600001', '2026-09-01', 10)]));
  assert.equal((await b).dataset.dataset_id, 'fixed-fixture');
  pending[0].resolve({...fixture([]), dataset_id: 'stale'});
  assert.equal((await a).stale, true);
  const c = loader.load('2026-09-30', 'data/selection-performance/2026-09-30.json', true);
  pending[2].reject(new Error('/private/secret path'));
  const failed = await c;
  assert.equal(failed.dataset.dataset_id, 'fixed-fixture');
  assert.equal(failed.updateFailed, true);
  assert.ok(!JSON.stringify(failed).includes('secret path'));
});

test('mount loads report-bound dataset and falls back only to a prior dated result', async () => {
  const prior = {...fixture([observation('600001', '2026-09-01', 10)]),
    dataset_id: 'prior', report_as_of: '2026-09-29',
    evaluation_as_of: '2026-09-29T15:20:00+08:00'};
  const urls = [];
  const root = {innerHTML: '', addEventListener() {}};
  const app = ui.mount(root, {pageDate: '2026-09-30', dataBasePrefix: '../',
    fetchJson: async (url) => {
      urls.push(url);
      if (url.endsWith('/2026-09-30.json')) throw new Error('missing');
      if (url.endsWith('/index.json')) return {dates: ['2026-09-29', '2026-10-01']};
      if (url.endsWith('/2026-09-29.json')) return prior;
      throw new Error('unexpected');
    }});
  await app.ready;
  assert.deepEqual(urls, [
    '../data/selection-performance/2026-09-30.json',
    '../data/selection-performance/index.json',
    '../data/selection-performance/2026-09-29.json',
  ]);
  assert.match(root.innerHTML, /2026-09-29T15:20:00\+08:00/);
  assert.match(root.innerHTML, /更新失败/);
  assert.ok(!root.innerHTML.includes('2026-10-01T'));
  app.setFilters({horizon: 30});
  assert.match(root.innerHTML, /T\+30/);
});

test('score sort appears only for one recorded definition in one strategy identity', () => {
  const good = (score) => ({strategy_key: 'one-version', role: 'research',
    recommendation_scope: 'published_observation', score_name: '当时策略分',
    score_definition: 'v1-definition', score_definition_status: 'recorded', score});
  const data = fixture([
    observation('600001', '2026-09-01', 1, {strategies: [good(60)]}),
    observation('600002', '2026-09-01', 2, {strategies: [good(90)]}),
  ]);
  const view = ui.computeView(data, {horizon: 1, strategyKey: 'one-version', view: 'details', sortByScore: true});
  assert.equal(view.details[0].code, '600002');
  assert.match(ui.renderHtml(view), /按当时策略分排序/);
  data.observations[1].strategy_refs[0].score_definition = null;
  const unknown = ui.computeView(data, {horizon: 1, strategyKey: 'one-version', view: 'details', sortByScore: true});
  assert.equal(unknown.scoreSort, null);
  assert.doesNotMatch(ui.renderHtml(unknown), /按当时策略分排序/);
});

test('automatic historical load refuses a future evaluation cutoff', async () => {
  const loader = ui.createLoader(async () => ({...fixture([]),
    report_as_of: '2026-09-29', evaluation_as_of: '2026-10-01T15:20:00+08:00'}));
  const result = await loader.load('2026-09-30', 'data/selection-performance/2026-09-29.json');
  assert.equal(result.dataset, null);
  assert.equal(result.updateFailed, true);
});

test('one missing cycle in a partial dataset keeps other verified results visible', () => {
  const valid = observation('600001', '2026-09-01', 10);
  const partial = observation('600002', '2026-09-01', 20);
  delete partial.outcomes.t1;
  const view = ui.computeView(fixture([valid, partial]), {horizon: 1});
  assert.equal(view.summary.counts.ready, 1);
  assert.equal(view.summary.counts.result_unavailable, 1);
  assert.equal(view.summary.mean_return_pct, 10);
  assert.match(ui.renderHtml(view), /结果缺项/);
  const partialCard = ui.renderHtml(view).match(/id="sp-observation-600002"[\s\S]*?<\/article>/)[0];
  assert.match(partialCard, /结果缺项/);
});

test('strategy groups retain recorded version and entry identity', () => {
  const version = (key, name) => ({strategy_key: key, strategy_id: 'main',
    strategy_version: name, entry_mode: 'published_close', role: 'research',
    recommendation_scope: 'published_observation'});
  const data = fixture([
    observation('600001', '2026-09-01', 10, {strategies: [version('v1-key', 'v1')]}),
    observation('600002', '2026-09-01', -10, {strategies: [version('v2-key', 'v2')]}),
  ]);
  const view = ui.computeView(data, {horizon: 1, view: 'strategies'});
  assert.equal(view.groups.strategies.length, 2);
  assert.equal(view.groups.strategies[0].summary.total_observations, 1);
  assert.match(ui.renderHtml(view), /v1/);
  assert.match(ui.renderHtml(view), /v2/);
  assert.match(ui.renderHtml(view), /published_close/);
});

test('detail keeps each recorded source score without inventing a shared definition', () => {
  const data = fixture([observation('600001', '2026-09-01', 10, {strategies: [
    {strategy_key: 'a', strategy_id: 'main', role: 'formal',
      recommendation_scope: 'formal_recommendation', score: 25,
      score_name: null, score_definition: null, score_definition_status: 'unrecorded'},
    {strategy_key: 'b', strategy_id: 'research', role: 'research',
      recommendation_scope: 'published_observation', score: 0,
      score_name: '研究分', score_definition: 'research-v1', score_definition_status: 'recorded'},
  ]})]);
  const html = ui.renderHtml(ui.computeView(data, {horizon: 1, view: 'details'}));
  const card = html.match(/id="sp-observation-600001"[\s\S]*?<\/article>/)[0];
  assert.match(card, /main/);
  assert.match(card, /当时记录分数 25.*定义未记录/);
  assert.match(card, /research/);
  assert.match(card, /研究分 0/);
  assert.doesNotMatch(html, /按当时策略分排序/);
});

test('observed 312 observations and 240 stocks with no ready return do not claim 240 result stocks', () => {
  // Frozen local preview shape: 263 basis-unverified, 49 waiting, 0 ready.
  const rows = Array.from({length: 312}, (_, i) => {
    const id = String(600001 + (i % 240));
    const row = observation(`o-${i}`, '2026-09-16', null);
    row.instrument_id = `SH${id}`;
    row.code = id;
    row.outcomes.t1 = {status: i < 263 ? 'price_basis_unverified' : 'waiting',
      return_pct: null, target_date: '2026-09-17'};
    return row;
  });
  const data = fixture(rows);
  data.coverage = {published_report_dates: 8, registered_observations: 312, unique_stocks: 240};
  const view = ui.computeView(data, {horizon: 1});
  assert.equal(view.summary.unique_stocks, 240, 'backend mother-cohort meaning must stay intact');
  const html = ui.renderHtml(view);
  assert.match(html, /已有结果 0 笔（0 只）/);
  assert.match(html, /应跟踪 312 笔（240 只）/);
  assert.doesNotMatch(html, /已有结果 0 笔（240 只）/);
});

test('coverage line counts calendar unknown and excluded only when nonzero', () => {
  const ready = observation('600001', '2026-09-01', 5);
  const unknown = observation('600002', '2026-09-01', null);
  const excluded = observation('600003', '2026-09-01', null);
  unknown.outcomes.t1 = {status: 'calendar_unknown', return_pct: null};
  excluded.outcomes.t1 = {status: 'excluded', return_pct: null};
  const view = ui.computeView(fixture([ready, unknown, excluded]), {horizon: 1});
  const counts = view.summary.counts;
  assert.equal(Object.values(counts).reduce((total, n) => total + n, 0), 3);
  const html = ui.renderHtml(view);
  assert.match(html, /已有结果 1 笔（1 只）/);
  assert.match(html, /应跟踪 3 笔（3 只）/);
  assert.match(html, /日期未核验 1 笔/);
  assert.match(html, /已排除 1 笔/);
  const allReady = ui.renderHtml(ui.computeView(fixture([ready]), {horizon: 1}));
  assert.doesNotMatch(allReady, /日期未核验 \d+ 笔/);
  assert.doesNotMatch(allReady, /已排除 \d+ 笔/);
});
