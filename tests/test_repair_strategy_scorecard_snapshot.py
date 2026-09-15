import copy
import json
import unittest
from pathlib import Path


from scripts.repair_strategy_scorecard_snapshot import (
    _workspace_upstream_contract_violations,
    protected_report_digest,
    rebuild_strategy_scorecard_report,
    workspace_selection_projection,
)
from chanlun.report_view_model import build_workspace


class RepairStrategyScorecardSnapshotTests(unittest.TestCase):
    @staticmethod
    def _empty_scorecards():
        return {
            "schema_version": 2,
            "thresholds": {},
            "formal": [],
            "baselines": [],
            "research": [],
            "gates": [],
            "classification_failures": [],
        }

    def _rebuild(self, report):
        return rebuild_strategy_scorecard_report(
            report,
            report_date=str(report["date"]),
            scorecards=self._empty_scorecards(),
            review_diagnostics={"status": "ok"},
        )

    @staticmethod
    def _current_c8_report():
        path = Path(__file__).resolve().parents[1] / "docs/data/2026-09-14.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _remove_current_luojie_marker(report):
        report["selection_input_health"]["by_view"].pop("luojie", None)
        meta = report["workspace"]["view_meta"]["luojie"]
        meta.pop("upstream_contract", None)
        report["workspace"]["diagnostics"][
            "upstream_contract_incidents"
        ] = [
            row
            for row in report["workspace"]["diagnostics"][
                "upstream_contract_incidents"
            ]
            if row.get("view") != "luojie"
        ]

    @staticmethod
    def _mark_luojie_fully_verified(report):
        pool = report["luojie_pool"]
        pool["mode"] = "enabled"
        pool["status"] = "verified"
        pool["reason"] = ""
        for health in (
            pool["input_health"],
            report["selection_input_health"]["by_strategy"]["luojie_pool"],
        ):
            health["status"] = "verified"
            health["research_output_trusted"] = True
            health["blocking_reason"] = ""
            health["invalid_count"] = 0
            health["invalid_codes"] = []
            health["missing_count"] = 0
            health["missing_codes"] = []
            health["budget_excluded_count"] = 0
            health["budget_excluded_codes"] = []
            health["formal_actions_allowed"] = False
            health["research_candidate_output_allowed"] = True

    def test_limit_up_watch_exception_is_not_an_upstream_contract_incident(self):
        report = {
            "picks_pure": [],
            "workspace": {
                "views": {
                    "observation_top5": [{
                        "code": "301630",
                        "view": "observation",
                        "tier": "watch",
                        "price_limit_state": "limit_up",
                    }],
                    "confirming": [{
                        "code": "301630",
                        "view": "observation",
                        "tier": "watch",
                        "price_limit_state": "limit_up",
                    }],
                    "main": [{
                        "code": "301631",
                        "view": "main",
                        "tier": "candidate",
                        "price_limit_state": "limit_up",
                    }],
                    "growth_quality": [{
                        "code": "301632",
                        "view": "observation",
                        "tier": "watch",
                        "price_limit_state": "normal",
                    }],
                },
            },
        }

        violations = _workspace_upstream_contract_violations(report)

        self.assertNotIn("observation_top5", violations)
        self.assertNotIn("confirming", violations)
        self.assertEqual(["301631"], violations["main"])
        self.assertEqual(["301632"], violations["growth_quality"])

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

    def test_rebuild_restores_current_lossless_independent_luojie_partial(self):
        report = self._current_c8_report()
        original_pool = copy.deepcopy(report["luojie_pool"])
        original_luojie_health = copy.deepcopy(
            report["selection_input_health"]["by_strategy"]["luojie_pool"]
        )
        original_main = copy.deepcopy(report["workspace"]["views"]["main"])
        original_h4 = copy.deepcopy(report["workspace"]["views"]["h4_t3"])
        original_unrelated_incidents = [
            copy.deepcopy(row)
            for row in report["workspace"]["diagnostics"][
                "upstream_contract_incidents"
            ]
            if row.get("view") != "luojie"
        ]
        expected_codes = [
            str(row["code"]) for row in report["luojie_pool"]["candidates"]
        ]
        self.assertEqual(report["workspace"]["views"]["luojie"], [])
        self.assertEqual(
            report["selection_input_health"]["by_view"]["luojie"][
                "blocking_reason"
            ],
            "strategy_upstream_contract_mismatch",
        )

        rebuilt, diagnostics = self._rebuild(report)

        restored = rebuilt["workspace"]["views"]["luojie"]
        self.assertEqual([str(row["code"]) for row in restored], expected_codes)
        self.assertEqual(len(restored), 30)
        self.assertTrue(all(row.get("sources") == ["luojie"] for row in restored))
        self.assertTrue(all(row.get("action_semantics") == "watch_only" for row in restored))
        self.assertEqual(rebuilt["luojie_pool"], original_pool)
        self.assertEqual(rebuilt["workspace"]["views"]["main"], original_main)
        self.assertEqual(rebuilt["workspace"]["views"]["h4_t3"], original_h4)
        self.assertNotIn("luojie", rebuilt["selection_input_health"]["by_view"])
        self.assertIn("highlights", rebuilt["selection_input_health"]["by_view"])
        self.assertEqual(
            rebuilt["selection_input_health"]["by_strategy"]["luojie_pool"],
            original_luojie_health,
        )
        self.assertEqual(diagnostics["restored_independent_views"], ["luojie"])
        self.assertNotIn("luojie", diagnostics["upstream_contract_blocked_views"])
        self.assertIn("highlights", diagnostics["upstream_contract_blocked_views"])
        self.assertEqual(
            original_unrelated_incidents,
            [
                row
                for row in rebuilt["workspace"]["diagnostics"][
                    "upstream_contract_incidents"
                ]
                if row.get("view") != "luojie"
            ],
        )

    def test_rebuild_keeps_budget_or_health_contradictory_luojie_closed(self):
        def verified_with_budget_exclusion(report):
            report["luojie_pool"].update(mode="enabled", status="verified")
            for health in (
                report["luojie_pool"]["input_health"],
                report["selection_input_health"]["by_strategy"]["luojie_pool"],
            ):
                health["status"] = "verified"

        def embedded_budget_disagreement(report):
            report["luojie_pool"]["input_health"].update(
                budget_excluded_count=0,
                budget_excluded_codes=[],
            )

        def budget_overlaps_verified(report):
            code = report["luojie_pool"]["input_health"]["verified_codes"][0]
            for health in (
                report["luojie_pool"]["input_health"],
                report["selection_input_health"]["by_strategy"]["luojie_pool"],
            ):
                health.update(
                    budget_excluded_count=1,
                    budget_excluded_codes=[code],
                )

        def invalid_input_claimed_complete(report):
            self._mark_luojie_fully_verified(report)
            for health in (
                report["luojie_pool"]["input_health"],
                report["selection_input_health"]["by_strategy"]["luojie_pool"],
            ):
                health.update(invalid_count=1, invalid_codes=["600000"])

        def missing_budget_codes_claimed_complete(report):
            self._mark_luojie_fully_verified(report)
            for health in (
                report["luojie_pool"]["input_health"],
                report["selection_input_health"]["by_strategy"]["luojie_pool"],
            ):
                health.pop("budget_excluded_codes")

        for name, mutate in (
            ("verified_with_budget_exclusion", verified_with_budget_exclusion),
            ("embedded_budget_disagreement", embedded_budget_disagreement),
            ("budget_overlaps_verified", budget_overlaps_verified),
            ("invalid_input_claimed_complete", invalid_input_claimed_complete),
            ("missing_budget_codes_claimed_complete", missing_budget_codes_claimed_complete),
        ):
            with self.subTest(name=name):
                report = self._current_c8_report()
                mutate(report)

                rebuilt, diagnostics = self._rebuild(report)

                self.assertEqual([], rebuilt["workspace"]["views"]["luojie"])
                self.assertNotIn(
                    "luojie", diagnostics.get("restored_independent_views", [])
                )
                self.assertIn(
                    "luojie", diagnostics["upstream_contract_blocked_views"]
                )

    def test_independent_luojie_never_suppresses_formal_sibling_guards(self):
        report = self._current_c8_report()
        report["workspace"]["views"]["main"] = [{"code": "000839"}]
        report["workspace"]["views"]["h4_t3"] = [{"code": "000839"}]

        violations = _workspace_upstream_contract_violations(report)

        self.assertEqual(["000839"], violations["main"])
        self.assertEqual(["000839"], violations["h4_t3"])

    def test_rebuild_rejects_legacy_restore_with_another_luojie_incident(self):
        report = self._current_c8_report()
        report["workspace"]["diagnostics"][
            "upstream_contract_incidents"
        ].append({
            "view": "luojie",
            "blocking_reason": "data_source_conflict",
            "invalid_count": 1,
            "invalid_codes": [report["luojie_pool"]["candidates"][0]["code"]],
        })
        original = copy.deepcopy(report)

        with self.assertRaisesRegex(
            RuntimeError, "workspace membership or ordering changed"
        ):
            self._rebuild(report)

        self.assertEqual(original, report)

    def test_rebuild_does_not_allow_luojie_membership_change_without_own_marker(self):
        report = self._current_c8_report()
        report["selection_input_health"]["by_view"].pop("luojie")
        report["workspace"]["view_meta"]["luojie"].pop("upstream_contract")
        report["workspace"]["view_meta"]["luojie"]["availability"] = {
            "state": "partial",
            "reason": "旧页未保留专用视图，不能猜测恢复",
        }
        incidents = report["workspace"]["diagnostics"][
            "upstream_contract_incidents"
        ]
        report["workspace"]["diagnostics"]["upstream_contract_incidents"] = [
            row for row in incidents if row.get("view") != "luojie"
        ]

        with self.assertRaisesRegex(
            RuntimeError, "workspace membership or ordering changed"
        ):
            self._rebuild(report)

    def test_rebuild_keeps_luojie_blocked_when_independent_diagnostic_is_missing(self):
        report = self._current_c8_report()
        report["luojie_pool"]["diagnostics"].pop("final_common_upstream")

        rebuilt, diagnostics = self._rebuild(report)

        self.assertEqual(rebuilt["workspace"]["views"]["luojie"], [])
        self.assertEqual(
            rebuilt["selection_input_health"]["by_view"]["luojie"][
                "blocking_reason"
            ],
            "strategy_upstream_contract_mismatch",
        )
        self.assertNotIn("luojie", diagnostics.get("restored_independent_views", []))
        self.assertIn("luojie", diagnostics["upstream_contract_blocked_views"])

    def test_rebuild_preserves_clean_fully_verified_independent_luojie(self):
        report = self._current_c8_report()
        self._remove_current_luojie_marker(report)
        self._mark_luojie_fully_verified(report)
        report["workspace"] = build_workspace(report)
        expected_codes = [
            str(row["code"]) for row in report["luojie_pool"]["candidates"]
        ]
        self.assertNotIn(
            "luojie", _workspace_upstream_contract_violations(report)
        )

        rebuilt, diagnostics = self._rebuild(report)

        self.assertEqual(
            [str(row["code"]) for row in rebuilt["workspace"]["views"]["luojie"]],
            expected_codes,
        )
        self.assertNotIn("luojie", diagnostics["upstream_contract_blocked_views"])

    def test_rebuild_preserves_verified_empty_independent_luojie(self):
        report = self._current_c8_report()
        self._remove_current_luojie_marker(report)
        self._mark_luojie_fully_verified(report)
        report["luojie_pool"]["candidates"] = []
        upstream = report["luojie_pool"]["diagnostics"][
            "final_common_upstream"
        ]
        upstream.update({
            "input_count": 0,
            "kept_count": 0,
            "excluded_count": 0,
            "excluded_codes": [],
            "candidate_count": 0,
        })
        report["workspace"] = build_workspace(report)

        rebuilt, diagnostics = self._rebuild(report)

        self.assertEqual(rebuilt["workspace"]["views"]["luojie"], [])
        self.assertNotIn("luojie", diagnostics["upstream_contract_blocked_views"])
        self.assertNotIn("luojie", rebuilt["selection_input_health"]["by_view"])

    def test_rebuild_drops_failed_luojie_output_instead_of_exempting_it(self):
        report = self._current_c8_report()
        self._remove_current_luojie_marker(report)
        report["luojie_pool"]["mode"] = "enabled"
        report["luojie_pool"]["status"] = "failed"
        report["workspace"]["views"]["luojie"] = [{
            "code": "000839",
            "view_rank": 1,
            "sources": ["luojie"],
            "action_semantics": "watch_only",
            "ref": {"pool": "luojie_pool", "code": "000839"},
        }]
        report["workspace"]["counts"]["luojie"] = 1
        self.assertEqual(
            _workspace_upstream_contract_violations(report)["luojie"],
            ["000839"],
        )

        with self.assertRaisesRegex(
            RuntimeError, "workspace membership or ordering changed"
        ):
            self._rebuild(report)

    def test_rebuild_keeps_mixed_identity_luojie_closed(self):
        report = self._current_c8_report()
        report["luojie_pool"]["candidates"][0]["role"] = "formal"
        report["luojie_pool"]["candidates"][0]["action"] = "可上车"

        rebuilt, diagnostics = self._rebuild(report)

        self.assertEqual(rebuilt["workspace"]["views"]["luojie"], [])
        self.assertEqual(
            rebuilt["selection_input_health"]["by_view"]["luojie"][
                "blocking_reason"
            ],
            "strategy_upstream_contract_mismatch",
        )
        self.assertNotIn("luojie", diagnostics["restored_independent_views"])
        self.assertIn("luojie", diagnostics["upstream_contract_blocked_views"])

    def test_rebuild_keeps_unknown_identity_luojie_closed(self):
        report = self._current_c8_report()
        report["luojie_pool"]["candidates"][0]["role"] = "unknown"

        rebuilt, diagnostics = self._rebuild(report)

        self.assertEqual(rebuilt["workspace"]["views"]["luojie"], [])
        self.assertNotIn("luojie", diagnostics["restored_independent_views"])
        self.assertIn("luojie", diagnostics["upstream_contract_blocked_views"])


if __name__ == "__main__":
    unittest.main()
