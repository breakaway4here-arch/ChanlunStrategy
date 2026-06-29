import unittest
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np

import run
from chanlun import data_fetcher


def _kline(dates, closes):
    n = len(dates)
    return {
        "dates": dates,
        "opens": np.array(closes, dtype=float),
        "highs": np.array(closes, dtype=float),
        "lows": np.array(closes, dtype=float),
        "closes": np.array(closes, dtype=float),
        "volumes": np.ones(n) * 1000,
    }


class TestMarketDataGuard(unittest.TestCase):

    def test_market_indices_raise_when_no_source_has_valid_today_data(self):
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=None):
            with self.assertRaises(data_fetcher.MarketDataUnavailable):
                run.fetch_market_indices(report_date="2026-06-26")

    def test_preview_market_indices_mark_unverified_without_live_data(self):
        result = run.build_unverified_market_indices(
            report_date="2026-06-26",
            reason="000001 指数多源取数失败",
            index_codes={"上证指数": "000001"},
        )

        self.assertEqual(result["上证指数"]["status"], "unverified")
        self.assertEqual(result["上证指数"]["date"], "2026-06-26")
        self.assertIsNone(result["上证指数"]["close"])
        self.assertIsNone(result["上证指数"]["change_pct"])
        self.assertIn("多源取数失败", result["上证指数"]["reason"])

    def test_market_indices_reject_stale_index_data(self):
        stale = _kline(["2026-06-24", "2026-06-25"], [4100, 4120])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=stale), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=stale), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=stale):
            with self.assertRaises(data_fetcher.MarketDataUnavailable):
                run.fetch_market_indices(report_date="2026-06-26")

    def test_market_indices_use_second_source_when_first_source_fails(self):
        fresh = _kline(["2026-06-25", "2026-06-26"], [4120.28, 4027.26])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=fresh), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=None):
            result = run.fetch_market_indices(
                report_date="2026-06-26",
                index_codes={"上证指数": "000001"},
            )

        self.assertEqual(result["上证指数"]["close"], 4027.26)
        self.assertEqual(result["上证指数"]["change_pct"], -2.26)
        self.assertEqual(result["上证指数"]["source"], "eastmoney")

    def test_long_index_analysis_rejects_quote_only_source(self):
        quote_only = _kline(["2026-06-26", "2026-06-26"], [4120.28, 4027.26])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=quote_only):
            with self.assertRaises(data_fetcher.MarketDataUnavailable):
                data_fetcher.fetch_shanghai_index(required_date="2026-06-26")

    def test_collect_daily_data_preview_can_continue_without_index(self):
        with patch.object(data_fetcher, "fetch_sector_flow", return_value=[
            {"code": "BK0001", "name": "测试板块", "flow_str": "1亿"}
        ]), \
             patch.object(data_fetcher, "fetch_sector_stocks", return_value=[
                 {"code": "600000", "name": "测试股"}
             ]), \
             patch.object(data_fetcher, "batch_fetch_daily_klines", return_value=[
                 {"code": "600000", "name": "测试股", "klines": _kline(["2026-06-25", "2026-06-26"], [10, 11])}
             ]), \
             patch.object(data_fetcher, "fetch_shanghai_index", side_effect=data_fetcher.MarketDataUnavailable("000001 指数多源取数失败")):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-26",
                allow_missing_index=True,
            )

        self.assertIsNone(result["sh_index"])
        self.assertEqual(result["index_error"], "000001 指数多源取数失败")
        self.assertEqual(len(result["stocks"]), 1)


class TestDailyRunScriptGuard(unittest.TestCase):

    def test_daily_run_does_not_skip_existing_output_after_recheck_time(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("python3 scripts/validate_today_report.py", script)
        self.assertNotIn("今日产物已存在，跳过补跑", script)


if __name__ == "__main__":
    unittest.main()
