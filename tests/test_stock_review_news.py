"""Unit tests for stock_review news module."""
import unittest
from unittest.mock import patch
from chanlun.stock_review.news import (
    fetch_news,
    analyze_news_sentiment,
    extract_recent_event_window,
)


class TestFetchNews(unittest.TestCase):

    def test_returns_list(self):
        result = fetch_news("600519", "贵州茅台")
        self.assertIsInstance(result, list)

    def test_no_fake_placeholder_when_empty(self):
        """API no results must return [], never generate fake '暂无相关新闻'."""
        result = fetch_news("000000", "不存在的股票")
        # Should be empty list, NOT contain a placeholder
        self.assertIsInstance(result, list)
        for item in result:
            self.assertNotIn("暂无", item.get("title", ""))

    def test_each_item_has_required_fields(self):
        result = fetch_news("600519", "贵州茅台")
        for item in result:
            for key in ["title", "time", "source", "url", "matched_reason",
                         "category", "sentiment", "impact_strength"]:
                self.assertIn(key, item, f"Missing key: {key}")

    def test_empty_code_returns_empty(self):
        result = fetch_news("", "")
        self.assertEqual(result, [])

    @patch("chanlun.stock_review.news.fetch_cls_news")
    @patch("chanlun.stock_review.news.SESSION.get")
    def test_falls_back_to_cls_news_when_stock_news_empty(self, mock_get, mock_fetch_cls_news):
        mock_get.return_value.json.return_value = {"data": {"list": []}}
        mock_fetch_cls_news.return_value = [
            {
                "title": "贵州茅台发布一季报",
                "content": "贵州茅台净利润增长",
                "brief": "业绩披露",
                "ctime": 1716700000,
            }
        ]
        result = fetch_news("600519", "贵州茅台")
        self.assertEqual(len(result), 1)
        self.assertIn("贵州茅台", result[0]["title"])
        self.assertEqual(result[0]["source"], "财联社")


class TestAnalyzeNewsSentiment(unittest.TestCase):

    def test_empty_news_returns_no_news(self):
        result = analyze_news_sentiment([])
        self.assertEqual(result["positive"], [])
        self.assertEqual(result["negative"], [])
        self.assertEqual(result["neutral"], [])
        self.assertEqual(result["summary"], "无有效新闻")

    def test_returns_structured_output(self):
        news = [
            {"title": "利好测试", "time": "2026-05-26", "source": "test",
             "url": "", "matched_reason": "test",
             "category": "其他", "sentiment": "利好", "impact_strength": "弱"}
        ]
        result = analyze_news_sentiment(news)
        for key in ["positive", "negative", "neutral", "already_priced_in", "summary"]:
            self.assertIn(key, result)

    def test_preserves_news_detail_in_categories(self):
        news = [
            {"title": "订单大增", "time": "2026-05-26", "source": "test",
             "url": "", "matched_reason": "test",
             "category": "订单类", "sentiment": "利好", "impact_strength": "中"},
            {"title": "减持公告", "time": "2026-05-25", "source": "test",
             "url": "", "matched_reason": "test",
             "category": "资本动作", "sentiment": "利空", "impact_strength": "中"},
        ]
        result = analyze_news_sentiment(news)
        self.assertEqual(len(result["positive"]), 1)
        self.assertEqual(len(result["negative"]), 1)
        self.assertEqual(result["positive"][0]["source_title"], "订单大增")
        self.assertEqual(result["negative"][0]["source_title"], "减持公告")


class TestRecentEventWindow(unittest.TestCase):

    def test_extracts_only_recent_five_day_events(self):
        news = [
            {"title": "最近订单落地", "time": "2026-05-26 10:00", "source": "test",
             "url": "", "matched_reason": "test", "category": "订单类",
             "sentiment": "利好", "impact_strength": "中"},
            {"title": "供应链争议发酵", "time": "2026-05-23 09:00", "source": "test",
             "url": "", "matched_reason": "test", "category": "风险事件",
             "sentiment": "利空", "impact_strength": "强"},
            {"title": "过期旧闻", "time": "2026-05-20 09:00", "source": "test",
             "url": "", "matched_reason": "test", "category": "资本动作",
             "sentiment": "利空", "impact_strength": "中"},
        ]

        result = extract_recent_event_window(news, reference_date="2026-05-27", window_days=5)
        self.assertEqual(result["event_window_days"], 5)
        self.assertEqual(len(result["short_term_catalysts"]), 1)
        self.assertEqual(len(result["short_term_risks"]), 1)
        self.assertEqual(result["short_term_catalysts"][0]["title"], "最近订单落地")
        self.assertEqual(result["short_term_risks"][0]["title"], "供应链争议发酵")

    def test_omits_invalid_or_undated_items_from_recent_window(self):
        news = [
            {"title": "无日期新闻", "time": "", "source": "test",
             "url": "", "matched_reason": "test", "category": "订单类",
             "sentiment": "利好", "impact_strength": "中"},
            {"title": "非法日期新闻", "time": "unknown", "source": "test",
             "url": "", "matched_reason": "test", "category": "风险事件",
             "sentiment": "利空", "impact_strength": "中"},
        ]

        result = extract_recent_event_window(news, reference_date="2026-05-27", window_days=5)
        self.assertEqual(result["short_term_catalysts"], [])
        self.assertEqual(result["short_term_risks"], [])


if __name__ == "__main__":
    unittest.main()
