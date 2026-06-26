"""Tests for GF-DMA health scoring utility."""

import unittest
from typing import List

from chanlun.research_frameworks import calc_gf_dma_health


def _series(base: float, length: int, final: float) -> List[float]:
    step = (final - base) / max(1, length - 1)
    return [base + step * i for i in range(length)]


class TestCalcGFDMAHealth(unittest.TestCase):
    def test_trending_up_case_returns_healthy_tag(self):
        closes = _series(50.0, 220, 120.0)
        volumes = [1000.0] * 220
        result = calc_gf_dma_health({"code": "000001", "name": "测试", "closes": closes, "volumes": volumes})

        self.assertEqual(result["data_quality"], "full")
        self.assertEqual(result["ma"]["ma200"] is not None, True)
        self.assertGreater(result["score"], 0)
        self.assertIn(result["alignment"], {"bullish", "repairing", "neutral"})
        self.assertIn(result["label"], {"强势健康", "趋势健康"})

    def test_overheated_case_marked_as_hot(self):
        closes = _series(90.0, 220, 90.0)
        closes[-1] = 130.0  # small spike on the last bar creates high乖离与拉升感
        closes[-2] = 128.0
        volumes = [1000.0] * 215 + [2000.0] * 5
        result = calc_gf_dma_health({"code": "000002", "name": "测试2", "closes": closes, "volumes": volumes})

        self.assertEqual(result["alignment"], "bullish")
        self.assertIn(result["fomo_risk"], {"high", "medium"})
        if result["fomo_risk"] == "high":
            self.assertEqual(result["label"], "强势过热")
        else:
            self.assertGreaterEqual(result["score"], 80)

    def test_broken_case_shows_weak_or_broken(self):
        closes = _series(200.0, 220, 40.0)
        volumes = [1000.0] * 220
        result = calc_gf_dma_health({"code": "000003", "name": "测试3", "closes": closes, "volumes": volumes})

        self.assertIn(result["alignment"], {"weak", "broken"})
        self.assertIn(result["label"], {"走势转弱", "结构破坏"})

    def test_small_sample_does_not_crash_and_marks_insufficient(self):
        closes = [10.0, 10.2, 10.1, 10.4, 10.3]
        result = calc_gf_dma_health({"code": "000004", "name": "测试4", "closes": closes, "volumes": [100, 100, 100, 100, 100]})

        self.assertEqual(result["data_quality"], "insufficient")
        self.assertIsNone(result["ma"]["ma200"])
        self.assertIn("label", result)
        self.assertIsInstance(result["score"], float)


if __name__ == "__main__":
    unittest.main()
