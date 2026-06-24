"""Unit tests for stock_review rule action engine."""
import unittest
from chanlun.stock_review.rule_action import generate_rule_action, ACTION_PRIORITY


class TestGenerateRuleAction(unittest.TestCase):

    def setUp(self):
        self.base_daily = {
            "close": 105.0,
            "trend_type": "盘整",
            "position": "中枢内",
            "current_pivot": {"ZD": 100.0, "ZG": 110.0},
            "buy_points": [],
            "sell_points": [],
            "divergence": None,
        }
        self.base_min30 = {
            "close": 105.0,
            "trend_type": "盘整",
            "position": "中枢内",
            "current_pivot": {"ZD": 102.0, "ZG": 108.0},
            "buy_points": [],
            "sell_points": [],
            "divergence": None,
            "above_ema5": True,
        }
        self.base_holding = {
            "code": "600519", "name": "测试",
            "cost_price": 100.0,
            "quantity": 100,
        }

    def test_below_zd_reduce(self):
        daily = {**self.base_daily, "close": 95.0, "position": "中枢下方"}
        min30 = {**self.base_min30, "close": 95.0, "position": "中枢下方"}
        action = generate_rule_action(daily, min30, self.base_holding)
        self.assertIn(action["action"], ["REDUCE", "STOP"])

    def test_top_divergence_reduce(self):
        daily = {**self.base_daily}
        daily["divergence"] = {"type": "盘整顶背驰", "is_divergence": True}
        action = generate_rule_action(daily, self.base_min30, self.base_holding)
        self.assertIn(action["action"], ["REDUCE", "WATCH"])

    def test_inside_pivot_no_sell_hold(self):
        action = generate_rule_action(self.base_daily, self.base_min30, self.base_holding)
        self.assertEqual(action["action"], "HOLD")

    def test_30min_confirm_daily_not_add_on_confirm(self):
        daily = {**self.base_daily}
        min30 = {
            **self.base_min30,
            "buy_points": [{"type": "一买", "price": 100.0, "strength": "中"}],
            "above_ema5": True,
        }
        action = generate_rule_action(daily, min30, self.base_holding)
        # 30min has buy signal but daily doesn't confirm -> ADD_ON_CONFIRM or HOLD
        self.assertIn(action["action"], ["ADD_ON_CONFIRM", "HOLD"])

    def test_no_cost_price_structure_stop_only(self):
        holding = {"code": "600519", "name": "测试"}
        daily = {**self.base_daily, "close": 95.0, "position": "中枢下方"}
        min30 = {**self.base_min30, "close": 95.0, "position": "中枢下方"}
        action = generate_rule_action(daily, min30, holding)
        # Without cost price: no account-level stop, only structure stop
        self.assertIn("stop_condition", action)
        self.assertIn(action["action"], ["REDUCE", "STOP", "WATCH"])

    def test_action_has_required_fields(self):
        action = generate_rule_action(self.base_daily, self.base_min30, self.base_holding)
        for field in ["action", "confidence", "primary_reason",
                       "hold_condition", "add_condition",
                       "reduce_condition", "stop_condition", "invalidated_by"]:
            self.assertIn(field, action, f"Missing field: {field}")

    def test_above_zg_with_sell_point_watch(self):
        daily = {**self.base_daily, "close": 115.0, "position": "中枢上方"}
        daily["sell_points"] = [{"type": "一卖", "price": 115.0, "strength": "中"}]
        action = generate_rule_action(daily, self.base_min30, self.base_holding)
        self.assertIn(action["action"], ["REDUCE", "WATCH"])

    def test_below_cost_stop(self):
        daily = {**self.base_daily, "close": 85.0, "position": "中枢下方"}
        min30 = {**self.base_min30, "close": 85.0, "position": "中枢下方"}
        # cost is 100, price dropped to 85 (-15%)
        action = generate_rule_action(daily, min30, self.base_holding)
        self.assertIn(action["action"], ["REDUCE", "STOP"])


class TestActionPriority(unittest.TestCase):

    def test_stop_highest_priority(self):
        self.assertLess(ACTION_PRIORITY["STOP"], ACTION_PRIORITY["HOLD"])

    def test_reduce_before_hold(self):
        self.assertLess(ACTION_PRIORITY["REDUCE"], ACTION_PRIORITY["HOLD"])

    def test_watch_before_hold(self):
        self.assertLess(ACTION_PRIORITY["WATCH"], ACTION_PRIORITY["HOLD"])


if __name__ == "__main__":
    unittest.main()
