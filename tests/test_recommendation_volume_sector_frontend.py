"""Frontend contracts for truthful volume, fund, market, and sector labels."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


_FIXTURE = r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{
    code: '600688',
    summary: { status: 'available', source: 'workspace', as_of: '2026-08-28', code: '600688', name: '上海石化', sector: '炼油化工', formal_action: '可上车' },
    decision_score: { status: 'available', source: 'decision', score: 93, components: {} },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 1, opportunity_score: 46 },
    price_evidence: { status: 'partial', source: 'prices', current_price: 2.91, reference_price: 2.89, trailing_targets: [] },
    display_derived: { status: 'partial', source: 'display' },
    daily_structure: { status: 'missing', reason: 'not provided' },
    sublevel_30m: { status: 'missing', reason: 'minute_data_not_serialized' },
    volume_and_capital: {
      status: 'partial', source: 'candidate volumes + explicit capital sources', as_of: '2026-08-28',
      summary: '量能可验证；20日平均成交额仅表示流动性；个股资金证据不足；板块资金单独展示',
      current_volume: 871295, average_volume_5: 684876.4, volume20: 618451.3,
      volume_ratio: 1.393, money20: 174570073.16, money20_text: '1.75亿', money20_kind: 'average_turnover_amount',
      money20_source: 'amounts', stock_money_flow: '个股资金证据不足',
      sector_money_flow: 675301216, sector_money_flow_text: '6.75亿', capital_state: '个股与板块资金严格分离'
    },
    market_and_sector: {
      status: 'partial', source: 'daily.market_sentiment + daily.sector_heat', as_of: '2026-08-28',
      summary: '正式市场偏强；板块证据部分可用，暂不判定资金支持',
      market: '62 / 100 · 偏强', market_label: '偏强', market_sentiment_score: 62,
      sector: '炼油化工', sector_state: '证据部分可用 · 方向未知',
      sector_support: null, sector_risk: null
    },
    risk_and_next: { status: 'missing', reason: 'not provided' },
    historical_validation: { status: 'missing', reason: 'not provided' }
  }] }
} };
"""


class RecommendationVolumeSectorFrontendTests(unittest.TestCase):

    def test_detail_labels_turnover_stock_fund_and_sector_fund_separately(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            _FIXTURE
            + r"""
const html = globalThis.__auxTest.detail({ code: '600688' }, {});
assert(html.includes('当日成交量') && html.includes('871295'), 'current volume is not displayed');
assert(html.includes('5日平均成交量'), 'five-day average volume label is missing');
assert(html.includes('20日平均成交量'), 'twenty-day average volume label is missing');
assert(html.includes('20日平均成交额'), 'turnover amount is still mislabeled as fund evidence');
assert(html.includes('个股资金证据不足'), 'missing stock-fund evidence is hidden');
assert(html.includes('板块资金') && html.includes('6.75亿'), 'sector fund evidence is missing');
assert(!html.includes('主力吸筹') && !html.includes('主力流入'), 'turnover/sector flow was called main-fund inflow');
""",
        )

    def test_partial_sector_data_never_renders_a_support_conclusion(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            _FIXTURE
            + r"""
const html = globalThis.__auxTest.detail({ code: '600688' }, {});
assert(html.includes('正式市场情绪') && html.includes('62'), 'formal market sentiment is missing');
assert(html.includes('偏强'), 'formal market label is missing');
assert(html.includes('证据部分可用') && html.includes('方向未知'), 'partial sector state is not explicit');
assert(!html.includes('板块资金支持'), 'partial sector data became a support conclusion');
assert(!html.includes('PSY12 100') && !html.includes('极强'), 'shadow sentiment leaked into formal market evidence');
""",
        )


if __name__ == '__main__':
    unittest.main()
