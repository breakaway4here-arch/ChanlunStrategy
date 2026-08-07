import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

import run
from chanlun import data_fetcher
from chanlun.kline_cache import write_cached_records
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


def _official_empty_report():
    return {
        "date": "2026-06-30",
        "picks_fusion": [],
        "picks_pure": [],
        "next_day_boom": {"candidates": []},
        "luojie_pool": {"candidates": []},
        "startup_watchlist": [],
        "workspace": {"views": {"highlights": [], "main": [], "baseline": []}},
        "data_quality": {
            "report_date": "2026-06-30",
            "generated_at": "2026-06-30T15:05:00+08:00",
            "as_of": "2026-06-30T15:05:00+08:00",
            "bar_state": "closed",
            "sources_trusted": True,
            "is_trading_day": True,
            "is_official": True,
            "stock_pool_incomplete": False,
            "market_status": "verified",
            "fallback_used": False,
            "stale_stock_count": 0,
            "missing_daily_count": 0,
        },
    }


def _sector_rows(start, count):
    return [
        {
            "f12": f"{index:06d}",
            "f14": f"股票{index}",
            "f3": 1.0,
            "f2": 10.0,
            "f20": 10_000_000_000,
            "f21": 5_000_000_000,
        }
        for index in range(start, start + count)
    ]


def _complete_sector_fetch(rows_by_code):
    def fake(code, *, return_diagnostics=False):
        rows = list(rows_by_code.get(code, []))
        diag = {
            "sector_code": code,
            "page_size": 100,
            "requested": len(rows),
            "fetched": len(rows),
            "unique": len({row.get("code") for row in rows if row.get("code")}),
            "pages": 1,
            "complete": True,
            "error": "",
        }
        return (rows, diag) if return_diagnostics else rows

    return fake


