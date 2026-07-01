"""Tests for report_generator — table columns, 30min确认, volumes_30min serialization, access control, startup watchlist chart."""
import hashlib
import json
import os
import re
import tempfile
import unittest
from unittest import mock
import numpy as np

from chanlun.report_generator import (
    _serialize_picks, _serialize_bp, _serialize_startup_watchlist,
    _serialize_next_day_boom, _serialize_luojie_pool,
    build_chart_window, build_chart_annotations, build_startup_watch_chart_annotations,
    _safe_list, NpEncoder, generate_report, build_recent_reviews, write_data_manifest,
    update_data_json, _backfill_workspace_scores, _serialize_picks_light,
)
from scripts.validate_today_report import validate_manifest_contract
from config import (
    ENABLE_WEAK_ACCESS_CONTROL, FULL_ACCESS_KEY, FULL_ACCESS_KEY_SALT,
    PUBLIC_DATES,
)


def _extract_bootstrap(html):
    match = re.search(r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});", html)
    if not match:
        raise AssertionError("Could not locate window.CHANLUN_BOOTSTRAP in HTML")
    return json.loads(match.group(1))


class DummyResult30min:
    def __init__(self):
        self.dates = ["2026-05-26 09:30:00", "2026-05-26 10:00:00"]
        self.opens = np.array([50.0, 51.0])
        self.highs = np.array([52.0, 53.0])
        self.lows = np.array([49.0, 50.0])
        self.closes = np.array([51.0, 52.0])
        self.volumes = np.array([1000.0, 2000.0])


class DummySegment:
    def __init__(self):
        self.start_idx = 10
        self.end_idx = 20


def make_pick(bp_type="底背驰候选", bp_tier="candidate", with_30min=True):
    n = 60
    pick = {
        "code": "600519",
        "name": "测试",
        "signal_tier": bp_tier,
        "best_buy_point": {
            "type": bp_type, "tier": bp_tier, "index": 45, "price": 50.0,
            "reason": "test reason", "strength": "强",
            "source_type": "swing底背驰参考",
            "confirmed_by": "底分型+MACD金叉+关键位不破",
            "seed_type": "swing底背驰候选种子",
            "seed_reason": "接近20日低点；接近日线中枢ZD",
        },
        "trend_type": "下跌趋势",
        "pivots": {"ZD": 48.0, "ZG": 55.0, "count": 2},
        "dates": [f"2026-05-{d:02d}" for d in range(1, n + 1)],
        "closes": np.linspace(55, 50, n),
        "opens": np.linspace(54, 49, n),
        "highs": np.linspace(56, 52, n),
        "lows": np.linspace(53, 48, n),
        "volumes": np.ones(n) * 1000,
        "macd_hist": np.zeros(n),
        "score": 85.0,
        "buy_points": [],
        "reference_buy_points": [],
        "blocked_buy_points": [],
        "buy_points_30min": [],
        "resonance": {"level": "中", "reason": "30分钟底背驰确认"},
    }
    if with_30min:
        pick["result_30min"] = DummyResult30min()
    return pick


class TestReportGenerator(unittest.TestCase):

    def test_serialize_picks_carries_decision_engine_payload(self):
        pick = make_pick()
        pick["decision_engine_v1"] = {
            "summary": "决策命中率优先",
            "score": 88.2,
            "reason": "风险平衡且趋势一致",
        }
        serialized = _serialize_picks([pick])

        self.assertEqual(serialized[0]["decision_engine_v1"], pick["decision_engine_v1"])

    def test_serialize_picks_light_carries_decision_engine_payload(self):
        pick = make_pick()
        pick["decision_engine_v1"] = {
            "version": "1",
            "decision": "推荐",
            "total_score": 72,
        }

        serialized = _serialize_picks_light([pick])

        self.assertEqual(serialized[0]["decision_engine_v1"], pick["decision_engine_v1"])

    def test_backfill_workspace_scores_syncs_decision_engine_payload(self):
        daily_data = {
            "picks_fusion": [{"code": "600001"}, {"code": "600002"}],
            "picks_pure": [{"code": "600101"}],
            "startup_watchlist": [{"code": "600201"}],
            "next_day_boom": {"candidates": [{"code": "600301"}]},
            "luojie_pool": {"candidates": [{"code": "600401"}]},
            "workspace": {
                "views": {
                    "main": [
                        {"code": "600002", "decision_engine_v1": {"summary": "main-2"}, "opportunity_score": 90, "rank_trace": {}},
                        {"code": "600001", "decision_engine_v1": {"summary": "main-1"}, "opportunity_score": 80, "rank_trace": {}},
                    ],
                    "baseline": [
                        {"code": "600101", "decision_engine_v1": {"summary": "baseline"}, "opportunity_score": 70, "rank_trace": {}},
                    ],
                    "confirming": [
                        {"code": "600201", "decision_engine_v1": {"summary": "confirming"}, "opportunity_score": 60, "rank_trace": {}},
                    ],
                    "acceleration": [
                        {"code": "600301", "decision_engine_v1": {"summary": "acceleration"}, "opportunity_score": 50, "rank_trace": {}},
                    ],
                    "luojie": [
                        {"code": "600401", "decision_engine_v1": {"summary": "luojie"}, "opportunity_score": 40, "rank_trace": {}},
                    ],
                }
            },
        }

        _backfill_workspace_scores(daily_data)

        fusion_by_code = {
            item["code"]: item["decision_engine_v1"]
            for item in daily_data["picks_fusion"]
        }
        self.assertEqual(fusion_by_code["600001"], {"summary": "main-1"})
        self.assertEqual(fusion_by_code["600002"], {"summary": "main-2"})
        self.assertEqual(daily_data["picks_pure"][0]["decision_engine_v1"], {"summary": "baseline"})
        self.assertEqual(daily_data["startup_watchlist"][0]["decision_engine_v1"], {"summary": "confirming"})
        self.assertEqual(daily_data["next_day_boom"]["candidates"][0]["decision_engine_v1"], {"summary": "acceleration"})
        self.assertEqual(daily_data["luojie_pool"]["candidates"][0]["decision_engine_v1"], {"summary": "luojie"})

    def test_serialize_picks_omits_30min_chart_arrays(self):
        """30min K线数组已从报告JSON删除，只保留确认摘要字段。"""
        pick = make_pick(with_30min=True)
        serialized = _serialize_picks([pick])
        s = serialized[0]
        for f in ("has_30min", "dates_30min", "opens_30min", "highs_30min",
                  "lows_30min", "closes_30min", "volumes_30min"):
            self.assertNotIn(f, s)
        # These fields are kept
        self.assertIn("buy_points_30min", s)

    def test_serialize_picks_json_encodable(self):
        """Serialized picks can be JSON-encoded (no numpy types leak)."""

    def test_serialize_bp_includes_30min_confirm_fields(self):
        """best_buy_point serialization preserves confirmed_by and strength."""
        bp = {
            "type": "底背驰候选", "tier": "candidate", "index": 10, "price": 45.0,
            "reason": "test", "strength": "强",
            "source_type": "swing底背驰参考",
            "confirmed_by": "底分型+MACD金叉",
            "seed_type": "swing底背驰候选种子",
            "seed_reason": "接近20日低点",
        }
        s = _serialize_bp(bp)
        self.assertEqual(s["confirmed_by"], "底分型+MACD金叉")
        self.assertEqual(s["strength"], "强")
        self.assertEqual(s["source_type"], "swing底背驰参考")

    def test_serialize_picks_has_chart_annotations(self):
        """Each pick gets chart_annotations dict."""
        pick = make_pick()
        serialized = _serialize_picks([pick])
        ann = serialized[0]["chart_annotations"]
        self.assertIsInstance(ann, dict)
        self.assertIn("markLines", ann)
        self.assertIn("markPoints", ann)

    def test_serialize_picks_includes_fusion_admission(self):
        """fusion_admission dict is serialized."""
        pick = make_pick()
        pick["fusion_admission"] = {"passed": True, "reason": "底背驰候选强市通过"}
        pick["market_regime"] = "strong"
        serialized = _serialize_picks([pick])
        s = serialized[0]
        self.assertEqual(s["fusion_admission"]["passed"], True)
        self.assertEqual(s["market_regime"], "strong")

    def test_serialize_picks_preserves_sector_and_status_metadata(self):
        pick = make_pick()
        pick["sector_tags"] = ["制造", "新能源"]
        pick["sector_rank"] = 3
        pick["sector_flow"] = {"total": 12000000}
        pick["sector_strength_label"] = "高"
        pick["data_status"] = {"daily": "verified", "bars": 20}

        serialized = _serialize_picks([pick])
        s = serialized[0]
        self.assertEqual(s["sector_tags"], ["制造", "新能源"])
        self.assertEqual(s["sector_rank"], 3)
        self.assertEqual(s["sector_flow"], {"total": 12000000})
        self.assertEqual(s["sector_strength_label"], "高")
        self.assertEqual(s["data_status"], {"daily": "verified", "bars": 20})

    def test_serialize_picks_computes_top_level_change_pct_from_latest_closes(self):
        """Candidate rows need a top-level change_pct for list rendering."""
        pick = make_pick()
        pick["closes"] = np.array([10.0, 10.5, 10.29])
        pick["dates"] = ["2026-06-26", "2026-06-29", "2026-06-30"]
        pick["best_buy_point"].pop("change_pct", None)

        serialized = _serialize_picks([pick])

        self.assertEqual(serialized[0]["change_pct"], -2.0)

    def test_build_chart_window_covers_key_points(self):
        """Window covers reference index, best_buy_point index, and latest bar."""
        pick = make_pick()
        pick["reference_buy_points"] = [{"index": 3, "type": "swing底背驰参考"}]
        pick["best_buy_point"]["index"] = 5
        start, end = build_chart_window(pick)
        self.assertLessEqual(start, 3)  # covers reference
        self.assertGreater(end, 5)       # covers best_buy_point
        self.assertGreaterEqual(end, 60) # covers latest

    def test_serialize_picks_json_encodable(self):
        """Serialized picks can be JSON-encoded (no numpy types leak)."""
        pick = make_pick()
        pick["gf_dma_health"] = {"label": "强势健康", "score": 78, "summary": "趋势健康"}
        serialized = _serialize_picks([pick])
        encoded = json.dumps(serialized, cls=NpEncoder)
        decoded = json.loads(encoded)
        self.assertEqual(decoded[0]["code"], "600519")
        self.assertIn("gf_dma_health", decoded[0])
        self.assertEqual(decoded[0]["gf_dma_health"]["label"], "强势健康")
        self.assertIn("buy_points_30min", decoded[0])
        self.assertEqual(decoded[0]["buy_points_30min"], [])

    def test_serialize_picks_sanitizes_signal_context_runtime_objects(self):
        """Signal classifier context may contain runtime ChanLun objects."""
        pick = make_pick()
        pick["best_buy_point"]["context"] = {
            "trend_strength": 1.0,
            "volatility": 0.05,
            "market_env": "weak",
            "signal_type": "强势启动候选",
            "pivot": object(),
            "segment": DummySegment(),
        }
        serialized = _serialize_picks([pick])
        encoded = json.dumps(serialized, cls=NpEncoder)
        decoded = json.loads(encoded)
        context = decoded[0]["best_buy_point"]["context"]
        self.assertEqual(context["trend_strength"], 1.0)
        self.assertEqual(context["market_env"], "weak")
        self.assertTrue(context["has_pivot"])
        self.assertTrue(context["has_segment"])
        self.assertNotIn("pivot", context)
        self.assertNotIn("segment", context)


