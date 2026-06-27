import json
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from contextlib import redirect_stderr
from unittest.mock import patch

from scripts.run_policy_experiments import main


def _fake_payload():
    return {
        "policies": [
            {
                "policy": "delay1_v1_cooldown3",
                "coverage": {
                    "snapshot_days": 10,
                    "picks_seen": 10,
                    "baseline_evaluated": 10,
                    "policy_evaluated": 8,
                    "baseline_filtered": 1,
                    "policy_filtered": 2,
                    "policy_filtered_by_reason": {"cooldown": 1},
                    "retained_ratio_pct": 80.0,
                },
                "baseline_summary": {
                    "n": 10,
                    "t3_mean": 1.2,
                },
                "policy_summary": {
                    "n": 8,
                    "t3_mean": 1.4,
                },
                "delta": {
                    "t3_mean_delta": 0.2,
                    "t3_win_rate_delta": 1.0,
                    "t3_loss_5pct_rate_delta": -2.0,
                    "big_drop_5pct_rate_delta": 0.0,
                },
            },
            {
                "policy": "delay1_v1_bottom_quality_guard",
                "coverage": {
                    "snapshot_days": 10,
                    "picks_seen": 10,
                    "baseline_evaluated": 10,
                    "policy_evaluated": 7,
                    "baseline_filtered": 1,
                    "policy_filtered": 3,
                    "policy_filtered_by_reason": {"bottom_quality_guard": 2},
                    "retained_ratio_pct": 70.0,
                },
                "baseline_summary": {
                    "n": 10,
                    "t3_mean": 1.2,
                },
                "policy_summary": {
                    "n": 7,
                    "t3_mean": 0.8,
                },
                "delta": {
                    "t3_mean_delta": -0.4,
                    "t3_win_rate_delta": -1.5,
                    "t3_loss_5pct_rate_delta": -3.0,
                    "big_drop_5pct_rate_delta": -1.0,
                },
            },
        ],
        "baseline_reference": "signal_delay1_by_type_guard",
        "execution": {
            "shared_baseline": True,
            "snapshot_rows": 10,
            "unique_codes": 6,
            "fetch_attempts": 6,
            "cache_hits": 4,
            "kline_missing": 1,
            "kline_invalid": 0,
            "baseline_rows": 9,
        },
    }


def _build_simple_breakdown():
    return {
        "market_regime": {
            "strong": {
                "total": 4,
                "accepted": 2,
                "filtered": 2,
                "filter_reasons": {
                    "bottom_quality_guard": 1,
                    "bottom_market_unknown": 1,
                },
            },
            "unknown": {
                "total": 1,
                "accepted": 0,
                "filtered": 1,
                "filter_reasons": {
                    "bottom_market_unknown": 1,
                },
            },
        },
        "best_buy_point_type": {
            "底背驰候选": {
                "total": 5,
                "accepted": 3,
                "filtered": 2,
                "filter_reasons": {},
            }
        },
        "confirmations": {
            "关键位不破 + 30min底分型": {
                "total": 4,
                "accepted": 3,
                "filtered": 1,
                "filter_reasons": {},
            },
            "none": {
                "total": 1,
                "accepted": 1,
                "filtered": 0,
                "filter_reasons": {},
            },
        },
    }


