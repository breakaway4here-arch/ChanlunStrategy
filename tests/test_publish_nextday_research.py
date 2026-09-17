from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from tests.test_nextday_public import REPORT_DATE, outcomes_for, selection_for
except ImportError:
    from test_nextday_public import REPORT_DATE, outcomes_for, selection_for
from scripts.publish_nextday_research import publish_sidecars


def git(cwd, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        check=check,
        capture_output=True,
        text=True,
    )


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.remote = self.base / "origin.git"
        self.runs = self.base / "runs"
        self.runs.mkdir()
        git(self.base, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.repo.mkdir()
        git(self.base, "init", "--initial-branch=main", str(self.repo))
        git(self.repo, "config", "user.name", "Publisher Test")
        git(self.repo, "config", "user.email", "publisher-test@example.invalid")
        (self.repo / "docs" / "2026-09-08").mkdir(parents=True)
        (self.repo / "docs" / "2026-09-08" / "index.html").write_text("old report\n", encoding="utf-8")
        (self.repo / "docs" / "compare").mkdir(parents=True)
        (self.repo / "docs" / "compare" / "index.html").write_text("comparison\n", encoding="utf-8")
        git(self.repo, "add", "docs")
        git(self.repo, "commit", "-m", "initial")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-u", "origin", "main")
        git(self.repo, "fetch", "origin", "main")
        self._write_run()

    def tearDown(self):
        self.temp.cleanup()

    def _write_run(self):
        date_dir = self.runs / REPORT_DATE
        date_dir.mkdir(exist_ok=True)
        selection = selection_for()
        outcomes = outcomes_for(selection)
        import json
        (date_dir / "selection.json").write_text(json.dumps(selection, ensure_ascii=False), encoding="utf-8")
        (date_dir / "outcomes.json").write_text(json.dumps(outcomes, ensure_ascii=False), encoding="utf-8")

    def test_commits_only_sidecar_and_preserves_unrelated_dirty_documents(self):
        (self.repo / "docs" / "2026-09-08" / "index.html").unlink()
        (self.repo / "docs" / "compare" / "index.html").write_text("user edit\n", encoding="utf-8")

        result = publish_sidecars(self.repo, self.runs)

        self.assertEqual(result["status"], "published")
        committed = git(self.repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.splitlines()
        self.assertEqual(committed, ["docs/research/nextday/2026-09-17.json"])
        self.assertFalse((self.repo / "docs" / "2026-09-08" / "index.html").exists())
        self.assertEqual((self.repo / "docs" / "compare" / "index.html").read_text(encoding="utf-8"), "user edit\n")
        dirty = git(self.repo, "status", "--short").stdout
        self.assertIn("D docs/2026-09-08/index.html", dirty)
        self.assertIn("M docs/compare/index.html", dirty)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/main").stdout.strip(), git(self.repo, "rev-parse", "HEAD").stdout.strip())

        previous_head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        repeated = publish_sidecars(self.repo, self.runs)
        self.assertEqual(repeated["status"], "no_changes")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), previous_head)

    def test_nonempty_index_refuses_before_creating_sidecar(self):
        (self.repo / "docs" / "compare" / "index.html").write_text("staged edit\n", encoding="utf-8")
        git(self.repo, "add", "docs/compare/index.html")

        result = publish_sidecars(self.repo, self.runs)

        self.assertEqual(result["status"], "pending")
        self.assertFalse((self.repo / "docs" / "research" / "nextday").exists())
        self.assertIn("docs/compare/index.html", git(self.repo, "diff", "--cached", "--name-only").stdout)

    def test_remote_ahead_refuses_before_creating_sidecar(self):
        updater = self.base / "updater"
        git(self.base, "clone", str(self.remote), str(updater))
        git(updater, "config", "user.name", "Remote Updater")
        git(updater, "config", "user.email", "remote-updater@example.invalid")
        (updater / "remote.txt").write_text("ahead\n", encoding="utf-8")
        git(updater, "add", "remote.txt")
        git(updater, "commit", "-m", "remote ahead")
        git(updater, "push", "origin", "main")

        result = publish_sidecars(self.repo, self.runs)

        self.assertEqual(result["status"], "pending")
        self.assertFalse((self.repo / "docs" / "research" / "nextday").exists())
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), git(self.remote, "rev-parse", "refs/heads/main").stdout.strip())

    def test_precommit_failure_restores_only_new_sidecar_and_index(self):
        hooks = Path(git(self.repo, "rev-parse", "--git-path", "hooks").stdout.strip())
        if not hooks.is_absolute():
            hooks = self.repo / hooks
        pre_commit = hooks / "pre-commit"
        pre_commit.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        pre_commit.chmod(0o755)

        result = publish_sidecars(self.repo, self.runs)

        self.assertEqual(result["status"], "pending")
        self.assertFalse((self.repo / "docs" / "research" / "nextday" / "2026-09-17.json").exists())
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only").stdout, "")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), git(self.remote, "rev-parse", "refs/heads/main").stdout.strip())

    def test_push_failure_keeps_sidecar_commit_pending(self):
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        result = publish_sidecars(self.repo, self.runs)

        self.assertEqual(result["status"], "committed_pending")
        self.assertTrue((self.repo / "docs" / "research" / "nextday" / "2026-09-17.json").is_file())
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), git(self.remote, "rev-parse", "refs/heads/main").stdout.strip())
        self.assertEqual(git(self.repo, "status", "--short").stdout, "")


if __name__ == "__main__":
    unittest.main()
