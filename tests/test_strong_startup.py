"""Tests for strong_startup detection and 30min upgrade."""
import unittest
import numpy as np

from chanlun.strong_startup import (
    build_strong_startup_pool,
    upgrade_strong_startup_with_30min,
    _check_low_position,
    _check_volume_breakout,
    _check_price_breakout,
    _check_30min_confirmations,
)


def _make_chan_result(code, name, closes, opens=None, highs=None, lows=None,
                       volumes=None, buy_points=None, dates=None):
    """Build a mock chan result object."""
    class MockResult:
        pass
    r = MockResult()
    r.code = code
    r.name = name
    r.closes = np.array(closes, dtype=float)
    r.opens = np.array(opens, dtype=float) if opens is not None else r.closes * 0.99
    r.highs = np.array(highs, dtype=float) if highs is not None else r.closes * 1.02
    r.lows = np.array(lows, dtype=float) if lows is not None else r.closes * 0.98
    r.volumes = np.array(volumes, dtype=float) if volumes is not None else np.ones(len(closes)) * 10000000
    r.buy_points = buy_points or []
    r.dates = dates if dates is not None else [f"2026-05-{i:02d}" for i in range(1, len(closes) + 1)]
    return r


def _make_bullish_closes(n=120):
    """Make gradually rising closes for a stock in uptrend (NOT low position)."""
    return np.linspace(50, 100, n)


def _make_low_position_closes(n=120):
    """Make closes that end near 60d/120d lows (low position)."""
    closes = np.ones(n) * 100.0
    closes[-60:] = np.linspace(100, 50, 60)  # declining last 60d
    closes[-5:] = np.linspace(50, 55, 5)      # small bounce at end
    return closes


def _make_volume_spike(n=120):
    """Normal volume except last day is 2x spike."""
    vols = np.ones(n) * 10000000
    vols[-1] = 20000000  # 2x last 5 avg
    return vols


class TestLowPositionCheck(unittest.TestCase):

    def test_60d_low_detected(self):
        closes = np.ones(120) * 100.0
        closes[-60:] = np.linspace(100, 50, 60)
        closes[-1] = 55.0
        highs = closes * 1.05
        lows = closes * 0.95
        result = _check_low_position(closes, highs, lows, 0.88, 0.82, 1.12)
        self.assertEqual(result, "60d_low")

    def test_high_position_not_low(self):
        closes = np.linspace(50, 100, 120)
        highs = closes * 1.05
        lows = closes * 0.95
        result = _check_low_position(closes, highs, lows, 0.88, 0.82, 1.12)
        self.assertIsNone(result)


class TestVolumeBreakout(unittest.TestCase):

    def test_volume_spike_detected(self):
        vols = np.ones(20) * 10000
        vols[-1] = 20000  # 2x avg
        closes = np.ones(20) * 50
        self.assertTrue(_check_volume_breakout(vols, closes, 1.5))

    def test_no_volume_spike(self):
        vols = np.ones(20) * 10000
        closes = np.ones(20) * 50
        self.assertFalse(_check_volume_breakout(vols, closes, 1.5))


class TestPriceBreakout(unittest.TestCase):

    def test_two_signals_minimum(self):
        closes = np.ones(20) * 50.0
        closes[-1] = 53.0  # +6%
        closes[-2] = 50.0
        opens = closes * 0.99
        highs = closes * 1.02
        signals = _check_price_breakout(closes, opens, highs, 4.0)
        self.assertGreaterEqual(len(signals), 2)

    def test_insufficient_breakout(self):
        closes = np.ones(20) * 50.0
        closes[-1] = 49.5  # -1%
        closes[-2] = 50.0
        opens = closes.copy()
        highs = closes * 1.02
        signals = _check_price_breakout(closes, opens, highs, 4.0)
        self.assertLess(len(signals), 2)


