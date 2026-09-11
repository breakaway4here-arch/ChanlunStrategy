"""Tests for 30min sublevel confirmation classifier."""
import unittest
import numpy as np
from chanlun.engine_types import Fractal
from chanlun.sublevel_confirm import (
    _check_key_level,
    _check_ema5_reclaim,
    build_30min_confirmation_evidence,
    classify_30min_confirmation,
)


def make_daily_stock_with_swing_seed(source_price=10.0):
    return {
        "code": "000001",
        "buy_points": [{"type": "swing底背驰参考", "price": source_price}],
        "pivots": {"ZG": None, "ZD": None, "count": 0},
        "price_basis": {"adjustment": "qfq", "factor_vs_raw": 1.0},
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

    def test_classifier_keeps_each_original_recommendable_buy_type(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        for bp_type, tier in (
            ("一买", "formal"),
            ("二买", "formal"),
            ("盘整低吸候选", "candidate"),
        ):
            with self.subTest(bp_type=bp_type):
                min30 = make_min30_result(
                    lows=[10.0] * 8,
                    closes=[10.0] * 8,
                    buy_points=[{
                        "type": bp_type,
                        "tier": tier,
                        "index": 7,
                    }],
                )
                confirmation = classify_30min_confirmation(
                    daily_stock,
                    {"type": "swing底背驰候选种子", "price": 10.0},
                    min30,
                )
                self.assertTrue(confirmation["confirmed"])
                self.assertIn(f"30min{bp_type}", confirmation["signals"])

    def test_classifier_rejects_buy_points_without_recent_valid_coordinates(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        for label, index in (
            ("missing", None),
            ("old", 0),
            ("future", 20),
            ("bool", True),
            ("fractional", 1.5),
        ):
            with self.subTest(index=label):
                min30 = make_min30_result(
                    lows=[10.0] * 20,
                    closes=[10.0] * 20,
                    buy_points=[{
                        "type": "二买",
                        "tier": "formal",
                        "index": index,
                    }],
                )
                confirmation = classify_30min_confirmation(
                    daily_stock,
                    {"type": "swing底背驰候选种子", "price": 10.0},
                    min30,
                )
                self.assertFalse(confirmation["confirmed"])
                self.assertNotIn("30min二买", confirmation["signals"])

    def test_classifier_requires_recent_divergence_event_coordinate(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        for label, segment, expected in (
            ("fresh", (12, 19), True),
            ("old", (0, 5), False),
            ("missing", None, False),
            ("future", (12, 20), False),
            ("bool", (True, 19), False),
        ):
            with self.subTest(segment=label):
                divergence = {
                    "is_divergence": True,
                    "type": "盘整底背驰",
                }
                if segment is not None:
                    divergence["last_segment"] = segment
                min30 = make_min30_result(
                    lows=[10.0] * 20,
                    closes=[10.0] * 20,
                    divergence=divergence,
                )
                confirmation = classify_30min_confirmation(
                    daily_stock,
                    {"type": "swing底背驰候选种子", "price": 10.0},
                    min30,
                )
                self.assertEqual(confirmation["confirmed"], expected)
                self.assertEqual(
                    "30min底背驰" in confirmation["signals"], expected
                )

    def test_bottom_fractal_macd_requires_recent_same_frequency_coordinates(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
        dif = np.full(20, np.nan, dtype=float)
        dea = np.full(20, np.nan, dtype=float)
        dif[4:18] = -0.2
        dea[4:18] = 0.0
        dif[18] = -1.0
        dea[18] = 0.0
        dif[19] = 1.0
        dea[19] = 0.0
        fresh = make_min30_result(
            lows=[10.0] * 20,
            closes=[10.0] * 20,
            fractals=[Fractal(type="bottom", index=17, price=10.0, klines=[17])],
            dif=dif,
            dea=dea,
        )
        stale = make_min30_result(
            lows=[10.0] * 20,
            closes=[10.0] * 20,
            fractals=[Fractal(type="bottom", index=0, price=10.0, klines=[0])],
            dif=dif,
            dea=dea,
        )
        mismatched = make_min30_result(
            lows=[10.0] * 20,
            closes=[10.0] * 20,
            fractals=[Fractal(type="bottom", index=17, price=10.0, klines=[17])],
            dif=dif[:-1],
            dea=dea[:-1],
        )

        fresh_confirmation = classify_30min_confirmation(
            daily_stock,
            {"type": "swing底背驰候选种子", "price": 10.0},
            fresh,
        )
        stale_confirmation = classify_30min_confirmation(
            daily_stock,
            {"type": "swing底背驰候选种子", "price": 10.0},
            stale,
        )
        mismatched_confirmation = classify_30min_confirmation(
            daily_stock,
            {"type": "swing底背驰候选种子", "price": 10.0},
            mismatched,
        )
        self.assertTrue(fresh_confirmation["confirmed"])
        self.assertFalse(stale_confirmation["confirmed"])
        self.assertFalse(mismatched_confirmation["confirmed"])

    def test_ema5_reclaim_requires_recent_true_cross(self):
        always_above = make_min30_result(
            lows=[1.0] * 8,
            closes=[1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7],
        )
        recent_cross = make_min30_result(
            lows=[9.0] * 8,
            closes=[10.0, 9.8, 9.7, 9.6, 9.5, 9.4, 9.6, 9.8],
        )

        self.assertFalse(_check_ema5_reclaim(always_above))
        self.assertTrue(_check_ema5_reclaim(recent_cross))

    def test_ema5_reclaim_fails_closed_for_equal_or_invalid_tail(self):
        equal = make_min30_result(lows=[1.0] * 8, closes=[1.0] * 8)
        invalid = make_min30_result(
            lows=[1.0] * 8,
            closes=[1.0, 1.1, 1.2, 1.3, 1.4, float("nan"), 1.6, 1.7],
        )

        self.assertFalse(_check_ema5_reclaim(equal))
        self.assertFalse(_check_ema5_reclaim(invalid))

    def test_key_level_aligns_raw_30m_low_to_daily_qfq_basis(self):
        daily_stock = make_daily_stock_with_swing_seed(source_price=5.0)
        daily_stock["closes"] = np.array([5.0] * 20, dtype=float)
        daily_stock["price_basis"]["factor_vs_raw"] = 0.5
        source_bp = {"type": "swing底背驰候选种子", "price": 5.0}
        min30 = make_min30_result(
            lows=[9.6] * 8,
            closes=[10.0] * 8,
        )

        self.assertFalse(_check_key_level(daily_stock, source_bp, min30))

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
