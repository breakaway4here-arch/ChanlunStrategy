import unittest

import numpy as np

import chanlun.shadow_evaluation as shadow_evaluation

from chanlun.shadow_evaluation import (
    clear_experiments,
    get_experiment,
    list_experiments,
    production_digest,
    register_experiment,
    run_shadow_evaluations,
)


class ShadowEvaluationContractTests(unittest.TestCase):
    def setUp(self):
        clear_experiments()

    def tearDown(self):
        clear_experiments()

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
            {"value": ("tuple",)},
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


if __name__ == "__main__":
    unittest.main()
