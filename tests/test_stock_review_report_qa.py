"""Unit tests for stock review report QA checks."""
import json
import os
import unittest
import tempfile
from scripts.qa_stock_review_report import check_json, check_html


def _make_test_data(results=None):
    """Build a minimal data JSON dict for QA testing."""
    if results is None:
        results = [{
            "holding": {"code": "600519", "name": "茅台"},
            "llm_review": {
                "llm_enabled": True,
                "fundamental_analysis": {"rating": "中", "summary": "稳健", "business": {}, "growth": {}, "profit_quality": {}, "financial_safety": {}, "valuation": {}, "risks_and_catalysts": {"risks": [], "catalysts": []}, "data_gaps": [], "chanlun_relation": ""},
                "news_analysis": {"rating": "中性", "summary": "无重大消息", "key_news": [{"title": "年报发布", "time": "2026-04-28", "source": "巨潮资讯", "category": "业绩类", "sentiment": "中性", "impact_strength": "中", "impact_reason": "", "price_in": "", "fundamental_impact": "", "chanlun_relation": ""}], "risk_news": [], "follow_up": [], "data_gaps": []},
                "integrated_decision": {"action": "HOLD", "reason": "", "add_condition": "", "reduce_condition": "", "stop_condition": "", "confidence": "中"},
                "data_quality": {"fundamental_complete": False, "news_complete": False, "missing_fields": []},
            },
            "news": {"summary": "1条中性"},
            "news_raw": [],
            "fundamentals": {"pe": 20.0, "pb": 3.5},
            "rule_action": {"action": "HOLD"},
        }]
    return {"results": results}


class TestQACheckJSON(unittest.TestCase):

    def test_valid_data_passes(self):
        data = _make_test_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errors = check_json(path)
            self.assertEqual(errors, [])

    def test_missing_fundamental_analysis(self):
        data = _make_test_data()
        data["results"][0]["llm_review"] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errors = check_json(path)
            self.assertTrue(any("fundamental_analysis" in e for e in errors))

    def test_missing_news_analysis(self):
        data = _make_test_data()
        data["results"][0]["llm_review"] = {"fundamental_analysis": {}}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errors = check_json(path)
            self.assertTrue(any("news_analysis" in e for e in errors))

    def test_banned_fake_news_in_raw(self):
        data = _make_test_data()
        data["results"][0]["news_raw"] = [{"title": "暂无相关新闻"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errors = check_json(path)
            self.assertTrue(any("banned title" in e for e in errors))

    def test_banned_news_summary_placeholder(self):
        data = _make_test_data()
        data["results"][0]["news"] = {"summary": "暂无茅台相关新闻"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errors = check_json(path)
            self.assertTrue(any("placeholder" in e for e in errors))

    def test_missing_news_title_in_key_news(self):
        data = _make_test_data()
        data["results"][0]["llm_review"]["news_analysis"]["key_news"] = [
            {"title": "", "sentiment": "中性"}
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errors = check_json(path)
            self.assertTrue(any("missing title" in e for e in errors))

    def test_missing_json_file(self):
        errors = check_json("/nonexistent/path.json")
        self.assertTrue(any("not found" in e for e in errors))


class TestQACheckHTML(unittest.TestCase):

    def test_banned_pe_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<html>PE: None</html>")
            errors = check_html(path)
            self.assertTrue(any("PE: None" in e for e in errors))

    def test_banned_pb_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<html>PB: None</html>")
            errors = check_html(path)
            self.assertTrue(any("PB: None" in e for e in errors))

    def test_banned_fake_news(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<html>暂无茅台相关新闻</html>")
            errors = check_html(path)
            self.assertTrue(any("fake placeholder" in e for e in errors))

    def test_banned_ai_review_rule_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<html>AI复核：rule_only</html>")
            errors = check_html(path)
            self.assertTrue(any("AI复核：rule_only" in e for e in errors))

    def test_clean_html_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<html><body>正常内容 规则诊断（未启用LLM）</body></html>")
            errors = check_html(path)
            self.assertEqual(errors, [])

    def test_missing_html_file(self):
        errors = check_html("/nonexistent/path.html")
        self.assertTrue(any("not found" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
