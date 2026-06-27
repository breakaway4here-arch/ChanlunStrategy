import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from config import DAY_LOOKBACK
from scripts.backtest_delayed_entry import main


def _fake_snapshots():
    return [
        ("2026-01-05", "picks_pure", {
            "code": "000001",
            "best_buy_point": {"type": "强势启动候选"},
        }),
        ("2026-01-04", "picks_fusion", {
            "code": "000001",
            "best_buy_point": {"type": "底背驰候选"},
        }),
    ]


def _fake_snapshots_repeated_code():
    return [
        ("2026-01-05", "picks_pure", {
            "code": "000001",
            "best_buy_point": {"type": "强势启动候选"},
        }),
        ("2026-01-04", "picks_fusion", {
            "code": "000001",
            "best_buy_point": {"type": "底背驰候选"},
        }),
    ]


def _fake_snapshots_unified_last_day():
    return [
        ("2026-01-06", "picks_pure", {
            "best_buy_point": {"type": "强势启动候选"},
        }),
        ("2026-01-06", "picks_fusion", {
            "code": "000001",
            "best_buy_point": {"type": "底背驰候选"},
        }),
    ]


def _fake_kline():
    return {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"],
        "opens": [10.0, 10.5, 11.0, 11.5, 12.0, 13.0],
        "highs": [10.2, 10.8, 11.2, 11.8, 12.4, 13.4],
        "lows": [9.8, 10.2, 10.7, 11.0, 11.5, 12.2],
        "closes": [10.1, 10.4, 10.9, 11.2, 11.7, 12.6],
    }


def _fake_kline_with_numpy():
    return {
        "dates": np.array(
            ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"]
        ),
        "opens": np.array([10.0, 10.5, 11.0, 11.5, 12.0, 13.0]),
        "highs": np.array([10.2, 10.8, 11.2, 11.8, 12.4, 13.4]),
        "lows": np.array([9.8, 10.2, 10.7, 11.0, 11.5, 12.2]),
        "closes": np.array([10.1, 10.4, 10.9, 11.2, 11.7, 12.6]),
    }


class BacktestDelayedEntryScriptTests(unittest.TestCase):
    @patch("scripts.backtest_delayed_entry.fetch_daily_kline")
    @patch("scripts.backtest_delayed_entry.iter_snapshot_picks")
    def test_script_generates_json(self, iter_snapshot_mock, fetch_mock):
        snapshots = _fake_snapshots()
        iter_snapshot_mock.side_effect = lambda: iter(snapshots)
        fetch_mock.return_value = _fake_kline()
        expected_calls = 1  # --limit-days 1 keeps only the latest snapshot day
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "phase6.1.json"
            rc = main(["--limit-days", "1", "--output-json", str(output)])
            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("summary", payload)
            self.assertIn("overall", payload)
            self.assertIn("by_type", payload)
            self.assertIn("evaluated_by_mode", payload["summary"])
            self.assertIn("skipped", payload["summary"])
            self.assertIn("snapshot_days", payload["summary"])
            self.assertEqual(fetch_mock.call_count, expected_calls)
            for call in fetch_mock.call_args_list:
                args, kwargs = call
                self.assertEqual(kwargs.get("count", args[1] if len(args) > 1 else None), DAY_LOOKBACK)

    @patch("scripts.backtest_delayed_entry.fetch_daily_kline")
    @patch("scripts.backtest_delayed_entry.iter_snapshot_picks")
    def test_script_generates_json_with_numpy_kline(self, iter_snapshot_mock, fetch_mock):
        snapshots = _fake_snapshots()
        iter_snapshot_mock.side_effect = lambda: iter(snapshots)
        fetch_mock.return_value = _fake_kline_with_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "phase6.1_numpy.json"
            rc = main(["--limit-days", "1", "--output-json", str(output)])
            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("summary", payload)
            self.assertIn("overall", payload)
            self.assertIn("by_type", payload)
            self.assertEqual(fetch_mock.call_count, 1)
            args, kwargs = fetch_mock.call_args
            self.assertEqual(kwargs.get("count", args[1] if len(args) > 1 else None), DAY_LOOKBACK)

    @patch("scripts.backtest_delayed_entry.fetch_daily_kline")
    @patch("scripts.backtest_delayed_entry.iter_snapshot_picks")
    def test_repeated_code_fetches_kline_once(self, iter_snapshot_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(_fake_snapshots_repeated_code())
        fetch_mock.return_value = _fake_kline()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "phase6.1_cache.json"
            rc = main(["--limit-days", "2", "--output-json", str(output)])
            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(fetch_mock.call_count, 1)
            summary = payload["summary"]
            self.assertEqual(summary["picks_seen"], 2)
            self.assertLessEqual(summary["evaluated_by_mode"]["immediate_close"], 2)

    @patch("scripts.backtest_delayed_entry.fetch_daily_kline")
    @patch("scripts.backtest_delayed_entry.iter_snapshot_picks")
    def test_summary_skipped_is_pick_level(self, iter_snapshot_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(_fake_snapshots_unified_last_day())
        fetch_mock.return_value = _fake_kline()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "phase6.1_skip.json"
            rc = main(["--limit-days", "1", "--output-json", str(output)])
            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            summary = payload["summary"]
            self.assertEqual(summary["picks_seen"], 2)
            self.assertEqual(summary["skipped_no_code"], 1)
            self.assertEqual(summary["skipped_no_kline"], 0)
            self.assertEqual(summary["skipped"], summary["skipped_no_code"] + summary["skipped_no_kline"])
            self.assertEqual(summary["not_evaluable_by_mode"]["immediate_close"], 1)
            self.assertEqual(summary["not_evaluable_by_mode"]["delay1_open"], 1)
            self.assertEqual(summary["not_evaluable_by_mode"]["delay1_close"], 1)


if __name__ == "__main__":
    unittest.main()
