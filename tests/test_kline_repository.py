import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from chanlun import data_fetcher
from chanlun.kline_repository import KLineRepository, KLineResult
from chanlun.market_history_store import MarketHistoryStore


def _bar(ts, close=10.0, final=True):
    return {
        "ts": ts,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1000,
        "amount": 10000,
        "adjustment": "qfq",
        "is_final": final,
        "source_batch": "fixture",
    }


def _payload(dates, final=True, source="remote"):
    count = len(dates)
    closes = np.array([10.0 + index for index in range(count)])
    return {
        "dates": dates,
        "opens": closes - 0.1,
        "highs": closes + 0.2,
        "lows": closes - 0.2,
        "closes": closes,
        "volumes": np.ones(count) * 1000,
        "amounts": np.ones(count) * 10000,
        "finals": [final] * count,
        "source": source,
    }


class KLineRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "market.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, code, bars, interval="day"):
        exchange = "SH" if code.startswith(("6", "68")) else "SZ"
        with MarketHistoryStore(self.db_path) as store:
            instrument_id = store.upsert_instrument("stock", exchange, code)
            store.upsert_bars(interval, instrument_id, bars, adjustment="qfq")

    def test_complete_final_local_window_does_not_call_remote(self):
        self.seed(
            "600000",
            [_bar("2026-06-30"), _bar("2026-07-01"), _bar("2026-07-02")],
        )
        calls = []
        repository = KLineRepository(
            self.db_path,
            remote_fetchers={"day": lambda code, count: calls.append((code, count))},
        )

        result = repository.get(
            "day", "600000", count=3, required_date="2026-07-02"
        )

        self.assertEqual(calls, [])
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.kline["dates"][-1], "2026-07-02")
        self.assertEqual(result.kline["source"], "market_history_db")

    def test_missing_fetches_remote_once_persists_and_reuses_database(self):
        calls = []

        def remote(code, count):
            calls.append((code, count))
            return _payload(["2026-06-30", "2026-07-01", "2026-07-02"])

        repository = KLineRepository(
            self.db_path, remote_fetchers={"day": remote}
        )
        first = repository.get(
            "day", "600000", count=3, required_date="2026-07-02"
        )
        second = repository.get(
            "day", "600000", count=3, required_date="2026-07-02"
        )

        self.assertEqual(calls, [("600000", 3)])
        self.assertEqual(first.status, "verified")
        self.assertEqual(second.status, "verified")
        with MarketHistoryStore(self.db_path, readonly=True) as store:
            instrument = store.resolve_instrument("stock", "SH", "600000")
            self.assertEqual(
                len(store.query_bars("day", instrument["instrument_id"])), 3
            )

    def test_stale_or_nonfinal_local_data_fetches_only_overlap_window(self):
        self.seed(
            "600000",
            [
                _bar("2026-06-30"),
                _bar("2026-07-01"),
                _bar("2026-07-02", final=False),
            ],
        )
        calls = []

        def remote(code, count):
            calls.append(count)
            return _payload(["2026-07-01", "2026-07-02"], final=True)

        repository = KLineRepository(
            self.db_path,
            remote_fetchers={"day": remote},
            overlap_counts={"day": 2, "30m": 16, "15m": 32},
        )
        result = repository.get(
            "day", "600000", count=3, required_date="2026-07-02"
        )

        self.assertEqual(calls, [2])
        self.assertEqual(result.status, "verified")
        self.assertEqual(len(result.kline["dates"]), 3)

    def test_ongoing_without_required_date_refreshes_old_local_tail(self):
        self.seed(
            "600000",
            [_bar("2026-06-30"), _bar("2026-07-01")],
        )
        calls = []

        def remote(code, count):
            calls.append(count)
            return _payload(["2026-07-15", "2026-07-16"], final=True)

        repository = KLineRepository(
            self.db_path,
            remote_fetchers={"day": remote},
            overlap_counts={"day": 2, "30m": 16, "15m": 32},
        )
        result = repository.get("day", "600000", count=2)

        self.assertEqual(calls, [2])
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.kline["dates"][-1], "2026-07-16")

    def test_remote_failure_returns_stale_local_status_in_ongoing_mode(self):
        self.seed("600000", [_bar("2026-06-30"), _bar("2026-07-01")])
        repository = KLineRepository(
            self.db_path, remote_fetchers={"day": lambda code, count: None}
        )

        result = repository.get(
            "day", "600000", count=2, required_date="2026-07-02"
        )

        self.assertEqual(result.status, "stale_cache")
        self.assertTrue(result.stale)
        self.assertEqual(result.kline["dates"][-1], "2026-07-01")

    def test_nonfinal_data_is_preview_when_refresh_fails(self):
        self.seed(
            "600000",
            [_bar("2026-07-01"), _bar("2026-07-02", final=False)],
        )
        repository = KLineRepository(
            self.db_path, remote_fetchers={"day": lambda code, count: None}
        )

        result = repository.get(
            "day", "600000", count=2, required_date="2026-07-02"
        )

        self.assertEqual(result.status, "preview")
        self.assertFalse(result.kline["_data_status"]["is_final"])

    def test_backtest_requires_as_of_never_calls_remote_and_hard_truncates(self):
        self.seed(
            "600000",
            [_bar("2026-07-01"), _bar("2026-07-02")],
        )
        calls = []
        repository = KLineRepository(
            self.db_path,
            mode="backtest",
            remote_fetchers={"day": lambda code, count: calls.append(code)},
        )

        with self.assertRaisesRegex(ValueError, "as_of"):
            repository.get("day", "600000", count=1)
        result = repository.get(
            "day", "600000", count=1, as_of="2026-07-01"
        )
        missing = repository.get(
            "day", "600000", count=2, as_of="2026-07-01"
        )

        self.assertEqual(calls, [])
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.kline["dates"], ["2026-07-01"])
        self.assertEqual(missing.status, "missing")
        self.assertEqual(missing.kline["dates"], ["2026-07-01"])

    def test_get_many_uses_bounded_database_queries_and_no_network_when_complete(self):
        for code in ("600000", "600001", "000001"):
            self.seed(code, [_bar("2026-07-01"), _bar("2026-07-02")])
        statements = []

        def trace(sql):
            normalized = " ".join(sql.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        repository = KLineRepository(
            self.db_path,
            remote_fetchers={"day": lambda code, count: self.fail("network called")},
            trace_callback=trace,
        )
        results = repository.get_many(
            "day",
            ["600000", "600001", "000001"],
            count=2,
            required_date="2026-07-02",
        )

        self.assertTrue(all(result.status == "verified" for result in results.values()))
        bar_selects = [sql for sql in statements if "from bars_day" in sql]
        instrument_selects = [sql for sql in statements if "from instruments" in sql]
        self.assertEqual(len(bar_selects), 1)
        self.assertEqual(len(instrument_selects), 1)

    def test_one_invalid_remote_stock_does_not_rollback_other_valid_stock(self):
        def remote(code, count):
            payload = _payload(["2026-07-01", "2026-07-02"])
            if code == "600001":
                payload["highs"][0] = 1.0
            return payload

        repository = KLineRepository(
            self.db_path, remote_fetchers={"day": remote}
        )
        results = repository.get_many(
            "day",
            ["600000", "600001"],
            count=2,
            required_date="2026-07-02",
        )

        self.assertEqual(results["600000"].status, "verified")
        self.assertEqual(results["600001"].status, "missing")
        with MarketHistoryStore(self.db_path, readonly=True) as store:
            self.assertIsNotNone(
                store.resolve_instrument("stock", "SH", "600000")
            )
            self.assertIsNone(
                store.resolve_instrument("stock", "SH", "600001")
            )

    def test_shadow_reader_is_diagnostic_only_and_cannot_replace_database_result(self):
        self.seed("600000", [_bar("2026-07-01"), _bar("2026-07-02")])
        shadow_calls = []
        repository = KLineRepository(
            self.db_path,
            remote_fetchers={"day": lambda code, count: self.fail("network called")},
            shadow_reader=lambda interval, code, count: shadow_calls.append(code)
            or _payload(["2026-01-01"]),
        )

        result = repository.get(
            "day", "600000", count=2, required_date="2026-07-02"
        )

        self.assertEqual(shadow_calls, ["600000"])
        self.assertEqual(result.kline["dates"][-1], "2026-07-02")
        self.assertTrue(result.diagnostics["shadow_mismatch"])

    def test_public_fetch_wrapper_keeps_array_shape_and_repository_status(self):
        self.seed(
            "600000",
            [_bar("2026-07-01"), _bar("2026-07-02", final=False)],
        )
        repository = KLineRepository(
            self.db_path, remote_fetchers={"day": lambda code, count: None}
        )
        previous = data_fetcher._KLINE_REPOSITORY
        try:
            data_fetcher._KLINE_REPOSITORY = repository
            kline = data_fetcher.fetch_daily_kline(
                "600000", count=2, required_date="2026-07-02"
            )
            status = data_fetcher.build_kline_status(
                kline, required_date="2026-07-02"
            )
        finally:
            data_fetcher._KLINE_REPOSITORY = previous

        self.assertIsInstance(kline["closes"], np.ndarray)
        self.assertEqual(status["daily"], "preview")
        self.assertEqual(status["source"], "market_history_db")

    def test_enabled_public_wrapper_does_not_read_or_write_legacy_json(self):
        remote = lambda code, count: _payload(
            ["2026-06-30", "2026-07-01", "2026-07-02"]
        )
        previous = data_fetcher._KLINE_REPOSITORY
        try:
            data_fetcher._KLINE_REPOSITORY = None
            with patch.object(
                data_fetcher, "MARKET_HISTORY_DB_PATH", str(self.db_path)
            ), patch.object(
                data_fetcher, "_fetch_daily_for_repository", side_effect=remote
            ), patch.object(
                data_fetcher, "read_cached_records"
            ) as legacy_read, patch.object(
                data_fetcher, "write_cached_records"
            ) as legacy_write:
                kline = data_fetcher.fetch_daily_kline(
                    "600000", count=3, required_date="2026-07-02"
                )
        finally:
            data_fetcher._KLINE_REPOSITORY = previous

        self.assertEqual(len(kline["dates"]), 3)
        legacy_read.assert_not_called()
        legacy_write.assert_not_called()

    def test_data_fetcher_batch_uses_one_repository_batch_call(self):
        kline = _payload(
            [
                "2026-05-{:02d}".format(index)
                for index in range(1, 29)
            ]
            + [
                "2026-06-{:02d}".format(index)
                for index in range(1, 31)
            ]
            + ["2026-07-01", "2026-07-02"]
        )
        kline["source"] = "market_history_db"
        kline["_data_status"] = {
            "daily": "verified",
            "latest_date": "2026-07-02",
            "source": "market_history_db",
            "bars": 60,
            "stale": False,
            "is_final": True,
        }
        repository = MagicMock()
        repository.get_many.return_value = {
            code: KLineResult(
                kline=dict(kline),
                status="verified",
                source="market_history_db",
                stale=False,
            )
            for code in ("600000", "600001", "600002")
        }
        previous = data_fetcher._KLINE_REPOSITORY
        try:
            data_fetcher._KLINE_REPOSITORY = repository
            rows = data_fetcher.batch_fetch_daily_klines(
                [
                    {"code": code, "name": code}
                    for code in ("600000", "600001", "600002")
                ],
                required_date="2026-07-02",
            )
        finally:
            data_fetcher._KLINE_REPOSITORY = previous

        self.assertEqual(len(rows), 3)
        repository.get_many.assert_called_once()


if __name__ == "__main__":
    unittest.main()
