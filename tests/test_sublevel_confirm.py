"""Tests for 30min sublevel confirmation classifier."""
import unittest
import numpy as np
from chanlun.sublevel_confirm import classify_30min_confirmation


def make_daily_stock_with_swing_seed(source_price=10.0):
    return {
        "code": "000001",
        "buy_points": [{"type": "swing底背驰参考", "price": source_price}],
        "pivots": {"ZG": None, "ZD": None, "count": 0},
    }


def make_min30_result(lows, closes, opens=None, divergence=None, buy_points=None,
                      fractals=None, dif=None, dea=None):
    """Lightweight fake ChanResult for 30min."""
    class FakeResult:
        pass
    r = FakeResult()
    r.code = "000001"
    r.lows = np.asarray(lows, dtype=float)
    r.closes = np.asarray(closes, dtype=float)
    r.opens = np.asarray(opens, dtype=float) if opens else np.asarray(closes, dtype=float)
    r.divergence = divergence
    r.buy_points = buy_points or []
    r.fractals = fractals or []
    r.macd_dif = dif
    r.macd_dea = dea
    return r


class TestSublevelConfirm(unittest.TestCase):

    def test_key_level_and_ema5_reclaim_is_medium_confirmation(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        bp = {"type": "swing底背驰候选种子", "price": 10.0}
        min30 = make_min30_result(
            lows=[10.2, 10.1, 10.0, 10.05, 10.08, 10.12, 10.2, 10.3],
            closes=[10.25, 10.15, 10.08, 10.1, 10.12, 10.18, 10.26, 10.35],
        )
        confirmation = classify_30min_confirmation(daily_stock, bp, min30)
        self.assertTrue(confirmation["confirmed"])
        self.assertEqual(confirmation["level"], "中")
        self.assertIn("EMA5收复", confirmation["signals"])

    def test_key_level_only_is_weak_not_confirmed(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        bp = {"type": "swing底背驰候选种子", "price": 10.0}
        min30 = make_min30_result(
            lows=[10.2, 10.1, 10.0, 10.05, 10.02, 10.01, 10.03, 10.04],
            closes=[10.2, 10.15, 10.1, 10.08, 10.05, 10.03, 10.02, 10.01],
        )
        confirmation = classify_30min_confirmation(daily_stock, bp, min30)
        self.assertFalse(confirmation["confirmed"])
        self.assertEqual(confirmation["level"], "弱")

    def test_stop_fall_bars_and_ema5_reclaim_is_medium_confirmation(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        bp = {"type": "swing底背驰候选种子", "price": 10.0}
        min30 = make_min30_result(
            lows=[10.4, 10.2, 10.0, 10.02, 10.05, 10.08, 10.12, 10.16],
            closes=[10.3, 10.1, 10.05, 10.08, 10.12, 10.18, 10.22, 10.28],
        )
        confirmation = classify_30min_confirmation(daily_stock, bp, min30)
        self.assertTrue(confirmation["confirmed"])
        self.assertEqual(confirmation["level"], "中")
        self.assertIn("止跌结构", "".join(confirmation["signals"]))


if __name__ == "__main__":
    unittest.main()
