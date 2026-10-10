"""Raw-response evidence for descriptive published-list price observations."""

import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from chanlun import data_fetcher, report_generator, selection_price_evidence
from chanlun.selection_performance import _series_bars


def _response(code="600460", market=1, closes=(31.34, 31.99)):
    lines = [
        f"2026-09-16,30,{closes[0]},32,29,898402,100000,0,0,0,0",
        f"2026-09-17,31,{closes[1]},33,30,991117,110000,0,0,0,0",
    ]
    return json.dumps({"data": {"code": code, "market": market,
                                "klines": lines}}, separators=(",", ":")).encode()


def _full_response():
    days = []
    current = date(2026, 8, 3)
    while len(days) < 31:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    lines = [f"{day},30,31.34,32,29,898402,100000,0,0,0,0"
             for day in days]
    return json.dumps({"data": {"code": "600460", "market": 1,
                                "klines": lines}}, separators=(",", ":")).encode()


def _tencent_response(symbol="sh600460", *, qfq=True, closes=(31.34, 31.99)):
    rows = [
        ["2026-09-16", "30", str(closes[0]), "32", "29", "898402"],
        ["2026-09-17", "31", str(closes[1]), "33", "30", "991117"],
    ]
    return json.dumps({"code": 0, "data": {symbol: {
        "qfqday" if qfq else "day": rows,
    }}}, separators=(",", ":")).encode()


def _full_tencent_response():
    eastmoney = json.loads(_full_response())
    rows = [line.split(",")[:6] for line in eastmoney["data"]["klines"]]
    return json.dumps({"code": 0, "data": {"sh600460": {"qfqday": rows}}},
                      separators=(",", ":")).encode()


PARAMS = {"secid": "1.600460", "klt": "101", "fqt": "1",
          "end": "20500101", "lmt": "2"}
TENCENT_REQUEST = {
    "symbol": "sh600460", "period": "day", "adjustment": "qfq",
    "start": "2026-09-16", "end": "2026-10-09", "count": "12",
    "param": "sh600460,day,2026-09-16,2026-10-09,12,qfq",
}
AS_OF = "2026-10-09T15:20:00+08:00"


