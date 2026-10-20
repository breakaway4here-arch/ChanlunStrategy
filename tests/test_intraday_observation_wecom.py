"""Offline delivery acceptance: real formatting/receipts, stub providers only."""
import hashlib
import io
import json
import multiprocessing
import signal
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import intraday_observation_run as runner
from chanlun import intraday_observation_delivery as delivery
from chanlun.preclose_notify import send_wecom_text
from tests.test_intraday_observation_delivery import report_fixture


NOW = datetime(2026, 10, 13, 14, 58, tzinfo=delivery.SHANGHAI)
WEBHOOK = "https://example.invalid/wecom?key=private-test-key"
ACCEPTED = {"success": True, "provider": "wecom", "provider_accepted": True,
            "delivery_status": "provider_accepted", "business_code": 0}


def snapshot_with_rows(count=0):
    report = report_fixture()
    if count:
        report["picks_pure"] = [{"code": str(600000 + i), "name": "中文🚀样本{:04d}".format(i)}
                                for i in range(count)]
        report["intraday_observation"]["pool_status"]["picks_pure"]["status"] = "available"
    return delivery.build_observation_snapshot(report)


class Clock:
    def __init__(self):
        self.value = NOW
        self.waits = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += timedelta(seconds=seconds)


def concurrent_delivery(path, calls, ready):
    """A finite child; flock must suppress the second provider call."""
    ready.wait(2)
    def sender(*args, **kwargs):
        with calls.get_lock():
            calls.value += 1
        time.sleep(.03)
        return ACCEPTED
    delivery.deliver_wecom_observation(snapshot_with_rows(), outbox_path=path,
        webhook=WEBHOOK, deadline=NOW + timedelta(seconds=20), clock=lambda: NOW, sender=sender)


