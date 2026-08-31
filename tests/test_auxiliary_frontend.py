"""Contract tests for the scan-first auxiliary decision cockpit."""

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = (ROOT / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
CSS = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")


def _assert_node_contract(testcase, exposure, body):
    script = r"""
const fs = require('fs');
const vm = require('vm');
global.window = { location: { pathname: '' } };
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
  + '\n globalThis.__auxTest = __EXPOSURE__;'
  + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
function assert(value, message) { if (!value) throw new Error(message); }
__BODY__
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


class TestAuxiliaryCockpitContract(unittest.TestCase):
    def test_candidate_evidence_comparison_preserves_workspace_order(self):
        _assert_node_contract(
            self,
            "({ projection: getRecommendationEvidenceProjection, rows: getEvidenceRowsForView, render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [
    { code: '301629', summary: { status: 'available', source: 'workspace', name: '矽电股份', formal_action: '观察' }, rank_evidence: { status: 'available', source: 'workspace', view_rank: 2, opportunity_score: 30 }, decision_score: { status: 'available', source: 'decision', score: 62, decision_code: 'recommend', components: {} } },
    { code: '301266', summary: { status: 'available', source: 'workspace', name: '宇邦新材', formal_action: '可上车' }, rank_evidence: { status: 'available', source: 'workspace', view_rank: 1, opportunity_score: 90 }, decision_score: { status: 'available', source: 'decision', score: 63, decision_code: 'recommend', components: {} } }
  ] }
} };
const rows = globalThis.__auxTest.rows('main');
assert(rows.map(function (row) { return row.code; }).join(',') === '301629,301266', 'workspace order was changed');
const html = globalThis.__auxTest.render('main');
assert(html.indexOf('301629') < html.indexOf('301266'), 'comparison renderer re-sorted candidates');
""",
        )

    def test_comparison_distinguishes_action_decision_and_rank_evidence(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '301629',
    summary: { status: 'available', source: 'workspace', name: '矽电股份', sector: '半导体', formal_action: '观察' },
    decision_score: { status: 'available', source: 'decision', score: 62, decision_code: 'recommend', components: { structure: { score: 10 }, position: { score: 15 }, sentiment: { score: 37 } } },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 2, opportunity_score: 30, note: '仅用于当前池内排序' },
    price_evidence: { status: 'partial', source: 'prices', current_price: 309.85, reference_price: 300 },
    display_derived: { status: 'partial', source: 'derived', distance_from_reference_pct: 3.2833 },
    daily_structure: { status: 'missing', reason: 'not provided' },
    sublevel_30m: { status: 'missing', reason: 'not provided' },
    volume_and_capital: { status: 'missing', reason: 'not provided' },
    market_and_sector: { status: 'missing', reason: 'not provided' },
    risk_and_next: { status: 'available', source: 'risk', risk_labels: ['追高风险'] },
    historical_validation: { status: 'missing', reason: 'not provided' }
  }] }
} };
const html = globalThis.__auxTest.render('main');
assert(html.includes('唯一正式动作'), 'formal action column missing');
assert(html.includes('观察'), 'formal action value missing');
assert(html.includes('决策分'), 'decision score label missing');
assert(html.includes('62'), 'decision score value missing');
assert(html.includes('结构 10') && html.includes('位置 15') && html.includes('情绪 37'), 'decision components missing');
assert(html.includes('池内排序证据'), 'rank evidence label missing');
assert(html.includes('排序分 30'), 'rank opportunity score missing');
assert(html.includes('仅用于当前池内排序'), 'rank scope boundary missing');
""",
        )

    def test_candidate_comparison_exposes_signal_freshness_and_data_status(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '301629',
    summary: { status: 'available', as_of: '2026-08-28', source: 'workspace.views.main',
      name: '矽电股份', sector: '半导体', formal_action: '观察' },
    decision_score: { status: 'available', source: 'decision', score: 62, components: {} },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 2, opportunity_score: 30 },
    daily_structure: { status: 'available', as_of: '2026-08-28', source: 'evidence-section-provenance',
      data_source: 'serialized daily candidate fields',
      signal: '二买', signal_date: '2026-08-28', signal_age_days: 0,
      latest_date: '2026-08-28', health: 'verified' },
    sublevel_30m: { status: 'missing', as_of: '2026-08-28', source: '30m', reason: 'not provided' },
    volume_and_capital: { status: 'missing', source: 'volume', reason: 'not provided' },
    market_and_sector: { status: 'missing', source: 'sector', reason: 'not provided' },
    risk_and_next: { status: 'missing', source: 'risk', risk_labels: [] },
    historical_validation: { status: 'missing', source: 'history', reason: 'not provided' }
  }] }
} };
const html = globalThis.__auxTest.render('main');
assert(html.includes('<th scope="col">信号与新鲜度</th>'),
  '桌面比较表缺少信号日期/新鲜度列');
assert(html.includes('<th scope="col">数据状态</th>'),
  '桌面比较表缺少数据状态列');
assert(html.includes('<dt>信号与新鲜度</dt>'),
  '移动候选卡缺少信号日期/新鲜度字段');
assert(html.includes('<dt>数据状态</dt>'),
  '移动候选卡缺少数据状态字段');
assert(html.includes('二买') && html.includes('2026-08-28'),
  '信号类型或信号日期没有进入候选比较');
assert(html.includes('0个交易日') || html.includes('0 个交易日') || html.includes('当日'),
  '信号年龄没有转换为新鲜度文案');
assert(html.includes('serialized daily candidate fields') && html.includes('verified'),
  '证据来源或终局数据状态没有进入候选比较');
""",
        )

    def test_candidate_comparison_has_no_sort_or_third_score(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [] }
} };
const html = globalThis.__auxTest.render('main');
assert(!html.includes('data-sort'), 'comparison exposes a browser sort control');
assert(!html.includes('<select'), 'comparison exposes a sort selector');
assert(!html.includes('综合分'), 'third composite score was introduced');
assert(!html.includes('成功概率'), 'uncalibrated success probability was introduced');
assert(html.includes('保持正式池原顺序'), 'no-order-change boundary missing');
""",
        )

    def test_candidate_comparison_mobile_tickets_and_desktop_scroll_contract(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '301629', summary: { status: 'available', source: 'workspace', name: '矽电股份' },
    decision_score: { status: 'missing', source: 'decision', score: null },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 1, opportunity_score: 30 }
  }] }
} };
const html = globalThis.__auxTest.render('main');
assert(html.includes('candidate-evidence-table-wrap'), 'desktop comparison table wrapper missing');
assert(html.includes('candidate-evidence-ticket-list'), 'mobile ticket list missing');
assert(html.includes('candidate-evidence-ticket'), 'mobile candidate ticket missing');
""",
        )
        self.assertIn(
            ".candidate-evidence-table-wrap {\n  max-width: 100%;\n  overflow-x: auto;",
            CSS,
        )
        self.assertIn(
            ".candidate-evidence-ticket-list {\n  display: none;",
            CSS,
        )
        self.assertIn(
            "@media (max-width: 760px)",
            CSS,
        )

    def test_candidate_comparison_escapes_all_evidence_text(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '301629<img src=x onerror=alert(1)>',
    summary: { status: 'available', source: 'workspace', name: '<img src=x onerror=alert(2)>', formal_action: '<script>alert(3)</script>' },
    decision_score: { status: 'missing', source: 'decision', score: null, reason: '<svg onload=alert(4)>' },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 1, opportunity_score: 30, note: '<b>rank</b>' },
    risk_and_next: { status: 'available', source: 'risk', risk_labels: ['<iframe>bad</iframe>'] }
  }] }
} };
const html = globalThis.__auxTest.render('main');
['<img', '<script', '<svg', '<iframe', '<b>rank</b>'].forEach(function (unsafe) {
  assert(!html.includes(unsafe), 'unsafe evidence text leaked: ' + unsafe);
});
assert(html.includes('&lt;img'), 'escaped evidence text missing');
""",
        )

    def test_candidate_comparison_hides_internal_risk_reason_behind_user_copy(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '301629',
    summary: { status: 'available', source: 'workspace', name: '矽电股份', formal_action: '可上车' },
    risk_and_next: {
      status: 'missing',
      source: 'workspace risk flags + declared candidate conditions',
      risk_labels: [],
      reason: 'strategy_risk_and_conditions_not_declared'
    }
  }] }
} };
const html = globalThis.__auxTest.render('main');
assert(html.includes('本期未登记可展示风险标签'), 'missing risk did not use user-facing copy');
assert(!html.includes('strategy_risk_and_conditions_not_declared'), 'internal risk audit reason leaked into comparison');
""",
        )

    def test_missing_or_mismatched_evidence_projection_fails_closed(self):
        _assert_node_contract(
            self,
            "({ projection: getRecommendationEvidenceProjection, render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
[{}, { recommendationEvidence: {} }, { recommendationEvidence: { schema_version: 1, report_date: '2026-08-27', views: { main: [{ code: 'stale' }] } } }].forEach(function (bootstrap) {
  window.CHANLUN_BOOTSTRAP = bootstrap;
  assert(globalThis.__auxTest.projection() === null, 'invalid evidence projection was accepted');
  const html = globalThis.__auxTest.render('main');
  assert(html.includes('本期未提供证据展示'), 'missing evidence did not fail closed');
  assert(!html.includes('stale'), 'mismatched-date evidence leaked');
});
""",
        )

    def test_evidence_projection_requires_canonical_date_and_page_match(self):
        _assert_node_contract(
            self,
            "({ projection: getRecommendationEvidenceProjection, state: state })",
            r"""
[
  { pageDate: '2026-02-30', reportDate: '2026-02-30' },
  { pageDate: '2026-08-27', reportDate: '2026-08-28' },
  { pageDate: '2026-8-28', reportDate: '2026-08-28' }
].forEach(function (item) {
  globalThis.__auxTest.state.data = { date: item.reportDate };
  window.CHANLUN_BOOTSTRAP = {
    pageDate: item.pageDate,
    recommendationEvidence: {
      schema_version: 1,
      report_date: item.reportDate,
      views: { main: [] }
    }
  };
  assert(globalThis.__auxTest.projection() === null,
    'invalid or cross-page evidence date was accepted');
});
""",
        )

    def test_psy12_shadow_stays_in_research_and_never_overrides_formal_temperature(self):
        _assert_node_contract(
            self,
            "{ render: renderPsy12ShadowCard, temperature: buildMarketTemperature }",
            r"""
const base = {
  date: '2026-08-26',
  market_sentiment: {
    date: '2026-08-26', score: 61, label: '偏强', version: 'v2',
    coverage: 1, insufficient: false,
    components: { breadth: 41, index: 52, limit_ecology: 63, turnover: 74, trend: 85 },
    evidence: {
      breadth: { available: true }, index: { available: true },
      limit_ecology: { available: true }, turnover: { available: true },
      trend: { available: true }
    }
  },
  psy12: {
    status: 'available', score: 50, up_days: 6, valid_days: 12, window: 12,
    start_date: '2026-08-11', end_date: '2026-08-26', daily_directions: []
  },
  psy12_shadow: {
    schema_version: 1, mode: 'shadow', affects_production: false,
    promotion_eligible: false, promotion_requires_new_authorization: true,
    status: 'available', formal_score: 61, shadow_score_with_psy12: 61,
    delta_vs_formal: 0, formal_label: '偏强', shadow_label: '偏强',
    weights: { psy12: 0.1 }
  }
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-26',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-26',
    views: {},
    market_sentiment: {
      formal_contract: {
        status: 'available',
        source: 'daily.market_sentiment',
        as_of: '2026-08-26',
        score: 61,
        label: '偏强',
        version: 'v2',
        coverage: 1,
        components: { breadth: 41, index: 52, limit_ecology: 63, turnover: 74, trend: 85 },
        evidence: {
          breadth: { available: true }, index: { available: true },
          limit_ecology: { available: true }, turnover: { available: true },
          trend: { available: true }
        }
      }
    }
  }
};
const html = globalThis.__auxTest.render(base);
assert(html.includes('PSY12 影子情绪'), 'PSY12 research card missing');
assert(html.includes('2026-08-11 至 2026-08-26'), 'PSY12 window missing');
assert(html.includes('6 / 12'), 'PSY12 up-day evidence missing');
assert(html.includes('正式分'), 'formal score missing');
assert(html.includes('影子分'), 'shadow score missing');
assert(html.includes('影子，不影响正式决策'), 'shadow boundary missing');
const temperature = globalThis.__auxTest.temperature(Object.assign({}, base, {
  psy12_shadow: Object.assign({}, base.psy12_shadow, {
    shadow_score_with_psy12: 5, shadow_label: '冰点'
  })
}));
assert(temperature.score === 61, 'shadow score replaced formal temperature');
assert(temperature.label === '偏强', 'shadow label replaced formal label');
""",
        )

    def test_psy12_shadow_fail_closed_and_label_difference_are_explicit(self):
        _assert_node_contract(
            self,
            "({ render: renderPsy12ShadowCard })",
            r"""
const insufficient = globalThis.__auxTest.render({
  psy12: { status: 'unavailable', reason: 'insufficient_history', valid_days: 8, window: 12 },
  psy12_shadow: {
    schema_version: 1, mode: 'shadow', affects_production: false,
    promotion_eligible: false, promotion_requires_new_authorization: true,
    status: 'unavailable', shadow_score_with_psy12: null,
    weights: { psy12: 0.1 }
  }
});
assert(insufficient.includes('PSY12 数据不足'), 'insufficient state hidden');
assert(!insufficient.includes('影子分</span><strong>0'), 'missing shadow score rendered as zero');

const changed = globalThis.__auxTest.render({
  psy12: {
    status: 'available', score: 75, up_days: 9, valid_days: 12, window: 12,
    start_date: '2026-08-11', end_date: '2026-08-26'
  },
  psy12_shadow: {
    schema_version: 1, mode: 'shadow', affects_production: false,
    promotion_eligible: false, promotion_requires_new_authorization: true,
    status: 'available', formal_score: 59, shadow_score_with_psy12: 62,
    delta_vs_formal: 3, formal_label: '平衡', shadow_label: '偏强',
    weights: { psy12: 0.1 }
  }
});
assert(changed.includes('正式标签 平衡'), 'formal label missing in divergence');
assert(changed.includes('影子标签 偏强'), 'shadow label missing in divergence');
assert(changed.includes('差异只用于研究验证'), 'label divergence boundary missing');

const escalated = globalThis.__auxTest.render({
  psy12: { status: 'available', score: 75, valid_days: 12, window: 12 },
  psy12_shadow: {
    schema_version: 1, mode: 'shadow', affects_production: true,
    status: 'available', shadow_score_with_psy12: 99
  }
});
assert(escalated.includes('PSY12 影子合同不可用'), 'production escalation did not fail closed');
assert(!escalated.includes('影子分</span><strong>99'), 'unsafe shadow score leaked');
""",
        )

    def test_main_recommendation_empty_state_hides_internal_reason_in_all_fail_closed_states(self):
        _assert_node_contract(
            self,
            "{ empty: buildCandidateEmptyState }",
            r"""
[
  { state: 'verified_empty', reason: '正式规则正常空池' },
  { state: 'unavailable', reason: '数据不可用 reason_code=formal_input_unavailable' },
  { state: 'disabled', reason: '正式动作已封闭 fail-close' }
].forEach(function (availability) {
  const html = globalThis.__auxTest.empty('main', availability, { filtered: false });
  assert(html.includes('本期未选出推荐票'), 'main empty state changed with internal reason');
  ['数据不可用', '正式动作已封闭', 'fail-close', 'reason_code', 'formal_input_unavailable'].forEach(function (term) {
    assert(!html.includes(term), 'main empty state leaked internal term: ' + term);
  });
});
const filtered = globalThis.__auxTest.empty('main', { state: 'available' }, {
  filtered: true, filterLabel: '工业金属', resultCount: 0
});
assert(filtered.includes('工业金属'), 'filtered zero state hid the active sector');
assert(!filtered.includes('本期未选出推荐票'), 'filtered zero result pretended to be a global empty recommendation');
""",
        )

    def test_main_recommendation_empty_state_is_one_full_width_message(self):
        _assert_node_contract(
            self,
            "{ empty: buildCandidateEmptyState }",
            r"""
const html = globalThis.__auxTest.empty('main', { state: 'verified_empty' }, { filtered: false });
assert(html === '<div class="candidate-empty is-verified-empty"><strong>本期未选出推荐票</strong></div>',
  'main empty state contains duplicate explanatory copy');
""",
        )
        self.assertIn(
            ".today-workspace .workspace-body.is-unified-empty {\n  grid-template-columns: minmax(0, 1fr);",
            CSS,
        )
        self.assertIn(
            ".today-workspace .workspace-body.is-unified-empty .workspace-detail {\n  display: none;",
            CSS,
        )
        self.assertIn(".today-workspace {\n  width: 100%;", CSS)

    def test_primary_workbench_shell_defaults_to_today_and_removes_top10(self):
        _assert_node_contract(
            self,
            "{ build: buildAppShell, state: state }",
            r"""
const app = {
  innerHTML: '',
  querySelector: function () { return null; }
};
global.document.getElementById = function (id) { return id === 'app' ? app : null; };
globalThis.__auxTest.build();
assert(globalThis.__auxTest.state.primaryMode === 'today', 'today decision is not the default primary view');
assert(app.innerHTML.includes('class="primary-mode-tabs"'), 'primary mode navigation missing');
assert(app.innerHTML.includes('data-primary-mode="today"'), 'today decision entry missing');
assert(app.innerHTML.includes('data-primary-mode="research"'), 'research validation entry missing');
assert(app.innerHTML.includes('id="todayDecisionView"'), 'today decision view missing');
assert(app.innerHTML.includes('id="researchValidationView"'), 'research validation view missing');
assert(app.innerHTML.includes('id="sectorStrip"'), 'sector strip missing from the first screen');
assert(app.innerHTML.includes('id="precloseAdvisory"'), 'pre-close advisory missing from today decision');
assert(app.innerHTML.includes('id="precloseReconciliation"'), 'post-close reconciliation missing from same advisory block');
assert(app.innerHTML.includes('class="candidate-list"'), 'candidate list missing from the first screen');
assert(!app.innerHTML.includes('id="top10Widget"'), 'temporary Top10 widget still occupies the default page');
""",
        )

    def test_primary_mode_switch_resizes_chart_after_hidden_research_view_is_revealed(self):
        _assert_node_contract(
            self,
            "{ render: renderPrimaryMode, state: state, nodes: nodes }",
            r"""
let sentimentResizeCalls = 0;
let todayHidden = false;
let researchHidden = true;
global.window.requestAnimationFrame = function (callback) { callback(); };
globalThis.__auxTest.nodes.todayDecisionView = {
  classList: { toggle: function (_name, hidden) { todayHidden = hidden; } }
};
globalThis.__auxTest.nodes.researchValidationView = {
  classList: { toggle: function (_name, hidden) { researchHidden = hidden; } }
};
const buttons = ['today', 'research'].map(function (mode) {
  return {
    getAttribute: function () { return mode; },
    classList: { toggle: function () {} },
    setAttribute: function () {}
  };
});
globalThis.__auxTest.nodes.primaryTabs = {
  querySelectorAll: function () { return buttons; }
};
globalThis.__auxTest.state.primaryMode = 'research';
globalThis.__auxTest.state.sentimentChartInstance = {
  resize: function () { sentimentResizeCalls += 1; }
};
globalThis.__auxTest.render();
assert(todayHidden === true, 'today view stayed visible');
assert(researchHidden === false, 'research view stayed hidden');
assert(sentimentResizeCalls === 1, 'research chart was not resized after reveal');
""",
        )

    def test_candidate_row_tags_are_bounded_and_keep_formal_action(self):
        _assert_node_contract(
            self,
            "{ tags: selectCandidateRowTags, state: state }",
            r"""