class TestMarketDataGuard(unittest.TestCase):

    def test_partial_industry_hydration_is_visible_in_data_quality_warnings(self):
        quality = {"warnings": []}

        run._record_industry_metadata_quality(
            quality,
            {"status": "partial", "missing_after": 12},
        )

        self.assertTrue(
            any("行业元数据覆盖不完整" in item for item in quality["warnings"])
        )

    def test_decision_context_carries_market_sentiment_risk_evidence(self):
        sentiment = {"score": 35, "turning_signal": "turning_weaker"}

        context = run._build_decision_market_context(
            market_indices={"上证指数": {"change_pct": -2.0}},
            sectors=[],
            report_date="2026-07-16",
            data_quality={"is_official": True},
            market_data_status="verified",
            market_sentiment=sentiment,
        )

        self.assertIs(context["market_sentiment"], sentiment)
        self.assertEqual(context["market_sentiment"]["turning_signal"], "turning_weaker")

    def test_position_evidence_uses_120_day_close_percentile_not_same_day_reference(self):
        closes = [10.0 + index * 0.1 for index in range(119)] + [30.0]
        row = {
            "code": "600000",
            "source_channel": "low_position",
            "best_buy_point": {
                "type": "强势启动候选",
                "source_type": "日线强势启动",
                "price": 30.0,
            },
            "closes": closes,
            "data_status": {"daily": "verified", "latest_date": "2026-07-16"},
        }

        result = run._attach_position_evidence(row, "2026-07-16")

        self.assertEqual(result["position_distance_pct"], 0.0)
        self.assertEqual(result["position_absolute_window"], 120)
        self.assertGreater(result["position_absolute_percentile"], 50.0)
        self.assertNotEqual(result["position_absolute_percentile"], 0.0)

    def test_sector_pagination_fetches_100_plus_50_and_reports_complete(self):
        calls = []

        def fake(params):
            calls.append(dict(params))
            page = int(params["pn"])
            rows = _sector_rows(0, 100) if page == 1 else _sector_rows(100, 50)
            return {"data": {"total": 150, "diff": list(reversed(rows))}}

        with patch.object(data_fetcher, "_fetch_eastmoney_json", side_effect=fake):
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BK0150", return_diagnostics=True
            )

        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call["pz"] == "100" for call in calls))
        self.assertTrue(all(call["fid"] == "f12" for call in calls))
        self.assertTrue(all(call["po"] == "0" for call in calls))
        self.assertEqual(len(stocks), 150)
        self.assertEqual([row["code"] for row in stocks], sorted(row["code"] for row in stocks))
        self.assertEqual(diag["requested"], 150)
        self.assertEqual(diag["fetched"], 150)
        self.assertEqual(diag["unique"], 150)
        self.assertEqual(diag["pages"], 2)
        self.assertTrue(diag["complete"])
        self.assertEqual(diag["error"], "")

    def test_sector_pagination_stops_at_total_without_third_page(self):
        calls = []

        def fake(params):
            calls.append(dict(params))
            page = int(params["pn"])
            if page > 2:
                raise AssertionError("third page must not be requested")
            return {"data": {"total": 200, "diff": _sector_rows((page - 1) * 100, 100)}}

        with patch.object(data_fetcher, "_fetch_eastmoney_json", side_effect=fake):
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BK0200", return_diagnostics=True
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(stocks), 200)
        self.assertTrue(diag["complete"])
        self.assertEqual(diag["pages"], 2)

    def test_sector_pagination_rejects_total_above_bounded_capacity_on_first_page(self):
        with patch.object(
            data_fetcher,
            "_fetch_eastmoney_json",
            return_value={"data": {"total": 6001, "diff": _sector_rows(0, 100)}},
        ) as fetch:
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BKOVERSIZED", return_diagnostics=True
            )

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(stocks), 100)
        self.assertEqual(diag["requested"], 6001)
        self.assertEqual(diag["pages"], 1)
        self.assertFalse(diag["complete"])
        self.assertEqual(diag["error"], "total_exceeds_limit")

    def test_sector_pagination_absolute_page_guard_stops_before_extra_request(self):
        calls = []

        def fake(params):
            calls.append(dict(params))
            page = int(params["pn"])
            rows = _sector_rows(0, 100) if page == 1 else _sector_rows(99, 100)
            return {"data": {"total": 200, "diff": rows}}

        with patch.object(
            data_fetcher, "SECTOR_COMPONENT_MAX_PAGES", 2
        ), patch.object(
            data_fetcher, "_fetch_eastmoney_json", side_effect=fake
        ):
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BKPAGEGUARD", return_diagnostics=True
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual([call["pn"] for call in calls], ["1", "2"])
        self.assertEqual(len(stocks), 199)
        self.assertEqual(diag["unique"], 199)
        self.assertEqual(diag["pages"], 2)
        self.assertFalse(diag["complete"])
        self.assertEqual(diag["error"], "max_pages_exceeded")

    def test_sector_pagination_accepts_zero_total_as_complete_empty_sector(self):
        with patch.object(
            data_fetcher,
            "_fetch_eastmoney_json",
            return_value={"data": {"total": 0, "diff": []}},
        ) as fetch:
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BKEMPTY", return_diagnostics=True
            )

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(stocks, [])
        self.assertEqual(diag["requested"], 0)
        self.assertTrue(diag["complete"])
        self.assertEqual(diag["error"], "")

    def test_sector_pagination_stops_on_repeated_page_and_marks_incomplete(self):
        repeated = _sector_rows(0, 100)

        with patch.object(
            data_fetcher,
            "_fetch_eastmoney_json",
            return_value={"data": {"total": 150, "diff": repeated}},
        ) as fetch:
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BKREPEAT", return_diagnostics=True
            )

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(stocks), 100)
        self.assertEqual(diag["fetched"], 200)
        self.assertEqual(diag["unique"], 100)
        self.assertFalse(diag["complete"])
        self.assertEqual(diag["error"], "no_new_codes")

    def test_sector_pagination_preserves_partial_rows_when_page_two_fails(self):
        def fake(params):
            if int(params["pn"]) == 2:
                raise RuntimeError("page two unavailable")
            return {"data": {"total": 150, "diff": _sector_rows(0, 100)}}

        with patch.object(data_fetcher, "_fetch_eastmoney_json", side_effect=fake):
            stocks, diag = data_fetcher.fetch_sector_stocks(
                "BKFAIL", return_diagnostics=True
            )

        self.assertEqual(len(stocks), 100)
        self.assertEqual(diag["pages"], 1)
        self.assertEqual(diag["unique"], 100)
        self.assertFalse(diag["complete"])
        self.assertEqual(diag["error"], "request_failed:RuntimeError")
        self.assertNotIn("page two unavailable", diag["error"])

    def test_sector_pagination_structures_missing_total_short_and_empty_failures(self):
        cases = {
            "missing_total": [
                {"data": {"diff": _sector_rows(0, 50)}},
            ],
            "short_page_before_total": [
                {"data": {"total": 150, "diff": _sector_rows(0, 50)}},
            ],
            "empty_page_before_total": [
                {"data": {"total": 150, "diff": _sector_rows(0, 100)}},
                {"data": {"total": 150, "diff": []}},
            ],
        }

        for expected_error, responses in cases.items():
            with self.subTest(expected_error=expected_error), patch.object(
                data_fetcher,
                "_fetch_eastmoney_json",
                side_effect=responses,
            ):
                stocks, diag = data_fetcher.fetch_sector_stocks(
                    f"BK-{expected_error}", return_diagnostics=True
                )

            self.assertTrue(stocks)
            self.assertFalse(diag["complete"])
            self.assertEqual(diag["error"], expected_error)
            for key in (
                "sector_code", "page_size", "requested", "fetched",
                "unique", "pages", "complete", "error",
            ):
                self.assertIn(key, diag)

    def test_run_main_uses_beijing_date_for_aware_generated_at(self):
        captured = []

        class StopAfterDateCapture(RuntimeError):
            pass

        def stop_collect(*args, **kwargs):
            captured.append(kwargs.get("required_date"))
            raise StopAfterDateCapture

        generated_at = datetime(2026, 6, 30, 16, 30, tzinfo=timezone.utc)
        with patch.object(run, "collect_daily_data", side_effect=stop_collect):
            with self.assertRaises(StopAfterDateCapture):
                run.main(debug=False, preview=False, generated_at=generated_at)

        self.assertEqual(captured, ["2026-07-01"])

    def test_closed_run_with_same_day_cache_fetches_full_remote_window(self):
        end = date(2026, 6, 30)
        dates = [(end - timedelta(days=99 - i)).isoformat() for i in range(100)]
        cached_records = [
            {"date": d, "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100}
            for d in dates
        ]
        remote_calls = []

        def remote(_code, count=100):
            remote_calls.append(count)
            return _kline(dates[-count:], [20.0] * count)

        with tempfile.TemporaryDirectory() as tmp, patch(
            "chanlun.kline_cache.KLINE_CACHE_DIR", tmp
        ), patch.object(data_fetcher, "KLINE_REPOSITORY_ENABLED", False):
            write_cached_records("day", "600000", cached_records, "intraday", keep_trading_days=120)
            with patch.object(data_fetcher, "_fetch_daily_kline_remote", side_effect=remote):
                rows = data_fetcher.batch_fetch_daily_klines(
                    [{"code": "600000", "name": "测试股"}],
                    required_date="2026-06-30",
                    force_refresh=True,
                )

        self.assertEqual(remote_calls, [100])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data_status"]["source"], "tencent")
        self.assertEqual(float(rows[0]["klines"]["closes"][-1]), 20.0)

    def test_closed_run_remote_failure_marks_cache_untrusted_and_not_official(self):
        end = date(2026, 6, 30)
        dates = [(end - timedelta(days=99 - i)).isoformat() for i in range(100)]
        cached_records = [
            {"date": d, "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100}
            for d in dates
        ]
        closed = datetime(2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8)))

        with tempfile.TemporaryDirectory() as tmp, patch(
            "chanlun.kline_cache.KLINE_CACHE_DIR", tmp
        ), patch.object(data_fetcher, "KLINE_REPOSITORY_ENABLED", False):
            write_cached_records("day", "600000", cached_records, "intraday", keep_trading_days=120)
            with patch.object(data_fetcher, "fetch_sector_flow", return_value=[
                {"code": "BK0001", "name": "AI", "change_pct": 2.1, "flow": 10_000_000}
            ]), patch.object(
                data_fetcher,
                "fetch_sector_stocks",
                side_effect=_complete_sector_fetch(
                    {"BK0001": [{"code": "600000", "name": "测试股"}]}
                ),
            ), patch.object(
                data_fetcher, "_fetch_daily_kline_remote", return_value=None
            ), patch.object(
                data_fetcher,
                "fetch_shanghai_index",
                return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
            ):
                result = data_fetcher.collect_daily_data(
                    required_date="2026-06-30",
                    generated_at=closed,
                )

        self.assertEqual(result["stocks"][0]["data_status"]["source"], "kline_cache")
        self.assertFalse(result["data_quality"]["sources_trusted"])
        self.assertFalse(result["data_quality"]["is_official"])

    def test_closed_producer_rejects_untrusted_source_and_date_mismatch(self):
        closed = datetime(2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8)))
        base_row = {
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

        for field, value in (("source", "unknown"), ("latest_date", "2026-06-29")):
            with self.subTest(field=field):
                row = dict(base_row)
                row["data_status"] = dict(base_row["data_status"])
                row["data_status"][field] = value
                with patch.object(data_fetcher, "fetch_sector_flow", return_value=[
                    {"code": "BK0001", "name": "AI", "change_pct": 2.1, "flow": 10_000_000}
                ]), patch.object(
                    data_fetcher,
                    "fetch_sector_stocks",
                    side_effect=_complete_sector_fetch(
                        {"BK0001": [{"code": "600000", "name": "测试股"}]}
                    ),
                ), patch.object(
                    data_fetcher, "batch_fetch_daily_klines", return_value=[row]
                ), patch.object(
                    data_fetcher,
                    "fetch_shanghai_index",
                    return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
                ):
                    result = data_fetcher.collect_daily_data(
                        required_date="2026-06-30",
                        generated_at=closed,
                    )

                self.assertFalse(result["data_quality"]["is_official"])

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
            data_fetcher,
            "fetch_sector_stocks",
            side_effect=_complete_sector_fetch(
                {"BK0001": [{"code": "600000", "name": "测试股"}]}
            ),
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

    def test_collect_daily_data_closed_run_uses_db_first_and_can_be_official(self):
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
            data_fetcher,
            "fetch_sector_stocks",
            side_effect=_complete_sector_fetch(
                {"BK0001": [{"code": "600000", "name": "测试股"}]}
            ),
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

        self.assertEqual(calls, [False])
        self.assertEqual(result["data_quality"]["bar_state"], "closed")
        self.assertTrue(result["data_quality"]["sources_trusted"])
        self.assertTrue(result["data_quality"]["is_official"])

    def test_batch_fetch_daily_klines_propagates_close_refresh(self):
        kline = _kline(["2026-06-30"] * 60, [10.0] * 60)
        with patch.object(
            data_fetcher, "KLINE_REPOSITORY_ENABLED", False
        ), patch.object(data_fetcher, "fetch_daily_kline", return_value=kline) as fetch:
            data_fetcher.batch_fetch_daily_klines(
                [{"code": "600000", "name": "测试股"}],
                required_date="2026-06-30",
                force_refresh=True,
            )

        fetch.assert_called_once_with("600000", force_refresh=True)

    def test_batch_fetch_daily_klines_missing_only_overrides_force_refresh(self):
        kline = _kline(["2026-06-30"] * 60, [10.0] * 60)
        with patch.object(
            data_fetcher, "KLINE_REPOSITORY_ENABLED", False
        ), patch.object(data_fetcher, "fetch_daily_kline", return_value=kline) as fetch:
            data_fetcher.batch_fetch_daily_klines(
                [{"code": "600000", "name": "测试股"}],
                required_date="2026-06-30",
                force_refresh=True,
                missing_only=True,
            )

        fetch.assert_called_once_with("600000", force_refresh=False)

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
                "total": 1,
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
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=_complete_sector_fetch(sector_stocks)), \
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

    def test_collect_daily_data_records_sector_diagnostics_and_fails_closed(self):
        closed = datetime(2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8)))
        sector_rows = [{"code": "600000", "name": "测试股"}]

        def incomplete_sector_fetch(code, *, return_diagnostics=False):
            diag = {
                "sector_code": code,
                "page_size": 100,
                "requested": 150,
                "fetched": 100,
                "unique": 1,
                "pages": 1,
                "complete": False,
                "error": "request_failed:RuntimeError",
            }
            return (sector_rows, diag) if return_diagnostics else sector_rows

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
            data_fetcher, "fetch_sector_stocks", side_effect=incomplete_sector_fetch
        ), patch.object(
            data_fetcher, "batch_fetch_daily_klines", return_value=[stock_row]
        ), patch.object(
            data_fetcher,
            "fetch_shanghai_index",
            return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
        ):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30",
                generated_at=closed,
            )

        quality = result["data_quality"]
        self.assertTrue(quality["stock_pool_incomplete"])
        self.assertFalse(quality["is_official"])
        self.assertEqual(len(quality["sector_component_diagnostics"]), 1)
        self.assertEqual(
            quality["sector_component_diagnostics"][0]["error"],
            "request_failed:RuntimeError",
        )

    def test_collect_daily_data_marks_unrequested_sectors_after_five_incomplete_empty_failures(self):
        sectors = [
            {"code": f"BK{index:04d}", "name": f"板块{index}", "flow": 1}
            for index in range(1, 8)
        ]
        calls = []

        def incomplete_empty(code, *, return_diagnostics=False):
            calls.append(code)
            diag = {
                "sector_code": code,
                "page_size": 100,
                "requested": 100,
                "fetched": 0,
                "unique": 0,
                "pages": 1,
                "complete": False,
                "error": "empty_page_before_total",
            }
            return ([], diag) if return_diagnostics else []

        with tempfile.TemporaryDirectory() as tmp, patch(
            "config.KLINE_CACHE_DIR", tmp
        ), patch.object(
            data_fetcher, "fetch_sector_flow", return_value=sectors
        ), patch.object(
            data_fetcher, "fetch_sector_stocks", side_effect=incomplete_empty
        ), patch.object(
            data_fetcher, "batch_fetch_daily_klines", return_value=[]
        ), patch.object(
            data_fetcher,
            "fetch_shanghai_index",
            return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
        ):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30",
                generated_at=datetime(
                    2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8))
                ),
            )

        quality = result["data_quality"]
        diagnostics = quality["sector_component_diagnostics"]
        self.assertEqual(calls, [sector["code"] for sector in sectors[:5]])
        self.assertEqual(len(diagnostics), 7)
        self.assertTrue(quality["stock_pool_incomplete"])
        self.assertFalse(quality["is_official"])
        self.assertEqual(
            [diag["error"] for diag in diagnostics[5:]],
            ["not_requested_after_consecutive_failures"] * 2,
        )
        self.assertTrue(all(not diag["complete"] for diag in diagnostics[5:]))
        self.assertTrue(
            any("未请求剩余2个板块" in warning for warning in quality["warnings"]),
            quality["warnings"],
        )

    def test_collect_daily_data_does_not_count_complete_empty_sector_as_failure(self):
        sectors = [
            {"code": f"BK{index:04d}", "name": f"板块{index}", "flow": 1}
            for index in range(1, 7)
        ]
        calls = []
        final_stock = {"code": "600000", "name": "测试股"}

        def complete_fetch(code, *, return_diagnostics=False):
            calls.append(code)
            rows = [final_stock] if code == sectors[-1]["code"] else []
            diag = {
                "sector_code": code,
                "page_size": 100,
                "requested": len(rows),
                "fetched": len(rows),
                "unique": len(rows),
                "pages": 1,
                "complete": True,
                "error": "",
            }
            return (rows, diag) if return_diagnostics else rows

        stock_row = {
            **final_stock,
            "klines": _kline(["2026-06-29", "2026-06-30"], [10.0, 11.0]),
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-06-30",
                "source": "tencent",
                "bars": 2,
                "stale": False,
            },
        }
        closed = datetime(2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8)))

        with patch.object(
            data_fetcher, "fetch_sector_flow", return_value=sectors
        ), patch.object(
            data_fetcher, "fetch_sector_stocks", side_effect=complete_fetch
        ), patch.object(
            data_fetcher, "batch_fetch_daily_klines", return_value=[stock_row]
        ), patch.object(
            data_fetcher,
            "fetch_shanghai_index",
            return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
        ):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30", generated_at=closed
            )

        quality = result["data_quality"]
        self.assertEqual(calls, [sector["code"] for sector in sectors])
        self.assertEqual(len(quality["sector_component_diagnostics"]), 6)
        self.assertFalse(quality["stock_pool_incomplete"])
        self.assertTrue(quality["is_official"])

    def test_collect_daily_data_static_sector_fallback_sets_fallback_used(self):
        stock_calls = [{"code": "600000", "name": "测试股"}]

        fake_sector_stocks = _complete_sector_fetch({"BK0480": stock_calls})

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
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=_complete_sector_fetch(
                 {"BK0001": [{"code": "600000", "name": "测试股"}]}
             )), \
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
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=_complete_sector_fetch(
                 {"BK0001": [{"code": "600000", "name": "测试股"}]}
             )), \
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

    def test_collect_daily_data_records_missing_only_refresh_mode(self):
        calls = []

        def fake_batch(
            stocks,
            required_date=None,
            allow_stale=False,
            max_workers=10,
            force_refresh=False,
            missing_only=False,
        ):
            calls.append(missing_only)
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
            {"code": "BK0001", "name": "测试板块", "flow_str": "1亿"}
        ]), patch.object(
            data_fetcher,
            "fetch_sector_stocks",
            side_effect=_complete_sector_fetch(
                {"BK0001": [{"code": "600000", "name": "测试股"}]}
            ),
        ), patch.object(
            data_fetcher, "batch_fetch_daily_klines", side_effect=fake_batch
        ), patch.object(
            data_fetcher,
            "fetch_shanghai_index",
            return_value=_kline(["2026-06-29", "2026-06-30"], [3.0, 3.0]),
        ):
            result = data_fetcher.collect_daily_data(
                required_date="2026-06-30",
                generated_at=datetime(
                    2026, 6, 30, 15, 5, tzinfo=timezone(timedelta(hours=8))
                ),
                missing_only=True,
            )

        self.assertEqual(calls, [True])
        self.assertEqual(result["data_quality"]["daily_refresh_mode"], "missing_only")


