import unittest

from chanlun.next_day_boom import build_next_day_boom_candidates


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


if __name__ == "__main__":
    unittest.main()
