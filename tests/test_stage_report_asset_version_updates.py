import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from chanlun.report_generator import _report_asset_version
from scripts.stage_report_asset_version_updates import (
    _journal_exclusions,
    stage_report_asset_version_updates,
)


def _report_shell(version, extra=""):
    return (
        f'<link rel="stylesheet" href="../assets/report-v2.css?v={version}">'
        '<script>window.CHANLUN_BOOTSTRAP={"note":"用户正文保持不变"};</script>'
        + extra
        + f'<script src="../assets/report-v2.js?v={version}"></script>\n'
    )


class TestStageReportAssetVersionUpdates(unittest.TestCase):

    def _git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout

    def test_stages_only_query_changes_and_preserves_dirty_or_deleted_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs = root / "docs"
            paths = {
                "compare": docs / "compare" / "index.html",
                "clean": docs / "2026-08-21" / "index.html",
                "dirty": docs / "2026-08-22" / "index.html",
                "deleted": docs / "2026-08-23" / "index.html",
                "invalid": docs / "2026-08-24" / "index.html",
                "manual_query": docs / "2026-08-25" / "index.html",
            }
            for path in paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_report_shell("111111111111"), encoding="utf-8")

            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "Chanlun Test")
            self._git(root, "config", "user.email", "chanlun-test@example.invalid")
            self._git(root, "add", "docs")
            self._git(root, "commit", "-q", "-m", "baseline")

            current_version = _report_asset_version()
            paths["compare"].write_text(_report_shell(current_version), encoding="utf-8")
            paths["clean"].write_text(_report_shell(current_version), encoding="utf-8")
            paths["dirty"].write_text(
                _report_shell(current_version, "<p>用户未提交正文</p>"),
                encoding="utf-8",
            )
            paths["deleted"].unlink()
            paths["invalid"].write_bytes(b"\xff\xfe\x00")
            paths["manual_query"].write_text(
                _report_shell(current_version),
                encoding="utf-8",
            )

            staged, skipped = stage_report_asset_version_updates(
                root,
                docs,
                excluded_paths={"docs/2026-08-25/index.html"},
            )

            self.assertEqual(
                set(staged),
                {
                    "docs/compare/index.html",
                    "docs/2026-08-21/index.html",
                },
            )
            self.assertEqual(
                skipped,
                [
                    "docs/2026-08-22/index.html",
                    "docs/2026-08-24/index.html",
                    "docs/2026-08-25/index.html",
                ],
            )
            cached = set(
                self._git(root, "diff", "--cached", "--name-only").splitlines()
            )
            self.assertEqual(cached, set(staged))
            unstaged = set(self._git(root, "diff", "--name-only").splitlines())
            self.assertEqual(
                unstaged,
                {
                    "docs/2026-08-22/index.html",
                    "docs/2026-08-23/index.html",
                    "docs/2026-08-24/index.html",
                    "docs/2026-08-25/index.html",
                },
            )
            self.assertIn("用户未提交正文", paths["dirty"].read_text(encoding="utf-8"))

    def test_rejects_docs_directory_outside_repository(self):
        with tempfile.TemporaryDirectory() as repo_tmpdir:
            with tempfile.TemporaryDirectory() as docs_tmpdir:
                with self.assertRaisesRegex(ValueError, "inside repo_root"):
                    stage_report_asset_version_updates(repo_tmpdir, docs_tmpdir)

    def test_cli_imports_repository_package_in_launchd_style_environment(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "stage_report_asset_version_updates.py"),
                "--help",
            ],
            cwd=str(root),
            env={
                "HOME": os.environ.get("HOME", "/private/tmp"),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_stages_generated_history_deletion_but_preserves_excluded_deletion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs = root / "docs"
            generated = docs / "2026-08-21" / "index.html"
            excluded = docs / "2026-08-22" / "index.html"
            for path in (generated, excluded):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_report_shell("111111111111"), encoding="utf-8")

            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "Chanlun Test")
            self._git(root, "config", "user.email", "chanlun-test@example.invalid")
            self._git(root, "add", "docs")
            self._git(root, "commit", "-q", "-m", "baseline")

            generated.unlink()
            excluded.unlink()
            staged, skipped = stage_report_asset_version_updates(
                root,
                docs,
                excluded_paths={"docs/2026-08-22/index.html"},
                stage_generated_deletions=True,
            )

            self.assertEqual(staged, ["docs/2026-08-21/index.html"])
            self.assertEqual(skipped, ["docs/2026-08-22/index.html"])
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only").splitlines(),
                ["docs/2026-08-21/index.html"],
            )
            self.assertEqual(
                self._git(root, "diff", "--name-only").splitlines(),
                ["docs/2026-08-22/index.html"],
            )

    def test_rejects_stale_journal_before_enabling_generated_deletions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tracked.txt").write_text("baseline", encoding="utf-8")
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "Chanlun Test")
            self._git(root, "config", "user.email", "chanlun-test@example.invalid")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-q", "-m", "baseline")
            journal = root / "journal.json"
            journal.write_text(
                json.dumps(
                    {
                        "head_sha": "0" * 40,
                        "excluded_report_entrypoints": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "HEAD"):
                _journal_exclusions(journal, root)


if __name__ == "__main__":
    unittest.main()
