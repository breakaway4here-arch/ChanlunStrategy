import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import chanlun.shadow_evaluation as shadow_evaluation
from chanlun.h4_t3_pool import STRATEGY_VERSION


def _candidate(index):
    code = "{:06d}".format(300000 + index)
    return {
        "code": code,
        "name": "candidate-{}".format(index),
        "dates": ["2026-08-21", "2026-08-22"],
        "closes": [10.0 + index, 11.0 + index],
        "data_status": {
            "daily": "verified",
            "latest_date": "2026-08-22",
            "source": "market_history_db",
            "is_final": True,
        },
        "decision_engine_v1": {"decision_code": "recommend"},
        "reason": "formal reason {}".format(index),
    }


def _formal_report(candidate_count=7):
    h4_candidates = [_candidate(index) for index in range(candidate_count)]
    return {
        "date": "2026-08-22",
        "picks_pure": [{"code": "000001", "reason": "pure"}],
        "picks_fusion": [{"code": "000002", "reason": "fusion"}],
        "startup_watchlist": [{"code": "000003"}],
        "observation_watchlist": [{"code": "000004"}],
        "next_day_boom": {"candidates": [{"code": "000005"}]},
        "luojie_pool": {"candidates": [{"code": "000006"}]},
        "h4_t3_pool": {
            "strategy_version": STRATEGY_VERSION,
            "candidates": h4_candidates,
        },
        "recommendation_ledger": [{"recommendation_id": "formal:one"}],
        "strategy_scorecards": [{"strategy_name": "formal"}],
        "diagnostics": {
            "candidate_funnel": {"persist_status": "saved", "final": ["000002"]}
        },
        "data_quality": {
            "runtime_policy": {
                "market_history_cutover_mode": "sqlite",
                "recall_strategy_mode": "active",
                "stock_selection_shadow_mode": "shadow",
            }
        },
    }


def _empty_review_context(_db_path, _entries, *, as_of=None):
    return {}, [], None, {"status": "empty", "as_of": as_of}


