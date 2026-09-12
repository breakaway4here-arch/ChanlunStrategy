import unittest

import numpy as np

from chanlun.decision_engine import evaluate_stock
from chanlun.next_day_boom import (
    _build_candidate_from_fusion,
    _build_candidate_from_watch,
    build_next_day_boom_candidates,
)
from run import _merge_next_day_source_fields


def _fusion_pick(code, name, change_pct=5.0, volume_ratio=1.5, ma_bullish=True):
    return {
        "code": code,
        "name": name,
        "score": 41,
        "ma_bullish": ma_bullish,
        "sector": "测试板块",
        "sector_tags": ["测试板块", "机器人"],
        "sector_rank": 2,
        "sector_flow": 123456,
        "sector_strength_label": "资金流入TOP2",
        "data_status": {"daily": "verified"},
        "best_buy_point": {
            "type": "强势启动候选",
            "tier": "candidate",
            "change_pct": change_pct,
            "volume_ratio": volume_ratio,
            "startup_reason": "处于60日低位区间；放量；站上MA5/MA10",
            "startup_signals": ["涨幅≥4.0%", "close_above_ma5", "close_above_ma10", "实体阳线≥3%"],
            "confirmations": ["30min EMA5维持"],
            "confirmed_by": "30min确认",
        },
    }


def _watch_item(code, name, change_pct=10.0, volume_ratio=1.5):
    return {
        "code": code,
        "name": name,
        "sector": "测试板块",
        "sector_tags": ["测试板块", "涨停"],
        "sector_rank": 3,
        "sector_flow": 654321,
        "sector_strength_label": "资金流入TOP3",
        "data_status": {"daily": "verified"},
        "type": "强势启动观察",
        "tier": "watch",
        "change_pct": change_pct,
        "volume_ratio": volume_ratio,
        "startup_reason": "低位放量涨停",
        "startup_signals": ["涨幅≥4.0%", "close_above_ma5", "close_above_ma10", "实体阳线≥3%"],
        "watch_reason": "涨停当日不追，等待次日回踩确认",
    }


