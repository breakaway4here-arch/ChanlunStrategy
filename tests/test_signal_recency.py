"""Tests for signal_recency — annotate, filter picks, filter watchlist."""
import unittest

from chanlun.signal_recency import (
    annotate_buy_point_recency,
    filter_recent_picks,
    filter_recent_watchlist,
)


class TestAnnotateBuyPointRecency(unittest.TestCase):

    def test_recent_signal_kept(self):
        bp = {"index": 95, "type": "二买候选", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertTrue(annotated["is_recent"])
        self.assertEqual(annotated["signal_age_days"], 4)

    def test_expired_signal_marked(self):
        bp = {"index": 80, "type": "二买候选", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertFalse(annotated["is_recent"])
        self.assertEqual(annotated["signal_age_days"], 19)

    def test_exact_boundary_kept(self):
        bp = {"index": 90, "type": "一买", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertTrue(annotated["is_recent"])
        self.assertEqual(annotated["signal_age_days"], 9)

    def test_exact_boundary_plus_one_dropped(self):
        bp = {"index": 88, "type": "一买", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertFalse(annotated["is_recent"])
        self.assertEqual(annotated["signal_age_days"], 11)

    def test_today_signal_age_zero(self):
        bp = {"index": 99, "type": "三买", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertTrue(annotated["is_recent"])
        self.assertEqual(annotated["signal_age_days"], 0)

    def test_no_index_returns_not_recent(self):
        bp = {"type": "底背驰候选", "price": 10.0}
        annotated = annotate_buy_point_recency(bp, [1.0] * 100, max_age=10)
        self.assertFalse(annotated["is_recent"])
        self.assertIsNone(annotated["signal_age_days"])

    def test_no_closes_returns_not_recent(self):
        bp = {"index": 50, "type": "中枢低吸候选", "price": 10.0}
        annotated = annotate_buy_point_recency(bp, None, max_age=10)
        self.assertFalse(annotated["is_recent"])
        self.assertIsNone(annotated["signal_age_days"])

    def test_dates_adds_signal_date(self):
        bp = {"index": 95, "type": "二买候选", "price": 10.0}
        closes = [1.0] * 100
        dates = [f"2026-05-{i:02d}" for i in range(1, 101)]
        annotated = annotate_buy_point_recency(bp, closes, dates, max_age=10)
        self.assertEqual(annotated["signal_date"], "2026-05-96")

    def test_recency_reason_recent(self):
        bp = {"index": 97, "type": "盘整低吸候选", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertIn("最近2个交易日", annotated["recency_reason"])

    def test_recency_reason_expired(self):
        bp = {"index": 50, "type": "盘整低吸候选", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertIn("超过10个交易日", annotated["recency_reason"])

    def test_negative_age_clamped_to_zero(self):
        bp = {"index": 105, "type": "一买", "price": 10.0}
        closes = [1.0] * 100
        annotated = annotate_buy_point_recency(bp, closes, max_age=10)
        self.assertEqual(annotated["signal_age_days"], 0)
        self.assertTrue(annotated["is_recent"])


class TestFilterRecentPicks(unittest.TestCase):

    def _make_pick(self, code, bp_index, bp_type="二买候选", closes=None):
        if closes is None:
            closes = [1.0] * 100
        return {
            "code": code,
            "name": f"股票{code}",
            "best_buy_point": {
                "index": bp_index,
                "type": bp_type,
                "price": 10.0,
                "reason": "test",
            },
            "closes": closes,
        }

    def test_recent_pick_kept(self):
        picks = [self._make_pick("000001", 95)]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(len(kept), 1)
        self.assertEqual(diag["kept"], 1)
        self.assertEqual(diag["dropped_expired"], 0)
        self.assertTrue(kept[0]["best_buy_point"]["is_recent"])

    def test_expired_pick_dropped(self):
        picks = [self._make_pick("000001", 80)]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(len(kept), 0)
        self.assertEqual(diag["dropped_expired"], 1)
        self.assertEqual(len(diag["dropped_details"]), 1)

    def test_mixed_picks_filtered(self):
        picks = [
            self._make_pick("000001", 95),
            self._make_pick("000002", 80),
            self._make_pick("000003", 97),
        ]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(len(kept), 2)
        self.assertEqual(diag["input"], 3)
        self.assertEqual(diag["kept"], 2)
        self.assertEqual(diag["dropped_expired"], 1)

    def test_dropped_details_format(self):
        picks = [self._make_pick("600519", 50, "强势启动候选")]
        kept, diag = filter_recent_picks(picks, 10)
        detail = diag["dropped_details"][0]
        self.assertEqual(detail["code"], "600519")
        self.assertEqual(detail["type"], "强势启动候选")
        self.assertIn("signal_age_days", detail)
        self.assertIn("reason", detail)

    def test_no_best_buy_point_dropped(self):
        picks = [{"code": "000001", "name": "test", "closes": [1.0] * 100}]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(len(kept), 0)
        self.assertEqual(diag["dropped_expired"], 1)
        self.assertIn("缺少best_buy_point", diag["dropped_details"][0]["reason"])

    def test_all_expired_returns_empty(self):
        picks = [self._make_pick(f"{c:06d}", 10) for c in range(1, 6)]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(len(kept), 0)
        self.assertEqual(diag["dropped_expired"], 5)

    def test_all_recent_returns_all(self):
        picks = [self._make_pick(f"{c:06d}", 95) for c in range(1, 6)]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(len(kept), 5)
        self.assertEqual(diag["dropped_expired"], 0)

    def test_dates_passed_through_to_bp(self):
        picks = [self._make_pick("000001", 95)]
        picks[0]["dates"] = [f"2026-05-{i:02d}" for i in range(1, 101)]
        kept, diag = filter_recent_picks(picks, 10)
        self.assertEqual(kept[0]["best_buy_point"]["signal_date"], "2026-05-96")

    def test_custom_max_age(self):
        picks = [self._make_pick("000001", 90)]
        kept, diag = filter_recent_picks(picks, 5)
        self.assertEqual(len(kept), 0)
        self.assertEqual(diag["max_age_trading_days"], 5)


class TestFilterRecentWatchlist(unittest.TestCase):

    def _make_watch(self, code, startup_age_days=None, closes=None, startup_index=None,
                    wtype="强势启动观察"):
        w = {
            "code": code,
            "name": f"股票{code}",
            "type": wtype,
            "watch_reason": "test",
        }
        if startup_age_days is not None:
            w["startup_age_days"] = startup_age_days
        if closes is not None:
            w["closes"] = closes
        if startup_index is not None:
            w["startup_index"] = startup_index
        return w

    def test_recent_watch_kept(self):
        wl = [self._make_watch("000001", startup_age_days=3)]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 1)
        self.assertEqual(diag["kept"], 1)

    def test_expired_watch_dropped(self):
        wl = [self._make_watch("000001", startup_age_days=15)]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 0)
        self.assertEqual(diag["dropped_expired"], 1)

    def test_derives_age_from_closes_and_startup_index(self):
        wl = [self._make_watch("000001", closes=[1.0] * 100, startup_index=95)]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["startup_age_days"], 4)

    def test_missing_all_age_info_dropped(self):
        wl = [self._make_watch("000001")]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 0)
        self.assertIn("无法确定信号日期", diag["dropped_details"][0]["reason"])

    def test_mixed_watchlist(self):
        wl = [
            self._make_watch("000001", startup_age_days=3),
            self._make_watch("000002", startup_age_days=42),
            self._make_watch("000003", startup_age_days=8),
        ]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 2)
        self.assertEqual(diag["dropped_expired"], 1)

    def test_boundary_exact_10_kept(self):
        wl = [self._make_watch("000001", startup_age_days=10)]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 1)

    def test_boundary_11_dropped(self):
        wl = [self._make_watch("000001", startup_age_days=11)]
        kept, diag = filter_recent_watchlist(wl, 10)
        self.assertEqual(len(kept), 0)


if __name__ == "__main__":
    unittest.main()
