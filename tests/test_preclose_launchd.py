import hashlib
import json
import plistlib
import re
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
    "f5821333f4c04be36f4bbb2d79fd3dc5a5463114ae2805dd503a51a636071c51"
)
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "chanlun-preclose-runbook.md"


def _load_plist(name):
    with (ROOT / "launchd" / name).open("rb") as source:
        return plistlib.load(source)


class PrecloseLaunchdTests(unittest.TestCase):
    def test_runbook_is_present_and_keeps_safe_production_rollback_contract(self):
        self.assertEqual(
            RUNBOOK_PATH.relative_to(ROOT).as_posix(),
            "docs/runbooks/chanlun-preclose-runbook.md",
        )
        self.assertTrue(RUNBOOK_PATH.is_file())
        text = RUNBOOK_PATH.read_text(encoding="utf-8")
        self.assertIn("/api/preclose/latest?date=", text)
        self.assertIn("PRECLOSE_ENABLED=false", text)
        self.assertIn("Durable Object", text)
        self.assertIn("向前部署", text)
        self.assertIn("不承诺旧版本简单 rollback 一定可用", text)
        self.assertIn("=> [redacted]", text)
        self.assertIn("cd cloudflare/preclose-worker", text)
        self.assertIn("npx wrangler secret list", text)
        for evidence_name in (
            "failure.json",
            "timings.json",
            "run-evidence.jsonl",
            "reconciliation-polls.jsonl",
            "reconciliation-failure.json",
        ):
            self.assertIn(evidence_name, text)
        self.assertIn("15:35 到点不再启动", text)
        self.assertNotIn("npx wrangler secret put PRE_CLOSE_WRITE_TOKEN", text)
        self.assertNotIn("npx wrangler --cwd cloudflare/preclose-worker", text)
        self.assertNotRegex(
            text,
            re.compile(
                r"(?m)^\s*(?:/bin/)?launchctl print\b(?!.*\|\s*/usr/bin/awk).*$"
            ),
        )

    def test_preclose_runs_each_weekday_at_1445_from_absolute_wrapper(self):
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
            {(weekday, 14, 45) for weekday in range(1, 6)},
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
        budgets = []
        sleeps = []

        def runner(trade_date, **kwargs):
            calls.append(trade_date)
            budgets.append(kwargs.get("deadline_seconds"))
            return {"status": "formal_pending", "exit_code": 0}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "preclose"
            result = poll_reconciliation(
                "2026-08-28",
                poll_seconds=30,
                stop_at="15:35:00",
                runner=runner,
                now=lambda: next(clock),
                sleep=sleeps.append,
                root=root,
            )
            evidence_path = (
                root / "2026-08-28" / "reconciliation-polls.jsonl"
            )
            evidence = [
                json.loads(line)
                for line in evidence_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["status"], "formal_pending_timeout")
        self.assertEqual(calls, ["2026-08-28"])
        self.assertEqual(budgets, [15.0])
        self.assertEqual(sleeps, [15.0])
        self.assertEqual(
            [row["status"] for row in evidence],
            ["formal_pending", "formal_pending_timeout"],
        )
        self.assertEqual(
            [row["observed_at"] for row in evidence],
            [
                "2026-08-28T15:34:45+08:00",
                "2026-08-28T15:35:00+08:00",
            ],
        )

    def test_reconciliation_poll_never_starts_at_the_hard_stop(self):
        from scripts.preclose_reconcile import poll_reconciliation

        cn_timezone = timezone(timedelta(hours=8))
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "preclose"
            result = poll_reconciliation(
                "2026-08-28",
                poll_seconds=30,
                stop_at="15:35:00",
                runner=lambda *_args, **_kwargs: calls.append(True),
                now=lambda: datetime(
                    2026, 8, 28, 15, 35, 0, tzinfo=cn_timezone
                ),
                sleep=lambda _seconds: None,
                root=root,
            )

        self.assertEqual(result["status"], "formal_pending_timeout")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