class TestDailyRunScriptGuard(unittest.TestCase):

    def test_validator_failure_stops_script_before_any_git_command(self):
        source_script = Path("daily_run.sh").read_text(encoding="utf-8")
        fixed_timestamp = datetime(
            2026, 6, 30, 12, 0, tzinfo=timezone(timedelta(hours=8))
        ).timestamp()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily_run.sh").write_text(source_script, encoding="utf-8")
            (root / ".zshrc").write_text("", encoding="utf-8")
            (root / "docs" / "data").mkdir(parents=True)
            (root / "docs" / "data" / "2026-06-30.json").write_text("{}", encoding="utf-8")
            (root / "docs" / "index.html").write_text("ok", encoding="utf-8")
            os.utime(root / "docs" / "data" / "2026-06-30.json", (fixed_timestamp, fixed_timestamp))
            os.utime(root / "docs" / "index.html", (fixed_timestamp, fixed_timestamp))

            (root / "scripts").mkdir()
            (root / "scripts" / "validate_today_report.py").write_text(
                "import os\n"
                "with open(os.environ['VALIDATOR_LOG'], 'a', encoding='utf-8') as f:\n"
                "    f.write('called\\n')\n"
                "raise SystemExit(9)\n",
                encoding="utf-8",
            )
            (root / "run.py").write_text("def main(*args, **kwargs):\n    return None\n", encoding="utf-8")
            (root / "chanlun").mkdir()
            (root / "chanlun" / "__init__.py").write_text("", encoding="utf-8")
            session_module = "class _Session:\n    trust_env = True\nSESSION = _Session()\n"
            (root / "chanlun" / "data_fetcher.py").write_text(session_module, encoding="utf-8")
            (root / "chanlun" / "market_news.py").write_text(session_module, encoding="utf-8")

            fake_bin = root / "bin"
            fake_bin.mkdir()
            git_log = root / "git.log"
            validator_log = root / "validator.log"
            fake_git = fake_bin / "git"
            fake_git.write_text(
                '#!/bin/zsh\nprint -r -- "$@" >> "$GIT_LOG"\nexit 0\n',
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            fake_date = fake_bin / "date"
            fake_date.write_text(
                '#!/bin/zsh\nif [[ "$1" == "+%Y-%m-%d" ]]; then print "2026-06-30"; '
                'else print "2026-06-30 15:05:00"; fi\n',
                encoding="utf-8",
            )
            fake_date.chmod(0o755)

            env = dict(os.environ)
            env.update({
                "HOME": str(root),
                "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                "GIT_LOG": str(git_log),
                "VALIDATOR_LOG": str(validator_log),
            })
            completed = subprocess.run(
                ["/bin/zsh", str(root / "daily_run.sh")],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            git_calls = git_log.read_text(encoding="utf-8") if git_log.exists() else ""
            validator_calls = validator_log.read_text(encoding="utf-8").splitlines()

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(validator_calls, ["called", "called"])
        self.assertEqual(git_calls, "", completed.stdout + completed.stderr)

    def test_daily_run_does_not_skip_existing_output_after_recheck_time(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("python3 scripts/validate_today_report.py", script)
        self.assertNotIn("今日产物已存在，跳过补跑", script)

    def test_daily_run_marks_existing_invalid_output_as_missing_only_retry(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertIn("RETRY_MISSING_ONLY=1", script)
        self.assertIn("CHANLUN_DAILY_RETRY_MISSING_ONLY", script)
        self.assertIn("缺失数据增量补跑", script)

    def test_daily_run_git_add_scope_is_today_and_assets_only(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            script = f.read()

        self.assertNotIn("docs/20*/", script)
        self.assertIn('"docs/${TODAY}/index.html"', script)
        self.assertIn('"docs/data/${TODAY}.json"', script)
        self.assertIn('"docs/data/comparison-index.json"', script)
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

    def test_validate_report_contract_reports_workspace_stale_row_once(self):
        report = _official_empty_report()
        report["workspace"]["views"]["highlights"] = [{
            "code": "600000",
            "change_pct": 1.0,
            "current_price": 10.0,
            "data_status": {"daily": "stale_cache"},
        }]

        errors = validate_report_contract(report)

        stale_errors = [
            error for error in errors
            if "highlights row has stale daily cache" in error
        ]
        self.assertEqual(stale_errors, [
            "highlights row has stale daily cache in official report: code=600000"
        ])

    def test_validate_report_contract_rejects_decision_action_conflicts(self):
        executable_actions = ("可上车", "等回踩", "慎追")
        for decision_code in ("reject", "observe"):
            for action in executable_actions:
                with self.subTest(decision_code=decision_code, action=action):
                    report = _official_empty_report()
                    report["workspace"]["views"]["main"] = [{
                        "code": "600000",
                        "change_pct": 1.0,
                        "current_price": 10.0,
                        "action": action,
                        "decision_engine_v1": {"decision_code": decision_code},
                        "data_status": {"daily": "verified"},
                    }]

                    errors = validate_report_contract(report)

                    self.assertTrue(
                        any("decision/action conflict" in error for error in errors),
                        errors,
                    )

    def test_validate_report_contract_allows_legal_or_legacy_decision_actions(self):
        cases = (
            ("recommend", "可上车"),
            ("observe", "仅观察"),
            ("reject", "仅观察"),
            (None, "可上车"),
        )
        for decision_code, action in cases:
            with self.subTest(decision_code=decision_code, action=action):
                report = _official_empty_report()
                row = {
                    "code": "600000",
                    "change_pct": 1.0,
                    "current_price": 10.0,
                    "action": action,
                    "data_status": {"daily": "verified"},
                }
                if decision_code is not None:
                    row["decision_engine_v1"] = {"decision_code": decision_code}
                report["workspace"]["views"]["main"] = [row]

                errors = validate_report_contract(report)

                self.assertFalse(
                    any("decision/action conflict" in error for error in errors),
                    errors,
                )

    def test_validate_official_requires_timezone_aware_post_close_timestamps(self):
        cases = (
            ("as_of", "2026-06-30T14:35:00+08:00", "as_of must be at or after 15:00 Asia/Shanghai"),
            ("as_of", "2026-06-30T15:05:00", "as_of must include timezone"),
            ("generated_at", "2026-06-30T15:05:00", "generated_at must include timezone"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                report = _official_empty_report()
                report["data_quality"][field] = value
                errors = validate_report_contract(report)
                self.assertTrue(any(expected in err for err in errors), errors)

    def test_validate_official_normalizes_aware_as_of_to_beijing_time(self):
        report = _official_empty_report()
        report["data_quality"]["generated_at"] = "2026-06-30T07:05:00+00:00"
        report["data_quality"]["as_of"] = "2026-06-30T07:05:00+00:00"

        self.assertEqual(validate_report_contract(report), [])

    def test_validate_report_contract_rejects_untrusted_source_and_as_of_mismatch(self):
        for field, value, expected in (
            ("sources_trusted", False, "sources_trusted == True"),
            ("report_date", "2026-06-29", "report date consistency"),
            ("as_of", "2026-06-29T15:05:00+08:00", "as_of date == report_date"),
        ):
            with self.subTest(field=field):
                report = _official_empty_report()
                report["data_quality"][field] = value
                errors = validate_report_contract(report)
                self.assertTrue(any(expected in err for err in errors), errors)

    def test_validate_report_contract_rejects_official_incomplete_or_unknown_stock_pool(self):
        for missing, value in ((False, True), (True, None)):
            with self.subTest(missing=missing):
                report = _official_empty_report()
                if missing:
                    report["data_quality"].pop("stock_pool_incomplete")
                else:
                    report["data_quality"]["stock_pool_incomplete"] = value

                errors = validate_report_contract(report)

                self.assertTrue(
                    any("stock_pool_incomplete == False" in err for err in errors),
                    errors,
                )

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

    def test_validate_report_contract_requires_literal_true_for_official_publish(self):
        for invalid_value in ("false", "true", 1):
            with self.subTest(invalid_value=invalid_value):
                report = _official_empty_report()
                report["data_quality"]["is_official"] = invalid_value

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any("requires data_quality.is_official == True" in err for err in errors),
                    errors,
                )

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
                {
                    "code": "600003",
                    "change_pct": 2.0,
                    "decision_engine_v1": {"decision_code": "recommend"},
                },
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
        self.assertIn("main view missing while recommend decisions exist", errors)
        self.assertIn("baseline view missing while picks_pure is non-empty", errors)

    def test_validate_report_contract_allows_empty_main_when_all_are_observe(self):
        report = {
            "picks_fusion": [{
                "code": "600003",
                "change_pct": 2.0,
                "decision_engine_v1": {"decision_code": "observe"},
            }],
            "picks_pure": [],
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

        self.assertEqual(validate_report_contract(report), [])

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
