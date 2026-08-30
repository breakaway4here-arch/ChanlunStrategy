"""Frontend contracts for scorecard maturity and simulation tracking."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


_BASE = r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
const historical = HISTORICAL_FIXTURE;
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{
    code: '600001',
    summary: { status: 'available', source: 'workspace', as_of: '2026-08-28', code: '600001', name: '证据股', formal_action: '观察' },
    decision_score: { status: 'available', source: 'decision', score: 62, components: {} },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 1, opportunity_score: 88 },
    price_evidence: { status: 'missing', source: 'prices', trailing_targets: [] },
    display_derived: { status: 'missing', source: 'display' },
    daily_structure: { status: 'missing', reason: 'not provided' },
    sublevel_30m: { status: 'missing', reason: 'not provided' },
    volume_and_capital: { status: 'missing', reason: 'not provided' },
    market_and_sector: { status: 'missing', reason: 'not provided' },
    risk_and_next: { status: 'missing', reason: 'not provided' },
    historical_validation: historical
  }] }
} };
"""


def _fixture(history):
    import json

    return _BASE.replace(
        "HISTORICAL_FIXTURE",
        json.dumps(history, ensure_ascii=False),
    )


class RecommendationHistoricalValidationFrontendTests(unittest.TestCase):

    def test_immature_scorecard_renders_progress_not_performance_claims(self):
        progress = {
            key: {
                "status": "collecting",
                "mature_samples": 4 if key != "t5" else 0,
                "waiting_samples": 2 if key == "t3" else 0,
                "unavailable_samples": 0,
                "required_mature_samples": 100,
                "active_dates": 3,
                "required_active_dates": 20,
                "active_months": 1,
                "required_calendar_months": 2,
            }
            for key in ("t1", "t3", "t5")
        }
        history = {
            "status": "collecting",
            "source": "daily.strategy_scorecards + daily.recommendation_ledger",
            "as_of": "2026-08-28",
            "summary": "未声明统一周期；历史样本仍在收集",
            "declared_horizon": None,
            "progress_by_horizon": progress,
            "metrics_by_horizon": {"t1": {}, "t3": {}, "t5": {}},
            "simulation_tracking": {
                "status": "available",
                "label": "策略模拟跟踪",
                "entry_mode": "immediate_close",
                "entry_price": 10.5,
                "entry_price_source": "ledger.exact.entry_price",
            },
        }
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            _fixture(history)
            + r"""
const html = globalThis.__auxTest.detail({ code: '600001' }, {});
assert(html.includes('未声明统一周期'), 'daily_fusion was given a default horizon');
assert(html.includes('T+1') && html.includes('T+3') && html.includes('T+5'), 'per-horizon progress is missing');
assert(html.includes('4 / 100'), 'mature-sample progress is missing');
assert(html.includes('3 / 20'), 'active-date progress is missing');
assert(html.includes('1 / 2'), 'active-month progress is missing');
assert(html.includes('等待成熟 2'), 'right-censored waiting samples are hidden');
assert(html.includes('策略模拟跟踪'), 'simulation tracking label is missing');
assert(html.includes('immediate_close') && html.includes('10.5'), 'verified simulated entry evidence is missing');
assert(!html.includes('胜率') && !html.includes('平均收益'), 'immature scorecard leaked performance claims');
assert(!html.includes('真实持仓') && !html.includes('真实交易'), 'simulation was described as a real trade');
""",
        )

    def test_ready_horizon_renders_only_whitelisted_metrics(self):
        history = {
            "status": "ready_for_manual_comparison",
            "source": "daily.strategy_scorecards + daily.recommendation_ledger",
            "as_of": "2026-08-28",
            "summary": "T+3 已达到人工比较门槛",
            "declared_horizon": 3,
            "progress_by_horizon": {
                "t3": {
                    "status": "ready_for_manual_comparison",
                    "mature_samples": 100,
                    "waiting_samples": 0,
                    "unavailable_samples": 0,
                    "required_mature_samples": 100,
                    "active_dates": 20,
                    "required_active_dates": 20,
                    "active_months": 2,
                    "required_calendar_months": 2,
                }
            },
            "metrics_by_horizon": {
                "t1": {},
                "t3": {"mean": 1.5, "median": 1.0, "win_rate": 66.7, "excess_mean": 0.2, "mean_mfe": 4.0, "mean_mae": -2.0, "max_drawdown": -4.0},
                "t5": {},
            },
            "simulation_tracking": {"status": "missing", "label": "暂无同合同历史跟踪记录"},
        }
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            _fixture(history)
            + r"""
const html = globalThis.__auxTest.detail({ code: '600001' }, {});
assert(html.includes('T+3') && html.includes('均值 1.5%'), 'mature mean is missing');
assert(html.includes('中位数 1%') && html.includes('上涨率 66.7%'), 'mature median/up-rate is missing');
assert(html.includes('基准超额 0.2%'), 'mature benchmark excess is missing');
assert(html.includes('MFE 4%') && html.includes('MAE -2%') && html.includes('最差 -4%'), 'mature risk metrics are missing');
assert(!html.includes('T+1 均值') && !html.includes('T+5 均值'), 'empty horizons fabricated metrics');
assert(html.includes('暂无同合同历史跟踪记录'), 'missing same-contract tracking is not explicit');
""",
        )


if __name__ == '__main__':
    unittest.main()
