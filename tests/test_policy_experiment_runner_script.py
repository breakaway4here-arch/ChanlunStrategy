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


if __name__ == "__main__":
    unittest.main()
