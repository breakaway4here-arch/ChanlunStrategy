import unittest
from unittest.mock import patch

from chanlun.backtest_execution import evaluate_forward_returns
from chanlun.filtered_sample_audit import _normalize_kline as normalize_filtered
from chanlun.historical_experiment_metrics import _normalize_kline as normalize_historical
from scripts.backtest_recommendation_quality import (
    _pick_local_kline,
    daily_kline_after,
)
from scripts.backtest_scoring_alpha_impact import _extract_kline, _kline_for_code


def _raw_kline():
    return {
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "opens": [10.0, 10.5, 11.0],
        "highs": [10.5, 11.0, 11.5],
        "lows": [9.5, 10.0, 10.5],
        "closes": [10.2, 10.7, 11.2],
        "is_final": [True, False, True],
    }


class BacktestR04CallerTests(unittest.TestCase):
    def test_historical_normalizer_preserves_row_finality(self):
        normalized = normalize_historical(_raw_kline())
        self.assertEqual(normalized["is_final"], [True, False, True])

    def test_filtered_normalizer_preserves_row_finality(self):
        normalized = normalize_filtered(_raw_kline())
        self.assertEqual(normalized["is_final"], [True, False, True])

    def test_recommendation_local_normalizer_preserves_row_finality(self):
        normalized = _pick_local_kline(_raw_kline())
        self.assertEqual(normalized["is_final"], [True, False, True])

    @patch("scripts.backtest_recommendation_quality.fetch_daily_kline")
    def test_recommendation_fetched_normalizer_preserves_row_finality(self, fetch_mock):
        fetch_mock.return_value = _raw_kline()
        normalized = daily_kline_after("000001", "2026-01-02")
        self.assertEqual(normalized["is_final"], [True, False, True])

    def test_alpha_normalizer_and_cache_preserve_row_finality(self):
        rows = _extract_kline(_raw_kline())
        self.assertEqual(rows["2026-01-02"]["is_final"], False)
        normalized = _kline_for_code({"000001": rows}, "000001")
        self.assertEqual(normalized["is_final"], [True, False, True])

    def test_missing_finality_is_not_accepted_by_callers(self):
        raw = _raw_kline()
        raw.pop("is_final")
        self.assertIsNone(normalize_historical(raw))
        self.assertEqual(normalize_filtered(raw), {})
        self.assertIsNone(_pick_local_kline(raw))
        self.assertIsNone(_extract_kline(raw))

    def test_each_normalizer_feeds_evaluator_without_losing_nonfinality(self):
        normalized = [
            normalize_historical(_raw_kline()),
            normalize_filtered(_raw_kline()),
            _pick_local_kline(_raw_kline()),
            _kline_for_code({"000001": _extract_kline(_raw_kline())}, "000001"),
        ]
        with patch(
            "scripts.backtest_recommendation_quality.fetch_daily_kline",
            return_value=_raw_kline(),
        ):
            normalized.append(daily_kline_after("000001", "2026-01-02"))

        for kline in normalized:
            with self.subTest(kline=kline):
                result = evaluate_forward_returns(
                    kline, "2026-01-01", "immediate_close", horizon=5
                )
                self.assertIsNotNone(result)
                self.assertFalse(result["maturity"]["t1"])
                self.assertFalse(result["maturity"]["t3"])


if __name__ == "__main__":
    unittest.main()
