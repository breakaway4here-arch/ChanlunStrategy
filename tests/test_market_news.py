"""Tests for market_news — JSON parsing + impact scoring."""
import unittest
from chanlun.market_news import (
    _extract_first_json_object, _parse_llm_json,
    THEME_SYNONYMS, classify_event_category, score_market_impact,
    rank_market_impact_events, rank_events,
)


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


class TestThemeSynonyms(unittest.TestCase):

    def test_has_enough_themes(self):
        self.assertGreaterEqual(len(THEME_SYNONYMS), 10)

    def test_all_themes_have_keywords(self):
        for theme, keywords in THEME_SYNONYMS.items():
            self.assertIsInstance(keywords, list)
            self.assertGreater(len(keywords), 0, f"Theme '{theme}' has empty keywords")


class TestClassifyEventCategory(unittest.TestCase):

    def test_semiconductor_match(self):
        events = [{"title": "先进封装需求大增", "content": "AI芯片带动先进封装"}]
        result = classify_event_category(events[0])
        self.assertIn("半导体", result)

    def test_no_match(self):
        events = [{"title": "无关内容测试", "content": "nothing relevant here"}]
        result = classify_event_category(events[0])
        self.assertEqual(result, [])

    def test_ai_match(self):
        events = [{"title": "大模型算力需求爆发"}]
        result = classify_event_category(events[0])
        self.assertIn("人工智能", result)

    def test_robot_match(self):
        events = [{"title": "人形机器人量产加速", "content": "减速器需求大增"}]
        result = classify_event_category(events[0])
        self.assertIn("机器人", result)


class TestScoreMarketImpact(unittest.TestCase):

    def test_basic_scoring(self):
        event = {
            "title": "半导体政策利好",
            "content": "国家出台半导体扶持政策",
            "stock_list": [{"name": "北方华创", "code": "002371"}],
            "plate_list": [{"name": "半导体"}],
            "level": 3,
        }
        event = score_market_impact(event, sector_flow=None, limit_up_pool=None)
        self.assertGreater(event["impact_score"], 10)
        self.assertIn("impact_level", event)
        self.assertIn("impact_reason", event)

    def test_level_a_scores_higher_than_c(self):
        event_a = {"title": "重大政策", "stock_list": [], "plate_list": [], "level": 3}
        event_c = {"title": "普通公告", "stock_list": [], "plate_list": [], "level": 1}
        event_a = score_market_impact(event_a, sector_flow=None, limit_up_pool=None)
        event_c = score_market_impact(event_c, sector_flow=None, limit_up_pool=None)
        self.assertGreater(event_a["impact_score"], event_c["impact_score"])

    def test_hot_sector_match(self):
        event = {"title": "半导体芯片行业", "content": "利好", "stock_list": [], "plate_list": [], "level": 2}
        sector_flow = [{"name": "半导体", "flow": 100}]
        event = score_market_impact(event, sector_flow=sector_flow)
        self.assertIn("半导体", event["matched_hot_sectors"])

    def test_limit_up_validation(self):
        event = {
            "title": "半导体涨停验证",
            "content": "芯片板块多股涨停",
            "stock_list": [{"name": "测试股", "code": "000001"}],
            "plate_list": [],
            "level": 2,
        }
        limit_up_pool = [{"name": "测试股", "code": "000001"}]
        event = score_market_impact(event, sector_flow=None, limit_up_pool=limit_up_pool)
        self.assertIn("涨停", event.get("market_validation", ""))

    def test_tradability_set(self):
        event = {"title": "测试", "stock_list": [], "plate_list": [], "level": 1}
        event = score_market_impact(event, sector_flow=None, limit_up_pool=None)
        self.assertIn(event["tradability"], ("强", "中", "弱"))


class TestRankMarketImpactEvents(unittest.TestCase):

    def test_returns_top_n(self):
        events = [
            {"title": f"事件{i}", "stock_list": [], "plate_list": [], "level": i % 3 + 1}
            for i in range(20)
        ]
        ranked = rank_market_impact_events(events, sector_flow=[], top_n=10)
        self.assertEqual(len(ranked), 10)

    def test_sorted_by_score_desc(self):
        events = [
            {"title": "low", "stock_list": [], "plate_list": [], "level": 1},
            {"title": "high", "stock_list": [{"name": "a"}], "plate_list": [{"name": "b"}], "level": 3},
        ]
        ranked = rank_market_impact_events(events, sector_flow=[])
        self.assertGreaterEqual(ranked[0]["impact_score"], ranked[-1]["impact_score"])

    def test_empty_returns_empty(self):
        self.assertEqual(rank_market_impact_events([], sector_flow=[]), [])


class TestRankEventsBackwardCompat(unittest.TestCase):

    def test_rank_events_works(self):
        events = [
            {"title": "测试", "stock_list": [], "plate_list": [], "level": 2}
        ]
        result = rank_events(events, hot_sectors=None)
        self.assertIsInstance(result, list)
        if result:
            self.assertIn("impact_score", result[0])


if __name__ == "__main__":
    unittest.main()
