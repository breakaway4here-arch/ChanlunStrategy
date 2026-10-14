"""Bounded Eastmoney sector relay contracts, independent of live requests."""

import unittest
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from chanlun.sector_sources import (
    SectorSourceError,
    SectorRelaySession,
    parse_component_relay,
    parse_fund_relay,
    verified_quote_snapshot,
)
from chanlun import data_fetcher


CN = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 14, 16, 45, tzinfo=CN)
STAMP = 1791963571  # 2026-10-14 15:39:31 Asia/Shanghai


def _payload(rows):
    return {"rc": 0, "data": {"total": len(rows), "diff": rows}}


def _fund_payloads():
    identity = [
        {"f12": "BK0486", "f13": 90, "f14": "传媒"},
        {"f12": "BK1340", "f13": 90, "f14": "印制电路板"},
        {"f12": "BK0459", "f13": 90, "f14": "元件"},
    ]
    return {
        "f62": _payload([dict(row, f62=flow) for row, flow in zip(identity, (300, 200, -100))]),
        "f124": _payload([dict(row, f124=STAMP) for row in identity]),
        "f3": _payload([dict(row, f3=pct) for row, pct in zip(identity, (165, 63, -125))]),
    }


def _quote(code, exchange, *, status="valid"):
    return {
        "asset_type": "stock", "exchange": exchange, "code": code,
        "quote_status": status, "quote_source": "sina",
        "price_basis": "raw",
        "quote_asof": "2026-10-14T15:20:09+08:00",
        "current_price": 10.0, "change_pct": 2.5,
        "open": 9.9, "high": 10.1, "low": 9.8, "prev_close": 9.75,
        "volume": 10000.0, "amount": 9990000.0,
        "volume_unit": "hands", "amount_unit": "CNY",
    }


