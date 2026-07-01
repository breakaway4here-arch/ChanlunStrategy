import unittest

from chanlun.scoring_engine import compute_opportunity_score


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
