"""Unit tests for stock_review CLI entry points."""
import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock


class TestReviewHoldingsCLI(unittest.TestCase):

    def test_module_importable(self):
        """review_holdings module can be imported."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import review_holdings
            self.assertTrue(hasattr(review_holdings, 'main'))
        finally:
            sys.path.pop(0)

    @patch('chanlun.stock_review.importer.load_accounts')
    @patch('chanlun.stock_review.report_generator.write_report')
    def test_main_no_llm_runs(self, mock_write, mock_load):
        """review_holdings --no-llm runs without error."""
        mock_load.return_value = []
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import review_holdings
            review_holdings.main(use_llm=False, output_dir=None)
            mock_load.assert_called_once()
        finally:
            sys.path.pop(0)


class TestReviewStockCLI(unittest.TestCase):

    def test_module_importable(self):
        """review_stock module can be imported."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import review_stock
            self.assertTrue(hasattr(review_stock, 'main'))
        finally:
            sys.path.pop(0)

    @patch('chanlun.stock_review.report_generator.write_report')
    def test_main_with_stocks_no_llm(self, mock_write):
        """review_stock --stocks 600519,宁德时代 --no-llm runs without error."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import review_stock
            review_stock.main(stocks=["600519", "宁德时代"], use_llm=False, output_dir=None)
        finally:
            sys.path.pop(0)

    def test_parse_stocks_arg(self):
        """Parse comma-separated stock list."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import review_stock
            result = review_stock.parse_stocks_arg("600519,宁德时代,新易盛")
            self.assertEqual(result, ["600519", "宁德时代", "新易盛"])
            result2 = review_stock.parse_stocks_arg("600519")
            self.assertEqual(result2, ["600519"])
        finally:
            sys.path.pop(0)


class TestUnresolvedOutput(unittest.TestCase):

    def test_unresolved_names_logged(self):
        """Unresolved stock names produce a warning not a crash."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            import review_stock
            # Empty result is fine - unresolved names should just be logged
            unresolved = review_stock.resolve_stock_names(["不存在的股票名称XYZ123"])
            # Should return something (maybe empty list if can't resolve)
            self.assertIsInstance(unresolved, list)
        finally:
            sys.path.pop(0)


class TestLLMFactsStructure(unittest.TestCase):

    def test_build_llm_input_accepts_raw_fields(self):
        """build_llm_input works with fundamentals_raw and news_raw keys."""
        from chanlun.stock_review.llm_review import build_llm_input
        facts = {
            "holding": {"code": "600519", "name": "茅台"},
            "daily_structure": {"close": 1500},
            "min30_structure": {},
            "fundamentals_raw": {"pe": 30, "pb": 8},
            "news_raw": [{"title": "中标大单", "time": "2026-05-26"}],
            "rule_action": {"action": "HOLD"},
        }
        prompt = build_llm_input(facts)
        self.assertIn("fundamentals_raw", prompt)
        self.assertIn("news_raw", prompt)
        self.assertIn("中标大单", prompt)
        self.assertIn('"pe": 30', prompt)

    def test_run_llm_review_no_llm_identifiable(self):
        """With use_llm=False and sufficient data, llm_enabled=False."""
        from chanlun.stock_review.llm_review import run_llm_review
        facts = {
            "rule_action": {"action": "HOLD"},
            "fundamentals": {"business": "测试", "pe": 20, "pb": 2, "roe": 10},
        }
        result = run_llm_review(facts, use_llm=False)
        self.assertFalse(result.get("llm_enabled", True))
        self.assertIn("integrated_decision", result)
        self.assertIn("fundamental_analysis", result)
        self.assertIn("news_analysis", result)

    def test_fallback_schema_has_required_sections(self):
        """Rule fallback contains all sections needed for report rendering."""
        from chanlun.stock_review.llm_review import generate_rule_summary_fallback
        result = generate_rule_summary_fallback(
            {"action": "WATCH", "primary_reason": "中枢下方",
             "stop_condition": "跌破5%", "add_condition": "", "reduce_condition": ""}
        )
        self.assertIn("executive_summary", result)
        self.assertIn("fundamental_analysis", result)
        self.assertIn("news_analysis", result)
        self.assertIn("integrated_decision", result)
        self.assertIn("data_quality", result)
        self.assertFalse(result["llm_enabled"])


if __name__ == "__main__":
    unittest.main()
