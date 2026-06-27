import unittest

import numpy as np

from chanlun.chan_engine import (
    analyze_dual,
    build_segments_by_break,
    build_segments_fixed_window,
    build_strokes,
    classify_trend,
    find_fractals,
    find_pivots,
    inclusion_process,
)
from chanlun.engine_candidate import analyze_with_candidate_trend, classify_trend_candidate
from chanlun.engine_types import Pivot
from config import USE_SEGMENT_BREAK_BUILDER
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


def _legacy_structure(closes):
    kline = _make_kline(closes)
    merged_high, merged_low, idx_map = inclusion_process(kline["highs"], kline["lows"])
    fractals = find_fractals(merged_high, merged_low, idx_map, kline["dates"])
    strokes = build_strokes(fractals, merged_high, merged_low)
    if USE_SEGMENT_BREAK_BUILDER:
        segments = build_segments_by_break(strokes)
    else:
        segments = build_segments_fixed_window(strokes)
    confirmed_segments = [s for s in segments if s.confirmed]
    pivots = find_pivots(confirmed_segments)
    return kline, confirmed_segments, pivots


def _make_pivots():
    return [
        Pivot(
            ZD=10.0,
            ZG=20.0,
            segments=[],
            start_idx=0,
            end_idx=9,
        ),
        Pivot(
            ZD=35.0,
            ZG=40.0,
            segments=[],
            start_idx=10,
            end_idx=19,
        ),
        Pivot(
            ZD=20.0,
            ZG=25.0,
            segments=[],
            start_idx=20,
            end_idx=29,
        ),
    ]


class ChanEngineCandidateTrendTests(unittest.TestCase):
    def test_candidate_trend_matches_legacy_trend(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                _, _, legacy_pivots = _legacy_structure(closes)
                candidate = classify_trend_candidate(legacy_pivots, [])
                legacy = classify_trend(legacy_pivots, [])
                self.assertEqual(candidate, legacy)

    def test_candidate_trend_handles_manual_empty_and_sideways(self):
        self.assertEqual(classify_trend_candidate([], []), "无中枢")
        self.assertEqual(
            classify_trend_candidate(
                [
                    Pivot(
                        ZD=10.0,
                        ZG=20.0,
                        segments=[],
                        start_idx=0,
                        end_idx=9,
                    )
                ],
                [],
            ),
            "盘整",
        )

    def test_candidate_trend_handles_manual_up_down_and_mixed(self):
        self.assertEqual(
            classify_trend_candidate(
                [
                    Pivot(
                        ZD=10.0,
                        ZG=20.0,
                        segments=[],
                        start_idx=0,
                        end_idx=9,
                    ),
                    Pivot(
                        ZD=21.0,
                        ZG=30.0,
                        segments=[],
                        start_idx=10,
                        end_idx=19,
                    ),
                ],
                [],
            ),
            "上涨趋势",
        )
        self.assertEqual(
            classify_trend_candidate(
                [
                    Pivot(
                        ZD=10.0,
                        ZG=20.0,
                        segments=[],
                        start_idx=0,
                        end_idx=9,
                    ),
                    Pivot(
                        ZD=2.0,
                        ZG=5.0,
                        segments=[],
                        start_idx=10,
                        end_idx=19,
                    ),
                ],
                [],
            ),
            "下跌趋势",
        )
        self.assertEqual(
            classify_trend_candidate(
                [
                    Pivot(
                        ZD=10.0,
                        ZG=20.0,
                        segments=[],
                        start_idx=0,
                        end_idx=9,
                    ),
                    Pivot(
                        ZD=11.0,
                        ZG=19.0,
                        segments=[],
                        start_idx=10,
                        end_idx=19,
                    ),
                ],
                [],
            ),
            "盘整",
        )
        self.assertEqual(classify_trend_candidate(_make_pivots(), []), "上涨趋势")

    def test_candidate_trend_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_trend,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