def _make_minimal_report_data():
    return {
        "date": "2026-05-26",
        "market": {},
        "chanlun_structure": {},
        "picks_pure": [],
        "picks_fusion": [],
        "sector_flow": [],
        "sector_outflow": [],
        "limit_up_pool": [],
        "events": [],
        "forecast": {},
        "sell_signals": [],
        "diagnostics": {},
    }


class TestAccessControl(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_ac_")
        report_data = _make_minimal_report_data()
        generate_report(report_data, output_dir=cls.tmpdir)
        html_path = os.path.join(cls.tmpdir, "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            cls.html = f.read()
        cls.bootstrap = _extract_bootstrap(cls.html)
        with open(os.path.join(cls.tmpdir, "data", "2026-05-26.json"), "r", encoding="utf-8") as f:
            cls.day_data = json.load(f)
        with open(os.path.join(cls.tmpdir, "assets", "report-v2.js"), "r", encoding="utf-8") as f:
            cls.asset_js = f.read()
        with open(os.path.join(cls.tmpdir, "assets", "report-v2.css"), "r", encoding="utf-8") as f:
            cls.asset_css = f.read()

    def test_bootstrap_payload_present(self):
        self.assertIn("window.CHANLUN_BOOTSTRAP", self.html)
        self.assertIn('"pageDate"', self.html)
        self.assertIn('"inlineReportData"', self.html)

    def test_no_plaintext_access_key_in_html(self):
        """HTML must NOT contain the plaintext ACCESS_KEY."""
        self.assertNotIn(FULL_ACCESS_KEY, self.html)

    def test_access_key_hash_in_html(self):
        """HTML contains ACCESS_KEY_HASH (sha256 hex of key+salt)."""
        expected_hash = hashlib.sha256(
            (FULL_ACCESS_KEY + FULL_ACCESS_KEY_SALT).encode()
        ).hexdigest()
        self.assertIn(expected_hash, self.html)

    def test_access_key_salt_in_html(self):
        """HTML contains ACCESS_KEY_SALT."""
        self.assertIn(FULL_ACCESS_KEY_SALT, self.html)

    def test_bootstrap_access_control_fields(self):
        self.assertEqual(self.bootstrap.get("accessControlEnabled"), True if ENABLE_WEAK_ACCESS_CONTROL and FULL_ACCESS_KEY else False)
        self.assertIn("accessKeyHash", self.bootstrap)
        self.assertIn("accessKeySalt", self.bootstrap)
        self.assertEqual(self.bootstrap.get("pageDate"), "2026-05-26")
        self.assertIn("inlineReportData", self.bootstrap)
        self.assertIn("market", self.bootstrap["inlineReportData"])

    def test_no_public_dates_in_html(self):
        """HTML no longer embeds the public-date allowlist."""
        self.assertNotIn("ACCESS_PUBLIC_DATES", self.html)
        self.assertNotIn(json.dumps(PUBLIC_DATES), self.html)

    def test_access_control_bootstrap_bootstrapped_values(self):
        expected_hash = hashlib.sha256(
            (FULL_ACCESS_KEY + FULL_ACCESS_KEY_SALT).encode()
        ).hexdigest()
        self.assertEqual(expected_hash, self.bootstrap.get("accessKeyHash"))
        self.assertIn(FULL_ACCESS_KEY_SALT, self.bootstrap.get("accessKeySalt", ""))

    def test_assets_and_bootstrap_paths(self):
        self.assertIn("assets/report-v2.css", self.html)
        self.assertIn("assets/report-v2.js", self.html)
        self.assertRegex(self.html, r"assets/report-v2\.css\?v=[0-9a-f]{12}")
        self.assertRegex(self.html, r"assets/report-v2\.js\?v=[0-9a-f]{12}")
        self.assertIn("window.location.protocol === 'file:'", self.html)
        self.assertIn("dataBasePrefix", self.html)
        self.assertIn("window.CHANLUN_BOOTSTRAP.dataBasePrefix = dataBasePrefix;", self.html)

    def test_v2_asset_enforces_archive_access_control(self):
        self.assertIn("function resolveGranted()", self.asset_js)
        self.assertIn("crypto.subtle.digest('SHA-256'", self.asset_js)
        self.assertIn("if (!state.granted && bootstrap.dataBasePrefix)", self.asset_js)
        self.assertIn("return Promise.reject(new Error('暂无日报数据'))", self.asset_js)

    def test_v2_asset_uses_correct_raw_pools_and_kline_order(self):
        self.assertIn("var nextDayBoom = data.next_day_boom;", self.asset_js)
        self.assertIn("next_day_boom: asArray((nextDayBoom && nextDayBoom.candidates) || [])", self.asset_js)
        self.assertIn("return pools.next_day_boom;", self.asset_js)
        self.assertIn("function hasChartData(item)", self.asset_js)
        self.assertIn("function mergeChartCandidate(primary, chartSource)", self.asset_js)
        self.assertIn("findChartCandidate(targetCode, found)", self.asset_js)
        self.assertIn("opens[i],\n        closes[i],\n        lows[i],\n        highs[i]", self.asset_js)

    def test_v2_asset_has_mobile_and_long_pool_interaction_guards(self):
        self.assertIn('class="candidate-list-shell"', self.asset_js)
        self.assertIn('class="mobile-drawer-toolbar"', self.asset_js)
        self.assertIn('class="mobile-drawer-floating-close"', self.asset_js)
        self.assertIn("nodes.drawerPanel.scrollTop = 0;", self.asset_js)
        self.assertIn("function syncMobileDrawerViewport()", self.asset_js)
        self.assertIn("window.visualViewport", self.asset_js)
        self.assertIn("图钉为买点/信号标记", self.asset_js)
        self.assertIn("@media (min-width: 1181px)", self.asset_css)
        self.assertIn(".candidate-list-shell", self.asset_css)
        self.assertIn("max-height: calc(100vh - 230px);", self.asset_css)
        self.assertIn(".mobile-drawer-toolbar", self.asset_css)
        self.assertIn(".mobile-drawer-floating-close", self.asset_css)
        self.assertIn("var(--mobile-drawer-bottom-offset, 16px)", self.asset_css)
        self.assertIn("min-width: 76px;", self.asset_css)
        self.assertIn("height: 42px;", self.asset_css)

    def test_v2_asset_contains_decision_engine_summary_block(self):
        self.assertIn("getDecisionEngineSummary", self.asset_js)
        self.assertIn("决策评分摘要", self.asset_js)

    def test_no_old_access_key_var(self):
        """HTML does not contain the old var ACCESS_KEY = 'plaintext' pattern."""
        self.assertNotIn('var ACCESS_KEY = "', self.html)

    def test_no_old_render_limited_view_blocking(self):
        """renderLimitedView is no longer called to block all rendering."""
        self.assertNotIn("renderLimitedView();", self.html)

    def test_no_public_notice_banner(self):
        """renderPublicNotice is removed — unauthorized users are silently restricted."""
        self.assertNotIn("function renderPublicNotice", self.html)

    def test_no_date_fallback_notice(self):
        """renderDateFallbackNotice is removed — date fallback is silent."""
        self.assertNotIn("function renderDateFallbackNotice", self.html)

    def test_report_assets_copied(self):
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "assets", "report-v2.css")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "assets", "report-v2.js")))
        source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source_css = os.path.join(source_root, "chanlun", "report_assets", "report-v2.css")
        source_js = os.path.join(source_root, "chanlun", "report_assets", "report-v2.js")
        with open(os.path.join(self.tmpdir, "assets", "report-v2.css"), "rb") as f:
            with open(source_css, "rb") as src:
                self.assertEqual(f.read(), src.read())
        with open(os.path.join(self.tmpdir, "assets", "report-v2.js"), "rb") as f:
            with open(source_js, "rb") as src:
                self.assertEqual(f.read(), src.read())

    def test_workspace_bootstrap_in_json(self):
        self.assertIn("workspace", self.day_data)
        self.assertEqual(self.day_data["workspace"].get("default_view"), "highlights")

    def test_raw_pools_are_backfilled_and_sorted_by_workspace_opportunity_score(self):
        tmpdir = tempfile.mkdtemp(prefix="test_score_backfill_")
        near_main = make_pick()
        near_main["code"] = "600100"
        near_main["score"] = 18
        near_main["best_buy_point"]["distance_from_reference_pct"] = 0.2
        near_main["best_buy_point"]["change_pct"] = 3.0
        far_main = make_pick()
        far_main["code"] = "600101"
        far_main["score"] = 96
        far_main["best_buy_point"]["distance_from_reference_pct"] = 11.5
        far_main["best_buy_point"]["change_pct"] = -1.0
        report_data = _make_minimal_report_data()
        report_data["picks_fusion"] = [far_main, near_main]
        report_data["next_day_boom"] = {
            "mode": "enabled",
            "candidates": [
                {
                    "rank": 1,
                    "code": "600201",
                    "name": "高分偏远加速",
                    "boom_score": 95,
                    "reference_price": 10.0,
                    "current_price": 11.2,
                    "change_pct": -1.0,
                    "data_status": {"daily": "verified"},
                },
                {
                    "rank": 2,
                    "code": "600200",
                    "name": "低分近位加速",
                    "boom_score": 20,
                    "reference_price": 10.0,
                    "current_price": 10.02,
                    "change_pct": 3.0,
                    "data_status": {"daily": "verified"},
                },
            ],
        }
        report_data["luojie_pool"] = {
            "mode": "enabled",
            "candidates": [
                {
                    "rank": 1,
                    "code": "600301",
                    "name": "高分偏远罗姐",
                    "score": 90,
                    "close": 11.5,
                    "life_line": 10.0,
                    "change_pct": -1.0,
                    "data_status": {"daily": "verified"},
                },
                {
                    "rank": 2,
                    "code": "600300",
                    "name": "低分近位罗姐",
                    "score": 20,
                    "close": 10.02,
                    "life_line": 10.0,
                    "change_pct": 3.0,
                    "data_status": {"daily": "verified"},
                },
            ],
        }

        generate_report(report_data, output_dir=tmpdir)
        update_data_json(report_data, output_dir=tmpdir)
        with open(os.path.join(tmpdir, "data", "2026-05-26.json"), "r", encoding="utf-8") as f:
            day_data = json.load(f)
        with open(os.path.join(tmpdir, "data.json"), "r", encoding="utf-8") as f:
            aggregate_data = json.load(f)["reports"]["2026-05-26"]

        for payload in (day_data, aggregate_data):
            self.assertEqual([p["code"] for p in payload["picks_fusion"]], ["600100", "600101"])
            self.assertEqual(
                [c["code"] for c in payload["next_day_boom"]["candidates"]],
                ["600200", "600201"],
            )
            self.assertEqual(
                [c["code"] for c in payload["luojie_pool"]["candidates"]],
                ["600300", "600301"],
            )
            for pool_items in (
                payload["picks_fusion"],
                payload["next_day_boom"]["candidates"],
                payload["luojie_pool"]["candidates"],
            ):
                self.assertGreaterEqual(pool_items[0]["opportunity_score"], pool_items[1]["opportunity_score"])
                for item in pool_items:
                    self.assertIn("opportunity_score", item)
                    self.assertIn("watch_score", item)
                    self.assertIn("view_rank", item)
                    self.assertIn("rank_trace", item)


