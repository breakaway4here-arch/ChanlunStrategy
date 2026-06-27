import unittest

from chanlun.engine_dual_metrics import (
    build_aggregate_dual_business_metrics,
    build_dual_business_metrics,
    result_to_recommendations,
)


class _FakeResult:
    def __init__(self, code, buy_points):
        self.code = code
        self.buy_points = buy_points


class EngineDualMetricsTests(unittest.TestCase):
    def test_result_to_recommendations_none(self):
        self.assertEqual(result_to_recommendations(None), [])

    def test_result_to_recommendations_only_dict_buy_points(self):
        result = _FakeResult(
            "AAA",
            [
                {"type": "signal"},
                "ignore",
                {"another": "signal"},
            ],
        )
        self.assertEqual(
            result_to_recommendations(result),
            [
                {"code": "AAA", "best_buy_point": {"type": "signal"}},
                {"code": "AAA", "best_buy_point": {"another": "signal"}},
            ],
        )

    def test_build_dual_business_metrics_defaults(self):
        legacy = _FakeResult(
            "AAA",
            [{"type": "signal", "code": "X"}],
        )
        candidate = _FakeResult(
            "AAA",
            [{"type": "signal_alt", "code": "X"}],
        )
        comparison = {"summary": {"equal": False}}
        metrics = build_dual_business_metrics(
            legacy,
            candidate,
            comparison,
        )

        self.assertEqual(metrics["structure"], {"equal": False})
        self.assertIn("recommendation_diff", metrics)
        self.assertEqual(metrics["return_metrics"], {
            "status": "not_provided",
            "legacy": None,
            "candidate": None,
        })
        self.assertEqual(metrics["coverage"], {"status": "not_provided"})

    def test_build_aggregate_dual_business_metrics_defaults(self):
        legacy_recommendations = [{"code": "AAA", "best_buy_point": {"type": "signal"}}]
        candidate_recommendations = [{"code": "AAA", "best_buy_point": {"type": "signal"}}]
        metrics = build_aggregate_dual_business_metrics(
            legacy_recommendations,
            candidate_recommendations,
        )

        self.assertEqual(metrics["structure"], None)
        self.assertIn("recommendation_diff", metrics)
        self.assertEqual(metrics["return_metrics"]["status"], "not_provided")
        self.assertEqual(metrics["coverage"]["status"], "not_provided")


if __name__ == "__main__":
    unittest.main()
