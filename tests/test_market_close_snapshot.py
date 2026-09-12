import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from chanlun.market_close_snapshot import ingest_market_close_snapshot
from chanlun.market_history_store import MarketHistoryStore


def _row(code="600000", exchange="SH"):
    return {
        "code": code,
        "exchange": exchange,
        "name": "测试股",
        "industry": "银行",
        "listed_date": "19991110",
        "current_price": 10.2,
        "open": 10.0,
        "high": 10.3,
        "low": 9.9,
        "prev_close": 10.0,
        "volume": 12345,
        "amount": 12600000,
    }


def _insert_legacy_stock_with_bar(store, code, exchange="SZ"):
    """Seed a pre-contract contradictory identity for migration tests only."""
    store.connection.execute(
        """
        INSERT OR IGNORE INTO bar_table_settings(table_name, adjustment, updated_at)
        VALUES ('bars_day', 'qfq', '2026-09-11T00:00:00Z')
        """
    )
    cursor = store.connection.execute(
        """
        INSERT INTO instruments(asset_type, exchange, code, name, updated_at)
        VALUES ('stock', ?, ?, '旧身份', '2026-09-11T00:00:00Z')
        """,
        (exchange, code),
    )
    instrument_id = cursor.lastrowid
    store.connection.execute(
        """
        INSERT INTO bars_day(
            instrument_id, ts, open, high, low, close, volume, amount,
            volume_unit, volume_raw_unit, volume_source,
            amount_unit, amount_source, amount_available,
            adjustment, is_final, source_batch, ingest_run_id, updated_at
        ) VALUES (?, '2026-09-10', 10, 10.2, 9.8, 10, 100, 1000,
                  'hands', 'hands', 'fixture', 'CNY', 'fixture', 1,
                  'qfq', 1, 'fixture', NULL, '2026-09-11T00:00:00Z')
        """,
        (instrument_id,),
    )
    store.connection.commit()
    return instrument_id


class MarketCloseSnapshotTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_complete_snapshot_is_written_as_final_in_one_database(self):
        rows = [_row("600000", "SH"), _row("000001", "SZ")]
        with MarketHistoryStore(self.path) as store:
            for row in rows:
                instrument_id = store.upsert_instrument(
                    "stock", row["exchange"], row["code"], name=row["name"]
                )
                store.upsert_bars("day", instrument_id, [{
                    "ts": "2026-07-16",
                    "open": 5.0,
                    "high": 5.1,
                    "low": 4.9,
                    "close": 5.0,
                    "volume": 100,
                    "amount": 50000,
                    "adjustment": "qfq",
                    "is_final": True,
                }])

        result = ingest_market_close_snapshot(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda **_kwargs: (
                rows,
                {"complete": True, "requested": 2, "unique": 2},
            ),
            min_coverage=0.9,
            generated_at=datetime(
                2026, 7, 17, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["valid_bar_count"], 2)
        with MarketHistoryStore(self.path, readonly=True) as store:
            record = store.connection.execute(
                """
                SELECT b.ts, b.is_final, b.source_batch, b.close
                FROM bars_day b
                JOIN instruments i ON i.instrument_id=b.instrument_id
                WHERE i.code='600000'
                ORDER BY b.ts DESC
                LIMIT 1
                """
            ).fetchone()
        self.assertEqual(record["ts"], "2026-07-17")
        self.assertEqual(record["is_final"], 1)
        self.assertEqual(
            record["source_batch"], "official_close_snapshot:eastmoney"
        )
        # Yesterday's qfq close is half the raw previous close, so today's raw
        # OHLC must be converted by the same factor before entering bars_day.
        self.assertEqual(record["close"], 5.1)

    def test_incomplete_universe_fails_closed_without_writes(self):
        result = ingest_market_close_snapshot(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda **_kwargs: (
                [_row()],
                {"complete": False, "requested": 2, "unique": 1},
            ),
            generated_at=datetime(
                2026, 7, 17, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "incomplete")
        with MarketHistoryStore(self.path) as store:
            count = store.connection.execute(
                "SELECT COUNT(*) FROM bars_day"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_low_valid_quote_coverage_fails_closed(self):
        invalid = dict(_row("000001", "SZ"), current_price=None)
        with MarketHistoryStore(self.path) as store:
            for exchange, code in (("SH", "600000"), ("SZ", "000001")):
                instrument_id = store.upsert_instrument(
                    "stock", exchange, code, name="测试股"
                )
                store.upsert_bars("day", instrument_id, [{
                    "ts": "2026-07-16", "open": 10, "high": 10, "low": 10,
                    "close": 10, "volume": 1, "amount": 1000,
                    "adjustment": "qfq", "is_final": True,
                }])
        result = ingest_market_close_snapshot(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda **_kwargs: (
                [_row(), invalid],
                {"complete": True, "requested": 2, "unique": 2},
            ),
            min_coverage=0.9,
            generated_at=datetime(
                2026, 7, 17, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "insufficient_coverage")
        with MarketHistoryStore(self.path, readonly=True) as store:
            count = store.connection.execute(
                "SELECT COUNT(*) FROM bars_day WHERE ts='2026-07-17'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_before_close_never_fetches_or_writes(self):
        calls = []
        result = ingest_market_close_snapshot(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda **_kwargs: calls.append(True),
            generated_at=datetime(
                2026, 7, 17, 14, 59, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "not_closed")
        self.assertEqual(calls, [])

    def test_existing_final_snapshot_uses_db_without_remote_call(self):
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument(
                "stock", "SH", "600000", name="测试股"
            )
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-07-17", "open": 10, "high": 10, "low": 10,
                "close": 10, "volume": 1, "amount": 1000,
                "adjustment": "qfq", "is_final": True,
            }])
        calls = []
        result = ingest_market_close_snapshot(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda **_kwargs: calls.append(True),
            generated_at=datetime(
                2026, 7, 17, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["source"], "db")
        self.assertEqual(result["remote_calls"], 0)
        self.assertEqual(calls, [])

    def test_legacy_bj_rows_stay_in_denominator_and_block_below_total_floor(self):
        valid = _row("600000", "SH")
        legacy_codes = ("920000", "920001", "920002")
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600000")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-10", "open": 10, "high": 10.2, "low": 9.8,
                "close": 10, "volume": 100, "amount": 1000,
                "adjustment": "qfq", "is_final": True,
            }])
            for code in legacy_codes:
                _insert_legacy_stock_with_bar(store, code)

        bj_rows = [_row(code, "BJ") for code in legacy_codes]
        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-11",
            fetch_all_a_stocks=lambda **_kwargs: (
                [valid] + bj_rows,
                {"complete": True, "requested": 4, "unique": 4},
            ),
            min_coverage=0.9,
            generated_at=datetime(
                2026, 9, 11, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "insufficient_coverage")
        self.assertEqual(result["reason"], "valid_bar_coverage_below_floor")
        self.assertEqual(result["identity_pending_rows"], 3)
        self.assertEqual(result["identity_invalid_rows"], 0)
        self.assertEqual(result["history_eligible_rows"], 1)
        self.assertEqual(result["valid_bar_count"], 1)
        self.assertEqual(result["skipped_missing_factor"], 3)
        self.assertEqual(result["eligible_coverage"], 1.0)
        self.assertEqual(result["coverage"], 0.25)
        with MarketHistoryStore(self.path, readonly=True) as store:
            current = store.connection.execute(
                "SELECT COUNT(*) FROM bars_day WHERE ts='2026-09-11'"
            ).fetchone()[0]
        # Below the total-market floor the otherwise valid peer is diagnosed
        # but the batch remains atomic and writes no current-day rows.
        self.assertEqual(current, 0)

    def test_isolated_legacy_identity_above_total_floor_is_partial(self):
        rows = [_row("600%03d" % index, "SH") for index in range(11)]
        with MarketHistoryStore(self.path) as store:
            for row in rows:
                instrument_id = store.upsert_instrument(
                    "stock", "SH", row["code"], name=row["name"]
                )
                store.upsert_bars("day", instrument_id, [{
                    "ts": "2026-09-10", "open": 10, "high": 10.2,
                    "low": 9.8, "close": 10, "volume": 100,
                    "amount": 1000, "adjustment": "qfq", "is_final": True,
                }])
            _insert_legacy_stock_with_bar(store, "920001")

        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-11",
            fetch_all_a_stocks=lambda **_kwargs: (
                rows + [_row("920001", "BJ")],
                {"complete": True, "requested": 12, "unique": 12},
            ),
            min_coverage=0.9,
            generated_at=datetime(
                2026, 9, 11, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reason"], "identity_migration_pending")
        self.assertEqual(result["valid_bar_count"], 11)
        self.assertEqual(result["coverage"], 0.916667)
        self.assertEqual(result["coverage_numerator"], 11)
        self.assertEqual(result["coverage_denominator"], 12)
        self.assertTrue(result["meets_minimum_coverage"])
        self.assertEqual(result["identity_pending_codes"], ["920001"])
        with MarketHistoryStore(self.path, readonly=True) as store:
            legacy_current = store.connection.execute(
                """
                SELECT COUNT(*)
                FROM bars_day b
                JOIN instruments i ON i.instrument_id=b.instrument_id
                WHERE i.exchange='SZ' AND i.code='920001'
                  AND b.ts='2026-09-11'
                """
            ).fetchone()[0]
        self.assertEqual(legacy_current, 0)

    def test_partial_db_fast_path_does_not_repeat_remote_request(self):
        with MarketHistoryStore(self.path) as store:
            for index in range(11):
                code = "600%03d" % index
                instrument_id = store.upsert_instrument("stock", "SH", code)
                store.upsert_bars("day", instrument_id, [{
                    "ts": "2026-09-11", "open": 10, "high": 10.2,
                    "low": 9.8, "close": 10, "volume": 100,
                    "amount": 1000, "adjustment": "qfq", "is_final": True,
                }])
            _insert_legacy_stock_with_bar(store, "920001")

        calls = []
        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-11",
            fetch_all_a_stocks=lambda **_kwargs: calls.append(True),
            min_coverage=0.9,
            generated_at=datetime(
                2026, 9, 11, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["source"], "db")
        self.assertEqual(result["coverage"], 0.916667)
        self.assertEqual(result["remote_calls"], 0)
        self.assertEqual(calls, [])

    def test_provider_identity_incompleteness_blocks_without_writes(self):
        valid = _row("600000", "SH")
        invalid = _row("920001", "SZ")
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600000")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-10", "open": 10, "high": 10.2,
                "low": 9.8, "close": 10, "volume": 100,
                "amount": 1000, "adjustment": "qfq", "is_final": True,
            }])

        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-11",
            fetch_all_a_stocks=lambda **_kwargs: (
                [valid, invalid],
                {"complete": True, "requested": 2, "unique": 2},
            ),
            generated_at=datetime(
                2026, 9, 11, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["reason"], "provider_identity_incomplete")
        with MarketHistoryStore(self.path, readonly=True) as store:
            current = store.connection.execute(
                "SELECT COUNT(*) FROM bars_day WHERE ts='2026-09-11'"
            ).fetchone()[0]
        self.assertEqual(current, 0)

    def test_zero_history_factor_rows_return_incomplete_instead_of_dividing(self):
        with MarketHistoryStore(self.path) as store:
            _insert_legacy_stock_with_bar(store, "920000")

        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-11",
            fetch_all_a_stocks=lambda **_kwargs: (
                [_row("920000", "BJ")],
                {"complete": True, "requested": 1, "unique": 1},
            ),
            min_coverage=0.9,
            generated_at=datetime(
                2026, 9, 11, 15, 5, tzinfo=timezone(timedelta(hours=8))
            ),
        )

        self.assertEqual(result["status"], "insufficient_coverage")
        self.assertEqual(result["reason"], "valid_bar_coverage_below_floor")
        self.assertEqual(result["history_eligible_rows"], 0)
        self.assertEqual(result["eligible_coverage"], 0.0)
        self.assertEqual(result["coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
