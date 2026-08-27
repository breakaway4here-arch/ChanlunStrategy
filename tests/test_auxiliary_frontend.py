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
    def test_historical_reconstruction_is_visibly_non_actionable(self):
        _assert_node_contract(
            self,
            "{ render: renderHistoricalReconstruction }",
            r"""
const mount = { innerHTML: '', className: '' };
const html = globalThis.__auxTest.render({ historical_reconstruction: {
  report_date: '2026-08-26', acquired_at: '2026-08-27T12:00:00+08:00',
  input: { latest_ts: '2026-08-26 15:00:00', status: 'verified' },
  original_publication: { main_count: 0, raw_main_candidate_count: 1 },
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
assert(html.includes('原始候选 1 只因分钟数据未核验而封闭'), 'incident cause hidden');
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
globalThis.__auxTest.state.data = { selection_input_health: {
  schema_version: 2,
  by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
} };
assert(globalThis.__auxTest.action({
  action: '可上车', effective_action: '可上车', action_semantics: 'formal',
  is_formal_recommendation: true
}, 'main') === '可上车', 'verified formal action was suppressed');
globalThis.__auxTest.state.data = {};
assert(globalThis.__auxTest.action({
  action: '可上车', effective_action: '可上车', action_semantics: 'formal',
  is_formal_recommendation: true
}, 'main').includes('已封闭'), 'missing formal health failed open');
globalThis.__auxTest.state.data = { selection_input_health: {
  schema_version: 2,
  by_strategy: { h4_t3: { status: 'unavailable', formal_actions_allowed: false } }
} };
assert(globalThis.__auxTest.action({ action: '可上车', action_semantics: 'formal' }, 'h4_t3')
  .includes('已封闭'), 'blocked H4 action failed open');
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
assert(unavailable.includes('数据不可用'), 'missing sector source looked like an empty result');
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
assert(globalThis.__auxTest.pageAction('formal', { state: 'unavailable' }) === '正式动作已封闭', 'unavailable formal view still advertised actions');
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
assert(unavailable.title === '数据不可用', 'unavailable pool mislabeled as empty');
""",
        )

    def test_workspace_tabs_print_the_state_not_only_a_colored_dot(self):
        start = JS.index("function renderWorkspaceTabs")
        end = JS.index("function renderViewDescription", start)
        renderer = JS[start:end]
        self.assertIn("workspace-tab-status", renderer)
        self.assertIn("availability.label", renderer)
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
assert(blocked.includes('正式动作已封闭'), 'invalid strategy input looked healthy');
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
assert(html.includes('页面动作：仅观察'), 'research action cap hidden');
assert(html.includes('跨池观察排序靠前'), 'page reason hidden');
assert(!html.includes('偏执行优先'), 'formal action reason leaked into research conclusion');
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
        start = JS.index("function renderAuxiliaryCenter")
        end = JS.index("function openMobileDetailDrawer", start)
        primary = JS[start:end]
        for call in (
            "renderSectorFlowCard(data)",
            "renderDecisionDirections(data)",
            "renderPersonalWatchlist(data)",
            "renderLimitUpEcologyCard(data)",
            "renderHoldingRiskSection(data)",
            "renderStrategyScorecards(data)",
            "renderShadowEvaluations(data)",
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
assert(html.includes('0.00%'), 'real zero was hidden');
assert(html.includes('等待到期'), 'right-censored horizon was not explicit');
assert(html.includes('参考收盘价缺失'), 'blocking reason was not translated');
assert(html.includes('≥5%命中'), 'high-return metric missing');
assert(html.includes('期间最高'), 'period high missing');
assert(html.includes('期间最低'), 'period low missing');
assert(html.includes('该门控不计算收益'), 'gate was presented as return strategy');
assert(html.includes('1 条账本身份无法安全分类'), 'classification failures were silently hidden');
assert(html.includes('罗姐主题策略'), 'known historical name was not normalized');
assert(!html.includes('罗杰主题策略'), 'legacy typo leaked into current UI');
assert(!html.includes('MAE'), 'internal MAE leaked to user');
assert(!html.includes('MFE'), 'internal MFE leaked to user');
assert(!html.includes('/20'), 'obsolete hard-coded threshold leaked');
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
assert(!emptyHtml.includes('<strong>数据不可用</strong>'), 'normal empty looked broken');
const disabledHtml = globalThis.__auxTest.horizon(
  't1', {}, { mature: 0, waiting: 0, unavailable: 0 },
  false, [], 'disabled'
);
assert(disabledHtml.includes('今日未启用'), 'disabled horizon was not neutral');
assert(!disabledHtml.includes('<strong>数据不可用</strong>'), 'disabled strategy looked broken');
const staleHtml = globalThis.__auxTest.horizon(
  't1', {}, { mature: 0, waiting: 0, unavailable: 1 },
  false, ['strategy_input_stale_or_unverified'], 'data_unavailable'
);
assert(staleHtml.includes('策略输入日期过期或未核验，禁止评分'), 'stale input blocker was not explained');
assert(staleHtml.includes('<strong>数据不可用</strong>'), 'stale input did not fail closed');
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
    source_pool: source, entry_mode: 'immediate_close', signal_count: 1,
    eligible_signal_count: 1, episode_count: 1, active_dates: 1, active_months: 1,
    evidence_tier: role === 'baseline' ? 'legacy_inferred' : 'prospective_ledger',
    evaluation_status: 'collecting', metrics_publishable: true,
    maturity_by_horizon: {
      t1: { mature: 1, waiting: 0, unavailable: 0 },
      t3: { mature: 0, waiting: 1, unavailable: 0 },
      t5: { mature: 0, waiting: 1, unavailable: 0 }
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
            ".aux-grid.decision-grid {\n    grid-template-columns: repeat(2, minmax(0, 1fr));",
            tablet,
        )
        self.assertIn(
            ".personal-watchlist-card,\n  .strategy-scorecards-card,\n  .decision-card.shadow-card {\n    grid-column: span 2;",
            tablet,
        )
        self.assertIn(".strategy-scorecards-card", tablet)
        self.assertIn(".decision-card.shadow-card", tablet)

    def test_dense_evaluation_cards_use_full_desktop_width(self):
        desktop = CSS[:CSS.index("@media (max-width: 1180px)")]
        self.assertIn(
            ".strategy-scorecards-card,\n.decision-card.shadow-card {\n  grid-column: span 4;",
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
            "页面动作：",
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

        start = JS.index("function renderAuxiliaryCenter")
        end = JS.index("function openMobileDetailDrawer", start)
        primary = JS[start:end]
        self.assertLess(
            primary.index("renderMarketTemperatureCard(data)"),
            primary.index("renderDecisionDirections(data)"),
        )
        self.assertLess(
            primary.index("renderDecisionDirections(data)"),
            primary.index("renderSectorFlowCard(data)"),
        )

    def test_formal_workspace_precedes_manual_top10_and_tabs_are_accessible(self):
        start = JS.index("function buildAppShell")
        end = JS.index("function getReportDataStatus", start)
        shell = JS[start:end]
        self.assertLess(shell.index('class="workspace"'), shell.index('class="top10-widget"'))
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
            shell.index('class="workspace"'),
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
        primary_start = JS.index("function renderAuxiliaryCenter")
        primary_end = JS.index("function openMobileDetailDrawer", primary_start)
        primary = JS[primary_start:primary_end]

        self.assertLess(
            primary.index("renderStrategyScorecards(data)"),
            primary.index("renderShadowEvaluations(data)"),
        )
        self.assertLess(
            primary.index("renderShadowEvaluations(data)"),
            primary.index("renderDiagnosticsCard(data)"),
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
