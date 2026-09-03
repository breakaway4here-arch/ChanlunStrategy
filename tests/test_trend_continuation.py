import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from chanlun.engine_types import Pivot
from chanlun.trend_continuation import (
    _confirm_30min,
    build_trend_continuation_pool,
    normalize_trend_candidate,
    upgrade_trend_continuation_with_30min,
)


def _result(
    code="600000",
    last_close=12.1,
    previous_close=11.2,
    today_volume=1_600_000,
    prior_volume=1_000_000,
    today_open=11.2,
):
    closes = np.linspace(9.0, 11.0, 70)
    closes[-2] = previous_close
    closes[-1] = last_close
    highs = closes + 0.2
    highs[-21:-1] = np.minimum(highs[-21:-1], 12.0)
    highs[-5] = 12.0
    lows = closes - 0.2
    opens = closes - 0.05
    opens[-1] = today_open
    volumes = np.full(70, prior_volume, dtype=float)
    volumes[-1] = today_volume
    return SimpleNamespace(
        code=code,
        name="趋势票",
        dates=["2026-07-{:02d}".format((index % 28) + 1) for index in range(70)],
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        volumes=volumes,
        buy_points=[{"price": 7.0, "source_price": 6.5}],
        pivots=[],
        price_basis={"adjustment": "qfq", "factor_vs_raw": 1.0},
    )


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "right_side_startup"
    / "2026-08-31.json"
)


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_result(code, interval="daily"):
    payload = _fixture()
    case = payload["cases"][code]
    source = case["daily_tail" if interval == "daily" else "min30_tail"]
    pad = 60 - len(source["closes"]) if interval == "daily" else 0

    def values(key):
        head = [source[key][0]] * pad
        return np.asarray(head + source[key], dtype=float)

    dates = ["2026-05-01"] * pad + list(source["dates"])
    evidence = {
        "interval": "30m",
        "status": "intraday_available",
        "latest_date": payload["trade_date"],
        "latest_ts": "2026-08-31 14:30:00",
        "source": "preclose_snapshot",
        "bars": len(source["closes"]),
        "stale": False,
        "is_final": False,
        "bar_state": "intraday",
        "as_of": payload["as_of"],
    }
    return SimpleNamespace(
        code=code,
        name=case["name"],
        dates=dates,
        opens=values("opens"),
        highs=values("highs"),
        lows=values("lows"),
        closes=values("closes"),
        volumes=values("volumes"),
        buy_points=[],
        pivots=[],
        strategy_input_evidence=(evidence if interval == "min30" else None),
        price_basis=(
            {"adjustment": "qfq", "factor_vs_raw": 1.0}
            if interval == "daily" else None
        ),
    )


def _verified_evidence(trade_date):
    return {
        "interval": "30m",
        "status": "verified",
        "latest_date": trade_date,
        "latest_ts": trade_date + " 15:00:00",
        "source": "market_history_db",
        "bars": 20,
        "stale": False,
        "is_final": True,
        "bar_state": "closed",
    }


def _min30_result(
    closes,
    *,
    code="600000",
    trade_date="2026-07-14",
    opens=None,
    volumes=None,
    evidence=None,
):
    closes = np.asarray(closes, dtype=float)
    opens = (
        np.asarray(opens, dtype=float)
        if opens is not None
        else closes - 0.05
    )
    volumes = (
        np.asarray(volumes, dtype=float)
        if volumes is not None
        else np.ones(len(closes), dtype=float) * 1_000_000
    )
    return SimpleNamespace(
        code=code,
        closes=closes,
        opens=opens,
        highs=np.maximum(opens, closes) + 0.05,
        lows=np.minimum(opens, closes) - 0.05,
        volumes=volumes,
        dates=[trade_date + " 14:30:00"] * len(closes),
        buy_points=[],
        macd_hist=None,
        strategy_input_evidence=(
            evidence if evidence is not None else _verified_evidence(trade_date)
        ),
    )


