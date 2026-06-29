import unittest
from unittest.mock import patch

from chanlun.policy_experiment_metrics import (
    list_policy_experiments,
    bottom_quality_guard_reasons,
    bottom_trend_guard_reasons,
    should_filter_for_policy,
    run_policy_experiment_metrics,
)


def _make_pick(
    code="000001",
    point_type="底背驰候选",
    distance=None,
    index=0,
    confirmations=None,
    market_regime=None,
    ma_bullish=None,
):
    bbp = {
        "type": point_type,
        "index": index,
    }
    if distance is not None:
        bbp["distance_from_reference_pct"] = distance
    if confirmations is not None:
        bbp["confirmations"] = confirmations
    return {
        "code": code,
        "best_buy_point": bbp,
        "market_regime": market_regime,
        "ma_bullish": ma_bullish,
        "closes": [1, 2, 3, 4, 5, 6, 7],
    }


def _make_fusion_pick(
    code="000001",
    best_type="一买",
    trend_strength=2.0,
    volatility=0.05,
    pivot=None,
    segment=None,
    signal_index=0,
    market_regime=None,
):
    return {
        "code": code,
        "best_buy_point": {
            "type": best_type,
            "trend_strength": trend_strength,
            "volatility": volatility,
            "pivot": pivot,
            "segment": segment,
            "index": signal_index,
        },
        "market_regime": market_regime,
    }


