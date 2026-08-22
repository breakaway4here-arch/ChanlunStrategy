"""Contract tests for the scan-first auxiliary decision cockpit."""

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = (ROOT / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
CSS = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")


class TestAuxiliaryCockpitContract(unittest.TestCase):
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
        self.assertIn("if (!rows.length) return '';", renderer)
        for field in ("position_source", "position_as_of", "confirmed_at"):
            self.assertIn(field, renderer)
        self.assertNotIn("rec.quantity", renderer)
        self.assertNotIn("rec.cost_price", renderer)
        self.assertNotIn("sell_signals", renderer)

    def test_position_configuration_diagnostic_is_prioritized_and_explained(self):
        start = JS.index("function renderDiagnosticsCard")
        end = JS.index("function bindSingleOpenDecisionDetails", start)
        renderer = JS[start:end]
        self.assertIn("position_book", renderer)
        self.assertIn("priorityKeys", renderer)
        self.assertIn("value.message", renderer)

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
        ):
            self.assertIn(field, renderer)
        self.assertIn("picks_pure", renderer)
        self.assertIn("原始缠论结构候选（基准）", renderer)
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
  return { shadow_evaluations: {
    schema_version: 1,
    mode: 'shadow',
    affects_production: false,
    status: 'collecting',
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
assert(!good.includes('<script>alert(7)</script>'), 'candidate XSS not escaped');
assert(good.includes('&lt;script&gt;alert(7)&lt;&#47;script&gt;'), 'escaped candidate absent');
assert(!good.includes('<img src=x onerror=alert(1)>'), 'long title XSS not escaped');

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
