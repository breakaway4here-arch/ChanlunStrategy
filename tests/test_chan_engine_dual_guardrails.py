import inspect
import unittest
import numpy as np

import run
import chanlun.chan_engine as ce


def make_kline():
    closes = np.asarray([10, 11, 12, 11, 10, 9, 10, 11, 12, 13] * 8, dtype=float)
    return {
        "code": "TEST",
        "name": "TEST",
        "dates": list(range(len(closes))),
        "opens": closes.copy(),
        "highs": closes + 0.6,
        "lows": closes - 0.6,
        "closes": closes,
        "volumes": np.array([1000.0] * len(closes), dtype=float),
    }


class ChanEngineDualGuardrailTests(unittest.TestCase):
    def test_run_py_does_not_reference_analyze_dual(self):
        source = inspect.getsource(run)
        self.assertNotIn("analyze_dual", source)

    def test_analyze_signature_stays_legacy(self):
        signature = inspect.signature(ce.analyze)
        self.assertEqual(
            list(signature.parameters),
            ["code", "name", "dates", "opens", "highs", "lows", "closes", "volumes"],
        )

    def test_analyze_dual_requires_explicit_call(self):
        self.assertTrue(callable(ce.analyze_dual))
        self.assertNotEqual(ce.analyze, ce.analyze_dual)

    def test_analyze_dual_accepts_candidate_registry_names(self):
        kline = make_kline()
        for candidate_name in [
            "signal",
            "signal_v1",
            "signal_delay1_by_type_guard",
        ]:
            with self.subTest(candidate_name=candidate_name):
                payload = ce.analyze_dual(candidate=candidate_name, **kline)
                self.assertIn("legacy", payload)
                self.assertIn("candidate", payload)
                self.assertIn("comparison", payload)

    def test_analyze_dual_default_candidate_matches_legacy(self):
        kline = make_kline()
        payload = ce.analyze_dual(**kline)
        self.assertTrue(payload["comparison"]["equal"])

    def test_analyze_dual_rejects_mutually_exclusive_inputs(self):
        kline = make_kline()

        with self.assertRaisesRegex(
            ValueError, "^candidate and candidate_analyzer are mutually exclusive$"
        ):
            ce.analyze_dual(
                candidate="signal",
                candidate_analyzer=ce.analyze,
                **kline,
            )

    def test_analyze_dual_unknown_candidate_is_rejected(self):
        kline = make_kline()
        with self.assertRaisesRegex(ValueError, "^unknown candidate: missing$"):
            ce.analyze_dual(candidate="missing", **kline)


if __name__ == "__main__":
    unittest.main()
