"""Unit tests for stock_review LLM review module."""
import json
import unittest
from unittest.mock import patch, MagicMock
from chanlun.stock_review.llm_review import (
    build_llm_input,
    parse_llm_response,
    generate_rule_summary_fallback,
    run_llm_review,
)


class TestBuildLLMInput(unittest.TestCase):

    def test_contains_fundamental_six_sections(self):
        """Prompt must require 6 fundamental analysis sections."""
        facts = {"holding": {}, "daily_structure": {}, "min30_structure": {},
                 "fundamentals": {}, "news": {}, "rule_action": {}}
        prompt = build_llm_input(facts)
        self.assertIn("公司是干什么的", prompt)
        self.assertIn("成长性", prompt)
        self.assertIn("盈利质量", prompt)
        self.assertIn("财务安全性", prompt)
        self.assertIn("估值", prompt)
        self.assertIn("风险与催化", prompt)

    def test_contains_news_classification(self):
        facts = {"holding": {}, "daily_structure": {}, "min30_structure": {},
                 "fundamentals": {}, "news": {}, "rule_action": {}}
        prompt = build_llm_input(facts)
        self.assertIn("消息面分析", prompt)
        self.assertIn("price-in", prompt.lower())
        self.assertIn("后续跟踪", prompt)

    def test_only_contains_structured_facts(self):
        facts = {
            "holding": {"code": "600519", "name": "贵州茅台"},
            "daily_structure": {"close": 1500.0, "trend_type": "盘整"},
            "min30_structure": {"close": 1495.0},
            "fundamentals": {"pe": 30},
            "news": {"summary": "测试"},
            "rule_action": {"action": "HOLD"},
        }
        prompt = build_llm_input(facts)
        self.assertIn("600519", prompt)
        self.assertIn("HOLD", prompt)


class TestParseLLMResponse(unittest.TestCase):

    def test_parses_new_schema_fields(self):
        resp = '''```json
{
  "executive_summary": "测试",
  "mid_term_view": "中线逻辑测试",
  "short_term_catalysts": [],
  "short_term_risks": [],
  "event_window_days": 5,
  "fundamental_analysis": {
    "rating": "中",
    "summary": "基本面总体一般",
    "business": {"title": "公司是干什么的", "conclusion": "制造业"},
    "growth": {"conclusion": "增长放缓"},
    "profit_quality": {"conclusion": "一般"},
    "financial_safety": {"conclusion": "安全"},
    "valuation": {"conclusion": "合理"},
    "risks_and_catalysts": {"risks": [], "catalysts": []},
    "data_gaps": ["缺少ROE"],
    "chanlun_relation": "基本面支持持有"
  },
  "news_analysis": {
    "rating": "中性",
    "summary": "无重大消息",
    "key_news": [],
    "risk_news": [],
    "follow_up": [],
    "data_gaps": []
  },
  "chanlun_structure_comment": "盘整中",
  "integrated_decision": {
    "action": "HOLD",
    "reason": "中枢内无明确卖点",
    "add_condition": "30min底分型确认",
    "reduce_condition": "跌破ZD",
    "stop_condition": "跌破成本8%",
    "confidence": "中"
  },
  "data_quality": {
    "fundamental_complete": false,
    "news_complete": false,
    "missing_fields": ["ROE", "现金流"]
  }
}
```'''
        result = parse_llm_response(resp)
        self.assertEqual(result["fundamental_analysis"]["rating"], "中")
        self.assertEqual(result["integrated_decision"]["action"], "HOLD")
        self.assertEqual(result["data_quality"]["fundamental_complete"], False)
        self.assertEqual(result["mid_term_view"], "中线逻辑测试")
        self.assertEqual(result["event_window_days"], 5)

    def test_fallback_has_llm_enabled_false(self):
        result = generate_rule_summary_fallback({"action": "HOLD"})
        self.assertFalse(result.get("llm_enabled", True))
        self.assertEqual(result["integrated_decision"]["action"], "HOLD")


class TestGenerateRuleSummaryFallback(unittest.TestCase):

    def test_includes_new_schema_structure(self):
        rule_action = {"action": "HOLD", "primary_reason": "中枢内，无卖点"}
        summary = generate_rule_summary_fallback(rule_action)
        self.assertIn("fundamental_analysis", summary)
        self.assertIn("news_analysis", summary)
        self.assertIn("integrated_decision", summary)
        self.assertIn("mid_term_view", summary)
        self.assertIn("short_term_catalysts", summary)
        self.assertIn("short_term_risks", summary)
        self.assertFalse(summary["llm_enabled"])


