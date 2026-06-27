import unittest

import inspect

import chanlun.chan_engine as ce
from chanlun.chan_engine import analyze, compare_chan_results
from chanlun.engine_candidate import (
    CANDIDATE_ANALYZERS,
    all_candidate_provider_bundle,
    analyze_with_all_candidate_components,
    candidate_provider_bundle,
)
from chanlun.engine_pipeline import (
    EngineProviders,
    LEGACY_PROVIDERS,
    analyze_with_provider_bundle,
    with_provider_overrides,
)
import chanlun.engine_pipeline as pipeline
from tests.test_chan_engine_candidate_macd import _make_kline
from tests.test_chan_engine_snapshot import SCENARIOS


EXPECTED_CANDIDATE_KEYS = [
    "macd",
    "inclusion",
    "fractal",
    "stroke",
    "segment",
    "pivot",
    "trend",
    "divergence",
    "signal",
    "all",
]

PROVIDER_FIELDS = [
    "macd_provider",
    "inclusion_provider",
    "fractal_provider",
    "stroke_provider",
    "segment_provider",
    "pivot_provider",
    "trend_provider",
    "divergence_provider",
    "signal_provider",
]


def _provider_names(providers):
    return {field: getattr(providers, field).__name__ for field in PROVIDER_FIELDS}


class ChanEngineProviderRegistryTests(unittest.TestCase):
    def test_public_analyze_uses_legacy_provider_bundle(self):
        source = inspect.getsource(ce.analyze)
        self.assertIn("analyze_with_provider_bundle", source)
        self.assertIn("LEGACY_PROVIDERS", source)

    def test_legacy_provider_bundle_matches_public_analyze(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                kwargs = {
                    "code": name,
                    "name": name,
                    "dates": kline["dates"],
                    "opens": kline["opens"],
                    "highs": kline["highs"],
                    "lows": kline["lows"],
                    "closes": kline["closes"],
                    "volumes": kline["volumes"],
                }

                legacy = analyze(**kwargs)
                bundled = analyze_with_provider_bundle(**kwargs, providers=LEGACY_PROVIDERS)

                comparison = compare_chan_results(legacy, bundled)
                self.assertTrue(comparison["equal"], comparison)

    def test_all_candidate_provider_bundle_uses_expected_candidates(self):
        providers = all_candidate_provider_bundle()
        self.assertIsInstance(providers, EngineProviders)
        self.assertEqual(providers.macd_provider.__name__, "calc_macd_candidate")
        self.assertEqual(providers.inclusion_provider.__name__, "inclusion_process_candidate")
        self.assertEqual(providers.fractal_provider.__name__, "find_fractals_candidate")
        self.assertEqual(providers.stroke_provider.__name__, "build_strokes_candidate")
        self.assertEqual(providers.segment_provider.__name__, "build_segments_candidate")
        self.assertEqual(providers.pivot_provider.__name__, "find_pivots_candidate")
        self.assertEqual(providers.trend_provider.__name__, "classify_trend_candidate")
        self.assertEqual(providers.divergence_provider.__name__, "check_divergence_candidate")
        self.assertEqual(providers.signal_provider.__name__, "locate_buy_sell_points_candidate")

    def test_candidate_analyzer_registry_has_stable_keys(self):
        self.assertEqual(list(CANDIDATE_ANALYZERS), EXPECTED_CANDIDATE_KEYS)
        self.assertNotIn("legacy", CANDIDATE_ANALYZERS)
        for analyzer in CANDIDATE_ANALYZERS.values():
            self.assertTrue(callable(analyzer))
        self.assertIs(CANDIDATE_ANALYZERS["all"], analyze_with_all_candidate_components)

    def test_with_provider_overrides_returns_new_bundle(self):
        providers = with_provider_overrides(LEGACY_PROVIDERS, macd_provider=lambda closes: closes)
        self.assertIsInstance(providers, EngineProviders)
        self.assertIsNot(providers, LEGACY_PROVIDERS)
        self.assertIsNot(providers.macd_provider, LEGACY_PROVIDERS.macd_provider)
        self.assertIs(providers.inclusion_provider, LEGACY_PROVIDERS.inclusion_provider)

    def test_single_candidate_provider_bundles_override_only_their_component(self):
        expected = {
            "macd": {"macd_provider": "calc_macd_candidate"},
            "inclusion": {"inclusion_provider": "inclusion_process_candidate"},
            "fractal": {"fractal_provider": "find_fractals_candidate"},
            "stroke": {"stroke_provider": "build_strokes_candidate"},
            "segment": {"segment_provider": "build_segments_candidate"},
            "pivot": {"pivot_provider": "find_pivots_candidate"},
            "trend": {"trend_provider": "classify_trend_candidate"},
            "divergence": {"divergence_provider": "check_divergence_candidate"},
            "signal": {"signal_provider": "locate_buy_sell_points_candidate"},
        }
        legacy_names = _provider_names(LEGACY_PROVIDERS)

        for candidate_name, expected_overrides in expected.items():
            with self.subTest(candidate_name=candidate_name):
                providers = candidate_provider_bundle(candidate_name)
                names = _provider_names(providers)
                for field in PROVIDER_FIELDS:
                    expected_name = expected_overrides.get(field, legacy_names[field])
                    self.assertEqual(names[field], expected_name)

    def test_unknown_candidate_provider_bundle_is_rejected(self):
        with self.assertRaises(ValueError):
            candidate_provider_bundle("missing")

    def test_pipeline_provider_entrypoints_are_bundle_based(self):
        self.assertTrue(callable(pipeline.analyze_with_provider_bundle))
        self.assertTrue(callable(pipeline.analyze_with_providers))
        for provider in ("macd", "inclusion", "fractal", "stroke", "pivot", "segment", "trend", "divergence"):
            name = f"analyze_with_{provider}_provider"
            self.assertFalse(hasattr(pipeline, name), name)


if __name__ == "__main__":
    unittest.main()
