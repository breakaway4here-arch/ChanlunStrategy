"""Regression invariants for legacy chan_engine output shape and bounds."""

import unittest
import numpy as np

from chanlun.chan_engine import analyze


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


SERIES = [
    [10, 11, 12, 11, 10, 9, 10, 11, 12, 13, 12, 11, 10, 11, 12, 13, 14, 13, 12, 11] * 4,
    [10 + i * 0.2 for i in range(80)],
    [20 - i * 0.15 for i in range(80)],
]


class ChanEngineInvariantsTests(unittest.TestCase):
    def test_strokes_are_ordered_and_directional(self):
        for closes in SERIES:
            result = analyze_closes(closes)
            for stroke in result.strokes:
                self.assertLess(stroke.start_idx, stroke.end_idx)
                self.assertIn(stroke.direction, ("up", "down"))

    def test_segments_have_valid_ranges(self):
        for closes in SERIES:
            result = analyze_closes(closes)
            for segment in result.segments:
                self.assertLessEqual(segment.low, segment.high)
                self.assertIn(segment.direction, ("up", "down"))
                self.assertLessEqual(segment.start_idx, segment.end_idx)

    def test_pivots_have_valid_overlap(self):
        for closes in SERIES:
            result = analyze_closes(closes)
            for pivot in result.pivots:
                self.assertGreater(pivot.ZG, pivot.ZD)
                self.assertLessEqual(pivot.start_idx, pivot.end_idx)

    def test_signal_indices_are_in_range(self):
        for closes in SERIES:
            result = analyze_closes(closes)
            n = len(result.closes)
            for bp in result.buy_points:
                self.assertGreaterEqual(bp["index"], 0)
                self.assertLess(bp["index"], n)
                self.assertIn("type", bp)
                self.assertIn("price", bp)
            for sp in result.sell_points:
                self.assertGreaterEqual(sp["index"], 0)
                self.assertLess(sp["index"], n)
                self.assertIn("type", sp)
                self.assertIn("price", sp)


if __name__ == "__main__":
    unittest.main()
