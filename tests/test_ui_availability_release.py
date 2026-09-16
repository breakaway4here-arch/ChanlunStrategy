"""Round 7 availability contracts for the published report UI.

These tests are deliberately limited to the availability release boundary:
the published ref-to-chart path, local degradation of optional facts, the
three current-detail entry points, and source/purpose preservation.  They do
not enable or specify the rejected cross-period fact merger.
"""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class UIAvailabilityRelease(unittest.TestCase):
    def test_published_ref_pool_candidate_keeps_real_ohlc(self):
        _assert_node_contract(self, "{ find: findRawCandidate, state: state }", r'''
const t = globalThis.__auxTest;
t.state.data = {
  date: '2026-09-11',
  startup_watchlist: [{
    code: '000636', name: '风华高科',
    dates: ['2026-09-10', '2026-09-11'],
    opens: [50.0, 51.5], highs: [52.0, 55.99],
    lows: [49.0, 51.09], closes: [51.0, 55.99]
  }]
};
t.state.rawPoolCandidates = null;
const raw = t.find({ pool: 'startup_watchlist', code: '000636' });
if (!raw || raw.code !== '000636' || raw.closes[1] !== 55.99)
  throw new Error('published ref pool did not return the real OHLC candidate');
''')

    def test_ohlc_chart_survives_missing_quantity_and_moving_average_series(self):
        _assert_node_contract(self, "{ chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
let option = null;
const mount = { innerHTML: '', isConnected: true };
const lane = { innerHTML: '' };
const switcher = { innerHTML: '', querySelectorAll() { return []; } };
window.echarts = { init(node) { return {
  getDom() { return node; },
  setOption(value) { option = value; },
  getOption() { return option || {}; },
  dispose() {}, resize() {}
}; } };
        t.state.data = { date: '2026-09-11' };
t.state.chartMount = mount;
t.state.chartAnnotationLane = lane;
t.state.chartLayerSwitcher = switcher;
t.state.chartLayer = 'decision';
const raw = {
  code: '000636', snapshot_id: '2026-09-11',
  dates: ['2026-09-10', '2026-09-11'],
  opens: [50.0, 51.5], highs: [52.0, 55.99],
  lows: [49.0, 51.09], closes: [51.0, 55.99],
  volumes: [], ema5: [], ema20: [], ma5: [], ma10: [],
  chart_annotations: { markPoints: [], markLines: [], labels: [] }
};
t.chart(raw, { code: '000636', snapshot_id: '2026-09-11' });
const candle = (option.series || []).find((series) => series.type === 'candlestick');
if (!candle || candle.data.length !== 2)
  throw new Error('OHLC series disappeared when optional series were missing');
const last = candle.data[candle.data.length - 1];
if (JSON.stringify(last) !== JSON.stringify([51.5, 55.99, 51.09, 55.99]))
  throw new Error('OHLC values were changed while degrading optional modules');
''')

    def test_short_judgment_keeps_real_next_and_cancel_conditions(self):
        _assert_node_contract(self, "{ brief: buildUnifiedShortJudgment }", r'''
const t = globalThis.__auxTest;
const html = t.brief({
  code: '000636', primary_reason: '等待回踩',
  next_confirmation: [], invalidation: [], blocking_reasons: []
}, { risk_and_next: {
  status: 'available',
  next_confirmation: { status: 'available', items: [{ text: '回踩 55.00 确认' }] },
  cancel_conditions: { status: 'available', items: [{ text: '跌破 51.00 取消' }] }
} }, false, 'formal', 'after');
if (!html.includes('回踩 55.00 确认') || !html.includes('跌破 51.00 取消'))
  throw new Error('real next/cancel conditions were not shown in the short judgment');
if (html.includes('具体失效条件待补充'))
  throw new Error('real cancel condition was replaced by the missing-condition placeholder');
''')

    def test_not_applicable_conditions_are_explicit_without_claiming_satisfied(self):
        _assert_node_contract(self, "{ brief: buildUnifiedShortJudgment }", r'''
const t = globalThis.__auxTest;
const html = t.brief({
  code: '900003', primary_reason: '条件不适用于本期',
  next_confirmation: [], invalidation: [], blocking_reasons: []
}, { risk_and_next: {
  status: 'available',
  next_confirmation: { status: 'not_applicable', items: [], empty_text: '本期不适用下一核验' },
  cancel_conditions: { status: 'not_applicable', items: [], empty_text: '本期不适用取消条件' }
} }, false, 'formal', 'after');
if (!html.includes('本期不适用下一核验') || !html.includes('本期不适用取消条件'))
  throw new Error('not-applicable condition status was reduced to generic missing text');
if (html.includes('已满足') || html.includes('条件已完整'))
  throw new Error('not-applicable conditions were presented as satisfied');
''')

    def test_selected_quick_comparison_exposes_current_detail_action(self):
        _assert_node_contract(self, "{ render: renderQuickComparison, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '000636', name: '风华高科', page_status: 'formal_ready',
  action_semantics: 'formal', formal_action: '可上车' };
t.state.data = {
  date: '2026-09-11',
  selection_input_health: {
    schema_version: 2, status: 'verified',
    by_view: { main: { status: 'verified', formal_actions_allowed: true } },
    by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
  }
};
t.state.workspace = { views: { main: [item] }, view_meta: {
  main: { role: 'formal', action_semantics: 'formal', availability: { state: 'available' } }
} };
t.state.currentView = 'main';
t.state.quickComparison = {
  selectedKeys: ['2026-09-11::main::000636'], selectedItems: {
    '2026-09-11::main::000636': item
  }, message: '', max: 3
};
const target = { innerHTML: '', querySelectorAll() { return []; } };
const html = t.render(target);
if (!html.includes('data-quick-detail="000636"')
    || !html.includes('查看当前图表'))
  throw new Error('selected comparison did not expose a current-detail action');
''')

    def test_changes_panel_only_offers_current_chart_for_current_members(self):
        _assert_node_contract(self, "{ render: renderDecisionChangesPanel, state: state }", r'''
const t = globalThis.__auxTest;
const current = { id: 'id-000636', code: '000636', name: '风华高科',
  candidate: { code: '000636', name: '风华高科' } };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-11', decisionWorkbench: {
  schema_version: 'decision-workbench-v1', report_date: '2026-09-11', phase: 'formal',
  snapshot_id: 'current-snapshot', version: 'v1', items: [current],
  changes: { status: 'available', previous_report_date: '2026-09-10',
    added: ['000636'], removed: ['600644'], changed: [] }
} };
        t.state.data = { date: '2026-09-11', selection_input_health: {
          schema_version: 2, status: 'verified',
          by_view: { main: { status: 'verified', formal_actions_allowed: true } },
          by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
        } };
const target = { innerHTML: '', querySelectorAll() { return []; } };
const html = t.render(target);
if (!html.includes('data-change-current="000636"') || !html.includes('查看当前图表'))
  throw new Error('current member had no current-chart action');
if (html.includes('data-change-current="600644"'))
  throw new Error('removed-only member was offered a fabricated current chart');
''')

    def test_unverified_legacy_reference_keeps_its_purpose_in_history_source(self):
        _assert_node_contract(self, "{ source: renderDecisionHistorySource }", r'''
const t = globalThis.__auxTest;
const html = t.source({ source: '旧来源', record: {
  code: '600184', reference_price: 19.8,
  reference_price_purpose: 'raw_reference',
  reference_price_purpose_status: 'unverified',
  role: 'research', action: '仅观察', report_date: '2026-09-10',
  workbench_item: { strategy_results: [{ strategy_id: 'main', role: 'formal',
    formal_action: '可上车', contract: { reference_price: 10, invalidation_price: 9,
      price_basis: 'qfq', intended_horizon: 'T+3' }, evidence: {} }] }
} }, null);
        if (!html.includes('参考价 10') || !html.includes('19.80'))
  throw new Error('formal contract or legacy raw reference value was dropped');
if (!/用途未核验|原始记录参考/.test(html))
  throw new Error('legacy reference purpose was presented as an ordinary formal price');
''')

    def test_quick_comparison_keeps_formal_contract_and_unverified_raw_reference(self):
        _assert_node_contract(self, "{ dimension: quickComparisonDimensionValues, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600184', name: '复合来源股', reference_price: 19.8,
  reference_price_purpose: 'raw_reference', reference_price_purpose_status: 'unverified',
  strategy_results: [{ strategy_id: 'main', role: 'formal', formal_action: '可上车',
    contract: { reference_price: 10, invalidation_price: 9, intended_horizon: 'T+3', price_basis: 'qfq' },
    evidence: { summary: { status: 'available' } } }] };
