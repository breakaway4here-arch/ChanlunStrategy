import copy
import json
import pathlib
import unittest

from chanlun.decision_workbench import (
    _instrument,
    build_decision_workbench,
    notification_semantics,
)
from chanlun.report_view_model import build_workspace
from chanlun.recommendation_ledger import build_recommendation_entries
from chanlun.report_generator import (
    _serialize_luojie_pool,
    _serialize_picks,
    _serialize_startup_watchlist,
)
from chanlun.strategy_review import (
    _manifest_price_basis,
    build_strategy_run_manifest,
    build_strategy_scorecards,
)


DAY = "2026-09-11"


def _report(**overrides):
    report = {
        "date": DAY,
        "data_quality": {
            "as_of": DAY + "T15:20:00+08:00",
            "is_official": True,
            "bar_state": "closed",
            "market_status": "verified",
            "universe_builder": {
                "eligibility": {
                    "instrument_count": 5951,
                    "eligible_count": 3482,
                    "excluded": {
                        "nonfinal_bars": 470,
                        "stale_latest_bar": 110,
                    },
                },
            },
        },
        "selection_input_health": {
            "schema_version": 2,
            "status": "verified",
            "formal": {
                "status": "verified",
                "formal_actions_allowed": True,
            },
            "by_strategy": {
                "daily_fusion": {"status": "verified", "formal_actions_allowed": True},
                "h4_t3": {"status": "verified", "formal_actions_allowed": True},
            },
            "sublevels": {
                "30m": {
                    "status": "partial",
                    "requested_count": 336,
                    "verified_count": 274,
                    "missing_count": 62,
                    "required_date": DAY,
                },
            },
        },
        "diagnostics": {
            "candidate_funnel": {
                "stage_counts": {"full_a": 5951, "retrieval": 873},
                "first_failure_counts": {"retrieval": 2609},
                "terminal_counts": {"observe": 20, "reject": 5887},
            },
            "sublevel_upgrade_fusion": {
                "requested_30min": 336,
                "fetched_30min": 274,
                "dropped_no_30min": 62,
                "dropped_no_confirm": 274,
            },
        },
        "strategy_scorecards": {
            "schema_version": 2,
            "formal": [{
                "strategy": "daily_fusion",
                "version": "daily-fusion-close-v1",
                "source_pool": "picks_fusion",
                "comparison_identity": {
                    "strategy": "daily_fusion",
                    "version": "daily-fusion-close-v1",
                    "policy_version": "policy-2026-09-11",
                    "source_pool": "picks_fusion",
                    "entry_mode": "immediate_close",
                },
                "latest_report_date": DAY,
            }],
        },
        "comparison_identity": {
            "price_basis": {
                "adjustment": "qfq",
                "factor_vs_raw": 1.02,
                "source": "verified_manifest",
            },
        },
    }
    report.update(overrides)
    return report


def _evidence(rows, *, blocked_code=None):
    result = {"report_date": DAY, "views": {}}
    for view, source_rows in rows.items():
        result["views"][view] = []
        for row in source_rows:
            code = row["code"]
            evidence = {
                "code": code,
                "summary": {"status": "available", "as_of": DAY},
                "daily_structure": {
                    "status": "available",
                    "as_of": DAY,
                    "is_final": True,
                },
                "sublevel_30m": {"status": "available", "as_of": DAY},
                "price_evidence": {"status": "available", "as_of": DAY},
                "risk_and_next": {
                    "status": "available",
                    "as_of": DAY,
                    "next_confirmation": ["回踩不破观察锚点"],
                    "invalidation_conditions": ["结构失效"],
                },
            }
            if code == blocked_code:
                evidence["daily_structure"]["status"] = "conflict"
            result["views"][view].append(evidence)
    return result


def _research_row(code="600001", **extra):
    row = {
        "code": code,
        "name": "观察样本",
        "action_semantics": "watch_only",
        "reference_price": 10.0,
        "current_price": 10.0,
        "price_basis": {"adjustment": "qfq", "factor_vs_raw": 1.02},
        "next_confirmation": ["回踩不破观察锚点"],
        "invalidation": ["结构失效"],
        "primary_reason": "等待确认",
        "ref": {"pool": "startup_watchlist", "code": code},
    }
    row.update(extra)
    return row


