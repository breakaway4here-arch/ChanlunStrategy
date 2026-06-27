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


if __name__ == "__main__":
    unittest.main()