class TestStartupWatchlistSerialization(unittest.TestCase):

    def _make_watch_item(self, with_chart=True):
        n = 60
        item = {
            "code": "000001",
            "name": "测试股",
            "sector": "测试板块",
            "type": "强势启动观察",
            "tier": "watch",
            "source_type": "日线强势启动",
            "startup_reason": "放量突破",
            "startup_signals": ["涨停", "放量"],
            "startup_index": 55,
            "startup_date": "2026-05-26",
            "startup_age_days": 0,
            "change_pct": 9.5,
            "volume_ratio": 2.5,
            "close": 15.00,
            "avoid_chase": True,
            "watch_reason": "等待回踩确认",
            "next_day_conditions": ["回踩不破突破位", "30min二买/三买"],
            "is_recent": True,
            "recency_reason": "信号发生在最近0个交易日内",
        }
        if with_chart:
            item["dates"] = [f"2026-05-{d:02d}" for d in range(1, n + 1)]
            item["closes"] = np.array([10.0 + i * 0.1 for i in range(n)])
            item["opens"] = np.array([10.0 + i * 0.1 - 0.05 for i in range(n)])
            item["highs"] = np.array([10.0 + i * 0.1 + 0.1 for i in range(n)])
            item["lows"] = np.array([10.0 + i * 0.1 - 0.15 for i in range(n)])
            item["volumes"] = np.array([10000.0 + i * 100 for i in range(n)])
        return item

    def test_serialized_has_chart_arrays(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        sw = result[0]
        self.assertIn("dates", sw)
        self.assertIn("closes", sw)
        self.assertIn("opens", sw)
        self.assertIn("highs", sw)
        self.assertIn("lows", sw)
        self.assertIn("volumes", sw)
        self.assertIn("macd_hist", sw)
        self.assertIn("chart_annotations", sw)
        self.assertIn("sector", sw)
        self.assertIn("daily_startup_label", sw)
        self.assertIn("sublevel_confirm_label", sw)
        self.assertIsInstance(sw["dates"], list)
        self.assertIsInstance(sw["closes"], list)

    def test_chart_arrays_same_length(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        sw = result[0]
        n = len(sw["dates"])
        self.assertEqual(len(sw["closes"]), n)
        self.assertEqual(len(sw["opens"]), n)
        self.assertEqual(len(sw["highs"]), n)
        self.assertEqual(len(sw["lows"]), n)
        self.assertEqual(len(sw["volumes"]), n)
        self.assertEqual(len(sw["macd_hist"]), n)

    def test_no_30min_fields(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        sw = result[0]
        self.assertNotIn("has_30min", sw)
        self.assertNotIn("dates_30min", sw)
        self.assertNotIn("closes_30min", sw)
        self.assertNotIn("opens_30min", sw)
        self.assertNotIn("highs_30min", sw)
        self.assertNotIn("lows_30min", sw)
        self.assertNotIn("volumes_30min", sw)

    def test_empty_input_no_crash(self):
        result = _serialize_startup_watchlist([])
        self.assertEqual(result, [])

    def test_no_chart_data_no_crash(self):
        items = self._make_watch_item(with_chart=False)
        result = _serialize_startup_watchlist([items])
        sw = result[0]
        self.assertEqual(sw["closes"], [])

    def test_annotations_has_marklines(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        ann = result[0]["chart_annotations"]
        self.assertIn("markLines", ann)
        self.assertIn("markPoints", ann)
        self.assertIn("labels", ann)
        self.assertGreater(len(ann["markLines"]), 0, "Should have at least reference price and current price lines")

    def test_annotations_has_startup_markpoint(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        ann = result[0]["chart_annotations"]
        self.assertGreater(len(ann["markPoints"]), 0, "Should have startup day markPoint")
        mp = ann["markPoints"][0]
        self.assertEqual(mp["symbol"], "triangle")

    def test_near_expiry_label(self):
        items = self._make_watch_item()
        items["startup_age_days"] = 9
        result = _serialize_startup_watchlist([items])
        ann = result[0]["chart_annotations"]
        labels = ann.get("labels", [])
        expiry_labels = [l for l in labels if "接近过期" in str(l)]
        self.assertGreater(len(expiry_labels), 0)

    def test_current_price_present(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        sw = result[0]
        self.assertGreater(sw["current_price"], 0)

    def test_json_encodable(self):
        items = self._make_watch_item()
        result = _serialize_startup_watchlist([items])
        json.dumps(result, cls=NpEncoder)

    def test_preserves_sector_and_status_metadata(self):
        items = self._make_watch_item()
        items["sector_tags"] = ["测试板块", "机器人"]
        items["sector_rank"] = 4
        items["sector_flow"] = 123456
        items["sector_strength_label"] = "资金流入TOP4"
        items["data_status"] = {"daily": "verified", "latest_date": "2026-05-26"}

        result = _serialize_startup_watchlist([items])
        sw = result[0]

        self.assertEqual(sw["sector_tags"], ["测试板块", "机器人"])
        self.assertEqual(sw["sector_rank"], 4)
        self.assertEqual(sw["sector_flow"], 123456)
        self.assertEqual(sw["sector_strength_label"], "资金流入TOP4")
        self.assertEqual(sw["data_status"]["daily"], "verified")


class TestBuildStartupWatchChartAnnotations(unittest.TestCase):

    def test_annotations_structure(self):
        watch_item = {
            "startup_index": 50,
            "close": 10.0,
            "startup_age_days": 5,
        }
        dates = [f"2026-05-{d:02d}" for d in range(1, 61)]
        closes = [10.0] * 60
        result = build_startup_watch_chart_annotations(watch_item, 0, dates, closes)
        self.assertIn("markLines", result)
        self.assertIn("markPoints", result)
        self.assertIn("labels", result)
        self.assertGreaterEqual(len(result["markLines"]), 2)

    def test_markpoint_triangle(self):
        watch_item = {
            "startup_index": 55,
            "close": 10.0,
            "startup_age_days": 1,
        }
        dates = [f"2026-05-{d:02d}" for d in range(1, 61)]
        closes = [10.0] * 60
        result = build_startup_watch_chart_annotations(watch_item, 0, dates, closes)
        mp = result["markPoints"]
        self.assertEqual(len(mp), 1)
        self.assertEqual(mp[0]["symbol"], "triangle")

    def test_no_startup_index_no_markpoint(self):
        watch_item = {
            "startup_index": None,
            "close": 10.0,
        }
        dates = [f"2026-05-{d:02d}" for d in range(1, 61)]
        closes = [10.0] * 60
        result = build_startup_watch_chart_annotations(watch_item, 0, dates, closes)
        self.assertEqual(len(result["markPoints"]), 0)

    def test_no_reference_price_no_markline(self):
        watch_item = {
            "startup_index": 50,
            "close": 0,
        }
        result = build_startup_watch_chart_annotations(watch_item, 0, [], [])
        # Should not crash, just no ref markLine
        ref_lines = [ml for ml in result["markLines"] if ml.get("name") == "source"]
        self.assertEqual(len(ref_lines), 0)


class TestBuildRecentReviews(unittest.TestCase):

    def test_computes_current_change_even_when_recommendation_date_missing_from_kline(self):
        with tempfile.TemporaryDirectory(prefix="test_recent_reviews_") as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({"dates": ["2026-06-19", "2026-06-29"], "latest": "2026-06-29"}, f)
            with open(os.path.join(data_dir, "2026-06-19.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "picks_fusion": [{
                        "code": "000001",
                        "name": "回看样例",
                        "best_buy_point": {"type": "强势启动候选", "price": 10.0},
                        "stop_loss": 8.0,
                    }]
                }, f)

            kline = {
                "dates": ["2026-06-20", "2026-06-29"],
                "closes": [11.0, 12.0],
                "lows": [10.5, 11.5],
            }
            with mock.patch("chanlun.data_fetcher.fetch_daily_kline", return_value=kline):
                rows = build_recent_reviews("2026-06-29", tmpdir)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ref_price"], 10.0)
        self.assertEqual(rows[0]["current_price"], 12.0)
        self.assertEqual(rows[0]["change_pct"], 20.0)
        self.assertEqual(rows[0]["lookback_days"], 2)

    def test_uses_trading_dates_and_marks_stale_or_verified(self):
        with tempfile.TemporaryDirectory(prefix="test_recent_reviews_") as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "dates": ["2026-06-20", "2026-06-29"],
                    "trading_dates": ["2026-06-29"],
                    "latest": "2026-06-30",
                    "latest_trading_date": "2026-06-29",
                }, f)
            with open(os.path.join(data_dir, "2026-06-20.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "picks_fusion": [{
                        "code": "000001",
                        "name": "应跳过",
                        "best_buy_point": {"type": "强势启动候选", "price": 9.0},
                        "stop_loss": 8.0,
                    }]
                }, f)
            with open(os.path.join(data_dir, "2026-06-29.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "picks_fusion": [{
                        "code": "000002",
                        "name": "回看样例",
                        "best_buy_point": {"type": "强势启动候选", "price": 10.0},
                        "stop_loss": 8.0,
                    }]
                }, f)

            kline = {
                "dates": ["2026-06-20", "2026-06-29"],
                "closes": [11.0, 12.0],
                "lows": [10.5, 11.5],
            }
            with mock.patch("chanlun.data_fetcher.fetch_daily_kline", return_value=kline):
                rows = build_recent_reviews("2026-06-30", tmpdir)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "000002")
        self.assertEqual(rows[0]["current_date"], "2026-06-29")
        self.assertEqual(rows[0]["data_status"], "stale_cache")

    def test_build_recent_reviews_missing_kline_marks_missing_status(self):
        with tempfile.TemporaryDirectory(prefix="test_recent_reviews_") as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "dates": ["2026-06-29"],
                    "trading_dates": ["2026-06-29"],
                    "latest": "2026-06-30",
                    "latest_trading_date": "2026-06-29",
                }, f)
            with open(os.path.join(data_dir, "2026-06-29.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "picks_fusion": [{
                        "code": "000001",
                        "name": "回看样例",
                        "best_buy_point": {"type": "强势启动候选", "price": 10.0},
                        "stop_loss": 8.0,
                    }]
                }, f)

            with mock.patch("chanlun.data_fetcher.fetch_daily_kline", return_value=None):
                rows = build_recent_reviews("2026-06-30", tmpdir)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "000001")
        self.assertEqual(rows[0]["data_status"], "missing")
        self.assertEqual(rows[0]["current_price"], None)
        self.assertEqual(rows[0]["current_date"], "")


