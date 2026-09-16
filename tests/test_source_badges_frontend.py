"""Frontend contracts for current-snapshot source-pool summaries."""

import pathlib
import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")

FIXTURE = r"""
const sourceFixture = JSON.parse(fs.readFileSync(
  'tests/fixtures/source_badges/2026-09-16-six.json', 'utf8'
));
function sourceProjection(rows) {
  return {
    schema_version: sourceFixture.snapshot.schema_version,
    report_date: sourceFixture.snapshot.report_date,
    phase: sourceFixture.snapshot.phase,
    snapshot_id: sourceFixture.snapshot.snapshot_id,
    items: JSON.parse(JSON.stringify(rows || sourceFixture.rows)),
    featured_ids: []
  };
}
function installProjection(rows, defaultView) {
  const projection = sourceProjection(rows);
  window.CHANLUN_BOOTSTRAP = {
    pageDate: sourceFixture.snapshot.report_date,
    decisionWorkbench: projection
  };
  const data = {
    date: sourceFixture.snapshot.report_date,
    workspace: { default_view: defaultView || 'decision_all', views: {}, view_meta: {} }
  };
  globalThis.__auxTest.state.data = data;
  globalThis.__auxTest.setup(data);
  globalThis.__auxTest.state.currentView = defaultView || 'decision_all';
  globalThis.__auxTest.state.candidateQuery = '';
  globalThis.__auxTest.state.candidateLimit = 20;
  globalThis.__auxTest.state.sectorFilter = '';
  globalThis.__auxTest.state.sectorFilterCode = '';
  globalThis.__auxTest.state.sectorFilterRefs = [];
  return projection;
}
"""


