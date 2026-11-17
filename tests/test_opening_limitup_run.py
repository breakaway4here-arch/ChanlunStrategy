from datetime import datetime
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import opening_limitup_run
from tests.test_opening_limitup import evidence


class OpeningRunTests(unittest.TestCase):
    def run_scheduled_at(self, instant, args, *, collector=None):
        now = datetime.fromisoformat(instant)
        output = io.StringIO()
        with mock.patch.object(opening_limitup_run, "datetime") as clock:
            clock.now.side_effect = now.astimezone
            code = opening_limitup_run.main(["--scheduled", *args], collector=collector, stdout=output)
        return code, json.loads(output.getvalue())

    def test_sleep_catchup_is_blocked_with_actual_shanghai_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "calendar.sqlite"
            args = ["--send", "--market-db", str(db)]
            collector = mock.Mock(side_effect=AssertionError("late trigger attempted to collect"))
            for instant in ("2026-11-17T01:41:00+00:00", "2026-11-17T01:48:58+00:00"):
                with self.subTest(instant=instant):
                    code, log = self.run_scheduled_at(instant, args, collector=collector)
                    expected = datetime.fromisoformat(instant).astimezone(opening_limitup_run.SHANGHAI)
                    self.assertEqual(code, 2)
                    self.assertEqual(log, {
                        "delivery_status": "blocked_time_or_calendar",
                        "blocked_reason": "outside_send_window",
                        "guard_checked_at": expected.isoformat(),
                        "trade_date": "2026-11-17",
                    })
            collector.assert_not_called()
            self.assertFalse(db.exists())

    def test_closed_calendar_and_mismatched_date_have_separate_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--send", "--market-db", str(Path(tmp) / "calendar.sqlite")]
            collector = mock.Mock(side_effect=AssertionError("blocked trigger attempted to collect"))
            for instant in ("2026-10-01", "2026-10-10", "2027-01-06"):
                with self.subTest(instant=instant):
                    code, log = self.run_scheduled_at(instant + "T09:40:00+08:00", args, collector=collector)
                    self.assertEqual(code, 2)
                    self.assertEqual(log.get("blocked_reason"), "closed_or_unsupported_calendar")
            code, log = self.run_scheduled_at(
                "2026-11-17T09:40:00+08:00", [*args, "--date", "2026-11-16"], collector=collector
            )
            self.assertEqual(code, 2)
            self.assertEqual(log.get("blocked_reason"), "date_mismatch")
            collector.assert_not_called()

    def test_open_fallback_calendar_runs_collection_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "calendar.sqlite"
            connection = sqlite3.connect(db)
            try:
                connection.execute("CREATE TABLE trade_calendar (trade_date TEXT, exchange TEXT, is_open INTEGER)")
            finally:
                connection.close()
            original = db.read_bytes()
            collected = []
            def collect(day, market_db, *, budget_seconds):
                collected.append((day, market_db, budget_seconds))
                return {"trade_date": day}
            code, log = self.run_scheduled_at(
                "2026-11-17T01:40:02+00:00", ["--market-db", str(db)], collector=collect
            )
            self.assertEqual(code, 0)
            self.assertEqual(log["delivery_status"], "dry_run")
            self.assertEqual(log.get("guard_checked_at"), "2026-11-17T09:40:02+08:00")
            self.assertEqual(collected, [("2026-11-17", str(db), 43.0)])
            self.assertEqual(db.read_bytes(), original)

    def test_offline_default_preview_never_calls_collector_or_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"input.json"; p.write_text(json.dumps(evidence()))
            output = io.StringIO()
            def forbidden(*a, **k): raise AssertionError("no network")
            code = opening_limitup_run.main(["--input", str(p)], collector=forbidden, stdout=output)
            r = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(r["delivery_status"], "dry_run")
            self.assertTrue(r["offline_replay"])
            self.assertEqual(r["result"]["status"], "candidate")

    def test_send_from_offline_input_is_blocked_without_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"input.json"; p.write_text(json.dumps(evidence()))
            output = io.StringIO()
            code = opening_limitup_run.main(["--input", str(p), "--send"], stdout=output)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["delivery_status"], "blocked_offline_input")

    def test_preview_output_does_not_allow_formal_data_directory(self):
        output = io.StringIO()
        code = opening_limitup_run.main(["--output-dir", "docs/data"], stdout=output)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["delivery_status"], "blocked_preview_directory")

    def test_collector_failure_renders_data_insufficient_without_traceback(self):
        output = io.StringIO()
        def failed(*a, **k): raise TimeoutError("secret detail")
        code = opening_limitup_run.main(["--date", "2026-11-03"], collector=failed, stdout=output)
        r = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(r["result"]["status"], "unavailable")
        self.assertIn("数据不足", r["message"])
        self.assertNotIn("secret detail", output.getvalue())

    def test_each_preview_leaf_replaces_symlink_without_following_target(self):
        for leaf in ("evidence.json", "result.json", "message.txt"):
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); p=root/"input.json";p.write_text(json.dumps(evidence()))
                preview=root/"opening-limitup-preview";preview.mkdir()
                target=root/"formal-db-standin.sqlite";target.write_bytes(b"UNCHANGED_STANDIN")
                (preview/leaf).symlink_to(target)
                code=opening_limitup_run.main(["--input",str(p),"--output-dir",str(preview)],stdout=io.StringIO())
                self.assertEqual(target.read_bytes(),b"UNCHANGED_STANDIN")
                self.assertEqual(code,0)
                self.assertFalse((preview/leaf).is_symlink())

    def test_regular_preview_can_be_exported_again_without_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"input.json";preview=root/"opening-limitup-preview"
            e=evidence();p.write_text(json.dumps(e))
            args=["--input",str(p),"--output-dir",str(preview)]
            self.assertEqual(opening_limitup_run.main(args,stdout=io.StringIO()),0)
            e["index"]["sessions"][-1]["open"]="9";p.write_text(json.dumps(e))
            self.assertEqual(opening_limitup_run.main(args,stdout=io.StringIO()),0)
            self.assertEqual(json.loads((preview/"result.json").read_text())["result"]["status"],"no_trade")
            self.assertEqual(sorted(p.name for p in preview.iterdir()),["evidence.json","message.txt","result.json"])


if __name__ == "__main__": unittest.main()
