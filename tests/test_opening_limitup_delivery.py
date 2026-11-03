from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
import time

from chanlun.opening_limitup import evaluate_opening_limitup
from chanlun.opening_limitup_delivery import deliver, render_message
from tests.test_opening_limitup import evidence


class OpeningDeliveryTests(unittest.TestCase):
    def test_b_message_names_the_opening_threshold_without_claiming_red_open(self):
        e=evidence();e["index"]["sessions"][-1]["open"]="9.99"
        m=render_message(evaluate_opening_limitup(e))
        self.assertIn("上证开盘涨幅≥-0.1%",m)
        self.assertNotIn("红开",m)

    def test_b_does_not_reuse_an_a_strategy_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"opening-limitup";root.mkdir(mode=0o700)
            old=root/"2026-11-03.opening-limitup-a-0940-v1.receipt.json"
            old.write_text(json.dumps({"strategy_id":"opening-limitup-a-0940-v1", "trade_date":"2026-11-03", "delivery_status":"provider_accepted"}))
            calls=[]
            r=deliver(evidence(),state_root=root,send=True,sender=lambda *a,**k:calls.append(1) or {"delivery_status":"provider_accepted"},
                      env_loader=lambda:{"WXPUSHER_APP_TOKEN":"token", "WXPUSHER_UID":"UID_One"},
                      testing_clock=lambda:datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
            self.assertEqual(calls,[1])
            self.assertEqual(r["delivery_status"],"provider_accepted")
            self.assertFalse(r["deduplicated"])
            self.assertEqual(r["result"]["strategy_id"],"opening-limitup-b-0940-v1")

    def test_preview_is_default_and_reads_no_credentials_or_state(self):
        def forbidden(*args, **kwargs): raise AssertionError("unexpected side effect")
        r = deliver(evidence(), sender=forbidden, env_loader=forbidden)
        self.assertEqual(r["delivery_status"], "dry_run")
        self.assertIn("条件候选，不代表排队成交", r["message"])
        self.assertIn("价格未核验", r["message"])

    def test_three_message_states_are_distinct(self):
        for status, label in (("candidate", "符合打板条件"), ("no_trade", "不参与"), ("unavailable", "数据不足")):
            r = evaluate_opening_limitup(evidence()); r["status"] = status
            self.assertIn(label, render_message(r))

    def test_environment_short_circuit_preview_uses_plain_chinese(self):
        e = evidence(); e["index"]["sessions"][-1]["open"] = "9"; e.pop("pools"); e.pop("events")
        m = render_message(evaluate_opening_limitup(e))
        self.assertIn("环境未通过，未计算板高和候选", m)
        self.assertNotIn("promotion_unknown", m)
        self.assertNotIn("二板 未知", m)
        self.assertNotIn("条件候选", m)

    def test_deduplicated_receipt_returns_its_frozen_message_not_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = dict(state_root=Path(tmp)/"opening-limitup", send=True,
                          sender=lambda *a, **k:{"delivery_status":"provider_accepted"},
                          env_loader=lambda:{"WXPUSHER_APP_TOKEN":"token", "WXPUSHER_UID":"UID_One"},
                          testing_clock=lambda:datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
            e=evidence();e["index"]["sessions"][-1]["open"]="9"
            first=deliver(e,**kwargs);second=deliver(evidence(),**kwargs)
            self.assertEqual(second["message"], first["message"])
            self.assertEqual(second["result"],first["result"])

    def test_mismatched_frozen_snapshot_never_sends_old_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"opening-limitup"
            kwargs = dict(state_root=root, send=True, sender=lambda *a, **k: {"delivery_status":"provider_accepted"},
                          env_loader=lambda: {}, testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
            self.assertEqual(deliver(evidence(), **kwargs)["delivery_status"], "configuration_unavailable")
            path = next(root.glob("*.snapshot.json")); body = json.loads(path.read_text())
            body["result"]["trade_date"] = "2026-11-02"; path.write_text(json.dumps(body))
            kwargs["env_loader"] = lambda: {"WXPUSHER_APP_TOKEN": "token", "WXPUSHER_UID": "UID_One"}
            self.assertEqual(deliver(evidence(), **kwargs)["delivery_status"], "blocked_state_snapshot")

    def test_post_has_total_deadline_and_unknown_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            def slow(*a, **k): time.sleep(1); return {"delivery_status": "provider_accepted"}
            started = time.monotonic()
            r = deliver(evidence(), state_root=Path(tmp)/"opening-limitup", send=True, sender=slow,
                        env_loader=lambda: {"WXPUSHER_APP_TOKEN": "token", "WXPUSHER_UID": "UID_One"},
                        testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:59.990000+08:00"))
            self.assertEqual(r["delivery_status"], "provider_result_unknown")
            self.assertLess(time.monotonic() - started, 0.8)

    def test_window_is_rechecked_after_durable_state_io_before_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            clocks=iter([datetime.fromisoformat(v) for v in ("2026-11-03T09:40:59+08:00", "2026-11-03T09:40:59+08:00", "2026-11-03T09:41:00+08:00")])
            calls=[]
            r=deliver(evidence(), state_root=Path(tmp)/"opening-limitup", send=True,
                      sender=lambda *a,**k:calls.append(1) or {"delivery_status":"provider_accepted"},
                      env_loader=lambda:{"WXPUSHER_APP_TOKEN":"token", "WXPUSHER_UID":"UID_One"}, testing_clock=lambda:next(clocks))
            self.assertEqual(r["delivery_status"], "blocked_time_or_calendar")
            self.assertEqual(calls,[])

    def test_real_send_clock_guard_cannot_be_overridden_by_offline_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = deliver(evidence(), state_root=Path(tmp)/"opening-limitup", send=True,
                        testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:01+08:00"), offline=True)
            self.assertEqual(r["delivery_status"], "blocked_offline_input")
            self.assertFalse((Path(tmp)/"opening-limitup").exists())

    def test_window_edges_closed_day_and_old_date_block_before_config(self):
        times = ["2026-11-03T09:39:59+08:00", "2026-11-03T09:41:00+08:00", "2026-11-04T09:40:01+08:00", "2026-11-07T09:40:01+08:00"]
        for value in times:
            def forbidden(*a, **k): raise AssertionError("should not send or read config")
            r = deliver(evidence(), send=True, sender=forbidden, env_loader=forbidden,
                        testing_clock=lambda value=value: datetime.fromisoformat(value))
            self.assertEqual(r["delivery_status"], "blocked_time_or_calendar")

    def test_accepted_and_unknown_attempts_are_never_retried(self):
        for outcome in ("provider_accepted", "provider_result_unknown"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                calls = []
                def sender(message, **kwargs):
                    calls.append(kwargs)
                    return {"delivery_status": outcome, "success": outcome == "provider_accepted", "secret": "MUST_NOT_SAVE"}
                kwargs = dict(state_root=Path(tmp)/"opening-limitup", send=True, sender=sender,
                              env_loader=lambda: {"WXPUSHER_APP_TOKEN": "SECRET_TOKEN", "WXPUSHER_UID": "UID_TestOne", "WECOM_WEBHOOK": "SECRET_GROUP"},
                              testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
                first = deliver(evidence(), **kwargs); second = deliver(evidence(), **kwargs)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["uid"], "UID_TestOne")
                self.assertEqual(first["delivery_status"], outcome)
                self.assertTrue(second["deduplicated"])
                body = "".join(p.read_text() for p in Path(tmp).rglob("*.json"))
                self.assertNotIn("SECRET", body); self.assertNotIn("MUST_NOT_SAVE", body)

    def test_sender_exception_is_unknown_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def sender(*a, **k): calls.append(1); raise TimeoutError("SECRET_TOKEN")
            kwargs = dict(state_root=Path(tmp)/"opening-limitup", send=True, sender=sender,
                          env_loader=lambda: {"WXPUSHER_APP_TOKEN": "SECRET_TOKEN", "WXPUSHER_UID": "UID_TestOne"},
                          testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
            self.assertEqual(deliver(evidence(), **kwargs)["delivery_status"], "provider_result_unknown")
            self.assertTrue(deliver(evidence(), **kwargs)["deduplicated"])
            self.assertEqual(len(calls), 1)

    def test_multiple_personal_targets_rejected_without_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            def forbidden(*a, **k): raise AssertionError("must not send")
            r = deliver(evidence(), state_root=Path(tmp)/"opening-limitup", send=True, sender=forbidden,
                        env_loader=lambda: {"WXPUSHER_APP_TOKEN": "token", "WXPUSHER_UID": "UID_a,UID_b"},
                        testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
            self.assertEqual(r["delivery_status"], "configuration_unavailable")

    def test_formal_report_or_other_outbox_directory_rejected(self):
        r = deliver(evidence(), state_root="docs/data/preclose/outbox", send=True, sender=lambda *a, **k: {},
                    testing_clock=lambda: datetime.fromisoformat("2026-11-03T09:40:01+08:00"))
        self.assertEqual(r["delivery_status"], "blocked_state_directory")


if __name__ == "__main__": unittest.main()
