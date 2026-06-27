import unittest
from unittest.mock import patch
from types import SimpleNamespace

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

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_drops_newly_formed_bottom_candidate(self, mock_locate):
        mock_locate.return_value = (
            [
                {"type": "底背驰候选", "index": 2, "price": 10.1},
                {"type": "底背驰候选", "index": 0, "price": 9.8},
                {"type": "一买", "index": 2, "price": 10.3},
            ],
            [{"type": "一卖", "index": 3}],
        )
        self.result = SimpleNamespace(closes=[1, 2, 3])
        buy_points, sell_points = signal_experiments.locate_buy_sell_points_delay1_by_type_guard(self.result)
        self.assertEqual([point["index"] for point in buy_points], [0, 2])
        self.assertIs(sell_points, mock_locate.return_value[1])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_keeps_older_bottom_candidate(self, mock_locate):
        mock_locate.return_value = (
            [
                {"type": "底背驰候选", "index": 1, "price": 10.5},
                {"type": "底背驰候选", "index": 2, "price": 10.9},
            ],
            [],
        )
        self.result = SimpleNamespace(closes=[1, 2, 3, 4])
        buy_points, _ = signal_experiments.locate_buy_sell_points_delay1_by_type_guard(self.result)
        self.assertEqual([point["index"] for point in buy_points], [1, 2])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_noop_with_missing_index_or_closes(self, mock_locate):
        mock_locate.return_value = (
            [
                {"type": "底背驰候选", "price": 9.9},
                {"type": "底背驰候选", "index": 0, "price": 9.8},
                {"type": "强势启动候选", "index": 2, "price": 12},
            ],
            [],
        )
        self.result = SimpleNamespace(closes=None)
        buy_points, _ = signal_experiments.locate_buy_sell_points_delay1_by_type_guard(self.result)
        self.assertEqual([point["index"] for point in buy_points if "index" in point], [0, 2])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_v2_filters_regular_bottom_candidate(self, mock_locate):
        mock_locate.return_value = (
            [
                {
                    "type": "底背驰候选",
                    "index": 2,
                    "distance_from_reference_pct": 2.9,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "price": 10.1,
                },
                {"type": "底背驰候选", "index": 2, "price": 9.7},
                {"type": "三买", "index": 2, "price": 10.3},
            ],
            [{"type": "一卖", "index": 3}],
        )
        self.result = SimpleNamespace(closes=[1, 2, 3])
        buy_points, _ = signal_experiments.locate_buy_sell_points_delay1_by_type_guard_v2(self.result)
        self.assertEqual([point["index"] for point in buy_points], [2, 2])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_v2_rescues_confirmed_candidate(self, mock_locate):
        mock_locate.return_value = (
            [
                {
                    "type": "底背驰候选",
                    "index": 2,
                    "distance_from_reference_pct": 3.0,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "price": 10.1,
                },
                {
                    "type": "底背驰候选",
                    "index": 3,
                    "distance_from_reference_pct": 3.2,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "price": 9.8,
                },
                {
                    "type": "底背驰候选",
                    "index": 1,
                    "distance_from_reference_pct": 2.8,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "price": 10.5,
                },
                {
                    "type": "强势启动候选",
                    "index": 2,
                    "price": 12.0,
                },
            ],
            [{"type": "一卖", "index": 3}],
        )
        self.result = SimpleNamespace(closes=[1, 2, 3, 4])
        buy_points, _ = signal_experiments.locate_buy_sell_points_delay1_by_type_guard_v2(self.result)
        self.assertEqual([point["type"] + ":" + str(point["index"]) for point in buy_points], [
            "底背驰候选:2",
            "底背驰候选:1",
            "强势启动候选:2",
        ])

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_v2_no_rescue_without_confirmations(self, mock_locate):
        mock_locate.return_value = (
            [
                {
                    "type": "底背驰候选",
                    "index": 3,
                    "distance_from_reference_pct": 2.8,
                    "price": 10.1,
                },
                {
                    "type": "底背驰候选",
                    "index": 3,
                    "confirmations": ["关键位不破", "EMA5收复", "止跌结构"],
                    "price": 9.8,
                },
            ],
            [],
        )
        self.result = SimpleNamespace(closes=[1, 2, 3, 4])
        buy_points, _ = signal_experiments.locate_buy_sell_points_delay1_by_type_guard_v2(self.result)
        self.assertEqual(len(buy_points), 0)

    @patch("chanlun.engine_signal_experiments.locate_buy_sell_points")
    def test_delay1_by_type_guard_does_not_filter_strong_startup(self, mock_locate):
        mock_locate.return_value = (
            [
                {"type": "强势启动候选", "index": 2, "price": 13.3},
                {"type": "底背驰候选", "index": 2, "price": 12.1},
            ],
            [],
        )
        self.result = SimpleNamespace(closes=[1, 2, 3])
        buy_points, _ = signal_experiments.locate_buy_sell_points_delay1_by_type_guard(self.result)
        self.assertEqual([point["type"] for point in buy_points], ["强势启动候选"])


if __name__ == "__main__":
    unittest.main()
