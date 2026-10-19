"""Execute the daily shell in disposable repositories; all network is local/faked."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
PYTHON = "/usr/bin/python3"


class DailyRunRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chanlun-daily-shell-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.remote = self.base / "remote.git"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.events = self.repo / ".test-events"
        self.day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        self.env = dict(os.environ, PATH=str(self.bin) + ":" + os.environ["PATH"],
                        TEST_REAL_GIT=GIT, TEST_REPO=str(self.repo),
                        TEST_EVENTS=str(self.events), TEST_DAY=self.day,
                        CHANLUN_DAILY_GIT_RETRY_DELAY_SECONDS="0", TZ="UTC")
        for name in ("CHANLUN_DOCS_PUBLISH_LOCK_HELD", "CHANLUN_DOCS_PUBLISH_LOCK_PATH",
                     "CHANLUN_DOCS_PUBLISH_LOCK_FD", "CHANLUN_KPL_PUBLISH_LOCK_FD",
                     "CHANLUN_FORMAL_PUBLISH_JOURNAL_PATH", "CHANLUN_GIT_UPSTREAM"):
            self.env.pop(name, None)
        self.write_executable(self.bin / "git", self.git_stub())
        self.write_executable(self.bin / "python", self.python_stub())
        script = (ROOT / "daily_run.sh").read_text()
        # Avoid the user's interactive profile; fake only external business I/O.
        script = script.replace("source ~/.zshrc 2>/dev/null || true", ":")
        script = script.replace(PYTHON, str(self.bin / "python"))
        self.write_executable(self.repo / "daily_run.sh", script)
        (self.repo / "scripts").mkdir()
        for name in ("run_with_docs_publish_lock.py", "run_daily_git_network.py"):
            if (ROOT / "scripts" / name).exists():
                shutil.copy2(ROOT / "scripts" / name, self.repo / "scripts" / name)
        # This suite isolates generic daily Git behavior; the real KPL shell and
        # frozen provider are exercised by test_ongoing_kaipanla instead.
        self.write_executable(self.repo / "scripts/kaipanla_refresh.sh", r'''#!/bin/zsh
/usr/bin/python3 - "$@" <<'PY'
import json,os,sys
with open(os.environ['TEST_EVENTS'],'a') as log:
    log.write(json.dumps({'python':'kaipanla_refresh.sh','args':sys.argv[1:]})+'\n')
PY
''')
        (self.repo / ".gitignore").write_text(".test-*\n.cache/\n")
        (self.repo / "baseline.txt").write_text("baseline\n")
        self.git("init", "--bare", str(self.remote), cwd=self.base)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Runtime Test")
        self.git("config", "user.email", "runtime@example.invalid")
        self.git("add", ".")
        self.git("commit", "-m", "test: baseline")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")

    @staticmethod
    def write_executable(path, text):
        path.write_text(text)
        path.chmod(0o755)

    @staticmethod
    def git_stub():
        return r"""#!/usr/bin/python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
operation = next((v for v in args if v in ('fetch', 'push')), '')
if operation:
    state = pathlib.Path(os.environ['TEST_REPO']) / ('.test-' + operation)
    count = int(state.read_text()) + 1 if state.exists() else 1
    state.write_text(str(count))
    with open(os.environ['TEST_EVENTS'], 'a') as log:
        log.write(json.dumps({'git':operation, 'attempt':count, 'args':args, 'prompt':os.environ.get('GIT_TERMINAL_PROMPT'), 'askpass':os.environ.get('GIT_ASKPASS')}) + '\n')
    if count <= int(os.environ.get('TEST_' + operation.upper() + '_FAILURES', '0')):
        raise SystemExit(75)
raise SystemExit(subprocess.call([os.environ['TEST_REAL_GIT']] + args))
"""

    @staticmethod
    def python_stub():
        return r"""#!/usr/bin/python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
if args and pathlib.Path(args[0]).name in ('run_with_docs_publish_lock.py', 'run_daily_git_network.py'):
    raise SystemExit(subprocess.call(['/usr/bin/python3'] + args))
name = pathlib.Path(args[0]).name if args else ''
with open(os.environ['TEST_EVENTS'], 'a') as log:
    log.write(json.dumps({'python':name, 'args':args, 'TZ':os.environ.get('TZ')}) + '\n')
if name == '-c':
    repo = pathlib.Path(os.environ['TEST_REPO'])
    day = os.environ['TEST_DAY']
    paths = ['docs/index.html','docs/data.json','docs/data/index.json','docs/data/' + day + '.json',
             'docs/' + day + '/index.html','docs/assets/report-v2.css','docs/assets/report-v2.js']
    for target in paths:
        path = repo / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
if name == 'validate_today_report.py' and '--needs-sublevel-retry' in args:
    raise SystemExit(0 if os.environ.get('TEST_SUBLEVEL_RETRY') == '1' else 1)
