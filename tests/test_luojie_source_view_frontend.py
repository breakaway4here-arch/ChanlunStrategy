"""Frontend contracts for the narrow historical Luojie source-view recovery."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


FIXTURE = r"""
function archivedBootstrap() {
  const html = fs.readFileSync('docs/2026-09-14/index.html', 'utf8');
  const bootstrapMarker = 'window.CHANLUN_BOOTSTRAP = ';
  const start = html.indexOf(bootstrapMarker) + bootstrapMarker.length;
  const end = html.indexOf(';\n  window.CHANLUN_BOOTSTRAP.dataBasePrefix', start);
  return JSON.parse(html.slice(start, end));
}
class Element {
  constructor() {
    this.innerHTML = '';
    this.textContent = '';
    this.attributes = {};
    this.children = [];
    this.hidden = false;
    this.classList = {
      add: function () {}, remove: function () {}, toggle: function () {},
      contains: function () { return false; }
    };
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key]; }
  addEventListener() {}
  appendChild(node) { this.children.push(node); return node; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
}
global.document.createElement = function () { return new Element(); };
"""


class TestLuojieSourceViewFrontend(unittest.TestCase):
    def _assert_contract(self, body):
        _assert_node_contract(
            self,
            "({ views: getCandidateViews, setup: normalizeWorkspace, tab: buildWorkspaceTabButton, description: renderViewDescription, list: renderCandidateList, detail: buildMergedCandidateDetail, evidence: getCandidateRecommendationEvidence, blocking: getStrategyViewBlockingReason, state: state, nodes: nodes })",
            FIXTURE + body,
        )

    def test_actual_sep14_partial_restores_tabs_list_budget_and_source_detail(self):
        self._assert_contract(
            r"""
const t = globalThis.__auxTest;
const bootstrap = archivedBootstrap();
const frozen = JSON.stringify(bootstrap);
window.CHANLUN_BOOTSTRAP = bootstrap;
t.state.data = bootstrap.inlineReportData;
t.setup(t.state.data);
t.state.currentView = 'luojie';
t.state.rawPoolCandidates = null;
const expected = bootstrap.decisionWorkbench.items.flatMap(function (item) {
  return item.strategy_results.filter(function (strategy) {
    return strategy.strategy_id === 'luojie';
  });
}).sort(function (left, right) { return left.view_rank - right.view_rank; });
const rawCodes = bootstrap.inlineReportData.luojie_pool.candidates
  .map(function (candidate) { return candidate.code; }).sort();
const views = t.views();
const rows = views.views.luojie;
assert(rows.length === 30 && expected.length === 30, 'actual partial source view is not 30 rows');
assert(rows.map(function (row) { return row.code; }).join(',')
  === expected.map(function (strategy) { return strategy.candidate.code; }).join(','),
  'source view did not preserve Luojie view_rank order');
assert(rows.map(function (row) { return row.code; }).sort().join(',') === rawCodes.join(','),
  'source projection and raw Luojie candidate sets differ');
rows.forEach(function (row, index) {
  assert(row === expected[index].candidate, 'canonical wrapper replaced the source candidate');
  assert(!row.workbench_item && row.action_semantics === 'watch_only'
    && row.is_formal_recommendation === false, 'mixed canonical identity leaked into Luojie view');
  assert(row.ref && row.ref.pool === 'luojie_pool' && row.ref.code === row.code,
    'Luojie detail source ref is not exact');
});
assert(views.meta.luojie.availability.state === 'partial', 'partial state was hidden');
['30 只', '核验 60 / 请求 60', '缺失 0', '预算外 100'].forEach(function (text) {
  assert(views.meta.luojie.availability.reason.includes(text),
    'partial budget explanation is missing: ' + text);
});
assert(t.blocking(t.state.data, 'luojie').includes('picks_pure'),
  'raw legacy closure marker was mutated instead of narrowly ignored');

const tab = t.tab({ key: 'luojie', label: '罗姐池' }, views, ['luojie']);
assert(tab.attributes['aria-label'] === '罗姐池，30只' && tab.innerHTML.includes('(30)'),
  'tab count was not synchronized');
t.nodes.description = new Element();
t.description();
assert(t.nodes.description.innerHTML.includes('部分可用')
  && t.nodes.description.innerHTML.includes('预算外 100'),
  'view description lost partial budget scope');