class TestNextDayBoomCandidates(unittest.TestCase):

    def test_run_merge_preserves_real_trend_when_source_is_empty(self):
        merged = _merge_next_day_source_fields(
            {"code": "600001", "trend_type": "上涨趋势"},
            {"code": "600001", "trend_type": "", "closes": [10.0]},
        )
        self.assertEqual(merged["trend_type"], "上涨趋势")
        self.assertEqual(merged["closes"], [10.0])

    def test_run_merge_can_carry_source_trend_when_builder_has_no_value(self):
        merged = _merge_next_day_source_fields(
            {"code": "600002", "trend_type": ""},
            {"code": "600002", "trend_type": "上涨趋势"},
        )
        self.assertEqual(merged["trend_type"], "上涨趋势")

    def test_run_merge_accepts_ndarray_amounts_and_closes(self):
        amounts = np.array([100.0, 120.0])
        closes = np.array([10.0, 10.5])

        merged = _merge_next_day_source_fields(
            {"code": "600003"},
            {"code": "600003", "amounts": amounts, "closes": closes},
        )

        np.testing.assert_array_equal(merged["amounts"], amounts)
        np.testing.assert_array_equal(merged["closes"], closes)

    @staticmethod
    def _decision(candidate):
        enriched = dict(candidate)
        enriched.update({
            "position_data_status": "verified",
            "position_evidence_date": "2026-09-11",
            "position_absolute_percentile": 45.0,
            "position_absolute_window": 120,
        })
        return evaluate_stock(
            enriched,
            market_context={"market_trend": "上涨趋势"},
        )

    def test_builder_preserves_trend_for_downstream_decision(self):
        fusion = _fusion_pick("600001", "融合启动")
        fusion["trend_type"] = "上涨趋势"
        fusion_candidate = _build_candidate_from_fusion(
            fusion,
            fusion["best_buy_point"],
            1.2,
        )
        self.assertEqual(fusion_candidate["trend_type"], "上涨趋势")
        self.assertIn("趋势向上", self._decision(fusion_candidate)["structure"]["reasons"])

        watch = _watch_item("600002", "涨停观察")
        watch["trend_type"] = "上涨趋势"
        watch_candidate = _build_candidate_from_watch(watch, 1.2)
        self.assertEqual(watch_candidate["trend_type"], "上涨趋势")
        self.assertIn("趋势向上", self._decision(watch_candidate)["structure"]["reasons"])

    def test_missing_trend_stays_unknown_and_does_not_borrow_market_trend(self):
        candidate = _build_candidate_from_fusion(
            _fusion_pick("600003", "缺失趋势"),
            _fusion_pick("600003", "缺失趋势")["best_buy_point"],
            1.2,
        )
        self.assertEqual(candidate.get("trend_type", ""), "")
        decision = self._decision(candidate)
        # The confirmation evidence still contributes its own +15; only the
        # missing stock trend must remain without the +20 structure fact.
        self.assertEqual(decision["structure"]["score"], 10)
        self.assertIn("趋势信息不足", decision["structure"]["reasons"])

    def test_disabled_when_shanghai_not_strong(self):
        result = build_next_day_boom_candidates(
            picks_fusion=[_fusion_pick("600001", "弱市票")],
            startup_watchlist=[_watch_item("600002", "弱市观察")],
            market={"上证指数": {"change_pct": 0.8}},
        )

        self.assertEqual(result["mode"], "disabled")
        self.assertEqual(result["candidates"], [])
        self.assertIn("上证涨幅", result["reason"])

    def test_ranks_fusion_ma_startup_before_watch_when_market_strong(self):
        result = build_next_day_boom_candidates(
            picks_fusion=[_fusion_pick("600001", "融合启动", change_pct=5.2, volume_ratio=1.45)],
            startup_watchlist=[_watch_item("600002", "涨停观察", change_pct=10.0, volume_ratio=2.4)],
            market={"上证指数": {"change_pct": 1.2}},
            top_n=5,
        )

        self.assertEqual(result["mode"], "enabled")
        self.assertEqual([c["code"] for c in result["candidates"]], ["600001", "600002"])
        self.assertEqual(result["candidates"][0]["rank"], 1)
        self.assertGreater(result["candidates"][0]["boom_score"], result["candidates"][1]["boom_score"])
        self.assertEqual(result["candidates"][0]["sector_tags"], ["测试板块", "机器人"])
        self.assertEqual(result["candidates"][0]["sector_rank"], 2)
        self.assertEqual(result["candidates"][0]["sector_strength_label"], "资金流入TOP2")
        self.assertEqual(result["candidates"][0]["data_status"]["daily"], "verified")
        self.assertEqual(result["candidates"][1]["sector_tags"], ["测试板块", "涨停"])

    def test_deduplicates_same_code_with_higher_scored_source(self):
        result = build_next_day_boom_candidates(
            picks_fusion=[_fusion_pick("600001", "重复票", change_pct=5.0, volume_ratio=1.45)],
            startup_watchlist=[_watch_item("600001", "重复票", change_pct=10.0, volume_ratio=2.8)],
            market={"上证指数": {"change_pct": 1.3}},
        )

        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["source_pool"], "fusion")

    def test_volume_ratio_sweet_spot_scores_higher_than_hot_volume(self):
        result = build_next_day_boom_candidates(
            picks_fusion=[
                _fusion_pick("600001", "甜区量比", change_pct=5.0, volume_ratio=1.45),
                _fusion_pick("600002", "过热量比", change_pct=5.0, volume_ratio=3.5),
            ],
            startup_watchlist=[],
            market={"上证指数": {"change_pct": 1.5}},
        )

        self.assertEqual([c["code"] for c in result["candidates"]], ["600001", "600002"])
        self.assertIn("量比甜区", result["candidates"][0]["boom_reason"])

    def test_two_yang_confirmation_adds_boom_score_and_preserves_fields(self):
        result = build_next_day_boom_candidates(
            picks_fusion=[
                {
                    **_fusion_pick("600001", "含两阳确认", volume_ratio=1.45),
                    "best_buy_point": {
                        **_fusion_pick("600001", "含两阳确认", volume_ratio=1.45)["best_buy_point"],
                        "confirmations": ["30min两阳夹两阴确认"],
                        "confirmed_by": "30min两阳夹两阴确认",
                    },
                },
                {
                    **_fusion_pick("600002", "无确认", volume_ratio=1.45),
                    "best_buy_point": {
                        **_fusion_pick("600002", "无确认", volume_ratio=1.45)["best_buy_point"],
                        "confirmations": ["30min EMA5维持"],
                        "confirmed_by": "30min确认",
                    },
                },
            ],
            startup_watchlist=[],
            market={"上证指数": {"change_pct": 1.5}},
            top_n=2,
        )

        self.assertEqual(result["candidates"][0]["code"], "600001")
        self.assertIn("30min两阳确认", result["candidates"][0]["boom_reason"])
        self.assertEqual(
            result["candidates"][0]["confirmations"],
            ["30min两阳夹两阴确认"],
        )
        self.assertEqual(result["candidates"][0]["confirmed_by"], "30min两阳夹两阴确认")
        self.assertTrue(result["candidates"][0]["ma_bullish"])
        self.assertGreater(result["candidates"][0]["boom_score"], result["candidates"][1]["boom_score"])


if __name__ == "__main__":
    unittest.main()
