import unittest

import numpy as np

from config import USE_SEGMENT_BREAK_BUILDER
from chanlun.chan_engine import (
    analyze_dual,
    build_segments_by_break,
    build_segments_fixed_window,
    build_strokes,
    find_fractals,
    inclusion_process,
)
from chanlun.engine_candidate import (
    analyze_with_candidate_segment,
    build_segments_by_break_candidate,
    build_segments_candidate,
    build_segments_fixed_window_candidate,
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


def _serialize_segments(segments):
    return [
        {
            "start_idx": s.start_idx,
            "end_idx": s.end_idx,
            "direction": s.direction,
            "high": round(float(s.high), 8),
            "low": round(float(s.low), 8),
            "destroyed_by_idx": s.destroyed_by_idx,
            "confirmed": s.confirmed,
            "strokes": [
                {
                    "start_idx": st.start_idx,
                    "end_idx": st.end_idx,
                    "start_price": round(float(st.start_price), 8),
                    "end_price": round(float(st.end_price), 8),
                    "direction": st.direction,
                }
                for st in s.strokes
            ],
        }
        for s in segments
    ]


def _legacy_strokes(closes):
    kline = _make_kline(closes)
    merged_high, merged_low, idx_map = inclusion_process(kline["highs"], kline["lows"])
    fractals = find_fractals(merged_high, merged_low, idx_map, kline["dates"])
    return kline, build_strokes(fractals, merged_high, merged_low)


class ChanEngineCandidateSegmentTests(unittest.TestCase):
    def test_candidate_break_segments_match_legacy_break_segments(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                _, strokes = _legacy_strokes(closes)
                legacy = build_segments_by_break(strokes)
                candidate = build_segments_by_break_candidate(strokes)
                self.assertEqual(
                    _serialize_segments(candidate),
                    _serialize_segments(legacy),
                )

    def test_candidate_fixed_window_segments_match_legacy_fixed_window_segments(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                _, strokes = _legacy_strokes(closes)
                legacy = build_segments_fixed_window(strokes)
                candidate = build_segments_fixed_window_candidate(strokes)
                self.assertEqual(
                    _serialize_segments(candidate),
                    _serialize_segments(legacy),
                )

    def test_candidate_configured_segments_match_legacy_current_config(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                _, strokes = _legacy_strokes(closes)
                if USE_SEGMENT_BREAK_BUILDER:
                    legacy = build_segments_by_break(strokes)
                else:
                    legacy = build_segments_fixed_window(strokes)

                candidate = build_segments_candidate(strokes)
                self.assertEqual(
                    _serialize_segments(candidate),
                    _serialize_segments(legacy),
                )

    def test_candidate_segment_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_segment,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
