import unittest

from chanlun.decision_workbench import build_decision_workbench


def _formal_report():
    return {
        "date": "2026-09-07",
        "data_quality": {"as_of": "2026-09-07T15:05:00+08:00", "is_official": True,
                         "bar_state": "closed", "market_status": "verified"},
        "selection_input_health": {
            "formal": {
                "formal_actions_allowed": True,
            },
        },
    }


def _workspace():
    return {
        "trade_date": "2026-09-07",
        "views": {
            "main": [
                {
                    "code": "600001",
                    "name": "测试A",
                    "opportunity_score": 88,
                    "formal_decision_contract": {
                        "action": "可上车",
                        "action_reason": "观察后确认趋势",
                        "reference_price": 9.9,
                        "intended_horizon": 2,
                        "position_band": 0.5,
                        "pressure_price": 9.7,
                        "invalidation_price": 8.6,
                    },
                }
            ],
            "h4_t3": [
                {
                    "code": "600001",
                    "name": "测试A",
                    "opportunity_price": 9.7,
                    "formal_decision_contract": {
                        "action": "可上车",
                        "action_reason": "盘中确认",
                        "reference_price": 9.9,
                        "intended_horizon": 2,
                        "position_band": 0.5,
                        "pressure_price": 9.7,
                        "invalidation_price": 8.6,
                    },
                },
                {
                    "code": "600002",
                    "name": "测试B",
                    "opportunity_score": 80,
                    "formal_decision_contract": {
                        "action": "谨慎观察",
                        "action_reason": "条件不足",
                        "reference_price": 11.2,
                        "intended_horizon": 3,
                        "position_band": 0.5,
                        "pressure_price": 10.5,
                        "invalidation_price": 9.2,
                    },
                    "action": "慎追",
                },
            ],
        },
        "as_of": "2026-09-07T15:30:00+08:00",
    }


def _evidence(workspace):
    return {"report_date": "2026-09-07", "views": {
        view: [{"code": row["code"], "summary": {"status": "available", "as_of": "2026-09-07"},
                "daily_structure": {"status": "available", "as_of": "2026-09-07", "is_final": True},
                "sublevel_30m": {"status": "available", "as_of": "2026-09-07"},
                "price_evidence": {"status": "available", "as_of": "2026-09-07"}}
               for row in rows] for view, rows in workspace["views"].items()}}


def _formal_output():
    return build_decision_workbench(_formal_report(), _workspace(), _evidence(_workspace()))


def _conflict_workspace():
    return {
        "trade_date": "2026-09-07",
        "as_of": "2026-09-07T15:30:00+08:00",
        "views": {
            "main": [
                {
                    "code": "600003",
                    "name": "冲突A",
                    "opportunity_score": 95,
                    "formal_decision_contract": {
                        "action": "可上车",
                        "action_reason": "主线一致",
                        "reference_price": 10.0,
                        "intended_horizon": 2,
                        "position_band": 0.2,
                        "pressure_price": 9.8,
                        "invalidation_price": 8.9,
                    },
                }
            ],
            "h4_t3": [
                {
                    "code": "600003",
                    "name": "冲突A",
                    "opportunity_score": 98,
                    "formal_decision_contract": {
                        "action": "等回踩",
                        "action_reason": "H4 提示",
                        "reference_price": 10.1,
                        "intended_horizon": 3,
                        "position_band": 0.2,
                        "pressure_price": 10.0,
                        "invalidation_price": 8.8,
                    },
                },
            ],
        },
    }


def _price_blocked_workspace():
    return {
        "trade_date": "2026-09-07",
        "as_of": "2026-09-07T15:30:00+08:00",
        "views": {
            "main": [
                {
                    "code": "600004",
                    "name": "坏价位",
                    "opportunity_score": 70,
                    "formal_decision_contract": {
                        "action": "可上车",
                        "action_reason": "价格不可用",
                        "reference_price": 0,
                        "intended_horizon": 2,
                        "position_band": 0.2,
                        "pressure_price": 10.0,
                        "invalidation_price": 9.0,
                    },
                }
            ],
        },
    }


