"""Tests for candidate_upgrade — swing seed → 底背驰候选 upgrade path."""
import unittest
import numpy as np
from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min


def make_stock(code, buy_points, closes=None):
    """Lightweight fake daily stock entry."""
    return {
        "code": code,
        "name": "测试" + code,
        "buy_points": buy_points,
        "best_buy_point": None,
        "pivots": {},
        "trend_type": "盘整",
        "divergence": None,
        "closes": np.asarray(closes, dtype=float) if closes else np.array([10.0] * 20),
        "opens": np.array([10.0] * 20),
        "highs": np.array([10.0] * 20),
        "lows": np.array([10.0] * 20),
        "dates": ["2026-01-01"] * 20,
        "volumes": np.ones(20) * 1e6,
        "fractals": [],
        "strokes": [],
        "segments": [],
        "macd_hist": np.zeros(20),
        "sector": "",
        "version": "pure",
    }


def make_min30_result(code, medium_confirm=True):
    """Fake 30min ChanResult that triggers medium or weak confirmation."""
    class FakeResult:
        pass
    r = FakeResult()
    r.code = code
    r.divergence = None
    r.buy_points = []
    r.fractals = []
    r.macd_dif = None
    r.macd_dea = None
    if medium_confirm:
        # key_level OK + EMA5 reclaim → 中
        r.lows = np.array([10.2, 10.1, 10.0, 10.05, 10.08, 10.12, 10.2, 10.3], dtype=float)
        r.closes = np.array([10.25, 10.15, 10.08, 10.1, 10.12, 10.18, 10.26, 10.35], dtype=float)
        r.opens = np.array([10.25, 10.15, 10.08, 10.1, 10.12, 10.18, 10.26, 10.35], dtype=float)
    else:
        # key_level OK but EMA5 failing → 弱
        r.lows = np.array([10.2, 10.1, 10.0, 10.05, 10.02, 10.01, 10.03, 10.04], dtype=float)
        r.closes = np.array([10.2, 10.15, 10.1, 10.08, 10.05, 10.03, 10.02, 10.01], dtype=float)
        r.opens = np.array([10.2, 10.15, 10.1, 10.08, 10.05, 10.03, 10.02, 10.01], dtype=float)
    return r


class TestCandidateUpgrade(unittest.TestCase):

    def test_swing_seed_upgrades_to_bottom_divergence_candidate_with_medium_confirmation(self):
        daily_pool = [make_stock(
            code="000001",
            buy_points=[
                {
                    "type": "swing底背驰候选种子",
                    "tier": "seed",
                    "source_type": "swing底背驰参考",
                    "price": 10.0,
                    "seed_reason": "接近20日低点",
                },
                {"type": "swing底背驰参考", "price": 10.0},
            ],
        )]
        min30_results = [make_min30_result(code="000001", medium_confirm=True)]
        recommended, diag = upgrade_daily_candidates_with_30min(daily_pool, min30_results, mode="pure")

        self.assertEqual(len(recommended), 1)
        bp = recommended[0]["best_buy_point"]
        self.assertEqual(bp["type"], "底背驰候选")
        self.assertEqual(bp["tier"], "candidate")
        self.assertEqual(bp["source_type"], "swing底背驰参考")
        self.assertEqual(bp.get("seed_type"), "swing底背驰候选种子")
        self.assertEqual(bp.get("seed_reason"), "接近20日低点")
        self.assertEqual(diag["candidate_upgraded"], 1)

    def test_swing_seed_without_30min_confirmation_is_not_recommended(self):
        daily_pool = [make_stock(
            code="000002",
            buy_points=[{
                "type": "swing底背驰候选种子",
                "tier": "seed",
                "source_type": "swing底背驰参考",
                "price": 10.0,
            }],
        )]
        min30_results = [make_min30_result(code="000002", medium_confirm=False)]
        recommended, diag = upgrade_daily_candidates_with_30min(daily_pool, min30_results, mode="pure")

        self.assertEqual(recommended, [])
        self.assertEqual(diag["dropped_no_confirm"], 1)


if __name__ == "__main__":
    unittest.main()