t.nodes.candidateList = new Element();
t.nodes.candidateCount = new Element();
t.nodes.detailPanel = new Element();
t.nodes.candidateMore = new Element();
t.list();
const candidateRows = t.nodes.candidateList.children.filter(function (node) {
  return node.attributes['data-code'];
});
assert(candidateRows.length === 20 && t.nodes.candidateCount.textContent === '显示 20 / 30'
  && t.nodes.candidateMore.hidden === false,
  'actual source list total or existing pagination was not synchronized');
assert(candidateRows[0].attributes['data-code'] === expected[0].candidate.code,
  'rendered list lost source view_rank order');
const detail = t.nodes.detailPanel.innerHTML;
const detailEvidence = t.evidence(rows[0], t.state.data, 'luojie');
assert(JSON.stringify(detailEvidence) === JSON.stringify(expected[0].evidence)
  && detailEvidence.view === 'luojie'
  && detailEvidence.code === rows[0].code
  && detailEvidence.summary.source === 'workspace.views.luojie',
  'dedicated detail was not bound to the exact Luojie source evidence');
assert(detail.includes('推荐结论') && detail.includes('日线结构')
  && detail.includes('完整证据与审计'),
  'dedicated detail did not render the Luojie evidence modules');
assert(detail.includes('页面动作：仅观察') && !detail.includes('正式动作：可上车'),
  'dedicated detail promoted research to a formal action');
assert(frozen === JSON.stringify(bootstrap), 'source-view recovery mutated the actual report input');
"""
        )

    def test_partial_recovery_rejects_wrong_date_ref_identity_and_health(self):
        self._assert_contract(
            r"""
const t = globalThis.__auxTest;
function count(mutator) {
  const bootstrap = archivedBootstrap();
  mutator(bootstrap);
  window.CHANLUN_BOOTSTRAP = bootstrap;
  t.state.data = bootstrap.inlineReportData;
  t.setup(t.state.data);
  t.state.currentView = 'luojie';
  t.state.rawPoolCandidates = null;
  return t.views().views.luojie.length;
}
assert(count(function (bootstrap) {
  bootstrap.decisionWorkbench.report_date = '2026-09-13';
}) === 0, 'wrong report date restored a source view');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.selection_input_health.required_date = '2026-09-13';
}) === 0, 'wrong selection-health date restored a source view');
assert(count(function (bootstrap) {
  const strategy = bootstrap.decisionWorkbench.items
    .flatMap(function (item) { return item.strategy_results; })
    .find(function (item) { return item.strategy_id === 'luojie'; });
  strategy.candidate.ref.pool = 'picks_fusion';
}) === 0, 'wrong source ref restored a source view');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.luojie_pool.input_health.invalid_count = 1;
  bootstrap.inlineReportData.luojie_pool.input_health.invalid_codes = ['002202'];
}) === 0, 'extra pool health error was ignored');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.luojie_pool.input_health.invalid_codes = 'unknown';
}) === 0, 'malformed health code collection was treated as empty');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.luojie_pool.input_health.blocking_reason = 'other_health_error';
  bootstrap.inlineReportData.selection_input_health.by_strategy.luojie_pool.blocking_reason = 'other_health_error';
}) === 0, 'matching but unknown partial health errors were accepted');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.luojie_pool.diagnostics.partial_candidate_output_allowed = false;
}) === 0, 'producer partial-output denial was ignored');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.selection_input_health.by_view.luojie.blocking_reason = 'other_health_error';
}) === 0, 'non-legacy view health error was ignored');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.selection_input_health.by_view.luojie.invalid_count = 0;
}) === 0, 'conflicting legacy closure count was ignored');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.workspace.view_meta.luojie.availability.reason = 'other_health_error';
}) === 0, 'unknown workspace availability error was ignored');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.luojie_pool.diagnostics.final_common_upstream.enforced = true;
}) === 0, 'enforced common upstream contract was bypassed');
assert(count(function (bootstrap) {
  const strategy = bootstrap.decisionWorkbench.items
    .flatMap(function (item) { return item.strategy_results; })
    .find(function (item) { return item.strategy_id === 'luojie'; });
  strategy.role = 'formal';
  strategy.formal_action = '可上车';
}) === 0, 'formal or unknown source identity entered the research view');
assert(count(function (bootstrap) {
  const strategy = bootstrap.decisionWorkbench.items
    .flatMap(function (item) { return item.strategy_results; })
    .find(function (item) { return item.strategy_id === 'luojie'; });
  strategy.candidate.view_rank = 99;
}) === 0, 'conflicting source candidate rank was accepted');
assert(count(function (bootstrap) {
  const strategy = bootstrap.decisionWorkbench.items
    .flatMap(function (item) { return item.strategy_results; })
    .find(function (item) { return item.strategy_id === 'luojie'; });
  strategy.candidate.evidence_view = 'highlights';
}) === 0, 'conflicting source candidate evidence view was accepted');
assert(count(function (bootstrap) {
  delete bootstrap.decisionWorkbench;
}) === 0, 'raw candidates alone restored the source view');
assert(count(function (bootstrap) {
  bootstrap.inlineReportData.luojie_pool.candidates.push({
    code: '999999', ref: { pool: 'luojie_pool', code: '999999' }
  });
}) === 0, 'mismatched raw/source candidate sets were accepted');
assert(count(function (bootstrap) {
  bootstrap.recommendationEvidence.views.luojie[0].code = '999999';
  bootstrap.recommendationEvidence.views.luojie[0].summary.code = '999999';
}) === 0, 'mismatched dedicated-detail evidence projection was accepted');
"""
        )

    def test_partial_recovery_rejects_source_candidate_workbench_evidence_alias(self):
        self._assert_contract(
            r"""
