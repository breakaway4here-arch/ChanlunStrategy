import unittest

from chanlun.scoring_engine import (
    ALPHA_BONUS_LIMIT,
    ALPHA_MULTIPLIER_MAX,
    compute_opportunity_score,
)


class TestScoringEngine(unittest.TestCase):
    def test_component_caps(self):
        score, trace = compute_opportunity_score(
            {
                "score": 100,
                "best_buy_point": {
                    "distance_from_reference_pct": 0.8,
                    "change_pct": 3.0,
                },
            },
            "main",
            {"source_count": 1, "data_quality": {"market_status": "verified"}},
        )

        self.assertEqual(score, trace["opportunity_score"])
        self.assertLessEqual(trace["signal_score"], 25)
        self.assertLessEqual(trace["entry_score"], 20)
        self.assertLessEqual(trace["momentum_score"], 20)
        self.assertLessEqual(trace["market_score"], 15)
        self.assertLessEqual(trace["risk_penalty"], 30)
        self.assertLessEqual(trace["data_penalty"], 20)

    def test_entry_score_banding(self):
        base = {
            "score": 60,
            "best_buy_point": {
                "change_pct": 1.0,
            },
        }
        cases = [
            (0.4, 16),
            (1.0, 16),
            (1.7, 14),
            (2.7, 11),
            (4.5, 8),
            (7.9, 4),
            (8.0, 4),
            (8.1, 0),
            (12.0, 0),
        ]

        for distance, expected in cases:
            item = dict(base)
            item["best_buy_point"] = {**base["best_buy_point"], "distance_from_reference_pct": distance}
            _, trace = compute_opportunity_score(
                item,
                "main",
                {"source_count": 1, "data_quality": {"market_status": "verified"}},
            )
            self.assertEqual(trace["entry_score"], expected)

    def test_momentum_score_is_capped(self):
        _, trace_cheap = compute_opportunity_score(
            {
                "score": 10,
                "best_buy_point": {"distance_from_reference_pct": 4.0, "change_pct": 13.0},
            },
            "main",
            {"source_count": 1, "data_quality": {"market_status": "verified"}},
        )
        self.assertEqual(trace_cheap["momentum_score"], 19.5)

        _, trace_cap = compute_opportunity_score(
            {
                "score": 10,
                "best_buy_point": {"distance_from_reference_pct": 4.0, "change_pct": 99.0},
            },
            "main",
            {"source_count": 1, "data_quality": {"market_status": "verified"}},
        )
        self.assertEqual(trace_cap["momentum_score"], 20)

        _, trace_zero = compute_opportunity_score(
            {
                "score": 10,
                "best_buy_point": {"distance_from_reference_pct": 4.0, "change_pct": -1.0},
            },
            "main",
            {"source_count": 1, "data_quality": {"market_status": "verified"}},
        )
        self.assertEqual(trace_zero["momentum_score"], 0)

    def test_confirming_not_change_proxy_and_not_raw_100_domination(self):
        _, trace = compute_opportunity_score(
            {
                "score": 100,
                "change_pct": 80.0,
                "distance_from_reference_pct": 1.0,
            },
            "confirming",
            {"source_count": 1, "data_quality": {"market_status": "verified"}},
        )

        self.assertEqual(trace["signal_score"], 10)
        self.assertLess(trace["signal_score"], 100)

    def test_same_condition_source_weights_distinguish_result(self):
        base_item = {
            "score": 88,
            "boom_score": 88,
            "change_pct": 3.0,
            "best_buy_point": {"distance_from_reference_pct": 1.5},
        }
        order = [
            "main",
            "acceleration",
            "luojie",
            "confirming",
            "baseline",
        ]

        scores = []
        markets = []
        for source in order:
            score, trace = compute_opportunity_score(
                base_item,
                source,
                {"source_count": 1, "data_quality": {"market_status": "verified"}},
            )
            scores.append(score)
            markets.append(trace["market_score"])

        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[1], scores[2])
        self.assertGreater(scores[2], scores[3])
        self.assertGreater(scores[3], scores[4])
        self.assertGreater(markets[0], markets[1])
        self.assertGreater(markets[1], markets[2])
        self.assertGreater(markets[2], markets[3])
        self.assertGreater(markets[3], markets[4])

    def test_data_penalty_is_capped(self):
        _, trace = compute_opportunity_score(
            {
                "score": 80,
                "best_buy_point": {"distance_from_reference_pct": 2.0},
            },
            "main",
            {
                "source_count": 1,
                "sources": ["main", "acceleration", "luojie"],
                "by_source": {
                    "main": {"data_status": {"daily": "missing"}},
                    "acceleration": {"data_status": {"daily": "missing"}},
                    "luojie": {"data_status": {"daily": "stale_cache"}},
                },
                "data_quality": {"market_status": "unverified", "fallback_used": True},
            },
        )

        self.assertLessEqual(trace["data_penalty"], 20)

    def test_alpha_breakout_two_yang_confirmation_adds_bonus(self):
        item = {
            "score": 50,
            "change_pct": 4.0,
            "volume_ratio": 1.3,
            "ma_bullish": True,
            "confirmed_by": "30min两阳夹一阴确认",
            "confirmations": ["30min两阳夹一阴确认", "30min EMA5维持"],
            "startup_signals": ["实体阳线≥3%", "close_above_ma5"],
            "best_buy_point": {
                "distance_from_reference_pct": 1.5,
                "confirmed_by": "30min两阳夹一阴确认",
                "confirmations": ["30min两阳夹一阴确认"],
                "startup_signals": ["实体阳线≥3%", "close_above_ma5"],
            },
        }
        context = {
            "alpha_enabled": True,
            "source_count": 1,
            "data_quality": {"market_status": "verified"},
            "by_source": {"main": {"volume_ratio": 1.3}},
            "market": {"index_trend_score": 45, "breadth_score": 40},
            "metrics": {"distance": 1.5},
            "best_buy_point": {"distance_from_reference_pct": 1.5},
        }

        _, trace = compute_opportunity_score(item, "main", context)
        self.assertGreater(trace["alpha_bonus"], 0)
        self.assertLessEqual(trace["alpha_bonus"], ALPHA_BONUS_LIMIT)
        self.assertEqual(trace["alpha_features"]["breakout_quality"]["ma_bullish"], True)
        self.assertIn("30min两阳夹一阴确认", trace["alpha_features"]["breakout_quality"]["confirmed_by"])

    def test_alpha_bonus_is_capped(self):
        item = {
            "score": 50,
            "change_pct": 6.0,
            "volume_ratio": 8.0,
            "ma_bullish": True,
            "confirmed_by": "30min两阳夹两阴确认",
            "confirmations": ["30min两阳夹两阴确认", "其他确认"],
            "startup_signals": ["实体阳线≥3%", "close_above_ma5", "close_above_ma10", "break_20d_high"],
            "sector_rank": 1,
            "sector_flow": 3200,
            "best_buy_point": {
                "distance_from_reference_pct": 1.0,
                "confirmed_by": "30min两阳夹两阴确认",
                "confirmations": ["30min两阳夹两阴确认"],
                "startup_signals": ["实体阳线≥3%", "close_above_ma5", "close_above_ma10", "break_20d_high"],
            },
        }
        context = {
            "alpha_enabled": True,
            "source_count": 3,
            "sources": ["main", "acceleration", "luojie"],
            "market": {"index_trend_score": 120, "breadth_score": 100, "market_regime_factor": 99},
            "data_quality": {"market_status": "verified"},
            "metrics": {"distance": 0.8},
            "by_source": {
                "main": {"data_status": {"daily": "verified"}, "volume_ratio": 8.0},
            },
        }

        score, trace = compute_opportunity_score(item, "main", context)
        self.assertEqual(trace["alpha_bonus"], ALPHA_BONUS_LIMIT)
        self.assertEqual(score, trace["opportunity_score"])
        self.assertLessEqual(trace["alpha_multiplier"], ALPHA_MULTIPLIER_MAX)

    def test_alpha_disabled_preserves_baseline_scoring(self):
        item = {
            "score": 55,
            "change_pct": 3.0,
            "best_buy_point": {"distance_from_reference_pct": 1.5},
            "ma_bullish": True,
            "volume_ratio": 2.2,
            "confirmed_by": "30min两阳夹一阴确认",
            "confirmations": ["30min两阳夹一阴确认"],
            "startup_signals": ["实体阳线≥3%"],
        }
        context = {
            "alpha_enabled": False,
            "source_count": 3,
            "sources": ["main", "acceleration", "luojie"],
            "market": {"index_trend_score": 120, "breadth_score": 100},
            "data_quality": {"market_status": "verified"},
            "metrics": {"distance": 1.0},
        }

        score, trace = compute_opportunity_score(item, "main", context)
        self.assertEqual(score, trace["base_opportunity_score"])
        self.assertEqual(trace["alpha_bonus"], 0)
        self.assertEqual(trace["pool_quality_bonus"], 0)
        self.assertEqual(trace["pool_quality_score"], 0)
        self.assertEqual(trace["pool_quality_tags"], [])
        self.assertEqual(trace["alpha_multiplier"], 1.0)

    def test_alpha_without_pool_quality_is_unchanged(self):
        item = {"score": 50, "change_pct": 4.0, "best_buy_point": {"distance_from_reference_pct": 1.2}}
        base_context = {
            "alpha_enabled": True,
            "source_count": 1,
            "market": {"index_trend_score": 45, "breadth_score": 55},
            "data_quality": {"market_status": "verified"},
        }

        _, trace_without_pool_quality = compute_opportunity_score(item, "main", base_context)
        _, trace_with_pool_quality = compute_opportunity_score(
            item,
            "main",
            {
                **base_context,
                "alpha_features": {"pool_quality": None},
            },
        )

        self.assertEqual(trace_without_pool_quality["alpha_bonus"], trace_with_pool_quality["alpha_bonus"])
        self.assertEqual(trace_with_pool_quality["pool_quality_bonus"], 0)
        self.assertEqual(trace_with_pool_quality["pool_quality_score"], 0)
        self.assertEqual(trace_with_pool_quality["pool_quality_tags"], [])
        self.assertEqual(trace_with_pool_quality["pool_quality_tier"], "none")

    def test_alpha_pool_quality_single_leg_not_notably_scored(self):
        item = {"score": 45}
        _, trace = compute_opportunity_score(
            item,
            "main",
            {
                "alpha_enabled": True,
                "source_count": 1,
                "alpha_features": {
                    "pool_quality": {
                        "liquidity_score": 60,
                        "growth_board_score": 40,
                        "sector_quality_score": 40,
                        "pool_quality_tags": ["liquidity", "growth", "sector"],
                    },
                },
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertEqual(trace["pool_quality_bonus"], 0)
        self.assertEqual(trace["pool_quality_tier"], "none")
        self.assertAlmostEqual(trace["pool_quality_score"], 46.6667, places=4)
        self.assertEqual(trace["pool_quality_tags"], ["liquidity", "growth", "sector"])

    def test_alpha_pool_quality_partial_two_legs_small_bonus(self):
        _, trace = compute_opportunity_score(
            {"score": 45},
            "main",
            {
                "alpha_enabled": True,
                "source_count": 1,
                "alpha_features": {
                    "pool_quality": {
                        "liquidity_score": 60,
                        "growth_board_score": 80,
                        "sector_quality_score": 50,
                    },
                },
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertEqual(trace["pool_quality_tier"], "partial")
        self.assertAlmostEqual(trace["pool_quality_bonus"], 0.49, places=6)
        self.assertLess(trace["pool_quality_bonus"], 0.7)
        self.assertGreater(trace["pool_quality_bonus"], 0)

    def test_alpha_pool_quality_strong_mid_bonus(self):
        _, trace = compute_opportunity_score(
            {"score": 45},
            "main",
            {
                "alpha_enabled": True,
                "source_count": 1,
                "alpha_features": {
                    "pool_quality": {
                        "liquidity_score": 80,
                        "growth_board_score": 65,
                        "sector_quality_score": 65,
                    },
                },
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertEqual(trace["pool_quality_tier"], "strong")
        self.assertAlmostEqual(trace["pool_quality_bonus"], 1.26, places=6)
        self.assertLess(trace["pool_quality_bonus"], 3.0)
        self.assertGreater(trace["pool_quality_bonus"], 0.7)

    def test_alpha_pool_quality_elite_high_bonus(self):
        _, trace = compute_opportunity_score(
            {"score": 45},
            "main",
            {
                "alpha_enabled": True,
                "source_count": 1,
                "alpha_features": {
                    "pool_quality": {
                        "liquidity_score": 90,
                        "growth_board_score": 95,
                        "sector_quality_score": 90,
                    },
                },
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertEqual(trace["pool_quality_tier"], "elite")
        self.assertAlmostEqual(trace["pool_quality_bonus"], 2.75, places=6)
        self.assertGreater(trace["pool_quality_bonus"], 1.8)

    def test_alpha_pool_quality_extreme_values_are_clamped(self):
        _, trace = compute_opportunity_score(
            {
                "score": 30,
                "best_buy_point": {"distance_from_reference_pct": 1.0},
            },
            "main",
            {
                "alpha_enabled": True,
                "source_count": 1,
                "alpha_features": {
                    "pool_quality": {
                        "liquidity_score": 9999,
                        "growth_board_score": 9999,
                        "sector_quality_score": 9999,
                        "pool_quality_score": 9999,
                    },
                },
            },
        )

        self.assertEqual(trace["pool_quality_bonus"], 3.0)
        self.assertEqual(trace["pool_quality_score"], 100)

    def test_alpha_pool_quality_bonus_is_subject_to_global_limit(self):
        context = {
            "alpha_enabled": True,
            "source_count": 1,
            "market": {"index_trend_score": 120, "breadth_score": 100, "market_regime_factor": 120},
            "alpha_features": {
                "pool_quality": {
                    "liquidity_score": 100,
                    "growth_board_score": 100,
                    "sector_quality_score": 100,
                },
                "sector_rank": 1,
                "sector_flow": 3200,
            },
            "data_quality": {"market_status": "verified"},
            "by_source": {
                "main": {"volume_ratio": 8.0},
            },
            "metrics": {"distance": 1.0},
        }
        _, trace = compute_opportunity_score(
            {
                "score": 30,
                "best_buy_point": {"distance_from_reference_pct": 1.2},
                "ma_bullish": True,
                "volume_ratio": 2.0,
                "confirmed_by": "30min两阳夹两阴确认",
                "confirmations": ["30min两阳夹两阴确认"],
                "startup_signals": ["实体阳线≥3%"],
            },
            "main",
            context,
        )

        self.assertEqual(trace["pool_quality_tier"], "elite")
        self.assertEqual(trace["alpha_bonus"], ALPHA_BONUS_LIMIT)
        self.assertEqual(trace["pool_quality_bonus"], 3.0)

    def test_context_risk_flags_are_respected(self):
        _, trace = compute_opportunity_score(
            {
                "score": 40,
                "best_buy_point": {"distance_from_reference_pct": 4.0},
            },
            "main",
            {
                "risk_flags": ["距离过近", "距参考价偏高"],
                "source_count": 1,
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertIn("距离过近", trace["risk_flags"])
        self.assertIn("距参考价偏高", trace["risk_flags"])
        self.assertGreater(trace["risk_penalty"], 0)

    def test_context_source_count_override_with_sources(self):
        _, trace = compute_opportunity_score(
            {
                "score": 40,
                "best_buy_point": {"distance_from_reference_pct": 4.0},
            },
            "main",
            {
                "source_count": 1,
                "sources": ["main", "acceleration", "luojie"],
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertEqual(trace["source_count"], 3)

    def test_risk_penalty_is_capped(self):
        by_source = {
            "main": {
                "distance_from_reference_pct": 10.0,
                "change_pct": 10.0,
                "signal_age_days": 9,
            },
        }
        _, trace = compute_opportunity_score(
            {
                "score": 50,
                "best_buy_point": {
                    "signal_age_days": 9,
                    "distance_from_reference_pct": 10.0,
                },
            },
            "main",
            {
                "source_count": 1,
                "by_source": by_source,
                "data_quality": {"market_status": "verified"},
            },
        )

        self.assertLessEqual(trace["risk_penalty"], 30)


if __name__ == "__main__":
    unittest.main()
