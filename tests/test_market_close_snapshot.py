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
            instrument_id = store.upsert_instrument(
                "stock", "SH", "600000", name="测试股"
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


if __name__ == "__main__":
    unittest.main()
