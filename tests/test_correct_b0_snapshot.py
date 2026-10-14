import copy
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from chanlun.nextday_research import adapt_report, freeze_selection
from scripts.repair_strategy_scorecard_snapshot import formal_report_digest
from scripts.repair_strategy_scorecard_snapshot import rebuild_strategy_scorecard_report, _refresh_report_bootstrap
from scripts.enable_shadow_evaluation_snapshot import _read_bootstrap_envelope
from scripts.correct_b0_snapshot import CorrectionError, build_corrected_b0


DAY = "2026-10-14"


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _report():
    source = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "b0_legacy_2026-10-14.json.gz"
    return json.loads(gzip.decompress(source.read_bytes()).decode("utf-8"))


def _archive(bootstrap):
    return ("<script>\nwindow.CHANLUN_BOOTSTRAP = "
            + json.dumps(bootstrap, ensure_ascii=False) + ";\n</script>").encode("utf-8")


@lru_cache(maxsize=1)
def _real_fixed_fixture():
    frozen = _report()
    old = frozen["report"]
    envelope = frozen["bootstrap_without_inline_report"]
    envelope["inlineReportData"] = copy.deepcopy(old)
    new, _ = rebuild_strategy_scorecard_report(
        old,
        report_date=DAY,
        scorecards=old["strategy_scorecards"],
        review_diagnostics=old["diagnostics"]["strategy_review"],
        ledger_finalization=old["diagnostics"].get("recommendation_ledger"),
    )
    root = Path(__file__).resolve().parents[1]
    refreshed = _refresh_report_bootstrap(envelope, new, root / "docs", DAY)
    return old, new, _archive(envelope), _archive(refreshed)


