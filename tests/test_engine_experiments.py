import unittest

from chanlun.engine_experiments import (
    build_experiment_provider_bundle,
    get_experiment,
    list_experiments,
)
from chanlun.engine_pipeline import EngineProviders, LEGACY_PROVIDERS


class EngineExperimentTests(unittest.TestCase):
    def test_get_experiment_legacy(self):
        exp = get_experiment("legacy")
        self.assertEqual(exp.name, "legacy")
        self.assertEqual(exp.module, "legacy")
        self.assertEqual(exp.overrides, {})

    def test_get_experiment_signal_v1(self):
        exp = get_experiment("signal_v1")
        self.assertEqual(exp.module, "signal")
        self.assertTrue(exp.overrides)
        self.assertIn("signal_provider", exp.overrides)
        self.assertEqual(exp.overrides["signal_provider"].__name__, "locate_buy_sell_points_candidate")

    def test_get_experiment_by_module_names(self):
        self.assertEqual(get_experiment("macd_v1").module, "macd")
        self.assertEqual(get_experiment("inclusion_v1").module, "inclusion")
        self.assertEqual(get_experiment("fractal_v1").module, "fractal")
        self.assertEqual(get_experiment("all_v1").module, "all")

    def test_build_experiment_provider_bundle_signal_v1(self):
        providers = build_experiment_provider_bundle("signal_v1")
        self.assertIsInstance(providers, EngineProviders)
        self.assertEqual(
            providers.signal_provider.__name__,
            "locate_buy_sell_points_candidate",
        )

    def test_list_experiments_includes_signal_guards(self):
        experiments = set(list_experiments())
        self.assertIn("signal_p0_distance_guard", experiments)
        self.assertIn("signal_p1_confirmation_guard", experiments)
        self.assertIn("signal_p0_p1_guard", experiments)
        self.assertIn("signal_delay1_by_type_guard", experiments)

    def test_unknown_experiment_raises(self):
        with self.assertRaises(ValueError):
            build_experiment_provider_bundle("missing")

    def test_legacy_not_mutated(self):
        providers = build_experiment_provider_bundle("legacy")
        self.assertIs(providers, LEGACY_PROVIDERS)

    def test_build_experiment_provider_bundle_signal_p0_p1_guard_overrides_only_signal(self):
        providers = build_experiment_provider_bundle("signal_p0_p1_guard")
        self.assertIsInstance(providers, EngineProviders)
        self.assertEqual(
            providers.signal_provider.__name__,
            "locate_buy_sell_points_p0_p1_guard",
        )
        self.assertIs(providers.macd_provider, LEGACY_PROVIDERS.macd_provider)
        self.assertIs(providers.inclusion_provider, LEGACY_PROVIDERS.inclusion_provider)
        self.assertIs(providers.fractal_provider, LEGACY_PROVIDERS.fractal_provider)
        self.assertIs(providers.stroke_provider, LEGACY_PROVIDERS.stroke_provider)
        self.assertIs(providers.segment_provider, LEGACY_PROVIDERS.segment_provider)
        self.assertIs(providers.pivot_provider, LEGACY_PROVIDERS.pivot_provider)
        self.assertIs(providers.trend_provider, LEGACY_PROVIDERS.trend_provider)
        self.assertIs(providers.divergence_provider, LEGACY_PROVIDERS.divergence_provider)

    def test_build_experiment_provider_bundle_signal_delay1_by_type_guard_overrides_only_signal(self):
        providers = build_experiment_provider_bundle("signal_delay1_by_type_guard")
        self.assertIsInstance(providers, EngineProviders)
        self.assertEqual(
            providers.signal_provider.__name__,
            "locate_buy_sell_points_delay1_by_type_guard",
        )
        self.assertIs(providers.macd_provider, LEGACY_PROVIDERS.macd_provider)
        self.assertIs(providers.inclusion_provider, LEGACY_PROVIDERS.inclusion_provider)
        self.assertIs(providers.fractal_provider, LEGACY_PROVIDERS.fractal_provider)
        self.assertIs(providers.stroke_provider, LEGACY_PROVIDERS.stroke_provider)
        self.assertIs(providers.segment_provider, LEGACY_PROVIDERS.segment_provider)
        self.assertIs(providers.pivot_provider, LEGACY_PROVIDERS.pivot_provider)
        self.assertIs(providers.trend_provider, LEGACY_PROVIDERS.trend_provider)
        self.assertIs(providers.divergence_provider, LEGACY_PROVIDERS.divergence_provider)

    def test_signal_p0_p1_guard_risk_is_medium(self):
        exp = get_experiment("signal_p0_p1_guard")
        self.assertEqual(exp.risk, "medium")

    def test_signal_delay1_by_type_guard_risk_is_medium(self):
        exp = get_experiment("signal_delay1_by_type_guard")
        self.assertEqual(exp.risk, "medium")


if __name__ == "__main__":
    unittest.main()
