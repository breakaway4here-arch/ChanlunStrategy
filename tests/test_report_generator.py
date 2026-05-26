"""Tests for report_generator — table columns, 30min确认, volumes_30min serialization, access control."""
import hashlib
import json
import os
import tempfile
import unittest
import numpy as np

from chanlun.report_generator import (
    _serialize_picks, _serialize_bp, build_chart_window, build_chart_annotations,
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


if __name__ == "__main__":
    unittest.main()
