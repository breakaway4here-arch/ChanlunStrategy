import numpy as np
import unittest


from chanlun.chan_engine import (
    Fractal,
    Stroke,
    Segment,
    Pivot,
    ChanResult,
    calc_macd,
    inclusion_process,
    find_fractals,
    build_strokes,
    build_segments_by_break,
    find_pivots,
    classify_trend,
    check_divergence,
    locate_buy_sell_points,
    analyze,
)


class ChanEngineImportCompatibilityTests(unittest.TestCase):
    def test_exports_and_basic_construction(self):
        self.assertTrue(callable(calc_macd))
        self.assertTrue(callable(inclusion_process))
        self.assertTrue(callable(find_fractals))
        self.assertTrue(callable(build_strokes))
        self.assertTrue(callable(build_segments_by_break))
        self.assertTrue(callable(find_pivots))
        self.assertTrue(callable(classify_trend))
        self.assertTrue(callable(check_divergence))
        self.assertTrue(callable(locate_buy_sell_points))
        self.assertTrue(callable(analyze))

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
