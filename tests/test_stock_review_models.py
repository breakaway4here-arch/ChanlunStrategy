"""Unit tests for stock_review models."""
import json
import unittest
from chanlun.stock_review.models import Holding, StockReviewResult


class TestHolding(unittest.TestCase):

    def test_full_holding(self):
        h = Holding(
            account="广发易淘金",
            code="600519",
            name="贵州茅台",
            source="excel",
            quantity=100,
            cost_price=1520.0,
            market_price=1480.0,
            market_value=148000.0,
            pnl=-4000.0,
            pnl_pct=-2.63,
        )
        self.assertEqual(h.account, "广发易淘金")
        self.assertEqual(h.code, "600519")
        self.assertEqual(h.name, "贵州茅台")
        self.assertEqual(h.source, "excel")
        self.assertEqual(h.quantity, 100)
        self.assertEqual(h.cost_price, 1520.0)
        self.assertEqual(h.market_price, 1480.0)
        self.assertEqual(h.market_value, 148000.0)
        self.assertEqual(h.pnl, -4000.0)
        self.assertEqual(h.pnl_pct, -2.63)

    def test_degraded_holding_name_only(self):
        h = Holding(
            account="其他账户A",
            code="",
            name="中际旭创",
            source="manual",
        )
        self.assertEqual(h.name, "中际旭创")
        self.assertEqual(h.code, "")
        self.assertIsNone(h.quantity)
        self.assertIsNone(h.cost_price)

    def test_degraded_holding_code_only(self):
        h = Holding(
            account="其他账户B",
            code="300750",
            name="宁德时代",
            source="manual",
        )
        self.assertEqual(h.code, "300750")
        self.assertEqual(h.name, "宁德时代")
        self.assertIsNone(h.cost_price)

    def test_note_field(self):
        h = Holding(
            account="test", code="000001", name="平安银行", source="manual",
            note="只知道持有，未录入成本"
        )
        self.assertEqual(h.note, "只知道持有，未录入成本")


class TestStockReviewResult(unittest.TestCase):

    def test_can_serialize_to_json(self):
        h = Holding(
            account="广发易淘金", code="600519", name="贵州茅台",
            source="excel", quantity=100, cost_price=1520.0,
        )
        result = StockReviewResult(
            holding=h,
            price_snapshot={"close": 1480.0, "date": "2026-05-26"},
            chanlun_daily={"trend_type": "盘整", "pivots": []},
            chanlun_30min={"trend_type": "下跌趋势"},
            fundamentals={"pe": 25.0},
            news={"positive": [], "negative": [], "neutral": []},
            rule_action={"action": "HOLD", "confidence": "medium"},
            llm_review={"stance": "agree"},
            risks=[{"type": "跌破ZD", "triggered": False}],
        )
        d = result.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["holding"]["code"], "600519")
        self.assertEqual(parsed["holding"]["name"], "贵州茅台")
        self.assertEqual(parsed["rule_action"]["action"], "HOLD")
        self.assertEqual(len(parsed["risks"]), 1)

    def test_empty_llm_review(self):
        h = Holding(account="test", code="000001", name="平安银行", source="manual")
        result = StockReviewResult(
            holding=h,
            price_snapshot={},
            chanlun_daily={},
            chanlun_30min={},
            fundamentals={},
            news={},
            rule_action={},
            llm_review={},
            risks=[],
        )
        d = result.to_dict()
        self.assertEqual(d["llm_review"], {})


if __name__ == "__main__":
    unittest.main()
