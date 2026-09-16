"""Frontend contracts for the single primary-reading entry."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


FIXTURE = r"""
const primaryFixture = JSON.parse(fs.readFileSync(
  'tests/fixtures/main_entry/2026-09-16-primary-entry.json', 'utf8'
));

function frozenProjection() {
  const formalByCode = {};
  primaryFixture.formal_items.forEach(function (item) {
    formalByCode[item.code] = JSON.parse(JSON.stringify(item));
  });
  const items = primaryFixture.ordered_identities.map(function (identity) {
    const instrumentId = identity[0];
    const code = identity[1];
    const name = identity[2];
    if (formalByCode[code]) return formalByCode[code];
    return {
      id: primaryFixture.snapshot.report_date + ':fixture:' + instrumentId,
      instrument_id: instrumentId,
      code: code,
      name: name,
      page_status: 'watch_only',
      status_label: '研究观察',
      formal_action: null,
      score: null,
      is_executable: false,
      evidence_view: 'baseline',
      candidate: {
        code: code,
        name: name,
        ref: { pool: 'picks_pure', code: code },
        action_semantics: 'watch_only'
      },
      strategy_results: [{
        strategy_id: 'baseline',
        role: 'research',
        action_semantics: 'watch_only',
        formal_action: null,
        page_status: 'watch_only',
        score: null
      }]
    };
  });
  return {
    schema_version: primaryFixture.snapshot.schema_version,
    report_date: primaryFixture.snapshot.report_date,
    phase: primaryFixture.snapshot.phase,
    snapshot_id: primaryFixture.snapshot.snapshot_id,
    items: items,
    featured_ids: primaryFixture.featured_ids.slice()
  };
}
"""


class MainEntryFrontend(unittest.TestCase):
    def test_frozen_16th_primary_is_exact_and_all_80_identities_stay_ordered(self):
        _assert_node_contract(
            self,
            "({ rows: decisionRows, navigation: decisionNavigation, setup: normalizeWorkspace, views: getCandidateViews, counts: decisionOverviewCounts, state: state })",
            FIXTURE + r"""
const projection = frozenProjection();
const data = {
  date: primaryFixture.snapshot.report_date,
  workspace: {
    default_view: 'main',
    views: { main: JSON.parse(JSON.stringify(primaryFixture.main_rows)) },
    view_meta: { main: { role: 'formal', action_semantics: 'formal', availability: { state: 'available' } } },
    view_order: ['main']
  }
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: primaryFixture.snapshot.report_date,
  decisionWorkbench: projection
};
const all = globalThis.__auxTest.rows(projection, 'decision_all', data.workspace.views);
assert(all.length === 80, 'frozen unified identities were lost');
assert(all.map(function (row) { return row.code; }).join(',')
  === primaryFixture.ordered_identities.map(function (identity) { return identity[1]; }).join(','),
  'unified relative order changed');
const primary = globalThis.__auxTest.rows(projection, 'decision_formal', data.workspace.views);
assert(primary.map(function (row) { return row.code; }).join(',') === '300095,688150',
  'frozen primary union changed');
assert(primary.map(function (row) { return row.workbench_item.score; }).join(',') === '61,71',
  'formal scores changed');
assert(primary.every(function (row) {
  return row.workbench_item.page_status === 'formal_incomplete'
    && row.workbench_item.is_executable === false
    && row.workbench_item.strategy_results.some(function (strategy) {
      return strategy.strategy_id === 'main' && strategy.role === 'formal';
    });
}), 'formal identity or non-executable condition changed');

const nav = globalThis.__auxTest.navigation();
assert(nav.filter(function (entry) { return entry.label === '主推'; }).length === 1,
  'primary navigation is not unique');
assert(nav.map(function (entry) { return entry.key; }).join(',')
  === 'decision_formal,decision_all,decision_blocked', 'legacy sibling entries remain visible');
assert(!nav.some(function (entry) {
  return ['优先关注', '正式结果', '正式待确认', '正式推荐', '正式主推'].indexOf(entry.label) !== -1;
}), 'legacy primary aliases remain visible');

globalThis.__auxTest.state.data = data;
globalThis.__auxTest.setup(data);
assert(globalThis.__auxTest.state.workspace.default_view === 'decision_formal'
  && globalThis.__auxTest.state.currentView === 'decision_formal',
  'old main default did not migrate at the navigation boundary');
assert(globalThis.__auxTest.state.workspace.views.main.length === 2,
  'source strategy key main was replaced or consumed');
