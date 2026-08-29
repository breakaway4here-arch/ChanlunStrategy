"""Tests for 30min sublevel confirmation classifier."""
import unittest
import numpy as np
from chanlun.sublevel_confirm import (
    build_30min_confirmation_evidence,
    classify_30min_confirmation,
)


def make_daily_stock_with_swing_seed(source_price=10.0):
    return {
        "code": "000001",
        "buy_points": [{"type": "swing底背驰参考", "price": source_price}],
        "pivots": {"ZG": None, "ZD": None, "count": 0},
    }


def make_min30_result(lows, closes, opens=None, highs=None, divergence=None,
                      buy_points=None, fractals=None, dif=None, dea=None,
                      hist=None):
    """Lightweight fake ChanResult for 30min."""
    class FakeResult:
        pass
    r = FakeResult()
    r.code = "000001"
    r.lows = np.asarray(lows, dtype=float)
    r.closes = np.asarray(closes, dtype=float)
    r.opens = np.asarray(opens, dtype=float) if opens is not None else np.asarray(closes, dtype=float)
    r.highs = np.asarray(highs, dtype=float) if highs is not None else r.closes
    r.divergence = divergence
    r.buy_points = buy_points or []
    r.fractals = fractals or []
    r.macd_dif = dif
    r.macd_dea = dea
    r.macd_hist = np.asarray(hist, dtype=float) if hist is not None else None
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


