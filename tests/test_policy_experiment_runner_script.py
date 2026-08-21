import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from contextlib import redirect_stderr
from unittest.mock import patch

from scripts.run_policy_experiments import _current_code_sha, main


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


def _returns_matching_scorecard(card):
    count = card["sample_size"]
    hit_count = round(card["hit_rate_ge_5"] * count / 100.0)
    median_value = float(card["median_close_return"])
    mean_value = float(card["mean_close_return"])
    low_count = count - hit_count
    lower_count = count // 2 - 1
    high_value = max(
        5.0,
        median_value + count * (mean_value - median_value) / hit_count,
    )
    median_count = low_count - lower_count
    lower_value = (
        count * mean_value
        - median_count * median_value
        - hit_count * high_value
    ) / lower_count
    return (
        [lower_value] * lower_count
        + [median_value] * median_count
        + [high_value] * hit_count
    )


def _write_oot_manifest(root, cards, code_sha):
    artifacts = []
    for card in cards:
        contract = {
            "source_pool": card["source_pool"],
            "strategy_version": card["version"],
            "intended_horizon": card["intended_horizon"],
            "entry_mode": card["entry_mode"],
            "cutoff": card["oot_cutoff"],
            "code_sha": code_sha,
        }
        artifact_path = root / "{}.json".format(card["version"])
        active_dates = []
        for index in range(card["active_dates"]):
            month = "07" if index < (card["active_dates"] + 1) // 2 else "08"
            day = index + 1 if month == "07" else index + 1 - (
                (card["active_dates"] + 1) // 2
            )
            active_dates.append("2026-{}-{:02d}".format(month, day))
        samples = []
        close_returns = _returns_matching_scorecard(card)
        for index in range(card["sample_size"]):
            report_date = active_dates[index % len(active_dates)]
            samples.append({
                "report_date": report_date,
                "target_date": card["oot_cutoff"],
                "feature_as_of": report_date,
                "maturity_status": "mature",
                "close_return": close_returns[index],
                "source_record_hash": hashlib.sha256(
                    "{}:{}".format(card["version"], index).encode("utf-8")
                ).hexdigest(),
            })
        artifact_bytes = json.dumps({
            "schema_version": 1,
            "contract": contract,
            "samples": samples,
        }, sort_keys=True).encode("utf-8")
        artifact_path.write_bytes(artifact_bytes)
        manifest_entry = dict(contract)
        manifest_entry.update({
            "data_hash": hashlib.sha256(artifact_bytes).hexdigest(),
            "artifact_path": artifact_path.name,
        })
        artifacts.append(manifest_entry)
    manifest_path = root / "oot-attestation.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "artifacts": artifacts,
    }), encoding="utf-8")
    return manifest_path


