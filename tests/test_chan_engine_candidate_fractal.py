import unittest

import numpy as np

from chanlun.chan_engine import analyze_dual, find_fractals, inclusion_process
from chanlun.engine_candidate import (
    analyze_with_candidate_fractal,
    find_fractals_candidate,
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


def _serialize_fractals(fractals):
    return [
        {
            "type": f.type,
            "index": f.index,
            "price": round(float(f.price), 8),
            "klines": list(f.klines),
        }
        for f in fractals
    ]


class ChanEngineCandidateFractalTests(unittest.TestCase):
    def test_candidate_fractals_match_legacy_fractals(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                merged_high, merged_low, idx_map = inclusion_process(
                    kline["highs"],
                    kline["lows"],
                )
                legacy = find_fractals(
                    merged_high,
                    merged_low,
                    idx_map,
                    kline["dates"],
                )
                candidate = find_fractals_candidate(
                    merged_high,
                    merged_low,
                    idx_map,
                    kline["dates"],
                )
                self.assertEqual(
                    _serialize_fractals(candidate),
                    _serialize_fractals(legacy),
                )

    def test_candidate_fractal_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_fractal,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