const before = JSON.stringify(item);
const prices = t.dimension(item)['关键价位'];
        if (!prices.includes('参考价 10') || !prices.includes('19.80'))
  throw new Error('comparison replaced one source price with another');
if (!/用途未核验|原始记录参考/.test(prices))
  throw new Error('comparison hid the raw reference purpose status');
if (JSON.stringify(item) !== before)
  throw new Error('comparison renderer mutated the source record');
''')

    def test_comparison_source_carries_contract_reference_purpose_to_all_views(self):
        _assert_node_contract(self, "{ source: comparisonStrategySource, text: comparisonStrategySourceText, dimension: quickComparisonDimensionValues, render: renderCandidateEvidenceComparison, state: state }", r'''
const t = globalThis.__auxTest;
const strategy = { strategy_id: 'confirming', role: 'research', formal_action: '仅观察',
  contract: { reference_price: 10, invalidation_price: 9, intended_horizon: 'T+1',
    purpose: 'raw_reference', purpose_status: 'unverified', price_basis: 'unknown' },
  evidence: {} };
const item = { code: '000636', is_executable: false, strategy_results: [strategy] };
const sourceModel = t.source(strategy);
const text = t.text(sourceModel);
const dimensions = t.dimension(item);
const purposeMarker = '用途未核验，仅原始记录';
if (!sourceModel.prices.includes('参考价 10') || !sourceModel.prices.includes(purposeMarker))
  throw new Error('contract reference purpose was dropped from the source model');
if (!text.includes(purposeMarker) || !dimensions['身份与来源动作'].includes(purposeMarker)
    || !dimensions['关键价位'].includes(purposeMarker))
  throw new Error('contract reference purpose did not reach every comparison consumer');
t.state.data = { date: '2026-08-14', selection_input_health: {
  schema_version: 2, status: 'verified',
  by_view: { main: { status: 'verified', formal_actions_allowed: true } },
  by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
} };
t.state.workspace = { views: { main: [{ code: '000636', name: '研究样本', workbench_item: item }] },
  view_meta: { main: { role: 'formal', action_semantics: 'formal', availability: { state: 'available' } } } };
t.state.currentView = 'main';
const fullComparison = t.render('main', t.state.data);
if (!fullComparison.includes(purposeMarker))
  throw new Error('full evidence comparison dropped the contract reference purpose');
