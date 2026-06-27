import unittest
from unittest.mock import patch

from chanlun.policy_experiment_metrics import (
    list_policy_experiments,
    bottom_quality_guard_reasons,
    should_filter_for_policy,
    run_policy_experiment_metrics,
)


def _make_pick(
    code="000001",
    point_type="底背驰候选",
    distance=None,
    index=0,
    confirmations=None,
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
        "closes": [1, 2, 3, 4, 5, 6, 7],
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
            },
        )

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

    def test_run_policy_experiment_metrics_rejects_unknown_policy(self):
        with self.assertRaisesRegex(ValueError, "unsupported policies"):
            run_policy_experiment_metrics(["delay1_v1_not_exists"])

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
