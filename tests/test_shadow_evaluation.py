import unittest

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


if __name__ == "__main__":
    unittest.main()