''')

    def test_comparison_source_handles_contract_aliases_and_verified_purpose(self):
        _assert_node_contract(self, "{ source: comparisonStrategySource, text: comparisonStrategySourceText }", r'''
const t = globalThis.__auxTest;
const aliased = t.source({ strategy_id: 'main', role: 'formal', formal_action: '可上车',
  formal_decision_contract: { reference_price: 12, invalidation_price: 11,
    purpose_status: 'verified', price_basis: 'qfq' }, evidence: {} });
if (!aliased.prices.includes('参考价 12') || aliased.prices.includes('用途未核验'))
  throw new Error('verified aliased contract lost its clean purpose');
if (t.text(aliased).includes('用途未核验'))
  throw new Error('verified aliased contract was downgraded in source text');
const missing = t.source({ strategy_id: 'mystery', role: 'unknown', formal_action: '仅观察',
  decision_contract: { reference_price: 13, price_basis: 'qfq' }, evidence: {} });
if (!missing.prices.includes('参考价 13') || !missing.prices.includes('用途未核验'))
  throw new Error('missing purpose on a contract alias was treated as verified');
''')

    def test_quick_comparison_labels_unfinished_conditions_by_explicit_identity(self):
        _assert_node_contract(self, "{ dimension: quickComparisonDimensionValues, state: state }", r'''
const t = globalThis.__auxTest;
const formal = { code: '600001', is_executable: false, strategy_results: [{
  strategy_id: 'main', role: 'formal', formal_action: '可上车', contract: {}, evidence: {}
}] };
const research = { code: '600002', is_executable: false, strategy_results: [{
  strategy_id: 'confirming', role: 'research', formal_action: null, contract: {},
  evidence: { risk_and_next: { next_confirmation: { status: 'available', items: ['等待回踩'] } } }
}] };
const watchOnly = { code: '600003', is_executable: false, strategy_results: [{
  strategy_id: 'observation_watchlist', role: 'watch_only', action_semantics: 'watch_only',
  formal_action: '仅观察', contract: {}, evidence: {}
}] };
const unknown = { code: '600004', is_executable: false, strategy_results: [{
  strategy_id: 'mystery', formal_action: null, contract: {}, evidence: {}
}] };
if (t.dimension(formal)['未满足条件'] !== '正式条件尚未完整')
  throw new Error('formal unfinished conditions lost their formal wording');
if (t.dimension(research)['未满足条件'] === '正式条件尚未完整'
    || !/仅观察|未记录具体阻碍/.test(t.dimension(research)['未满足条件']))
  throw new Error('research identity was promoted to formal pending wording');
if (t.dimension(watchOnly)['未满足条件'] === '正式条件尚未完整'
    || !/仅观察|未记录具体阻碍/.test(t.dimension(watchOnly)['未满足条件']))
  throw new Error('watch-only identity was promoted to formal pending wording');
if (t.dimension(unknown)['未满足条件'] !== '未记录具体阻碍')
  throw new Error('unknown identity was turned into a formal or satisfied claim');
const blocked = { code: '600005', is_executable: false, blocking_reasons: ['证据不可用'],
  strategy_results: [{ strategy_id: 'confirming', role: 'research', contract: {}, evidence: {} }] };
if (t.dimension(blocked)['未满足条件'] !== '证据不可用')
  throw new Error('explicit blocking reason was replaced by identity copy');
''')

    def test_history_source_rows_keep_same_strategy_versions_and_contract_plans(self):
        _assert_node_contract(self, "{ source: renderDecisionHistorySource }", r'''
const t = globalThis.__auxTest;
const strategy = (version, contractId, reference) => ({ strategy_id: 'main',
  strategy_version: version, contract_id: contractId, role: 'formal',
  formal_action: '等回踩', contract: {
    reference_price: reference, invalidation_price: reference - 1,
    price_basis: 'qfq', intended_horizon: 'T+3'
  }, evidence: { summary: { status: 'available' } } });
const html = t.source({ source: '统一来源', record: {
  code: '600184', workbench_item: { strategy_results: [
    strategy('sv1', 'P', 10), strategy('sv1', 'Q', 11), strategy('sv2', 'P', 10)
  ] }
} }, null);
if ((html.match(/class="decision-history-source"/g) || []).length !== 3
    || !html.includes('策略版本 sv1') || !html.includes('策略版本 sv2')
    || !html.includes('合同 P') || !html.includes('合同 Q')
    || !html.includes('参考价 10') || !html.includes('参考价 11'))
  throw new Error('same-strategy versions or distinct contract plans were merged or hidden');
''')

    def test_history_entries_keep_version_conflicts_and_attached_raw_source(self):
        _assert_node_contract(self, "{ entries: decisionHistoryEntries }", r'''
const t = globalThis.__auxTest;
const row = (version, marker) => ({ code: '600184', version,
  strategy_version: version, source_marker: marker, phase: 'formal',
  report_date: '2026-09-10' });
const payload = { workspace: { views: { main: [row('sv1', 'workspace-v1'), row('sv2', 'workspace-v2')] } },
  picks_fusion: [row('sv2', 'raw-attached')] };
const projection = { items: [row('sv2', 'projection')] };
const rows = t.entries(payload, '600184', projection, { version: 'sv2', phase: 'formal', date: '2026-09-10' });
const markers = rows.map((entry) => entry.record.source_marker);
if (!markers.includes('workspace-v1') || !markers.includes('workspace-v2') || !markers.includes('projection')
    || !markers.includes('raw-attached'))
  throw new Error('history source rows were silently replaced by a preferred source/version');