class PolicyExperimentRunnerScriptTests(unittest.TestCase):
    def test_unknown_policy_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_unknown.json"
            output_md = Path(tmpdir) / "policy_unknown.md"
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = main([
                    "--policies",
                    "not_exists",
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ])
            self.assertNotEqual(rc, 0)
            self.assertIn("unknown policy", stderr.getvalue())

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_valid_policy_writes_json_and_markdown(self, run_mock):
        run_mock.return_value = _fake_payload()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest.json"
            output_md = Path(tmpdir) / "policy_backtest.md"
            rc = main([
                "--policies",
                "delay1_v1",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertIn("policies", payload)
            self.assertEqual(len(payload["policies"]), 2)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("Generated:", text)
            self.assertIn("delay1_v1_cooldown3", text)
            self.assertIn("Filtered By Reason", text)
            self.assertIn("Execution Summary", text)
            self.assertIn("shared_baseline: True", text)
            self.assertIn("fetch_attempts: 6", text)
            self.assertIn("cache_hits: 4", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_multiple_policies_in_arg(self, run_mock):
        run_mock.return_value = _fake_payload()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest_multi.json"
            output_md = Path(tmpdir) / "policy_backtest_multi.md"
            rc = main([
                "--policies",
                "delay1_v1_cooldown3,delay1_v1_bottom_quality_guard",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["policies"]), 2)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("delay1_v1_cooldown3", text)
            self.assertIn("delay1_v1_bottom_quality_guard", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_markdown_includes_breakdown_summary(self, run_mock):
        payload = _fake_payload()
        for item in payload["policies"]:
            item["breakdown"] = _build_simple_breakdown()
        run_mock.return_value = payload
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest_single.json"
            output_md = Path(tmpdir) / "policy_backtest_single.md"
            rc = main([
                "--policies",
                "delay1_v1",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("## Breakdown Summary", text)
            self.assertIn("### delay1_v1_cooldown3", text)
            self.assertIn("#### market_regime", text)
            self.assertIn("#### best_buy_point_type", text)
            self.assertIn("#### confirmations", text)
            self.assertIn(
                "unknown: total=1, accepted=0, filtered=1, reasons=bottom_market_unknown:1",
                text,
            )
            self.assertIn("bottom_market_unknown:1", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_markdown_includes_execution_model_columns(self, run_mock):
        payload = _fake_payload()
        payload["policies"] = [
            {
                "policy": "delay1_v1_bottom_quality_market_known_guard_entry_next_open",
                "coverage": {
                    "snapshot_days": 3,
                    "picks_seen": 3,
                    "baseline_evaluated": 3,
                    "policy_evaluated": 3,
                    "baseline_filtered": 0,
                    "policy_filtered": 0,
                    "policy_not_evaluable": 1,
                    "policy_filtered_by_reason": {},
                    "retained_ratio_pct": 100.0,
                },
                "baseline_summary": {
                    "n": 3,
                    "t3_mean": 1.2,
                },
                "policy_summary": {
                    "n": 3,
                    "t3_mean": 1.4,
                },
                "execution_model": {
                    "entry_label": "entry_next_open",
                    "entry_mode": "delay1_open",
                    "exit_model": "exit_stop_loss_5pct",
                },
                "delta": {
                    "t3_mean_delta": 0.2,
                    "t3_win_rate_delta": 1.0,
                    "t3_loss_5pct_rate_delta": -2.0,
                    "big_drop_5pct_rate_delta": 0.0,
                },
            }
        ]
        run_mock.return_value = payload
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest_single.json"
            output_md = Path(tmpdir) / "policy_backtest_single.md"
            rc = main([
                "--policies",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("Entry Model", text)
            self.assertIn("Entry Mode", text)
            self.assertIn("Exit Model", text)
            self.assertIn("Not Evaluable", text)
            self.assertIn("entry_next_open", text)
            self.assertIn("delay1_open", text)
            self.assertIn("exit_stop_loss_5pct", text)
            self.assertIn("1", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_markdown_confirmations_top_10(self, run_mock):
        payload = _fake_payload()
        confirmations = {}
        for idx in range(12):
            confirmations[f"bucket_{idx}"] = {
                "total": 12 - idx,
                "accepted": idx,
                "filtered": 12 - idx,
                "filter_reasons": {},
            }
        payload["policies"] = [
            {
                "policy": "delay1_v1_cooldown3",
                "coverage": {
                    "snapshot_days": 3,
                    "picks_seen": 3,
                    "baseline_evaluated": 3,
                    "policy_evaluated": 3,
                    "baseline_filtered": 0,
                    "policy_filtered": 0,
                    "policy_filtered_by_reason": {},
                    "retained_ratio_pct": 100.0,
                },
                "baseline_summary": {"n": 3, "t3_mean": 1.2},
                "policy_summary": {"n": 3, "t3_mean": 1.4},
                "delta": {
                    "t3_mean_delta": 0.2,
                    "t3_win_rate_delta": 1.0,
                    "t3_loss_5pct_rate_delta": -2.0,
                    "big_drop_5pct_rate_delta": 0.0,
                },
                "breakdown": {
                    "market_regime": {},
                    "best_buy_point_type": {},
                    "confirmations": confirmations,
                },
            }
        ]
        run_mock.return_value = payload
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest_top10.json"
            output_md = Path(tmpdir) / "policy_backtest_top10.md"
            rc = main([
                "--policies",
                "delay1_v1_cooldown3",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("bucket_0", text)
            self.assertIn("bucket_9", text)
            self.assertNotIn("bucket_10", text)
            self.assertNotIn("bucket_11", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_new_reason_policy_output_in_markdown(self, run_mock):
        payload = _fake_payload()
        payload["policies"] = [
            {
                "policy": "delay1_v1_bottom_missing_shape_guard",
                "coverage": {
                    "snapshot_days": 5,
                    "picks_seen": 5,
                    "baseline_evaluated": 5,
                    "policy_evaluated": 4,
                    "baseline_filtered": 0,
                    "policy_filtered": 1,
                    "policy_filtered_by_reason": {"bottom_missing_shape_or_stop_drop": 1},
                    "retained_ratio_pct": 80.0,
                },
                "baseline_summary": {
                    "n": 5,
                    "t3_mean": 1.2,
                },
                "policy_summary": {
                    "n": 4,
                    "t3_mean": 1.6,
                },
                "delta": {
                    "t3_mean_delta": 0.4,
                    "t3_win_rate_delta": 1.0,
                    "t3_loss_5pct_rate_delta": -1.0,
                    "big_drop_5pct_rate_delta": 0.0,
                },
            }
        ]
        run_mock.return_value = payload
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest_single.json"
            output_md = Path(tmpdir) / "policy_backtest_single.md"
            rc = main([
                "--policies",
                "delay1_v1_bottom_missing_shape_guard",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["policies"]), 1)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("bottom_missing_shape_or_stop_drop", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_new_trend_reason_policy_output_in_markdown(self, run_mock):
        payload = _fake_payload()
        payload["policies"] = [
            {
                "policy": "delay1_v1_bottom_quality_market_strong_guard",
                "coverage": {
                    "snapshot_days": 5,
                    "picks_seen": 5,
                    "baseline_evaluated": 5,
                    "policy_evaluated": 4,
                    "baseline_filtered": 0,
                    "policy_filtered": 1,
                    "policy_filtered_by_reason": {"bottom_market_not_strong": 1},
                    "retained_ratio_pct": 80.0,
                },
                "baseline_summary": {
                    "n": 5,
                    "t3_mean": 1.2,
                },
                "policy_summary": {
                    "n": 4,
                    "t3_mean": 1.6,
                },
                "delta": {
                    "t3_mean_delta": 0.4,
                    "t3_win_rate_delta": 1.0,
                    "t3_loss_5pct_rate_delta": -1.0,
                    "big_drop_5pct_rate_delta": 0.0,
                },
            }
        ]
        run_mock.return_value = payload
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest_single.json"
            output_md = Path(tmpdir) / "policy_backtest_single.md"
            rc = main([
                "--policies",
                "delay1_v1_bottom_quality_market_strong_guard",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])
            self.assertEqual(rc, 0)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("bottom_market_not_strong", text)


if __name__ == "__main__":
    unittest.main()