const views = globalThis.__auxTest.views();
assert(views.views.decision_formal.map(function (row) { return row.code; }).join(',')
  === '300095,688150', 'rendered primary view diverged from the union');
const counts = globalThis.__auxTest.counts();
assert(counts.primary === 2 && counts.formal === 2 && counts.research === 78,
  'overview counts changed business roles or used another set');
""",
        )

    def test_union_keeps_over_five_h4_research_and_legacy_rows_without_promotion(self):
        _assert_node_contract(
            self,
            "({ rows: decisionRows })",
            r"""
function record(instrumentId, code, status, role, strategyId) {
  const formal = role === 'formal';
  return {
    id: 'row:' + instrumentId,
    instrument_id: instrumentId,
    code: code,
    name: '股票' + code,
    page_status: status,
    formal_action: formal ? '可上车' : null,
    score: formal ? 60 : null,
    is_executable: status === 'formal_ready',
    candidate: { code: code, name: '股票' + code, ref: { pool: strategyId + '_pool', code: code }, action_semantics: formal ? 'formal' : 'watch_only' },
    strategy_results: [{ strategy_id: strategyId, role: role,
      action_semantics: formal ? 'formal' : 'watch_only',
      formal_action: formal ? '可上车' : null, page_status: status }]
  };
}
const research = record('SZ300001', '300001', 'waiting_trigger', 'research', 'confirming');
const researchFormalIncomplete = record('SZ300002', '300002', 'formal_incomplete', 'research', 'confirming');
const h4 = record('SH600001', '600001', 'formal_ready', 'formal', 'h4_t3');
const main = record('SH600002', '600002', 'formal_incomplete', 'formal', 'main');
const formals = [h4, main];
for (let code = 600003; code <= 600008; code += 1) {
  formals.push(record('SH' + code, String(code), 'formal_ready', 'formal', 'main'));
}
const duplicateH4 = JSON.parse(JSON.stringify(h4));
duplicateH4.id = 'duplicate-h4-version';
const projection = {
  items: [research, researchFormalIncomplete].concat(formals, [duplicateH4]),
  featured_ids: [research.id, researchFormalIncomplete.id]
};
const legacy = { code: '000777', name: '旧版合法行', page_status: 'formal_incomplete',
  score: 55, legacy_marker: 'keep-detail-ref',
  ref: { pool: 'picks_fusion', code: '000777' }, action_semantics: 'formal' };
const views = { main: [
  { code: '600002', name: '旧主推重复', ref: { pool: 'picks_fusion', code: '600002' } },
  legacy
] };
const primary = globalThis.__auxTest.rows(projection, 'decision_formal', views);
assert(primary.map(function (row) { return row.code; }).join(',')
  === '300001,300002,600001,600002,600003,600004,600005,600006,600007,600008,000777',
  'union order, dedupe, H4, featured research, or legacy append changed');
assert(primary.length === 11, 'primary union was globally truncated to five');
const researchRow = primary[0].workbench_item;
assert(researchRow.page_status === 'waiting_trigger'
  && researchRow.formal_action === null
  && researchRow.strategy_results[0].role === 'research',
  'featured research was promoted to formal or executable');
assert(primary[2].workbench_item.strategy_results[0].strategy_id === 'h4_t3',
  'H4-only formal row disappeared');
assert(primary[primary.length - 1].legacy_marker === 'keep-detail-ref'
  && primary[primary.length - 1].ref.pool === 'picks_fusion'
  && !primary[primary.length - 1].workbench_item,
  'legacy row lost its original detail path');

const focusAlias = globalThis.__auxTest.rows(projection, 'decision_focus', views);
assert(focusAlias.map(function (row) { return row.code; }).join(',')
  === primary.map(function (row) { return row.code; }).join(','),
  'old focus navigation did not migrate to primary');
const pendingAlias = globalThis.__auxTest.rows(projection, 'decision_wait', views);
assert(pendingAlias.map(function (row) { return row.code; }).join(',') === '600002,000777',
  'pending alias included research waiting or lost a formal/legacy pending row');