class TestBuildStrongStartupPool(unittest.TestCase):

    def test_chinext_large_gain_below_real_limit_remains_seed(self):
        closes = _make_low_position_closes(120)
        closes[-2] = 50.0
        closes[-1] = 56.85  # +13.7%，不是创业板涨停
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        result = _make_chan_result(
            "301629", "矽电股份", closes, opens, highs, lows, vols
        )

        seeds, watchlist, diag = build_strong_startup_pool([result])

        self.assertEqual([row["code"] for row in seeds], ["301629"])
        self.assertEqual(watchlist, [])
        self.assertEqual(diag["daily_startup_seed"], 1)

    def test_actual_chinext_limit_up_stays_in_observation(self):
        closes = _make_low_position_closes(120)
        closes[-2] = 50.0
        closes[-1] = 60.0
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        result = _make_chan_result(
            "301630", "创业板涨停测试", closes, opens, highs, lows, vols
        )

        seeds, watchlist, diag = build_strong_startup_pool([result])

        self.assertEqual(seeds, [])
        self.assertEqual([row["code"] for row in watchlist], ["301630"])
        self.assertEqual(watchlist[0]["price_limit_state"], "limit_up")
        self.assertEqual(diag["watch_due_to_limit_up"], 1)

    def test_low_volume_breakout_price_up(self):
        """Low position + volume spike + price breakout → seed."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 52.0  # +5.7%
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000001", "测试股", closes, opens, highs, lows, vols)
        seeds, watchlist, diag = build_strong_startup_pool([r])
        self.assertEqual(diag["daily_startup_seed"], 1)
        self.assertEqual(len(seeds), 1)
        self.assertEqual(len(watchlist), 0)

    def test_high_position_dropped(self):
        """High position stock is dropped."""
        closes = _make_bullish_closes(120)
        closes[-1] = 105.0
        closes[-2] = 100.0  # +5%
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000002", "高位股", closes, opens, highs, lows, vols)
        seeds, watchlist, diag = build_strong_startup_pool([r])
        self.assertEqual(diag["dropped_high_position"], 1)
        self.assertEqual(len(seeds), 0)

    def test_no_volume_dropped(self):
        """Low position but no volume → dropped."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 52.0
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = np.ones(120) * 10000000  # normal volume
        r = _make_chan_result("000003", "无放量股", closes, opens, highs, lows, vols)
        seeds, watchlist, diag = build_strong_startup_pool([r])
        self.assertEqual(diag["dropped_no_volume"], 1)
        self.assertEqual(len(seeds), 0)

    def test_limit_up_goes_to_watchlist(self):
        """Limit-up stock in low position → watchlist, not seed."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 50.0  # +10%
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000506", "招金黄金", closes, opens, highs, lows, vols)
        seeds, watchlist, diag = build_strong_startup_pool([r])
        self.assertEqual(diag["watch_due_to_limit_up"], 1)
        self.assertEqual(len(watchlist), 1)
        self.assertEqual(watchlist[0]["type"], "强势启动观察")
        self.assertTrue(watchlist[0]["avoid_chase"])
        self.assertEqual(watchlist[0]["name"], "招金黄金")

    def test_watch_item_has_required_fields(self):
        """Watchlist items have watch_reason and next_day_conditions."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 50.0
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000506", "招金黄金", closes, opens, highs, lows, vols)
        _, watchlist, _ = build_strong_startup_pool([r])
        w = watchlist[0]
        self.assertIn("watch_reason", w)
        self.assertIn("next_day_conditions", w)
        self.assertTrue(len(w["next_day_conditions"]) >= 2)
        self.assertEqual(w["source_channel"], "low_position")
        self.assertEqual(w["view"], "observation")
        self.assertIn("failure_gate", w)
        self.assertIn("cancel_conditions", w)

    def test_disabled_config_returns_empty(self):
        """When ENABLE_STRONG_STARTUP_CANDIDATES=False, returns empty."""
        import config
        old_val = config.ENABLE_STRONG_STARTUP_CANDIDATES
        config.ENABLE_STRONG_STARTUP_CANDIDATES = False
        try:
            r = _make_chan_result("000001", "测试", _make_low_position_closes(120))
            seeds, watchlist, diag = build_strong_startup_pool([r])
            self.assertEqual(len(seeds), 0)
            self.assertEqual(len(watchlist), 0)
            self.assertFalse(diag.get("enabled"))
        finally:
            config.ENABLE_STRONG_STARTUP_CANDIDATES = old_val


