import unittest
from types import SimpleNamespace

import numpy as np

from chanlun.trend_continuation import (
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
    )


class TrendContinuationTests(unittest.TestCase):
    def test_platform_breakout_reference_does_not_use_old_buy_source_price(self):
        seeds, watchlist, diagnostics = build_trend_continuation_pool([_result()])

        self.assertEqual(len(seeds), 1)
        self.assertEqual(watchlist, [])
        self.assertEqual(seeds[0]["reference_type"], "platform_high_20d")
        self.assertAlmostEqual(seeds[0]["reference_price"], 12.0)
        self.assertNotIn(seeds[0]["reference_price"], (7.0, 6.5))
        self.assertEqual(seeds[0]["source_channel"], "trend_continuation")
        self.assertEqual(seeds[0]["view"], "main")
        self.assertEqual(diagnostics["trend_seed"], 1)

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
        self.assertEqual(watchlist[0]["reason_code"], "ma_near_miss")
        self.assertEqual(diagnostics["watch_near_miss"], 1)

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
        min30 = SimpleNamespace(
            code="600000",
            closes=closes,
            volumes=np.array([1_000_000] * 15 + [700_000] * 5, dtype=float),
            dates=["2026-07-16 10:00"] * 20,
            buy_points=[],
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


if __name__ == "__main__":
    unittest.main()
