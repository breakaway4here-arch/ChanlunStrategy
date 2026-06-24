"""Unit tests for stock_review notify module."""
import unittest
from chanlun.stock_review.notify import generate_summary, NoOpNotifier


class TestGenerateSummary(unittest.TestCase):

    def setUp(self):
        self.results = [
            {
                "holding": {"code": "000001", "name": "股票A"},
                "rule_action": {"action": "STOP", "primary_reason": "跌破ZD"},
            },
            {
                "holding": {"code": "000002", "name": "股票B"},
                "rule_action": {"action": "REDUCE", "primary_reason": "顶背驰"},
            },
            {
                "holding": {"code": "000003", "name": "股票C"},
                "rule_action": {"action": "HOLD", "primary_reason": "中枢内"},
            },
            {
                "holding": {"code": "000004", "name": "股票D"},
                "rule_action": {"action": "HOLD", "primary_reason": "中枢内"},
            },
            {
                "holding": {"code": "000005", "name": "股票E"},
                "rule_action": {"action": "ADD_ON_CONFIRM", "primary_reason": "30min有信号"},
            },
        ]

    def test_high_risk_listed_first(self):
        summary = generate_summary(self.results, report_url="http://example.com")
        self.assertIn("股票A", summary)
        self.assertIn("股票B", summary)
        # High risk line appears before HOLD count line
        idx_high = summary.index("高风险")
        idx_hold = summary.index("可继续持有")
        self.assertLess(idx_high, idx_hold)

    def test_includes_counts(self):
        summary = generate_summary(self.results, report_url="http://example.com")
        self.assertIn("高风险", summary)
        self.assertIn("2 只", summary)
        self.assertIn("继续持有", summary)

    def test_includes_report_url(self):
        summary = generate_summary(self.results, report_url="http://example.com")
        self.assertIn("http://example.com", summary)

    def test_empty_results(self):
        summary = generate_summary([], report_url="http://example.com")
        self.assertIn("无持仓", summary)


class TestNoOpNotifier(unittest.TestCase):

    def test_send_does_not_raise(self):
        notifier = NoOpNotifier()
        notifier.send("测试消息")

    def test_no_webhook_no_error(self):
        notifier = NoOpNotifier()
        self.assertFalse(notifier.is_configured())


if __name__ == "__main__":
    unittest.main()
