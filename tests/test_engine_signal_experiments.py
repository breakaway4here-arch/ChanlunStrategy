import unittest
from unittest.mock import patch

from chanlun import engine_signal_experiments as signal_experiments


class EngineSignalExperimentTests(unittest.TestCase):
    def setUp(self):
        self.result = object()

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_p0_distance_guard_filters_candidate(self, mock_locate):
        mock_locate.return_value = (
            [
                {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 3.6,
                    "index": 1,
                },
                {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 3,
                    "index": 2,
                },
                {"type": "一买", "distance_from_reference_pct": 10, "index": 3},
            ],
            [
                {"type": "一卖", "index": 10},
            ],
        )

        buy_points, sell_points = signal_experiments.locate_buy_sell_points_p0_distance_guard(self.result)
        self.assertEqual(len(buy_points), 2)
        self.assertEqual(buy_points[0]["index"], 2)
        self.assertEqual(buy_points[1]["index"], 3)
        self.assertIs(sell_points, mock_locate.return_value[1])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_p0_distance_guard_noop_without_reference_distance(self, mock_locate):
        mock_locate.return_value = (
            [
                {"type": "底背驰候选", "index": 1},
                {"type": "一买", "index": 2},
            ],
            [{"type": "一卖", "index": 10}],
        )
        buy_points, _ = signal_experiments.locate_buy_sell_points_p0_distance_guard(self.result)
        self.assertEqual(len(buy_points), 2)

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_p1_confirmation_guard_filters_by_confirmations(self, mock_locate):
        mock_locate.return_value = (
            [
                {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "A类确认"],
                    "index": 1,
                },
                {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "关键位不破", "30min底分型"],
                    "index": 2,
                },
                {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "关键位不破"],
                    "index": 3,
                },
                {
                    "type": "三买",
                    "confirmations": ["EMA5收复", "A类确认"],
                    "index": 4,
                },
                {"type": "三买", "index": 5},
            ],
            [
                {"type": "一卖", "index": 20},
            ],
        )
        buy_points, sell_points = signal_experiments.locate_buy_sell_points_p1_confirmation_guard(self.result)
        self.assertEqual([point["index"] for point in buy_points], [2, 3, 4, 5])
        self.assertIs(sell_points, mock_locate.return_value[1])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_p1_confirmation_guard_noop_without_confirmations(self, mock_locate):
        mock_locate.return_value = (
            [{"type": "三买", "index": 1}],
            [{"type": "一卖", "index": 10}],
        )
        buy_points, _ = signal_experiments.locate_buy_sell_points_p1_confirmation_guard(self.result)
        self.assertEqual(len(buy_points), 1)
        self.assertEqual(buy_points[0]["index"], 1)

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_p0_p1_guard_combined_filtering(self, mock_locate):
        mock_locate.return_value = (
            [
                {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 4.2,
                    "confirmations": ["止跌结构", "EMA5收复", "A类确认"],
                    "index": 1,
                },
                {
                    "type": "底背驰候选",
                    "distance_from_reference_pct": 2.8,
                    "confirmations": ["止跌结构", "EMA5收复", "A类确认"],
                    "index": 2,
                },
                {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "A类确认"],
                    "index": 3,
                },
                {
                    "type": "三买",
                    "confirmations": ["止跌结构", "EMA5收复", "关键位不破"],
                    "index": 4,
                },
            ],
            [
                {"type": "一卖", "index": 12},
            ],
        )
        buy_points, sell_points = signal_experiments.locate_buy_sell_points_p0_p1_guard(self.result)
        self.assertEqual([point["index"] for point in buy_points], [4])
        self.assertIs(sell_points, mock_locate.return_value[1])


if __name__ == "__main__":
    unittest.main()
