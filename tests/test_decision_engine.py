import unittest
from unittest.mock import patch

import config

from chanlun.decision_engine import evaluate_stock


class DecisionEngineTestCase(unittest.TestCase):
    def test_fusion_owned_market_fact_is_not_scored_again(self):
        fusion_effect = {
            "fact_code": "index_above_ema50",
            "owner_pool": "picks_fusion",
            "stage": "fusion_admission",
            "effect": "gate",
            "reason_code": "fusion_weak_market_gate",
            "outcome": "admitted",
        }
        result = evaluate_stock({
            "code": "NO-DOUBLE-MARKET",
            "trend_type": "上升趋势",
            "market_regime": "weak",
            "market_effects": [fusion_effect],
            "position_data_status": "verified",
            "position_evidence_date": "2026-08-20",
            "position_absolute_percentile": 45.0,
            "position_absolute_window": 120,
        })

        self.assertNotIn("弱市风险", result["sentiment"]["reasons"])
        self.assertIn(
            "弱市风险",
            result["legacy_h4_v1"]["sentiment"]["reasons"],
        )
        index_effects = [
            row for row in result["market_effects"]
            if row["fact_code"] == "index_above_ema50"
        ]
        self.assertEqual(index_effects, [fusion_effect])

    def test_arbitrary_confirmation_text_is_not_pullback_confirmation(self):
        result = evaluate_stock({
            "code": "UNTYPED-CONFIRMATION",
            "trend_type": "上升趋势",
            "confirmed_by": "这是任意非空确认文本",
            "position_data_status": "verified",
            "position_evidence_date": "2026-08-20",
            "position_absolute_percentile": 45.0,
            "position_absolute_window": 120,
        })

        self.assertNotIn("回踩确认", result["structure"]["reasons"])

    def test_trend_continuation_uses_reference_position_not_low_position_percentile(self):
        result = evaluate_stock({
            "code": "TREND-NEAR-REFERENCE",
            "source_channel": "trend_continuation",
            "source_status": "candidate",
            "trend_type": "up",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 2.0,
            "position_reference_price": 10.0,
            "position_reference_type": "channel_reference:platform_high_20d",
            "position_data_status": "verified",
            "position_evidence_date": "2026-08-20",
            "position_absolute_percentile": 95.0,
            "position_absolute_window": 120,
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
            "change_pct": 3.0,
            "gap_pct": 1.0,
        })

        self.assertEqual(result["decision_code"], "recommend")
        self.assertIn("趋势向上", result["structure"]["reasons"])
        self.assertIn("趋势参考位附近", result["position"]["reasons"])
        self.assertNotIn("120日收盘分位高位风险", result["position"]["reasons"])

    def test_trend_continuation_overextension_is_rejected_by_own_position_contract(self):
        result = evaluate_stock({
            "code": "TREND-OVEREXTENDED",
            "source_channel": "trend_continuation",
            "source_status": "candidate",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 15.0,
            "position_reference_price": 10.0,
            "position_reference_type": "channel_reference:platform_high_20d",
            "position_data_status": "verified",
            "position_evidence_date": "2026-08-20",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
            "change_pct": 4.0,
            "gap_pct": 1.0,
        })

        self.assertEqual(result["decision_code"], "reject")
        self.assertIn("远离趋势参考位", result["position"]["reasons"])
        self.assertEqual(
            result["legacy_h4_v1"]["structure"]["score"],
            50,
        )

    def test_observation_source_status_caps_an_otherwise_recommendable_stock(self):
        result = evaluate_stock({
            "code": "SOURCE-OBSERVE",
            "source_status": "observe",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 3.0,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["source_status_cap"], "observe")
        self.assertIn("来源池", result["decision"])

    def test_insufficient_source_status_also_caps_recommendation(self):
        result = evaluate_stock({
            "code": "SOURCE-INSUFFICIENT",
            "source_status": "insufficient",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 3.0,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
            "sector_strength_label": "强",
            "volume_ratio": 1.8,
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["source_status_cap"], "observe")


    def test_verified_top_level_position_evidence_is_consumed(self):
        result = evaluate_stock({
            "code": "VERIFIED",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 3.0,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
        })

        self.assertEqual(result["decision_code"], "recommend")
        self.assertEqual(result["decision"], "推荐")
        self.assertIn("120日收盘分位低位", result["position"]["reasons"])

    def test_unverified_top_level_position_evidence_is_not_consumed(self):
        result = evaluate_stock({
            "code": "UNVERIFIED",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 3.0,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "stale_cache",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "暂不判断（位置信息不足）")

    def test_incomplete_or_invalid_position_evidence_is_not_consumed(self):
        valid = {
            "code": "INVALID-EVIDENCE",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 3.0,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
        }
        invalid_overrides = (
            {"position_data_status": "missing"},
            {"position_evidence_date": "2026/07/16"},
            {"position_absolute_percentile": None},
            {"position_absolute_window": 119},
        )

        for override in invalid_overrides:
            with self.subTest(override=override):
                result = evaluate_stock({**valid, **override})
                self.assertEqual(result["decision_code"], "observe")
                self.assertEqual(result["decision"], "暂不判断（位置信息不足）")

    def test_legacy_distance_is_not_consumed_without_verified_evidence(self):
        result = evaluate_stock({
            "code": "LEGACY",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "distance_from_reference_pct": 3.0,
            "best_buy_point": {"distance_from_reference_pct": 0.0},
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "暂不判断（位置信息不足）")

    def test_recommend_case(self):
        stock = {
            "code": "AAA",
            "name": "Alpha",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "position_distance_pct": 3,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
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
            "position_distance_pct": 12,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 45.0,
            "position_absolute_window": 120,
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
        self.assertEqual(result["position"]["reasons"][0], "120日收盘分位中位")
        self.assertIn("structure", result)
        self.assertIn("sentiment", result)

    def test_reject_high_risk_case(self):
        stock = {
            "code": "CCC",
            "name": "Gamma",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "position_distance_pct": 35,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 92.0,
            "position_absolute_window": 120,
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

    def test_best_buy_point_distance_is_ignored_even_if_derived_distance_switch_is_enabled(self):
        stock = {
            "code": "DERIVED",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "best_buy_point": {"distance_from_reference_pct": 3.0},
        }

        with patch.object(config, "ENABLE_DISTANCE_DECISION", False):
            disabled = evaluate_stock(stock)
        with patch.object(config, "ENABLE_DISTANCE_DECISION", True):
            enabled = evaluate_stock(stock)

        self.assertEqual(disabled["decision_code"], "observe")
        self.assertEqual(disabled["decision"], "暂不判断（位置信息不足）")
        self.assertEqual(enabled["decision_code"], "observe")
        self.assertEqual(enabled["decision"], "暂不判断（位置信息不足）")

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

    def test_weak_market_regime_is_mild_risk_not_full_recession(self):
        result = evaluate_stock({
            "code": "WEAK-REGIME",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_regime": "weak",
            "position_distance_pct": 1.0,
            "position_reference_price": 10.0,
            "position_reference_type": "daily_support",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
            "position_absolute_percentile": 12.0,
            "position_absolute_window": 120,
        })

        self.assertIn("弱市风险", result["sentiment"]["reasons"])
        self.assertNotIn("退潮期风险", result["sentiment"]["reasons"])
        self.assertNotIn("市场不明", result["sentiment"]["reasons"])

    def test_weak_market_with_cold_sentiment_caps_good_stock_to_observe_not_reject(self):
        result = evaluate_stock(
            {
                "code": "WEAK-COLD",
                "trend_type": "上升趋势",
                "breakout_structure": True,
                "pullback_confirmed": True,
                "market_regime": "weak",
                "position_data_status": "verified",
                "position_evidence_date": "2026-07-16",
                "position_absolute_percentile": 12.0,
                "position_absolute_window": 120,
                "sector_strength_label": "强",
                "volume_ratio": 2.0,
                "ma_bullish": True,
            },
            market_context={
                "market_sentiment": {
                    "score": 35,
                    "turning_signal": "turning_weaker",
                },
            },
        )

        self.assertEqual(result["decision_code"], "observe")
        self.assertNotEqual(result["decision"], "不推荐")

    def test_cold_market_keeps_non_high_position_candidate_as_watch_not_blanket_reject(self):
        result = evaluate_stock(
            {
                "code": "WEAK-WATCH",
                "trend_type": "",
                "pullback_confirmed": True,
                "market_regime": "weak",
                "position_data_status": "verified",
                "position_evidence_date": "2026-07-16",
                "position_absolute_percentile": 45.0,
                "position_absolute_window": 120,
                "volume_ratio": 1.8,
                "ma_bullish": True,
                "gf_dma_health": {"summary": "趋势健康度偏弱"},
            },
            market_context={
                "market_sentiment": {
                    "score": 35,
                    "turning_signal": "turning_weaker",
                },
            },
        )

        self.assertLess(result["total_score"], 40)
        self.assertEqual(result["decision_code"], "observe")
        self.assertIn("弱市只观察", result["risk_reasons"])

    def test_cold_market_does_not_rescue_high_position_reject(self):
        result = evaluate_stock(
            {
                "code": "WEAK-HIGH",
                "trend_type": "上升趋势",
                "market_regime": "weak",
                "position_data_status": "verified",
                "position_evidence_date": "2026-07-16",
                "position_absolute_percentile": 90.0,
                "position_absolute_window": 120,
            },
            market_context={"market_sentiment": {"score": 35}},
        )

        self.assertEqual(result["decision_code"], "reject")

    def test_cold_or_weakening_market_sentiment_caps_recommend_to_observe(self):
        result = evaluate_stock(
            {
                "code": "RISK-CAP",
                "trend_type": "上升趋势",
                "breakout_structure": True,
                "pullback_confirmed": True,
                "market_phase": "主升",
                "position_distance_pct": 1.0,
                "position_reference_price": 10.0,
                "position_reference_type": "daily_support",
                "position_data_status": "verified",
                "position_evidence_date": "2026-07-16",
                "position_absolute_percentile": 12.0,
                "position_absolute_window": 120,
                "sector_strength_label": "强",
                "volume_ratio": 2.0,
            },
            market_context={
                "market_sentiment": {"score": 35, "turning_signal": "turning_weaker"},
            },
        )

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "观察")
        self.assertIn("市场情绪偏冷", result["risk_reasons"])
        self.assertIn("市场情绪转弱", result["risk_reasons"])

    def test_strong_or_neutral_market_sentiment_does_not_cap_recommend(self):
        result = evaluate_stock(
            {
                "code": "NORMAL-CONTEXT",
                "trend_type": "上升趋势",
                "breakout_structure": True,
                "pullback_confirmed": True,
                "market_phase": "主升",
                "position_distance_pct": 1.0,
                "position_reference_price": 10.0,
                "position_reference_type": "daily_support",
                "position_data_status": "verified",
                "position_evidence_date": "2026-07-16",
                "position_absolute_percentile": 12.0,
                "position_absolute_window": 120,
            },
            market_context={"market_sentiment": {"score": 65, "turning_signal": "stable"}},
        )

        self.assertEqual(result["decision_code"], "recommend")

    def test_signal_distance_without_absolute_position_is_observe(self):
        result = evaluate_stock({
            "code": "SAME-DAY-STARTUP",
            "trend_type": "上升趋势",
            "breakout_structure": True,
            "pullback_confirmed": True,
            "market_phase": "主升",
            "position_distance_pct": 0.0,
            "position_reference_price": 10.0,
            "position_reference_type": "low_position_channel:daily_startup",
            "position_data_status": "verified",
            "position_evidence_date": "2026-07-16",
        })

        self.assertEqual(result["decision_code"], "observe")
        self.assertEqual(result["decision"], "暂不判断（位置信息不足）")


if __name__ == "__main__":
    unittest.main()
