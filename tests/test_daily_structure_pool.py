"""Tests for daily_structure_pool — position guard and swing seed construction."""
import unittest
import numpy as np
from chanlun.daily_structure_pool import build_daily_structure_pool


def make_result(code, closes, buy_points, volumes=None):
    """Lightweight fake mimicking ChanResult attributes needed by pool builder."""
    class FakeResult:
        pass
    r = FakeResult()
    r.code = code
    r.name = "测试" + code
    r.closes = np.asarray(closes, dtype=float)
    r.opens = np.asarray(closes, dtype=float)
    r.highs = np.asarray(closes, dtype=float)
    r.lows = np.asarray(closes, dtype=float)
    r.dates = ["2026-01-01"] * len(closes)
    r.volumes = np.asarray(volumes, dtype=float) if volumes else np.ones(len(closes)) * 1e6
    r.buy_points = buy_points
    r.trend_type = "盘整"
    r.divergence = None
    r.fractals = []
    r.strokes = []
    r.segments = []
    r.macd_hist = np.zeros(len(closes))
    r.pivots = []
    return r


class TestSwingSeedConstruction(unittest.TestCase):

    def test_swing_reference_without_position_guard_is_excluded(self):
        """swing底背驰参考 above 20-day low +8% and near highs → no seed, excluded."""
        closes = [10, 10.5, 11, 11.2, 11.5] * 20  # 100 bars, all near 11
        result = make_result(
            code="000001",
            closes=closes,
            buy_points=[{"type": "swing底背驰参考", "tier": "reference", "price": 8.0, "index": 99}],
        )
        pool, diag = build_daily_structure_pool([result], sector_stocks={}, mode="pure")
        self.assertEqual(pool, [])
        self.assertEqual(diag.get("swing_seed_count", 0), 0)
        self.assertEqual(diag.get("reference_only_count", 0), 1)

    def test_swing_reference_with_position_guard_enters_pool_as_seed(self):
        """swing底背驰参考 near source price → seed created, enters pool."""
        closes = [12, 11.5, 11, 10.5, 10.2, 10.1, 10.0, 10.1] * 13  # 104 bars, end near 10
        result = make_result(
            code="000002",
            closes=closes,
            buy_points=[{"type": "swing底背驰参考", "tier": "reference", "price": 10.0, "index": 103}],
        )
        pool, diag = build_daily_structure_pool([result], sector_stocks={}, mode="pure")
        self.assertEqual(len(pool), 1)
        seeds = [bp for bp in pool[0]["buy_points"] if bp["type"] == "swing底背驰候选种子"]
        self.assertEqual(len(seeds), 1)
        seed = seeds[0]
        self.assertEqual(seed["tier"], "seed")
        self.assertEqual(seed["source_type"], "swing底背驰参考")
        self.assertTrue(seed.get("seed_reason"))
        self.assertEqual(diag.get("swing_seed_count", 0), 1)


if __name__ == "__main__":
    unittest.main()