class RawEvidenceTests(unittest.TestCase):
    def test_capture_and_reload_verifies_original_eastmoney_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(), fetched_at=AS_OF,
            )
            self.assertTrue(saved.is_file())
            series, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"], evaluation_as_of=AS_OF,
            )
            self.assertEqual(len(series["SH600460"]), 1)
            bars, verified = _series_bars(series["SH600460"][0])
            self.assertTrue(verified)
            self.assertEqual((bars["2026-09-16"]["close"],
                              bars["2026-09-17"]["close"]), (31.34, 31.99))
            self.assertEqual(len(fingerprint), 64)
            self.assertEqual(saved, selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(), fetched_at=AS_OF,
            ))
            self.assertEqual(len(list((root / "SH600460").glob("*.json"))), 1)

    def test_wrong_request_or_identity_cannot_create_verified_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for params, raw in [
                ({**PARAMS, "fqt": "0"}, _response()),
                ({**PARAMS, "secid": "0.600460"}, _response()),
                (PARAMS, _response(code="600461")),
            ]:
                with self.assertRaises(ValueError):
                    selection_price_evidence.capture_eastmoney_historical_response(
                        root, "SH600460", params, raw, fetched_at=AS_OF,
                    )
            self.assertFalse((root / "SH600460").exists())

    def test_tencent_qfq_response_is_redecoded_and_plain_day_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = selection_price_evidence.capture_tencent_historical_response(
                root, "SH600460", TENCENT_REQUEST, _tencent_response(),
                fetched_at=AS_OF,
            )
            series, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"], evaluation_as_of=AS_OF,
            )
            self.assertTrue(saved.is_file())
            self.assertEqual(len(fingerprint), 64)
            self.assertEqual(series["SH600460"][0]["source_response"]["provider"],
                             "tencent")
            self.assertTrue(_series_bars(series["SH600460"][0])[1])
            self.assertEqual(series["SH600460"][0]["bars"][1]["close"], 31.99)
            with self.assertRaises(ValueError):
                selection_price_evidence.capture_tencent_historical_response(
                    root, "SH600460", TENCENT_REQUEST,
                    _tencent_response(qfq=False), fetched_at=AS_OF,
                )

    def test_tencent_identity_param_and_window_conflicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for request, raw in [
                ({**TENCENT_REQUEST, "param": "sh600460,day,,,12,qfq"},
                 _tencent_response()),
                ({**TENCENT_REQUEST, "adjustment": "raw"}, _tencent_response()),
                (TENCENT_REQUEST, _tencent_response(symbol="sz600460")),
                ({**TENCENT_REQUEST, "end": "2026-09-16",
                  "param": "sh600460,day,2026-09-16,2026-09-16,12,qfq"},
                 _tencent_response()),
                (TENCENT_REQUEST, _tencent_response(closes=(31.34, -1))),
            ]:
                with self.assertRaises(ValueError):
                    selection_price_evidence.capture_tencent_historical_response(
                        root, "SH600460", request, raw, fetched_at=AS_OF,
                    )

    def test_bounded_tencent_fetch_uses_one_physical_get_and_saves_qfqday(self):
        raw = _tencent_response()

        class Response:
            status_code = 200
            content = raw

        class Budget:
            requests = 0

            def take_request(self):
                self.requests += 1
                return 3.0

        with tempfile.TemporaryDirectory() as temporary:
            evidence_dir = Path(temporary) / "selection-price-evidence"
            budget = Budget()
            with mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()) as get:
                result = data_fetcher._fetch_selection_qfq_tencent_remote(
                    "600460", count=12, start_date="20260916",
                    end_date="20261009", request_budget=budget,
                    evidence_dir=evidence_dir,
                )
            self.assertIsNotNone(result)
            self.assertEqual((get.call_count, budget.requests), (1, 1))
            self.assertIn("sh600460,day,2026-09-16,2026-10-09,12,qfq",
                          get.call_args.args[0])
            series, _ = selection_price_evidence.load_verified_price_series(
                evidence_dir, ["SH600460"],
                evaluation_as_of="2026-10-09T15:20:00+08:00",
                evidence_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                                timedelta(minutes=1)).isoformat(),
            )
            self.assertEqual(series["SH600460"][0]["source_response"]["provider"],
                             "tencent")

    def test_tencent_plain_day_fallback_is_never_saved_as_qfq_proof(self):
        raw = _tencent_response(qfq=False)

        class Response:
            status_code = 200
            content = raw

        class Budget:
            def take_request(self):
                return 3.0

        with tempfile.TemporaryDirectory() as temporary:
            evidence_dir = Path(temporary) / "selection-price-evidence"
            with mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()) as get:
                result = data_fetcher._fetch_selection_qfq_tencent_remote(
                    "600460", count=12, start_date="20260916",
                    end_date="20261009", request_budget=Budget(),
                    evidence_dir=evidence_dir,
                )
            self.assertIsNone(result)
            self.assertEqual(get.call_count, 1)
            self.assertFalse(evidence_dir.exists())

    def test_tampered_raw_bytes_and_self_consistent_claims_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(), fetched_at=AS_OF,
            )
            payload = json.loads(saved.read_text())
            payload["raw_response"] = _response(closes=(31.34, 99.99)).decode()
            saved.write_text(json.dumps(payload))
            result, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"], evaluation_as_of=AS_OF,
            )
            self.assertEqual(result, {})
            self.assertIsNone(fingerprint)
            self.assertNotEqual(hashlib.sha256(payload["raw_response"].encode()).hexdigest(),
                                payload["raw_sha256"])

    def test_future_response_is_not_used_for_earlier_evaluation_cutoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(), fetched_at=AS_OF,
            )
            result, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"], evaluation_as_of="2026-09-16T15:20:00+08:00",
            )
            self.assertEqual(result, {})
            self.assertIsNone(fingerprint)

    def test_later_capture_cannot_rewrite_earlier_asof_even_with_old_bars(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(),
                fetched_at="2026-10-10T17:34:00+08:00",
            )
            result, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"], evaluation_as_of=AS_OF,
            )
            self.assertEqual(result, {})
            self.assertIsNone(fingerprint)

    def test_later_capture_can_prove_frozen_prices_with_explicit_evidence_cutoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captured = "2026-10-10T17:34:00+08:00"
            selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(), fetched_at=captured,
            )
            result, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"], evaluation_as_of=AS_OF,
                evidence_as_of=captured,
            )
            self.assertEqual(len(result["SH600460"]), 1)
            self.assertEqual(result["SH600460"][0]["source_response"]["fetched_at"],
                             captured)
            self.assertEqual(len(fingerprint), 64)

    def test_explicit_evidence_cutoff_never_expands_price_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captured = "2026-10-10T17:34:00+08:00"
            selection_price_evidence.capture_eastmoney_historical_response(
                root, "SH600460", PARAMS, _response(), fetched_at=captured,
            )
            result, fingerprint = selection_price_evidence.load_verified_price_series(
                root, ["SH600460"],
                evaluation_as_of="2026-09-16T15:20:00+08:00",
                evidence_as_of=captured,
            )
            self.assertEqual(result, {})
            self.assertIsNone(fingerprint)

    def test_normal_eastmoney_fetch_retains_raw_response_without_extra_request(self):
        raw = _full_response()

        class Response:
            status_code = 200
            content = raw

            def json(self):
                return json.loads(self.content)

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "market_history.sqlite"
            with mock.patch.object(data_fetcher, "MARKET_HISTORY_DB_PATH", str(database)), \
                    mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()) as get:
                result = data_fetcher._fetch_daily_kline_eastmoney_remote("600460", count=31)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(len(result["dates"]), 31)
            evidence, _ = selection_price_evidence.load_verified_price_series(
                database.parent / "selection-price-evidence", ["SH600460"],
                evaluation_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                                  timedelta(minutes=1)).isoformat(),
            )
            self.assertEqual(len(evidence["SH600460"]), 1)

    def test_normal_short_overlap_does_not_accumulate_unusable_proof_files(self):
        raw = _response()

        class Response:
            status_code = 200
            content = raw

            def json(self):
                return json.loads(self.content)

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "market_history.sqlite"
            with mock.patch.object(data_fetcher, "MARKET_HISTORY_DB_PATH", str(database)), \
                    mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()):
                result = data_fetcher._fetch_daily_kline_eastmoney_remote("600460", count=2)
            self.assertEqual(len(result["dates"]), 2)
            self.assertFalse((database.parent / "selection-price-evidence").exists())

    def test_normal_tencent_full_qfq_response_is_saved_without_extra_get(self):
        raw = _full_tencent_response()

        class Response:
            status_code = 200
            content = raw

            def json(self):
                return json.loads(self.content)

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "market_history.sqlite"
            with mock.patch.object(data_fetcher, "MARKET_HISTORY_DB_PATH", str(database)), \
                    mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()) as get:
                result = data_fetcher._fetch_daily_kline_remote("600460", count=31)
            self.assertEqual((get.call_count, len(result["dates"])), (1, 31))
            series, _ = selection_price_evidence.load_verified_price_series(
                database.parent / "selection-price-evidence", ["SH600460"],
                evaluation_as_of="2026-10-09T15:20:00+08:00",
                evidence_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                                timedelta(minutes=1)).isoformat(),
            )
            self.assertEqual(len(series["SH600460"]), 1)
            self.assertEqual(series["SH600460"][0]["source_response"]["provider"],
                             "tencent")

    def test_evidence_write_failure_does_not_discard_acquired_kline(self):
        raw = _response()

        class Response:
            status_code = 200
            content = raw

            def json(self):
                return json.loads(self.content)

        with mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()), \
                mock.patch.object(selection_price_evidence,
                                  "capture_eastmoney_historical_response",
                                  side_effect=OSError("cache unavailable")):
            result = data_fetcher._fetch_daily_kline_eastmoney_remote("600460", count=2)
        self.assertEqual(result["dates"], ["2026-09-16", "2026-09-17"])

    def test_bounded_historical_request_uses_report_cutoff_not_future_end(self):
        raw = _response()

        class Response:
            status_code = 200
            content = raw

            def json(self):
                return json.loads(self.content)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(data_fetcher, "MARKET_HISTORY_DB_PATH",
                                   str(Path(temporary) / "market_history.sqlite")), \
                    mock.patch.object(data_fetcher.SESSION, "get", return_value=Response()) as get:
                data_fetcher._fetch_daily_kline_eastmoney_remote(
                    "600460", count=40, start_date="20260916",
                    end_date="20261009",
                )
            self.assertEqual(get.call_args.kwargs["params"]["end"], "20261009")
            self.assertEqual(get.call_args.kwargs["params"]["beg"], "20260916")

    def test_normal_publish_fills_one_matured_stock_then_reuses_saved_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = "2026-10-09"
            as_of = "2026-10-09T15:20:00+08:00"
            self._published(root, day)
            database = root / "market_history.sqlite"
            evidence_dir = root / "selection-price-evidence"
            build_calls = []
            fetch_args = []

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                build_calls.append(Path(price_evidence_dir))
                series, _ = selection_price_evidence.load_verified_price_series(
                    price_evidence_dir, ["SH600460"], evaluation_as_of=evaluation,
                    evidence_as_of=price_evidence_as_of,
                )
                state = "ready" if series else "price_basis_unverified"
                dataset = self._dataset(day, evaluation, [
                    {"instrument_id": "SH600460", "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": state, "target_date": "2026-09-17"}}},
                ])
                dataset["trading_dates"] = [
                    "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21",
                    "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-28",
                    "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09",
                ]
                dataset["evidence_as_of"] = price_evidence_as_of or evaluation
                return dataset

            def fake_fetch(identity, count, *, request_budget, start_date,
                           end_date, evidence_dir):
                fetch_args.append((identity.exchange + identity.code, count,
                                   start_date, end_date, Path(evidence_dir)))
                request_budget.take_request()
                captured_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
                selection_price_evidence.capture_eastmoney_historical_response(
                    evidence_dir, identity.exchange + identity.code,
                    {**PARAMS, "lmt": str(count), "end": end_date,
                     "beg": start_date},
                    _response(), fetched_at=captured_at,
                )
                return {"dates": ["2026-09-16", "2026-09-17"]}

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      side_effect=fake_fetch) as fetch, \
                    mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                      side_effect=AssertionError("unexpected Tencent request")):
                first = report_generator.refresh_selection_performance_after_publish(
                    root, database, day, as_of, evidence_target_id="SH600460",
                )
                self.assertEqual(fetch.call_count, 1, first)
                second = report_generator.refresh_selection_performance_after_publish(
                    root, database, day, as_of, evidence_target_id="SH600460",
                )
            self.assertEqual((first["status"], second["status"]), ("ready", "ready"))
            self.assertEqual(first["evidence_fill"]["status"], "captured")
            self.assertEqual(fetch.call_count, 1, (first, second, fetch_args))
            self.assertEqual(fetch_args[0][:4],
                             ("SH600460", 12, "20260916", "20261009"))
            self.assertEqual(fetch_args[0][4], evidence_dir.resolve())
            self.assertEqual(build_calls, [evidence_dir.resolve()] * 3)
            published = json.loads((root / "data" / "selection-performance" /
                                    (day + ".json")).read_text())
            self.assertEqual(published["observations"][0]["outcomes"]["t1"]["status"],
                             "ready")
            self.assertEqual(published["evaluation_as_of"], as_of)
            self.assertGreater(published["evidence_as_of"], as_of)

    def test_failed_fill_is_bounded_and_rotates_to_another_missing_stock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "market_history.sqlite"
            for day in ("2026-10-09", "2026-10-12"):
                self._published(root, day)

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                return self._dataset(report_day, evaluation, [
                    {"instrument_id": identity, "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": "price_basis_unverified",
                                         "target_date": "2026-09-17"}}}
                    for identity in ("SH600460", "SH600498")
                ])

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      return_value=None) as eastmoney, \
                    mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                      return_value=None) as tencent:
                first = report_generator.refresh_selection_performance_after_publish(
                    root, database, "2026-10-09", "2026-10-10T17:34:00+08:00",
                )
                second = report_generator.refresh_selection_performance_after_publish(
                    root, database, "2026-10-09", "2026-10-10T17:34:00+08:00",
                )
            self.assertEqual((first["evidence_fill"]["requests"],
                              second["evidence_fill"]["requests"]), (2, 2))
            self.assertEqual((eastmoney.call_count, tencent.call_count), (2, 2))
            self.assertEqual([call.args[0].exchange + call.args[0].code
                              for call in eastmoney.call_args_list],
                             ["SH600460", "SH600498"])
            self.assertEqual([call.args[0].exchange + call.args[0].code
                              for call in tencent.call_args_list],
                             ["SH600460", "SH600498"])

    def test_failed_preferred_stock_can_retry_on_later_normal_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = "2026-10-09"
            self._published(root, day)

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                return self._dataset(day, evaluation, [
                    {"instrument_id": "SH600460", "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": "price_basis_unverified"}}},
                ])

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      return_value=None) as eastmoney, \
                    mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                      return_value=None) as tencent:
                first = report_generator.refresh_selection_performance_after_publish(
                    root, root / "market_history.sqlite", day,
                    "2026-10-09T15:20:00+08:00", evidence_target_id="SH600460",
                )
                second = report_generator.refresh_selection_performance_after_publish(
                    root, root / "market_history.sqlite", day,
                    "2026-10-09T15:20:00+08:00", evidence_target_id="SH600460",
                )
            self.assertEqual((first["evidence_fill"]["requests"],
                              second["evidence_fill"]["requests"]), (2, 2))
            self.assertEqual((eastmoney.call_count, tencent.call_count), (2, 2))

    def test_normal_publish_falls_back_to_one_tencent_qfq_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = "2026-10-09"
            market_as_of = "2026-10-09T15:20:00+08:00"
            self._published(root, day)

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                series, _ = selection_price_evidence.load_verified_price_series(
                    price_evidence_dir, ["SH600460"],
                    evaluation_as_of=evaluation,
                    evidence_as_of=price_evidence_as_of,
                )
                state = "ready" if series else "price_basis_unverified"
                return self._dataset(day, evaluation, [
                    {"instrument_id": "SH600460", "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": state,
                                         "target_date": "2026-09-17"}}},
                ])

            def failed_eastmoney(identity, count, *, request_budget, **kwargs):
                request_budget.take_request()
                return {"dates": ["2026-09-16"]}

            def fetched_tencent(identity, count, *, request_budget, start_date,
                                end_date, evidence_dir):
                request_budget.take_request()
                self.assertEqual(identity.exchange + identity.code, "SH600460")
                request = {**TENCENT_REQUEST, "start": "2026-09-16",
                           "end": "2026-10-09", "count": str(count),
                           "param": ("sh600460,day,2026-09-16,2026-10-09,"
                                     f"{count},qfq")}
                selection_price_evidence.capture_tencent_historical_response(
                    evidence_dir, "SH600460", request, _tencent_response(),
                    fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                )
                return {"dates": ["2026-09-16", "2026-09-17"]}

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      side_effect=failed_eastmoney) as eastmoney, \
                    mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                      side_effect=fetched_tencent) as tencent:
                result = report_generator.refresh_selection_performance_after_publish(
                    root, root / "market_history.sqlite", day, market_as_of,
                    evidence_target_id="SH600460",
                )
            self.assertEqual((eastmoney.call_count, tencent.call_count), (1, 1))
            self.assertEqual(result["evidence_fill"]["requests"], 2)
            self.assertEqual(result["evidence_fill"]["status"], "captured")
            published = json.loads((root / "data" / "selection-performance" /
                                    (day + ".json")).read_text())
            self.assertEqual(published["observations"][0]["outcomes"]["t1"]["status"],
                             "ready")

    def test_old_conflicting_full_proofs_and_new_partial_eastmoney_do_not_block_tencent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = "2026-10-09"
            self._published(root, day)
            evidence_dir = root / "selection-price-evidence"
            for closes in ((31.34, 31.99), (31.34, 32.99)):
                selection_price_evidence.capture_eastmoney_historical_response(
                    evidence_dir, "SH600460", PARAMS, _response(closes=closes),
                    fetched_at=AS_OF,
                )

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                return self._dataset(day, evaluation, [
                    {"instrument_id": "SH600460", "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": "price_basis_unverified",
                                         "target_date": "2026-09-17"}}},
                ])

            def partial_eastmoney(identity, count, *, start_date, end_date,
                                  evidence_dir, request_budget):
                request_budget.take_request()
                raw = json.loads(_response(closes=(30.0, 31.0)))
                raw["data"]["klines"] = raw["data"]["klines"][:1]
                selection_price_evidence.capture_eastmoney_historical_response(
                    evidence_dir, "SH600460",
                    {**PARAMS, "beg": start_date, "end": end_date,
                     "lmt": str(count)},
                    json.dumps(raw, separators=(",", ":")).encode(),
                    fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                )
                return {"dates": ["2026-09-16"]}

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      side_effect=partial_eastmoney) as eastmoney, \
                    mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                      return_value=None) as tencent:
                result = report_generator.refresh_selection_performance_after_publish(
                    root, root / "market_history.sqlite", day, AS_OF,
                    evidence_dir=evidence_dir, evidence_target_id="SH600460",
                )
            self.assertEqual((eastmoney.call_count, tencent.call_count), (1, 1))
            self.assertEqual(result["evidence_fill"]["requests"], 2)
            self.assertNotEqual(result["evidence_fill"]["status"], "captured")

    def test_new_zero_volume_proof_does_not_prevent_tencent_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = "2026-10-09"
            self._published(root, day)

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                return self._dataset(day, evaluation, [
                    {"instrument_id": "SH600460", "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": "price_basis_unverified",
                                         "target_date": "2026-09-17"}}},
                ])

            def zero_volume(identity, count, *, start_date, end_date,
                            evidence_dir, request_budget):
                request_budget.take_request()
                raw = json.loads(_response())
                row = raw["data"]["klines"][1].split(",")
                row[5] = "0"
                raw["data"]["klines"][1] = ",".join(row)
                selection_price_evidence.capture_eastmoney_historical_response(
                    evidence_dir, "SH600460",
                    {**PARAMS, "beg": start_date, "end": end_date,
                     "lmt": str(count)},
                    json.dumps(raw, separators=(",", ":")).encode(),
                    fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                )
                return {"dates": ["2026-09-16", "2026-09-17"]}

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      side_effect=zero_volume) as eastmoney, \
                    mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                      return_value=None) as tencent:
                result = report_generator.refresh_selection_performance_after_publish(
                    root, root / "market_history.sqlite", day, AS_OF,
                    evidence_target_id="SH600460",
                )
            self.assertEqual((eastmoney.call_count, tencent.call_count), (1, 1))
            self.assertEqual(result["evidence_fill"]["requests"], 2)

    def test_preferred_published_member_with_ready_or_waiting_result_needs_no_fill(self):
        dataset = self._dataset("2026-10-12", "2026-10-12T15:20:00+08:00", [
            {"instrument_id": "SH600460", "report_date": "2026-09-16",
             "outcomes": {"t1": {"status": "ready"},
                          "t30": {"status": "waiting"}}},
        ])
        with tempfile.TemporaryDirectory() as temporary:
            chosen = selection_price_evidence.select_due_fill_candidate(
                dataset, temporary, preferred_identity="SH600460",
            )
            self.assertIsNone(chosen)
            with self.assertRaises(ValueError):
                selection_price_evidence.select_due_fill_candidate(
                    dataset, temporary, preferred_identity="SH600498",
                )

    def test_first_normal_publish_reuses_later_ordinary_capture_without_http(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = "2026-10-09"
            market_as_of = "2026-10-09T15:20:00+08:00"
            self._published(root, day)
            evidence_dir = root / "selection-price-evidence"
            captured_at = (datetime.now(timezone(timedelta(hours=8))) -
                           timedelta(seconds=1)).isoformat()
            selection_price_evidence.capture_eastmoney_historical_response(
                evidence_dir, "SH600460", PARAMS, _response(),
                fetched_at=captured_at,
            )

            def build(data, db_path, report_day, evaluation, *, price_evidence_dir,
                      price_evidence_as_of=None):
                series, _ = selection_price_evidence.load_verified_price_series(
                    price_evidence_dir, ["SH600460"],
                    evaluation_as_of=evaluation,
                    evidence_as_of=price_evidence_as_of,
                )
                return self._dataset(day, evaluation, [
                    {"instrument_id": "SH600460", "report_date": "2026-09-16",
                     "outcomes": {"t1": {"status": "ready" if series else
                                         "price_basis_unverified"}}},
                ])

            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=build), \
                    mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                                      side_effect=AssertionError("no new HTTP expected")) as fetch:
                result = report_generator.refresh_selection_performance_after_publish(
                    root, root / "market_history.sqlite", day, market_as_of,
                    evidence_dir=evidence_dir, evidence_target_id="SH600460",
                )
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["evidence_fill"]["requests"], 0)
            fetch.assert_not_called()
            published = json.loads((root / "data" / "selection-performance" /
                                    (day + ".json")).read_text())
            self.assertEqual(published["observations"][0]["outcomes"]["t1"]["status"],
                             "ready")
            self.assertEqual(published["evaluation_as_of"], market_as_of)

    @staticmethod
    def _published(root, day):
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / (day + ".json")).write_text("{}")
        (root / "data" / "comparison-index.json").write_text("{}")
        (root / day).mkdir(exist_ok=True)
        (root / day / "index.html").write_text("<html></html>")

    @staticmethod
    def _dataset(day, evaluation, observations):
        return {
            "schema_version": "selection-performance-v1",
            "dataset_id": "test-evidence-dataset",
            "report_as_of": day,
            "evaluation_as_of": evaluation,
            "observations": observations,
        }


if __name__ == "__main__":
    unittest.main()