const old = rows.find((entry) => entry.record.source_marker === 'workspace-v1');
if (!old.validation || old.validation.versionStatus !== 'conflict')
  throw new Error('the retained conflicting version lost its validation status');
''')

    def test_same_missing_risk_is_not_rendered_as_comparable_same_fact(self):
        _assert_node_contract(self, "{ dimension: quickComparisonDimensionValues, dimensionHtml: quickComparisonDimensionHtml, state: state }", r'''
const t = globalThis.__auxTest;
const missing = (code) => ({ code, name: code, strategy_results: [{ strategy_id: 'main', role: 'formal',
  evidence: { risk_and_next: { status: 'missing', risk_labels: [],
    next_confirmation: { status: 'missing', items: [] }, cancel_conditions: { status: 'missing', items: [] } } }
}] });
const a = missing('600184');
const b = missing('002600');
const cell = t.dimensionHtml('主要风险', [{ item: a }, { item: b }], 0);
if (cell.includes('is-same'))
  throw new Error('identical missing-risk placeholders were marked as a verified same fact');
if (cell.includes('is-different'))
  throw new Error('identical missing-risk placeholders were marked as a factual difference');
const values = t.dimension(a);
if (!values['主要风险'].includes('未登记') || values['未满足条件'].includes('已满足'))
  throw new Error('missing risk/conditions were presented as satisfied facts');
''')

    def test_filtered_quick_comparison_remove_and_readd_keeps_one_selection(self):
        _assert_node_contract(self, "{ toggle: toggleQuickComparisonSelection, render: renderQuickComparison, state: state, nodes: nodes }", r'''
const t = globalThis.__auxTest;
const item = { code: '000636', name: '风华高科', page_status: 'watch_only' };
const other = { code: '002600', name: '领益智造', page_status: 'watch_only' };
t.state.data = { date: '2026-09-11', selection_input_health: {
  schema_version: 2, status: 'verified',
  by_view: {
    main: { status: 'verified', formal_actions_allowed: true },
    other: { status: 'verified', formal_actions_allowed: true }
  },
  by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
} };
t.state.workspace = { views: { main: [item], other: [other] }, view_meta: {
  main: { role: 'research', action_semantics: 'watch_only', availability: { state: 'available' } },
  other: { role: 'research', action_semantics: 'watch_only', availability: { state: 'available' } }
} };
t.state.currentView = 'main';
t.state.quickComparison = { selectedKeys: [], selectedItems: {}, message: '', max: 3 };
let removeHandler = null;
const removeButton = {
  getAttribute(name) { return (name === 'data-quick-key' || name === 'data-quick-remove') ? this.value : ''; },
  addEventListener(name, handler) { if (name === 'click') removeHandler = handler; }
};
const comparisonTarget = { html: '', querySelectorAll(selector) {
  return selector === '[data-quick-remove]' ? [removeButton] : [];
} };
Object.defineProperty(comparisonTarget, 'innerHTML', {
  get() { return this.html; },
  set(value) {
    this.html = value;
    const match = String(value).match(/data-quick-key="([^"]+)"/);
    removeButton.value = match ? match[1] : '';
  }
});
t.nodes.candidateQuickComparison = comparisonTarget;
if (!t.toggle(item)) throw new Error('initial comparison selection failed');
t.state.currentView = 'other';
t.render(t.nodes.candidateQuickComparison);
const storedKey = '2026-09-11::main::000636';
if (removeButton.value !== storedKey || !removeHandler)
  throw new Error('filtered-out removal did not retain the selected stored key');
removeHandler({ currentTarget: removeButton });
if (t.state.quickComparison.selectedKeys.length !== 0)
  throw new Error('filtered-out selected stock was not removed by its stored key');
t.state.currentView = 'main';
if (!t.toggle('000636')) throw new Error('removed stock could not be re-added in its original view');
if (t.state.quickComparison.selectedKeys.length !== 1)
  throw new Error('remove/re-add created duplicate comparison selections');
''')

    def test_missing_optional_fact_panel_has_no_fabricated_zero_or_risk(self):
        _assert_node_contract(self, "{ facts: renderCandidateFactPanel }", r'''
const html = globalThis.__auxTest.facts({
  code: '900003', name: '缺量样本',
  data_status: { status: 'missing', daily: 'missing' },
  pool_quality: { money20: null, market_cap: null, circulating_market_cap: null }
});
if (!html.includes('量能与参考位数据未提供'))
  throw new Error('missing optional facts had no local empty state');
if (html.includes('0.00') || html.includes('无风险') || html.includes('已满足'))
  throw new Error('missing optional facts were fabricated as zero or satisfied');
''')

    def test_ref_source_does_not_borrow_same_code_from_another_pool(self):
        _assert_node_contract(self, "{ find: findRawCandidate, state: state }", r'''
const t = globalThis.__auxTest;
const primary = { code: '600184', source: 'pool-a', price_basis: 'qfq',
  data_status: { latest_date: '2026-09-11' }, dates: [], opens: [], highs: [], lows: [], closes: [] };
const borrowed = { code: '600184', source: 'pool-b', price_basis: 'hfq',
  data_status: { latest_date: '2026-09-11' }, dates: ['2026-09-10', '2026-09-11'],
  opens: [1, 2], highs: [2, 3], lows: [0.5, 1], closes: [1.5, 2.5] };
