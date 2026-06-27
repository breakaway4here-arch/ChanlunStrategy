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