class TestRunLLMReview(unittest.TestCase):

    @patch("chanlun.stock_review.llm_review._call_llm_with_retry")
    def test_no_llm_insufficient_data_still_skips_remote_call(self, mock_retry):
        """--no-llm must not trigger any remote LLM call even with sparse fundamentals."""
        facts = {"holding": {"code": "000001", "name": "测试"},
                 "daily_structure": {}, "min30_structure": {},
                 "fundamentals": {}, "news": {},
                 "rule_action": {"action": "HOLD"}}
        result = run_llm_review(facts, use_llm=False)
        self.assertFalse(result.get("llm_enabled", True))
        mock_retry.assert_not_called()

    @patch("chanlun.stock_review.llm_review._call_llm_with_retry")
    def test_no_llm_sufficient_data_skips_llm(self, mock_retry):
        """When API data is sufficient, --no-llm should skip LLM entirely."""
        facts = {
            "holding": {"code": "600519", "name": "贵州茅台"},
            "daily_structure": {}, "min30_structure": {},
            "fundamentals": {
                "business": "白酒生产和销售",
                "industry": "白酒", "pe": 28.6, "pb": 8.3, "roe": 31.2,
            },
            "news": {}, "rule_action": {"action": "HOLD"},
        }
        result = run_llm_review(facts, use_llm=False)
        self.assertFalse(result.get("llm_enabled", True))
        mock_retry.assert_not_called()

    @patch("chanlun.stock_review.llm_review._call_llm")
    def test_llm_failure_falls_back_with_false_flag(self, mock_call):
        mock_call.side_effect = Exception("API error")
        facts = {"holding": {}, "daily_structure": {}, "min30_structure": {},
                 "fundamentals": {}, "news": {}, "rule_action": {"action": "HOLD"}}
        result = run_llm_review(facts, use_llm=True)
        self.assertFalse(result.get("llm_enabled", True))

    @patch("chanlun.stock_review.llm_review._call_llm")
    def test_llm_bad_json_preserves_rule_action(self, mock_call):
        mock_call.return_value = "not-json"
        facts = {
            "holding": {"code": "600000", "name": "测试"},
            "daily_structure": {},
            "min30_structure": {},
            "fundamentals": {},
            "news": {},
            "rule_action": {"action": "STOP", "primary_reason": "跌破止损位"},
        }
        result = run_llm_review(facts, use_llm=True)
        self.assertEqual(result["integrated_decision"]["action"], "STOP")
        self.assertIn("跌破止损位", result["integrated_decision"]["reason"])

    def test_no_llm_uses_raw_facts_for_fallback_analysis(self):
        facts = {
            "holding": {"code": "600519", "name": "贵州茅台"},
            "daily_structure": {"trend_type": "盘整", "position": "中枢内"},
            "min30_structure": {},
            "fundamentals_raw": {
                "company_name": "贵州茅台",
                "industry": "白酒",
                "market_cap": 2200000000000,
                "pe": 28.6,
                "pb": 8.3,
                "roe": 31.2,
                "gross_margin": 91.5,
                "net_margin": 52.4,
                "revenue_yoy": 15.6,
                "profit_yoy": 14.1,
                "debt_ratio": 18.2,
                "missing_fields": ["经营现金流"],
            },
            "news_raw": [
                {
                    "title": "贵州茅台发布2026年一季报",
                    "time": "2026-05-26",
                    "source": "巨潮资讯",
                    "url": "https://example.com/1",
                    "matched_reason": "股票名称匹配",
                    "category": "业绩类",
                    "sentiment": "中性",
                    "impact_strength": "中",
                }
            ],
            "rule_action": {"action": "HOLD", "primary_reason": "中枢内无卖点"},
        }
        result = run_llm_review(facts, use_llm=False)
        self.assertFalse(result.get("llm_enabled", True))
        self.assertNotEqual(result["fundamental_analysis"]["rating"], "数据不足")
        self.assertIn("白酒", result["fundamental_analysis"]["summary"])
        self.assertEqual(len(result["news_analysis"]["key_news"]), 1)
        self.assertIn("一季报", result["news_analysis"]["summary"])
        self.assertEqual(result["event_window_days"], 5)


if __name__ == "__main__":
    unittest.main()