globalThis.__auxTest.state.data = {
  date: '2026-08-28',
  selection_input_health: {
    schema_version: 2,
    by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
  }
};
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28',
  views: { main: [{ code: '600001', summary: {
    formal_action: '可上车', applicable_horizon_status: 'missing'
  } }] }
} };
const tags = globalThis.__auxTest.tags({
  code: '600001',
  action: '可上车', effective_action: '可上车', action_semantics: 'formal',
  is_formal_recommendation: true,
  source_labels: ['正式主推', '日线共振', '30分钟确认'],
  resonance_label: '多周期共振',
  risk_flags: ['追高风险', '量能不足'],
  intended_horizon: 'T+3'
}, 'main');
assert(Array.isArray(tags), 'candidate tag selector did not return a list');
assert(tags.length <= 2, 'candidate row rendered more than two tags');
assert(tags.some(function (tag) { return tag.text.includes('可上车'); }), 'formal action was removed from candidate row');
""",
        )

    def test_candidate_row_horizon_uses_only_formal_evidence_summary(self):
        _assert_node_contract(
            self,
            "({ tags: selectCandidateRowTags, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [
    { code: '600001', summary: {
      applicable_horizon: 5,
      applicable_horizon_text: 'T+5',
      applicable_horizon_status: 'available'
    } },
    { code: '600002', summary: {
      applicable_horizon: null,
      applicable_horizon_text: '策略周期证据冲突',
      applicable_horizon_status: 'conflict'
    } }
  ] }
} };
const formalTags = globalThis.__auxTest.tags({
  code: '600001', action: '可上车', intended_horizon: 'T+3'
}, 'main');
assert(formalTags.some(function (tag) { return tag.text === 'T+5'; }), 'formal horizon was not rendered');
assert(!formalTags.some(function (tag) { return tag.text === 'T+3'; }), 'raw horizon overrode formal evidence');
const conflictTags = globalThis.__auxTest.tags({
  code: '600002', action: '观察', intended_horizon: 'T+3'
}, 'main');
assert(conflictTags.some(function (tag) { return tag.text === '周期证据冲突'; }), 'horizon conflict was hidden');
assert(!conflictTags.some(function (tag) { return tag.text === 'T+3'; }), 'conflicting raw horizon leaked');
""",
        )

    def test_candidate_row_action_uses_only_formal_evidence_summary(self):
        _assert_node_contract(
            self,
            "({ tags: selectCandidateRowTags, state: state })",
            r"""
globalThis.__auxTest.state.data = {
  date: '2026-08-28',
  selection_input_health: {
    schema_version: 2,
    by_strategy: {
      daily_fusion: { status: 'verified', formal_actions_allowed: true }
    }
  }
};
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{ code: '600001', summary: {
    formal_action: '观察',
    applicable_horizon_status: 'missing'
  } }] }
} };
const tags = globalThis.__auxTest.tags({
  code: '600001',
  page_action: '可上车',
  effective_action: '可上车',
  action: '可上车',
  action_semantics: 'formal'
}, 'main');
assert(tags.some(function (tag) { return tag.text === '正式动作：观察'; }), 'formal evidence action was not rendered');
assert(!tags.some(function (tag) { return tag.text.includes('可上车'); }), 'raw action overrode formal evidence');
""",
        )

    def test_candidate_row_uses_public_reason_projection_without_leaking_internal_reason_fields(self):
        _assert_node_contract(
            self,
            "({ tags: selectCandidateRowTags, chip: makeChip, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{ code: '600001', summary: {
    formal_action: '可上车',
    formal_action_reason: '正式结构确认<script>alert(0)</script>',
    applicable_horizon_status: 'missing'
  } }] }
} };
const item = {
  code: '600001',
  action: '可上车',
  action_reason: 'strategy_risk_and_conditions_not_declared',
  primary_reason: 'decision_score_not_provided',
  page_action_reason: '候选页公开理由不应覆盖正式证据',
  source_labels: ['正式主推']
};
const tags = globalThis.__auxTest.tags(item, 'main');
assert(tags.length === 2, 'candidate row did not keep the compact two-tag contract');
assert(tags[1].text === '正式结构确认<script>alert(0)</script>', 'public formal action reason was not preferred');
const html = globalThis.__auxTest.chip(tags[1].text, 'source-chip');
assert(html.includes('&lt;script&gt;'), 'candidate reason was not HTML escaped');
assert(!html.includes('<script>'), 'candidate reason leaked executable markup');
assert(!html.includes('strategy_risk_and_conditions_not_declared'), 'internal action reason leaked into the row');
assert(!html.includes('decision_score_not_provided'), 'internal primary reason leaked into the row');
""",
        )

    def test_candidate_row_uses_page_reason_when_formal_projection_reason_is_missing(self):
        _assert_node_contract(
            self,
            "({ tags: selectCandidateRowTags, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{ code: '600002', summary: {
    formal_action: '观察',
    applicable_horizon_status: 'missing'
  } }] }
} };
const tags = globalThis.__auxTest.tags({
  code: '600002',
  page_action_reason: '页面公开说明：等待下一确认',
  action_reason: 'formal_action_not_declared',
  primary_reason: 'internal_reason_code'
}, 'main');
assert(tags.some(function (tag) { return tag.text === '页面公开说明：等待下一确认'; }),
  'page-facing reason was not used when the formal projection reason was absent');
assert(!tags.some(function (tag) { return tag.text.includes('internal_reason_code'); }),
  'internal primary reason leaked when page-facing reason was available');
""",
        )

    def test_candidate_row_meta_separates_price_from_identity(self):
        start = JS.index("function renderCandidateList")
        end = JS.index("function buildDecisionHeader", start)
        renderer = JS[start:end]
        self.assertIn('class="candidate-row-meta"', renderer)
        self.assertLess(
            renderer.index('class="candidate-row-meta"'),
            renderer.index('candidate-price'),
        )
        desktop_start = CSS.index(".candidate-row {")
        desktop_end = CSS.index(".candidate-row:hover", desktop_start)
        desktop_rules = CSS[desktop_start:desktop_end]
        self.assertIn("grid-template-columns: minmax(0, 1fr);", desktop_rules)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto;", desktop_rules)
        self.assertNotIn("84px", desktop_rules)
        self.assertNotIn("76px", desktop_rules)
        self.assertIn(".candidate-row-meta {", CSS)

    def test_decision_header_has_one_formal_action_and_omits_missing_contract_fields(self):
        _assert_node_contract(
            self,
            "{ header: buildDecisionHeader }",
            r"""
const html = globalThis.__auxTest.header({
  code: '600001', name: '测试股', sector: '工业金属',
  formal_decision_contract: { action: '观察', reference_price: 10.5 },
  strategy_stances: [
    { strategy: 'H4 T+3', stance: 'support', action: '买入' },
    { strategy: 'AI', stance: 'oppose', action: '卖出' }
  ]
});
assert((html.match(/formal-action/g) || []).length === 1, 'detail rendered more than one formal action');
assert(html.includes('观察'), 'formal fusion action missing');
assert(!html.includes('买入') && !html.includes('卖出'), 'strategy opinion replaced the formal action');
assert(!html.includes('position_band') && !html.includes('仓位'), 'missing position contract rendered a fake value');
assert(!html.includes('intended_horizon') && !html.includes('周期'), 'missing horizon contract rendered a fake value');
assert(!html.includes('pressure_price') && !html.includes('压力位'), 'missing pressure contract rendered a fake value');
""",
        )

    def test_decision_header_uses_formal_contract_instead_of_raw_strategy_fields(self):
        _assert_node_contract(
            self,
            "{ header: buildDecisionHeader }",
            r"""
const html = globalThis.__auxTest.header({
  code: '600001', name: '测试股', sector: '工业金属',
  intended_horizon: 'T+9', position_band: '90%-100%', pressure_price: 99,
  stop_loss: 1.23,
  formal_decision_contract: {
    action: '观察', intended_horizon: 'T+3', position_band: '10%-30%',
    reference_price: 10.5, invalidation_price: 9.2, pressure_price: 12
  }
}, {
  intended_horizon: 'T+7', position_band: '70%-80%', pressure_price: 77
});
assert(html.includes('正式动作：观察'), 'formal action missing');
assert(html.includes('T+3') && !html.includes('T+9') && !html.includes('T+7'), 'raw horizon overrode contract');
assert(html.includes('10%-30%') && !html.includes('90%-100%') && !html.includes('70%-80%'), 'raw position overrode contract');
assert(html.includes('9.20') && !html.includes('1.23'), 'raw stop loss overrode contract invalidation');
assert(html.includes('12.00') && !html.includes('99.00') && !html.includes('77.00'), 'raw pressure overrode contract');
""",
        )

    def test_strategy_opinions_are_stances_and_ai_cannot_change_formal_action(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyStances }",
            r"""
const html = globalThis.__auxTest.render({
  strategy_stances: [
    { strategy: 'H4 T+3', stance: 'support', action: '买入', reason: '结构支持' },
    { strategy: '加速池', stance: 'reserve', action: '追涨', reason: '位置偏高' },
    { strategy: '罗姐池', stance: 'oppose', action: '卖出', reason: '周期冲突' },
    { strategy: 'AI', stance: 'insufficient_sample', action: '目标价20', reason: '证据不足' }
  ],
  ai_research: { summary: '存在情绪风险', action: '清仓', target_price: 20 }
});
['支持', '保留', '反对', '样本不足'].forEach(function (label) {
  assert(html.includes(label), 'normalized stance missing: ' + label);
});
['买入', '追涨', '卖出', '目标价20', '清仓'].forEach(function (action) {
  assert(!html.includes(action), 'strategy or AI action leaked into the formal decision: ' + action);
});
assert(html.includes('不改变正式动作'), 'AI research boundary is not explicit');
""",
        )

    def test_strategy_disagreement_is_summary_first_and_detailed_only_in_research(self):
        _assert_node_contract(
            self,
            "{ summary: buildStrategyDisagreementSummary, audit: renderStrategyDisagreementAudit }",
            r"""
const item = {
  code: '600001', name: '测试股',
  strategy_stances: [
    { strategy: 'H4 T+3', stance: 'support', reason: 'H4结构支持', intended_horizon: 'T+3', version: 'h4-v1', evidence_refs: ['contrib:h4'] },
    { strategy: '罗姐池', stance: 'oppose', reason: '周期冲突', intended_horizon: 'T+5', version: 'luojie-v2', evidence_refs: ['contrib:luojie'] }
  ],
  strategy_disagreement_summary: { counts: { support: 1, reserve: 0, oppose: 1, insufficient_sample: 0 } },
  ai_research: { assessment: 'risk_notice', summary: '短周期回撤风险', evidence_refs: ['ai:risk'] }
};
const summary = globalThis.__auxTest.summary(item);
assert(summary.includes('策略分歧') && summary.includes('1 支持') && summary.includes('1 反对'), 'first-screen disagreement count missing');
['H4结构支持', '周期冲突', 'h4-v1', 'contrib:h4'].forEach(function (detail) {
  assert(!summary.includes(detail), 'first-screen summary leaked drill-down detail: ' + detail);
});
const audit = globalThis.__auxTest.audit({ workspace: { views: { main: [item] } } });
['H4结构支持', '周期冲突', 'T+3', 'T+5', 'h4-v1', 'luojie-v2', 'contrib:h4', 'contrib:luojie'].forEach(function (detail) {
  assert(audit.includes(detail), 'research audit dropped strategy detail: ' + detail);
});
assert(audit.includes('短周期回撤风险') && audit.includes('不改变正式动作'), 'AI boundary missing from research audit');
""",
        )

    def test_merged_candidate_detail_uses_evidence_modules_chart_and_audit_layers(self):
        _assert_node_contract(
            self,
            "{ build: buildMergedCandidateDetail, state: state }",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '600001',
    summary: { status: 'available', as_of: '2026-08-28', source: 'summary', code: '600001', name: '测试股', sector: '工业金属', formal_action: '观察' },
    decision_score: { status: 'missing', source: 'decision', score: null },
    rank_evidence: { status: 'missing', source: 'rank', view_rank: null, opportunity_score: null },
    price_evidence: { status: 'partial', source: 'price', reference_price: 10.5, trailing_targets: [] },
    daily_structure: { status: 'missing', source: 'daily' },
    sublevel_30m: { status: 'missing', source: '30m' },
    volume_and_capital: { status: 'missing', source: 'volume' },
    market_and_sector: { status: 'missing', source: 'market' },
    risk_and_next: { status: 'available', source: 'risk', risk_labels: ['追高风险'], next_confirmation: { items: ['放量', '站稳压力', '板块增强', '多余条件'] }, cancel_conditions: { items: ['跌破失效位'] } },
    historical_validation: { status: 'missing', source: 'history' },
    display_derived: { status: 'missing', source: 'derived' }
  }] }
} };
const html = globalThis.__auxTest.build({
  code: '600001', name: '测试股', sector: '工业金属',
  formal_decision_contract: { action: '观察', reference_price: 10.5 }
}, {});
assert((html.match(/formal-action/g) || []).length === 1, 'merged detail duplicated the formal action');
assert(html.includes('class="chart-panel"'), 'K-line workspace missing');
assert((html.match(/data-evidence-module=/g) || []).length === 8, 'eight evidence modules missing');
assert(html.includes('下一确认') && html.includes('取消或降级'), 'risk and next-step semantics incomplete');
assert(html.includes('class="evidence-audit-drawer"'), 'evidence and audit drawer missing');
""",
        )

    def test_price_label_collision_keeps_all_real_values_and_kinds_without_two_lane_truncation(self):
        _assert_node_contract(
            self,
            "{ select: selectPersistentPriceLabels, format: formatPersistentPriceLabel }",
            r"""
const priceLabels = [
  { kind: 'target', value: 11.6, label: '目标 T+5' },
  { kind: 'pressure', value: 10.8, label: '压力位' },
  { kind: 'reference', value: 10.01, label: '参考价' },
  { kind: 'current', value: 10.05, label: '现价' },
  { kind: 'invalidation', value: 9.2, label: '失效位' }
];
const before = JSON.stringify(priceLabels);
const selected = globalThis.__auxTest.select(priceLabels);
assert(selected.length === 5, 'collision governance removed a real price line');
assert(selected[0].kind === 'invalidation', 'invalidation did not win label priority');
assert(selected[1].kind === 'current', 'current price did not win the close-price merge');
assert(selected[1].merged === true, 'prices within 0.6% were not merged');
assert(selected[1].value === 10.05, 'merged lane changed the primary true y value');
assert(selected[2].kind === 'reference' && selected[2].value === 10.01, 'merged lane removed the secondary real y line');
assert(selected[1].labelVisible === true && selected[2].labelVisible === false, 'collision governance did not merge only the right-side label lane');
const visible = selected.filter(function (item) { return item.labelVisible !== false; });
assert(visible.length <= 2, 'persistent chart labels exceeded the two-label visible budget');
assert(visible.some(function (item) { return item.kind === 'invalidation'; })
  && visible.some(function (item) { return item.kind === 'current'; }),
  'persistent label priority did not retain invalidation and current price');
assert(selected[1].labelEntries.some(function (entry) { return entry.kind === 'current' && entry.value === 10.05; })
  && selected[1].labelEntries.some(function (entry) { return entry.kind === 'reference' && entry.value === 10.01; }), 'merged lane lost true source label values');
assert(selected[3].kind === 'pressure' && selected[4].kind === 'target', 'non-colliding pressure or target lane was dropped');
const retainedValues = selected.reduce(function (all, item) { return all.concat(item.values); }, []).sort(function (a, b) { return a - b; });
const retainedKinds = selected.reduce(function (all, item) { return all.concat(item.kinds); }, []).sort();
assert(JSON.stringify(retainedValues) === JSON.stringify([9.2, 10.01, 10.05, 10.8, 11.6]), 'collision governance lost a real source price');
assert(JSON.stringify(retainedKinds) === JSON.stringify(['current', 'invalidation', 'pressure', 'reference', 'target']), 'collision governance lost a source price kind');
const mergedText = globalThis.__auxTest.format(selected[1]);
assert(mergedText.includes('10.05') && mergedText.includes('10.01'), 'merged right-lane label hid one of the true prices');
assert(JSON.stringify(priceLabels) === before, 'price label selection mutated source evidence');
""",
        )

    def test_price_display_renders_real_boundary_derivatives(self):
        _assert_node_contract(
            self,
            "{ render: renderRecommendationPriceEvidence }",
            r"""
const html = globalThis.__auxTest.render({
  price_evidence: {
    status: 'available',
    current_price: 10,
    reference_price: 9,
    pressure_price: 12,
    invalidation_price: 8,
    trailing_targets: []
  },
  display_derived: {
    status: 'available',
    distance_from_reference_pct: 11.1111,
    upside_to_pressure_pct: 20,
    downside_to_invalidation_pct: 20,
    risk_reward_ratio: 1
  }
});
assert(html.includes('上行空间 20%'), 'real upside-to-pressure distance was not rendered');
assert(html.includes('下行空间 20%'), 'real downside-to-invalidation distance was not rendered');
assert(html.includes('展示风险收益比 1'), 'real display risk/reward ratio was not rendered');
""",
        )

    def test_price_display_hides_stale_or_status_inconsistent_derived_values(self):
        _assert_node_contract(
            self,
            "{ render: renderRecommendationPriceEvidence }",
            r"""
const html = globalThis.__auxTest.render({
  price_evidence: {
    status: 'missing',
    current_price: 10,
    reference_price: 9,
    pressure_price: null,
    invalidation_price: null,
    trailing_targets: []
  },
  display_derived: {
    status: 'available',
    distance_from_reference_pct: 999,
    upside_to_pressure_pct: 99,
    downside_to_invalidation_pct: 88,
    risk_reward_ratio: 4,
    distance_state: '伪造状态'
  }
});
assert(!html.includes('距参考价 999%'), 'stale distance was rendered despite missing price status');
assert(!html.includes('上行空间 99%') && !html.includes('下行空间 88%'),
  'derived boundaries were rendered without matching price evidence');
assert(!html.includes('展示风险收益比 4'), 'risk/reward was rendered from an inconsistent payload');
assert(!html.includes('伪造状态'), 'distance state was rendered without a validated distance');

const mismatch = globalThis.__auxTest.render({
  price_evidence: {
    status: 'available', current_price: 10, reference_price: 9,
    pressure_price: 12, invalidation_price: 8, trailing_targets: []
  },
  display_derived: {
    status: 'available', distance_from_reference_pct: 999,
    upside_to_pressure_pct: 20, downside_to_invalidation_pct: 20,
    risk_reward_ratio: 1
  }
});
assert(!mismatch.includes('距参考价 999%'), 'mismatched distance was rendered');
assert(!mismatch.includes('上行空间 20%') && !mismatch.includes('下行空间 20%')
  && !mismatch.includes('展示风险收益比 1'),
  'available derived block was partially rendered after a boundary mismatch');
""",
        )

    def test_price_display_uses_existing_distance_state_without_inventing_thresholds(self):
        _assert_node_contract(
            self,
            "{ render: renderRecommendationPriceEvidence }",
            r"""
const withState = globalThis.__auxTest.render({
  price_evidence: { status: 'partial', current_price: 10, reference_price: 9 },
  display_derived: { status: 'partial', distance_from_reference_pct: 11.1111, distance_state: '偏离' }
});
assert(withState.includes('距参考价 11.11% · 偏离'),
  'an existing distance state was not displayed alongside its percentage');
const withoutState = globalThis.__auxTest.render({
  price_evidence: { status: 'partial', current_price: 10, reference_price: 9 },
  display_derived: { status: 'partial', distance_from_reference_pct: 11.1111 }
});
assert(withoutState.includes('距参考价 11.11%')
  && !withoutState.includes('接近')
  && !withoutState.includes('适中')
  && !withoutState.includes('偏离'),
  'distance display invented a strategy threshold when no state was provided');
""",
        )

    def test_sublevel_display_renders_satisfied_and_missing_confirmation_items(self):
        _assert_node_contract(
            self,
            "{ render: renderSublevelEvidence }",
            r"""
