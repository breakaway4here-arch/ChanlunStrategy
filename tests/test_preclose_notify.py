import json
import os
import tempfile
import unittest
from pathlib import Path

from chanlun.preclose_notify import (
    NotificationOutbox,
    format_reconciliation_message,
    format_preclose_message,
    load_preclose_env,
    publish_preclose_and_notify,
    publish_reconciliation,
    publish_preclose_snapshot,
    send_reconciliation_notifications,
    send_wecom_text,
    send_wxpusher_message,
)


def _snapshot():
    return {
        "trade_date": "2026-08-27",
        "snapshot_id": "preclose:2026-08-27:abc",
        "content_hash": "a" * 64,
        "status": "available",
        "expires_at": "2026-08-27T14:56:30+08:00",
        "pools": {
            "main": [
                {"code": "300998", "name": "宁波方正", "reference_price": 26.86},
                {"code": "600001", "name": "第四只不展示", "reference_price": 10.0},
                {"code": "600002", "name": "第二只", "reference_price": 11.0},
                {"code": "600003", "name": "第三只", "reference_price": 12.0},
            ],
            "h4_t3": [],
            "acceleration": [
                {"code": "002328", "name": "新朋股份", "reference_price": 7.61}
            ],
        },
        "diagnostics": {"reason_code": "internal"},
        "psy12": {"score": 50},
        "news": ["internal"],
        "score": 99,
    }


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class PrecloseNotifyTests(unittest.TestCase):
    def test_simple_message_contract_and_three_per_pool_cap(self):
        message = format_preclose_message(_snapshot())

        self.assertEqual(message, "\n".join([
            "【14:47预跑】14:56:30前有效",
            "主推：宁波方正 300998｜参考26.86；第四只不展示 600001｜参考10.00；第二只 600002｜参考11.00",
            "H4 T+3：本期未选出推荐票",
            "加速：新朋股份 002328｜参考7.61",
            "14:57后不再下单",
        ]))
        self.assertNotIn("第三只", message)
        for forbidden in (
            "评分", "PSY", "新闻", "reason_code", "校验", "仓位", "最高可买价", "internal"
        ):
            self.assertNotIn(forbidden, message)

    def test_empty_failed_and_timeout_all_use_one_empty_message(self):
        for status in ("empty", "failed", "deadline_exceeded"):
            snapshot = _snapshot()
            snapshot["status"] = status
            snapshot["pools"] = {"main": [], "h4_t3": [], "acceleration": []}
            self.assertEqual(
                format_preclose_message(snapshot),
                "【14:47预跑】\n本期未选出推荐票",
            )

    def test_wxpusher_requires_http_and_business_success(self):
        calls = []

        def success_post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(payload={"success": True, "code": 1000})

        result = send_wxpusher_message(
            "message", app_token="app-token", uid="uid-1", post=success_post
        )
        self.assertTrue(result["success"])
        self.assertNotIn("app-token", json.dumps(result))
        self.assertEqual(calls[0][1]["json"]["uids"], ["uid-1"])

        for response in (
            FakeResponse(status_code=500, payload={"success": True}),
            FakeResponse(payload={"success": False, "code": 1001}),
        ):
            result = send_wxpusher_message(
                "message",
                app_token="app-token",
                uid="uid-1",
                post=lambda *args, response=response, **kwargs: response,
            )
            self.assertFalse(result["success"])

    def test_optional_wecom_requires_errcode_zero(self):
        success = send_wecom_text(
            "message",
            webhook="https://wecom.example/hook",
            post=lambda *args, **kwargs: FakeResponse(payload={"errcode": 0}),
        )
        failed = send_wecom_text(
            "message",
            webhook="https://wecom.example/hook",
            post=lambda *args, **kwargs: FakeResponse(payload={"errcode": 40013}),
        )
        self.assertTrue(success["success"])
        self.assertFalse(failed["success"])

    def test_notification_outbox_records_failure_without_changing_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outbox.jsonl"
            snapshot = _snapshot()
            before = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            outbox = NotificationOutbox(path)
            outbox.record(
                content_hash=snapshot["content_hash"],
                channel="wxpusher",
                success=False,
                response={"error": "provider_failure"},
            )

            self.assertEqual(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), before)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["success"])
            self.assertFalse(outbox.was_successful(snapshot["content_hash"], "wxpusher"))

    def test_env_file_must_be_owned_by_current_user_and_mode_0600(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preclose.env"
            path.write_text(
                "PRECLOSE_API_BASE=https://preclose.example\n"
                "PRECLOSE_WRITE_TOKEN=write-token\n"
                "WXPUSHER_APP_TOKEN=app-token\n"
                "WXPUSHER_UID=uid-1\n",
                encoding="utf-8",
            )
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                load_preclose_env(path)

            path.chmod(0o600)
            values = load_preclose_env(path)
            self.assertEqual(values["WXPUSHER_UID"], "uid-1")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_publish_puts_then_gets_and_requires_same_snapshot_hash(self):
        snapshot = _snapshot()
        calls = []

        def put(url, **kwargs):
            calls.append(("put", url, kwargs))
            return FakeResponse(status_code=201, payload={"status": "created", "revision": 1})

        def get(url, **kwargs):
            calls.append(("get", url, kwargs))
            return FakeResponse(payload={
                "snapshot_id": snapshot["snapshot_id"],
                "content_hash": snapshot["content_hash"],
            })

        result = publish_preclose_snapshot(
            snapshot,
            api_base="https://preclose.example/",
            write_token="secret-write-token",
            put=put,
            get=get,
        )

        self.assertTrue(result["success"])
        self.assertEqual([call[0] for call in calls], ["put", "get"])
        self.assertEqual(calls[1][2]["params"], {"date": "2026-08-27"})
        self.assertNotIn("secret-write-token", json.dumps(result))

    def test_worker_readback_mismatch_prevents_all_notifications(self):
        snapshot = _snapshot()
        provider_calls = []

        def put(*args, **kwargs):
            return FakeResponse(status_code=201, payload={"status": "created", "revision": 1})

        def get(*args, **kwargs):
            return FakeResponse(payload={
                "snapshot_id": snapshot["snapshot_id"],
                "content_hash": "b" * 64,
            })

        with tempfile.TemporaryDirectory() as temp_dir:
            result = publish_preclose_and_notify(
                snapshot,
                api_base="https://preclose.example",
                write_token="write-token",
                wxpusher_app_token="app-token",
                wxpusher_uid="uid-1",
                outbox=NotificationOutbox(Path(temp_dir) / "outbox.jsonl"),
                put=put,
                get=get,
                post=lambda *args, **kwargs: provider_calls.append((args, kwargs)),
            )

        self.assertFalse(result["publish"]["success"])
        self.assertEqual(result["notifications"], {})
        self.assertEqual(provider_calls, [])

    def test_reconciliation_messages_cover_unchanged_changed_and_pending(self):
        unchanged = {
            "trade_date": "2026-08-27",
            "formal_content_hash": "f" * 64,
            "status": "unchanged",
            "pools": {
                "main": {"retained": [{"name": "A股"}, {"name": "B股"}]},
                "h4_t3": {"retained": [{"name": "H股"}]},
                "acceleration": {"retained": [{"name": "加速股"}]},
            },
        }
        self.assertEqual(format_reconciliation_message(unchanged), "\n".join([
            "【盘后复核】",
            "正式结果与14:47预跑一致",
            "主推2只｜H4 T+3 1只｜加速1只",
        ]))

        changed = {
            "trade_date": "2026-08-27",
            "formal_content_hash": "e" * 64,
            "status": "changed",
            "pools": {
                "main": {
                    "retained": [{"name": "宁波方正"}],
                    "added_after_close": [{"name": "新朋股份"}],
                    "removed_after_close": [{"name": "A股"}],
                },
                "h4_t3": {"retained": [], "added_after_close": [], "removed_after_close": []},
                "acceleration": {"added_after_close": [{"name": "B股"}]},
            },
        }
        self.assertEqual(format_reconciliation_message(changed), "\n".join([
            "【盘后复核】与14:47预跑有变化",
            "主推：保留 宁波方正｜正式新增 新朋股份｜预跑有、正式无 A股",
            "H4 T+3：无变化",
            "加速：正式新增 B股",
        ]))
        pending = dict(changed, status="formal_pending")
        self.assertEqual(format_reconciliation_message(pending), "\n".join([
            "【盘后复核】",
            "今日正式结果尚未生成，暂不继续参考预跑清单",
        ]))

    def test_reconciliation_idempotency_uses_trade_date_formal_hash_and_channel(self):
        reconciliation = {
            "trade_date": "2026-08-27",
            "snapshot_id": "preclose:2026-08-27:abc",
            "preclose_content_hash": "a" * 64,
            "formal_content_hash": "f" * 64,
            "status": "unchanged",
            "pools": {
                "main": {"retained": []},
                "h4_t3": {"retained": []},
                "acceleration": {"retained": []},
            },
        }
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            outbox = NotificationOutbox(Path(temp_dir) / "outbox.jsonl")

            def post(*args, **kwargs):
                calls.append((args, kwargs))
                return FakeResponse(payload={"success": True, "code": 1000})

            first = send_reconciliation_notifications(
                reconciliation,
                outbox=outbox,
                wxpusher_app_token="app-token",
                wxpusher_uid="uid-1",
                post=post,
            )
            repeated = send_reconciliation_notifications(
                reconciliation,
                outbox=outbox,
                wxpusher_app_token="app-token",
                wxpusher_uid="uid-1",
                post=post,
            )
            changed_hash = dict(reconciliation, formal_content_hash="e" * 64)
            changed = send_reconciliation_notifications(
                changed_hash,
                outbox=outbox,
                wxpusher_app_token="app-token",
                wxpusher_uid="uid-1",
                post=post,
            )

        self.assertTrue(first["wxpusher"]["success"])
        self.assertEqual(repeated["wxpusher"]["status"], "already_sent")
        self.assertTrue(changed["wxpusher"]["success"])
        self.assertEqual(len(calls), 2)

    def test_reconciliation_publish_retries_changed_hash_with_worker_revision(self):
        reconciliation = {
            "trade_date": "2026-08-27",
            "snapshot_id": "preclose:2026-08-27:abc",
            "content_hash": "c" * 64,
            "preclose_content_hash": "a" * 64,
            "formal_content_hash": "f" * 64,
            "status": "changed",
            "pools": {},
        }
        calls = []

        def put(url, **kwargs):
            calls.append((url, kwargs))
            if len(calls) == 1:
                return FakeResponse(
                    status_code=412,
                    payload={"error": "precondition failed", "revision": 2},
                )
            return FakeResponse(
                status_code=200,
                payload={"status": "updated", "revision": 3},
            )

        def get(*_args, **_kwargs):
            return FakeResponse(payload={
                "content_hash": reconciliation["content_hash"],
                "preclose_content_hash": reconciliation["preclose_content_hash"],
                "formal_content_hash": reconciliation["formal_content_hash"],
            })

        result = publish_reconciliation(
            reconciliation,
            api_base="https://preclose.example",
            write_token="write-token",
            put=put,
            get=get,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["revision"], 3)
        self.assertNotIn("if-match", calls[0][1]["headers"])
        self.assertEqual(calls[1][1]["headers"]["if-match"], '"2"')


if __name__ == "__main__":
    unittest.main()
