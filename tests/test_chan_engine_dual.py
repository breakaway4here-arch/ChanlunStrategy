import json
import unittest

import numpy as np

from chanlun.chan_engine import analyze, analyze_dual


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


class ChanEngineDualTests(unittest.TestCase):
    def test_analyze_dual_default_candidate_matches_legacy(self):
        kline = make_kline()
        payload = analyze_dual(**kline)
        self.assertIsNotNone(payload["legacy"])
        self.assertIsNotNone(payload["candidate"])
        self.assertTrue(payload["comparison"]["equal"])
        json.dumps(payload["comparison"], ensure_ascii=False)

    def test_analyze_dual_accepts_candidate_analyzer(self):
        kline = make_kline()

        def candidate_analyzer(**kwargs):
            result = analyze(**kwargs)
            result.trend_type = "TEST_CHANGED"
            return result

        payload = analyze_dual(candidate_analyzer=candidate_analyzer, **kline)
        self.assertFalse(payload["comparison"]["equal"])
        self.assertIn("trend_type", payload["comparison"]["summary"]["changed_fields"])

    def test_analyze_signature_remains_legacy_shape(self):
        kline = make_kline()
        result = analyze(
            kline["code"],
            kline["name"],
            kline["dates"],
            kline["opens"],
            kline["highs"],
            kline["lows"],
            kline["closes"],
            kline["volumes"],
        )
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
