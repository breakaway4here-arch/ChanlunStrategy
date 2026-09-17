"""Focused browser-side contracts for the public next-day research projection."""

import pathlib
import subprocess
import unittest

from tests.css_test_helpers import media_rule_blocks


ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = (ROOT / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
CSS = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")


def _run_node_contract(testcase, exposure, body):
    script = r"""
const fs = require('fs');
const vm = require('vm');
global.window = {
  location: { pathname: '', hash: '' },
  CHANLUN_BOOTSTRAP: {},
  fetch: undefined
};
global.document = {
  readyState: 'loading',
  addEventListener: function () {},
  getElementById: function () { return null; }
};
let source = fs.readFileSync('chanlun/report_assets/report-v2.js', 'utf8');
const marker = '\n})();';
const at = source.lastIndexOf(marker);
if (at < 0) throw new Error('IIFE marker missing');
source = source.slice(0, at)
  + '\n globalThis.__nextdayTest = __EXPOSURE__;'
  + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
function assert(value, message) { if (!value) throw new Error(message); }
function sampleCandidate(code, name, rank, extra) {
  return Object.assign({
    stock_identity: code,
    exchange: code.slice(0, 2),
    code: code.slice(2),
    name: name,
    rank: rank,
    method: rank === 1 ? 'L1_limit_sector' : 'B0_original_highlights',
    algorithm_version: 'nextday-strength-exploration-v0',
    source_pools: ['observation_watchlist', 'startup_watchlist'],
    industry: '汽车',
    limit_sector: '汽车零部',
    industry_count: 8,
    board_n: 1,
    first_limit_time: '10:58',
    risk_flags: ['涨幅过热'],
    avoid_chase: true,
    invalidation: ['跌破启动参考位'],
    next_confirmation: ['回踩不破突破位'],
    cancel_conditions: ['放量长阴破坏结构'],
    next_day_conditions: ['回踩不破突破位'],
    upgrade_conditions: ['30min二买/三买'],
    startup_date: '2026-09-17',
    startup_reason: '低位放量涨停',
    watch_reason: '涨停当日不追，等待次日回踩确认'
  }, extra || {});
}
function pendingMetric() {
  return { status: 'pending', price_basis_status: 'not_matured', value_pct: null };
}
function pendingOutcome(code, name, rank) {
  return {
    stock_identity: code,
    entry_one_price: null,
    name: name,
    rank: rank,
    status: 'pending',
    target_dates: { t1: '2026-09-18', t2: '2026-09-21', t3: '2026-09-22' },
    maturity_status: { t1: 'pending', t2: 'pending', t3: 'pending' },
    path_metrics: {
      cc1: pendingMetric(), gap1: pendingMetric(), oc1: pendingMetric(),
      oc2: pendingMetric(), oc3: pendingMetric()
    }
  };
}
function groupMetrics(selected) {
  function metric() { return { observed: 0, mean_pct: null }; }
  return {
    selected: selected,
    cc1: Object.assign(metric(), { median_pct: null, gain_ge_5: null, loss_le_minus5: null }),
    gap1: metric(),
    oc1: Object.assign(metric(), { median_pct: null, gain_ge_3: null, loss_le_minus5: null }),
    oc2: metric(),
    oc3: metric()
  };
}
function samplePayload() {
  const l1 = [
    sampleCandidate('SH600609', '金杯汽车', 1),
    sampleCandidate('SH603960', '克来机电', 2)
  ];
  const b0 = [
    sampleCandidate('SZ301075', '多瑞医药', 1),
    sampleCandidate('SH603960', '克来机电', 2),
    sampleCandidate('SH688521', '芯原股份', 3)
  ];
  return {
    schema_version: 'nextday-research-public-v1',
    report_date: '2026-09-17',
    algorithm_version: 'nextday-strength-exploration-v0',
    source_run_id: '20260917-test',
    status: 'available',
    reason: '',
    frozen_at: '2026-09-17T08:00:00+08:00',
    registration_status: 'frozen',
    summary: {
      candidate_count: 36,
      snapshot_unique_count: 47,
      candidate_snapshot_intersection: 13
    },
    l1: { status: 'evaluated', reason: '', selected: l1 },
    b0: { status: 'evaluated', reason: '', selected: b0 },
    outcomes: {
      as_of_date: '2026-09-17',
      l1: {
        status: 'evaluated', reason: '', metrics: groupMetrics(l1.length),
        outcome_rows: l1.map(function (item) { return pendingOutcome(item.stock_identity, item.name, item.rank); })
      },
      b0: {
        status: 'evaluated', reason: '', metrics: groupMetrics(b0.length),
        outcome_rows: b0.map(function (item) { return pendingOutcome(item.stock_identity, item.name, item.rank); })
      }
    }
  };
}
function response(payload) {
  return { ok: true, status: 200, json: function () { return Promise.resolve(payload); } };
}
(async function () {
__BODY__
})().catch(function (error) { console.error(error && error.stack || error); process.exitCode = 1; });
""".replace("__EXPOSURE__", exposure).replace("__BODY__", body)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    testcase.assertEqual(completed.returncode, 0, completed.stderr)


class TestNextdayResearchFrontend(unittest.TestCase):
    def test_projection_shows_ordered_l1_and_b0_with_sources_risks_and_overlap(self):
        _run_node_contract(
            self,
            "({ validate: validateNextdayResearchPayload, render: renderNextdayResearchProjection })",
            r"""
const payload = samplePayload();
assert(__nextdayTest.validate(payload, '2026-09-17'), 'valid same-date sidecar was rejected');
const html = __nextdayTest.render(payload, '2026-09-17');
assert(html.includes('系统候选 36') && html.includes('完整涨停快照 47') && html.includes('交集 13'),
  'same-day input coverage summary is missing');
const l1Start = html.indexOf('L1 次日强势候选');
const b0Start = html.indexOf('B0 原看点对照');
const l1Html = html.slice(l1Start, b0Start);
assert(l1Html.indexOf('金杯汽车') < l1Html.indexOf('克来机电'), 'L1 source order changed');
assert(html.indexOf('多瑞医药') < html.indexOf('克来机电', html.indexOf('原看点')), 'B0 source order changed');
assert(html.includes('观察门控池') && html.includes('启动确认池'), 'source pools were not humanized');
assert(html.includes('汽车零部') && html.includes('8家') && html.includes('1板') && html.includes('10:58'),
  'industry count, board count, or seal time is missing');
assert(html.includes('家数降序') && html.includes('连板数降序') && html.includes('首封时间升序'),
  'L1 ordering rule is missing');
assert(html.includes('涨幅过热') && html.includes('涨停当日不追'), 'first-line risks are missing');
assert(html.includes('回踩不破突破位') && html.includes('放量长阴破坏结构'), 'confirmation/cancel conditions are missing');
assert(html.includes('与 L1 重叠') || html.includes('L1 / B0 重叠'), 'L1/B0 overlap is missing');
assert(html.includes('研究观察') && html.includes('不构成正式推荐'), 'research-only boundary is missing');
assert(html.includes('SH600609') && html.includes('SH603960'), 'instrument IDs are missing');
assert(!html.includes('回溯登记'), 'legacy group without freeze metadata changed its rendering');
const hostile = samplePayload();
hostile.l1.selected[0].name = '<img src=x onerror=alert(1)>';
hostile.l1.selected[0].watch_reason = '<script>alert(2)</script>';
const safe = __nextdayTest.render(hostile, '2026-09-17');
assert(!safe.includes('<img') && !safe.includes('<script>'), 'sidecar text was not escaped');
assert(safe.includes('&lt;img') && safe.includes('&lt;script&gt;'), 'escaped source text is missing');
""",
        )

    def test_historical_group_freeze_is_visible_only_for_that_group(self):
        _run_node_contract(
            self,
            "({ render: renderNextdayResearchProjection })",
            r"""
const payload = samplePayload();
payload.l1.registration_status = 'prospective';
payload.l1.frozen_at = '2026-09-17T08:30:00Z';
payload.b0.registration_status = 'historical';
payload.b0.frozen_at = '2026-09-18T09:15:00Z';
const html = __nextdayTest.render(payload, '2026-09-17');
assert(html.includes('回溯登记 · 冻结 2026-09-18T09:15:00Z'), 'historical group freeze was hidden');
const l1Start = html.indexOf('L1 次日强势候选');
const b0Start = html.indexOf('B0 原看点对照');
assert(!html.slice(l1Start, b0Start).includes('回溯登记'), 'prospective L1 was mislabeled retrospective');
assert(!html.includes('source_hash') && !html.includes('selection.json'), 'private freeze metadata leaked');
""",
        )

    def test_insufficient_and_evaluated_empty_are_distinct_and_missing_is_not_zero(self):
        _run_node_contract(
            self,
            "({ render: renderNextdayResearchProjection })",
            r"""
const payload = samplePayload();
payload.status = 'partial';
payload.l1.status = 'not_evaluated';
payload.l1.reason = '同日涨停快照不完整';
payload.l1.selected = [];
const html = __nextdayTest.render(payload, '2026-09-17');
assert(html.includes('L1 未评估') && html.includes('同日涨停快照不完整'), 'input insufficiency was hidden');
assert(html.includes('涨停快照样本') && !html.includes('完整涨停快照'), 'partial snapshot was labeled complete');
assert(!html.includes('L1 已评估，未选出候选'), 'not-evaluated was shown as a successful empty result');
assert(!html.includes('0.00%'), 'pending or missing observations became zero percent');
const empty = samplePayload();
empty.l1.selected = [];
empty.l1.status = 'evaluated';
const emptyHtml = __nextdayTest.render(empty, '2026-09-17');
assert(emptyHtml.includes('L1 已评估，未选出候选'), 'evaluated empty was not identified');
""",
        )

    def test_outcome_projection_only_displays_observed_values_with_verified_basis(self):
        _run_node_contract(
            self,
            "({ render: renderNextdayResearchProjection })",
            r"""
const payload = samplePayload();
const row = payload.outcomes.l1.outcome_rows[0];
row.path_metrics.cc1 = { status: 'observed', price_basis_status: 'raw_comparable', value_pct: 0 };
row.path_metrics.gap1 = { status: 'observed', price_basis_status: 'qfq_comparable', value_pct: 1.25 };
row.path_metrics.oc1 = { status: 'observed', price_basis_status: 'within_bar_invariant', value_pct: 3 };
row.entry_one_price = true;
payload.outcomes.l1.metrics.cc1 = {
  observed: 1, mean_pct: 0, median_pct: 0, gain_ge_5: 0, loss_le_minus5: 0
};
payload.outcomes.l1.metrics.oc1 = {
  observed: 1, mean_pct: 3, median_pct: 3, gain_ge_3: 1, loss_le_minus5: 0
};
payload.outcomes.l1.metrics.gap1 = { observed: 1, mean_pct: 1.25 };
payload.outcomes.l1.outcome_rows[1].path_metrics.cc1 = {
  status: 'basis_unverified', price_basis_status: 'price_basis_unverified', value_pct: null
};
payload.outcomes.l1.outcome_rows[1].path_metrics.gap1 = {
  status: 'missing', price_basis_status: 'data_unavailable', value_pct: null
};
const html = __nextdayTest.render(payload, '2026-09-17');
assert(html.includes('截至 2026-09-17'), 'outcome as-of date is missing');
assert(html.includes('0.00%'), 'an observed real zero was hidden');
assert(html.includes('1.25%') && !html.includes('价基状态未识别'), 'verified qfq value was rejected');
assert(html.includes('价基未核验') && html.includes('数据缺失'), 'unverified and missing statuses were collapsed');
assert(html.includes('信号日收盘→次日收盘') && html.includes('信号日收盘→次日开盘')
  && html.includes('次日开盘→次日收盘') && html.includes('次日开盘→T+2收盘') && html.includes('次日开盘→T+3收盘'),
  'outcome metrics are missing');
assert(html.includes('一字日，成交不确定'), 'single-price-day uncertainty was omitted');
const summaryStart = html.indexOf('分组价格路径统计');
const cc1Start = html.indexOf('(CC1)', summaryStart);
const gap1Start = html.indexOf('(GAP1)', cc1Start);
const oc1Start = html.indexOf('(OC1)', gap1Start);
const oc2Start = html.indexOf('(OC2)', oc1Start);
const cc1Text = html.slice(cc1Start, gap1Start);
const oc1Text = html.slice(oc1Start, oc2Start);
assert(cc1Text.includes('≥5% 0&#47;1'), 'CC1 threshold was lost: ' + cc1Text);
assert(oc1Text.includes('≥3% 1&#47;1') && !oc1Text.includes('≥5%'), 'OC1 threshold was conflated with CC1: ' + oc1Text);
assert(html.includes('不代表可成交结果或实盘收益') && html.includes('费用、滑点、排队与成交均未模拟'),
  'price-path results were presented without the execution boundary');
""",
        )

    def test_fetch_is_report_date_scoped_retries_404_and_rejects_wrong_date_locally(self):
        _run_node_contract(
            self,
            "({ load: loadNextdayResearch, state: state, nodes: nodes, url: getNextdayResearchUrl })",
            r"""
const mount = { innerHTML: '', addEventListener: function () {} };
__nextdayTest.nodes.nextdayResearch = mount;
__nextdayTest.state.granted = true;
__nextdayTest.state.data = { date: '2026-09-17' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-17', dataBasePrefix: '' };
assert(__nextdayTest.url('2026-09-17') === 'research/nextday/2026-09-17.json', 'root sidecar URL is wrong');
window.fetch = function (url) {
  assert(url === 'research/nextday/2026-09-17.json', 'loader requested a non-report date');
  return Promise.resolve({ ok: false, status: 404 });
};
await __nextdayTest.load();
assert(mount.innerHTML.includes('本日研究结果尚未发布'), '404 was not reported as a local unpublished state');
assert(mount.innerHTML.includes('data-nextday-research-retry'), '404 did not offer a local retry');
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-17', dataBasePrefix: '../' };
assert(__nextdayTest.url('2026-09-17') === '../research/nextday/2026-09-17.json', 'archive sidecar URL is wrong');
window.fetch = function (url) {
  assert(url === '../research/nextday/2026-09-17.json', 'archived report fetched the wrong relative path');
  return Promise.resolve(response(Object.assign(samplePayload(), { report_date: '2026-09-16' })));
};
await __nextdayTest.load();
assert(mount.innerHTML.includes('本期研究结果不可用'), 'wrong-date sidecar was not locally rejected');
assert(!mount.innerHTML.includes('金杯汽车'), 'wrong-date sidecar candidate leaked');
""",
        )

    def test_current_report_mismatch_and_out_of_order_fetch_cannot_leak_other_dates(self):
        _run_node_contract(
            self,
            "({ load: loadNextdayResearch, state: state, nodes: nodes })",
            r"""
const mount = { innerHTML: '', addEventListener: function () {} };
__nextdayTest.nodes.nextdayResearch = mount;
__nextdayTest.state.granted = true;
__nextdayTest.state.data = { date: '2026-09-17' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-16', dataBasePrefix: '' };
let called = 0;
window.fetch = function () { called += 1; return Promise.resolve(response(samplePayload())); };
await __nextdayTest.load();
assert(called === 0, 'mismatched report/bootstrap date still fetched a sidecar');
assert(mount.innerHTML.includes('报告日期无法匹配'), 'report date mismatch did not fail locally');

__nextdayTest.state.data = { date: '2026-09-17' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-17', dataBasePrefix: '' };
const deferred = [];
window.fetch = function () { return new Promise(function (resolve) { deferred.push(resolve); }); };
const oldRequest = __nextdayTest.load();
__nextdayTest.state.data = { date: '2026-09-18' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-18', dataBasePrefix: '' };
const current = samplePayload();
current.report_date = '2026-09-18';
current.l1.selected[0].name = '当前日报标的';
const currentRequest = __nextdayTest.load();
deferred[1](response(current));
await currentRequest;
const stale = samplePayload();
stale.l1.selected[0].name = '过期日报标的';
deferred[0](response(stale));
await oldRequest;
assert(mount.innerHTML.includes('当前日报标的'), 'current-date list was not rendered');
assert(!mount.innerHTML.includes('过期日报标的'), 'stale response replaced the current report list');
""",
        )

    def test_hash_opens_research_tab_and_mobile_rules_keep_list_single_column(self):
        _run_node_contract(
            self,
            "({ openFromHash: openNextdayResearchFromHash, state: state, nodes: nodes })",
            r"""
let scrolled = 0;
function viewNode() { return { classList: { toggle: function () {} } }; }
__nextdayTest.nodes.todayDecisionView = viewNode();
__nextdayTest.nodes.researchValidationView = viewNode();
__nextdayTest.nodes.primaryTabs = { querySelectorAll: function () { return []; } };
__nextdayTest.nodes.nextdayResearchSection = {
  scrollIntoView: function () { scrolled += 1; }, focus: function () {}
};
window.requestAnimationFrame = function (callback) { callback(); };
window.location.hash = '#nextday-research';
assert(__nextdayTest.openFromHash(), 'research deep link was not recognized');
assert(__nextdayTest.state.primaryMode === 'research', 'deep link did not open research mode');
assert(scrolled > 0, 'deep link did not scroll the research list into view');
""",
        )
        research = CSS.find(".l1-nextday-research")
        self.assertGreaterEqual(research, 0, "research section has no scoped styles")
        mobile = "\n".join(media_rule_blocks(CSS[research:], "@media (max-width: 760px)"))
        self.assertIn(".l1-nextday-groups { grid-template-columns: 1fr; }", mobile)
        self.assertNotIn("min-width: 900px", CSS[research : research + 4000])
        self.assertIn('id="nextday-research"', JS)
        self.assertIn('id="nextdayResearchContent"', JS)
        shell = JS[JS.index("function buildAppShell") : JS.index("function getReportDataStatus")]
        self.assertLess(shell.index('id="nextday-research"'), shell.index('class="aux-center'))
        self.assertIn("addEventListener('hashchange', openNextdayResearchFromHash)", JS)


if __name__ == "__main__":
    unittest.main()
