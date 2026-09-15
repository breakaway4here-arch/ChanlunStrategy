"""Contracts for the chart-centered daily decision workbench."""

import re
import unittest

from tests.test_auxiliary_frontend import CSS, JS, _assert_node_contract


class TestChartCenteredDecisionWorkbench(unittest.TestCase):
    def test_full_market_evidence_stays_in_document_flow_inside_today_workspace(self):
        shell_start = JS.index("function buildAppShell")
        shell_end = JS.index("function getReportDataStatus", shell_start)
        shell = JS[shell_start:shell_end]

        workspace = shell.index('class="workspace today-workspace"')
        self.assertIn('id="marketDecisionBar"', shell)
        market_bar = shell.index('id="marketDecisionBar"')
        tabs = shell.index('id="workspaceTabs"')
        workspace_end = shell.index("</section>", tabs)

        self.assertLess(workspace, market_bar)
        self.assertLess(market_bar, tabs)
        self.assertLess(tabs, workspace_end)
        for token in (
            'id="marketDecisionSummary"',
            'id="sectorStrip"',
            'id="directionQuickSummary"',
        ):
            self.assertIn(token, shell[market_bar:tabs])

        sticky = re.search(
            r"\.market-decision-bar\s*\{(?P<body>[^}]*)\}", CSS, re.DOTALL
        )
        self.assertIsNotNone(sticky)
        self.assertRegex(sticky.group("body"), r"position:\s*static\s*;")

    def test_formal_market_summary_uses_real_contract_and_quality(self):
        _assert_node_contract(
            self,
            "{ build: buildDecisionMarketSummary }",
            r"""
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-09-01',
    market_sentiment: {
      formal_contract: {
        status: 'available', as_of: '2026-09-01', score: 68,
        label: '偏强', coverage: 1, version: 'formal-market-v1',
        insufficient: false,
        components: { breadth: 66, limit_ecology: 70, index: 61, turnover: 72, trend: 74 },
        evidence: {
          breadth: { available: true }, limit_ecology: { available: true },
          index: { available: true }, turnover: { available: true }, trend: { available: true }
        }
      }
    },
    views: { main: [] }
  }
};
const html = globalThis.__auxTest.build({
  date: '2026-09-01',
  data_quality: {
    is_official: true, bar_state: 'closed', market_status: 'verified',
    as_of: '2026-09-01T15:08:00+08:00'
  }
});
['市场状态', '偏强', '68', '广度', '涨跌停生态', '指数', '成交', '趋势',
 '2026-09-01', '15:08', '正式收盘版', '行情已核验'].forEach(function (text) {
  assert(html.includes(text), 'market summary missing real fact: ' + text);
});
assert(!html.includes('PSY12'), 'shadow market metric leaked into the formal summary');
""",
        )

    def test_market_summary_discloses_degraded_quality(self):
        _assert_node_contract(
            self,
            "{ build: buildDecisionMarketSummary }",
            r"""
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-01' };
const html = globalThis.__auxTest.build({
  date: '2026-09-01', market: {},
  data_quality: {
    is_official: true, bar_state: 'closed', market_status: 'verified',
    as_of: '2026-09-01T15:08:00+08:00', fallback_used: true,
    warnings: ['行情使用本地回退']
  }
});
assert(html.includes('数据降级'), 'market quality slot hid fallback/warning state');
""",
        )

    def test_detail_orders_chart_and_four_decision_questions_before_research(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            r"""
const section = function (extra) {
  return Object.assign({ status: 'available', as_of: '2026-09-01', source: 'fixture' }, extra || {});
};
const evidence = {
  code: '600001',
  summary: section({
    code: '600001', name: '测试股', sector: '工业', formal_action: '推荐',
    formal_action_reason: '日线结构与量能共振', data_health: 'verified',
    data_is_final: true, data_stale: false
  }),
  decision_score: section({ score: 72, decision_code: 'recommend', components: {} }),
  rank_evidence: section({ view_rank: 1, opportunity_score: 91 }),
  price_evidence: section({ current_price: 10.8, reference_price: 10.2, invalidation_price: 9.6 }),
  daily_structure: section({ summary: '日线突破中枢上沿' }),
  sublevel_30m: section({ summary: '30分钟等待回踩确认' }),
  volume_and_capital: section({ summary: '成交量温和放大' }),
  market_and_sector: section({ summary: '市场偏强；板块资金同向' }),
  main_rise_clue: section({}),
  risk_and_next: section({
    next_confirmation: { items: ['回踩不破参考价'] },
    invalidation_conditions: { items: ['跌破 9.60'] }
  }),
  historical_validation: section({})
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01',
  recommendationEvidence: {
    schema_version: 1, report_date: '2026-09-01', views: { main: [evidence] }
  }
};
globalThis.__auxTest.state.data = {
  date: '2026-09-01',
  selection_input_health: {
    by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
  }
};
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001', name: '测试股', ref: { pool: 'picks_fusion', code: '600001' }
}, {});
const conclusion = html.indexOf('data-evidence-module="01"');
const chart = html.indexOf('id="chartCanvas"');
const brief = html.indexOf('class="decision-workbench-brief"');
const research = html.indexOf('class="candidate-research-details"');
assert(conclusion >= 0 && conclusion < chart, 'formal conclusion is not before the chart');
assert(chart < brief, 'four-question brief is not directly after the chart');
assert(brief < research, 'research evidence is still ahead of the decision brief');
['为什么', '可执行性', '下一确认', '失效'].forEach(function (label) {
  assert(html.slice(brief, research).includes(label), 'decision brief missing: ' + label);
});
assert(html.slice(0, research).includes('正式动作：推荐'),
  'formal action is hidden inside the research disclosure');
assert(!html.includes('candidate-research-details" open'),
  'full research evidence must be closed by default');
""",
        )

    def test_research_candidate_obeys_watch_only_action_and_public_reason(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, state: state })",
            r"""
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01', recommendationEvidence: {
    schema_version: 1, report_date: '2026-09-01', views: { acceleration: [{
      code: '600088', summary: {
        formal_action: '可上车', formal_action_reason: '立即执行'
      }
    }] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-09-01' };
globalThis.__auxTest.state.currentView = 'acceleration';
const summary = globalThis.__auxTest.summary({
  code: '600088', action_semantics: 'formal',
  page_action_reason: '研究观察：等待盘面确认',
  decision_engine_v1: { decision: '推荐', total_score: 70 }
}, 'acceleration');
assert(summary.action === '仅观察', 'research row reused formal executable action');
assert(summary.reason === '研究观察：等待盘面确认', 'research row reused formal action reason');
assert(summary.scoreText === '决策分 70', 'intentional formal total_score display disappeared');
assert(!JSON.stringify(summary).includes('立即执行') && !JSON.stringify(summary).includes('可上车'),
  'research row leaked formal action semantics');
""",
        )

    def test_research_detail_uses_page_action_not_pseudo_formal_action(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            r"""
const section = function (extra) {
  return Object.assign({ status: 'available', as_of: '2026-09-01', source: 'fixture' }, extra || {});
};
const evidence = {
  code: '600088',
  summary: section({
    code: '600088', name: '研究票', view_identity: 'acceleration',
    formal_action: null, formal_action_reason: null,
    data_health: 'verified', data_is_final: true, data_stale: false
  }),
  decision_score: section({ score: 70, decision_code: 'recommend', components: {} }),
  rank_evidence: section({ view_rank: 1, opportunity_score: 90 }),
  price_evidence: section({}), daily_structure: section({ summary: '日线研究线索' }),
  sublevel_30m: section({}), volume_and_capital: section({}),
  market_and_sector: section({}), main_rise_clue: section({}),
  risk_and_next: section({}), historical_validation: section({})
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01', recommendationEvidence: {
    schema_version: 1, report_date: '2026-09-01', views: { acceleration: [evidence] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-09-01' };
globalThis.__auxTest.state.currentView = 'acceleration';
const html = globalThis.__auxTest.detail({
  code: '600088', name: '研究票', action_semantics: 'formal',
  page_action: '可上车', page_action_reason: '研究观察：等待盘面确认',
  ref: { pool: 'next_day_boom', code: '600088' }
}, {});
assert(html.includes('页面动作：仅观察'), 'research detail did not use view-level watch-only action');
assert(html.includes('研究观察：等待盘面确认'), 'research detail lost its public page reason');
assert(!html.includes('正式动作：') && !html.includes('本期未声明正式动作'),
  'research detail rendered a pseudo-formal action');
assert(!html.includes('正式动作：可上车'), 'malformed item action overrode research view semantics');
""",
        )

    def test_recommendation_with_missing_key_price_keeps_action_but_blocks_execution(self):
        _assert_node_contract(
            self,
            "{ brief: renderDecisionWorkbenchBrief }",
            r"""
const html = globalThis.__auxTest.brief({
  summary: {
    status: 'available', formal_action: '推荐', formal_action_reason: '日线结构确认',
    data_health: 'verified', data_is_final: true, data_stale: false
  },
  price_evidence: { current_price: 10.8, reference_price: null, invalidation_price: null },
  daily_structure: { summary: '日线结构确认' },
  sublevel_30m: {},
  market_and_sector: {},
  risk_and_next: { next_confirmation: { items: [] }, invalidation_conditions: { items: [] } }
});
assert(html.includes('正式动作：推荐'), 'formal action disappeared because execution prices are missing');
assert(html.includes('关键价格待确认：缺少参考价、失效位'),
  'missing execution boundary is not named precisely');
assert(html.includes('下一确认待补充'), 'missing next confirmation is not visible');
assert(html.includes('失效条件待补充'), 'missing invalidation condition is not visible');
""",
        )

    def test_candidate_summary_uses_only_formal_total_score(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, state: state })",
            r"""
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01',
  recommendationEvidence: {
    schema_version: 1, report_date: '2026-09-01', views: { main: [
      { code: '600001', summary: { formal_action: '推荐', formal_action_reason: '日线结构确认' } },
      { code: '600002', summary: { formal_action: '观察', formal_action_reason: '等待下一确认' } }
    ] }
  }
};
globalThis.__auxTest.state.data = {
  date: '2026-09-01',
  selection_input_health: {
    by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
  }
};
globalThis.__auxTest.state.currentView = 'main';
const formal = globalThis.__auxTest.summary({
  code: '600001', decision_engine_v1: {
    decision: '推荐', total_score: 62, score: 88, final_score: 77, opportunity_score: 99
  }
}, 'main');
assert(formal.action === '推荐', 'candidate summary lost the one formal action');
assert(formal.reason === '日线结构确认', 'candidate summary lost the public formal reason');
assert(formal.scoreText === '决策分 62', 'formal total_score was not rendered as decision score');
assert(!JSON.stringify(formal).includes('88') && !JSON.stringify(formal).includes('77')
  && !JSON.stringify(formal).includes('99'), 'candidate summary leaked a fallback score');

const rankingOnly = globalThis.__auxTest.summary({
  code: '600002', decision_engine_v1: {
    decision: '观察', score: 88, final_score: 77, opportunity_score: 99
  }
}, 'main');
assert(rankingOnly.scoreText === '暂无正式决策分',
  'missing formal total_score did not fail closed');
assert(!JSON.stringify(rankingOnly).includes('88') && !JSON.stringify(rankingOnly).includes('77')
  && !JSON.stringify(rankingOnly).includes('99'), 'missing score summary leaked ranking values');

[true, false, Infinity, -1, 101].forEach(function (invalidScore) {
  const malformed = globalThis.__auxTest.summary({
    code: '600002', decision_engine_v1: { decision: '观察', total_score: invalidScore }
  }, 'main');
  assert(malformed.scoreText === '暂无正式决策分',
    'malformed or out-of-range total_score became public: ' + String(invalidScore));
});
""",
        )

    def test_incident_review_candidate_never_restores_action_or_score(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, state: state })",
            r"""
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01', recommendationEvidence: {
    schema_version: 1, report_date: '2026-09-01', views: { main: [{
      code: '600099', summary: {
        formal_action: '推荐', formal_action_reason: '事故前原始理由'
      }
    }] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-09-01' };
globalThis.__auxTest.state.currentView = 'main';
const summary = globalThis.__auxTest.summary({
  code: '600099', incident_review_only: true,
  page_action_reason: '策略输入过期或未核验，仅供事故复盘。',
  decision_engine_v1: { decision: '推荐', total_score: 70 }
}, 'main');
assert(summary.action === '仅追溯', 'incident review restored an actionable formal label');
assert(summary.scoreText === '暂无正式决策分', 'incident review restored an invalid formal score');
assert(!JSON.stringify(summary).includes('70'), 'incident review leaked invalid score value');
""",
        )

    def test_formal_source_scores_are_visible_without_merging_or_research_leak(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, identity: renderCandidateRowIdentity, detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
t.state.data = { date: '2026-09-14' };
const item = { code: '600001', name: '多来源样本', workbench_item: {
  code: '600001', name: '多来源样本', status_label: '正式策略分歧',
  formal_action: null, score: null, primary_reason: '来源动作不同',
  is_executable: false, blocking_reasons: ['正式策略意见不一致'],
  contracts: {}, strategy_results: [
    { strategy_id: 'main', role: 'formal', action_semantics: 'formal',
      formal_action: '推荐', score: 88, contract: {}, evidence: {} },
    { strategy_id: 'h4_t3', role: 'formal', action_semantics: 'formal',
      formal_action: '观察', score: 60, contract: {}, evidence: {} },
    { strategy_id: 'acceleration', role: 'research', action_semantics: 'formal',
      formal_action: null, score: 91, contract: {}, evidence: {} }
  ]
} };
const identity = t.identity(item, 'decision_all', t.summary(item, 'decision_all'));
assert(identity.includes('正式主推') && identity.includes('决策分 88'),
  'main formal source score is missing from the identity line');
assert(identity.includes('H4 T+3') && identity.includes('决策分 60'),
  'H4 formal source score is missing from the identity line');
assert(!identity.includes('91'), 'research score leaked into the identity line');
assert((identity.match(/data-source-score/g) || []).length === 2,
  'different formal source scores were merged or duplicated');
const detail = t.detail(item);
assert(detail.includes('data-source-score="main">决策分 88'),
  'main score is not readable beside its detail source title');
assert(detail.includes('data-source-score="h4_t3">决策分 60'),
  'H4 score is not readable beside its detail source title');
assert(!detail.includes('data-source-score="acceleration"') && !detail.includes('决策分 91'),
  'research score leaked into the source detail');

const zero = { code: '600002', name: '零分样本', action_semantics: 'formal',
  decision_engine_v1: { total_score: 0 } };
const zeroIdentity = t.identity(zero, 'main', t.summary(zero, 'main'));
assert(zeroIdentity.includes('决策分 0'), 'a real formal zero score disappeared');
const missing = { code: '600003', name: '缺分样本', action_semantics: 'formal',
  decision_engine_v1: { opportunity_score: 99 } };
const missingIdentity = t.identity(missing, 'main', t.summary(missing, 'main'));
assert(!missingIdentity.includes('决策分 0') && !missingIdentity.includes('99'),
  'missing formal score was filled from zero or a ranking score');
const research = { code: '600004', name: '研究样本', action_semantics: 'watch_only',
  decision_engine_v1: { total_score: 91 } };
const researchIdentity = t.identity(research, 'acceleration', t.summary(research, 'acceleration'));
assert(!researchIdentity.includes('决策分') && !researchIdentity.includes('91'),
  'legacy research score was connected to the visible identity line');
const incident = { code: '600005', name: '事故复盘', incident_review_only: true,
  action_semantics: 'formal', decision_engine_v1: { total_score: 77 } };
const incidentIdentity = t.identity(incident, 'main', t.summary(incident, 'main'));
assert(!incidentIdentity.includes('决策分') && !incidentIdentity.includes('77'),
  'incident review restored a visible formal score');
const unifiedIncident = { code: '600006', name: '统一事故复盘', workbench_item: {
  code: '600006', name: '统一事故复盘', status_label: '仅追溯', formal_action: null,
  score: null, primary_reason: '原始记录', contracts: {}, strategy_results: [
    { strategy_id: 'main', role: 'formal', action_semantics: 'formal', score: 76,
      candidate: { incident_review_only: true }, contract: {}, evidence: {} }
  ]
} };
const unifiedIncidentIdentity = t.identity(unifiedIncident, 'decision_all', t.summary(unifiedIncident, 'decision_all'));
assert(!unifiedIncidentIdentity.includes('决策分') && !t.detail(unifiedIncident).includes('决策分 76'),
  'strategy-level incident review restored a visible formal score');
const anonymousFormal = { code: '600007', name: '来源缺失', workbench_item: {
  code: '600007', name: '来源缺失', status_label: '待核验', formal_action: null,
  score: null, primary_reason: '来源未声明', contracts: {}, strategy_results: [
    { role: 'formal', action_semantics: 'formal', score: 75, contract: {}, evidence: {} }
  ]
} };
assert(!t.identity(anonymousFormal, 'decision_all', t.summary(anonymousFormal, 'decision_all')).includes('决策分 75'),
  'a score without a named formal source became visible');
""",
        )

    def test_visible_formal_scores_accept_only_numeric_scalars(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, identity: renderCandidateRowIdentity, detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
t.state.data = { date: '2026-09-14' };
function unified(score) {
  return { code: '600001', name: '正式分类型样本', workbench_item: {
    code: '600001', name: '正式分类型样本', status_label: '正式待确认',
    formal_action: '观察', primary_reason: '核对原始决策分', is_executable: false,
    contracts: {}, strategy_results: [
      { strategy_id: 'main', role: 'formal', action_semantics: 'formal',
        formal_action: '观察', score: score, contract: {}, evidence: {} }
    ]
  } };
}
for (const value of ['   ', [], ['88'], true, false, Infinity, -1, 101]) {
  const item = unified(value);
  const identity = t.identity(item, 'decision_all', t.summary(item, 'decision_all'));
  const detail = t.detail(item);
  assert(!identity.includes('data-source-score') && !detail.includes('data-source-score'),
    'invalid formal score became visible: ' + JSON.stringify(value));
}
const unifiedNumericString = unified('88');
assert(t.identity(unifiedNumericString, 'decision_all', t.summary(unifiedNumericString, 'decision_all')).includes('决策分 88'),
  'valid unified numeric string score disappeared');
assert(t.detail(unifiedNumericString).includes('决策分 88'),
  'valid unified numeric string score disappeared from detail');

for (const value of ['   ', [], ['88'], true, false, Infinity, -1, 101]) {
  const item = { code: '600002', name: 'Legacy 正式分类型样本', action_semantics: 'formal',
    decision_engine_v1: { total_score: value } };
  const identity = t.identity(item, 'main', t.summary(item, 'main'));
  assert(!identity.includes('决策分'),
    'invalid legacy formal score became visible: ' + JSON.stringify(value));
}
const legacyNumericString = { code: '600003', name: 'Legacy 数字字符串', action_semantics: 'formal',
  decision_engine_v1: { total_score: '88' } };
assert(t.identity(legacyNumericString, 'main', t.summary(legacyNumericString, 'main')).includes('决策分 88'),
  'valid legacy numeric string score disappeared');
""",
        )

    def test_legacy_formal_score_respects_explicit_record_identity(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, identity: renderCandidateRowIdentity, state: state })",
            r"""
const t = globalThis.__auxTest;
t.state.data = { date: '2026-09-14' };
function identity(patch) {
  const item = Object.assign({ code: '600001', name: 'Legacy 身份样本',
    decision_engine_v1: { total_score: 91 } }, patch);
  return t.identity(item, 'main', t.summary(item, 'main'));
}
for (const patch of [
  { action_semantics: 'watch_only' },
  { action_semantics: 'upstream_only' },
  { role: 'research' },
  { role: 'baseline' },
  { role: 'research', action_semantics: 'formal' },
  { role: 'formal', action_semantics: 'watch_only' }
]) {
  assert(!identity(patch).includes('决策分 91'),
    'formal view overrode explicit non-formal identity: ' + JSON.stringify(patch));
}
assert(identity({ action_semantics: 'formal' }).includes('决策分 91'),
  'explicit legacy formal identity lost its score');
assert(identity({}).includes('决策分 91'),
  'legacy formal-view compatibility lost its score');
""",
        )

    def test_unified_detail_header_exposes_source_scores_before_collapsed_evidence(self):
        _assert_node_contract(
            self,
            "({ detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
t.state.data = { date: '2026-09-14' };
const item = { code: '600001', name: '首屏来源分样本', workbench_item: {
  code: '600001', name: '首屏来源分样本', status_label: '正式策略分歧',
  formal_action: null, primary_reason: '来源动作不同', is_executable: false,
  blocking_reasons: ['正式策略意见不一致'], contracts: {}, strategy_results: [
    { strategy_id: 'main', role: 'formal', action_semantics: 'formal', score: 88,
      formal_action: '推荐', contract: {}, evidence: {} },
    { strategy_id: 'h4_t3', role: 'formal', action_semantics: 'formal', score: 60,
      formal_action: '观察', contract: {}, evidence: {} },
    { strategy_id: 'acceleration', role: 'research', action_semantics: 'watch_only', score: 91,
      formal_action: null, contract: {}, evidence: {} }
  ]
} };
const html = t.detail(item);
const headerStart = html.indexOf('<header class="unified-stock-head">');
const headerEnd = html.indexOf('</header>', headerStart);
const header = html.slice(headerStart, headerEnd);
assert(header.includes('正式主推 决策分 88'),
  'main source score is not visible in the first-layer detail header');
assert(header.includes('H4 T+3 决策分 60'),
  'H4 source score is not visible in the first-layer detail header');
assert(!header.includes('91') && !header.includes('acceleration'),
  'research score leaked into the first-layer detail header');
assert(header.includes('正式策略分歧') && header.includes('正式策略意见不一致'),
  'first-layer score displaced status or blocker context');
""",
        )

    def test_top_level_incident_suppresses_header_and_source_title_scores(self):
        _assert_node_contract(
            self,
            "({ detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
t.state.data = { date: '2026-09-14' };
const item = { code: '600008', name: '顶层事故复盘', incident_review_only: true,
  workbench_item: { code: '600008', name: '顶层事故复盘', status_label: '仅追溯',
    formal_action: null, primary_reason: '原始记录', is_executable: false,
    contracts: {}, strategy_results: [
      { strategy_id: 'main', role: 'formal', action_semantics: 'formal', score: 88,
        formal_action: '推荐', candidate: { incident_review_only: false }, contract: {}, evidence: {} }
    ]
  }
};
const html = t.detail(item);
const header = (html.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
const sourceTitle = (html.match(/<header class="candidate-source-title">([\s\S]*?)<\/header>/) || [])[1] || '';
assert(!header.includes('data-source-score') && !header.includes('决策分 88'),
  'top-level incident leaked a formal score into the first-layer header');
assert(!sourceTitle.includes('data-source-score') && !sourceTitle.includes('决策分 88'),
  'top-level incident leaked a formal score into the source title');
""",
        )

    def test_decision_navigation_descriptions_remain_readable_for_empty_views(self):
        _assert_node_contract(
            self,
            "({ render: renderViewDescription, state: state, nodes: nodes })",
            r"""
const t = globalThis.__auxTest;
t.nodes.description = { innerHTML: '' };
t.state.data = { date: '2026-09-14' };
t.state.workspace = { views: {}, view_meta: {} };
t.state.currentView = 'decision_formal';
t.render();
assert(t.nodes.description.innerHTML.includes('本期正式策略的全部结果，包含待确认、不可执行及风险状态；请查看具体动作。'),
  'formal-results explanation disappeared when the pool is empty');
t.state.currentView = 'decision_focus';
t.render();
assert(t.nodes.description.innerHTML.includes('按本期状态及原顺序选取至多 5 项供优先复核，可能包含研究观察；不是独立推荐排名。'),
  'focus explanation disappeared when the pool is empty');
""",
        )

    def test_candidate_row_is_limited_to_identity_market_and_reason_lines(self):
        start = JS.index("function renderCandidateList")
        end = JS.index("function buildDecisionHeader", start)
        renderer = JS[start:end]
        for token in (
            "buildCandidateRowSummary(",
            "renderCandidateRowIdentity(item, state.currentView, rowSummary)",
            "renderCandidateRowMarket(item, marketContext)",
            "renderCandidateRowReason(item, state.currentView, rowSummary)",
        ):
            self.assertIn(token, renderer)
        self.assertNotIn('renderCandidateStatusSummary(item, state.currentView)', renderer)
        self.assertNotIn('class="candidate-row-score"', renderer)
        for forbidden in (
            'class="candidate-price',
            "getCandidateChangePct(item)",
            "getRankClass(rank)",
        ):
            self.assertNotIn(forbidden, renderer)

    def test_data_risk_observe_and_reject_states_fail_closed_in_first_layer(self):
        _assert_node_contract(
            self,
            "{ brief: renderDecisionWorkbenchBrief }",
            r"""
const stale = globalThis.__auxTest.brief({
  summary: {
    formal_action: '推荐', formal_action_reason: '历史结构曾满足',
    data_health: 'stale', data_is_final: false, data_stale: true
  },
  price_evidence: { reference_price: 10, invalidation_price: 9 },
  risk_and_next: {}
});
['数据陈旧', '非终局', '数据健康异常：stale', '当前不可作为正式可执行结果'].forEach(function (text) {
  assert(stale.includes(text), 'stale/non-final state is not fail closed: ' + text);
});

const observe = globalThis.__auxTest.brief({
  summary: { formal_action: '观察', formal_action_reason: '等待确认', data_health: 'verified', data_is_final: true, data_stale: false },
  price_evidence: {}, risk_and_next: {}
});
assert(observe.includes('正式动作：观察') && observe.includes('下一确认待补充'),
  'observe state does not separate action from missing confirmation');

const reject = globalThis.__auxTest.brief({
  summary: { formal_action: '不推荐', data_health: 'verified', data_is_final: true, data_stale: false },
  price_evidence: {}, risk_and_next: {}
});
assert(reject.includes('正式动作：不推荐') && reject.includes('拒绝原因待核验'),
  'reject state hides its missing formal reason');
""",
        )

    def test_unknown_data_finality_blocks_recommendation_execution(self):
        _assert_node_contract(
            self,
            "{ brief: renderDecisionWorkbenchBrief }",
            r"""
const html = globalThis.__auxTest.brief({
  summary: { status: 'available', formal_action: '推荐', formal_action_reason: '结构曾满足' },
  price_evidence: { reference_price: 10, invalidation_price: 9 },
  risk_and_next: {}
});
['陈旧状态未提供', '终局状态未提供', '数据健康未提供', '当前不可作为正式可执行结果'].forEach(function (text) {
  assert(html.includes(text), 'unknown data finality did not fail closed: ' + text);
});
assert(!html.includes('关键价格完整，可按正式动作核验执行'),
  'unknown data finality was presented as executable');
""",
        )

    def test_conflicting_summary_status_blocks_execution_even_with_healthy_flags(self):
        _assert_node_contract(
            self,
            "{ brief: renderDecisionWorkbenchBrief }",
            r"""
const html = globalThis.__auxTest.brief({
  summary: {
    status: 'conflict', formal_action: '可上车', formal_action_reason: '结构满足',
    data_health: 'verified', data_is_final: true, data_stale: false
  },
  price_evidence: { reference_price: 10, invalidation_price: 9 },
  risk_and_next: {}
});
assert(html.includes('证据状态异常：conflict'), 'conflicting evidence status is not visible');
assert(html.includes('当前不可作为正式可执行结果'), 'conflicting evidence status did not block execution');
assert(!html.includes('关键价格完整，可按正式动作核验执行'),
  'conflicting evidence was presented as executable');
""",
        )

    def test_primary_conclusion_collapses_score_composition_before_chart(self):
        _assert_node_contract(
            self,
            "{ render: renderRecommendationConclusion }",
            r"""
const html = globalThis.__auxTest.render({
  summary: {
    code: '600001', name: '风险股', formal_action: '观察',
    formal_action_reason: '等待确认', data_health: 'stale',
    data_is_final: false, data_stale: true
  },
  decision_score: {
    score: 61, decision_code: 'observe',
    components: { structure: { score: 20, reasons: ['结构待确认'] } }
  },
  rank_evidence: { view_rank: 2, opportunity_score: 88 }
}, false);
const risk = html.indexOf('class="recommendation-evidence-risk-facts"');
const meta = html.indexOf('<details class="evidence-meta-details">');
const scoreAudit = html.indexOf('class="decision-score-audit"');
assert(risk >= 0 && risk < meta, 'data risk is hidden in the collapsed audit layer');
assert(meta < scoreAudit, 'score composition is not inside the collapsed audit layer');
assert(!html.includes('<details class="evidence-meta-details" open'),
  'score and audit detail must remain closed by default');
""",
        )

    def test_decision_score_readouts_require_formal_non_incident_semantics(self):
        _assert_node_contract(
            self,
            "{ render: renderRecommendationConclusion }",
            r"""
function evidence(score) {
  return {
    summary: {
      code: '600001', name: '控制样本', formal_action: '观察',
      formal_action_reason: '等待确认', data_health: 'verified',
      data_is_final: true, data_stale: false
    },
    decision_score: {
      score: score, decision_code: 'observe',
      components: {
        structure: { score: score, reasons: ['结构原因'] },
        position: { score: 0, reasons: ['位置原因'] },
        sentiment: { score: 0, reasons: ['情绪原因'] }
      }
    },
    rank_evidence: { view_rank: 2, opportunity_score: 88 }
  };
}
const formal = globalThis.__auxTest.render(evidence(64), false, 'audit', 'formal');
assert(formal.includes('<span>决策分</span><strong>64')
  && formal.includes('class="recommendation-component-grid"')
  && formal.includes('<span>结构</span><strong>64'),
  'validated formal decision score or its components disappeared');
const formalZero = globalThis.__auxTest.render(evidence(0), false, 'audit', 'formal');
assert(formalZero.includes('<span>决策分</span><strong>0')
  && formalZero.includes('<span>结构</span><strong>0'),
  'a true formal zero score or zero component was treated as missing');
const incident = globalThis.__auxTest.render(evidence(64), true, 'audit', 'formal');
assert(incident.includes('事故复盘评分不生效')
  && !incident.includes('<span>决策分</span><strong>64')
  && !incident.includes('class="recommendation-component-grid"')
  && !incident.includes('<span>结构</span><strong>64'),
  'incident review exposed an active score or score components');
""",
        )

    def test_390_stacks_market_chart_brief_and_disables_sticky_overlay(self):
        mobile_start = CSS.rfind("@media (max-width: 390px)")
        self.assertGreaterEqual(mobile_start, 0)
        mobile = CSS[mobile_start:]
        self.assertRegex(
            mobile,
            re.compile(
                r"\.market-decision-bar\s*\{[^}]*position:\s*static\s*;",
                re.DOTALL,
            ),
        )
        for selector in (
            r"\.market-decision-summary",
            r"\.decision-workbench-brief",
        ):
            self.assertRegex(
                mobile,
                re.compile(selector + r"\s*\{[^}]*grid-template-columns:\s*1fr\s*;", re.DOTALL),
            )
        self.assertRegex(
            mobile,
            re.compile(
                r"\.decision-workbench-brief\s*>\s*section\s*\{[^}]*min-height:\s*0\s*;",
                re.DOTALL,
            ),
        )

    def test_1366_prioritizes_workspace_and_compacts_market_and_conclusion(self):
        shell_start = JS.index("function buildAppShell")
        shell_end = JS.index("function getReportDataStatus", shell_start)
        shell = JS[shell_start:shell_end]
        workspace = shell.index('class="workspace today-workspace"')
        preclose = shell.index('id="precloseAdvisory"')
        supporting = shell.index('id="supportingDecisionsStack"')
        workspace_body = shell.index('class="workspace-body"')
        view_description = shell.index('id="viewDescription"')
        self.assertLess(workspace, preclose)
        self.assertLess(preclose, supporting)
        self.assertLess(workspace_body, view_description)

        market = re.search(
            r"\.market-decision-bar\s*\{(?P<body>[^}]*)\}", CSS, re.DOTALL
        )
        self.assertIsNotNone(market)
        self.assertRegex(
            market.group("body"),
            r"grid-template-columns:\s*minmax\([^;]+\)\s+minmax\([^;]+\)\s+minmax\([^;]+\)\s*;",
        )

        detail_start = JS.index("function buildMergedCandidateDetail")
        detail_end = JS.index("function renderCandidateDetail", detail_start)
        detail = JS[detail_start:detail_end]
        module_call = re.search(
            r"renderRecommendationEvidenceModule\([\s\S]*?'01',[\s\S]*?reportDate,\s*null,\s*true,\s*\)",
            detail,
        )
        self.assertIsNotNone(module_call, "primary conclusion still renders duplicate outer metadata")

    def test_primary_conclusion_keeps_action_and_data_risk_while_audit_moves_to_research(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            r"""
const section = function (extra) {
  return Object.assign({ status: 'available', as_of: '2026-09-01', source: 'fixture' }, extra || {});
};
const evidence = {
  code: '600001',
  summary: section({
    code: '600001', name: '风险股', formal_action: '观察', formal_action_reason: '等待确认',
    data_health: 'stale', data_is_final: false, data_stale: true
  }),
  decision_score: section({ score: 61, decision_code: 'observe', components: {
    structure: { score: 20, reasons: ['结构待确认'] }
  } }),
  rank_evidence: section({ view_rank: 2, opportunity_score: 88 }),
  price_evidence: section({}), daily_structure: section({}), sublevel_30m: section({}),
  volume_and_capital: section({}), market_and_sector: section({}), main_rise_clue: section({}),
  risk_and_next: section({}), historical_validation: section({})
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-09-01', recommendationEvidence: {
    schema_version: 1, report_date: '2026-09-01', views: { main: [evidence] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-09-01' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({ code: '600001', ref: { pool: 'picks_fusion', code: '600001' } }, {});
const first = html.indexOf('data-evidence-module="01"');
const chart = html.indexOf('id="chartCanvas"');
const research = html.indexOf('class="candidate-research-details"');
const price = html.indexOf('data-evidence-module="02"');
const primary = html.slice(first, chart);
const researchLayer = html.slice(research, price);
assert(primary.includes('正式动作：观察'), 'formal action is missing from the first layer');
assert(primary.includes('已陈旧') && primary.includes('非终局') && primary.includes('stale'),
  'data risk is missing from the first layer');
assert(!primary.includes('decision-score-audit') && !primary.includes('evidence-meta-details'),
  'score composition or audit still pushes the chart down');
assert(researchLayer.includes('data-evidence-module="01A"'),
  'decision score audit did not move into research details');
assert(researchLayer.includes('decision-score-audit') && researchLayer.includes('evidence-meta-details'),
  'research layer lost score composition or provenance');
""",
        )

    def test_missing_real_chart_uses_explicit_verifiable_kline_copy(self):
        self.assertIn(
            "var CHART_EMPTY_TEXT = '无法展示可验证 K 线：本期未提供真实日 K 数据；推荐原因和来源仍保留。';",
            JS,
        )

    def test_invalid_ohlc_arrays_render_explicit_empty_state(self):
        _assert_node_contract(
            self,
            "({ has: hasChartData, chart: renderChart, state: state })",
            r"""
let setOptionCalled = false;
global.window.echarts = { init: function () { return {
  setOption: function () { setOptionCalled = true; },
  dispose: function () {}, resize: function () {}
}; } };
const invalid = {
  dates: ['2026-08-31', '2026-09-01'],
  opens: [null, Infinity], highs: [null, 'bad'],
  lows: [undefined, NaN], closes: [null, false],
  volumes: [100, 120], macd_hist: [0.1, 0.2]
};
assert(globalThis.__auxTest.has(invalid) === false,
  'invalid OHLC arrays were treated as verifiable chart data');
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.chartLayerSwitcher = null;
globalThis.__auxTest.chart(invalid, {});
assert(globalThis.__auxTest.state.chartMount.innerHTML.includes('无法展示可验证 K 线'),
  'invalid OHLC arrays did not render explicit empty copy');
assert(setOptionCalled === false, 'invalid OHLC arrays reached ECharts');
""",
        )

    def test_chart_layer_switcher_uses_active_detail_scope(self):
        _assert_node_contract(
            self,
            "({ render: renderChartLayerSwitcher, state: state })",
            r"""
const hiddenDesktop = { innerHTML: '', querySelectorAll: function () { return []; } };
const activeDrawer = { innerHTML: '', querySelectorAll: function () { return []; } };
global.document.getElementById = function () { return hiddenDesktop; };
globalThis.__auxTest.state.chartLayer = 'decision';
globalThis.__auxTest.state.chartLayerSwitcher = activeDrawer;
globalThis.__auxTest.render({ chart_annotations: { markLines: [], markPoints: [] } }, {}, {});
assert(activeDrawer.innerHTML.includes('决策位'), 'active drawer switcher was not rendered');
assert(hiddenDesktop.innerHTML === '', 'hidden desktop switcher was targeted by duplicate id');
""",
        )

    def test_mobile_candidate_identity_has_no_legacy_rank_gutter(self):
        self.assertNotIn(
            "grid-template-columns: 36px minmax(0, 1fr);",
            CSS,
        )

    def test_mobile_chart_controls_wrap_into_touch_sized_rows_without_locking_page_scroll(self):
        self.assertIn(".chart-layer-status", CSS)
        self.assertIn("touch-action: pan-y", CSS)
        mobile_start = CSS.rfind("@media (max-width: 390px)")
        self.assertGreaterEqual(mobile_start, 0)
        mobile = CSS[mobile_start:]
        self.assertRegex(mobile, r"\.chart-layer-switcher[^}]*flex-wrap:\s*wrap\s*;")
        self.assertRegex(mobile, r"\.chart-layer-switcher button[^}]*min-height:\s*44px\s*;")
        self.assertRegex(mobile, r"\.chart-window-tools[^}]*border-top:")

    def test_actual_sep14_non_executable_result_uses_current_copy_and_traces_original_strategy(self):
        _assert_node_contract(
            self,
            "({ rows: decisionRows, summary: buildCandidateRowSummary, rowReason: renderCandidateRowReason, detail: buildUnifiedCandidateDetail, quick: quickComparisonDimensionValues, normalizeEvidence: normalizeCandidateEvidenceRow, state: state })",
            r"""
const t = globalThis.__auxTest;
const archivedHtml = require('zlib').gunzipSync(fs.readFileSync(
  'tests/fixtures/chanlun-c8-ma-before/page.html.gz'
)).toString('utf8');
const bootstrapMarker = 'window.CHANLUN_BOOTSTRAP = ';
const start = archivedHtml.indexOf(bootstrapMarker) + bootstrapMarker.length;
const end = archivedHtml.indexOf(';\n  window.CHANLUN_BOOTSTRAP.dataBasePrefix', start);
const bootstrap = JSON.parse(archivedHtml.slice(start, end));
const frozen = JSON.stringify(bootstrap);
window.CHANLUN_BOOTSTRAP = bootstrap;
t.state.data = bootstrap.inlineReportData;
t.state.workspace = bootstrap.inlineReportData.workspace;
t.state.currentView = 'decision_formal';
const row = t.rows(bootstrap.decisionWorkbench, 'decision_formal')
  .find(function (item) { return item.code === '603344'; });
assert(row, 'actual Sep14 星德胜 row is missing');
const value = row.workbench_item;
assert(value.page_status === 'evidence_blocked' && value.status_label === '暂无法判断'
  && value.is_executable === false && value.formal_action === '可上车'
  && value.score === 62, 'actual Sep14 F2 fields changed unexpectedly');

const summary = t.summary(row, 'decision_formal');
const rowHtml = t.rowReason(row, 'decision_formal', summary);
assert(summary.action === '暂无法判断' && summary.reason.includes('当前提示：暂无法判断'),
  'list summary is not led by the current workbench state');
assert(!summary.reason.includes('偏执行优先') && !rowHtml.includes('偏执行优先'),
  'non-executable list still presents the original execution reason as current');
assert(rowHtml.includes('缺少有效参考价') && rowHtml.includes('缺少有效失效位'),
  'list lost the concrete current blockers');

const detail = t.detail(row);
const header = (detail.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
const core = (detail.match(/<section class="decision-workbench-brief unified-short-judgment decision-brief-core"[\s\S]*?<\/section><\/section>/) || [])[0] || '';
const sources = detail.slice(detail.indexOf('来源策略与完整证据'));
assert(header.includes('当前提示：暂无法判断') && header.includes('当前不可执行'),
  'detail first layer does not state current non-executable status');
assert(!header.includes('正式动作：可上车') && !core.includes('偏执行优先'),
  'detail first layer still promotes the original strategy conclusion');
assert(core.includes('当前提示') && core.includes('暂无法判断')
  && core.includes('结构摘要：证据冲突'), 'chart-front judgment lost current state or blockers');
assert(sources.includes('原策略结论：可上车')
  && sources.includes('原策略依据：主推命中，确认与结构条件已满足，偏执行优先。'),
  'source provenance did not retain and relabel the original strategy facts');

const quick = t.quick(row);
assert(quick['身份与来源动作'].includes('当前提示：暂无法判断')
  && quick['身份与来源动作'].includes('原策略结论：'),
  'quick comparison did not separate current status from source conclusions');
assert(quick['结构依据'].includes('原策略依据：') && quick['结构依据'].includes('偏执行优先'),
  'quick comparison lost the original strategy reason provenance');
const selected = value.strategy_results.find(function (strategy) {
  return strategy.strategy_id === value.evidence_view;
}) || value.strategy_results[0];
const comparison = t.normalizeEvidence(Object.assign({}, selected.evidence, {
  __strategy_results: value.strategy_results,
  __workbench_item: value
}));
assert(comparison.actionDisplay.includes('当前提示：暂无法判断')
  && comparison.actionDisplay.includes('原策略结论：'),
  'evidence comparison did not separate current status from source conclusions');
assert(frozen === JSON.stringify(bootstrap), 'F2 render consumers mutated the actual report input');
""",
        )

    def test_unified_current_copy_preserves_ready_and_fails_closed_for_non_ready_states(self):
        _assert_node_contract(
            self,
            "({ summary: buildCandidateRowSummary, detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-14' };
t.state.data = { date: '2026-09-14' };
t.state.currentView = 'decision_formal';
function item(patch) {
  const value = Object.assign({
    code: '600001', name: '状态样本', page_status: 'formal_ready',
    status_label: '正式条件完整', formal_action: '可上车', score: 62,
    is_executable: true, primary_reason: '条件已满足，偏执行优先',
    blocking_reasons: [], contracts: {}, strategy_results: [{
      strategy_id: 'main', role: 'formal', action_semantics: 'formal',
      formal_action: '可上车', score: 62, primary_reason: '条件已满足，偏执行优先',
      contract: {}, evidence: {}
    }]
  }, patch || {});
  return { code: value.code, name: value.name, workbench_item: value };
}
const ready = item();
const readySummary = t.summary(ready, 'decision_formal');
const readyDetail = t.detail(ready);
const readyHeader = (readyDetail.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
const readyCore = (readyDetail.match(/<section class="decision-workbench-brief unified-short-judgment decision-brief-core"[\s\S]*?<\/section><\/section>/) || [])[0] || '';
assert(readySummary.reason === '条件已满足，偏执行优先',
  'formal_ready list path was downgraded');
assert(readyHeader.includes('正式动作：可上车') && readyCore.includes('条件已满足，偏执行优先'),
  'formal_ready first layer lost its current executable conclusion');

for (const sample of [
  { page_status: 'formal_incomplete', status_label: '正式待确认', is_executable: false,
    blocking_reasons: ['缺少有效参考价', '缺少有效失效位'] },
  { page_status: 'evidence_blocked', status_label: '暂无法判断', is_executable: false,
    blocking_reasons: ['日线结构：证据冲突'] },
  { page_status: 'strategy_disagreement', status_label: '正式策略分歧', is_executable: false,
    blocking_reasons: ['正式策略意见不一致'] },
  { page_status: 'unknown', status_label: '', is_executable: false,
    blocking_reasons: [] },
  { page_status: 'formal_ready', status_label: '正式条件完整', is_executable: false,
    blocking_reasons: [] }
]) {
  const blocked = item(sample);
  const summary = t.summary(blocked, 'decision_formal');
  const detail = t.detail(blocked);
  const header = (detail.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
  assert(summary.reason.includes('当前提示：') && !summary.reason.includes('条件已满足'),
    'non-ready summary exposed an executable reason: ' + sample.page_status);
  assert(header.includes('当前不可执行') && !header.includes('正式动作：可上车'),
    'non-ready detail exposed an executable action: ' + sample.page_status);
  assert(!summary.reason.includes('无风险') && !summary.reason.includes('条件齐全'),
    'unknown or conflicting state was filled as safe: ' + sample.page_status);
}
""",
        )

    def test_formal_ready_without_verified_executability_updates_every_current_status_label(self):
        _assert_node_contract(
            self,
            "({ current: getWorkbenchCurrentDecision, status: renderCandidateStatusSummary, detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-14' };
t.state.data = { date: '2026-09-14' };
t.state.currentView = 'decision_formal';
function item() {
  const value = {
    code: '600001', name: '状态样本', page_status: 'formal_ready',
    status_label: '正式条件完整', formal_action: '可上车', score: 62,
    is_executable: true, primary_reason: '条件已满足，偏执行优先',
    blocking_reasons: [], contracts: {}, strategy_results: [{
      strategy_id: 'main', role: 'formal', action_semantics: 'formal',
      formal_action: '可上车', score: 62, primary_reason: '条件已满足，偏执行优先',
      contract: {}, evidence: {}
    }]
  };
  return { code: value.code, name: value.name, workbench_item: value };
}
const ready = item();
const readyDetail = t.detail(ready);
const readyHeader = (readyDetail.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
assert(readyHeader.includes('<strong>正式条件完整</strong>')
  && t.status(ready, 'decision_formal').includes('条件：正式条件完整'),
  'verified formal_ready current labels were downgraded');

for (const mode of ['false', 'missing']) {
  const blocked = item();
  if (mode === 'false') blocked.workbench_item.is_executable = false;
  else delete blocked.workbench_item.is_executable;
  const current = t.current(blocked);
  const detail = t.detail(blocked);
  const header = (detail.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
  const sources = detail.slice(detail.indexOf('来源策略与完整证据'));
  assert(current.statusLabel === '可执行性未核验',
    mode + ' executable contract did not fail closed');
  assert(header.includes('<strong>可执行性未核验</strong>')
    && !header.includes('<strong>正式条件完整</strong>'),
    mode + ' executable contract left a stale header status');
  assert(t.status(blocked, 'decision_formal').includes('条件：可执行性未核验')
    && !t.status(blocked, 'decision_formal').includes('条件：正式条件完整'),
    mode + ' executable contract left a stale condition summary');
  assert(header.includes('决策分 62') && sources.includes('原策略结论：可上车')
    && sources.includes('原策略依据：条件已满足，偏执行优先'),
    mode + ' executable contract lost score or labeled strategy history');
}
""",
        )

    def test_outer_incident_guard_reaches_unified_core_judgment(self):
        _assert_node_contract(
            self,
            "({ current: getWorkbenchCurrentDecision, status: renderCandidateStatusSummary, detail: buildUnifiedCandidateDetail, state: state })",
            r"""
const t = globalThis.__auxTest;
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-14' };
t.state.data = { date: '2026-09-14' };
t.state.currentView = 'decision_formal';
const value = {
  code: '600001', name: '事故复盘样本', page_status: 'formal_ready',
  status_label: '正式条件完整', formal_action: '可上车', score: 62,
  is_executable: true, primary_reason: '条件已满足，偏执行优先',
  blocking_reasons: [], contracts: {}, strategy_results: [{
    strategy_id: 'main', role: 'formal', action_semantics: 'formal',
    formal_action: '可上车', score: 62, primary_reason: '条件已满足，偏执行优先',
    contract: {}, evidence: {}
  }]
};
const normal = { code: value.code, name: value.name, workbench_item: value };
const normalSources = t.detail(normal).slice(
  t.detail(normal).indexOf('来源策略与完整证据')
);
assert(normalSources.includes('data-source-score="main"')
  && normalSources.includes('决策分 62'),
  'normal formal source score disappeared');
const incident = {
  code: value.code, name: value.name, incident_review_only: true, workbench_item: value
};
const current = t.current(incident);
const detail = t.detail(incident);
const header = (detail.match(/<header class="unified-stock-head">([\s\S]*?)<\/header>/) || [])[1] || '';
const core = (detail.match(/<section class="decision-workbench-brief unified-short-judgment decision-brief-core"[\s\S]*?<\/section><\/section>/) || [])[0] || '';
const sources = detail.slice(detail.indexOf('来源策略与完整证据'));
assert(current.incident && current.statusLabel === '仅追溯',
  'formal_ready overwrote the incident current status');
assert(header.includes('<strong>仅追溯</strong>') && header.includes('当前不可执行')
  && t.status(incident, 'decision_formal').includes('条件：仅追溯'),
  'incident current status did not reach every first-layer label');
assert(core.includes('当前提示') && core.includes('仅追溯')
  && core.includes('当前不可执行') && !core.includes('偏执行优先'),
  'outer incident guard was lost by the chart-front judgment consumer');
assert(!sources.includes('data-source-score="main"')
  && sources.includes('原策略依据：条件已满足，偏执行优先'),
  'incident detail exposed an active score or lost labeled strategy history');
const innerValue = Object.assign({}, value, { incident_review_only: true });
const innerIncident = {
  code: value.code, name: value.name, workbench_item: innerValue
};
const innerDetail = t.detail(innerIncident);
const innerSources = innerDetail.slice(innerDetail.indexOf('来源策略与完整证据'));
assert(t.current(innerIncident).incident
  && !innerSources.includes('data-source-score="main"')
  && innerSources.includes('原策略依据：条件已满足，偏执行优先'),
  'inner incident detail exposed an active score or lost labeled strategy history');
""",
        )


if __name__ == "__main__":
    unittest.main()
