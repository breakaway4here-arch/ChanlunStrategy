import unittest
from types import SimpleNamespace

import numpy as np

from chanlun.luojie_pool import build_luojie_pool, match_luojie_themes


def _rising_array(n=220, start=10.0, step=0.03):
    return np.array([start + i * step for i in range(n)], dtype=float)


def _result(code="600001", name="测试通信", closes=None, lows=None,
            buy_points=None, pivots=None, dif=None, dea=None):
    closes = closes if closes is not None else _rising_array()
    lows = lows if lows is not None else closes * 0.995
    highs = closes * 1.01
    opens = closes * 0.998
    return SimpleNamespace(
        code=code,
        name=name,
        dates=[f"2026-06-24 10:{i % 60:02d}:00" for i in range(len(closes))],
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=np.ones(len(closes)) * 1000,
        buy_points=buy_points or [],
        pivots=pivots or [],
        macd_dif=dif if dif is not None else np.ones(len(closes)) * 0.2,
        macd_dea=dea if dea is not None else np.ones(len(closes)) * 0.1,
    )


class TestLuojieThemeMatching(unittest.TestCase):

    def test_matches_hardcoded_national_team_themes(self):
        stock = {"code": "300308", "name": "中际旭创", "sector": "光通信"}

        themes = match_luojie_themes(stock)

        self.assertIn("赛道层", themes)
        self.assertIn("光模块", themes["赛道层"])
        self.assertIn("六网", themes)
        self.assertIn("新一代通信网", themes["六网"])


class TestBuildLuojiePool(unittest.TestCase):

    def test_keeps_stock_above_lifeline_with_macd_above_zero_and_third_buy(self):
        closes = _rising_array()
        lows = closes * 0.997
        bp = {"type": "三买", "price": float(closes[-3]), "date": "2026-06-24 14:45:00"}
        pivot = SimpleNamespace(ZD=float(closes[-40]), ZG=float(closes[-20]), start_idx=160, end_idx=200)
        result = _result(closes=closes, lows=lows, buy_points=[bp], pivots=[pivot])

        pool = build_luojie_pool(
            stocks=[{"code": "600001", "name": "测试通信", "sector": "通信设备"}],
            min15_results=[result],
        )

        self.assertEqual(pool["mode"], "enabled")
        self.assertEqual(len(pool["candidates"]), 1)
        candidate = pool["candidates"][0]
        self.assertEqual(candidate["tier"], "主升候选")
        self.assertEqual(candidate["buy_point_type"], "三买")
        self.assertGreater(candidate["life_line"], 0)
        self.assertTrue(candidate["macd_above_zero"])

    def test_drops_stock_when_macd_double_lines_not_above_zero(self):
        closes = _rising_array()
        result = _result(
            code="600002",
            name="测试芯片",
            closes=closes,
            dif=np.ones(len(closes)) * 0.2,
            dea=np.ones(len(closes)) * -0.01,
        )

        pool = build_luojie_pool(
            stocks=[{"code": "600002", "name": "测试芯片", "sector": "半导体"}],
            min15_results=[result],
        )

        self.assertEqual(pool["candidates"], [])
        self.assertEqual(pool["diagnostics"]["dropped_macd_below_zero"], 1)

    def test_drops_stock_after_lifeline_break(self):
        closes = _rising_array()
        closes[-1] = closes[-80] * 0.98
        result = _result(code="600003", name="测试算力", closes=closes, lows=closes * 0.995)

        pool = build_luojie_pool(
            stocks=[{"code": "600003", "name": "测试算力", "sector": "算力"}],
            min15_results=[result],
        )

        self.assertEqual(pool["candidates"], [])
        self.assertEqual(pool["diagnostics"]["dropped_lifeline_break"], 1)

    def test_marks_risk_watch_when_77ma_break_is_still_in_five_bar_window(self):
        closes = _rising_array()
        lows = closes * 0.997
        result = _result(code="600004", name="测试IDC", closes=closes, lows=lows)
        ma77 = np.mean(closes[-77:])
        result.closes[-3] = ma77 * 0.995
        result.closes[-2] = ma77 * 1.002
        result.closes[-1] = ma77 * 1.004

        pool = build_luojie_pool(
            stocks=[{"code": "600004", "name": "测试IDC", "sector": "IDC"}],
            min15_results=[result],
        )

        self.assertEqual(pool["candidates"][0]["tier"], "风控观察")
        self.assertIn("跌破77线后5根K内修复观察", pool["candidates"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
