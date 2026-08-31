"""Frontend completion contracts for recommendation evidence modules 01-06."""

import unittest

from tests.test_auxiliary_frontend import ROOT, _assert_node_contract


FIXTURE = r"""
const section = function (extra) {
  return Object.assign({
    status: 'available',
    as_of: '2026-08-28',
    source: 'fixture.evidence'
  }, extra || {});
};
const evidence = {
  view: 'main',
  code: '600001',
  summary: section({
    name: '证据股<script>alert(1)</script>',
    sector: '半导体<img src=x onerror=alert(2)>',
    formal_action: '观察',
    formal_action_reason: '等待结构确认',
    pool_identity: 'picks_fusion',
    view_identity: 'main',
    view_rank: 2,
    signal_type: '三买<svg onload=alert(3)>',
    signal_date: '2026-08-28',
    signal_age_days: 0,
    applicable_horizon: 3,
    applicable_horizon_text: 'T+3',
    data_latest_date: '2026-08-28',
    data_source: 'market_history_db<script>alert(4)</script>',
    data_health: 'verified',
    data_is_final: true,
    data_stale: false
  }),
  decision_score: section({
    score: 62,
    decision_code: 'recommend',
    components: {
      structure: { score: 20, reasons: ['结构支持'] },
      position: { score: 18, reasons: ['位置适中'] },
      sentiment: { score: 24, reasons: ['情绪支持'] }
    }
  }),
  rank_evidence: section({
    view_rank: 2,
    opportunity_score: 88,
    note: '仅用于当前池内排序'
  }),
  price_evidence: section({
    status: 'conflict',
    current_price: 19.8,
    current_price_source: 'serialized.close',
    reference_price: 18.9,
    reference_price_source: 'workspace.formal_decision_contract.reference_price',
    pressure_price: null,
    invalidation_price: 17.2,
    trailing_targets: [{ price: 22.3, label: 'T+3' }],
    pivot_zg: 20.5,
    pivot_zg_source: 'serialized.pivots.ZG<script>alert(5)</script>',
    pivot_zd: 17.8,
    pivot_zd_source: 'serialized.pivots.ZD',
    platform_high: 21.2,
    platform_high_source: 'serialized.platform_high',
    buy_point_price: 18.6,
    buy_point_price_source: 'serialized.best_buy_point.price',
    audit_reasons: { pressure_price: 'conflict' }
  }),
  daily_structure: section({
    summary: '20日平台突破',
    trend: '上涨趋势',
    stage: '突破',
    signal: '三买',
    signal_date: '2026-08-28',
    signal_age_days: 0,
    signal_reason: '中枢上沿回踩<img src=x onerror=alert(6)>',
    buy_point_price: 18.6,
    health: 'verified',
    latest_date: '2026-08-28',
    data_source: 'market_history_db',
    is_final: true,
    stale: false,
    pivots: { ZG: 20.5, ZD: 17.8, count: 2 },
    ma5: null,
    ma10: null,
    ma20: 18.2,
    ma50: 16.9,
    ma_bullish: false,
    macd: 'DIF/DEA 0轴上',
    missing_evidence: ['MA5、MA10 当前值未提供<script>alert(7)</script>']
  }),
  sublevel_30m: section({
    summary: '部分确认',
    reason: '30分钟确认原因仅来自当前证据<script>alert(15)</script>',
    confirmation_status: 'partial',
    latest_date: '2026-08-28',
    latest_ts: '2026-08-28 14:30:00',
    bars: 32,
    is_final: true,
    stale: false,
    ema5: 309.1,
    ema10: 304.8,
    ema5_direction: '上行',
    ema10_direction: '走平',
    close: 309.85,
    close_above_ema5: true,
    close_above_ema10: true,
    macd_dif: 8.3,
    macd_dea: 7.6,
    macd_state: '柱体缩短',
    breakout_holds: true,
    pullback_volume_state: '缩量',
    missing_evidence: ['MACD柱体连续性未提供<img src=x onerror=alert(8)>']
  }),
  volume_and_capital: section({
    summary: '量价与资金证据',
    current_volume: 123456,
    average_volume_5: 100000,
    volume20: 90000,
    volume_ratio: 1.37,
    turnover_rate: 4.82,
    volume_labels: ['放量突破', '缩量回踩<script>alert(9)</script>'],
    stock_net_flow: 12000000,
    stock_net_inflow_days: 3,
    sector_money_flow: 830000000,
    sector_money_flow_text: '8.3亿',
    sector_capital_flow: { status: 'available', rank: 4 },
    capital_alignment_state: '个股与板块资金同向',
    missing_evidence: ['换手率来源明细未提供<svg onload=alert(10)>']
  }),
  market_and_sector: section({
    summary: '正式市场偏强；板块正反证据分歧',
    market: '62 / 100 · 偏强',
    market_label: '偏强',
    market_sentiment_score: 62,
    formal_market_sentiment: {
      components: { breadth: 41, limit_ecology: 63, index: 52, turnover: 74, trend: 85 }
    },
    sector: '半导体',
    sector_state: '证据部分可用 · 方向未知',
    sector_layer_state: '风险',
    sector_change_pct: 3.21,
    sector_up_count: 36,
    sector_total_count: 52,
    sector_limit_up_count: 4,
    sector_net_flow: 830000000,
    sector_market_rank: 4,
    stock_relative_strength: '板块内偏强<script>alert(11)</script>',
    market_state: '支持',
    stock_state: '风险',
    missing_evidence: ['板块层级去重状态未提供<img src=x onerror=alert(12)>']
  }),
  main_rise_clue: section({
    clue_type: 'trend_continuation',
    label: '趋势延续线索',
    supporting_evidence: ['日线趋势延续'],
    opposing_evidence: [],
    evidence_guards: ['30分钟证据缺失，相关确认未纳入主升浪支持项<script>alert(13)</script>'],
    note: '只翻译现有证据，不生成正式动作'
  }),
  risk_and_next: section({
    risk_labels: [],
    event_risk_status: 'available',
    event_risk_source: 'formal_daily_report<script>alert(16)</script>',
    event_risk_as_of: '2026-08-28<img src=x onerror=alert(17)>',
    event_risks: [
      '公告风险：股东减持<script>alert(14)</script>',
      { label: '结构化风险不得字符串化', reason: '对象不是展示合同' }
    ],
    next_confirmation: { items: [] },
    keep_conditions: { items: [] },
    retest_conditions: { items: [] },
    cancel_conditions: { items: [] },
    invalidation_conditions: { items: [] }
  }),
  historical_validation: section({ summary: '样本采集中', progress_by_horizon: {}, metrics_by_horizon: {} }),
  display_derived: section({ distance_from_reference_pct: 4.76 })
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [evidence] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600001',
  name: '证据股',
  sector: '半导体',
  ref: { pool: 'picks_fusion', code: '600001' },
  formal_decision_contract: { action: '观察' }
}, {});
function moduleHtml(number, nextNumber) {
  const start = html.indexOf('data-evidence-module="' + number + '"');
  const end = nextNumber
    ? html.indexOf('data-evidence-module="' + nextNumber + '"', start + 1)
    : html.length;
  assert(start >= 0 && end > start, 'module ' + number + ' missing');
  return html.slice(start, end);
}
"""


