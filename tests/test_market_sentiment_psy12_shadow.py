import unittest
from datetime import date, timedelta

from chanlun.market_sentiment import build_market_sentiment_psy12_shadow
from scripts.evaluate_market_sentiment_psy12_shadow import evaluate_shadow_reports


def _reports(count=31):
    start = date(2026, 7, 1)
    points = []
    reports = []
    for index in range(count):
        trade_date = (start + timedelta(days=index)).isoformat()
        change = [0.8, -0.5, 0.0, 1.2, -0.3][index % 5]
        points.append({
            "date": trade_date,
            "evidence": {
                "index": {
                    "available": True,
                    "average_change_pct": change,
                }
            },
        })
        breadth = 35.0 + index
        components = {
            "breadth": breadth,
            "limit_ecology": 54.0,
            "index": 42.0 + index * 0.5,
            "turnover": 51.0,
            "trend": 48.0,
        }
        formal_raw = (
            components["breadth"] * 0.30
            + components["limit_ecology"] * 0.30
            + components["index"] * 0.15
            + components["turnover"] * 0.15
            + components["trend"] * 0.10
        )
        formal = {
            "date": trade_date,
            "score": round(formal_raw),
            "label": "偏强" if round(formal_raw) >= 60 else "平衡",
            "components": components,
        }
        shadow_fields = build_market_sentiment_psy12_shadow(formal, points)
        reports.append({
            "date": trade_date,
            "market_sentiment": formal,
            "market_sentiment_history": list(points),
            "psy12": shadow_fields["psy12"],
            "psy12_shadow": shadow_fields["psy12_shadow"],
        })
    return reports


class Psy12ShadowEvaluationTests(unittest.TestCase):
    def test_requires_twenty_complete_reproducible_days(self):
        result = evaluate_shadow_reports(_reports(30)[:-1], required_days=20)

        self.assertEqual(result["status"], "insufficient_observation_days")
        self.assertEqual(result["valid_days"], 18)
        self.assertFalse(result["promotion_eligible"])

    def test_generates_read_only_twenty_day_manual_review_audit(self):
        reports = _reports()
        before = repr(reports)

        result = evaluate_shadow_reports(reports, required_days=20)

        self.assertEqual(result["status"], "ready_for_manual_review")
        self.assertEqual(result["valid_days"], 20)
        self.assertEqual(len(result["daily"]), 20)
        self.assertEqual(result["recalculation_consistency_rate"], 1.0)
        self.assertIn("average_delta", result["summary"])
        self.assertIn("maximum_absolute_delta", result["summary"])
        self.assertIn("label_change_count", result["summary"])
        self.assertIn("breadth", result["correlations"])
        self.assertIn("index", result["correlations"])
        self.assertIn("hypothetical_changes", result)
        self.assertFalse(result["affects_production"])
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(repr(reports), before)

    def test_recalculation_mismatch_fails_manual_review_gate(self):
        reports = _reports()
        reports[-1]["psy12_shadow"]["shadow_score_with_psy12"] += 1

        result = evaluate_shadow_reports(reports, required_days=20)

        self.assertEqual(result["status"], "recalculation_mismatch")
        self.assertLess(result["recalculation_consistency_rate"], 1.0)
        self.assertFalse(result["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
