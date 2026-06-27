import unittest

import numpy as np

from chanlun.chan_engine import analyze_dual, build_strokes, find_fractals, inclusion_process
from chanlun.engine_candidate import (
    analyze_with_candidate_stroke,
    build_strokes_candidate,
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


def _serialize_strokes(strokes):
    return [
        {
            "start_idx": s.start_idx,
            "end_idx": s.end_idx,
            "start_price": round(float(s.start_price), 8),
            "end_price": round(float(s.end_price), 8),
            "direction": s.direction,
            "start_fractal": {
                "type": s.start_fractal.type,
                "index": s.start_fractal.index,
                "price": round(float(s.start_fractal.price), 8),
                "klines": list(s.start_fractal.klines),
            },
            "end_fractal": {
                "type": s.end_fractal.type,
                "index": s.end_fractal.index,
                "price": round(float(s.end_fractal.price), 8),
                "klines": list(s.end_fractal.klines),
            },
        }
        for s in strokes
    ]


class ChanEngineCandidateStrokeTests(unittest.TestCase):
    def test_candidate_strokes_match_legacy_strokes(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                merged_high, merged_low, idx_map = inclusion_process(
                    kline["highs"],
                    kline["lows"],
                )
                fractals = find_fractals(
                    merged_high,
                    merged_low,
                    idx_map,
                    kline["dates"],
                )
                legacy = build_strokes(fractals, merged_high, merged_low)
                candidate = build_strokes_candidate(fractals, merged_high, merged_low)
                self.assertEqual(
                    _serialize_strokes(candidate),
                    _serialize_strokes(legacy),
                )

    def test_candidate_stroke_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_stroke,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