class DailyShadowIntegrationTests(unittest.TestCase):
    def test_shadow_integrates_only_h4_all_candidates_and_preserves_formal_snapshot(self):
        report = _formal_report(candidate_count=7)
        before = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=True,
                ledger_path=Path(tmpdir) / "ledger.jsonl",
                pending_dir=Path(tmpdir) / "pending",
                db_path=Path(tmpdir) / "market.sqlite",
                review_context_loader=_empty_review_context,
            )

            pending = shadow_evaluation.shadow_pending_ledger_path(
                "2026-08-22", pending_dir=Path(tmpdir) / "pending"
            )
            self.assertTrue(Path(pending).exists())

        self.assertEqual(report, before)
        self.assertEqual(payload["mode"], "shadow")
        self.assertEqual(payload["status"], "collecting")
        self.assertTrue(payload["production_guard"]["unchanged"])
        self.assertFalse(payload["affects_production"])
        self.assertEqual(len(payload["experiments"]), 1)
        experiment = payload["experiments"][0]
        self.assertEqual(experiment["experiment_id"], "h4-t3-close-review-v1")
        self.assertEqual(experiment["display_name"], "H4 T+3 收盘价影子回看")
        self.assertEqual(experiment["version"], STRATEGY_VERSION)
        self.assertEqual(experiment["upstream_pool"], "picks_pure")
        self.assertEqual(experiment["source_pool"], "h4_t3_pool")
        self.assertEqual(experiment["intended_horizon"], 3)
        self.assertEqual(experiment["entry_mode"], "immediate_close")
        self.assertEqual(experiment["reference_adjustment"], "qfq")
        candidates = experiment["today"]["candidates"]
        self.assertEqual(len(candidates), 7)
        self.assertEqual(
            [row["code"] for row in candidates],
            [row["code"] for row in before["h4_t3_pool"]["candidates"]],
        )
        self.assertTrue(all(row["reference_is_final"] for row in candidates))
        self.assertTrue(all(row["reference_adjustment"] == "qfq" for row in candidates))
        self.assertNotIn("next_day_boom", [row["experiment_id"] for row in payload["experiments"]])
        shadow_ids = {row["shadow_evaluation_id"] for row in payload["today_entries"]}
        formal_text = repr(before)
        self.assertTrue(shadow_ids)
        self.assertTrue(all(shadow_id not in formal_text for shadow_id in shadow_ids))

    def test_off_mode_does_not_run_load_or_stage(self):
        report = _formal_report()
        with mock.patch.object(
            shadow_evaluation, "run_shadow_evaluations"
        ) as runner, mock.patch.object(
            shadow_evaluation, "load_shadow_evaluation_entries"
        ) as loader, mock.patch.object(
            shadow_evaluation, "stage_shadow_evaluation_entries"
        ) as stage:
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="off",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=True,
            )

        self.assertEqual(payload["mode"], "off")
        self.assertEqual(payload["status"], "disabled")
        runner.assert_not_called()
        loader.assert_not_called()
        stage.assert_not_called()

    def test_runner_builder_guard_stage_and_scorecard_failures_degrade_without_formal_mutation(self):
        failure_cases = (
            ("run_shadow_evaluations", RuntimeError("runner failed")),
            ("_build_h4_shadow_result", RuntimeError("builder failed")),
            ("stage_shadow_evaluation_entries", OSError("stage failed")),
            ("build_shadow_scorecards", RuntimeError("scorecard failed")),
        )
        for target, error in failure_cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmpdir:
                report = _formal_report()
                before = copy.deepcopy(report)
                with mock.patch.object(shadow_evaluation, target, side_effect=error):
                    payload = shadow_evaluation.build_daily_shadow_evaluations(
                        report,
                        mode="shadow",
                        generated_at="2026-08-22T15:10:00+08:00",
                        publication_eligible=True,
                        ledger_path=Path(tmpdir) / "ledger.jsonl",
                        pending_dir=Path(tmpdir) / "pending",
                        db_path=Path(tmpdir) / "market.sqlite",
                        review_context_loader=_empty_review_context,
                    )
                self.assertEqual(report, before)
                self.assertEqual(payload["status"], "unavailable")
                self.assertEqual(payload["experiments"], [])

        report = _formal_report()
        guard_failed = {
            "schema_version": 1,
            "mode": "shadow",
            "affects_production": False,
            "status": "production_guard_failed",
            "production_guard": {
                "unchanged": False,
                "before_sha256": "before",
                "after_sha256": "after",
            },
            "production_reference": {},
            "experiments": [{
                "experiment_id": "h4-t3-close-review-v1",
                "status": "available",
                "today": {"candidates": [_candidate(1)]},
            }],
        }
        with mock.patch.object(
            shadow_evaluation, "run_shadow_evaluations", return_value=guard_failed
        ), mock.patch.object(
            shadow_evaluation, "stage_shadow_evaluation_entries"
        ) as stage:
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=True,
            )
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["experiments"], [])
        stage.assert_not_called()

    def test_builder_receives_copy_and_projection_failure_is_unavailable(self):
        report = _formal_report()
        before = copy.deepcopy(report)

        def mutating_runner(snapshot, experiments):
            snapshot["picks_pure"].clear()
            return {
                "schema_version": 1,
                "mode": "shadow",
                "affects_production": False,
                "status": "collecting",
                "production_guard": {
                    "unchanged": True,
                    "before_sha256": "same",
                    "after_sha256": "same",
                },
                "production_reference": {},
                "experiments": [],
            }

        with mock.patch.object(
            shadow_evaluation, "run_shadow_evaluations", side_effect=mutating_runner
        ):
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=False,
                review_context_loader=_empty_review_context,
            )
        self.assertEqual(report, before)
        self.assertEqual(payload["status"], "collecting")

        report["diagnostics"]["candidate_funnel"]["bad"] = object()
        payload = shadow_evaluation.build_daily_shadow_evaluations(
            report,
            mode="shadow",
            generated_at="2026-08-22T15:10:00+08:00",
            publication_eligible=False,
        )
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["experiments"], [])

    def test_run_hook_is_after_formal_report_and_before_report_generation(self):
        source = Path("run.py").read_text(encoding="utf-8")
        report_index = source.index("report_data = {")
        shadow_index = source.index("build_daily_shadow_evaluations(", report_index)
        generate_index = source.index("generate_report(report_data", report_index)
        for formal_token in (
            "recommendation_entries = build_recommendation_entries(",
            "strategy_scorecards = build_strategy_scorecards(",
            '"h4_t3_pool": h4_t3_pool',
            '"next_day_boom": next_day_boom',
            '"decision_brief": decision_brief',
        ):
            self.assertLess(source.index(formal_token), shadow_index)
        self.assertLess(report_index, shadow_index)
        self.assertLess(shadow_index, generate_index)


if __name__ == "__main__":
    unittest.main()
