import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from chanlun.preclose_notify import (
    NotificationOutbox,
    publish_preclose_and_notify,
    publish_reconciliation_and_notify,
)
from preclose_run import run_preclose_once
from scripts.preclose_reconcile import run_reconciliation_once
from tests.test_preclose_compare import _formal_report
from tests.test_preclose_pipeline import _components, _config, _market_inputs


TRADE_DATE = "2026-08-27"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")


class MemoryPrecloseWorker:
    """Small transport adapter; Worker contract details stay in JS tests."""

    def __init__(self):
        self.snapshot = None
        self.reconciliation = None
        self.revision = 0

    def put(self, url, *, json, headers, timeout):
        del headers, timeout
        self.revision += 1
        if url.endswith("/snapshot"):
            self.snapshot = dict(json)
        elif url.endswith("/reconciliation"):
            self.reconciliation = dict(json)
        else:
            return FakeResponse({}, status_code=404)
        return FakeResponse({"status": "stored", "revision": self.revision})

    def get(self, url, *, params, headers, timeout):
        del params, headers, timeout
        if url.endswith("/latest") and self.snapshot is not None:
            return FakeResponse(dict(self.snapshot))
        if url.endswith("/reconciliation") and self.reconciliation is not None:
            return FakeResponse(dict(self.reconciliation))
        return FakeResponse({}, status_code=404)


def _fingerprint(path):
    path = Path(path)
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


class PrecloseEndToEndTests(unittest.TestCase):
    def test_frozen_snapshot_publish_reconcile_and_notify_preserve_formal_files(self):
        worker = MemoryPrecloseWorker()
        provider_calls = []

        def post(_url, *, json, timeout):
            del timeout
            provider_calls.append(dict(json))
            return FakeResponse({"success": True, "code": 1000})

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            formal_db = base / "market_history.sqlite"
            formal_ledger = base / "recommendation_ledger.jsonl"
            docs = base / "docs"
            report_path = docs / "data" / (TRADE_DATE + ".json")
            report_path.parent.mkdir(parents=True)
            formal_db.write_bytes(b"formal-market-sentinel")
            formal_ledger.write_bytes(b"formal-ledger-sentinel\n")
            report_path.write_text(
                json.dumps(_formal_report(), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            formal_before = {
                str(path): _fingerprint(path)
                for path in (formal_db, formal_ledger, report_path)
            }

            preclose_root = base / "preclose"
            run = run_preclose_once(
                _market_inputs(),
                config=_config(),
                root=preclose_root,
                components=_components(),
            )
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["snapshot_status"], "available")
            snapshot = json.loads(
                Path(run["snapshot_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(snapshot["expires_at"], "2026-08-27T14:56:30+08:00")
            self.assertLessEqual(snapshot["diagnostics"]["elapsed_seconds"], 120)

            preclose_delivery = publish_preclose_and_notify(
                snapshot,
                api_base="https://preclose.test",
                write_token="write-token",
                wxpusher_app_token="app-token",
                wxpusher_uid="uid-1",
                outbox=NotificationOutbox(preclose_root / "notification-outbox.jsonl"),
                notify=True,
                put=worker.put,
                get=worker.get,
                post=post,
            )
            self.assertTrue(preclose_delivery["publish"]["success"])
            self.assertTrue(preclose_delivery["notifications"]["wxpusher"]["success"])
            self.assertEqual(worker.snapshot["snapshot_id"], snapshot["snapshot_id"])
            self.assertEqual(worker.snapshot["content_hash"], snapshot["content_hash"])

            env_file = base / "preclose.env"
            env_file.write_text(
                "PRECLOSE_API_BASE=https://preclose.test\n"
                "PRECLOSE_WRITE_TOKEN=write-token\n"
                "WXPUSHER_APP_TOKEN=app-token\n"
                "WXPUSHER_UID=uid-1\n",
                encoding="utf-8",
            )
            env_file.chmod(0o600)

            def publisher(reconciliation, **kwargs):
                return publish_reconciliation_and_notify(
                    reconciliation,
                    api_base=kwargs["api_base"],
                    write_token=kwargs["write_token"],
                    wxpusher_app_token=kwargs["wxpusher_app_token"],
                    wxpusher_uid=kwargs["wxpusher_uid"],
                    wecom_webhook=kwargs["wecom_webhook"],
                    outbox=kwargs["outbox"],
                    notify=kwargs["notify"],
                    put=worker.put,
                    get=worker.get,
                    post=post,
                )

            first = run_reconciliation_once(
                TRADE_DATE,
                root=preclose_root,
                docs_dir=docs,
                env_file=env_file,
                notify=True,
                validator=lambda *_args: True,
                publisher=publisher,
            )
            repeated = run_reconciliation_once(
                TRADE_DATE,
                root=preclose_root,
                docs_dir=docs,
                env_file=env_file,
                notify=True,
                validator=lambda *_args: True,
                publisher=publisher,
            )

            self.assertEqual(first["status"], "changed")
            self.assertEqual(first["exit_code"], 0)
            self.assertEqual(repeated["content_hash"], first["content_hash"])
            self.assertEqual(
                repeated["formal_content_hash"], first["formal_content_hash"]
            )
            self.assertEqual(worker.reconciliation["snapshot_id"], snapshot["snapshot_id"])
            self.assertEqual(
                worker.reconciliation["preclose_content_hash"],
                snapshot["content_hash"],
            )
            # One 14:45 notice and one post-close notice; the repeated formal hash
            # is suppressed by the append-only outbox.
            self.assertEqual(len(provider_calls), 2)

            formal_after = {
                str(path): _fingerprint(path)
                for path in (formal_db, formal_ledger, report_path)
            }
            self.assertEqual(formal_after, formal_before)


if __name__ == "__main__":
    unittest.main()
