import hashlib
import plistlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = (
    "/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime"
)
PRECLOSE_LABEL = "com.breakaway4here.chanlun-preclose"
RECONCILE_LABEL = "com.breakaway4here.chanlun-preclose-reconcile"
DAILY_RUN_BASELINE_SHA256 = (
    "a0c5a68f3c67b6e0d5e632a5348ac362b73a7b1247dc9d38030bfaf875e1fbf0"
)


def _load_plist(name):
    with (ROOT / "launchd" / name).open("rb") as source:
        return plistlib.load(source)


class PrecloseLaunchdTests(unittest.TestCase):
    def test_preclose_runs_each_weekday_at_1447_from_absolute_wrapper(self):
        plist = _load_plist(PRECLOSE_LABEL + ".plist")
        self.assertEqual(plist["Label"], PRECLOSE_LABEL)
        self.assertEqual(plist["WorkingDirectory"], PRODUCTION_ROOT)
        self.assertEqual(plist["ProgramArguments"], [
            "/bin/zsh",
            PRODUCTION_ROOT + "/scripts/preclose_run.sh",
        ])
        schedule = plist["StartCalendarInterval"]
        self.assertEqual(
            {(row["Weekday"], row["Hour"], row["Minute"]) for row in schedule},
            {(weekday, 14, 47) for weekday in range(1, 6)},
        )
        self.assertFalse(plist["RunAtLoad"])

    def test_reconciliation_runs_independently_at_1505_and_polls_to_1535(self):
        plist = _load_plist(RECONCILE_LABEL + ".plist")
        self.assertEqual(plist["Label"], RECONCILE_LABEL)
        self.assertEqual(plist["WorkingDirectory"], PRODUCTION_ROOT)
        self.assertEqual(plist["ProgramArguments"], [
            "/bin/zsh",
            PRODUCTION_ROOT + "/scripts/preclose_reconcile.sh",
        ])
        schedule = plist["StartCalendarInterval"]
        self.assertEqual(
            {(row["Weekday"], row["Hour"], row["Minute"]) for row in schedule},
            {(weekday, 15, 5) for weekday in range(1, 6)},
        )
        wrapper = (ROOT / "scripts" / "preclose_reconcile.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--poll-seconds 30", wrapper)
        self.assertIn("--stop-at 15:35:00", wrapper)

    def test_jobs_have_distinct_logs_locks_and_no_formal_dependency(self):
        preclose = _load_plist(PRECLOSE_LABEL + ".plist")
        reconcile = _load_plist(RECONCILE_LABEL + ".plist")
        self.assertNotEqual(preclose["Label"], reconcile["Label"])
        self.assertNotEqual(
            preclose["StandardOutPath"], reconcile["StandardOutPath"]
        )
        self.assertNotEqual(
            preclose["StandardErrorPath"], reconcile["StandardErrorPath"]
        )
        script_text = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "scripts/preclose_run.sh",
                "scripts/preclose_reconcile.sh",
                "preclose_run.py",
                "scripts/preclose_reconcile.py",
            )
        )
        self.assertNotIn("daily_run.sh", script_text)
        self.assertIn("run.lock", script_text)
        self.assertIn("reconcile.lock", script_text)
        daily = (ROOT / "daily_run.sh").read_bytes()
        self.assertEqual(hashlib.sha256(daily).hexdigest(), DAILY_RUN_BASELINE_SHA256)

    def test_plists_do_not_embed_credentials_or_interactive_shell_profiles(self):
        for label in (PRECLOSE_LABEL, RECONCILE_LABEL):
            path = ROOT / "launchd" / (label + ".plist")
            text = path.read_text(encoding="utf-8")
            for forbidden in (
                "PRECLOSE_WRITE_TOKEN",
                "WXPUSHER_APP_TOKEN",
                "WXPUSHER_UID",
                "WECOM_BOT_WEBHOOK",
                "Bearer ",
                "-l",
            ):
                self.assertNotIn(forbidden, text)

    def test_jobs_drop_inherited_research_and_llm_credentials_before_runtime(self):
        forbidden_runtime_keys = (
            "IWENCAI_API_KEY",
            "IWENCAI_BASE_URL",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
        )
        for label in (PRECLOSE_LABEL, RECONCILE_LABEL):
            plist = _load_plist(label + ".plist")
            environment = plist["EnvironmentVariables"]
            for key in forbidden_runtime_keys:
                self.assertIn(key, environment)
                self.assertEqual(environment[key], "")

        for wrapper_name in ("preclose_run.sh", "preclose_reconcile.sh"):
            wrapper = (ROOT / "scripts" / wrapper_name).read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "unset " + " ".join(forbidden_runtime_keys),
                wrapper,
            )

    def test_installer_validates_refuses_overwrite_bootstraps_and_reads_back(self):
        script = (ROOT / "scripts" / "install_preclose_launchd.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('PRODUCTION_ROOT="{}"'.format(PRODUCTION_ROOT), script)
        self.assertIn('[[ "$REPO_DIR" != "$PRODUCTION_ROOT" ]]', script)
        self.assertIn("plutil -lint", script)
        self.assertIn("already exists", script)
        self.assertIn("launchctl bootstrap", script)
        self.assertIn("launchctl print", script)
        self.assertIn("sanitize_launchctl_print", script)
        self.assertIn("=> [redacted]", script)
        self.assertNotIn("launchctl load", script)
        self.assertNotIn("WXPUSHER_APP_TOKEN=", script)

    def test_schedule_guard_skips_weekends_holidays_and_closed_calendar_rows(self):
        from chanlun.preclose_schedule import is_trading_day

        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "market.sqlite"
            connection = sqlite3.connect(str(db))
            connection.execute(
                "CREATE TABLE trade_calendar ("
                "exchange TEXT, trade_date TEXT, is_open INTEGER)"
            )
            connection.execute(
                "INSERT INTO trade_calendar VALUES ('SH', '2026-08-31', 0)"
            )
            connection.commit()
            connection.close()

            self.assertFalse(is_trading_day("2026-08-29", db))
            self.assertFalse(is_trading_day("2026-10-01", db))
            self.assertFalse(is_trading_day("2026-08-31", db))
            self.assertTrue(is_trading_day("2026-08-28", db))

    def test_reconciliation_poll_stops_exactly_at_1535(self):
        from scripts.preclose_reconcile import poll_reconciliation

        cn_timezone = timezone(timedelta(hours=8))
        clock = iter([
            datetime(2026, 8, 28, 15, 34, 45, tzinfo=cn_timezone),
            datetime(2026, 8, 28, 15, 35, 0, tzinfo=cn_timezone),
        ])
        calls = []
        sleeps = []

        def runner(trade_date, **_kwargs):
            calls.append(trade_date)
            return {"status": "formal_pending", "exit_code": 0}

        result = poll_reconciliation(
            "2026-08-28",
            poll_seconds=30,
            stop_at="15:35:00",
            runner=runner,
            now=lambda: next(clock),
            sleep=sleeps.append,
        )

        self.assertEqual(result["status"], "formal_pending_timeout")
        self.assertEqual(calls, ["2026-08-28", "2026-08-28"])
        self.assertEqual(sleeps, [15.0])


if __name__ == "__main__":
    unittest.main()