const html = globalThis.__auxTest.render({
  status: 'available',
  summary: '30分钟确认',
  confirmation_status: 'confirmed',
  confirmations: ['EMA5重新站上', '突破位保持'],
  confirmed_by: '30m confirmation contract v1',
  missing_evidence: ['MACD柱体连续性未提供']
});
assert(html.includes('已满足确认项'), 'satisfied confirmation heading was not rendered');
assert(html.includes('EMA5重新站上') && html.includes('突破位保持'),
  'satisfied confirmation items were not rendered');
assert(html.includes('确认依据') && html.includes('30m confirmation contract v1'),
  'confirmed_by provenance was not rendered');
assert(html.includes('缺失证据') && html.includes('MACD柱体连续性未提供'),
  'missing confirmation evidence was not rendered');
""",
        )

    def test_volume_display_renders_current_amount_with_date_and_source(self):
        _assert_node_contract(
            self,
            "{ render: renderVolumeCapitalEvidence }",
            r"""
const html = globalThis.__auxTest.render({
  status: 'partial',
  current_amount: 250000000,
  current_amount_text: '2.5亿',
  current_amount_as_of: '2026-08-28',
  current_amount_source: 'daily_kline.amounts',
  current_amount_source_label: '日K成交额序列'
});
assert(html.includes('当日成交额') && html.includes('2.5亿'),
  'current turnover amount was not rendered');
assert(html.includes('2026-08-28') && html.includes('日K成交额序列'),
  'current turnover amount provenance was not rendered');
""",
        )

    def test_decision_price_layer_includes_every_real_trailing_target(self):
        _assert_node_contract(
            self,
            "{ chart: renderChart, state: state }",
            r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.isMobile = false;
globalThis.__auxTest.state.chartLayer = 'decision';
globalThis.__auxTest.state.currentView = 'main';
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '600001',
    summary: { status: 'available', source: 'workspace', code: '600001' },
    price_evidence: {
      status: 'available', source: 'price_evidence',
      current_price: 11.7, reference_price: 11.2,
      invalidation_price: 10.4, pressure_price: 12.0,
      trailing_targets: [
        { price: 12.4, label: 'T+1', source: 'trailing_targets[0]' },
        { price: 13.8, label: 'T+3', source: 'trailing_targets[1]' },
        { price: 15.2, label: 'T+5', source: 'trailing_targets[2]' }
      ]
    },
    display_derived: { status: 'available', source: 'derived', chart_evidence: {
      status: 'available', source: 'chart metadata',
      macd: { status: 'available' },
      prices: {
        status: 'available', source: 'price_evidence',
        available: ['current_price', 'reference_price', 'invalidation_price', 'pressure_price', 'trailing_targets']
      }
    } }
  }] }
} };
const raw = {
  dates: ['2026-08-26', '2026-08-27', '2026-08-28'],
  opens: [10.8, 11.0, 11.4], highs: [11.2, 11.6, 12.0],
  lows: [10.4, 10.7, 11.1], closes: [11.0, 11.4, 11.7],
  volumes: [100, 120, 180], macd_hist: [-0.1, 0.1, 0.2],
  chart_annotations: {
    markLines: [
      { name: 'source price', yAxis: 11.2 },
      { name: 'source price duplicate', yAxis: 11.2 },
      { name: 'current close stale', yAxis: 99.0 },
      { name: 'pressure stale', yAxis: 88.0 }
    ],
    markPoints: [], labels: []
  }
};
globalThis.__auxTest.chart(raw, {
  code: '600001', current_price: 11.7,
  formal_decision_contract: {
    action: '观察', reference_price: 11.2,
    invalidation_price: 10.4, pressure_price: 12.0
  }
});
const decisionLines = chartOption.series[0].markLine.data;
const references = decisionLines.filter(function (line) { return line.kind === 'reference'; });
const currents = decisionLines.filter(function (line) { return line.kind === 'current'; });
const pressures = decisionLines.filter(function (line) { return line.kind === 'pressure'; });
assert(references.length === 1 && references[0].yAxis === 11.2, 'raw duplicate was not deduped against canonical reference evidence');
assert(currents.length === 1 && currents[0].yAxis === 11.7, 'stale raw current price was mixed with canonical evidence');
assert(pressures.length === 1 && pressures[0].yAxis === 12.0, 'stale raw pressure was mixed with canonical evidence');
const targets = decisionLines.filter(function (line) { return line.kind === 'target'; });
assert(targets.length === 3, 'decision price layer omitted one or more real trailing targets');
assert(JSON.stringify(targets.map(function (line) { return line.yAxis; })) === JSON.stringify([12.4, 13.8, 15.2]), 'decision price layer changed or reordered trailing target prices');
assert(targets.map(function (line) { return line.name; }).join(',').includes('T+1')
  && targets.map(function (line) { return line.name; }).join(',').includes('T+3')
  && targets.map(function (line) { return line.name; }).join(',').includes('T+5'), 'decision price layer lost trailing target labels');
""",
        )

    def test_trailing_target_display_declares_bounded_overflow(self):
        _assert_node_contract(
            self,
            "{ render: renderRecommendationPriceEvidence }",
            r"""
const html = globalThis.__auxTest.render({
  price_evidence: {
    current_price: 10.2,
    trailing_targets: [
      { price: 11.0, label: 'T+1' },
      { price: 12.0, label: 'T+3' }
    ],
    trailing_targets_contract: {
      max_visible: 5,
      input_count: 7,
      valid_count: 7,
      visible_count: 5,
      omitted_count: 2,
      truncated: true,
      reason: 'display_payload_limit'
    }
  },
  display_derived: {}
});
assert(html.includes('另有 2 个目标未展开'), 'bounded trailing-target overflow was hidden from the user');
assert(html.includes('展示上限 5'), 'trailing-target display bound was not declared');
""",
        )

    def test_decision_price_kinds_have_distinct_non_color_line_and_symbol_contracts(self):
        _assert_node_contract(
            self,
            "{ chart: renderChart, state: state }",
            r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.isMobile = false;
globalThis.__auxTest.state.chartLayer = 'decision';
globalThis.__auxTest.state.currentView = 'main';
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '600001',
    summary: { status: 'available', source: 'workspace', code: '600001' },
    price_evidence: {
      status: 'available', source: 'price_evidence',
      reference_price: 10.0, invalidation_price: 8.0, pressure_price: 12.0,
      trailing_targets: [{ price: 14.0, label: 'T+3', source: 'trailing_targets[0]' }]
    },
    display_derived: { status: 'available', source: 'derived', chart_evidence: {
      status: 'available', source: 'chart metadata',
      macd: { status: 'available' },
      prices: {
        status: 'available', source: 'price_evidence',
        available: ['reference_price', 'invalidation_price', 'pressure_price', 'trailing_targets']
      }
    } }
  }] }
} };
globalThis.__auxTest.chart({
  dates: ['2026-08-26', '2026-08-27', '2026-08-28'],
  opens: [9.0, 9.4, 9.8], highs: [9.5, 10.0, 10.5],
  lows: [8.7, 9.1, 9.5], closes: [9.4, 9.8, 10.2],
  volumes: [100, 120, 180], macd_hist: [-0.1, 0.1, 0.2],
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
}, {
  code: '600001',
  formal_decision_contract: {
    action: '观察', reference_price: 10.0,
    invalidation_price: 8.0, pressure_price: 12.0
  }
});
const lines = chartOption.series[0].markLine.data;
const requiredKinds = ['reference', 'invalidation', 'pressure', 'target'];
const signatures = requiredKinds.map(function (kind) {
  const line = lines.filter(function (candidate) { return candidate.kind === kind; })[0];
  assert(line, 'decision price layer did not preserve kind contract: ' + kind);
  assert(line.lineStyle && typeof line.lineStyle.type === 'string' && line.lineStyle.type, 'lineType contract missing: ' + kind);
  const symbol = Array.isArray(line.symbol) ? line.symbol.join('/') : String(line.symbol || '');
  assert(symbol, 'symbol contract missing: ' + kind);
  return line.lineStyle.type + '|' + symbol;
});
assert(new Set(signatures).size === requiredKinds.length, 'reference/invalidation/pressure/target are distinguishable only by color');
""",
        )

    def test_historical_chart_actions_keep_only_latest_text_and_layer_entries_are_data_driven(self):
        _assert_node_contract(
            self,
            "{ marks: selectChartActionMarkers, short: shortChartSignalLabel, layers: getAvailableChartLayers }",
            r"""
const rawMarks = [
  { coord: ['2026-08-21', 10], barIndex: 3, name: '底背驰候选', symbolSize: 18 },
  { coord: ['2026-08-27', 11], barIndex: 8, name: '启动日', symbolSize: 18 },
  { coord: ['2026-08-28', 12], barIndex: 9, name: '趋势延续候选', symbolSize: 18 },
  { coord: ['', 13], barIndex: 10, name: '无日期' },
  { coord: ['2026-08-29', 'not-a-price'], barIndex: 11, name: '无价格' }
];
const before = JSON.stringify(rawMarks);
const marks = globalThis.__auxTest.marks(rawMarks, 40);
const visible = marks.filter(function (item) { return item.label && item.label.show; });
assert(marks.length === 3, 'invalid action coordinates were not filtered');
assert(visible.length === 1, 'price plot must keep exactly one latest short label');
assert(visible[0].name === '趋势延续候选', 'latest action did not win label priority');
assert(visible[0].label.formatter === '趋势', 'latest action did not use the short real-type label');
assert(marks[0].label.show === false, 'historical action still carries permanent text');
assert(marks[0].symbolSize < visible[0].symbolSize, 'historical marker was not visually reduced');
assert(JSON.stringify(rawMarks) === before, 'action marker selection mutated source evidence');
assert(globalThis.__auxTest.short('底背驰候选') === '底背驰', 'bottom-divergence mapping missing');
assert(globalThis.__auxTest.short('swing底背驰候选种子') === '底背驰', 'swing bottom-divergence mapping missing');
assert(globalThis.__auxTest.short('启动日') === '启动', 'startup mapping missing');
assert(globalThis.__auxTest.short('30分钟结构确认') === '确认', 'confirmation mapping missing');
assert(globalThis.__auxTest.short('非常非常长的未知信号名称') === '非常非常长的…', 'unknown signal did not retain a bounded truthful name');
assert(visible.length <= 3, 'more than three permanent labels were emitted in a 40-bar window');
const layers = globalThis.__auxTest.layers({
  chart_annotations: { markPoints: [{ coord: [1, 10] }] },
  ema5: [1, 2], ema20: [1, 2]
});
assert(layers.includes('decision') && layers.includes('trend'), 'available chart layers missing');
assert(!layers.includes('structure'), 'structure switch appeared without structure evidence');
""",
        )

    def test_chart_renders_volume_macd_and_defaults_to_latest_twenty_bars(self):
        _assert_node_contract(
            self,
            "{ chart: renderChart, state: state }",
            r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
const dates = Array.from({ length: 50 }, function (_, index) {
  return 'D' + String(index + 1).padStart(2, '0');
});
const opens = dates.map(function (_, index) { return 10 + index / 10; });
const closes = opens.map(function (value, index) { return value + (index % 2 === 0 ? 0.2 : -0.2); });
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.isMobile = false;
globalThis.__auxTest.chart({
  dates: dates,
  opens: opens,
  highs: opens.map(function (value) { return value + 0.4; }),
  lows: opens.map(function (value) { return value - 0.4; }),
  closes: closes,
  volumes: dates.slice(1).map(function (_, index) { return 1000 + index; }),
  macd_hist: dates.map(function (_, index) { return index % 2 === 0 ? 1 : -1; }),
  chart_annotations: { markPoints: [], markLines: [] }
}, {});
assert(chartOption.grid.length === 3, 'chart does not have three synchronized panels');
assert(chartOption.xAxis.length === 3 && chartOption.yAxis.length === 3, 'three-axis contract missing');
assert(chartOption.yAxis[1].name === '成交量', 'volume panel label missing');
assert(chartOption.yAxis[2].name === 'MACD', 'MACD panel label missing');
assert(chartOption.yAxis[1].axisLabel.show === false, 'volume scale labels still collide in the compact panel');
assert(chartOption.yAxis[2].axisLabel.show === false, 'MACD scale labels still collide in the compact panel');
const names = chartOption.series.map(function (series) { return series.name; });
assert(names.includes('K线') && names.includes('成交量') && names.includes('MACD'), 'price/volume/MACD series incomplete');
const volume = chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(volume.data.length === 50 && volume.data[0] === null, 'short volume series was not tail-aligned with null evidence');
assert(volume.itemStyle.color({ dataIndex: 0 }) === '#94a3b8', 'missing volume was colored like real evidence');
assert(volume.itemStyle.color({ dataIndex: 1 }) === '#10B981', 'down-volume bar is not A-share green');
assert(volume.itemStyle.color({ dataIndex: 2 }) === '#EF4444', 'up-volume bar is not A-share red');
chartOption.dataZoom.forEach(function (zoom) {
  assert(JSON.stringify(zoom.xAxisIndex) === JSON.stringify([0, 1, 2]), 'data zoom does not control all panels');
  assert(zoom.startValue === 'D31' && zoom.endValue === 'D50', 'default window is not the latest 20 bars');
});
""",
        )

    def test_chart_moves_action_text_into_annotation_lane(self):
        self.assertIn('id="chartAnnotationLane"', JS)
        _assert_node_contract(
            self,
            "{ lane: renderChartAnnotationLane, model: buildChartSignalLaneModel, marks: selectChartActionMarkers, state: state }",
            r"""
let hidden = null;
globalThis.__auxTest.state.chartAnnotationLane = {
  innerHTML: '',
  classList: { toggle: function (_name, value) { hidden = value; } }
};
const marks = globalThis.__auxTest.marks([
  { coord: ['2026-08-20', 9], barIndex: 1, name: '第四条旧信号' },
  { coord: ['2026-08-21', 10], barIndex: 2, name: '底背驰候选' },
  { coord: ['2026-08-27', 11], barIndex: 8, name: '启动日' },
  { coord: ['2026-08-28', 12], barIndex: 9, name: '趋势延续候选' }
], 50);
const extras = ['确认日: 2026-08-28', '接近20日低点；接近swing参考价', '<img src=x onerror=alert(1)>'];
const model = globalThis.__auxTest.model(marks, extras);
assert(model.signals.length === 3, 'signal lane did not cap actions at three');
assert(model.signals.map(function (item) { return item.date; }).join(',') === '2026-08-28,2026-08-27,2026-08-21', 'signal lane is not newest-first');
globalThis.__auxTest.lane(marks, extras);
const html = globalThis.__auxTest.state.chartAnnotationLane.innerHTML;
assert((html.match(/class="chart-signal-item/g) || []).length === 3, 'signal lane rendered more or fewer than three actions');
assert(html.includes('趋势延续候选') && html.includes('2026-08-28'), 'latest full signal evidence missing from lane');
assert(html.includes('底背驰候选') && html.includes('2026-08-21'), 'historical bottom-divergence evidence missing from lane');
assert(html.includes('>趋势<') && html.includes('>底背驰<'), 'signal lane short types missing');
assert(!html.includes('第四条旧信号'), 'fourth historical action escaped the lane cap');
assert(html.includes('确认日: 2026-08-28'), 'confirmation-day annotation missing');
assert(html.includes('接近20日低点；接近swing参考价'), 'seed reason annotation missing');
assert(!html.includes('<img src=x onerror=alert(1)>') && html.includes('&lt;img'), 'annotation text was not escaped');
assert(hidden === false, 'lane hidden despite action evidence');
globalThis.__auxTest.lane([], []);
assert(hidden === true && globalThis.__auxTest.state.chartAnnotationLane.innerHTML === '', 'empty action lane left stale content');
""",
        )
        self.assertIn(".chart-signal-list {", CSS)
        self.assertIn(".chart-signal-item {", CSS)
        self.assertIn("overflow-wrap: anywhere", CSS)

    def test_chart_uses_a_responsive_right_label_lane(self):
        start = JS.index("function renderChart")
        end = JS.index("function renderStatusBadge", start)
        renderer = JS[start:end]
        self.assertIn("selectPersistentPriceLabels", renderer)
        self.assertIn("selectChartActionMarkers", renderer)
        self.assertIn("getAvailableChartLayers", renderer)
        self.assertIn("left: state.isMobile ? '10%' : '6%'", renderer)
        self.assertIn("right: state.isMobile ? '96px' : '124px'", renderer)
        self.assertIn("决策位", JS)
        self.assertIn("结构", JS)
        self.assertIn("趋势", JS)
        self.assertIn("formatPersistentPriceLabel", renderer)
        self.assertIn("renderChartAnnotationLane", renderer)

    def test_chart_renders_structure_lines_and_signal_tooltips(self):
        _assert_node_contract(
            self,
            "{ chart: renderChart, structure: selectStructureChartLines, state: state }",
            r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.isMobile = false;
const raw = {
  dates: ['2026-08-26', '2026-08-27', '2026-08-28'],
  opens: [10.8, 11, 11.4], highs: [11.2, 11.6, 12],
  lows: [10.4, 10.7, 11.1], closes: [11, 11.4, 11.7],
  volumes: [100, 120, 180], macd_hist: [-0.1, 0.1, 0.2],
  chart_annotations: {
    markLines: [
      { name: 'ZG', yAxis: 12.4 },
      { name: 'ZD', yAxis: 10.8 },
      { name: 'source', yAxis: 11.2 },
      { name: '现价', yAxis: 11.7 },
      { name: 'ZG', yAxis: 'not-a-number' }
    ],
    markPoints: [{ name: '底背驰候选<img src=x onerror=alert(1)>', coord: ['2026-08-28', 11.7] }],
    labels: []
  }
};
const structure = globalThis.__auxTest.structure(raw.chart_annotations.markLines);
assert(structure.length === 2, 'structure selector admitted non-ZG/ZD or invalid y values');
assert(structure[0].name === 'ZG' && structure[0].yAxis === 12.4, 'ZG true y value changed');
assert(structure[1].name === 'ZD' && structure[1].yAxis === 10.8, 'ZD true y value changed');

globalThis.__auxTest.state.chartLayer = 'decision';
globalThis.__auxTest.chart(raw, {});
let lineNames = chartOption.series[0].markLine.data.map(function (line) { return line.name; });
assert(lineNames.includes('现价'), 'decision layer lost its persistent price evidence');
assert(!lineNames.includes('ZG') && !lineNames.includes('ZD'), 'structure lines leaked into decision layer');
const action = chartOption.series[0].markPoint.data[0];
const tooltip = action.tooltip.formatter();
assert(tooltip.includes('底背驰候选') && tooltip.includes('2026-08-28') && tooltip.includes('11.70'), 'signal tooltip lost full name/date/price');
assert(!tooltip.includes('<img src=x onerror=alert(1)>') && tooltip.includes('&lt;img'), 'signal tooltip did not escape its full name');

globalThis.__auxTest.state.chartLayer = 'structure';
globalThis.__auxTest.chart(raw, {});
lineNames = chartOption.series[0].markLine.data.map(function (line) { return line.name; });
assert(lineNames.join(',') === 'ZG,ZD', 'structure layer did not exclusively render ZG/ZD');
assert(chartOption.series[0].markLine.data[0].yAxis === 12.4, 'structure layer changed the real ZG coordinate');
assert(!lineNames.includes('现价') && !lineNames.includes('参考价'), 'decision price labels leaked into structure layer');
""",
        )

    def test_three_panel_chart_has_explicit_desktop_and_mobile_heights(self):
        desktop_start = CSS.index(".chart-canvas {")
        desktop_end = CSS.index("}", desktop_start)
        desktop_rule = CSS[desktop_start:desktop_end]
        self.assertIn("height: 380px", desktop_rule)
        mobile_start = CSS.rindex("@media (max-width: 760px)")
        mobile_rules = CSS[mobile_start:]
        self.assertRegex(
            mobile_rules,
            r"\.chart-canvas\s*\{[^}]*\bheight:\s*360px",
        )
        self.assertIn(".candidate-row-meta {", mobile_rules)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", mobile_rules)

    def test_today_and_research_stacks_have_distinct_semantic_ownership(self):
        _assert_node_contract(
            self,
            "{ build: buildAuxiliaryStacks }",
            r"""
const stacks = globalThis.__auxTest.build({ diagnostics: {} });
['decision-directions-card', 'personal-watchlist-card', 'holding-risk-card'].forEach(function (className) {
  assert(stacks.today.includes(className), 'today decision stack missing ' + className);
  assert(!stacks.research.includes(className), 'today-only module leaked into research: ' + className);
});
['market-temperature-card', 'strategy-scorecards-card', 'shadow-card', 'diagnostics-card'].forEach(function (className) {
  assert(stacks.research.includes(className), 'research validation stack missing ' + className);
  assert(!stacks.today.includes(className), 'research-only module leaked into today decision: ' + className);
});
assert(stacks.research.includes('sector-flow-card') && stacks.research.includes('limit-up-ecology-card'), 'market evidence details incomplete');
""",
        )

    def test_normal_diagnostics_are_collapsed_and_auxiliary_stacks_are_vertical(self):
        start = JS.index("function renderDiagnosticsCard")
        end = JS.index("function bindSingleOpenDetailsWithin", start)
        diagnostics = JS[start:end]
        self.assertIn('class="diagnostics-details"', diagnostics)
        self.assertNotIn('class="diagnostics-details" open', diagnostics)
        self.assertIn(".supporting-decisions-stack", CSS)
        self.assertIn(".research-validation-stack", CSS)
        self.assertNotIn(
            ".aux-grid.decision-grid {\n  grid-template-columns: repeat(4, minmax(0, 1fr));",
            CSS,
        )

    def test_comparison_summary_inserts_into_the_research_layer_parent(self):
        start = JS.index("function initComparisonSummary")
        end = JS.index("function renderComparisonSummaryResults", start)
        renderer = JS[start:end]
        self.assertIn("auxCenter.parentNode.insertBefore(section, auxCenter)", renderer)
        self.assertNotIn("nodes.shell.insertBefore(section, auxCenter || null)", renderer)

    def test_historical_reconstruction_is_visibly_non_actionable(self):
        _assert_node_contract(
            self,
            "{ render: renderHistoricalReconstruction }",
            r"""
const mount = { innerHTML: '', className: '' };
const html = globalThis.__auxTest.render({ historical_reconstruction: {
  report_date: '2026-08-26', acquired_at: '2026-08-27T12:00:00+08:00',
  input: { latest_ts: '2026-08-26 15:00:00', status: 'verified' },
  original_publication: { main_count: 0, affected_candidate_count: 1 },
  candidates: [{
    code: '300697', name: '电工合金', reference_close: 16.03,
    confirmations: ['30min EMA5维持'], confirm_date: '2026-08-26 15:00:00',
    review_reason: '仅用于复盘', is_formal_recommendation: false,
    scorecard_eligible: false
  }]
}}, mount);
assert(html.includes('历史数据修复复盘'), 'repair overlay heading missing');
assert(html.includes('不属于正式主推'), 'formal-history boundary missing');
assert(html.includes('评分不生效'), 'scorecard boundary missing');
assert(html.includes('原始日报保持不变：当日正式推荐 0 只'), 'original count hidden');
assert(html.includes('本次受影响候选 1 只因分钟数据未核验而封闭'), 'incident cause hidden');
assert(html.includes('电工合金'), 'reconstructed candidate hidden');
assert(html.includes('2026-08-26 15:00:00'), 'verified close timestamp hidden');
assert(!html.includes('可上车'), 'historical review leaked an executable action');
""",
        )

    def test_reject_decision_is_never_colored_as_recommendation(self):
        _assert_node_contract(
            self,
            "{ tone: getDecisionTone, badge: renderDecisionBadge }",
            r"""
const rejected = { decision: '不推荐', decision_code: 'reject', total_score: -5 };
assert(globalThis.__auxTest.tone(rejected) === 'is-reject', 'reject matched recommendation substring');
const html = globalThis.__auxTest.badge(rejected);
assert(html.includes('规则判定：不推荐'), 'scoring decision hierarchy is missing');
assert(!html.includes('页面动作'), 'scoring badge pretended to be the page action');
""",
        )

    def test_non_formal_tabs_cannot_leak_an_actionable_main_label(self):
        _assert_node_contract(
            self,
            "{ action: resolvePageAction, state: state }",
            r"""
assert(globalThis.__auxTest.action({
  action: '可上车', effective_action: '可上车', action_semantics: 'watch_only',
  is_formal_recommendation: false
}) === '仅观察', 'watch-only tab leaked actionable label');
assert(globalThis.__auxTest.action({
  action: '可上车', action_semantics: 'upstream_only', is_formal_recommendation: false
}) === '仅作为上游候选', 'shared upstream pretended to be a page action');
globalThis.__auxTest.state.data = {
  date: '2026-08-28',
  selection_input_health: {
    schema_version: 2,
    by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
  }
};
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28',
  views: { main: [{ code: '600001', summary: { formal_action: '可上车' } }] }
} };
assert(globalThis.__auxTest.action({
  code: '600001',
  action: '可上车', effective_action: '可上车', action_semantics: 'formal',
  is_formal_recommendation: true
}, 'main') === '可上车', 'verified formal action was suppressed');
globalThis.__auxTest.state.data = {};
assert(globalThis.__auxTest.action({
  action: '可上车', effective_action: '可上车', action_semantics: 'formal',
  is_formal_recommendation: true
}, 'main') === '本期未选出推荐票', 'missing formal health failed open');
globalThis.__auxTest.state.data = { selection_input_health: {
  schema_version: 2,
  by_strategy: { h4_t3: { status: 'unavailable', formal_actions_allowed: false } }
} };
assert(globalThis.__auxTest.action({ action: '可上车', action_semantics: 'formal' }, 'h4_t3')
  === '本期未选出推荐票', 'blocked H4 action failed open');
