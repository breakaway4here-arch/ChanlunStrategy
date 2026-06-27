import unittest

import numpy as np

from config import USE_SEGMENT_BREAK_BUILDER
from chanlun.chan_engine import (
    analyze_dual,
    build_segments_by_break,
    build_segments_fixed_window,
    build_strokes,
    find_fractals,
    find_pivots,
    inclusion_process,
)
from chanlun.engine_candidate import analyze_with_candidate_pivot, find_pivots_candidate
from chanlun.engine_types import Segment
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


def _serialize_pivots(pivots):
    return [
        {
            "ZD": round(float(p.ZD), 8),
            "ZG": round(float(p.ZG), 8),
            "start_idx": p.start_idx,
            "end_idx": p.end_idx,
            "level": p.level,
            "segments": [
                {
                    "start_idx": s.start_idx,
                    "end_idx": s.end_idx,
                    "direction": s.direction,
                    "high": round(float(s.high), 8),
                    "low": round(float(s.low), 8),
                    "confirmed": s.confirmed,
                    "destroyed_by_idx": s.destroyed_by_idx,
                }
                for s in p.segments
            ],
        }
        for p in pivots
    ]


def _legacy_confirmed_segments(closes):
    kline = _make_kline(closes)
    merged_high, merged_low, idx_map = inclusion_process(kline["highs"], kline["lows"])
    fractals = find_fractals(merged_high, merged_low, idx_map, kline["dates"])
    strokes = build_strokes(fractals, merged_high, merged_low)
    if USE_SEGMENT_BREAK_BUILDER:
        segments = build_segments_by_break(strokes)
    else:
        segments = build_segments_fixed_window(strokes)
    return kline, [s for s in segments if s.confirmed]


class ChanEngineCandidatePivotTests(unittest.TestCase):
    def test_candidate_pivots_match_legacy_pivots(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                _, confirmed_segments = _legacy_confirmed_segments(closes)
                legacy = find_pivots(confirmed_segments)
                candidate = find_pivots_candidate(confirmed_segments)
                self.assertEqual(
                    _serialize_pivots(candidate),
                    _serialize_pivots(legacy),
                )

    def test_candidate_pivot_handles_manual_overlap_extension(self):
        candidate_segments = [
            Segment(
                strokes=[],
                start_idx=0,
                end_idx=10,
                direction="up",
                high=10,
                low=1,
                confirmed=True,
                destroyed_by_idx=None,
            ),
            Segment(
                strokes=[],
                start_idx=10,
                end_idx=20,
                direction="down",
                high=12,
                low=2,
                confirmed=True,
                destroyed_by_idx=None,
            ),
            Segment(
                strokes=[],
                start_idx=20,
                end_idx=30,
                direction="up",
                high=11,
                low=3,
                confirmed=True,
                destroyed_by_idx=None,
            ),
            Segment(
                strokes=[],
                start_idx=30,
                end_idx=40,
                direction="down",
                high=9,
                low=4,
                confirmed=True,
                destroyed_by_idx=None,
            ),
            Segment(
                strokes=[],
                start_idx=40,
                end_idx=50,
                direction="up",
                high=8.5,
                low=4.5,
                confirmed=True,
                destroyed_by_idx=None,
            ),
        ]
        legacy = find_pivots(candidate_segments[:5])
        candidate = find_pivots_candidate(candidate_segments[:5])
        self.assertEqual(_serialize_pivots(candidate), _serialize_pivots(legacy))

    def test_candidate_pivot_returns_empty_without_overlap(self):
        non_overlap_segments = [
            Segment(
                strokes=[],
                start_idx=0,
                end_idx=10,
                direction="up",
                high=10,
                low=1,
                confirmed=True,
            ),
            Segment(
                strokes=[],
                start_idx=10,
                end_idx=20,
                direction="down",
                high=6,
                low=5,
                confirmed=True,
            ),
            Segment(
                strokes=[],
                start_idx=20,
                end_idx=30,
                direction="up",
                high=20,
                low=15,
                confirmed=True,
            ),
        ]
        self.assertEqual(find_pivots(non_overlap_segments), [])
        self.assertEqual(find_pivots_candidate(non_overlap_segments), [])

    def test_candidate_pivot_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_pivot,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
