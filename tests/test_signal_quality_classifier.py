import unittest

from chanlun.signal_quality_classifier import (
    LOW_VOLATILITY_MAX,
    HIGH_VOLATILITY_MIN,
    build_signal_context,
    classify_signal,
    classify_signal_tier,
    classify_signal_expected_horizon,
    explain_signal_tier,
    explain_signal_rejection,
    explain_signal_expected_horizon,
    calculate_signal_recommendation_score,
    explain_signal_recommendation_score,
    list_quality_profiles,
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

    def test_list_quality_profiles(self):
        self.assertEqual(
            list_quality_profiles(),
            [
                "fusion_strict",
                "fusion_strict_startup_rescue_v1",
                "fusion_mid",
                "fusion_loose",
            ],
        )

    def test_classify_signal_fusion_mid_relaxes_trend(self):
        signal = {
            "type": "一买",
            "trend_strength": 1.6,
            "volatility": 0.09,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        self.assertEqual(classify_signal(signal, profile="fusion_mid"), "A")
        self.assertEqual(classify_signal(signal), "B")

    def test_classify_signal_startup_rescue_only_rescues_weak_startup(self):
        startup = {
            "type": "强势启动候选",
            "trend_strength": 1.0,
            "volatility": 0.15,
            "pivot": None,
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }
        strong_startup = {
            **startup,
            "market_env": "strong",
        }
        strong_startup_with_context = {
            **strong_startup,
            "context": {
                "trend_strength": 1.0,
                "volatility": 0.15,
                "pivot": None,
                "segment": {"high": 12, "low": 10},
            },
        }
        strict_original = {
            "type": "强势启动候选",
            "trend_strength": 2.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "strong",
        }
        bottom = {
            "type": "底背驰候选",
            "trend_strength": 1.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        low_absorb = {
            "type": "中枢低吸候选",
            "trend_strength": 1.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        choppy_startup = {
            **startup,
            "trend_type": "震荡区",
        }

        self.assertEqual(
            classify_signal(startup, profile="fusion_strict_startup_rescue_v1"),
            "A",
        )
        self.assertEqual(
            classify_signal(strong_startup, profile="fusion_strict_startup_rescue_v1"),
            "B",
        )
        self.assertEqual(
            classify_signal(
                strong_startup_with_context,
                profile="fusion_strict_startup_rescue_v1",
            ),
            "B",
        )
        self.assertEqual(
            classify_signal(bottom, profile="fusion_strict_startup_rescue_v1"),
            "B",
        )
        self.assertEqual(
            classify_signal(low_absorb, profile="fusion_strict_startup_rescue_v1"),
            "B",
        )
        self.assertEqual(
            classify_signal(choppy_startup, profile="fusion_strict_startup_rescue_v1"),
            "C",
        )
        self.assertEqual(
            classify_signal(strict_original, profile="fusion_strict_startup_rescue_v1"),
            "A",
        )
        self.assertEqual(
            classify_signal(strong_startup, profile="fusion_strict"),
            "B",
        )

    def test_classify_signal_default_profile_is_startup_rescue_v1(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 1.0,
            "volatility": 0.15,
            "pivot": None,
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }
        self.assertEqual(classify_signal(signal), "A")

    def test_classify_signal_fusion_mid_does_not_relax_structure_with_trend(self):
        signal = {
            "type": "一买",
            "trend_strength": 1.6,
            "volatility": 0.09,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": None,
        }
        self.assertEqual(classify_signal(signal, profile="fusion_mid"), "B")

    def test_classify_signal_fusion_loose_allows_weak_strength(self):
        signal = {
            "type": "一买",
            "trend_strength": 1.0,
            "volatility": 0.09,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        self.assertEqual(classify_signal(signal, profile="fusion_loose"), "A")
        self.assertEqual(classify_signal(signal), "B")

    def test_classify_signal_tier_marks_high_confidence_as_a_plus(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 3.0,
            "volatility": 0.05,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "strong",
        }

        self.assertEqual(
            classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
            "A",
        )
        self.assertEqual(
            classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            "A+",
        )
        self.assertEqual(
            explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            ["strong_trend", "low_volatility", "complete_structure"],
        )

    def test_classify_signal_tier_marks_rescue_as_a_minus(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 1.0,
            "volatility": 0.05,
            "pivot": None,
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }

        self.assertEqual(
            classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
            "A",
        )
        self.assertEqual(
            classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            "A-",
        )
        self.assertEqual(
            explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            ["startup_rescue"],
        )

    def test_classify_signal_tier_marks_standard_a(self):
        signal = {
            "type": "一买",
            "trend_strength": 2.0,
            "volatility": 0.07,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }

        self.assertEqual(
            classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
            "A",
        )
        self.assertEqual(
            classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            "A",
        )
        self.assertEqual(
            explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            ["standard_a"],
        )

    def test_classify_signal_tier_ignores_non_a_signals(self):
        signal = {
            "type": "底背驰候选",
            "trend_strength": 1.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }

        self.assertEqual(
            classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
            "B",
        )
        self.assertIsNone(
            classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        )
        self.assertEqual(
            explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
            [],
        )

    def test_expected_horizon_maps_a_plus_to_t5(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 3.0,
            "volatility": 0.05,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "strong",
        }

        self.assertEqual(
            classify_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            "T+5",
        )
        self.assertEqual(
            explain_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            ["high_confidence_hold"],
        )

    def test_expected_horizon_maps_standard_a_to_t3(self):
        signal = {
            "type": "一买",
            "trend_strength": 2.0,
            "volatility": 0.07,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }

        self.assertEqual(
            classify_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            "T+3",
        )
        self.assertEqual(
            explain_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            ["standard_swing"],
        )

    def test_expected_horizon_maps_a_minus_to_t1(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 1.0,
            "volatility": 0.05,
            "pivot": None,
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }

        self.assertEqual(
            classify_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            "T+1",
        )
        self.assertEqual(
            explain_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            ["fast_confirm_or_exit"],
        )

    def test_recommendation_score_for_a_plus(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 3.0,
            "volatility": 0.05,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "strong",
        }

        self.assertEqual(
            calculate_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            91.0,
        )
        self.assertEqual(
            explain_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            ["tier:A+", "longer_horizon_bonus", "strong_market_audit_penalty"],
        )

    def test_recommendation_score_for_standard_a(self):
        signal = {
            "type": "一买",
            "trend_strength": 2.0,
            "volatility": 0.07,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }

        self.assertEqual(
            calculate_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            78.0,
        )
        self.assertEqual(
            explain_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            ["tier:A"],
        )

    def test_recommendation_score_for_startup_rescue(self):
        signal = {
            "type": "强势启动候选",
            "trend_strength": 1.0,
            "volatility": 0.05,
            "pivot": None,
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }

        self.assertEqual(
            calculate_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            57.0,
        )
        self.assertEqual(
            explain_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            ["tier:A-", "short_horizon_penalty", "startup_rescue_penalty"],
        )

    def test_recommendation_score_ignores_non_a(self):
        signal = {
            "type": "底背驰候选",
            "trend_strength": 1.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }

        self.assertIsNone(
            calculate_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
        )
        self.assertEqual(
            explain_signal_recommendation_score(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            [],
        )

    def test_expected_horizon_ignores_non_a_signals(self):
        signal = {
            "type": "底背驰候选",
            "trend_strength": 1.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }

        self.assertIsNone(
            classify_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
        )
        self.assertEqual(
            explain_signal_expected_horizon(
                signal,
                profile="fusion_strict_startup_rescue_v1",
            ),
            [],
        )

    def test_tag_signal_quality_adds_quality_tier_for_a_only(self):
        a_signal = {
            "type": "强势启动候选",
            "trend_strength": 1.0,
            "volatility": 0.05,
            "pivot": None,
            "segment": {"high": 12, "low": 10},
            "market_env": "weak",
        }
        b_signal = {
            "type": "底背驰候选",
            "trend_strength": 1.0,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }

        tagged_a = tag_signal_quality(
            a_signal,
            profile="fusion_strict_startup_rescue_v1",
        )
        tagged_b = tag_signal_quality(
            b_signal,
            profile="fusion_strict_startup_rescue_v1",
        )

        self.assertEqual(tagged_a["category"], "A")
        self.assertEqual(tagged_a["quality_tier"], "A-")
        self.assertEqual(tagged_a["quality_tier_reasons"], ["startup_rescue"])
        self.assertEqual(tagged_a["expected_horizon"], "T+1")
        self.assertEqual(
            tagged_a["expected_horizon_reasons"],
            ["fast_confirm_or_exit"],
        )
        self.assertEqual(tagged_a["recommendation_score"], 57.0)
        self.assertEqual(
            tagged_a["recommendation_score_reasons"],
            ["tier:A-", "short_horizon_penalty", "startup_rescue_penalty"],
        )
        self.assertEqual(tagged_b["category"], "B")
        self.assertNotIn("quality_tier", tagged_b)
        self.assertNotIn("quality_tier_reasons", tagged_b)
        self.assertNotIn("expected_horizon", tagged_b)
        self.assertNotIn("expected_horizon_reasons", tagged_b)
        self.assertNotIn("recommendation_score", tagged_b)
        self.assertNotIn("recommendation_score_reasons", tagged_b)

    def test_tag_signal_quality_profile(self):
        signal = {
            "type": "一买",
            "trend_strength": 1.6,
            "volatility": 0.09,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        out = tag_signal_quality(signal, profile="fusion_mid")
        self.assertNotIn("category", signal)
        self.assertEqual(out.get("category"), "A")
        out_strict = tag_signal_quality(signal)
        self.assertEqual(out_strict.get("category"), "B")

    def test_unknown_profile_raises(self):
        signal = {
            "type": "一买",
            "trend_strength": 2,
            "volatility": LOW_VOLATILITY_MAX,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        with self.assertRaises(ValueError):
            classify_signal(signal, profile="unknown")
        with self.assertRaises(ValueError):
            tag_signal_quality(signal, profile="unknown")
        with self.assertRaises(ValueError):
            filter_executable_signals([signal], profile="unknown")

    def test_explain_signal_rejection_returns_empty_for_a(self):
        signal = {
            "type": "一买",
            "trend_strength": 2,
            "volatility": 0.08,
            "pivot": {"ZG": 12, "ZD": 10},
            "segment": {"high": 12, "low": 10},
        }
        self.assertEqual(explain_signal_rejection(signal), [])

    def test_explain_signal_rejection_reports_bottleneck_reasons(self):
        signal = {
            "type": "一买",
            "trend_strength": 1,
            "volatility": 0.2,
            "pivot": None,
            "segment": None,
        }
        reasons = explain_signal_rejection(signal, profile="fusion_strict")
        self.assertIn("trend_strength_below_min", reasons)
        self.assertIn("volatility_above_max", reasons)
        self.assertIn("high_volatility", reasons)
        self.assertIn("missing_pivot", reasons)
        self.assertIn("missing_segment", reasons)

    def test_filter_executable_signals_profile_flexible(self):
        signals = [
            {
                "type": "一买",
                "trend_strength": 1.0,
                "volatility": 0.09,
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
        ]
        self.assertEqual(len(filter_executable_signals(signals, profile="fusion_loose")), 1)
        self.assertEqual(len(filter_executable_signals(signals, profile="fusion_strict")), 0)

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
