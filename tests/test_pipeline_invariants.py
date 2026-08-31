import unittest
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from types import SimpleNamespace

import run
from chanlun.chan_engine import analyze


class PipelineInvariantTests(unittest.TestCase):
    def test_shadow_right_side_targets_never_enter_writable_30min_fetch(self):
        targets = run._partition_30min_targets(
            pure_pool=[{"code": "600001"}],
            fusion_pool=[{"code": "600002"}],
            startup_seeds=[{"code": "600003"}],
            right_side_seeds=[{"code": "300709"}],
            fusion_admission_enabled=True,
            right_side_mode="shadow",
        )

        self.assertEqual(
            {"600001", "600003"}, targets["writable_codes"]
        )
        self.assertEqual({"300709"}, targets["readonly_shadow_codes"])

        active = run._partition_30min_targets(
            pure_pool=[{"code": "600001"}],
            fusion_pool=[],
            startup_seeds=[],
            right_side_seeds=[{"code": "300709"}],
            fusion_admission_enabled=True,
            right_side_mode="active",
        )
        self.assertEqual(
            {"600001", "300709"}, active["writable_codes"]
        )
        self.assertEqual(set(), active["readonly_shadow_codes"])

    def test_acceleration_accepts_only_formal_main_right_side_rows(self):
        rows = [
            {"code": "600001", "source_channel": "classic"},
            {
                "code": "300001",
                "source_channel": "right_side_startup",
                "decision_engine_v1": {"decision_code": "observe"},
            },
            {
                "code": "300002",
                "source_channel": "right_side_startup",
                "decision_engine_v1": {"decision_code": "recommend"},
            },
        ]

        eligible = run._eligible_acceleration_inputs(rows)

        self.assertEqual(["600001", "300002"], [row["code"] for row in eligible])

    def test_formal_channels_keep_classic_upstream_and_scan_right_side_independently(self):
        results = [
            SimpleNamespace(
                code="600001", name="结构票", closes=np.array([10.0, 10.1])
            ),
            SimpleNamespace(
                code="600002", name="右侧票", closes=np.array([10.0, 10.1])
            ),
        ]
        calls = {}

        def classic_builder(rows, _sectors):
            calls["classic"] = [row.code for row in rows]
            return [], [], {"channel": "classic"}

        def right_builder(rows, _sectors):
            calls["right"] = [row.code for row in rows]
            return [], [], {"channel": "right"}

        state = run._build_independent_daily_channels(
            results,
            [{"code": "600001"}],
            {},
            mode="shadow",
            classic_builder=classic_builder,
            right_builder=right_builder,
        )

        self.assertEqual(["600001"], calls["classic"])
        self.assertEqual(["600001", "600002"], calls["right"])
        self.assertEqual("picks_pure", state["classic_upstream"]["upstream_pool"])

    def test_shadow_publish_keeps_formal_candidates_byte_equivalent(self):
        existing = [{"code": "600001", "score": 88, "nested": ["keep"]}]
        right_side = [{"code": "300001", "score": 95}]

        merged, diagnostics = run._merge_right_side_scored_candidates(
            existing, right_side, mode="shadow"
        )
        off, _ = run._merge_right_side_scored_candidates(
            existing, right_side, mode="off"
        )

        self.assertEqual(existing, merged)
        self.assertEqual([], diagnostics["published_codes"])
        self.assertEqual(["keep"], existing[0]["nested"])
        canonical = lambda rows: hashlib.sha256(
            json.dumps(
                rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(canonical(off), canonical(merged))

    def test_active_publish_appends_top_three_without_reordering_existing(self):
        existing = [{"code": "600001", "score": 88}]
        right_side = [
            {"code": "300001", "score": 80},
            {"code": "300002", "score": 96},
            {"code": "300003", "score": 90},
            {"code": "300004", "score": 85},
        ]

        merged, diagnostics = run._merge_right_side_scored_candidates(
            existing, right_side, mode="active"
        )

        self.assertEqual(
            ["600001", "300002", "300003", "300004"],
            [row["code"] for row in merged],
        )
        self.assertEqual(
            ["300002", "300003", "300004"],
            diagnostics["published_codes"],
        )

    def test_no_third_buy_without_standard_pivot(self):
        dates = list(range(60))
        closes = np.array([10 + i * 0.1 for i in range(60)], dtype=float)
        highs = closes + 0.2
        lows = closes - 0.2
        opens = closes
        volumes = np.ones(60) * 10000

        result = analyze("TEST", "TEST", dates, opens, highs, lows, closes, volumes)

        # 纯单边上涨不会形成中枢
        self.assertEqual(len(result.pivots), 0, "Linear data should produce no pivots")
        self.assertFalse(any(bp["type"] == "三买" for bp in result.buy_points))

    def test_swing_does_not_create_formal_buy_points(self):
        dates = list(range(60))
        closes = np.array([10 + i * 0.1 for i in range(60)], dtype=float)
        highs = closes + 0.2
        lows = closes - 0.2
        opens = closes
        volumes = np.ones(60) * 10000

        result = analyze("TEST", "TEST", dates, opens, highs, lows, closes, volumes)

        self.assertEqual(len(result.pivots), 0, "Linear data should produce no pivots")
        # 无标准中枢时不应产生正式买卖点
        self.assertFalse(any(bp["type"] in {"一买", "二买", "三买"} for bp in result.buy_points))


def _run_qa(path):
    return subprocess.run(
        ["python3", "scripts/qa_signal_invariants.py", str(path)],
        capture_output=True,
        text=True,
    )


class QASignalInvariantTests(unittest.TestCase):

    def test_qa_rejects_unknown_buy_point_type(self):
        payload = {
            "picks_pure": [{
                "code": "000001",
                "name": "TEST",
                "best_buy_point": {"type": "未知候选", "tier": "candidate"},
                "buy_points": [{"type": "未知候选", "tier": "candidate"}],
            }],
            "picks_fusion": [],
            "diagnostics": {"daily_scan": {"buy_point_type_counts": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = _run_qa(path)
            self.assertNotEqual(result.returncode, 0)

    def test_qa_rejects_candidate_missing_metadata(self):
        payload = {
            "picks_pure": [{
                "code": "000001",
                "name": "TEST",
                "best_buy_point": {"type": "底背驰候选", "tier": "candidate"},
                "buy_points": [{"type": "底背驰候选", "tier": "candidate"}],
            }],
            "picks_fusion": [],
            "diagnostics": {"daily_scan": {"buy_point_type_counts": {}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = _run_qa(path)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
