import unittest

import numpy as np

from chanlun.backtest_execution import (
    SUPPORTED_EXIT_MODELS,
    evaluate_exit_returns,
    evaluate_forward_returns,
    execute_signal,
)
from scripts.backtest_recommendation_quality import iter_signal_records_from_report


def _build_kline():
    return {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"],
        "opens": [10.0, 12.0, 13.0, 20.0, 19.0, 21.0],
        "highs": [11.2, 12.6, 14.2, 20.5, 19.5, 21.0],
        "lows": [9.5, 11.2, 12.0, 17.0, 15.0, 19.0],
        "closes": [11.0, 12.0, 13.0, 18.0, 16.0, 20.0],
        "is_final": [True, True, True, True, True, True],
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
        kline["highs"] = [11.2, 12.6, 14.2, 25.0, 19.5, 21.0]
        kline["lows"] = [9.5, 11.2, 12.0, 17.5, 15.0, 19.0]
        sample = evaluate_exit_returns(kline, "2026-01-03", "delay1_open", "exit_take_profit_8pct_or_t3")
        self.assertIsNotNone(sample)
        self.assertEqual(sample["exit_model"], "exit_take_profit_8pct_or_t3")
        self.assertEqual(sample["exit_reason"], "take_profit_8pct")
        self.assertEqual(sample["exit_day_index"], 1)
        self.assertEqual(sample["exit_return_pct"], 8.0)
        self.assertAlmostEqual(sample["t3_close_pct"], 8.0, places=6)

    def test_exit_stop5_take8_conservative_prioritizes_stop_when_same_day(self):
        kline = _build_kline().copy()
        kline["highs"] = [11.2, 12.6, 14.2, 30.0, 19.5, 21.0]
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
        self.assertAlmostEqual(res["t1_return"], res["t1_close_pct"])
        self.assertAlmostEqual(res["t3_return"], res["t3_close_pct"])
        self.assertIsNone(res["t5_return"])
        self.assertFalse(res["maturity"]["t5"])
        self.assertAlmostEqual(res["max_drawdown"], 15.3846153846, places=6)
        self.assertAlmostEqual(res["max_up_3d"], 61.5384615385, places=6)
        self.assertAlmostEqual(res["max_dd_3d"], 15.3846153846, places=6)
        self.assertFalse(res["hit_stop"])

    def test_delay1_open_mode(self):
        res = evaluate_forward_returns(_build_kline(), "2026-01-03", "delay1_open", horizon=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["entry_mode"], "delay1_open")
        self.assertEqual(res["entry_date"], "2026-01-04")
        self.assertEqual(res["ref_date"], "2026-01-04")
        self.assertEqual(res["n_forward_days"], 3)
        self.assertAlmostEqual(res["t1_return"], -10.0, places=6)
        self.assertAlmostEqual(res["t1_close_pct"], -10.0, places=6)
        self.assertAlmostEqual(res["t3_close_pct"], 0.0, places=6)
        self.assertIsNone(res["t5_return"])
        self.assertFalse(res["maturity"]["t5"])
        self.assertAlmostEqual(res["max_up_3d"], 5.0, places=6)
        self.assertAlmostEqual(res["max_dd_3d"], -25.0, places=6)
        self.assertAlmostEqual(res["max_drawdown"], -25.0, places=6)
        self.assertTrue(res["hit_stop"])

    def test_delay1_close_mode(self):
        res = evaluate_forward_returns(_build_kline(), "2026-01-03", "delay1_close", horizon=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["entry_mode"], "delay1_close")
        self.assertEqual(res["entry_date"], "2026-01-04")
        self.assertEqual(res["ref_date"], "2026-01-04")
        self.assertEqual(res["n_forward_days"], 2)
        self.assertAlmostEqual(res["t1_close_pct"], -11.1111111111, places=6)
        self.assertIsNone(res["t3_close_pct"])
        self.assertIsNone(res["t5_return"])
        self.assertFalse(res["maturity"]["t3"])
        self.assertFalse(res["maturity"]["t5"])
        self.assertIsNone(res["max_up_3d"])
        self.assertIsNone(res["max_dd_3d"])
        self.assertAlmostEqual(res["max_drawdown"], -16.6666666667, places=6)
        self.assertTrue(res["hit_stop"])

    def test_incomplete_forward_window_does_not_fill_t3_or_t5(self):
        short_kline = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "opens": [10.0, 10.0, 10.0, 10.0],
            "highs": [11.0, 12.0, 14.0, 16.0],
            "lows": [9.0, 9.5, 10.0, 10.0],
            "closes": [10.0, 12.0, 14.0, 16.0],
            "is_final": [True, True, True, True],
        }
        res = evaluate_forward_returns(short_kline, "2026-01-02", "immediate_close", horizon=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["n_forward_days"], 2)
        self.assertAlmostEqual(res["t1_return"], 16.6666666667, places=6)
        self.assertIsNone(res["t3_return"])
        self.assertIsNone(res["t5_return"])
        self.assertEqual(res["maturity"], {"t1": True, "t3": False, "t5": False})

    def test_exit_t3_partial_window_remains_right_censored(self):
        sample = evaluate_exit_returns(
            {
                "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
                "opens": [10.0, 10.0, 10.0, 10.0],
                "highs": [11.0, 12.0, 14.0, 16.0],
                "lows": [9.0, 9.5, 10.0, 10.0],
                "closes": [10.0, 12.0, 14.0, 16.0],
                "is_final": [True, True, True, True],
            },
            "2026-01-02",
            "immediate_close",
            "exit_t3",
            horizon=5,
        )

        self.assertIsNotNone(sample)
        self.assertIsNone(sample["t3_close_pct"])
        self.assertIsNone(sample["exit_return_pct"])
        self.assertEqual(sample["exit_reason"], "t3_not_matured")

    def test_invalid_dates_or_ohlc_never_become_mature_forward_samples(self):
        duplicate_dates = _build_kline().copy()
        duplicate_dates["dates"] = list(duplicate_dates["dates"])
        duplicate_dates["dates"][4] = duplicate_dates["dates"][3]
        self.assertIsNone(
            evaluate_forward_returns(
                duplicate_dates, "2026-01-03", "immediate_close", horizon=5
            )
        )

        nonfinite_price = _build_kline().copy()
        nonfinite_price["closes"] = list(nonfinite_price["closes"])
        nonfinite_price["closes"][4] = float("nan")
        self.assertIsNone(
            evaluate_forward_returns(
                nonfinite_price, "2026-01-03", "immediate_close", horizon=5
            )
        )

    def test_nonfinal_forward_bar_does_not_mature_t3(self):
        kline = _build_kline().copy()
        kline["is_final"][5] = False

        result = evaluate_forward_returns(
            kline, "2026-01-03", "immediate_close", horizon=5
        )

        self.assertIsNotNone(result)
        self.assertIsNone(result["t3_close_pct"])
        self.assertFalse(result["maturity"]["t3"])

    def test_missing_finality_is_not_inferred_as_all_final(self):
        kline = _build_kline().copy()
        kline.pop("is_final")

        self.assertIsNone(
            evaluate_forward_returns(
                kline, "2026-01-03", "immediate_close", horizon=5
            )
        )

    def test_explicit_closed_contract_allows_all_final_inference(self):
        kline = _build_kline().copy()
        kline.pop("is_final")
        kline["finality_contract"] = "all_bars_closed_v1"

        result = evaluate_forward_returns(
            kline, "2026-01-03", "immediate_close", horizon=5
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["maturity"]["t3"])

    def test_invalid_ohlc_geometry_is_rejected(self):
        kline = _build_kline().copy()
        kline["highs"] = list(kline["highs"])
        kline["lows"] = list(kline["lows"])
        kline["highs"][4] = 8.0
        kline["lows"][4] = 9.0

        self.assertIsNone(
            evaluate_forward_returns(
                kline, "2026-01-03", "immediate_close", horizon=5
            )
        )

    def test_nonfinal_bar_does_not_pollute_auxiliary_risk_metrics(self):
        kline = _build_kline().copy()
        kline["is_final"] = list(kline["is_final"])
        kline["is_final"][5] = False
        kline["lows"] = list(kline["lows"])
        kline["lows"][5] = 1.0

        result = evaluate_forward_returns(
            kline, "2026-01-03", "immediate_close", horizon=5
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["auxiliary_metrics"]["status"], "partial")
        self.assertEqual(result["auxiliary_metrics"]["completed_forward_days"], 2)
        self.assertAlmostEqual(result["max_drawdown"], 15.3846153846, places=6)
        self.assertFalse(result["hit_stop"])

    def test_nonfinal_entry_bar_is_not_evaluable(self):
        kline = _build_kline().copy()
        kline["is_final"] = [True] * len(kline["dates"])
        kline["is_final"][2] = False

        self.assertIsNone(
            evaluate_forward_returns(
                kline, "2026-01-03", "immediate_close", horizon=5
            )
        )

    def test_string_false_finality_does_not_mature_forward_horizons(self):
        kline = _build_kline().copy()
        kline.pop("is_final")
        kline["finals"] = [True, True, True, "false", True, True]

        result = evaluate_forward_returns(
            kline, "2026-01-01", "immediate_close", horizon=5
        )

        self.assertIsNone(result)

    def test_scalar_malformed_finality_is_rejected_without_exception(self):
        kline = _build_kline().copy()
        kline["is_final"] = False

        self.assertIsNone(
            evaluate_forward_returns(
                kline, "2026-01-01", "immediate_close", horizon=5
            )
        )

    def test_boolean_ohlc_values_are_not_numeric_market_bars(self):
        kline = _build_kline().copy()
        kline["closes"] = list(kline["closes"])
        kline["closes"][3] = True

        self.assertIsNone(
            evaluate_forward_returns(
                kline, "2026-01-01", "immediate_close", horizon=5
            )
        )

    def test_numpy_boolean_finality_is_normalized_to_python_flags(self):
        kline = _build_kline().copy()
        kline["is_final"] = np.array(
            [True, True, True, False, True, True], dtype=bool
        )

        result = evaluate_forward_returns(
            kline, "2026-01-01", "immediate_close", horizon=5
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["maturity"], {"t1": True, "t3": False, "t5": False})

    def test_numpy_boolean_ohlc_values_are_rejected_before_numeric_coercion(self):
        kline = _build_kline().copy()
        kline["opens"] = np.ones(6, dtype=bool)
        kline["highs"] = np.ones(6, dtype=bool)
        kline["lows"] = np.ones(6, dtype=bool)
        kline["closes"] = np.ones(6, dtype=bool)

        self.assertIsNone(
            evaluate_forward_returns(
                kline, "2026-01-01", "immediate_close", horizon=5
            )
        )

    def test_signal_records_prefer_workspace_opportunity_score(self):
        report = {
            "date": "2026-06-30",
            "picks_fusion": [{
                "code": "600001",
                "score": 12,
                "best_buy_point": {"current_price": 9.9},
            }],
            "workspace": {
                "views": {
                    "main": [{
                        "code": "600001",
                        "opportunity_score": 87,
                        "reference_price": 10.5,
                    }],
                    "luojie": [{
                        "code": "600002",
                        "opportunity_score": 71,
                        "current_price": 18.8,
                    }],
                }
            },
        }

        rows = iter_signal_records_from_report(report)

        self.assertEqual(rows, [
            {
                "code": "600001",
                "date": "2026-06-30",
                "source_view": "main",
                "opportunity_score": 87.0,
                "ref_price": 10.5,
            },
            {
                "code": "600002",
                "date": "2026-06-30",
                "source_view": "luojie",
                "opportunity_score": 71.0,
                "ref_price": 18.8,
            },
        ])

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

    def test_execute_signal_for_a(self):
        action = execute_signal({"category": "A"})
        self.assertEqual(action["action"], "place_order")
        self.assertTrue(action["execute"])

    def test_execute_signal_for_b(self):
        action = execute_signal({"category": "B"})
        self.assertEqual(action["action"], "log_only")
        self.assertFalse(action["execute"])

    def test_execute_signal_for_c(self):
        action = execute_signal({"category": "C"})
        self.assertEqual(action["action"], "ignore")
        self.assertFalse(action["execute"])

    def test_execute_signal_from_classification(self):
        action = execute_signal({"trend_strength": 2, "pivot": {"ZG": 10}, "segment": {"high": 11}, "volatility": 0.05})
        self.assertEqual(action["action"], "place_order")
        self.assertEqual(action["category"], "A")


if __name__ == "__main__":
    unittest.main()
