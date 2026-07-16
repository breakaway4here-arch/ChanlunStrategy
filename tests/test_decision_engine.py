import unittest

import config

from chanlun.decision_engine import evaluate_stock


class DecisionEngineTestCase(unittest.TestCase):
    def test_recommend_case(self):
        stock = {
            "code": "AAA",
            "name": "Alpha",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "distance_from_reference_pct": 3,
            "is_extended_move": False,
            "recent_run_days": 1,
            "sector_hot": True,
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
            "market_phase": "主升",
            "limit_up_recent": True,
            "ma_bullish": True,
            "change_pct": 12,
        }
        result = evaluate_stock(stock)

        self.assertEqual(result["version"], "1")
        self.assertEqual(result["code"], "AAA")
        self.assertEqual(result["name"], "Alpha")
        self.assertEqual(result["decision_code"], "recommend")
        self.assertEqual(result["decision"], "推荐")
        self.assertGreaterEqual(result["total_score"], 60)
        self.assertIn("structure", result)
        self.assertIn("position", result)
        self.assertIn("sentiment", result)
        self.assertIsInstance(result["structure"]["reasons"], list)
        self.assertIsInstance(result["position"]["score"], int)
        self.assertIsInstance(result["sentiment"]["score"], int)

        self.assertGreater(result["structure"]["score"], 0)
        self.assertGreater(result["position"]["score"], 0)
        self.assertGreater(result["sentiment"]["score"], 0)

    def test_observe_case(self):
        stock = {
            "code": "BBB",
            "name": "Beta",
            "trend_type": "震荡",
            "breakout_structure": False,
            "pullback_confirmed": False,
            "distance_from_reference_pct": 12,
            "is_extended_move": False,
            "recent_run_days": 4,
            "market_regime": "震荡",
            "sector_strength_label": "强",
            "volume_ratio": 1.1,
            "ma_bullish": True,
            "change_pct": 4,
        }
        result = evaluate_stock(stock)

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "观察")
        self.assertGreaterEqual(result["total_score"], 40)
        self.assertLess(result["total_score"], 60)
        self.assertEqual(result["position"]["reasons"][0], "中位运行")
        self.assertIn("structure", result)
        self.assertIn("sentiment", result)

    def test_reject_high_risk_case(self):
        stock = {
            "code": "CCC",
            "name": "Gamma",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "distance_from_reference_pct": 35,
            "is_extended_move": True,
            "recent_run_days": 6,
            "market_phase": "主升",
        }
        result = evaluate_stock(stock)

        self.assertEqual(result["decision_code"], "reject")
        self.assertEqual(result["decision"], "不推荐（高位风险）")
        self.assertLess(result["position"]["score"], -10)
        self.assertLess(result["total_score"], 60)

    def test_missing_distance_is_observe_with_position_information_insufficient(self):
        result = evaluate_stock({
            "code": "MISS",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
            "market_phase": "主升",
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "暂不判断（位置信息不足）")
        self.assertIn("位置信息不足", result["position"]["reasons"])

    def test_non_finite_distance_is_observe_with_position_information_insufficient(self):
        for distance in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(distance=distance):
                result = evaluate_stock({
                    "code": "INVALID",
                    "distance_from_reference_pct": distance,
                    "trend_type": "上升趋势",
                    "breakout_structure": True,
                    "pullback_confirmed": True,
                    "market_phase": "主升",
                })

                self.assertEqual(result["decision_code"], "observe")
                self.assertEqual(result["decision"], "暂不判断（位置信息不足）")

    def test_price_and_closes_do_not_derive_distance_when_disabled(self):
        self.assertFalse(config.ENABLE_DISTANCE_DECISION)

        result = evaluate_stock({
            "code": "NO-DERIVE",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "best_buy_point": {"price": 10.0},
            "closes": [9.8, 10.2, 10.8],
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "暂不判断（位置信息不足）")
        self.assertNotEqual(result["decision_code"], "recommend")

    def test_incomplete_fields_fallback_to_safe_decision(self):
        stock = {
            "code": "DDD",
            "name": "Delta",
            # 故意缺失核心字段
            "trend_type": None,
            "market_trend": None,
            "best_buy_point": None,
        }
        result = evaluate_stock(stock)

        self.assertEqual(result["version"], "1")
        self.assertEqual(result["decision"], "暂不判断（位置信息不足）")
        self.assertEqual(result["decision_code"], "observe")
        self.assertIsInstance(result["total_score"], (int, float))
        self.assertIn("位置信息不足", result["position"]["reasons"])
        self.assertIn("结构信息不足", result["structure"]["reasons"])
        self.assertIn("情绪信息不足", result["sentiment"]["reasons"])

    def test_market_indices_and_health_context_are_supported(self):
        stock = {
            "code": "EEE",
            "name": "Epsilon",
            "trend_type": "震荡",
            "distance_from_reference_pct": 4.0,
            "volume_ratio": 1.3,
            "gf_dma_health": {"label": "结构破坏", "trend_stage": "broken"},
        }
        result = evaluate_stock(
            stock,
            market_context={"market_indices": {"上证指数": {"change_pct": 1.2}}},
        )

        self.assertIn("主升周期", result["sentiment"]["reasons"])
        self.assertIn("趋势健康度偏弱", result["sentiment"]["reasons"])

    def test_market_drawdown_adds_sentiment_risk(self):
        result = evaluate_stock(
            {
                "code": "FFF",
                "name": "Zeta",
                "trend_type": "震荡",
                "distance_from_reference_pct": 4.0,
            },
            market_context={"market_indices": {"上证指数": {"change_pct": -1.8}}},
        )

        self.assertIn("退潮期风险", result["sentiment"]["reasons"])
        self.assertLessEqual(result["sentiment"]["score"], -30)


if __name__ == "__main__":
    unittest.main()
