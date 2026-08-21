import unittest

import run
from chanlun.candidate_funnel import CandidateFunnel, merge_confirmed_candidates
from chanlun.decision_engine import evaluate_stock
from chanlun.report_view_model import build_workspace


class RunHorizonContractTests(unittest.TestCase):
    def test_fusion_recommend_requires_one_verified_source_horizon(self):
        enforce = getattr(run, "_enforce_fusion_horizon_contract", None)
        self.assertIsNotNone(enforce)
        if enforce is None:
            return
        unique = {
            "code": "600001",
            "strategy_sources": [{
                "strategy_source": "validated-t3",
                "source_status": "candidate",
                "intended_horizon": 3,
            }],
            "decision_engine_v1": {
                "decision": "推荐",
                "decision_code": "recommend",
            },
        }
        missing = {
            "code": "600002",
            "strategy_sources": [{
                "strategy_source": "unvalidated",
                "source_status": "candidate",
                "intended_horizon": None,
            }],
            "decision_engine_v1": {
                "decision": "推荐",
                "decision_code": "recommend",
            },
        }
        conflict = {
            "code": "600003",
            "strategy_sources": [
                {"strategy_source": "t1", "source_status": "candidate", "intended_horizon": 1},
                {"strategy_source": "t5", "source_status": "candidate", "intended_horizon": 5},
            ],
            "decision_engine_v1": {
                "decision": "推荐",
                "decision_code": "recommend",
            },
        }

        enforce([unique, missing, conflict])

        self.assertEqual(unique["intended_horizon"], 3)
        self.assertEqual(unique["horizon_status"], "verified")
        self.assertEqual(unique["decision_engine_v1"]["decision_code"], "recommend")
        self.assertEqual(missing["horizon_status"], "missing")
        self.assertEqual(missing["decision_engine_v1"]["decision_code"], "observe")
        self.assertEqual(conflict["horizon_status"], "conflict")
        self.assertEqual(conflict["decision_engine_v1"]["decision_code"], "observe")

    def test_shadow_contract_does_not_replace_legacy_production_main(self):
        item = {
            "code": "600004",
            "strategy_sources": [{
                "strategy_source": "legacy-unvalidated",
                "source_status": "candidate",
            }],
            "decision_engine_v1": {
                "decision": "推荐",
                "decision_code": "recommend",
            },
        }

        diagnostics = run._enforce_fusion_horizon_contract(
            [item], mode="shadow"
        )

        self.assertEqual(
            item["decision_engine_v1"]["decision_code"], "recommend"
        )
        self.assertEqual(item["horizon_status"], "missing")
        self.assertEqual(item["selection_contract_mode"], "legacy_production")
        self.assertFalse(item["high_return_eligible"])
        self.assertEqual(diagnostics["legacy_production_count"], 1)
        self.assertEqual(diagnostics["high_return_eligible_count"], 0)

    def test_shadow_does_not_treat_declared_horizon_as_oot_proof(self):
        item = {
            "code": "600005",
            "intended_horizon": 3,
            "decision_engine_v1": {
                "decision": "推荐",
                "decision_code": "recommend",
            },
        }

        diagnostics = run._enforce_fusion_horizon_contract(
            [item], mode="shadow"
        )

        self.assertTrue(item["horizon_contract_eligible"])
        self.assertFalse(item["high_return_eligible"])
        self.assertEqual(item["selection_contract_mode"], "legacy_production")
        self.assertEqual(diagnostics["horizon_contract_eligible_count"], 1)
        self.assertEqual(diagnostics["high_return_eligible_count"], 0)

    def test_merged_source_horizon_conflict_cannot_be_hidden_by_top_level(self):
        merged = merge_confirmed_candidates([
            {
                "code": "600006",
                "strategy_source": "source-t1",
                "source_status": "candidate",
                "intended_horizon": 1,
                "decision_engine_v1": {"decision_code": "recommend"},
            },
            {
                "code": "600006",
                "strategy_source": "source-t5",
                "source_status": "candidate",
                "intended_horizon": 5,
                "decision_engine_v1": {"decision_code": "recommend"},
            },
        ])

        run._enforce_fusion_horizon_contract(merged, mode="shadow")

        self.assertEqual(merged[0]["horizon_status"], "conflict")
        self.assertIsNone(merged[0]["intended_horizon"])
        self.assertEqual(merged[0]["source_horizons"], [1, 5])
        self.assertFalse(merged[0]["horizon_contract_eligible"])

    def test_funnel_main_uses_only_published_main_contract(self):
        rows = [
            {
                "code": "600011",
                "horizon_status": "verified",
                "decision_engine_v1": {"decision_code": "recommend"},
            },
            {
                "code": "600012",
                "horizon_status": "missing",
                "selection_contract_mode": "legacy_production",
                "decision_engine_v1": {"decision_code": "recommend"},
            },
            {
                "code": "600013",
                "horizon_status": "verified",
                "decision_engine_v1": {"decision_code": "observe"},
            },
            {
                "code": "600014",
                "horizon_status": "missing",
                "decision_engine_v1": {"decision_code": "recommend"},
            },
        ]

        self.assertEqual(
            ["600011", "600012"],
            [
                row["code"]
                for row in run._published_main_candidates(rows)
            ],
        )

    def test_funnel_decision_uses_terminal_source_priority(self):
        pure = [
            {"code": "600021", "decision_engine_v1": {"decision": "pure"}},
            {"code": "600022", "decision_engine_v1": {"decision": "pure"}},
        ]
        fusion = [{
            "code": "600021",
            "horizon_status": "verified",
            "decision_engine_v1": {
                "decision_code": "recommend",
                "decision": "fusion-main",
            },
        }]
        observation = [
            {"code": "600021", "decision_engine_v1": {"decision": "watch"}},
            {"code": "600022", "decision_engine_v1": {"decision": "watch"}},
            {"code": "600023", "decision_engine_v1": {"decision": "watch"}},
        ]

        decisions = run._build_funnel_decision_map(
            pure, fusion, observation
        )

        self.assertEqual(decisions["600021"]["decision"], "fusion-main")
        self.assertEqual(decisions["600022"]["decision"], "pure")
        self.assertEqual(decisions["600023"]["decision"], "watch")

    def test_fusion_decision_aggregates_per_source_without_order_dependency(self):
        variants = [
            {
                "code": "600031",
                "strategy_source": "chanlun_structure",
                "source_channel": "low_position",
            },
            {
                "code": "600031",
                "strategy_source": "trend_continuation",
                "source_channel": "trend_continuation",
            },
        ]

        def evaluator(item, market_context=None):
            source = item.get("strategy_source")
            return {
                "decision_code": (
                    "recommend"
                    if source == "trend_continuation" else "observe"
                ),
                "decision": source,
            }

        first = {"code": "600031", "strategy_variants": variants}
        reversed_item = {
            "code": "600031",
            "strategy_variants": list(reversed(variants)),
        }

        run._inject_fusion_decision_engine([first], evaluator, {})
        run._inject_fusion_decision_engine([reversed_item], evaluator, {})

        self.assertEqual(first["decision_engine_v1"], reversed_item["decision_engine_v1"])
        self.assertEqual(
            first["decision_engine_v1"]["decision_code"], "recommend"
        )
        self.assertEqual(
            first["decision_engine_v1"]["representative_strategy_source"],
            "trend_continuation",
        )
        self.assertEqual(len(first["source_decisions"]), 2)

    def test_independent_recommend_is_not_vetoed_by_another_source(self):
        item = {
            "code": "600032",
            "strategy_variants": [
                {"code": "600032", "strategy_source": "strong_startup"},
                {"code": "600032", "strategy_source": "trend_continuation"},
            ],
        }

        def evaluator(candidate, market_context=None):
            source = candidate.get("strategy_source")
            return {
                "decision_code": (
                    "reject" if source == "strong_startup" else "recommend"
                ),
                "decision": source,
            }

        run._inject_fusion_decision_engine([item], evaluator, {})

        self.assertEqual(item["decision_engine_v1"]["decision_code"], "recommend")
        self.assertEqual(
            item["decision_engine_v1"]["representative_strategy_source"],
            "trend_continuation",
        )
        self.assertEqual(
            item["decision_engine_v1"]["aggregation_rule"],
            "any_recommend_then_observe_then_reject",
        )

    def test_real_trend_recommend_survives_low_position_high_percentile_reject(self):
        closes = [9.0] * 119 + [10.1]
        common = {
            "code": "600037",
            "source_status": "candidate",
            "closes": closes,
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-20",
            },
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
            "change_pct": 3.0,
            "gap_pct": 1.0,
        }
        structure = {
            **common,
            "strategy_source": "chanlun_structure",
            "source_channel": "low_position",
            "best_buy_point": {
                "type": "三买",
                "source_type": "日线缠论",
                "price": 10.0,
            },
        }
        trend = {
            **common,
            "strategy_source": "trend_continuation",
            "source_channel": "trend_continuation",
            "trend_type": "up",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "reference_type": "platform_high_20d",
            "reference_price": 10.0,
        }
        item = merge_confirmed_candidates([structure, trend])[0]
        for variant in item["strategy_variants"]:
            run._attach_position_evidence(variant, "2026-08-20")
        independent = {
            variant["strategy_source"]: evaluate_stock(variant)
            for variant in item["strategy_variants"]
        }
        self.assertEqual(
            "reject", independent["chanlun_structure"]["decision_code"]
        )
        self.assertEqual(
            "recommend", independent["trend_continuation"]["decision_code"]
        )

        run._inject_fusion_decision_engine([item], evaluate_stock, {})

        self.assertEqual("recommend", item["decision_engine_v1"]["decision_code"])
        self.assertEqual(
            "trend_continuation",
            item["representative_strategy_source"],
        )

    def test_real_engine_single_variant_matches_unmerged_source(self):
        source = {
            "code": "600033",
            "strategy_source": "trend_continuation",
            "source_channel": "trend_continuation",
            "source_status": "candidate",
            "trend_type": "up",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "reference_type": "platform_high_20d",
            "reference_price": 10.0,
            "closes": [10.2] * 120,
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-20",
            },
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
            "change_pct": 3.0,
            "gap_pct": 1.0,
        }
        expected_source = dict(source)
        run._attach_position_evidence(expected_source, "2026-08-20")
        expected = evaluate_stock(expected_source)
        merged = merge_confirmed_candidates([source])
        variant = merged[0]["strategy_variants"][0]
        run._attach_position_evidence(variant, "2026-08-20")

        run._inject_fusion_decision_engine(merged, evaluate_stock, {})

        self.assertEqual(
            expected,
            merged[0]["source_decisions"][0]["decision_engine_v1"],
        )
        self.assertEqual("verified", variant["position_data_status"])

    def test_each_fusion_variant_gets_its_own_verified_position_reference(self):
        common = {
            "code": "600034",
            "source_status": "candidate",
            "closes": [10.0] * 120,
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-20",
            },
        }
        low = {
            **common,
            "strategy_source": "chanlun_structure",
            "source_channel": "low_position",
            "best_buy_point": {
                "type": "三买",
                "source_type": "日线缠论",
                "price": 9.8,
            },
        }
        trend = {
            **common,
            "strategy_source": "trend_continuation",
            "source_channel": "trend_continuation",
            "reference_type": "platform_high_20d",
            "reference_price": 9.9,
        }
        merged = merge_confirmed_candidates([trend, low])

        for variant in merged[0]["strategy_variants"]:
            run._attach_position_evidence(variant, "2026-08-20")
        run._inject_fusion_decision_engine(merged, evaluate_stock, {})

        by_source = {
            row["strategy_source"]: row
            for row in merged[0]["strategy_variants"]
        }
        self.assertEqual(
            "low_position_channel:日线缠论",
            by_source["chanlun_structure"]["position_reference_type"],
        )
        self.assertEqual(
            "channel_reference:platform_high_20d",
            by_source["trend_continuation"]["position_reference_type"],
        )
        self.assertTrue(all(
            row["position_data_status"] == "verified"
            for row in by_source.values()
        ))

    def test_page_reason_and_score_follow_explicit_fusion_representative(self):
        item = {
            "code": "600035",
            "name": "代表来源测试",
            "selection_contract_mode": "legacy_production",
            "strategy_sources": [
                {
                    "strategy_source": "chanlun_structure",
                    "source_status": "candidate",
                    "reason": "结构来源理由",
                },
                {
                    "strategy_source": "trend_continuation",
                    "source_status": "candidate",
                    "reason": "趋势来源理由",
                },
            ],
            "strategy_variants": [
                {
                    "code": "600035",
                    "strategy_source": "chanlun_structure",
                    "source_channel": "low_position",
                    "score": 41,
                    "best_buy_point": {"reason": "结构来源理由"},
                },
                {
                    "code": "600035",
                    "strategy_source": "trend_continuation",
                    "source_channel": "trend_continuation",
                    "score": 88,
                    "best_buy_point": {"reason": "趋势来源理由"},
                },
            ],
        }

        def evaluator(candidate, market_context=None):
            source = candidate.get("strategy_source")
            return {
                "decision_code": (
                    "recommend"
                    if source == "trend_continuation" else "observe"
                ),
                "decision": source,
            }

        run._inject_fusion_decision_engine([item], evaluator, {})
        row = build_workspace({"picks_fusion": [item]})["views"]["main"][0]

        self.assertEqual("trend_continuation", item["strategy_source"])
        self.assertEqual(88, item["score"])
        self.assertEqual("trend_continuation", row["representative_strategy_source"])
        self.assertEqual("趋势延续", row["representative_strategy_label"])
        self.assertEqual("趋势来源理由", row["primary_reason"])
        self.assertEqual(88, row["representative_source_score"])
        self.assertIn("融合排名代表来源：趋势延续", row["rank_trace"]["selected_reason"])

    def test_recency_filters_each_source_before_same_code_remerge(self):
        common = {
            "code": "600036",
            "name": "时效测试",
            "closes": [10.0] * 20,
        }
        expired_structure = {
            **common,
            "strategy_source": "chanlun_structure",
            "source_channel": "low_position",
            "best_buy_point": {"type": "三买", "index": 0},
        }
        fresh_trend = {
            **common,
            "strategy_source": "trend_continuation",
            "source_channel": "trend_continuation",
            "best_buy_point": {
                "type": "趋势延续候选",
                "index": 19,
            },
        }
        merged = merge_confirmed_candidates([
            expired_structure,
            fresh_trend,
        ])

        kept, diagnostics = run._filter_recent_strategy_sources(
            merged, 5
        )

        self.assertEqual(["600036"], [row["code"] for row in kept])
        self.assertEqual(
            ["trend_continuation"],
            [
                row["strategy_source"]
                for row in kept[0]["strategy_sources"]
            ],
        )
        self.assertEqual(
            ["trend_continuation"],
            [
                row["strategy_source"]
                for row in kept[0]["strategy_variants"]
            ],
        )
        self.assertEqual(1, diagnostics["input"])
        self.assertEqual(1, diagnostics["kept"])
        self.assertEqual(0, diagnostics["dropped_expired"])
        self.assertEqual(1, diagnostics["source_dropped_expired"])
        self.assertEqual(
            "chanlun_structure",
            diagnostics["dropped_details"][0]["strategy_source"],
        )

    def test_fusion_funnel_records_dropped_pure_code_and_source_reason(self):
        funnel = CandidateFunnel("run-fusion-drop", "2026-08-20")
        pure = [{"code": "600041"}, {"code": "600042"}]
        fusion = [{"code": "600042"}]
        funnel.register_many(pure)

        run._record_fusion_funnel_outcomes(
            funnel,
            pure,
            fusion,
            {
                "drop_details": [{
                    "code": "600041",
                    "reason": "MA多头不成立",
                    "strategy_source": "chanlun_structure",
                }],
            },
        )

        dropped = funnel.event_for("600041")
        self.assertEqual("fusion", dropped["first_failure_gate"])
        self.assertEqual("fusion_not_admitted", dropped["first_failure_reason"])
        self.assertEqual("MA多头不成立", dropped["source_failures"][0]["reason"])
        self.assertIn("fusion", funnel.event_for("600042")["passed_stages"])

    def test_observation_overlap_does_not_pollute_main_or_candidate_failure(self):
        for final_state in ("candidate", "main"):
            with self.subTest(final_state=final_state):
                funnel = CandidateFunnel(
                    "run-observe-{}".format(final_state), "2026-08-20"
                )
                funnel.register({"code": "600043"})
                run._record_observation_funnel_outcome(
                    funnel,
                    {
                        "code": "600043",
                        "strategy_source": "strong_startup",
                        "failure_gate": "minute30",
                        "reason_code": "waiting_confirmation",
                    },
                    {"600043"},
                )
                funnel.finalize(
                    main_codes=(
                        ["600043"] if final_state == "main" else []
                    ),
                    candidate_codes=(
                        ["600043"] if final_state == "candidate" else []
                    ),
                    observation_codes=["600043"],
                )

                event = funnel.event_for("600043")
                self.assertEqual(final_state, event["final_state"])
                self.assertEqual("", event["first_failure_gate"])
                self.assertEqual({}, funnel.summary()["first_failure_counts"])
                self.assertEqual(
                    "waiting_confirmation",
                    event["source_failures"][0]["reason"],
                )


if __name__ == "__main__":
    unittest.main()
