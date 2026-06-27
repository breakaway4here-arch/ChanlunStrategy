import unittest
from unittest.mock import patch

from chanlun.historical_experiment_metrics import (
    entry_mode_for_pick,
    run_historical_experiment_return_metrics,
    should_drop_pick_for_experiment,
)


def fake_kline():
    return {
        "dates": [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
        ],
        "opens": [10.0, 10.1, 10.2, 10.5, 10.6, 10.7, 10.8],
        "highs": [10.1, 10.2, 10.3, 10.6, 10.7, 10.9, 10.95],
        "lows": [9.9, 10.0, 10.1, 10.4, 10.5, 10.6, 10.7],
        "closes": [10.0, 10.1, 10.2, 10.5, 10.6, 10.7, 10.8],
    }


def fake_snapshots_with_types():
    return [
        (
            "2026-01-04",
            "picks_pure",
            {
                "code": "000001",
                "best_buy_point": {"type": "底背驰候选", "index": 6},
                "closes": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
        (
            "2026-01-04",
            "picks_pure",
            {
                "code": "000001",
                "best_buy_point": {"type": "底背驰候选", "index": 4},
                "closes": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
        (
            "2026-01-04",
            "picks_fusion",
            {
                "code": "000001",
                "best_buy_point": {"type": "强势启动候选", "index": 4},
                "closes": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
    ]


class HistoricalExperimentMetricsTests(unittest.TestCase):
    def test_should_drop_pick_for_signal_delay1_by_type_guard_when_newly_formed(self):
        point = {"type": "底背驰候选", "index": 3}
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard",
            {"best_buy_point": point, "closes": [1, 2, 3, 4], "code": "000001"},
        ))

    def test_should_drop_pick_for_signal_delay1_by_type_guard_v2_when_newly_formed(self):
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard_v2",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "index": 3,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "distance_from_reference_pct": 3.1,
                },
                "closes": [1, 2, 3, 4],
                "code": "000001",
            },
        ))

    def test_should_not_drop_pick_for_signal_delay1_by_type_guard_v2_with_rescue(self):
        self.assertFalse(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard_v2",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "index": 3,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "distance_from_reference_pct": 2.8,
                },
                "closes": [1, 2, 3, 4],
                "code": "000001",
            },
        ))

    def test_should_drop_signal_delay1_by_type_guard_v2_when_missing_fields(self):
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard_v2",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "index": 3,
                    "distance_from_reference_pct": 2.8,
                },
                "closes": [1, 2, 3, 4],
                "code": "000001",
            },
        ))
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard_v2",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "index": 3,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                },
                "closes": [1, 2, 3, 4],
                "code": "000001",
            },
        ))

    def test_should_not_drop_when_missing_index_or_closes(self):
        self.assertFalse(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard",
            {"best_buy_point": {"type": "底背驰候选"}, "code": "000001"},
        ))
        self.assertFalse(should_drop_pick_for_experiment(
            "signal_delay1_by_type_guard",
            {"best_buy_point": {"type": "底背驰候选", "index": 1}},
        ))

    def test_should_drop_pick_for_p0_distance_guard(self):
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_p0_distance_guard",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 3.1,
                },
            },
        ))
        self.assertFalse(should_drop_pick_for_experiment(
            "signal_p0_distance_guard",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 3.0,
                },
            },
        ))

    def test_should_drop_pick_for_p1_confirmation_guard(self):
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_p1_confirmation_guard",
            {
                "best_buy_point": {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复"],
                },
            },
        ))
        self.assertFalse(should_drop_pick_for_experiment(
            "signal_p1_confirmation_guard",
            {
                "best_buy_point": {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "关键位不破"],
                },
            },
        ))

    def test_should_drop_pick_for_p0_p1_combined_guard(self):
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_p0_p1_guard",
            {
                "best_buy_point": {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 4.0,
                    "confirmations": ["止跌结构", "EMA5收复", "关键位不破"],
                },
            },
        ))
        self.assertTrue(should_drop_pick_for_experiment(
            "signal_p0_p1_guard",
            {
                "best_buy_point": {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复"],
                },
            },
        ))
        self.assertFalse(should_drop_pick_for_experiment(
            "signal_p0_p1_guard",
            {
                "best_buy_point": {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "关键位不破"],
                },
            },
        ))

    def test_entry_mode_by_type(self):
        self.assertEqual(
            entry_mode_for_pick(
                "signal_delay1_by_type_guard",
                {"best_buy_point": {"type": "底背驰候选"}},
            ),
            "delay1_close",
        )
        self.assertEqual(
            entry_mode_for_pick(
                "signal_delay1_by_type_guard",
                {"best_buy_point": {"type": "强势启动候选"}},
            ),
            "delay1_open",
        )
        self.assertEqual(
            entry_mode_for_pick(
                "signal_delay1_by_type_guard",
                {"best_buy_point": {"type": "一买"}},
            ),
            "immediate_close",
        )
        self.assertEqual(
            entry_mode_for_pick(
                "signal_delay1_by_type_guard_v2",
                {"best_buy_point": {"type": "底背驰候选"}},
            ),
            "delay1_close",
        )
        self.assertEqual(
            entry_mode_for_pick(
                "signal_delay1_by_type_guard_v2",
                {"best_buy_point": {"type": "强势启动候选"}},
            ),
            "delay1_open",
        )
        self.assertEqual(
            entry_mode_for_pick(
                "signal_delay1_by_type_guard_v2",
                {"best_buy_point": {"type": "一买"}},
            ),
            "immediate_close",
        )
        self.assertEqual(
            entry_mode_for_pick("signal_p0_distance_guard", {"best_buy_point": {"type": "底背驰候选"}}),
            "immediate_close",
        )

    @patch("chanlun.historical_experiment_metrics.fetch_daily_kline")
    @patch("chanlun.historical_experiment_metrics.iter_snapshot_picks")
    def test_historical_metrics_returns_nonempty_for_signal_delay1_by_type_guard(
        self,
        iter_snapshot_mock,
        fetch_kline_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(fake_snapshots_with_types())
        fetch_kline_mock.return_value = fake_kline()

        payload = run_historical_experiment_return_metrics("signal_delay1_by_type_guard")
        self.assertIsNotNone(payload)
        self.assertIn("return_metrics", payload)
        self.assertIn("coverage", payload)
        coverage = payload["coverage"]
        self.assertGreater(coverage.get("evaluated", 0), 0)
        self.assertGreater(coverage.get("legacy_evaluated", 0), 0)
        self.assertEqual(payload["return_metrics"]["experiment"]["n"], 2)

    @patch("chanlun.historical_experiment_metrics.fetch_daily_kline")
    @patch("chanlun.historical_experiment_metrics.iter_snapshot_picks")
    def test_historical_metrics_returns_nonempty_for_signal_delay1_by_type_guard_v2(
        self,
        iter_snapshot_mock,
        fetch_kline_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(fake_snapshots_with_types())
        fetch_kline_mock.return_value = fake_kline()

        payload = run_historical_experiment_return_metrics("signal_delay1_by_type_guard_v2")
        self.assertIsNotNone(payload)
        self.assertIn("return_metrics", payload)
        self.assertIn("coverage", payload)
        coverage = payload["coverage"]
        self.assertGreater(coverage.get("evaluated", 0), 0)
        self.assertGreater(coverage.get("legacy_evaluated", 0), 0)
        self.assertEqual(payload["return_metrics"]["experiment"]["n"], 2)

    @patch("chanlun.historical_experiment_metrics.fetch_daily_kline")
    @patch("chanlun.historical_experiment_metrics.iter_snapshot_picks")
    def test_historical_metrics_keeps_strong_startup_not_filtered(
        self,
        iter_snapshot_mock,
        fetch_kline_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(fake_snapshots_with_types())
        fetch_kline_mock.return_value = fake_kline()
        payload = run_historical_experiment_return_metrics("signal_delay1_by_type_guard")
        # total samples: 3 picks, one newly-formed 底背驰被过滤, thus 2 experiment samples
        self.assertEqual(payload["coverage"].get("filtered"), 1)
        self.assertEqual(payload["return_metrics"]["experiment"]["n"], 2)
        self.assertEqual(payload["return_metrics"]["legacy"]["n"], 3)


if __name__ == "__main__":
    unittest.main()
