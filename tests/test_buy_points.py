import unittest

from chanlun.chan_engine import (
    ChanResult, Pivot, Segment, Stroke,
    locate_buy_sell_points,
)


def make_seg(start_idx, end_idx, direction, high, low, strokes=None):
    return Segment(
        strokes=strokes or [],
        start_idx=start_idx,
        end_idx=end_idx,
        direction=direction,
        high=high,
        low=low,
    )


def make_result_with_pivot_leave_and_pullback():
    """标准中枢 + 向上离开段 + 向下回拉段（不破ZG）"""
    closes = [10.0] * 50
    pivot = Pivot(ZD=10.0, ZG=12.0, segments=[], start_idx=10, end_idx=20)
    seg_leave = make_seg(21, 30, "up", 15.0, 11.0)
    seg_pullback = make_seg(31, 40, "down", 14.5, 12.5)
    result = ChanResult(
        code="TEST", name="TEST",
        closes=closes, highs=closes, lows=closes, opens=closes,
        volumes=closes, dates=list(range(50)),
    )
    result.pivots = [pivot]
    result.segments = [seg_leave, seg_pullback]
    result.divergence = None
    return result


def make_result_with_no_pivots_but_fake_zone():
    closes = [10.0] * 50
    result = ChanResult(
        code="TEST", name="TEST",
        closes=closes, highs=closes, lows=closes, opens=closes,
        volumes=closes, dates=list(range(50)),
    )
    result.pivots = []
    result.segments = []
    result.divergence = None
    return result


def make_result_confirmed_second_buy():
    """一买在 confirmed 下跌段(idx=10, price=8.0)，
    随后 confirmed 上离开(idx=20) + confirmed 回拉(idx=30, low=9.0>8.0) → 正式 二买。"""
    closes = [10.0] * 50
    seg_down = make_seg(0, 10, "down", 12.0, 8.0)
    seg_down.confirmed = True
    seg_up = make_seg(10, 20, "up", 11.0, 8.5)
    seg_up.confirmed = True
    seg_pullback = make_seg(20, 30, "down", 10.5, 9.0)
    seg_pullback.confirmed = True
    result = ChanResult(
        code="TEST", name="TEST",
        closes=closes, highs=closes, lows=closes, opens=closes,
        volumes=closes, dates=list(range(50)),
    )
    result.segments = [seg_down, seg_up, seg_pullback]
    result.pivots = []
    result.divergence = {
        "type": "趋势底背驰",
        "is_divergence": True,
        "area_ratio": 0.5,
        "hist_divergence": False,
        "prev_segment": (0, 5),
        "last_segment": (0, 10),
    }
    return result


def make_result_unconfirmed_second_buy():
    """一买在 confirmed 下跌段(idx=10, price=8.0)，
    随后 unconfirmed 上离开 + unconfirmed 回拉 → 只应产生 二买待确认。"""
    closes = [10.0] * 50
    seg_down = make_seg(0, 10, "down", 12.0, 8.0)
    seg_down.confirmed = True
    seg_up = make_seg(10, 20, "up", 11.0, 8.5)
    seg_up.confirmed = False
    seg_pullback = make_seg(20, 30, "down", 10.5, 9.0)
    seg_pullback.confirmed = False
    result = ChanResult(
        code="TEST", name="TEST",
        closes=closes, highs=closes, lows=closes, opens=closes,
        volumes=closes, dates=list(range(50)),
    )
    result.segments = [seg_down, seg_up, seg_pullback]
    result.pivots = []
    result.divergence = {
        "type": "趋势底背驰",
        "is_divergence": True,
        "area_ratio": 0.5,
        "hist_divergence": False,
        "prev_segment": (0, 5),
        "last_segment": (0, 10),
    }
    return result


def make_result_with_only_first_buy():
    """只有一买，没有后续上离开+回拉，因此不应产生任何 二买。"""
    closes = [10.0] * 50
    seg_down = make_seg(0, 10, "down", 12.0, 8.0)
    seg_down.confirmed = True
    result = ChanResult(
        code="TEST", name="TEST",
        closes=closes, highs=closes, lows=closes, opens=closes,
        volumes=closes, dates=list(range(50)),
    )
    result.segments = [seg_down]
    result.pivots = []
    result.divergence = {
        "type": "趋势底背驰",
        "is_divergence": True,
        "area_ratio": 0.5,
        "hist_divergence": False,
        "prev_segment": (0, 5),
        "last_segment": (0, 10),
    }
    return result