class PolicyExperimentRunnerScriptTests(unittest.TestCase):
    @patch("scripts.run_policy_experiments.subprocess.run")
    def test_code_sha_attestation_rejects_dirty_tracked_files(self, run_mock):
        run_mock.return_value.stdout = " M chanlun/policy_experiment_metrics.py\n"

        with self.assertRaisesRegex(ValueError, "dirty"):
            _current_code_sha()

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_can_evaluate_locked_high_return_scorecards_as_shadow(self, run_mock):
        run_mock.return_value = _fake_payload()
        evidence = {
            "truth_verified": True,
            "leakage_free": True,
            "maturity_verified": True,
            "oot_locked": True,
        }
        baseline = {
            "source_pool": "picks_fusion",
            "version": "baseline-v1",
            "entry_mode": "immediate_close",
            "intended_horizon": 3,
            "oot_cutoff": "2026-08-20",
            "sample_size": 120,
            "active_dates": 24,
            "active_months": 2,
            "mean_close_return": 2.0,
            "median_close_return": 1.8,
            "hit_rate_ge_5": 40.0,
            "research_evidence": evidence,
        }
        candidate = dict(baseline)
        candidate.update({
            "version": "candidate-v2",
            "mean_close_return": 3.0,
            "median_close_return": 2.0,
            "hit_rate_ge_5": 45.0,
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "scorecards.json"
            input_path.write_text(json.dumps({
                "baseline": baseline,
                "candidates": [candidate],
            }), encoding="utf-8")
            output_json = Path(tmpdir) / "policy.json"
            output_md = Path(tmpdir) / "policy.md"
            code_sha = "a" * 40
            attestation_path = _write_oot_manifest(
                Path(tmpdir), [baseline, candidate], code_sha
            )
            with patch(
                "scripts.run_policy_experiments._current_code_sha",
                return_value=code_sha,
            ):
                rc = main([
                    "--policies", "delay1_v1",
                    "--high-return-scorecards-json", str(input_path),
                    "--high-return-oot-attestation-json",
                    str(attestation_path),
                    "--output-json", str(output_json),
                    "--output-md", str(output_md),
                ])

            self.assertEqual(rc, 0)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            selection = payload["high_return_version_selection"]
            self.assertIsNone(selection["selected_version"])
            self.assertEqual(selection["candidates"][0]["research_tier"], "shadow")
            self.assertIn(
                "trusted_oot_provenance_unavailable",
                selection["candidates"][0]["hard_gate_reasons"],
            )

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_scorecard_boolean_flags_without_attestation_cannot_promote(
        self, run_mock
    ):
        run_mock.return_value = _fake_payload()
        baseline = {
            "source_pool": "picks_fusion",
            "version": "baseline-v1",
            "entry_mode": "immediate_close",
            "intended_horizon": 3,
            "oot_cutoff": "2026-08-20",
            "sample_size": 120,
            "active_dates": 24,
            "active_months": 2,
            "mean_close_return": 2.0,
            "median_close_return": 1.8,
            "hit_rate_ge_5": 40.0,
            "research_evidence": {
                "truth_verified": True,
                "leakage_free": True,
                "maturity_verified": True,
                "oot_locked": True,
            },
        }
        candidate = dict(baseline)
        candidate.update({
            "version": "candidate-v2",
            "mean_close_return": 3.0,
            "median_close_return": 2.0,
            "hit_rate_ge_5": 45.0,
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "scorecards.json"
            input_path.write_text(json.dumps({
                "baseline": baseline,
                "candidates": [candidate],
            }), encoding="utf-8")
            output_json = Path(tmpdir) / "policy.json"
            output_md = Path(tmpdir) / "policy.md"

            rc = main([
                "--policies", "delay1_v1",
                "--high-return-scorecards-json", str(input_path),
                "--output-json", str(output_json),
                "--output-md", str(output_md),
            ])

            self.assertEqual(rc, 0)
            selection = json.loads(
                output_json.read_text(encoding="utf-8")
            )["high_return_version_selection"]
            self.assertIsNone(selection["selected_version"])
            self.assertIn(
                "oot_attestation_verified",
                selection["baseline_hard_gate_reasons"],
            )

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_markdown_includes_high_return_selection_without_top_k_cap(
        self, run_mock
    ):
        payload = _fake_payload()
        payload["high_return_version_selection"] = {
            "baseline_version": "baseline-v1",
            "selected_version": "healthy-v2",
            "ranking_metric": "mean_close_return",
            "production_top_k_cap": False,
            "candidates": [
                {
                    "version": "healthy-v2",
                    "source_pool": "picks_fusion",
                    "entry_mode": "immediate_close",
                    "intended_horizon": 3,
                    "sample_size": 120,
                    "active_dates": 24,
                    "active_months": 2,
                    "mean_close_return": 3.0,
                    "median_close_return": 2.2,
                    "hit_rate_ge_5": 45.0,
                    "research_tier": "production",
                    "outlier_driven": False,
                    "promotion_eligible": True,
                }
            ],
        }
        run_mock.return_value = payload
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy.json"
            output_md = Path(tmpdir) / "policy.md"
            rc = main([
                "--policies", "delay1_v1",
                "--output-json", str(output_json),
                "--output-md", str(output_md),
            ])

            self.assertEqual(rc, 0)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("High-return Version Selection", text)
            self.assertIn("healthy-v2", text)
            self.assertIn("outlier_driven", text)
            self.assertIn("no production Top-K cap", text)

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

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_business_metrics_flag_noop_keeps_payload(self, run_mock):
        payload = _fake_payload()
        payload["fusion_threshold_scan"] = {
            "profiles": [
                {
                    "candidate": "fusion_strict",
                    "samples_before": 100,
                    "samples_after": 25,
                    "coverage": 0.25,
                    "coverage_pct": 25.0,
                    "t3_mean_before": 1.2,
                    "t3_mean_after": 1.4,
                    "t3_win_rate_before": 45.0,
                    "t3_win_rate_after": 52.0,
                    "drawdown_mean_before": -5.0,
                    "drawdown_mean_after": -4.8,
                    "accepted": True,
                }
            ],
            "selected": {"candidate": "fusion_strict", "reason": "meets target criteria", "accepted": True},
            "rejected": ["fusion_mid", "fusion_loose"],
            "pareto_frontier": ["fusion_strict"],
        }
        run_mock.return_value = payload

        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "policy_backtest.json"
            output_md = Path(tmpdir) / "policy_backtest.md"
            rc = main([
                "--policies",
                "fusion_strict,fusion_mid,fusion_loose",
                "--business-metrics",
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])

            self.assertEqual(rc, 0)
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("## Fusion Threshold Scan", text)
            self.assertIn("Fusion Threshold Scan", text)
            self.assertIn("Selected Candidate", text)
            self.assertIn("fusion_strict", text)

    @patch("scripts.run_policy_experiments.run_policy_experiment_metrics")
    def test_can_attach_recall_walkforward_summary(self, run_mock):
        run_mock.return_value = _fake_payload()
        recall_payload = {
            "sample_count": 424,
            "network_requests": 0,
            "acceptance_gates": {
                "accepted": True,
                "attention_p95": 5,
                "tail_risk_delta_pp": 1.2,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            recall_json = Path(tmpdir) / "recall.json"
            recall_json.write_text(
                json.dumps(recall_payload), encoding="utf-8"
            )
            output_json = Path(tmpdir) / "policy.json"
            output_md = Path(tmpdir) / "policy.md"
            rc = main([
                "--policies",
                "delay1_v1",
                "--recall-walkforward-json",
                str(recall_json),
                "--output-json",
                str(output_json),
                "--output-md",
                str(output_md),
            ])

            self.assertEqual(0, rc)
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(
                424, payload["recall_walkforward"]["sample_count"]
            )
            text = output_md.read_text(encoding="utf-8")
            self.assertIn("## Recall Walk-forward", text)
            self.assertIn("network_requests: 0", text)


if __name__ == "__main__":
    unittest.main()
