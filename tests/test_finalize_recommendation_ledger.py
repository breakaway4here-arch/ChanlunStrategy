import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import chanlun.shadow_evaluation as shadow_evaluation
import scripts.finalize_recommendation_ledger as finalizer
from chanlun.recommendation_ledger import (
    load_recommendation_entries,
    pending_ledger_path,
    stage_recommendation_entries,
)
from chanlun.shadow_evaluation import (
    load_shadow_evaluation_entries,
    shadow_pending_ledger_path,
    stage_shadow_evaluation_entries,
)
from scripts.finalize_recommendation_ledger import finalize_for_date


def _shadow_entry(**updates):
    entry = {
        "schema_version": "1",
        "shadow_evaluation_id": "shadow:one",
        "evaluation_role": "shadow_candidate",
        "publication_effect": False,
        "evaluation_eligible": True,
        "report_date": "2026-08-20",
        "generated_at": "2026-08-20T15:10:00+08:00",
        "code": "300308",
        "experiment_id": "h4-close-v1",
        "version": "v1",
        "source_pool": "h4_t3_pool",
        "upstream_pool": "picks_pure",
        "intended_horizon": 3,
        "entry_mode": "immediate_close",
        "reference_close": 100.0,
        "reference_date": "2026-08-20",
        "reference_is_final": True,
        "reference_adjustment": "qfq",
        "reason_snapshot": {},
    }
    entry.update(updates)
    return entry