class WecomObservationTests(unittest.TestCase):
    def send(self, snapshot, path, **kwargs):
        options = dict(webhook=WEBHOOK, deadline=NOW + timedelta(seconds=60), clock=lambda: NOW,
                       sender=lambda *a, **k: ACCEPTED)
        options.update(kwargs)
        return delivery.deliver_wecom_observation(snapshot, outbox_path=path, **options)

    def test_utf8_parts_preserve_every_name_order_and_failure_meaning(self):
        snapshot = snapshot_with_rows(190)
        parts = delivery.format_observation_messages(snapshot, max_bytes=2048)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part.encode("utf-8")) <= 2048 for part in parts))
        text = "\n".join(parts)
        offsets = []
        for row in snapshot["pools"]["picks_pure"]["rows"]:
            item = "{} {}".format(row["name"], row["code"])
            self.assertEqual(text.count(item), 1)
            offsets.append(text.index(item))
        self.assertEqual(offsets, sorted(offsets))
        failed = delivery.build_failure_snapshot("2026-10-13", cutoff="2026-10-13T14:45:00+08:00",
                                                 failure_code="collection_failed")
        self.assertIn("本次计算失败", delivery.format_observation_messages(failed, max_bytes=2048)[0])
        self.assertIn("本次未选出候选", "\n".join(delivery.format_observation_messages(snapshot_with_rows(), max_bytes=2048)))

    def test_wecom_receipt_is_independent_and_binds_webhook_without_secret(self):
        snapshot = snapshot_with_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outbox-wecom.json"
            wx = Path(directory) / "outbox.json"
            wx.write_bytes(b'{"legacy": "untouched"}\n')
            calls = []
            sender = lambda message, **kwargs: calls.append((message, kwargs)) or ACCEPTED
            self.assertTrue(self.send(snapshot, path, sender=sender)["success"])
            self.assertEqual(self.send(snapshot, path, sender=sender)["status"], "already_sent")
            self.assertEqual(len(calls), 1)
            stored = path.read_text()
            receipt = json.loads(stored)
            self.assertEqual(receipt["channel"], "wecom")
            self.assertEqual(receipt["webhook_hash"], hashlib.sha256(WEBHOOK.encode()).hexdigest())
            self.assertNotIn("private-test-key", stored)
            self.assertNotIn(WEBHOOK, stored)
            self.assertEqual(wx.read_bytes(), b'{"legacy": "untouched"}\n')
            with self.assertRaises(ValueError):
                self.send(snapshot, path, webhook=WEBHOOK + "other", sender=sender)
            self.assertEqual(len(calls), 1)

    def test_unknown_or_crash_is_never_resent_and_explicit_rejection_is_truthful(self):
        outcomes = [TimeoutError("secret"), KeyboardInterrupt(),
                    {"success": False, "delivery_status": "provider_rejected", "business_code": 45009}]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "outbox-wecom.json"
                calls = []
                def sender(*args, **kwargs):
                    calls.append(1)
                    if isinstance(outcome, BaseException):
                        raise outcome
                    return outcome
                if isinstance(outcome, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        self.send(snapshot_with_rows(), path, sender=sender)
                    self.assertEqual(json.loads(path.read_text())["parts"]["0"]["state"], "dispatching")
                else:
                    result = self.send(snapshot_with_rows(), path, sender=sender)
                    self.assertFalse(result["success"])
                    if isinstance(outcome, dict):
                        self.assertEqual(result["status"], "provider_rejected")
                self.assertFalse(self.send(snapshot_with_rows(), path, sender=sender)["success"])
                self.assertEqual(calls, [1])
                self.assertNotIn("secret", path.read_text())

    def test_partial_deadline_retains_full_manifest_and_cross_restart_rate(self):
        snapshot = snapshot_with_rows(190)
        clock = Clock()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outbox-wecom.json"
            sender = lambda *a, **k: calls.append(clock()) or ACCEPTED
            result = self.send(snapshot, path, clock=clock, sleep=clock.sleep,
                               deadline=NOW + timedelta(seconds=2), sender=sender)
            self.assertEqual(result["status"], "deadline_exceeded")
            self.assertFalse(result["success"])
            self.assertEqual(len(calls), 1)
            receipt = json.loads(path.read_text())
            self.assertEqual(len(receipt["message_hashes"]), len(delivery.format_observation_messages(snapshot, max_bytes=2048)))
            result = self.send(snapshot, path, clock=clock, sleep=clock.sleep, sender=sender)
            self.assertTrue(result["success"])
            self.assertTrue(all((b-a).total_seconds() >= 4 for a,b in zip(calls,calls[1:])))
            self.assertEqual(len(calls), len(receipt["message_hashes"]))
            self.assertTrue(all(0 < wait <= 4 for wait in clock.waits))

    def test_real_provider_schema_rejected_unknown_and_accepted(self):
        for payload, expected in [({"errcode": 0}, True), ({"errcode": 45009}, False),
                                  ({"errcode": "0"}, False), ({}, False)]:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                response = mock.Mock(status_code=200)
                response.json.return_value = payload
                sender = lambda text, **kwargs: send_wecom_text(text, **kwargs, post=lambda *a, **k: response)
                result = self.send(snapshot_with_rows(), Path(directory)/"receipt.json", sender=sender)
                self.assertEqual(result["success"], expected)

    def test_http_error_bad_json_and_timeout_remain_unknown_or_rejected_without_retry(self):
        import requests
        outcomes = [(429, {"errcode": 45009}, "provider_rejected"),
                    (503, {}, "delivery_uncertain"),
                    (200, ValueError("bad json"), "delivery_uncertain"),
                    (None, requests.exceptions.ReadTimeout("secret"), "delivery_uncertain")]
        for http, payload, status in outcomes:
            with self.subTest(http=http), tempfile.TemporaryDirectory() as directory:
                calls=[]
                response=mock.Mock(status_code=http)
                if http and http >= 400:
                    response.raise_for_status.side_effect=requests.exceptions.HTTPError(response=response)
                if isinstance(payload, ValueError):
                    response.json.side_effect=payload
                else:
                    response.json.return_value=payload
                def post(*a,**k):
                    calls.append(k)
                    if http is None:
                        raise payload
                    return response
                def sender(message,**kwargs):
                    return send_wecom_text(message,**kwargs,post=post)
                path=Path(directory)/"receipt.json"
                first=self.send(snapshot_with_rows(),path,sender=sender)
                repeated=self.send(snapshot_with_rows(),path,sender=sender)
                self.assertEqual(first["status"],status)
                self.assertFalse(repeated["success"])
                self.assertEqual(len(calls),1)
                self.assertTrue(0 < calls[0]["timeout"] <= 10)
                self.assertNotIn("secret",path.read_text())

    def test_two_concurrent_processes_only_dispatch_once(self):
        context = multiprocessing.get_context("fork")
        calls, ready = context.Value("i", 0), context.Event()
        children = []
        with tempfile.TemporaryDirectory() as directory:
            try:
                for _ in range(2):
                    child = context.Process(target=concurrent_delivery,
                                            args=(str(Path(directory)/"receipt.json"), calls, ready))
                    child.start()
                    children.append(child)
                ready.set()
                for child in children:
                    child.join(3)
                    self.assertEqual(child.exitcode, 0)
                self.assertEqual(calls.value, 1)
            finally:
                for child in children:
                    if child.is_alive():
                        child.terminate()
                    child.join(2)
                    self.assertFalse(child.is_alive())


class WecomRoutingTests(unittest.TestCase):
    def route(self, path, **kwargs):
        options = dict(deadline=NOW+timedelta(seconds=60), clock=lambda: NOW,
            outbox_path=path, app_token="fake", uid="fake-uid", wecom_webhook=WEBHOOK,
            wecom_sender=lambda *a, **k: ACCEPTED, sender=lambda *a, **k: {"success": True})
        options.update(kwargs)
        return runner.deliver_before_deadline(snapshot_with_rows(), **options)

    def test_wecom_first_and_old_wx_receipt_bytes_are_untouched(self):
        for old_state in ("sent", "uncertain", "dispatching"):
            with self.subTest(old_state=old_state), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"outbox.json"
                snapshot = snapshot_with_rows()
                old = {"run_id":snapshot["run_id"], "content_hash":snapshot["content_hash"],
                       "input_hash":snapshot["input_hash"], "channel":"wxpusher", "parts":{"0":{"state":old_state}}}
                original = json.dumps(old).encode()
                path.write_bytes(original)
                calls = []
                result = self.route(path, wecom_sender=lambda *a, **k: calls.append("wecom") or ACCEPTED,
                                    sender=lambda *a, **k: calls.append("wx") or {"success":True})
                self.assertEqual(calls, ["wecom"])
                self.assertEqual(path.read_bytes(), original)
                self.assertTrue(result["channels"]["wecom"]["success"])
                self.assertEqual(result["success"], old_state == "sent")

    def test_accepted_then_crash_before_receipt_is_unknown_and_restart_only_sends_wx(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"outbox.json"
            calls=[]
            original=delivery._replace_receipt
            writes=[]
            def interrupted(receipt_path,value):
                writes.append(1)
                if len(writes)==2:
                    raise KeyboardInterrupt()
                original(receipt_path,value)
            def wecom(*a,**k):
                calls.append("wecom")
                return ACCEPTED
            with mock.patch.object(delivery,"_replace_receipt",side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    self.route(path,wecom_sender=wecom)
            sidecar=path.with_name("outbox-wecom.json")
            self.assertEqual(json.loads(sidecar.read_text())["parts"]["0"]["state"],"dispatching")
            result=self.route(path,wecom_sender=wecom,sender=lambda *a,**k:calls.append("wx") or {"success":True})
            self.assertEqual(calls,["wecom","wx"])
            self.assertFalse(result["channels"]["wecom"]["success"])
            self.assertTrue(result["channels"]["wxpusher"]["success"])

    def test_bad_wecom_manifest_blocks_that_route_but_allows_wx(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"outbox.json"
            first=self.route(path,app_token=None,uid=None)
            self.assertTrue(first["success"])
            sidecar=path.with_name("outbox-wecom.json")
            receipt=json.loads(sidecar.read_text())
            receipt["message_hashes"]=["bad"]
            sidecar.write_text(json.dumps(receipt))
            calls=[]
            result=self.route(path,wecom_sender=lambda *a,**k:calls.append("wecom") or ACCEPTED,
                              sender=lambda *a,**k:calls.append("wx") or {"success":True})
            self.assertEqual(calls,["wx"])
            self.assertEqual(result["channels"]["wecom"]["status"],"delivery_failed")
            self.assertFalse(result["success"])

    def test_one_failed_or_unconfigured_route_never_blocks_other(self):
        for failure in ("wecom", "wxpusher"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                calls = []
                def sender(channel):
                    def send(*a, **k):
                        calls.append(channel)
                        if channel == failure:
                            raise TimeoutError("secret")
                        return {"success":True}
                    return send
                result = self.route(Path(directory)/"outbox.json", sender=sender("wxpusher"), wecom_sender=sender("wecom"))
                self.assertEqual(calls, ["wecom", "wxpusher"])
                self.assertFalse(result["success"])
                self.assertTrue(result["channels"]["wxpusher" if failure=="wecom" else "wecom"]["success"])
        with tempfile.TemporaryDirectory() as directory:
            result = self.route(Path(directory)/"outbox.json", app_token=None, uid=None)
            self.assertTrue(result["success"])
            self.assertEqual(result["channels"]["wxpusher"]["status"], "not_configured")
        with tempfile.TemporaryDirectory() as directory:
            result = self.route(Path(directory)/"outbox.json", app_token=None, uid=None, wecom_webhook=None)
            self.assertFalse(result["success"])

    def test_wecom_priority_budget_reserves_only_one_wx_request(self):
        for seconds, expected in [(60,50), (20,10), (8,4)]:
            with self.subTest(seconds=seconds), tempfile.TemporaryDirectory() as directory:
                calls = []
                def sent(*args, **kwargs):
                    calls.append(kwargs["deadline"])
                    return {"success":True,"status":"sent"}
                with mock.patch.object(runner,"deliver_wecom_observation",side_effect=sent), \
                     mock.patch.object(runner,"deliver_observation",side_effect=sent), \
                     mock.patch.object(runner.elapsed_clock,"monotonic",return_value=100):
                    self.route(Path(directory)/"outbox.json", deadline=NOW+timedelta(seconds=seconds))
                self.assertEqual((calls[0]-NOW).total_seconds(),expected)
                self.assertEqual((calls[1]-NOW).total_seconds(),seconds)

    def test_real_wall_clock_stall_gives_other_channel_a_chance_and_restores_alarm(self):
        calls = []
        old_handler = signal.getsignal(signal.SIGALRM)
        def stalled(*args, **kwargs):
            calls.append("wecom")
            time.sleep(.3)
            return ACCEPTED
        with tempfile.TemporaryDirectory() as directory:
            start = time.monotonic()
            result = self.route(Path(directory)/"outbox.json", clock=lambda:datetime.now(delivery.SHANGHAI),
                deadline=datetime.now(delivery.SHANGHAI)+timedelta(seconds=.12),
                wecom_sender=stalled, sender=lambda *a,**k:calls.append("wxpusher") or {"success":True})
            self.assertLess(time.monotonic()-start,.25)
            self.assertEqual(calls,["wecom","wxpusher"])
            self.assertFalse(result["success"])
            self.assertTrue(result["channels"]["wxpusher"]["success"])
        self.assertIs(signal.getsignal(signal.SIGALRM),old_handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0,0))

    def test_deadline_escapes_sender_and_never_starts_unbounded_final_receipt(self):
        calls=[]
        writes=[]
        original=delivery._replace_receipt
        def persist(path,value):
            state=value["parts"]["0"]["state"]
            writes.append((Path(path).name,state))
            if Path(path).name=="outbox-wecom.json" and state=="uncertain":
                time.sleep(.20)
            return original(path,value)
        def stalled(*a,**k):
            calls.append("wecom")
            time.sleep(.30)
            return ACCEPTED
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(delivery,"_replace_receipt",side_effect=persist):
            path=Path(directory)/"outbox.json"
            start=time.monotonic()
            result=self.route(path,clock=lambda:datetime.now(delivery.SHANGHAI),
                deadline=datetime.now(delivery.SHANGHAI)+timedelta(seconds=.12),wecom_sender=stalled,
                sender=lambda *a,**k:calls.append("wx") or {"success":True})
            self.assertEqual(calls,["wecom","wx"])
            self.assertLess(time.monotonic()-start,.20)
            self.assertTrue(result["channels"]["wxpusher"]["success"])
            self.assertNotIn(("outbox-wecom.json","uncertain"),writes)
            sidecar=path.with_name("outbox-wecom.json")
            self.assertEqual(json.loads(sidecar.read_text())["parts"]["0"]["state"],"dispatching")
            self.route(path,wecom_sender=stalled,sender=lambda *a,**k:calls.append("wx") or {"success":True})
            self.assertEqual(calls,["wecom","wx"])

    def test_deadline_during_alarm_arming_restores_previous_handler_and_timer(self):
        actual_set=signal.setitimer
        original_handler=signal.getsignal(signal.SIGALRM)
        original_timer=signal.getitimer(signal.ITIMER_REAL)
        def previous(*a):
            raise AssertionError("previous alarm must remain in the future")
        armed=[]
        def interrupt_arming(which,seconds,*args):
            if seconds > 0 and not armed:
                armed.append(1)
                raise runner._DeliveryDeadline("signal arrived while arming")
            return actual_set(which,seconds,*args)
        signal.signal(signal.SIGALRM,previous)
        actual_set(signal.ITIMER_REAL,5)
        try:
            with mock.patch.object(runner.signal,"setitimer",side_effect=interrupt_arming):
                try:
                    result=runner._deliver_channel(lambda *a,**k:{"success":True},snapshot_with_rows(),
                        deadline=NOW+timedelta(seconds=.001),clock=lambda:NOW,budget=.001)
                except runner._DeliveryDeadline:
                    self.fail("arming deadline escaped the channel cleanup boundary")
            self.assertEqual(result["status"],"deadline_exceeded")
            self.assertIs(signal.getsignal(signal.SIGALRM),previous)
            self.assertTrue(4 < signal.getitimer(signal.ITIMER_REAL)[0] <= 5)
        finally:
            actual_set(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,original_handler)
            if original_timer[0] > 0:
                actual_set(signal.ITIMER_REAL,*original_timer)

    def test_real_process_interrupts_propagate_and_restore_alarm(self):
        previous=signal.getsignal(signal.SIGALRM)
        for interrupt in (KeyboardInterrupt(),SystemExit(7)):
            with self.subTest(interrupt=type(interrupt).__name__):
                def stopped(*a,**k):
                    raise interrupt
                with self.assertRaises(type(interrupt)):
                    runner._deliver_channel(stopped,snapshot_with_rows(),
                        deadline=NOW+timedelta(seconds=1),clock=lambda:NOW,budget=1)
                self.assertIs(signal.getsignal(signal.SIGALRM),previous)
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0,0))

    def test_frozen_clock_does_not_reset_total_wall_budget_or_request_timeout(self):
        calls=[]
        def stalled(*args,**kwargs):
            calls.append(("wecom",kwargs["timeout"]))
            time.sleep(.3)
            return ACCEPTED
        def wx(*args,**kwargs):
            calls.append(("wx",kwargs["timeout"]))
            return {"success":True}
        with tempfile.TemporaryDirectory() as directory:
            start=time.monotonic()
            result=self.route(Path(directory)/"outbox.json",deadline=NOW+timedelta(seconds=.12),
                              wecom_sender=stalled,sender=wx)
            self.assertLess(time.monotonic()-start,.25)
            self.assertEqual([item[0] for item in calls],["wecom","wx"])
            self.assertTrue(all(0 < item[1] <= .061 for item in calls))
            self.assertFalse(result["success"])

    def test_expired_deadline_never_opens_either_outbox_or_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"outbox.json"
            def prohibited(*a,**k):
                raise AssertionError("no provider call after cutoff")
            result=self.route(path,deadline=NOW,sender=prohibited,wecom_sender=prohibited)
            self.assertFalse(result["success"])
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_main_passes_existing_optional_webhook_without_reacquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"intraday-observation"
            with mock.patch.object(runner,"_now",return_value=NOW), \
                 mock.patch.object(runner,"_run_worker",return_value=snapshot_with_rows()), \
                 mock.patch.object(runner,"should_start_scheduled",return_value=True), \
                 mock.patch("chanlun.preclose_notify.load_preclose_env",return_value={
                     "WXPUSHER_APP_TOKEN":"fake", "WXPUSHER_UID":"fake-uid", "WECOM_BOT_WEBHOOK":WEBHOOK}), \
                 mock.patch.object(runner,"deliver_before_deadline",return_value={"success":True}) as deliver, \
                 redirect_stdout(io.StringIO()):
                result=runner.main(["--scheduled","--send","--root",str(root),
                    "--formal-market-db",str(Path(directory)/"protected.sqlite")])
            self.assertEqual(result,0)
            self.assertIn("wecom_webhook",deliver.call_args.kwargs,
                          "the real scheduled entry must give the configured WeCom route a chance")
            self.assertEqual(deliver.call_args.kwargs["wecom_webhook"],WEBHOOK)


if __name__ == "__main__":
    unittest.main()