class TestBuild30minConfirmationEvidence(unittest.TestCase):

    def test_stale_buy_point_is_not_a_fresh_structure(self):
        closes = np.linspace(10.0, 11.0, 20)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            buy_points=[{"type": "二买", "index": 2}],
            hist=np.linspace(-0.5, 0.5, 20),
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertIsNone(evidence["buy_point"])

    def test_buy_point_in_recent_window_is_fresh_structure(self):
        closes = np.linspace(10.0, 11.0, 20)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            buy_points=[{"type": "二买", "index": 18}],
            hist=np.linspace(-0.5, 0.5, 20),
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertEqual(evidence["buy_point"], "二买")

    def test_first_buy_in_recent_window_is_not_strong_startup_confirmation(self):
        closes = np.linspace(10.0, 11.0, 20)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            buy_points=[{"type": "一买", "index": 18}],
            hist=np.linspace(-0.5, 0.5, 20),
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertIsNone(evidence["buy_point"])

    def test_unrelated_candidate_in_recent_window_is_not_confirmation(self):
        closes = np.linspace(10.0, 11.0, 20)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            buy_points=[{"type": "盘整低吸候选", "index": 18}],
            hist=np.linspace(-0.5, 0.5, 20),
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertIsNone(evidence["buy_point"])

    def test_blocked_tier_cannot_override_buy_point_type_whitelist(self):
        closes = np.linspace(10.0, 11.0, 20)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            buy_points=[{"type": "二买", "tier": "blocked", "index": 18}],
            hist=np.linspace(-0.5, 0.5, 20),
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertIsNone(evidence["buy_point"])

    def test_buy_point_index_beyond_available_bars_fails_closed(self):
        closes = np.linspace(10.0, 11.0, 20)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            buy_points=[{"type": "二买", "index": 99}],
            hist=np.linspace(-0.5, 0.5, 20),
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertIsNone(evidence["buy_point"])

    def test_301629_pullback_is_alignment_not_recovery(self):
        closes = [
            252.0, 254.0, 257.0, 261.0, 268.0, 279.0, 292.0, 310.0,
            322.41, 318.01, 315.71, 312.89, 308.85, 308.38, 308.00, 309.85,
        ]
        result = make_min30_result(
            lows=[value * 0.99 for value in closes],
            closes=closes,
            opens=[value * 0.998 for value in closes],
            highs=[252.5, 255.0, 258.0, 263.0, 270.0, 281.0, 295.0, 325.0,
                   324.0, 320.0, 317.0, 314.0, 311.0, 310.0, 309.0, 310.5],
            hist=[0.5, 1.0, 2.0, 4.0, 7.0, 10.0, 12.0, 14.0,
                  13.693, 12.4, 10.8, 8.9, 7.1, 5.9, 4.8, 4.331],
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertTrue(evidence["ema_bullish_alignment"])
        self.assertEqual(evidence["macd_hist_direction"], "weakening")
        self.assertGreater(evidence["recent_peak_drawdown_pct"], 4.0)
        self.assertFalse(evidence["recovery_bundle_match"])

    def test_healthy_recovery_has_price_and_momentum_repair(self):
        closes = [10.8, 10.5, 10.2, 10.0, 9.9, 9.95, 10.08, 10.24, 10.42, 10.58]
        result = make_min30_result(
            lows=[10.7, 10.4, 10.1, 9.9, 9.82, 9.88, 9.98, 10.10, 10.28, 10.44],
            closes=closes,
            opens=[10.75, 10.55, 10.3, 10.1, 9.96, 9.90, 10.0, 10.12, 10.30, 10.45],
            highs=[value * 1.01 for value in closes],
            hist=[-0.7, -0.6, -0.5, -0.45, -0.4, -0.32, -0.20, -0.08, 0.04, 0.16],
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertTrue(evidence["close_above_ema5"])
        self.assertGreaterEqual(evidence["ema5_rising_bars"], 2)
        self.assertEqual(evidence["macd_hist_direction"], "improving")
        self.assertTrue(evidence["stop_fall"])
        self.assertTrue(evidence["recovery_bundle_match"])

    def test_missing_macd_fails_closed(self):
        closes = np.linspace(10.0, 11.0, 10)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            hist=None,
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertEqual(evidence["macd_hist_direction"], "unavailable")
        self.assertFalse(evidence["recovery_bundle_match"])

    def test_leading_macd_warmup_nans_do_not_hide_recent_direction(self):
        closes = np.linspace(10.0, 11.0, 10)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            hist=[float("nan"), float("nan"), -0.8, -0.7, -0.6,
                  -0.5, -0.4, -0.3, -0.2, -0.1],
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertEqual(evidence["macd_hist_direction"], "improving")

    def test_trailing_macd_nan_fails_closed_instead_of_using_stale_values(self):
        closes = np.linspace(10.0, 11.0, 10)
        result = make_min30_result(
            lows=closes * 0.99,
            closes=closes,
            opens=closes * 0.995,
            highs=closes * 1.01,
            hist=[-0.8, -0.7, -0.6, -0.5, -0.4, -0.3, -0.2, -0.1, 0.0,
                  float("nan")],
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertEqual(evidence["macd_hist_direction"], "unavailable")

    def test_insufficient_bars_returns_complete_fail_closed_schema(self):
        result = make_min30_result(
            lows=[10.0, 10.1, 10.2],
            closes=[10.1, 10.2, 10.3],
            opens=[10.0, 10.1, 10.2],
            highs=[10.2, 10.3, 10.4],
            hist=[0.1, 0.2, 0.3],
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertEqual(evidence["schema_version"], 1)
        self.assertFalse(evidence["sufficient_bars"])
        self.assertFalse(evidence["recovery_bundle_match"])

    def test_misaligned_ohlc_arrays_cannot_create_stop_fall_shadow_evidence(self):
        result = make_min30_result(
            lows=[8.0, 8.1, 8.2, 8.3],
            closes=[9.0, 9.1, 9.2, 9.3, 9.4],
            opens=[8.0, 8.1, 8.2, 8.3],
            highs=[9.1, 9.2, 9.3, 9.4, 9.5],
            hist=[-0.4, -0.3, -0.2, -0.1, 0.0],
        )

        evidence = build_30min_confirmation_evidence(result)

        self.assertFalse(evidence["stop_fall"])
        self.assertFalse(evidence["recovery_bundle_match"])


if __name__ == "__main__":
    unittest.main()
