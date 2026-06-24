"""Unit tests for stock_review fundamentals module."""
import unittest
from unittest.mock import patch
from chanlun.stock_review.fundamentals import fetch_fundamentals


class TestFetchFundamentals(unittest.TestCase):

    def test_returns_dict_with_expected_keys(self):
        result = fetch_fundamentals("600519", "贵州茅台")
        self.assertIsInstance(result, dict)
        expected_keys = [
            "company_name", "industry", "business", "market_cap",
            "pe", "pb", "ps", "roe", "gross_margin", "net_margin",
            "revenue_yoy", "profit_yoy", "debt_ratio",
            "operating_cashflow", "accounts_receivable", "inventory",
            "goodwill", "cash", "interest_bearing_debt",
            "deducted_profit_yoy", "source", "updated_at",
            "missing_fields", "risk_flags", "status",
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_missing_fields_tracked(self):
        result = fetch_fundamentals("600519", "贵州茅台")
        self.assertIsInstance(result["missing_fields"], list)
        # Some fields will be missing from the API; that's OK
        # but they must be tracked

    def test_no_none_string_in_output(self):
        """Fields that are None should not become the string 'None'."""
        result = fetch_fundamentals("600519", "贵州茅台")
        for key, val in result.items():
            if isinstance(val, str):
                self.assertNotEqual(val, "None", f"Field {key} is string 'None'")

    def test_failure_does_not_raise(self):
        result = fetch_fundamentals("000001", "平安银行")
        self.assertIn("status", result)

    def test_empty_code_returns_degraded(self):
        result = fetch_fundamentals("", "未知股票")
        self.assertEqual(result["status"], "degraded")

    def test_has_source_field(self):
        result = fetch_fundamentals("600519", "贵州茅台")
        self.assertTrue(result["source"])

    @patch("chanlun.stock_review.fundamentals._eastmoney_profile")
    def test_normalizes_implausible_ratio_scales(self, mock_profile):
        mock_profile.return_value = {
            "company_name": "测试公司",
            "industry": "半导体",
            "pe": 20314,
            "pb": 560,
            "market_cap": 24085137194.71,
            "roe": 3145,
            "revenue_yoy": 2683,
            "profit_yoy": 2566,
            "gross_margin": 168254,
            "net_margin": 88,
            "debt_ratio": 3278,
        }
        result = fetch_fundamentals("300102", "测试公司")
        self.assertLess(result["pe"], 1000)
        self.assertLess(result["pb"], 100)
        self.assertLess(result["gross_margin"], 1000)
        self.assertLess(result["debt_ratio"], 1000)


if __name__ == "__main__":
    unittest.main()