class RecommendationEvidenceFrontendCompletionTests(unittest.TestCase):
    def test_all_frontend_assets_exclude_internal_unavailable_terms(self):
        forbidden = ("数据不可用", "正式动作已封闭")
        asset_paths = []
        for base in (ROOT / "chanlun" / "report_assets", ROOT / "docs" / "assets"):
            asset_paths.extend(
                path for path in base.rglob("*")
                if path.is_file() and path.suffix in {".js", ".css", ".html"}
            )
        self.assertTrue(asset_paths)
        for path in asset_paths:
            text = path.read_text(encoding="utf-8")
            for term in forbidden:
                self.assertNotIn(term, text, f"{path} leaked internal UI term {term}")

    def test_user_facing_statuses_translate_internal_terms_without_mutation(self):
        _assert_node_contract(
            self,
            "({ empty: buildCandidateEmptyState, message: getViewAvailabilityMessage, meta: getViewAvailabilityMeta, pageAction: getViewPageActionLabel, action: resolvePageAction, reportStatus: getReportDataStatus, sector: getSectorFlowStatus, scoreStatus: getScorecardStatusMeta, horizon: renderStrategyHorizon, block: getStrategyViewBlockingReason, state: state })",
            r"""
const availability = {
  state: 'unavailable',
  reason: '数据不可用；正式动作已封闭；reason_code 保留在底层'
};
const beforeAvailability = JSON.stringify(availability);
const researchEmpty = globalThis.__auxTest.empty('luojie', availability, { filtered: false });
const message = globalThis.__auxTest.message({ availability: availability });
const meta = globalThis.__auxTest.meta(availability);
const pageAction = globalThis.__auxTest.pageAction('formal', availability);
globalThis.__auxTest.state.data = {};
const action = globalThis.__auxTest.action({ action_semantics: 'formal' }, 'main');
const reportStatus = globalThis.__auxTest.reportStatus({
  data_quality: {},
  selection_input_health: { formal: { formal_actions_allowed: false } }
});
const sector = globalThis.__auxTest.sector({}, [], []);
const scoreStatus = globalThis.__auxTest.scoreStatus('data_unavailable');
const horizon = globalThis.__auxTest.horizon(
  't3', {}, {}, false, ['market_data_unavailable'], 'running', {}, ''
);
const block = globalThis.__auxTest.block({}, 'main');
const visible = [
  researchEmpty, message.title, message.detail, meta.label, pageAction,
  action, reportStatus, sector.label, sector.detail, scoreStatus.label,
  horizon, block
].join('\n');
['数据不可用', '正式动作已封闭'].forEach(function (term) {
  assert(!visible.includes(term), 'user-facing status leaked internal term: ' + term);
});
assert(researchEmpty.includes('证据不足') && sector.label.includes('证据不足'),
  'research evidence gaps lack user-readable evidence wording');
assert(pageAction === '本期未选出推荐票' && action === '本期未选出推荐票',
  'formal action gap is not unified to the formal empty copy');
assert(reportStatus.includes('本期未选出推荐票') && block.includes('本期未选出推荐票'),
  'formal status copy is not unified to the formal empty copy');
assert(JSON.stringify(availability) === beforeAvailability,
  'display translation mutated the underlying availability reason/state');
""",
        )

    def test_decision_score_badges_only_accept_formal_total_score(self):
        _assert_node_contract(
            self,
            "({ score: getDecisionScore, badge: renderDecisionBadge, summary: getDecisionEngineSummary })",
            r"""
const rankingOnly = {
  decision: '观察', score: 88, final_score: 77, opportunity_score: 99,
  structure: { score: 20 }, position: { score: 18 }, sentiment: { score: 24 }
};
const before = JSON.stringify(rankingOnly);
assert(globalThis.__auxTest.score(rankingOnly) === null,
  'decision score fell back to score/final_score/opportunity_score');
const missingBadge = globalThis.__auxTest.badge(rankingOnly);
assert(missingBadge.includes('评分未提供'),
  'decision badge did not disclose missing formal total_score');
['评分 88', '评分 77', '评分 99'].forEach(function (text) {
  assert(!missingBadge.includes(text), 'decision badge leaked fallback score: ' + text);
});
const summary = globalThis.__auxTest.summary({ decision_engine_v1: rankingOnly }, null);
assert(summary.includes('评分未提供'),
  'decision summary did not disclose missing formal total_score');
assert(!summary.includes('评分 88') && !summary.includes('评分 77') && !summary.includes('评分 99'),
  'decision summary leaked a non-formal score');
const formal = { decision: '推荐', total_score: 62, opportunity_score: 99 };
assert(globalThis.__auxTest.score(formal) === 62, 'formal total_score was not used');
const formalBadge = globalThis.__auxTest.badge(formal);
assert(formalBadge.includes('评分 62') && !formalBadge.includes('评分 99'),
  'formal badge mixed decision and ranking scores');
assert(JSON.stringify(rankingOnly) === before,
  'score rendering mutated the decision object');
""",
        )

    def test_candidate_comparison_reads_daily_data_source_not_section_source(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1, report_date: '2026-08-28', views: { main: [{
    code: '301629',
    summary: { status: 'available', name: '矽电股份', formal_action: '观察' },
    decision_score: { status: 'available', score: 62, components: {} },
    rank_evidence: { status: 'available', view_rank: 1, opportunity_score: 30 },
    daily_structure: {
      status: 'available', source: 'forbidden-section-provenance',
      data_source: 'market_history_db', signal: '二买', signal_date: '2026-08-28',
      signal_age_days: 0, latest_date: '2026-08-28', health: 'verified',
      is_final: true, stale: false
    }
  }] }
} };
const comparison = globalThis.__auxTest.render('main');
assert(comparison.includes('来源 market_history_db'),
  'candidate comparison did not render daily_structure.data_source');
