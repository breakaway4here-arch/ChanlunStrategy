import unittest

from chanlun.experiment_gates import evaluate_promotion_gates


class PromotionGateTests(unittest.TestCase):
    def test_all_gates_pass(self):
        before = {
            "sample_count": 120,
            "t3_mean": 1.0,
            "t3_win_rate": 15.0,
            "t3_loss_5pct_rate": -2.0,
            "big_drop_5pct_rate": -3.0,
        }
        after = {
            "sample_count": 150,
            "t3_mean": 2.0,
            "t3_win_rate": 20.0,
            "t3_loss_5pct_rate": -8.0,
            "big_drop_5pct_rate": -10.0,
        }
        coverage = {"evaluated": 120}
        result = evaluate_promotion_gates(before, after, coverage)

        self.assertEqual(result["final_decision"], "pass")
        self.assertEqual(result["gates"]["coverage_evaluated"]["status"], "pass")
        self.assertEqual(result["gates"]["sample_count"]["status"], "pass")
        self.assertEqual(result["gates"]["t3_mean_delta"]["status"], "pass")
        self.assertEqual(result["gates"]["t3_win_rate_delta"]["status"], "pass")
        self.assertEqual(result["gates"]["t3_loss_5pct_rate_delta"]["status"], "pass")
        self.assertEqual(result["gates"]["big_drop_5pct_rate_delta"]["status"], "pass")

    def test_fail_when_gate_not_passed(self):
        before = {
            "sample_count": 200,
            "t3_mean": 1.0,
            "t3_win_rate": 15.0,
            "t3_loss_5pct_rate": -2.0,
            "big_drop_5pct_rate": -3.0,
        }
        after = {
            "sample_count": 200,
            "t3_mean": 1.2,
            "t3_win_rate": 17.0,
            "t3_loss_5pct_rate": -1.0,
            "big_drop_5pct_rate": -6.0,
        }
        coverage = {"evaluated": 200}
        result = evaluate_promotion_gates(before, after, coverage)

        self.assertEqual(result["final_decision"], "fail")
        self.assertEqual(result["gates"]["t3_loss_5pct_rate_delta"]["status"], "fail")
        self.assertIn("failed gates", result["reason"][0])

    def test_insufficient_data_when_coverage_zero(self):
        before = {
            "sample_count": 120,
            "t3_mean": 1.0,
            "t3_win_rate": 15.0,
            "t3_loss_5pct_rate": -2.0,
            "big_drop_5pct_rate": -3.0,
        }
        after = {
            "sample_count": 150,
            "t3_mean": 2.0,
            "t3_win_rate": 20.0,
            "t3_loss_5pct_rate": -8.0,
            "big_drop_5pct_rate": -10.0,
        }
        coverage = {"evaluated": 0}
        result = evaluate_promotion_gates(before, after, coverage)

        self.assertEqual(result["final_decision"], "insufficient_data")
        self.assertEqual(result["gates"]["coverage_evaluated"]["status"], "insufficient")

    def test_insufficient_data_when_missing_metric(self):
        before = {
            "sample_count": 120,
            "t3_mean": 1.0,
            "t3_win_rate": 15.0,
        }
        after = {
            "sample_count": 150,
            "t3_mean": 2.0,
            "t3_win_rate": 20.0,
            "t3_loss_5pct_rate": -8.0,
            "big_drop_5pct_rate": -10.0,
        }
        coverage = {"evaluated": 120}
        result = evaluate_promotion_gates(before, after, coverage)

        self.assertEqual(result["final_decision"], "insufficient_data")
        self.assertIn("missing metrics", result["reason"][0])

    def test_sample_count_accepts_n_alias(self):
        before = {
            "n": 120,
            "t3_mean": 1.0,
            "t3_win_rate": 15.0,
            "t3_loss_5pct_rate": -4.0,
            "big_drop_5pct_rate": -8.0,
        }
        after = {
            "n": 150,
            "t3_mean": 2.5,
            "t3_win_rate": 20.0,
            "t3_loss_5pct_rate": -15.0,
            "big_drop_5pct_rate": -15.0,
        }
        coverage = {"evaluated": 10}
        result = evaluate_promotion_gates(before, after, coverage)

        self.assertEqual(result["final_decision"], "pass")
        self.assertEqual(result["gates"]["sample_count"]["status"], "pass")
        self.assertNotEqual(result["gates"]["coverage_evaluated"]["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