t.state.data = { date: '2026-09-11', startup_watchlist: [primary], picks_fusion: [borrowed] };
t.state.rawPoolCandidates = null;
const direct = t.find({ pool: 'startup_watchlist', code: '600184' });
if (direct !== primary || direct.dates.length)
  throw new Error('source ref borrowed OHLC from another pool');
const unknownPool = t.find({ pool: 'highlights', code: '600184' });
if (unknownPool !== null)
  throw new Error('unknown source ref fell back to the first same-code raw record');
''')

    def test_unverified_raw_reference_stays_text_only_and_off_chart(self):
        _assert_node_contract(self, "{ calc: getCandidateReferencePriceForCalculation, price: buildPriceSection, chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600101', reference_price: 10, current_price: 11,
  data_status: { daily: 'verified', latest_date: '2026-08-14', is_final: true, stale: false },
  contract: { reference_price: 10, purpose: 'raw_reference', purpose_status: 'unverified', price_basis: 'unknown' } };
const raw = { code: '600101', data_status: item.data_status,
  dates: ['2026-08-13', '2026-08-14'], opens: [10, 10.5], highs: [10.5, 11],
  lows: [9.5, 10], closes: [10, 11],
  chart_annotations: { markLines: [{ name: '参考价', yAxis: 10 }], markPoints: [], labels: [] } };
if (t.calc(item) !== null) throw new Error('unverified raw reference entered calculation');
const price = t.price(item, raw);
if (!price.includes('10.00') || !/用途未核验|原始记录参考/.test(price))
  throw new Error('unverified raw reference was not retained with its purpose');
let chartOption = null;
window.echarts = { init(node) { return { getDom() { return node; }, setOption(value) { chartOption = value; }, getOption() { return chartOption || {}; }, dispose() {}, resize() {} }; } };
t.state.data = { date: '2026-08-14' };
t.state.chartMount = { innerHTML: '' }; t.state.chartAnnotationLane = null; t.state.chartLayerSwitcher = null;
t.chart(raw, item);
const lines = ((chartOption && chartOption.series) || []).flatMap((series) => Array.isArray(series.markLine && series.markLine.data) ? series.markLine.data : []);
if (lines.some((line) => String(line.label && line.label.formatter || '').includes('10.00')))
  throw new Error('unverified raw reference was drawn as an active chart line');
''')

    def test_reference_calculation_uses_the_consumed_contract_purpose(self):
        _assert_node_contract(self, "{ calc: getCandidateReferencePriceForCalculation, chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
const explicitlyUnverified = {
  reference_price: 10,
  reference_price_purpose_status: 'verified',
  contract: { reference_price: 10, purpose_status: 'unverified', price_basis: 'qfq' }
};
if (t.calc(explicitlyUnverified) !== null)
  throw new Error('top-level verified status upgraded an explicitly unverified contract');
['', 'unknown', 'missing'].forEach((status) => {
  const incompletePurpose = { contract: { reference_price: 10, purpose_status: status, price_basis: 'qfq' } };
  if (t.calc(incompletePurpose) !== null)
    throw new Error('incomplete purpose status entered calculation: ' + status);
});
const currentContract = {
  formal_decision_contract: { reference_price: 12, purpose_status: 'verified', price_basis: 'qfq' },
  strategy_results: [{ contract: { reference_price: 99, purpose_status: 'unverified', price_basis: 'qfq' } }]
};
if (t.calc(currentContract) !== 12)
  throw new Error('an unrelated strategy contract supplied or blocked the current formal reference');
const missingContractReference = {
  reference_price: 19.8,
  reference_price_purpose_status: 'unverified',
  contract: { purpose_status: 'verified', price_basis: 'qfq' }
};
if (t.calc(missingContractReference) !== null)
  throw new Error('formal contract purpose upgraded a raw price when the contract had no value');
let option = null;
window.echarts = { init(node) { return { getDom() { return node; }, setOption(value) { option = value; }, getOption() { return option || {}; }, dispose() {}, resize() {} }; } };
t.state.data = { date: '2026-08-14' };
t.state.chartMount = { innerHTML: '' }; t.state.chartAnnotationLane = null; t.state.chartLayerSwitcher = null;
t.chart({ code: '600109', dates: ['2026-08-13', '2026-08-14'],
  opens: [19, 19.5], highs: [19.5, 20], lows: [18.5, 19], closes: [19, 19.8],
  chart_annotations: { markLines: [{ name: '参考价', yAxis: 19.8 }], markPoints: [], labels: [] } }, missingContractReference);
const lines = ((option && option.series) || []).flatMap((series) => Array.isArray(series.markLine && series.markLine.data) ? series.markLine.data : []);
if (lines.some((line) => String(line.label && line.label.formatter || '').includes('19.80')))
  throw new Error('raw price returned through a missing formal contract and was drawn');
''')

    def test_unverified_raw_reference_cannot_become_active_beside_verified_contract(self):
        _assert_node_contract(self, "{ facts: renderCandidateFactPanel, price: buildPriceSection, chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600108', reference_price: 19.8, current_price: 21,
  data_status: { daily: 'verified', latest_date: '2026-08-14', is_final: true, stale: false },
  formal_decision_contract: { reference_price: 20, purpose_status: 'verified', price_basis: 'qfq' } };
 t.state.data = { date: '2026-08-14' };
const facts = t.facts(item);
if (!facts.includes('19.80') || !facts.includes('用途未核验'))
  throw new Error('raw reference was not retained with its own unverified purpose');
if (facts.includes('距结构参考'))
  throw new Error('raw reference received an active distance calculation from another contract');
const price = t.price(item, {});
if (!price.includes('20.00') || !price.includes('原始记录参考 19.80（用途未核验）'))
  throw new Error('formal and raw references were not kept distinct in the price detail');
if (price.includes('结构参考价（用途未核验'))
  throw new Error('verified formal contract was downgraded by the raw reference status');
let option = null;
window.echarts = { init(node) { return { getDom() { return node; }, setOption(value) { option = value; }, getOption() { return option || {}; }, dispose() {}, resize() {} }; } };
t.state.chartMount = { innerHTML: '' }; t.state.chartAnnotationLane = null; t.state.chartLayerSwitcher = null;
const raw = { code: '600108', dates: ['2026-08-13', '2026-08-14'],
  opens: [20, 20.5], highs: [20.5, 21], lows: [19.5, 20], closes: [20, 21],
  reference_buy_points: [{ reference_price: 19.8, purpose_status: 'verified' }],
  chart_annotations: { markLines: [{ name: '参考价', yAxis: 19.8 }], markPoints: [], labels: [] } };
t.chart(raw, item);
const lines = ((option && option.series) || []).flatMap((series) => Array.isArray(series.markLine && series.markLine.data) ? series.markLine.data : []);
if (lines.some((line) => String(line.label && line.label.formatter || '').includes('19.80')))
  throw new Error('unverified raw reference was reintroduced by chart annotation fallback');
if (!lines.some((line) => String(line.label && line.label.formatter || '').includes('20.00')))
  throw new Error('verified formal contract reference line disappeared');
''')

    def test_nonformal_source_keeps_unverified_contract_reference_as_text(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600110', name: '观察来源', workbench_item: {
  code: '600110', name: '观察来源', status_label: '仅观察',
  strategy_results: [{ strategy_id: 'observation_watchlist', role: 'watch_only',
    formal_action: '仅观察', contract: { reference_price: 10, purpose_status: 'unverified' }, evidence: {} }]
} };
t.state.data = { date: '2026-08-14' };
const html = t.detail(item, { code: '600110' });
if (!html.includes('原始记录参考价 10') || !html.includes('用途未核验'))
  throw new Error('non-formal source reference was hidden instead of retained with its purpose');