class SectorRelayParsingTests(unittest.TestCase):
    def test_fund_relay_joins_complete_identity_sets_and_scales_pct(self):
        rows = parse_fund_relay(_fund_payloads(), "2026-10-14", NOW)
        self.assertEqual([row["code"] for row in rows], ["BK0486", "BK1340", "BK0459"])
        self.assertEqual([row["flow"] for row in rows], [300, 200, -100])
        self.assertEqual([row["change_pct"] for row in rows], [1.65, 0.63, -1.25])
        self.assertTrue(all(row["board_quote_as_of"].startswith("2026-10-14T15:39:31") for row in rows))
        self.assertTrue(all(row["flow_retrieved_at"] == NOW.isoformat() for row in rows))

    def test_fund_relay_rejects_missing_duplicate_future_or_wrong_day_rows(self):
        cases = {}
        missing = _fund_payloads()
        missing["f124"]["data"]["diff"].pop()
        cases["missing_page_row"] = missing
        duplicate = _fund_payloads()
        duplicate["f62"]["data"]["diff"][1]["f12"] = "BK0486"
        cases["duplicate_identity"] = duplicate
        wrong_day = _fund_payloads()
        wrong_day["f124"]["data"]["diff"][0]["f124"] = STAMP - 86400
        cases["wrong_day"] = wrong_day
        future = _fund_payloads()
        future["f124"]["data"]["diff"][0]["f124"] = int(NOW.timestamp()) + 120
        cases["future"] = future
        not_finite = _fund_payloads()
        not_finite["f62"]["data"]["diff"][0]["f62"] = float("nan")
        cases["nan_flow"] = not_finite
        for name, payloads in cases.items():
            with self.subTest(name=name), self.assertRaises(SectorSourceError):
                parse_fund_relay(payloads, "2026-10-14", NOW)

    def test_missing_f3_value_or_column_preserves_fund_rank_with_unknown_pct(self):
        payloads = _fund_payloads()
        payloads["f3"]["data"]["diff"][0]["f3"] = "-"
        rows = parse_fund_relay(payloads, "2026-10-14", NOW)
        self.assertEqual(rows[0]["flow"], 300)
        self.assertIsNone(rows[0]["change_pct"])
        self.assertEqual(rows[1]["change_pct"], 0.63)
        payloads.pop("f3")
        rows = parse_fund_relay(payloads, "2026-10-14", NOW)
        self.assertEqual([row["flow"] for row in rows], [300, 200, -100])
        self.assertTrue(all(row["change_pct"] is None for row in rows))

    def test_member_relay_preserves_complete_identity_set_with_unknown_quote(self):
        payload = _payload([
            {"f12": "603598", "f13": 1, "f14": "引力传媒", "f62": 123},
            {"f12": "920021", "f13": 0, "f14": "流金科技", "f62": 80},
            {"f12": "600825", "f13": 1, "f14": "新华传媒", "f62": -20},
            {"f12": "200037", "f13": 0, "f14": "深南电B", "f62": 2},
        ])
        quotes = [_quote("603598", "SH"), _quote("920021", "BJ"), _quote("600825", "SH", status="unavailable")]
        rows, diag = parse_component_relay(payload, "BK0486", quotes, "2026-10-14", NOW)
        self.assertEqual([row["code"] for row in rows], ["600825", "603598", "920021"])
        self.assertEqual(next(row for row in rows if row["code"] == "920021")["exchange"], "BJ")
        self.assertIsNone(next(row for row in rows if row["code"] == "600825")["close"])
        self.assertIsNone(next(row for row in rows if row["code"] == "600825")["change_pct"])
        self.assertTrue(diag["complete"])
        self.assertEqual(diag["raw_valid_unique"], 4)
        self.assertEqual(diag["requested"], 4)
        self.assertEqual(diag["filtered_unique"], 3)
        self.assertIn("200037", diag["raw_component_codes"])
        self.assertEqual(diag["quote_usable_count"], 2)
        self.assertEqual(diag["quote_missing_codes"], ["600825"])
        self.assertEqual(diag["component_codes"], ["600825", "603598", "920021"])
        self.assertEqual(diag["quote_usable_codes"], ["603598", "920021"])
        self.assertEqual(diag["quote_evidence_status"], "verified")
        self.assertEqual(diag["quote_evidence_date"], "2026-10-14")

    def test_member_relay_rejects_missing_or_duplicate_identity(self):
        rows = [{"f12": "603598", "f13": 1, "f14": "引力传媒", "f62": 123}]
        missing = _payload(rows)
        missing["data"]["total"] = 2
        duplicate = _payload(rows + rows)
        for payload in (missing, duplicate):
            with self.assertRaises(SectorSourceError):
                parse_component_relay(payload, "BK0486", [], "2026-10-14", NOW)

    def test_snapshot_requires_complete_aware_same_day_identity_proof(self):
        quotes = [_quote("603598", "SH")]
        payload = {"schema_version": 1, "requested": 1,
                   "universe_source": "sina_hs_a", "fetched_at": "2026-10-14T15:20:09+08:00",
                   "diagnostics": {"complete": True, "requested": 1, "fetched": 1,
                                   "unique": 1, "universe_source": "sina_hs_a"},
                   "rows": quotes}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.json"
            path.write_text(json.dumps(payload))
            self.assertEqual(verified_quote_snapshot(path, "2026-10-14", NOW)[1], "verified")
            for change in ({"fetched_at": "2026-10-13T15:20:09+08:00"},
                           {"fetched_at": "2026-10-14T15:20:09"},
                           {"diagnostics": {"complete": False, "requested": 1, "fetched": 1, "unique": 1}},
                           {"requested": 2}):
                with self.subTest(change=change):
                    path.write_text(json.dumps({**payload, **change}))
                    self.assertEqual(verified_quote_snapshot(path, "2026-10-14", NOW)[1], "unavailable")

    def test_failed_clist_switches_once_then_reuses_funds_for_outflow_and_members(self):
        member = _payload([{"f12": "603598", "f13": 1, "f14": "引力传媒", "f62": 2}])
        calls = []

        def relay(field, code):
            calls.append((field, code))
            return member if code == "b:BK0486" else _fund_payloads()[field]

        session = SectorRelaySession("2026-10-14", relay, "/missing/quotes.json", lambda: NOW)
        with patch.object(data_fetcher, "_fetch_eastmoney_json", side_effect=ConnectionError("closed")) as clist:
            inflow = data_fetcher.fetch_sector_flow(2, source_session=session)
            outflow = data_fetcher.fetch_sector_outflow(2, source_session=session)
            stocks, diagnostics = data_fetcher.fetch_sector_stocks(
                "BK0486", source_session=session, return_diagnostics=True)
        self.assertEqual(clist.call_count, 1)
        self.assertEqual([row["code"] for row in inflow], ["BK0486", "BK1340"])
        self.assertEqual([row["code"] for row in outflow], ["BK0459"])
        self.assertEqual(calls, [(field, "m:90+t:2") for field in ("f62", "f124", "f3")]
                         + [("f62", "b:BK0486")])
        self.assertTrue(diagnostics["complete"])
        self.assertEqual(diagnostics["quote_evidence_status"], "unavailable")
        self.assertIsNone(stocks[0]["close"])
        self.assertIsNone(stocks[0]["change_pct"])

    def test_failed_relay_fund_request_is_not_retried_for_outflow(self):
        calls = []

        def relay(field, code):
            calls.append((field, code))
            raise ConnectionError("relay closed")

        session = SectorRelaySession("2026-10-14", relay, "/missing/quotes.json", lambda: NOW)
        with patch.object(data_fetcher, "_fetch_eastmoney_json", side_effect=ConnectionError("clist closed")) as clist:
            self.assertEqual(data_fetcher.fetch_sector_flow(2, source_session=session), [])
            self.assertEqual(data_fetcher.fetch_sector_outflow(2, source_session=session), [])
        self.assertEqual(clist.call_count, 1)
        self.assertEqual(calls, [("f62", "m:90+t:2")])

    def test_failed_optional_f3_request_retains_dated_money(self):
        calls = []

        def relay(field, code):
            calls.append((field, code))
            if field == "f3":
                raise ConnectionError("pct unavailable")
            return _fund_payloads()[field]

        session = SectorRelaySession("2026-10-14", relay, "/missing/quotes.json", lambda: NOW)
        rows = session.funds()
        self.assertEqual([row["flow"] for row in rows], [300, 200, -100])
        self.assertTrue(all(row["change_pct"] is None for row in rows))
        self.assertEqual(len(calls), 3)
        self.assertEqual(session.funds(), rows)
        self.assertEqual(len(calls), 3)

    def test_incomplete_clist_member_response_switches_to_complete_relay(self):
        full = _payload([{"f12": "603598", "f13": 1, "f14": "引力传媒", "f62": 2}])
        cases = ({"data": None},
                 {"data": {"total": 2, "diff": [
                     {"f12": "603598", "f14": "引力传媒", "f2": 10, "f3": 1}]}})
        for clist_response in cases:
            with self.subTest(clist_response=clist_response):
                calls = []

                def relay(field, code):
                    calls.append((field, code))
                    return full

                session = SectorRelaySession("2026-10-14", relay, "/missing/quotes.json", lambda: NOW)
                with patch.object(data_fetcher, "_fetch_eastmoney_json", return_value=clist_response) as clist:
                    stocks, diagnostics = data_fetcher.fetch_sector_stocks(
                        "BK0486", source_session=session, return_diagnostics=True)
                self.assertEqual(clist.call_count, 1)
                self.assertEqual(calls, [("f62", "b:BK0486")])
                self.assertTrue(session.clist_failed)
                self.assertEqual([stock["code"] for stock in stocks], ["603598"])
                self.assertTrue(diagnostics["complete"])
                self.assertEqual(diagnostics["source"], "eastmoney_relay")

    def test_partial_nonempty_clist_fund_page_switches_to_full_relay(self):
        row = {"f12": "BK0486", "f14": "传媒", "f3": 1.65, "f62": 300}
        for partial in ({"data": {"total": 496, "diff": [row]}},
                        {"data": {"diff": [row]}},
                        {"data": {"total": 496, "diff": [row, row]}}):
            for direction in ("inflow", "outflow"):
                with self.subTest(direction=direction, partial=partial):
                    session = SectorRelaySession(
                        "2026-10-14", lambda field, _: _fund_payloads()[field],
                        "/missing/quotes.json", lambda: NOW)
                    with patch.object(data_fetcher, "_fetch_eastmoney_json", return_value=partial) as clist:
                        if direction == "inflow":
                            rows = data_fetcher.fetch_sector_flow(2, source_session=session)
                            self.assertEqual([row["code"] for row in rows], ["BK0486", "BK1340"])
                        else:
                            rows = data_fetcher.fetch_sector_outflow(2, source_session=session)
                            self.assertEqual([row["code"] for row in rows], ["BK0459"])
                    self.assertEqual(clist.call_count, 1)
                    self.assertTrue(session.clist_failed)

    def test_incomplete_clist_and_failed_relay_preserve_partial_diagnostics(self):
        partial = {"data": {"total": 2, "diff": [
            {"f12": "603598", "f14": "引力传媒", "f2": 10, "f3": 1}]}}
        session = SectorRelaySession("2026-10-14", lambda *_: (_ for _ in ()).throw(
            ConnectionError("relay closed")), "/missing/quotes.json", lambda: NOW)
        with patch.object(data_fetcher, "_fetch_eastmoney_json", return_value=partial) as clist:
            stocks, diagnostics = data_fetcher.fetch_sector_stocks(
                "BK0486", source_session=session, return_diagnostics=True)
        self.assertEqual(clist.call_count, 1)
        self.assertEqual([stock["code"] for stock in stocks], ["603598"])
        self.assertFalse(diagnostics["complete"])
        self.assertEqual(diagnostics["error"], "short_page_before_total")
        self.assertEqual(diagnostics["requested"], 2)


if __name__ == "__main__":
    unittest.main()
