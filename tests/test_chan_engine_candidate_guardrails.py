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
