import unittest
from types import SimpleNamespace

import numpy as np

from chanlun.screener_fusion import _confirm_third_buy_30min
from chanlun.screener_pure import screen_30min_pure


class ScreenerPriceBasisTests(unittest.TestCase):
    @staticmethod
    def _min30(low=9.6, close=10.0):
        return SimpleNamespace(
            code="300900",
            closes=np.array([close] * 8, dtype=float),
            opens=np.array([close] * 8, dtype=float),
            highs=np.array([close + 0.1] * 8, dtype=float),
            lows=np.array([low] * 8, dtype=float),
            dates=["2026-09-03 14:30:00"] * 8,
            buy_points=[],
            fractals=[],
            divergence=None,
            macd_dif=None,
            macd_dea=None,
        )

    def test_legacy_third_buy_guard_aligns_30m_low_to_daily_basis(self):
        stock = {
            "pivots": {"ZG": 5.0},
            "closes": np.array([5.0] * 20, dtype=float),
            "price_basis": {"adjustment": "qfq", "factor_vs_raw": 0.5},
        }

        self.assertFalse(_confirm_third_buy_30min(stock, self._min30()))

    def test_legacy_bottom_fractal_is_compared_in_daily_basis(self):
        stock = {
            "code": "300900",
            "best_buy_point": {"type": "一买", "price": 5.0},
            "closes": np.array([5.0] * 20, dtype=float),
            "price_basis": {"adjustment": "qfq", "factor_vs_raw": 0.5},
        }
        min30 = self._min30()
        min30.divergence = {"is_divergence": True, "type": "底背驰"}
        min30.fractals = [
            SimpleNamespace(type="bottom", price=9.6, index=7)
        ]

        result = screen_30min_pure([stock], [min30])

        self.assertEqual(len(result[0]["buy_points_30min"]), 1)
        self.assertAlmostEqual(result[0]["buy_points_30min"][0]["price"], 4.8)


if __name__ == "__main__":
    unittest.main()