class CorrectB0SnapshotTests(unittest.TestCase):
    def _files(self, root):
        old, new, original_archive, corrected_archive = _real_fixed_fixture()
        paths = {name: root / name for name in (
            "old-report.json", "old-archive.html", "new-report.json", "new-archive.html",
            "selection.json", "outcomes.json",
        )}
        paths["old-report.json"].write_bytes(_json_bytes(old))
        paths["old-archive.html"].write_bytes(original_archive)
        paths["new-report.json"].write_bytes(_json_bytes(new))
        paths["new-archive.html"].write_bytes(corrected_archive)
        prepared = adapt_report(copy.deepcopy(old), {
            "identity_matches": True,
            "workbench": {"report_date": DAY, "items": []},
        })
        prepared["b0"].update(status="evaluated", selected=[], reason="")
        prepared["source_hashes"] = {
            "report_sha256": hashlib.sha256(paths["old-report.json"].read_bytes()).hexdigest(),
            "archive_sha256": hashlib.sha256(paths["old-archive.html"].read_bytes()).hexdigest(),
        }
        prepared["report_identity"] = prepared["source_hashes"]["report_sha256"]
        freeze_selection(root, prepared, "a" * 64, frozen_at="2026-10-14T07:25:28Z")
        frozen = root / DAY / "selection.json"
        paths["selection.json"].write_bytes(frozen.read_bytes())
        paths["outcomes.json"].write_bytes(_json_bytes({
            "report_date": DAY, "as_of_date": DAY,
            "l1": {"status": "evaluated_empty", "selected": [], "metrics": {"selected": 0}},
            "b0": {"status": "evaluated_empty", "selected": [], "metrics": {"selected": 0}},
        }))
        return paths

    def test_corrects_only_b0_with_cas_and_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._files(root)
            old_selection = json.loads(paths["selection.json"].read_text())
            old_outcomes = json.loads(paths["outcomes.json"].read_text())
            expected_selection = hashlib.sha256(paths["selection.json"].read_bytes()).hexdigest()
            expected_outcomes = hashlib.sha256(paths["outcomes.json"].read_bytes()).hexdigest()
            output = root / "correction"
            build_corrected_b0(
                old_report_path=paths["old-report.json"],
                old_archive_path=paths["old-archive.html"],
                corrected_report_path=paths["new-report.json"],
                corrected_archive_path=paths["new-archive.html"],
                selection_path=paths["selection.json"],
                outcomes_path=paths["outcomes.json"],
                db_path=root / "unused.sqlite", output_dir=output,
                expected_selection_sha256=expected_selection,
                expected_outcomes_sha256=expected_outcomes,
                corrected_at="2026-10-14T10:05:00Z",
                outcome_evaluator=lambda snapshot, _db, as_of: {
                    "status": "evaluated", "report_date": DAY, "as_of_date": as_of,
                    "outcome_rows": [], "metrics": {"selected": len(snapshot["selected"]), "pending_t1": len(snapshot["selected"])},
                },
            )
            selection = json.loads((output / "corrected" / "selection.json").read_text())
            outcomes = json.loads((output / "corrected" / "outcomes.json").read_text())
            self.assertEqual(selection["l1"], old_selection["l1"])
            self.assertEqual(selection["group_freezes"]["l1"], old_selection["group_freezes"]["l1"])
            self.assertEqual(outcomes["l1"], old_outcomes["l1"])
            self.assertEqual([row["code"] for row in selection["b0"]["selected"]],
                             ["002404", "600570", "688111", "601858", "603992"])
            self.assertEqual(selection["b0"]["correction"]["corrected_at"], "2026-10-14T10:05:00Z")
            self.assertEqual(paths["selection.json"].read_bytes(),
                             (output / "original" / "selection.json").read_bytes())
            self.assertEqual(paths["outcomes.json"].read_bytes(),
                             (output / "original" / "outcomes.json").read_bytes())

    def test_wrong_cas_or_raw_fact_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._files(root)
            kwargs = dict(
                old_report_path=paths["old-report.json"], old_archive_path=paths["old-archive.html"],
                corrected_report_path=paths["new-report.json"], corrected_archive_path=paths["new-archive.html"],
                selection_path=paths["selection.json"], outcomes_path=paths["outcomes.json"],
                db_path=root / "unused.sqlite", output_dir=root / "correction",
                expected_outcomes_sha256=hashlib.sha256(paths["outcomes.json"].read_bytes()).hexdigest(),
                corrected_at="2026-10-14T10:05:00Z",
                outcome_evaluator=lambda *_: {},
            )
            with self.assertRaises(CorrectionError):
                build_corrected_b0(expected_selection_sha256="0" * 64, **kwargs)
            self.assertFalse((root / "correction").exists())

            changed = json.loads(paths["new-report.json"].read_text())
            changed["picks_pure"] = []
            paths["new-report.json"].write_bytes(_json_bytes(changed))
            with self.assertRaises(CorrectionError):
                build_corrected_b0(
                    expected_selection_sha256=hashlib.sha256(paths["selection.json"].read_bytes()).hexdigest(),
                    **kwargs,
                )
            self.assertFalse((root / "correction").exists())

    def test_same_codes_with_changed_candidate_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._files(root)
            changed = json.loads(paths["new-report.json"].read_text())
            changed["workspace"]["views"]["highlights"][0]["watch_score"] = -999
            changed_digest = formal_report_digest(changed)
            changed["shadow_evaluations"]["production_guard"] = {
                "unchanged": True,
                "before_sha256": changed_digest,
                "after_sha256": changed_digest,
            }
            paths["new-report.json"].write_bytes(_json_bytes(changed))
            with self.assertRaisesRegex(CorrectionError, "source-derived rows"):
                build_corrected_b0(
                    old_report_path=paths["old-report.json"], old_archive_path=paths["old-archive.html"],
                    corrected_report_path=paths["new-report.json"], corrected_archive_path=paths["new-archive.html"],
                    selection_path=paths["selection.json"], outcomes_path=paths["outcomes.json"],
                    db_path=root / "unused.sqlite", output_dir=root / "correction",
                    expected_selection_sha256=hashlib.sha256(paths["selection.json"].read_bytes()).hexdigest(),
                    expected_outcomes_sha256=hashlib.sha256(paths["outcomes.json"].read_bytes()).hexdigest(),
                    corrected_at="2026-10-14T10:05:00Z",
                    outcome_evaluator=lambda *_: {},
                )
            self.assertFalse((root / "correction").exists())

    def test_unrelated_old_hidden_state_cannot_be_corrected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._files(root)
            changed = json.loads(paths["old-report.json"].read_text())
            changed["selection_input_health"]["by_view"]["highlights"]["blocking_reason"] = "another_failure"
            paths["old-report.json"].write_bytes(_json_bytes(changed))
            with self.assertRaises(CorrectionError):
                build_corrected_b0(
                    old_report_path=paths["old-report.json"], old_archive_path=paths["old-archive.html"],
                    corrected_report_path=paths["new-report.json"], corrected_archive_path=paths["new-archive.html"],
                    selection_path=paths["selection.json"], outcomes_path=paths["outcomes.json"],
                    db_path=root / "unused.sqlite", output_dir=root / "correction",
                    expected_selection_sha256=hashlib.sha256(paths["selection.json"].read_bytes()).hexdigest(),
                    expected_outcomes_sha256=hashlib.sha256(paths["outcomes.json"].read_bytes()).hexdigest(),
                    corrected_at="2026-10-14T10:05:00Z",
                    outcome_evaluator=lambda *_: {},
                )
            self.assertFalse((root / "correction").exists())

    def test_archive_missing_other_strategy_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._files(root)
            envelope = _read_bootstrap_envelope(paths["new-archive.html"])
            for item in envelope["decisionWorkbench"]["items"]:
                item["strategy_results"] = [
                    strategy for strategy in item.get("strategy_results", [])
                    if strategy.get("strategy_id") == "highlights"
                ]
            paths["new-archive.html"].write_bytes(_archive(envelope))
            with self.assertRaisesRegex(CorrectionError, "source-replayed workbench"):
                build_corrected_b0(
                    old_report_path=paths["old-report.json"], old_archive_path=paths["old-archive.html"],
                    corrected_report_path=paths["new-report.json"], corrected_archive_path=paths["new-archive.html"],
                    selection_path=paths["selection.json"], outcomes_path=paths["outcomes.json"],
                    db_path=root / "unused.sqlite", output_dir=root / "correction",
                    expected_selection_sha256=hashlib.sha256(paths["selection.json"].read_bytes()).hexdigest(),
                    expected_outcomes_sha256=hashlib.sha256(paths["outcomes.json"].read_bytes()).hexdigest(),
                    corrected_at="2026-10-14T10:05:00Z",
                    outcome_evaluator=lambda *_: {},
                )
