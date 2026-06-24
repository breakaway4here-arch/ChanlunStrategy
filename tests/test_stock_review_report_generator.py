"""Unit tests for stock_review report generator."""
import json
import os
import unittest
import tempfile
from chanlun.stock_review.report_generator import (
    build_report_data,
    sort_by_risk,
    generate_html_report,
    write_report,
)


def _make_review_result(code, name, action="HOLD", has_cost=True, llm_enabled=True):
    """Build a minimal StockReviewResult-like dict for testing."""
    holding = {
        "code": code, "name": name, "account": "test", "source": "manual",
        "quantity": 100, "cost_price": 50.0 if has_cost else None,
        "market_price": 52.0, "market_value": 5200.0,
        "pnl": 200.0, "pnl_pct": 4.0,
    }
    llm_review = {
        "llm_enabled": llm_enabled,
        "executive_summary": "基本面稳健，消息面中性，缠论结构中枢盘整。建议持有等待方向选择。",
        "chanlun_structure_comment": "30min中枢盘整，等待方向选择",
        "fundamental_analysis": {
            "rating": "中",
            "summary": "基本面总体稳健，但成长性放缓",
            "business": {"title": "公司是干什么的", "conclusion": "高端白酒龙头，主营业务清晰", "details": ["白酒生产销售", "品牌壁垒强"], "data_gaps": []},
            "growth": {"title": "成长性", "conclusion": "增速放缓至个位数", "details": ["营收增速放缓"], "data_gaps": ["扣非净利润同比"]},
            "profit_quality": {"title": "盈利质量", "conclusion": "高毛利高净利，现金流充裕", "details": [], "data_gaps": ["经营现金流"]},
            "financial_safety": {"title": "财务安全性", "conclusion": "低负债高现金，财务安全", "details": [], "data_gaps": ["有息负债"]},
            "valuation": {"title": "估值是否合理", "conclusion": "PE处于历史中位，估值合理", "details": [], "data_gaps": []},
            "risks_and_catalysts": {"risks": ["消费疲软"], "catalysts": ["提价预期"]},
            "data_gaps": ["扣非净利润同比", "经营现金流", "有息负债"],
            "chanlun_relation": "基本面稳健支持中枢内持有",
        },
        "news_analysis": {
            "rating": "中性",
            "summary": "近期无重大消息",
            "key_news": [
                {"title": "公司发布年报", "time": "2026-04-28", "source": "巨潮资讯", "category": "业绩类", "sentiment": "中性", "impact_strength": "中", "impact_reason": "年报披露", "price_in": "充分反应", "fundamental_impact": "短期情绪", "chanlun_relation": "无"},
            ],
            "risk_news": [],
            "follow_up": ["关注Q1季报"],
            "data_gaps": [],
        },
        "mid_term_view": "基本面稳健但成长性放缓，中线先看持有观察。",
        "short_term_catalysts": [
            {
                "date": "2026-05-25",
                "type": "order",
                "title": "新增订单催化",
                "impact": "positive",
                "summary": "订单落地带来短线情绪支撑",
                "source": "财联社",
            }
        ],
        "short_term_risks": [
            {
                "date": "2026-05-24",
                "type": "supply_chain_risk",
                "title": "供应链争议",
                "impact": "negative",
                "summary": "短线风险偏好受压制",
                "source": "证券时报",
            }
        ],
        "event_window_days": 5,
        "integrated_decision": {
            "action": "HOLD",
            "reason": "中枢内无买卖点",
            "add_condition": "放量突破ZG55",
            "reduce_condition": "跌破ZD48",
            "stop_condition": "跌破成本8%",
            "confidence": "中",
        },
        "data_quality": {"fundamental_complete": False, "news_complete": False, "missing_fields": ["扣非净利润同比", "经营现金流"]},
    }
    if not llm_enabled:
        llm_review = {
            "llm_enabled": False,
            "executive_summary": "规则建议: 继续持有。中枢内无卖点",
            "fundamental_analysis": {"rating": "数据不足", "summary": "LLM未启用", "business": {}, "growth": {}, "profit_quality": {}, "financial_safety": {}, "valuation": {}, "risks_and_catalysts": {"risks": [], "catalysts": []}, "data_gaps": ["LLM未启用"], "chanlun_relation": ""},
            "news_analysis": {"rating": "数据不足", "summary": "LLM未启用", "key_news": [], "risk_news": [], "follow_up": [], "data_gaps": ["LLM未启用"]},
            "integrated_decision": {"action": action, "reason": "中枢内无卖点", "add_condition": "", "reduce_condition": "", "stop_condition": "", "confidence": "中"},
            "data_quality": {"fundamental_complete": False, "news_complete": False, "missing_fields": ["LLM未启用"]},
        }
    return {
        "holding": holding,
        "price_snapshot": {"close": 52.0},
        "chanlun_daily": {
            "close": 52.0, "trend_type": "盘整", "position": "中枢内",
            "current_pivot": {"ZD": 48.0, "ZG": 55.0},
            "buy_points": [], "sell_points": [],
        },
        "chanlun_30min": {
            "close": 52.0, "trend_type": "盘整", "position": "中枢内",
            "above_ema5": True, "buy_points": [], "sell_points": [],
        },
        "fundamentals": {"pe": 20.0, "pb": 3.5, "industry": "白酒", "roe": 25.0},
        "news": {"summary": "1条中性"},
        "news_raw": [],
        "rule_action": {
            "action": action,
            "confidence": "medium",
            "primary_reason": "中枢内无卖点",
            "hold_condition": "不破ZD",
            "add_condition": "30min确认",
            "reduce_condition": "放量跌破ZD",
            "stop_condition": "跌破ZD 48",
        },
        "llm_review": llm_review,
        "risks": [],
    }


