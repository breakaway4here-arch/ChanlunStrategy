import unittest

from chanlun.chan_engine import Stroke, build_segments_by_break


def s(a, b, ap, bp, direction):
    return Stroke(
        start_idx=a,
        end_idx=b,
        start_price=ap,
        end_price=bp,
        direction=direction,
    )


class SegmentBuilderTests(unittest.TestCase):
    def test_up_segment_extends_until_destroyed(self):
        strokes = [
            s(0, 1, 10, 15, "up"),
            s(1, 2, 15, 12, "down"),
            s(2, 3, 12, 18, "up"),
            s(3, 4, 18, 14, "down"),
            s(4, 5, 14, 20, "up"),
            s(5, 6, 20, 11, "down"),  # destroys prior key low 12
            s(6, 7, 11, 16, "up"),
            s(7, 8, 16, 9, "down"),
        ]

        segments = build_segments_by_break(strokes)

        self.assertGreaterEqual(len(segments), 1)
        self.assertGreater(len(segments[0].strokes), 3)
        self.assertEqual(segments[0].direction, "up")
        self.assertEqual(segments[0].start_idx, 0)

    def test_segments_are_not_arbitrary_three_stroke_windows(self):
        strokes = [
            s(0, 1, 10, 15, "up"),
            s(1, 2, 15, 12, "down"),
            s(2, 3, 12, 18, "up"),
            s(3, 4, 18, 14, "down"),
            s(4, 5, 14, 20, "up"),
        ]

        segments = build_segments_by_break(strokes)

        self.assertEqual(len(segments), 1)
        self.assertEqual([st.start_idx for st in segments[0].strokes], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
