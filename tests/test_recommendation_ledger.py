import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np

from chanlun.recommendation_ledger import (
    append_recommendation_entries,
    build_recommendation_entries,
    finalize_staged_recommendation_entries,
    load_recommendation_entries,
    load_staged_recommendation_entries,
    prepare_recommendation_history,
    stage_recommendation_entries,
)


def _item(code="300308", decision_code="recommend"):
    return {
        "code": code,
        "name": "中际旭创" if code == "300308" else "测试股",
        "closes": [180.0, 188.0],
        "best_buy_point": {
            "type": "三买",
            "price": 186.0,
            "reason": "放量突破后回踩确认",
        },
        "decision_engine_v1": {
            "version": "1",
            "decision": "推荐" if decision_code == "recommend" else "观察",
            "decision_code": decision_code,
            "total_score": 78,
            "structure": {"score": 40, "reasons": ["突破结构"]},
            "position": {"score": 20, "reasons": ["位置较低"]},
            "sentiment": {"score": 18, "reasons": ["板块共振"]},
            "risk_reasons": [],
        },
    }


def _strategy(name, version, items, **extra):
    row = {
        "strategy_name": name,
        "strategy_version": version,
        "source_pool": name,
        "entry_mode": "immediate_close",
        "intended_horizon": 3,
        "publication_status": "published",
        "user_action_from_decision": True,
        "items": items,
    }
    row.update(extra)
    return row


