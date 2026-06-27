import unittest

import numpy as np

from chanlun.chan_engine import (
    analyze,
    analyze_dual,
    check_divergence,
)
from chanlun.engine_candidate import (
    analyze_with_candidate_divergence,
    check_divergence_candidate,
)
from chanlun.engine_types import Pivot, Segment
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


def _serialize_divergence(divergence):
    if divergence is None:
        return None
    return {
        "type": divergence.get("type"),
        "is_divergence": divergence.get("is_divergence"),
        "area_ratio": divergence.get("area_ratio"),
        "hist_divergence": divergence.get("hist_divergence"),
        "prev_segment": divergence.get("prev_segment"),
        "last_segment": divergence.get("last_segment"),
    }


def _seg(start, end, direction, high, low):
    return Segment(
        strokes=[],
        start_idx=start,
        end_idx=end,
        direction=direction,
        high=high,
        low=low,
        confirmed=True,
    )


def _pivot(zd, zg, start=0, end=1):
    return Pivot(ZD=zd, ZG=zg, segments=[], start_idx=start, end_idx=end)


class ChanEngineCandidateDivergenceTests(unittest.TestCase):
    def test_candidate_divergence_matches_legacy_divergence(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                result = analyze(
                    name,
                    name,
                    kline["dates"],
                    kline["opens"],
                    kline["highs"],
                    kline["lows"],
                    kline["closes"],
                    kline["volumes"],
                )
                confirmed_segments = [s for s in result.segments if s.confirmed]
                legacy = check_divergence(
                    result.closes,
                    confirmed_segments,
                    result.macd_dif,
                    result.macd_dea,
                    result.macd_hist,
                    pivots=result.pivots,
                )
                candidate = check_divergence_candidate(
                    result.closes,
                    confirmed_segments,
                    result.macd_dif,
                    result.macd_dea,
                    result.macd_hist,
                    pivots=result.pivots,
                )
                self.assertEqual(
                    _serialize_divergence(candidate),
                    _serialize_divergence(legacy),
                )

    def test_candidate_divergence_returns_none_with_insufficient_segments(self):
        hist = np.ones(8, dtype=float)
        dif = hist.copy()
        dea = hist.copy()
        closes = np.arange(8, dtype=float)

        self.assertIsNone(
            check_divergence_candidate(
                closes,
                [_seg(0, 2, "up", 10.0, 5.0)],
                dif,
                dea,
                hist,
            )
        )
        self.assertIsNone(
            check_divergence_candidate(
                closes,
                [
                    _seg(0, 2, "up", 10.0, 5.0),
                    _seg(3, 5, "down", 9.0, 4.0),
                ],
                dif,
                dea,
                hist,
            )
        )

    def test_candidate_divergence_matches_manual_top_and_bottom_area_divergence(self):
        closes = np.arange(8, dtype=float)
        dif = np.zeros(8, dtype=float)
        dea = np.zeros(8, dtype=float)

        top_segments = [
            _seg(0, 2, "up", 10.0, 5.0),
            _seg(3, 3, "down", 9.0, 6.0),
            _seg(4, 6, "up", 12.0, 7.0),
        ]
        top_hist = np.array([2.0, 2.0, 2.0, 0.0, 1.0, 1.0, 1.0, 0.0])
        legacy_top = check_divergence(closes, top_segments, dif, dea, top_hist)
        candidate_top = check_divergence_candidate(closes, top_segments, dif, dea, top_hist)
        self.assertEqual(_serialize_divergence(candidate_top), _serialize_divergence(legacy_top))
        self.assertEqual(candidate_top["type"], "盘整顶背驰")

        bottom_segments = [
            _seg(0, 2, "down", 10.0, 5.0),
            _seg(3, 3, "up", 11.0, 6.0),
            _seg(4, 6, "down", 9.0, 3.0),
        ]
        bottom_hist = np.array([-2.0, -2.0, -2.0, 0.0, -1.0, -1.0, -1.0, 0.0])
        legacy_bottom = check_divergence(closes, bottom_segments, dif, dea, bottom_hist)
        candidate_bottom = check_divergence_candidate(closes, bottom_segments, dif, dea, bottom_hist)
        self.assertEqual(
            _serialize_divergence(candidate_bottom),
            _serialize_divergence(legacy_bottom),
        )
        self.assertEqual(candidate_bottom["type"], "盘整底背驰")

    def test_candidate_divergence_matches_manual_trend_prefix_and_hist_divergence(self):
        closes = np.arange(8, dtype=float)
        dif = np.zeros(8, dtype=float)
        dea = np.zeros(8, dtype=float)
        pivots = [_pivot(10.0, 12.0), _pivot(14.0, 16.0, start=2, end=3)]
        segments = [
            _seg(0, 2, "down", 10.0, 5.0),
            _seg(3, 3, "up", 12.0, 6.0),
            _seg(4, 6, "down", 9.0, 3.0),
        ]
        hist = np.array([-2.0, -2.0, -2.0, 0.0, -1.0, -1.0, -1.0, 0.0])

        legacy = check_divergence(closes, segments, dif, dea, hist, pivots=pivots)
        candidate = check_divergence_candidate(closes, segments, dif, dea, hist, pivots=pivots)

        self.assertEqual(_serialize_divergence(candidate), _serialize_divergence(legacy))
        self.assertEqual(candidate["type"], "趋势底背驰")
        self.assertTrue(candidate["hist_divergence"])

    def test_candidate_divergence_handles_zero_previous_area_and_out_of_range(self):
        closes = np.arange(8, dtype=float)
        hist = np.zeros(8, dtype=float)
        dif = hist.copy()
        dea = hist.copy()

        zero_area_segments = [
            _seg(0, 2, "up", 10.0, 5.0),
            _seg(3, 3, "down", 9.0, 6.0),
            _seg(4, 6, "up", 12.0, 7.0),
        ]
        self.assertIsNone(
            check_divergence_candidate(closes, zero_area_segments, dif, dea, hist)
        )

        out_of_range_segments = [
            _seg(20, 22, "up", 10.0, 5.0),
            _seg(23, 23, "down", 9.0, 6.0),
            _seg(24, 26, "up", 12.0, 7.0),
        ]
        self.assertIsNone(
            check_divergence_candidate(closes, out_of_range_segments, dif, dea, hist)
        )

    def test_candidate_divergence_analyzer_matches_legacy_dual_output(self):
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
                    candidate_analyzer=analyze_with_candidate_divergence,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
