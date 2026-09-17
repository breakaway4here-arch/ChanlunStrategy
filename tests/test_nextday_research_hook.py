import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT_DIR / "scripts" / "nextday_research_hook.py"
SPEC = importlib.util.spec_from_file_location("nextday_research_hook", HOOK_PATH)
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class NextdayResearchHookTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.report = self.root / "2026-09-17.json"
        self.report.write_text("{}", encoding="utf-8")
        self.db = self.root / "market.sqlite"
        self.output_dir = self.root / "runs"

    def _call_main(self, *, output_dir=None, as_of="2026-09-17"):
        args = ["--report", str(self.report), "--db", str(self.db)]
        if output_dir is not None:
            args.extend(["--output-dir", str(output_dir)])
        if as_of is not None:
            args.extend(["--as-of", as_of])
        return HOOK.main(args)

    def test_success_calls_explicit_cli_with_paths_and_60_second_bound(self):
        child = subprocess.CompletedProcess([], 0, stdout="done", stderr="")
        with mock.patch.object(HOOK, "PROJECT_ROOT", self.root), mock.patch.object(
            HOOK.subprocess, "run", return_value=child
        ) as run_child, contextlib.redirect_stderr(io.StringIO()):
            status = self._call_main(output_dir=self.output_dir)

        self.assertEqual(0, status)
        command = run_child.call_args.args[0]
        self.assertEqual(str((self.root / "scripts" / "nextday_research.py").resolve()), command[1])
        self.assertEqual(str(self.report.resolve()), command[command.index("--report") + 1])
        self.assertEqual(str(self.output_dir.resolve()), command[command.index("--output-dir") + 1])
        self.assertEqual(str(self.db.resolve()), command[command.index("--db") + 1])
        self.assertEqual("2026-09-17", command[command.index("--as-of") + 1])
        self.assertEqual(60, run_child.call_args.kwargs["timeout"])
        self.assertTrue(run_child.call_args.kwargs["capture_output"])
        self.assertEqual(str(self.root), run_child.call_args.kwargs["cwd"])
        status = json.loads((self.output_dir / "last_hook_status.json").read_text(encoding="utf-8"))
        self.assertEqual("completed", status["status"])
        self.assertEqual("2026-09-17", status["as_of"])

    def test_cli_failure_is_logged_and_does_not_fail_the_hook(self):
        child = subprocess.CompletedProcess([], 7, stdout="", stderr="research failed")
        output = io.StringIO()
        with mock.patch.object(HOOK, "PROJECT_ROOT", self.root), mock.patch.object(
            HOOK.subprocess, "run", return_value=child
        ), contextlib.redirect_stderr(output):
            status = self._call_main(output_dir=self.output_dir)

        self.assertEqual(0, status)
        self.assertIn("status=failed", output.getvalue())
        self.assertIn("exit_code=7", output.getvalue())
        self.assertIn("research failed", output.getvalue())
        selections = self.output_dir / "2026-09-17.json"
        selections.write_text("frozen selections", encoding="utf-8")
        child = subprocess.CompletedProcess([], 5, stdout="", stderr="later failure")
        with mock.patch.object(HOOK, "PROJECT_ROOT", self.root), mock.patch.object(
            HOOK.subprocess, "run", return_value=child
        ), contextlib.redirect_stderr(io.StringIO()):
            status = self._call_main(output_dir=self.output_dir)
        self.assertEqual(0, status)
        persisted = json.loads((self.output_dir / "last_hook_status.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", persisted["status"])
        self.assertEqual(5, persisted["exit_code"])
        self.assertEqual("frozen selections", selections.read_text(encoding="utf-8"))

    def test_timeout_is_logged_and_does_not_fail_the_hook(self):
        timeout = subprocess.TimeoutExpired(
            cmd=["nextday_research.py"], timeout=60, output="partial", stderr="timed out"
        )
        output = io.StringIO()
        with mock.patch.object(HOOK, "PROJECT_ROOT", self.root), mock.patch.object(
            HOOK.subprocess, "run", side_effect=timeout
        ), contextlib.redirect_stderr(output):
            status = self._call_main(output_dir=self.output_dir)

        self.assertEqual(0, status)
        self.assertIn("status=timeout", output.getvalue())
        self.assertIn("timeout_seconds=60", output.getvalue())
        persisted = json.loads((self.output_dir / "last_hook_status.json").read_text(encoding="utf-8"))
        self.assertEqual("timeout", persisted["status"])
        self.assertEqual(60, persisted["timeout_seconds"])

    def test_status_write_failure_stays_optional(self):
        output_path = self.root / "not-a-directory"
        output_path.write_text("preserve", encoding="utf-8")
        child = subprocess.CompletedProcess([], 0, stdout="done", stderr="")
        output = io.StringIO()
        with mock.patch.object(HOOK, "PROJECT_ROOT", self.root), mock.patch.object(
            HOOK.subprocess, "run", return_value=child
        ), contextlib.redirect_stderr(output):
            status = self._call_main(output_dir=output_path)

        self.assertEqual(0, status)
        self.assertIn("status_write_failed", output.getvalue())
        self.assertEqual("preserve", output_path.read_text(encoding="utf-8"))

    def test_default_output_dir_resolves_the_shared_cache_symlink(self):
        canonical_root = self.root / "canonical"
        cache_target = canonical_root / ".cache" / "chanlun"
        cache_target.mkdir(parents=True)
        runtime_root = self.root / "runtime"
        (runtime_root / ".cache").mkdir(parents=True)
        (runtime_root / ".cache" / "chanlun").symlink_to(
            cache_target, target_is_directory=True
        )

        with mock.patch.object(HOOK, "PROJECT_ROOT", runtime_root), mock.patch.dict(
            os.environ, {"CHANLUN_NEXTDAY_RESEARCH_DIR": ""}
        ):
            output_dir = HOOK.resolve_output_dir(None)

        self.assertEqual(
            (canonical_root / "research" / "nextday-strength-v0" / "runs").resolve(),
            output_dir,
        )

    def test_environment_output_dir_overrides_the_derived_path(self):
        override = self.root / "custom-runs"
        with mock.patch.dict(
            os.environ, {"CHANLUN_NEXTDAY_RESEARCH_DIR": str(override)}
        ):
            output_dir = HOOK.resolve_output_dir(None)

        self.assertEqual(override.resolve(), output_dir)

    def test_publish_function_keeps_push_error_code_and_skips_research(self):
        result = self._run_publish_stub(push_status=23, hook_status=0)

        self.assertEqual("publish_status=23", result.stdout.strip().splitlines()[-1])
        self.assertNotIn("hook", result.stdout)

    def test_publish_function_ignores_research_error_after_successful_push(self):
        result = self._run_publish_stub(push_status=0, hook_status=19)

        self.assertEqual("publish_status=0", result.stdout.strip().splitlines()[-1])
        self.assertLess(result.stdout.index("push"), result.stdout.index("hook"))
        self.assertEqual(1, result.stdout.splitlines().count("hook"))

    def _run_publish_stub(self, *, push_status, hook_status):
        daily_script = (ROOT_DIR / "daily_run.sh").read_text(encoding="utf-8")
        marker = "publish_ready_report() {"
        start = daily_script.index(marker)
        end = daily_script.index("\n}\n", start) + len("\n}\n")
        function_path = self.root / "publish_ready_report.zsh"
        function_path.write_text(daily_script[start:end], encoding="utf-8")

        shell = r'''set -e
GIT_UPSTREAM=origin/main
source "$1"
fetch_with_proxy_fallback() { print -r -- fetch; return 0; }
git() { print -r -- git; return 0; }
commit_today_report_if_changed() { print -r -- commit; return 0; }
push_pending_commits() { print -r -- push; return "$PUSH_STATUS"; }
run_optional_nextday_research_hook() { print -r -- hook; return "$HOOK_STATUS"; }
if publish_ready_report; then
  print -r -- publish_status=0
else
  publish_status=$?
  print -r -- "publish_status=$publish_status"
fi
'''
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PUSH_STATUS": str(push_status),
            "HOOK_STATUS": str(hook_status),
        }
        return subprocess.run(
            ["/bin/zsh", "-c", shell, "zsh", str(function_path)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )


if __name__ == "__main__":
    unittest.main()