assert(!comparison.includes('forbidden-section-provenance'),
  'candidate comparison read section provenance as market data source');
""",
        )

    def test_modules_01_to_03_render_complete_evidence(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            FIXTURE
            + r"""
const module01 = moduleHtml('01', '02');
[
  '池身份', '融合候选池', '正式主推', '池内顺序', '#2',
  '信号类型', '三买', '信号日期', '2026-08-28', '信号新鲜度', '当日',
  '适用周期', 'T+3', '数据日期', '数据来源', 'market_history_db',
  '终局状态', '已终局', '陈旧状态', '未陈旧'
].forEach(function (text) {
  assert(module01.includes(text), 'module 01 missing: ' + text);
});

const module02 = moduleHtml('02', '03');
[
  '中枢 ZG', '20.5', 'serialized.pivots.ZG',
  '中枢 ZD', '17.8', 'serialized.pivots.ZD',
  '平台高点', '21.2', 'serialized.platform_high',
  '买点价格', '18.6', 'serialized.best_buy_point.price',
  '关键价格存在冲突'
].forEach(function (text) {
  assert(module02.includes(text), 'module 02 missing: ' + text);
});

const module03 = moduleHtml('03', '04');
[
  '中枢数量', '2', '最近 ZG', '20.5', '最近 ZD', '17.8',
  '买点价格', '18.6', '信号原因', '中枢上沿回踩',
  '均线多头', '否', 'MA5、MA10 当前值未提供'
].forEach(function (text) {
  assert(module03.includes(text), 'module 03 missing: ' + text);
});
""",
        )

    def test_modules_04_to_06_render_complete_evidence(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            FIXTURE
            + r"""