const bjResearch = record('BJ920001', '920001', 'waiting_trigger', 'research', 'confirming');
bjResearch.id = 'sample-bj';
const shBoundary = record('SH600011', '600011', 'formal_ready', 'formal', 'main');
const szBoundary = record('SZ300011', '300011', 'formal_ready', 'formal', 'main');
const identityProjection = {
  items: [bjResearch, shBoundary, szBoundary],
  featured_ids: ['sample-bj']
};
const identityViews = { main: [
  { code: '920001', name: '旧版北交所行', ref: { pool: 'picks_fusion', code: '920001' } },
  { code: '600011', name: '旧版沪市行', ref: { pool: 'picks_fusion', code: '600011' } },
  { code: '300011', name: '旧版深市行', ref: { pool: 'picks_fusion', code: '300011' } }
] };
const identityPrimary = globalThis.__auxTest.rows(
  identityProjection, 'decision_formal', identityViews
);
assert(identityPrimary.length === 3
  && identityPrimary.map(function (row) {
    return row.workbench_item && row.workbench_item.instrument_id;
  }).join(',') === 'BJ920001,SH600011,SZ300011',
  'legacy bare codes did not dedupe against canonical BJ/SH/SZ identities');
assert(identityPrimary[0].workbench_item.strategy_results[0].role === 'research'
  && identityPrimary[0].workbench_item.page_status === 'waiting_trigger'
  && identityPrimary[0].workbench_item.is_executable === false,
  'BJ featured research identity was promoted while deduping');

const explicitSh920001 = record('SH920001', '920001', 'formal_ready', 'formal', 'main');
const explicitMarkets = globalThis.__auxTest.rows({
  items: [bjResearch, explicitSh920001], featured_ids: ['sample-bj']
}, 'decision_formal', { main: identityViews.main.slice(0, 1) });
assert(explicitMarkets.length === 2
  && explicitMarkets.map(function (row) {
    return row.workbench_item.instrument_id;
  }).join(',') === 'BJ920001,SH920001',
  'explicit canonical identities for distinct securities were collapsed or reordered');

""",
        )

    def test_status_filter_empty_state_and_search_paging_share_primary_union(self):
        _assert_node_contract(
            self,
            "({ setup: normalizeWorkspace, selection: getCandidateSelection, quick: getQuickComparisonPool, description: renderViewDescription, empty: buildCandidateEmptyState, state: state, nodes: nodes })",
            r"""
function record(instrumentId, code, status, role, strategyId) {
  const formal = role === 'formal';
  return { id: 'row:' + instrumentId, instrument_id: instrumentId, code: code,
    name: '股票' + code, sector: '测试', page_status: status,
    formal_action: formal ? '可上车' : null, score: formal ? 60 : null,
    is_executable: status === 'formal_ready',
    candidate: { code: code, name: '股票' + code, sector: '测试',
      ref: { pool: strategyId + '_pool', code: code }, action_semantics: formal ? 'formal' : 'watch_only' },
    strategy_results: [{ strategy_id: strategyId, role: role,
      action_semantics: formal ? 'formal' : 'watch_only',
      formal_action: formal ? '可上车' : null, page_status: status }] };
}
const pending = record('SH600001', '600001', 'formal_incomplete', 'formal', 'main');
const ready = record('SH600002', '600002', 'formal_ready', 'formal', 'h4_t3');
const research = record('SZ300001', '300001', 'waiting_trigger', 'research', 'confirming');
const projection = { schema_version: 'decision-workbench-v1', report_date: '2026-09-16',
  phase: 'formal', items: [pending, ready, research], featured_ids: [research.id] };
const data = { date: '2026-09-16', workspace: { default_view: 'decision_wait',
  views: { main: [{ code: '600001', name: '股票600001' }] }, view_meta: {} } };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-16', decisionWorkbench: projection };
const t = globalThis.__auxTest;
t.state.data = data;
t.setup(data);
assert(t.state.currentView === 'decision_formal'
  && t.state.decisionStatusFilter === 'formal_incomplete',
  'old pending navigation did not migrate into the primary status filter');
let selected = t.selection('decision_formal', { query: '', sectorName: '', sectorCode: '', sectorRefs: [], limit: 20 });
assert(selected.poolItems.length === 3 && selected.items.length === 1
  && selected.items[0].code === '600001',
  'status filter did not stay inside the primary union');
assert(t.quick('decision_formal').map(function (row) { return row.code; }).join(',') === '600001',
  'comparison used a different collection from the status-filtered primary list');
t.state.candidateQuery = '600001';
selected = t.selection('decision_formal', { limit: 1 });
assert(selected.items.length === 1 && selected.visibleItems.length === 1,
  'search or paging escaped the primary status set');

