"""Publish the optional performance triplet from a real, isolated Git checkout."""

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.formal_publish_guard import (
    prepare_formal_publish,
    record_formal_publish_targets,
)
from scripts.stage_selection_performance import stage_selection_performance


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGER = REPO_ROOT / "scripts/stage_selection_performance.py"
DAY = "2026-10-12"
AS_OF = "2026-10-12T15:20:11+08:00"
DATASET_ID = "a" * 64


class TestSelectionPerformanceStaging(unittest.TestCase):
    def _git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout

    def _put_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def _repo(self, root):
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "Chanlun Test")
        self._git(root, "config", "user.email", "chanlun-test@example.invalid")
        (root / ".gitignore").write_text(".cache/\n", encoding="utf-8")
        self._put_json(root / f"docs/data/{DAY}.json", {
            "date": DAY,
            "data_quality": {"is_official": True, "bar_state": "closed", "as_of": AS_OF},
        })
        (root / f"docs/{DAY}/index.html").parent.mkdir(parents=True)
        (root / f"docs/{DAY}/index.html").write_text("published\n", encoding="utf-8")
        (root / "docs/data/2026-10-09.json").write_text("history\n", encoding="utf-8")
        old_derived = root / "docs/data/selection-performance"
        old_derived.mkdir(parents=True)
        (old_derived / "index.json").write_text("previous-index\n", encoding="utf-8")
        (old_derived / "status.json").write_text("previous-status\n", encoding="utf-8")
        self._git(root, "add", ".gitignore", "docs")
        self._git(root, "commit", "-q", "-m", "baseline")
        return root / ".cache/formal-publish-targets.json"

    def _derived(self, root, as_of=AS_OF):
        derived = root / "docs/data/selection-performance"
        entry = {"dataset_id": DATASET_ID, "evaluation_as_of": as_of,
                 "evidence_as_of": as_of}
        self._put_json(derived / f"{DAY}.json", {
            "schema_version": "selection-performance-v1",
            "report_as_of": DAY, "evaluation_as_of": as_of,
            "dataset_id": DATASET_ID,
        })
        self._put_json(derived / "index.json", {
            "schema_version": "selection-performance-index-v1",
            "dates": [DAY], "datasets": {DAY: entry},
        })
        self._put_json(derived / "status.json", {
            "status": "ready", "attempted_report_as_of": DAY,
            "last_success": entry,
        })
        return derived

    def _run_stager(self, root, journal):
        return subprocess.run(
            [sys.executable, str(STAGER), "--repo-root", str(root),
             "--trade-date", DAY, "--journal-path", str(journal)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def _staged(self, root):
        return self._git(root, "diff", "--cached", "--name-only").splitlines()

    def test_stages_only_current_valid_triplet_after_journal_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            self._derived(root)
            (root / "docs/data/selection-performance/2026-10-09.json").write_text(
                "historical-user-file\n", encoding="utf-8")
            (root / "docs/unrelated.txt").write_text("untracked\n", encoding="utf-8")
            record_formal_publish_targets(root, DAY, journal)

            result = self._run_stager(root, journal)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self._staged(root), [
                f"docs/data/selection-performance/{DAY}.json",
                "docs/data/selection-performance/index.json",
                "docs/data/selection-performance/status.json",
            ])
            self.assertTrue((root / "docs/unrelated.txt").exists())

    def test_report_cutoff_uses_shanghai_calendar_date(self):
        cases = (
            ("same_shanghai_day", "2026-10-11T23:20:11-08:00", True),
            ("next_shanghai_day", "2026-10-12T23:20:11-08:00", False),
        )
        for name, as_of, expected_staged in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                journal = self._repo(root)
                prepare_formal_publish(root, DAY, journal)
                self._put_json(root / f"docs/data/{DAY}.json", {
                    "date": DAY,
                    "data_quality": {"is_official": True, "bar_state": "closed",
                                     "as_of": as_of},
                })
                derived = self._derived(root, as_of=as_of)
                record_formal_publish_targets(root, DAY, journal)

                result = self._run_stager(root, journal)

                self.assertEqual(result.returncode, 0, result.stderr)
                if expected_staged:
                    self.assertEqual(self._staged(root), [
                        f"docs/data/selection-performance/{DAY}.json",
                        "docs/data/selection-performance/index.json",
                        "docs/data/selection-performance/status.json",
                    ])
                else:
                    self.assertEqual(self._staged(root), [])
                    self.assertFalse((derived / f"{DAY}.json").exists())
                    self.assertEqual((derived / "index.json").read_text(),
                                     "previous-index\n")

    def test_missing_optional_files_do_not_stage_or_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            record_formal_publish_targets(root, DAY, journal)

            result = self._run_stager(root, journal)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self._staged(root), [])

    def test_invalid_or_changed_triplet_is_skipped_as_one_unit(self):
        mutations = {
            "wrong_date": lambda root, derived: self._put_json(
                derived / f"{DAY}.json", {
                    "schema_version": "selection-performance-v1",
                    "report_as_of": "2026-10-09", "evaluation_as_of": AS_OF,
                    "dataset_id": DATASET_ID,
                }),
            "wrong_id": lambda root, derived: self._put_json(
                derived / "index.json", {
                    "schema_version": "selection-performance-index-v1",
                    "dates": [DAY], "datasets": {DAY: {
                        "dataset_id": "b" * 64, "evaluation_as_of": AS_OF,
                        "evidence_as_of": AS_OF,
                    }},
                }),
            "failed_status": lambda root, derived: self._put_json(
                derived / "status.json", {
                    "status": "update_failed", "attempted_report_as_of": DAY,
                    "last_success": None,
                }),
            "wrong_report": lambda root, derived: self._put_json(
                root / f"docs/data/{DAY}.json", {
                    "date": DAY, "data_quality": {
                        "is_official": True, "bar_state": "closed",
                        "as_of": "2026-10-12T15:05:00+08:00",
                    },
                }),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                journal = self._repo(root)
                prepare_formal_publish(root, DAY, journal)
                derived = self._derived(root)
                mutate(root, derived)
                record_formal_publish_targets(root, DAY, journal)

                result = self._run_stager(root, journal)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self._staged(root), [])
                self.assertFalse((derived / f"{DAY}.json").exists())
                self.assertEqual((derived / "index.json").read_text(), "previous-index\n")
                self.assertEqual((derived / "status.json").read_text(), "previous-status\n")
                receipts = list((journal.parent / "selection-performance-stage-skips")
                                .glob(DAY + "-*.json"))
                self.assertEqual(len(receipts), 1)
                receipt = receipts[0]
                self.assertTrue(receipt.is_file())
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
                evidence = json.loads(receipt.read_text(encoding="utf-8"))
                for relative, backup_name in evidence["backups"].items():
                    backup = receipt.parent / backup_name
                    self.assertTrue(backup.is_file())
                    self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(
                        hashlib.sha256(backup.read_bytes()).hexdigest(),
                        evidence["generated_sha256"][relative],
                    )

    def test_two_skips_same_day_keep_both_private_receipts_and_byte_backups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            receipt_dir = journal.parent / "selection-performance-stage-skips"
            originals = []
            for _ in range(2):
                derived = self._derived(root)
                self._put_json(derived / "status.json", {
                    "status": "update_failed", "attempted_report_as_of": DAY,
                    "last_success": None,
                })
                record_formal_publish_targets(root, DAY, journal)
                generated = {
                    name: (derived / name).read_bytes()
                    for name in (DAY + ".json", "index.json", "status.json")
                }
                result = self._run_stager(root, journal)
                self.assertEqual(result.returncode, 0, result.stderr)
                receipts = sorted(receipt_dir.glob(DAY + "-*.json"))
                self.assertEqual(len(receipts), len(originals) + 1)
                self.assertEqual(receipt_dir.stat().st_mode & 0o777, 0o700)
                for receipt, prior in originals:
                    self.assertEqual(receipt.read_bytes(), prior)
                latest = (set(receipts) - {item[0] for item in originals}).pop()
                payload = json.loads(latest.read_text(encoding="utf-8"))
                self.assertEqual(latest.stat().st_mode & 0o777, 0o600)
                self.assertEqual(len(payload["backups"]), 3)
                for relative, backup_name in payload["backups"].items():
                    backup = receipt_dir / backup_name
                    self.assertEqual(backup.read_bytes(), generated[Path(relative).name])
                    self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                originals.append((latest, latest.read_bytes()))

    def test_backup_write_failure_leaves_generated_group_untouched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            derived = self._derived(root)
            self._put_json(derived / "status.json", {
                "status": "update_failed", "attempted_report_as_of": DAY,
                "last_success": None,
            })
            record_formal_publish_targets(root, DAY, journal)
            generated = {name: (derived / name).read_bytes()
                         for name in (DAY + ".json", "index.json", "status.json")}
            with mock.patch("scripts.stage_selection_performance.os.fsync",
                            side_effect=OSError("synthetic backup sync failure")):
                with self.assertRaises(OSError):
                    stage_selection_performance(root, DAY, journal)
            self.assertEqual({name: (derived / name).read_bytes()
                              for name in generated}, generated)
            receipt_dir = journal.parent / "selection-performance-stage-skips"
            self.assertEqual(list(receipt_dir.glob(DAY + "-*.json")), [])
            self.assertEqual(list(receipt_dir.glob(DAY + "-*.bak")), [])
            self.assertEqual(self._staged(root), [])

    def test_missing_tracked_status_without_journal_hash_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            derived = self._derived(root)
            (derived / "status.json").unlink()
            record_formal_publish_targets(root, DAY, journal)

            result = self._run_stager(root, journal)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse((derived / "status.json").exists())
            self.assertTrue((derived / f"{DAY}.json").exists())
            self.assertEqual(self._staged(root), [])

    def test_changed_bytes_after_record_are_not_staged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            derived = self._derived(root)
            record_formal_publish_targets(root, DAY, journal)
            with (derived / "status.json").open("a", encoding="utf-8") as handle:
                handle.write(" \n")

            result = self._run_stager(root, journal)

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self._staged(root), [])
            self.assertTrue((derived / f"{DAY}.json").exists())
            self.assertIn(" \n", (derived / "status.json").read_text())

    def test_failed_optional_group_leaves_clean_tree_for_next_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            journal = self._repo(root)
            prepare_formal_publish(root, DAY, journal)
            derived = self._derived(root)
            self._put_json(derived / "status.json", {
                "status": "update_failed", "attempted_report_as_of": DAY,
                "last_success": None,
            })
            record_formal_publish_targets(root, DAY, journal)

            result = self._run_stager(root, journal)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self._git(root, "status", "--porcelain"), "")
            (root / "docs/index.html").write_text("formal-result\n", encoding="utf-8")
            self._git(root, "add", "docs/index.html")
            self._git(root, "commit", "-q", "-m", "publish formal")
            prepare_formal_publish(root, "2026-10-13", journal)
            self.assertEqual(self._git(root, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