const module04 = moduleHtml('04', '05');
[
  '原因', '30分钟确认原因仅来自当前证据',
  'K线数量', '32', '终局状态', '已终局', '陈旧状态', '未陈旧',
  'EMA5', '309.1', 'EMA10', '304.8', 'EMA5方向', '上行', 'EMA10方向', '走平',
  '最新收盘价', '309.85', '收盘价高于 EMA5', '收盘价高于 EMA10',
  'MACD DIF', '8.3', 'MACD DEA', '7.6', '突破位保持', '回踩量能', '缩量',
  'MACD柱体连续性未提供'
].forEach(function (text) {
  assert(module04.includes(text), 'module 04 missing: ' + text);
});
assert(module04.includes('<dt>原因</dt><dd>30分钟确认原因仅来自当前证据'),
  'sublevel value.reason appears only in audit metadata, not the module body');

const module05 = moduleHtml('05', '06');
[
  '换手率', '4.82', '量价标签', '放量突破', '缩量回踩',
  '个股净流入', '12000000', '连续净流入天数', '3',
  '板块净流入', '8.3亿', '板块资金排名', '4',
  '资金同向性', '个股与板块资金同向', '换手率来源明细未提供'
].forEach(function (text) {
  assert(module05.includes(text), 'module 05 missing: ' + text);
});

