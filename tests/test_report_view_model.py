import unittest

from chanlun.report_view_model import EXCLUDED_FIELDS, build_workspace


LARGE_FIELDS = EXCLUDED_FIELDS


def _fusion_pick(
    code="600001",
    name="主推票",
    score=82,
    distance=1.8,
    change_pct=2.6,
    reason="底背驰候选强市通过",
    sector="测试板块",
    sector_tags=None,
):
    return {
        "code": code,
        "name": name,
        "sector": sector,
        "score": score,
        "best_buy_point": {
            "type": "底背驰候选",
            "reason": reason,
            "price": 10.0,
            "current_price": 10.18,
            "distance_from_reference_pct": distance,
            "change_pct": change_pct,
            "confirmed_by": "30min确认",
        },
        # Large fields intentionally present to verify they are not copied.
        "dates": ["2026-06-26"],
        "opens": [9.9],
        "highs": [10.2],
        "lows": [9.8],
        "closes": [10.18],
        "volumes": [1000],
        "macd_hist": [0.1],
        "chart_annotations": {"markLines": []},
        "buy_points": [{"type": "二买"}],
        "reference_buy_points": [{"type": "参考"}],
        "blocked_buy_points": [{"type": "拦截"}],
        "sector_tags": list(sector_tags or []),
    }


def _baseline_pick(code="600099", name="基准票"):
    pick = _fusion_pick(code=code, name=name, score=65, distance=0.7)
    pick["version"] = "picks_pure"
    return pick


def _acceleration_pick(code="600002", name="加速票", boom_score=78, change_pct=5.2):
    return {
        "code": code,
        "name": name,
        "sector": "测试板块",
        "boom_score": boom_score,
        "boom_reason": "量比甜区；低位启动",
        "change_pct": change_pct,
        "reference_price": 20.0,
        "current_price": 20.6,
    }


def _luojie_pick(code="600003", name="罗姐票", score=74):
    return {
        "code": code,
        "name": name,
        "sector": "通信设备",
        "score": score,
        "close": 31.5,
        "life_line": 31.1,
        "reason": "15min生命线不破；DIF/DEA双线0轴上",
        "tier": "主升候选",
    }


def _confirming_pick(code="600004", name="等确认票", change_pct=4.2, distance=3.1):
    return {
        "code": code,
        "name": name,
        "sector": "测试板块",
        "startup_reason": "低位放量启动",
        "watch_reason": "涨停当日不追，等待次日回踩确认",
        "change_pct": change_pct,
        "close": 12.0,
        "current_price": 12.37,
        "distance_from_reference_pct": distance,
    }


def _report_data(overrides=None):
    base = {
        "picks_fusion": [],
        "picks_pure": [],
        "next_day_boom": {"mode": "enabled", "candidates": []},
        "luojie_pool": {"candidates": []},
        "startup_watchlist": [],
    }
    if overrides:
        base.update(overrides)
    return base


