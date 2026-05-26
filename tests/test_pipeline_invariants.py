import unittest
import json
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from chanlun.chan_engine import analyze


class PipelineInvariantTests(unittest.TestCase):
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
