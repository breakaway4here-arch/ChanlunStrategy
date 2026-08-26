import copy
import unittest


from scripts.repair_strategy_scorecard_snapshot import (
    protected_report_digest,
    rebuild_strategy_scorecard_report,
    workspace_selection_projection,
)
from chanlun.report_view_model import build_workspace


class RepairStrategyScorecardSnapshotTests(unittest.TestCase):
    def _report(self):
        return {
            "date": "2026-08-26",
            "picks_pure": [{"code": "000001", "score": 88}],
            "picks_fusion": [{"code": "000001", "action": "建议关注"}],
            "next_day_boom": {"mode": "enabled", "candidates": []},
            "luojie_pool": {
                "mode": "enabled",
                "candidates": [{
                    "code": "000002",
                    "name": "研究样本",
                    "change_pct": 0,
                    "current_price": 10.0,
                    "dates": [],
                    "closes": [],
                }],
            },
            "strategy_scorecards": [],
            "diagnostics": {
                "strategy_review": {"status": "ok", "resolved_codes": 1},
                "other": {"status": "kept"},
            },
            "data_quality": {
                "report_date": "2026-08-26",
                "bar_state": "closed",
                "is_official": True,
                "market_status": "verified",
            },
            "shadow_evaluations": {
                "mode": "shadow",
                "production_guard": {
                    "unchanged": True,
                    "before_sha256": "old",
                    "after_sha256": "old",
                },
                "experiments": [{"experiment_id": "kept"}],
            },
            "workspace": {"legacy": True},
        }

    def test_rebuild_updates_only_review_surfaces_and_unproven_zero(self):
        original = self._report()
        original["workspace"] = build_workspace(original)
        before = protected_report_digest(original)
        workspace_before = workspace_selection_projection(
            original,
            ignore_views=("highlights", "luojie"),
        )
        scorecards = {
            "schema_version": 2,
            "thresholds": {"mature_samples": 100},
            "formal": [],
            "baselines": [],
            "research": [],
            "gates": [],
            "classification_failures": [],
        }
        diagnostics = {"status": "ok", "resolved_codes": 632}
        finalization = {
            "status": "finalized",
            "report_date": "2026-08-26",
            "today_entries": 1,
            "finalized_today_entries": 1,
            "missing_today_entries": 0,
            "finalized_entries": 878,
            "evaluation_entries": 878,
            "evidence": "immutable_ledger_membership",
        }

        rebuilt, repair_diagnostics = rebuild_strategy_scorecard_report(
            original,
            report_date="2026-08-26",
            scorecards=scorecards,
            review_diagnostics=diagnostics,
            ledger_finalization=finalization,
        )

        self.assertEqual(scorecards, rebuilt["strategy_scorecards"])
        self.assertEqual(diagnostics, rebuilt["diagnostics"]["strategy_review"])
        self.assertEqual({"status": "kept"}, rebuilt["diagnostics"]["other"])
        self.assertEqual(
            finalization, rebuilt["diagnostics"]["recommendation_ledger"]
        )
        self.assertIsNone(
            rebuilt["luojie_pool"]["candidates"][0]["change_pct"]
        )
        self.assertEqual(10.0, rebuilt["luojie_pool"]["candidates"][0]["current_price"])
        self.assertEqual([], rebuilt["workspace"]["views"]["luojie"])
        self.assertEqual(
            "strategy_upstream_contract_mismatch",
            rebuilt["selection_input_health"]["by_view"]["luojie"][
                "blocking_reason"
            ],
        )
        self.assertEqual(1, repair_diagnostics["unproven_zero_changes_removed"])
        self.assertIn("view_meta", rebuilt["workspace"])
        self.assertFalse(
            rebuilt["selection_input_health"]["formal"][
                "formal_actions_allowed"
            ]
        )
        self.assertEqual(
            ["300697"],
            rebuilt["selection_input_health"]["formal"]["invalid_codes"],
        )
        self.assertEqual([], rebuilt["workspace"]["views"]["main"])
        self.assertEqual(
            "unavailable",
            rebuilt["workspace"]["view_meta"]["main"]["availability"][
                "state"
            ],
        )
        self.assertEqual(
            workspace_before,
            workspace_selection_projection(
                rebuilt,
                ignore_views=("highlights", "luojie"),
            ),
        )
        self.assertEqual(before, protected_report_digest(rebuilt))
        self.assertEqual(
            {"experiment_id": "kept"},
            rebuilt["shadow_evaluations"]["experiments"][0],
        )
        guard = rebuilt["shadow_evaluations"]["production_guard"]
        self.assertTrue(guard["unchanged"])
        self.assertEqual(guard["before_sha256"], guard["after_sha256"])
        self.assertEqual(64, len(guard["after_sha256"]))

    def test_rebuild_keeps_zero_change_when_price_series_proves_it(self):
        original = self._report()
        candidate = original["luojie_pool"]["candidates"][0]
        candidate["dates"] = ["2026-08-25", "2026-08-26"]
        candidate["closes"] = [10.0, 10.0]

        rebuilt, diagnostics = rebuild_strategy_scorecard_report(
            original,
            report_date="2026-08-26",
            scorecards={
                "schema_version": 2,
                "thresholds": {},
                "formal": [],
                "baselines": [],
                "research": [],
                "gates": [],
                "classification_failures": [],
            },
            review_diagnostics={"status": "ok"},
        )

        self.assertEqual(
            0, rebuilt["luojie_pool"]["candidates"][0]["change_pct"]
        )
        self.assertEqual(0, diagnostics["unproven_zero_changes_removed"])

    def test_rebuild_rejects_non_official_or_wrong_day_snapshot(self):
        report = self._report()
        report["data_quality"]["is_official"] = False
        with self.assertRaisesRegex(ValueError, "official closed snapshot"):
            rebuild_strategy_scorecard_report(
                report,
                report_date="2026-08-26",
                scorecards={},
                review_diagnostics={"status": "ok"},
            )

        report = self._report()
        report["date"] = "2026-08-25"
        with self.assertRaisesRegex(ValueError, "report date mismatch"):
            rebuild_strategy_scorecard_report(
                report,
                report_date="2026-08-26",
                scorecards={},
                review_diagnostics={"status": "ok"},
            )

    def test_protected_digest_detects_formal_selection_drift(self):
        report = self._report()
        changed = copy.deepcopy(report)
        changed["picks_fusion"][0]["action"] = "不建议"
        self.assertNotEqual(
            protected_report_digest(report), protected_report_digest(changed)
        )

    def test_protected_digest_ignores_only_incident_health_annotation(self):
        report = self._report()
        changed = copy.deepcopy(report)
        changed["selection_input_health"] = {
            "status": "unavailable",
            "incident_ids": ["registered-incident"],
        }
        self.assertEqual(
            protected_report_digest(report), protected_report_digest(changed)
        )

    def test_registered_incident_suppresses_formal_view_without_rewriting_pool(self):
        report = self._report()
        report["selection_input_health"] = {
            "schema_version": 2,
            "status": "verified",
            "formal": {
                "formal_actions_allowed": True,
                "all_formal_actions_allowed": True,
            },
            "by_strategy": {
                "daily_fusion": {
                    "status": "verified",
                    "formal_actions_allowed": True,
                },
                "h4_t3": {
                    "status": "verified",
                    "formal_actions_allowed": True,
                },
            },
        }
        report["picks_fusion"] = [{
            "code": "300697",
            "name": "电工合金",
            "score": 88,
            "action": "可上车",
            "action_reason": "旧快照动作",
            "decision_engine_v1": {"decision_code": "recommend"},
        }]
        report["picks_pure"].append({
            "code": "300697", "name": "电工合金", "score": 88,
        })
        raw_pool = copy.deepcopy(report["picks_fusion"])
        report["workspace"] = build_workspace(report)
        self.assertEqual(1, len(report["workspace"]["views"]["main"]))

        rebuilt, _ = rebuild_strategy_scorecard_report(
            report,
            report_date="2026-08-26",
            scorecards={
                "schema_version": 2,
                "thresholds": {},
                "formal": [],
                "baselines": [],
                "research": [],
                "gates": [],
                "classification_failures": [],
            },
            review_diagnostics={"status": "ok"},
        )

        self.assertEqual(raw_pool, rebuilt["picks_fusion"])
        self.assertEqual([], rebuilt["workspace"]["views"]["main"])
        self.assertEqual([], rebuilt["workspace"]["views"]["highlights"])
        self.assertEqual(
            "strategy_upstream_contract_mismatch",
            rebuilt["selection_input_health"]["by_view"]["highlights"][
                "blocking_reason"
            ],
        )

    def test_incident_projection_ignores_only_formal_views_and_order(self):
        before = {
            "workspace": {
                "view_order": ["main", "baseline"],
                "views": {
                    "main": [{"code": "300697", "view_rank": 1}],
                    "baseline": [{"code": "000001", "view_rank": 1}],
                },
            },
        }
        after = copy.deepcopy(before)
        after["workspace"]["view_order"] = [
            "main", "h4_t3", "baseline"
        ]
        after["workspace"]["views"]["main"] = []
        after["workspace"]["views"]["h4_t3"] = []

        self.assertEqual(
            workspace_selection_projection(before, ignore_formal=True),
            workspace_selection_projection(after, ignore_formal=True),
        )
        self.assertNotEqual(
            workspace_selection_projection(before),
            workspace_selection_projection(after),
        )

    def test_rebuild_refuses_incomplete_ledger_finalization(self):
        report = self._report()
        with self.assertRaisesRegex(ValueError, "ledger finalization incomplete"):
            rebuild_strategy_scorecard_report(
                report,
                report_date="2026-08-26",
                scorecards={
                    "schema_version": 2,
                    "thresholds": {},
                    "formal": [],
                    "baselines": [],
                    "research": [],
                    "gates": [],
                    "classification_failures": [],
                },
                review_diagnostics={"status": "ok"},
                ledger_finalization={
                    "status": "finalization_incomplete",
                    "today_entries": 2,
                    "finalized_today_entries": 1,
                    "missing_today_entries": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()
