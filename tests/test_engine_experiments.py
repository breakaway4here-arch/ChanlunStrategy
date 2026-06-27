import unittest

from chanlun.engine_experiments import (
    build_experiment_provider_bundle,
    get_experiment,
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

    def test_unknown_experiment_raises(self):
        with self.assertRaises(ValueError):
            build_experiment_provider_bundle("missing")

    def test_legacy_not_mutated(self):
        providers = build_experiment_provider_bundle("legacy")
        self.assertIs(providers, LEGACY_PROVIDERS)


if __name__ == "__main__":
    unittest.main()
