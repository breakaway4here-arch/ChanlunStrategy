"""Tests for market_news JSON parsing fallback — nested objects, markdown fences, noise."""
import unittest
from chanlun.market_news import _extract_first_json_object, _parse_llm_json


class TestMarketNewsJsonParsing(unittest.TestCase):

    def test_extract_clean_json(self):
        raw = '{"no_impact": false, "headline": "test"}'
        result = _parse_llm_json(raw)
        self.assertEqual(result["headline"], "test")

    def test_extract_nested_positive_stocks(self):
        raw = """{
  "no_impact": false,
  "headline": "利好半导体板块",
  "analysis": ["半导体需求回暖", "龙头业绩超预期"],
  "positive_sectors": ["半导体"],
  "negative_sectors": [],
  "positive_stocks": [{"name": "北方华创", "code": "002371", "reason": "设备龙头受益"}],
  "negative_stocks": []
}"""
        result = _parse_llm_json(raw)
        self.assertEqual(result["headline"], "利好半导体板块")
        self.assertEqual(len(result["positive_stocks"]), 1)
        self.assertEqual(result["positive_stocks"][0]["name"], "北方华创")

    def test_extract_with_prefix_noise(self):
        raw = """这是一些前缀文本
{"no_impact": false, "headline": "测试", "analysis": ["分析1"], "positive_sectors": [], "negative_sectors": [], "positive_stocks": [], "negative_stocks": []}
后面还有文本"""
        result = _parse_llm_json(raw)
        self.assertEqual(result["headline"], "测试")

    def test_extract_markdown_fenced(self):
        raw = """```json
{
  "no_impact": false,
  "headline": "markdown包裹",
  "analysis": ["a", "b"],
  "positive_sectors": [],
  "negative_sectors": [],
  "positive_stocks": [],
  "negative_stocks": []
}
```"""
        result = _parse_llm_json(raw)
        self.assertEqual(result["headline"], "markdown包裹")

    def test_extract_markdown_fenced_no_lang(self):
        raw = """```
{"no_impact": true, "headline": "无明显影响", "analysis": [], "positive_sectors": [], "negative_sectors": [], "positive_stocks": [], "negative_stocks": []}
```"""
        result = _parse_llm_json(raw)
        self.assertTrue(result["no_impact"])

    def test_extract_deeply_nested_stocks(self):
        raw = """{
  "no_impact": false,
  "headline": "重大利好",
  "analysis": ["政策推动"],
  "positive_sectors": ["光伏", "储能"],
  "negative_sectors": ["火电"],
  "positive_stocks": [
    {"name": "隆基绿能", "code": "601012", "reason": "硅片龙头"},
    {"name": "阳光电源", "code": "300274", "reason": "逆变器龙头"}
  ],
  "negative_stocks": [
    {"name": "华能国际", "code": "600011", "reason": "火电承压"}
  ]
}"""
        result = _parse_llm_json(raw)
        self.assertEqual(len(result["positive_stocks"]), 2)
        self.assertEqual(len(result["negative_stocks"]), 1)
        self.assertEqual(result["negative_stocks"][0]["code"], "600011")

    def test_extract_escaped_quotes_in_strings(self):
        raw = """{
  "no_impact": false,
  "headline": "他说\\"利好\\"",
  "analysis": ["包含\\"引号\\"的分析"],
  "positive_sectors": [],
  "negative_sectors": [],
  "positive_stocks": [],
  "negative_stocks": []
}"""
        result = _parse_llm_json(raw)
        self.assertEqual(result["headline"], '他说"利好"')

    def test_extract_raises_on_garbage(self):
        with self.assertRaises(ValueError):
            _parse_llm_json("这不是JSON，完全没有大括号")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            _parse_llm_json("")


if __name__ == "__main__":
    unittest.main()
