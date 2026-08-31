import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.replay_right_side_startup import (
    DEFAULT_BLOCK_COUNT,
    DEFAULT_TEST_DAYS,
    MIN_OOS_TRADE_DATES,
    build_activation_gate,
    build_replay_report,
    build_walkforward_blocks,
    collect_forward_outcome,
    connect_read_only,
    load_30m_bars,
    load_daily_bars,
    read_only_uri,
    select_replay_right_side_public,
    summarize_lane,
    _retrieval_codes,
)


def _event(day, code, t1, t3, t5, dd1=-1.0, dd3=-2.0, dd5=-3.0):
    return {
        "trade_date": day,
        "code": code,
        "returns_pct": {"t1": t1, "t3": t3, "t5": t5},
        "drawdowns_pct": {"t1": dd1, "t3": dd3, "t5": dd5},
    }


class ReplayRightSideStartupTests(unittest.TestCase):
    def test_default_walkforward_can_reach_activation_sample_floor(self):
        self.assertGreaterEqual(
            DEFAULT_TEST_DAYS * DEFAULT_BLOCK_COUNT,
            MIN_OOS_TRADE_DATES,
        )

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "market.sqlite"
        connection = sqlite3.connect(self.db_path)
        connection.executescript(
            """
            CREATE TABLE instruments (
                instrument_id INTEGER PRIMARY KEY,
                asset_type TEXT NOT NULL,
                exchange TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL
            );
            CREATE TABLE bars_day (
                instrument_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                is_final INTEGER NOT NULL
            );
            CREATE TABLE bars_30m (
                instrument_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                is_final INTEGER NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO instruments VALUES (1, 'stock', 'SZ', '300709', '精研科技')"
        )
        for index in range(1, 11):
            day = "2026-01-{:02d}".format(index)
            close = 10.0 + index
            connection.execute(
                "INSERT INTO bars_day VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (1, day, close - 0.2, close + 0.5, close - 0.5, close, 1000 + index),
            )
        for hour in (10, 11, 14, 15, 16):
            ts = "2026-01-05 {:02d}:00:00".format(hour)
            connection.execute(
                "INSERT INTO bars_30m VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (1, ts, 14.8, 15.2, 14.5, 15.0, 2000),
            )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_sqlite_is_opened_with_mode_ro_and_query_only(self):
        uri = read_only_uri(self.db_path)
        self.assertIn("mode=ro", uri)

        connection = connect_read_only(self.db_path)
        try:
            self.assertEqual(1, connection.execute("PRAGMA query_only").fetchone()[0])
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "INSERT INTO instruments VALUES (2, 'stock', 'SZ', '000001', '测试')"
                )
        finally:
            connection.close()

    def test_feature_queries_never_read_future_bars(self):
        connection = connect_read_only(self.db_path)
        try:
            daily = load_daily_bars(connection, 1, "2026-01-05", limit=30)
            minute30 = load_30m_bars(connection, 1, "2026-01-05", limit=30)
        finally:
            connection.close()

        self.assertEqual("2026-01-05", daily[-1]["ts"])
        self.assertLessEqual(minute30[-1]["ts"], "2026-01-05 15:00:00")
        self.assertNotIn("2026-01-05 16:00:00", [row["ts"] for row in minute30])

    def test_walkforward_blocks_keep_embargo_between_train_and_test(self):
        dates = ["2026-01-{:02d}".format(index) for index in range(1, 13)]
        blocks = build_walkforward_blocks(
            dates,
            train_days=4,
            embargo_days=2,
            test_days=2,
            block_count=3,
        )

        self.assertEqual(3, len(blocks))
        for block in blocks:
            self.assertEqual(2, len(block["embargo_dates"]))
            self.assertTrue(
                max(block["train_dates"])
                < min(block["embargo_dates"])
                < min(block["test_dates"])
            )
            self.assertTrue(set(block["train_dates"]).isdisjoint(block["test_dates"]))

    def test_forward_outcome_is_separate_from_feature_cutoff(self):
        connection = connect_read_only(self.db_path)
        try:
            outcome = collect_forward_outcome(connection, 1, "2026-01-05")
        finally:
            connection.close()

        self.assertEqual(6.666667, outcome["returns_pct"]["t1"])
        self.assertEqual(20.0, outcome["returns_pct"]["t3"])
        self.assertEqual(33.333333, outcome["returns_pct"]["t5"])
        self.assertEqual("2026-01-10", outcome["outcome_max_date"])

    def test_summary_includes_returns_tail_risk_and_daily_p95(self):
        events = [
            _event("2026-01-01", "A", 1, 3, 5, dd3=-3, dd5=-4),
            _event("2026-01-01", "B", -2, -1, 2, dd3=-6, dd5=-7),
            _event("2026-01-02", "C", 4, 5, -6, dd3=-2, dd5=-8),
        ]

        summary = summarize_lane(events)

        self.assertEqual(3, summary["event_count"])
        self.assertEqual(2, summary["daily_counts"]["2026-01-01"])
        self.assertEqual(2.0, summary["daily_count_p95"])
        for horizon in ("t1", "t3", "t5"):
            metrics = summary["outcomes"][horizon]
            self.assertIn("p10_return_pct", metrics)
            self.assertIn("worst_return_pct", metrics)
            self.assertIn("max_drawdown_pct", metrics)
            self.assertIn("tail_le_minus_5_rate_pct", metrics)
        self.assertEqual(33.333333, summary["outcomes"]["t3"]["tail_le_minus_5_rate_pct"])

    def test_gate_requires_non_inferior_t3_and_tail_delta_at_most_two_points(self):
        days = ["2026-01-{:02d}".format(index) for index in range(1, 21)]
        baseline = summarize_lane([
            _event(day, "M{:02d}".format(index), 1, 2, 3, dd3=-4)
            for index, day in enumerate(days, 1)
        ])
        passing = summarize_lane([
            _event(day, "R{:02d}".format(index), 2, 3, 5, dd3=-4)
            for index, day in enumerate(days, 1)
        ])
        inferior = summarize_lane([
            _event(day, "R{:02d}".format(index), 2, 1, 5, dd3=-4)
            for index, day in enumerate(days, 1)
        ])
        risky = summarize_lane([
            _event(day, "R{:02d}".format(index), 2, 4, 5, dd3=-7)
            for index, day in enumerate(days, 1)
        ])
        raw_counts = [
            {"trade_date": day, "confirmed_count": 2} for day in days
        ]

        self.assertTrue(
            build_activation_gate(
                passing, baseline, shadow_diagnostics=raw_counts
            )["passed"]
        )
        self.assertFalse(
            build_activation_gate(
                inferior, baseline, shadow_diagnostics=raw_counts
            )["passed"]
        )
        self.assertFalse(
            build_activation_gate(
                risky, baseline, shadow_diagnostics=raw_counts
            )["passed"]
        )

    def test_gate_fails_closed_without_minimum_dates_samples_or_raw_counts(self):
        short = summarize_lane([
            _event("2026-01-01", "R1", 1, 3, 4)
        ])
        gate = build_activation_gate(short, short)

        self.assertFalse(gate["passed"])
        self.assertIn("insufficient_oos_trade_dates", gate["reasons"])
        self.assertIn("insufficient_t3_samples", gate["reasons"])
        self.assertIn("missing_raw_candidate_volume_evidence", gate["reasons"])

    def test_retrieval_codes_fail_closed_without_full_gate_event_universe(self):
        connection = connect_read_only(self.db_path)
        try:
            with self.assertRaisesRegex(
                RuntimeError, "gate_events.*required"
            ):
                _retrieval_codes(
                    connection,
                    "2026-01-05",
                    {"picks_fusion": [{"code": "300709"}]},
                )
        finally:
            connection.close()

    def test_report_keeps_right_side_and_formal_baseline_separate(self):
        right = [_event("2026-01-01", "R1", 1, 3, 4)]
        baseline = [_event("2026-01-01", "M1", 2, 2, 3)]
        blocks = build_walkforward_blocks(
            ["2026-01-{:02d}".format(index) for index in range(1, 9)],
            train_days=4,
            embargo_days=2,
            test_days=2,
            block_count=1,
        )

        report = build_replay_report(
            right,
            baseline,
            blocks=blocks,
            source={"database_read_only": True, "network": "disabled"},
        )

        self.assertEqual(1, report["lanes"]["right_side"]["event_count"])
        self.assertEqual(1, report["lanes"]["formal_main_baseline"]["event_count"])
        self.assertTrue(report["source"]["database_read_only"])
        self.assertEqual("disabled", report["source"]["network"])
        self.assertEqual(1, len(report["walkforward"]["blocks"]))

    def test_replay_public_lane_reuses_fusion_top3_and_decision_gate(self):
        closes = list(range(1, 30))
        closes[-5:] = [100, 90, 80, 70, 60]
        candidate = {
            "code": "300709",
            "name": "精研科技",
            "source_channel": "right_side_startup",
            "reference_price": 50.0,
            "close": 60.0,
            "closes": closes,
            "opens": closes,
            "highs": [value + 1 for value in closes],
            "lows": [value - 1 for value in closes],
            "volumes": [1000] * len(closes),
            "confirmations": ["30min突破位不破"],
            "best_buy_point": {
                "type": "右侧启动候选",
                "tier": "candidate",
                "strength": "中",
                "confirmed_by": "30min突破位不破",
                "index": len(closes) - 1,
                "price": 50.0,
                "current_price": 60.0,
                "change_pct": 3.0,
                "volume_ratio": 1.5,
            },
        }

        state = select_replay_right_side_public(
            [candidate],
            report={},
            trade_date="2026-01-05",
            shanghai_closes=list(range(100, 180)),
            evaluator=lambda item, market_context=None: {
                "decision_code": "recommend",
                "decision": "推荐",
                "total_score": 80,
            },
        )

        self.assertEqual(["300709"], [row["code"] for row in state["main"]])
        self.assertEqual(1, state["diagnostics"]["fusion"]["output_count"])
        self.assertEqual(1, state["diagnostics"]["top3"]["published_count"])
        self.assertEqual(1, state["diagnostics"]["public_main_count"])


if __name__ == "__main__":
    unittest.main()