def make_result_pending_only_buy():
    """只有 二买待确认 + swing底背驰参考，无正式买点。筛选器应排除。"""
    closes = [10.0] * 50
    result = ChanResult(
        code="TEST", name="TEST",
        closes=closes, highs=closes, lows=closes, opens=closes,
        volumes=closes, dates=list(range(50)),
    )
    result.pivots = []
    result.segments = []
    result.divergence = None
    result.buy_points = [
        {"type": "二买待确认", "index": 20, "price": 10.0, "date": "", "reason": "", "strength": "弱"},
        {"type": "swing底背驰参考", "index": 15, "price": 9.5, "date": "", "reason": "", "strength": "弱"},
        {"type": "中枢震荡低吸参考", "index": 25, "price": 10.2, "date": "", "reason": "", "strength": "弱"},
    ]
    return result


class BuyPointTests(unittest.TestCase):
    def test_third_buy_requires_standard_pivot(self):
        result = make_result_with_no_pivots_but_fake_zone()
        buy_points, _ = locate_buy_sell_points(result)
        self.assertFalse(any(bp["type"] == "三买" for bp in buy_points))

    def test_third_buy_uses_pullback_low_not_current_close(self):
        result = make_result_with_pivot_leave_and_pullback()
        buy_points, _ = locate_buy_sell_points(result)
        third = next((bp for bp in buy_points if bp["type"] == "三买"), None)
        self.assertIsNotNone(third, "Expected 三买 to be generated")
        self.assertEqual(third["price"], 12.5)
        self.assertEqual(third["index"], 40)

    def test_confirmed_second_buy_is_selectable(self):
        """confirmed 下跌一买 + confirmed 上离开 + confirmed 回拉 → 正式 二买。"""
        result = make_result_confirmed_second_buy()
        buy_points, _ = locate_buy_sell_points(result)

        first = next((bp for bp in buy_points if bp["type"] == "一买"), None)
        second = next((bp for bp in buy_points if bp["type"] == "二买"), None)

        self.assertIsNotNone(first, "Expected 一买 to be generated")
        self.assertIsNotNone(second, "Expected formal 二买 from confirmed segments")
        self.assertGreater(second["index"], first["index"])
        self.assertGreater(second["price"], first["price"])

        # 不应同时产出 二买待确认
        pending = [bp for bp in buy_points if bp["type"] == "二买待确认"]
        self.assertEqual(len(pending), 0, "Should not emit 二买待确认 when formal 二买 exists")

    def test_unconfirmed_second_buy_is_pending_only(self):
        """confirmed 一买 + unconfirmed 上离开+回拉 → 二买待确认，不生成正式 二买。"""
        result = make_result_unconfirmed_second_buy()
        buy_points, _ = locate_buy_sell_points(result)

        first = next((bp for bp in buy_points if bp["type"] == "一买"), None)
        formal = [bp for bp in buy_points if bp["type"] == "二买"]
        pending = [bp for bp in buy_points if bp["type"] == "二买待确认"]

        self.assertIsNotNone(first, "Expected 一买 to be generated")
        self.assertEqual(len(formal), 0, "Should NOT emit formal 二买 from unconfirmed segments")
        self.assertEqual(len(pending), 1, "Should emit 二买待确认 from unconfirmed segments")

    def test_second_buy_cannot_share_first_buy_index(self):
        result = make_result_with_only_first_buy()
        buy_points, _ = locate_buy_sell_points(result)
        self.assertFalse(any(bp["type"] == "二买" for bp in buy_points))
        self.assertFalse(any(bp["type"] == "二买待确认" for bp in buy_points))


class ScreenerFilterTests(unittest.TestCase):
    """验证筛选器不会选入待确认/参考类买点。"""

    def test_pending_buy_not_selected_by_pure(self):
        from chanlun.screener_pure import screen_daily_pure
        result = make_result_pending_only_buy()
        pool = screen_daily_pure([result], {}, [])
        # 所有买点都是不可选类型，应被过滤
        self.assertEqual(len(pool), 0,
                         "二买待确认/swing底背驰参考/中枢震荡低吸参考 should not be selected")

    def test_pending_buy_not_selected_by_fusion(self):
        from chanlun.screener_fusion import screen_daily_fusion
        result = make_result_pending_only_buy()
        # 给一段假的上涨指数（满足MA趋势计算需要的长度）
        sh_closes = [10.0] * 60
        pool = screen_daily_fusion([result], sh_closes, {})
        self.assertEqual(len(pool), 0,
                         "二买待确认/swing底背驰参考/中枢震荡低吸参考 should not be selected")


if __name__ == "__main__":
    unittest.main()