class DecisionWorkbenchTests(unittest.TestCase):
    def test_build_decision_workbench_deduplicates_by_code(self):
        result = _formal_output()

        self.assertEqual(result["phase"], "formal")
        self.assertEqual(len(result["items"]), 2)
        codes = [row["code"] for row in result["items"]]
        self.assertEqual(codes, ["600001", "600002"])
        self.assertEqual(result["items"][0]["is_executable"], True)
        self.assertEqual(result["items"][0]["action"], "可上车")
        self.assertIn("sources", result["items"][0])
        self.assertEqual(result["items"][0]["sources"], ["main", "h4_t3"])

    def test_build_decision_workbench_tracks_health_blocking_and_changes(self):
        blocked = _formal_report()
        blocked["selection_input_health"]["formal"]["formal_actions_allowed"] = False
        result = build_decision_workbench(blocked, _workspace(), {})

        self.assertFalse(result["health"]["formal_actions_allowed"])
        self.assertEqual(
            result["health"]["blocking_reasons"],
            ["formal动作策略暂未授权"],
        )
        self.assertFalse(result["items"][0]["is_executable"])

    def test_build_decision_workbench_prefers_primary_source_and_detects_conflict(self):
        result = build_decision_workbench(_formal_report(), _conflict_workspace(), _evidence(_conflict_workspace()))
        self.assertEqual(len(result["items"]), 1)

        item = result["items"][0]
        self.assertEqual(item["code"], "600003")
        self.assertEqual(item["page_status"], "strategy_disagreement")
        self.assertEqual(item["sources"], ["main", "h4_t3"])
        self.assertIn("strategy_conflict", item["blocked_reasons"])
        self.assertIn("strategy_conflicts", item)
        self.assertEqual(item["strategy_conflicts"], [
            {"source": "main", "action": "可上车"},
            {"source": "h4_t3", "action": "等回踩"}
        ])
        self.assertEqual(
            item["strategy_actions"],
            [
                {"source": "main", "action": "可上车"},
                {"source": "h4_t3", "action": "等回踩"},
            ],
        )
        self.assertFalse(item["is_executable"])

    def test_build_decision_workbench_blocks_non_positive_reference_price(self):
        result = build_decision_workbench(_formal_report(), _price_blocked_workspace(), {})

        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["code"], "600004")
        self.assertEqual(item["action"], "可上车")
        self.assertIn("missing_reference_price", item["blocked_reasons"])
        self.assertFalse(item["is_executable"])

    def test_build_changes_requires_phase_and_date_match(self):
        current = _formal_output()
        previous = {
            "report_date": "2026-09-06",
            "phase": "formal",
            "items": [],
        }
        current_again = build_decision_workbench(
            _formal_report(),
            _workspace(),
            {},
            previous=previous,
        )
        self.assertEqual(current_again["changes"]["status"], "comparison_unavailable")
        self.assertEqual(
            current_again["changes"]["reason"],
            "comparison_contract_unavailable_or_changed",
        )

    def test_formal_observe_conflicts_with_executable_formal_action(self):
        workspace = {
            "trade_date": "2026-09-07",
            "as_of": "2026-09-07T15:30:00+08:00",
            "views": {
                "main": [
                    {
                        "code": "600010",
                        "name": "冲突样本A",
                        "opportunity_score": 99,
                        "formal_decision_contract": {
                            "action": "可上车",
                            "action_reason": "主线候选",
                            "reference_price": 12.0,
                            "intended_horizon": 2,
                            "position_band": 0.2,
                            "pressure_price": 11.8,
                            "invalidation_price": 10.5,
                        },
                    }
                ],
                "h4_t3": [
                    {
                        "code": "600010",
                        "name": "冲突样本A",
                        "opportunity_score": 88,
                        "formal_decision_contract": {
                            "action": "仅观察",
                            "action_reason": "仅研究观察",
                            "reference_price": 12.0,
                            "intended_horizon": 3,
                            "position_band": 0.5,
                            "pressure_price": 11.5,
                            "invalidation_price": 10.3,
                        },
                    }
                ],
            },
        }
        result = build_decision_workbench(_formal_report(), workspace, _evidence(workspace))
        self.assertEqual(result["items"][0]["page_status"], "strategy_disagreement")
        self.assertIn("strategy_conflict", result["items"][0]["blocked_reasons"])
        self.assertFalse(result["items"][0]["is_executable"])

    def test_safe_float_ignores_boolean_reference_price(self):
        workspace = {
            "trade_date": "2026-09-07",
            "as_of": "2026-09-07T15:30:00+08:00",
            "views": {
                "main": [
                    {
                        "code": "600020",
                        "name": "布尔测试",
                        "opportunity_score": 77,
                        "formal_decision_contract": {
                            "action": "可上车",
                            "action_reason": "布尔价格测试",
                            "reference_price": True,
                            "intended_horizon": 2,
                            "position_band": 0.4,
                            "pressure_price": 10.0,
                            "invalidation_price": 9.0,
                        },
                    }
                ],
            },
        }
        result = build_decision_workbench(_formal_report(), workspace, {})
        self.assertEqual(result["items"][0]["action"], "可上车")
        self.assertIn("missing_reference_price", result["items"][0]["blocked_reasons"])
        self.assertFalse(result["items"][0]["is_executable"])

    def test_payload_hash_deterministic_for_same_input(self):
        first = _formal_output()["payload_hash"]
        second = _formal_output()["payload_hash"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
