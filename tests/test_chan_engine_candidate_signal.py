import copy
import unittest

import numpy as np

from chanlun.chan_engine import (
    analyze,
    analyze_dual,
    locate_buy_sell_points,
)
from chanlun.engine_candidate import (
    analyze_with_candidate_signal,
    locate_buy_sell_points_candidate,
)
from chanlun.engine_types import ChanResult, Pivot, Segment
from tests.test_buy_points import (
    make_result_confirmed_second_buy,
    make_result_unconfirmed_second_buy,
    make_result_with_no_pivots_but_fake_zone,
    make_result_with_only_first_buy,
    make_result_with_pivot_leave_and_pullback,
)
from tests.test_chan_engine_snapshot import SCENARIOS


def _make_kline(closes):
    closes = np.asarray(closes, dtype=float)
    return {
        "dates": list(range(len(closes))),
        "opens": closes.copy(),
        "highs": closes + 0.6,
        "lows": closes - 0.6,
        "closes": closes,
        "volumes": np.array([1000.0] * len(closes), dtype=float),
    }


def _serialize_points(points):
    return [
        {
            "type": p.get("type"),
            "tier": p.get("tier"),
            "index": p.get("index"),
            "price": p.get("price"),
            "date": p.get("date"),
            "reason": p.get("reason"),
            "strength": p.get("strength"),
        }
        for p in points
    ]


def _result_with_top_divergence_sell():
    closes = [10.0] * 50
    result = ChanResult(
        code="TEST",
        name="TEST",
        closes=closes,
        highs=closes,
        lows=closes,
        opens=closes,
        volumes=closes,
        dates=list(range(len(closes))),
    )
    seg = Segment(
        strokes=[],
        start_idx=10,
        end_idx=20,
        direction="up",
        high=15.0,
        low=9.0,
        confirmed=True,
    )
    result.segments = [seg]
    result.pivots = []
    result.divergence = {
        "type": "趋势顶背驰",
        "is_divergence": True,
        "area_ratio": 0.5,
        "hist_divergence": False,
        "prev_segment": (0, 5),
        "last_segment": (10, 20),
    }
    return result


def _result_with_swing_bottom_divergence_ref():
    closes = [10.0] * 80
    result = ChanResult(
        code="TEST",
        name="TEST",
        closes=closes,
        highs=closes,
        lows=closes,
        opens=closes,
        volumes=closes,
        dates=list(range(len(closes))),
    )
    result.segments = []
    result.pivots = []
    result.divergence = None
    result.swing_waves = [
        {"direction": "down", "start_idx": 0, "end_idx": 10, "start_price": 12.0, "end_price": 8.0},
        {"direction": "up", "start_idx": 10, "end_idx": 20, "start_price": 8.0, "end_price": 11.0},
        {"direction": "down", "start_idx": 20, "end_idx": 30, "start_price": 11.0, "end_price": 7.0},
    ]
    hist = np.zeros(80, dtype=float)
    hist[0:11] = -1.0
    hist[20:31] = -0.4
    result.macd_hist = hist
    return result


def _result_with_recent_pivot_absorb_reference():
    closes = [10.0] * 80
    closes[-1] = 9.95
    result = ChanResult(
        code="TEST",
        name="TEST",
        closes=closes,
        highs=closes,
        lows=closes,
        opens=closes,
        volumes=closes,
        dates=list(range(len(closes))),
    )
    result.segments = []
    result.pivots = [Pivot(ZD=9.8, ZG=11.0, segments=[], start_idx=40, end_idx=60)]
    result.divergence = None
    return result


class ChanEngineCandidateSignalTests(unittest.TestCase):
    def test_candidate_signal_matches_legacy_signal_on_snapshot_scenarios(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                base = analyze(
                    name,
                    name,
                    kline["dates"],
                    kline["opens"],
                    kline["highs"],
                    kline["lows"],
                    kline["closes"],
                    kline["volumes"],
                )

                legacy_source = copy.deepcopy(base)
                candidate_source = copy.deepcopy(base)
                legacy_source.buy_points = []
                legacy_source.sell_points = []
                candidate_source.buy_points = []
                candidate_source.sell_points = []

                legacy_points = locate_buy_sell_points(legacy_source)
                candidate_points = locate_buy_sell_points_candidate(candidate_source)

                self.assertEqual(_serialize_points(legacy_points[0]), _serialize_points(candidate_points[0]))
                self.assertEqual(_serialize_points(legacy_points[1]), _serialize_points(candidate_points[1]))

    def test_candidate_signal_analyzer_matches_legacy_dual_output(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                payload = analyze_dual(
                    code=name,
                    name=name,
                    dates=kline["dates"],
                    opens=kline["opens"],
                    highs=kline["highs"],
                    lows=kline["lows"],
                    closes=kline["closes"],
                    volumes=kline["volumes"],
                    candidate_analyzer=analyze_with_candidate_signal,
                )
                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])

    def test_candidate_signal_matches_third_buy_cases(self):
        for result in (
            make_result_with_no_pivots_but_fake_zone(),
            make_result_with_pivot_leave_and_pullback(),
        ):
            legacy_buy, legacy_sell = locate_buy_sell_points(result)
            candidate_buy, candidate_sell = locate_buy_sell_points_candidate(copy.deepcopy(result))

            self.assertEqual(_serialize_points(legacy_buy), _serialize_points(candidate_buy))
            self.assertEqual(_serialize_points(legacy_sell), _serialize_points(candidate_sell))

    def test_candidate_signal_matches_second_buy_cases(self):
        for result in (
            make_result_confirmed_second_buy(),
            make_result_unconfirmed_second_buy(),
            make_result_with_only_first_buy(),
        ):
            legacy_buy, legacy_sell = locate_buy_sell_points(result)
            candidate_buy, candidate_sell = locate_buy_sell_points_candidate(copy.deepcopy(result))

            self.assertEqual(_serialize_points(legacy_buy), _serialize_points(candidate_buy))
            self.assertEqual(_serialize_points(legacy_sell), _serialize_points(candidate_sell))

    def test_candidate_signal_matches_sell_and_swing_reference_cases(self):
        for result in (_result_with_top_divergence_sell(), _result_with_swing_bottom_divergence_ref()):
            legacy_buy, legacy_sell = locate_buy_sell_points(result)
            candidate_buy, candidate_sell = locate_buy_sell_points_candidate(copy.deepcopy(result))

            self.assertEqual(_serialize_points(legacy_buy), _serialize_points(candidate_buy))
            self.assertEqual(_serialize_points(legacy_sell), _serialize_points(candidate_sell))

    def test_candidate_signal_matches_pivot_low_absorb_reference(self):
        result = _result_with_recent_pivot_absorb_reference()
        legacy_buy, _ = locate_buy_sell_points(result)
        candidate_buy, _ = locate_buy_sell_points_candidate(copy.deepcopy(result))

        legacy_types = [p["type"] for p in legacy_buy]
        candidate_types = [p["type"] for p in candidate_buy]

        self.assertIn("中枢震荡低吸参考", legacy_types)
        self.assertIn("中枢震荡低吸参考", candidate_types)
        self.assertEqual(_serialize_points(legacy_buy), _serialize_points(candidate_buy))


if __name__ == "__main__":
    unittest.main()