const filterButtons = [];
t.nodes.description = {
  innerHTML: '',
  querySelectorAll: function () { return filterButtons; }
};
t.description();
assert(t.nodes.description.innerHTML.includes('主推')
  && t.nodes.description.innerHTML.includes('全部状态')
  && t.nodes.description.innerHTML.includes('正式待确认')
  && t.nodes.description.innerHTML.includes('正式 2 · 研究 1'),
  'primary status filter is not actually rendered');

t.state.decisionStatusFilter = '';
const emptyProjection = { schema_version: 'decision-workbench-v1', report_date: '2026-09-16',
  phase: 'formal', items: [], featured_ids: [] };
window.CHANLUN_BOOTSTRAP.decisionWorkbench = emptyProjection;
t.state.workspace.views.main = [];
const emptyHtml = t.empty('decision_formal', {}, {});
assert(emptyHtml.includes('本期暂无主推'), 'empty primary did not keep its natural empty state');
assert(!emptyHtml.includes('data-workbench-open-all')
  && !emptyHtml.includes('查看全部'), 'empty primary fell back to the complete research list');
""",
        )

    def test_pending_filter_keeps_list_detail_active_and_comparison_on_same_selection(self):
        _assert_node_contract(
            self,
            "({ setup: normalizeWorkspace, bind: bindPrimaryStatusFilters, "
            "initialize: function () { return renderCurrentCandidateSelection(); }, "
            "capture: function (action) { var calls = []; var original = renderCandidateDetail; "
            "renderCandidateDetail = function (item, target) { calls.push(item ? item.code : null); "
            "return original(item, target); }; try { action(); } finally { renderCandidateDetail = original; } "
            "var selection = getCandidateSelection(state.currentView); return { "
            "list: asArray(nodes.candidateList && nodes.candidateList.children).filter(function (node) { "
            "return node && node.attrs && node.attrs[\"data-code\"]; }).map(function (node) { "
            "return node.attrs[\"data-code\"]; }), visible: selection.visibleItems.map(function (item) { "
            "return item.code; }), detailCalls: calls, detailHtml: normalizeString(nodes.detailPanel && "
            "nodes.detailPanel.innerHTML), active: state.activeItem ? state.activeItem.code : null, "
            "quick: getQuickComparisonPool(state.currentView).map(function (item) { return item.code; }), "
            "filter: state.decisionStatusFilter }; }, state: state, nodes: nodes })",
            r"""
function element() {
  const node = {
    textContent: '', hidden: false, children: [], attrs: {}, handlers: {},
    setAttribute: function (key, value) { this.attrs[key] = String(value); },
    getAttribute: function (key) { return this.attrs[key] || null; },
    appendChild: function (child) { this.children.push(child); return child; },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    addEventListener: function (key, handler) { this.handlers[key] = handler; },
    focus: function () {},
    classList: { add: function () {}, remove: function () {},
      toggle: function () {}, contains: function () { return false; } }
  };
  let html = '';
  Object.defineProperty(node, 'innerHTML', {
    get: function () { return html; },
    set: function (value) {
      html = String(value || '');
      if (!html) this.children = [];
    }
  });
  return node;
}
document.createElement = element;
document.body = element();

function record(instrumentId, code, status, role, strategyId) {
  const formal = role === 'formal';
  return {
    id: 'row:' + instrumentId, instrument_id: instrumentId, code: code,
    name: '股票' + code, sector: '测试', page_status: status,
    status_label: formal ? '正式推荐·条件待补充' : '等待条件确认',
    formal_action: formal ? '可上车' : null, score: formal ? 60 : null,
    is_executable: false,
    candidate: { code: code, name: '股票' + code, sector: '测试',
      ref: { pool: strategyId + '_pool', code: code },
      action_semantics: formal ? 'formal' : 'watch_only' },
    strategy_results: [{ strategy_id: strategyId, role: role,
      action_semantics: formal ? 'formal' : 'watch_only',
      formal_action: formal ? '可上车' : null, page_status: status }]
  };
}

const t = globalThis.__auxTest;
function statusButton(value) {
  const button = element();
  button.getAttribute = function (key) {
    return key === 'data-decision-status-filter' ? value : (this.attrs[key] || null);
  };
  return button;
}