const module06 = moduleHtml('06', '07');
[
  '板块涨跌幅', '3.21', '上涨家数', '36', '板块总家数', '52',
  '涨停家数', '4', '板块净流入', '830000000', '板块市场排名', '4',
  '个股相对强弱', '板块内偏强',
  '市场层', '支持', '板块层', '风险', '个股层', '风险',
  '板块层级去重状态未提供'
].forEach(function (text) {
  assert(module06.includes(text), 'module 06 missing: ' + text);
});
assert(module06.includes('<dt>板块层</dt><dd>风险</dd>'),
  'module 06 did not prioritize canonical sector_layer_state');
assert(module06.includes('<dt>板块说明</dt><dd>证据部分可用 · 方向未知</dd>'),
  'legacy sector explanation was not preserved as non-layer context');
assert(!module06.includes('<dt>板块层</dt><dd>证据部分可用 · 方向未知</dd>'),
  'legacy sector_state was presented as the canonical sector layer state');
""",
        )

    def test_completion_fields_escape_objects_and_boolean_values(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            FIXTURE
            + r"""
assert(!html.includes('[object Object]'), 'object field leaked as [object Object]');
['<script', '<img', '<svg'].forEach(function (unsafe) {
  assert(!html.includes(unsafe), 'unsafe evidence text leaked: ' + unsafe);
});
assert(html.includes('&lt;script&gt;'), 'escaped script evidence missing');
assert(html.includes('&lt;img'), 'escaped image evidence missing');
assert(html.includes('&lt;svg'), 'escaped svg evidence missing');
assert(!html.includes('>true<') && !html.includes('>false<'),
  'boolean evidence rendered as raw true/false');
assert(html.includes('已终局') && html.includes('未陈旧'),
  'boolean evidence lacks user-facing semantics');
""",
        )

    def test_main_rise_guards_and_event_risks_are_visible_and_safe(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            FIXTURE
            + r"""
const module03 = moduleHtml('03', '04');
assert(module03.includes('证据边界'), 'main-rise evidence guard heading missing');
assert(module03.includes('30分钟证据缺失，相关确认未纳入主升浪支持项'),
  '30m evidence guard missing from main-rise module');
assert(!module03.includes('<script'), 'main-rise evidence guard was not escaped');
assert(module03.includes('&lt;script&gt;'), 'escaped main-rise evidence guard missing');

const module07 = moduleHtml('07', '08');
assert(module07.includes('事件风险'), 'event risk heading missing');
assert(module07.includes('公告风险：股东减持'), 'Python event_risks text missing');
assert(module07.includes('验证状态') && module07.includes('已验证'),
  'event risk verification status missing or not user-readable');
assert(module07.includes('来源') && module07.includes('formal_daily_report'),
  'event risk source missing');
assert(module07.includes('截至') && module07.includes('2026-08-28'),
  'event risk as-of date missing');
assert(!module07.includes('[object Object]'), 'structured event risk leaked as [object Object]');
assert(!module07.includes('结构化风险不得字符串化'),
  'structured event risk bypassed the declared text contract');
assert(!module07.includes('<script'), 'event risk text was not escaped');
assert(module07.includes('&lt;script&gt;'), 'escaped event risk text missing');
""",
        )

    def test_unverified_missing_or_incomplete_event_risk_hides_legacy_copy(self):
        _assert_node_contract(
            self,
            "({ render: renderRiskAndNextEvidence })",
            r"""
function risk(status, source, asOf) {
  return {
    event_risk_status: status,
    event_risk_source: source,
    event_risk_as_of: asOf,
    event_risks: ['遗留事件风险不得显示<script>alert(18)</script>']
  };
}
[
  [risk('unverified', null, null), '未验证'],
  [risk('missing', null, null), '未提供'],
  [risk('available', null, '2026-08-28'), '验证信息不完整']
].forEach(function (entry) {
  const html = globalThis.__auxTest.render(entry[0]);
  assert(html.includes('验证状态') && html.includes(entry[1]),
    'event risk status is not user-readable: ' + entry[1]);
  assert(html.includes('来源') && html.includes('截至'),
    'event risk metadata labels missing');
  assert(!html.includes('遗留事件风险不得显示'),
    'unverified/missing event risk leaked legacy copy');
  assert(!html.includes('<script'), 'hidden legacy event risk leaked markup');
});
""",
        )

    def test_missing_sector_layer_state_falls_back_to_unknown_not_legacy_copy(self):
        _assert_node_contract(
            self,
            "({ render: renderMarketSectorEvidence })",
            r"""
