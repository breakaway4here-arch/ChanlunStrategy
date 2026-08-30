"""RED contracts for the eight-module recommendation evidence detail.

These tests intentionally target the HTML-only evidence surface before the
production renderer is implemented.  Keep them separate from the existing
cockpit contract tests so the implementation agent can turn this file green
without touching unrelated frontend behavior.
"""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class TestRecommendationEvidenceDetailContract(unittest.TestCase):
    def test_detail_renders_eight_modules_in_order_with_chart_between_price_and_daily(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, state: state }",
            r"""
const section = function (extra) {
  return Object.assign({
    status: 'available',
    as_of: '2026-08-28',
    source: 'fixture.evidence',
  }, extra || {});
};
global.window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [{
      view: 'main', code: '600001',
      summary: section({ code: '600001', name: '证据股', sector: '工业', formal_action: '可上车' }),
      decision_score: section({ score: 88, components: {
        structure: { score: 30, reasons: ['结构支持'] },
        position: { score: 28, reasons: ['位置适中'] },
        sentiment: { score: 30, reasons: ['情绪支持'] }
      }}),
      rank_evidence: section({ view_rank: 1, opportunity_score: 97, note: '仅用于当前池内排序' }),
      price_evidence: section({ current_price: 10, reference_price: 9.5, pressure_price: 11, invalidation_price: 9 }),
      daily_structure: section({ trend: '上行', stage: '突破' }),
      sublevel_30m: section({ status: 'partial', summary: '部分确认' }),
      volume_and_capital: section({ volume_ratio: 1.4 }),
      market_and_sector: section({ market: '支持', sector: '支持' }),
      risk_and_next: section({ risk_labels: [], next_confirmation: { items: ['放量站稳'] } }),
      historical_validation: section({ summary: '样本进度' }),
      display_derived: section({ distance_from_reference_pct: 5.2632 })
    }]}
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001', name: '证据股', sector: '工业',
  ref: { pool: 'picks_fusion', code: '600001' },
  formal_decision_contract: { action: '可上车' }
}, {
  code: '600001',
  dates: ['2026-08-27', '2026-08-28'],
  opens: [9.8, 10], highs: [10.2, 10.6], lows: [9.5, 9.8], closes: [10, 10.4],
  volumes: [100, 140], macd_hist: [0.1, 0.2],
  chart_annotations: { markPoints: [], markLines: [] }
});
const modules = [
  '01', '02', '03', '04', '05', '06', '07', '08'
].map(function (number) {
  return 'data-evidence-module="' + number + '"';
});
const positions = modules.map(function (marker) { return html.indexOf(marker); });
assert(positions.every(function (position) { return position >= 0; }), '八个证据模块未完整渲染');
assert(positions.every(function (position, index) {
  return index === 0 || position > positions[index - 1];
}), '八模块顺序未按 01-08 固定');
const chart = html.indexOf('class="chart-panel"');
assert(chart > positions[1] && chart < positions[2], '图表没有位于 02 与 03 之间');
""",
        )

    def test_detail_has_one_formal_action_and_separates_decision_score_from_rank_evidence(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, state: state }",
            r"""
global.window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [{
      code: '600001',
      summary: { status: 'available', as_of: '2026-08-28', source: 'summary', formal_action: '观察' },
      decision_score: { status: 'available', as_of: '2026-08-28', source: 'decision', score: 62,
        components: { structure: { score: 10 }, position: { score: 15 }, sentiment: { score: 37 } } },
      rank_evidence: { status: 'available', as_of: '2026-08-28', source: 'rank', view_rank: 1,
        opportunity_score: 97, note: '仅用于当前池内排序' }
    }]}
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001', name: '测试股', sector: '工业', opportunity_score: 97,
  strategy_stances: [{ strategy: 'H4', stance: 'support', action: '买入' }],
  ai_research: { summary: '研究提示', action: '卖出' },
  formal_decision_contract: { action: '观察', reference_price: 10 }
}, {
  decision_engine_v1: { decision_code: 'observe', opportunity_score: 97 }
});
assert((html.match(/formal-action/g) || []).length === 1, '详情出现第二个正式动作');
assert(html.includes('决策分') && html.includes('结构') && html.includes('位置') && html.includes('情绪'),
  '决策分及结构/位置/情绪分项未展示');
assert(html.includes('排序证据') && html.includes('仅用于当前池内排序'),
  '排序证据缺少独立解释');
assert(!html.includes('评分 97') && !html.includes('决策分 97'),
  'opportunity_score 被错误回退为决策分');
assert(!html.includes('买入') && !html.includes('卖出'), '策略或 AI 动作泄漏为正式动作');
""",
        )

    def test_detail_fails_closed_for_missing_evidence_without_zero_or_default_targets(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, state: state }",
            r"""
global.window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [{
      code: '600001',
      summary: { status: 'available', as_of: '2026-08-28', source: 'summary', formal_action: '观察' },
      decision_score: { status: 'missing', source: 'decision', score: null, reason: 'decision_score_not_provided' },
      rank_evidence: { status: 'missing', source: 'rank', view_rank: null, opportunity_score: null, reason: 'rank_evidence_not_provided' },
      price_evidence: { status: 'missing', as_of: '2026-08-28', source: 'price',
        current_price: null, reference_price: null, pressure_price: null,
        invalidation_price: null, trailing_targets: [],
        reason: 'verified_prices_not_provided' },
      daily_structure: { status: 'missing', source: 'daily', reason: 'daily_not_serialized' },
      sublevel_30m: { status: 'missing', source: '30m', reason: 'minute_data_not_serialized' },
      volume_and_capital: { status: 'missing', source: 'volume', reason: 'funds_not_verified' },
      market_and_sector: { status: 'missing', source: 'sector', reason: 'sector_not_verified' },
      risk_and_next: { status: 'missing', source: 'risk', reason: 'strategy_risk_and_conditions_not_declared' },
      historical_validation: { status: 'missing', source: 'history', reason: 'sample_insufficient' },
      display_derived: { status: 'missing', source: 'derived', reason: 'real_price_boundaries_incomplete' }
    }]}
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001', name: '缺证据股', ref: { pool: 'picks_fusion', code: '600001' },
  formal_decision_contract: { action: '观察' }
}, {});
assert(html.includes('本期未形成可验证压力位'), '缺失压力位没有 fail-closed 文案');
assert(html.includes('本期未形成可验证失效位'), '缺失失效位没有 fail-closed 文案');
assert(html.includes('本期未形成分级目标'), '缺失目标没有 fail-closed 文案');
assert(html.includes('30分钟数据未序列化') || html.includes('分钟数据未序列化'),
  '缺失 30m 证据没有明确说明');
assert(!html.includes('0.00') && !html.includes('目标 5%') && !html.includes('目标 10%'),
  '缺失证据生成了零值或默认目标');
assert(!html.includes('决策分</span><strong>0') && !html.includes('池内 #0') && !html.includes('排序分 0'),
  '缺失决策或排序证据被渲染成零分');
""",
        )

    def test_detail_escapes_evidence_text_and_exposes_source_date_status(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, state: state }",
            r"""
global.window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [{
      code: '600001',
      summary: { status: 'available', as_of: '2026-08-28', source: '<script>summary</script>',
        name: '<img src=x onerror=alert(1)>', formal_action: '观察' },
      decision_score: { status: 'available', as_of: '2026-08-28', source: 'decision', score: 80,
        components: { structure: { score: 30, reasons: ['<b>危险</b>'] } } },
      rank_evidence: { status: 'available', as_of: '2026-08-28', source: 'rank',
        view_rank: 1, opportunity_score: 55, note: '仅用于当前池内排序' },
      price_evidence: { status: 'partial', as_of: '2026-08-28', source: 'price',
        current_price: 10, reference_price: null, pressure_price: null, invalidation_price: null,
        trailing_targets: [], reason: '<em>missing</em>' },
      daily_structure: { status: 'missing', source: 'daily', reason: '<svg onload=alert(1)>' },
      sublevel_30m: { status: 'missing', source: '30m', reason: 'minute_data_not_serialized' },
      volume_and_capital: { status: 'missing', source: 'volume', reason: 'funds_not_verified' },
      market_and_sector: { status: 'missing', source: 'sector', reason: 'sector_not_verified' },
      risk_and_next: { status: 'missing', source: 'risk', reason: 'strategy_risk_and_conditions_not_declared' },
      historical_validation: { status: 'missing', source: 'history', reason: 'sample_insufficient' },
      display_derived: { status: 'missing', source: 'derived', reason: 'real_price_boundaries_incomplete' }
    }]}
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001', name: '安全名称', ref: { pool: 'picks_fusion', code: '600001' },
  formal_decision_contract: { action: '观察' }
}, {});
assert(html.includes('2026-08-28'), '证据 as_of/日报日期未展示');
assert(html.includes('来源') && html.includes('状态'), '证据来源/状态元数据未展示');
assert(html.includes('&lt;script&gt;summary&lt;&#47;script&gt;'), '证据 source 未转义');
assert(html.includes('&lt;img src=x onerror=alert(1)&gt;'), '证据名称未转义');
assert(html.includes('&lt;svg onload=alert(1)&gt;'), '证据 reason 未转义');
assert(!html.includes('<script>summary</script>') && !html.includes('<img src=x onerror=alert(1)>'),
  '详情输出了未转义证据 HTML');
""",
        )

    def test_incident_review_keeps_shared_renderer_but_never_restores_executable_action(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, state: state }",
            r"""
global.window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [{
      code: '600001',
      summary: { status: 'available', as_of: '2026-08-28', source: 'summary', formal_action: '可上车' },
      decision_score: { status: 'missing', source: 'decision' },
      rank_evidence: { status: 'missing', source: 'rank' },
      price_evidence: { status: 'missing', source: 'price' },
      daily_structure: { status: 'missing', source: 'daily' },
      sublevel_30m: { status: 'missing', source: '30m' },
      volume_and_capital: { status: 'missing', source: 'volume' },
      market_and_sector: { status: 'missing', source: 'sector' },
      risk_and_next: { status: 'missing', source: 'risk' },
      historical_validation: { status: 'missing', source: 'history' },
      display_derived: { status: 'missing', source: 'derived' }
    }]}
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001', name: '历史票', incident_review_only: true,
  ref: { pool: 'picks_fusion', code: '600001' },
  formal_decision_contract: { action: '可上车' },
  action: '可上车', effective_action: '可上车'
}, {});
assert(!html.includes('正式动作：可上车'), '事故复盘恢复了可执行正式动作');
assert(html.includes('仅追溯') || html.includes('评分不生效'), '事故复盘边界未展示');
""",
        )

    def test_desktop_and_mobile_detail_paths_share_the_same_eight_module_builder(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, render: renderCandidateDetail, open: openMobileDetailDrawer, state: state, nodes: nodes }",
            r"""
const detailSource = String(globalThis.__auxTest.render);
const drawerSource = String(globalThis.__auxTest.open);
assert(detailSource.includes('buildMergedCandidateDetail'), '桌面详情没有使用统一详情构建器');
assert(drawerSource.includes('renderCandidateDetail(state.activeItem, nodes.drawerContent)'),
  '移动抽屉没有复用统一详情构建器');
assert(detailSource.includes('target = target || nodes.detailPanel'), '详情没有保留桌面/抽屉 target 参数');
""",
        )

    def test_legacy_or_mismatched_evidence_keeps_chart_with_explicit_missing_copy(self):
        _assert_node_contract(
            self,
            "{ detail: buildMergedCandidateDetail, state: state }",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const item = {
  code: '600001', name: '历史票', ref: { pool: 'picks_fusion', code: '600001' },
  formal_decision_contract: { action: '观察' }
};
const raw = {
  dates: ['2026-08-27', '2026-08-28'],
  opens: [9.8, 10], highs: [10.2, 10.6], lows: [9.5, 9.8], closes: [10, 10.4],
  volumes: [100, 140], macd_hist: [0.1, 0.2],
  chart_annotations: { markPoints: [], markLines: [] }
};
[
  {},
  { recommendationEvidence: {} },
  { recommendationEvidence: { schema_version: 99, report_date: '2026-08-28', views: { main: [] } } },
  { recommendationEvidence: { schema_version: 1, report_date: '2026-08-27', views: { main: [] } } }
].forEach(function (bootstrap) {
  window.CHANLUN_BOOTSTRAP = bootstrap;
  const html = globalThis.__auxTest.detail(item, raw);
  assert(html.includes('本期未提供证据展示'), 'legacy detail did not fail closed explicitly');
  assert(html.includes('class="chart-panel"'), 'legacy detail lost its K-line workspace');
  assert(html.includes('id="chartCanvas"'), 'legacy detail lost the chart mount');
  assert(!html.includes('formal-action'), 'missing evidence restored an unverified formal action');
});
""",
        )


if __name__ == "__main__":
    unittest.main()