function prepare(formalStatus, defaultView) {
  const research = record('SZ300001', '300001', 'waiting_trigger', 'research', 'confirming');
  const formal = record('SH600001', '600001', formalStatus, 'formal', 'main');
  const projection = {
    schema_version: 'decision-workbench-v1', report_date: '2026-09-16',
    phase: 'formal', items: [research, formal], featured_ids: [research.id]
  };
  const data = {
    date: '2026-09-16',
    workspace: {
      default_view: defaultView,
      views: { main: [{ code: '600001', name: '股票600001',
        ref: { pool: 'picks_fusion', code: '600001' } }] },
      view_meta: { main: { role: 'formal', action_semantics: 'formal',
        availability: { state: 'available' } } }
    }
  };
  window.CHANLUN_BOOTSTRAP = {
    pageDate: '2026-09-16', decisionWorkbench: projection
  };
  t.state.data = data;
  t.setup(data);
  t.state.currentView = t.state.workspace.default_view;
  t.state.candidateQuery = '';
  t.state.candidateLimit = 20;
  t.state.sectorFilter = '';
  t.state.sectorFilterCode = '';
  t.state.sectorFilterRefs = [];
  t.state.activeItem = null;
  t.state.activeCandidateKey = '';
  t.state.detailCandidateKey = '';
  t.state.detailTarget = null;
  t.state.chartInstance = null;
  t.state.chartMount = null;

  const pending = statusButton('formal_incomplete');
  const all = statusButton('');
  const description = element();
  description.querySelectorAll = function () { return [all, pending]; };
  t.nodes.description = description;
  t.nodes.tabs = null;
  t.nodes.candidateList = element();
  t.nodes.detailPanel = element();
  t.nodes.workspaceBody = element();
  t.nodes.candidateTools = null;
  t.nodes.candidateCount = element();
  t.nodes.candidateMore = element();
  t.nodes.candidateSearch = element();
  t.nodes.candidateSearch.value = '';
  t.nodes.candidateEvidenceComparison = null;
  t.nodes.candidateQuickComparison = null;
  t.nodes.drawerContent = null;
  return { pending: pending, all: all };
}

const switched = prepare('formal_incomplete', 'decision_formal');
const pendingResult = t.capture(function () {
  t.bind();
  switched.pending.handlers.click({ currentTarget: switched.pending });
});
assert(pendingResult.filter === 'formal_incomplete'
  && pendingResult.list.join(',') === '600001'
  && pendingResult.visible.join(',') === '600001'
  && pendingResult.quick.join(',') === '600001',
  'pending click did not keep list and comparison on the filtered formal set');
assert(pendingResult.active === '600001'
  && pendingResult.detailCalls.length > 0
  && pendingResult.detailCalls.every(function (code) { return code === '600001'; }),
  'pending click let an unfiltered research item overwrite active detail');

prepare('formal_incomplete', 'decision_wait');
assert(t.state.currentView === 'decision_formal'
  && t.state.decisionStatusFilter === 'formal_incomplete',
  'legacy pending state did not restore at the navigation boundary');
const restored = t.capture(function () { t.initialize(); });
assert(restored.list.join(',') === '600001'
  && restored.visible.join(',') === '600001'
  && restored.quick.join(',') === '600001'
  && restored.active === '600001'
  && restored.detailCalls.every(function (code) { return code === '600001'; }),
  'legacy pending restore did not initialize from the filtered visible set');

const zero = prepare('formal_ready', 'decision_formal');
const emptyResult = t.capture(function () {
  t.bind();
  zero.pending.handlers.click({ currentTarget: zero.pending });
});
assert(emptyResult.list.length === 0 && emptyResult.visible.length === 0
  && emptyResult.quick.length === 0 && emptyResult.active === null,
  'zero-match pending filter borrowed an item outside the filtered set');
assert(emptyResult.detailCalls.length > 0
  && emptyResult.detailCalls.every(function (code) { return code === null; })
  && emptyResult.detailHtml.includes('主推中暂无正式待确认'),
  'zero-match pending filter did not preserve its empty detail state');

const allResult = t.capture(function () {
  zero.all.handlers.click({ currentTarget: zero.all });
});
assert(allResult.filter === ''
  && allResult.list.join(',') === '300001,600001'
  && allResult.visible.join(',') === '300001,600001'
  && allResult.quick.join(',') === '300001,600001',
  'returning to all statuses did not restore the primary union consistently');
assert(allResult.active === '300001'
  && allResult.detailCalls.length > 0
  && allResult.detailCalls.every(function (code) { return code === '300001'; }),
  'all-status detail did not follow the restored first visible item');
""",
        )


if __name__ == "__main__":
    unittest.main()
