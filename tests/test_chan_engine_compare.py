import copy
import json
import unittest

import numpy as np

from chanlun.chan_engine import analyze
from chanlun.engine_compare import compare_chan_results, serialize_chan_result


def analyze_closes(closes):
    closes = np.asarray(closes, dtype=float)
    return analyze(
        code="TEST",
        name="TEST",
        dates=list(range(len(closes))),
        opens=closes.copy(),
        highs=closes + 0.6,
        lows=closes - 0.6,
        closes=closes,
        volumes=np.array([1000.0] * len(closes), dtype=float),
    )


class ChanEngineCompareTests(unittest.TestCase):
    def test_serialize_chan_result_is_json_compatible(self):
        result = analyze_closes([10, 11, 12, 11, 10, 9, 10, 11, 12, 13] * 8)
        payload = serialize_chan_result(result)
        json.dumps(payload, ensure_ascii=False)
        self.assertIn("counts", payload)
        self.assertIn("trend_type", payload)
        self.assertIn("macd_tail", payload)

    def test_compare_identical_results_is_equal(self):
        result = analyze_closes([10, 11, 12, 11, 10, 9, 10, 11, 12, 13] * 8)
        comparison = compare_chan_results(result, result)
        self.assertTrue(comparison["equal"])
        self.assertEqual(comparison["summary"]["difference_count"], 0)
        self.assertEqual(comparison["differences"], [])

    def test_compare_detects_changed_trend_type(self):
        legacy = analyze_closes([10, 11, 12, 11, 10, 9, 10, 11, 12, 13] * 8)
        candidate = copy.deepcopy(legacy)
        candidate.trend_type = "TEST_CHANGED"
        comparison = compare_chan_results(legacy, candidate)
        self.assertFalse(comparison["equal"])
        self.assertIn("trend_type", comparison["summary"]["changed_fields"])
        self.assertGreaterEqual(comparison["summary"]["difference_count"], 1)

    def test_compare_handles_none_result(self):
        legacy = analyze_closes([10, 11, 12, 11, 10, 9, 10, 11, 12, 13] * 8)
        comparison = compare_chan_results(legacy, None)
        self.assertFalse(comparison["equal"])
        self.assertIn("result", comparison["summary"]["changed_fields"])


if __name__ == "__main__":
    unittest.main()
