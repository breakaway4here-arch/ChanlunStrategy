"""Tests for report_generator — table columns, 30min确认, volumes_30min serialization."""
import json
import unittest
import numpy as np

from chanlun.report_generator import (
    _serialize_picks, _serialize_bp, build_chart_window, build_chart_annotations,
    _safe_list, NpEncoder,
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


if __name__ == "__main__":
    unittest.main()