def _make_30min_result(code, closes_30, opens_30=None, buy_points=None):
    """Build a mock 30min chan result."""
    class Mock30Result:
        pass
    r = Mock30Result()
    r.code = code
    r.closes = np.array(closes_30, dtype=float)
    r.opens = np.array(
        opens_30 if opens_30 is not None else np.array(closes_30, dtype=float) * 0.99
    )
    r.highs = np.array(closes_30, dtype=float) * 1.01
    r.lows = np.array(closes_30, dtype=float) * 0.99
    r.volumes = np.ones(len(closes_30)) * 100000
    r.buy_points = buy_points or []
    r.dates = [f"2026-05-26 {i:02d}:00:00" for i in range(len(closes_30))]
    return r


def _make_seed(code="000001", name="测试"):
    closes = _make_low_position_closes(120)
    closes[-1] = 55.0
    closes[-2] = 52.0
    return {
        "code": code,
        "name": name,
        "type": "强势启动候选",
        "tier": "candidate",
        "source_type": "日线强势启动",
        "startup_reason": "低位放量突破",
        "startup_signals": ["涨幅≥4%", "close_above_ma5"],
        "startup_index": len(closes) - 1,
        "startup_date": "2026-05-26",
        "startup_age_days": 0,
        "change_pct": 5.7,
        "volume_ratio": 1.8,
        "close": 55.0,
        "pivot_info": {},
        "closes": closes,
        "opens": closes * 0.98,
        "highs": closes * 1.02,
        "lows": closes * 0.97,
        "volumes": np.ones(120) * 10000000,
        "dates": [f"2026-05-{i:02d}" for i in range(1, 121)],
        "buy_points": [],
        "result_30min": None,
    }


class TestUpgrade30min(unittest.TestCase):

    def test_30min_confirm_upgrades_to_candidate(self):
        """Seed with 30min EMA5 > EMA10 → candidate."""
        seed = _make_seed()
        min30 = _make_30min_result("000001", np.linspace(50, 55, 50))
        candidates, watchlist, diag = upgrade_strong_startup_with_30min([seed], [min30])
        self.assertEqual(diag["startup_candidate"], 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["type"], "强势启动候选")

    def test_no_30min_confirm_goes_to_watch(self):
        """Seed with 30min data but no confirmation signals → watch."""
        import chanlun.strong_startup as ss
        seed = _make_seed()
        min30 = _make_30min_result("000001", np.linspace(55, 50, 50))
        orig = ss._check_30min_confirmations
        try:
            ss._check_30min_confirmations = lambda r, s: []
            candidates, watchlist, diag = upgrade_strong_startup_with_30min([seed], [min30])
            self.assertEqual(diag["watch_due_to_no_30min_confirm"], 1)
            self.assertEqual(len(watchlist), 1)
            self.assertEqual(watchlist[0]["type"], "强势启动观察")
        finally:
            ss._check_30min_confirmations = orig

    def test_no_30min_data_goes_to_watch(self):
        """Seed without 30min data → watch."""
        seed = _make_seed()
        candidates, watchlist, diag = upgrade_strong_startup_with_30min([seed], [])
        self.assertEqual(diag["watch_due_to_no_30min_confirm"], 1)
        self.assertEqual(len(watchlist), 1)

    def test_candidate_has_confirmations_field(self):
        """Upgraded candidate has confirmations list."""
        seed = _make_seed()
        min30 = _make_30min_result("000001", np.linspace(50, 55, 50))
        candidates, _, _ = upgrade_strong_startup_with_30min([seed], [min30])
        self.assertIn("confirmations", candidates[0])

    def test_candidate_preserves_verified_strategy_input_evidence(self):
        seed = _make_seed()
        min30 = _make_30min_result("000001", np.linspace(50, 55, 50))
        min30.strategy_input_evidence = {
            "interval": "30m",
            "status": "verified",
            "latest_date": "2026-08-26",
            "latest_ts": "2026-08-26 15:00:00",
            "source": "market_history_db",
            "bars": 50,
            "stale": False,
            "is_final": True,
        }

        candidates, _, _ = upgrade_strong_startup_with_30min(
            [seed], [min30]
        )

        self.assertEqual(
            candidates[0]["strategy_input_evidence"],
            min30.strategy_input_evidence,
        )


