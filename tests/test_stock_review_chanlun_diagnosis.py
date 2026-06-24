"""Unit tests for stock_review chanlun diagnosis."""
import unittest
import numpy as np
from chanlun.chan_engine import analyze, ChanResult
from chanlun.stock_review.chanlun_diagnosis import (
    extract_daily_structure,
    extract_30min_structure,
    classify_price_position,
    build_diagnosis,
)


def _make_fake_chan_result(code="600519", name="贵州茅台", n=100,
                            trend_type="盘整", has_pivot=True):
    """Build a minimal ChanResult for testing diagnosis extraction."""
    closes = np.linspace(100, 110, n) + np.random.randn(n) * 2
    highs = closes + np.abs(np.random.randn(n)) * 1.5
    lows = closes - np.abs(np.random.randn(n)) * 1.5
    opens = closes.copy()
    volumes = np.ones(n) * 10000
    dates = [f"2026-05-{d:02d}" for d in range(1, min(n + 1, 32))]

    result = ChanResult(
        code=code, name=name,
        closes=closes, highs=highs, lows=lows, opens=opens,
        volumes=volumes, dates=dates,
        trend_type=trend_type,
    )

    if has_pivot:
        from chanlun.chan_engine import Pivot
        zd = float(np.mean(closes[-20:]) * 0.95)
        zg = float(np.mean(closes[-20:]) * 1.05)
        result.pivots = [Pivot(ZD=zd, ZG=zg, segments=[], start_idx=n-30, end_idx=n-5)]

    return result


class TestClassifyPricePosition(unittest.TestCase):

    def test_below_zd(self):
        self.assertEqual(classify_price_position(90, 100, 110), "中枢下方")

    def test_near_zd(self):
        self.assertEqual(classify_price_position(101, 100, 110), "中枢下沿附近")

    def test_inside_pivot(self):
        self.assertEqual(classify_price_position(105, 100, 110), "中枢内")

    def test_near_zg(self):
        self.assertEqual(classify_price_position(109, 100, 110), "中枢上沿附近")

    def test_above_zg(self):
        self.assertEqual(classify_price_position(115, 100, 110), "中枢上方")

    def test_no_pivot(self):
        self.assertEqual(classify_price_position(105, None, None), "无中枢")


class TestExtractDailyStructure(unittest.TestCase):

    def test_extract_basic_fields(self):
        result = _make_fake_chan_result()
        s = extract_daily_structure(result)
        self.assertEqual(s["code"], "600519")
        self.assertEqual(s["trend_type"], "盘整")
        self.assertIn("pivots", s)
        self.assertIn("buy_points", s)
        self.assertIn("sell_points", s)
        self.assertIn("close", s)

    def test_no_pivot_returns_degraded(self):
        result = _make_fake_chan_result(has_pivot=False)
        s = extract_daily_structure(result)
        self.assertEqual(len(s["pivots"]), 0)
        self.assertEqual(s["position"], "无中枢")

    def test_none_result_returns_degraded(self):
        s = extract_daily_structure(None)
        self.assertEqual(s["status"], "data_insufficient")


class TestExtract30minStructure(unittest.TestCase):

    def test_extract_basic_fields(self):
        result = _make_fake_chan_result()
        s = extract_30min_structure(result)
        self.assertEqual(s["code"], "600519")
        self.assertIn("trend_type", s)

    def test_none_result_returns_degraded(self):
        s = extract_30min_structure(None)
        self.assertEqual(s["status"], "data_insufficient")


class TestBuildDiagnosis(unittest.TestCase):

    def test_returns_complete_diagnosis(self):
        daily = _make_fake_chan_result()
        min30 = _make_fake_chan_result()
        diag = build_diagnosis("600519", "贵州茅台", daily, min30)
        self.assertEqual(diag["code"], "600519")
        self.assertIn("daily", diag)
        self.assertIn("min30", diag)
        self.assertIn("position", diag["daily"])

    def test_both_none_returns_degraded(self):
        diag = build_diagnosis("000001", "测试", None, None)
        self.assertEqual(diag["daily"]["status"], "data_insufficient")
        self.assertEqual(diag["min30"]["status"], "data_insufficient")


if __name__ == "__main__":
    unittest.main()
