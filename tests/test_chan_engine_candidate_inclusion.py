import unittest

import numpy as np

from chanlun.chan_engine import analyze_dual, inclusion_process
from chanlun.engine_candidate import (
    analyze_with_candidate_inclusion,
    inclusion_process_candidate,
)
from tests.test_chan_engine_snapshot import SCENARIOS


def _make_kline(closes):
    closes = np.asarray(closes, dtype=float)
    return {
        "dates": list(range(len(closes))),
        "opens": closes.copy(),
        "highs": closes + 0.6,
        "lows": closes - 0.6,
        "closes": closes,
        "volumes": np.array([1000.0] * len(closes), dtype=float),
    }


class ChanEngineCandidateInclusionTests(unittest.TestCase):
    def test_candidate_inclusion_matches_legacy_inclusion(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                legacy_high, legacy_low, legacy_idx = inclusion_process(
                    kline["highs"],
                    kline["lows"],
                )
                candidate_high, candidate_low, candidate_idx = inclusion_process_candidate(
                    kline["highs"],
                    kline["lows"],
                )
                np.testing.assert_allclose(
                    candidate_high,
                    legacy_high,
                    equal_nan=True,
                )
                np.testing.assert_allclose(candidate_low, legacy_low, equal_nan=True)
                self.assertEqual(candidate_idx, legacy_idx)

    def test_candidate_inclusion_analyzer_matches_legacy_dual_output(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                payload = analyze_dual(
                    code=name,
                    name=name,
                    dates=kline["dates"],
                    opens=kline["opens"],
                    highs=kline["highs"],
                    lows=kline["lows"],
                    closes=kline["closes"],
                    volumes=kline["volumes"],
                    candidate_analyzer=analyze_with_candidate_inclusion,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
