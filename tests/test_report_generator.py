"""Tests for report_generator — table columns, 30min确认, volumes_30min serialization, access control, startup watchlist chart."""
import hashlib
import json
import os
import tempfile
import unittest
import numpy as np

from chanlun.report_generator import (
    _serialize_picks, _serialize_bp, _serialize_startup_watchlist,
    build_chart_window, build_chart_annotations, build_startup_watch_chart_annotations,
    _safe_list, NpEncoder, generate_report,
)
from config import (
    ENABLE_WEAK_ACCESS_CONTROL, FULL_ACCESS_KEY, FULL_ACCESS_KEY_SALT,
    PUBLIC_DATES,
)


class DummyResult30min:
    def __init__(self):
        self.dates = ["2026-05-26 09:30:00", "2026-05-26 10:00:00"]
        self.opens = np.array([50.0, 51.0])
        self.highs = np.array([52.0, 53.0])
        self.lows = np.array([49.0, 50.0])
        self.closes = np.array([51.0, 52.0])
        self.volumes = np.array([1000.0, 2000.0])


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

    def test_serialize_picks_volumes_30min(self):
        """volumes_30min is serialized when result_30min is present."""
        pick = make_pick(with_30min=True)
        serialized = _serialize_picks([pick])
        self.assertEqual(len(serialized), 1)
        s = serialized[0]
        self.assertTrue(s["has_30min"])
        self.assertEqual(len(s["volumes_30min"]), 2)
        self.assertEqual(s["volumes_30min"], [1000.0, 2000.0])

    def test_serialize_picks_no_30min_empty_arrays(self):
        """When no result_30min, volumes_30min is empty list."""
        pick = make_pick(with_30min=False)
        serialized = _serialize_picks([pick])
        s = serialized[0]
        self.assertFalse(s["has_30min"])
        self.assertEqual(s["volumes_30min"], [])
        self.assertEqual(s["dates_30min"], [])

    def test_serialize_picks_includes_30min_ohlc(self):
        """30min OHLC data is serialized for dual chart."""
        pick = make_pick(with_30min=True)
        serialized = _serialize_picks([pick])
        s = serialized[0]
        self.assertEqual(len(s["dates_30min"]), 2)
        self.assertEqual(len(s["opens_30min"]), 2)
        self.assertEqual(len(s["highs_30min"]), 2)
        self.assertEqual(len(s["lows_30min"]), 2)
        self.assertEqual(len(s["closes_30min"]), 2)
        self.assertEqual(s["opens_30min"][0], 50.0)

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
        serialized = _serialize_picks([pick])
        encoded = json.dumps(serialized, cls=NpEncoder)
        decoded = json.loads(encoded)
        self.assertEqual(decoded[0]["code"], "600519")
        self.assertEqual(decoded[0]["volumes_30min"], [1000.0, 2000.0])


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

    def test_access_control_enabled_in_html(self):
        """HTML contains ACCESS_CONTROL_ENABLED = true."""
        self.assertIn("ACCESS_CONTROL_ENABLED = true", self.html)

    def test_public_dates_in_html(self):
        """HTML contains ACCESS_PUBLIC_DATES with configured dates."""
        self.assertIn(json.dumps(PUBLIC_DATES), self.html)

    def test_sha256_helper_in_html(self):
        """HTML contains sha256Hex function for crypto.subtle hashing."""
        self.assertIn("crypto.subtle.digest('SHA-256'", self.html)
        self.assertIn("function sha256Hex", self.html)

    def test_resolve_granted_in_html(self):
        """HTML contains async resolveGranted function."""
        self.assertIn("function resolveGranted", self.html)

    def test_get_allowed_dates_in_html(self):
        """HTML contains getAllowedDates filter function."""
        self.assertIn("function getAllowedDates", self.html)

    def test_resolve_initial_date_in_html(self):
        """HTML contains resolveInitialDate fallback function."""
        self.assertIn("function resolveInitialDate", self.html)

    def test_filter_history_data_in_html(self):
        """HTML contains filterHistoryData function."""
        self.assertIn("function filterHistoryData", self.html)

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

    def test_no_public_data_function_in_html(self):
        """HTML contains renderNoPublicData for empty allowlist."""
        self.assertIn("function renderNoPublicData", self.html)
        self.assertIn("暂无日报数据", self.html)

    def test_show_history_guards_disallowed_dates(self):
        """showHistory checks GRANTED and PUBLIC_DATES before switching dates."""
        self.assertIn("ACCESS_PUBLIC_DATES.indexOf(dateStr)", self.html)


class TestStartupWatchlistSerialization(unittest.TestCase):

    def _make_watch_item(self, with_chart=True):
        n = 60
        item = {
            "code": "000001",
            "name": "测试股",
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


if __name__ == "__main__":
    unittest.main()