const html = globalThis.__auxTest.render({
  status: 'partial',
  sector_state: '证据部分可用 · 方向未知',
  market_state: '支持',
  stock_state: '未知'
});
assert(html.includes('<dt>板块层</dt><dd>未知</dd>'),
  'missing canonical sector layer state did not fail closed to unknown');
assert(!html.includes('<dt>板块层</dt><dd>证据部分可用 · 方向未知</dd>'),
  'legacy sector_state was reused as the layer state');
""",
        )

    def test_chart_gates_30m_confirmation_annotations_with_fresh_evidence(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
const lane = {
  innerHTML: '',
  classList: { toggle: function () {} }
};
const raw = {
  dates: ['D01', 'D02', 'D03', 'D04'],
  opens: [10, 10.2, 10.1, 10.4],
  highs: [10.3, 10.4, 10.5, 10.8],
  lows: [9.8, 10.0, 9.9, 10.2],
  closes: [10.2, 10.1, 10.4, 10.7],
  volumes: [100, 110, 120, 130],
  macd_hist: [0.1, 0.2, 0.3, 0.4],
  chart_annotations: {
    markPoints: [
      { coord: ['D02', 10.1], name: '启动日' },
      { coord: ['D03', 10.4], name: '30分钟结构确认' },
      { coord: ['D04', 10.7], name: '确认日' }
    ],
    markLines: [],
    labels: ['确认日: D04', '日线结构保持']
  }
};
const projected = {
  code: '600001',
  summary: { code: '600001' },
  sublevel_30m: {}
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [projected] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = lane;
globalThis.__auxTest.state.isMobile = false;
globalThis.__auxTest.state.chartLayer = 'decision';

[
  { status: 'missing', confirmation_status: 'confirmed', confirmed: true, stale: false, is_final: true },
  { status: 'available', confirmation_status: 'confirmed', confirmed: true, stale: true, is_final: true },
  { status: 'available', confirmation_status: 'partial', confirmed: false, stale: false, is_final: true }
].forEach(function (sublevel) {
  projected.sublevel_30m = sublevel;
  lane.innerHTML = '';
  globalThis.__auxTest.chart(raw, { code: '600001' });
  const marks = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0].markPoint.data;
  assert(marks.some(function (point) { return point.name === '启动日'; }),
    'non-30m daily marker was removed by the confirmation gate');
  assert(!marks.some(function (point) { return point.name === '30分钟结构确认' || point.name === '确认日'; }),
    'stale/missing/unconfirmed 30m marker remained visible');
  assert(lane.innerHTML.includes('日线结构保持'), 'non-30m annotation label was removed');
  assert(!lane.innerHTML.includes('确认日: D04') && !lane.innerHTML.includes('30分钟结构确认'),
    'stale/missing/unconfirmed 30m annotation remained in the lane');
});

projected.sublevel_30m = {
  status: 'available', confirmation_status: 'confirmed', confirmed: true,
  stale: false, is_final: true
};
lane.innerHTML = '';
globalThis.__auxTest.chart(raw, { code: '600001' });
const freshMarks = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0].markPoint.data;
assert(freshMarks.some(function (point) { return point.name === '30分钟结构确认'; }),
  'fresh confirmed 30m marker was incorrectly removed');
assert(lane.innerHTML.includes('确认日: D04'),
  'fresh confirmed 30m annotation label was incorrectly removed');
""",
        )

    def test_chart_discloses_missing_real_trend_series_without_injection(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, layers: getAvailableChartLayers, state: state })",
            r"""
let chartOption = null;
const switcher = {
  innerHTML: '',
  querySelectorAll: function () { return []; }
};
global.document.getElementById = function (id) {
  return id === 'chartLayerSwitcher' ? switcher : null;
};
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
const dates = Array.from({ length: 25 }, function (_, index) { return 'D' + (index + 1); });
const raw = {
  dates: dates,
  opens: dates.map(function (_, index) { return 10 + index * 0.1; }),
  highs: dates.map(function (_, index) { return 10.3 + index * 0.1; }),
  lows: dates.map(function (_, index) { return 9.8 + index * 0.1; }),
  closes: dates.map(function (_, index) { return 10.1 + index * 0.1; }),
  volumes: dates.map(function (_, index) { return 1000 + index; }),
  macd_hist: dates.map(function (_, index) { return index % 2 ? -0.1 : 0.1; }),
  ema5: [null, null],
  ma20: ['not-a-number'],
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
};
const before = JSON.stringify(raw);
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.isMobile = false;
globalThis.__auxTest.state.chartLayer = 'decision';
assert(!globalThis.__auxTest.layers(raw).includes('trend'),
  'trend layer appeared without a real MA/EMA series');
globalThis.__auxTest.chart(raw, {});
assert(switcher.innerHTML.includes('本期未提供真实均线序列'),
  'missing real trend series was silently hidden');
assert(!chartOption.series.some(function (series) {
  return ['EMA5', 'EMA20', 'MA5', 'MA20'].includes(String(series.name || ''));
}), 'missing trend evidence produced a fabricated MA/EMA line');
assert(JSON.stringify(raw) === before, 'chart display injected or mutated trend data');
""",
        )

    def test_stale_and_non_final_risk_states_visible_outside_collapsed_details(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            r"""
const staleNonFinalEvidence = {
  view: 'main',
  code: '600002',
  summary: {
    name: '风险股',
    sector: '半导体',
    formal_action: '观察',
    pool_identity: 'picks_fusion',
    view_identity: 'main',
    view_rank: 1,
    signal_type: '二买',
    signal_date: '2026-08-25',
    signal_age_days: 3,
    applicable_horizon: 3,
    applicable_horizon_text: 'T+3',
    data_latest_date: '2026-08-25',
    data_source: 'market_history_db',
    data_health: 'stale',
    data_is_final: false,
    data_stale: true,
    status: 'stale'
  },
  decision_score: { status: 'available', score: 50, components: {} },
  rank_evidence: { status: 'available', view_rank: 1, opportunity_score: 50 },
  price_evidence: { status: 'available', current_price: 10, reference_price: 10 },
  daily_structure: { status: 'stale', stale: true, is_final: false },
  sublevel_30m: { status: 'stale' },
  volume_and_capital: { status: 'available' },
  market_and_sector: { status: 'available' },
  main_rise_clue: { status: 'missing' },
  risk_and_next: { status: 'available', risk_labels: [] },
  historical_validation: { status: 'missing' },
  display_derived: { status: 'available' }
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [staleNonFinalEvidence] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const html = globalThis.__auxTest.detail({
  code: '600002', name: '风险股', sector: '半导体',
  ref: { pool: 'picks_fusion', code: '600002' },
  formal_decision_contract: { action: '观察' }
}, {});
const module01Start = html.indexOf('data-evidence-module="01"');
const module02Start = html.indexOf('data-evidence-module="02"');
const module01 = html.slice(module01Start, module02Start);
const detailsIndex = module01.indexOf('<details class="evidence-meta-details">');
assert(detailsIndex > 0, '<details class="evidence-meta-details"> missing from module 01');
const mainArea = module01.slice(0, detailsIndex);
assert(mainArea.includes('陈旧状态') && mainArea.includes('已陈旧'),
  'stale risk status is not visible outside collapsed details');
assert(mainArea.includes('终局状态') && mainArea.includes('非终局'),
  'non-final risk status is not visible outside collapsed details');
assert(module01.includes('证据已过期') || module01.includes('is-stale'),
  'stale status badge is missing from module 01 header');
""",
        )


if __name__ == "__main__":
    unittest.main()
