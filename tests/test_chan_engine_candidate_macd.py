import unittest

import numpy as np

from chanlun.chan_engine import analyze_dual, calc_macd
from chanlun.engine_candidate import analyze_with_candidate_macd, calc_macd_candidate
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


class ChanEngineCandidateMacdTests(unittest.TestCase):
    def test_candidate_macd_matches_legacy_macd(self):
        closes = np.asarray(SCENARIOS["legacy_mixed"], dtype=float)
        legacy = calc_macd(closes)
        candidate = calc_macd_candidate(closes)
        for legacy_arr, candidate_arr in zip(legacy, candidate):
            np.testing.assert_allclose(candidate_arr, legacy_arr, equal_nan=True)

    def test_candidate_macd_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_macd,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