assert(globalThis.__auxTest.action({
  action: '可上车', effective_action: '可上车'
}, 'luojie') === '仅观察', 'legacy research tab leaked an actionable label');
assert(globalThis.__auxTest.action({ action: '可上车' }, 'baseline')
  === '仅作为上游候选', 'legacy shared upstream leaked an action');
""",
        )

    def test_formal_source_label_keeps_formal_visual_priority(self):
        _assert_node_contract(
            self,
            "{ sourceClass: getSourceClass }",
            r"""
assert(globalThis.__auxTest.sourceClass('正式主推').includes('tag-main'), 'formal source was styled like a baseline');
assert(globalThis.__auxTest.sourceClass('融合候选').includes('tag-fusion'), 'fusion source lacked its research identity');
""",
        )

    def test_watchlist_reuses_verified_risk_semantics(self):
        _assert_node_contract(
            self,
            "{ render: renderWatchDirectionAnalysis }",
            r"""
const verified = globalThis.__auxTest.render([{
  theme: '测试风险', direction: 'negative', stage: 'risk',
  risk_reasons: [{ detail: '订单撤销', verification_status: 'verified' }]
}], {});
assert(verified.includes('>风险<'), 'verified risk was still marked pending');
assert(!verified.includes('风险待核实'), 'verified risk was downgraded');
assert(verified.includes('订单撤销'), 'watchlist hid the concrete verified risk reason');
assert(verified.includes('风险升级条件'), 'watchlist used a generic label for risk escalation');
assert(verified.includes('风险解除条件'), 'watchlist used a generic label for risk resolution');
const pending = globalThis.__auxTest.render([{
  theme: '测试风险', direction: 'negative', stage: 'risk',
  risk_reasons: [{
    detail: '模型传闻 <img src=x onerror=alert(1)>',
    verification_status: 'model_extracted', evidence_refs: ['event:watch-risk']
  }]
}], {});
assert(pending.includes('风险待核实'), 'model-only risk was overstated');
assert(pending.includes('模型提取待核实'), 'watchlist hid model-only provenance');
assert(pending.includes('event:watch-risk'), 'watchlist hid the risk evidence reference');
assert(!pending.includes('<img src=x onerror=alert(1)>'), 'watchlist risk reason was not escaped');
""",
        )

    def test_watchlist_reuses_explicit_direction_condition_contract(self):
        _assert_node_contract(
            self,
            "{ render: renderWatchDirectionAnalysis }",
            r"""
const html = globalThis.__auxTest.render([{
  theme: '光模块', direction: 'negative', stage: 'risk',
  risk_reasons: [{ detail: '风险证据成立', verification_status: 'verified' }],
  confirmation_conditions: ['显式风险升级条件'],
  invalidation_conditions: ['显式风险解除条件'],
  next_trigger: ['遗留确认字段不应出现'],
  invalidation: ['遗留失效字段不应出现']
}], {});
assert(html.includes('显式风险升级条件'), 'watchlist ignored explicit confirmation contract');
assert(html.includes('显式风险解除条件'), 'watchlist ignored explicit invalidation contract');
assert(!html.includes('遗留确认字段不应出现'), 'watchlist leaked legacy confirmation');
assert(!html.includes('遗留失效字段不应出现'), 'watchlist leaked legacy invalidation');
""",
        )

    def test_watchlist_direction_discloses_associated_stocks_and_roles(self):
        _assert_node_contract(
            self,
            "{ render: renderWatchDirectionAnalysis }",
            r"""
const html = globalThis.__auxTest.render([{
  theme: '光模块', direction: 'positive', stage: 'confirmed',
  stock_links: [
    { code: '300308', name: '中际旭创', role: 'leader' },
    { code: '300502', name: '新易盛', role: 'beneficiary' }
  ]
}], {});
assert(html.includes('关联个股'), 'associated-stock heading missing');
assert(html.includes('中际旭创 300308'), 'associated stock identity missing');
assert(html.includes('方向龙头'), 'leader role was not translated');
assert(html.includes('受益关联'), 'beneficiary role was not translated');
""",
        )

    def test_missing_market_and_score_values_never_render_as_zero(self):
        _assert_node_contract(
            self,
            "{ top10: renderTop10Result, summary: buildMarketSummary, regime: renderMarketRegime, nodes: nodes }",
            r"""
const mount = { innerHTML: '' };
globalThis.__auxTest.nodes.top10Result = mount;
globalThis.__auxTest.top10({ items: [{ code: '000001', name: '测试' }] }, 'done');
assert(mount.innerHTML.includes('top10-cell score">--<'), 'missing score became zero');
const summary = globalThis.__auxTest.summary({ 沪深300: { close: 4000, change_pct: null } });
const regime = globalThis.__auxTest.regime(summary);
assert(regime.includes('主要指数涨跌数据缺失'), 'missing index changes became 0/0');
assert(!regime.includes('>0/1<'), 'missing index changes were counted as flat/down');
""",
        )

    def test_sector_flow_empty_state_has_a_provenance_contract(self):
        _assert_node_contract(
            self,
            "{ render: renderSectorFlowCard }",
            r"""
const unavailable = globalThis.__auxTest.render({});
assert(unavailable.includes('证据不足'), 'missing sector source looked like an empty result');
const verifiedEmpty = globalThis.__auxTest.render({
  sector_flow: [], sector_outflow: [], data_quality: { sector_source: 'eastmoney' }
});
assert(verifiedEmpty.includes('确认空池'), 'trusted empty sector result was ambiguous');
""",
        )

    def test_sector_flow_preserves_real_zero_and_discloses_unknown_hierarchy(self):
        _assert_node_contract(
            self,
            "{ render: renderSectorFlowCard }",
            r"""
const html = globalThis.__auxTest.render({
  sector_flow: [{ name: '零流量板块', flow: 0, net_flow: 99 }],
  sector_outflow: [{ name: '已去重板块', amount: -12, hierarchy_dedup_status: 'deduped_representative' }],
  data_quality: { sector_source: 'eastmoney' }
});
assert(html.includes('>0.00<'), 'real zero was replaced by a fallback field');
assert(!html.includes('>99.00<'), 'fallback field overrode explicit zero');
assert(html.includes('层级状态未记录'), 'unknown hierarchy was mislabeled as deduped');
assert(!html.includes('资金流入与流出方向 · 层级已去重'), 'mixed hierarchy overstated deduplication');
""",
        )

    def test_verified_sector_heat_upgrades_funding_mainline_without_composite_score(self):
        _assert_node_contract(
            self,
            "{ model: buildFundingMainlineModel, render: renderFundingMainline }",
            r"""
const missing = globalThis.__auxTest.model({});
const missingHtml = globalThis.__auxTest.render(missing, '');
assert(missing.title === '资金主线', 'P0 sector title changed to an unsupported hot-sector claim');
assert(missingHtml.includes('资金主线'), 'funding mainline title missing');
assert(!missingHtml.includes('今日无热点'), 'missing facts were presented as a verified no-hotspot result');
const model = globalThis.__auxTest.model({
  sector_flow: [{ name: ' 工业金属 ', flow: 12 }],
  sector_outflow: [{ sector: '白酒', flow: -8 }],
  sector_heat: {
    status: 'verified_complete',
    as_of: '2026-08-27T15:10:00+08:00',
    source: 'eastmoney_sector_flow+verified_daily_close',
    items: [{
      sector_code: 'BK0099', sector_name: 'AI算力', change_pct: 3.21, rank: 1,
      sector_refs: ['600001', '600002'],
      up_count: 42, total_count: 51, limit_up_count: 6,
      net_flow: 1200000000, net_flow_text: '12.00亿', status: 'verified_complete'
    }]
  },
  data_quality: { sector_source: 'eastmoney' }
});
assert(model.title === '热门板块', 'verified sector heat did not upgrade the title');
assert(model.items.length === 1 && model.items[0].name === 'AI算力', 'sector heat was not authoritative');
assert(model.items[0].sectorCode === 'BK0099' && model.items[0].sectorRefs.join(',') === '600001,600002', 'exact sector mapping was dropped');
const html = globalThis.__auxTest.render(model, '');
assert(html.includes('+3.21%'), 'sector change is missing');
assert(html.includes('涨 42/51'), 'sector breadth is missing');
assert(html.includes('涨停 6'), 'sector limit-up count is missing');
assert(html.includes('12.00亿'), 'sector net flow is missing');
assert(!html.includes('热度分'), 'an unexplained composite heat score was rendered');
const partial = globalThis.__auxTest.model({
  sector_flow: [{ name: '工业金属', flow: 12 }], sector_outflow: [],
  sector_heat: { status: 'verified_partial', items: [{ sector_name: 'AI算力' }] },
  data_quality: { sector_source: 'eastmoney' }
});
assert(partial.title === '资金主线', 'partial breadth masqueraded as verified hot sectors');
assert(partial.items[0].name === '工业金属', 'funding fallback disappeared for partial heat');
""",
        )

    def test_sector_filter_is_exact_reversible_and_preserves_candidate_contracts(self):
        _assert_node_contract(
            self,
            "{ normalize: normalizeSectorName, filter: filterCandidatesBySector }",
            r"""
const rows = [
  { code: '600001', sector: ' 工业金属 ', action: '可上车', source_pool: 'picks_fusion' },
  { code: '600002', sector: '工业金属加工', action: '观察', source_pool: 'picks_fusion' },
  { code: '600003', sector: '白酒', action: '仅观察', source_pool: 'observation_watchlist' }
];
assert(globalThis.__auxTest.normalize('  工业 金属  ') === '工业 金属', 'sector normalization is not deterministic');
const filtered = globalThis.__auxTest.filter(rows, '工业金属');
assert(filtered.length === 1 && filtered[0].code === '600001', 'sector filter used fuzzy containment instead of exact matching');
assert(filtered[0] === rows[0], 'filter cloned or rewrote the candidate contract');
assert(filtered[0].action === '可上车' && filtered[0].source_pool === 'picks_fusion', 'filter changed action or pool identity');
const restored = globalThis.__auxTest.filter(rows, '');
assert(restored.length === rows.length, 'clearing the sector filter did not restore the current pool');
assert(restored[0] === rows[0], 'clearing the filter changed candidate identity');
assert(globalThis.__auxTest.filter(rows, '不存在板块').length === 0, 'zero-result filter backfilled candidates');
""",
        )

    def test_verified_heat_filter_uses_exact_sector_code_and_sector_refs(self):
        _assert_node_contract(
            self,
            "{ filter: filterCandidatesBySector }",
            r"""
const rows = [
  { code: '600001', sector: 'AI算力', sector_code: 'BK0098' },
  { code: '600002', sector: '通信设备', sector_code: 'BK0099' },
  { code: '600003', sector: '光模块', sector_refs: [{ sector_code: 'BK0099' }] },
  { code: '600004', sector: '服务器', sector_refs: ['BK0099'] },
  { code: '600005', sector: 'AI算力加工', sector_code: 'BK0100' }
];
const filtered = globalThis.__auxTest.filter(rows, 'AI算力', 'BK0099');
assert(filtered.map((row) => row.code).join(',') === '600002,600003,600004', 'heat filter did not use exact sector_code/sector_refs');
assert(!filtered.some((row) => row.code === '600001'), 'same Chinese sector name bypassed a conflicting sector code');
assert(!filtered.some((row) => row.code === '600005'), 'fuzzy Chinese containment bypassed the exact code contract');
const byRefs = globalThis.__auxTest.filter(rows, 'AI算力', 'BK0099', ['600001', '600005']);
assert(byRefs.map((row) => row.code).join(',') === '600001,600005', 'declared sector_refs did not map exact candidate codes');
""",
        )

    def test_view_meta_exposes_source_action_and_distinct_availability_tones(self):
        _assert_node_contract(
            self,
            "{ availability: getViewAvailabilityMeta, source: getViewSourcePoolLabel, action: getViewActionSemanticsLabel, pageAction: getViewPageActionLabel }",
            r"""
assert(globalThis.__auxTest.availability({ state: 'available' }).tone === 'positive', 'available tone wrong');
assert(globalThis.__auxTest.availability({ state: 'disabled' }).tone === 'neutral', 'disabled tone wrong');
assert(globalThis.__auxTest.availability({ state: 'partial' }).tone === 'warning', 'partial tone wrong');
assert(globalThis.__auxTest.availability({ state: 'unavailable' }).tone === 'danger', 'unavailable tone wrong');
assert(globalThis.__auxTest.source('picks_pure').includes('共同上游'), 'source pool was not translated');
assert(globalThis.__auxTest.action('watch_only') === '页面只能观察', 'watch-only semantics hidden');
assert(globalThis.__auxTest.pageAction('formal', { state: 'unavailable' }) === '本期未选出推荐票', 'unavailable formal view still advertised actions');
assert(globalThis.__auxTest.pageAction('formal', { state: 'available' }) === '页面可显示策略动作', 'available formal action semantics changed');
assert(globalThis.__auxTest.pageAction('watch_only', { state: 'unavailable' }) === '页面只能观察', 'watch-only semantics should not be rewritten');
""",
        )

    def test_legacy_workspace_meta_uses_view_key_fallback_contract(self):
        _assert_node_contract(
            self,
            "{ contract: resolveViewDisplayContract }",
            r"""
const main = globalThis.__auxTest.contract('main', { label: '正式主推' });
assert(main.role === 'formal', 'legacy main lost formal role');
assert(main.source_pool === 'picks_fusion', 'legacy main source fallback missing');
assert(main.action_semantics === 'formal', 'legacy main action fallback missing');
const baseline = globalThis.__auxTest.contract('baseline', {});
assert(baseline.role === 'baseline', 'legacy baseline role missing');
assert(baseline.source_pool === 'picks_pure', 'legacy baseline source missing');
assert(baseline.action_semantics === 'upstream_only', 'legacy baseline action missing');
const research = globalThis.__auxTest.contract('luojie', {});
assert(research.role === 'research', 'legacy research role missing');
assert(research.action_semantics === 'watch_only', 'legacy research action missing');
""",
        )

    def test_action_source_and_risk_tones_share_explicit_mappings(self):
        _assert_node_contract(
            self,
            "{ action: getActionPillClass, source: getSourceClass, risk: getRiskClass }",
            r"""
