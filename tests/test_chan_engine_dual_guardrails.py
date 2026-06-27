import inspect
import unittest

import run
import chanlun.chan_engine as ce


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


if __name__ == "__main__":
    unittest.main()
