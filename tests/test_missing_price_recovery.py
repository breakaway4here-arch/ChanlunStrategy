"""Synthetic raw responses through the published performance refresh entry."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from chanlun import data_fetcher, report_generator, selection_price_evidence
from chanlun.market_history_store import MarketHistoryStore
from chanlun.report_comparison import comparison_review_snapshot, write_comparison_index
from chanlun.selection_performance import (
    aggregate_selection_performance, build_selection_performance,
    evaluate_observations,
)


START = "2026-08-03"
TARGET = "2026-08-04"
AS_OF = TARGET + "T15:20:00+08:00"
IDENTITY = "SH600001"


def _raw_response(*, start=True, target=True, volume=100):
    rows = []
    if start:
        rows.append(f"{START},100,100,101,99,{volume},10000,0,0,0,0")
    if target:
        rows.append(f"{TARGET},105,105,106,104,{volume},10500,0,0,0,0")
    return json.dumps({"data": {"code": "600001", "market": 1,
                                "klines": rows}}, separators=(",", ":")).encode()


class MissingPriceRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="missing-price-synthetic-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.root / "market.sqlite"
        self.evidence = self.root / "proof"
        (self.data / "index.json").write_text(json.dumps({"dates": [START, TARGET]}))
        self.report = {"date": START, "kaipanla_context": {
            "status": "available", "source": "kaipanla", "data_date": START,
            "fetched_at": START + "T14:00:00+08:00",
            "groups": [{"code": "ai", "name": "AI应用",
                        "stocks": [{"code": "600001"}]}],
        }}
        self.workbench = {
            "schema_version": "decision-workbench-v1", "report_date": START,
            "snapshot_id": "synthetic-published", "phase": "formal",
            "as_of": START + "T15:20:00+08:00", "comparison_contract": {},
            "items": [{"code": "600001", "instrument_id": IDENTITY,
                       "name": "甲", "strategy_results": [{
                           "strategy_id": "main", "role": "formal",
                           "candidate": {"strategy_version": "v1"},
                       }]}],
        }
        (self.data / (START + ".json")).write_text(json.dumps(self.report))
        html = self.root / START / "index.html"
        html.parent.mkdir()
        html.write_text("<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
            "pageDate": START, "inlineReportData": self.report,
            "decisionWorkbench": self.workbench,
        }) + ";</script>")
        with MarketHistoryStore(self.db) as store:
            stock = store.upsert_instrument("stock", "SH", "600001", "甲")
            store.upsert_bars("day", stock, [{
                "ts": START, "open": 100, "high": 101, "low": 99,
                "close": 100, "volume": 100, "amount": 10000,
                "adjustment": "qfq", "is_final": True,
            }])
        with comparison_review_snapshot(self.workbench):
            write_comparison_index(str(self.data), str(self.db))
        (self.data / (TARGET + ".json")).write_text(json.dumps({"date": TARGET}))
        latest = self.root / TARGET / "index.html"
        latest.parent.mkdir()
        latest.write_text("<html>synthetic published report</html>")

    def _build(self):
        return build_selection_performance(
            self.data, self.db, TARGET, AS_OF, price_evidence_dir=self.evidence,
            price_evidence_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                                  timedelta(seconds=1)).isoformat(),
        )

    def _refresh(self, eastmoney, tencent=None, *, day=TARGET, as_of=AS_OF):
        with mock.patch.object(data_fetcher, "_fetch_daily_kline_eastmoney_remote",
                               side_effect=eastmoney) as east, \
                mock.patch.object(data_fetcher, "_fetch_selection_qfq_tencent_remote",
                                  side_effect=tencent or (lambda *a, **k: None)) as ten:
            result = report_generator.refresh_selection_performance_after_publish(
                self.root, self.db, day, as_of, evidence_dir=self.evidence,
                evidence_target_id=IDENTITY,
            )
        return result, east, ten

    def _fetch(self, raw, *, end_day=TARGET):
        def fetch(identity, count, *, request_budget, start_date, end_date,
                  evidence_dir):
            request_budget.take_request()
            self.assertEqual((identity.exchange + identity.code, start_date, end_date),
                             (IDENTITY, "20260803", end_day.replace("-", "")))
            selection_price_evidence.capture_eastmoney_historical_response(
                evidence_dir, IDENTITY,
                {"secid": "1.600001", "klt": "101", "fqt": "1",
                 "beg": start_date, "end": end_date, "lmt": str(count)}, raw,
                fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            )
            return {"dates": [START, TARGET]}
        return fetch

    def _extend_to_t3(self):
        day = "2026-08-06"
        (self.data / "index.json").write_text(json.dumps({
            "dates": [START, TARGET, day]}))
        (self.data / (day + ".json")).write_text(json.dumps({"date": day}))
        html = self.root / day / "index.html"
        html.parent.mkdir()
        html.write_text("<html>synthetic later published report</html>")
        return day, day + "T15:20:00+08:00"

    def _publish_second_day(self):
        report = {"date": TARGET}
        workbench = dict(self.workbench, report_date=TARGET,
                         snapshot_id="synthetic-published-second",
                         as_of=TARGET + "T15:20:00+08:00")
        (self.data / (TARGET + ".json")).write_text(json.dumps(report))
        (self.root / TARGET / "index.html").write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": TARGET, "inlineReportData": report,
                "decisionWorkbench": workbench,
            }) + ";</script>")
        with comparison_review_snapshot(workbench):
            write_comparison_index(str(self.data), str(self.db))

    def _fetch_tencent(self, raw, *, end_day=TARGET):
        def fetch(identity, count, *, request_budget, start_date, end_date,
                  evidence_dir):
            request_budget.take_request()
            request = {"symbol": "sh600001", "period": "day",
                       "adjustment": "qfq", "start": START, "end": end_day,
                       "count": str(count),
                       "param": f"sh600001,day,{START},{end_day},{count},qfq"}
            selection_price_evidence.capture_tencent_historical_response(
                evidence_dir, IDENTITY, request, raw,
                fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            )
            return {"dates": [START, TARGET]}
        return fetch

    def test_missing_target_traverses_refresh_to_ready_and_reuses_proof(self):
        before = self._build()
        outcome = before["observations"][0]["outcomes"]["t1"]
        self.assertEqual((outcome["status"], outcome["reason_code"]),
                         ("missing_price", "missing_price"))
        first, east, ten = self._refresh(self._fetch(_raw_response()))
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(first["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (TARGET + ".json")).read_text())
        self.assertEqual(dated["observations"][0]["outcomes"]["t1"]["status"],
                         "ready")
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        self.assertEqual(dated["summary"]["t1"]["counts"]["ready"], 1)
        self.assertAlmostEqual(dated["summary"]["t1"]["mean_return_pct"], 5)
        self.assertEqual(dated["summary"]["t1"]["best_observations"][0]
                         ["instrument_id"], IDENTITY)
        self.assertEqual(dated["summary"]["t1"]["worst_observations"][0]
                         ["instrument_id"], IDENTITY)
        self.assertEqual(json.loads((self.data / "selection-performance" /
                                     "index.json").read_text())["datasets"][TARGET]
                         ["dataset_id"], dated["dataset_id"])
        self.assertEqual(json.loads((self.data / "selection-performance" /
                                     "status.json").read_text())["evidence_fill"]
                         ["status"], "captured")
        second, east, ten = self._refresh(
            lambda *a, **k: self.fail("cached proof must avoid HTTP"))
        self.assertEqual((east.call_count, ten.call_count), (0, 0))
        self.assertEqual(second["evidence_fill"]["status"], "not_needed")

    def test_missing_start_is_recovered_from_one_verified_response(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM bars_day")
        before = self._build()
        self.assertEqual(before["observations"][0]["outcomes"]["t1"]["status"],
                         "missing_price")
        result, east, ten = self._refresh(self._fetch(_raw_response()))
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        after = json.loads((self.data / "selection-performance" /
                            (TARGET + ".json")).read_text())
        self.assertEqual(after["observations"][0]["outcomes"]["t1"]
                         ["start_close"], 100)
        self.assertAlmostEqual(after["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)

    def test_request_window_uses_frozen_evaluation_cutoff_for_old_report(self):
        # The last saved report can precede its later, frozen evaluation date.
        result, east, ten = self._refresh(
            self._fetch(_raw_response()), day=START, as_of=AS_OF)
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (START + ".json")).read_text())
        self.assertEqual(dated["observations"][0]["outcomes"]["t1"]["status"],
                         "ready")

    def test_same_raw_recaptured_after_close_enters_normal_refresh_without_http(self):
        early = TARGET + "T14:00:00+08:00"
        confirmed = TARGET + "T15:20:00+08:00"
        request = {"secid": "1.600001", "klt": "101", "fqt": "1",
                   "beg": "20260803", "end": "20260804", "lmt": "2"}
        raw = _raw_response()
        selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY, request, raw, fetched_at=early)
        self.assertEqual(self._build()["observations"][0]["outcomes"]["t1"]
                         ["status"], "missing_price")
        selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY, request, raw, fetched_at=confirmed)
        result, east, ten = self._refresh(
            lambda *args, **kwargs: self.fail("saved final proof avoids HTTP"))
        self.assertEqual((east.call_count, ten.call_count), (0, 0))
        self.assertEqual(result["evidence_fill"]["status"], "not_needed")
        dated = json.loads((self.data / "selection-performance" /
                            (TARGET + ".json")).read_text())
        self.assertEqual(dated["observations"][0]["outcomes"]["t1"]["status"],
                         "ready")
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)

    def test_same_raw_provider_refetch_promotes_confirmation_through_refresh(self):
        day, as_of = self._extend_to_t3()
        early = TARGET + "T14:00:00+08:00"
        path = selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY,
            {"secid": "1.600001", "klt": "101", "fqt": "1",
             "beg": "20260803", "end": "20260806", "lmt": "4"},
            _raw_response(), fetched_at=early)
        before = build_selection_performance(
            self.data, self.db, day, as_of, price_evidence_dir=self.evidence,
            price_evidence_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                                  timedelta(seconds=1)).isoformat())
        self.assertEqual(before["observations"][0]["outcomes"]["t1"]["status"],
                         "missing_price")
        result, east, ten = self._refresh(
            self._fetch(_raw_response(), end_day=day), day=day, as_of=as_of)
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        record = json.loads(path.read_text())
        self.assertEqual(record["fetched_at"], early)
        self.assertIsNotNone(record.get("confirmed_at"))
        self.assertEqual(len(list((self.evidence / IDENTITY).glob("*.json"))), 1)
        dated = json.loads((self.data / "selection-performance" /
                            (day + ".json")).read_text())
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        old_cutoff, _ = selection_price_evidence.load_verified_price_series(
            self.evidence, [IDENTITY], evaluation_as_of=as_of,
            evidence_as_of=TARGET + "T14:30:00+08:00")
        self.assertFalse(old_cutoff[IDENTITY][0]["bars"][-1]["is_final"])

    def test_partial_first_response_uses_second_provider_and_missing_middle_is_valid(self):
        day, as_of = self._extend_to_t3()
        partial = _raw_response(target=False)
        full = json.dumps({"code": 0, "data": {"sh600001": {"qfqday": [
            [START, "100", "100", "101", "99", "100"],
            [day, "105", "105", "106", "104", "100"],
        ]}}}, separators=(",", ":")).encode()
        result, east, ten = self._refresh(
            self._fetch(partial, end_day=day),
            self._fetch_tencent(full, end_day=day), day=day, as_of=as_of)
        self.assertEqual((east.call_count, ten.call_count), (1, 1))
        self.assertEqual(result["evidence_fill"]["requests"], 2)
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        self.assertEqual(result["evidence_fill"]["provider"], "tencent")
        dated = json.loads((self.data / "selection-performance" /
                            (day + ".json")).read_text())
        self.assertEqual(dated["observations"][0]["outcomes"]["t1"]["status"],
                         "missing_price")
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t3"]
                               ["return_pct"], 5)

    def test_both_responses_unusable_keep_gap_and_record_attempt(self):
        result, east, ten = self._refresh(
            self._fetch(_raw_response(target=False)),
            lambda *args, **kwargs: None)
        self.assertEqual((east.call_count, ten.call_count), (1, 1))
        self.assertEqual(result["evidence_fill"]["requests"], 2)
        self.assertNotEqual(result["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (TARGET + ".json")).read_text())
        self.assertEqual(dated["observations"][0]["outcomes"]["t1"]["status"],
                         "missing_price")
        self.assertEqual(json.loads((self.evidence / "fill-attempts.json")
                                    .read_text())[IDENTITY]["count"], 1)

    def test_refresh_recovers_when_same_hash_cache_file_is_corrupt(self):
        raw = _raw_response()
        folder = self.evidence / IDENTITY
        folder.mkdir(parents=True)
        target = folder / (hashlib.sha256(raw).hexdigest() + ".json")
        target.write_bytes(b"{bad json")
        result, east, ten = self._refresh(self._fetch(raw))
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (TARGET + ".json")).read_text())
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        quarantined = list((self.evidence / "quarantine").rglob(target.name))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), b"{bad json")
        self.assertEqual(json.loads(target.read_text())["raw_response"].encode(),
                         raw)

    def test_due_eligibility_is_cutoff_and_reason_bounded(self):
        base = self._build()
        row = base["observations"][0]
        outcome = row["outcomes"]["t1"]
        eligible = selection_price_evidence.is_due_price_gap
        self.assertTrue(eligible(base, row, "t1", outcome))
        self.assertTrue(eligible(base, row, "t1", {
            **outcome, "reason_code": "target_close_unconfirmed"}))
        self.assertTrue(eligible(base, row, "t1", {
            "status": "missing_price", "target_date": TARGET}))
        for changed_data, changed_row, changed_outcome in (
            ({**base, "evaluation_as_of": TARGET + "T14:30:00+08:00"}, row, outcome),
            ({**base, "trading_dates": []}, row, outcome),
            (base, {**row, "excluded_reason": "registered_incident"}, outcome),
            (base, {**row, "code": "600002"}, outcome),
            (base, row, {**outcome, "target_date": None}),
            (base, row, {**outcome, "status": "waiting"}),
            (base, row, {**outcome, "reason_code": "target_no_traded_close"}),
            (base, row, {**outcome, "reason_code": "start_no_traded_close"}),
        ):
            with self.subTest(changed_data=changed_data.get("evaluation_as_of"),
                              reason=changed_outcome.get("reason_code")):
                self.assertFalse(eligible(changed_data, changed_row, "t1",
                                          changed_outcome))

    def test_confirmed_zero_volume_gap_is_not_fetched_or_called_unneeded(self):
        with MarketHistoryStore(self.db) as store:
            stock = store.resolve_instrument("stock", "SH", "600001")
            store.upsert_bars("day", stock["instrument_id"], [{
                "ts": TARGET, "open": 105, "high": 106, "low": 104,
                "close": 105, "volume": 0, "amount": 0,
                "adjustment": "qfq", "is_final": True,
            }])
        before = self._build()["observations"][0]["outcomes"]["t1"]
        self.assertEqual((before["status"], before["reason_code"]),
                         ("missing_price", "target_no_traded_close"))
        result, east, ten = self._refresh(
            lambda *args, **kwargs: self.fail("confirmed no trade must not fetch"))
        self.assertEqual((east.call_count, ten.call_count), (0, 0))
        self.assertEqual(result["evidence_fill"]["status"], "deferred")

    def test_missing_start_does_not_mask_confirmed_zero_volume_target(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM bars_day")
        with MarketHistoryStore(self.db) as store:
            stock = store.resolve_instrument("stock", "SH", "600001")
            store.upsert_bars("day", stock["instrument_id"], [{
                "ts": TARGET, "open": 105, "high": 106, "low": 104,
                "close": 105, "volume": 0, "amount": 0,
                "adjustment": "qfq", "is_final": True,
            }])
        outcome = self._build()["observations"][0]["outcomes"]["t1"]
        self.assertEqual((outcome["status"], outcome["reason_code"]),
                         ("missing_price", "target_no_traded_close"))
        result, east, ten = self._refresh(
            lambda *args, **kwargs: self.fail("no traded close must not fetch"))
        self.assertEqual((east.call_count, ten.call_count), (0, 0))
        self.assertEqual(result["evidence_fill"]["status"], "deferred")

    def test_one_response_updates_matured_horizon_and_leaves_later_gap(self):
        day, as_of = self._extend_to_t3()
        first, east, ten = self._refresh(
            self._fetch(_raw_response(), end_day=day), day=day, as_of=as_of)
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(first["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (day + ".json")).read_text())
        outcomes = dated["observations"][0]["outcomes"]
        self.assertEqual((outcomes["t1"]["status"], outcomes["t3"]["status"]),
                         ("ready", "missing_price"))
        self.assertEqual((dated["summary"]["t1"]["counts"]["ready"],
                          dated["summary"]["t3"]["counts"]["missing_price"]),
                         (1, 1))

    def test_one_response_is_reused_across_two_publication_days_and_horizons(self):
        day, as_of = self._extend_to_t3()
        self._publish_second_day()
        raw = json.dumps({"data": {"code": "600001", "market": 1,
                                   "klines": [
                                       f"{START},100,100,101,99,100,10000,0,0,0,0",
                                       f"{TARGET},105,105,106,104,100,10500,0,0,0,0",
                                       "2026-08-05,106,106,107,105,100,10600,0,0,0,0",
                                       f"{day},110,110,111,109,100,11000,0,0,0,0",
                                   ]}}, separators=(",", ":")).encode()
        result, east, ten = self._refresh(self._fetch(raw, end_day=day),
                                          day=day, as_of=as_of)
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (day + ".json")).read_text())
        rows = {row["report_date"]: row for row in dated["observations"]}
        self.assertEqual(set(rows), {START, TARGET})
        self.assertAlmostEqual(rows[START]["outcomes"]["t1"]["return_pct"], 5)
        self.assertAlmostEqual(rows[START]["outcomes"]["t3"]["return_pct"], 10)
        self.assertAlmostEqual(rows[TARGET]["outcomes"]["t1"]["return_pct"],
                               (106 - 105) / 105 * 100)
        self.assertEqual(dated["summary"]["t1"]["counts"]["ready"], 2)

    def test_failed_later_gap_attempt_preserves_earlier_ready_result(self):
        day, as_of = self._extend_to_t3()
        selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY,
            {"secid": "1.600001", "klt": "101", "fqt": "1",
             "beg": "20260803", "end": "20260806", "lmt": "4"},
            _raw_response(),
            fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        )
        first = build_selection_performance(
            self.data, self.db, day, as_of, price_evidence_dir=self.evidence,
            price_evidence_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                                  timedelta(seconds=1)).isoformat())
        self.assertEqual(first["observations"][0]["outcomes"]["t1"]["status"],
                         "ready")
        self.assertEqual(first["observations"][0]["outcomes"]["t3"]["status"],
                         "missing_price")
        result, east, ten = self._refresh(
            self._fetch(_raw_response(), end_day=day),
            lambda *args, **kwargs: None, day=day, as_of=as_of)
        self.assertEqual((east.call_count, ten.call_count), (1, 1))
        self.assertNotEqual(result["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (day + ".json")).read_text())
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        self.assertEqual(dated["observations"][0]["outcomes"]["t3"]["status"],
                         "missing_price")

    def test_conflicting_new_full_proof_never_erases_old_ready_in_two_refreshes(self):
        day, as_of = self._extend_to_t3()
        selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY,
            {"secid": "1.600001", "klt": "101", "fqt": "1",
             "beg": "20260803", "end": "20260806", "lmt": "4"},
            _raw_response(),
            fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        )
        conflict = json.dumps({"code": 0, "data": {"sh600001": {"qfqday": [
            [date, str(price), str(price), str(price + 1),
             str(price - 1), "100"]
            for date, price in ((START, 101), (TARGET, 106),
                                ("2026-08-05", 107), (day, 110))
        ]}}}, separators=(",", ":")).encode()
        first, east, ten = self._refresh(
            lambda *args, **kwargs: None,
            self._fetch_tencent(conflict, end_day=day), day=day, as_of=as_of)
        self.assertEqual((east.call_count, ten.call_count), (1, 1))
        self.assertNotEqual(first["evidence_fill"]["status"], "captured")
        first_dated = json.loads((self.data / "selection-performance" /
                                  (day + ".json")).read_text())
        self.assertEqual(first_dated["observations"][0]["outcomes"]["t1"]["status"],
                         "ready")
        self.assertAlmostEqual(first_dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        second, _, _ = self._refresh(lambda *a, **k: None,
                                     lambda *a, **k: None, day=day, as_of=as_of)
        second_dated = json.loads((self.data / "selection-performance" /
                                   (day + ".json")).read_text())
        self.assertEqual(second["status"], "ready")
        self.assertEqual(second_dated["observations"][0]["outcomes"]["t1"]
                         ["status"], "ready")
        self.assertAlmostEqual(second_dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        self.assertEqual(len(list((self.evidence / IDENTITY).glob("*.json"))), 1)
        self.assertTrue(list((self.evidence / "quarantine").rglob("*.json")))

    def test_conflicting_partial_proof_cannot_poison_next_normal_refresh(self):
        day, as_of = self._extend_to_t3()
        selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY,
            {"secid": "1.600001", "klt": "101", "fqt": "1",
             "beg": "20260803", "end": "20260806", "lmt": "4"},
            _raw_response(),
            fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        )
        conflict = json.dumps({"code": 0, "data": {"sh600001": {"qfqday": [
            [START, "101", "101", "102", "100", "100"],
            [TARGET, "106", "106", "107", "105", "100"],
        ]}}}, separators=(",", ":")).encode()
        first, _, _ = self._refresh(
            lambda *args, **kwargs: None,
            self._fetch_tencent(conflict, end_day=day), day=day, as_of=as_of)
        self.assertNotEqual(first["evidence_fill"]["status"], "captured")
        second, _, _ = self._refresh(lambda *a, **k: None,
                                     lambda *a, **k: None, day=day, as_of=as_of)
        dated = json.loads((self.data / "selection-performance" /
                            (day + ".json")).read_text())
        self.assertEqual(second["status"], "ready")
        self.assertEqual(dated["observations"][0]["outcomes"]["t1"]["status"],
                         "ready")
        self.assertAlmostEqual(dated["observations"][0]["outcomes"]["t1"]
                               ["return_pct"], 5)
        self.assertEqual(len(list((self.evidence / IDENTITY).glob("*.json"))), 1)
        self.assertTrue(list((self.evidence / "quarantine").rglob("*.json")))

    def test_incident_source_stays_excluded_while_other_source_recovers(self):
        row = self._build()["observations"][0]
        row["strategy_refs"] = [
            {"strategy_key": "incident", "role": "research",
             "formal_performance_status": "incident_excluded"},
            {"strategy_key": "valid", "role": "research",
             "formal_performance_status": "review_only"},
        ]
        selection_price_evidence.capture_eastmoney_historical_response(
            self.evidence, IDENTITY,
            {"secid": "1.600001", "klt": "101", "fqt": "1",
             "beg": "20260803", "end": "20260804", "lmt": "2"},
            _raw_response(),
            fetched_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        )
        proof, _ = selection_price_evidence.load_verified_price_series(
            self.evidence, [IDENTITY], evaluation_as_of=AS_OF,
            evidence_as_of=(datetime.now(timezone(timedelta(hours=8))) +
                            timedelta(seconds=1)).isoformat())
        rows = evaluate_observations([row], self._build()["trading_dates"],
                                     proof, AS_OF)
        self.assertEqual(rows[0]["source_outcomes"]["incident"]["t1"]["status"],
                         "excluded")
        self.assertEqual(rows[0]["source_outcomes"]["valid"]["t1"]["status"],
                         "ready")
        self.assertEqual(aggregate_selection_performance(
            {"observations": rows}, horizon=1, strategy_key="valid")
                         ["counts"]["ready"], 1)
        self.assertEqual(aggregate_selection_performance(
            {"observations": rows}, horizon=1, strategy_key="incident")
                         ["counts"]["excluded"], 1)

    def test_published_mixed_incident_refresh_keeps_all_group_denominators(self):
        self.report["selection_input_health"] = {
            "schema_version": 2, "by_strategy": {
                "daily_fusion": {"status": "verified",
                                 "formal_actions_allowed": True},
            },
        }
        self.workbench["items"][0]["strategy_results"] = [
            {"strategy_id": "main", "role": "formal",
             "candidate": {"strategy_version": "formal-v1"}},
            {"strategy_id": "highlights", "role": "research",
             "candidate": {"strategy_version": "research-v1"}},
        ]
        (self.data / (START + ".json")).write_text(json.dumps(self.report))
        (self.root / START / "index.html").write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": START, "inlineReportData": self.report,
                "decisionWorkbench": self.workbench,
            }) + ";</script>")
        with mock.patch("chanlun.report_comparison._registered_incident_codes",
                        side_effect=lambda day, view: {"600001"}
                        if view == "main" else set()):
            with comparison_review_snapshot(self.workbench):
                write_comparison_index(str(self.data), str(self.db))
            before = self._build()
            refs = {ref["view"]: ref for ref in before["observations"][0]
                    ["strategy_refs"]}
            self.assertEqual(refs["main"]["formal_performance_status"],
                             "incident_excluded")
            self.assertEqual(refs["highlights"]["formal_performance_status"],
                             "review_only")
            result, east, ten = self._refresh(self._fetch(_raw_response()))
        self.assertEqual((east.call_count, ten.call_count), (1, 0))
        self.assertEqual(result["evidence_fill"]["status"], "captured")
        dated = json.loads((self.data / "selection-performance" /
                            (TARGET + ".json")).read_text())
        row = dated["observations"][0]
        self.assertEqual(row["outcomes"]["t1"]["status"], "ready")
        self.assertEqual(row["source_outcomes"][refs["main"]["strategy_key"]]
                         ["t1"]["status"], "excluded")
        self.assertEqual(row["source_outcomes"][refs["highlights"]["strategy_key"]]
                         ["t1"]["status"], "ready")
        self.assertEqual(dated["summary"]["t1"]["counts"]["ready"], 1)
        self.assertEqual(dated["groups"]["themes"]["kaipanla:ai"]
                         ["horizons"]["t1"]["counts"]["ready"], 1)
        self.assertEqual(dated["groups"]["strategies"]
                         [refs["main"]["strategy_key"]]["horizons"]["t1"]
                         ["counts"]["excluded"], 1)
        self.assertEqual(dated["groups"]["strategies"]
                         [refs["highlights"]["strategy_key"]]["horizons"]["t1"]
                         ["counts"]["ready"], 1)


if __name__ == "__main__":
    unittest.main()