class TrendContinuationTests(unittest.TestCase):
    def test_reference_hold_aligns_30m_prices_to_daily_basis(self):
        min30 = _min30_result(
            [10.0] * 15 + [9.9] * 5,
            trade_date="2026-07-14",
        )

        evidence = _confirm_30min(
            min30,
            reference_price=5.0,
            expected_date="2026-07-14",
            factor_vs_raw=0.5,
        )

        self.assertFalse(evidence["mandatory"]["reference_hold"])

    def test_reference_hold_without_price_basis_fails_closed(self):
        min30 = _min30_result(
            [10.0] * 20,
            trade_date="2026-07-14",
        )

        evidence = _confirm_30min(
            min30,
            reference_price=10.0,
            expected_date="2026-07-14",
            daily_current_price=10.0,
        )

        self.assertFalse(evidence["mandatory"]["reference_hold"])
    def test_20260831_right_side_regression_contract(self):
        fixture = _fixture()
        daily_results = [
            _fixture_result(code) for code in fixture["cases"]
        ]

        seeds, watchlist, _ = build_trend_continuation_pool(daily_results)
        seeds_by_code = {row["code"]: row for row in seeds}
        watch_by_code = {row["code"]: row for row in watchlist}

        self.assertEqual(["300709"], list(seeds_by_code))
        self.assertEqual(
            "right_side_startup",
            seeds_by_code["300709"]["source_channel"],
        )
        self.assertAlmostEqual(
            fixture["cases"]["300709"]["reference_price"],
            seeds_by_code["300709"]["reference_price"],
            places=2,
        )
        for code in ("002636", "002952"):
            self.assertIn(code, watch_by_code)
            self.assertEqual(
                fixture["cases"][code]["failure_gate"],
                watch_by_code[code]["failure_gate"],
            )

        candidates, waiting, _ = upgrade_trend_continuation_with_30min(
            list(seeds_by_code.values()),
            [_fixture_result("300709", interval="min30")],
        )
        self.assertEqual([], waiting)
        self.assertEqual(["300709"], [row["code"] for row in candidates])
        self.assertTrue(candidates[0]["confirmation_evidence"]["passed"])

    def test_chinext_large_gain_below_real_limit_is_trend_seed(self):
        result = _result(
            code="301629",
            last_close=12.735,
            previous_close=11.2,
            today_open=11.2,
        )

        seeds, watchlist, diagnostics = build_trend_continuation_pool([result])

        self.assertEqual([row["code"] for row in seeds], ["301629"])
        self.assertEqual(watchlist, [])
        self.assertEqual(diagnostics["trend_seed"], 1)

    def test_actual_chinext_limit_up_stays_in_observation(self):
        result = _result(
            code="301630",
            last_close=12.72,
            previous_close=10.6,
            today_open=10.6,
        )

        seeds, watchlist, diagnostics = build_trend_continuation_pool([result])

        self.assertEqual(seeds, [])
        self.assertEqual([row["code"] for row in watchlist], ["301630"])
        self.assertEqual(watchlist[0]["reason_code"], "limit_up")
        self.assertEqual(watchlist[0]["price_limit_state"], "limit_up")
        self.assertEqual(diagnostics["watch_risk"], 1)

    def test_platform_breakout_reference_does_not_use_old_buy_source_price(self):
        seeds, watchlist, diagnostics = build_trend_continuation_pool([_result()])

        self.assertEqual(len(seeds), 1)
        self.assertEqual(watchlist, [])
        self.assertEqual(seeds[0]["reference_type"], "platform_high_20d")
        self.assertAlmostEqual(seeds[0]["reference_price"], 12.0)
        self.assertNotIn(seeds[0]["reference_price"], (7.0, 6.5))
        self.assertEqual(seeds[0]["source_channel"], "right_side_startup")
        self.assertEqual(seeds[0]["view"], "main")
        self.assertEqual(diagnostics["trend_seed"], 1)

    def test_pivot_object_and_mapping_use_the_same_zg_reference(self):
        object_result = _result(
            code="600011", last_close=11.5, previous_close=11.0
        )
        object_result.pivots = [
            Pivot(
                ZD=10.2,
                ZG=11.2,
                segments=[],
                start_idx=20,
                end_idx=50,
            )
        ]
        mapping_result = _result(
            code="600012", last_close=11.5, previous_close=11.0
        )
        mapping_result.pivots = [{"ZD": 10.2, "ZG": 11.2}]

        seeds, watchlist, _ = build_trend_continuation_pool(
            [object_result, mapping_result]
        )

        self.assertEqual([], watchlist)
        self.assertEqual(["600011", "600012"], [row["code"] for row in seeds])
        self.assertEqual(
            ["pivot_upper", "pivot_upper"],
            [row["reference_type"] for row in seeds],
        )
        self.assertEqual(
            [11.2, 11.2], [row["reference_price"] for row in seeds]
        )

    def test_ma_hold_without_breakout_is_daily_breakout_watch_only(self):
        result = _result(
            code="600013", last_close=11.5, previous_close=11.0
        )

        seeds, watchlist, diagnostics = build_trend_continuation_pool([result])

        self.assertEqual([], seeds)
        self.assertEqual(["600013"], [row["code"] for row in watchlist])
        self.assertEqual("daily_breakout", watchlist[0]["failure_gate"])
        self.assertEqual("platform_high_20d", watchlist[0]["reference_type"])
        self.assertAlmostEqual(12.0, watchlist[0]["reference_price"])
        self.assertEqual(1, diagnostics["watch_near_miss"])

    def test_volume_ratio_1_3_requires_strong_structure(self):
        strong = _result(code="600001", today_volume=1_300_000)
        weak = _result(
            code="600002",
            last_close=11.1,
            previous_close=11.0,
            today_volume=1_300_000,
        )

        seeds, watchlist, diagnostics = build_trend_continuation_pool(
            [strong, weak]
        )

        self.assertEqual([row["code"] for row in seeds], ["600001"])
        self.assertEqual([row["code"] for row in watchlist], ["600002"])
        self.assertEqual(
            watchlist[0]["reason_code"], "daily_breakout_near_miss"
        )
        self.assertEqual(diagnostics["watch_near_miss"], 1)

    def test_volume_ratio_1_05_strong_structure_enters_observation_only(self):
        strong = _result(code="600005", today_volume=1_050_000)

        seeds, watchlist, diagnostics = build_trend_continuation_pool(
            [strong]
        )

        self.assertEqual(seeds, [])
        self.assertEqual([row["code"] for row in watchlist], ["600005"])
        self.assertEqual(watchlist[0]["reason_code"], "volume_near_miss")
        self.assertEqual(watchlist[0]["view"], "observation")
        self.assertEqual(diagnostics["watch_near_miss"], 1)

    def test_volume_ratio_1_05_weak_structure_stays_out(self):
        weak = _result(
            code="600006",
            last_close=11.1,
            previous_close=11.0,
            today_volume=1_050_000,
        )

        seeds, watchlist, diagnostics = build_trend_continuation_pool(
            [weak]
        )

        self.assertEqual(seeds, [])
        self.assertEqual(watchlist, [])
        self.assertEqual(diagnostics["dropped_structure"], 1)

    def test_limit_up_and_overextended_go_to_watch_only(self):
        limit_up = _result(
            code="600003",
            last_close=12.1,
            previous_close=11.0,
            today_open=11.8,
        )
        overextended = _result(
            code="600004",
            last_close=13.6,
            previous_close=13.0,
            today_open=13.1,
        )

        seeds, watchlist, diagnostics = build_trend_continuation_pool(
            [limit_up, overextended]
        )

        self.assertEqual(seeds, [])
        self.assertEqual(
            {row["reason_code"] for row in watchlist},
            {"limit_up", "overextended"},
        )
        self.assertEqual(diagnostics["watch_risk"], 2)

    def test_30min_confirmation_upgrades_seed_without_changing_reference(self):
        seeds, _, _ = build_trend_continuation_pool([_result()])
        closes = np.linspace(12.0, 12.8, 20)
        opens = closes - 0.05
        opens[-3:-1] = closes[-3:-1] + 0.05
        min30 = _min30_result(
            closes,
            opens=opens,
            volumes=[1_000_000] * 15 + [500_000] * 5,
        )

        candidates, watchlist, diagnostics = (
            upgrade_trend_continuation_with_30min(seeds, [min30])
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(watchlist, [])
        self.assertEqual(candidates[0]["reference_price"], 12.0)
        self.assertEqual(candidates[0]["tier"], "candidate")
        self.assertEqual(candidates[0]["category"], "A")
        self.assertEqual(diagnostics["trend_candidate"], 1)
        pick = normalize_trend_candidate(candidates[0])
        self.assertEqual(
            pick["best_buy_point"]["price"],
            candidates[0]["reference_price"],
        )
        self.assertNotEqual(pick["best_buy_point"]["price"], 7.0)

    def test_30min_ema_state_without_fresh_structure_stays_watch(self):
        seeds, _, _ = build_trend_continuation_pool([_result()])
        closes = np.linspace(12.0, 12.8, 20)
        min30 = _min30_result(
            closes,
            volumes=[1_000_000] * 15 + [500_000] * 5,
        )

        candidates, watchlist, _ = upgrade_trend_continuation_with_30min(
            seeds, [min30]
        )

        self.assertEqual([], candidates)
        self.assertEqual("30min_structure", watchlist[0]["failure_gate"])
        evidence = watchlist[0]["confirmation_evidence"]
        self.assertTrue(evidence["mandatory"]["reference_hold"])
        self.assertFalse(evidence["structure"]["fresh_event"])
        self.assertTrue(evidence["quality"]["independent_confirm"])

    def test_30min_structure_without_independent_quality_stays_watch(self):
        seeds, _, _ = build_trend_continuation_pool([_result()])
        closes = np.asarray([12.1] * 20, dtype=float)
        opens = closes.copy()
        opens[-4:] = [12.0, 12.2, 12.2, 12.0]
        min30 = _min30_result(closes, opens=opens)

        candidates, watchlist, _ = upgrade_trend_continuation_with_30min(
            seeds, [min30]
        )

        self.assertEqual([], candidates)
        self.assertEqual("30min_quality", watchlist[0]["failure_gate"])
        evidence = watchlist[0]["confirmation_evidence"]
        self.assertTrue(evidence["structure"]["fresh_event"])
        self.assertFalse(evidence["quality"]["independent_confirm"])

    def test_30min_stale_or_wrong_date_evidence_fails_closed(self):
        seeds, _, _ = build_trend_continuation_pool([_result()])
        closes = np.linspace(12.0, 12.8, 20)
        opens = closes - 0.05
        opens[-3:-1] = closes[-3:-1] + 0.05
        stale = _verified_evidence("2026-07-13")
        stale.update({"status": "stale_cache", "stale": True})
        min30 = _min30_result(
            closes,
            opens=opens,
            evidence=stale,
        )

        candidates, watchlist, _ = upgrade_trend_continuation_with_30min(
            seeds, [min30]
        )

        self.assertEqual([], candidates)
        self.assertEqual("30min_data_contract", watchlist[0]["failure_gate"])
        self.assertFalse(watchlist[0]["confirmation_evidence"]["data"]["valid"])

    def test_30min_candidate_preserves_verified_strategy_input_evidence(self):
        seeds, _, _ = build_trend_continuation_pool([_result()])
        seeds[0]["startup_date"] = "2026-08-26"
        closes = np.linspace(12.0, 12.8, 20)
        opens = closes - 0.05
        opens[-3:-1] = closes[-3:-1] + 0.05
        evidence = {
            "interval": "30m",
            "status": "verified",
            "latest_date": "2026-08-26",
            "latest_ts": "2026-08-26 15:00:00",
            "source": "market_history_db",
            "bars": 20,
            "stale": False,
            "is_final": True,
            "bar_state": "closed",
        }
        min30 = _min30_result(
            closes,
            trade_date="2026-08-26",
            opens=opens,
            volumes=[1_000_000] * 15 + [500_000] * 5,
            evidence=evidence,
        )

        candidates, _, _ = upgrade_trend_continuation_with_30min(
            seeds, [min30]
        )
        normalized = normalize_trend_candidate(candidates[0])

        self.assertEqual(candidates[0]["strategy_input_evidence"], evidence)
        self.assertEqual(normalized["strategy_input_evidence"], evidence)


if __name__ == "__main__":
    unittest.main()
