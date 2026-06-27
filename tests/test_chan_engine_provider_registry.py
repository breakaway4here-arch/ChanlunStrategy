import unittest

import inspect

import chanlun.chan_engine as ce
from chanlun.chan_engine import analyze, compare_chan_results
from chanlun.engine_candidate import (
    CANDIDATE_ANALYZERS,
    all_candidate_provider_bundle,
    analyze_with_all_candidate_components,
)
from chanlun.engine_pipeline import LEGACY_PROVIDERS, EngineProviders, analyze_with_provider_bundle
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


if __name__ == "__main__":
    unittest.main()
