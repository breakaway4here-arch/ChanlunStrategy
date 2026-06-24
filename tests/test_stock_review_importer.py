"""Unit tests for stock_review importer."""
import os
import json
import unittest
import tempfile
from chanlun.stock_review.importer import (
    parse_excel_holdings,
    normalize_holdings,
    merge_holdings_by_code,
    resolve_names,
    parse_note_cost,
)


class TestParseExcelHoldings(unittest.TestCase):

    def test_parse_gf_excel(self):
        excel_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "持仓数据", "广发易淘金PC版-持仓.xlsx"
        )
        if not os.path.exists(excel_path):
            self.skipTest("Excel file not found")
        holdings = parse_excel_holdings(excel_path, account="广发易淘金")
        self.assertGreater(len(holdings), 0)
        for h in holdings:
            self.assertEqual(h.account, "广发易淘金")
            self.assertEqual(h.source, "excel")
            self.assertTrue(len(h.name) > 0)
        # At least some holdings have quantity/cost (real positions)
        holdings_with_qty = [h for h in holdings if h.quantity is not None]
        self.assertGreater(len(holdings_with_qty), 0)
        for h in holdings_with_qty:
            self.assertIsNotNone(h.cost_price)
        # Resolve codes from name cache
        resolved, unresolved, _ = resolve_names(holdings)
        self.assertEqual(len(unresolved), 0, f"unresolved: {[h.name for h in unresolved]}")
        for h in resolved:
            self.assertTrue(len(h.code) > 0, f"code empty for {h.name}")


class TestNormalizeHoldings(unittest.TestCase):

    def test_strip_and_dedup_code(self):
        raw = [{"name": " 贵州茅台 ", "code": "600519"}]
        result = normalize_holdings(raw, account="test", source="manual")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "贵州茅台")
        self.assertEqual(result[0].code, "600519")

    def test_name_only_no_code(self):
        raw = [{"name": "中际旭创"}]
        result = normalize_holdings(raw, account="test", source="manual")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "中际旭创")
        self.assertEqual(result[0].code, "")

    def test_code_only_no_name(self):
        raw = [{"code": "300750"}]
        result = normalize_holdings(raw, account="test", source="manual")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "300750")
        self.assertEqual(result[0].name, "")


class TestMergeHoldingsByCode(unittest.TestCase):

    def test_same_code_merged(self):
        h1 = type('Holding', (), {
            'account': 'A', 'code': '600519', 'name': '贵州茅台',
            'source': 'excel', 'quantity': 100, 'cost_price': 1500.0,
            'market_price': 1480.0, 'market_value': 148000.0,
            'pnl': -2000.0, 'pnl_pct': -1.33, 'note': '',
        })()
        h2 = type('Holding', (), {
            'account': 'B', 'code': '600519', 'name': '贵州茅台',
            'source': 'manual', 'quantity': None, 'cost_price': None,
            'market_price': None, 'market_value': None,
            'pnl': None, 'pnl_pct': None, 'note': '',
        })()
        from chanlun.stock_review.models import Holding
        merged = merge_holdings_by_code([h1, h2])
        self.assertEqual(len(merged), 1)
        code, group = merged.popitem()
        self.assertEqual(code, "600519")
        self.assertEqual(len(group["accounts"]), 2)

    def test_different_codes_not_merged(self):
        from chanlun.stock_review.models import Holding
        h1 = Holding(account="A", code="600519", name="茅台", source="excel")
        h2 = Holding(account="A", code="000858", name="五粮液", source="excel")
        merged = merge_holdings_by_code([h1, h2])
        self.assertEqual(len(merged), 2)


class TestResolveNames(unittest.TestCase):

    def test_unresolved_output(self):
        from chanlun.stock_review.models import Holding
        holdings = [Holding(account="test", code="", name="不存在的股票", source="manual")]
        resolved, unresolved, ambiguous = resolve_names(holdings)
        self.assertEqual(len(resolved), 0)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].name, "不存在的股票")

    def test_resolved_by_code(self):
        from chanlun.stock_review.models import Holding
        holdings = [Holding(account="test", code="600519", name="", source="manual")]
        resolved, unresolved, ambiguous = resolve_names(holdings)
        # Should resolve name from cache if possible, or keep as-is with code
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].code, "600519")


class TestParseNoteCost(unittest.TestCase):

    def test_cost_with_space(self):
        self.assertAlmostEqual(parse_note_cost("成本 35.77"), 35.77)

    def test_cost_with_colon(self):
        self.assertAlmostEqual(parse_note_cost("成本:35.77"), 35.77)

    def test_cost_english(self):
        self.assertAlmostEqual(parse_note_cost("cost 35.77"), 35.77)

    def test_buy_price(self):
        self.assertAlmostEqual(parse_note_cost("买入价 35.77"), 35.77)

    def test_no_cost_returns_none(self):
        self.assertIsNone(parse_note_cost("只知道持有，未录入成本"))

    def test_empty_note_returns_none(self):
        self.assertIsNone(parse_note_cost(""))

    def test_none_note_returns_none(self):
        self.assertIsNone(parse_note_cost(None))

    def test_normalize_applies_cost_parsing(self):
        raw = [{"name": "中际旭创", "note": "成本 35.77"}]
        result = normalize_holdings(raw, account="test", source="manual")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].cost_price, 35.77)
        self.assertEqual(result[0].note, "成本 35.77")


if __name__ == "__main__":
    unittest.main()
