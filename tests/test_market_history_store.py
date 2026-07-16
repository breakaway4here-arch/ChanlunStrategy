import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chanlun.market_history_store import MarketHistoryStore


def _bar(ts, close=10.0, is_final=True, adjustment="qfq"):
    return {
        "ts": ts,
        "open": close - 0.2,
        "high": close + 0.3,
        "low": close - 0.4,
        "close": close,
        "volume": 1000,
        "amount": 10000,
        "is_final": is_final,
        "adjustment": adjustment,
        "source_batch": "batch-a",
    }


class MarketHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "market_history.sqlite"
        self.store = MarketHistoryStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_initializes_required_schema_primary_keys_and_cross_section_indexes(self):
        tables = {
            row[0]
            for row in self.store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertEqual(tables, {
            "instruments", "stock_meta_asof", "trade_calendar", "bars_day",
            "bars_30m", "bars_15m", "ingest_runs", "shard_manifests",
        })
        for table in ("bars_day", "bars_30m", "bars_15m"):
            index_sql = " ".join(
                row[0] or ""
                for row in self.store.connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
                    (table,),
                )
            )
            self.assertIn("ts, instrument_id", index_sql)

    def test_instrument_identity_includes_asset_type_exchange_and_code(self):
        stock = self.store.upsert_instrument("stock", "SZ", "000001", name="平安银行")
        index = self.store.upsert_instrument("index", "SH", "000001", name="上证指数")
        same_stock = self.store.upsert_instrument("stock", "SZ", "000001", name="平安银行A")

        self.assertNotEqual(stock, index)
        self.assertEqual(stock, same_stock)
        self.assertEqual(
            self.store.resolve_instrument("stock", "SZ", "000001")["name"],
            "平安银行A",
        )

    def test_bar_upsert_is_idempotent_updates_same_key_and_never_downgrades_final(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        self.store.upsert_bars("day", instrument_id, [_bar("2026-07-01", 10.0, False)])
        self.store.upsert_bars("day", instrument_id, [_bar("2026-07-01", 11.0, True)])
        self.store.upsert_bars("day", instrument_id, [_bar("2026-07-01", 9.0, False)])

        rows = self.store.query_bars("day", instrument_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 11.0)
        self.assertEqual(rows[0]["is_final"], 1)

        final_update = _bar("2026-07-01", 11.5, True)
        self.store.upsert_bars("day", instrument_id, [final_update])
        self.assertEqual(self.store.query_bars("day", instrument_id)[0]["close"], 11.5)

    def test_adjustment_is_canonical_per_bar_table(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        self.store.upsert_bars("day", instrument_id, [_bar("2026-07-01", adjustment="qfq")])
        other = self.store.upsert_instrument("stock", "SH", "600001")

        with self.assertRaisesRegex(ValueError, "adjustment"):
            self.store.upsert_bars("day", other, [_bar("2026-07-01", adjustment="raw")])

        self.store.upsert_bars("30m", instrument_id, [_bar("2026-07-01T10:00:00", adjustment="raw")])
        self.assertEqual(self.store.get_canonical_adjustment("day"), "qfq")
        self.assertEqual(self.store.get_canonical_adjustment("30m"), "raw")

        second_writer = MarketHistoryStore(self.db_path)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "adjustment"):
                second_writer.connection.execute(
                    """
                    INSERT INTO bars_day(
                        instrument_id, ts, open, high, low, close, volume, amount,
                        adjustment, is_final, source_batch, ingest_run_id, updated_at
                    ) VALUES (?, ?, 10, 11, 9, 10, 1, 1, 'raw', 1, '', NULL, 'now')
                    """,
                    (instrument_id, "2026-07-02"),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "adjustment"):
                second_writer.connection.execute(
                    "UPDATE bars_day SET adjustment='raw' WHERE instrument_id=?",
                    (instrument_id,),
                )
        finally:
            second_writer.close()

    def test_rejects_invalid_ohlc_nonfinite_and_negative_volume_amount(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        invalid = []
        bad_high = _bar("2026-07-01")
        bad_high["high"] = 9.0
        invalid.append(bad_high)
        bad_low = _bar("2026-07-02")
        bad_low["low"] = 11.0
        invalid.append(bad_low)
        bad_nan = _bar("2026-07-03")
        bad_nan["close"] = math.nan
        invalid.append(bad_nan)
        bad_zero = _bar("2026-07-03-zero")
        bad_zero["open"] = 0
        invalid.append(bad_zero)
        bad_pos_inf = _bar("2026-07-03-pos-inf")
        bad_pos_inf["high"] = math.inf
        invalid.append(bad_pos_inf)
        bad_neg_inf = _bar("2026-07-03-neg-inf")
        bad_neg_inf["low"] = -math.inf
        invalid.append(bad_neg_inf)
        bad_volume = _bar("2026-07-04")
        bad_volume["volume"] = -1
        invalid.append(bad_volume)
        bad_amount = _bar("2026-07-05")
        bad_amount["amount"] = -1
        invalid.append(bad_amount)

        for bar in invalid:
            with self.subTest(ts=bar["ts"]), self.assertRaises(ValueError):
                self.store.upsert_bars("day", instrument_id, [bar])
        self.assertEqual(self.store.query_bars("day", instrument_id), [])

    def test_window_many_cross_section_and_as_of_are_hard_bounded(self):
        first = self.store.upsert_instrument("stock", "SH", "600000")
        second = self.store.upsert_instrument("stock", "SZ", "000001")
        for instrument_id, offset in ((first, 0), (second, 10)):
            self.store.upsert_bars("day", instrument_id, [
                _bar("2026-06-30", 10 + offset),
                _bar("2026-07-01", 11 + offset),
                _bar("2026-07-02", 12 + offset),
            ])

        window = self.store.query_bars(
            "day", first, start="2026-06-30", end="2026-07-02", as_of="2026-07-01"
        )
        self.assertEqual([row["ts"] for row in window], ["2026-06-30", "2026-07-01"])
        statements = []
        def trace(statement):
            statements.append(statement)
        self.store.connection.set_trace_callback(trace)
        many = self.store.query_bars_many(
            "day", [first, second], as_of="2026-07-01", limit=1
        )
        self.store.connection.set_trace_callback(None)
        self.assertEqual(set(many), {first, second})
        self.assertTrue(all([row["ts"] for row in rows] == ["2026-07-01"] for rows in many.values()))
        bar_selects = [
            sql for sql in statements
            if sql.lstrip().upper().startswith("SELECT") and "BARS_DAY" in sql.upper()
        ]
        self.assertEqual(len(bar_selects), 1, bar_selects)
        section = self.store.query_cross_section("day", "2026-07-01", as_of="2026-07-01")
        self.assertEqual([row["instrument_id"] for row in section], sorted([first, second]))
        self.assertEqual(
            self.store.query_cross_section("day", "2026-07-02", as_of="2026-07-01"),
            [],
        )

    def test_stock_meta_calendar_ingest_and_manifest_upsert(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        self.store.upsert_stock_meta(instrument_id, "2026-07-01", {"name": "浦发银行", "listed_days": 5000})
        self.store.upsert_stock_meta(instrument_id, "2026-07-01", {"name": "浦发", "listed_days": 5001})
        self.store.upsert_trade_calendar("SH", "2026-07-01", True)
        self.store.upsert_trade_calendar("SH", "2026-07-01", False)
        self.store.start_ingest_run(
            "run-1", "backfill", started_at="2026-07-01T01:00:00Z", metadata={"attempt": 1}
        )
        self.store.finish_ingest_run(
            "run-1", "complete", finished_at="2026-07-01T02:00:00Z", rows_written=3
        )
        self.store.start_ingest_run(
            "run-1", "backfill", started_at="2026-07-01T03:00:00Z", metadata={"attempt": 2}
        )
        self.store.upsert_shard_manifest(
            "run-1", 0, 20, "complete", row_count=3, checksum="abc", metadata={"host": "s0"}
        )
        self.store.upsert_shard_manifest(
            "run-1", 0, 20, "complete", row_count=4, checksum="def", metadata={"host": "s1"}
        )

        meta = self.store.query_stock_meta(instrument_id, as_of="2026-07-01")
        self.assertEqual(meta["name"], "浦发")
        self.assertFalse(self.store.is_trading_day("SH", "2026-07-01"))
        run = self.store.get_ingest_run("run-1")
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["started_at"], "2026-07-01T03:00:00Z")
        self.assertIsNone(run["finished_at"])
        self.assertEqual(run["rows_written"], 0)
        self.assertEqual(run["metadata"], {"attempt": 2})
        manifest = self.store.list_shard_manifests("run-1")[0]
        self.assertEqual(manifest["checksum"], "def")
        self.assertEqual(manifest["metadata"], {"host": "s1"})

    def test_is_final_accepts_only_bool_or_integer_zero_one(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        valid_missing = _bar("2026-07-01")
        valid_missing.pop("is_final")
        self.assertEqual(self.store.upsert_bars("day", instrument_id, [valid_missing]), 1)
        for index, value in enumerate((None, "false", "0", 2, -1, 1.0)):
            with self.subTest(value=value):
                bar = _bar("2026-07-{:02d}".format(index + 2))
                bar["is_final"] = value
                with self.assertRaisesRegex(ValueError, "is_final"):
                    self.store.upsert_bars("day", instrument_id, [bar])

    def test_upsert_returns_actual_changes_and_round_trips_batch_metadata(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        bar = _bar("2026-07-01", 10.0, True)
        bar["source_batch"] = "source-42"
        bar["ingest_run_id"] = "run-42"
        self.assertEqual(self.store.upsert_bars("day", instrument_id, [bar]), 1)
        self.assertEqual(self.store.upsert_bars("day", instrument_id, [bar]), 0)
        nonfinal = dict(bar)
        nonfinal["close"] = 10.1
        nonfinal["is_final"] = False
        self.assertEqual(self.store.upsert_bars("day", instrument_id, [nonfinal]), 0)
        row = self.store.query_bars("day", instrument_id)[0]
        self.assertEqual(row["source_batch"], "source-42")
        self.assertEqual(row["ingest_run_id"], "run-42")

    def test_readonly_and_immutable_open_support_reads_and_reject_writes(self):
        instrument_id = self.store.upsert_instrument("stock", "SH", "600000")
        self.store.upsert_bars("day", instrument_id, [_bar("2026-07-01")])
        self.store.close()

        readonly = MarketHistoryStore(self.db_path, readonly=True, immutable=True)
        try:
            self.assertEqual(len(readonly.query_bars("day", instrument_id)), 1)
            with self.assertRaises((sqlite3.OperationalError, PermissionError)):
                readonly.upsert_instrument("stock", "SH", "600001")
        finally:
            readonly.close()
        self.store = MarketHistoryStore(self.db_path)

    def test_staging_database_merge_is_idempotent_and_preserves_final(self):
        self.store.upsert_instrument("stock", "SZ", "000001", name="目标库占位")
        self.store.upsert_instrument("stock", "SZ", "000002", name="目标库占位2")
        staging_path = Path(self.tmp.name) / "staging.sqlite"
        staging = MarketHistoryStore(staging_path)
        try:
            staging.upsert_instrument("stock", "SZ", "300001", name="分片库占位")
            sid = staging.upsert_instrument("stock", "SH", "600000", name="浦发银行")
            staging.upsert_bars("day", sid, [_bar("2026-07-01", 12.0, True)])
            staging.start_ingest_run("run-stage", "backfill")
            staging.finish_ingest_run("run-stage", "complete", rows_written=1)
            staging.upsert_shard_manifest("run-stage", 0, 1, "complete", row_count=1)
        finally:
            staging.close()

        first_merge = self.store.merge_staging_database(staging_path)
        second_merge = self.store.merge_staging_database(staging_path)
        iid = self.store.resolve_instrument("stock", "SH", "600000")["instrument_id"]
        self.assertNotEqual(iid, sid)
        self.assertEqual(len(self.store.query_bars("day", iid)), 1)
        self.assertEqual(self.store.query_bars("day", iid)[0]["close"], 12.0)
        self.assertEqual(len(self.store.list_shard_manifests("run-stage")), 1)
        self.assertEqual(first_merge["bars"], 1)
        self.assertEqual(second_merge["bars"], 0)

        lower_path = Path(self.tmp.name) / "lower.sqlite"
        lower = MarketHistoryStore(lower_path)
        try:
            lower_id = lower.upsert_instrument("stock", "SH", "600000")
            lower.upsert_bars("day", lower_id, [_bar("2026-07-01", 8.0, False)])
        finally:
            lower.close()
        self.store.merge_staging_database(lower_path)
        self.assertEqual(self.store.query_bars("day", iid)[0]["close"], 12.0)

    def test_running_ingest_run_survives_staging_merge_as_running(self):
        staging_path = Path(self.tmp.name) / "running.sqlite"
        staging = MarketHistoryStore(staging_path)
        try:
            staging.start_ingest_run(
                "run-live", "backfill", started_at="2026-07-01T01:00:00Z",
                metadata={"state": "live"},
            )
        finally:
            staging.close()
        self.store.merge_staging_database(staging_path)
        run = self.store.get_ingest_run("run-live")
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["metadata"], {"state": "live"})

    def test_failed_ingest_run_restart_resets_completion_fields(self):
        self.store.start_ingest_run("run-failed", "backfill", started_at="t1")
        self.store.finish_ingest_run(
            "run-failed", "failed", finished_at="t2", rows_written=7
        )
        self.store.start_ingest_run(
            "run-failed", "backfill", started_at="t3", metadata={"retry": True}
        )
        run = self.store.get_ingest_run("run-failed")
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["started_at"], "t3")
        self.assertIsNone(run["finished_at"])
        self.assertEqual(run["rows_written"], 0)
        self.assertEqual(run["metadata"], {"retry": True})

    def test_staging_merge_rolls_back_all_rows_on_canonical_adjustment_conflict(self):
        target_id = self.store.upsert_instrument("stock", "SH", "600000")
        self.store.upsert_bars("day", target_id, [_bar("2026-07-01", adjustment="qfq")])
        staging_path = Path(self.tmp.name) / "conflict.sqlite"
        staging = MarketHistoryStore(staging_path)
        try:
            staging_id = staging.upsert_instrument("stock", "SH", "600999")
            staging.upsert_bars(
                "day", staging_id, [_bar("2026-07-01", adjustment="raw")]
            )
        finally:
            staging.close()

        with self.assertRaisesRegex(ValueError, "adjustment"):
            self.store.merge_staging_database(staging_path)

        self.assertIsNone(self.store.resolve_instrument("stock", "SH", "600999"))


if __name__ == "__main__":
    unittest.main()
