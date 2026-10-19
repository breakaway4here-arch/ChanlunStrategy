"""Offline counterexamples for bounded transport, capture writes and budgets."""
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import requests

import intraday_observation_run as runner
from chanlun import intraday_observation_data as data
from chanlun.market_history_store import MarketHistoryStore
from tests.test_intraday_observation_data import CN, CUTOFF, IDENTITY, fixture
from tests import test_intraday_observation_runner as runner_tests


NOW = datetime(2026, 10, 13, 14, 46, tzinfo=CN)
DEADLINE = NOW.replace(minute=58)


class FakeResponse:
    def __init__(self, params, status=200):
        self.params, self.status_code, self.closed = params, status, False

    def json(self):
        market, code = self.params["secid"].split(".")
        if self.params["klt"] == "101":
            lines = ["{ts},{open},{close},{high},{low},{volume},{amount}".format(**r)
                     for r in fixture()[0]]
        else:
            lines = fixture()[1]["data"]["klines"]
        return {"data": {"code": code, "market": market, "klines": lines}}

    def close(self):
        self.closed = True


class CaptureReliabilityTests(unittest.TestCase):
    def make_market_db(self, directory):
        db = Path(directory) / "formal.sqlite"
        with MarketHistoryStore(db) as store:
            for code in ("600000", "600001"):
                stock = store.upsert_instrument("stock", "SH", code)
                store.upsert_stock_meta(stock, "2026-10-12", dict(name=code, listed_days=500,
                    is_st=False, delisting_risk=False, risk_status="verified", risk_source="eastmoney",
                    risk_as_of="2026-10-12", code=code, exchange="SH", asset_type="stock"))
            for row in fixture()[0] + [{"ts": "2026-10-13"}]:
                for exchange in ("SH", "SZ"):
                    store.upsert_trade_calendar(exchange, row["ts"], True)
        return db

    def fetch(self, session, **kwargs):
        return data.fetch_eastmoney_cutoff_pair(IDENTITY, cutoff=CUTOFF,
            previous_trade_date="2026-10-12", session=session,
            deadline=DEADLINE, clock=lambda: NOW, **kwargs)

    def test_one_transient_disconnect_recovers_without_restarting_other_endpoints(self):
        calls = []
        class Session:
            def get(self, url, **kwargs):
                calls.append(kwargs["params"].copy())
                if len(calls) == 1:
                    raise requests.ConnectionError("remote closed before response")
                return FakeResponse(kwargs["params"])
        try:
            pair = self.fetch(Session())
        except requests.ConnectionError:
            self.fail("one transient disconnect must get one bounded retry")
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual([e["attempts"] for e in pair["source_evidence"]], [2, 1, 1, 1])

    def test_retry_allowance_is_once_per_identity_not_once_per_endpoint(self):
        calls = []
        class Session:
            def get(self, url, **kwargs):
                calls.append(kwargs["params"].copy())
                if len(calls) in (1, 3):
                    raise requests.ConnectionError("remote closed")
                return FakeResponse(kwargs["params"])
        with self.assertRaises(requests.ConnectionError):
            self.fetch(Session())
        self.assertEqual(len(calls), 3)

    def test_certificate_http_and_parse_errors_are_not_retried(self):
        for failure in (requests.exceptions.SSLError("certificate verify failed"),
                        429, 456, 503, "wrong_identity"):
            with self.subTest(failure=failure):
                calls = []
                class Session:
                    def get(self, url, **kwargs):
                        calls.append(kwargs)
                        if isinstance(failure, Exception):
                            raise failure
                        response = FakeResponse(kwargs["params"], failure if isinstance(failure, int) else 200)
                        if failure == "wrong_identity":
                            response.json = lambda: {"data": {"code": "000001", "market": 1}}
                        return response
                with self.assertRaises((requests.exceptions.SSLError, ValueError, data.SourceRateLimited)):
                    self.fetch(Session())
                self.assertEqual(len(calls), 1)

    def test_disconnect_at_deadline_does_not_issue_retry(self):
        current = [NOW]
        calls = []
        class Session:
            def get(self, url, **kwargs):
                calls.append(kwargs)
                current[0] = DEADLINE
                raise requests.ConnectionError("remote closed")
        with self.assertRaises((requests.ConnectionError, TimeoutError)):
            data.fetch_eastmoney_cutoff_pair(IDENTITY, cutoff=CUTOFF,
                previous_trade_date="2026-10-12", session=Session(),
                deadline=DEADLINE, clock=lambda: current[0])
        self.assertEqual(len(calls), 1)

    def test_capture_write_is_byte_equivalent_immutable_and_never_partial(self):
        self.assertTrue(hasattr(data, "_freeze_capture"), "capture needs an atomic create-once writer")
        value = {"cutoff": CUTOFF, "result": {"pair": fixture()[1]}}
        expected = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            data._freeze_capture(path, value)
            self.assertEqual(path.read_bytes(), expected)
            data._freeze_capture(path, value)
            with self.assertRaises(FileExistsError):
                data._freeze_capture(path, {"other": True})
            self.assertEqual(path.read_bytes(), expected)
            other = Path(directory) / "interrupted.json"
            with mock.patch.object(data.os, "link", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    data._freeze_capture(other, value)
            self.assertFalse(other.exists())
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_default_transport_reuses_one_session_per_worker_and_closes_it(self):
        sessions = []
        class Session:
            def __init__(self):
                self.calls, self.closed, self.owner = [], False, None
                sessions.append(self)
            def get(self, url, **kwargs):
                owner = threading.get_ident()
                if self.owner is None:
                    self.owner = owner
                if self.owner != owner:
                    raise AssertionError("HTTP Session was shared across workers")
                self.calls.append(kwargs)
                return FakeResponse(kwargs["params"])
            def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as directory:
            db = self.make_market_db(directory)
            before = db.read_bytes()
            with mock.patch("requests.Session", Session), mock.patch.object(data, "INDEX_NAMES", {"上证指数": "000001"}):
                payload = data.acquire_observation_payload(db, "2026-10-13", deadline=DEADLINE,
                    clock=lambda: NOW, snapshot_dir=Path(directory) / "inputs", max_workers=1)
            self.assertEqual(payload["collection_health"]["acquired"], 2)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(len(sessions[0].calls), 12)
            self.assertFalse(sessions[0].trust_env)
            self.assertTrue(all(s.closed for s in sessions))
            self.assertFalse({s.owner for s in sessions} & {t.ident for t in threading.enumerate()})
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(payload["collection_health"]["source_requests_per_identity_max"], 5)

    def test_failed_capture_retains_actual_attempts_and_is_not_blindly_retried(self):
        calls, sessions = [], []
        class Session:
            def __init__(self):
                self.closed = False
                sessions.append(self)
            def get(self, url, **kwargs):
                calls.append(kwargs)
                raise requests.ConnectionError("remote closed")
            def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as directory:
            db = self.make_market_db(directory)
            source = Path(directory) / "inputs"
            with mock.patch("requests.Session", Session), mock.patch.object(data, "INDEX_NAMES", {"上证指数": "000001"}):
                kwargs = dict(deadline=DEADLINE, clock=lambda: NOW, snapshot_dir=source, max_workers=1)
                first = data.acquire_observation_payload(db, "2026-10-13", **kwargs)
                stored = {p.name: p.read_bytes() for p in source.glob("*.json")}
                second = data.acquire_observation_payload(db, "2026-10-13", **kwargs)
            self.assertEqual(first, second)
            self.assertEqual(first["collection_health"]["status"], "failed")
            self.assertEqual(len(calls), 12)  # Three identities, two bounded attempts in each of two phases.
            self.assertEqual(stored, {p.name: p.read_bytes() for p in source.glob("*.json")})
            for material in stored.values():
                evidence = json.loads(material)["result"]["request_evidence"]
                self.assertEqual(evidence["request_count"], 2)
                self.assertEqual(len(evidence["failures"]), 2)
            self.assertTrue(all(s.closed for s in sessions))

    def test_session_close_error_does_not_skip_other_worker_sessions(self):
        sessions, first_requests = [], threading.Barrier(2)
        class Session:
            def __init__(self):
                self.called = self.close_called = False
                sessions.append(self)
            def get(self, url, **kwargs):
                if not self.called:
                    self.called = True
                    first_requests.wait(timeout=3)
                return FakeResponse(kwargs["params"])
            def close(self):
                self.close_called = True
                if self is sessions[0]:
                    raise RuntimeError("simulated close error")
        with tempfile.TemporaryDirectory() as directory:
            db = self.make_market_db(directory)
            with mock.patch("requests.Session", Session), mock.patch.object(data, "INDEX_NAMES", {"上证指数": "000001"}):
                with self.assertRaises(RuntimeError):
                    data.acquire_observation_payload(db, "2026-10-13", deadline=DEADLINE,
                        clock=lambda: NOW, snapshot_dir=Path(directory) / "inputs", max_workers=2)
            self.assertEqual(len(sessions), 2)
            self.assertTrue(all(s.close_called for s in sessions))


class CalculationBudgetTests(unittest.TestCase):
    execute = runner_tests.ObservationRunnerTests.execute
    evaluate = runner_tests.ObservationRunnerTests.evaluate

    def test_live_acquisition_reserves_thirty_seconds_for_complete_finalization(self):
        seen = []
        def acquire(*args, **kwargs):
            seen.append(kwargs["deadline"])
            return runner_tests.payload_fixture()
        with tempfile.TemporaryDirectory() as directory:
            result = self.execute(directory, acquire=acquire)
            timing = json.loads((Path(directory) / "2026-10-13" / "timings.json").read_text())
        self.assertEqual(result["status"], "empty")
        self.assertEqual(seen, [DEADLINE.replace(minute=57, second=30)])
        self.assertEqual(timing["computation_deadline"], DEADLINE.isoformat())
        self.assertEqual(set(timing["phase_seconds"]), {"input_acquisition", "calculation", "output_validation"})


class BatchRecoveryTests(unittest.TestCase):
    make_market_db = CaptureReliabilityTests.make_market_db

    def setUp(self):
        self.sessions, self.calls, self.sleeps = [], {}, []

    def collect(self, directory, fail, *, clock=lambda: NOW, pause=None):
        test = self
        class Session:
            def __init__(self):
                self.closed = False
                test.sessions.append(self)
            def get(self, url, **kwargs):
                params = kwargs["params"]
                identity = params["secid"]
                test.calls[identity] = test.calls.get(identity, 0) + 1
                error = fail(identity, test.calls[identity])
                if isinstance(error, BaseException):
                    raise error
                if error == "wrong_identity":
                    return FakeResponse(dict(params, secid="1.999999"))
                return FakeResponse(params, error or 200)
            def close(self):
                self.closed = True
        db = Path(directory) / "formal.sqlite"
        if not db.exists():
            db = self.make_market_db(directory)
        with mock.patch("requests.Session", Session), mock.patch.object(data, "INDEX_NAMES", {"上证指数": "000001"}), mock.patch.object(data.elapsed_clock, "sleep", side_effect=pause or self.sleeps.append):
            return data.acquire_observation_payload(db, "2026-10-13", deadline=DEADLINE,
                clock=clock, snapshot_dir=Path(directory) / "inputs", max_workers=1)

    def test_one_independent_recovery_round_preserves_first_failure_and_caps_ten_requests(self):
        def fail(identity, count):
            if identity == "1.600001" and count in (4, 5, 6):
                return requests.ConnectionError("remote closed")
        with tempfile.TemporaryDirectory() as directory:
            payload = self.collect(directory, fail)
            root = Path(directory) / "inputs"
            first = json.loads((root / "stock-SH600001.json").read_text())
            self.assertTrue((root / "recovery-1" / "stock-SH600001.json").exists(),
                "explicit transport failures need one independent recovery capture")
            recovery = json.loads((root / "recovery-1" / "stock-SH600001.json").read_text())
            self.assertEqual(payload["collection_health"]["acquired"], 2)
            self.assertEqual(payload["collection_health"]["status"], "available")
            self.assertTrue(first["result"]["reason"])
            self.assertEqual(first["result"]["request_evidence"]["request_count"], 5)
            self.assertEqual(recovery["result"]["pair"]["request_count"], 5)
            self.assertEqual(self.calls, {"1.000001": 4, "1.600000": 4, "1.600001": 10})
            self.assertEqual(self.sleeps.count(2.0), 1)
            self.assertEqual(payload["collection_health"]["source_requests_per_identity_max"], 10)
            self.assertEqual(payload["collection_health"]["source_recovery"]["recovered"], 1)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")}
            again = self.collect(directory, lambda *a: AssertionError("must not request"))
            self.assertEqual(again, payload)
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")})
            self.assertTrue(all(s.closed for s in self.sessions))

    def test_missing_core_index_can_recover_even_when_stock_coverage_is_full(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.collect(directory, lambda identity,count:
                requests.ConnectionError("remote closed") if identity=="1.000001" and count<=2 else None)
            self.assertEqual(value["collection_health"]["status"], "available")
            self.assertEqual(value["market_indices"]["上证指数"]["status"], "available")
            self.assertEqual(self.calls["1.000001"], 6)

    def test_permanent_disconnect_is_two_frozen_rounds_and_never_a_third(self):
        with tempfile.TemporaryDirectory() as directory:
            fail = lambda *a: requests.ConnectionError("remote closed")
            first = self.collect(directory, fail)
            second = self.collect(directory, fail)
            self.assertEqual(first, second)
            self.assertEqual(first["collection_health"]["status"], "failed")
            self.assertEqual(self.calls, {"1.000001": 4, "1.600000": 4, "1.600001": 4})
            self.assertFalse((Path(directory) / "inputs" / "recovery-2").exists())

    def test_non_retryable_errors_and_rate_limit_never_enter_batch_recovery(self):
        for error in (requests.exceptions.SSLError("certificate error"), 503, 429):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                self.calls.clear();self.sleeps.clear()
                value = self.collect(directory, lambda *a: error)
                self.assertEqual(value["collection_health"]["status"], "failed")
                self.assertFalse((Path(directory) / "inputs" / "recovery-1").exists())
                self.assertNotIn(2.0, self.sleeps)
                if error == 429:
                    again = self.collect(directory, lambda *a: AssertionError("must not request"))
                    self.assertTrue(again["collection_health"]["source_rate_limited"])

    def test_less_than_sixty_seconds_remaining_never_starts_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.collect(directory, lambda *a: requests.ConnectionError("remote closed"),
                clock=lambda: DEADLINE.replace(minute=57, second=1))
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertEqual(self.calls, {"1.000001": 2, "1.600000": 2, "1.600001": 2})
            self.assertNotIn(2.0, self.sleeps)

    def test_successful_retry_then_identity_failure_is_not_a_transport_failure(self):
        def fail(identity, count):
            if identity == "1.600001":
                return requests.ConnectionError("remote closed") if count == 1 else "wrong_identity"
        with tempfile.TemporaryDirectory() as directory:
            value = self.collect(directory, fail)
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertEqual(self.calls["1.600001"], 2)
            self.assertFalse((Path(directory) / "inputs" / "recovery-1").exists())

    def test_verified_response_then_price_basis_failure_is_not_reacquired(self):
        original = data.build_cutoff_stock
        def build(candidate, *args, **kwargs):
            if candidate["code"] == "600001":
                raise ValueError("historical_basis_conflict")
            return original(candidate, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(data, "build_cutoff_stock", side_effect=build):
            value = self.collect(directory, lambda identity,count:
                requests.ConnectionError("remote closed") if identity=="1.600001" and count==1 else None)
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertEqual(self.calls["1.600001"], 5)
            self.assertFalse((Path(directory) / "inputs" / "recovery-1").exists())

    def test_completed_recovery_captures_remain_usable_with_less_than_sixty_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.collect(directory, lambda identity,count:
                requests.ConnectionError("remote closed") if identity=="1.600001" and count<=2 else None)
            calls = dict(self.calls)
            again = self.collect(directory, lambda *a: AssertionError("must use completed captures"),
                clock=lambda: DEADLINE.replace(minute=57, second=40))
            self.assertEqual(again, first)
            self.assertEqual(self.calls, calls)

    def test_recovery_dispatch_interruption_is_durable_and_never_blindly_reissued(self):
        def fail(identity, count):
            if identity == "1.600001":
                return requests.ConnectionError("remote closed") if count <= 2 else SystemExit("interrupt")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit):
                self.collect(directory, fail)
            self.assertEqual(self.calls["1.600001"], 3)
            value = self.collect(directory, lambda *a: AssertionError("must not reissue unknown dispatch"))
            self.assertEqual(self.calls["1.600001"], 3)
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertTrue(any("dispatch_uncertain" in r["reason"] for r in value["collection_health"]["failures"]))

    def test_foundation_failure_does_not_cause_unrepairable_network_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            db = self.make_market_db(directory)
            with MarketHistoryStore(db) as store:
                store.upsert_instrument("stock", "SH", "600002")
            value = self.collect(directory, lambda identity,count:
                requests.ConnectionError("remote closed") if identity=="1.600001" else None)
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertEqual(value["collection_health"]["foundation_missing"], 1)
            self.assertEqual(self.calls["1.600001"], 2)
            self.assertNotIn(2.0, self.sleeps)

    def test_phase_intent_must_be_durable_before_any_source_request(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_market_db(directory)
            with mock.patch("chanlun.intraday_observation_delivery.os.fsync", side_effect=OSError("not durable")):
                with self.assertRaises(OSError):
                    self.collect(directory, lambda *a: None)
            self.assertEqual(self.calls, {})

    def test_primary_dispatch_interruption_cannot_spend_the_first_budget_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit):
                self.collect(directory, lambda identity,count:
                    SystemExit("interrupt") if identity == "1.600001" else None)
            value = self.collect(directory, lambda *a: AssertionError("unknown primary dispatch must not repeat"))
            self.assertEqual(self.calls["1.600001"], 1)
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertTrue(any("dispatch_uncertain" in r["reason"] for r in value["collection_health"]["failures"]))

    def test_recovery_rate_limit_remains_a_source_stop_on_restart(self):
        def fail(identity, count):
            if count <= 2:
                return requests.ConnectionError("remote closed")
            return 456
        with tempfile.TemporaryDirectory() as directory:
            first = self.collect(directory, fail)
            calls = dict(self.calls)
            again = self.collect(directory, lambda *a: AssertionError("persistent rate limit forbids requests"))
            self.assertTrue(first["collection_health"]["source_rate_limited"])
            self.assertTrue(again["collection_health"]["source_rate_limited"])
            self.assertEqual(self.calls, calls)
            self.assertEqual(again["collection_health"]["status"], "failed")

    def test_crossing_deadline_during_cooldown_never_starts_recovery_gets(self):
        current = [NOW]
        def pause(seconds):
            self.sleeps.append(seconds)
            if seconds == 2.0:
                current[0] = DEADLINE
        with tempfile.TemporaryDirectory() as directory:
            value = self.collect(directory, lambda *a: requests.ConnectionError("remote closed"),
                clock=lambda: current[0], pause=pause)
            self.assertEqual(value["collection_health"]["status"], "failed")
            self.assertFalse(value["collection_health"]["source_recovery"]["attempted"])
            self.assertEqual(self.calls, {"1.000001": 2, "1.600000": 2, "1.600001": 2})
