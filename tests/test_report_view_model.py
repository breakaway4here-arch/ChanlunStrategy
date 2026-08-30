import unittest

from chanlun.report_view_model import EXCLUDED_FIELDS, build_workspace, _build_pool_quality_features


LARGE_FIELDS = EXCLUDED_FIELDS


def _fusion_pick(
    code="600001",
    name="主推票",
    score=82,
    distance=1.8,
    change_pct=2.6,
    reason="底背驰候选强市通过",
    sector="测试板块",
    sector_tags=None,
    decision_engine_v1=None,
):
    pick = {
        "code": code,
        "name": name,
        "sector": sector,
        "score": score,
        "best_buy_point": {
            "type": "底背驰候选",
            "reason": reason,
            "price": 10.0,
            "current_price": 10.18,
            "distance_from_reference_pct": distance,
            "change_pct": change_pct,
            "confirmed_by": "30min确认",
        },
        # Large fields intentionally present to verify they are not copied.
        "dates": ["2026-06-26"],
        "opens": [9.9],
        "highs": [10.2],
        "lows": [9.8],
        "closes": [10.18],
        "volumes": [1000],
        "macd_hist": [0.1],
        "chart_annotations": {"markLines": []},
        "buy_points": [{"type": "二买"}],
        "reference_buy_points": [{"type": "参考"}],
        "blocked_buy_points": [{"type": "拦截"}],
        "sector_tags": list(sector_tags or []),
        "money20": 150_000_000,
        "market_cap": 120,
    }
    pick["decision_engine_v1"] = decision_engine_v1 or {
        "decision_code": "recommend",
        "decision": "推荐",
    }
    return pick


def _baseline_pick(code="600099", name="基准票"):
    pick = _fusion_pick(code=code, name=name, score=65, distance=0.7)
    pick["version"] = "picks_pure"
    return pick


def _acceleration_pick(code="600002", name="加速票", boom_score=78, change_pct=5.2):
    return {
        "code": code,
        "name": name,
        "sector": "测试板块",
        "boom_score": boom_score,
        "boom_reason": "量比甜区；低位启动",
        "change_pct": change_pct,
        "reference_price": 20.0,
        "current_price": 20.6,
        "money20": 180_000_000,
        "market_cap": 180,
    }


def _luojie_pick(code="600003", name="罗姐票", score=74):
    return {
        "code": code,
        "name": name,
        "sector": "通信设备",
        "score": score,
        "close": 31.5,
        "life_line": 31.1,
        "reason": "15min生命线不破；DIF/DEA双线0轴上",
        "tier": "主升候选",
        "money20": 160_000_000,
        "market_cap": 160,
    }


def _confirming_pick(code="600004", name="等确认票", change_pct=4.2, distance=3.1):
    return {
        "code": code,
        "name": name,
        "sector": "测试板块",
        "startup_reason": "低位放量启动",
        "watch_reason": "涨停当日不追，等待次日回踩确认",
        "change_pct": change_pct,
        "close": 12.0,
        "current_price": 12.37,
        "distance_from_reference_pct": distance,
        "money20": 120_000_000,
        "market_cap": 100,
    }


def _report_data(overrides=None):
    base = {
        "picks_fusion": [],
        "picks_pure": [],
        "next_day_boom": {"mode": "enabled", "candidates": []},
        "luojie_pool": {"mode": "enabled", "candidates": []},
        "startup_watchlist": [],
        "selection_input_health": {
            "schema_version": 2,
            "status": "verified",
            "formal": {
                "status": "verified",
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
                "luojie_pool": {"status": "verified"},
            },
        },
    }
    if overrides:
        base.update(overrides)
    return base


