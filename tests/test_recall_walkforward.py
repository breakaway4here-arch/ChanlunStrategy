import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path

from chanlun.candidate_funnel import CandidateFunnel
from chanlun.market_history_store import MarketHistoryStore
from scripts.run_recall_walkforward import (
    DEFAULT_THRESHOLD_GRID,
    build_walkforward_blocks,
    load_walkforward_samples,
    run_recall_walkforward,
)


def _dates(count):
    start = date(2026, 1, 2)
    return [
        (start + timedelta(days=index)).isoformat()
        for index in range(count)
    ]


def _samples(day_count=53, per_day=8):
    rows = []
    dates = _dates(day_count)
    for day_index, signal_date in enumerate(dates):
        for stock_index in range(per_day):
            strong = stock_index < 3
            rows.append({
                "signal_date": signal_date,
                "code": "{:06d}".format(stock_index),
                "source_channel": (
                    "trend" if stock_index % 2 else "low_position"
                ),
                "distance_from_reference_pct": (
                    2.5 if strong else 5.5
                ),
                "chase_distance_pct": 10.0 if strong else 18.0,
                "volume_ratio": 1.4 if strong else 1.1,
                "ma_policy": "gap_neg025_ema5_up" if strong else "rank_only",
                "t3_return_pct": (
                    3.0 + day_index * 0.01 if strong else -2.0
                ),
                "max_dd_3d": -1.0 if strong else -6.0,
                "is_observation": stock_index == 3,
                "baseline_accepted": stock_index < 2,
                "is_top20": strong,
                "is_top30": stock_index < 4,
            })
    return rows


def _bar(ts, close, low=None):
    return {
        "ts": ts,
        "open": close,
        "high": close * 1.01,
        "low": low if low is not None else close * 0.99,
        "close": close,
        "volume": 1_000_000,
        "amount": 100_000_000,
        "adjustment": "qfq",
        "is_final": True,
        "source_batch": "fixture",
    }


class RecallWalkforwardTest(unittest.TestCase):
    def test_builds_30_day_train_3_day_embargo_and_five_four_day_tests(self):
        blocks = build_walkforward_blocks(_dates(53))

        self.assertEqual(5, len(blocks))
        self.assertEqual(30, len(blocks[0]["train_dates"]))
        self.assertEqual(3, len(blocks[0]["embargo_dates"]))
        self.assertTrue(all(len(block["test_dates"]) == 4 for block in blocks))
        for block in blocks:
            test_start = block["test_dates"][0]
            self.assertLess(block["train_dates"][-1], test_start)
            self.assertTrue(
                set(block["train_dates"]).isdisjoint(block["test_dates"])
            )
            self.assertTrue(
                set(block["embargo_dates"]).isdisjoint(block["test_dates"])
            )

    def test_runs_single_factor_then_adjacent_combinations_with_hashes(self):
        result = run_recall_walkforward(
            _samples(),
            bootstrap_iterations=200,
            random_seed=7,
            code_version="test-version",
        )

        self.assertEqual(5, len(result["blocks"]))
        self.assertEqual(
            set(DEFAULT_THRESHOLD_GRID),
            set(result["single_factor_scan"]),
        )
        self.assertGreater(len(result["adjacent_combinations"]), 0)
        full_cartesian = 1
        for values in DEFAULT_THRESHOLD_GRID.values():
            full_cartesian *= len(values)
        self.assertLess(len(result["adjacent_combinations"]), full_cartesian)
        self.assertEqual(64, len(result["data_hash"]))
        self.assertEqual(64, len(result["config_hash"]))
        self.assertEqual("test-version", result["code_version"])
        self.assertEqual(0, result["network_requests"])

    def test_reports_bootstrap_stability_attention_and_tail_risk_gates(self):
        result = run_recall_walkforward(
            _samples(),
            bootstrap_iterations=200,
            random_seed=11,
        )

        gates = result["acceptance_gates"]
        self.assertIn("bootstrap_95_ci", gates)
        self.assertIn("threshold_stability", gates)
        self.assertIn("attention_p95", gates)
        self.assertIn("tail_risk_delta_pp", gates)
        self.assertLessEqual(gates["attention_p95"], 5)
        self.assertGreaterEqual(
            gates["threshold_stability"]["stable_folds"], 4
        )
        self.assertTrue(gates["accepted"])

    def test_rejects_samples_without_strict_t3_labels(self):
        rows = _samples()
        rows[0]["t3_return_pct"] = None
        with self.assertRaisesRegex(ValueError, "T\\+3"):
            run_recall_walkforward(rows)

    def test_observation_returns_do_not_enter_main_recommendation_gates(self):
        rows = _samples()
        for row in rows:
            if row["is_observation"]:
                row.update({
                    "distance_from_reference_pct": 2.5,
                    "chase_distance_pct": 10.0,
                    "volume_ratio": 1.4,
                    "ma_policy": "gap_neg025_ema5_up",
                    "t3_return_pct": -50.0,
                    "max_dd_3d": -50.0,
                })
        result = run_recall_walkforward(
            rows,
            bootstrap_iterations=200,
            random_seed=13,
        )

        self.assertTrue(result["acceptance_gates"]["accepted"])
        self.assertGreater(result["acceptance_gates"]["attention_p95"], 0)

    def test_database_loader_uses_t_features_and_exact_t3_final_bars(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                instrument_id = store.upsert_instrument(
                    "stock", "SZ", "000001", "测试"
                )
                store.upsert_bars(
                    "day",
                    instrument_id,
                    [
                        _bar("2026-01-02", 10.0),
                        _bar("2026-01-03", 11.0),
                        _bar("2026-01-04", 10.5, low=9.0),
                        _bar("2026-01-05", 12.0),
                        _bar("2026-01-06", 99.0),
                    ],
                    adjustment="qfq",
                )
                funnel = CandidateFunnel("run-1", "2026-01-02")
                funnel.register({
                    "code": "000001",
                    "source_channel": "trend",
                    "distance_from_reference_pct": 2.0,
                    "volume_ratio": 1.4,
                    "ma5": 10.0,
                    "ma10": 9.8,
                    "ma20": 9.5,
                })
                funnel.pass_stage("000001", "eligible")
                funnel.pass_stage("000001", "retrieval")
                funnel.pass_stage("000001", "daily_channel")
                funnel.finalize(main_codes=["000001"], observation_codes=[])
                store.save_candidate_funnel(
                    funnel.run_record(metadata={"is_official": True}),
                    funnel.events,
                )

            samples = load_walkforward_samples(path)

        self.assertEqual(1, len(samples))
        self.assertAlmostEqual(20.0, samples[0]["t3_return_pct"], places=6)
        self.assertAlmostEqual(-10.0, samples[0]["max_dd_3d"], places=6)
        self.assertEqual(2.0, samples[0]["distance_from_reference_pct"])


if __name__ == "__main__":
    unittest.main()
