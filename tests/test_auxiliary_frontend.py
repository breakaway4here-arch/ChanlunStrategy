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
        start = JS.index("function renderWatchDirectionAnalysis")
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
        self.assertIn("目标周期：", renderer)
        self.assertIn("个评测分组", renderer)
        self.assertNotIn("个策略'", renderer)

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
            ".personal-watchlist-card {\n    grid-column: span 2;",
            tablet,
        )

    def test_strategy_attribution_drilldown_stacks_on_mobile(self):
        mobile = CSS[CSS.rindex("@media (max-width: 760px)"):]
        self.assertIn(".strategy-attribution-meta", mobile)
        self.assertIn(".strategy-sample-row", mobile)
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
const warningData = { diagnostics: {
  position_book: { status: 'unconfigured', message: '持仓未配置' },
  data_quality: { warnings: ['重点观察池使用本地回退'] },
  scan: { status: 'ok' }, cache: { status: 'ok' }, a: 1,
  b: 2, c: 3, d: 4, e: 5, f: 6
} };
const warningHtml = globalThis.__auxTest.render(warningData);
assert(warningHtml.includes('有提醒'), 'warning badge missing');
assert(warningHtml.includes('展示 8 &#47; 10 项'), 'displayed/total count missing');
assert(warningHtml.indexOf('重点观察池使用本地回退') < warningHtml.indexOf('持仓未配置'), 'warning row was not prioritized');

const errorHtml = globalThis.__auxTest.render({ diagnostics: {
  scan: { status: 'error', error: '扫描失败' },
  data_quality: { warnings: ['次要提醒'] }
} });
assert(errorHtml.includes('异常'), 'error badge missing');
assert(errorHtml.indexOf('扫描失败') < errorHtml.indexOf('次要提醒'), 'error row was not prioritized');

const normalHtml = globalThis.__auxTest.render({ diagnostics: {
  scan: { status: 'ok' }
} });
assert(normalHtml.includes('正常'), 'normal badge missing');
""",
        )

    def test_strategy_review_is_bounded_by_scorecard_and_drilldown(self):
        start = JS.index("function renderStrategyScorecards")
        end = JS.index("function renderDiagnosticsCard", start)
        renderer = JS[start:end]
        self.assertIn("strategy_scorecards", renderer)
        self.assertIn("representative_samples", renderer)
        for field in (
            "gate_outcomes",
            "matured_by_horizon",
            "recommendation_id",
            "reason_summary",
            "rec_date",
            "entry_date",
        ):
            self.assertIn(field, renderer)
        self.assertIn("推荐 / 观察 / 拒绝", renderer)
        self.assertIn("推荐原因", renderer)
        self.assertNotIn("recent_reviews", renderer)

    def test_strategy_scorecards_show_entry_mode_with_ledger_fallback(self):
        _assert_node_contract(
            self,
            "{ render: renderStrategyScorecards }",
            r"""
const html = globalThis.__auxTest.render({
  strategy_scorecards: [
    { strategy: 'daily_fusion', name: '融合', version: 'v1', sample_size: 0 },
    { strategy: 'close_research', name: '收盘研究', version: 'v2', entry_mode: 'immediate_close', sample_size: 0 },
    { strategy: 'unknown_mode', name: '未知口径', version: 'v3', sample_size: 0 }
  ],
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
        self.assertIn("页面主推", renderer)
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
assert(good.includes('页面主推'), 'published main count label missing');
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
