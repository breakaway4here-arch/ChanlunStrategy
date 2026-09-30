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

    def test_missing_previous_trading_day_never_scales_from_older_close(self):
        # Frozen 9/29 case: 9/24 qfq close 16.05 is not the 9/28 close
        # represented by the 9/29 Sina quote's prev_close=15.98.
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-24", "open": 16.02, "high": 16.11,
                "low": 15.94, "close": 16.05, "volume": 100,
                "amount": 160000, "adjustment": "qfq", "is_final": True,
            }])
        quote = _row("600062", "SH")
        quote.update(
            open=15.90, high=16.08, low=15.86, current_price=15.92,
            prev_close=15.98, volume=37976.88, amount=60530546.0,
            quote_source="sina", quote_asof="2026-09-29T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY", volume_raw_unit="shares",
        )
        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-29",
            fetch_all_a_stocks=lambda **_kwargs: (
                [quote], {"complete": True, "requested": 1, "unique": 1},
            ),
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "insufficient_coverage")
        self.assertEqual(result["skipped_missing_factor"], 1)
        with MarketHistoryStore(self.path, readonly=True) as store:
            current = store.connection.execute(
                "SELECT COUNT(*) FROM bars_day WHERE ts='2026-09-29'"
            ).fetchone()[0]
        self.assertEqual(current, 0)

    def test_exact_previous_trading_day_uses_that_close_not_older_history(self):
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            for date, close in (("2026-09-24", 16.05), ("2026-09-28", 15.98)):
                store.upsert_bars("day", instrument_id, [{
                    "ts": date, "open": close, "high": close,
                    "low": close, "close": close, "volume": 100,
                    "amount": 100000, "adjustment": "qfq", "is_final": True,
                }])
        quote = _row("600062", "SH")
        quote.update(
            open=15.90, high=16.08, low=15.86, current_price=15.92,
            prev_close=15.98, volume=37976.88, amount=60530546.0,
            quote_source="sina", quote_asof="2026-09-29T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY", volume_raw_unit="shares",
        )
        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-29",
            fetch_all_a_stocks=lambda **_kwargs: (
                [quote], {"complete": True, "requested": 1, "unique": 1},
            ),
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["previous_trade_date"], "2026-09-28")
        with MarketHistoryStore(self.path, readonly=True) as store:
            current = store.connection.execute(
                "SELECT open, high, low, close, volume, amount, "
                "volume_raw_unit, source_batch FROM bars_day WHERE ts='2026-09-29'"
            ).fetchone()
        self.assertEqual(tuple(current), (
            15.90, 16.08, 15.86, 15.92, 37976.88, 60530546.0,
            "shares", "official_close_snapshot:sina",
        ))

    def test_unknown_calendar_year_does_not_treat_unknown_weekdays_as_holidays(self):
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-12-31", "open": 10, "high": 10,
                "low": 10, "close": 10, "volume": 100,
                "amount": 100000, "adjustment": "qfq", "is_final": True,
            }])
        result = ingest_market_close_snapshot(
            self.path,
            "2027-01-05",
            fetch_all_a_stocks=lambda **_kwargs: (
                [_row("600062", "SH")],
                {"complete": True, "requested": 1, "unique": 1},
            ),
            generated_at=datetime(
                2027, 1, 5, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "insufficient_coverage")
        self.assertEqual(result["previous_trade_date"], "")
        with MarketHistoryStore(self.path, readonly=True) as store:
            current = store.connection.execute(
                "SELECT COUNT(*) FROM bars_day WHERE ts='2027-01-05'"
            ).fetchone()[0]
        self.assertEqual(current, 0)

    def test_known_holiday_gap_keeps_exact_previous_trading_day(self):
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-24", "open": 16.02, "high": 16.11,
                "low": 15.94, "close": 16.05, "volume": 100,
                "amount": 160000, "adjustment": "qfq", "is_final": True,
            }])
        quote = _row("600062", "SH")
        quote.update(
            open=16.14, high=16.18, low=15.91, current_price=15.98,
            prev_close=16.05, volume=45135, amount=72000000,
            quote_source="sina", quote_asof="2026-09-28T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY",
        )
        result = ingest_market_close_snapshot(
            self.path,
            "2026-09-28",
            fetch_all_a_stocks=lambda **_kwargs: (
                [quote], {"complete": True, "requested": 1, "unique": 1},
            ),
            generated_at=datetime(
                2026, 9, 28, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["previous_trade_date"], "2026-09-24")
        self.assertEqual(result["status"], "complete")
        with MarketHistoryStore(self.path, readonly=True) as store:
            close = store.connection.execute(
                "SELECT close FROM bars_day WHERE ts='2026-09-28'"
            ).fetchone()[0]
        self.assertEqual(close, 15.98)

    def test_explicit_future_calendar_can_supply_previous_trading_day(self):
        with MarketHistoryStore(self.path) as store:
            for exchange in ("SH", "SZ"):
                store.upsert_trade_calendar(exchange, "2027-01-04", True)
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2027-01-04", "open": 10, "high": 10,
                "low": 10, "close": 10, "volume": 100,
                "amount": 100000, "adjustment": "qfq", "is_final": True,
            }])
        result = ingest_market_close_snapshot(
            self.path,
            "2027-01-05",
            fetch_all_a_stocks=lambda **_kwargs: (
                [_row("600062", "SH")],
                {"complete": True, "requested": 1, "unique": 1},
            ),
            generated_at=datetime(
                2027, 1, 5, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["previous_trade_date"], "2027-01-04")
        self.assertEqual(result["status"], "complete")

    def test_cached_final_snapshot_is_rechecked_after_prior_day_is_restored(self):
        quote = _row("600062", "SH")
        quote.update(
            open=15.90, high=16.08, low=15.86, current_price=15.92,
            prev_close=15.98, volume=37976.88, amount=60530546.0,
            quote_source="sina", quote_asof="2026-09-29T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY", volume_raw_unit="shares",
        )
        stale_factor = 16.05 / 15.98
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            for date, close in (("2026-09-24", 16.05), ("2026-09-28", 15.98)):
                store.upsert_bars("day", instrument_id, [{
                    "ts": date, "open": close, "high": close,
                    "low": close, "close": close, "volume": 100,
                    "amount": 100000, "adjustment": "qfq", "is_final": True,
                }])
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-29", "open": 15.90 * stale_factor,
                "high": 16.08 * stale_factor, "low": 15.86 * stale_factor,
                "close": 15.92 * stale_factor, "volume": 37976.88,
                "amount": 60530546.0, "adjustment": "qfq", "is_final": True,
                "source_batch": "official_close_snapshot:sina",
            }])
        calls = []

        def frozen_quotes(**_kwargs):
            calls.append(True)
            return [quote], {"complete": True, "requested": 1, "unique": 1}

        result = ingest_market_close_snapshot(
            self.path, "2026-09-29", frozen_quotes,
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(calls, [True])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["previous_trade_date"], "2026-09-28")
        with MarketHistoryStore(self.path, readonly=True) as store:
            close = store.connection.execute(
                "SELECT close FROM bars_day WHERE ts='2026-09-29'"
            ).fetchone()[0]
        self.assertEqual(close, 15.92)
        again = ingest_market_close_snapshot(
            self.path, "2026-09-29", frozen_quotes,
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(calls, [True, True])
        self.assertTrue(again["rechecked_cached_snapshot"])
        self.assertEqual(again["written"], 0)

    def test_cached_final_snapshot_without_exact_prior_day_cannot_fast_pass(self):
        with MarketHistoryStore(self.path) as store:
            instrument_id = store.upsert_instrument("stock", "SH", "600062")
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-24", "open": 16.05, "high": 16.05,
                "low": 16.05, "close": 16.05, "volume": 100,
                "amount": 100000, "adjustment": "qfq", "is_final": True,
            }])
            store.upsert_bars("day", instrument_id, [{
                "ts": "2026-09-29", "open": 15.9696495619524,
                "high": 16.1504380475594, "low": 15.9294743429287,
                "close": 15.9897371714643, "volume": 37976.88,
                "amount": 60530546.0, "adjustment": "qfq", "is_final": True,
                "source_batch": "official_close_snapshot:sina",
            }])
        quote = _row("600062", "SH")
        quote.update(
            open=15.90, high=16.08, low=15.86, current_price=15.92,
            prev_close=15.98, volume=37976.88, amount=60530546.0,
            quote_source="sina", quote_asof="2026-09-29T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY",
        )
        result = ingest_market_close_snapshot(
            self.path, "2026-09-29",
            fetch_all_a_stocks=lambda **_kwargs: (
                [quote], {"complete": True, "requested": 1, "unique": 1},
            ),
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["reason"], "cached_snapshot_unverified")
        self.assertTrue(result["rechecked_cached_snapshot"])
        self.assertEqual(result["skipped_missing_factor"], 1)
        self.assertEqual(result["written"], 0)

    def test_rechecking_snapshot_preserves_independent_current_qfq_bar(self):
        with MarketHistoryStore(self.path) as store:
            snapshot_id = store.upsert_instrument("stock", "SH", "600062")
            direct_id = store.upsert_instrument("stock", "SZ", "000001")
            kpl_id = store.upsert_instrument("stock", "SZ", "000002")
            for instrument_id, close in (
                (snapshot_id, 15.98), (direct_id, 10.0), (kpl_id, 8.0)
            ):
                store.upsert_bars("day", instrument_id, [{
                    "ts": "2026-09-28", "open": close, "high": close,
                    "low": close, "close": close, "volume": 100,
                    "amount": 100000, "adjustment": "qfq", "is_final": True,
                }])
            store.upsert_bars("day", snapshot_id, [{
                "ts": "2026-09-29", "open": 15.9696495619524,
                "high": 16.1504380475594, "low": 15.9294743429287,
                "close": 15.9897371714643, "volume": 37976.88,
                "amount": 60530546.0, "adjustment": "qfq", "is_final": True,
                "source_batch": "official_close_snapshot:sina",
            }])
            store.upsert_bars("day", direct_id, [{
                "ts": "2026-09-29", "open": 10, "high": 10.3,
                "low": 9.9, "close": 10.2, "volume": 12345,
                "amount": 12600000, "adjustment": "qfq", "is_final": True,
                "source_batch": "ongoing:tencent",
            }])
            store.upsert_bars("day", kpl_id, [{
                "ts": "2026-09-29", "open": 8, "high": 8.2,
                "low": 7.9, "close": 8.1, "volume": 10000,
                "amount": 8100000, "adjustment": "qfq", "is_final": True,
                "source_batch": "ongoing:kaipanla",
            }])
        quote = _row("600062", "SH")
        quote.update(
            open=15.90, high=16.08, low=15.86, current_price=15.92,
            prev_close=15.98, volume=37976.88, amount=60530546.0,
            quote_source="sina", quote_asof="2026-09-29T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY",
        )
        rows = [quote, _row("000001", "SZ"), _row("000002", "SZ")]
        result = ingest_market_close_snapshot(
            self.path, "2026-09-29",
            fetch_all_a_stocks=lambda **_kwargs: (
                rows, {"complete": True, "requested": 3, "unique": 3},
            ),
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["coverage_numerator"], 3)
        self.assertEqual(result["quote_sources"], {"sina": 1})
        self.assertEqual(result["quote_identity_keys"], ["stock|SH|600062"])
        self.assertEqual(result["preserved_independent_final_count"], 2)
        self.assertEqual(result["preserved_independent_final_rows"], [{
            "identity_key": "stock|SZ|000001",
            "asset_type": "stock", "exchange": "SZ", "code": "000001",
            "date": "2026-09-29", "source_batch": "ongoing:tencent",
            "adjustment": "qfq", "is_final": True,
        }, {
            "identity_key": "stock|SZ|000002",
            "asset_type": "stock", "exchange": "SZ", "code": "000002",
            "date": "2026-09-29", "source_batch": "ongoing:kaipanla",
            "adjustment": "qfq", "is_final": True,
        }])
        with MarketHistoryStore(self.path, readonly=True) as store:
            values = store.connection.execute(
                "SELECT i.code, b.close, b.source_batch FROM bars_day b "
                "JOIN instruments i ON i.instrument_id=b.instrument_id "
                "WHERE b.ts='2026-09-29' ORDER BY i.code"
            ).fetchall()
        self.assertEqual([tuple(row) for row in values], [
            ("000001", 10.2, "ongoing:tencent"),
            ("000002", 8.1, "ongoing:kaipanla"),
            ("600062", 15.92, "official_close_snapshot:sina"),
        ])

    def test_one_unverified_cached_snapshot_cannot_hide_behind_healthy_coverage(self):
        rows = [_row("600%03d" % index, "SH") for index in range(9)]
        bad_quote = _row("600062", "SH")
        bad_quote.update(
            open=15.90, high=16.08, low=15.86, current_price=15.92,
            prev_close=15.98, volume=37976.88, amount=60530546.0,
            quote_source="sina", quote_asof="2026-09-29T15:00:00+08:00",
            volume_unit="hands", amount_unit="CNY",
        )
        rows.append(bad_quote)
        with MarketHistoryStore(self.path) as store:
            for row in rows[:9]:
                instrument_id = store.upsert_instrument("stock", "SH", row["code"])
                store.upsert_bars("day", instrument_id, [{
                    "ts": "2026-09-29", "open": 10, "high": 10.3,
                    "low": 9.9, "close": 10.2, "volume": 12345,
                    "amount": 12600000, "adjustment": "qfq", "is_final": True,
                    "source_batch": "ongoing:tencent",
                }])
            bad_id = store.upsert_instrument("stock", "SH", "600062")
            store.upsert_bars("day", bad_id, [{
                "ts": "2026-09-24", "open": 16.05, "high": 16.05,
                "low": 16.05, "close": 16.05, "volume": 100,
                "amount": 100000, "adjustment": "qfq", "is_final": True,
            }])
            store.upsert_bars("day", bad_id, [{
                "ts": "2026-09-29", "open": 15.9696495619524,
                "high": 16.1504380475594, "low": 15.9294743429287,
                "close": 15.9897371714643, "volume": 37976.88,
                "amount": 60530546.0, "adjustment": "qfq", "is_final": True,
                "source_batch": "official_close_snapshot:sina",
            }])
        result = ingest_market_close_snapshot(
            self.path, "2026-09-29",
            fetch_all_a_stocks=lambda **_kwargs: (
                rows, {"complete": True, "requested": 10, "unique": 10},
            ),
            generated_at=datetime(
                2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8))
            ),
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["reason"], "cached_snapshot_unverified")
        self.assertEqual(result["cached_snapshot_unverified_count"], 1)
        self.assertEqual(result["coverage_numerator"], 9)
        self.assertEqual(result["coverage_denominator"], 10)
        self.assertEqual(result["valid_bar_count"], 9)
        self.assertEqual(result["written"], 0)

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
                "source_batch": "ongoing:tencent",
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