const t = globalThis.__auxTest;
const bootstrap = archivedBootstrap();
const strategy = bootstrap.decisionWorkbench.items
  .flatMap(function (item) { return item.strategy_results; })
  .find(function (item) { return item.strategy_id === 'luojie'; });
strategy.candidate.workbench_item = {
  code: strategy.candidate.code, evidence_view: 'highlights', strategy_results: []
};
window.CHANLUN_BOOTSTRAP = bootstrap;
t.state.data = bootstrap.inlineReportData;
t.setup(t.state.data);
t.state.currentView = 'luojie';
t.state.rawPoolCandidates = null;
assert(t.views().views.luojie.length === 0,
  'source candidate workbench evidence alias was accepted');
"""
        )

    def test_mixed_canonical_entity_projects_only_luojie_and_other_guards_stay_closed(self):
        self._assert_contract(
            r"""
const t = globalThis.__auxTest;
const bootstrap = archivedBootstrap();
const item = bootstrap.decisionWorkbench.items.find(function (row) {
  return row.strategy_results.some(function (strategy) { return strategy.strategy_id === 'luojie'; });
});
item.strategy_results.push({
  strategy_id: 'main', role: 'formal', action_semantics: 'formal', view_rank: 1,
  formal_action: '可上车', score: 99, page_status: 'formal_ready',
  primary_reason: '主策略条件已满足', candidate: {
    code: item.code, name: item.name, action_semantics: 'formal',
    page_action: '可上车', decision_engine_v1: { total_score: 99 },
    ref: { pool: 'picks_fusion', code: item.code }
  }, contract: {}, evidence: {}
});
bootstrap.inlineReportData.selection_input_health.by_view.main = {
  status: 'unavailable', required_date: '2026-09-14', output_hidden: true,
  blocking_reason: 'strategy_upstream_contract_mismatch', invalid_codes: ['999999']
};
window.CHANLUN_BOOTSTRAP = bootstrap;
t.state.data = bootstrap.inlineReportData;
t.setup(t.state.data);
t.state.currentView = 'luojie';
t.state.rawPoolCandidates = null;
const views = t.views();
const first = views.views.luojie[0];
assert(views.views.luojie.length === 30 && views.views.main.length === 0,
  'Luojie exception changed another view guard');
assert(first.action_semantics === 'watch_only' && !first.workbench_item
  && JSON.stringify(first).indexOf('99') === -1,
  'same-stock main score/action leaked through the canonical wrapper');
const detail = t.detail(first, first);
assert(detail.includes('页面动作：仅观察') && !detail.includes('决策分 99')
  && !detail.includes('正式动作：可上车'),
  'same-stock main conclusion leaked into dedicated Luojie detail');
"""
        )


if __name__ == "__main__":
    unittest.main()
