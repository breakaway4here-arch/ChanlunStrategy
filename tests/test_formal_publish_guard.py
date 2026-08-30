import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.formal_publish_guard import (
    preflight_formal_publish,
    prepare_formal_publish,
    record_formal_publish_targets,
)


TRADE_DATE = "2026-08-31"


class TestFormalPublishGuard(unittest.TestCase):

    def _git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout

    def _build_repo(self, root):
        files = {
            "docs/index.html": "root-old\n",
            "docs/data.json": "{}\n",
            "docs/data/comparison-index.json": "{}\n",
            "docs/data/index.json": "{}\n",
            f"docs/data/{TRADE_DATE}.json": "{}\n",
            f"docs/{TRADE_DATE}/index.html": "today-old\n",
            "docs/assets/report-v2.css": "old-css\n",
            "docs/assets/report-v2.js": "old-js\n",
            "docs/compare/index.html": "compare-old\n",
            "docs/2026-08-28/index.html": "history-old\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self._git(root, "init", "-q")
        self._git(root, "config", "user.name", "Chanlun Test")
        self._git(root, "config", "user.email", "chanlun-test@example.invalid")
        self._git(root, "add", "docs")
        self._git(root, "commit", "-q", "-m", "baseline")

    def test_allows_hash_identical_generated_outputs_on_retry_but_not_user_edit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root)
            journal = root / ".cache" / "formal-publish-targets.json"

            prepare_formal_publish(root, TRADE_DATE, journal)
            (root / "docs/index.html").write_text("root-generated\n", encoding="utf-8")
            (root / f"docs/data/{TRADE_DATE}.json").write_text(
                '{"generated":true}\n',
                encoding="utf-8",
            )
            record_formal_publish_targets(root, TRADE_DATE, journal)

            prepare_formal_publish(root, TRADE_DATE, journal)

            (root / "docs/index.html").write_text("root-user-edit\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "does not match generated journal"):
                prepare_formal_publish(root, TRADE_DATE, journal)

    def test_rejects_preexisting_dirty_fixed_target_without_valid_journal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root)
            journal = root / ".cache" / "formal-publish-targets.json"
            (root / "docs/index.html").write_text("preexisting-user-edit\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "preexisting user change"):
                prepare_formal_publish(root, TRADE_DATE, journal)

    def test_records_preexisting_dirty_history_as_stage_exclusion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root)
            journal = root / ".cache" / "formal-publish-targets.json"
            (root / "docs/compare/index.html").write_text(
                "compare-user-edit\n",
                encoding="utf-8",
            )
            (root / "docs/2026-08-28/index.html").unlink()

            prepared = prepare_formal_publish(root, TRADE_DATE, journal)

            self.assertEqual(
                prepared["excluded_report_entrypoints"],
                [
                    "docs/2026-08-28/index.html",
                    "docs/compare/index.html",
                ],
            )
            persisted = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(persisted, prepared)
            self.assertEqual(journal.stat().st_mode & 0o777, 0o600)

    def test_prepare_after_head_advance_rewrites_stale_clean_journal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root)
            journal = root / ".cache" / "formal-publish-targets.json"
            first = prepare_formal_publish(root, TRADE_DATE, journal)

            (root / "README.md").write_text("new head\n", encoding="utf-8")
            self._git(root, "add", "README.md")
            self._git(root, "commit", "-q", "-m", "advance head")

            self.assertIsNone(preflight_formal_publish(root, TRADE_DATE, journal))
            second = prepare_formal_publish(root, TRADE_DATE, journal)
            self.assertNotEqual(first["head_sha"], second["head_sha"])
            (root / "docs/index.html").write_text("generated\n", encoding="utf-8")
            recorded = record_formal_publish_targets(root, TRADE_DATE, journal)
            self.assertIn("docs/index.html", recorded["generated_targets"])

    def test_record_can_refresh_hashes_after_finalizer_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root)
            journal = root / ".cache" / "formal-publish-targets.json"
            prepare_formal_publish(root, TRADE_DATE, journal)
            (root / "docs/index.html").write_text("run output\n", encoding="utf-8")
            first = record_formal_publish_targets(root, TRADE_DATE, journal)

            (root / "docs/index.html").write_text("finalized output\n", encoding="utf-8")
            second = record_formal_publish_targets(root, TRADE_DATE, journal)

            self.assertNotEqual(
                first["generated_targets"]["docs/index.html"],
                second["generated_targets"]["docs/index.html"],
            )
            self.assertEqual(
                preflight_formal_publish(root, TRADE_DATE, journal),
                second,
            )


if __name__ == "__main__":
    unittest.main()