class SourceBadgesFrontend(unittest.TestCase):
    def test_real_six_source_relationships_match_the_frozen_snapshot(self):
        _assert_node_contract(
            self,
            "({ summary: getPoolHitSummary, setup: normalizeWorkspace, state: state })",
            FIXTURE + r"""
const projection = installProjection();
const frozen = JSON.stringify(projection.items);
const expected = {
  '605358': [2, '等确认,罗姐池', ''],
  '300456': [2, '罗姐池,基础候选·上游', ''],
  '300095': [2, '主推策略,基础候选·上游', '看点榜'],
  '688150': [2, '主推策略,基础候选·上游', '看点榜'],
  '688008': [1, '罗姐池', '看点榜'],
  '300656': [1, '等确认', '观察Top5']
};
projection.items.forEach(function (item) {
  const result = globalThis.__auxTest.summary(item);
  const target = expected[item.code];
  assert(result.count === target[0], item.code + ' source count changed');
  assert(result.pools.map(function (pool) { return pool.label; }).join(',') === target[1],
    item.code + ' source labels changed');
  assert(result.collections.map(function (entry) { return entry.label; }).join(',') === target[2],
    item.code + ' derived collection labels changed');
  assert(result.badgeText === '命中' + target[0] + '池', item.code + ' badge text changed');
});
assert(projection.items.find(function (item) { return item.code === '300095'; }).score === 61
  && projection.items.find(function (item) { return item.code === '688150'; }).score === 71,
  'formal source scores changed');
assert(projection.items.filter(function (item) {
  return item.code === '300095' || item.code === '688150';
}).every(function (item) {
  return item.page_status === 'formal_incomplete' && item.is_executable === false;
}), 'formal execution conditions changed');
assert(JSON.stringify(projection.items) === frozen, 'source summary mutated the frozen input');
""",
        )

    def test_dedup_derived_unknown_missing_many_and_html_escape_are_fail_closed(self):
        _assert_node_contract(
            self,
            "({ summary: getPoolHitSummary, render: renderPoolHitSummary, setup: normalizeWorkspace, state: state })",
            FIXTURE + r"""
installProjection([]);
function strategy(id, pool, role) {
  return { strategy_id: id, role: role || 'research',
    action_semantics: role === 'formal' ? 'formal' : 'watch_only',
    formal_action: role === 'formal' ? '可上车' : null,
    candidate: { code: '600001', ref: { pool: pool, code: '600001' } } };
}
const duplicate = { code: '600001', strategy_results: [
  strategy('main', 'picks_fusion', 'formal'),
  Object.assign(strategy('main', 'picks_fusion', 'formal'), { strategy_version: 'v2' })
], sources: ['main', 'picks_fusion'], source_refs: [
  { view: 'main', ref: { pool: 'picks_fusion', code: '600001' } }
] };
let result = globalThis.__auxTest.summary(duplicate);
assert(result.count === 1 && result.pools[0].label === '主推策略',
  'same-pool versions or aliases were counted more than once');
result = globalThis.__auxTest.summary({ code: '600008', strategy_results: [
  strategy('main', 'picks_fusion', 'research')
] });
assert(result.count === 1 && result.pools[0].label === '融合候选',
  'non-formal fusion source was promoted to primary strategy');
result = globalThis.__auxTest.summary({ code: '600009', sources: [
  'decision_formal', 'decision_all', 'baseline'
] });
assert(result.count === 1 && result.pools[0].label === '基础候选·上游'
  && result.unknown.length === 0,
  'navigation entries were counted or exposed as unknown strategy sources');
result = globalThis.__auxTest.summary({ code: '600010', sources: [
  '__proto__', 'constructor'
] });
assert(result.count === 0
  && result.unknown.join(',') === '__proto__,constructor'
  && result.badgeText === '有来源待识别',
  'prototype-chain identifiers were promoted to pools or lost from unknown sources');
const prototypeHtml = globalThis.__auxTest.render({ code: '600010', sources: [
  '__proto__', 'constructor'
] }, 'list');
assert(prototypeHtml.includes('未识别：__proto__')
  && prototypeHtml.includes('未识别：constructor'),
  'prototype-chain identifiers were not preserved as visible escaped unknowns');

const derivedOnly = { code: '600002', strategy_results: [
  strategy('highlights', 'luojie_pool', 'research')
] };
result = globalThis.__auxTest.summary(derivedOnly);
assert(result.count === 1 && result.pools[0].label === '罗姐池'
  && result.collections[0].label === '看点榜',
  'derived record with an explicit real ref did not count its source exactly once');

const observationOnly = { code: '600003', sources: ['observation_top5'],
  source_refs: [{ view: 'observation_top5', ref: {
    pool: 'observation_watchlist', code: '600003'
  } }] };
result = globalThis.__auxTest.summary(observationOnly);
assert(result.count === 0 && result.badgeText === '来源待补'
  && result.collections.map(function (entry) { return entry.label; }).join(',') === '观察Top5'
  && result.unknown.length === 0,
  'observation physical collection became a counted or unknown source pool');

const mixed = { code: '600004', sources: ['baseline', 'mystery<script>alert(1)</script>'] };
result = globalThis.__auxTest.summary(mixed);
assert(result.count === 1
  && result.badgeText === '已知命中1池 · 有来源待识别'
  && result.unknown[0] === 'mystery<script>alert(1)</script>',
  'mixed known and unknown sources lost their partial disclosure');
const escaped = globalThis.__auxTest.render(mixed, 'comparison');
assert(!escaped.includes('<script>') && escaped.includes('&lt;script&gt;'),
  'unknown raw source identifier was not HTML-escaped');

result = globalThis.__auxTest.summary({ code: '600005', sources: ['unknown_only'] });
assert(result.count === 0 && result.badgeText === '有来源待识别',
  'unknown-only source was presented as zero or missing');
result = globalThis.__auxTest.summary({ code: '600006' });
assert(result.count === 0 && result.badgeText === '来源待补',
  'fully missing sources were presented as zero or one pool');

const many = { code: '600007', strategy_results: [
  strategy('main', 'picks_fusion', 'formal'),
  strategy('h4_t3', 'h4_t3_pool', 'formal'),
  strategy('luojie', 'luojie_pool', 'research')
] };
result = globalThis.__auxTest.summary(many);
assert(result.count === 3 && result.badgeTone === 'many'
  && result.badgeText === '命中3池'
  && result.pools.map(function (pool) { return pool.label; }).join(',') === '主推策略,H4,罗姐池',
  'three-plus source boundary did not preserve the real count and purple tone');
""",
        )

    def test_explicit_research_main_source_is_not_promoted_by_action_text(self):
        _assert_node_contract(
            self,
            "({ summary: getPoolHitSummary, setup: normalizeWorkspace, state: state })",
            FIXTURE + r"""
installProjection([]);
const result = globalThis.__auxTest.summary({
  code: '600011', role: 'research', action_semantics: 'watch_only',
  formal_action: '仅观察', is_formal_recommendation: false,
  sources: ['main'], ref: { pool: 'picks_fusion', code: '600011' }
});
assert(result.count === 1 && result.pools[0].label === '融合候选',
  'research observation action text was promoted to a formal primary identity');
""",
        )

    def test_same_snapshot_lookup_survives_search_and_specialized_view_but_not_other_dates(self):
        _assert_node_contract(
            self,
            "({ summary: getPoolHitSummary, render: renderPoolHitSummary, setup: normalizeWorkspace, state: state })",
            FIXTURE + r"""
installProjection();
const legacyLuojie = { code: '605358', name: 'XD立昂微',
  ref: { pool: 'luojie_pool', code: '605358' } };
globalThis.__auxTest.state.currentView = 'luojie';
globalThis.__auxTest.state.candidateQuery = '605358';
let result = globalThis.__auxTest.summary(legacyLuojie);
assert(result.count === 2
  && result.pools.map(function (pool) { return pool.label; }).join(',') === '等确认,罗姐池',
  'specialized legacy row or search lost full same-snapshot sources');
assert(globalThis.__auxTest.render(legacyLuojie, 'list').includes('命中2池'),
  'same-snapshot lookup was not visible in the specialized row');

result = globalThis.__auxTest.summary({
  code: '605358', name: '昨日同股', report_date: '2026-09-15'
});
assert(result.count === 0 && result.badgeText === '来源待补',
  'same security from another report date borrowed current sources');
result = globalThis.__auxTest.summary({
  code: '605358', name: '另快照同股', report_date: '2026-09-16', snapshot_id: 'other-snapshot'
});
assert(result.count === 0 && result.badgeText === '来源待补',
  'same security from another snapshot borrowed current sources');
result = globalThis.__auxTest.summary({
  code: '605358', name: '另一阶段同股', report_date: '2026-09-16', phase: 'research'
});
assert(result.count === 0 && result.badgeText === '来源待补',
  'same security from another phase borrowed formal snapshot sources');
""",
        )

    def test_local_summary_exception_is_traceable_without_hiding_candidate(self):
        _assert_node_contract(
            self,
            "({ summary: getPoolHitSummary, render: renderPoolHitSummary, "
            "row: renderCandidateRowIdentity, setup: normalizeWorkspace, state: state })",
            FIXTURE + r"""
installProjection([]);
const item = {
  code: '600012', name: '局部降级样本', role: 'research',
  action_semantics: 'watch_only', page_status: 'watch_only'
};
Object.defineProperty(item, 'sources', {
  get: function () { throw new Error('/private/path/secret-value'); }
});
const result = globalThis.__auxTest.summary(item);
assert(result.count === 0 && result.badgeText === '来源待补'
  && result.status === 'degraded'
  && result.reasonCode === 'source_summary_unavailable',
  'local source-summary failure did not expose a fixed traceable degradation state');
const html = globalThis.__auxTest.render(item, 'list');
assert(html.includes('data-source-summary-status="degraded"')
  && html.includes('data-source-summary-reason="source_summary_unavailable"')
  && html.includes('来源待补'),
  'degraded source summary was not traceable in its local DOM');
assert(!html.includes('/private/path') && !html.includes('secret-value'),
  'private error detail leaked into the public source summary');
const rowHtml = globalThis.__auxTest.row(item, 'decision_all', { action: '仅观察' });
assert(rowHtml.includes('局部降级样本') && rowHtml.includes('600012')
  && rowHtml.includes('data-source-summary-status="degraded"'),
  'local source-summary failure hid the candidate row or its other content');
""",
        )

    def test_list_detail_quick_and_multicolumn_titles_share_one_visible_summary(self):
        _assert_node_contract(
            self,
            "({ setup: normalizeWorkspace, row: renderCandidateRowIdentity, detail: buildMergedCandidateDetail, "
            "quick: renderQuickComparison, comparison: renderCandidateEvidenceComparison, list: renderCandidateList, "
            "key: quickComparisonKey, state: state, nodes: nodes })",
            FIXTURE + r"""
function element() {
  return { innerHTML: '', textContent: '', hidden: false, children: [], attrs: {}, handlers: {},
    setAttribute: function (key, value) { this.attrs[key] = String(value); },
    getAttribute: function (key) { return this.attrs[key] || null; },
    appendChild: function (child) { this.children.push(child); return child; },
    querySelector: function () { return null; }, querySelectorAll: function () { return []; },
    addEventListener: function (key, handler) { this.handlers[key] = handler; }, focus: function () {},
    classList: { add: function () {}, remove: function () {}, toggle: function () {},
      contains: function () { return false; } } };
}
document.createElement = element;
document.body = element();
const projection = installProjection();
const canonical = projection.items.find(function (item) { return item.code === '300095'; });
const wrapper = Object.assign({}, canonical.candidate, {
  code: canonical.code, name: canonical.name, workbench_item: canonical
});
const rowHtml = globalThis.__auxTest.row(wrapper, 'decision_all', { action: '正式待确认' });
assert(rowHtml.includes('命中2池') && rowHtml.includes('主推策略')
  && rowHtml.includes('基础候选·上游') && rowHtml.includes('收录：看点榜'),
  'candidate identity line omitted the shared source summary');
assert(!rowHtml.includes('<button'), 'source summary nested an interactive control inside the row button');

const detailHtml = globalThis.__auxTest.detail(wrapper, {});
assert(detailHtml.includes('pool-hit-summary') && detailHtml.includes('命中2池')
  && detailHtml.indexOf('pool-hit-summary') < detailHtml.indexOf('chart-panel'),
  'default detail top omitted or misplaced the shared source summary');
globalThis.__auxTest.state.currentView = 'luojie';
const legacyDetail = globalThis.__auxTest.detail({
  code: '605358', name: 'XD立昂微', ref: { pool: 'luojie_pool', code: '605358' }
}, {});
assert(legacyDetail.includes('命中2池') && legacyDetail.includes('等确认')
  && legacyDetail.includes('罗姐池'),
  'legacy detail without evidence omitted the same-snapshot source summary');
globalThis.__auxTest.state.currentView = 'decision_all';

const key = globalThis.__auxTest.key(wrapper, 'decision_all');
globalThis.__auxTest.state.quickComparison = {
  selectedKeys: [key], selectedItems: {}, message: '', max: 3
};
globalThis.__auxTest.state.quickComparison.selectedItems[key] = wrapper;
const quickTarget = element();
const quickHtml = globalThis.__auxTest.quick(quickTarget);
assert(quickHtml.includes('quick-comparison-column') && quickHtml.includes('命中2池')
  && quickHtml.includes('收录：看点榜'),
  'quick comparison title omitted the shared source summary');

const comparisonHtml = globalThis.__auxTest.comparison('decision_all', globalThis.__auxTest.state.data);
assert(comparisonHtml.includes('candidate-evidence-table')
  && comparisonHtml.includes('candidate-evidence-ticket-list')
  && comparisonHtml.includes('命中2池')
  && comparisonHtml.includes('收录：看点榜'),
  'multi-column comparison titles omitted the shared source summary');

globalThis.__auxTest.nodes.candidateList = element();
globalThis.__auxTest.nodes.detailPanel = element();
globalThis.__auxTest.nodes.workspaceBody = element();
globalThis.__auxTest.nodes.candidateTools = null;
globalThis.__auxTest.nodes.candidateCount = element();
globalThis.__auxTest.nodes.candidateMore = element();
globalThis.__auxTest.nodes.drawerContent = null;
globalThis.__auxTest.list();
const notes = globalThis.__auxTest.nodes.candidateList.children.filter(function (node) {
  return node.className === 'pool-hit-note';
});
assert(notes.length === 1
  && notes[0].textContent === '按来源池计数，含上游基础池；榜单重复收录不叠加',
  'source-count boundary note was absent or repeated per stock');
""",
        )

    def test_fixed_visual_tokens_wrap_without_turning_labels_into_controls(self):
        for token in (
            ".pool-hit-summary",
            "flex-wrap: wrap",
            "min-width: 0",
            "white-space: nowrap",
            "#1D4ED8",
            "#6D28D9",
            "#EFF6FF",
            "#EEF2FF",
            "#FAF5FF",
            "#F0FDFA",
            "#FFF7ED",
            "#F1F5F9",
            "#FAFAFA",
        ):
            self.assertIn(token, CSS)
        self.assertNotIn(".pool-hit-summary button", CSS)


if __name__ == "__main__":
    unittest.main()
