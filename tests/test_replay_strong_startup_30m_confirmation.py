"""Tests for the read-only strong-startup 30-minute replay harness."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from scripts.replay_strong_startup_30m_confirmation import (
    build_policy_flags,
    connect_read_only,
    dedupe_report_events,
    summarize_outcomes,
)


class TestReadOnlyConnection(unittest.TestCase):

    def test_script_entrypoint_loads_project_imports(self):
        script = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "scripts",
            "replay_strong_startup_30m_confirmation.py",
        )
        completed = subprocess.run(
            [sys.executable, script, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_connection_rejects_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "market.sqlite")
            writable = sqlite3.connect(path)
            writable.execute("CREATE TABLE sample (value INTEGER)")
            writable.commit()
            writable.close()

            readonly = connect_read_only(path)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO sample VALUES (1)")
            finally:
                readonly.close()


class TestReplayCountingSemantics(unittest.TestCase):

    def test_recovery_bundle_remains_shadow_only(self):
        flags = build_policy_flags({
            "ema_bullish_alignment": True,
            "buy_point": None,
            "fresh_yang_pattern": None,
            "recovery_bundle_match": True,
        })

        self.assertTrue(flags["recovery_bundle"])
        self.assertFalse(flags["structure_only"])
        self.assertFalse(flags["proposed"])

    def test_fresh_structure_is_the_only_production_proposal(self):
        flags = build_policy_flags({
            "ema_bullish_alignment": True,
            "buy_point": "二买",
            "fresh_yang_pattern": None,
            "recovery_bundle_match": False,
        })

        self.assertTrue(flags["structure_only"])
        self.assertTrue(flags["proposed"])

    def test_report_rows_and_unique_events_are_separate_counts(self):
        rows = [
            {"trade_date": "2026-08-28", "code": "301629", "source": "picks_pure"},
            {"trade_date": "2026-08-28", "code": "301629", "source": "picks_fusion"},
            {"trade_date": "2026-08-28", "code": "300816", "source": "picks_pure"},
        ]

        events, counts = dedupe_report_events(rows)

        self.assertEqual(counts["report_rows"], 3)
        self.assertEqual(counts["unique_events"], 2)
        self.assertEqual(len(events), 2)

    def test_missing_forward_returns_are_not_counted_as_losses(self):
        events = [
            {"returns": {"t1": 0.03, "t3": -0.02, "t5": None}},
            {"returns": {"t1": None, "t3": 0.04, "t5": None}},
        ]

        summary = summarize_outcomes(events)

        self.assertEqual(summary["t1"]["evaluable"], 1)
        self.assertEqual(summary["t1"]["wins"], 1)
        self.assertEqual(summary["t1"]["losses"], 0)
        self.assertEqual(summary["t1"]["missing"], 1)
        self.assertEqual(summary["t3"]["evaluable"], 2)
        self.assertEqual(summary["t5"]["evaluable"], 0)
        self.assertEqual(summary["t5"]["missing"], 2)


if __name__ == "__main__":
    unittest.main()
