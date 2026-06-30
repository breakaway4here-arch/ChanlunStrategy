import unittest
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np

import run
from chanlun import data_fetcher
from scripts.validate_today_report import validate_report_contract


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
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=None), \
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
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=stale), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=stale), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=stale), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=stale):
            with self.assertRaises(data_fetcher.MarketDataUnavailable):
                run.fetch_market_indices(report_date="2026-06-26")

    def test_market_indices_use_second_source_when_first_source_fails(self):
        fresh = _kline(["2026-06-25", "2026-06-26"], [4120.28, 4027.26])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=fresh), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=None):
            result = run.fetch_market_indices(
                report_date="2026-06-26",
                index_codes={"上证指数": "000001"},
            )

        self.assertEqual(result["上证指数"]["close"], 4027.26)
        self.assertEqual(result["上证指数"]["change_pct"], -2.26)
        self.assertEqual(result["上证指数"]["source"], "eastmoney")

    def test_long_index_analysis_uses_tencent_plain_history_when_qfq_is_blocked(self):
        history = _kline([f"2026-01-{i:02d}" for i in range(1, 21)] + ["2026-06-26"], list(range(1, 22)))
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=history), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=None):
            result = data_fetcher.fetch_shanghai_index(required_date="2026-06-26")

        self.assertEqual(result["source"], "tencent_plain")
        self.assertEqual(result["dates"][-1], "2026-06-26")

    def test_long_index_analysis_splices_sina_history_with_verified_realtime_bar(self):
        history = _kline([f"2026-01-{i:02d}" for i in range(1, 20)] + ["2026-06-26"], list(range(1, 21)))
        quote = _kline(["2026-06-29", "2026-06-29"], [20.0, 21.0])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=history), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=quote):
            result = data_fetcher.fetch_shanghai_index(required_date="2026-06-29")

        self.assertEqual(result["source"], "sina_daily+sina_quote")
        self.assertEqual(result["dates"][-2:], ["2026-06-26", "2026-06-29"])
        self.assertEqual(float(result["closes"][-2]), 20.0)
        self.assertEqual(float(result["closes"][-1]), 21.0)

    def test_long_index_analysis_rejects_cache_splice_when_quote_prev_close_mismatches(self):
        stale_cache = [{"date": f"2026-01-{i:02d}", "open": 1, "high": 1, "low": 1, "close": i, "volume": 1}
                       for i in range(1, 20)]
        stale_cache.append({"date": "2026-06-24", "open": 1, "high": 1, "low": 1, "close": 99, "volume": 1})
        quote = _kline(["2026-06-29", "2026-06-29"], [20.0, 21.0])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_quote_remote", return_value=quote), \
             patch.object(data_fetcher, "read_cached_records", return_value=stale_cache):
            with self.assertRaises(data_fetcher.MarketDataUnavailable):
                data_fetcher.fetch_shanghai_index(required_date="2026-06-29")

    def test_long_index_analysis_rejects_quote_only_source(self):
        quote_only = _kline(["2026-06-26", "2026-06-26"], [4120.28, 4027.26])
        with patch.object(data_fetcher, "_fetch_daily_kline_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_tencent_plain_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote", return_value=None), \
             patch.object(data_fetcher, "_fetch_daily_kline_sina_daily_remote", return_value=None), \
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

    def test_daily_run_git_add_scope_is_today_and_assets_only(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertNotIn("docs/20*/", script)
        self.assertIn('"docs/${TODAY}/index.html"', script)
        self.assertIn('"docs/data/${TODAY}.json"', script)
        self.assertNotIn("git add docs/index.html docs/data.json docs/data/ docs/20*/", script)


class TestReportContractGuard(unittest.TestCase):

    def test_validate_report_contract_allows_raw_change_fallback(self):
        report = {
            "picks_fusion": [
                {
                    "code": "600001",
                    "closes": [10.0, 10.5, 10.29],
                    "best_buy_point": {"current_price": 10.29},
                }
            ],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [
                        {"code": "600001", "ref": {"pool": "picks_fusion", "code": "600001"}},
                    ],
                    "main": [
                        {"code": "600001", "ref": {"pool": "picks_fusion", "code": "600001"}},
                    ],
                    "baseline": [],
                }
            },
        }

        self.assertEqual(validate_report_contract(report), [])

    def test_validate_report_contract_reports_missing_change_when_not_resolvable(self):
        report = {
            "picks_fusion": [
                {"code": "600002", "closes": [10.0]},
            ],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [
                        {"code": "600002", "ref": {"pool": "picks_fusion", "code": "600002"}},
                    ],
                    "main": [
                        {"code": "600002", "ref": {"pool": "picks_fusion", "code": "600002"}},
                    ],
                    "baseline": [],
                }
            },
        }

        self.assertTrue(validate_report_contract(report))
        errors = validate_report_contract(report)
        self.assertTrue(any("missing displayable change_pct" in err and "600002" in err for err in errors))

    def test_validate_report_contract_requires_main_with_nonempty_source_pool(self):
        report = {
            "picks_fusion": [
                {"code": "600003", "change_pct": 2.0},
            ],
            "picks_pure": [{"code": "600004", "change_pct": 1.0}],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [],
                    "main": [],
                    "baseline": [],
                }
            },
        }

        errors = validate_report_contract(report)
        self.assertIn("main view missing while picks_fusion is non-empty", errors)
        self.assertIn("baseline view missing while picks_pure is non-empty", errors)

    def test_validate_report_contract_handles_malformed_source_pools(self):
        report = {
            "picks_fusion": None,
            "picks_pure": {"bad": "shape"},
            "next_day_boom": {"candidates": None},
            "luojie_pool": {"candidates": None},
            "startup_watchlist": None,
            "workspace": {
                "views": {
                    "highlights": [],
                    "main": [],
                    "baseline": [],
                }
            },
        }

        self.assertEqual(validate_report_contract(report), [])


if __name__ == "__main__":
    unittest.main()
