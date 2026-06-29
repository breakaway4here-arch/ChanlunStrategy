import unittest

from chanlun.signal_quality_classifier import (
    LOW_VOLATILITY_MAX,
    HIGH_VOLATILITY_MIN,
    build_signal_context,
    classify_signal,
    tag_signal_quality,
    tag_signal_quality_in_place,
    tag_signal_quality_many,
    filter_executable_signals,
)


class SignalQualityClassifierTests(unittest.TestCase):

    def test_classify_signal_strong_trend_pivot_segment_low_volatility_is_a(self):
        signal = {
            "type": "一买",
            "trend_strength": 2,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 9},
            "segment": {"high": 12, "low": 8},
        }
        self.assertEqual(classify_signal(signal), "A")

    def test_classify_signal_trend_strength_1_is_b(self):
        signal = {
            "type": "一买",
            "trend_strength": 1,
            "volatility": 0.05,
            "pivot": {"ZG": 12, "ZD": 9},
            "segment": {"high": 12, "low": 8},
        }
        self.assertEqual(classify_signal(signal), "B")

    def test_classify_signal_missing_pivot_or_segment_is_b(self):
        signal = {
            "type": "一买",
            "trend_strength": 2,
            "volatility": 0.05,
            "segment": {"high": 12, "low": 8},
        }
        self.assertEqual(classify_signal(signal), "B")

    def test_classify_signal_trend_strength_0_is_c(self):
        signal = {
            "type": "一买",
            "trend_strength": 0,
            "volatility": 0.05,
            "pivot": {"ZG": 12, "ZD": 9},
            "segment": {"high": 12, "low": 8},
        }
        self.assertEqual(classify_signal(signal), "C")

    def test_classify_signal_high_volatility_with_weak_structure_is_c(self):
        signal = {
            "type": "一买",
            "trend_strength": 2,
            "volatility": HIGH_VOLATILITY_MIN,
            "pivot": {"ZG": 12, "ZD": 9},
        }
        self.assertEqual(classify_signal(signal), "C")

    def test_tag_signal_quality_does_not_mutate_input(self):
        signal = {
            "type": "一买",
            "trend_strength": 2,
            "volatility": LOW_VOLATILITY_MAX,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        out = tag_signal_quality(signal)
        self.assertIsNot(out, signal)
        self.assertNotIn("category", signal)
        self.assertEqual(out.get("category"), "A")

    def test_tag_signal_quality_in_place_sets_category(self):
        signal = {"type": "一买", "trend_strength": 1, "volatility": 0.05}
        out = tag_signal_quality_in_place(signal)
        self.assertIs(out, signal)
        self.assertEqual(signal.get("category"), "B")

    def test_tag_signal_quality_many_in_place_false_returns_copy(self):
        signals = [
            {"type": "一买", "trend_strength": 2, "volatility": LOW_VOLATILITY_MAX},
            {"type": "一买", "trend_strength": 0, "volatility": 0.05},
        ]
        out = tag_signal_quality_many(signals)
        self.assertEqual(len(out), 2)
        self.assertIsNot(out[0], signals[0])
        self.assertIn("category", out[0])
        self.assertIn("category", out[1])
        self.assertNotIn("category", signals[0])
        self.assertNotIn("category", signals[1])

    def test_filter_executable_signals_only_keep_a(self):
        signals = [
            {
                "type": "一买",
                "trend_strength": 2,
                "volatility": LOW_VOLATILITY_MAX,
                "pivot": {"ZG": 12, "ZD": 10},
                "segment": {"high": 12, "low": 10},
            },
            {
                "type": "一买",
                "trend_strength": 0,
                "volatility": 0.05,
                "pivot": {"ZG": 12, "ZD": 10},
                "segment": {"high": 12, "low": 10},
            },
            {
                "type": "一买",
                "trend_strength": 1,
                "volatility": 0.05,
                "pivot": {"ZG": 12, "ZD": 10},
                "segment": {"high": 12, "low": 10},
            },
        ]
        self.assertEqual(len(filter_executable_signals(signals)), 1)
        self.assertEqual(filter_executable_signals(signals)[0]["trend_strength"], 2)

    def test_build_signal_context_from_result_and_pick(self):
        result = {
            "closes": [10, 10.5, 11, 11.2],
            "highs": [10.2, 10.6, 11.2, 11.4],
            "lows": [9.7, 10.0, 10.8, 11.0],
            "pivots": [{"ZG": 11.4, "ZD": 10.2}],
            "segments": [{"high": 11.4, "low": 10.2}],
            "trend_type": "上涨趋势",
            "strength": 3,
        }
        signal = {"type": "一买"}

        context = build_signal_context(result, signal)
        self.assertIn("pivot", context)
        self.assertIn("segment", context)
        self.assertEqual(context["trend_type"], "上涨趋势")
        self.assertEqual(context["strength"], 3)
        self.assertEqual(context["trend_strength"], 3)
        self.assertEqual(context["pivot"], {"ZG": 11.4, "ZD": 10.2})
        self.assertEqual(context["segment"], {"high": 11.4, "low": 10.2})

    def test_build_signal_context_uses_snapshot_proxies_for_confirmed_startup(self):
        pick = {
            "closes": [10, 10.1, 10.2, 10.3, 10.4, 10.5],
            "highs": [10.2, 10.3, 10.4, 10.5, 10.6, 10.7],
            "lows": [9.8, 9.9, 10.0, 10.1, 10.2, 10.3],
            "pivots": {},
            "segments": [],
        }
        signal = {
            "type": "强势启动候选",
            "index": 5,
            "price": 10.5,
            "reference_price": 10.5,
            "current_price": 10.5,
            "distance_from_reference_pct": 0.0,
            "sublevel_confirm_grade": "A",
            "volatility": 0.05,
        }

        tagged = tag_signal_quality({**signal, "context": build_signal_context(pick, signal)})

        self.assertEqual(tagged["context"]["pivot"]["source"], "startup_reference_proxy")
        self.assertEqual(tagged["context"]["segment"]["source"], "price_window_proxy")
        self.assertEqual(tagged["category"], "A")


if __name__ == "__main__":
    unittest.main()
