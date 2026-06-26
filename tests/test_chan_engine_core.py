import unittest
import numpy as np

from chanlun.chan_engine import (
    Fractal,
    Segment,
    Pivot,
    inclusion_process,
    find_fractals,
    build_strokes,
    find_pivots,
    classify_trend,
)


def make_segment(start_idx, end_idx, direction, high, low):
    return Segment(
        strokes=[],
        start_idx=start_idx,
        end_idx=end_idx,
        direction=direction,
        high=high,
        low=low,
    )


class InclusionProcessCoreTests(unittest.TestCase):
    def test_inclusion_process_keeps_non_included_lines(self):
        highs = np.array([10.0, 12.0, 13.0], dtype=float)
        lows = np.array([5.0, 4.0, 3.0], dtype=float)

        merged_highs, merged_lows, idx_map = inclusion_process(highs, lows)

        self.assertEqual(list(merged_highs), [10.0, 12.0, 13.0])
        self.assertEqual(list(merged_lows), [5.0, 4.0, 3.0])
        self.assertEqual(idx_map, [[0], [1], [2]])

    def test_inclusion_process_keeps_initial_includes_without_direction(self):
        highs = np.array([10.0, 12.0, 11.0, 11.0], dtype=float)
        lows = np.array([5.0, 2.0, 3.0, 4.0], dtype=float)

        merged_highs, merged_lows, idx_map = inclusion_process(highs, lows)

        self.assertEqual(list(merged_highs), [10.0, 12.0, 11.0, 11.0])
        self.assertEqual(list(merged_lows), [5.0, 2.0, 3.0, 4.0])
        self.assertEqual(idx_map, [[0], [1], [2], [3]])

    def test_inclusion_process_merges_upward_with_higher_extremes(self):
        highs = np.array([10.0, 12.0, 13.0, 12.5], dtype=float)
        lows = np.array([5.0, 6.0, 7.0, 7.5], dtype=float)

        merged_highs, merged_lows, idx_map = inclusion_process(highs, lows)

        self.assertEqual(list(merged_highs), [10.0, 12.0, 13.0])
        self.assertEqual(list(merged_lows), [5.0, 6.0, 7.5])
        self.assertEqual(idx_map, [[0], [1], [2, 3]])

    def test_inclusion_process_merges_downward_with_lower_extremes(self):
        highs = np.array([12.0, 10.0, 8.0], dtype=float)
        lows = np.array([5.0, 4.0, 4.5], dtype=float)

        merged_highs, merged_lows, idx_map = inclusion_process(highs, lows)

        self.assertEqual(list(merged_highs), [12.0, 8.0])
        self.assertEqual(list(merged_lows), [5.0, 4.0])
        self.assertEqual(idx_map, [[0], [1, 2]])

    def test_idx_map_stays_synchronized_after_inclusion(self):
        highs = np.array([10.0, 12.0, 13.0, 12.5, 14.0], dtype=float)
        lows = np.array([5.0, 6.0, 7.0, 7.5, 8.0], dtype=float)

        _, _, idx_map = inclusion_process(highs, lows)
        self.assertEqual(idx_map, [[0], [1], [2, 3], [4]])


class FindFractalsCoreTests(unittest.TestCase):
    def test_find_fractals_detects_top_bottom_and_maps_index_to_original_kline(self):
        highs = np.array([1.0, 5.0, 1.0, 4.0, 2.0, 6.0, 3.0], dtype=float)
        lows = np.array([1.0, 2.0, 1.0, 1.0, 0.0, 1.0, 0.0], dtype=float)
        idx_map = [[0], [10, 11], [12], [13, 14], [15, 16, 17], [18, 19], [20]]

        fractals = find_fractals(highs, lows, idx_map)

        self.assertEqual(len(fractals), 2)
        self.assertEqual(fractals[0].type, "top")
        self.assertEqual(fractals[0].index, 11)
        self.assertEqual(fractals[1].type, "bottom")
        self.assertEqual(fractals[1].index, 16)