assert(globalThis.__auxTest.action('等回踩').includes('is-wait'), 'wait action looked executable');
assert(globalThis.__auxTest.action('盯盘').includes('is-watch'), 'watch action looked executable');
assert(globalThis.__auxTest.source('融合候选').includes('tag-fusion'), 'fusion candidate looked like baseline');
assert(globalThis.__auxTest.risk('数据不足').includes('is-data'), 'data risk lacked a data tone');
assert(globalThis.__auxTest.risk('待核实风险').includes('is-pending'), 'pending risk looked confirmed');
assert(globalThis.__auxTest.risk('破位风险').includes('is-danger'), 'confirmed trading risk lacked danger tone');
""",
        )

    def test_direction_tones_follow_a_share_market_color_semantics(self):
        _assert_node_contract(
            self,
            "{ meta: getDirectionMeta }",
            r"""
assert(globalThis.__auxTest.meta('positive', 'confirmed', false, false).tone === 'up',
  'bullish direction did not use the A-share up tone');
assert(globalThis.__auxTest.meta('negative', 'risk', true, true).tone === 'down',
  'verified risk direction did not use the A-share down tone');
assert(globalThis.__auxTest.meta('negative', 'risk', true, false).tone === 'warning',
  'unverified risk lost its pending warning tone');
""",
        )
        self.assertIn(".status-badge.is-up", CSS)
        self.assertIn("color: var(--up-red);", CSS)
        self.assertIn(".status-badge.is-down", CSS)
        self.assertIn("color: var(--down-green);", CSS)

    def test_direction_quick_summary_carries_market_tone_classes(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionQuickSummary, nodes: nodes }",
            r"""
const mount = { innerHTML: '', querySelector: function () { return null; } };
globalThis.__auxTest.nodes.directionQuick = mount;
globalThis.__auxTest.render({ decision_brief: { theses: [
  { theme: '算力', direction: 'positive', stage: 'confirmed', risk_reasons: [] },
  { theme: '高位股', direction: 'negative', stage: 'risk', risk_reasons: [
    { detail: '跌破支撑', verification_status: 'verified' }
  ] }
] } });
assert(mount.innerHTML.includes('<span class="is-up">'), 'bullish quick direction lacked the up class');
assert(mount.innerHTML.includes('<span class="is-down">'), 'risk quick direction lacked the down class');
""",
        )

    def test_watchlist_reload_requires_discard_confirmation_when_dirty(self):
        _assert_node_contract(
            self,
            "{ confirmDiscard: confirmDiscardWatchlistChanges, state: state }",
            r"""
globalThis.__auxTest.state.watchlistManager.dirty = true;
let prompted = 0;
window.confirm = function () { prompted += 1; return false; };
assert(globalThis.__auxTest.confirmDiscard() === false, 'dirty edits were discarded');
assert(prompted === 1, 'discard confirmation missing');
window.confirm = function () { return true; };
assert(globalThis.__auxTest.confirmDiscard() === true, 'confirmed reload was blocked');
""",
        )

    def test_workspace_empty_state_distinguishes_verified_empty_and_disabled(self):
        _assert_node_contract(
            self,
            "{ empty: getViewAvailabilityMessage }",
            r"""
const verified = globalThis.__auxTest.empty({ availability: {
  state: 'verified_empty', reason: '今日没有候选通过全部门槛'
} });
assert(verified.title === '正常空选', 'verified empty was not explicit');
assert(verified.detail.includes('全部门槛'), 'verified empty reason hidden');
const disabled = globalThis.__auxTest.empty({ availability: {
  state: 'disabled', reason: '上证涨幅未超过1%'
} });
assert(disabled.title === '今日未启用', 'disabled pool mislabeled as empty');
const unavailable = globalThis.__auxTest.empty({ availability: {
  state: 'unavailable', reason: '上游生成失败'
} });
assert(unavailable.title === '本期证据不足', 'unavailable pool mislabeled as empty');
""",
        )

    def test_workspace_tabs_keep_compact_counts_without_internal_state_copy(self):
        start = JS.index("function buildWorkspaceTabButton")
        end = JS.index("function renderViewDescription", start)
        renderer = JS[start:end]
        self.assertNotIn("workspace-tab-status", renderer)
        self.assertNotIn("getViewPageActionLabel", renderer)
        self.assertIn("workspace-tab-count", renderer)
        self.assertIn("aria-label", renderer)

    def test_missing_formal_health_hides_legacy_formal_rows(self):
        _assert_node_contract(
            self,
            "{ views: getCandidateViews, state: state }",
            r"""
globalThis.__auxTest.state.data = {};
globalThis.__auxTest.state.workspace = {
    views: {
      main: [{ code: '300473', name: '旧事故股' }],
      h4_t3: [{ code: '600001', name: '旧H4股' }],
      highlights: [{ code: '000002', name: '旧看点股' }],
      luojie: [{ code: '000003', name: '旧罗姐股' }],
      baseline: [{ code: '000001', name: '基础候选' }]
  },
  view_meta: {},
  view_order: ['main', 'h4_t3', 'baseline']
};
const result = globalThis.__auxTest.views();
assert(result.views.main.length === 0, 'legacy main row remained visible without health');
assert(result.views.h4_t3.length === 0, 'legacy H4 row remained visible without health');
assert(result.views.highlights.length === 0, 'legacy research row remained visible without health');
assert(result.views.luojie.length === 0, 'legacy Luo row remained visible without health');
assert(result.views.baseline.length === 1, 'upstream baseline was incorrectly hidden');
assert(result.meta.main.availability.state === 'unavailable', 'main state was not fail-closed');
""",
        )

    def test_empty_detail_preserves_the_active_view_reason(self):
        _assert_node_contract(
            self,
            "{ render: renderCandidateDetail, state: state }",
            r"""
globalThis.__auxTest.state.currentView = 'acceleration';
globalThis.__auxTest.state.data = {
  selection_input_health: { schema_version: 2, by_strategy: {} }
};
globalThis.__auxTest.state.workspace = {
  views: { acceleration: [] }, view_order: ['acceleration'],
  view_meta: { acceleration: { availability: {
    state: 'disabled', reason: '上证涨幅未超过1%'
  } } }
};
const target = { innerHTML: '' };
globalThis.__auxTest.render(null, target);
assert(target.innerHTML.includes('今日未启用'), 'detail lost disabled state');
assert(target.innerHTML.includes('上证涨幅未超过1%'), 'detail lost the exact reason');
assert(!target.innerHTML.includes('尚无可选候选'), 'detail replaced exact state with generic text');
""",
        )

    def test_header_discloses_official_close_and_data_degradation(self):
        _assert_node_contract(
            self,
            "{ status: getReportDataStatus }",
            r"""