class Test30minPatterns(unittest.TestCase):

    def test_two_yang_one_yin_confirmation(self):
        closes = np.array([10, 10.2, 11, 10.6, 11.4], dtype=float)
        opens = np.array([9.8, 10.0, 10.5, 10.9, 11.0], dtype=float)
        result = _make_30min_result("000001", closes, opens_30=opens)
        confirms = _check_30min_confirmations(result, {})
        self.assertIn("30min两阳夹一阴确认", confirms)

    def test_two_yang_two_yin_confirmation(self):
        closes = np.array([10, 11, 10.5, 10.2, 11.4], dtype=float)
        opens = np.array([9.8, 10.5, 10.8, 10.6, 10.9], dtype=float)
        result = _make_30min_result("000001", closes, opens_30=opens)
        confirms = _check_30min_confirmations(result, {})
        self.assertIn("30min两阳夹两阴确认", confirms)

    def test_historical_shape_does_not_create_stale_confirmation(self):
        closes = np.array([10, 9.5, 10.5, 10.8, 11.0, 11.2], dtype=float)
        opens = np.array([9.5, 10.0, 10.0, 10.4, 10.7, 10.9], dtype=float)
        result = _make_30min_result("000001", closes, opens_30=opens)
        confirms = _check_30min_confirmations(result, {})
        self.assertNotIn("30min两阳夹一阴确认", confirms)
        self.assertNotIn("30min两阳夹两阴确认", confirms)

    def test_non_shape_does_not_match_yang_patterns(self):
        closes = np.array([100, 101, 102, 103, 104, 105], dtype=float)
        opens = np.array([99.5, 100.5, 101.5, 102.5, 103.5, 104.5], dtype=float)
        result = _make_30min_result("000001", closes, opens_30=opens)
        confirms = _check_30min_confirmations(result, {})
        self.assertNotIn("30min两阳夹一阴确认", confirms)
        self.assertNotIn("30min两阳夹两阴确认", confirms)


class TestStartupAgeFields(unittest.TestCase):

    def test_seed_has_startup_age_fields(self):
        """Seed from build_strong_startup_pool has startup_index/date/age."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 52.0
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000001", "测试", closes, opens, highs, lows, vols)
        seeds, _, _ = build_strong_startup_pool([r])
        self.assertEqual(len(seeds), 1)
        s = seeds[0]
        self.assertEqual(s["startup_index"], len(closes) - 1)
        self.assertIn("startup_date", s)
        self.assertEqual(s["startup_age_days"], 0)
        self.assertIn("dates", s)

    def test_watchlist_has_startup_age_fields(self):
        """Watchlist item inherits startup_index/date/age from seed."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 50.0  # +10% → limit up
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000506", "招金黄金", closes, opens, highs, lows, vols)
        _, watchlist, _ = build_strong_startup_pool([r])
        self.assertEqual(len(watchlist), 1)
        w = watchlist[0]
        self.assertEqual(w["startup_index"], len(closes) - 1)
        self.assertEqual(w["startup_age_days"], 0)

    def test_candidate_has_confirm_age_fields(self):
        """Upgraded candidate has confirm_index/date/age."""
        seed = _make_seed()
        min30 = _make_30min_result("000001", np.linspace(50, 55, 50))
        candidates, _, _ = upgrade_strong_startup_with_30min([seed], [min30])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertIn("confirm_index", c)
        self.assertEqual(c["confirm_index"], 49)
        self.assertIn("confirm_date", c)
        self.assertEqual(c["confirm_age_days"], 0)

    def test_seed_startup_age_is_zero(self):
        """First version only detects today's bar as startup, so age is 0."""
        closes = _make_low_position_closes(120)
        closes[-1] = 55.0
        closes[-2] = 52.0
        opens = closes * 0.98
        highs = closes * 1.02
        lows = closes * 0.97
        vols = _make_volume_spike(120)
        r = _make_chan_result("000001", "测试", closes, opens, highs, lows, vols)
        seeds, _, _ = build_strong_startup_pool([r])
        self.assertEqual(seeds[0]["startup_age_days"], 0)


if __name__ == "__main__":
    unittest.main()
