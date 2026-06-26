import numpy as np
import unittest


from chanlun.chan_engine import (
    BI_MIN_KLINE_COUNT,
    DIVERGENCE_PLATEAU,
    Fractal,
    ChanResult,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    PIVOT_MIN_SEGMENTS,
    Pivot,
    SEGMENT_MIN_STROKES,
    Segment,
    Stroke,
    THIRD_BUY_MAX_CHASE_PCT,
    USE_SEGMENT_BREAK_BUILDER,
    calc_macd,
    build_segments_fixed_window,
    build_segments_by_break,
    build_stroke_pivots,
    build_strokes,
    build_strokes_swing,
    classify_trend,
    check_divergence,
    find_fractals,
    find_pivots,
    inclusion_process,
    locate_buy_sell_points,
    prune_strokes,
    stroke_high,
    stroke_low,
    analyze,
)


class ChanEngineImportCompatibilityTests(unittest.TestCase):
    def test_exports_and_basic_construction(self):
        self.assertTrue(callable(calc_macd))
        self.assertTrue(callable(inclusion_process))
        self.assertTrue(callable(find_fractals))
        self.assertTrue(callable(build_strokes))
        self.assertTrue(callable(build_segments_by_break))
        self.assertTrue(callable(build_segments_fixed_window))
        self.assertTrue(callable(find_pivots))
        self.assertTrue(callable(classify_trend))
        self.assertTrue(callable(check_divergence))
        self.assertTrue(callable(locate_buy_sell_points))
        self.assertTrue(callable(build_strokes_swing))
        self.assertTrue(callable(prune_strokes))
        self.assertTrue(callable(build_stroke_pivots))
        self.assertTrue(callable(stroke_high))
        self.assertTrue(callable(stroke_low))
        self.assertTrue(callable(analyze))
        self.assertGreaterEqual(BI_MIN_KLINE_COUNT, 1)
        self.assertGreaterEqual(SEGMENT_MIN_STROKES, 1)
        self.assertGreaterEqual(PIVOT_MIN_SEGMENTS, 1)
        self.assertGreater(MACD_FAST, 0)
        self.assertGreater(MACD_SLOW, 0)
        self.assertGreater(MACD_SIGNAL, 0)
        self.assertGreater(DIVERGENCE_PLATEAU, 0)
        self.assertGreater(THIRD_BUY_MAX_CHASE_PCT, 0)
        self.assertIsInstance(USE_SEGMENT_BREAK_BUILDER, bool)

        fractal = Fractal(type="top", index=1, price=10.0)
        stroke = Stroke(start_idx=0, end_idx=2, start_price=10.0, end_price=12.0, direction="up")
        segment = Segment(strokes=[stroke], start_idx=0, end_idx=2, direction="up", high=12.0, low=10.0)
        pivot = Pivot(ZD=10.0, ZG=12.0, segments=[segment], start_idx=0, end_idx=2)
        result = ChanResult(
            code="TEST",
            name="TEST",
            closes=np.array([10.0, 11.0, 12.0]),
            highs=np.array([10.5, 11.5, 12.5]),
            lows=np.array([9.5, 10.5, 11.5]),
            opens=np.array([10.0, 11.0, 12.0]),
            volumes=np.array([100, 100, 100]),
            dates=[0, 1, 2],
            fractals=[fractal],
            strokes=[stroke],
            segments=[segment],
            pivots=[pivot],
        )

        self.assertEqual(result.code, "TEST")
        self.assertEqual(len(result.fractals), 1)
        self.assertEqual(len(result.pivots), 1)

        diverg = check_divergence(
            closes=result.closes,
            segments=result.segments,
            dif=np.array([1.0, 2.0, 3.0]),
            dea=np.array([0.5, 1.0, 1.5]),
            hist=np.array([0.1, 0.1, 0.1]),
            pivots=result.pivots,
        )
        self.assertIn(diverg, (None, dict))


if __name__ == "__main__":
    unittest.main()
