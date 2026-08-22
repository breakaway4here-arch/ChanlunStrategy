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
            "shadow_evaluation_id": "shadow:one",
            "evaluation_role": "shadow_candidate",
            "publication_effect": False,
            "evaluation_eligible": True,
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