def _formal_row(code="600001", version="row-version-that-must-not-win"):
    return {
        "code": code,
        "name": "正式样本",
        "action_semantics": "formal",
        "price_basis": {"adjustment": "qfq", "factor_vs_raw": 1.02},
        "view_rank": 1,
        "decision_engine_v1": {"version": version, "total_score": 70},
        "formal_decision_contract": {
            "action": "可上车",
            "action_reason": "合同完整",
            "reference_price": 10.0,
            "invalidation_price": 9.0,
            "intended_horizon": 3,
            "position_band": "10%-20%",
        },
        "ref": {"pool": "picks_fusion", "code": code},
        "data_status": {"latest_date": DAY, "stale": False, "is_final": True},
    }


class ProjectAuditUiContracts(unittest.TestCase):
    def test_bare_beijing_92_code_keeps_exchange_identity(self):
        self.assertEqual(_instrument("920001"), ("920001", "BJ920001"))
        self.assertEqual(_instrument("920001.BJ"), ("920001", "BJ920001"))
        self.assertEqual(_instrument("600001"), ("600001", "SH600001"))

    def test_summary_exposes_real_eligibility_retrieval_and_minute_denominators(self):
        report = _report()
        workspace = {
            "views": {"main": [], "h4_t3": []},
            "view_meta": {
                "main": {"availability": {"state": "verified_empty"}},
                "h4_t3": {"availability": {"state": "verified_empty"}},
            },
        }
        result = build_decision_workbench(report, workspace, _evidence({}))
        coverage = result["summary"]["coverage"]
        self.assertEqual(coverage["eligibility"]["excluded"]["nonfinal_bars"], 470)
        self.assertEqual(coverage["eligibility"]["excluded"]["stale_latest_bar"], 110)
        self.assertEqual(coverage["retrieval"]["full_a"], 5951)
        self.assertEqual(coverage["retrieval"]["retrieval"], 873)
        self.assertEqual(coverage["retrieval"]["first_failure"], 2609)
        self.assertEqual(coverage["minute30"]["requested"], 336)
        self.assertEqual(coverage["minute30"]["verified"], 274)
        self.assertEqual(coverage["minute30"]["missing"], 62)
        self.assertEqual(coverage["status"], "partial")

    def test_coverage_uses_funnel_denominators_and_universe_final_fallback(self):
        report = _report(
            data_quality={
                "as_of": DAY + "T15:20:00+08:00",
                "is_official": True,
                "bar_state": "closed",
                "market_status": "verified",
                "universe_builder": {
                    "final_count": 7,
                    "retrieval_mode": "base_plus_overlay",
                    "base_count": 5,
                    "overlay_count": 2,
                },
            },
            diagnostics={
                "candidate_funnel": {
                    "stage_counts": {"full_a": 9, "eligible": 6},
                },
            },
            selection_input_health={
                "formal": {
                    "status": "verified",
                    "formal_actions_allowed": True,
                },
                "sublevels": {
                    "30m": {
                        "status": "verified",
                        "requested_count": 1,
                        "verified_count": 1,
                        "missing_count": 0,
                    },
                },
            },
        )
        coverage = build_decision_workbench(
            report, {"views": {"main": [], "h4_t3": []}}, _evidence({})
        )["summary"]["coverage"]
        self.assertEqual(coverage["eligibility"]["instrument_count"], 9)
        self.assertEqual(coverage["eligibility"]["eligible_count"], 6)
        self.assertEqual(coverage["retrieval"]["retrieval"], 7)
        self.assertEqual(coverage["retrieval"]["mode"], "base_plus_overlay")
        self.assertEqual(coverage["status"], "verified")

    def test_missing_coverage_fields_are_unknown_and_never_zero(self):
        report = _report(
            data_quality={"as_of": DAY + "T15:20:00+08:00", "is_official": True,
                          "bar_state": "closed", "market_status": "verified"},
            diagnostics={},
            selection_input_health={
                "formal": {"status": "verified", "formal_actions_allowed": True},
            },
        )
        result = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        coverage = result["summary"]["coverage"]
        self.assertEqual(coverage["status"], "unknown")
        self.assertIsNone(coverage["eligibility"]["instrument_count"])
        self.assertIsNone(coverage["minute30"]["requested"])

    def test_nonfinite_or_fractional_coverage_counts_are_unknown(self):
        report = _report()
        report["data_quality"]["universe_builder"]["eligibility"].update({
            "instrument_count": float("inf"),
            "eligible_count": 1.9,
        })
        result = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        coverage = result["summary"]["coverage"]
        self.assertIsNone(coverage["eligibility"]["instrument_count"])
        self.assertIsNone(coverage["eligibility"]["eligible_count"])

    def test_recorded_eligibility_with_unknown_retrieval_and_minutes_is_not_verified(self):
        report = _report(
            selection_input_health={
                "formal": {
                    "status": "verified",
                    "formal_actions_allowed": True,
                },
            },
            diagnostics={},
        )
        result = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        coverage = result["summary"]["coverage"]
        self.assertEqual(coverage["status"], "partial")
        self.assertIn("retrieval_coverage_unrecorded", coverage["reasons"])
        self.assertIn("minute30_coverage_unrecorded", coverage["reasons"])
        self.assertEqual(coverage["minute30"]["status"], "unknown")

    def test_coverage_rejects_inconsistent_minute_and_eligibility_relations(self):
        report = _report()
        report["selection_input_health"]["sublevels"]["30m"].update({
            "status": "verified",
            "requested_count": 10,
            "verified_count": 8,
            "missing_count": 1,
        })
        report["data_quality"]["universe_builder"]["eligibility"].update({
            "instrument_count": 10,
            "eligible_count": 11,
        })
        result = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        coverage = result["summary"]["coverage"]
        self.assertEqual(coverage["minute30"]["status"], "conflict")
        self.assertIn("minute30_coverage_conflict", coverage["reasons"])
        self.assertIn("eligibility_coverage_conflict", coverage["reasons"])

    def test_observation_conditions_without_anchor_stay_watch_only(self):
        row = _research_row()
        result = build_decision_workbench(
            _report(),
            {"views": {"confirming": [row]}},
            _evidence({"confirming": [row]}),
        )
        item = result["items"][0]
        self.assertEqual(item["page_status"], "watch_only")
        self.assertIsNone(item["watch_reference_price"])
        self.assertEqual(item["watch_anchor"]["status"], "missing")
        self.assertIn("缺少可验证观察锚点", item["watch_anchor"]["reason"])
        self.assertNotIn("失效位", json.dumps(item["watch_anchor"], ensure_ascii=False))

    def test_observation_with_explicit_anchor_can_wait_for_trigger(self):
        row = _research_row(
            watch_anchor={
                "value": 9.8,
                "source": "candidate.pivot_info.breakout",
                "reference_date": DAY,
                "price_basis": {"adjustment": "qfq", "factor_vs_raw": 1.02},
                "purpose": "观察回踩是否守住突破位",
            },
        )
        result = build_decision_workbench(
            _report(),
            {"views": {"confirming": [row]}},
            _evidence({"confirming": [row]}),
        )
        item = result["items"][0]
        self.assertEqual(item["page_status"], "waiting_trigger")
        self.assertEqual(item["watch_anchor"]["value"], 9.8)
        self.assertEqual(item["watch_anchor"]["source"], "candidate.pivot_info.breakout")
        self.assertEqual(item["watch_reference_price"], 9.8)

    def test_report_serializers_preserve_source_basis_and_anchor_fields(self):
        basis = {"adjustment": "qfq", "factor_vs_raw": 1.02}
        anchor = {
            "value": 9.8,
            "source": "candidate.pivot_info.breakout",
            "reference_date": DAY,
            "price_basis": basis,
            "purpose": "观察回踩",
        }
        pick = {
            "code": "600001",
            "name": "正式样本",
            "price_basis": basis,
            "watch_anchor": anchor,
            "pivots": {},
        }
        self.assertEqual(_serialize_picks([pick])[0]["price_basis"], basis)
        self.assertEqual(_serialize_picks([pick])[0]["watch_anchor"], anchor)
        startup = _serialize_startup_watchlist([{
            "code": "600001",
            "price_basis": basis,
            "watch_anchor": anchor,
        }])[0]
        self.assertEqual(startup["price_basis"], basis)
        self.assertEqual(startup["watch_anchor"], anchor)
        luojie = _serialize_luojie_pool({"candidates": [{
            "code": "600001",
            "price_basis": basis,
            "watch_anchor": anchor,
        }]})["candidates"][0]
        self.assertEqual(luojie["price_basis"], basis)
        self.assertEqual(luojie["watch_anchor"], anchor)

    def test_future_or_conflicting_anchor_cannot_be_revived_by_report_date(self):
        for anchor in (
            {
                "value": 9.8,
                "source": "candidate.pivot_info.breakout",
                "reference_date": "2026-09-12",
                "price_basis": {"adjustment": "qfq", "factor_vs_raw": 1.02},
                "purpose": "观察回踩",
            },
            {
                "value": 9.8,
                "source": "candidate.pivot_info.breakout",
                "reference_date": DAY,
                "price_basis": {"adjustment": "raw", "factor_vs_raw": 1.0},
                "purpose": "观察回踩",
            },
        ):
            with self.subTest(anchor=anchor):
                row = _research_row(watch_anchor=anchor)
                result = build_decision_workbench(
                    _report(),
                    {"views": {"confirming": [row]}},
                    _evidence({"confirming": [row]}),
                )
                item = result["items"][0]
                self.assertEqual(item["page_status"], "watch_only")
                self.assertIsNone(item["watch_reference_price"])

    def test_anchor_with_unverifiable_basis_stays_missing(self):
        row = _research_row(
            price_basis={"adjustment": "qfq"},
            watch_anchor={
                "value": 9.8,
                "source": "candidate.pivot_info.breakout",
                "reference_date": DAY,
                "price_basis": {"adjustment": "qfq", "factor_vs_raw": 1.02},
                "purpose": "观察回踩",
            },
        )
        result = build_decision_workbench(
            _report(),
            {"views": {"confirming": [row]}},
            _evidence({"confirming": [row]}),
        )
        item = result["items"][0]
        self.assertEqual(item["page_status"], "watch_only")
        self.assertEqual(item["watch_anchor"]["status"], "invalid")
        self.assertIn("candidate_price_basis_invalid", item["watch_anchor"]["missing_fields"])

    def test_comparison_uses_scorecard_identity_when_pool_is_empty(self):
        report = _report()
        result = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        contract = result["comparison_contract"]
        self.assertEqual(
            contract["strategy_version"]["daily_fusion"],
            "daily-fusion-close-v1",
        )
        self.assertEqual(contract["price_basis"]["adjustment"], "qfq")
        self.assertNotIn("row-version-that-must-not-win", json.dumps(contract))
        self.assertEqual(
            contract["strategy_identities"][0]["policy_version"],
            "policy-2026-09-11",
        )

    def test_manifest_and_scorecard_carry_only_declared_price_basis(self):
        basis = {
            "adjustment": "qfq",
            "factor_vs_raw": 1.02,
            "raw_current_price": 9.8,
            "adjusted_current_price": 9.996,
            "as_of": DAY,
        }
        report = _report(
            picks_pure=[{"code": "600001", "price_basis": basis}],
            picks_fusion=[{"code": "600001", "price_basis": basis}],
            observation_watchlist=[],
            next_day_boom={"mode": "disabled", "candidates": []},
            luojie_pool={"mode": "enabled", "candidates": []},
            h4_t3_pool={"mode": "production", "status": "ok", "candidates": []},
            comparison_identity={"price_basis": basis},
            recommendation_entries=[{
                "policy_version": "policy-from-ledger",
                "strategy_contributions": [{"strategy_name": "daily_fusion"}],
            }],
            strategy_inputs=[{
                "strategy_name": "daily_fusion",
                "strategy_version": "daily-fusion-policy-v2",
            }],
        )
        manifest = build_strategy_run_manifest(report)
        self.assertTrue(manifest)
        self.assertTrue(all(item.get("price_basis") == basis for item in manifest))
        self.assertEqual(
            next(item for item in manifest if item["strategy"] == "daily_fusion")["policy_version"],
            "policy-from-ledger",
        )
        self.assertEqual(
            next(item for item in manifest if item["strategy"] == "daily_fusion")["version"],
            "daily-fusion-policy-v2",
        )
        cards = build_strategy_scorecards([], {}, run_manifest=manifest)
        self.assertTrue(all(
            card.get("comparison_identity", {}).get("price_basis") == basis
            for group in ("formal", "baselines", "research")
            for card in cards[group]
            if card.get("comparison_identity", {}).get("strategy")
        ))
        self.assertEqual(
            next(card for card in cards["formal"]
                 if card["strategy"] == "daily_fusion")["comparison_identity"]["policy_version"],
            "policy-from-ledger",
        )
        self.assertEqual(
            next(card for card in cards["formal"]
                 if card["strategy"] == "daily_fusion")["comparison_identity"]["version"],
            "daily-fusion-policy-v2",
        )

    def test_current_strategy_input_identity_wins_older_ledger_policy(self):
        report = _report(
            picks_pure=[],
            picks_fusion=[],
            observation_watchlist=[],
            next_day_boom={"mode": "disabled", "candidates": []},
            luojie_pool={"mode": "enabled", "candidates": []},
            h4_t3_pool={"mode": "production", "status": "ok", "candidates": []},
            strategy_inputs=[{
                "strategy_name": "daily_fusion",
                "strategy_version": "fusion-current-v2",
                "policy_version": "policy-current-v2",
            }],
            recommendation_entries=[{
                "policy_version": "policy-old-v1",
                "strategy_contributions": [{"strategy_name": "daily_fusion"}],
            }],
        )
        manifest = build_strategy_run_manifest(report)
        current = next(row for row in manifest if row["strategy"] == "daily_fusion")
        self.assertEqual(current["version"], "fusion-current-v2")
        self.assertEqual(current["policy_version"], "policy-current-v2")

    def test_different_stock_factors_are_compared_per_stock(self):
        previous_rows = [_formal_row("600001"), _formal_row("600002")]
        previous_rows[1]["price_basis"] = {
            "adjustment": "qfq", "factor_vs_raw": 1.05,
        }
        previous = build_decision_workbench(
            _report(), {"views": {"main": previous_rows}},
            _evidence({"main": previous_rows}),
        )
        current_rows = copy.deepcopy(previous_rows)
        current_rows[0]["formal_decision_contract"]["reference_price"] = 11.0
        current_rows[1]["formal_decision_contract"]["reference_price"] = 12.0
        current = build_decision_workbench(
            _report(), {"views": {"main": current_rows}},
            _evidence({"main": current_rows}), previous=previous,
        )
        self.assertEqual(current["changes"]["status"], "available")
        self.assertEqual(current["changes"]["changed"], ["600001", "600002"])

    def test_manifest_keeps_different_stock_basis_facts_without_common_factor(self):
        basis_a = {
            "adjustment": "qfq",
            "factor_vs_raw": 1.02,
            "raw_current_price": 10.0,
            "adjusted_current_price": 10.2,
            "reference_date": DAY,
        }
        basis_b = {
            "adjustment": "qfq",
            "factor_vs_raw": 1.05,
            "raw_current_price": 10.0,
            "adjusted_current_price": 10.5,
            "reference_date": DAY,
        }
        report = _report(
            comparison_identity={},
            picks_pure=[
                {"code": "600001", "price_basis": basis_a},
                {"code": "600002", "price_basis": basis_b},
            ],
            picks_fusion=[],
            observation_watchlist=[],
            next_day_boom={"mode": "disabled", "candidates": []},
            luojie_pool={"mode": "enabled", "candidates": []},
            h4_t3_pool={"mode": "production", "status": "ok", "candidates": []},
        )
        declared = _manifest_price_basis(report)
        self.assertEqual(declared["scope"], "per_instrument")
        self.assertEqual(
            declared["by_instrument"], {"600001": basis_a, "600002": basis_b}
        )
        manifest = build_strategy_run_manifest(report)
        self.assertTrue(all(
            row["price_basis"]["scope"] == "per_instrument"
            for row in manifest
        ))

        report["strategy_run_manifest"] = [{
            "strategy": "daily_fusion",
            "version": "daily-fusion-close-v1",
            "source_pool": "picks_fusion",
            "entry_mode": "immediate_close",
            "price_basis": declared,
        }]
        contract = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )["comparison_contract"]
        self.assertEqual(contract["price_basis"]["scope"], "per_instrument")
        self.assertFalse(contract["price_basis_invalid"])
        self.assertEqual(contract["price_basis_status"], "verified")
        self.assertEqual(contract["price_basis_scope"], "per_instrument")

    def test_one_stock_missing_or_changed_basis_only_hides_its_value_change(self):
        previous_rows = [_formal_row("600001"), _formal_row("600002")]
        previous = build_decision_workbench(
            _report(), {"views": {"main": previous_rows}},
            _evidence({"main": previous_rows}),
        )
        current_rows = copy.deepcopy(previous_rows)
        current_rows[0].pop("price_basis")
        current_rows[0]["formal_decision_contract"]["reference_price"] = 11.0
        current_rows[1]["formal_decision_contract"]["reference_price"] = 12.0
        current = build_decision_workbench(
            _report(), {"views": {"main": current_rows}},
            _evidence({"main": current_rows}), previous=previous,
        )
        self.assertEqual(current["changes"]["status"], "partial")
        self.assertIn("600001", current["changes"]["value_unavailable_codes"])
        self.assertEqual(current["changes"]["value_unavailable_reasons"]["600001"], "price_basis_missing")
        self.assertIn("600002", current["changes"]["changed"])
        self.assertNotIn("600001", current["changes"]["changed"])

        changed_rows = copy.deepcopy(previous_rows)
        changed_rows[0]["price_basis"] = {
            "adjustment": "qfq", "factor_vs_raw": 1.05,
        }
        changed_rows[0]["formal_decision_contract"]["reference_price"] = 11.0
        changed = build_decision_workbench(
            _report(), {"views": {"main": changed_rows}},
            _evidence({"main": changed_rows}), previous=previous,
        )
        self.assertEqual(changed["changes"]["value_unavailable_reasons"]["600001"], "price_basis_changed")

    def test_current_manifest_wins_over_accumulated_scorecard_cards(self):
        report = _report(
            strategy_run_manifest=[{
                "strategy": "daily_fusion",
                "version": "daily-fusion-policy-v2",
                "policy_version": "policy-v2",
                "source_pool": "picks_fusion",
                "entry_mode": "immediate_close",
                "research_tier": "prospective_ledger",
            }],
        )
        contract = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )["comparison_contract"]
        self.assertEqual(
            {(row["strategy_id"], row["strategy_version"])
             for row in contract["strategy_identities"]},
            {("daily_fusion", "daily-fusion-policy-v2")},
        )

    def test_strategy_version_change_only_blocks_affected_group(self):
        main_previous = _formal_row("600001")
        h4_previous = _formal_row("600002")
        workspace = {
            "views": {"main": [main_previous], "h4_t3": [h4_previous]},
            "view_meta": {
                "main": {"availability": {"state": "available"}},
                "h4_t3": {"availability": {"state": "available"}},
            },
        }
        previous_report = _report(strategy_run_manifest=[
            {"strategy": "daily_fusion", "version": "fusion-v1"},
            {"strategy": "h4_t3", "version": "h4-v1"},
        ])
        current_report = _report(strategy_run_manifest=[
            {"strategy": "daily_fusion", "version": "fusion-v2"},
            {"strategy": "h4_t3", "version": "h4-v1"},
        ])
        evidence = _evidence({"main": [main_previous], "h4_t3": [h4_previous]})
        previous = build_decision_workbench(previous_report, workspace, evidence)
        current_h4 = copy.deepcopy(h4_previous)
        current_h4["formal_decision_contract"]["reference_price"] = 12.0
        current_workspace = {
            "views": {"main": [main_previous], "h4_t3": [current_h4]},
            "view_meta": workspace["view_meta"],
        }
        current = build_decision_workbench(
            current_report, current_workspace,
            _evidence({"main": [main_previous], "h4_t3": [current_h4]}),
            previous=previous,
        )
        self.assertEqual(current["changes"]["status"], "partial")
        self.assertIn("600001", current["changes"]["unavailable_codes"])
        self.assertIn("600002", current["changes"]["changed"])

    def test_comparison_identity_change_is_incompatible_even_for_empty_pool(self):
        report = _report()
        current = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        previous = copy.deepcopy(current)
        previous["report_date"] = "2026-09-10"
        previous["comparison_contract"]["strategy_version"]["daily_fusion"] = "old-v0"
        result = build_decision_workbench(
            report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
            previous=previous,
        )
        self.assertEqual(result["changes"]["status"], "comparison_unavailable")
        self.assertIn("comparison_identity_changed", result["changes"]["reason"])

    def test_normal_run_to_empty_does_not_change_identity_signature(self):
        previous_report = _report(
            date="2026-09-10",
            data_quality={
                "as_of": "2026-09-10T15:20:00+08:00",
                "is_official": True,
                "bar_state": "closed",
                "market_status": "verified",
            },
        )
        previous_report["strategy_scorecards"]["formal"][0]["latest_report_date"] = "2026-09-10"
        previous_report["strategy_scorecards"]["formal"][0]["latest_run_status"] = "completed"
        current_report = _report()
        current_report["strategy_scorecards"]["formal"][0]["latest_run_status"] = "verified_empty"
        previous = build_decision_workbench(
            previous_report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
        )
        current = build_decision_workbench(
            current_report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
            previous=previous,
        )
        self.assertEqual(current["changes"]["status"], "available")
        self.assertEqual(current["changes"]["added"], [])
        self.assertEqual(current["changes"]["removed"], [])

        unavailable_report = copy.deepcopy(current_report)
        unavailable_report["strategy_scorecards"]["formal"][0]["latest_run_status"] = "unavailable"
        unavailable = build_decision_workbench(
            unavailable_report,
            {"views": {"main": [], "h4_t3": []}},
            _evidence({}),
            previous=previous,
        )
        self.assertEqual(unavailable["changes"]["status"], "partial")
        self.assertEqual(unavailable["changes"]["unavailable_strategies"], ["daily_fusion"])

    def test_one_bad_item_does_not_block_unrelated_comparison(self):
        rows = [_formal_row("600001"), _formal_row("600002")]
        workspace = {"views": {"main": rows}}
        previous = build_decision_workbench(
            _report(), workspace, _evidence({"main": rows})
        )
        current = copy.deepcopy(rows)
        current[0]["formal_decision_contract"]["action_reason"] = "条件变化"
        now = build_decision_workbench(
            _report(), {"views": {"main": current}},
            _evidence({"main": current}, blocked_code="600002"),
            previous=previous,
        )
        self.assertEqual(now["changes"]["status"], "partial")
        self.assertIn("600002", now["changes"]["unavailable_codes"])
        self.assertIn("600001", now["changes"]["changed"])

    def test_declared_manifest_basis_allows_numeric_condition_change(self):
        previous_row = _formal_row("600001")
        previous = build_decision_workbench(
            _report(),
            {"views": {"main": [previous_row]}},
            _evidence({"main": [previous_row]}),
        )
        current_row = copy.deepcopy(previous_row)
        current_row["formal_decision_contract"]["reference_price"] = 11.0
        current = build_decision_workbench(
            _report(),
            {"views": {"main": [current_row]}},
            _evidence({"main": [current_row]}),
            previous=previous,
        )
        self.assertEqual(current["changes"]["status"], "available")
        self.assertEqual(current["changes"]["changed"], ["600001"])
        self.assertNotIn("value_comparison_status", current["changes"])

    def test_mobile_visual_order_places_conclusion_before_market_evidence(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        css = (root / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")
        js = (root / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
        mobile_start = css.rfind("@media (max-width: 760px)")
        mobile = css[mobile_start:]
        self.assertIn(".mobile-decision-summary", mobile)
        self.assertIn("display: block", mobile)
        self.assertIn("mobile-decision-summary-copy", css)
        self.assertIn("width: fit-content", mobile)
        self.assertIn("id=\"mobileDecisionSummary\"", js)
        self.assertIn("class=\"mobile-decision-summary-copy\"", js)
        self.assertIn("href=\"#decisionOverview\"", js)
        self.assertIn("summary.coverage", js)
        self.assertIn("日线检索 ' + retrieval.retrieval + '/登记候选 '", js)
        self.assertIn("检索筛选未入", js)
        self.assertNotIn("日线检索预算", js)
        self.assertIn("watch_anchor", js)
        self.assertIn("成员级", js)
        self.assertIn("value_comparison_status", js)
        self.assertIn("anchorBasis.adjustment", js)

    def test_verified_research_partial_survives_workspace_manifest_and_notification_role_chain(self):
        verified = {
            "code": "600001",
            "name": "逐股核验样本",
            "action_semantics": "watch_only",
            "primary_reason": "15分钟研究观察",
        }
        unverified = {
            "code": "600002",
            "name": "待核验样本",
            "action_semantics": "watch_only",
        }
        input_health = {
            "status": "partial",
            "required_date": DAY,
            "requested_count": 2,
            "verified_count": 1,
            "verified_codes": ["600001"],
            "missing_count": 1,
            "missing_codes": ["600002"],
            "research_candidate_output_allowed": True,
            "formal_actions_allowed": False,
        }
        report = _report(
            picks_pure=[],
            picks_fusion=[],
            observation_watchlist=[],
            next_day_boom={"mode": "disabled", "candidates": []},
            luojie_pool={
                "mode": "partial",
                "status": "partial",
                "reason": "15分钟部分核验",
                "input_health": input_health,
                "candidates": [verified, unverified],
            },
            h4_t3_pool={
                "mode": "production",
                "status": "ok",
                "production_attested": True,
                "candidates": [],
            },
            selection_input_health={
                "formal": {
                    "status": "unavailable",
                    "formal_actions_allowed": False,
                },
                "by_strategy": {"luojie_pool": input_health},
            },
        )
        workspace = build_workspace(report)
        self.assertEqual(
            [row["code"] for row in workspace["views"]["luojie"]],
            ["600001"],
        )
        self.assertEqual(
            workspace["view_meta"]["luojie"]["availability"]["state"],
            "partial",
        )
        evidence = _evidence({"luojie": [verified]})
        projection = build_decision_workbench(report, workspace, evidence)
        self.assertEqual(projection["items"][0]["page_status"], "watch_only")
        self.assertIsNone(projection["items"][0]["formal_action"])

        manifest = build_strategy_run_manifest(report)
        luojie_manifest = next(
            row for row in manifest if row["strategy"] == "luojie_pool"
        )
        self.assertEqual(luojie_manifest["run_status"], "partial")
        self.assertEqual(luojie_manifest["signal_count"], 1)
        entries = build_recommendation_entries(
            DAY,
            DAY + "T15:20:00+08:00",
            [{
                "strategy_name": "luojie_pool",
                "strategy_version": "luojie-close-v1",
                "source_pool": "luojie_pool",
                "evaluation_role": "research",
                "publication_surface": "research_review",
                "entry_mode": "immediate_close",
                "items": [verified],
            }],
            policy_version="policy-v1",
            code_version="test-code",
        )
        contribution = entries[0]["strategy_contributions"][0]
        self.assertEqual(contribution["evaluation_role"], "research")
        self.assertEqual(contribution["publication_surface"], "research_review")
        notification = notification_semantics(projection)
        self.assertEqual(notification["items"][0]["status"], "watch_only")
        self.assertIsNone(notification["items"][0]["action"])

    def test_unproved_partial_research_and_partial_h4_remain_closed(self):
        candidate = {"code": "600001", "name": "未证明样本"}
        report = _report(
            picks_pure=[], picks_fusion=[], observation_watchlist=[],
            next_day_boom={"mode": "disabled", "candidates": []},
            luojie_pool={"mode": "partial", "status": "partial", "candidates": [candidate]},
            h4_t3_pool={
                "mode": "partial", "status": "partial",
                "production_attested": True, "candidates": [candidate],
            },
            selection_input_health={
                "formal": {"status": "unavailable", "formal_actions_allowed": False},
                "by_strategy": {
                    "luojie_pool": {"status": "partial", "verified_count": 0, "verified_codes": []},
                    "h4_t3": {"status": "partial", "formal_actions_allowed": False},
                },
            },
        )
        workspace = build_workspace(report)
        self.assertEqual(workspace["views"]["luojie"], [])
        self.assertFalse(workspace["views"].get("h4_t3"))
        manifest = build_strategy_run_manifest(report)
        by_strategy = {row["strategy"]: row for row in manifest}
        self.assertEqual(by_strategy["luojie_pool"]["run_status"], "unavailable")
        self.assertEqual(by_strategy["luojie_pool"]["signal_count"], 0)
        self.assertEqual(by_strategy["h4_t3"]["run_status"], "unavailable")
        self.assertFalse(report["selection_input_health"]["formal"]["formal_actions_allowed"])


if __name__ == "__main__":
    unittest.main()
