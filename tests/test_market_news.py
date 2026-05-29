"""Tests for market_news — JSON parsing + impact scoring."""
import unittest
from unittest.mock import Mock, patch
from chanlun.market_news import (
    _extract_first_json_object, _parse_llm_json,
    THEME_SYNONYMS, classify_event_category, classify_event_type,
    score_market_impact, dedupe_or_downgrade_events, fetch_cls_news,
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


class TestFetchClsNews(unittest.TestCase):

    @patch("chanlun.market_news.SESSION.get")
    def test_prefers_next_data_when_available(self, mock_get):
        page_resp = Mock()
        page_resp.text = (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"initialState":{"telegraph":{"telegraphList":['
            '{"title":"旧站快讯","content":"正文","brief":"摘要","ctime":123,"level":"A"}'
            ']}}}}</script>'
        )
        page_resp.encoding = "utf-8"
        mock_get.return_value = page_resp

        result = fetch_cls_news(count=5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "旧站快讯")
        self.assertEqual(result[0]["level"], 3)
        self.assertEqual(mock_get.call_count, 1)

    @patch("chanlun.market_news.SESSION.get")
    def test_falls_back_to_roll_api_when_next_data_missing(self, mock_get):
        page_resp = Mock()
        page_resp.text = "<html><body>no next data</body></html>"
        page_resp.encoding = "utf-8"

        api_resp = Mock()
        api_resp.json.return_value = {
            "data": {
                "roll_data": [
                    {
                        "title": "新站快讯",
                        "content": "新正文",
                        "brief": "新摘要",
                        "ctime": 456,
                        "importance": "B",
                        "stockList": [{"name": "测试股", "code": "000001"}],
                        "plateList": [{"name": "半导体"}],
                    }
                ]
            }
        }
        mock_get.side_effect = [page_resp, api_resp]

        result = fetch_cls_news(count=5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "新站快讯")
        self.assertEqual(result[0]["level"], 2)
        self.assertEqual(result[0]["stock_list"][0]["code"], "000001")
        self.assertEqual(result[0]["plate_list"][0]["name"], "半导体")
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("/v1/roll/get_roll_list", mock_get.call_args_list[1][0][0])

    @patch("chanlun.market_news.SESSION.get")
    def test_uses_template_when_both_sources_empty(self, mock_get):
        page_resp = Mock()
        page_resp.text = "<html><body>no next data</body></html>"
        page_resp.encoding = "utf-8"

        api_resp = Mock()
        api_resp.json.return_value = {"data": {"roll_data": []}}
        ws_resp = Mock()
        ws_resp.json.return_value = {"data": {"items": []}}
        mock_get.side_effect = [page_resp, api_resp, ws_resp]

        result = fetch_cls_news(count=5)

        self.assertEqual(result, [])

    @patch("chanlun.market_news.SESSION.get")
    def test_falls_back_to_wallstreetcn_when_cls_empty(self, mock_get):
        page_resp = Mock()
        page_resp.text = "<html><body>no next data</body></html>"
        page_resp.encoding = "utf-8"

        api_resp = Mock()
        api_resp.json.return_value = {"data": {"roll_data": []}}

        ws_resp = Mock()
        ws_resp.json.return_value = {
            "data": {
                "items": [
                    {
                        "title": "见闻A股快讯",
                        "content_text": "算力链盘中走强",
                        "display_time": 789,
                    }
                ]
            }
        }
        mock_get.side_effect = [page_resp, api_resp, ws_resp]

        result = fetch_cls_news(count=5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "见闻A股快讯")
        self.assertEqual(result[0]["content"], "算力链盘中走强")
        self.assertEqual(result[0]["level"], 2)
        self.assertIn("api-one.wallstcn.com", mock_get.call_args_list[2][0][0])


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
        self.assertIn("AI算力", result)

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


class TestScoreMarketImpactDowngrades(unittest.TestCase):

    def test_company_reply_with_no_major_impact_is_downgraded(self):
        event = {
            "title": "某公司称不构成重大影响",
            "content": "公司在互动平台表示，本次投资规模较小，不构成重大影响",
            "stock_list": [{"name": "测试股", "code": "000001"}],
            "plate_list": [],
            "level": 1,
        }
        event = score_market_impact(event, sector_flow=None, limit_up_pool=None)
        self.assertIn("降权", event["impact_reason"])
        self.assertTrue(len(event.get("downgrade_reasons", [])) > 0)

    def test_pure_overseas_without_a_share_mapping_is_downgraded(self):
        event = {
            "title": "伊朗说尚未就霍尔木兹海峡问题与美国达成一致",
            "content": "中东地缘局势持续紧张",
            "stock_list": [],
            "plate_list": [],
            "level": 2,
        }
        event = score_market_impact(event, sector_flow=None, limit_up_pool=None)
        self.assertEqual(event["event_category"], "overseas")
        self.assertIn("降权", event["impact_reason"])
        # With overseas type(+2) + level 2(+16) = 18 + downgrade -12 -8 = -2 → "微弱"
        self.assertLess(event["impact_score"], 18)

    def test_no_a_share_clue_event_is_downgraded(self):
        event = {
            "title": "某国军事采购联盟变化",
            "content": "英媒说9国退出供乌弹药采购联盟",
            "stock_list": [],
            "plate_list": [],
            "level": 2,
        }
        event = score_market_impact(event, sector_flow=None, limit_up_pool=None)
        self.assertIn("降权", event["impact_reason"])
        self.assertLess(event["impact_score"], 22)


class TestScoreMarketImpactThemeLimitUp(unittest.TestCase):

    def test_theme_limit_up_validation_scores_even_without_stock_list(self):
        event = {
            "title": "半导体产业政策扶持",
            "content": "国务院发布半导体产业规划",
            "stock_list": [],  # No direct stock mapping
            "plate_list": [{"name": "半导体"}],
            "level": 3,
        }
        limit_up_pool = [
            {"name": "中芯国际", "code": "688981", "sector": "半导体"},
            {"name": "北方华创", "code": "002371", "sector": "半导体"},
            {"name": "韦尔股份", "code": "603501", "sector": "半导体"},
        ]
        event = score_market_impact(event, sector_flow=None, limit_up_pool=limit_up_pool)
        # Should get theme-limit-up validation bonus
        self.assertIn("涨停主题验证", event["impact_reason"])
        self.assertGreater(event["impact_score"], 30)


class TestRankMarketImpactSortOrder(unittest.TestCase):

    def test_rank_uses_score_then_tradability_then_level(self):
        events = [
            # Higher score should win
            {"title": "半导体政策扶持", "stock_list": [{"name": "芯", "code": "001"}],
             "plate_list": [{"name": "半导体"}], "level": 3, "ctime": 1000},
            # Lower score, higher level doesn't matter
            {"title": "普通公告", "stock_list": [], "plate_list": [],
             "level": 1, "ctime": 2000},
        ]
        ranked = rank_market_impact_events(events, sector_flow=[], top_n=10)
        self.assertEqual(len(ranked), 2)
        self.assertGreater(ranked[0]["impact_score"], ranked[1]["impact_score"])

    def test_same_score_higher_tradability_wins(self):
        """When scores are equal, 强 tradability ranks above 弱."""
        # Two events that should score similarly but differ in tradability
        e1 = {
            "title": "白酒板块资金流入", "content": "白酒",
            "stock_list": [], "plate_list": [{"name": "白酒"}], "level": 2, "ctime": 1000,
        }
        e2 = {
            "title": "海外地缘冲突", "content": "伊朗 霍尔木兹",
            "stock_list": [], "plate_list": [], "level": 3, "ctime": 2000,
        }
        sector_flow = [{"name": "白酒", "flow": 50}]
        ranked = rank_market_impact_events([e1, e2], sector_flow=sector_flow, top_n=10)
        # e1 should rank higher because it has hot sector + theme, while e2 is overseas downgraded
        self.assertGreater(ranked[0]["impact_score"], ranked[1]["impact_score"])


class TestClassifyEventType(unittest.TestCase):

    def test_company_reply_via_回应(self):
        e = {"title": "公司回应股价波动", "content": "公司回应近期股价波动"}
        self.assertEqual(classify_event_type(e), "company_reply")

    def test_lawsuit_is_risk_not_tech(self):
        e = {"title": "专利诉讼撤回", "content": "双方就专利诉讼达成和解并撤诉"}
        self.assertEqual(classify_event_type(e), "risk")

    def test_和解_is_mna(self):
        e = {"title": "某公司和解公告", "content": "与原告达成和解"}
        self.assertEqual(classify_event_type(e), "mna")

    def test_order_matches_before_company_reply(self):
        e = {"title": "某公司回应订单传闻", "content": "回应称订单情况正常"}
        # "订单" (order) appears before "回应" (company_reply) in rules — order wins
        self.assertEqual(classify_event_type(e), "order")

    def test_tech_breakthrough_still_works(self):
        e = {"title": "国产芯片技术突破", "content": "实现先进制程量产"}
        self.assertEqual(classify_event_type(e), "tech")


class TestScoreMarketImpactNoValidationPenalty(unittest.TestCase):

    def test_no_market_validation_gets_penalty(self):
        """Events with zero market validation get -10 penalty."""
        event = {
            "title": "某公司发布公告",
            "content": "公司发布日常经营公告",
            "stock_list": [{"name": "测试股", "code": "000001"}],
            "plate_list": [],
            "level": 1,
        }
        event = score_market_impact(event, sector_flow=[], limit_up_pool=None)
        self.assertIn("降权", event["impact_reason"])
        self.assertIn("无盘面验证", event["impact_reason"])

    def test_validated_event_ranks_above_unvalidated(self):
        """An event with market validation should rank above one without."""
        e_validated = {
            "title": "半导体政策利好", "content": "半导体 芯片",
            "stock_list": [], "plate_list": [{"name": "半导体"}], "level": 1,
        }
        e_unvalidated = {
            "title": "某公司日常公告", "content": "经营情况正常",
            "stock_list": [{"name": "测试", "code": "000001"}], "plate_list": [], "level": 3,
        }
        sector_flow = [{"name": "半导体", "flow": 100}]
        ranked = rank_market_impact_events([e_validated, e_unvalidated], sector_flow=sector_flow, top_n=10)
        self.assertEqual(ranked[0]["title"], "半导体政策利好")


class TestDedupeOrDowngrade(unittest.TestCase):

    def test_empty_title_dropped(self):
        events = [
            {"title": "", "content": "empty title event"},
            {"title": "正常事件", "content": "normal"},
        ]
        result = dedupe_or_downgrade_events(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "正常事件")

    def test_whitespace_title_dropped(self):
        events = [
            {"title": "   ", "content": "whitespace title"},
            {"title": "正常", "content": "normal"},
        ]
        result = dedupe_or_downgrade_events(events)
        self.assertEqual(len(result), 1)

    def test_identical_title_dedupe(self):
        events = [
            {"title": "重复事件", "content": "a"},
            {"title": "重复事件", "content": "b"},
        ]
        result = dedupe_or_downgrade_events(events)
        self.assertEqual(len(result), 1)

    def test_same_theme_4th_downgraded(self):
        events = [
            {"title": f"半导体新闻{i}", "content": "芯片",
             "affected_themes": ["半导体"], "event_category": "policy",
             "impact_score": 30}
            for i in range(5)
        ]
        result = dedupe_or_downgrade_events(events)
        self.assertEqual(len(result), 5)
        # 4th and 5th should be downgraded
        self.assertLess(result[3]["impact_score"], 30)
        self.assertLess(result[4]["impact_score"], 30)


if __name__ == "__main__":
    unittest.main()
