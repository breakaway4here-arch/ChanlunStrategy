import unittest
from unittest.mock import patch

from chanlun.policy_experiment_metrics import (
    _run_fusion_threshold_scan,
    _run_one_policy,
    _summarize_fusion_variant,
)


def _pick(code):
    return {
        "code": code,
        "best_buy_point": {
            "type": "一买",
            "trend_strength": 2.0,
            "volatility": 0.05,
            "pivot": {"ZG": 12.0, "ZD": 10.0},
            "segment": {"high": 12.0, "low": 10.0},
        },
    }


class BacktestR04PolicyCoverageTests(unittest.TestCase):
    def test_fusion_promotion_coverage_uses_mature_t3_rows(self):
        mature = {
            "n_forward_days": 3,
            "maturity": {"t1": True, "t3": True, "t5": False},
            "t3_close_pct": 3.0,
            "max_dd_3d": -2.0,
        }
        immature = {
            "n_forward_days": 2,
            "maturity": {"t1": True, "t3": False, "t5": False},
            "t3_close_pct": None,
            "max_dd_3d": None,
        }
        row = _summarize_fusion_variant(
            "fusion_strict",
            "fusion_strict",
            [
                {"pick": _pick("000001"), "baseline_sample": mature},
                {"pick": _pick("000002"), "baseline_sample": immature},
            ],
            baseline_n=1,
            t3_mean_before=3.0,
            t3_win_rate_before=100.0,
            drawdown_before=-2.0,
        )

        self.assertEqual(row["samples_before"], 1)
        self.assertEqual(row["samples_after"], 1)
        self.assertEqual(row["n_after"], 1)
        self.assertEqual(row["rows_processed"], 2)
        self.assertEqual(row["coverage"], 1.0)
        self.assertEqual(row["failure_sample_audit"]["samples"], 1)

    def test_fusion_scan_uses_mature_t3_baseline_denominator(self):
        mature = {
            "n_forward_days": 3,
            "maturity": {"t1": True, "t3": True, "t5": False},
            "t3_close_pct": 3.0,
            "max_dd_3d": -2.0,
        }
        immature = {
            "n_forward_days": 2,
            "maturity": {"t1": True, "t3": False, "t5": False},
            "t3_close_pct": None,
            "max_dd_3d": None,
        }
        pick_one = _pick("000001")
        pick_two = _pick("000002")
        context = {
            "baseline_samples": [mature, immature],
            "evaluated_rows": [
                {"pick": pick_one, "baseline_sample": mature, "normalized_kline": {}},
                {"pick": pick_two, "baseline_sample": immature, "normalized_kline": {}},
            ],
            "coverage": {"picks_seen": 2},
            "execution": {"baseline_rows": 2},
        }

        with patch(
            "chanlun.policy_experiment_metrics._build_picks_fusion_snapshot_rows",
            return_value=[
                ("2026-01-01", "picks_fusion", pick_one),
                ("2026-01-02", "picks_fusion", pick_two),
            ],
        ), patch(
            "chanlun.policy_experiment_metrics._build_fusion_baseline_context",
            return_value=context,
        ):
            scan = _run_fusion_threshold_scan(["fusion_strict"])

        self.assertEqual(scan["baseline_metrics"]["samples"], 1)
        self.assertEqual(scan["baseline_metrics"]["rows_processed"], 2)
        profile = scan["profiles"][0]
        self.assertEqual(profile["samples_before"], 1)
        self.assertEqual(profile["samples_after"], 1)
        self.assertEqual(profile["rows_processed"], 2)
        self.assertEqual(profile["coverage"], 1.0)

    def test_right_censored_policy_row_is_processed_but_not_t3_evaluable(self):
        result = _run_one_policy(
            "delay1_v1",
            [
                {
                    "snap_date": "2026-01-01",
                    "pick": _pick("000001"),
                    "baseline_sample": {
                        "n_forward_days": 2,
                        "maturity": {"t1": True, "t3": False, "t5": False},
                        "t3_close_pct": None,
                    },
                }
            ],
            {"2026-01-01": 0},
            {
                "n": 1,
                "n_t3_evaluable": 1,
                "t3_mean": 1.0,
                "t3_win_rate": 100.0,
                "t3_loss_5pct_rate": 0.0,
                "big_drop_5pct_rate": 0.0,
            },
            {
                "picks_seen": 1,
                "baseline_rows_processed": 1,
                "baseline_filtered": 0,
            },
        )

        coverage = result["coverage"]
        self.assertEqual(coverage["policy_rows_processed"], 1)
        self.assertEqual(coverage["policy_t3_evaluable"], 0)
        self.assertEqual(coverage["policy_evaluated"], 0)
        self.assertEqual(coverage["policy_right_censored"], 1)
        self.assertEqual(coverage["retained_ratio_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
