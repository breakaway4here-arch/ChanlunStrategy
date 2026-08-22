import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import chanlun.shadow_evaluation as shadow_evaluation
from chanlun.engine_types import Fractal, Segment, Stroke

from chanlun.shadow_evaluation import (
    append_shadow_evaluation_entries,
    build_shadow_evaluation_entries,
    build_shadow_scorecards,
    clear_experiments,
    finalize_staged_shadow_evaluation_entries,
    get_experiment,
    list_experiments,
    load_shadow_evaluation_entries,
    production_digest,
    register_experiment,
    run_shadow_evaluations,
    shadow_pending_ledger_path,
    stage_shadow_evaluation_entries,
)


class ShadowEvaluationContractTests(unittest.TestCase):
    def setUp(self):
        clear_experiments()

    def tearDown(self):
        clear_experiments()

    def test_shadow_entries_have_independent_identity_and_never_join_formal_cohort(self):
        experiments = [{
            "experiment_id": "boom-close-v1",
            "version": "v1",
            "upstream_pool": "picks_pure",
            "source_pool": "next_day_boom_pool",
            "intended_horizon": 1,
            "entry_mode": "immediate_close",
            "status": "available",
            "today": {"candidates": [{
                "code": "300308",
                "name": "中际旭创",
                "closes": [99, 100],
                "best_buy_point": {"type": "三买", "reason": "回踩确认"},
                "decision_engine_v1": {"decision_code": "recommend"},
            }]},
        }]

        entries = build_shadow_evaluation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            experiments,
        )

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertTrue(entry["shadow_evaluation_id"].startswith("shadow:"))
        self.assertNotIn("recommendation_id", entry)
        self.assertNotIn("cohort_eligible", entry)
        self.assertEqual(entry["evaluation_role"], "shadow_candidate")
        self.assertFalse(entry["publication_effect"])
        self.assertTrue(entry["evaluation_eligible"])
        self.assertEqual(entry["experiment_id"], "boom-close-v1")
        self.assertEqual(entry["version"], "v1")
        self.assertEqual(entry["source_pool"], "next_day_boom_pool")
        self.assertEqual(entry["upstream_pool"], "picks_pure")
        self.assertEqual(entry["intended_horizon"], 1)
        self.assertEqual(entry["entry_mode"], "immediate_close")
        self.assertEqual(entry["reference_close"], 100.0)
        self.assertIn("best_buy_point", entry["reason_snapshot"])

    def test_shadow_pending_is_separate_idempotent_and_only_finalized_explicitly(self):
        entry = {
            "shadow_evaluation_id": "shadow:one",
            "evaluation_role": "shadow_candidate",
            "publication_effect": False,
            "evaluation_eligible": True,
            "report_date": "2026-08-20",
            "code": "300308",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_dir = Path(tmpdir) / "shadow-pending"
            pending = shadow_pending_ledger_path(
                "2026-08-20", pending_dir=pending_dir
            )
            ledger = Path(tmpdir) / "shadow-ledger.jsonl"

            self.assertEqual(stage_shadow_evaluation_entries(pending, [entry]), 1)
            self.assertFalse(ledger.exists())
            self.assertEqual(
                finalize_staged_shadow_evaluation_entries(pending, ledger), 1
            )
            self.assertEqual(
                finalize_staged_shadow_evaluation_entries(pending, ledger), 0
            )
            self.assertEqual(append_shadow_evaluation_entries(ledger, [entry]), 0)
            self.assertEqual(load_shadow_evaluation_entries(ledger), [entry])

    def test_shadow_scorecard_uses_only_evaluation_eligible_rows_and_primary_horizon(self):
        base = {
            "evaluation_role": "shadow_candidate",
            "publication_effect": False,
            "evaluation_eligible": True,
            "experiment_id": "h4-close-v1",
            "version": "v1",
            "display_name": "H4 收盘影子",
            "source_pool": "h4_t3_pool",
            "upstream_pool": "picks_pure",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "generated_at": "2026-08-20T15:10:00+08:00",
            "reason_snapshot": {"best_buy_point": {"type": "三买"}},
        }
        first = dict(base, shadow_evaluation_id="shadow:first",
                     report_date="2026-08-20", code="300308",
                     name="中际旭创", reference_close=100.0)
        ignored = dict(base, shadow_evaluation_id="shadow:ignored",
                       report_date="2026-08-20", code="300001",
                       name="特锐德", reference_close=100.0,
                       evaluation_eligible=False, cohort_eligible=True)
        dates = [
            "2026-08-20", "2026-08-21", "2026-08-24",
            "2026-08-25", "2026-08-26", "2026-08-27",
        ]
        kline = {
            "dates": dates,
            "opens": [100, 101, 103, 104, 106, 108],
            "closes": [100, 105, 98, 110, 107, 112],
            "highs": [150, 106, 104, 111, 109, 113],
            "lows": [50, 99, 96, 97, 105, 106],
            "volumes": [1000] * 6,
            "is_final": [True] * 6,
            "adjustment": "qfq",
        }

        cards = build_shadow_scorecards(
            [first, ignored],
            {"300308": kline, "300001": kline},
            trading_calendar=dates,
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["sample_size"], 1)
        self.assertEqual(card["active_dates"], 1)
        self.assertEqual(card["active_months"], 1)
        self.assertAlmostEqual(card["mean_close_return"], 10.0)
        self.assertAlmostEqual(card["median_close_return"], 10.0)
        self.assertAlmostEqual(card["up_rate"], 100.0)
        self.assertAlmostEqual(card["hit_rate_ge_5"], 100.0)
        self.assertAlmostEqual(card["mean_mfe"], 11.0)
        self.assertAlmostEqual(card["mean_mae"], -4.0)
        self.assertAlmostEqual(card["worst_close_return"], 10.0)
        self.assertFalse(card["promotion_eligible"])
        self.assertTrue(card["hard_gate_reasons"])
        self.assertEqual(
            card["representative_samples"][0]["shadow_evaluation_id"],
            "shadow:first",
        )

    def test_production_digest_is_stable_for_mapping_order(self):
        first = {
            "picks_fusion": [
                {"code": "600001", "decision": "recommend", "research_price": 10.2},
            ],
            "production": {"action": "buy", "reason": "结构确认"},
        }
        reordered = {
            "production": {"reason": "结构确认", "action": "buy"},
            "picks_fusion": [
                {"research_price": 10.2, "decision": "recommend", "code": "600001"},
            ],
        }

        self.assertEqual(production_digest(first), production_digest(reordered))
        self.assertNotEqual(
            production_digest(first),
            production_digest(
                {
                    **first,
                    "picks_fusion": [
                        {"code": "600002", "decision": "recommend", "research_price": 10.2}
                    ],
                }
            ),
        )

    def test_shadow_builder_receives_deep_copy_and_cannot_mutate_official_picks(self):
        official = [
            {
                "code": "600001",
                "decision": "recommend",
                "evidence": {"tags": ["底分型"]},
            }
        ]
        original = [
            {
                "code": "600001",
                "decision": "recommend",
                "evidence": {"tags": ["底分型"]},
            }
        ]
        seen = []

        def mutating_builder(candidates):
            seen.append(candidates is official)
            candidates[0]["decision"] = "reject"
            candidates[0]["evidence"]["tags"].append("shadow-only")
            return {"candidates": candidates}

        register_experiment(
            {
                "experiment_id": "mutating-v1",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 3,
                "entry_mode": "immediate_close",
                "builder": mutating_builder,
            }
        )

        result = run_shadow_evaluations(official)

        self.assertEqual(official, original)
        self.assertEqual(seen, [False])
        self.assertEqual(result["production_guard"]["unchanged"], True)
        self.assertEqual(result["production_guard"]["before_sha256"], result["production_guard"]["after_sha256"])
        self.assertEqual(result["experiments"][0]["status"], "available")

    def test_one_experiment_error_does_not_abort_other_experiments(self):
        official = [{"code": "600001", "decision": "recommend"}]

        def broken_builder(_candidates):
            raise RuntimeError("diagnostic failed")

        register_experiment(
            {
                "experiment_id": "broken-v1",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 1,
                "entry_mode": "immediate_close",
                "builder": broken_builder,
            }
        )
        register_experiment(
            {
                "experiment_id": "healthy-v1",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 5,
                "entry_mode": "immediate_close",
                "builder": lambda candidates: {"count": len(candidates)},
            }
        )

        result = run_shadow_evaluations(official)
        rows = {row["experiment_id"]: row for row in result["experiments"]}

        self.assertEqual(result["mode"], "shadow")
        self.assertFalse(result["affects_production"])
        self.assertEqual(rows["broken-v1"]["status"], "unavailable")
        self.assertIn("diagnostic failed", rows["broken-v1"]["error"])
        self.assertEqual(rows["healthy-v1"]["status"], "available")
        self.assertFalse(rows["healthy-v1"]["affects_production"])

    def test_registry_rejects_incomplete_or_non_close_specs(self):
        base = {
            "experiment_id": "candidate",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "builder": lambda candidates: candidates,
        }

        for key, value in (
            ("version", None),
            ("source_pool", None),
            ("intended_horizon", 2),
            ("entry_mode", "delay1_open"),
        ):
            with self.subTest(key=key):
                invalid = dict(base)
                invalid[key] = value
                with self.assertRaises(ValueError):
                    register_experiment(invalid)

    def test_registry_requires_explicit_version_and_both_pool_fields(self):
        base = {
            "experiment_id": "candidate",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "builder": lambda candidates: candidates,
        }
        invalid_specs = []

        missing_version = dict(base)
        missing_version.pop("version")
        invalid_specs.append(missing_version)

        missing_upstream = dict(base)
        missing_upstream.pop("upstream_pool")
        invalid_specs.append(missing_upstream)

        missing_source = dict(base)
        missing_source.pop("source_pool")
        invalid_specs.append(missing_source)

        strategy_version_alias = dict(base)
        strategy_version_alias.pop("version")
        strategy_version_alias["strategy_version"] = "v1"
        invalid_specs.append(strategy_version_alias)

        pool_alias = dict(base)
        pool_alias.pop("upstream_pool")
        pool_alias.pop("source_pool")
        pool_alias["pool"] = "picks_fusion"
        invalid_specs.append(pool_alias)

        for invalid in invalid_specs:
            with self.subTest(spec=invalid):
                with self.assertRaises(ValueError):
                    register_experiment(invalid)

    def test_registry_rejects_non_integer_or_unhashable_horizons_with_value_error(self):
        base = {
            "experiment_id": "candidate",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "builder": lambda candidates: candidates,
        }
        for horizon in (1.5, [], {}):
            with self.subTest(horizon=horizon):
                invalid = dict(base)
                invalid["intended_horizon"] = horizon
                with self.assertRaises(ValueError):
                    register_experiment(invalid)

    def test_registry_is_private_and_get_returns_a_defensive_copy(self):
        self.assertFalse(hasattr(shadow_evaluation, "EXPERIMENT_REGISTRY"))
        register_experiment(
            {
                "experiment_id": "candidate",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 3,
                "entry_mode": "immediate_close",
                "builder": lambda candidates: candidates,
            }
        )

        exposed = get_experiment("candidate")
        exposed["version"] = "tampered"
        exposed["metadata"] = {"mutated": True}

        self.assertEqual(list_experiments(), ["candidate"])
        self.assertEqual(get_experiment("candidate")["version"], "v1")
        self.assertNotIn("metadata", get_experiment("candidate"))

    def test_mapping_of_experiment_ids_is_rejected_fail_closed(self):
        spec = {
            "experiment_id": "candidate",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "builder": lambda candidates: candidates,
        }

        with self.assertRaises(ValueError):
            run_shadow_evaluations(
                [{"code": "600001"}],
                experiments={"candidate": spec},
            )

    def test_invalid_inline_spec_isolated_from_other_experiments(self):
        valid = {
            "experiment_id": "healthy-v1",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "builder": lambda candidates: {"count": len(candidates)},
        }
        invalid = dict(valid)
        invalid["experiment_id"] = "invalid-v1"
        invalid.pop("version")

        result = run_shadow_evaluations(
            [{"code": "600001"}],
            experiments=[invalid, valid],
        )
        rows = {row["experiment_id"]: row for row in result["experiments"]}

        self.assertEqual(rows["invalid-v1"]["status"], "unavailable")
        self.assertIn("version", rows["invalid-v1"]["error"])
        self.assertEqual(rows["healthy-v1"]["status"], "available")

    def test_top_level_inline_spec_validation_isolated_as_one_error_row(self):
        result = run_shadow_evaluations(
            [{"code": "600001"}],
            experiments={
                "experiment_id": "invalid-v1",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 3,
                "entry_mode": "immediate_close",
            },
        )

        self.assertEqual(len(result["experiments"]), 1)
        self.assertEqual(result["experiments"][0]["experiment_id"], "invalid-v1")
        self.assertEqual(result["experiments"][0]["status"], "unavailable")

    def test_production_digest_rejects_non_string_keys_and_key_collisions(self):
        with self.assertRaises(ValueError):
            production_digest({1: "numeric key"})
        with self.assertRaises(ValueError):
            production_digest({1: "numeric", "1": "string"})

    def test_production_digest_rejects_non_json_safe_values(self):
        unsupported_values = (
            {"value": object()},
            {"value": b"bytes"},
            {"value": {"set-item"}},
            {"value": float("nan")},
            {"value": float("inf")},
        )
        for value in unsupported_values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    production_digest(value)

    def test_numpy_pool_is_projected_for_shadow_without_mutating_official_arrays(self):
        raw_pool = {
            "picks_fusion": [
                {
                    "code": "600001",
                    "closes": np.array([10.0, 10.5]),
                    "score": np.float64(8.5),
                    "volume": np.int64(100),
                }
            ]
        }
        original_closes = raw_pool["picks_fusion"][0]["closes"].copy()
        captured = []

        def mutating_builder(candidates):
            captured.append(candidates)
            candidates["picks_fusion"][0]["closes"].append(99.0)
            return {"count": 1}

        register_experiment(
            {
                "experiment_id": "numpy-v1",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 3,
                "entry_mode": "immediate_close",
                "builder": mutating_builder,
            }
        )

        result = run_shadow_evaluations(raw_pool)

        self.assertEqual(result["experiments"][0]["status"], "available")
        projected_pick = captured[0]["picks_fusion"][0]
        self.assertIsInstance(projected_pick["closes"], list)
        self.assertIsInstance(projected_pick["score"], float)
        self.assertIsInstance(projected_pick["volume"], int)
        self.assertTrue(np.array_equal(raw_pool["picks_fusion"][0]["closes"], original_closes))
        self.assertEqual(result["production_guard"]["unchanged"], True)

    def test_error_row_drops_uncopyable_metadata_and_keeps_other_experiments_running(self):
        class Uncopyable:
            def __deepcopy__(self, memo):
                raise RuntimeError("metadata must not be copied")

        invalid = {
            "experiment_id": "bad-metadata-v1",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "delay1_open",
            "builder": lambda candidates: candidates,
            "metadata": Uncopyable(),
        }
        healthy = {
            "experiment_id": "healthy-v1",
            "version": "v1",
            "upstream_pool": "picks_fusion",
            "source_pool": "picks_fusion",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "builder": lambda candidates: {"count": len(candidates)},
        }

        result = run_shadow_evaluations(
            [{"code": "600001"}],
            experiments=[invalid, healthy],
        )
        rows = {row["experiment_id"]: row for row in result["experiments"]}

        self.assertEqual(rows["bad-metadata-v1"]["status"], "unavailable")
        self.assertNotIn("metadata", rows["bad-metadata-v1"])
        self.assertEqual(rows["healthy-v1"]["status"], "available")

    def test_engine_dataclasses_and_tuples_are_projected_without_mutating_official_rows(self):
        fractal = Fractal(type="bottom", index=1, price=10.0, klines=[1, 2, 3])
        stroke = Stroke(
            start_idx=1,
            end_idx=3,
            start_price=10.0,
            end_price=11.0,
            direction="up",
            start_fractal=fractal,
            end_fractal=None,
        )
        segment = Segment(
            strokes=[stroke],
            start_idx=1,
            end_idx=3,
            direction="up",
            high=11.0,
            low=9.5,
        )
        raw_pool = {
            "picks_fusion": [
                {
                    "code": "600001",
                    "fractals": [fractal],
                    "strokes": (stroke,),
                    "segments": [segment],
                    "divergence": ("bottom", 0.4),
                    "closes": np.array([10.0, 10.5]),
                }
            ]
        }
        captured = []

        def builder(candidates):
            captured.append(candidates)
            candidates["picks_fusion"][0]["fractals"][0]["price"] = 99.0
            candidates["picks_fusion"][0]["divergence"].append("shadow-only")
            return {"count": 1}

        register_experiment(
            {
                "experiment_id": "engine-types-v1",
                "version": "v1",
                "upstream_pool": "picks_fusion",
                "source_pool": "picks_fusion",
                "intended_horizon": 3,
                "entry_mode": "immediate_close",
                "builder": builder,
            }
        )

        result = run_shadow_evaluations(raw_pool)

        self.assertEqual(result["experiments"][0]["status"], "available")
        projected_pick = captured[0]["picks_fusion"][0]
        self.assertIsInstance(projected_pick["fractals"][0], dict)
        self.assertIsInstance(projected_pick["strokes"], list)
        self.assertIsInstance(projected_pick["strokes"][0], dict)
        self.assertIsInstance(projected_pick["segments"][0], dict)
        self.assertIsInstance(projected_pick["divergence"], list)
        self.assertIsInstance(projected_pick["closes"], list)
        self.assertEqual(fractal.price, 10.0)
        self.assertEqual(fractal.klines, [1, 2, 3])
        self.assertEqual(raw_pool["picks_fusion"][0]["divergence"], ("bottom", 0.4))
        self.assertEqual(result["production_guard"]["unchanged"], True)


if __name__ == "__main__":
    unittest.main()