const official = globalThis.__auxTest.status({ data_quality: {
  is_official: true, bar_state: 'closed', as_of: '2026-08-26T15:05:10+08:00',
  market_status: 'verified', fallback_used: false, warnings: []
} });
assert(official.includes('正式收盘版'), 'official close state hidden');
assert(official.includes('截至 15:05'), 'as-of time hidden');
assert(official.includes('策略输入状态未记录'), 'missing strategy input contract was called healthy');
const healthy = globalThis.__auxTest.status({
  data_quality: {
    is_official: true, bar_state: 'closed', as_of: '2026-08-26T15:05:10+08:00',
    market_status: 'verified', fallback_used: false, warnings: []
  },
  selection_input_health: {
    status: 'verified', formal: { formal_actions_allowed: true }
  }
});
assert(healthy.includes('行情与选股输入健康'), 'verified selection inputs were hidden');
const blocked = globalThis.__auxTest.status({
  data_quality: {
    is_official: true, bar_state: 'closed', as_of: '2026-08-26T15:05:10+08:00',
    market_status: 'verified', fallback_used: false, warnings: []
  },
  selection_input_health: {
    status: 'unavailable', formal: { formal_actions_allowed: false }
  }
});
assert(blocked.includes('本期未选出推荐票'), 'invalid strategy input looked healthy');
const partialFormal = globalThis.__auxTest.status({
  data_quality: {
    is_official: true, bar_state: 'closed', as_of: '2026-08-26T15:05:10+08:00',
    market_status: 'verified', fallback_used: false, warnings: []
  },
  selection_input_health: {
    schema_version: 2, status: 'partial',
    formal: { formal_actions_allowed: true, all_formal_actions_allowed: false,
      blocked_strategies: ['daily_fusion'] }
  }
});
assert(partialFormal.includes('部分正式策略输入不可用'), 'partial formal closure was hidden');
const degraded = globalThis.__auxTest.status({ data_quality: {
  is_official: false, bar_state: 'intraday', fallback_used: true
} });
assert(degraded.includes('非正式数据'), 'unofficial data not warned');
assert(degraded.includes('存在降级'), 'fallback not warned');
""",
        )

    def test_signal_close_and_change_fail_closed_without_final_daily_evidence(self):
        _assert_node_contract(
            self,
            "{ price: getCandidateCurrentPriceFromRecord, change: getCandidateChangePctFromRecord, state: state }",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-26' };
assert(globalThis.__auxTest.price({ current_price: 12.34 }) === null,
  'arbitrary current_price was labeled as signal close');
assert(globalThis.__auxTest.change({ change_pct: 3.2 }) === null,
  'arbitrary change_pct was labeled as daily change');
const verified = {
  current_price: 12.34, change_pct: 3.2,
  data_status: {
    daily: 'verified', latest_date: '2026-08-26', stale: false, is_final: true
  }
};
assert(globalThis.__auxTest.price(verified) === 12.34, 'verified signal close was hidden');
assert(globalThis.__auxTest.change(verified) === 3.2, 'verified daily change was hidden');
const stale = Object.assign({}, verified, { data_status: Object.assign({}, verified.data_status, { latest_date: '2026-08-25' }) });
assert(globalThis.__auxTest.price(stale) === null, 'stale close was shown as signal-day close');
""",
        )

    def test_research_conclusion_uses_page_reason_not_formal_action_reason(self):
        _assert_node_contract(
            self,
            "{ section: buildConclusionSection, state: state }",
            r"""
globalThis.__auxTest.state.currentView = 'highlights';
const html = globalThis.__auxTest.section({
  name: '研究票', code: '000001', action: '可上车',
  action_reason: '主推命中，偏执行优先',
  page_action: '仅观察', page_action_reason: '跨池观察排序靠前',
  action_semantics: 'watch_only'
}, {});
assert(html.includes('正式动作：仅观察'), 'research action cap hidden');
assert(html.includes('跨池观察排序靠前'), 'page reason hidden');
assert(!html.includes('偏执行优先'), 'formal action reason leaked into research conclusion');
""",
        )

    def test_alignment_only_reason_is_truthful_and_hides_internal_evidence_keys(self):
        _assert_node_contract(
            self,
            "({ reasons: buildReasonSection })",
            r"""
const html = globalThis.__auxTest.reasons(
  { primary_reason: '日线强势启动观察', action_semantics: 'watch_only' },
  {
    sublevel_confirm_reason: '30分钟均线仍为多头排列，但未形成独立确认',
    confirmation_evidence: {
      ema_bullish_alignment: true,
      recovery_bundle_match: false,
      macd_hist_direction: 'weakening'
    }
  }
);
assert(html.includes('30分钟均线仍为多头排列，但未形成独立确认'),
  'alignment-only reason is not displayed truthfully');
assert(!html.includes('EMA5维持'), 'legacy EMA state was presented as confirmation');
assert(!html.includes('确认良好'), 'alignment-only state was overstated');
['ema_bullish_alignment', 'recovery_bundle_match', 'macd_hist_direction'].forEach(function (key) {
  assert(!html.includes(key), 'internal evidence key leaked: ' + key);
});
""",
        )

    def test_incident_review_marks_raw_decision_invalid_and_hides_scores(self):
        _assert_node_contract(
            self,
            "{ badge: renderCandidateDecisionBadge, dataBadges: renderDataBadges, decision: buildDecisionEngineSection, details: buildDetailsSection, reasons: buildReasonSection, price: buildPriceSection, chartHelp: buildChartPlaceholder, chart: renderChart, state: state }",
            r"""
const item = {
  code: '300697', incident_review_only: true,
  page_action_reason: '策略输入过期或未核验，已排除正式动作和评分；本行仅供事故复盘。',
  primary_reason: '过期30分钟金叉', reference_price: 15.2,
  opportunity_score: 70,
  data_badges: [{ type: 'risk', label: '策略输入过期·仅复盘' }],
  decision_engine_v1: {
    decision: '推荐', total_score: 70,
    structure: { score: 30, reasons: ['过期结构'] },
    position: { score: 20 }, sentiment: { score: 20 }
  }
};
const raw = { sublevel_confirm_reason: '30分钟金叉', decision_engine_v1: item.decision_engine_v1 };
const badge = globalThis.__auxTest.badge(item, item.decision_engine_v1);
assert(badge.includes('事故前原始判定'), 'incident candidate lacked invalid-decision marker');
assert(!badge.includes('评分 70'), 'incident candidate still showed an effective score');
assert(globalThis.__auxTest.dataBadges(item).includes('策略输入过期·仅复盘'), 'incident data badge was not rendered');
const detail = globalThis.__auxTest.decision(item, raw)
  + globalThis.__auxTest.details(item, raw)
  + globalThis.__auxTest.reasons(item, raw)
  + globalThis.__auxTest.price(item, raw);
assert(detail.includes('原始判定和评分不生效'), 'detail did not explain score invalidation');
assert(detail.includes('事故前结构参考价（仅追溯）'), 'stale reference price looked current');
assert(!detail.includes('评分 70'), 'detail leaked the invalid score');
assert(!detail.includes('结构</span><strong>30'), 'detail leaked component scores');
assert(!detail.includes('30分钟金叉'), 'stale intraday reason looked valid');
assert(globalThis.__auxTest.chartHelp(item).includes('事故前原始证据，仅供追溯'), 'chart help treated incident evidence as current');
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
globalThis.__auxTest.state.data = { date: '2026-08-26' };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
const chartItem = Object.assign({}, item, {
  current_price: 4.1,
  data_status: { daily: 'verified', latest_date: '2026-08-26', stale: false, is_final: true }
});
globalThis.__auxTest.chart({
  dates: ['2026-08-25', '2026-08-26'],
  opens: [4.0, 4.1], highs: [4.2, 4.3], lows: [3.9, 4.0], closes: [4.1, 4.2],
  chart_annotations: {
    markLines: [{ name: 'source', yAxis: 4.0375, label: { formatter: '参考 4.0375' } }]
  }
}, chartItem);
const chartJson = JSON.stringify(chartOption);
assert(chartJson.includes('事故前参考·仅追溯'), 'incident chart reference was not relabeled');
assert(!chartJson.includes('参考 4.0375'), 'raw reference annotation still looked valid');
assert(!chartJson.includes('参考 15.20'), 'computed reference still looked valid');
""",
        )

    def test_decision_badge_score_keeps_full_contrast(self):
        start = CSS.index(".decision-badge-score {")
        end = CSS.index("}", start)
        rule = CSS[start:end]
        self.assertNotIn("opacity", rule)
        self.assertIn("color: inherit", rule)

    def test_top10_forces_watch_only_and_uses_chinese_semantic_headers(self):
        _assert_node_contract(
            self,
            "{ render: renderTop10Result, nodes: nodes }",
            r"""
const mount = { innerHTML: '' };
globalThis.__auxTest.nodes.top10Result = mount;
globalThis.__auxTest.render({ items: [{
  code: '000001', name: '研究票', action: '可上车',
  action_reason: '立即执行', reason: '观察理由'
}] }, 'done');
assert(mount.innerHTML.includes('页面身份'), 'top10 semantic header missing');
assert(mount.innerHTML.includes('研究依据'), 'top10 reason header missing');
assert(mount.innerHTML.includes('仅观察'), 'top10 leaked actionable label');
assert(!mount.innerHTML.includes('立即执行'), 'top10 leaked formal action reason');
""",
        )

    def test_comparison_omits_mixed_all_pool_average(self):
        start = JS.index("function renderComparisonResult")
        end = JS.index("function renderComparisonTable", start)
        renderer = JS[start:end]
        self.assertNotIn("comparisonSummary('all'", renderer)
        start = JS.index("function renderComparisonSummaryResults")
        end = JS.index("function initComparisonPage", start)
        summary = JS[start:end]
        self.assertNotIn("comparisonSummary('all'", summary)
        self.assertIn("isComparablePerformanceView", JS)

    def test_scorecard_discloses_samples_excluded_by_input_incidents(self):
        _assert_node_contract(
            self,
            "{ render: renderScorecardV2Card }",
            r"""
const html = globalThis.__auxTest.render({}, {
  strategy: 'daily_fusion', version: 'v1', source_pool: 'picks_fusion',
  evaluation_role: 'formal', evaluation_status: 'data_unavailable',
  signal_count: 2, eligible_signal_count: 1, excluded_signal_count: 1,
  episode_count: 1, active_dates: 1, active_months: 1,
  sample_exclusions: [{
    incident_id: 'stale-30m', reason: 'strategy_input_stale_or_unverified', count: 1
  }],
  metrics_publishable: false,
  metrics_blocking_reasons: ['strategy_input_stale_or_unverified'],
  metrics_by_horizon: {}, maturity_by_horizon: {}
});
assert(html.includes('事故排除 1'), 'excluded sample count hidden');
assert(html.includes('stale-30m'), 'incident id hidden');
assert(html.includes('策略输入日期过期或未核验'), 'incident reason hidden');
""",
        )

    def test_scorecard_separates_today_ledger_and_return_universes(self):
        _assert_node_contract(
            self,
            "{ render: renderScorecardV2Card }",
            r"""
const html = globalThis.__auxTest.render({}, {
  strategy: 'daily_fusion', version: 'v1', source_pool: 'picks_fusion',
  evaluation_role: 'formal', evaluation_status: 'collecting',
  latest_run_status: 'ran', latest_signal_count: 3,
  signal_count: 12, eligible_signal_count: 8, excluded_signal_count: 4,
  episode_count: 6, active_dates: 5, active_months: 1,
  ledger_active_dates: 9, ledger_date_start: '2026-08-14', ledger_date_end: '2026-08-26',
  gate_outcomes: { recommend: 7, observe: 4, reject: 1 },
  publication_outcomes: { recommendation: 5, watch: 7 },
  metrics_publishable: true, metrics_by_horizon: {}, maturity_by_horizon: {}
});
assert(html.includes('今日运行：今日已运行，产生 3 个信号'), 'today universe missing');
assert(html.includes('账本累计：2026-08-14 至 2026-08-26'), 'ledger window missing');
assert(html.includes('累计信号 12'), 'ledger signal count missing');
assert(html.includes('收益评测：可评 8'), 'return-evaluation universe missing');
assert(html.includes('合同样本 12'), 'evaluation-contract denominator missing');
assert(html.includes('事故排除 4'), 'evaluation exclusion count missing');
assert(html.includes('非收益样本 0'), 'non-return sample count missing');
""",
        )

    def test_candidate_keyboard_navigation_contract_is_bounded(self):
        _assert_node_contract(
            self,
            "{ move: getCandidateNavigationIndex }",
            r"""
assert(globalThis.__auxTest.move(0, 'ArrowDown', 3) === 1, 'ArrowDown did not advance');
assert(globalThis.__auxTest.move(2, 'ArrowDown', 3) === 0, 'ArrowDown did not wrap');
assert(globalThis.__auxTest.move(0, 'ArrowUp', 3) === 2, 'ArrowUp did not wrap');
assert(globalThis.__auxTest.move(1, 'Home', 3) === 0, 'Home did not reach first');
assert(globalThis.__auxTest.move(1, 'End', 3) === 2, 'End did not reach last');
assert(globalThis.__auxTest.move(1, 'Enter', 3) === 1, 'unrelated key changed selection');
""",
        )

    def test_direction_quick_summary_identifies_rules_and_llm_fallback(self):
        _assert_node_contract(
            self,
            "{ label: getDirectionBriefSourceLabel }",
            r"""
assert(globalThis.__auxTest.label({ status: 'rules_only' }) === '规则生成', 'rules-only identity hidden');
assert(globalThis.__auxTest.label({ llm_error: 'timeout' }) === 'LLM 复核失败·已回退规则', 'LLM fallback identity hidden');
assert(globalThis.__auxTest.label({ status: 'verified', model: 'x' }) === '模型复核', 'model identity hidden');
""",
        )

    def test_picks_pure_tab_is_named_as_the_shared_base_candidate_universe(self):
        self.assertIn("baseline: '基础候选'", JS)
        self.assertIn("原始缠论结构候选 / 各策略共同上游全集", JS)
        self.assertNotIn("baseline: '基准'", JS)

    def test_legacy_snapshot_cannot_restore_the_old_baseline_tab_label(self):
        _assert_node_contract(
            self,
            "{ state: state, label: getCurrentLabel, shortLabel: getCurrentShortLabel, description: getCurrentDescription }",
            r"""
globalThis.__auxTest.state.workspace = {
  view_meta: { baseline: {
    label: '基准', short_label: '基准', description: '旧快照说明'
  } },
  views: { baseline: [] }, view_order: ['baseline']
};
assert(globalThis.__auxTest.label('baseline') === '基础候选', 'legacy label leaked');
assert(globalThis.__auxTest.shortLabel('baseline') === '基础候选', 'legacy short label leaked');
assert(globalThis.__auxTest.description('baseline').includes('共同上游全集'), 'legacy description leaked');
""",
        )

    def test_scan_first_renderers_exist(self):
        for helper in (
            "function renderLimitUpEcologyCard",
            "function renderDecisionDirections",
            "function renderPersonalWatchlist",
            "function renderHoldingRiskSection",
            "function renderStrategyScorecards",
            "function renderShadowEvaluations",
        ):
            self.assertIn(helper, JS)

    def test_primary_path_uses_decision_contracts_not_global_sell_list(self):
        start = JS.index("function buildAuxiliaryStacks")
        end = JS.index("function renderAuxiliaryCenter", start)
        primary = JS[start:end]
        for call in (
            "renderSectorFlowCard(source)",
            "renderDecisionDirections(source)",
            "renderPersonalWatchlist(source)",
            "renderLimitUpEcologyCard(source)",
            "renderHoldingRiskSection(source)",
            "renderStrategyScorecards(source)",
            "renderShadowEvaluations(source)",
        ):
            self.assertIn(call, primary)
        self.assertNotIn("renderSellSignalsCard(data)", primary)
        self.assertNotIn("renderRecentReviewsCard(data)", primary)

    def test_watchlist_consumes_fact_and_direction_analysis_fields(self):
        start = JS.index("function resolveDirectionConditions")
        end = JS.index("function renderHoldingRiskSection", start)
        renderer = JS[start:end]
        for field in (
            "evidence_date",
            "change_status",
            "action_status",
            "price_levels",
            "candidate_intersections",
            "next_trigger",
            "invalidation",
        ):
            self.assertIn(field, renderer)
        self.assertIn("方向级 LLM 关联", renderer)
        self.assertIn("不是个股独立结论", renderer)
        self.assertIn("evidence_registry", renderer)

    def test_watchlist_manager_supports_versioned_crud_without_mutating_snapshot(self):
        for helper in (
            "function renderWatchlistManager",
            "function loadWatchlistManagerConfig",
            "function addWatchlistManagerItem",
            "function removeWatchlistManagerItem",
            "function moveWatchlistManagerItem",
            "function toggleWatchlistManagerItem",
            "function saveWatchlistManagerConfig",
            "function bindWatchlistManager",
        ):
            self.assertIn(helper, JS)
        self.assertIn("function getDecisionWatchlistUrl", JS)
        self.assertIn("getBootstrap().decisionWatchlistUrl", JS)
        self.assertIn("If-Match", JS)
        self.assertIn("watchlist revision conflict", JS)
        self.assertIn("等待下次日报分析", JS)
        self.assertIn("当前日报快照", JS)
        self.assertIn("type=\"password\"", JS)
        self.assertNotIn("WATCHLIST_ADMIN_PASSWORD", JS)

        save_start = JS.index("function saveWatchlistManagerConfig")
        save_end = JS.index("function bindWatchlistManager", save_start)
        save = JS[save_start:save_end]
        load_start = JS.index("function loadWatchlistManagerConfig")
        load_end = JS.index("function syncWatchlistManagerForm", load_start)
        load = JS[load_start:load_end]
        self.assertIn("getDecisionWatchlistUrl()", load)
        self.assertIn("window.fetch(apiBase", load)
        self.assertIn("getDecisionWatchlistUrl()", save)
        self.assertIn("window.fetch(apiBase", save)
        self.assertNotIn("state.data.personal_watchlist =", save)

    def test_watchlist_manager_has_conflict_and_save_failure_states(self):
        for text in (
            "配置版本冲突",
            "保存失败",
            "重新载入线上配置",
            "配置已保存",
        ):
            self.assertIn(text, JS)
        self.assertIn(".watchlist-manager", CSS)
        self.assertIn(".watchlist-manager-row", CSS)

    def test_watchlist_manager_labels_note_as_note_with_auto_name_resolution(self):
        start = JS.index("function renderWatchlistManager")
        end = JS.index("function loadWatchlistManagerConfig", start)
        renderer = JS[start:end]
        self.assertIn('data-watch-field="note"', renderer)
        self.assertIn('aria-label="备注（名称自动识别）"', renderer)
        self.assertIn('placeholder="备注（名称自动识别）"', renderer)
        self.assertNotIn('aria-label="股票名称"', renderer)
        self.assertNotIn('placeholder="股票名称"', renderer)

    def test_watchlist_candidate_intersections_use_user_facing_pool_names(self):
        start = JS.index("function getWatchPoolLabel")
        end = JS.index("function renderWatchPriceLevels", start)
        labels = JS[start:end]
        for token in (
            "pure: '基础候选池（原始缠论结构）'",
            "fusion: '融合候选全集'",
            "observation: '观察池'",
            "next_day_boom: '次日爆发策略池'",
            "luojie: '罗姐策略池'",
            "h4_t3_pool: 'H4 T+3 策略池'",
        ):
            self.assertIn(token, labels)

    def test_strategy_scorecards_disclose_horizon_and_count_evaluation_groups(self):
        start = JS.index("function renderStrategyScorecards")
        end = JS.index("function renderShadowEvaluations", start)
        renderer = JS[start:end]
        self.assertIn("逐周期核算", renderer)
        self.assertIn("个评测分组", renderer)
        self.assertNotIn("个策略'", renderer)

    def test_strategy_scorecards_v2_separate_roles_and_honest_metric_states(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
const base = {
  strategy: 'daily_fusion', name: '融合策略', version: 'v2',
  source_pool: 'picks_fusion', entry_mode: 'immediate_close',
  intended_horizon: 3, signal_count: 8, eligible_signal_count: 7,
  episode_count: 6, active_dates: 4, active_months: 1,
  evaluation_status: 'collecting', metrics_publishable: true,
  maturity_by_horizon: {
    t1: { mature: 6, waiting: 0, unavailable: 0 },
    t3: { mature: 4, waiting: 2, unavailable: 0 },
    t5: { mature: 0, waiting: 6, unavailable: 0 }
  },
  horizon_readiness: {
    t1: 'collecting', t3: 'collecting', t5: 'waiting_for_maturity'
  },
  comparison_progress_by_horizon: {
    t1: { status: 'collecting', mature_samples: 6, required_mature_samples: 100, active_dates: 4, required_active_dates: 20, active_months: 1, required_calendar_months: 2 },
    t3: { status: 'collecting', mature_samples: 4, required_mature_samples: 100, active_dates: 4, required_active_dates: 20, active_months: 1, required_calendar_months: 2 },
    t5: { status: 'waiting_for_maturity', mature_samples: 0, required_mature_samples: 100, active_dates: 0, required_active_dates: 20, active_months: 0, required_calendar_months: 2 }
  },
  metrics_by_horizon: {
    t1: { n: 6, mean: 0, median: -0.2, excess_mean: 0.1, excess_n: 6,
      win_rate: 50, win_rate_n: 6, hit_rate_ge_5: 16.67, hit_rate_ge_5_n: 6,
      period_high: 6.8, period_high_n: 6, period_low: -2.1, period_low_n: 6 },
    t3: { n: 4, mean: 2.5, median: 2, excess_mean: null, excess_n: 0,
      win_rate: 75, win_rate_n: 4, hit_rate_ge_5: 25, hit_rate_ge_5_n: 4,
      period_high: 9.2, period_high_n: 4, period_low: -1.5, period_low_n: 4 },
    t5: { n: 0, mean: null, median: null, excess_mean: null, excess_n: 0,
      win_rate: null, win_rate_n: 0, hit_rate_ge_5: null, hit_rate_ge_5_n: 0,
      period_high: null, period_high_n: 0, period_low: null, period_low_n: 0 }
  },
  gate_outcomes: { recommend: 3, observe: 4, reject: 1 },
  publication_outcomes: { recommendation: 3, watch: 4 },
  representative_samples: []
};
const html = globalThis.__auxTest.render({
  strategy_scorecards: {
    schema_version: 2,
    thresholds: { mature_samples: 100, active_dates: 20, calendar_months: 2 },
    classification_failures: [{ strategy: 'unknown_strategy', version: 'v0', source_pool: 'mystery', reason: 'legacy_identity_unknown' }],
    formal: [base],
    baselines: [Object.assign({}, base, { strategy: 'daily_pure', name: '基础候选', source_pool: 'picks_pure' })],
    research: [Object.assign({}, base, { strategy: 'luojie_pool', name: '罗杰主题策略', source_pool: 'luojie_pool', metrics_publishable: false, evaluation_status: 'data_unavailable', metrics_blocking_reasons: ['reference_close_missing'] })],
    gates: [{ strategy: 'observation_gate', name: '观察门控', version: 'v1', source_pool: 'observation_watchlist', entry_mode: 'immediate_close', signal_count: 8, evaluation_status: 'collecting', gate_outcomes: { recommend: 0, observe: 8, reject: 0 }, publication_outcomes: { watch: 8 } }]
  },
  diagnostics: { strategy_review: { benchmark_status: 'missing' } }
});
for (const label of ['正式推荐收益', '基础候选基线', '研究策略回看', '门控运行诊断']) {
  assert(html.includes(label), 'missing section ' + label);
}
assert(html.includes('T+1 收盘'), 'T+1 close semantics missing');
assert(html.includes('6&#47;100 成熟样本'), 'sample maturity progress missing');
assert(html.includes('4&#47;20 活跃日'), 'active-day progress missing');
assert(html.includes('等待到期'), 'right-censored horizon was not explicit');
assert(html.includes('参考收盘价缺失'), 'blocking reason was not translated');
assert(!html.includes('≥5%命中'), 'small-sample hit-rate conclusion leaked');
assert(!html.includes('期间最高'), 'small-sample excursion conclusion leaked');
assert(!html.includes('期间最低'), 'small-sample excursion conclusion leaked');
assert(html.includes('该门控不计算收益'), 'gate was presented as return strategy');
assert(html.includes('1 条账本身份无法安全分类'), 'classification failures were silently hidden');
assert(html.includes('罗姐主题策略'), 'known historical name was not normalized');
assert(!html.includes('罗杰主题策略'), 'legacy typo leaked into current UI');
assert(!html.includes('MAE'), 'internal MAE leaked to user');
assert(!html.includes('MFE'), 'internal MFE leaked to user');
""",
        )

    def test_strategy_scorecards_legacy_payload_is_explicitly_non_comparable(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
const html = globalThis.__auxTest.render({
  strategy_scorecards: [{ strategy: 'daily_fusion', name: '旧融合', version: 'v1', sample_size: 3 }],
  diagnostics: { strategy_review: {} }
});
assert(html.includes('历史旧口径'), 'legacy warning missing');
assert(html.includes('不作为成绩'), 'legacy score was still comparable');
assert(html.includes('旧口径，仅追溯'), 'legacy badge still implied scored groups');
assert(!html.includes('1个评测分组'), 'legacy identity row was counted as a score group');
""",
        )

    def test_strategy_comparison_gate_hides_conclusions_until_mature(self):
        _assert_node_contract(
            self,
            "({ renderScorecardV2Card })",
            r"""
const base = {
  evaluation_role: 'research', strategy: 'next_day_boom', name: '次日爆发策略',
  version: 'boom-v1', source_pool: 'next_day_boom', entry_mode: 'immediate_close',
  intended_horizon: 3, research_tier: 'prospective_oot', evaluation_status: 'collecting',
  metrics_publishable: true, signal_count: 4, eligible_signal_count: 4,
  excluded_signal_count: 0, episode_count: 4, active_dates: 3, active_months: 1,
  gate_outcomes: {}, publication_outcomes: {},
  maturity_by_horizon: {
    t1: { mature: 4, waiting: 0, unavailable: 0 },
    t3: { mature: 4, waiting: 0, unavailable: 0 },
    t5: { mature: 0, waiting: 4, unavailable: 0 }
  },
  horizon_readiness: { t1: 'collecting', t3: 'collecting', t5: 'waiting_for_maturity' },
  comparison_progress_by_horizon: {
    t1: { status: 'collecting', mature_samples: 4, required_mature_samples: 100, active_dates: 3, required_active_dates: 20, active_months: 1, required_calendar_months: 2 },
    t3: { status: 'collecting', mature_samples: 4, required_mature_samples: 100, active_dates: 3, required_active_dates: 20, active_months: 1, required_calendar_months: 2 },
    t5: { status: 'waiting_for_maturity', mature_samples: 0, required_mature_samples: 100, active_dates: 3, required_active_dates: 20, active_months: 1, required_calendar_months: 2 }
  },
  metrics_by_horizon: {
    t1: { n: 4, mean: 88, median: 77, win_rate: 100 },
    t3: { n: 4, mean: 99, median: 66, win_rate: 100 }, t5: {}
  },
  representative_samples: [{ code: '300308', returns: { t3: 99 } }]
};
const collecting = globalThis.__auxTest.renderScorecardV2Card({}, base);
assert(collecting.includes('4&#47;100 成熟样本'), 'mature sample progress missing');
assert(collecting.includes('3&#47;20 活跃日'), 'active date progress missing');
assert(collecting.includes('1&#47;2 自然月'), 'calendar month progress missing');
assert(!collecting.includes('+99.00%'), 'immature mean leaked');
assert(!collecting.includes('上涨率'), 'immature win-rate conclusion leaked');
assert(!collecting.includes('300308'), 'immature representative sample leaked');

const mature = JSON.parse(JSON.stringify(base));
mature.evaluation_status = 'ready_for_manual_comparison';
mature.horizon_readiness.t3 = 'ready_for_manual_comparison';
mature.comparison_progress_by_horizon.t3.status = 'ready_for_manual_comparison';
mature.comparison_progress_by_horizon.t3.mature_samples = 100;
mature.comparison_progress_by_horizon.t3.active_dates = 20;
mature.comparison_progress_by_horizon.t3.active_months = 2;
mature.maturity_by_horizon.t3.mature = 100;
mature.metrics_by_horizon.t3 = {
  n: 100, date_start: '2026-01-05', date_end: '2026-02-27', median: 3.5,
  mean: 4.0, excess_mean: 1.2, excess_n: 100, max_drawdown: -8.0,
  mean_mfe: 7.0, mean_mae: -2.0, mfe_n: 100, mae_n: 100
};
const ready = globalThis.__auxTest.renderScorecardV2Card({}, mature);
['样本数', '样本区间', '中位收益', '平均收益', '基准超额', '最大回撤', 'MFE', 'MAE'].forEach(function (label) {
  assert(ready.includes(label), 'mature metric missing: ' + label);
});
assert(!ready.includes('综合分'), 'unexplained composite score rendered');
""",
        )

    def test_no_signal_and_disabled_horizons_are_not_called_data_unavailable(self):
        _assert_node_contract(
            self,
            "{ horizon: renderStrategyHorizon }",
            r"""
const emptyHtml = globalThis.__auxTest.horizon(
  't1', {}, { mature: 0, waiting: 0, unavailable: 0 },
  false, ['no_signals'], 'no_signals'
);
assert(emptyHtml.includes('本期无信号'), 'normal empty horizon was not neutral');
assert(!emptyHtml.includes('<strong>本期证据不足</strong>'), 'normal empty looked broken');
const disabledHtml = globalThis.__auxTest.horizon(
  't1', {}, { mature: 0, waiting: 0, unavailable: 0 },
  false, [], 'disabled'
);
assert(disabledHtml.includes('今日未启用'), 'disabled horizon was not neutral');
assert(!disabledHtml.includes('<strong>本期证据不足</strong>'), 'disabled strategy looked broken');
const staleHtml = globalThis.__auxTest.horizon(
  't1', {}, { mature: 0, waiting: 0, unavailable: 1 },
  false, ['strategy_input_stale_or_unverified'], 'data_unavailable'
);
assert(staleHtml.includes('策略输入日期过期或未核验，禁止评分'), 'stale input blocker was not explained');
assert(staleHtml.includes('<strong>本期证据不足</strong>'), 'stale input did not fail closed');
""",
        )

    def test_gate_scorecard_separates_today_from_ledger_cumulative_counts(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
const html = globalThis.__auxTest.render({ strategy_scorecards: {
  schema_version: 2, formal: [], baselines: [], research: [],
  gates: [{
    strategy: 'observation_gate', version: 'v1',
    source_pool: 'observation_watchlist', evaluation_status: 'running',
    latest_run_status: 'ran', latest_signal_count: 321,
    active_dates: 8, ledger_active_dates: 8,
    ledger_date_start: '2026-08-15', ledger_date_end: '2026-08-26',
    gate_outcomes: { recommend: 182, observe: 310, reject: 203 },
    publication_outcomes: { watch: 695 }
  }], classification_failures: []
}, diagnostics: {} });
assert(html.includes('当日运行：今日已运行，产生 321 个信号'), 'today run count missing');
assert(html.includes('账本累计（2026-08-15 至 2026-08-26 · 8 个交易日）'), 'cumulative window was not labeled');
assert(html.includes('推荐 / 观察 / 拒绝：182 / 310 / 203'), 'cumulative gate counts missing');
""",
        )

    def test_limit_up_theme_is_not_duplicated_as_sector_flow(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const registry = {
  'sector:power': { kind: 'sector_flow', change_pct: 1.51 },
  'limit:power': { kind: 'limit_up_theme', name: '涨停电力', count: 3 }
};
const html = globalThis.__auxTest.render({
  theme: '电力', direction: 'positive', stage: 'confirmed',
  rule_summary: '方向成立', risk_reasons: [],
  sector_links: [
    { link_type: 'sector_flow', name: '资金电力', evidence_ref: 'sector:power' },
    { link_type: 'limit_up_theme', name: '涨停电力', evidence_ref: 'limit:power' }
  ],
  evidence_refs: ['limit:power']
}, 0, registry);
assert(html.includes('<strong>资金电力 +1.51%</strong>'), 'sector flow evidence missing');
assert(!html.includes('<strong>资金电力 +1.51% &#47; 涨停电力</strong>'), 'limit-up theme duplicated in sector evidence');
assert(html.includes('涨停电力 3只'), 'limit-up theme missing from screen evidence');
""",
        )

    def test_long_diagnostic_text_wraps_instead_of_being_clipped(self):
        start = CSS.index(".diagnostic-row span")
        end = CSS.index("}", start)
        rule = CSS[start:end]
        self.assertIn("min-width: 0", rule)
        self.assertIn("overflow-wrap: anywhere", rule)

    def test_strategy_scorecard_partial_maturity_contract_fails_closed(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
const html = globalThis.__auxTest.render({
  strategy_scorecards: { schema_version: 2, thresholds: {}, formal: [{
    strategy: 'daily_fusion', name: '融合', version: 'v2',
    source_pool: 'picks_fusion', entry_mode: 'immediate_close',
    signal_count: 1, eligible_signal_count: 1, episode_count: 1,
    metrics_publishable: true,
    maturity_by_horizon: {
      t1: { waiting: 0, unavailable: 0 },
      t3: { mature: 0, waiting: 1, unavailable: 0 },
      t5: { mature: 0, waiting: 1, unavailable: 0 }
    },
    metrics_by_horizon: {
      t1: { n: 0, mean: 0 }, t3: { n: 0 }, t5: { n: 0 }
    }, representative_samples: []
  }], baselines: [], research: [], gates: [], classification_failures: [] },
  diagnostics: { strategy_review: { benchmark_status: 'ok' } }
});
assert(html.includes('合同字段缺失'), 'partial maturity contract was not failed closed');
assert(html.includes('成熟、等待或不可用分母未完整记录'), 'missing denominator was not explained');
assert(!html.includes('-- 个成熟回合'), 'missing mature count rendered as a count');
assert(!html.includes('<small>平均收益</small>'), 'metrics rendered despite missing required denominator');
""",
        )

    def test_strategy_scorecard_role_controls_action_and_reason_labels(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
function card(role, strategy, source) {
  return {
    evaluation_role: role, strategy: strategy, name: strategy, version: 'v1',
    source_pool: source, entry_mode: 'immediate_close', intended_horizon: 1, signal_count: 1,
    eligible_signal_count: 1, episode_count: 1, active_dates: 1, active_months: 1,
    evidence_tier: role === 'baseline' ? 'legacy_inferred' : 'prospective_ledger',
    evaluation_status: 'collecting', metrics_publishable: true,
    maturity_by_horizon: {
      t1: { mature: 1, waiting: 0, unavailable: 0 },
      t3: { mature: 0, waiting: 1, unavailable: 0 },
      t5: { mature: 0, waiting: 1, unavailable: 0 }
    },
    horizon_readiness: {
      t1: 'ready_for_manual_comparison',
      t3: 'waiting_for_maturity',
      t5: 'waiting_for_maturity'
    },
    comparison_progress_by_horizon: {
      t1: { status: 'ready_for_manual_comparison', mature_samples: 100, required_mature_samples: 100, active_dates: 20, required_active_dates: 20, active_months: 2, required_calendar_months: 2 },
      t3: { status: 'waiting_for_maturity', mature_samples: 0, required_mature_samples: 100, active_dates: 0, required_active_dates: 20, active_months: 0, required_calendar_months: 2 },
      t5: { status: 'waiting_for_maturity', mature_samples: 0, required_mature_samples: 100, active_dates: 0, required_active_dates: 20, active_months: 0, required_calendar_months: 2 }
    },
    metrics_by_horizon: {
      t1: { n: 1, mean: 1, median: 1, excess_mean: 0, excess_n: 1,
        win_rate: 100, win_rate_n: 1, hit_rate_ge_5: 0, hit_rate_ge_5_n: 1,
        period_high: 2, period_high_n: 1, period_low: -1, period_low_n: 1 },
      t3: { n: 0 }, t5: { n: 0 }
    },
    gate_outcomes: { recommend: 94, observe: 42, reject: 0 },
    publication_outcomes: { recommendation: 94, watch: 42 },
    representative_samples: [{ name: '样本', reason_summary: '结构成立' }]
  };
}
const baselineHtml = globalThis.__auxTest.render({
  strategy_scorecards: { schema_version: 2, thresholds: {}, formal: [],
    baselines: [card('baseline', 'daily_pure', 'picks_pure')],
    research: [], gates: [], classification_failures: [] }, diagnostics: {}
});
assert(baselineHtml.includes('页面身份：共同上游候选，不计作正式推荐'), 'baseline action identity missing');
assert(baselineHtml.includes('上游候选原因'), 'baseline sample called a recommendation');
assert(baselineHtml.includes('旧账本兼容推断'), 'legacy evidence identity hidden');
assert(!baselineHtml.includes('页面正式动作 推荐'), 'baseline counts presented as formal actions');

const researchHtml = globalThis.__auxTest.render({
  strategy_scorecards: { schema_version: 2, thresholds: {}, formal: [],
    baselines: [], research: [card('research', 'luojie_pool', 'luojie_pool')],
    gates: [], classification_failures: [] }, diagnostics: {}
});
assert(researchHtml.includes('页面身份：研究信号，不计作正式推荐'), 'research action identity missing');
assert(researchHtml.includes('研究信号原因'), 'research sample called a recommendation');
""",
        )

    def test_shadow_guard_rail_has_one_desktop_column_per_summary_item(self):
        start = CSS.index(".shadow-guard-rail {")
        end = CSS.index("}", start)
        rule = CSS[start:end]
        self.assertIn("repeat(6, minmax(0, 1fr))", rule)

    def test_directions_are_capped_and_watchlist_is_not_truncated(self):
        self.assertIn("decisionBrief.theses).slice(0, 3)", JS)
        self.assertIn("personalWatchlist.items).filter", JS)
        self.assertNotIn("personalWatchlist.items).slice", JS)

    def test_limit_up_statuses_and_honest_empty_states_are_distinct(self):
        for status in (
            "verified_complete",
            "verified_empty",
            "partial",
            "missing",
            "error",
        ):
            self.assertIn(status, JS)
        self.assertIn("上游明确返回 0 只涨停", JS)
        self.assertIn("数据缺失，不等于没有涨停", JS)

    def test_limit_up_ecology_discloses_top_five_and_total_counts(self):
        _assert_node_contract(
            self,
            "{ render: renderLimitUpEcologyCard }",
            r"""
const groups = Array.from({ length: 7 }, function (_, index) {
  return { name: '题材' + index, count: index + 1 };
});
const leaders = Array.from({ length: 6 }, function (_, index) {
  return { code: '30000' + index, name: '样本' + index, lianban: 1 };
});
const html = globalThis.__auxTest.render({ limit_up_snapshot: {
  status: 'verified_complete', raw_total: 20, parsed_count: 20,
  coverage: 1, limit_down_total: 2, theme_groups: groups, leaders: leaders
} });
assert(html.includes('题材梯队（前5 &#47; 共7）'), 'theme top/total disclosure missing');
assert(html.includes('领涨样本（前5 &#47; 共6）'), 'leader top/total disclosure missing');
assert(!html.includes('题材5'), 'theme renderer exceeded top five');
assert(!html.includes('样本5'), 'leader renderer exceeded top five');
""",
        )

    def test_one_direction_detail_can_be_open_at_a_time(self):
        self.assertIn("function bindSingleOpenDecisionDetails", JS)
        self.assertIn("detail.open = false", JS)
        self.assertIn('class="decision-direction"', JS)

    def test_direction_chain_resolves_human_readable_evidence(self):
        self.assertIn("function buildEvidenceRegistryMap", JS)
        self.assertIn("(decisionBrief || {}).evidence_registry", JS)
        self.assertIn("eventEvidence", JS)
        self.assertIn("evidence.title", JS)
        self.assertIn("limitEvidence", JS)
        self.assertIn("evidence.count", JS)
        self.assertIn("renderDirectionRow(row, index, registryMap)", JS)

    def test_risk_direction_renders_reasons_and_risk_condition_labels(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const html = globalThis.__auxTest.render({
  theme: 'AI算力', direction: 'negative', stage: 'risk',
  risk_reasons: [
    { detail: '风险事件进一步发酵', verification_status: 'verified', evidence_refs: ['event:1'] },
    '板块资金持续流出'
  ],
  next_trigger: ['风险证据减弱且结构止跌'],
  invalidation: ['风险继续扩散']
}, 0, {});
assert(html.includes('风险原因'), 'risk reason heading missing');
assert(html.includes('风险事件进一步发酵'), 'first risk reason missing');
assert(html.includes('板块资金持续流出'), 'second risk reason missing');
assert(html.includes('规则核实'), 'verified risk status missing');
assert(html.includes('event:1'), 'risk evidence reference missing');
assert(html.includes('风险升级条件'), 'risk escalation label missing');
assert(html.includes('风险解除条件'), 'risk resolution label missing');
const escalationAt = html.indexOf('风险升级条件');
const spreadAt = html.indexOf('风险继续扩散');
const resolutionAt = html.indexOf('风险解除条件');
const weakenAt = html.indexOf('风险证据减弱且结构止跌');
assert(escalationAt < spreadAt && spreadAt < resolutionAt, 'risk worsening was not grouped under escalation');
assert(resolutionAt < weakenAt, 'risk weakening was not grouped under resolution');
assert(!html.includes('下一确认'), 'generic confirmation label leaked into risk row');
assert(!html.includes('失效条件'), 'generic invalidation label leaked into risk row');
""",
        )

    def test_negative_monitor_is_labeled_pending_instead_of_established_risk(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const html = globalThis.__auxTest.render({
  theme: '半导体', direction: 'negative', stage: 'monitor',
  risk_reasons: [],
  confirmation_conditions: ['补充可追溯风险证据'],
  invalidation_conditions: ['负向线索被证伪']
}, 0, {});
assert(html.includes('负向待核验'), 'negative monitor mislabeled');
assert(!html.includes('风险成立'), 'unverified negative rendered as established risk');
assert(!html.includes('<span>风险原因</span>'), 'empty risk reason block should stay hidden');
""",
        )

    def test_model_extracted_risk_cannot_be_labeled_established(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const html = globalThis.__auxTest.render({
  theme: '算力', direction: 'negative', stage: 'risk',
  risk_reasons: [{
    detail: '模型提取到负向事件', verification_status: 'model_extracted'
  }]
}, 0, {});
assert(html.includes('风险待核实'), 'model-only risk not marked pending');
assert(!html.includes('风险成立'), 'model-only risk mislabeled established');
assert(html.includes('模型提取待核实'), 'risk provenance hidden');
""",
        )

    def test_mixed_direction_discloses_model_extracted_risk_reason(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const html = globalThis.__auxTest.render({
  theme: '创新药', direction: 'mixed', stage: 'developing',
  risk_reasons: [{
    detail: '部分关联个股出现负向事件',
    verification_status: 'model_extracted',
    evidence_refs: ['event:mixed']
  }]
}, 0, {});
assert(html.includes('分化含风险'), 'mixed risk label missing');
assert(html.includes('风险原因'), 'mixed risk reasons hidden');
assert(html.includes('模型提取待核实'), 'model extraction status hidden');
assert(html.includes('event:mixed'), 'mixed risk evidence ref hidden');
""",
        )

    def test_risk_direction_prefers_explicit_condition_contract(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const html = globalThis.__auxTest.render({
  theme: '光模块', direction: 'negative', stage: 'risk',
  risk_reasons: [{ detail: '已有可追溯风险事实', verification_status: 'verified' }],
  confirmation_conditions: ['风险证据继续扩散'],
  invalidation_conditions: ['风险证据减弱并止跌'],
  next_trigger: ['遗留确认字段不应采用'],
  invalidation: ['遗留失效字段不应采用']
}, 0, {});
const escalationAt = html.indexOf('风险升级条件');
const escalationTextAt = html.indexOf('风险证据继续扩散');
const resolutionAt = html.indexOf('风险解除条件');
const resolutionTextAt = html.indexOf('风险证据减弱并止跌');
assert(escalationAt < escalationTextAt && escalationTextAt < resolutionAt, 'explicit confirmation contract ignored');
assert(resolutionAt < resolutionTextAt, 'explicit invalidation contract ignored');
assert(!html.includes('遗留确认字段不应采用'), 'legacy confirmation leaked over explicit contract');
assert(!html.includes('遗留失效字段不应采用'), 'legacy invalidation leaked over explicit contract');
""",
        )

    def test_direction_stock_links_use_explicit_role_mapping(self):
        _assert_node_contract(
            self,
            "{ render: renderDirectionRow }",
            r"""
const html = globalThis.__auxTest.render({
  theme: '光模块', direction: 'positive', stage: 'confirmed',
  stock_links: [
    { code: '300001', name: '候选甲', link_type: 'candidate_intersection' },
    { code: '300002', name: '观察乙', link_type: 'watchlist_intersection' },
    { code: '300003', name: '领涨丙', link_type: 'limit_up_leader' },
    { code: '300004', name: '新闻丁', link_type: 'news_named' }
  ]
}, 0, {});
assert(html.includes('候选甲·候选池交集'), 'candidate intersection mislabeled');
assert(html.includes('观察乙·重点池'), 'watchlist intersection mislabeled');
assert(html.includes('领涨丙·领涨样本'), 'limit-up leader mislabeled');
assert(html.includes('新闻丁·事件点名'), 'news named mislabeled');
""",
        )

    def test_mobile_evidence_chain_becomes_vertical(self):
        self.assertIn(".evidence-chain", CSS)
        self.assertIn(".evidence-step", CSS)
        mobile = CSS[CSS.rindex("@media (max-width: 760px)"):]
        self.assertIn(".evidence-chain", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)
        self.assertIn(".decision-direction > summary", mobile)
        self.assertIn("display: grid", mobile)

    def test_expandable_rows_have_visible_disclosure_marker(self):
        self.assertIn(".decision-direction > summary::after", CSS)
        self.assertIn(".strategy-scorecard > summary::after", CSS)
        self.assertIn("content: '+'", CSS)

    def test_tablet_grid_has_no_unfillable_third_column(self):
        tablet_start = CSS.index("@media (max-width: 1180px)")
        tablet_end = CSS.index("@media (max-width: 760px)", tablet_start)
        tablet = CSS[tablet_start:tablet_end]
        self.assertIn(
            ".aux-grid.decision-grid {\n    grid-template-columns: 1fr;",
            tablet,
        )
        self.assertNotIn("grid-template-columns: repeat(3, minmax(0, 1fr));", tablet)
        self.assertIn(".strategy-scorecards-card", tablet)
        self.assertIn(".decision-card.shadow-card", tablet)

    def test_dense_evaluation_cards_use_full_desktop_width(self):
        desktop = CSS[:CSS.index("@media (max-width: 1180px)")]
        self.assertIn(
            ".research-validation-stack,\n.supporting-decisions-stack {\n  display: grid;\n  grid-template-columns: 1fr;",
            desktop,
        )

    def test_strategy_attribution_drilldown_stacks_on_mobile(self):
        mobile = CSS[CSS.rindex("@media (max-width: 760px)"):]
        self.assertIn(".strategy-attribution-meta", mobile)
        self.assertIn(".strategy-sample-row", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)

    def test_health_status_colors_are_separate_from_market_return_colors(self):
        self.assertNotIn(".status-badge.is-positive,\n.is-up", CSS)
        self.assertNotIn(".status-badge.is-danger,\n.is-down", CSS)
        self.assertIn(".status-badge.is-positive", CSS)
        self.assertIn("color: var(--down-green)", CSS)
        self.assertIn(".status-badge.is-danger", CSS)
        self.assertIn("color: var(--up-red)", CSS)

    def test_whole_page_copy_and_interaction_semantics_are_explicit(self):
        for text in (
            "正式动作：",
            "规则判定：",
            "主要指数上涨数",
            "指标组件覆盖",
            "解析覆盖率",
            "规则生成，未经过 LLM 复核",
            "受保护融合候选全集",
            "正式推荐",
            "当日 ",
            "信号日收盘",
            "结构参考价",
            "未发现已登记风险；不代表无风险",
        ):
            self.assertIn(text, JS)
        self.assertNotIn("当前视图无候选。", JS)
        self.assertIn("function bindSingleOpenDetailsWithin", JS)
        self.assertIn("pending_report_validation", JS)
        self.assertIn("pending|waiting", JS)

        start = JS.index("function buildAuxiliaryStacks")
        end = JS.index("function renderAuxiliaryCenter", start)
        primary = JS[start:end]
        self.assertLess(
            primary.index("renderDecisionDirections(source)"),
            primary.index("renderPersonalWatchlist(source)"),
        )
        self.assertLess(
            primary.index("renderMarketTemperatureCard(source)"),
            primary.index("renderSectorFlowCard(source)"),
        )

    def test_today_workspace_precedes_research_layer_and_tabs_are_accessible(self):
        start = JS.index("function buildAppShell")
        end = JS.index("function getReportDataStatus", start)
        shell = JS[start:end]
        self.assertLess(shell.index('id="todayDecisionView"'), shell.index('id="researchValidationView"'))
        self.assertNotIn('class="top10-widget"', shell)
        for token in (
            'role="tablist"',
            "setAttribute('role', 'tab')",
            "setAttribute('aria-selected'",
            "setAttribute('role', 'tabpanel')",
            "ArrowRight",
            "ArrowLeft",
        ):
            self.assertIn(token, JS)

    def test_direction_summary_and_large_pool_controls_are_above_the_fold(self):
        start = JS.index("function buildAppShell")
        end = JS.index("function getReportDataStatus", start)
        shell = JS[start:end]
        self.assertLess(
            shell.index('id="directionQuickSummary"'),
            shell.index('class="workspace today-workspace"'),
        )
        for token in (
            'id="candidateSearch"',
            'id="candidateCount"',
            'id="candidateMore"',
            "代码 / 名称 / 板块",
            "加载更多",
        ):
            self.assertIn(token, shell)

        quick_start = JS.index("function renderDirectionQuickSummary")
        quick_end = JS.index("function getMarketItems", quick_start)
        quick = JS[quick_start:quick_end]
        self.assertIn("getDirectionMeta(", quick)
        self.assertIn("directionMeta.label", quick)
        self.assertNotIn("direction || '待确认'", quick)

        render_start = JS.index("function renderCandidateList")
        render_end = JS.index("function renderCandidateDetail", render_start)
        renderer = JS[render_start:render_end]
        self.assertIn("items.slice(0, state.candidateLimit)", renderer)
        self.assertIn("显示 ' + visibleItems.length + ' / ' + items.length", renderer)
        self.assertIn("nodes.candidateMore.hidden", renderer)
        self.assertIn("state.candidateLimit += 20", JS)
        self.assertIn("state.candidateLimit = 20", JS)

    def test_mobile_drawer_has_dialog_focus_and_keyboard_contract(self):
        for token in (
            'role="dialog"',
            'aria-modal="true"',
            'aria-hidden="true"',
            "event.key === 'Escape'",
            "event.key !== 'Tab'",
            'drawerReturnFocus',
            'setDrawerBackgroundInert',
        ):
            self.assertIn(token, JS)

    def test_strategy_horizons_stack_on_mobile(self):
        mobile = CSS[CSS.rindex("@media (max-width: 760px)"):]
        self.assertIn(".strategy-returns", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)

    def test_holding_risk_has_no_placeholder_action(self):
        start = JS.index("function renderHoldingRiskSection")
        end = JS.index("function renderStrategyScorecards", start)
        renderer = JS[start:end]
        self.assertNotIn("if (!rows.length) return '';", renderer)
        self.assertIn("position_book", renderer)
        for field in ("position_source", "position_as_of", "confirmed_at"):
            self.assertIn(field, renderer)
        self.assertNotIn("rec.quantity", renderer)
        self.assertNotIn("rec.cost_price", renderer)
        self.assertNotIn("sell_signals", renderer)

    def test_empty_holding_risks_render_position_book_state(self):
        _assert_node_contract(
            self,
            "{ render: renderHoldingRiskSection }",
            r"""
const html = globalThis.__auxTest.render({
  holding_risks: [],
  diagnostics: { position_book: {
    status: 'unconfigured',
    message: '未配置已确认持仓；不显示卖出动作'
  } }
});
assert(html.includes('持仓风险'), 'holding risk card disappeared');
assert(html.includes('未配置'), 'position-book status label missing');
assert(html.includes('未配置已确认持仓；不显示卖出动作'), 'position-book explanation missing');
assert(!html.includes('持仓风险已触发'), 'placeholder risk action was invented');
""",
        )

    def test_position_configuration_diagnostic_is_prioritized_and_explained(self):
        start = JS.index("function renderDiagnosticsCard")
        end = JS.index("function bindSingleOpenDecisionDetails", start)
        renderer = JS[start:end]
        self.assertIn("position_book", renderer)
        self.assertIn("priorityKeys", renderer)
        self.assertIn("value.message", renderer)

    def test_diagnostics_badge_uses_error_warning_normal_and_discloses_count(self):
        _assert_node_contract(
            self,
            "{ render: renderDiagnosticsCard }",
            r"""
const warningData = {
  selection_input_health: {
    status: 'verified',
    formal: { formal_actions_allowed: true, all_formal_actions_allowed: true }
  },
  diagnostics: {
  position_book: { status: 'unconfigured', message: '持仓未配置' },
  data_quality: { warnings: ['重点观察池使用本地回退'] },
  scan: { status: 'ok' }, cache: { status: 'ok' }, a: 1,
  b: 2, c: 3, d: 4, e: 5, f: 6
} };
const warningHtml = globalThis.__auxTest.render(warningData);
assert(warningHtml.includes('有提醒'), 'warning badge missing');
assert(warningHtml.includes('展示 8 &#47; 11 项'), 'displayed/total count missing');
assert(warningHtml.indexOf('重点观察池使用本地回退') < warningHtml.indexOf('持仓未配置'), 'warning row was not prioritized');

const errorHtml = globalThis.__auxTest.render({ diagnostics: {
  scan: { status: 'error', error: '扫描失败' },
  data_quality: { warnings: ['次要提醒'] }
} });
assert(errorHtml.includes('异常'), 'error badge missing');
assert(errorHtml.indexOf('扫描失败') < errorHtml.indexOf('次要提醒'), 'error row was not prioritized');

const normalHtml = globalThis.__auxTest.render({
  selection_input_health: {
    status: 'verified',
    formal: { formal_actions_allowed: true, all_formal_actions_allowed: true }
  },
  diagnostics: { scan: { status: 'ok' } }
});
assert(normalHtml.includes('正常'), 'normal badge missing');

const missingHealthHtml = globalThis.__auxTest.render({ diagnostics: {
  scan: { status: 'ok' }
} });
assert(missingHealthHtml.includes('异常'), 'missing selection health looked normal');
assert(missingHealthHtml.includes('正式策略输入过期、未核验或未记录'), 'missing selection health reason hidden');
""",
        )

    def test_incomplete_ledger_finalization_is_a_visible_error(self):
        _assert_node_contract(
            self,
            "{ render: renderDiagnosticsCard }",
            r"""
const html = globalThis.__auxTest.render({ diagnostics: {
  recommendation_ledger: {
    status: 'finalization_incomplete', today_entries: 2,
    finalized_today_entries: 1, missing_today_entries: 1
  }
} });
assert(html.includes('异常'), 'incomplete ledger looked healthy');
assert(html.includes('账本终结不完整'), 'incomplete ledger lacked a Chinese explanation');
""",
        )

    def test_decision_llm_error_is_really_listed_in_diagnostics(self):
        _assert_node_contract(
            self,
            "{ directions: renderDecisionDirections, diagnostics: renderDiagnosticsCard }",
            r"""
const data = {
  decision_brief: {
    status: 'rules_only',
    llm_error: '模型超时 <secret>',
    theses: []
  },
  diagnostics: { scan: { status: 'ok' } }
};
const directionHtml = globalThis.__auxTest.directions(data);
const diagnosticHtml = globalThis.__auxTest.diagnostics(data);
assert(directionHtml.includes('技术错误已列入数据诊断'), 'direction card made an unverifiable routing claim');
assert(diagnosticHtml.includes('今日方向模型复核'), 'LLM diagnostic label missing');
assert(diagnosticHtml.includes('模型超时 &lt;secret&gt;'), 'LLM error detail missing or unescaped');
assert(diagnosticHtml.includes('异常'), 'LLM error was not prioritized as an error');
""",
        )

    def test_strategy_review_is_bounded_by_scorecard_and_drilldown(self):
        start = JS.index("function renderStrategySampleReturns")
        end = JS.index("function renderDiagnosticsCard", start)
        renderer = JS[start:end]
        self.assertIn("strategy_scorecards", renderer)
        self.assertIn("representative_samples", renderer)
        for field in (
            "gate_outcomes",
            "maturity_by_horizon",
            "metrics_by_horizon",
            "recommendation_id",
            "reason_summary",
            "rec_date",
            "entry_date",
        ):
            self.assertIn(field, renderer)
        self.assertIn("规则判定 推荐 / 观察 / 拒绝", renderer)
        self.assertIn("推荐原因", renderer)
        self.assertNotIn("recent_reviews", renderer)

    def test_strategy_scorecards_show_entry_mode_with_ledger_fallback(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
const html = globalThis.__auxTest.render({
  strategy_scorecards: { schema_version: 2, thresholds: {}, formal: [
    { strategy: 'daily_fusion', name: '融合', version: 'v1', signal_count: 0 },
    { strategy: 'close_research', name: '收盘研究', version: 'v2', entry_mode: 'immediate_close', signal_count: 0 },
    { strategy: 'unknown_mode', name: '未知口径', version: 'v3', signal_count: 0 }
  ], baselines: [], research: [], gates: [] },
  recommendation_ledger: [{ strategy_contributions: [{
    strategy_name: 'daily_fusion', strategy_version: 'v1', entry_mode: 'delay1_open'
  }] }],
  diagnostics: { strategy_review: {} }
});
assert(html.includes('入场口径：T+1开盘'), 'delay1-open entry mode missing');
assert(html.includes('入场口径：信号日收盘'), 'immediate-close entry mode missing');
assert(html.includes('入场口径：未知'), 'unknown entry mode was not explicit');
""",
        )

    def test_shadow_evaluation_card_contract_and_render_order(self):
        start = JS.index("function renderShadowEvaluations")
        end = JS.index("function renderDiagnosticsCard", start)
        renderer = JS[start:end]
        primary_start = JS.index("function buildAuxiliaryStacks")
        primary_end = JS.index("function renderAuxiliaryCenter", primary_start)
        primary = JS[primary_start:primary_end]

        self.assertLess(
            primary.index("renderStrategyScorecards(source)"),
            primary.index("renderShadowEvaluations(source)"),
        )
        self.assertLess(
            primary.index("renderShadowEvaluations(source)"),
            primary.index("renderDiagnosticsCard(source)"),
        )
        for text in (
            "影子评测",
            "影子评测中",
            "不影响正式主推",
            "不是推荐",
            "样本进度",
            "尚未晋级原因",
            "等待首个收盘样本",
            "影子模式已关闭",
            "影子评测暂不可用",
            "正式主推不受影响",
            "信号日收盘",
        ):
            self.assertIn(text, renderer)
        for field in (
            "production_guard",
            "before_sha256",
            "after_sha256",
            "experiments",
            "scorecards",
            "today_entries",
            "today",
            "candidates",
            "sample_size",
            "active_dates",
            "active_months",
            "mean_close_return",
            "median_close_return",
            "up_rate",
            "hit_rate_ge_5",
            "mean_mfe",
            "mean_mae",
            "worst_close_return",
            "excursion_sample_size",
            "representative_samples",
            "hard_gate_reasons",
            "upstream_pool",
            "source_pool",
            "intended_horizon",
            "entry_mode",
            "collection_health",
            "outcome_maturity",
            "comparison_readiness",
            "data_gap",
        ):
            self.assertIn(field, renderer)
        self.assertIn("picks_pure", renderer)
        self.assertIn("原始缠论结构候选 / 共同上游全集", renderer)
        self.assertIn("融合候选全集", renderer)
        self.assertIn("正式推荐", renderer)
        self.assertNotIn("正式融合主推池", renderer)
        self.assertIn("h4_t3_pool", renderer)
        self.assertIn("H4 T+3 策略池", renderer)
        self.assertIn("shadow.affects_production === false", renderer)
        self.assertIn("var disabled = isolated", renderer)
        self.assertIn("var collecting = isolated", renderer)
        self.assertIn("var unavailable = !isolated", renderer)
        self.assertIn("status === 'collecting'", renderer)
        self.assertIn("metrics.promotion_eligible === false", renderer)
        for text in (
            "当前结论",
            "研究层级",
            "不可自动晋级",
            "晋级边界异常",
            "上线后样本 / 前瞻影子",
            "平均期间最高收益（MFE）",
            "平均期间最低收益（MAE）",
            "canonical_kline_invalid",
            "canonical_report_volume_invalid",
            "影子采集失败",
            "本日形成数据缺口",
            "采集成功，今日",
            "T+3 已到期",
            "可进入人工验收",
        ):
            self.assertIn(text, renderer)
        self.assertIn("comparison_status", renderer)
        self.assertIn("research_tier", renderer)
        self.assertIn("promotion_eligible", renderer)
        self.assertNotIn(".slice(", renderer)
        self.assertIn("escapeHtml", renderer)
        self.assertIn('<h4>', renderer)
        self.assertIn('<h5>', renderer)

    def test_shadow_card_uses_swiss_audit_styles_and_390px_layout(self):
        for selector in (
            ".shadow-card",
            ".shadow-guard-rail",
            ".shadow-conclusion-grid",
            ".shadow-metric-grid",
            ".shadow-candidate-row",
        ):
            self.assertIn(selector, CSS)
        shadow_start = CSS.index("/* Shadow evaluation: Swiss audit card */")
        responsive_start = CSS.index("@media (max-width: 390px)", shadow_start)
        shadow_styles = CSS[shadow_start:responsive_start]
        responsive = CSS[responsive_start:]
        self.assertIn("#FFFFFF", shadow_styles)
        self.assertIn("#002FA7", shadow_styles)
        self.assertIn("1px", shadow_styles)
        self.assertIn(
            "grid-template-columns: repeat(6, minmax(0, 1fr));",
            shadow_styles,
        )
        self.assertNotIn("gradient", shadow_styles)
        self.assertIn(".shadow-metric-grid", responsive)
        self.assertIn("grid-template-columns: 1fr", responsive)
        self.assertIn("content-visibility: auto", shadow_styles)

    def test_shadow_renderer_runtime_fail_closes_and_escapes_untrusted_contracts(self):
        script = r"""
const fs = require('fs');
const vm = require('vm');
global.window = { location: { pathname: '' } };
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
  + '\n globalThis.__shadowTest = { render: renderShadowEvaluations };'
  + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
const render = globalThis.__shadowTest.render;
const sha = 'a'.repeat(64);
function fixture() {
  return {
    workspace: { views: { main: [{ code: '300999' }, { code: '301000' }] } },
    shadow_evaluations: {
    schema_version: 1,
    mode: 'shadow',
    affects_production: false,
    status: 'collecting',
    data_gap: false,
    collection_health: {
      status: 'ok',
      candidate_count: 1,
      eligible_count: 1,
      staged_count: 0
    },
    outcome_maturity: {
      t1: { mature: 0, right_censored: 1, unavailable: 0 },
      t3: { mature: 0, right_censored: 1, unavailable: 0 },
      t5: { mature: 0, right_censored: 1, unavailable: 0 }
    },
    comparison_readiness: {
      status: 'insufficient',
      promotion_eligible: false
    },
    production_guard: {
      unchanged: true,
      before_sha256: sha,
      after_sha256: sha
    },
    production_reference: { pool: 'picks_fusion', today_count: 1 },
    experiments: [{
      experiment_id: 'h4-t3-close-review-v1',
      display_name: '<img src=x onerror=alert(1)>'.repeat(40),
      version: 'v1',
      upstream_pool: 'picks_pure',
      source_pool: 'h4_t3_pool',
      intended_horizon: 3,
      entry_mode: 'immediate_close',
      status: 'available',
      affects_production: false,
      promotion_eligible: false,
      comparison_status: 'collecting',
      outcome_maturity: {
        t1: { mature: 0, right_censored: 1, unavailable: 0 },
        t3: { mature: 0, right_censored: 1, unavailable: 0 },
        t5: { mature: 0, right_censored: 1, unavailable: 0 }
      },
      comparison_readiness: {
        status: 'insufficient',
        promotion_eligible: false
      },
      research_tier: 'oot_shadow',
      sample_size: 0,
      active_dates: 0,
      active_months: 0,
      excursion_sample_size: 0,
      hard_gate_reasons: ['mature_samples_below_100'],
      representative_samples: [],
      today: { candidates: [{
        code: '300001',
        name: '<script>alert(7)</script>',
        reference_close: 10,
        evaluation_eligible: true
      }] }
    }],
    scorecards: [],
    today_entries: [],
    pending: { status: 'withheld', entries: 0 }
  } };
}
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function assert(value, message) { if (!value) throw new Error(message); }

const good = render(fixture());
assert(good.includes('正式输出保护通过'), 'valid guard not shown');
assert(good.includes('影子评测中'), 'valid collecting state missing');
assert(good.includes('采集成功，今日 1 只'), 'collection health missing');
assert(good.includes('T+3 已到期'), 'T+3 maturity missing');
assert(good.includes('等待 1'), 'right-censored maturity missing');
assert(good.includes('样本不足'), 'comparison readiness missing');
assert(good.includes('融合候选全集'), 'fusion candidate pool label missing');
assert(good.includes('正式推荐'), 'published main count label missing');
assert(good.includes('2 只'), 'published main count missing');
assert(good.includes('原始缠论结构候选 &#47; 共同上游全集'), 'shared upstream label missing');
assert(!good.includes('<script>alert(7)</script>'), 'candidate XSS not escaped');
assert(good.includes('&lt;script&gt;alert(7)&lt;&#47;script&gt;'), 'escaped candidate absent');
assert(!good.includes('<img src=x onerror=alert(1)>'), 'long title XSS not escaped');

const healthyZero = fixture();
healthyZero.shadow_evaluations.collection_health.candidate_count = 0;
healthyZero.shadow_evaluations.collection_health.eligible_count = 0;
healthyZero.shadow_evaluations.experiments[0].today.candidates = [];
const healthyZeroHtml = render(healthyZero);
assert(healthyZeroHtml.includes('采集成功，今日 0 只'), 'healthy zero cohort hidden');
assert(!healthyZeroHtml.includes('影子评测暂不可用'), 'healthy zero marked unavailable');

const missingCollectionCount = fixture();
delete missingCollectionCount.shadow_evaluations.collection_health.candidate_count;
const missingCollectionHtml = render(missingCollectionCount);
assert(missingCollectionHtml.includes('影子合同字段缺失'), 'missing collection count did not fail closed');
assert(missingCollectionHtml.includes('影子评测暂不可用'), 'missing collection count stayed collecting');
assert(!missingCollectionHtml.includes('采集成功，今日 0 只'), 'missing collection count rendered as zero');

const missingMaturityCount = fixture();
delete missingMaturityCount.shadow_evaluations.outcome_maturity.t3.mature;
const missingMaturityHtml = render(missingMaturityCount);
assert(missingMaturityHtml.includes('影子合同字段缺失'), 'missing maturity count did not fail closed');
assert(missingMaturityHtml.includes('影子评测暂不可用'), 'missing maturity count stayed collecting');
assert(!missingMaturityHtml.includes('影子评测中'), 'partial maturity contract claimed collecting');

const missingPendingCount = fixture();
delete missingPendingCount.shadow_evaluations.pending.entries;
const missingPendingHtml = render(missingPendingCount);
assert(missingPendingHtml.includes('影子合同字段缺失'), 'missing pending count did not fail closed');
assert(!missingPendingHtml.includes('影子批次</span><strong>0 条'), 'missing pending count rendered as zero');

const missingProgressCount = fixture();
delete missingProgressCount.shadow_evaluations.experiments[0].sample_size;
const missingProgressHtml = render(missingProgressCount);
assert(missingProgressHtml.includes('影子合同字段缺失'), 'missing progress count did not fail closed');
assert(!missingProgressHtml.includes('0/100 成熟样本'), 'missing progress count rendered as zero');

const collectionFailed = fixture();
collectionFailed.shadow_evaluations.status = 'unavailable';
collectionFailed.shadow_evaluations.data_gap = true;
collectionFailed.shadow_evaluations.collection_health = {
  status: 'collection_failed',
  failure_stage: 'shadow_input_projection',
  error_code: 'unsupported_type',
  candidate_count: 0,
  eligible_count: 0,
  staged_count: 0
};
collectionFailed.shadow_evaluations.error = 'unsupported_type at $.picks_pure[0].amount';
const collectionFailedHtml = render(collectionFailed);
assert(collectionFailedHtml.includes('影子采集失败'), 'collection failure not explicit');
assert(collectionFailedHtml.includes('本日形成数据缺口'), 'data gap not explicit');
assert(collectionFailedHtml.includes('shadow_input_projection'), 'failure stage hidden');

const mismatch = fixture();
mismatch.shadow_evaluations.production_guard.after_sha256 = 'b'.repeat(64);
const mismatchHtml = render(mismatch);
assert(mismatchHtml.includes('影子评测暂不可用'), 'digest mismatch not failed closed');
assert(!mismatchHtml.includes('正式输出保护通过'), 'digest mismatch claims guard pass');
assert(!mismatchHtml.includes('不影响正式主推'), 'digest mismatch claims isolation');
assert(!mismatchHtml.includes('300001'), 'digest mismatch leaked candidate');

const unknownSchema = fixture();
unknownSchema.shadow_evaluations.schema_version = 2;
const schemaHtml = render(unknownSchema);
assert(schemaHtml.includes('影子评测暂不可用'), 'unknown schema not failed closed');
assert(!schemaHtml.includes('300001'), 'unknown schema leaked candidate');

const topEscalated = fixture();
topEscalated.shadow_evaluations.affects_production = true;
const topEscalatedHtml = render(topEscalated);
assert(topEscalatedHtml.includes('影子评测暂不可用'), 'top escalation not failed closed');
assert(!topEscalatedHtml.includes('不影响正式主推'), 'top escalation claims isolation');
assert(!topEscalatedHtml.includes('300001'), 'top escalation leaked candidate');

const topIsolationMissing = fixture();
delete topIsolationMissing.shadow_evaluations.affects_production;
const topIsolationMissingHtml = render(topIsolationMissing);
assert(topIsolationMissingHtml.includes('影子评测暂不可用'), 'missing top isolation not failed closed');
assert(!topIsolationMissingHtml.includes('300001'), 'missing top isolation leaked candidate');

const unauthorized = fixture();
unauthorized.shadow_evaluations.experiments[0].affects_production = true;
const unauthorizedHtml = render(unauthorized);
assert(unauthorizedHtml.includes('实验合同异常'), 'experiment escalation not warned');
assert(!unauthorizedHtml.includes('300001'), 'experiment escalation leaked candidate');

const wrongEntry = fixture();
wrongEntry.shadow_evaluations.experiments[0].entry_mode = 'delay1_open';
const wrongEntryHtml = render(wrongEntry);
assert(wrongEntryHtml.includes('实验合同异常'), 'wrong entry mode not warned');
assert(!wrongEntryHtml.includes('300001'), 'wrong entry mode leaked candidate');

const promotable = fixture();
promotable.shadow_evaluations.experiments[0].promotion_eligible = true;
const promotableHtml = render(promotable);
assert(promotableHtml.includes('晋级边界异常'), 'promotable experiment not warned');
assert(!promotableHtml.includes('300001'), 'promotable experiment leaked candidate');

const wrongScorecardIdentity = fixture();
wrongScorecardIdentity.shadow_evaluations.scorecards = [{
  experiment_id: 'h4-t3-close-review-v1',
  version: 'v1',
  upstream_pool: 'picks_pure',
  source_pool: 'h4_t3_pool',
  intended_horizon: '3',
  entry_mode: 'immediate_close',
  promotion_eligible: false,
  sample_size: 999,
  mean_close_return: 999
}];
const wrongScorecardHtml = render(wrongScorecardIdentity);
assert(!wrongScorecardHtml.includes('+999.00%'), 'wrong scorecard identity was bound');
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
