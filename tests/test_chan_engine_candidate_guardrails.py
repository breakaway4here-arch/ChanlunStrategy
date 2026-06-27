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

    def test_legacy_and_candidate_share_pipeline_helper(self):
        self.assertIn("analyze_with_macd_provider", inspect.getsource(ce.analyze))
        self.assertIn(
            "analyze_with_macd_provider",
            inspect.getsource(candidate.analyze_with_candidate_macd),
        )