class TestReportViewModel(unittest.TestCase):
    def test_formal_decision_contract_preserves_only_declared_verified_fields(self):
        pick = _fusion_pick()
        pick.update({
            "intended_horizon": "T+3",
            "position_band": "10%-30%",
            "reference_price": 10.0,
            "invalidation_price": 9.2,
            "pressure_price": 12.0,
            "horizon_states": {
                "daily": "up",
                "weekly": "confirming",
                "60m": "waiting",
            },
            "policy_version": "formal-policy-v1",
            "evidence_refs": ["decision:2026-06-26:600001"],
        })

        row = build_workspace(_report_data({"picks_fusion": [pick]}))["views"]["main"][0]

        self.assertEqual(row["formal_decision_contract"], {
            "action": "可上车",
            "action_reason": "主推命中，确认与结构条件已满足，偏执行优先。",
            "intended_horizon": "T+3",
            "position_band": "10%-30%",
            "reference_price": 10.0,
            "invalidation_price": 9.2,
            "pressure_price": 12.0,
            "horizon_states": {
                "daily": "up",
                "weekly": "confirming",
                "60m": "waiting",
            },
            "policy_version": "formal-policy-v1",
            "evidence_refs": ["decision:2026-06-26:600001"],
        })

    def test_formal_decision_contract_omits_conflicting_or_undeclared_fields(self):
        pick = _fusion_pick(decision_engine_v1={
            "decision_code": "recommend",
            "decision": "推荐",
            "intended_horizon": "T+5",
        })
        pick.update({
            "intended_horizon": "T+3",
            "highs": [99.0],
            "position_band": "invalid",
        })

        row = build_workspace(_report_data({"picks_fusion": [pick]}))["views"]["main"][0]
        contract = row["formal_decision_contract"]

        self.assertNotIn("intended_horizon", contract)
        self.assertNotIn("position_band", contract)
        self.assertNotIn("pressure_price", contract)
        self.assertEqual(
            row["formal_decision_contract_diagnostics"]["intended_horizon"],
            "conflict",
        )

    def test_existing_observe_contract_cannot_be_upgraded_by_outer_wrapper(self):
        pick = _fusion_pick()
        pick["formal_decision_contract"] = {
            "action": "observe",
            "action_reason": "周期尚未完成确认",
        }

        row = build_workspace(_report_data({"picks_fusion": [pick]}))["views"]["main"][0]

        self.assertEqual(row["formal_decision_contract"]["action"], "观察")
        self.assertEqual(
            row["formal_decision_contract"]["action_reason"],
            "周期尚未完成确认",
        )

    def test_research_view_never_exposes_a_formal_decision_contract(self):
        pick = _fusion_pick()
        pick["formal_decision_contract"] = {"action": "可上车"}

        workspace = build_workspace(_report_data({"picks_fusion": [pick]}))

        self.assertIsNotNone(
            workspace["views"]["main"][0]["formal_decision_contract"]
        )
        self.assertIsNone(
            workspace["views"]["highlights"][0].get(
                "formal_decision_contract"
            )
        )

    def test_workspace_exposes_primary_and_research_navigation_groups(self):
        workspace = build_workspace({
            "date": "2026-08-27",
            "picks_fusion": [],
            "picks_pure": [],
            "startup_watchlist": {"candidates": []},
            "selection_input_health": {
                "schema_version": 2,
                "by_strategy": {
                    "daily_fusion": {"status": "verified", "formal_actions_allowed": True},
                },
            },
        })

        groups = workspace["navigation_groups"]
        self.assertEqual(
            [item["key"] for item in groups["primary"]],
            ["main", "confirming", "observation_top5"],
        )
        self.assertEqual(
            [item["label"] for item in groups["primary"]],
            ["主推", "待确认", "观察"],
        )
        research_keys = [item["key"] for item in groups["research"]]
        for key in ("baseline", "h4_t3", "acceleration", "luojie", "growth_quality"):
            self.assertIn(key, research_keys)
        self.assertNotIn("highlights", [item["key"] for item in groups["primary"]])

    def test_workspace_keeps_internal_main_empty_reason_for_research_audit(self):
        workspace = build_workspace({
            "date": "2026-08-27",
            "picks_fusion": [{"code": "600001", "name": "测试股"}],
            "selection_input_health": {
                "schema_version": 2,
                "by_strategy": {
                    "daily_fusion": {
                        "status": "unavailable",
                        "formal_actions_allowed": False,
                        "reason_code": "formal_input_unavailable",
                        "reason": "选股输入不可用，正式动作已封闭",
                    },
                },
            },
        })

        self.assertEqual(workspace["views"]["main"], [])
        availability = workspace["view_meta"]["main"]["availability"]
        self.assertEqual(availability["state"], "unavailable")
        self.assertTrue(availability["reason"])


    def test_workspace_shape_view_order_meta_counts_and_diagnostics(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick()],
                "picks_pure": [_baseline_pick()],
                "next_day_boom": {"mode": "enabled", "candidates": [_acceleration_pick()]},
                "luojie_pool": {"mode": "enabled", "candidates": [_luojie_pick()]},
                "startup_watchlist": [_confirming_pick()],
                "observation_watchlist": [_confirming_pick()],
            }
        )

        workspace = build_workspace(report_data)

        self.assertEqual(workspace["default_view"], "main")
        self.assertEqual(
            workspace["view_order"],
            ["main", "highlights", "observation_top5", "acceleration", "luojie", "confirming", "growth_quality", "baseline"],
        )
        self.assertEqual(set(workspace["views"]), set(workspace["view_order"]))
        self.assertEqual(workspace["counts"]["main"], 1)
        self.assertEqual(workspace["counts"]["baseline"], 1)
        self.assertEqual(workspace["counts"]["observation_top5"], 1)
        self.assertEqual(workspace["counts"]["highlights"], 4)
        self.assertEqual(workspace["counts"]["growth_quality"], 0)
        self.assertEqual(workspace["view_meta"]["highlights"]["label"], "看点 Top10")
        self.assertEqual(workspace["view_meta"]["growth_quality"]["label"], "高弹性观察 Top10")
        self.assertEqual(workspace["view_meta"]["baseline"]["label"], "基础候选")
        self.assertIn(
            "共同上游全集",
            workspace["view_meta"]["baseline"]["description"],
        )
        self.assertIn("source_counts", workspace["diagnostics"])
        self.assertEqual(workspace["diagnostics"]["highlights"]["baseline_included"], False)
        self.assertIn("growth_quality_overlap", workspace["diagnostics"])
        self.assertIn("overlap_codes", workspace["diagnostics"]["growth_quality_overlap"])
        self.assertIn("highlights_codes", workspace["diagnostics"]["growth_quality_overlap"])
        self.assertIn("growth_quality_codes", workspace["diagnostics"]["growth_quality_overlap"])

    def test_view_meta_explains_role_source_action_and_real_empty_states(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick()],
                "picks_pure": [_baseline_pick()],
                "h4_t3_pool": {
                    "mode": "production",
                    "status": "ok",
                    "production_attested": True,
                    "reason": "今日没有候选通过H4 T+3全部门槛。",
                    "candidates": [],
                },
                "next_day_boom": {
                    "mode": "disabled",
                    "reason": "上证涨幅未超过1%，次日大涨模式关闭",
                    "candidates": [],
                },
                "luojie_pool": {
                    "mode": "enabled",
                    "reason": "今日没有候选通过罗姐池门槛。",
                    "candidates": [],
                },
            }
        )

        workspace = build_workspace(report_data)

        for view_name in workspace["view_order"]:
            meta = workspace["view_meta"][view_name]
            self.assertIn("role", meta)
            self.assertIn("source_pool", meta)
            self.assertIn("action_semantics", meta)
            self.assertEqual(set(meta["availability"]), {"state", "reason"})

        self.assertEqual(workspace["view_meta"]["main"]["role"], "formal")
        self.assertEqual(workspace["view_meta"]["main"]["source_pool"], "picks_fusion")
        self.assertEqual(
            workspace["view_meta"]["main"]["action_semantics"],
            "formal",
        )
        self.assertEqual(workspace["view_meta"]["h4_t3"]["role"], "formal")
        self.assertEqual(workspace["view_meta"]["baseline"]["role"], "baseline")
        self.assertEqual(
            workspace["view_meta"]["h4_t3"]["availability"],
            {
                "state": "verified_empty",
                "reason": "今日没有候选通过H4 T+3全部门槛。",
            },
        )
        self.assertEqual(
            workspace["view_meta"]["acceleration"]["availability"],
            {
                "state": "disabled",
                "reason": "上证涨幅未超过1%，次日大涨模式关闭",
            },
        )

    def test_invalid_h4_contract_stays_visible_but_unavailable(self):
        workspace = build_workspace(
            _report_data(
                {
                    "h4_t3_pool": {
                        "mode": "production",
                        "status": "error",
                        "production_attested": True,
                        "reason": "生产证明校验失败",
                        "candidates": [_fusion_pick(code="600088")],
                    }
                }
            )
        )

        self.assertIn("h4_t3", workspace["view_order"])
        self.assertEqual([], workspace["views"]["h4_t3"])
        self.assertEqual(
            "unavailable",
            workspace["view_meta"]["h4_t3"]["availability"]["state"],
        )
        self.assertEqual(
            "生产证明校验失败",
            workspace["view_meta"]["h4_t3"]["availability"]["reason"],
        )

    def test_disabled_luojie_contract_cannot_leak_candidates(self):
        workspace = build_workspace(
            _report_data({
                "luojie_pool": {
                    "mode": "disabled",
                    "reason": "今日未启用",
                    "candidates": [_luojie_pick(code="600089")],
                }
            })
        )
        self.assertEqual([], workspace["views"]["luojie"])
        self.assertEqual(
            "disabled",
            workspace["view_meta"]["luojie"]["availability"]["state"],
        )

    def test_invalid_pool_shapes_are_unavailable_not_verified_empty(self):
        workspace = build_workspace({
            "picks_fusion": {"bad": "shape"},
            "picks_pure": None,
            "observation_watchlist": {"bad": "shape"},
            "startup_watchlist": None,
            "next_day_boom": {"mode": "enabled", "candidates": None},
            "luojie_pool": {"mode": "enabled", "candidates": None},
            "h4_t3_pool": {
                "mode": "production", "status": "ok",
                "production_attested": True,
            },
        })

        for view in (
            "main", "baseline", "observation_top5", "acceleration",
            "luojie", "confirming", "h4_t3",
        ):
            self.assertEqual(
                workspace["view_meta"][view]["availability"]["state"],
                "unavailable",
                view,
            )
            self.assertNotIn(
                "运行正常",
                workspace["view_meta"][view]["availability"]["reason"],
            )

    def test_enabled_pool_with_error_status_is_unavailable(self):
        workspace = build_workspace(
            _report_data({
                "luojie_pool": {
                    "mode": "enabled",
                    "status": "error",
                    "reason": "15分钟输入过期",
                    "candidates": [],
                }
            })
        )

        self.assertEqual([], workspace["views"]["luojie"])
        self.assertEqual(
            "unavailable",
            workspace["view_meta"]["luojie"]["availability"]["state"],
        )
        self.assertEqual(
            "15分钟输入过期",
            workspace["view_meta"]["luojie"]["availability"]["reason"],
        )

    def test_missing_pool_contract_is_unavailable_not_verified_empty(self):
        workspace = build_workspace({"startup_watchlist": []})

        self.assertEqual(
            workspace["view_meta"]["main"]["availability"]["state"],
            "unavailable",
        )
        self.assertEqual(
            workspace["view_meta"]["baseline"]["availability"]["state"],
            "unavailable",
        )

    def test_formal_input_health_suppresses_only_the_affected_strategy(self):
        report_data = _report_data({
            "picks_fusion": [_fusion_pick()],
            "h4_t3_pool": {
                "mode": "production",
                "status": "ok",
                "production_attested": True,
                "candidates": [_fusion_pick(code="600002")],
            },
            "selection_input_health": {
                "schema_version": 2,
                "status": "partial",
                "formal": {
                    "status": "partial",
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": False,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "unavailable",
                        "formal_actions_allowed": False,
                        "blocking_reason": "strategy_input_stale_or_unverified",
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                        "blocking_reason": "",
                    },
                },
            },
        })

        workspace = build_workspace(report_data)

        self.assertEqual([], workspace["views"]["main"])
        self.assertEqual(["600002"], [
            row["code"] for row in workspace["views"]["h4_t3"]
        ])
        self.assertEqual(
            "unavailable",
            workspace["view_meta"]["main"]["availability"]["state"],
        )
        self.assertEqual(
            "available",
            workspace["view_meta"]["h4_t3"]["availability"]["state"],
        )
        self.assertTrue(workspace["views"]["highlights"])
        self.assertEqual(
            "仅观察", workspace["views"]["highlights"][0]["page_action"]
        )

    def test_formal_health_flag_cannot_override_unavailable_status(self):
        report_data = _report_data({
            "picks_fusion": [_fusion_pick()],
            "selection_input_health": {
                "schema_version": 2,
                "status": "partial",
                "formal": {
                    "status": "partial",
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": False,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "unavailable",
                        "formal_actions_allowed": True,
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                },
            },
        })

        workspace = build_workspace(report_data)

        self.assertEqual([], workspace["views"]["main"])
        self.assertEqual(
            "unavailable",
            workspace["view_meta"]["main"]["availability"]["state"],
        )

    def test_incident_affected_research_rows_are_marked_review_only(self):
        report_data = _report_data({
            "picks_fusion": [_fusion_pick(code="300697")],
            "luojie_pool": {
                "mode": "enabled",
                "status": "ok",
                "candidates": [_luojie_pick(code="600003")],
            },
            "selection_input_health": {
                "schema_version": 2,
                "status": "partial",
                "formal": {
                    "status": "partial",
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": False,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "unavailable",
                        "formal_actions_allowed": False,
                        "invalid_codes": ["300697"],
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "luojie_pool": {
                        "status": "unavailable",
                        "invalid_codes": [],
                    },
                },
                "incident_ids": ["fusion-300697", "luojie-15m"],
            },
        })

        workspace = build_workspace(report_data)

        self.assertEqual("partial", workspace["view_meta"]["highlights"]["availability"]["state"])
        self.assertEqual("partial", workspace["view_meta"]["luojie"]["availability"]["state"])
        affected = {
            row["code"]: row
            for row in workspace["views"]["highlights"]
        }
        self.assertTrue(affected["300697"]["incident_review_only"])
        self.assertTrue(affected["600003"]["incident_review_only"])
        self.assertIn("仅供事故复盘", affected["300697"]["page_action_reason"])
        self.assertTrue(any(
            badge["label"] == "策略输入过期·仅复盘"
            for badge in affected["600003"]["data_badges"]
        ))

    def test_observation_top5_does_not_silently_fallback_to_startup_pool(self):
        workspace = build_workspace({
            "observation_watchlist": [],
            "startup_watchlist": [_confirming_pick()],
        })

        self.assertEqual([], workspace["views"]["observation_top5"])
        self.assertEqual(
            "verified_empty",
            workspace["view_meta"]["observation_top5"]["availability"]["state"],
        )

    def test_workspace_preserves_final_close_evidence_and_page_action_contract(self):
        pick = _fusion_pick()
        pick["data_status"] = {
            "daily": "verified",
            "latest_date": "2026-08-26",
            "source": "tencent",
            "bars": 100,
            "stale": False,
            "is_final": True,
        }

        workspace = build_workspace(_report_data({"picks_fusion": [pick]}))
        formal = workspace["views"]["main"][0]
        research = workspace["views"]["highlights"][0]

        self.assertIs(formal["data_status"]["is_final"], True)
        self.assertEqual("可上车", formal["page_action"])
        self.assertEqual("仅观察", research["page_action"])
        self.assertNotEqual(formal["strategy_action"], research["page_action"])

    def test_observation_top5_enforces_sector_and_failure_reason_caps(self):
        rows = []
        for index in range(8):
            item = _confirming_pick(code="60{:04d}".format(index))
            item.update({
                "sector": "行业A" if index < 4 else "行业{}".format(index),
                "reason_code": (
                    "waiting_30m_confirm"
                    if index in (0, 1, 2)
                    else "ma_near_miss_{}".format(index)
                ),
                "failure_gate": "30min_confirm",
                "actual_value": index,
                "upgrade_conditions": ["30min确认"],
                "cancel_conditions": ["跌破参考位"],
            })
            rows.append(item)

        workspace = build_workspace({"observation_watchlist": rows})
        selected = workspace["views"]["observation_top5"]

        self.assertEqual(len(selected), 5)
        self.assertLessEqual(
            sum(row["sector"] == "行业A" for row in selected), 2
        )
        self.assertLessEqual(
            sum(
                row["reason_code"] == "waiting_30m_confirm"
                for row in selected
            ),
            2,
        )
        self.assertEqual(workspace["counts"]["main"], 0)
        self.assertTrue(
            all(row["view"] == "observation" for row in selected)
        )

    def test_observation_top5_preserves_limit_up_exception_markers(self):
        item = _confirming_pick(code="301630")
        item.update({
            "view": "observation",
            "tier": "watch",
            "price_limit_state": "limit_up",
            "reason_code": "limit_up",
            "failure_gate": "chase_risk",
        })

        workspace = build_workspace({"observation_watchlist": [item]})
        row = workspace["views"]["observation_top5"][0]

        self.assertEqual(row["view"], "observation")
        self.assertEqual(row["tier"], "watch")
        self.assertEqual(row["price_limit_state"], "limit_up")

    def test_growth_quality_view_exists_but_default_is_main(self):
        report_data = _report_data(
            {
                "picks_fusion": [
                    _fusion_pick(
                        code="600030", score=40,
                        decision_engine_v1={"decision_code": "observe", "decision": "观察"},
                    ),
                    _fusion_pick(code="600031", score=85),
                ],
            }
        )
        report_data["picks_fusion"][0]["ret20"] = 12.0

        workspace = build_workspace(report_data)

        self.assertEqual(workspace["default_view"], "main")
        self.assertTrue(len(workspace["views"]["growth_quality"]) > 0)
        self.assertEqual(
            len([item["code"] for item in workspace["views"]["growth_quality"]]),
            len(set(item["code"] for item in workspace["views"]["growth_quality"])),
        )
        self.assertNotEqual(workspace["views"]["growth_quality"], [])

    def test_baseline_never_enters_highlights(self):
        report_data = _report_data(
            {
                "picks_pure": [_baseline_pick()],
                "next_day_boom": {"mode": "enabled", "candidates": []},
            }
        )

        workspace = build_workspace(report_data)

        self.assertEqual([item["code"] for item in workspace["views"]["baseline"]], ["600099"])
        self.assertEqual(workspace["views"]["highlights"], [])

    def test_growth_quality_order_does_not_change_highlights_ranking(self):
        near_reference_weak = _fusion_pick(
            code="600030",
            name="近参考弱信号",
            score=18,
            distance=0.2,
            change_pct=3.0,
        )
        far_reference_strong = _fusion_pick(
            code="600031",
            name="远参考强信号",
            score=96,
            distance=11.5,
            change_pct=-1.0,
        )
        near_reference_weak.update({
            "position_distance_pct": 0.2,
            "position_reference_price": 10.0,
            "position_reference_type": "range_low_60d",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
        })
        far_reference_strong.update({
            "position_distance_pct": 11.5,
            "position_reference_price": 10.0,
            "position_reference_type": "range_low_60d",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
        })
        report_data = _report_data(
            {
                "picks_fusion": [near_reference_weak, far_reference_strong],
            }
        )
        workspace = build_workspace(report_data)
        self.assertEqual([item["code"] for item in workspace["views"]["highlights"]], ["600030", "600031"])

    def test_growth_quality_tier_sorted_growth_liquidity_sector_first(self):
        elite = _fusion_pick(
            code="300001",
            name="成长优先",
            score=90,
            distance=1.1,
            change_pct=1.2,
            sector="成长板块",
        )
        elite["money20"] = 250_000_000
        elite["market_cap"] = 120
        elite["ret20"] = 20
        elite["sector_rank"] = 1
        elite["sector_flow"] = 3_500_000_000
        elite["decision_engine_v1"] = {"decision_code": "observe", "decision": "观察"}

        normal = _fusion_pick(
            code="600002",
            name="普通候选",
            score=98,
            distance=1.1,
            change_pct=1.2,
            sector="普通板块",
        )
        normal["money20"] = 100_000
        normal["sector_rank"] = 80
        normal["sector_flow"] = 500_000
        normal["ret20"] = 10.0
        normal["decision_engine_v1"] = {"decision_code": "observe", "decision": "观察"}

        report_data = _report_data({"picks_fusion": [normal, elite]})
        workspace = build_workspace(report_data)

        self.assertEqual(
            [item["code"] for item in workspace["views"]["growth_quality"]],
            ["300001", "600002"],
        )

    def test_baseline_not_in_growth_quality(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick(code="600030", score=80)],
                "picks_pure": [_baseline_pick(code="600099", name="基准票")],
            }
        )

        workspace = build_workspace(report_data)

        self.assertEqual([item["code"] for item in workspace["views"]["baseline"]], ["600099"])
        self.assertNotIn("600099", [item["code"] for item in workspace["views"]["growth_quality"]])

    def test_money20_takes_priority_over_volume_proxy_for_liquidity_score(self):
        pick = _fusion_pick(code="600080", name="成交额优先票", score=50)
        pick["money20"] = 150_000_000
        pick["volume_ratio"] = 0.4
        pick["volumes"] = [1_000_000, 1_000_000]

        pool_quality = _build_pool_quality_features(pick)
        self.assertGreaterEqual(pool_quality["liquidity_score"], 70.0)
        self.assertEqual(pool_quality["money20"], 150_000_000.0)

        pick["money20"] = 4_000_000
        self.assertEqual(_build_pool_quality_features(pick)["liquidity_score"], 0.0)
        pick.pop("money20")
        pick["volume_ratio20"] = 0.4
        self.assertLess(_build_pool_quality_features(pick)["liquidity_score"], 30.0)

    def test_highlights_dedupe_and_resonance_label(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick(code="600010", name="共振票")],
                "next_day_boom": {
                    "mode": "enabled",
                    "candidates": [_acceleration_pick(code="600010", name="共振票")],
                },
            }
        )

        workspace = build_workspace(report_data)
        highlights = workspace["views"]["highlights"]

        self.assertEqual(len(highlights), 1)
        item = highlights[0]
        self.assertEqual(item["sources"], ["main", "acceleration"])
        self.assertEqual(item["source_labels"], ["融合候选", "加速"])
        self.assertEqual(item["resonance_label"], "共振·进攻")
        self.assertEqual(item["ref"]["pool"], "picks_fusion")
        self.assertIn("source:main", item["rank_trace"])
        self.assertIn("source:acceleration", item["rank_trace"])

    def test_main_opportunity_score_balances_signal_with_entry_quality(self):
        near_reference_weak = _fusion_pick(
            code="600030",
            name="近参考弱信号",
            score=18,
            distance=0.2,
            change_pct=3.0,
        )
        far_reference_strong = _fusion_pick(
            code="600031",
            name="远参考强信号",
            score=96,
            distance=11.5,
            change_pct=-1.0,
        )
        near_reference_weak.update({
            "position_distance_pct": 0.2,
            "position_reference_price": 10.0,
            "position_reference_type": "range_low_60d",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
        })
        far_reference_strong.update({
            "position_distance_pct": 11.5,
            "position_reference_price": 10.0,
            "position_reference_type": "range_low_60d",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
        })
        report_data = _report_data(
            {
                "picks_fusion": [near_reference_weak, far_reference_strong],
            }
        )
        workspace = build_workspace(report_data)

        self.assertEqual([item["code"] for item in workspace["views"]["main"]], ["600030", "600031"])
        self.assertEqual([item["code"] for item in workspace["views"]["highlights"]], ["600030", "600031"])

    def test_rank_trace_explains_opportunity_components_and_penalties(self):
        pick = _fusion_pick(
            code="600040",
            name="机会分解释",
            score=88,
            distance=8.5,
            change_pct=9.2,
        )
        report_data = _report_data(
            {
                "picks_fusion": [pick],
                "data_quality": {"market_status": "unverified", "fallback_used": True},
            }
        )
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        trace = item["rank_trace"]

        self.assertIn("signal_score", trace)
        self.assertIn("entry_score", trace)
        self.assertIn("momentum_score", trace)
        self.assertIn("market_score", trace)
        self.assertIn("risk_penalty", trace)
        self.assertIn("data_penalty", trace)
        self.assertIn("opportunity_score", trace)
        self.assertEqual(trace["opportunity_score"], item["opportunity_score"])
        self.assertLessEqual(trace["signal_score"], 25)
        self.assertLessEqual(trace["market_score"], 15)
        self.assertLessEqual(trace["data_penalty"], 20)
        self.assertGreaterEqual(trace["risk_penalty"], 0)
        self.assertGreaterEqual(trace["data_penalty"], 0)

    def test_confirming_score_no_longer_uses_change_pct_as_signal_proxy(self):
        report_data = _report_data(
            {
                "startup_watchlist": [
                    _confirming_pick(code="600041", name="高涨幅等确认", change_pct=18.0, distance=1.0),
                ],
            }
        )

        workspace = build_workspace(report_data)
        trace = workspace["views"]["confirming"][0]["rank_trace"]

        self.assertEqual(trace["signal_score"], 10)
        self.assertLess(trace["signal_score"], 50 + 18.0)
        self.assertLessEqual(trace["signal_score"], 10)

    def test_highlights_ranking_is_deterministic_with_equal_score(self):
        high1 = _fusion_pick(
            code="600060",
            name="排序测一号",
            score=80,
            distance=1.4,
            change_pct=1.0,
        )
        high2 = _fusion_pick(
            code="600059",
            name="排序测二号",
            score=80,
            distance=1.4,
            change_pct=1.0,
        )
        report_data = _report_data({"picks_fusion": [high1, high2]})
        workspace = build_workspace(report_data)
        highlights = workspace["views"]["highlights"]

        self.assertEqual([item["code"] for item in highlights], ["600059", "600060"])

    def test_workspace_item_has_info_tags(self):
        report_data = _report_data({"picks_fusion": [_fusion_pick()]})

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        tags = {(tag["type"], tag["label"]) for tag in item["info_tags"]}

        self.assertIn(("sector", "测试板块"), tags)
        self.assertIn(("source", "正式主推"), tags)
        self.assertIn(("signal", "底背驰候选"), tags)

    def test_item_contract_separates_formal_action_from_scoring_decision(self):
        recommend = _fusion_pick(code="600071", name="正式推荐")
        observe = _fusion_pick(
            code="600072",
            name="融合观察",
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        observe["ret20"] = 12.0

        workspace = build_workspace(_report_data({"picks_fusion": [recommend, observe]}))
        main_item = workspace["views"]["main"][0]
        highlight_recommend = next(
            row for row in workspace["views"]["highlights"] if row["code"] == "600071"
        )
        highlight_observe = next(
            row for row in workspace["views"]["highlights"] if row["code"] == "600072"
        )
        growth_observe = workspace["views"]["growth_quality"][0]

        self.assertEqual(main_item["source_labels"], ["正式主推"])
        self.assertEqual(main_item["effective_action"], main_item["action"])
        self.assertEqual(main_item["action_semantics"], "formal")
        self.assertEqual(main_item["scoring_decision"]["decision_code"], "recommend")
        self.assertEqual(main_item["scoring_decision"]["decision"], "推荐")
        self.assertTrue(main_item["is_formal_recommendation"])

        for item in (highlight_recommend, highlight_observe, growth_observe):
            self.assertIn("融合候选", item["source_labels"])
            self.assertNotIn("主推", item["source_labels"])
            self.assertEqual(item["effective_action"], "仅观察")
            self.assertEqual(item["action_semantics"], "watch_only")
            self.assertFalse(item["is_formal_recommendation"])

        self.assertEqual(
            highlight_recommend["scoring_decision"]["decision_code"], "recommend"
        )
        self.assertEqual(highlight_observe["scoring_decision"]["decision_code"], "observe")
        self.assertEqual(highlight_observe["scoring_decision"]["decision"], "观察")

        self.assertTrue(
            all(
                not item["is_formal_recommendation"]
                for view_name, items in workspace["views"].items()
                if view_name not in {"main", "h4_t3"}
                for item in items
            )
        )

    def test_workspace_item_preserves_observe_decision_payload_in_highlights(self):
        decision = {
            "version": "1",
            "decision": "观察",
            "decision_code": "observe",
            "total_score": 42,
            "structure": {"score": 5, "reasons": ["震荡结构"]},
            "position": {"score": 35, "reasons": ["低位启动区"]},
            "sentiment": {"score": 2, "reasons": ["情绪信息不足"]},
        }
        with_decision = _fusion_pick(
            code="600050",
            name="决策票",
            score=10,
            distance=0.5,
            decision_engine_v1=decision,
        )
        higher_rank = _fusion_pick(
            code="600049",
            name="高机会分",
            score=95,
            distance=0.5,
        )

        workspace = build_workspace(_report_data({
            "picks_fusion": [with_decision, higher_rank]
        }))
        main_rows = workspace["views"]["main"]
        highlight_rows = workspace["views"]["highlights"]

        self.assertEqual([item["code"] for item in main_rows], ["600049"])
        self.assertEqual([item["code"] for item in highlight_rows], ["600049", "600050"])
        self.assertEqual(highlight_rows[1]["decision_engine_v1"], decision)

    def test_workspace_reject_decision_is_excluded_from_main_and_highlights(self):
        pick = _fusion_pick(
            decision_engine_v1={
                "decision_code": "reject",
                "decision": "不推荐（高位风险）",
            }
        )

        workspace = build_workspace({"picks_fusion": [pick]})
        self.assertEqual(workspace["views"]["main"], [])
        self.assertEqual(workspace["views"]["highlights"], [])

    def test_workspace_observe_decision_is_excluded_from_main_but_kept_in_highlights(self):
        pick = _fusion_pick(
            decision_engine_v1={
                "decision_code": "observe",
                "reason_code": "missing_position",
                "decision": "观察（位置数据不足）",
            }
        )

        workspace = build_workspace({"picks_fusion": [pick]})
        self.assertEqual(workspace["views"]["main"], [])
        item = workspace["views"]["highlights"][0]
        self.assertEqual(item["action"], "仅观察")
        self.assertIn("observe", item["action_reason"])
        self.assertIn("决策上限", item["action_reason"])

    def test_workspace_main_keeps_recommend_and_excludes_missing_decision(self):
        missing_decision = _fusion_pick(code="600051")
        missing_decision.pop("decision_engine_v1")
        rows = [
            _fusion_pick(
                code="600050",
                decision_engine_v1={
                    "decision_code": "recommend",
                    "decision": "推荐",
                },
            ),
            missing_decision,
        ]

        items = {
            item["code"]: item
            for item in build_workspace(_report_data({
                "picks_fusion": rows
            }))["views"]["main"]
        }

        self.assertEqual(list(items), ["600050"])
        self.assertEqual(items["600050"]["action"], "可上车")

    def test_workspace_does_not_treat_chinese_decision_without_code_as_recommend(self):
        pick = _fusion_pick(
            decision_engine_v1={"decision": "不推荐（高位风险）"}
        )

        workspace = build_workspace({"picks_fusion": [pick]})
        self.assertEqual(workspace["views"]["main"], [])

    def test_main_view_contains_all_recommendations_without_top_limit(self):
        rows = [
            _fusion_pick(code="60{:04d}".format(index))
            for index in range(12)
        ]
        rows.append(
            _fusion_pick(
                code="600099",
                decision_engine_v1={
                    "decision_code": "observe",
                    "decision": "暂不判断（位置信息不足）",
                },
            )
        )

        workspace = build_workspace(_report_data({"picks_fusion": rows}))

        self.assertEqual(len(workspace["views"]["main"]), 12)
        self.assertTrue(
            all(
                row["decision_engine_v1"]["decision_code"] == "recommend"
                for row in workspace["views"]["main"]
            )
        )

    def test_highlights_prioritizes_recommend_before_observe(self):
        recommend = _fusion_pick(code="600201", score=20)
        observe = _fusion_pick(
            code="600202",
            score=99,
            decision_engine_v1={
                "decision_code": "observe",
                "decision": "观察",
            },
        )

        rows = build_workspace({"picks_fusion": [observe, recommend]})["views"]["highlights"]

        self.assertEqual([row["code"] for row in rows], ["600201", "600202"])

    def test_growth_quality_excludes_rows_without_minimum_evidence(self):
        complete = _fusion_pick(
            code="600301",
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        complete["ret20"] = 12.0
        missing = _fusion_pick(
            code="600302",
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        missing["ret20"] = 12.0
        missing.pop("money20")
        missing.pop("market_cap")

        workspace = build_workspace({"picks_fusion": [missing, complete]})

        self.assertEqual(
            [row["code"] for row in workspace["views"]["growth_quality"]],
            ["600301"],
        )
        self.assertEqual(
            workspace["diagnostics"]["growth_quality"]["excluded_insufficient_evidence"],
            1,
        )

    def test_growth_quality_is_observe_only_and_requires_real_industry(self):
        observe = _fusion_pick(
            code="300401",
            sector="医药生物",
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        observe["ret20"] = 12.0
        recommend = _fusion_pick(code="300402", sector="医药生物")
        recommend["ret20"] = 12.0
        no_industry = _fusion_pick(
            code="300403",
            sector="",
            sector_tags=[],
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        no_industry["ret20"] = 12.0

        workspace = build_workspace({"picks_fusion": [observe, recommend, no_industry]})

        self.assertEqual(
            [row["code"] for row in workspace["views"]["growth_quality"]],
            ["300401"],
        )
        self.assertEqual(workspace["diagnostics"]["growth_quality"]["excluded_non_observe"], 1)
        self.assertEqual(workspace["diagnostics"]["growth_quality"]["excluded_missing_industry"], 1)

    def test_growth_quality_caps_each_industry_at_two_and_accepts_industry_fallback(self):
        picks = []
        for index in range(3):
            pick = _fusion_pick(
                code=f"30041{index}",
                sector="医药生物",
                decision_engine_v1={"decision_code": "observe", "decision": "观察"},
            )
            pick["ret20"] = 10.0 - index
            picks.append(pick)
        industry_only = _fusion_pick(
            code="300420",
            sector="",
            sector_tags=[],
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        industry_only["industry"] = "半导体"
        industry_only["ret20"] = 11.0
        picks.append(industry_only)

        workspace = build_workspace({"picks_fusion": picks})
        rows = workspace["views"]["growth_quality"]

        self.assertEqual(sum(row["pool_quality"]["industry_key"] == "医药生物" for row in rows), 2)
        self.assertIn("300420", [row["code"] for row in rows])
        self.assertEqual(workspace["diagnostics"]["growth_quality"]["excluded_industry_cap"], 1)

    def test_growth_quality_prefers_canonical_industry_over_theme_sector(self):
        pick = _fusion_pick(
            code="300425",
            sector="机器人概念",
            decision_engine_v1={"decision_code": "observe", "decision": "观察"},
        )
        pick["industry"] = "医药生物"
        pick["ret20"] = 12.0

        workspace = build_workspace({"picks_fusion": [pick]})

        row = workspace["views"]["growth_quality"][0]
        self.assertEqual(row["pool_quality"]["industry_key"], "医药生物")

    def test_pool_quality_does_not_use_stock_change_as_sector_quality_and_penalizes_crowded_ret20(self):
        calm = _fusion_pick(code="300430", sector="电子")
        calm["ret20"] = 15.0
        calm["change_pct"] = 1.0
        crowded = _fusion_pick(code="300431", sector="电子")
        crowded["ret20"] = 45.0
        crowded["change_pct"] = 9.0

        calm_quality = _build_pool_quality_features(calm)
        crowded_quality = _build_pool_quality_features(crowded)

        self.assertEqual(calm_quality["sector_quality_score"], crowded_quality["sector_quality_score"])
        self.assertGreater(calm_quality["ret20_score"], crowded_quality["ret20_score"])
        self.assertLess(crowded_quality["ret20_score"], 100.0)

    def test_workspace_info_tags_include_extra_sector_tags(self):
        pick = _fusion_pick(code="600005", name="半导体票", sector="电子")
        pick["sector_tags"] = ["电子", "半导体", "AI"]

        report_data = _report_data({"picks_fusion": [pick]})
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]

        sector_labels = [tag["label"] for tag in item["info_tags"] if tag["type"] == "sector"]

        self.assertIn("电子", sector_labels)
        self.assertIn("半导体", sector_labels)
        self.assertIn("AI", sector_labels)

    def test_pool_quality_growth_board_labels(self):
        report_data = _report_data(
            {
                "picks_fusion": [
                    _fusion_pick(code="300001", name="创业票", score=30),
                    _fusion_pick(code="688001", name="科创票", score=40),
                    _fusion_pick(code="002001", name="二级票", score=50),
                    _fusion_pick(code="600001", name="大盘票", score=20),
                ]
            }
        )

        workspace = build_workspace(report_data)
        main_items = {item["code"]: item["pool_quality"] for item in workspace["views"]["main"]}

        self.assertIn("创业板弹性", main_items["300001"]["pool_quality_tags"])
        self.assertIn("科创弹性", main_items["688001"]["pool_quality_tags"])
        self.assertIn("中小成长", main_items["002001"]["pool_quality_tags"])
        self.assertEqual(main_items["600001"]["growth_board_score"], 0.0)
        self.assertEqual(main_items["600001"]["growth_board_label"], "")

    def test_pool_quality_does_not_penalize_large_codes(self):
        report_data = _report_data(
            {
                "picks_fusion": [
                    _fusion_pick(code="600000", name="主板票", score=25),
                    _fusion_pick(code="000001", name="指数级码", score=26),
                ]
            }
        )

        workspace = build_workspace(report_data)
        main_items = {item["code"]: item["pool_quality"] for item in workspace["views"]["main"]}

        self.assertEqual(main_items["600000"]["growth_board_score"], 0.0)
        self.assertEqual(main_items["600000"]["growth_board_label"], "")
        self.assertEqual(main_items["000001"]["growth_board_score"], 0.0)
        self.assertEqual(main_items["000001"]["growth_board_label"], "")

    def test_pool_quality_handles_missing_volume_gracefully(self):
        pick = _fusion_pick(code="600033", name="缺数据票", score=33)
        pick.pop("volumes", None)
        pick.pop("money20", None)

        report_data = _report_data({"picks_fusion": [pick]})
        workspace = build_workspace(report_data)
        pool_quality = workspace["views"]["main"][0]["pool_quality"]

        self.assertEqual(pool_quality["volume20"], 0.0)
        self.assertEqual(pool_quality["volume_ratio20"], 0.0)
        self.assertEqual(pool_quality["liquidity_score"], 0.0)

    def test_workspace_item_exposes_pool_quality(self):
        report_data = _report_data({"picks_fusion": [_fusion_pick(code="600034", name="池质量可视", score=44)]})
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]

        self.assertIn("pool_quality", item)
        self.assertIn("volume20", item["pool_quality"])
        self.assertIn("pool_quality_score", item["pool_quality"])
        self.assertIsInstance(item["pool_quality"]["pool_quality_tags"], list)

    def test_workspace_data_badges_reflect_stale_status(self):
        pick = _fusion_pick(code="600006", name="延时票")
        pick["data_status"] = {"daily": "stale_cache"}

        report_data = _report_data({"picks_fusion": [pick]})
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]

        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertIn("缓存兜底", badge_labels)
        self.assertIn("数据非最新", badge_labels)

    def test_workspace_does_not_claim_verified_when_market_unverified(self):
        pick = _fusion_pick(code="600007", name="非交易态票")
        report_data = _report_data(
            {
                "data_quality": {"market_status": "unverified", "fallback_used": False},
                "picks_fusion": [pick],
            }
        )

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertNotIn("数据已校验", badge_labels)

    def test_workspace_does_not_claim_verified_without_row_status(self):
        pick = _fusion_pick(code="600008", name="无状态票")
        report_data = _report_data(
            {
                "data_quality": {"market_status": "verified", "fallback_used": False},
                "picks_fusion": [pick],
            }
        )

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertNotIn("数据已校验", badge_labels)
        self.assertIn("数据状态未标记", badge_labels)

    def test_workspace_claims_verified_with_row_status(self):
        pick = _fusion_pick(code="600009", name="已校验票")
        pick["data_status"] = {"daily": "verified"}
        report_data = _report_data({"picks_fusion": [pick]})

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertIn("数据已校验", badge_labels)

    def test_no_acceleration_without_enabled_mode(self):
        report_data = _report_data(
            {
                "next_day_boom": {"mode": "disabled", "candidates": [_acceleration_pick(code="600020")]},
            }
        )
        workspace = build_workspace(report_data)

        self.assertEqual(workspace["views"]["acceleration"], [])
        self.assertEqual(workspace["views"]["highlights"], [])

    def test_no_boarding_actions_for_non_main_sources(self):
        report_data = _report_data(
            {
                "next_day_boom": {"mode": "enabled", "candidates": [_acceleration_pick(code="600020")]},
                "luojie_pool": {"mode": "enabled", "candidates": [_luojie_pick(code="600021")]},
                "startup_watchlist": [_confirming_pick(code="600022")],
            }
        )
        workspace = build_workspace(report_data)

        for view_name in ("acceleration", "luojie", "confirming"):
            for item in workspace["views"][view_name]:
                self.assertIn(item["action"], {"盯盘", "慎追", "等回踩", "仅观察"})
                self.assertNotEqual(item["action"], "可上车", view_name)

    def test_workspace_items_do_not_copy_large_chart_fields(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick()],
                "next_day_boom": {"mode": "enabled", "candidates": [_acceleration_pick()]},
                "luojie_pool": {"mode": "enabled", "candidates": [_luojie_pick()]},
                "startup_watchlist": [_confirming_pick()],
                "picks_pure": [_baseline_pick()],
            }
        )

        workspace = build_workspace(report_data)
        for view_name in workspace["view_order"]:
            for item in workspace["views"][view_name]:
                self.assertFalse(LARGE_FIELDS.intersection(item), view_name)
                self.assertIn("watch_score", item, view_name)
                self.assertIn("opportunity_score", item, view_name)
                self.assertEqual(item["watch_score"], item["opportunity_score"], view_name)
                self.assertIn("action_reason", item)
                self.assertIn("primary_reason", item)
                self.assertIn("risk_flags", item)
                self.assertIn("rank_trace", item)
                self.assertIn("ref", item)

    def test_conservative_risk_heuristics(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick(code="600030", distance=7.4, change_pct=8.6)],
                "next_day_boom": {"mode": "enabled", "candidates": []},
                "startup_watchlist": [_confirming_pick(code="600031", change_pct=4.0, distance=3.1)],
            }
        )

        workspace = build_workspace(report_data)
        main_item = workspace["views"]["main"][0]
        confirming_item = workspace["views"]["confirming"][0]

        self.assertEqual(main_item["action"], "慎追")
        self.assertIn("距参考价偏高", main_item["risk_flags"])
        self.assertIn("涨幅过热", main_item["risk_flags"])
        self.assertEqual(confirming_item["action"], "等回踩")
        self.assertNotEqual(confirming_item["action"], "可上车")

    def test_confirming_observe_action_is_not_duplicated_as_risk_tag(self):
        report_data = _report_data(
            {
                "startup_watchlist": [_confirming_pick(code="600032", change_pct=9.0, distance=1.2)],
            }
        )

        workspace = build_workspace(report_data)
        confirming_item = workspace["views"]["confirming"][0]

        self.assertEqual(confirming_item["action"], "仅观察")
        self.assertNotIn("仅观察", confirming_item["risk_flags"])
        self.assertIn("涨幅过热", confirming_item["risk_flags"])

    def test_workspace_main_derives_change_pct_from_closes_when_pick_lacks_change_field(self):
        pick = _fusion_pick(code="600100", name="主推闭坑票")
        pick.pop("change_pct", None)
        pick["best_buy_point"].pop("change_pct", None)
        pick["closes"] = [10.0, 10.5, 10.29]
        pick["best_buy_point"]["current_price"] = 10.29

        report_data = _report_data(
            {
                "picks_fusion": [pick],
            }
        )
        workspace = build_workspace(report_data)

        main_item = workspace["views"]["main"][0]
        highlight_item = workspace["views"]["highlights"][0]

        self.assertEqual(main_item["change_pct"], -2.0)
        self.assertEqual(highlight_item["change_pct"], -2.0)
        self.assertEqual(main_item["current_price"], 10.29)

    def test_workspace_baseline_uses_pick_metric_derivation(self):
        pick = _baseline_pick(code="600101", name="基准回补票")
        pick.pop("change_pct", None)
        pick["best_buy_point"].pop("change_pct", None)
        pick["closes"] = [20.0, 21.0, 21.42]
        pick["best_buy_point"]["current_price"] = 21.42

        report_data = _report_data(
            {
                "picks_pure": [pick],
            }
        )
        workspace = build_workspace(report_data)
        item = workspace["views"]["baseline"][0]

        self.assertEqual(item["change_pct"], 2.0)
        self.assertEqual(item["current_price"], 21.42)


if __name__ == "__main__":
    unittest.main()
