import inspect
import unittest

import run
import chanlun.chan_engine as ce
import chanlun.engine_candidate as candidate


class ChanEngineCandidateGuardrailTests(unittest.TestCase):
    def test_run_py_does_not_reference_candidate_module(self):
        source = inspect.getsource(run)
        self.assertNotIn("engine_candidate", source)
        self.assertNotIn("analyze_with_candidate_macd", source)

    def test_legacy_analyze_does_not_reference_candidate_module(self):
        source = inspect.getsource(ce.analyze)
        self.assertNotIn("calc_macd_candidate", source)
        self.assertNotIn("analyze_with_candidate_macd", source)

    def test_candidate_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_macd))
        self.assertNotIn("analyze_with_candidate_macd", ce.__all__)

    def test_candidate_macd_does_not_call_legacy_calc_macd(self):
        source = inspect.getsource(candidate.calc_macd_candidate)
        self.assertNotIn("calc_macd(", source)

    def test_candidate_inclusion_does_not_call_legacy_inclusion(self):
        source = inspect.getsource(candidate.inclusion_process_candidate)
        self.assertNotIn("inclusion_process(", source)

    def test_candidate_inclusion_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_inclusion))
        self.assertNotIn("analyze_with_candidate_inclusion", ce.__all__)

    def test_candidate_fractal_does_not_call_legacy_find_fractals(self):
        source = inspect.getsource(candidate.find_fractals_candidate)
        self.assertNotIn("find_fractals(", source)

    def test_candidate_fractal_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_fractal))
        self.assertNotIn("analyze_with_candidate_fractal", ce.__all__)

    def test_candidate_stroke_does_not_call_legacy_build_strokes(self):
        source = inspect.getsource(candidate.build_strokes_candidate)
        self.assertNotIn("build_strokes(", source)

    def test_candidate_stroke_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_stroke))
        self.assertNotIn("analyze_with_candidate_stroke", ce.__all__)

    def test_candidate_pivot_does_not_call_legacy_find_pivots(self):
        source = inspect.getsource(candidate.find_pivots_candidate)
        self.assertNotIn("find_pivots(", source)

    def test_candidate_pivot_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_pivot))
        self.assertNotIn("analyze_with_candidate_pivot", ce.__all__)

    def test_candidate_trend_does_not_call_legacy_classify_trend(self):
        source = inspect.getsource(candidate.classify_trend_candidate)
        self.assertNotIn("classify_trend(", source)

    def test_candidate_trend_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_trend))
        self.assertNotIn("analyze_with_candidate_trend", ce.__all__)

    def test_candidate_divergence_does_not_call_legacy_check_divergence(self):
        source = inspect.getsource(candidate.check_divergence_candidate)
        self.assertNotIn("check_divergence(", source)

    def test_candidate_divergence_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_divergence))
        self.assertNotIn("analyze_with_candidate_divergence", ce.__all__)

    def test_candidate_signal_does_not_call_legacy_signal_locator(self):
        source = inspect.getsource(candidate.locate_buy_sell_points_candidate)
        self.assertNotIn("locate_buy_sell_points(", source)

    def test_candidate_signal_helpers_do_not_call_legacy_signal_helpers(self):
        for fn in (
            candidate._detect_swing_divergence_ref_candidate,
            candidate._find_second_buy_point_candidate,
            candidate._find_third_buy_point_candidate,
            candidate._find_pivot_buy_points_candidate,
            candidate._segment_extreme_index_candidate,
        ):
            source = inspect.getsource(fn)
            self.assertNotIn("_detect_swing_divergence_ref(", source)
            self.assertNotIn("_find_second_buy_point(", source)
            self.assertNotIn("_find_third_buy_point(", source)
            self.assertNotIn("_find_pivot_buy_points(", source)
            self.assertNotIn("_segment_extreme_index(", source)

    def test_candidate_signal_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_signal))
        self.assertNotIn("analyze_with_candidate_signal", ce.__all__)

    def test_candidate_registry_is_not_public_chan_engine_export(self):
        self.assertTrue(candidate.CANDIDATE_ANALYZERS)
        self.assertNotIn("CANDIDATE_ANALYZERS", ce.__all__)
        self.assertNotIn("all_candidate_provider_bundle", ce.__all__)

    def test_candidate_signal_uses_pipeline_signal_provider(self):
        self.assertIn(
            "signal_provider",
            inspect.getsource(candidate.analyze_with_candidate_signal),
        )

    def test_candidate_segment_builders_do_not_call_legacy_segment_builders(self):
        for fn in (
            candidate.build_segments_by_break_candidate,
            candidate.build_segments_fixed_window_candidate,
            candidate.build_segments_candidate,
        ):
            source = inspect.getsource(fn)
            self.assertNotIn("build_segments_by_break(strokes", source)
            self.assertNotIn("build_segments_fixed_window(strokes", source)

    def test_candidate_segment_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_candidate_segment))
        self.assertNotIn("analyze_with_candidate_segment", ce.__all__)

    def test_legacy_and_candidate_share_pipeline_helper(self):
        self.assertIn("analyze_with_macd_provider", inspect.getsource(ce.analyze))
        self.assertIn(
            "analyze_with_macd_provider",
            inspect.getsource(candidate.analyze_with_candidate_macd),
        )

    def test_candidate_pivot_uses_pipeline_pivot_provider(self):
        self.assertIn(
            "pivot_provider",
            inspect.getsource(candidate.analyze_with_candidate_pivot),
        )

    def test_candidate_trend_uses_pipeline_trend_provider(self):
        self.assertIn(
            "trend_provider",
            inspect.getsource(candidate.analyze_with_candidate_trend),
        )

    def test_candidate_divergence_uses_pipeline_divergence_provider(self):
        self.assertIn(
            "divergence_provider",
            inspect.getsource(candidate.analyze_with_candidate_divergence),
        )

    def test_all_candidate_analyzer_is_not_public_chan_engine_export(self):
        self.assertTrue(callable(candidate.analyze_with_all_candidate_components))
        self.assertNotIn("analyze_with_all_candidate_components", ce.__all__)

    def test_all_candidate_provider_bundle_uses_all_candidate_providers(self):
        source = inspect.getsource(candidate.all_candidate_provider_bundle)
        for provider_name in (
            "calc_macd_candidate",
            "inclusion_process_candidate",
            "find_fractals_candidate",
            "build_strokes_candidate",
            "build_segments_candidate",
            "find_pivots_candidate",
            "classify_trend_candidate",
            "check_divergence_candidate",
            "locate_buy_sell_points_candidate",
        ):
            self.assertIn(provider_name, source)
