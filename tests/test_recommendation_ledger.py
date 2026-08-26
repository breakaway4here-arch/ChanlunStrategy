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
        "dates": ["2026-08-19", "2026-08-20"],
        "closes": [180.0, 188.0],
        "data_status": {
            "daily": "verified",
            "latest_date": "2026-08-20",
            "is_final": True,
        },
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
        "entry_mode": "delay1_open",
        "intended_horizon": 3,
        "publication_status": "published",
        "user_action_from_decision": True,
        "items": items,
    }
    row.update(extra)
    return row


class RecommendationLedgerTests(unittest.TestCase):
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
        self.assertEqual(entries[0]["reference_close_source"], "closes[-1]")
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
        self.assertEqual(contribution["evaluation_role"], "diagnostic")
        self.assertFalse(contribution["evaluation_eligible"])
        self.assertEqual(contribution["eligibility_reason"], "diagnostic_only")
        self.assertEqual(contribution["publication_surface"], "gate_diagnostics")

    def test_strategy_roles_are_frozen_and_only_formal_can_enter_cohort(self):
        strategies = [
            _strategy("daily_fusion", "fusion-v1", [_item("300308")]),
            _strategy("daily_pure", "pure-v1", [_item("300139")]),
            _strategy(
                "next_day_boom", "boom-v1", [_item("688041")],
                intended_horizon=1,
                published_decision_code="recommend",
            ),
            _strategy(
                "luojie_pool", "luojie-v1", [_item("600001")],
                user_action="watch",
                user_action_from_decision=False,
            ),
            _strategy(
                "observation_gate", "gate-v1", [_item("000001")],
                publication_status="internal",
                user_action="watch",
                user_action_from_decision=False,
            ),
        ]

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            strategies,
        )
        contributions = {
            row["strategy_name"]: row
            for entry in entries
            for row in entry["strategy_contributions"]
        }

        self.assertEqual(contributions["daily_fusion"]["evaluation_role"], "formal")
        self.assertEqual(contributions["daily_pure"]["evaluation_role"], "baseline")
        self.assertEqual(contributions["next_day_boom"]["evaluation_role"], "research")
        self.assertEqual(contributions["luojie_pool"]["evaluation_role"], "research")
        self.assertEqual(contributions["observation_gate"]["evaluation_role"], "diagnostic")
        self.assertTrue(contributions["daily_fusion"]["cohort_eligible"])
        self.assertFalse(contributions["daily_pure"]["cohort_eligible"])
        self.assertFalse(contributions["next_day_boom"]["cohort_eligible"])
        self.assertFalse(contributions["luojie_pool"]["cohort_eligible"])
        self.assertFalse(contributions["observation_gate"]["cohort_eligible"])
        self.assertTrue(contributions["daily_pure"]["evaluation_eligible"])
        self.assertTrue(contributions["next_day_boom"]["evaluation_eligible"])
        self.assertTrue(contributions["luojie_pool"]["evaluation_eligible"])
        self.assertFalse(contributions["observation_gate"]["evaluation_eligible"])
        self.assertEqual(
            contributions["daily_fusion"]["publication_surface"],
            "formal_recommendation",
        )
        self.assertEqual(
            contributions["daily_pure"]["publication_surface"],
            "baseline_candidates",
        )
        self.assertEqual(
            contributions["next_day_boom"]["publication_surface"],
            "research_review",
        )
        self.assertEqual(
            contributions["observation_gate"]["publication_surface"],
            "gate_diagnostics",
        )

    def test_registered_strategy_role_cannot_be_promoted_by_input(self):
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [
                _strategy(
                    "daily_pure", "pure-v1", [_item("300139")],
                    evaluation_role="formal",
                    publication_surface="formal_recommendation",
                ),
                _strategy(
                    "observation_gate", "gate-v1", [_item("000001")],
                    evaluation_role="formal",
                    publication_surface="formal_recommendation",
                ),
            ],
        )
        by_strategy = {
            row["strategy_name"]: row
            for entry in entries
            for row in entry["strategy_contributions"]
        }

        self.assertEqual(by_strategy["daily_pure"]["evaluation_role"], "unknown")
        self.assertEqual(
            by_strategy["daily_pure"]["publication_surface"],
            "technical_detail",
        )
        self.assertFalse(by_strategy["daily_pure"]["cohort_eligible"])
        self.assertFalse(by_strategy["daily_pure"]["evaluation_eligible"])
        self.assertEqual(
            by_strategy["daily_pure"]["eligibility_reason"],
            "unknown_evaluation_role",
        )
        self.assertEqual(
            by_strategy["observation_gate"]["evaluation_role"],
            "unknown",
        )
        self.assertFalse(by_strategy["observation_gate"]["cohort_eligible"])
        self.assertFalse(by_strategy["observation_gate"]["evaluation_eligible"])

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
                "daily_pure",
                "pure-v1",
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

    def test_explicit_candidate_strategy_still_respects_a_present_gate_decision(self):
        observe = _item("300308", "observe")
        no_gate = _item("300139", "recommend")
        no_gate.pop("decision_engine_v1")
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy(
                "next_day_boom",
                "boom-v1",
                [observe, no_gate],
                intended_horizon=1,
                published_decision_code="recommend",
            )],
        )

        by_code = {
            entry["code"]: entry["strategy_contributions"][0]
            for entry in entries
        }
        self.assertEqual(by_code["300308"]["user_action"], "watch")
        self.assertFalse(by_code["300308"]["cohort_eligible"])
        self.assertTrue(by_code["300308"]["evaluation_eligible"])
        self.assertEqual(by_code["300139"]["user_action"], "recommendation")
        self.assertFalse(by_code["300139"]["cohort_eligible"])
        self.assertTrue(by_code["300139"]["evaluation_eligible"])

    def test_top_level_close_is_only_a_verified_final_fallback(self):
        verified = _item()
        verified.pop("closes")
        verified["close"] = 191.5
        verified["data_status"] = {
            "daily": "verified",
            "is_final": True,
            "latest_date": "2026-08-20",
        }
        stale = _item("300139")
        stale.pop("closes")
        stale["close"] = 199.5
        stale["data_status"] = {
            "daily": "verified",
            "is_final": True,
            "latest_date": "2026-08-19",
        }
        unverified = _item("688041")
        unverified.pop("closes")
        unverified["close"] = 201.5
        unverified["data_status"] = {
            "daily": "estimated",
            "is_final": True,
            "latest_date": "2026-08-20",
        }

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("daily_fusion", "fusion-v1", [verified, stale, unverified])],
        )
        by_code = {entry["code"]: entry for entry in entries}
        self.assertEqual(by_code["300308"]["reference_close"], 191.5)
        self.assertEqual(
            by_code["300308"]["reference_close_source"],
            "top_level_close",
        )
        self.assertIsNone(by_code["300139"]["reference_close"])
        self.assertEqual(by_code["300139"]["reference_close_source"], "missing")
        self.assertIsNone(by_code["688041"]["reference_close"])
        self.assertEqual(by_code["688041"]["reference_close_source"], "missing")

    def test_closes_reference_requires_signal_date_and_verified_final_status(self):
        valid = _item("300308")
        stale_date = _item("300139")
        stale_date["dates"][-1] = "2026-08-19"
        nonfinal = _item("688041")
        nonfinal["data_status"]["is_final"] = False
        unverified = _item("000001")
        unverified["data_status"]["daily"] = "estimated"

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [_strategy("daily_fusion", "fusion-v1", [
                valid, stale_date, nonfinal, unverified,
            ])],
        )
        by_code = {entry["code"]: entry for entry in entries}
        self.assertEqual(by_code["300308"]["reference_close"], 188.0)
        self.assertIsNone(by_code["300139"]["reference_close"])
        self.assertIsNone(by_code["688041"]["reference_close"])
        self.assertIsNone(by_code["000001"]["reference_close"])

    def test_explicit_invalid_or_conflicting_role_is_not_legacy_corrected(self):
        invalid = _strategy(
            "daily_pure", "pure-v1", [_item("300139")],
            evaluation_role="unknown",
        )
        conflict = _strategy(
            "daily_pure", "pure-v1", [_item("688041")],
            evaluation_role="formal",
        )
        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [invalid, conflict],
        )
        by_code = {entry["code"]: entry for entry in entries}
        for code in ("300139", "688041"):
            contribution = by_code[code]["strategy_contributions"][0]
            self.assertEqual(contribution["evaluation_role"], "unknown")
            self.assertFalse(contribution["evaluation_eligible"])

    def test_invalid_role_fails_closed_and_surface_cannot_cross_role(self):
        invalid = _strategy(
            "daily_fusion",
            "fusion-v1",
            [_item()],
            evaluation_role="not-a-role",
            publication_surface="formal_recommendation",
        )
        mismatched = _strategy(
            "daily_pure",
            "pure-v1",
            [_item("300139")],
            evaluation_role="baseline",
            publication_surface="formal_recommendation",
        )

        entries = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [invalid, mismatched],
        )
        by_strategy = {
            row["strategy_name"]: row
            for entry in entries
            for row in entry["strategy_contributions"]
        }
        self.assertEqual(by_strategy["daily_fusion"]["evaluation_role"], "unknown")
        self.assertEqual(
            by_strategy["daily_fusion"]["publication_surface"],
            "technical_detail",
        )
        self.assertFalse(by_strategy["daily_fusion"]["evaluation_eligible"])
        self.assertEqual(
            by_strategy["daily_pure"]["publication_surface"],
            "baseline_candidates",
        )

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