def _shadow_digest(entries):
    ordered = sorted(entries, key=lambda row: row["shadow_evaluation_id"])
    encoded = json.dumps(
        ordered,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_report(path, shadow_payload):
    path.write_text(
        json.dumps({
            "date": "2026-08-20",
            "shadow_evaluations": shadow_payload,
        }),
        encoding="utf-8",
    )


def _eligible_shadow_report(entries, *, digest=None, status="collecting"):
    return {
        "mode": "shadow",
        "status": status,
        "today_entries": entries,
        "pending": {
            "status": "staged",
            "batch_sha256": digest or _shadow_digest(entries),
        },
    }


class FinalizeRecommendationLedgerTests(unittest.TestCase):
    def test_finalizer_accepts_an_injected_verified_report_path(self):
        self.assertIn("report_path", inspect.signature(finalize_for_date).parameters)

    def test_shadow_batch_digest_is_canonical_and_includes_generated_at(self):
        first = _shadow_entry()
        second = _shadow_entry(
            shadow_evaluation_id="shadow:two",
            code="300309",
        )
        digest = getattr(
            shadow_evaluation, "shadow_batch_digest", lambda _entries: None
        )

        self.assertEqual(digest([second, first]), _shadow_digest([first, second]))
        self.assertEqual(
            digest([dict(second), dict(reversed(list(first.items())))]),
            _shadow_digest([first, second]),
        )
        self.assertNotEqual(
            digest([first]),
            digest([dict(first, generated_at="2026-08-20T15:20:00+08:00")]),
        )

    def test_finalizes_formal_and_shadow_batches_without_mixing_them(self):
        formal = {
            "recommendation_id": "rec:one",
            "report_date": "2026-08-20",
            "code": "300308",
        }
        shadow = _shadow_entry()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            formal_pending_dir = root / "formal-pending"
            shadow_pending_dir = root / "shadow-pending"
            formal_ledger = root / "formal.jsonl"
            shadow_ledger = root / "shadow.jsonl"
            report_path = root / "report.json"
            stage_recommendation_entries(
                pending_ledger_path("2026-08-20", formal_pending_dir),
                [formal],
            )
            stage_shadow_evaluation_entries(
                shadow_pending_ledger_path("2026-08-20", shadow_pending_dir),
                [shadow],
            )
            _write_report(report_path, _eligible_shadow_report([shadow]))

            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=formal_pending_dir,
                recommendation_ledger_path=formal_ledger,
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
                report_path=report_path,
            )

            self.assertEqual(result["status"], "finalized")
            self.assertEqual(result["appended_entries"], 1)
            self.assertEqual(result["shadow_status"], "finalized")
            self.assertEqual(result["shadow_appended_entries"], 1)
            self.assertEqual(load_recommendation_entries(formal_ledger), [formal])
            self.assertEqual(load_shadow_evaluation_entries(shadow_ledger), [shadow])

            retry = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=formal_pending_dir,
                recommendation_ledger_path=formal_ledger,
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
                report_path=report_path,
            )
            self.assertEqual(retry["appended_entries"], 0)
            self.assertEqual(retry["shadow_status"], "finalized")
            self.assertEqual(retry["shadow_appended_entries"], 0)

    def test_partial_report_is_evaluable_and_default_report_path_is_used(self):
        shadow = _shadow_entry()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shadow_pending_dir = root / "shadow-pending"
            shadow_ledger = root / "shadow.jsonl"
            report_path = root / "docs" / "data" / "2026-08-20.json"
            report_path.parent.mkdir(parents=True)
            stage_shadow_evaluation_entries(
                shadow_pending_ledger_path(
                    "2026-08-20", shadow_pending_dir
                ),
                [shadow],
            )
            _write_report(
                report_path,
                _eligible_shadow_report([shadow], status="partial"),
            )

            with mock.patch.object(finalizer, "ROOT_DIR", str(root)):
                result = finalize_for_date(
                    "2026-08-20",
                    recommendation_pending_dir=root / "formal-pending",
                    recommendation_ledger_path=root / "formal.jsonl",
                    shadow_pending_dir=shadow_pending_dir,
                    shadow_ledger_path=shadow_ledger,
                )

            self.assertEqual(result["shadow_status"], "finalized")
            self.assertEqual(result["shadow_appended_entries"], 1)
            self.assertEqual(
                load_shadow_evaluation_entries(shadow_ledger), [shadow]
            )

    def test_unavailable_or_disabled_report_never_finalizes_old_shadow_pending(self):
        shadow = _shadow_entry()
        for status in ("unavailable", "disabled"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                shadow_pending_dir = root / "shadow-pending"
                shadow_ledger = root / "shadow.jsonl"
                report_path = root / "report.json"
                stage_shadow_evaluation_entries(
                    shadow_pending_ledger_path(
                        "2026-08-20", shadow_pending_dir
                    ),
                    [shadow],
                )
                _write_report(report_path, {
                    "status": status,
                    "today_entries": [],
                })

                result = finalize_for_date(
                    "2026-08-20",
                    recommendation_pending_dir=root / "formal-pending",
                    recommendation_ledger_path=root / "formal.jsonl",
                    shadow_pending_dir=shadow_pending_dir,
                    shadow_ledger_path=shadow_ledger,
                    report_path=report_path,
                )

                self.assertIn(result["shadow_status"], {"withheld", "unavailable"})
                self.assertEqual(result["shadow_appended_entries"], 0)
                self.assertFalse(shadow_ledger.exists())

    def test_off_mode_report_is_withheld_even_if_status_is_tampered_to_collecting(self):
        shadow = _shadow_entry()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shadow_pending_dir = root / "shadow-pending"
            shadow_ledger = root / "shadow.jsonl"
            report_path = root / "report.json"
            stage_shadow_evaluation_entries(
                shadow_pending_ledger_path(
                    "2026-08-20", shadow_pending_dir
                ),
                [shadow],
            )
            payload = _eligible_shadow_report([shadow])
            payload["mode"] = "off"
            _write_report(report_path, payload)

            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=root / "formal-pending",
                recommendation_ledger_path=root / "formal.jsonl",
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
                report_path=report_path,
            )

            self.assertEqual(result["shadow_status"], "withheld")
            self.assertEqual(result["shadow_appended_entries"], 0)
            self.assertFalse(shadow_ledger.exists())

    def test_missing_or_mismatched_report_digest_withholds_shadow_batch(self):
        shadow = _shadow_entry()
        cases = {
            "missing_pending": {"status": "collecting"},
            "missing_digest": {
                "status": "collecting",
                "today_entries": [shadow],
                "pending": {"status": "staged"},
            },
            "mismatched_digest": _eligible_shadow_report(
                [shadow], digest="0" * 64
            ),
        }
        for name, payload in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                shadow_pending_dir = root / "shadow-pending"
                shadow_ledger = root / "shadow.jsonl"
                report_path = root / "report.json"
                stage_shadow_evaluation_entries(
                    shadow_pending_ledger_path(
                        "2026-08-20", shadow_pending_dir
                    ),
                    [shadow],
                )
                _write_report(report_path, payload)

                result = finalize_for_date(
                    "2026-08-20",
                    recommendation_pending_dir=root / "formal-pending",
                    recommendation_ledger_path=root / "formal.jsonl",
                    shadow_pending_dir=shadow_pending_dir,
                    shadow_ledger_path=shadow_ledger,
                    report_path=report_path,
                )

                self.assertIn(result["shadow_status"], {"withheld", "unavailable"})
                self.assertEqual(result["shadow_appended_entries"], 0)
                self.assertFalse(shadow_ledger.exists())

    def test_tampered_pending_is_rejected_without_affecting_formal_finalization(self):
        formal = {
            "recommendation_id": "rec:one",
            "report_date": "2026-08-20",
            "code": "300308",
        }
        shadow = _shadow_entry()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            formal_pending_dir = root / "formal-pending"
            shadow_pending_dir = root / "shadow-pending"
            formal_ledger = root / "formal.jsonl"
            shadow_ledger = root / "shadow.jsonl"
            report_path = root / "report.json"
            stage_recommendation_entries(
                pending_ledger_path("2026-08-20", formal_pending_dir),
                [formal],
            )
            shadow_pending = Path(shadow_pending_ledger_path(
                "2026-08-20", shadow_pending_dir
            ))
            stage_shadow_evaluation_entries(shadow_pending, [shadow])
            _write_report(report_path, _eligible_shadow_report([shadow]))
            shadow_pending.write_text(
                json.dumps([
                    dict(shadow, generated_at="2026-08-20T15:20:00+08:00")
                ]),
                encoding="utf-8",
            )

            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=formal_pending_dir,
                recommendation_ledger_path=formal_ledger,
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
                report_path=report_path,
            )

            self.assertEqual(result["status"], "finalized")
            self.assertEqual(result["appended_entries"], 1)
            self.assertIn(result["shadow_status"], {"withheld", "unavailable"})
            self.assertEqual(result["shadow_appended_entries"], 0)
            self.assertEqual(load_recommendation_entries(formal_ledger), [formal])
            self.assertFalse(shadow_ledger.exists())

    def test_corrupt_shadow_pending_does_not_roll_back_formal_finalization(self):
        formal = {
            "recommendation_id": "rec:one",
            "report_date": "2026-08-20",
            "code": "300308",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            formal_pending_dir = root / "formal-pending"
            shadow_pending_dir = root / "shadow-pending"
            formal_ledger = root / "formal.jsonl"
            shadow_ledger = root / "shadow.jsonl"
            report_path = root / "report.json"
            stage_recommendation_entries(
                pending_ledger_path("2026-08-20", formal_pending_dir),
                [formal],
            )
            shadow_pending = Path(shadow_pending_ledger_path(
                "2026-08-20", shadow_pending_dir
            ))
            shadow_pending.parent.mkdir(parents=True)
            shadow_pending.write_text("{broken json", encoding="utf-8")
            _write_report(
                report_path,
                _eligible_shadow_report([_shadow_entry()]),
            )

            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=formal_pending_dir,
                recommendation_ledger_path=formal_ledger,
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
                report_path=report_path,
            )

            self.assertEqual(result["status"], "finalized")
            self.assertEqual(result["appended_entries"], 1)
            self.assertEqual(result["shadow_status"], "unavailable")
            self.assertIn("JSONDecodeError", result["shadow_error"])
            self.assertEqual(load_recommendation_entries(formal_ledger), [formal])
            self.assertFalse(shadow_ledger.exists())

    def test_return_contract_stays_compatible_when_no_batches_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=root / "formal-pending",
                recommendation_ledger_path=root / "formal.jsonl",
                shadow_pending_dir=root / "shadow-pending",
                shadow_ledger_path=root / "shadow.jsonl",
                report_path=root / "missing-report.json",
            )

        self.assertEqual(result["status"], "no_pending_batch")
        self.assertEqual(result["appended_entries"], 0)
        self.assertIn(result["shadow_status"], {"withheld", "unavailable"})
        self.assertEqual(result["shadow_appended_entries"], 0)


if __name__ == "__main__":
    unittest.main()
