import unittest

from chanlun.backtest_metrics import summarize_return_samples


class BacktestMetricsTests(unittest.TestCase):
    def test_empty_samples_returns_none(self):
        self.assertIsNone(summarize_return_samples([]))

    def test_summarize_return_samples_with_evaluable_and_unevaluable(self):
        samples = [
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 2.5,
                "max_up_3d": 4.0,
                "max_dd_3d": -1.0,
            },
            {
                "t1_close_pct": 3.0,
                "t3_close_pct": -6.0,
                "max_up_3d": 5.2,
                "max_dd_3d": -7.0,
            },
            {
                "t1_close_pct": 2.0,
                "t3_close_pct": None,
                "max_up_3d": 2.0,
                "max_dd_3d": None,
            },
        ]

        summary = summarize_return_samples(samples)
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["n_evaluable"], 2)
        self.assertEqual(summary["t1_mean"], 2.0)
        self.assertEqual(summary["t1_median"], 2.0)
        self.assertEqual(summary["t3_mean"], -1.75)
        self.assertEqual(summary["t3_median"], -1.75)
        self.assertEqual(summary["t3_win_rate"], 50.0)
        self.assertEqual(summary["t3_loss_5pct_rate"], 50.0)
        self.assertEqual(summary["max_up_3d_mean"], 3.73)
        self.assertEqual(summary["max_dd_3d_mean"], -4.0)
        self.assertEqual(summary["big_drop_5pct_rate"], 50.0)
        self.assertEqual(summary["big_run_5pct_rate"], 33.3)

    def test_summary_excludes_non_mature_t3_and_t5_values(self):
        summary = summarize_return_samples([
            {
                "n_forward_days": 2,
                "t1_close_pct": 1.0,
                "t3_close_pct": 99.0,
                "t5_close_pct": 99.0,
                "max_up_3d": 99.0,
                "max_dd_3d": -99.0,
            },
            {
                "n_forward_days": 3,
                "t1_close_pct": 2.0,
                "t3_close_pct": 3.0,
                "t5_close_pct": 88.0,
                "max_up_3d": 4.0,
                "max_dd_3d": -2.0,
            },
        ])

        self.assertEqual(summary["n"], 2)
        self.assertEqual(summary["n_t1_evaluable"], 2)
        self.assertEqual(summary["n_evaluable"], 1)
        self.assertEqual(summary["n_t5_evaluable"], 0)
        self.assertEqual(summary["t3_mean"], 3.0)
        self.assertIsNone(summary["t5_mean"])
        self.assertEqual(summary["max_up_3d_mean"], 4.0)

    def test_nonfinite_forward_day_count_is_not_mature(self):
        summary = summarize_return_samples([
            {
                "n_forward_days": float("inf"),
                "t3_close_pct": 10.0,
            }
        ])

        self.assertEqual(summary["n"], 1)
        self.assertEqual(summary["n_evaluable"], 0)
        self.assertIsNone(summary["t3_mean"])

    def test_partial_maturity_metadata_does_not_infer_missing_horizon(self):
        summary = summarize_return_samples([
            {
                "n_forward_days": 5,
                "maturity": {"t3": True},
                "t3_close_pct": 3.0,
                "t5_close_pct": 9.0,
            }
        ])

        self.assertEqual(summary["n_t3_evaluable"], 1)
        self.assertEqual(summary["n_t5_evaluable"], 0)
        self.assertIsNone(summary["t5_mean"])

    def test_nonfinite_return_is_not_summarized(self):
        summary = summarize_return_samples([
            {"t3_close_pct": float("nan")},
            {"t3_close_pct": float("inf")},
            {"t3_close_pct": float("-inf")},
        ])

        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["n_evaluable"], 0)
        self.assertIsNone(summary["t3_mean"])

    def test_boolean_return_is_not_coerced_to_numeric_statistic(self):
        summary = summarize_return_samples([
            {"t3_close_pct": True},
        ])

        self.assertEqual(summary["n"], 1)
        self.assertEqual(summary["n_evaluable"], 0)
        self.assertIsNone(summary["t3_mean"])


if __name__ == "__main__":
    unittest.main()
