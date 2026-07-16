import unittest
from datetime import date, datetime, timedelta, timezone
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

    def test_collect_daily_data_intraday_has_close_metadata_but_is_not_official(self):
        as_of = datetime(2026, 6, 30, 14, 35, tzinfo=timezone(timedelta(hours=8)))
        stock_row = {
            "code": "600000",
            "name": "测试股",
            "klines": _kline(["2026-06-29", "2026-06-30"], [10.0, 11.0]),
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-06-30",
                "source": "tencent",
                "bars": 2,
                "stale": False,
            },
        }

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=[
            {"code": "BK0001", "name": "AI", "change_pct": 2.1, "flow": 10_000_000}
        ]), patch.object(
            data_fetcher, "fetch_sector_stocks", return_value=[{"code": "600000", "name": "测试股"}]
        ), patch.object(
            data_fetcher, "batch_fetch_daily_klines", return_value=[stock_row]
        ), patch.object(
            data_fetcher,
            "fetch_shanghai_index",
            return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
        ):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30",
                generated_at=as_of,
            )

        quality = result["data_quality"]
        self.assertEqual(quality["bar_state"], "intraday")
        self.assertEqual(quality["generated_at"], "2026-06-30T14:35:00+08:00")
        self.assertEqual(quality["as_of"], "2026-06-30T14:35:00+08:00")
        self.assertFalse(quality["is_official"])

    def test_collect_daily_data_closed_run_forces_daily_refresh_and_can_be_official(self):
        as_of = datetime(2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8)))
        calls = []

        def fake_batch(stocks, required_date=None, allow_stale=False, max_workers=10, force_refresh=False):
            calls.append(force_refresh)
            return [{
                "code": "600000",
                "name": "测试股",
                "klines": _kline(["2026-06-29", "2026-06-30"], [10.0, 11.0]),
                "data_status": {
                    "daily": "verified",
                    "latest_date": "2026-06-30",
                    "source": "tencent",
                    "bars": 2,
                    "stale": False,
                },
            }]

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=[
            {"code": "BK0001", "name": "AI", "change_pct": 2.1, "flow": 10_000_000}
        ]), patch.object(
            data_fetcher, "fetch_sector_stocks", return_value=[{"code": "600000", "name": "测试股"}]
        ), patch.object(
            data_fetcher, "batch_fetch_daily_klines", side_effect=fake_batch
        ), patch.object(
            data_fetcher,
            "fetch_shanghai_index",
            return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
        ):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30",
                generated_at=as_of,
            )

        self.assertEqual(calls, [True])
        self.assertEqual(result["data_quality"]["bar_state"], "closed")
        self.assertTrue(result["data_quality"]["sources_trusted"])
        self.assertTrue(result["data_quality"]["is_official"])

    def test_batch_fetch_daily_klines_propagates_close_refresh(self):
        kline = _kline(["2026-06-30"] * 60, [10.0] * 60)
        with patch.object(data_fetcher, "fetch_daily_kline", return_value=kline) as fetch:
            data_fetcher.batch_fetch_daily_klines(
                [{"code": "600000", "name": "测试股"}],
                required_date="2026-06-30",
                force_refresh=True,
            )

        fetch.assert_called_once_with("600000", force_refresh=True)

    def test_build_kline_status_marks_verified_and_stale(self):
        verified = _kline(
            ["2026-06-29", "2026-06-30"],
            [10.0] * 2,
        )
        stale = _kline(
            ["2026-06-29", "2026-06-29"],
            [10.0] * 2,
        )

        verified_status = data_fetcher.build_kline_status(
            verified,
            required_date="2026-06-30",
            source="tencent",
        )
        stale_status = data_fetcher.build_kline_status(
            stale,
            required_date="2026-06-30",
            source="tencent",
        )

        self.assertEqual(
            verified_status,
            {
                "daily": "verified",
                "latest_date": "2026-06-30",
                "source": "tencent",
                "bars": 2,
                "stale": False,
            },
        )
        self.assertEqual(
            stale_status,
            {
                "daily": "stale_cache",
                "latest_date": "2026-06-29",
                "source": "tencent",
                "bars": 2,
                "stale": True,
            },
        )

    def test_batch_fetch_daily_klines_filters_stale_in_official_mode(self):
        stale = _kline(
            ["2026-06-29"] * 60,
            [10.0] * 60,
        )

        with patch.object(data_fetcher, "fetch_daily_kline", return_value=stale):
            stocks = data_fetcher.batch_fetch_daily_klines(
                [{"code": "600000", "name": "测试股"}],
                required_date="2026-06-30",
                allow_stale=False,
            )

        self.assertEqual(stocks, [])

    def test_batch_fetch_daily_klines_keeps_stale_with_status_in_preview_mode(self):
        stale = _kline(
            ["2026-06-29"] * 60,
            [10.0] * 60,
        )

        with patch.object(data_fetcher, "fetch_daily_kline", return_value=stale):
            stocks = data_fetcher.batch_fetch_daily_klines(
                [{"code": "600000", "name": "测试股"}],
                required_date="2026-06-30",
                allow_stale=True,
            )

        self.assertEqual(len(stocks), 1)
        self.assertEqual(stocks[0]["data_status"]["daily"], "stale_cache")

    def test_batch_fetch_daily_klines_passes_market_cap_metadata(self):
        stable = _kline(
            ["2026-06-30"] * 60,
            [10.0] * 60,
        )

        stock = {
            "code": "600000",
            "name": "测试股",
            "sector": "测试板块",
            "sector_tags": ["测试板块"],
            "market_cap": 12345.67,
            "float_market_cap": 9876.54,
            "amount": 555,
            "amounts": [1000, 2000, 3000],
        }

        with patch.object(data_fetcher, "fetch_daily_kline", return_value=stable):
            stocks = data_fetcher.batch_fetch_daily_klines(
                [stock],
                required_date="2026-06-30",
                allow_stale=True,
            )

        self.assertEqual(len(stocks), 1)
        self.assertEqual(stocks[0]["market_cap"], 12345.67)
        self.assertEqual(stocks[0]["float_market_cap"], 9876.54)
        self.assertEqual(stocks[0]["amount"], 555)
        self.assertEqual(stocks[0]["amounts"], [1000, 2000, 3000])

    def test_fetch_sector_stocks_normalizes_market_caps_to_yi(self):
        payload = {
            "data": {
                "diff": [
                    {
                        "f12": "300001",
                        "f14": "测试成长",
                        "f3": 2.0,
                        "f2": 20.0,
                        "f20": 30_000_000_000,
                        "f21": 12_000_000_000,
                    }
                ]
            }
        }

        with patch.object(data_fetcher, "_fetch_eastmoney_json", return_value=payload):
            stocks = data_fetcher.fetch_sector_stocks("BK0001")

        self.assertEqual(stocks[0]["market_cap"], 300.0)
        self.assertEqual(stocks[0]["circulating_market_cap"], 120.0)
        self.assertEqual(stocks[0]["float_market_cap"], 120.0)

    def test_eastmoney_kline_parser_keeps_amounts(self):
        api_payload = {
            "data": {
                "klines": [
                    "2026-06-27,10.00,10.20,10.40,9.90,1000,500000,10000,10020,10030,10040,10050",
                    "2026-06-28,10.20,10.30,10.60,10.00,1200,600000,13000,12020,12030,12040,12050",
                ]
            }
        }

        class FakeResp:
            def json(self):
                return api_payload

        with patch.object(data_fetcher.SESSION, "get", return_value=FakeResp()):
            kline = data_fetcher._fetch_daily_kline_eastmoney_remote("600000", count=2)

        self.assertIn("amounts", kline)
        self.assertIsInstance(kline["amounts"], np.ndarray)
        self.assertEqual(len(kline["amounts"]), 2)
        self.assertEqual(float(kline["amounts"][0]), 500000.0)
        self.assertEqual(float(kline["amounts"][1]), 600000.0)

    def test_collect_daily_data_preserves_sector_tags_and_quality(self):
        sectors = [
            {"code": "BK0001", "name": "AI", "change_pct": 2.1, "flow": 10_000_000},
            {"code": "BK0002", "name": "新能源", "change_pct": 1.4, "flow": 8_000_000},
        ]
        sector_stocks = {
            "BK0001": [{"code": "600000", "name": "测试股", "change_pct": 2.1}],
            "BK0002": [{"code": "600000", "name": "测试股", "change_pct": 1.4}],
        }

        def fake_batch_fetch(
            stocks, required_date=None, allow_stale=False, max_workers=10, force_refresh=False
        ):
            stock = stocks[0]
            self.assertEqual(stock["code"], "600000")
            self.assertEqual(stock["sector"], "AI")
            self.assertEqual(stock["sector_tags"], ["AI", "新能源"])
            return [
                {
                    "code": stock["code"],
                    "name": stock["name"],
                    "sector": stock["sector"],
                    "sector_tags": stock["sector_tags"],
                    "sector_rank": stock["sector_rank"],
                    "sector_flow": stock["sector_flow"],
                    "sector_strength_label": stock["sector_strength_label"],
                    "change_pct": stock["change_pct"],
                    "klines": _kline(["2026-06-29", "2026-06-30"], [10.0, 11.0]),
                    "data_status": {
                        "daily": "verified",
                        "latest_date": "2026-06-30",
                        "source": "tencent",
                        "bars": 2,
                        "stale": False,
                    },
                }
            ]

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=sectors), \
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=lambda code: sector_stocks.get(code, [])), \
             patch.object(data_fetcher, "batch_fetch_daily_klines", side_effect=fake_batch_fetch), \
             patch.object(data_fetcher, "fetch_shanghai_index", return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0])):
            result = data_fetcher.collect_daily_data(required_date="2026-06-30")

        self.assertEqual(len(result["stocks"]), 1)
        self.assertEqual(result["stocks"][0]["sector"], "AI")
        self.assertEqual(result["stocks"][0]["sector_tags"][0], "AI")
        self.assertEqual(result["stocks"][0]["sector_rank"], 1)
        self.assertEqual(result["stocks"][0]["sector_strength_label"], "资金流入TOP1")
        self.assertIn("data_quality", result)
        self.assertEqual(result["data_quality"]["stock_pool_source"], "sector_components")
        self.assertEqual(result["data_quality"]["sector_source"], "eastmoney")
        self.assertTrue(result["data_quality"]["is_official"])

    def test_collect_daily_data_static_sector_fallback_sets_fallback_used(self):
        stock_calls = [{"code": "600000", "name": "测试股"}]

        def fake_sector_stocks(code):
            if code == "BK0480":
                return stock_calls
            return []

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=[]), \
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=fake_sector_stocks), \
             patch.object(data_fetcher, "batch_fetch_daily_klines", return_value=[
                 {
                     "code": "600000",
                     "name": "测试股",
                     "sector": "人工智能",
                     "sector_tags": ["人工智能"],
                     "sector_rank": 1,
                     "sector_flow": 0,
                     "sector_strength_label": "资金流入TOP1",
                     "klines": _kline(["2026-06-29", "2026-06-30"], [10, 11]),
                     "data_status": {
                         "daily": "verified",
                         "latest_date": "2026-06-30",
                         "source": "tencent",
                         "bars": 2,
                         "stale": False,
                     },
                 }
             ]), \
             patch.object(data_fetcher, "fetch_shanghai_index", return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0])):
            result = data_fetcher.collect_daily_data(required_date="2026-06-30")

        dq = result["data_quality"]
        self.assertTrue(dq["fallback_used"])
        self.assertTrue(dq["warnings"])
        self.assertEqual(dq["sector_source"], "fallback_static")
        self.assertFalse(dq["is_official"])

    def test_collect_daily_data_stale_rows_are_official_false(self):
        sectors = [{"code": "BK0001", "name": "AI", "change_pct": 2.1, "flow": 10_000_000}]
        stale_kline = _kline(["2026-06-29", "2026-06-29"] * 30, [10.0] * 60)

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=sectors), \
             patch.object(data_fetcher, "fetch_sector_stocks", return_value=[{"code": "600000", "name": "测试股"}]), \
             patch.object(data_fetcher, "fetch_daily_kline", return_value=stale_kline), \
             patch.object(data_fetcher, "fetch_shanghai_index", return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0])):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30",
                allow_missing_index=True,
            )

        dq = result["data_quality"]
        self.assertTrue(dq["stale_stock_count"] > 0)
        self.assertFalse(dq["is_official"])

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

    def test_daily_run_revalidates_immediately_before_staging(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("set -e", script)
        last_validator = script.rfind('/usr/bin/python3 scripts/validate_today_report.py "$TODAY"')
        git_add = script.find("git add \\")
        self.assertGreater(last_validator, 0)
        self.assertGreater(git_add, last_validator)


class TestReportContractGuard(unittest.TestCase):

    def test_validate_report_contract_rejects_official_without_closed_metadata(self):
        report = {
            "date": "2026-06-30",
            "picks_fusion": [],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {"views": {"highlights": [], "main": [], "baseline": []}},
            "data_quality": {
                "report_date": "2026-06-30",
                "generated_at": "2026-06-30T14:35:00+08:00",
                "as_of": "2026-06-30T14:35:00+08:00",
                "bar_state": "intraday",
                "sources_trusted": True,
                "is_trading_day": True,
                "is_official": True,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
        }

        errors = validate_report_contract(report)
        self.assertTrue(any("bar_state == 'closed'" in err for err in errors))

        for missing_key, expected_error in (
            ("generated_at", "valid data_quality.generated_at"),
            ("as_of", "valid data_quality.as_of"),
            ("bar_state", "bar_state == 'closed'"),
        ):
            with self.subTest(missing_key=missing_key):
                missing = dict(report)
                missing["data_quality"] = dict(report["data_quality"])
                missing["data_quality"].pop(missing_key)
                missing_errors = validate_report_contract(missing)
                self.assertTrue(any(expected_error in err for err in missing_errors))

    def test_validate_report_contract_requires_official_for_publish_but_keeps_preview_compatible(self):
        report = {
            "date": "2026-06-30",
            "picks_fusion": [],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {"views": {"highlights": [], "main": [], "baseline": []}},
            "data_quality": {
                "report_date": "2026-06-30",
                "generated_at": "2026-06-30T14:35:00+08:00",
                "as_of": "2026-06-30T14:35:00+08:00",
                "bar_state": "intraday",
                "sources_trusted": True,
                "is_trading_day": True,
                "is_official": False,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
        }

        self.assertEqual(validate_report_contract(report), [])
        errors = validate_report_contract(report, require_official=True)
        self.assertTrue(any("requires data_quality.is_official == True" in err for err in errors))

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

    def test_validate_report_contract_rejects_official_stale_data_quality(self):
        report = {
            "picks_fusion": [
                {
                    "code": "600001",
                    "change_pct": 1.2,
                    "current_price": 10.2,
                    "data_status": {"daily": "verified"},
                },
            ],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [
                        {
                            "code": "600001",
                            "ref": {"pool": "picks_fusion", "code": "600001"},
                            "data_status": {"daily": "verified"},
                        },
                    ],
                    "main": [
                        {
                            "code": "600001",
                            "ref": {"pool": "picks_fusion", "code": "600001"},
                            "data_status": {"daily": "verified"},
                        },
                    ],
                    "baseline": [],
                }
            },
            "data_quality": {
                "is_official": True,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 1,
                "missing_daily_count": 0,
            },
        }

        errors = validate_report_contract(report)
        self.assertTrue(any("stale_stock_count" in err for err in errors))

    def test_validate_report_contract_rejects_official_stale_candidate_status(self):
        report = {
            "picks_fusion": [
                {
                    "code": "600002",
                    "change_pct": 2.1,
                    "current_price": 11.4,
                    "data_status": {"daily": "stale_cache"},
                }
            ],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [
                        {
                            "code": "600002",
                            "ref": {"pool": "picks_fusion", "code": "600002"},
                            "data_status": {"daily": "verified"},
                        },
                    ],
                    "main": [
                        {
                            "code": "600002",
                            "ref": {"pool": "picks_fusion", "code": "600002"},
                            "data_status": {"daily": "verified"},
                        },
                    ],
                    "baseline": [],
                }
            },
            "data_quality": {
                "is_official": True,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
        }

        errors = validate_report_contract(report)
        self.assertTrue(any("stale daily cache" in err for err in errors))

    def test_validate_report_contract_rejects_official_stale_non_main_view_row(self):
        report = {
            "picks_fusion": [],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [],
                    "main": [],
                    "baseline": [],
                    "confirming": [
                        {
                            "code": "600005",
                            "change_pct": 1.0,
                            "current_price": 9.9,
                            "data_status": {"daily": "stale_cache"},
                        }
                    ],
                }
            },
            "data_quality": {
                "is_official": True,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
        }

        errors = validate_report_contract(report)
        self.assertTrue(any("confirming row has stale daily cache" in err for err in errors))

    def test_validate_report_contract_rejects_official_stale_raw_pool_candidate(self):
        report = {
            "picks_fusion": [],
            "picks_pure": [],
            "next_day_boom": {
                "candidates": [
                    {
                        "code": "600006",
                        "change_pct": 1.0,
                        "current_price": 10.0,
                        "data_status": {"daily": "stale_cache"},
                    }
                ]
            },
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [],
                    "main": [],
                    "baseline": [],
                    "acceleration": [],
                }
            },
            "data_quality": {
                "is_official": True,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
        }

        errors = validate_report_contract(report)
        self.assertTrue(any("next_day_boom candidate has stale daily cache" in err for err in errors))

    def test_validate_report_contract_rejects_official_malformed_data_status(self):
        report = {
            "picks_fusion": [
                {
                    "code": "600007",
                    "change_pct": 1.0,
                    "current_price": 10.0,
                    "data_status": "bad-shape",
                }
            ],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [],
                    "main": [
                        {
                            "code": "600007",
                            "change_pct": 1.0,
                            "current_price": 10.0,
                            "ref": {"pool": "picks_fusion", "code": "600007"},
                            "data_status": "bad-shape",
                        }
                    ],
                    "baseline": [],
                }
            },
            "data_quality": {
                "is_official": True,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
        }

        errors = validate_report_contract(report)
        self.assertTrue(any("main row missing valid data_status" in err for err in errors))
        self.assertTrue(any("picks_fusion candidate missing valid data_status" in err for err in errors))

    def test_validate_report_contract_allows_preview_stale_status_when_not_official(self):
        report = {
            "picks_fusion": [
                {
                    "code": "600003",
                    "change_pct": 1.6,
                    "current_price": 13.3,
                    "data_status": {"daily": "stale_cache"},
                }
            ],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "workspace": {
                "views": {
                    "highlights": [
                        {"code": "600003", "ref": {"pool": "picks_fusion", "code": "600003"}},
                    ],
                    "main": [
                        {"code": "600003", "ref": {"pool": "picks_fusion", "code": "600003"}},
                    ],
                    "baseline": [],
                }
            },
            "data_quality": {
                "is_official": False,
                "market_status": "unverified",
                "fallback_used": True,
                "stale_stock_count": 0,
                "missing_daily_count": 3,
            },
        }

        self.assertEqual(validate_report_contract(report), [])


if __name__ == "__main__":
    unittest.main()