class TestDataManifestAndQuality(unittest.TestCase):

    def test_manifest_keeps_trading_dates_separate_from_dates(self):
        with tempfile.TemporaryDirectory(prefix="test_manifest_") as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            write_data_manifest("2026-06-20", data_dir, is_trading_day=False, is_official=False)
            write_data_manifest("2026-06-30", data_dir, is_trading_day=True, is_official=True)

            with open(os.path.join(data_dir, "index.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)

        self.assertIn("2026-06-20", manifest["dates"])
        self.assertNotIn("2026-06-20", manifest["trading_dates"])
        self.assertIn("2026-06-30", manifest["dates"])
        self.assertIn("2026-06-30", manifest["trading_dates"])
        self.assertEqual(manifest["latest"], "2026-06-30")
        self.assertEqual(manifest["latest_trading_date"], "2026-06-30")

    def test_manifest_handles_old_manifest_when_writing_non_trading_date(self):
        with tempfile.TemporaryDirectory(prefix="test_manifest_") as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            old_manifest = {
                "dates": ["2026-06-29"],
                "latest": "2026-06-29",
            }
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump(old_manifest, f, ensure_ascii=False, indent=2)

            write_data_manifest("2026-06-30", data_dir, is_trading_day=False, is_official=False)

            with open(os.path.join(data_dir, "index.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)

        self.assertEqual(manifest["trading_dates"], ["2026-06-29"])
        self.assertEqual(manifest["latest"], "2026-06-30")
        self.assertEqual(manifest["latest_trading_date"], "2026-06-29")
        self.assertEqual(manifest["date_meta"]["2026-06-30"]["is_trading_day"], False)

    def test_manifest_refuses_non_trading_date_from_existing_date_meta(self):
        with tempfile.TemporaryDirectory(prefix="test_manifest_") as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            old_manifest = {
                "dates": ["2026-06-29", "2026-06-30", "2026-06-29"],
                "trading_dates": ["2026-06-29", "2026-06-30", "2026-05-01"],
                "latest": "2026-06-29",
                "latest_trading_date": "2026-06-30",
                "date_meta": {
                    "2026-06-29": {"is_trading_day": True, "is_official": True},
                    "2026-06-30": {"is_trading_day": False, "is_official": True},
                },
            }
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
                json.dump(old_manifest, f, ensure_ascii=False, indent=2)

            write_data_manifest("2026-06-30", data_dir, is_trading_day=False, is_official=False)

            with open(os.path.join(data_dir, "index.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)

        self.assertEqual(manifest["trading_dates"], ["2026-06-29"])
        self.assertEqual(manifest["latest_trading_date"], "2026-06-29")
        self.assertEqual(manifest["latest"], "2026-06-30")

    def test_validate_manifest_contract(self):
        manifest_ok = {
            "dates": ["2026-06-29", "2026-06-30"],
            "trading_dates": ["2026-06-29", "2026-06-30"],
            "latest": "2026-06-30",
            "latest_trading_date": "2026-06-30",
            "date_meta": {
                "2026-06-29": {"is_trading_day": True, "is_official": True},
                "2026-06-30": {"is_trading_day": True, "is_official": False},
            },
        }
        manifest_bad = {
            "dates": ["2026-06-29", "2026-06-30"],
            "trading_dates": ["2026-06-29", "2026-06-30"],
            "latest": "2026-06-30",
            "latest_trading_date": "2026-06-30",
            "date_meta": {
                "2026-06-29": {"is_trading_day": True, "is_official": True},
                "2026-06-30": {"is_trading_day": False, "is_official": False},
            },
        }

        self.assertEqual(validate_manifest_contract(manifest_ok), [])

        errors = validate_manifest_contract(manifest_bad)
        # latest_trading_date points to a non-trading day
        self.assertTrue(any("non-trading day" in err for err in errors))

    def test_data_quality_written_to_daily_json_and_data_json(self):
        with tempfile.TemporaryDirectory(prefix="test_dq_") as tmpdir:
            report_data = _make_minimal_report_data()
            report_data["date"] = "2026-06-30"
            report_data["data_quality"] = {
                "is_trading_day": True,
                "is_official": True,
                "market_status": "verified",
            }

            generate_report(report_data, output_dir=tmpdir)
            update_data_json(report_data, output_dir=tmpdir)

            with open(os.path.join(tmpdir, "data", "2026-06-30.json"), "r", encoding="utf-8") as f:
                daily_data = json.load(f)
            with open(os.path.join(tmpdir, "data", "index.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)
            with open(os.path.join(tmpdir, "data.json"), "r", encoding="utf-8") as f:
                aggregate = json.load(f)

        self.assertEqual(daily_data["data_quality"], report_data["data_quality"])
        self.assertEqual(manifest["latest"], "2026-06-30")
        self.assertEqual(manifest["date_meta"]["2026-06-30"], {
            "is_trading_day": True,
            "is_official": True,
        })
        self.assertEqual(aggregate["reports"]["2026-06-30"]["data_quality"], report_data["data_quality"])


class TestHTMLEscape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_esc_")
        report_data = _make_minimal_report_data()
        report_data["events"] = [{
            "title": "<img src=x onerror=alert(1)>",
            "display_title": "<script>alert('xss')</script>",
            "content": "<b>bold</b>",
            "brief": "brief & more",
            "level": 1,
            "event_category": "policy",
            "event_category_name": "政策催化",
            "impact_score": 20,
            "impact_level": "一般",
            "impact_reason": "<script>bad</script>",
            "affected_themes": ["<img onerror=alert(1)>"],
            "matched_hot_sectors": ["<b>x</b>"],
            "downgrade_reasons": ["<script>alert(2)</script>"],
            "market_validation": "<img src=x>",
            "impact": {
                "headline": "<script>alert(3)</script>",
                "analysis": ["<img onerror=alert(4)>", "normal text"],
                "positive_sectors": ["<b>sector</b>"],
                "negative_sectors": [],
                "positive_stocks": [{"name": "<script>x</script>", "code": "000001", "reason": "<img>"}],
                "negative_stocks": [],
            },
        }]
        report_data["picks_fusion"] = [{
            "code": "<script>x</script>",
            "name": "<img src=x>",
            "sector": "<svg onload=alert(9)>",
            "best_buy_point": {
                "type": "强势启动候选",
                "reason": "<b>reason</b>",
                "startup_reason": "<script>alert(5)</script>",
                "confirmed_by": "<img src=x>",
                "confirmations": ["<b>conf</b>"],
                "daily_startup_grade": "strong",
                "daily_startup_label": "<x>",
                "daily_startup_warning": "<script>warn</script>",
                "sublevel_confirm_grade": "A",
                "sublevel_confirm_label": "A级确认",
                "sublevel_confirm_reason": "<b>reason</b>",
                "signal_date": "2026-05-26",
                "reference_price": 10,
                "current_price": 12,
            },
            "closes": [10.0] * 60,
            "opens": [10.0] * 60,
            "highs": [10.0] * 60,
            "lows": [10.0] * 60,
            "volumes": [1000.0] * 60,
            "dates": ["2026-05-{:02d}".format(d) for d in range(1, 61)],
            "macd_hist": [0.1] * 60,
            "buy_points": [],
            "buy_points_30min": [],
            "reference_buy_points": [],
            "blocked_buy_points": [],
            "pivots": {},
            "score": 10,
        }]
        report_data["startup_watchlist"] = [{
            "code": "<img src=x>",
            "name": "<script>alert(6)</script>",
            "sector": "<svg onload=alert(10)>",
            "type": "强势启动观察",
            "startup_reason": "<b>reason</b>",
            "watch_reason": "<script>bad</script>",
            "next_day_conditions": ["<img onerror=alert(7)>"],
            "startup_age_days": 0,
            "close": 10,
            "current_price": 12,
            "distance_from_reference_pct": 20,
            "startup_date": "2026-05-26",
            "source_type": "<b>source</b>",
            "startup_signals": ["<script>x</script>"],
            "recency_reason": "<img src=x>",
            "closes": [10.0] * 60,
            "opens": [10.0] * 60,
            "highs": [10.0] * 60,
            "lows": [10.0] * 60,
            "volumes": [1000.0] * 60,
            "dates": ["2026-05-{:02d}".format(d) for d in range(1, 61)],
        }]
        report_data["sell_signals"] = [{
            "code": "<script>x</script>",
            "name": "<img src=x>",
            "sell_points": [{"type": "<b>sell</b>", "reason": "<script>bad</script>"}],
            "sector": "<img src=x>",
            "trend_type": "<b>trend</b>",
        }]
        report_data["limit_up_pool"] = [{
            "name": "<script>alert(8)</script>",
            "code": "000001",
            "sector": "<img src=x>",
        }]
        report_data["sector_outflow"] = [{
            "name": "<b>outflow</b>",
            "change_pct": -1.5,
            "flow_str": "-1.23亿",
        }]
        generate_report(report_data, output_dir=cls.tmpdir)
        html_path = os.path.join(cls.tmpdir, "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_no_unescaped_script_tags(self):
        self.assertNotIn("<script>alert('xss')</script>", self.html)
        self.assertNotIn("<script>alert(1)</script>", self.html)
        self.assertNotIn("<script>alert(2)</script>", self.html)
        self.assertNotIn("<script>alert(3)</script>", self.html)
        self.assertNotIn("<script>alert(5)</script>", self.html)
        self.assertNotIn("<script>alert(6)</script>", self.html)
        self.assertNotIn("<script>alert(8)</script>", self.html)
        self.assertNotIn("<script>x</script>", self.html)
        self.assertNotIn("<script>bad</script>", self.html)
        self.assertNotIn("<svg onload=alert(9)>", self.html)
        self.assertNotIn("<svg onload=alert(10)>", self.html)

    def test_startup_and_pick_headers_rendered(self):
        self.assertIn('<div id="app"></div>', self.html)
        self.assertNotIn("<th>板块</th>", self.html)
        self.assertNotIn("<th>启动形态</th>", self.html)
        self.assertNotIn("<th>30min确认</th>", self.html)


class TestMarketCardRendering(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_market_cards_")
        report_data = _make_minimal_report_data()
        report_data["market"] = {
            "上证指数": {"close": "", "change_pct": 0.0},
            "深证成指": {"close": "bad-data", "change_pct": 1.23},
        }
        generate_report(report_data, output_dir=cls.tmpdir)
        html_path = os.path.join(cls.tmpdir, "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_market_card_uses_finite_number_guard(self):
        self.assertIn('"market":', self.html)
        self.assertIn('"上证指数":', self.html)
        self.assertIn('"深证成指":', self.html)

    def test_market_card_does_not_embed_nan_fallback(self):
        self.assertNotIn("<script>warn</script>", self.html)

    def test_no_img_onerror(self):
        self.assertNotIn("onerror=alert(1)", self.html)
        self.assertNotIn("onerror=alert(4)", self.html)
        self.assertNotIn("onerror=alert(7)", self.html)

    def test_escapeHtml_function_defined(self):
        self.assertNotIn("function escapeHtml(value)", self.html)

    def test_no_raw_html_in_js_innerHTML(self):
        """Verify all dynamic text in JS is wrapped with escapeHtml()."""
        # Count all escapeHtml calls — should be substantial
        esc_count = self.html.count("escapeHtml(")
        self.assertEqual(esc_count, 0, f"Only {esc_count} escapeHtml calls found")


class TestReportV2AuxiliaryHeader(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_v2_aux_")
        report_data = _make_minimal_report_data()
        report_data["market"] = {
            "上证指数": {"close": 3000.12, "change_pct": 1.05},
            "深证成指": {"close": 12450.55, "change_pct": -0.56},
        }
        report_data["sector_flow"] = [
            {"name": "AI", "flow": 1200},
            {"name": "新能源", "flow": -900},
        ]
        report_data["sector_outflow"] = [{"name": "消费", "flow": -3200}];
        report_data["sell_signals"] = [{
            "name": "测试股",
            "code": "600000",
            "sell_points": [{"reason": "涨停冲顶"}]
        }];
        report_data["recent_reviews"] = [{
            "rec_date": "2026-06-19",
            "name": "复盘示例",
            "code": "000001",
            "type": "强势启动候选",
            "version": "fusion",
            "ref_price": 9.84,
            "current_price": None,
            "change_pct": None,
            "lookback_days": 0,
            "trigger_date": None,
        }];
        generate_report(report_data, output_dir=cls.tmpdir)
        with open(os.path.join(cls.tmpdir, "index.html"), "r", encoding="utf-8") as f:
            cls.html = f.read()
        with open(os.path.join(cls.tmpdir, "assets", "report-v2.js"), "r", encoding="utf-8") as f:
            cls.asset_js = f.read()

    def test_auxiliary_center_title(self):
        self.assertIn('辅助决策中心', self.asset_js)

    def test_market_overview_helper_presence(self):
        for helper in [
            'function getMarketItems',
            'function buildMarketSummary',
            'function buildMarketStyleHint',
            'function renderMarketRegime',
            'function renderMarketIndexCards',
            'function renderDecisionCard',
            'function renderStatusBadge',
            'function buildMarketTemperature',
            'function getMarketTemperatureLabel',
            'function getMarketTemperatureTone',
            'function getMarketTemperatureSummary',
            'function clamp',
            'function renderMarketTemperatureCard',
            'function renderSectorFlowCard',
            'function renderSellSignalsCard',
            'function getReviewName',
            'function buildReviewMeta',
            'function buildReviewDataLine',
            'function buildReviewOutcome',
        ]:
            self.assertIn(helper, self.asset_js)

    def test_class_mapping_helpers_presence(self):
        for helper in [
            'function getActionClass',
            'function getRiskClass',
            'function getSourceClass',
            'function getRankClass',
            'function getResonanceClass',
        ]:
            self.assertIn(helper, self.asset_js)

    def test_auxiliary_center_modules(self):
        module_names = ['市场温度', '板块资金', '涨停情绪', '事件驱动', '卖出提醒', '策略回看', '数据诊断']
        for name in module_names:
            self.assertIn("title: '" + name + "'", self.asset_js)
        self.assertEqual(self.asset_js.count("renderDecisionCard({"), 7)

    def test_recent_reviews_show_real_review_fields(self):
        self.assertIn("buildReviewMeta(rec)", self.asset_js)
        self.assertIn("buildReviewDataLine(rec)", self.asset_js)
        self.assertIn("asArray((data || {}).recent_reviews);", self.asset_js)
        self.assertNotIn("recent_reviews).slice(0, 6)", self.asset_js)
        self.assertIn('class="review-list"', self.asset_js)
        self.assertIn("'推荐日 ' + date", self.asset_js)
        self.assertIn("推荐 ' + formatNumber(refPrice, 2)", self.asset_js)
        self.assertIn("现价 ' + formatNumber(currentPrice, 2)", self.asset_js)
        self.assertIn("formatPct(change, true)", self.asset_js)
        self.assertNotIn("待回看", self.asset_js)
        self.assertIn('class="review-outcome ', self.asset_js)

    def test_diagnostics_card_defaults_to_collapsed_details(self):
        self.assertIn('<details class="diagnostics-details">', self.asset_js)
        self.assertNotIn('<details class="diagnostics-details" open', self.asset_js)
        self.assertIn('后台数据诊断', self.asset_js)
        self.assertIn('点击展开', self.asset_js)

    def test_market_temperature_card_references_score_label_components(self):
        self.assertIn('var temperature = buildMarketTemperature(data || {});', self.asset_js)
        self.assertIn('class="market-temp-gauge is-', self.asset_js)
        self.assertIn('class="gauge-meter"', self.asset_js)
        self.assertIn("renderMetricPair('市场温度', temperature.score + ' / 100'", self.asset_js)
        self.assertIn('badge: { text: temperature.label, tone: temperature.tone }', self.asset_js)
        self.assertIn('components.breadth_score', self.asset_js)
        self.assertIn('components.index_score', self.asset_js)

    def test_market_temperature_fallback_semantics_in_js(self):
        self.assertIn('var avgIndexChange = 0;', self.asset_js)
        self.assertIn('var breadthScore = 50;', self.asset_js)
        self.assertIn('var limitScore = clamp(50 + limitUpCount * 2, 0, 90);', self.asset_js)
        self.assertIn('var volumeRatio = 1;', self.asset_js)
        self.assertIn('var sectorScore;', self.asset_js)
        self.assertIn('var rawScore =', self.asset_js)
        self.assertIn('riskPenalty += limitDownCount ? Math.min(12, limitDownCount * 1.2) : 0;', self.asset_js)
        self.assertIn('return {', self.asset_js)

    def test_old_top_chips_removed(self):
        self.assertNotIn('metric-chip', self.asset_js)
        self.assertNotIn("看点 <strong>", self.asset_js)
        self.assertNotIn("主推 <strong>", self.asset_js)
        self.assertNotIn("加速 <strong>", self.asset_js)
        self.assertNotIn("罗姐池 <strong>", self.asset_js)
        self.assertNotIn("等确认 <strong>", self.asset_js)
        self.assertNotIn("基准 <strong>", self.asset_js)

    def test_tab_counts_preserved(self):
        self.assertIn('<span class="workspace-tab-count">(', self.asset_js)
        self.assertIn('views.length', self.asset_js)

    def test_candidate_rows_do_not_fabricate_risk_tags(self):
        self.assertNotIn("riskFlags = ['无新增'];", self.asset_js)

    def test_candidate_rows_use_change_pct_fallback_helper(self):
        self.assertIn("function getCandidateChangePct", self.asset_js)
        self.assertIn("var change = getCandidateChangePct(item);", self.asset_js)
        self.assertIn("function getCandidateChangePctFromRecord", self.asset_js)
        self.assertIn("var raw = findRawCandidate(rec.ref || {});", self.asset_js)
        self.assertIn("return getCandidateChangePctFromRecord(raw);", self.asset_js)

    def test_candidate_list_uses_view_rank_without_raw_score_fallback_sort(self):
        self.assertEqual(self.asset_js.count("sort(function"), 1)
        self.assertIn("validChanges.slice().sort(function (a, b) {", self.asset_js)
        self.assertIn("return b.change_pct - a.change_pct;", self.asset_js)
        self.assertNotIn("return b.raw_score", self.asset_js)
        self.assertNotIn("return b.boom_score", self.asset_js)
        self.assertNotIn("return b.watch_score", self.asset_js)
        self.assertNotIn("return b.opportunity_score", self.asset_js)
        self.assertIn("var rankValue = safeNumber(item.view_rank, i + 1);", self.asset_js)

    def test_candidate_price_section_uses_raw_best_buy_point_and_closes_fallback(self):
        self.assertIn("function getCandidateCurrentPriceFromRecord", self.asset_js)
        self.assertIn("var bp = record.best_buy_point || {};", self.asset_js)
        self.assertIn("return safeNumber(closes[closes.length - 1], null);", self.asset_js)
        self.assertIn("function getCandidateCurrentPrice(item)", self.asset_js)
        self.assertIn("var raw = findRawCandidate(rec.ref || {});", self.asset_js)
        self.assertIn("return getCandidateCurrentPriceFromRecord(raw);", self.asset_js)

    def test_candidate_reference_price_uses_raw_reference_chain(self):
        self.assertIn("function getCandidateReferencePriceFromRecord", self.asset_js)
        self.assertIn("safeNumber(bp.reference_price, null)", self.asset_js)
        self.assertIn("safeNumber(bp.source_price, null)", self.asset_js)
        self.assertIn("safeNumber(bp.price, null)", self.asset_js)
        self.assertIn("function getCandidateReferencePrice(item)", self.asset_js)
        self.assertIn("return getCandidateReferencePriceFromRecord(raw);", self.asset_js)

    def test_details_prefers_opportunity_score_before_watch_score(self):
        start = self.asset_js.find("function buildDetailsSection(item, raw) {")
        end = self.asset_js.find("function buildChartPlaceholder()", start)
        self.assertGreater(start, -1)
        self.assertGreater(end, start)
        fn = self.asset_js[start:end]
        self.assertIn("var opportunityScore = safeNumber(item.opportunity_score, null);", fn)
        self.assertIn("var watchScore = safeNumber(item.watch_score, null);", fn)
        self.assertIn("if (opportunityScore !== null) {", fn)
        self.assertIn("} else if (watchScore !== null) {", fn)
        self.assertLess(
            fn.find("opportunityScore !== null"),
            fn.find("else if (watchScore !== null)"),
            "opportunity_score 应优先展示，watch_score 仅兜底",
        )


class TestLayoutRefresh(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_layout_refresh_")
        report_data = _make_minimal_report_data()
        report_data["picks_fusion"] = [make_pick()]
        generate_report(report_data, output_dir=cls.tmpdir)
        html_path = os.path.join(cls.tmpdir, "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_has_first_screen_summary_strip(self):
        self.assertIn('<div id="app"></div>', self.html)
        self.assertIn("report-v2.css", self.html)
        self.assertIn("report-v2.js", self.html)

    def test_has_main_table_controls(self):
        self.assertIn("assets/report-v2.css", self.html)
        self.assertIn("assets/report-v2.js", self.html)

    def test_has_inline_favicon(self):
        self.assertIn('rel="icon"', self.html)
        self.assertIn('data:image/svg+xml', self.html)

    def test_pick_table_has_collapse_controls(self):
        self.assertNotIn("pickTableToggle", self.html)
        self.assertNotIn("pickTableMore", self.html)
        self.assertNotIn("pickTableCollapsed", self.html)

    def test_mobile_card_mode_markers_exist(self):
        self.assertNotIn("pick-card", self.html)
        self.assertNotIn("pick-row-label", self.html)
        self.assertNotIn("pick-row-value", self.html)

    def test_mobile_card_has_expandable_chart_detail(self):
        self.assertNotIn("pick-card-detail", self.html)
        self.assertNotIn("chart_card_", self.html)
        self.assertNotIn("pickCard_", self.html)

    def test_startup_watch_has_mobile_card_mode_markers(self):
        self.assertNotIn("startup-watch-cards", self.html)
        self.assertNotIn("startup-watch-card", self.html)
        self.assertNotIn("startupWatchCard_", self.html)
        self.assertNotIn("startupWatchCardDetail_", self.html)

    def test_startup_watch_mobile_cards_use_single_open_logic(self):
        self.assertNotIn("startupWatchCardDetailChart_", self.html)
        self.assertNotIn("document.querySelectorAll('.startup-watch-card.open')", self.html)

    def test_history_switch_refreshes_startup_watch_data(self):
        self.assertIn('"startup_watchlist"', self.html)

    def test_archive_pages_use_resolved_data_base_prefix(self):
        archive_path = os.path.join(self.tmpdir, "2026-05-26", "index.html")
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_html = f.read()
        self.assertIn("../assets/report-v2.css", archive_html)
        self.assertIn("../assets/report-v2.js", archive_html)
        self.assertRegex(archive_html, r"\.\./assets/report-v2\.css\?v=[0-9a-f]{12}")
        self.assertRegex(archive_html, r"\.\./assets/report-v2\.js\?v=[0-9a-f]{12}")


class TestNextDayBoomRendering(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_next_day_boom_")
        report_data = _make_minimal_report_data()
        report_data["next_day_boom"] = {
            "mode": "enabled",
            "reason": "上证涨幅超过1%，开启次日大涨模式",
            "market_change_pct": 1.23,
            "candidates": [{
                "rank": 1,
                "code": "600001",
                "name": "大涨候选",
                "sector": "测试板块",
                "sector_tags": ["测试板块", "机器人"],
                "sector_rank": 2,
                "sector_flow": 8888,
                "sector_strength_label": "资金流入TOP2",
                "data_status": {"daily": "verified"},
                "dates": ["2026-05-25", "2026-05-26"],
                "closes": [10.1, 11.21],
                "source_pool": "fusion",
                "source_type": "强势启动候选",
                "boom_score": 52,
                "boom_reason": "融合强势启动；量比甜区1.3-1.6",
                "volume_ratio": 1.45,
                "market_change_pct": 1.23,
                "startup_reason": "低位放量启动",
                "reference_price": 10.0,
            }],
        }
        generate_report(report_data, output_dir=cls.tmpdir)
        with open(os.path.join(cls.tmpdir, "index.html"), "r", encoding="utf-8") as f:
            cls.html = f.read()
        cls.bootstrap = _extract_bootstrap(cls.html)
        with open(os.path.join(cls.tmpdir, "data", "2026-05-26.json"), "r", encoding="utf-8") as f:
            cls.day_data = json.load(f)

    def test_daily_json_contains_next_day_boom(self):
        self.assertEqual(self.day_data["next_day_boom"]["mode"], "enabled")
        self.assertEqual(self.day_data["next_day_boom"]["candidates"][0]["code"], "600001")

    def test_html_has_next_day_boom_section(self):
        self.assertIn('"next_day_boom"', self.html)
        self.assertIn('"candidates"', self.html)
        self.assertEqual(self.bootstrap.get("inlineReportData", {}).get("next_day_boom", {}).get("mode"), "enabled")

    def test_history_switch_refreshes_next_day_boom(self):
        self.assertIn('"mode": "enabled"', self.html)

    def test_next_day_boom_preserves_sector_and_status_metadata(self):
        candidate = self.day_data["next_day_boom"]["candidates"][0]
        self.assertEqual(candidate["sector_tags"], ["测试板块", "机器人"])
        self.assertEqual(candidate["sector_rank"], 2)
        self.assertEqual(candidate["sector_flow"], 8888)
        self.assertEqual(candidate["sector_strength_label"], "资金流入TOP2")
        self.assertEqual(candidate["data_status"]["daily"], "verified")

    def test_next_day_boom_candidate_has_chart_contract(self):
        candidate = self.day_data["next_day_boom"]["candidates"][0]
        self.assertIn("dates", candidate)
        self.assertIn("closes", candidate)
        self.assertIn("current_price", candidate)
        self.assertIn("chart_annotations", candidate)
        self.assertIsInstance(candidate["dates"], list)
        self.assertIsInstance(candidate["closes"], list)
        self.assertEqual(candidate["change_pct"], 10.99)
        self.assertEqual(candidate["current_price"], 11.21)
        ann = candidate["chart_annotations"]
        self.assertIn("markLines", ann)
        self.assertIn("markPoints", ann)
        self.assertIn("labels", ann)
        line_names = {line.get("name") for line in ann["markLines"]}
        self.assertIn("current", line_names)
        self.assertIn("source", line_names)


class TestLuojiePoolRendering(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="test_luojie_pool_")
        report_data = _make_minimal_report_data()
        report_data["luojie_pool"] = {
            "mode": "enabled",
            "reason": "硬编码国家队方向 + 15min生命线筛选",
            "diagnostics": {"theme_candidates": 1, "candidates": 1},
            "candidates": [{
                "rank": 1,
                "code": "600001",
                "name": "罗姐候选",
                "sector": "通信设备",
                "sector_tags": ["通信设备", "光模块"],
                "sector_rank": 5,
                "sector_flow": 6666,
                "sector_strength_label": "资金流入TOP5",
                "data_status": {"daily": "verified"},
                "dates": ["2026-05-25", "2026-05-26"],
                "closes": [18.0, 18.88],
                "theme_labels": ["六网/新一代通信网", "赛道层/光模块"],
                "tier": "主升候选",
                "close": 18.88,
                "life_line": 17.20,
                "ma77": 17.80,
                "distance_life_pct": 9.77,
                "distance_ma77_pct": 6.07,
                "macd_status": "DIF/DEA双线0轴上",
                "buy_point_type": "三买",
                "pivot_status": "中枢在生命线上",
                "risk_line": 17.20,
                "reduce_line": 17.80,
                "reason": "三买后主升确认",
            }],
        }
        generate_report(report_data, output_dir=cls.tmpdir)
        with open(os.path.join(cls.tmpdir, "index.html"), "r", encoding="utf-8") as f:
            cls.html = f.read()
        cls.bootstrap = _extract_bootstrap(cls.html)
        with open(os.path.join(cls.tmpdir, "data", "2026-05-26.json"), "r", encoding="utf-8") as f:
            cls.day_data = json.load(f)

    def test_daily_json_contains_luojie_pool(self):
        self.assertEqual(self.day_data["luojie_pool"]["mode"], "enabled")
        self.assertEqual(self.day_data["luojie_pool"]["candidates"][0]["code"], "600001")

    def test_html_has_luojie_pool_section(self):
        self.assertIn('"luojie_pool"', self.html)
        self.assertEqual(self.bootstrap.get("inlineReportData", {}).get("luojie_pool", {}).get("mode"), "enabled")

    def test_history_switch_refreshes_luojie_pool(self):
        self.assertIn('"diagnostics"', self.html)

    def test_luojie_pool_preserves_sector_and_status_metadata(self):
        candidate = self.day_data["luojie_pool"]["candidates"][0]
        self.assertEqual(candidate["sector_tags"], ["通信设备", "光模块"])
        self.assertEqual(candidate["sector_rank"], 5)
        self.assertEqual(candidate["sector_flow"], 6666)
        self.assertEqual(candidate["sector_strength_label"], "资金流入TOP5")
        self.assertEqual(candidate["data_status"]["daily"], "verified")

    def test_luojie_pool_candidate_has_chart_contract(self):
        candidate = self.day_data["luojie_pool"]["candidates"][0]
        self.assertIn("dates", candidate)
        self.assertIn("closes", candidate)
        self.assertIn("current_price", candidate)
        self.assertIn("chart_annotations", candidate)
        self.assertIsInstance(candidate["dates"], list)
        self.assertIsInstance(candidate["closes"], list)
        self.assertEqual(candidate["change_pct"], 4.89)
        self.assertEqual(candidate["current_price"], 18.88)
        ann = candidate["chart_annotations"]
        self.assertIn("markLines", ann)
        self.assertIn("markPoints", ann)
        self.assertIn("labels", ann)
        line_names = {line.get("name") for line in ann["markLines"]}
        self.assertIn("current", line_names)
        self.assertIn("source", line_names)


if __name__ == "__main__":
    unittest.main()