class TestReportViewModel(unittest.TestCase):

    def test_workspace_shape_view_order_meta_counts_and_diagnostics(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick()],
                "picks_pure": [_baseline_pick()],
                "next_day_boom": {"mode": "enabled", "candidates": [_acceleration_pick()]},
                "luojie_pool": {"candidates": [_luojie_pick()]},
                "startup_watchlist": [_confirming_pick()],
            }
        )

        workspace = build_workspace(report_data)

        self.assertEqual(workspace["default_view"], "highlights")
        self.assertEqual(
            workspace["view_order"],
            ["highlights", "main", "acceleration", "luojie", "confirming", "baseline"],
        )
        self.assertEqual(set(workspace["views"]), set(workspace["view_order"]))
        self.assertEqual(workspace["counts"]["main"], 1)
        self.assertEqual(workspace["counts"]["baseline"], 1)
        self.assertEqual(workspace["counts"]["highlights"], 4)
        self.assertEqual(workspace["view_meta"]["highlights"]["label"], "看点 Top10")
        self.assertIn("source_counts", workspace["diagnostics"])
        self.assertEqual(workspace["diagnostics"]["highlights"]["baseline_included"], False)

    def test_baseline_never_enters_highlights(self):
        report_data = _report_data(
            {
                "picks_pure": [_baseline_pick()],
                "next_day_boom": {"mode": "enabled", "candidates": []},
            }
        )

        workspace = build_workspace(report_data)

        self.assertEqual([item["code"] for item in workspace["views"]["baseline"]], ["600099"])
        self.assertEqual(workspace["views"]["highlights"], [])

    def test_highlights_dedupe_and_resonance_label(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick(code="600010", name="共振票")],
                "next_day_boom": {
                    "mode": "enabled",
                    "candidates": [_acceleration_pick(code="600010", name="共振票")],
                },
            }
        )

        workspace = build_workspace(report_data)
        highlights = workspace["views"]["highlights"]

        self.assertEqual(len(highlights), 1)
        item = highlights[0]
        self.assertEqual(item["sources"], ["main", "acceleration"])
        self.assertEqual(item["source_labels"], ["主推", "加速"])
        self.assertEqual(item["resonance_label"], "共振·进攻")
        self.assertEqual(item["ref"]["pool"], "picks_fusion")
        self.assertIn("source:main", item["rank_trace"])
        self.assertIn("source:acceleration", item["rank_trace"])

    def test_main_opportunity_score_balances_signal_with_entry_quality(self):
        near_reference_weak = _fusion_pick(
            code="600030",
            name="近参考弱信号",
            score=18,
            distance=0.2,
            change_pct=3.0,
        )
        far_reference_strong = _fusion_pick(
            code="600031",
            name="远参考强信号",
            score=96,
            distance=11.5,
            change_pct=-1.0,
        )
        report_data = _report_data(
            {
                "picks_fusion": [near_reference_weak, far_reference_strong],
            }
        )
        workspace = build_workspace(report_data)

        self.assertEqual([item["code"] for item in workspace["views"]["main"]], ["600030", "600031"])
        self.assertEqual([item["code"] for item in workspace["views"]["highlights"]], ["600030", "600031"])

    def test_rank_trace_explains_opportunity_components_and_penalties(self):
        pick = _fusion_pick(
            code="600040",
            name="机会分解释",
            score=88,
            distance=8.5,
            change_pct=9.2,
        )
        report_data = _report_data(
            {
                "picks_fusion": [pick],
                "data_quality": {"market_status": "unverified", "fallback_used": True},
            }
        )
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        trace = item["rank_trace"]

        self.assertIn("signal_score", trace)
        self.assertIn("entry_score", trace)
        self.assertIn("momentum_score", trace)
        self.assertIn("market_score", trace)
        self.assertIn("risk_penalty", trace)
        self.assertIn("data_penalty", trace)
        self.assertIn("opportunity_score", trace)
        self.assertEqual(trace["opportunity_score"], item["opportunity_score"])
        self.assertLessEqual(trace["signal_score"], 25)
        self.assertLessEqual(trace["market_score"], 15)
        self.assertLessEqual(trace["data_penalty"], 20)
        self.assertGreaterEqual(trace["risk_penalty"], 0)
        self.assertGreaterEqual(trace["data_penalty"], 0)

    def test_confirming_score_no_longer_uses_change_pct_as_signal_proxy(self):
        report_data = _report_data(
            {
                "startup_watchlist": [
                    _confirming_pick(code="600041", name="高涨幅等确认", change_pct=18.0, distance=1.0),
                ],
            }
        )

        workspace = build_workspace(report_data)
        trace = workspace["views"]["confirming"][0]["rank_trace"]

        self.assertEqual(trace["signal_score"], 10)
        self.assertLess(trace["signal_score"], 50 + 18.0)
        self.assertLessEqual(trace["signal_score"], 10)

    def test_highlights_ranking_is_deterministic_with_equal_score(self):
        high1 = _fusion_pick(
            code="600060",
            name="排序测一号",
            score=80,
            distance=1.4,
            change_pct=1.0,
        )
        high2 = _fusion_pick(
            code="600059",
            name="排序测二号",
            score=80,
            distance=1.4,
            change_pct=1.0,
        )
        report_data = _report_data({"picks_fusion": [high1, high2]})
        workspace = build_workspace(report_data)
        highlights = workspace["views"]["highlights"]

        self.assertEqual([item["code"] for item in highlights], ["600059", "600060"])

    def test_workspace_item_has_info_tags(self):
        report_data = _report_data({"picks_fusion": [_fusion_pick()]})

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        tags = {(tag["type"], tag["label"]) for tag in item["info_tags"]}

        self.assertIn(("sector", "测试板块"), tags)
        self.assertIn(("source", "主推"), tags)
        self.assertIn(("signal", "底背驰候选"), tags)

    def test_workspace_info_tags_include_extra_sector_tags(self):
        pick = _fusion_pick(code="600005", name="半导体票", sector="电子")
        pick["sector_tags"] = ["电子", "半导体", "AI"]

        report_data = _report_data({"picks_fusion": [pick]})
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]

        sector_labels = [tag["label"] for tag in item["info_tags"] if tag["type"] == "sector"]

        self.assertIn("电子", sector_labels)
        self.assertIn("半导体", sector_labels)
        self.assertIn("AI", sector_labels)

    def test_workspace_data_badges_reflect_stale_status(self):
        pick = _fusion_pick(code="600006", name="延时票")
        pick["data_status"] = {"daily": "stale_cache"}

        report_data = _report_data({"picks_fusion": [pick]})
        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]

        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertIn("缓存兜底", badge_labels)
        self.assertIn("数据非最新", badge_labels)

    def test_workspace_does_not_claim_verified_when_market_unverified(self):
        pick = _fusion_pick(code="600007", name="非交易态票")
        report_data = _report_data(
            {
                "data_quality": {"market_status": "unverified", "fallback_used": False},
                "picks_fusion": [pick],
            }
        )

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertNotIn("数据已校验", badge_labels)

    def test_workspace_does_not_claim_verified_without_row_status(self):
        pick = _fusion_pick(code="600008", name="无状态票")
        report_data = _report_data(
            {
                "data_quality": {"market_status": "verified", "fallback_used": False},
                "picks_fusion": [pick],
            }
        )

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertNotIn("数据已校验", badge_labels)
        self.assertIn("数据状态未标记", badge_labels)

    def test_workspace_claims_verified_with_row_status(self):
        pick = _fusion_pick(code="600009", name="已校验票")
        pick["data_status"] = {"daily": "verified"}
        report_data = _report_data({"picks_fusion": [pick]})

        workspace = build_workspace(report_data)
        item = workspace["views"]["main"][0]
        badge_labels = [badge["label"] for badge in item["data_badges"]]

        self.assertIn("数据已校验", badge_labels)

    def test_no_acceleration_without_enabled_mode(self):
        report_data = _report_data(
            {
                "next_day_boom": {"mode": "disabled", "candidates": [_acceleration_pick(code="600020")]},
            }
        )
        workspace = build_workspace(report_data)

        self.assertEqual(workspace["views"]["acceleration"], [])
        self.assertEqual(workspace["views"]["highlights"], [])

    def test_no_boarding_actions_for_non_main_sources(self):
        report_data = _report_data(
            {
                "next_day_boom": {"mode": "enabled", "candidates": [_acceleration_pick(code="600020")]},
                "luojie_pool": {"candidates": [_luojie_pick(code="600021")]},
                "startup_watchlist": [_confirming_pick(code="600022")],
            }
        )
        workspace = build_workspace(report_data)

        for view_name in ("acceleration", "luojie", "confirming"):
            for item in workspace["views"][view_name]:
                self.assertIn(item["action"], {"盯盘", "慎追", "等回踩", "仅观察"})
                self.assertNotEqual(item["action"], "可上车", view_name)

    def test_workspace_items_do_not_copy_large_chart_fields(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick()],
                "next_day_boom": {"mode": "enabled", "candidates": [_acceleration_pick()]},
                "luojie_pool": {"candidates": [_luojie_pick()]},
                "startup_watchlist": [_confirming_pick()],
                "picks_pure": [_baseline_pick()],
            }
        )

        workspace = build_workspace(report_data)
        for view_name in workspace["view_order"]:
            for item in workspace["views"][view_name]:
                self.assertFalse(LARGE_FIELDS.intersection(item), view_name)
                self.assertIn("watch_score", item, view_name)
                self.assertIn("opportunity_score", item, view_name)
                self.assertEqual(item["watch_score"], item["opportunity_score"], view_name)
                self.assertIn("action_reason", item)
                self.assertIn("primary_reason", item)
                self.assertIn("risk_flags", item)
                self.assertIn("rank_trace", item)
                self.assertIn("ref", item)

    def test_conservative_risk_heuristics(self):
        report_data = _report_data(
            {
                "picks_fusion": [_fusion_pick(code="600030", distance=7.4, change_pct=8.6)],
                "next_day_boom": {"mode": "enabled", "candidates": []},
                "startup_watchlist": [_confirming_pick(code="600031", change_pct=4.0, distance=3.1)],
            }
        )

        workspace = build_workspace(report_data)
        main_item = workspace["views"]["main"][0]
        confirming_item = workspace["views"]["confirming"][0]

        self.assertEqual(main_item["action"], "慎追")
        self.assertIn("距参考价偏高", main_item["risk_flags"])
        self.assertIn("涨幅过热", main_item["risk_flags"])
        self.assertEqual(confirming_item["action"], "等回踩")
        self.assertNotEqual(confirming_item["action"], "可上车")

    def test_workspace_main_derives_change_pct_from_closes_when_pick_lacks_change_field(self):
        pick = _fusion_pick(code="600100", name="主推闭坑票")
        pick.pop("change_pct", None)
        pick["best_buy_point"].pop("change_pct", None)
        pick["closes"] = [10.0, 10.5, 10.29]
        pick["best_buy_point"]["current_price"] = 10.29

        report_data = _report_data(
            {
                "picks_fusion": [pick],
            }
        )
        workspace = build_workspace(report_data)

        main_item = workspace["views"]["main"][0]
        highlight_item = workspace["views"]["highlights"][0]

        self.assertEqual(main_item["change_pct"], -2.0)
        self.assertEqual(highlight_item["change_pct"], -2.0)
        self.assertEqual(main_item["current_price"], 10.29)

    def test_workspace_baseline_uses_pick_metric_derivation(self):
        pick = _baseline_pick(code="600101", name="基准回补票")
        pick.pop("change_pct", None)
        pick["best_buy_point"].pop("change_pct", None)
        pick["closes"] = [20.0, 21.0, 21.42]
        pick["best_buy_point"]["current_price"] = 21.42

        report_data = _report_data(
            {
                "picks_pure": [pick],
            }
        )
        workspace = build_workspace(report_data)
        item = workspace["views"]["baseline"][0]

        self.assertEqual(item["change_pct"], 2.0)
        self.assertEqual(item["current_price"], 21.42)


if __name__ == "__main__":
    unittest.main()