if (html.includes('正式参考价 10.00'))
  throw new Error('watch-only source reference was presented as a formal price');
''')

    def test_no_evidence_incident_detail_keeps_raw_reference_text_and_ohlc_mount(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
t.state.data = { date: '2026-08-26' }; t.state.currentView = 'main';
const item = { code: '300697', name: '事故复盘样本', incident_review_only: true,
  reference_price: 15.2, ref: { pool: 'startup_watchlist', code: '300697' } };
const raw = { code: '300697', dates: ['2026-08-25', '2026-08-26'],
  opens: [4, 4.1], highs: [4.2, 4.3], lows: [3.9, 4], closes: [4.1, 4.2] };
const html = t.detail(item, raw);
if (!html.includes('15.20')) throw new Error('no-evidence incident detail dropped the raw reference');
if (!/事故前|仅追溯|用途未核验/.test(html))
  throw new Error('no-evidence incident raw reference lacked its non-executable purpose');
if (!html.includes('id="chartCanvas"')) throw new Error('no-evidence incident detail lost the OHLC chart mount');
''')

    def test_actual_aug14_blocked_view_gets_one_collapsed_read_only_condition_trace(self):
        _assert_node_contract(self, "{ setup: normalizeWorkspace, views: getCandidateViews, list: renderCandidateList, state: state, nodes: nodes }", r'''
const t = globalThis.__auxTest;
function node() {
  return { innerHTML: '', textContent: '', hidden: false, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelector() { return null; }, querySelectorAll() { return []; },
    appendChild(child) { this.children.push(child); return child; },
    addEventListener() {}, setAttribute() {}, getAttribute() { return ''; } };
}
const data = JSON.parse(fs.readFileSync('docs/data/2026-08-14.json', 'utf8'));
const frozen = JSON.stringify(data);
t.state.data = data;
t.setup(data);
t.state.currentView = 'confirming';
t.state.rawPoolCandidates = null;
t.state.candidateQuery = '';
t.state.sectorFilter = '';
t.nodes.candidateList = node();
t.nodes.candidateCount = node();
t.nodes.candidateMore = node();
t.nodes.candidateTools = node();
t.nodes.candidateSearch = node();
t.nodes.detailPanel = node();
t.nodes.drawerContent = t.nodes.detailPanel;
t.nodes.workspaceBody = node();
t.list();
if (t.views().views.confirming.length !== 0)
  throw new Error('legacy health guard was bypassed and restored current candidates');
const html = t.nodes.candidateList.innerHTML;
if (!html.includes('原始条件追溯') || !html.includes('<details')
    || !html.includes('网宿科技') || !html.includes('300017')
    || !html.includes('回踩不破突破位') || !html.includes('跌破启动参考位'))
  throw new Error('actual blocked confirming view lacks its collapsed raw-condition trace');
if (!html.includes('未重新确认') || !html.includes('不生成当前动作'))
  throw new Error('raw-condition trace lacks its read-only historical boundary');
if (html.includes('class="candidate-row"') || html.includes('正式动作：'))
  throw new Error('raw-condition trace reintroduced a current candidate or action');
if (t.nodes.detailPanel.innerHTML.includes('原始条件追溯'))
  throw new Error('raw-condition trace was duplicated into the detail empty state');
if (t.nodes.candidateCount.textContent !== '显示 0 / 0')
  throw new Error('raw-condition trace changed the guarded candidate count');

t.state.candidateQuery = '300017';
t.nodes.candidateSearch.value = '300017';
t.list();
if (!t.nodes.candidateList.innerHTML.includes('300017 · 0只')
    || t.nodes.candidateList.innerHTML.includes('原始条件追溯'))
  throw new Error('raw-condition trace replaced the existing filtered empty state');
if (t.state.candidateQuery !== '300017')
  throw new Error('rendering the filtered empty state cleared the existing query');
if (frozen !== JSON.stringify(data))
  throw new Error('actual Aug14 input was mutated by the trace');
''')

    def test_raw_condition_trace_preserves_duplicate_workspace_rows_but_never_uses_schema2(self):
        _assert_node_contract(self, "{ trace: renderLegacyRawConditionTrace, state: state }", r'''
const t = globalThis.__auxTest;
const first = { code: '600206', name: '重复记录一',
  ref: { pool: 'observation_watchlist', code: '600206' },
  next_day_conditions: ['first item next'] };
const second = { code: '600206', name: '重复记录二',
  ref: { pool: 'observation_watchlist', code: '600206' },
  next_day_conditions: ['second item next'] };
const rawFirst = { code: '600206', next_day_conditions: ['wrong raw first'] };
const rawSecond = { code: '600206', next_day_conditions: ['wrong raw second'] };
t.state.data = { date: '2026-08-14', observation_watchlist: [rawFirst, rawSecond] };
t.state.workspace = { views: { observation_top5: [first, second] } };
t.state.rawPoolCandidates = null;
let html = t.trace('observation_top5');
if (!(html.indexOf('first item next') < html.indexOf('second item next'))
    || html.includes('wrong raw first') || html.includes('wrong raw second'))
  throw new Error('duplicate workspace records were deduplicated, reordered, or merged with raw rows');

t.state.data.selection_input_health = { schema_version: 2, by_view: {
  observation_top5: { status: 'unavailable', output_hidden: true }
} };
html = t.trace('observation_top5');
if (html !== '') throw new Error('schema2 unavailable/output-hidden contract was bypassed');

t.state.data.selection_input_health = { schema_version: 99, by_view: {
  observation_top5: { status: 'unavailable', output_hidden: true }
} };
html = t.trace('observation_top5');
if (html !== '') throw new Error('explicit unknown health-contract version was treated as legacy absence');

t.state.data = { date: '2026-08-14', selection_input_health: null };
t.state.workspace = { views: { confirming: [{ code: '600208', name: '坏来源名样本',
  ref: { pool: 'constructor', code: '600208' }, next_day_conditions: ['item retained safely']
}] } };
t.state.rawPoolCandidates = null;
html = t.trace('confirming');
if (!html.includes('item retained safely'))
  throw new Error('an invalid source key hid safe item-owned conditions');
if (html.includes('constructor') || html.includes('function Object') || html.includes('[native code]'))
  throw new Error('an internal or invalid source-pool key was exposed to the user');
''')

    def test_no_evidence_unique_ref_shows_real_historical_conditions_without_reconfirming(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const report = JSON.parse(fs.readFileSync('docs/data/2026-08-14.json', 'utf8'));
const item = report.workspace.views.confirming.find((row) => row.code === '300017');
const raw = report.startup_watchlist.find((row) => row.code === '300017');
t.state.data = report;
t.state.rawPoolCandidates = null;
const html = t.detail(item, raw);
if (!html.includes('历史原始条件') || !html.includes('未重新确认'))
  throw new Error('historical condition boundary was not disclosed');
if (!/data-condition-kind="next_day"[\s\S]*回踩不破突破位/.test(html))
  throw new Error('real next-day condition was not shown in its own group');
if (!/data-condition-kind="upgrade"[\s\S]*30min二买(?:\/|&#47;)三买/.test(html))
  throw new Error('real upgrade condition was not shown in its own group');
if (!/data-condition-kind="cancel"[\s\S]*跌破启动参考位/.test(html))
  throw new Error('real cancel condition was not shown in its own group');
if (html.includes('已满足') || html.includes('条件满足'))
  throw new Error('historical conditions were inferred as currently satisfied');
''')

    def test_no_evidence_next_day_conditions_remain_independent_from_upgrade_conditions(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600201', name: '独立字段样本', ref: { pool: 'startup_watchlist', code: '600201' },
  next_day_conditions: ['仅次日条件'], upgrade_conditions: ['仅升级条件'],
  cancel_conditions: ['仅取消条件'] };
t.state.data = { date: '2026-08-14', startup_watchlist: [] };
t.state.rawPoolCandidates = null;
const html = t.detail(item, null);
if (!/data-condition-kind="next_day"[\s\S]*仅次日条件/.test(html))
  throw new Error('next_day_conditions did not keep an independent group');
if (!/data-condition-kind="upgrade"[\s\S]*仅升级条件/.test(html))
  throw new Error('upgrade_conditions did not keep an independent group');
if (!/data-condition-kind="cancel"[\s\S]*仅取消条件/.test(html))
  throw new Error('cancel_conditions did not keep an independent group');
''')

    def test_no_evidence_conditions_prefer_item_fields_over_unique_raw_fields(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const raw = { code: '600202', next_day_conditions: ['raw次日'],
  upgrade_conditions: ['raw升级'], cancel_conditions: ['raw取消'] };
const item = { code: '600202', name: 'item优先样本',
  ref: { pool: 'startup_watchlist', code: '600202' },
  next_day_conditions: ['item次日'], upgrade_conditions: ['item升级'],
  cancel_conditions: ['item取消'] };
t.state.data = { date: '2026-08-14', startup_watchlist: [raw] };
t.state.rawPoolCandidates = null;
const html = t.detail(item, raw);
['item次日', 'item升级', 'item取消'].forEach((text) => {
  if (!html.includes(text)) throw new Error('item condition was not preferred: ' + text);
});
['raw次日', 'raw升级', 'raw取消'].forEach((text) => {
  if (html.includes(text)) throw new Error('raw condition was merged over an existing item field: ' + text);
});
''')

    def test_no_evidence_conditions_keep_empty_and_malformed_values_local_and_escape_html(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const raw = { code: '600203', next_day_conditions: ['<script>危险</script>', null, { text: '对象条件' }, 7],
  upgrade_conditions: { text: '错误顶层类型' }, cancel_conditions: '错误顶层类型' };
const item = { code: '600203', name: '异常类型样本', reference_price: 10.2,
  ref: { pool: 'startup_watchlist', code: '600203' },
  next_day_conditions: [], upgrade_conditions: null };
t.state.data = { date: '2026-08-14', startup_watchlist: [raw] };
t.state.rawPoolCandidates = null;
const html = t.detail(item, raw);
if (!html.includes('&lt;script&gt;危险&lt;&#47;script&gt;') || html.includes('<script>危险</script>'))
  throw new Error('historical condition HTML was not escaped');
if (html.includes('对象条件') || html.includes('>7<') || html.includes('错误顶层类型'))
  throw new Error('malformed historical condition values became visible claims');
if (html.includes('data-condition-kind="upgrade"') || html.includes('data-condition-kind="cancel"'))
  throw new Error('missing or malformed groups were fabricated');
if (!html.includes('10.20') || !html.includes('id="chartCanvas"'))
  throw new Error('local condition degradation removed the existing reference or chart');
''')

    def test_no_evidence_raw_conditions_stay_with_the_referenced_pool(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const startup = { code: '600204', next_day_conditions: ['启动池条件'] };
const observation = { code: '600204', next_day_conditions: ['观察池条件'] };
const item = { code: '600204', name: '来源隔离样本',
  ref: { pool: 'startup_watchlist', code: '600204' } };
t.state.data = { date: '2026-08-14', startup_watchlist: [startup], observation_watchlist: [observation] };
t.state.rawPoolCandidates = null;
const html = t.detail(item, startup);
if (!html.includes('启动池条件')) throw new Error('referenced-pool condition was not shown');
if (html.includes('观察池条件')) throw new Error('same-code condition leaked from another pool');

const badRefItem = { code: '600999', name: '坏ref样本',
  ref: { pool: 'startup_watchlist', code: '600204' } };
const badRefHtml = t.detail(badRefItem, startup);
if (badRefHtml.includes('启动池条件'))
  throw new Error('a ref for another code supplied historical conditions');
''')

    def test_no_evidence_raw_conditions_do_not_guess_among_same_pool_duplicates(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const first = { code: '600205', next_day_conditions: ['首条raw条件'] };
const second = { code: '600205', next_day_conditions: ['次条raw条件'] };
const item = { code: '600205', name: '同池重复样本',
  ref: { pool: 'observation_watchlist', code: '600205' },
  next_day_conditions: ['item自带条件'] };
t.state.data = { date: '2026-08-14', observation_watchlist: [first, second] };
t.state.rawPoolCandidates = null;
const html = t.detail(item, first);
if (!html.includes('item自带条件')) throw new Error('item-owned condition was lost on an ambiguous ref');
if (html.includes('首条raw条件') || html.includes('次条raw条件'))
  throw new Error('same-pool duplicate was guessed by code order');
if (!html.includes('同一来源有多条同代码记录') || !html.includes('未自动补充')
    || html.includes('ref'))
  throw new Error('ambiguous raw-condition degradation was not explained');
''')

    def test_no_evidence_condition_deduplication_handles_prototype_named_text(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600207', name: '原型名条件样本',
  next_day_conditions: ['__proto__', '__proto__', 'constructor', 'constructor'] };
t.state.data = { date: '2026-08-14' };
const html = t.detail(item, null);
if (!html.includes('__proto__') || !html.includes('constructor'))
  throw new Error('prototype-named condition text was dropped by deduplication');
if ((html.match(/__proto__/g) || []).length !== 1
    || (html.match(/constructor/g) || []).length !== 1)
  throw new Error('prototype-named condition text was not deduplicated');
''')

    def test_no_evidence_condition_rendering_does_not_mutate_item_raw_or_report(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const raw = { code: '600206', next_day_conditions: ['次日'],
  upgrade_conditions: ['升级'], cancel_conditions: ['取消'] };
const item = { code: '600206', name: '只读样本', ref: { pool: 'startup_watchlist', code: '600206' } };
const report = { date: '2026-08-14', startup_watchlist: [raw] };
const beforeItem = JSON.stringify(item);
const beforeRaw = JSON.stringify(raw);
const beforeReport = JSON.stringify(report);
t.state.data = report;
t.state.rawPoolCandidates = null;
t.detail(item, raw);
if (JSON.stringify(item) !== beforeItem) throw new Error('condition rendering mutated the item');
if (JSON.stringify(raw) !== beforeRaw) throw new Error('condition rendering mutated the raw record');
if (JSON.stringify(report) !== beforeReport) throw new Error('condition rendering mutated the report input');
''')


if __name__ == '__main__':
    unittest.main()