class PolicyExperimentMetricsTests(unittest.TestCase):
    def test_list_policy_experiments(self):
        names = set(list_policy_experiments())
        self.assertEqual(
            names,
            {
                "delay1_v1",
                "delay1_v1_cooldown3",
                "delay1_v1_cooldown5",
                "delay1_v1_bottom_quality_guard",
                "delay1_v1_cooldown3_bottom_quality",
                "delay1_v1_bottom_missing_key_guard",
                "delay1_v1_bottom_missing_distance_guard",
                "delay1_v1_bottom_invalid_distance_guard",
                "delay1_v1_bottom_distance_gt6_guard",
                "delay1_v1_bottom_missing_shape_guard",
                "delay1_v1_bottom_quality_market_strong_guard",
                "delay1_v1_bottom_quality_market_known_guard",
                "delay1_v1_bottom_quality_market_known_guard_entry_signal_close",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open",
                "delay1_v1_bottom_quality_market_known_guard_entry_confirm_close",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative",
                "delay1_v1_bottom_quality_market_or_ma_guard",
                "fusion_strict",
                "fusion_strict_startup_rescue_v1",
                "fusion_mid",
                "fusion_loose",
            },
        )

    def test_execution_variant_policy_has_same_filters_as_known_market_guard(self):
        base_policy = "delay1_v1_bottom_quality_market_known_guard"
        variant_policies = (
            "delay1_v1_bottom_quality_market_known_guard_entry_signal_close",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open",
            "delay1_v1_bottom_quality_market_known_guard_entry_confirm_close",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative",
        )
        picks = (
            _make_pick(
                point_type="底背驰候选",
                distance=1.8,
                confirmations=["关键位不破", "30min底分型", "止跌结构"],
                market_regime="strong",
            ),
            _make_pick(
                point_type="底背驰候选",
                distance=7.0,
                confirmations=["关键位不破", "30min底分型", "止跌结构"],
                market_regime="strong",
            ),
            _make_pick(
                point_type="底背驰候选",
                distance=None,
                confirmations=["关键位不破", "30min底分型", "止跌结构"],
                market_regime="strong",
            ),
            _make_pick(
                point_type="底背驰候选",
                distance=1.8,
                confirmations=[],
                market_regime="weak",
                ma_bullish=True,
            ),
        )

        for variant in variant_policies:
            for pick in picks:
                base_filtered, base_reason = should_filter_for_policy(base_policy, pick, {})
                variant_filtered, variant_reason = should_filter_for_policy(variant, pick, {})
                self.assertEqual(base_filtered, variant_filtered)
                self.assertEqual(base_reason, variant_reason)

    def test_bottom_quality_guard_reasons(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), [])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["missing_key_protection"])

        pick = _make_pick(
            point_type="底背驰候选",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["missing_distance"])

        pick = _make_pick(
            point_type="底背驰候选",
            distance="invalid",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["invalid_distance"])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=7.1,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["distance_gt_6"])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["关键位不破"],
        )
        self.assertEqual(
            bottom_quality_guard_reasons(pick),
            ["missing_bottom_shape_or_stop_drop"],
        )

        pick = _make_pick(
            point_type="底背驰候选",
            distance="invalid",
            confirmations=["止跌结构"],
        )
        self.assertEqual(
            bottom_quality_guard_reasons(pick),
            ["missing_key_protection", "invalid_distance"],
        )

        pick = {"best_buy_point": {"type": "强势启动候选"}}
        self.assertEqual(bottom_quality_guard_reasons(pick), [])

    def test_bottom_trend_guard_reasons(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="strong",
            ma_bullish=False,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_trend_guard_reasons(pick), [])

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=False,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(
            bottom_trend_guard_reasons(pick),
            ["market_not_strong", "market_not_strong_no_ma"],
        )

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=True,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_trend_guard_reasons(pick), ["market_not_strong"])

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="",
            ma_bullish=True,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_trend_guard_reasons(pick), ["market_unknown", "market_not_strong"])

        pick = {"best_buy_point": {"type": "强势启动候选"}, "market_regime": None}
        self.assertEqual(bottom_trend_guard_reasons(pick), [])

    def test_bottom_trend_guard_filters(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="strong",
            ma_bullish=False,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_strong_guard",
            pick,
            {},
        )
        self.assertFalse(filtered)
        self.assertEqual(reason, "")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=True,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_strong_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_not_strong")

    def test_bottom_trend_guard_order_quality_before_trend(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=False,
            distance="invalid",
            confirmations=["30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_quality_guard")

    def test_bottom_trend_known_and_or_ma_policies(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime=None,
            ma_bullish=True,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_known_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_unknown")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=False,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_not_strong_no_ma")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="",
            ma_bullish=False,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_not_strong_no_ma")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=True,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertFalse(filtered)
        self.assertEqual(reason, "")

    def test_bottom_quality_guard_filters_missing_key_reference_distance_or_confirmations(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["30min底分型"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_quality_guard")

        pick = _make_pick(
            point_type="底背驰候选",
            confirmations=["关键位不破", "30min底分型"],
        )
        self.assertTrue(should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})[0])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=7.0,
            confirmations=["关键位不破", "止跌结构"],
        )
        self.assertTrue(should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})[0])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["关键位不破"],
        )
        self.assertTrue(should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})[0])

    def test_bottom_quality_guard_keeps_valid_bottom_and_non_bottom(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "其他"],
        )
        filtered, _reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertFalse(filtered)

        pick = _make_pick(
            point_type="底背驰候选",
            distance=5.9,
            confirmations=["关键位不破", "止跌结构"],
        )
        filtered, _reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertFalse(filtered)

        pick = _make_pick(point_type="强势启动候选")
        filtered, _reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertFalse(filtered)

    def test_bottom_quality_single_reason_policies(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_key_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_missing_key_protection")

        pick = _make_pick(
            point_type="底背驰候选",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_distance_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_missing_distance")

        pick = _make_pick(
            point_type="底背驰候选",
            distance="abc",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_invalid_distance_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_invalid_distance")

        pick = _make_pick(
            point_type="底背驰候选",
            distance=7.5,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_distance_gt6_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_distance_gt_6")

        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["关键位不破"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_shape_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_missing_shape_or_stop_drop")

        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_shape_guard", pick, {})
        self.assertFalse(filtered)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_cooldown_policy(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-05", "picks_fusion", _make_pick()),
                ("2026-01-04", "picks_fusion", _make_pick()),
                ("2026-01-04", "picks_pure", _make_pick(index=1)),
                ("2026-01-06", "picks_pure", _make_pick()),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }
        payload = run_policy_experiment_metrics(["delay1_v1_cooldown3"])
        self.assertEqual(len(payload["policies"]), 1)
        result = payload["policies"][0]
        self.assertEqual(result["coverage"]["picks_seen"], 4)
        self.assertGreater(result["coverage"]["baseline_evaluated"], 0)
        # first sorted by (snap_date, version, code): 01-04 picks_fusion -> 01-04 picks_pure -> 01-05 -> 01-06
        # cooldown window=3 => keep only the first 01-04 sample.
        self.assertEqual(result["coverage"]["policy_evaluated"], 1)
        self.assertEqual(result["coverage"]["policy_filtered_by_reason"].get("cooldown"), 3)

    @patch("chanlun.historical_experiment_metrics.fetch_daily_kline")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_multiple_policies_share_kline_fetch_across_codes(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-05", "picks_fusion", _make_pick(code="000001")),
                ("2026-01-06", "picks_fusion", _make_pick(code="000001")),
                ("2026-01-07", "picks_pure", _make_pick(code="000002")),
            ],
        )
        fetch_mock.return_value = {
            "dates": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
            ],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(
            ["delay1_v1", "delay1_v1_bottom_quality_guard"],
        )
        self.assertEqual(len(payload["policies"]), 2)
        self.assertEqual(fetch_mock.call_count, 2)
        policy_names = [item["policy"] for item in payload["policies"]]
        self.assertEqual(policy_names, ["delay1_v1", "delay1_v1_bottom_quality_guard"])
        for item in payload["policies"]:
            self.assertEqual(item["coverage"]["baseline_evaluated"], 3)
            self.assertEqual(item["coverage"]["baseline_filtered"], 0)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_summary_reports_shared_cache_counters(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-07", "picks_pure", _make_pick(code="000002")),
                ("2026-01-05", "picks_fusion", _make_pick(code="000001")),
                ("2026-01-06", "picks_fusion", _make_pick(code="000001")),
            ],
        )
        fetch_mock.side_effect = lambda code, *_args, **_kwargs: {
            "000001": {
                "dates": [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                ],
                "opens": [1, 1, 1, 1, 1, 1, 1],
                "highs": [1, 1, 1, 1, 1, 1, 1],
                "lows": [1, 1, 1, 1, 1, 1, 1],
                "closes": [1, 1, 1, 1, 1, 1, 1],
            },
            "000002": {
                "dates": [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                ],
                "opens": [1, 1, 1, 1, 1, 1, 1],
                "highs": [1, 1, 1, 1, 1, 1, 1],
                "lows": [1, 1, 1, 1, 1, 1, 1],
                "closes": [1, 1, 1, 1, 1, 1, 1],
            },
        }.get(code)
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        execution = payload.get("execution") or {}
        self.assertTrue(execution["shared_baseline"])
        self.assertEqual(execution["snapshot_rows"], 3)
        self.assertEqual(execution["unique_codes"], 2)
        self.assertEqual(execution["fetch_attempts"], 2)
        self.assertEqual(execution["cache_hits"], 1)
        self.assertEqual(execution["baseline_rows"], 3)
        self.assertEqual(execution["kline_missing"], 0)
        self.assertEqual(execution["kline_invalid"], 0)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._normalize_kline")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_summary_reports_missing_and_invalid_kline_rows(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        normalize_mock,
        fetch_mock,
    ):
        invalid_kline = object()
        valid_kline = {
            "dates": ["2026-01-01", "2026-01-02"],
            "opens": [1, 1],
            "highs": [1, 1],
            "lows": [1, 1],
            "closes": [1, 1],
        }

        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-05", "picks_pure", _make_pick(code="000001")),
                ("2026-01-06", "picks_pure", _make_pick(code="000002")),
                ("2026-01-07", "picks_pure", _make_pick(code="000003")),
            ],
        )
        fetch_mock.side_effect = lambda code, *_args, **_kwargs: {
            "000001": None,
            "000002": invalid_kline,
            "000003": valid_kline,
        }.get(code)
        normalize_mock.side_effect = lambda kline: {} if kline is invalid_kline else {
            "dates": ["x"],
            "opens": [1.0],
            "highs": [1.0],
            "lows": [1.0],
            "closes": [1.0],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        execution = payload.get("execution") or {}
        self.assertTrue(execution["shared_baseline"])
        self.assertEqual(execution["snapshot_rows"], 3)
        self.assertEqual(execution["unique_codes"], 3)
        self.assertEqual(execution["fetch_attempts"], 3)
        self.assertEqual(execution["cache_hits"], 0)
        self.assertEqual(execution["kline_missing"], 1)
        self.assertEqual(execution["kline_invalid"], 1)
        self.assertEqual(execution["baseline_rows"], 1)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_multiple_policies_keep_cooldown_state_independent(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-01", "picks_fusion", _make_pick()),
                ("2026-01-02", "picks_fusion", _make_pick()),
                ("2026-01-03", "picks_fusion", _make_pick()),
            ],
        )
        fetch_mock.return_value = {
            "dates": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
            ],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(
            ["delay1_v1", "delay1_v1_cooldown3"],
        )
        policy_map = {item["policy"]: item for item in payload["policies"]}
        self.assertEqual(policy_map["delay1_v1"]["coverage"]["policy_evaluated"], 3)
        self.assertEqual(policy_map["delay1_v1_cooldown3"]["coverage"]["policy_evaluated"], 1)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_run_policy_experiment_metrics_returns_baseline_and_policy(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-02", "picks_pure", {"code": "000001", "best_buy_point": {"type": "强势启动候选", "index": 0}, "closes": [1, 2, 3]}),
                ("2026-01-01", "picks_fusion", {"code": "000002", "best_buy_point": {"type": "强势启动候选", "index": 0}, "closes": [1, 2, 3]}),
            ]
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        self.assertIn("policies", payload)
        self.assertEqual(len(payload["policies"]), 1)
        result = payload["policies"][0]
        self.assertEqual(result["policy"], "delay1_v1")
        self.assertIn("baseline_summary", result)
        self.assertIn("policy_summary", result)
        self.assertIn("delta", result)
        self.assertEqual(result["delta"]["t3_mean_delta"], 0.0)
        self.assertEqual(payload["requested_policies"], ["delay1_v1"])

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_variant_re_evaluates_with_explicit_entry_mode(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }

        observed_entry_modes = []

        def evaluate_side_effect(_normalized_kline, _snap_date, entry_mode):
            observed_entry_modes.append(entry_mode)
            if entry_mode == "delay1_close":
                return {
                    "t1_close_pct": 1.0,
                    "t3_close_pct": 1.0,
                    "max_up_3d": 0.5,
                    "max_dd_3d": -0.2,
                }
            if entry_mode == "delay1_open":
                return {
                    "t1_close_pct": 2.0,
                    "t3_close_pct": 2.0,
                    "max_up_3d": 1.5,
                    "max_dd_3d": -0.1,
                }
            return {
                "t1_close_pct": 3.0,
                "t3_close_pct": 3.0,
                "max_up_3d": 2.0,
                "max_dd_3d": -0.05,
            }

        evaluate_mock.side_effect = evaluate_side_effect
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_next_open"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 0)
        self.assertEqual(coverage["policy_evaluated"], 1)
        self.assertEqual(coverage["policy_filtered"], 0)
        self.assertEqual(result["policy_summary"]["n"], 1)
        self.assertEqual(result["policy_summary"]["t3_mean"], 2.0)
        self.assertEqual(result["execution_model"]["entry_label"], "entry_next_open")
        self.assertEqual(result["execution_model"]["entry_mode"], "delay1_open")
        self.assertEqual(result["execution_model"]["exit_model"], "exit_t3")
        self.assertIn("delay1_close", observed_entry_modes)
        self.assertIn("delay1_open", observed_entry_modes)

    @patch("chanlun.policy_experiment_metrics.evaluate_exit_returns")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_exit_variant_calls_exit_evaluator(
        self,
        iter_snapshot_mock,
        fetch_mock,
        evaluate_pick_mock,
        evaluate_exit_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_exit_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 2.0,
            "max_up_3d": 1.5,
            "max_dd_3d": -0.2,
            "exit_model": "exit_stop_loss_5pct",
            "exit_reason": "t3_close",
            "exit_return_pct": 2.0,
            "exit_day_index": 3,
        }
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 0)
        self.assertEqual(coverage["policy_evaluated"], 1)
        self.assertEqual(result["execution_model"]["entry_label"], "entry_next_open")
        self.assertEqual(result["execution_model"]["entry_mode"], "delay1_open")
        self.assertEqual(result["execution_model"]["exit_model"], "exit_stop_loss_5pct")
        evaluate_exit_mock.assert_called_once()
        evaluate_exit_mock.assert_called_with(
            fetch_mock.return_value,
            "2026-01-02",
            "delay1_open",
            "exit_stop_loss_5pct",
        )

    @patch("chanlun.policy_experiment_metrics.evaluate_exit_returns")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_exit_variant_not_evaluable_counted(self, iter_snapshot_mock, fetch_mock, evaluate_pick_mock, evaluate_exit_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_exit_mock.return_value = None
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 1)
        self.assertEqual(coverage["policy_evaluated"], 0)
        self.assertIsNone(result["policy_summary"])
        evaluate_exit_mock.assert_called_once()
        evaluate_exit_mock.assert_called_with(
            fetch_mock.return_value,
            "2026-01-02",
            "delay1_open",
            "exit_take_profit_8pct_or_t3",
        )

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_variant_records_policy_not_evaluable(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }

        def evaluate_side_effect(_normalized_kline, _snap_date, entry_mode):
            if entry_mode == "immediate_close":
                return None
            return {
                "t1_close_pct": 1.0,
                "t3_close_pct": 1.0,
                "max_up_3d": 0.5,
                "max_dd_3d": -0.2,
            }

        evaluate_mock.side_effect = evaluate_side_effect
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_signal_close"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 1)
        self.assertEqual(coverage["policy_evaluated"], 0)
        self.assertEqual(result["policy_summary"], None)
        self.assertEqual(
            result["breakdown"]["market_regime"]["strong"]["accepted"],
            1,
        )

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_bottom_quality_guard_reports_detailed_reason_breakdown(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-02", "picks_pure", _make_pick(distance=None, confirmations=["止跌结构"])),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1_bottom_quality_guard"])
        self.assertEqual(len(payload["policies"]), 1)
        result = payload["policies"][0]
        self.assertEqual(result["coverage"]["policy_filtered"], 1)
        self.assertEqual(result["coverage"]["policy_filtered_by_reason"]["bottom_quality_guard"], 1)
        self.assertEqual(
            result["coverage"]["policy_filtered_detail_by_reason"]["bottom_missing_key_protection"],
            1,
        )
        self.assertEqual(
            result["coverage"]["policy_filtered_detail_by_reason"]["bottom_missing_distance"],
            1,
        )
        self.assertNotIn(
            "bottom_missing_key_protection",
            result["coverage"]["policy_filtered_by_reason"],
        )

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_run_policy_experiment_metrics_includes_breakdown(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-01",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="",
                    ),
                ),
                (
                    "2026-01-03",
                    "picks_pure",
                    _make_pick(
                        point_type="强势启动候选",
                        confirmations=[],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.side_effect = lambda code, *_args, **_kwargs: {
            "000001": {
                "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
                "opens": [1, 1, 1, 1, 1],
                "highs": [1, 1, 1, 1, 1],
                "lows": [1, 1, 1, 1, 1],
                "closes": [1, 1, 1, 1, 1],
            }
        }.get(code)
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1_bottom_quality_market_known_guard"])
        result = payload["policies"][0]
        breakdown = result["breakdown"]
        self.assertEqual(breakdown["market_regime"]["strong"]["accepted"], 2)
        self.assertEqual(breakdown["market_regime"]["unknown"]["filtered"], 1)
        self.assertEqual(
            breakdown["market_regime"]["unknown"]["filter_reasons"]["bottom_market_unknown"],
            1,
        )
        self.assertEqual(
            breakdown["best_buy_point_type"]["底背驰候选"]["total"],
            2,
        )
        self.assertEqual(
            breakdown["best_buy_point_type"]["强势启动候选"]["accepted"],
            1,
        )
        confirmation_bucket_key = next(
            key
            for key in breakdown["confirmations"].keys()
            if "关键位不破" in key and "30min底分型" in key
        )
        self.assertEqual(
            breakdown["confirmations"][confirmation_bucket_key]["filtered"],
            1,
        )
        self.assertEqual(breakdown["confirmations"]["none"]["accepted"], 1)

    def test_run_policy_experiment_metrics_rejects_unknown_policy(self):
        with self.assertRaisesRegex(ValueError, "unsupported policies"):
            run_policy_experiment_metrics(["delay1_v1_not_exists"])

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_run_policy_experiment_metrics_fusion_threshold_scan(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=2.0, volatility=0.05, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=0, code="000001")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=1.6, volatility=0.08, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=1, code="000002")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(best_type="强势启动候选", trend_strength=1.0, volatility=0.08, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=2, code="000003", market_regime="weak")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=1.0, volatility=0.11, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=3, code="000004")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=1.0, volatility=0.11, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=4, code="000005")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(best_type="强势启动候选", trend_strength=1.0, volatility=0.08, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=5, code="000006", market_regime="strong")),
                ("2026-01-01", "picks_pure", _make_fusion_pick(code="000007")),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
            "opens": [1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1],
        }
        evaluate_mock.side_effect = [
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 2.0,
                "max_up_3d": 0.5,
                "max_dd_3d": -5.0,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 2.5,
                "max_up_3d": 1.0,
                "max_dd_3d": -4.8,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": -0.5,
                "max_up_3d": -0.5,
                "max_dd_3d": -4.7,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": -1.0,
                "max_up_3d": -1.0,
                "max_dd_3d": -5.5,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 0.5,
                "max_up_3d": 0.5,
                "max_dd_3d": -6.0,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 0.7,
                "max_up_3d": 0.5,
                "max_dd_3d": -5.2,
            },
        ]

        payload = run_policy_experiment_metrics(
            [
                "fusion_strict",
                "fusion_strict_startup_rescue_v1",
                "fusion_mid",
                "fusion_loose",
            ],
        )
        self.assertEqual(payload["policies"], [])
        scan = payload.get("fusion_threshold_scan")
        self.assertIsNotNone(scan)
        self.assertIn("profiles", scan)
        self.assertEqual(len(scan["profiles"]), 4)

        strict_profile = next(item for item in scan["profiles"] if item["candidate"] == "fusion_strict")
        rescue_profile = next(
            item for item in scan["profiles"]
            if item["candidate"] == "fusion_strict_startup_rescue_v1"
        )
        mid_profile = next(item for item in scan["profiles"] if item["candidate"] == "fusion_mid")
        loose_profile = next(item for item in scan["profiles"] if item["candidate"] == "fusion_loose")

        self.assertEqual(strict_profile["samples_before"], 6)
        self.assertEqual(strict_profile["samples_after"], 1)
        self.assertEqual(strict_profile["rejected_samples"], 5)
        self.assertEqual(
            strict_profile["reject_reason_distribution"]["trend_strength_below_min"],
            5,
        )
        self.assertEqual(
            strict_profile["reject_reason_distribution"]["volatility_above_max"],
            2,
        )
        self.assertEqual(rescue_profile["samples_after"], 2)
        self.assertEqual(rescue_profile["reject_reason_distribution"]["strong_market_rescue_guard"], 1)
        self.assertEqual(
            rescue_profile["reject_reason_distribution"]["trend_strength_below_min"],
            4,
        )
        self.assertEqual(
            rescue_profile["quality_tier_distribution"],
            {"A": 1, "A-": 1},
        )
        self.assertEqual(
            rescue_profile["expected_horizon_distribution"],
            {"T+1": 1, "T+3": 1},
        )
        self.assertEqual(mid_profile["samples_after"], 2)
        self.assertEqual(mid_profile["rejected_samples"], 4)
        self.assertEqual(mid_profile["variant"], "fusion_mid_trend")
        self.assertEqual(
            mid_profile["reject_reason_distribution"]["trend_strength_below_min"],
            4,
        )
        self.assertEqual(loose_profile["samples_after"], 4)
        self.assertEqual(payload["baseline_reference"], "picks_fusion")

        selected = scan["selected"]
        self.assertEqual(selected["candidate"], "fusion_strict_startup_rescue_v1")
        self.assertEqual(selected["accepted"], False)
        self.assertEqual(
            set(scan["rejected"]),
            {"fusion_strict", "fusion_mid", "fusion_loose"},
        )

        self.assertEqual(scan["baseline_metrics"]["samples"], 6)
        self.assertEqual(scan["baseline_metrics"]["t3_mean_before"], 0.7)
        self.assertEqual(scan["baseline_metrics"]["t3_win_rate_before"], 66.7)
        self.assertEqual(scan["baseline_metrics"]["drawdown_mean_before"], -5.2)
        self.assertEqual(scan["execution"]["baseline_rows"], 6)
        self.assertEqual(scan["snapshot_rows"], 6)

        pareto = scan["pareto_frontier"]
        self.assertEqual(set(pareto), {"fusion_mid", "fusion_loose"})

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_baseline_excludes_delay1_v1_filtered_samples(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-01",
                    "picks_pure",
                    {
                        "code": "000001",
                        "best_buy_point": {"type": "底背驰候选", "index": 2},
                        "closes": [1, 2, 3],
                    },
                ),
                (
                    "2026-01-02",
                    "picks_pure",
                    {
                        "code": "000002",
                        "best_buy_point": {"type": "强势启动候选", "index": 0},
                        "closes": [1, 2, 3],
                    },
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        result = payload["policies"][0]
        self.assertEqual(result["coverage"]["baseline_filtered"], 1)
        self.assertEqual(result["coverage"]["baseline_evaluated"], 1)
        self.assertEqual(result["coverage"]["policy_evaluated"], 1)
        self.assertEqual(result["baseline_summary"]["n"], 1)
        self.assertEqual(result["policy_summary"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
