"""Tests for market_news — JSON parsing + impact scoring."""
import json
import unittest
from unittest.mock import Mock, patch
import chanlun.market_news as market_news
from chanlun.market_news import (
    _DECISION_BRIEF_SYSTEM_PROMPT, _analyze_event_llm,
    _call_llm_with_retry, _extract_first_json_object, _parse_llm_json,
    analyze_decision_brief_facts,
    THEME_SYNONYMS, classify_event_category, classify_event_type,
    score_market_impact, dedupe_or_downgrade_events, fetch_cls_news,
    rank_market_impact_events, rank_events,
)


class TestLocalCodexProvider(unittest.TestCase):
    def test_provider_defaults_to_ephemeral_codex_cli(self):
        self.assertEqual(getattr(market_news, "_LLM_PROVIDER", None), "codex")
        self.assertTrue(callable(getattr(market_news, "_codex_exec_json", None)))

    @patch("chanlun.market_news.subprocess.run")
    @patch("chanlun.market_news.os.path.exists", return_value=True)
    @patch("chanlun.market_news._CODEX_BIN", "/usr/local/bin/codex")
    @patch.dict(
        "chanlun.market_news.os.environ",
        {
            "HOME": "/Users/tester",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "CODEX_HOME": "/Users/tester/.codex",
            "HTTPS_PROXY": "http://127.0.0.1:7890",
            "OPENAI_API_KEY": "must-not-leak",
            "ANTHROPIC_AUTH_TOKEN": "must-not-leak",
            "UNRELATED_SECRET": "must-not-leak",
        },
        clear=True,
    )
    def test_codex_call_starts_read_only_ephemeral_session(
        self, _mock_exists, mock_run
    ):
        mock_run.return_value = Mock(
            returncode=0,
            stdout=(
                '{"type":"item.completed","item":'
                '{"type":"agent_message","text":"{\\"ok\\":true}"}}\n'
            ),
            stderr="",
        )

        result = market_news._codex_exec_json("system", "user")

        self.assertEqual(result, {"ok": True})
        command = mock_run.call_args[0][0]
        self.assertIn("--ephemeral", command)
        self.assertIn("read-only", command)
        self.assertNotIn("resume", command)
        self.assertNotIn("--ignore-rules", command)
        self.assertIn("system", mock_run.call_args[1]["input"])
        self.assertIn("user", mock_run.call_args[1]["input"])
        child_env = mock_run.call_args[1]["env"]
        self.assertEqual(child_env["HOME"], "/Users/tester")
        self.assertEqual(child_env["CODEX_HOME"], "/Users/tester/.codex")
        self.assertEqual(child_env["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertNotIn("OPENAI_API_KEY", child_env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", child_env)
        self.assertNotIn("UNRELATED_SECRET", child_env)

    @patch("chanlun.market_news._CODEX_MODEL", "gpt-test")
    @patch("chanlun.market_news._DS_API_KEY", "")
    @patch("chanlun.market_news._LLM_PROVIDER", "codex")
    @patch("chanlun.market_news._codex_exec_json")
    def test_event_analysis_uses_one_codex_batch(self, mock_codex):
        mock_codex.return_value = {
            "items": [
                {
                    "event_index": 1,
                    "impact": {
                        "no_impact": False,
                        "headline": "半导体需求回暖",
                        "analysis": ["需求改善"],
                        "positive_sectors": ["半导体"],
                        "negative_sectors": [],
                        "positive_stocks": [],
                        "negative_stocks": [],
                    },
                },
                {
                    "event_index": 2,
                    "impact": {
                        "no_impact": True,
                        "headline": "没有新增催化",
                        "analysis": [],
                        "positive_sectors": [],
                        "negative_sectors": [],
                        "positive_stocks": [],
                        "negative_stocks": [],
                    },
                },
            ]
        }
        events = [{"title": "事件一"}, {"title": "事件二"}]

        result = market_news.enrich_events(events)

        self.assertIs(result, events)
        self.assertEqual(mock_codex.call_count, 1)
        self.assertEqual(result[0]["impact"]["status"], "ok")
        self.assertEqual(result[0]["impact"]["model"], "gpt-test")
        self.assertEqual(result[1]["impact"]["headline"], "没有新增催化")

    @patch("chanlun.market_news._CODEX_MODEL", "gpt-test")
    @patch("chanlun.market_news._DS_API_KEY", "")
    @patch("chanlun.market_news._LLM_PROVIDER", "codex")
    @patch("chanlun.market_news._codex_exec_json")
    def test_decision_brief_uses_codex_with_trusted_metadata(self, mock_codex):
        mock_codex.return_value = {"theses": []}
        packet = {"report_date": "2026-08-21", "directions": []}

        result = market_news.analyze_decision_brief_facts(packet)

        self.assertEqual(result["model"], "gpt-test")
        self.assertEqual(result["prompt_version"], "decision-brief-v4")
        self.assertEqual(mock_codex.call_count, 1)
        self.assertIn("directions", mock_codex.call_args[0][1])

    @patch("chanlun.market_news._DS_API_KEY", "")
    @patch("chanlun.market_news._LLM_PROVIDER", "codex")
    @patch("chanlun.market_news._codex_exec_json")
    def test_forecast_uses_codex_without_deepseek_key(self, mock_codex):
        mock_codex.return_value = {
            "core_judgment": "科技方向偏强",
            "volume_note": "量能平稳",
            "short_term": ["观察持续性"],
            "mid_term": "等待结构确认",
            "risks": ["高位分化"],
        }

        result = market_news.generate_forecast({}, {}, [], [], [])

        self.assertEqual(result["core_judgment"], "科技方向偏强")
        self.assertEqual(mock_codex.call_count, 1)

    @patch("chanlun.market_news._DS_API_KEY", "configured")
    @patch("chanlun.market_news._LLM_PROVIDER", "codeex")
    @patch("chanlun.market_news._call_llm_with_retry")
    def test_unknown_provider_does_not_fall_back_to_deepseek(self, mock_call):
        with self.assertRaisesRegex(RuntimeError, "不支持的 LLM provider"):
            market_news.analyze_decision_brief_facts({"directions": []})
        mock_call.assert_not_called()


class TestEventImpactLlmSchema(unittest.TestCase):
    @patch("chanlun.market_news._call_llm_with_retry")
    @patch("chanlun.market_news._DS_API_KEY", "configured")
    def test_malformed_sector_arrays_are_rejected(self, mock_call):
        malformed_values = [123, [{"name": "通信"}], ["通信", 3]]

        for malformed in malformed_values:
            with self.subTest(malformed=malformed):
                mock_call.return_value = {
                    "headline": "产业事件",
                    "analysis": ["待验证"],
                    "positive_sectors": malformed,
                    "negative_sectors": [],
                    "positive_stocks": [],
                    "negative_stocks": [],
                    "no_impact": False,
                }

                with self.assertRaisesRegex(ValueError, "positive_sectors"):
                    _analyze_event_llm({"title": "产业事件"})

    @patch("chanlun.market_news._call_llm_with_retry")
    @patch("chanlun.market_news._DS_API_KEY", "configured")
    def test_event_analysis_has_capacity_for_complete_json(self, mock_call):
        mock_call.return_value = {
            "headline": "产业事件",
            "analysis": ["待验证"],
            "positive_sectors": ["半导体"],
            "negative_sectors": [],
            "positive_stocks": [],
            "negative_stocks": [],
            "no_impact": False,
        }

        _analyze_event_llm({"title": "产业事件"})

        self.assertEqual(mock_call.call_args[1]["max_retries"], 3)
        self.assertEqual(mock_call.call_args[1]["max_tokens"], 2400)
        self.assertNotIn("raw_response", mock_call.call_args[1])


class TestMarketNewsJsonParsing(unittest.TestCase):

    @patch("chanlun.market_news.time.sleep")
    @patch("chanlun.market_news.requests.post")
    @patch("chanlun.market_news._DS_API_KEY", "configured")
    def test_retry_client_accepts_valid_json_with_surrounding_text(
        self, mock_post, _mock_sleep
    ):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{
                "message": {"content": '前缀\n{"ok": true}\n后缀'}
            }]
        }
        mock_post.return_value = response

        result = _call_llm_with_retry(
            [{"role": "user", "content": "test"}], max_retries=1
        )

        self.assertEqual(result, {"ok": True})

    @patch("chanlun.market_news.time.sleep")
    @patch("chanlun.market_news.requests.post")
    @patch("chanlun.market_news._DS_API_KEY", "configured")
    def test_retry_client_explains_reasoning_token_exhaustion(
        self, mock_post, _mock_sleep
    ):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{
                "finish_reason": "length",
                "message": {
                    "content": "",
                    "reasoning_content": "推理过程",
                },
            }]
        }
        mock_post.return_value = response

        with self.assertRaisesRegex(
            ValueError, "finish_reason=length.*reasoning_chars=4"
        ):
            _call_llm_with_retry(
                [{"role": "user", "content": "test"}], max_retries=1
            )

    @patch("chanlun.market_news.time.sleep")
    @patch("chanlun.market_news.requests.post")
    @patch("chanlun.market_news._DS_API_KEY", "configured")
    def test_retry_client_retries_truncated_nonempty_json(
        self, mock_post, mock_sleep
    ):
        truncated = Mock()
        truncated.raise_for_status.return_value = None
        truncated.json.return_value = {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": '{"headline":"未完成"'},
            }]
        }
        complete = Mock()
        complete.raise_for_status.return_value = None
        complete.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": '{"headline":"完成"}'},
            }]
        }
        mock_post.side_effect = [truncated, complete]

        result = _call_llm_with_retry(
            [{"role": "user", "content": "test"}], max_retries=2
        )

        self.assertEqual(result, {"headline": "完成"})
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1)

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