class RecommendationLedgerTests(unittest.TestCase):
    def test_immediate_close_contract_freezes_signal_close_and_horizon(self):
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("daily_fusion", "fusion-v2", [_item()])],
        )

        entry = entries[0]
        contribution = entry["strategy_contributions"][0]
        self.assertEqual(entry["schema_version"], "2")
        self.assertEqual(entry["signal_close"], 188.0)
        self.assertEqual(contribution["entry_mode"], "immediate_close")
        self.assertEqual(contribution["entry_price"], 188.0)
        self.assertEqual(contribution["intended_horizon"], 3)
        self.assertEqual(contribution["intended_horizon_label"], "T+3")
        self.assertEqual(contribution["horizon_status"], "verified")

    def test_missing_or_conflicting_horizon_cannot_enter_recommendation_cohort(self):
        missing = _strategy(
            "daily_fusion", "fusion-v2", [_item()], intended_horizon=None
        )
        conflict_item = _item("300139")
        conflict_item["strategy_sources"] = [
            {"strategy_source": "source-a", "intended_horizon": 1},
            {"strategy_source": "source-b", "intended_horizon": 5},
        ]
        conflict = _strategy(
            "daily_fusion", "fusion-v2", [conflict_item],
            intended_horizon=None,
        )

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [missing, conflict],
        )
        by_code = {
            row["code"]: row["strategy_contributions"][0]
            for row in entries
        }
        self.assertEqual(by_code["300308"]["horizon_status"], "missing")
        self.assertEqual(by_code["300139"]["horizon_status"], "conflict")
        self.assertFalse(by_code["300308"]["cohort_eligible"])
        self.assertFalse(by_code["300139"]["cohort_eligible"])

    def test_top_level_horizon_cannot_hide_source_conflict(self):
        item = _item("300140")
        item["intended_horizon"] = 1
        item["strategy_sources"] = [
            {
                "strategy_source": "source-a",
                "source_status": "candidate",
                "intended_horizon": 1,
            },
            {
                "strategy_source": "source-b",
                "source_status": "candidate",
                "intended_horizon": 5,
            },
        ]

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("daily_fusion", "fusion-v2", [item])],
        )

        contribution = entries[0]["strategy_contributions"][0]
        self.assertEqual(contribution["horizon_status"], "conflict")
        self.assertIsNone(contribution["intended_horizon"])
        self.assertFalse(contribution["cohort_eligible"])

    def test_h4_uses_its_own_t3_source_not_upstream_fusion_horizons(self):
        item = _item("300141")
        item["intended_horizon"] = 3
        item["strategy_source"] = "h4_t3"
        item["strategy_sources"] = [{
            "strategy_source": "h4_t3",
            "source_status": "candidate",
            "intended_horizon": 3,
        }]
        item["upstream_strategy_sources"] = [
            {
                "strategy_source": "chanlun_structure",
                "source_status": "candidate",
                "intended_horizon": 1,
            },
            {
                "strategy_source": "trend_continuation",
                "source_status": "candidate",
                "intended_horizon": 5,
            },
        ]

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("h4_t3", "h4-v1", [item])],
        )

        contribution = entries[0]["strategy_contributions"][0]
        self.assertEqual(3, contribution["intended_horizon"])
        self.assertEqual([3], contribution["source_horizons"])
        self.assertEqual("verified", contribution["horizon_status"])
        self.assertTrue(contribution["cohort_eligible"])
        self.assertEqual(
            "chanlun_structure",
            contribution["reason_snapshot"][
                "upstream_strategy_sources"
            ][0]["strategy_source"],
        )

    def test_daily_pure_is_a_candidate_universe_not_a_recommendation(self):
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("daily_pure", "", [_item()])],
        )

        contribution = entries[0]["strategy_contributions"][0]
        self.assertEqual(
            contribution["strategy_version"],
            "daily-pure-candidate-universe-v1",
        )
        self.assertEqual(contribution["version_status"], "verified")
        self.assertEqual(contribution["publication_status"], "candidate")
        self.assertEqual(contribution["user_action"], "watch")
        self.assertFalse(contribution["cohort_eligible"])

    def test_daily_fusion_only_publishes_recommend_decisions(self):
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy(
                "daily_fusion",
                "",
                [
                    _item("300308", "recommend"),
                    _item("300139", "observe"),
                ],
            )],
        )

        by_code = {
            entry["code"]: entry["strategy_contributions"][0]
            for entry in entries
        }
        self.assertEqual(
            by_code["300308"]["strategy_version"],
            "daily-fusion-main-v2",
        )
        self.assertEqual(by_code["300308"]["publication_status"], "published")
        self.assertEqual(by_code["300308"]["user_action"], "recommendation")
        self.assertTrue(by_code["300308"]["cohort_eligible"])
        self.assertEqual(by_code["300139"]["publication_status"], "internal")
        self.assertEqual(by_code["300139"]["user_action"], "watch")
        self.assertFalse(by_code["300139"]["cohort_eligible"])

    def test_numpy_vector_fields_are_frozen_as_json_arrays(self):
        item = _item()
        item["dates"] = np.array(["2026-08-19", "2026-08-20"])
        item["closes"] = np.array([180.0, 188.0])

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("daily_pure", "pure-v1", [item])],
            policy_version="decision-v1",
            config_revision="cfg-abc",
            code_version="commit-123",
        )

        self.assertEqual(entries[0]["reference_close"], 188.0)
        self.assertEqual(
            entries[0]["strategy_contributions"][0]["reason_snapshot"]
            ["best_buy_point"]["price"],
            186.0,
        )

    def test_ids_are_stable_and_input_order_independent(self):
        strategies = [
            _strategy("daily_pure", "pure-v1", [_item("300308")]),
            _strategy("daily_fusion", "fusion-v2", [_item("300139")]),
        ]

        first = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            strategies,
            policy_version="decision-v1",
            config_revision="cfg-abc",
            code_version="commit-123",
        )
        second = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            list(reversed(strategies)),
            policy_version="decision-v1",
            config_revision="cfg-abc",
            code_version="commit-123",
        )

        self.assertEqual(
            [entry["recommendation_id"] for entry in first],
            [entry["recommendation_id"] for entry in second],
        )
        self.assertEqual(
            [entry["code"] for entry in first],
            ["300139", "300308"],
        )

    def test_same_stock_keeps_multiple_strategy_contributions(self):
        source = _item()
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [
                _strategy("daily_pure", "pure-v1", [source]),
                _strategy("daily_fusion", "fusion-v2", [source]),
            ],
            policy_version="decision-v1",
            config_revision={"recall": "active"},
            code_version="commit-123",
        )

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(len(entry["strategy_contributions"]), 2)
        self.assertEqual(
            [row["strategy_name"] for row in entry["strategy_contributions"]],
            ["daily_fusion", "daily_pure"],
        )
        self.assertEqual(entry["policy_version"], "decision-v1")
        self.assertEqual(entry["code_version"], "commit-123")
        self.assertTrue(entry["config_revision"].startswith("sha256:"))

        frozen = copy.deepcopy(entry)
        source["decision_engine_v1"]["structure"]["reasons"][0] = "后改理由"
        self.assertEqual(entry, frozen)

    def test_missing_versions_and_decisions_are_marked_unknown_not_inferred(self):
        item = _item()
        item.pop("decision_engine_v1")
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("legacy_pool", "", [item])],
            policy_version="",
            config_revision="",
            code_version="",
        )

        contribution = entries[0]["strategy_contributions"][0]
        self.assertEqual(contribution["strategy_version"], "unknown")
        self.assertEqual(contribution["version_status"], "unknown")
        self.assertEqual(contribution["decision_code"], "unknown")
        self.assertEqual(contribution["attribution_status"], "legacy_unknown")
        self.assertEqual(entries[0]["policy_version"], "unknown")

    def test_publication_role_controls_performance_cohort(self):
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy(
                "observation_gate",
                "gate-v1",
                [_item()],
                publication_status="internal",
                user_action="watch",
                user_action_from_decision=False,
            )],
        )

        contribution = entries[0]["strategy_contributions"][0]
        self.assertEqual(contribution["decision_code"], "recommend")
        self.assertEqual(contribution["publication_status"], "internal")
        self.assertEqual(contribution["user_action"], "watch")
        self.assertFalse(contribution["cohort_eligible"])

    def test_missing_entry_mode_is_unknown_not_delay1_open(self):
        strategy = _strategy("legacy_pool", "", [_item()])
        strategy.pop("entry_mode")

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [strategy],
        )

        self.assertEqual(
            entries[0]["strategy_contributions"][0]["entry_mode"],
            "unknown",
        )

    def test_user_action_is_frozen_from_each_items_final_decision(self):
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy(
                "daily_fusion",
                "fusion-v2",
                [
                    _item("300308", "recommend"),
                    _item("300139", "observe"),
                    _item("688041", "reject"),
                ],
            )],
        )

        actions = {
            entry["code"]: entry["strategy_contributions"][0]["user_action"]
            for entry in entries
        }
        self.assertEqual(actions["300308"], "recommendation")
        self.assertEqual(actions["300139"], "watch")
        self.assertEqual(actions["688041"], "none")

    def test_unvalidated_observation_strategies_never_enter_recommendation_cohort(self):
        observe = _item("300308", "observe")
        no_gate = _item("300139", "recommend")
        no_gate.pop("decision_engine_v1")
        for strategy_name, horizon in (
            ("next_day_boom", 1),
            ("luojie_pool", None),
        ):
            entries = build_recommendation_entries(
                "2026-08-20",
                "2026-08-20T15:10:00+08:00",
                [_strategy(
                    strategy_name,
                    "observation-v1",
                    [observe, no_gate],
                    intended_horizon=horizon,
                    published_decision_code="recommend",
                )],
            )

            by_code = {
                entry["code"]: entry["strategy_contributions"][0]
                for entry in entries
            }
            for contribution in by_code.values():
                self.assertEqual(contribution["publication_status"], "internal")
                self.assertEqual(contribution["user_action"], "watch")
                self.assertFalse(contribution["cohort_eligible"])

    def test_append_is_idempotent_and_never_rewrites_existing_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ledger.jsonl"
            entries = build_recommendation_entries(
                "2026-08-20",
                "2026-08-20T15:10:00+08:00",
                [_strategy("daily_pure", "pure-v1", [_item()])],
                policy_version="decision-v1",
                config_revision="cfg-1",
                code_version="commit-123",
            )
            self.assertEqual(append_recommendation_entries(path, entries), 1)

            changed = copy.deepcopy(entries)
            changed[0]["strategy_contributions"][0]["reason_snapshot"] = {
                "tampered": True
            }
            self.assertEqual(append_recommendation_entries(path, changed), 0)

            loaded = load_recommendation_entries(path)
            self.assertEqual(len(loaded), 1)
            self.assertNotIn(
                "tampered",
                loaded[0]["strategy_contributions"][0]["reason_snapshot"],
            )

    def test_append_deduplicates_repeated_ids_within_the_same_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ledger.jsonl"
            entries = build_recommendation_entries(
                "2026-08-20",
                "2026-08-20T15:10:00+08:00",
                [_strategy("daily_pure", "pure-v1", [_item()])],
            )

            self.assertEqual(
                append_recommendation_entries(path, entries + entries), 1
            )
            self.assertEqual(len(load_recommendation_entries(path)), 1)

    def test_staged_entries_only_reach_ledger_after_explicit_finalize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pending = Path(tmpdir) / "pending.json"
            ledger = Path(tmpdir) / "ledger.jsonl"
            entries = build_recommendation_entries(
                "2026-08-20",
                "2026-08-20T15:10:00+08:00",
                [_strategy("daily_pure", "pure-v1", [_item()])],
            )

            stage_recommendation_entries(pending, entries)

            self.assertFalse(ledger.exists())
            self.assertEqual(load_staged_recommendation_entries(pending), entries)
            self.assertEqual(
                finalize_staged_recommendation_entries(pending, ledger), 1
            )
            self.assertEqual(load_recommendation_entries(ledger), entries)
            self.assertEqual(
                finalize_staged_recommendation_entries(pending, ledger), 0
            )

    def test_preview_or_unofficial_entries_are_withheld_from_pending_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pending = Path(tmpdir) / "pending.json"
            ledger = Path(tmpdir) / "ledger.jsonl"
            entries = build_recommendation_entries(
                "2026-08-20",
                "2026-08-20T15:10:00+08:00",
                [_strategy("daily_pure", "pure-v1", [_item()])],
            )

            history, diagnostics = prepare_recommendation_history(
                ledger,
                pending,
                entries,
                publication_eligible=False,
            )

            self.assertEqual(history, entries)
            self.assertEqual(diagnostics["status"], "withheld")
            self.assertFalse(pending.exists())
            self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
