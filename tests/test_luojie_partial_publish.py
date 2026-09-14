import copy
import json
import unittest

from chanlun.pool_contract import resolve_nested_strategy_pool
from chanlun.report_generator import _serialize_luojie_pool
from chanlun.report_view_model import build_workspace
from scripts.validate_today_report import validate_report_contract


def _official_report():
    return {
        "date": "2026-09-14",
        "picks_fusion": [],
        "picks_pure": [],
        "startup_watchlist": [],
        "observation_watchlist": [],
        "next_day_boom": {
            "mode": "disabled",
            "status": "disabled",
            "reason": "测试日未启用",
            "candidates": [],
        },
        "h4_t3_pool": {
            "mode": "production",
            "status": "ok",
            "production_attested": True,
            "diagnostics": {"upstream_pool": "picks_pure"},
            "candidates": [],
        },
        "selection_input_health": {
            "schema_version": 2,
            "status": "verified",
            "formal": {
                "status": "verified",
                "formal_actions_allowed": True,
                "invalid_count": 0,
                "invalid_codes": [],
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
        },
        "data_quality": {
            "report_date": "2026-09-14",
            "generated_at": "2026-09-14T15:05:00+08:00",
            "as_of": "2026-09-14T15:05:00+08:00",
            "bar_state": "closed",
            "sources_trusted": True,
            "is_trading_day": True,
            "is_official": True,
            "stock_pool_incomplete": False,
            "market_status": "verified",
            "fallback_used": False,
            "stale_stock_count": 0,
            "missing_daily_count": 0,
        },
        "workspace": {
            "views": {"highlights": [], "main": [], "baseline": []},
        },
    }


def _health():
    return {
        "status": "partial",
        "required_date": "2026-09-14",
        "requested_count": 3,
        "verified_count": 2,
        "verified_codes": ["600001", "600002"],
        "missing_count": 1,
        "missing_codes": ["600003"],
        "budget_excluded_count": 0,
        "budget_excluded_codes": [],
        "formal_actions_allowed": False,
        "research_output_trusted": False,
        "research_candidate_output_allowed": True,
    }


def _producer_pool():
    return {
        "status": "partial",
        "mode": "partial",
        "strategy_version": "luojie-research-v2",
        "input_health": _health(),
        "reason": "15分钟研究输入部分核验，保留已核验候选并标注缺口",
        "diagnostics": {"source": "producer"},
        "candidates": [
            {
                "code": "600001",
                "name": "已核验一",
                "current_price": 10.0,
                "change_pct": 1.0,
                "data_status": {
                    "daily": "verified",
                    "latest_date": "2026-09-14",
                    "stale": False,
                    "is_final": True,
                },
                "dates": [],
                "closes": [],
            },
            {
                "code": "600002",
                "name": "已核验二",
                "current_price": 11.0,
                "change_pct": 2.0,
                "data_status": {
                    "daily": "verified",
                    "latest_date": "2026-09-14",
                    "stale": False,
                    "is_final": True,
                },
                "dates": [],
                "closes": [],
            },
        ],
    }


def _contract_pool():
    pool = _serialize_luojie_pool(_producer_pool())
    pool.update({
        "status": "partial",
        "mode": "partial",
        "strategy_version": "luojie-research-v2",
        "input_health": _health(),
    })
    return pool


class TestLuojiePartialPublish(unittest.TestCase):

    def test_producer_serializer_resolver_validator_roundtrip_keeps_research_candidates(self):
        report = _official_report()
        report["luojie_pool"] = json.loads(
            json.dumps(_serialize_luojie_pool(_producer_pool()))
        )

        report["workspace"] = build_workspace(report)
        state = resolve_nested_strategy_pool(report, "luojie_pool")

        self.assertEqual(report["luojie_pool"].get("status"), "partial")
        self.assertEqual(
            report["luojie_pool"].get("strategy_version"), "luojie-research-v2"
        )
        self.assertEqual(report["luojie_pool"].get("input_health"), _health())
        self.assertEqual(state["state"], "partial")
        self.assertTrue(state["contract_valid"])
        self.assertEqual(state["count"], 2)
        self.assertEqual(len(report["workspace"]["views"]["luojie"]), 2)
        self.assertEqual(validate_report_contract(report, require_official=True), [])

    def test_partial_luojie_rejects_missing_or_conflicting_health_counts(self):
        for mutation in (
            lambda health: health.pop("verified_codes"),
            lambda health: health.update({"verified_count": 3}),
            lambda health: health.update({"missing_count": 2}),
            lambda health: health.update({"required_date": "2026-09-13"}),
        ):
            with self.subTest(mutation=mutation):
                report = _official_report()
                pool = _contract_pool()
                mutation(pool["input_health"])
                report["luojie_pool"] = pool
                report["workspace"] = build_workspace(report)

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any("luojie_pool pool contract invalid" in error for error in errors),
                    errors,
                )

    def test_partial_luojie_rejects_permission_or_duplicate_health_conflicts(self):
        mutations = (
            lambda health: health.update({"formal_actions_allowed": True}),
            lambda health: health.update({"research_candidate_output_allowed": False}),
            lambda health: health.update({"verified_count": 1}),
        )
        for mutate_pool_health in mutations:
            with self.subTest(mutate_pool_health=mutate_pool_health):
                report = _official_report()
                report["selection_input_health"]["by_strategy"]["luojie_pool"] = (
                    copy.deepcopy(_health())
                )
                pool = _contract_pool()
                mutate_pool_health(pool["input_health"])
                report["luojie_pool"] = pool
                report["workspace"] = build_workspace(report)

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any("luojie_pool pool contract invalid" in error for error in errors),
                    errors,
                )

    def test_partial_luojie_rejects_mode_status_conflicts(self):
        for mode, status in (
            ("enabled", "partial"),
            ("disabled", "partial"),
            ("partial", "enabled"),
        ):
            with self.subTest(mode=mode, status=status):
                report = _official_report()
                pool = _contract_pool()
                pool.update({"mode": mode, "status": status})
                report["luojie_pool"] = pool

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any("luojie_pool pool contract invalid" in error for error in errors),
                    errors,
                )

    def test_partial_luojie_rejects_non_collection_duplicate_health_codes_and_rows(self):
        cases = ("non_collection", "duplicate_verified", "duplicate_missing", "duplicate_row")
        for case in cases:
            with self.subTest(case=case):
                report = _official_report()
                report["selection_input_health"]["by_strategy"]["luojie_pool"] = (
                    copy.deepcopy(_health())
                )
                pool = _contract_pool()
                if case == "non_collection":
                    report["selection_input_health"]["by_strategy"]["luojie_pool"][
                        "verified_codes"
                    ] = 1
                elif case == "duplicate_verified":
                    pool["input_health"]["verified_codes"] = ["600001", "600001"]
                elif case == "duplicate_missing":
                    pool["input_health"]["missing_codes"] = ["600003", "600003"]
                else:
                    pool["candidates"].append(dict(pool["candidates"][0]))
                report["luojie_pool"] = pool

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any("luojie_pool pool contract invalid" in error for error in errors),
                    errors,
                )

    def test_partial_luojie_rejects_verified_code_whitespace_when_resolver_drops_rows(self):
        report = _official_report()
        pool = _contract_pool()
        pool["input_health"]["verified_codes"] = ["600001 ", "600002 "]
        report["luojie_pool"] = pool

        errors = validate_report_contract(report, require_official=True)

        self.assertTrue(
            any("luojie_pool pool contract invalid" in error for error in errors),
            errors,
        )

    def test_partial_luojie_rejects_missing_code_intersection_and_unverified_candidate(self):
        for mutation in ("missing_intersection", "unverified_candidate"):
            with self.subTest(mutation=mutation):
                report = _official_report()
                pool = _contract_pool()
                if mutation == "missing_intersection":
                    pool["input_health"]["missing_codes"] = ["600002"]
                else:
                    pool["candidates"].append(
                        {"code": "600003", "name": "未核验", "dates": [], "closes": []}
                    )
                report["luojie_pool"] = pool
                report["workspace"] = build_workspace(report)

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any("luojie_pool pool contract invalid" in error for error in errors),
                    errors,
                )

    def test_partial_without_status_does_not_default_to_verified(self):
        report = _official_report()
        pool = _contract_pool()
        pool.pop("status")
        report["luojie_pool"] = pool
        report["workspace"] = build_workspace(report)

        errors = validate_report_contract(report, require_official=True)

        self.assertTrue(
            any("luojie_pool pool contract invalid" in error for error in errors),
            errors,
        )

    def test_partial_formal_or_other_research_pool_remains_blocked(self):
        for field in ("next_day_boom", "h4_t3_pool"):
            with self.subTest(field=field):
                report = _official_report()
                if field == "next_day_boom":
                    report[field] = {
                        "mode": "partial",
                        "status": "partial",
                        "input_health": _health(),
                        "candidates": [],
                    }
                else:
                    report[field] = {
                        "mode": "partial",
                        "status": "partial",
                        "production_attested": False,
                        "candidates": [],
                    }
                report["luojie_pool"] = _serialize_luojie_pool(_producer_pool())
                report["workspace"] = build_workspace(report)

                errors = validate_report_contract(report, require_official=True)

                self.assertTrue(
                    any(f"{field} pool contract invalid" in error for error in errors),
                    errors,
                )

    def test_luojie_disabled_enabled_and_empty_states_keep_existing_contracts(self):
        states = [
            {"mode": "disabled", "status": "not_requested", "candidates": []},
            {"mode": "enabled", "status": "verified", "candidates": []},
            {"mode": "enabled", "status": "verified", "candidates": [{"code": "600001"}]},
        ]
        for pool in states:
            with self.subTest(pool=pool):
                report = _official_report()
                report["luojie_pool"] = copy.deepcopy(pool)
                if report["luojie_pool"].get("candidates"):
                    report["luojie_pool"]["candidates"] = [{
                        "code": "600001",
                        "name": "已核验",
                        "current_price": 10.0,
                        "change_pct": 1.0,
                        "data_status": {
                            "daily": "verified",
                            "latest_date": "2026-09-14",
                            "stale": False,
                            "is_final": True,
                        },
                    }]
                report["workspace"] = build_workspace(report)
                self.assertEqual(
                    validate_report_contract(report, require_official=True), []
                )


if __name__ == "__main__":
    unittest.main()