class BuildStrokesCoreTests(unittest.TestCase):
    def test_build_strokes_forms_expected_directional_strokes(self):
        fractals = [
            Fractal(type="bottom", index=0, price=10.0, klines=[0]),
            Fractal(type="top", index=6, price=18.0, klines=[6]),
            Fractal(type="bottom", index=14, price=12.0, klines=[14]),
            Fractal(type="top", index=22, price=20.0, klines=[22]),
        ]
        highs = np.array([10, 12, 14, 16, 18, 20, 22, 24], dtype=float)
        lows = np.array([8, 9, 10, 11, 12, 13, 14, 15], dtype=float)

        strokes = build_strokes(fractals, highs, lows)

        self.assertEqual(len(strokes), 3)
        self.assertEqual(strokes[0].direction, "up")
        self.assertEqual(strokes[0].start_idx, 0)
        self.assertEqual(strokes[0].end_idx, 6)
        self.assertEqual(strokes[1].direction, "down")
        self.assertEqual(strokes[1].start_idx, 6)
        self.assertEqual(strokes[1].end_idx, 14)

    def test_build_strokes_does_not_create_stroke_when_distance_too_short(self):
        fractals = [
            Fractal(type="bottom", index=0, price=10.0, klines=[0]),
            Fractal(type="top", index=3, price=20.0, klines=[3]),
        ]
        highs = np.array([10, 12, 14, 16], dtype=float)
        lows = np.array([8, 9, 10, 11], dtype=float)

        self.assertEqual(build_strokes(fractals, highs, lows), [])


class FindPivotsCoreTests(unittest.TestCase):
    def test_find_pivots_identifies_overlap_structure(self):
        segments = [
            make_segment(0, 2, "up", 15.0, 8.0),
            make_segment(3, 5, "down", 14.0, 7.0),
            make_segment(6, 8, "up", 13.0, 9.0),
            make_segment(9, 11, "down", 14.0, 6.0),
        ]

        pivots = find_pivots(segments)

        self.assertEqual(len(pivots), 1)
        self.assertEqual(pivots[0].ZD, 9)
        self.assertEqual(pivots[0].ZG, 13)
        self.assertEqual(pivots[0].start_idx, 0)
        self.assertEqual(pivots[0].end_idx, 11)

    def test_find_pivots_returns_none_when_no_overlap(self):
        segments = [
            make_segment(0, 3, "up", 30.0, 10.0),
            make_segment(4, 6, "down", 50.0, 40.0),
            make_segment(7, 9, "up", 70.0, 60.0),
        ]

        pivots = find_pivots(segments)
        self.assertEqual(pivots, [])


class ClassifyTrendCoreTests(unittest.TestCase):
    def test_classify_trend_empty(self):
        self.assertEqual(classify_trend([], []), "无中枢")

    def test_classify_trend_single_pivot_is_sideways(self):
        pivot = Pivot(ZD=10.0, ZG=12.0, segments=[], start_idx=1, end_idx=10)
        self.assertEqual(classify_trend([pivot], []), "盘整")

    def test_classify_trend_two_upward_pivots(self):
        pivot1 = Pivot(ZD=10.0, ZG=12.0, segments=[], start_idx=1, end_idx=10)
        pivot2 = Pivot(ZD=12.5, ZG=14.0, segments=[], start_idx=11, end_idx=20)
        self.assertEqual(classify_trend([pivot1, pivot2], []), "上涨趋势")

    def test_classify_trend_two_downward_pivots(self):
        pivot1 = Pivot(ZD=10.0, ZG=12.0, segments=[], start_idx=1, end_idx=10)
        pivot2 = Pivot(ZD=9.0, ZG=9.5, segments=[], start_idx=11, end_idx=20)
        self.assertEqual(classify_trend([pivot1, pivot2], []), "下跌趋势")


if __name__ == "__main__":
    unittest.main()
