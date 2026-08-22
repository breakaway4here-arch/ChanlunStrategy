import tempfile
import unittest
from pathlib import Path

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


class FinalizeRecommendationLedgerTests(unittest.TestCase):
    def test_finalizes_formal_and_shadow_batches_without_mixing_them(self):
        formal = {
            "recommendation_id": "rec:one",
            "report_date": "2026-08-20",
            "code": "300308",
        }
        shadow = {
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
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            formal_pending_dir = root / "formal-pending"
            shadow_pending_dir = root / "shadow-pending"
            formal_ledger = root / "formal.jsonl"
            shadow_ledger = root / "shadow.jsonl"
            stage_recommendation_entries(
                pending_ledger_path("2026-08-20", formal_pending_dir),
                [formal],
            )
            stage_shadow_evaluation_entries(
                shadow_pending_ledger_path("2026-08-20", shadow_pending_dir),
                [shadow],
            )

            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=formal_pending_dir,
                recommendation_ledger_path=formal_ledger,
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
            )

            self.assertEqual(result["status"], "finalized")
            self.assertEqual(result["appended_entries"], 1)
            self.assertEqual(result["shadow_status"], "finalized")
            self.assertEqual(result["shadow_appended_entries"], 1)
            self.assertEqual(load_recommendation_entries(formal_ledger), [formal])
            self.assertEqual(load_shadow_evaluation_entries(shadow_ledger), [shadow])

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
            stage_recommendation_entries(
                pending_ledger_path("2026-08-20", formal_pending_dir),
                [formal],
            )
            shadow_pending = Path(shadow_pending_ledger_path(
                "2026-08-20", shadow_pending_dir
            ))
            shadow_pending.parent.mkdir(parents=True)
            shadow_pending.write_text("{broken json", encoding="utf-8")

            result = finalize_for_date(
                "2026-08-20",
                recommendation_pending_dir=formal_pending_dir,
                recommendation_ledger_path=formal_ledger,
                shadow_pending_dir=shadow_pending_dir,
                shadow_ledger_path=shadow_ledger,
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
            )

        self.assertEqual(result["status"], "no_pending_batch")
        self.assertEqual(result["appended_entries"], 0)
        self.assertEqual(result["shadow_status"], "no_pending_batch")
        self.assertEqual(result["shadow_appended_entries"], 0)


if __name__ == "__main__":
    unittest.main()