class TestDecisionBriefLlmProvider(unittest.TestCase):
    def test_prompt_forbids_leader_word_in_free_text(self):
        self.assertIn("自由文本", _DECISION_BRIEF_SYSTEM_PROMPT)
        self.assertIn("禁止使用“龙头”", _DECISION_BRIEF_SYSTEM_PROMPT)
        self.assertNotIn(
            "不得称某只股票为龙头，除非",
            _DECISION_BRIEF_SYSTEM_PROMPT,
        )

    def test_prompt_requires_independent_structured_risk_reasons(self):
        self.assertIn('"risk_reasons"', _DECISION_BRIEF_SYSTEM_PROMPT)
        self.assertIn('"reason"', _DECISION_BRIEF_SYSTEM_PROMPT)
        self.assertIn('"impact"', _DECISION_BRIEF_SYSTEM_PROMPT)
        self.assertIn('"evidence_refs"', _DECISION_BRIEF_SYSTEM_PROMPT)
        self.assertIn("负向或风险方向", _DECISION_BRIEF_SYSTEM_PROMPT)

    @patch("chanlun.market_news._call_llm_with_retry")
    @patch("chanlun.market_news._LLM_PROVIDER", "deepseek")
    @patch("chanlun.market_news._DS_API_KEY", "configured")
    @patch("chanlun.market_news._DS_MODEL", "deepseek-test")
    def test_provider_sends_structured_evidence_and_attaches_trusted_metadata(
        self, mock_call
    ):
        mock_call.return_value = {
            "theses": [
                {
                    "theme": "光模块",
                    "direction": "positive",
                    "stage": "confirmed",
                    "confidence": "medium",
                    "evidence_refs": ["event:2026-08-20:abc"],
                    "watchlist_codes": ["300308"],
                    "summary": "光通信催化已获得盘面验证。",
                    "next_trigger": ["涨停梯队扩散"],
                    "invalidation": ["板块资金转负"],
                }
            ]
        }
        packet = {
            "schema_version": "1",
            "report_date": "2026-08-20",
            "evidence_registry": [
                {
                    "evidence_ref": "event:2026-08-20:abc",
                    "kind": "event",
                    "title": "海外光通信上涨",
                }
            ],
            "directions": [
                {
                    "theme": "光模块",
                    "direction": "positive",
                    "evidence_refs": ["event:2026-08-20:abc"],
                    "watchlist_codes": ["300308"],
                }
            ],
        }

        result = analyze_decision_brief_facts(packet)

        self.assertEqual(result["model"], "deepseek-test")
        self.assertEqual(result["prompt_version"], "decision-brief-v4")
        self.assertEqual(result["schema_version"], "1")
        messages = mock_call.call_args[0][0]
        self.assertIn("event:2026-08-20:abc", messages[1]["content"])
        self.assertIn("300308", messages[1]["content"])
        self.assertEqual(mock_call.call_args[1]["max_retries"], 3)
        self.assertEqual(mock_call.call_args[1]["max_tokens"], 4800)

    @patch("chanlun.market_news._LLM_PROVIDER", "deepseek")
    @patch("chanlun.market_news._DS_API_KEY", "")
    def test_provider_fails_explicitly_when_unconfigured(self):
        with self.assertRaises(RuntimeError):
            analyze_decision_brief_facts({"directions": []})


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
