import unittest

from chanlun.experiment_metrics import compare_recommendations


class ExperimentMetricsTests(unittest.TestCase):
    def test_compare_recommendations_with_add_remove_keep_and_changes(self):
        legacy = [
            {"code": "AAA", "best_buy_point": {"type": "强势启动候选", "score": 1}},
            {"code": "BBB", "best_buy_point": {"type": "底背驰候选", "score": 2}},
            {"code": "CCC", "best_buy_point": {"type": "回踩", "score": 3}},
        ]
        experiment = [
            {"code": "AAA", "best_buy_point": {"type": "强势启动候选", "score": 1}},
            {"code": "BBB", "best_buy_point": {"type": "底背驰候选", "score": 20}},
            {"code": "DDD", "best_buy_point": {"type": "强势启动候选", "score": 4}},
        ]

        diff = compare_recommendations(legacy, experiment)
        self.assertEqual(diff["legacy_count"], 3)
        self.assertEqual(diff["experiment_count"], 3)
        self.assertEqual(diff["added_codes"], ["DDD"])
        self.assertEqual(diff["removed_codes"], ["CCC"])
        self.assertEqual(diff["kept_codes"], ["AAA", "BBB"])
        self.assertEqual(diff["changed_best_buy_point_codes"], ["BBB"])

    def test_compare_recommendations_ignores_key_order_in_best_buy_point(self):
        legacy = [
            {
                "code": "AAA",
                "best_buy_point": {
                    "confirmations": ["ema_reclaim", "跌势中转"],
                    "type": "强势启动候选",
                },
            },
        ]
        experiment = [
            {
                "code": "AAA",
                "best_buy_point": {
                    "type": "强势启动候选",
                    "confirmations": ["跌势中转", "ema_reclaim"],
                },
            }
        ]

        diff = compare_recommendations(legacy, experiment)
        self.assertEqual(diff["legacy_count"], 1)
        self.assertEqual(diff["experiment_count"], 1)
        self.assertEqual(diff["added_codes"], [])
        self.assertEqual(diff["removed_codes"], [])
        self.assertEqual(diff["kept_codes"], ["AAA"])
        self.assertEqual(diff["changed_best_buy_point_codes"], [])


if __name__ == "__main__":
    unittest.main()
