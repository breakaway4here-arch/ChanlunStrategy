import unittest

from chanlun.backtest_execution import (
    SUPPORTED_EXIT_MODELS,
    evaluate_exit_returns,
    evaluate_forward_returns,
)


def _build_kline():
    return {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"],
        "opens": [10.0, 12.0, 13.0, 20.0, 19.0, 21.0],
        "highs": [10.8, 12.6, 14.2, 19.0, 17.5, 21.0],
        "lows": [9.5, 11.2, 12.0, 17.0, 15.0, 19.0],
        "closes": [11.0, 12.0, 13.0, 18.0, 16.0, 20.0],
    }


class BacktestExecutionTests(unittest.TestCase):
    def test_exit_t3_matches_forward_t3(self):
        sample = evaluate_exit_returns(_build_kline(), "2026-01-03", "delay1_open", "exit_t3")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["exit_model"], "exit_t3")
        self.assertEqual(sample["exit_reason"], "t3_close")
        self.assertEqual(sample["exit_day_index"], 3)
        self.assertEqual(sample["exit_return_pct"], sample["t3_close_pct"])
        self.assertAlmostEqual(sample["exit_return_pct"], 0.0, places=6)
        self.assertEqual(sample["entry_mode"], "delay1_open")
        self.assertEqual(sample["entry_date"], "2026-01-04")

    def test_exit_stop_loss_5pct(self):
        sample = evaluate_exit_returns(_build_kline(), "2026-01-03", "delay1_open", "exit_stop_loss_5pct")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["exit_model"], "exit_stop_loss_5pct")
        self.assertEqual(sample["exit_reason"], "stop_loss_5pct")
        self.assertEqual(sample["exit_day_index"], 1)
        self.assertEqual(sample["exit_return_pct"], -5.0)

    def test_exit_take_profit_8pct_or_t3(self):
        kline = _build_kline().copy()
        kline["highs"] = [10.8, 12.6, 14.2, 25.0, 17.5, 21.0]
        kline["lows"] = [9.5, 11.2, 12.0, 19.5, 15.0, 19.0]
        sample = evaluate_exit_returns(kline, "2026-01-03", "delay1_open", "exit_take_profit_8pct_or_t3")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["exit_model"], "exit_take_profit_8pct_or_t3")
        self.assertEqual(sample["exit_reason"], "take_profit_8pct")
        self.assertEqual(sample["exit_day_index"], 1)
        self.assertEqual(sample["exit_return_pct"], 8.0)
        self.assertAlmostEqual(sample["t3_close_pct"], 8.0, places=6)

    def test_exit_stop5_take8_conservative_prioritizes_stop_when_same_day(self):
        kline = _build_kline().copy()
        kline["highs"] = [10.8, 12.6, 14.2, 30.0, 17.5, 21.0]
        kline["lows"] = [9.5, 11.2, 12.0, 18.0, 15.0, 19.0]
        sample = evaluate_exit_returns(
            kline,
            "2026-01-03",
            "delay1_open",
            "exit_stop5_take8_conservative",
        )
        self.assertIsNotNone(sample)
        self.assertEqual(sample["exit_model"], "exit_stop5_take8_conservative")
        self.assertEqual(sample["exit_reason"], "stop_loss_5pct")
        self.assertEqual(sample["exit_day_index"], 1)
        self.assertEqual(sample["exit_return_pct"], -5.0)

    def test_exit_unknown_model_returns_none(self):
        self.assertIsNone(
            evaluate_exit_returns(_build_kline(), "2026-01-03", "delay1_open", "bad_exit_model"),
        )

    def test_immediate_close_mode(self):
        res = evaluate_forward_returns(_build_kline(), "2026-01-03", "immediate_close", horizon=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["entry_mode"], "immediate_close")
        self.assertEqual(res["entry_date"], "2026-01-03")
        self.assertEqual(res["ref_date"], "2026-01-03")
        self.assertEqual(res["n_forward_days"], 3)
        self.assertAlmostEqual(res["t1_close_pct"], 38.4615384615, places=6)
        self.assertAlmostEqual(res["t3_close_pct"], 53.8461538462, places=6)
        self.assertAlmostEqual(res["max_up_3d"], 61.5384615385, places=6)
        self.assertAlmostEqual(res["max_dd_3d"], 15.3846153846, places=6)

    def test_delay1_open_mode(self):
        res = evaluate_forward_returns(_build_kline(), "2026-01-03", "delay1_open", horizon=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["entry_mode"], "delay1_open")
        self.assertEqual(res["entry_date"], "2026-01-04")
        self.assertEqual(res["ref_date"], "2026-01-04")
        self.assertEqual(res["n_forward_days"], 3)
        self.assertAlmostEqual(res["t1_close_pct"], -10.0, places=6)
        self.assertAlmostEqual(res["t3_close_pct"], 0.0, places=6)
        self.assertAlmostEqual(res["max_up_3d"], 5.0, places=6)
        self.assertAlmostEqual(res["max_dd_3d"], -25.0, places=6)

    def test_delay1_close_mode(self):
        res = evaluate_forward_returns(_build_kline(), "2026-01-03", "delay1_close", horizon=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["entry_mode"], "delay1_close")
        self.assertEqual(res["entry_date"], "2026-01-04")
        self.assertEqual(res["ref_date"], "2026-01-04")
        self.assertEqual(res["n_forward_days"], 2)
        self.assertAlmostEqual(res["t1_close_pct"], -11.1111111111, places=6)
        self.assertAlmostEqual(res["t3_close_pct"], 11.1111111111, places=6)
        self.assertAlmostEqual(res["max_up_3d"], 16.6666666667, places=6)
        self.assertAlmostEqual(res["max_dd_3d"], -16.6666666667, places=6)

    def test_delay_mode_need_next_day(self):
        kline = _build_kline()
        self.assertIsNone(evaluate_forward_returns(kline, "2026-01-06", "immediate_close", horizon=5))
        self.assertIsNone(evaluate_forward_returns(kline, "2026-01-06", "delay1_open", horizon=5))
        self.assertIsNone(evaluate_forward_returns(kline, "2026-01-05", "delay1_close", horizon=5))

    def test_invalid_entry_mode(self):
        self.assertIsNone(evaluate_forward_returns(_build_kline(), "2026-01-03", "bad_mode"))

    def test_supported_exit_models(self):
        self.assertEqual(
            SUPPORTED_EXIT_MODELS,
            {
                "exit_t3",
                "exit_stop_loss_5pct",
                "exit_take_profit_8pct_or_t3",
                "exit_stop5_take8_conservative",
            },
        )


if __name__ == "__main__":
    unittest.main()