class TestSortByRisk(unittest.TestCase):

    def test_stop_before_hold(self):
        results = [
            _make_review_result("001", "A", "HOLD"),
            _make_review_result("002", "B", "STOP"),
            _make_review_result("003", "C", "WATCH"),
        ]
        sorted_results = sort_by_risk(results)
        actions = [r["rule_action"]["action"] for r in sorted_results]
        self.assertEqual(actions[0], "STOP")

    def test_reduce_before_hold(self):
        results = [
            _make_review_result("001", "A", "HOLD"),
            _make_review_result("002", "B", "REDUCE"),
        ]
        sorted_results = sort_by_risk(results)
        self.assertEqual(sorted_results[0]["rule_action"]["action"], "REDUCE")


class TestBuildReportData(unittest.TestCase):

    def test_includes_overview(self):
        results = [
            _make_review_result("001", "A", "HOLD"),
            _make_review_result("002", "B", "STOP"),
        ]
        data = build_report_data(results, date_str="2026-05-26")
        self.assertIn("overview", data)
        self.assertEqual(data["overview"]["total"], 2)
        self.assertGreater(data["overview"]["high_risk"], 0)

    def test_overview_counts_correctly(self):
        results = [
            _make_review_result("001", "A", "HOLD"),
            _make_review_result("002", "B", "STOP", has_cost=True),
            _make_review_result("003", "C", "WATCH", has_cost=False),
        ]
        data = build_report_data(results, "2026-05-26")
        ov = data["overview"]
        self.assertEqual(ov["total"], 3)
        self.assertEqual(ov["with_cost"], 2)
        self.assertEqual(ov["structure_only"], 1)
        self.assertGreaterEqual(ov["high_risk"], 1)

    def test_no_cost_shows_structure_only(self):
        results = [_make_review_result("001", "A", "HOLD", has_cost=False)]
        data = build_report_data(results, "2026-05-26")
        self.assertEqual(data["overview"]["structure_only"], 1)


