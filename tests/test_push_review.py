"""Unit tests for push_review summary building."""
import unittest

from push_review import _build_summary


class TestPushReviewSummary(unittest.TestCase):

    def test_uses_rule_action_for_counts_and_risk_lines(self):
        data = {
            "overview": {},
            "results": [
                {
                    "holding": {"name": "测试A", "code": "600000", "cost_price": 10},
                    "price_snapshot": {"close": 9.0},
                    "rule_action": {"action": "STOP", "primary_reason": "跌破止损位"},
                    "llm_review": {
                        "llm_enabled": True,
                        "fundamental_analysis": {"rating": "中"},
                        "integrated_decision": {"action": "HOLD", "reason": "LLM想继续观察"},
                    },
                }
            ],
            "highlights": [],
        }

        summary = _build_summary(data, "2026-05-29")
        self.assertIn("止损:1", summary)
        self.assertIn("测试A(600000) — 止损: 跌破止损位", summary)
        self.assertNotIn("持有:1", summary)


if __name__ == "__main__":
    unittest.main()
