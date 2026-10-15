"""Offline contracts for dated icepoint evidence; no live gateway calls."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from chanlun.market_icepoint_sources import (
    IcepointSourceError,
    build_breadth_evidence,
    collect_missing_icepoint_evidence,
    parse_turnover_response,
    turnover_query,
    breadth_query,
    suspended_query,
)


CN = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 14, 16, 0, tzinfo=CN)
DATES = ["2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14"]
AMOUNTS = [1450049400000, 1694272300000, 1916677000000,
           1550743500000, 1688900400000, 1426389200000]


def _response(query, rows, *, total=None):
    count = len(rows) if total is None else total
    return {"success": True, "query": query, "code_count": count,
            "returned_count": len(rows), "page": "1", "limit": "100",
            "has_more": False, "datas": rows}


def _native(payload):
    return {key: payload[key] for key in ("code_count", "datas")}


def _turnover():
    row = {"指数代码": "883957.TI", "指数简称": "同花顺全A(沪深京)",
           "最新价": "9999", "最新成交额": 999999999999999}
    row.update({"成交额[{}]".format(day.replace("-", "")): value
                for day, value in zip(DATES, AMOUNTS)})
    return _response(turnover_query(DATES), [row])


def _breadth():
    return _response(breadth_query(DATES[-1]), [{"指数代码": "883957.TI",
        "指数简称": "同花顺全A(沪深京)", "上涨家数[20261014]": 1,
        "下跌家数[20261014]": 1, "平盘家数[20261014]": 0,
        "最新涨跌幅:前复权": 3.2}])


def _suspended():
    return _response(suspended_query(DATES[-1]), [{"股票代码": "600825.SH",
        "股票简称": "新华传媒", "停牌[20261014]": True, "最新涨跌幅": 0.0}])


def _quote(code, status, change):
    return {"asset_type": "stock", "exchange": "SH", "code": code,
            "quote_status": status, "quote_source": "sina", "price_basis": "raw",
            "quote_asof": "2026-10-14T15:20:09+08:00", "current_price": 10.0,
            "change_pct": change, "open": 9.9, "high": 10.1, "low": 9.8,
            "prev_close": 9.75, "volume": 10000.0, "amount": 9990000.0,
            "volume_unit": "hands", "amount_unit": "CNY"}


def _quote_cache():
    return {"schema_version": 1, "requested": 3, "universe_source": "sina_hs_a",
            "fetched_at": "2026-10-14T15:20:09+08:00",
            "diagnostics": {"complete": True, "requested": 3, "fetched": 3,
                            "unique": 3, "universe_source": "sina_hs_a"},
            "rows": [_quote("600293", "valid", 2.0),
                     _quote("600824", "valid", -2.0),
                     _quote("600825", "unavailable", None)]}


class IcepointSourcesTests(unittest.TestCase):
    def test_turnover_uses_only_six_explicit_dated_yuan_columns(self):
        result = parse_turnover_response(_turnover(), DATES, NOW)
        self.assertEqual(result["current"], AMOUNTS[-1])
        self.assertEqual(result["prior"], AMOUNTS[:-1])
        self.assertEqual(result["prior_dates"], DATES[:-1])
        self.assertEqual(result["source_code"], "883957.TI")
        self.assertEqual(result["evidence_contract"], "provider_aggregate_v1")
        self.assertEqual(result["amount_unit"], "CNY")
        self.assertNotIn("coverage_counts", result)
        self.assertTrue(result["complete"])

    def test_turnover_rejects_wrong_identity_missing_date_or_truncated_page(self):
        for change in ({"指数代码": "000001.SH"},
                       {"指数简称": "上证指数"},
                       {"成交额[20261014]": None},
                       {"成交额[20261014]": float("nan")},
                       {"成交额[20261014]": "14263.892亿元"},
                       {"成交额[20261014]": 14263.892}):
            with self.subTest(change=change):
                payload = _turnover()
                payload["datas"][0].update(change)
                with self.assertRaises(IcepointSourceError):
                    parse_turnover_response(payload, DATES, NOW)
        payload = _turnover()
        payload["code_count"] = 2
        with self.assertRaises(IcepointSourceError):
            parse_turnover_response(payload, DATES, NOW)
        wrong_dates = DATES.copy()
        wrong_dates[1] = "2026-10-07"  # Exchange holiday, not one of the six sessions.
        with self.assertRaises(IcepointSourceError):
            parse_turnover_response(_turnover(), wrong_dates, NOW)
        payload = _turnover()
        payload["datas"][0].pop("成交额[20261008]")
        with self.assertRaises(IcepointSourceError):
            parse_turnover_response(payload, DATES, NOW)

    def test_breadth_requires_exact_quote_and_suspension_partition(self):
        result = build_breadth_evidence(_quote_cache(), _breadth(), _suspended(), DATES[-1], NOW)
        self.assertEqual((result["advance_count"], result["decline_count"],
                          result["flat_count"]), (1, 1, 0))
        self.assertEqual((result["valid_count"], result["denominator"],
                          result["quote_snapshot_count"], result["suspended_count"],
                          result["unknown_count"]), (2, 2, 3, 1, 0))
        self.assertEqual(result["source"], "quote_snapshot+wencai")
        self.assertTrue(result["complete"])

    def test_breadth_rejects_wrong_suspension_overlap_or_unusable_quote(self):
        bad_suspended = _suspended()
        bad_suspended["datas"][0]["股票代码"] = "600826.SH"
        bad_overlap = _suspended()
        bad_overlap["datas"][0]["股票代码"] = "600293.SH"
        bad_quote = _quote_cache()
        bad_quote["rows"][0]["price_basis"] = "qfq"
        bad_count = _breadth()
        bad_count["datas"][0]["上涨家数[20261014]"] = 2
        for cache, breadth, suspended in (
                (_quote_cache(), _breadth(), bad_suspended),
                (_quote_cache(), _breadth(), bad_overlap),
                (bad_quote, _breadth(), _suspended()),
                (_quote_cache(), bad_count, _suspended())):
            with self.assertRaises(IcepointSourceError):
                build_breadth_evidence(cache, breadth, suspended, DATES[-1], NOW)

    def test_collection_is_three_requests_max_and_reuses_dated_cache(self):
        payloads = {_turnover()["query"]: _turnover(),
                    _breadth()["query"]: _breadth(),
                    _suspended()["query"]: _suspended()}
        calls = []

        def transport(query, limit, headers, timeout):
            calls.append(query)
            self.assertEqual(headers["X-Claw-Skill-Id"], "hithink-market-query")
            self.assertEqual(len(headers["X-Claw-Trace-Id"]), 64)
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertLessEqual(timeout, 10)
            return payloads[query]

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"IWENCAI_API_KEY": "test-key"}):
            quote_path = Path(directory) / "quotes.json"
            quote_path.write_text(json.dumps(_quote_cache()))
            result = collect_missing_icepoint_evidence(
                DATES[-1], NOW, trade_dates=DATES, quote_cache_path=quote_path,
                cache_dir=Path(directory) / "icepoint", need_turnover=True,
                need_breadth=True, transport=transport, clock=lambda: NOW)
            self.assertEqual(len(calls), 3)
            self.assertEqual(result["turnover"]["current"], AMOUNTS[-1])
            self.assertEqual(result["breadth"]["suspended_count"], 1)
            self.assertNotIn("test-key", str(result))
            for record in (Path(directory) / "icepoint").glob("*.json"):
                self.assertNotIn("test-key", record.read_text())
            calls.clear()
            again = collect_missing_icepoint_evidence(
                DATES[-1], NOW + timedelta(minutes=2), trade_dates=DATES,
                quote_cache_path=quote_path, cache_dir=Path(directory) / "icepoint",
                need_turnover=True, need_breadth=True, transport=transport, clock=lambda: NOW)
            self.assertEqual(calls, [])
            self.assertEqual(again["turnover"]["current"], AMOUNTS[-1])
            turnover_cache = Path(directory) / "icepoint" / "icepoint-2026-10-14-turnover.json"
            saved = json.loads(turnover_cache.read_text())
            saved["report_date"] = "2026-10-13"
            turnover_cache.write_text(json.dumps(saved))
            refreshed = collect_missing_icepoint_evidence(
                DATES[-1], NOW + timedelta(minutes=2), trade_dates=DATES,
                quote_cache_path=quote_path, cache_dir=Path(directory) / "icepoint",
                need_turnover=True, need_breadth=True, transport=transport, clock=lambda: NOW)
            self.assertEqual(calls, [turnover_query(DATES)])
            self.assertEqual(refreshed["turnover"]["current"], AMOUNTS[-1])

    def test_natural_run_does_not_fetch_prior_day_or_preclose(self):
        with tempfile.TemporaryDirectory() as directory:
            def forbidden(*_args, **_kwargs):
                self.fail("must not call remote gateway")
            for report_date, now in (("2026-10-13", NOW),
                                     ("2026-10-14", datetime(2026, 10, 14, 14, 30, tzinfo=CN))):
                result = collect_missing_icepoint_evidence(
                    report_date, now, trade_dates=DATES, quote_cache_path="/missing",
                    cache_dir=directory, need_turnover=True, need_breadth=True,
                    transport=forbidden)
                self.assertIsNone(result["turnover"])
                self.assertIsNone(result["breadth"])

    def test_historical_repair_is_explicit_and_keeps_actual_retrieval_time(self):
        next_day = NOW + timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"IWENCAI_API_KEY": "test-key"}):
            result = collect_missing_icepoint_evidence(
                DATES[-1], next_day, trade_dates=DATES,
                quote_cache_path="/missing", cache_dir=directory,
                need_turnover=True, need_breadth=False, allow_historical=True,
                transport=lambda *_: _turnover(), clock=lambda: next_day)
            self.assertTrue(result["turnover"]["complete"])
            self.assertEqual(result["turnover"]["date"], "2026-10-14")
            self.assertEqual(result["turnover"]["retrieved_at"], next_day.isoformat())

    def test_turnover_failure_does_not_hide_independently_verified_breadth(self):
        turnover = _turnover()
        turnover["datas"][0]["指数代码"] = "000001.SH"
        payloads = {turnover["query"]: turnover, _breadth()["query"]: _breadth(),
                    _suspended()["query"]: _suspended()}
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"IWENCAI_API_KEY": "test-key"}):
            quote_path = Path(directory) / "quotes.json"
            quote_path.write_text(json.dumps(_quote_cache()))
            result = collect_missing_icepoint_evidence(
                DATES[-1], NOW, trade_dates=DATES, quote_cache_path=quote_path,
                cache_dir=Path(directory) / "icepoint", need_turnover=True,
                need_breadth=True, transport=lambda query, *_: payloads[query],
                clock=lambda: NOW)
            self.assertIsNone(result["turnover"])
            self.assertEqual(result["breadth"]["valid_count"], 2)
            self.assertTrue(result["errors"])

    def test_raw_gateway_shape_works_without_cli_synthetic_fields(self):
        payloads = {_turnover()["query"]: _native(_turnover()),
                    _breadth()["query"]: _native(_breadth()),
                    _suspended()["query"]: _native(_suspended())}
        calls = []
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"IWENCAI_API_KEY": "test-key"}):
            quote_path = Path(directory) / "quotes.json"
            quote_path.write_text(json.dumps(_quote_cache()))

            def transport(query, *_):
                calls.append(query)
                return payloads[query]

            result = collect_missing_icepoint_evidence(
                DATES[-1], NOW, trade_dates=DATES, quote_cache_path=quote_path,
                cache_dir=Path(directory) / "icepoint", need_turnover=True,
                need_breadth=True, transport=transport, clock=lambda: NOW)
            self.assertEqual(len(calls), 3)
            self.assertEqual(result["turnover"]["current"], AMOUNTS[-1])
            self.assertEqual(result["breadth"]["valid_count"], 2)
            record = json.loads((Path(directory) / "icepoint" /
                                 "icepoint-2026-10-14-turnover.json").read_text())
            self.assertEqual(record["payload"], payloads[_turnover()["query"]])
            self.assertNotIn("success", record["payload"])

    def test_breadth_can_recover_when_six_day_turnover_window_is_missing(self):
        payloads = {_breadth()["query"]: _native(_breadth()),
                    _suspended()["query"]: _native(_suspended())}
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"IWENCAI_API_KEY": "test-key"}):
            quote_path = Path(directory) / "quotes.json"
            quote_path.write_text(json.dumps(_quote_cache()))
            result = collect_missing_icepoint_evidence(
                DATES[-1], NOW, trade_dates=[], quote_cache_path=quote_path,
                cache_dir=Path(directory) / "icepoint", need_turnover=False,
                need_breadth=True, transport=lambda query, *_: payloads[query],
                clock=lambda: NOW)
            self.assertIsNone(result["turnover"])
            self.assertEqual(result["breadth"]["valid_count"], 2)

    def test_missing_key_fails_closed_without_transport_call(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"IWENCAI_API_KEY": ""}):
            result = collect_missing_icepoint_evidence(
                DATES[-1], NOW, trade_dates=DATES,
                quote_cache_path="/missing", cache_dir=directory,
                need_turnover=True, need_breadth=False,
                transport=lambda *_: self.fail("transport called"), clock=lambda: NOW)
            self.assertIsNone(result["turnover"])
            self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