class TestGenerateHTMLReport(unittest.TestCase):

    def test_generates_valid_html(self):
        results = [_make_review_result("600519", "贵州茅台", "HOLD")]
        data = build_report_data(results, "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("贵州茅台", html)
        self.assertIn("持仓驾驶舱", html)

    def test_includes_risk_queue(self):
        results = [
            _make_review_result("001", "A", "HOLD"),
            _make_review_result("002", "B", "STOP"),
        ]
        data = build_report_data(results, "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("风险队列", html)

    def test_mobile_viewport_meta(self):
        results = [_make_review_result("001", "A", "HOLD")]
        data = build_report_data(results, "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("viewport", html)


class TestWriteReport(unittest.TestCase):

    def test_writes_daily_report(self):
        results = [_make_review_result("600519", "贵州茅台", "HOLD")]
        with tempfile.TemporaryDirectory() as tmpdir:
            write_report(results, tmpdir, "2026-05-26", is_ad_hoc=False)
            index_path = os.path.join(tmpdir, "index.html")
            data_path = os.path.join(tmpdir, "data", "2026-05-26.json")
            self.assertTrue(os.path.exists(index_path))
            self.assertTrue(os.path.exists(data_path))

    def test_writes_ad_hoc_report(self):
        results = [_make_review_result("600519", "贵州茅台", "HOLD")]
        with tempfile.TemporaryDirectory() as tmpdir:
            ad_hoc_dir = os.path.join(tmpdir, "ad-hoc")
            write_report(results, ad_hoc_dir, "2026-05-26", is_ad_hoc=True)
            self.assertTrue(os.path.exists(os.path.join(ad_hoc_dir, "index.html")))

    def test_risk_sorted_in_report(self):
        results = [
            _make_review_result("001", "A", "HOLD"),
            _make_review_result("002", "B", "STOP"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            write_report(results, tmpdir, "2026-05-26", is_ad_hoc=False)
            with open(os.path.join(tmpdir, "data", "2026-05-26.json")) as f:
                saved = json.load(f)
            actions = [r["rule_action"]["action"] for r in saved["results"]]
            self.assertEqual(actions[0], "STOP")


class TestConclusionFirstLayout(unittest.TestCase):
    """Spec: report shows conclusion-first with rating tags."""

    def test_shows_fundamental_rating(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("基本面：中", html)
        self.assertIn("消息面：中性", html)

    def test_shows_six_fundamental_sections(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("公司是干什么的", html)
        self.assertIn("成长性", html)
        self.assertIn("盈利质量", html)
        self.assertIn("财务安全性", html)
        self.assertIn("估值是否合理", html)
        self.assertIn("⚠️ 风险", html)
        self.assertIn("消费疲软", html)

    def test_shows_news_title_source_time(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("公司发布年报", html)
        self.assertIn("巨潮资讯", html)
        self.assertIn("2026-04-28", html)

    def test_shows_mid_term_and_recent_event_sections(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("中线逻辑", html)
        self.assertIn("最近5天短线触发器", html)
        self.assertIn("最近5天短线风险", html)
        self.assertIn("基本面稳健但成长性放缓", html)
        self.assertIn("新增订单催化", html)
        self.assertIn("供应链争议", html)

    def test_escapes_untrusted_html_content(self):
        result = _make_review_result("600519", "<script>alert(1)</script>", "HOLD")
        result["llm_review"]["executive_summary"] = '结论含<script>"x"&</script>'
        result["llm_review"]["mid_term_view"] = '中线<&>"'
        result["llm_review"]["news_analysis"]["summary"] = '新闻摘要<script>&'
        result["llm_review"]["news_analysis"]["key_news"][0]["title"] = '<b>恶意标题</b>'
        result["llm_review"]["short_term_risks"][0]["title"] = '<img src=x onerror=1>'
        result["llm_review"]["short_term_risks"][0]["summary"] = '风险<&>"'
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;b&gt;恶意标题&lt;/b&gt;", html)
        self.assertIn("&lt;img src=x onerror=1&gt;", html)
        self.assertIn("风险&lt;&amp;&gt;&quot;", html)

    def test_no_pe_none_in_html(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertNotIn("PE: None", html)
        self.assertNotIn("PB: None", html)

    def test_shows_no_ai_review_rule_only(self):
        """HTML must not show 'AI复核：rule_only'."""
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertNotIn("AI复核：rule_only", html)

    def test_llm_disabled_shows_rule_diagnosis(self):
        result = _make_review_result("600519", "茅台", "HOLD", llm_enabled=False)
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("规则诊断（未启用LLM）", html)

    def test_empty_scenarios_not_rendered(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertNotIn("乐观路径", html)
        self.assertNotIn("悲观路径", html)
        self.assertNotIn("中性路径", html)

    def test_no_news_shows_placeholder(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        result["llm_review"]["news_analysis"]["key_news"] = []
        result["news"] = {"summary": "无有效新闻"}
        result["news_raw"] = []
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("暂无相关新闻", html)

    def test_shows_executive_summary(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("基本面稳健", html)

    def test_shows_operation_conditions(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("持有：不破ZD", html)
        self.assertIn("止损：跌破ZD 48", html)
        self.assertIn("加仓：30min确认", html)

    def test_shows_data_gaps(self):
        result = _make_review_result("600519", "茅台", "HOLD")
        data = build_report_data([result], "2026-05-26")
        html = generate_html_report(data)
        self.assertIn("数据缺口", html)


if __name__ == "__main__":
    unittest.main()