raise SystemExit(0)
"""

    def git(self, *args, **kwargs):
        return subprocess.run([GIT] + list(args), cwd=kwargs.get("cwd", self.repo),
                              text=True, capture_output=True, check=True).stdout.strip()

    def report(self, published=False):
        for path in ("docs/index.html", "docs/data.json", "docs/data/index.json",
                     "docs/data/" + self.day + ".json", "docs/" + self.day + "/index.html",
                     "docs/assets/report-v2.css", "docs/assets/report-v2.js"):
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        self.git("add", "docs")
        self.git("commit", "-m", "test: report")
        if published:
            self.git("push")

    def run_daily(self, **env):
        return subprocess.run(["/bin/zsh", str(self.repo / "daily_run.sh")], cwd=self.repo,
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=25)

    def logs(self):
        return [json.loads(row) for row in self.events.read_text().splitlines()]

    def test_fetch_recovers_after_both_routes_fail_once(self):
        result = self.run_daily(TEST_FETCH_FAILURES="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fetches = [row for row in self.logs() if row.get("git") == "fetch"]
        self.assertGreaterEqual(len(fetches), 3)
        self.assertEqual(fetches[0]["prompt"], "0")
        self.assertEqual(fetches[0]["askpass"], "/usr/bin/false")
        self.assertIn("http.https://github.com.proxy=http://127.0.0.1:17891", fetches[0]["args"])
        generated = [row for row in self.logs() if row.get("python") == "-c"]
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0]["TZ"], "Asia/Shanghai")
        self.assertEqual(self.git("rev-list", "--count", "origin/main..HEAD"), "0")

    def test_push_recovers_after_both_routes_fail_once(self):
        self.report()
        result = self.run_daily(TEST_PUSH_FAILURES="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len([row for row in self.logs() if row.get("git") == "push"]), 3)
        self.assertFalse(any(row.get("python") == "-c" for row in self.logs()))
        self.assertEqual(self.git("rev-list", "--count", "origin/main..HEAD"), "0")

    def test_permanent_network_failure_stops_before_generation(self):
        result = self.run_daily(TEST_FETCH_FAILURES="99")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len([row for row in self.logs() if row.get("git") == "fetch"]), 6)
        self.assertFalse(any(row.get("python") == "-c" for row in self.logs()))

    def test_permanent_push_failure_keeps_pending_commit(self):
        self.report()
        head = self.git("rev-parse", "HEAD")
        result = self.run_daily(TEST_PUSH_FAILURES="99")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len([row for row in self.logs() if row.get("git") == "push"]), 6)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("rev-list", "--count", "origin/main..HEAD"), "1")

    def test_already_published_valid_report_skips_formal_hooks_but_checks_kpl(self):
        self.report(published=True)
        result = self.run_daily()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [row.get("python") for row in self.logs()]
        self.assertNotIn("-c", calls)
        self.assertNotIn("finalize_recommendation_ledger.py", calls)
        self.assertNotIn("repair_strategy_scorecard_snapshot.py", calls)
        self.assertNotIn("nextday_research_hook.py", calls)
        self.assertEqual(calls.count("kaipanla_refresh.sh"), 1)
        self.assertIn("--public-planes-only", [a for r in self.logs() for a in r.get("args", [])])

    def test_untracked_optional_performance_is_not_mistaken_for_published(self):
        self.report(published=True)
        pending = self.repo / "docs/data/selection-performance" / (self.day + ".json")
        pending.parent.mkdir(parents=True)
        pending.write_text("{}")
        result = self.run_daily()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stage_selection_performance.py", [r.get("python") for r in self.logs()])

    def test_published_report_with_missing_sublevel_still_retries(self):
        self.report(published=True)
        result = self.run_daily(TEST_SUBLEVEL_RETRY="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len([r for r in self.logs() if r.get("python") == "-c"]), 1)

    def remote_advance(self):
        peer = self.base / "peer"
        self.git("clone", "--branch", "main", str(self.remote), str(peer), cwd=self.base)
        self.git("config", "user.name", "Peer", cwd=peer)
        self.git("config", "user.email", "peer@example.invalid", cwd=peer)
        (peer / "remote.txt").write_text("remote\n")
        self.git("add", "remote.txt", cwd=peer)
        self.git("commit", "-m", "test: remote", cwd=peer)
        self.git("push", cwd=peer)

    def test_dirty_behind_tree_is_preserved_and_stops(self):
        self.remote_advance()
        (self.repo / "baseline.txt").write_text("user work\n")
        head = self.git("rev-parse", "HEAD")
        result = self.run_daily()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.repo / "baseline.txt").read_text(), "user work\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertFalse(any(row.get("python") == "-c" for row in self.logs()))

    def test_diverged_tree_is_preserved_and_stops(self):
        self.remote_advance()
        (self.repo / "local.txt").write_text("local\n")
        self.git("add", "local.txt")
        self.git("commit", "-m", "test: local")
        head = self.git("rev-parse", "HEAD")
        result = self.run_daily()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertFalse(any(row.get("python") == "-c" for row in self.logs()))


if __name__ == "__main__":
    unittest.main()
