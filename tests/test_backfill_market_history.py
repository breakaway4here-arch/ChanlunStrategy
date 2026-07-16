import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from chanlun import data_fetcher
from chanlun.market_history_store import MarketHistoryStore
from scripts.backfill_market_history import (
    BackfillIncomplete,
    DEFAULT_WORKERS,
    _retry_fetch,
    merge_completed_run,
    run_shard,
    stable_code_shards,
    validate_complete_manifests,
)


def _kline(code, count, start=1, interval="day"):
    base = datetime(2026, 1, 1) + timedelta(days=start - 1)
    if interval == "day":
        dates = [
            (base + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(count)
        ]
    else:
        dates = [
            (base + timedelta(minutes=30 * i)).strftime("%Y-%m-%d %H:%M")
            for i in range(count)
        ]
    closes = np.array([10.0 + i * 0.1 for i in range(count)])
    return {
        "dates": dates,
        "opens": closes - 0.1,
        "highs": closes + 0.2,
        "lows": closes - 0.2,
        "closes": closes,
        "volumes": np.array([1000.0 + i for i in range(count)]),
        "amounts": np.array([10000.0 + i for i in range(count)]),
        "source": "fake-{}".format(code),
    }


class BackfillMarketHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stable_twenty_way_shards_are_sorted_unique_and_disjoint(self):
        codes = ["000003", "000001", "000002", "000001"] + [
            "{:06d}".format(value) for value in range(4, 45)
        ]

        shards = stable_code_shards(codes, shard_count=20)

        normalized = sorted(set(codes))
        self.assertEqual(shards, [normalized[index::20] for index in range(20)])
        flattened = [code for shard in shards for code in shard]
        self.assertEqual(sorted(flattened), normalized)
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(3, DEFAULT_WORKERS)

    def test_retry_fetch_uses_sequential_sources_and_exponential_backoff(self):
        calls = []
        sleeps = []

        def first(code, count):
            calls.append(("first", code, count))
            return None

        attempts = {"count": 0}

        def second(code, count):
            attempts["count"] += 1
            calls.append(("second", code, count))
            if attempts["count"] == 1:
                return None
            return {"dates": ["2026-07-15"]}

        result = _retry_fetch(
            "600000",
            1000,
            [first, second],
            attempts=3,
            base_delay=0.25,
            sleep_fn=sleeps.append,
        )

        self.assertEqual({"dates": ["2026-07-15"]}, result)
        self.assertEqual(
            [
                ("first", "600000", 1000),
                ("second", "600000", 1000),
                ("first", "600000", 1000),
                ("second", "600000", 1000),
            ],
            calls,
        )
        self.assertEqual([0.25], sleeps)

    def test_retry_fetch_rejects_invalid_payload_before_next_provider(self):
        calls = []

        def invalid(code, count):
            calls.append("invalid")
            return {"dates": ["2026-07-15"], "opens": [0]}

        def valid(code, count):
            calls.append("valid")
            return {"dates": ["2026-07-15"], "opens": [10]}

        result = _retry_fetch(
            "600000",
            1000,
            [invalid, valid],
            validator=lambda payload: payload["opens"][0] > 0,
        )

        self.assertEqual({"dates": ["2026-07-15"], "opens": [10]}, result)
        self.assertEqual(["invalid", "valid"], calls)

    def test_run_shard_writes_manifest_and_classifies_short_history(self):
        staging = self.root / "shard.sqlite"

        def fetcher(code, count):
            return _kline(
                code, count if code == "600000" else count - 1, interval="30m"
            )

        result = run_shard(
            run_id="run-1",
            shard_id=0,
            shard_count=20,
            interval="30m",
            codes=["600000", "600001"],
            staging_path=staging,
            fetcher=fetcher,
            count=500,
            stock_metadata={
                "600000": {
                    "name": "浦发银行",
                    "listed_date": "19991110",
                    "is_st": False,
                    "delisting_risk": False,
                }
            },
            meta_as_of="2026-07-01",
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["insufficient_count"], 1)
        self.assertEqual(result["failure_count"], 0)
        with MarketHistoryStore(staging, readonly=True) as store:
            manifest = store.list_shard_manifests("run-1")[0]
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["metadata"]["processed_count"], 2)
            self.assertEqual(
                manifest["metadata"]["insufficient"][0]["reason"],
                "insufficient_history",
            )
            instrument = store.resolve_instrument("stock", "SH", "600000")
            meta = store.query_stock_meta(
                instrument["instrument_id"], as_of="2026-07-01"
            )
            self.assertEqual(instrument["name"], "浦发银行")
            self.assertGreater(meta["listed_days"], 60)
            self.assertEqual(
                len(store.query_bars("30m", instrument["instrument_id"])), 500
            )

    def test_failed_shard_is_resumable_and_retry_is_idempotent(self):
        staging = self.root / "retry.sqlite"
        attempts = {"600001": 0}
        calls = []

        def flaky_fetcher(code, count):
            calls.append(code)
            if code == "600001" and attempts[code] == 0:
                attempts[code] += 1
                payload = _kline(code, count)
                payload["opens"][0] = 0
                return payload
            return _kline(code, count)

        first = run_shard(
            "run-retry", 0, 1, "day", ["600000", "600001"], staging,
            fetcher=flaky_fetcher, count=3,
        )
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["failure_count"], 1)

        second = run_shard(
            "run-retry", 0, 1, "day", ["600000", "600001"], staging,
            fetcher=flaky_fetcher, count=3,
        )
        self.assertEqual(second["status"], "complete")
        self.assertEqual(second["failure_count"], 0)
        self.assertEqual(
            ["600000", "600001", "600001"],
            calls,
        )
        with MarketHistoryStore(staging, readonly=True) as store:
            rows = store.connection.execute("SELECT COUNT(*) FROM bars_day").fetchone()[0]
            self.assertEqual(rows, 6)
            manifest = store.list_shard_manifests("run-retry")[0]
            self.assertEqual(manifest["status"], "complete")

    def test_sparse_remote_unavailable_is_audited_without_blocking_shard(self):
        staging = self.root / "sparse-unavailable.sqlite"

        def fetcher(code, count):
            if code == "600001":
                return None
            return _kline(code, count)

        result = run_shard(
            "run-sparse",
            0,
            1,
            "day",
            ["600000", "600001"],
            staging,
            fetcher=fetcher,
            count=3,
            stock_metadata={
                "600001": {
                    "name": "待上市样本",
                    "listed_date": "20260720",
                    "is_st": False,
                    "delisting_risk": False,
                }
            },
            meta_as_of="2026-07-16",
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual(0, result["failure_count"])
        self.assertEqual(1, result["unavailable_count"])
        self.assertEqual(
            "remote_unavailable",
            result["insufficient"][0]["reason"],
        )
        with MarketHistoryStore(staging, readonly=True) as store:
            instrument = store.resolve_instrument(
                "stock", "SH", "600001"
            )
            self.assertIsNotNone(instrument)
            meta = store.query_stock_meta(
                instrument["instrument_id"], as_of="2026-07-16"
            )
            self.assertEqual("待上市样本", meta["name"])

    def test_invalid_ohlc_fails_shard_without_marking_complete(self):
        staging = self.root / "invalid.sqlite"

        def invalid_fetcher(code, count):
            payload = _kline(code, count)
            payload["highs"][0] = payload["lows"][0] - 1
            return payload

        result = run_shard(
            "run-invalid", 0, 1, "day", ["600000"], staging,
            fetcher=invalid_fetcher, count=2,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_count"], 1)
        with MarketHistoryStore(staging, readonly=True) as store:
            self.assertEqual(
                store.list_shard_manifests("run-invalid")[0]["status"], "failed"
            )
            self.assertEqual(
                store.connection.execute("SELECT COUNT(*) FROM bars_day").fetchone()[0],
                0,
            )

    def test_invalid_or_duplicate_timestamp_fails_closed(self):
        for invalid_dates in (["not-a-date"], ["2026-07-01", "2026-07-01"]):
            with self.subTest(invalid_dates=invalid_dates):
                staging = self.root / "bad-ts-{}.sqlite".format(len(invalid_dates))

                def invalid_fetcher(code, count, dates=invalid_dates):
                    payload = _kline(code, len(dates))
                    payload["dates"] = dates
                    return payload

                result = run_shard(
                    "run-bad-ts-{}".format(len(invalid_dates)),
                    0, 1, "day", ["600000"], staging,
                    fetcher=invalid_fetcher, count=len(invalid_dates),
                )
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["failure_count"], 1)

    def test_manifest_validation_rejects_missing_failed_or_mismatched_shards(self):
        paths = []
        for shard_id, status in ((0, "complete"), (1, "failed")):
            path = self.root / "manifest-{}.sqlite".format(shard_id)
            with MarketHistoryStore(path) as store:
                store.upsert_shard_manifest(
                    "run-manifest", shard_id, 2, status,
                    metadata={"code_checksum": "checksum-{}".format(shard_id)},
                )
            paths.append(path)

        with self.assertRaises(BackfillIncomplete):
            validate_complete_manifests(paths, "run-manifest", expected_shards=2)
        with self.assertRaises(BackfillIncomplete):
            validate_complete_manifests(paths[:1], "run-manifest", expected_shards=2)

    def test_merge_completed_run_is_single_transaction_and_finishes_master_run(self):
        paths = []
        for shard_id, code in enumerate(("600000", "000001")):
            path = self.root / "complete-{}.sqlite".format(shard_id)
            run_shard(
                "run-merge", shard_id, 2, "day", [code], path,
                fetcher=lambda current, count: _kline(current, count),
                count=2,
            )
            paths.append(path)
        target = self.root / "market.sqlite"

        result = merge_completed_run(
            target, paths, run_id="run-merge", expected_shards=2
        )

        self.assertEqual(result["bars"], 4)
        with MarketHistoryStore(target, readonly=True) as store:
            run = store.get_ingest_run("run-merge")
            self.assertEqual(run["status"], "complete")
            self.assertEqual(run["rows_written"], 4)
            self.assertEqual(
                store.connection.execute("SELECT COUNT(*) FROM bars_day").fetchone()[0],
                4,
            )

    def test_all_a_fetch_paginates_and_deduplicates_stably(self):
        pages = [
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "600001", "f14": "*ST B", "f26": "20000101"},
                        {"f12": "000001", "f14": "A", "f26": "19910403"},
                    ],
                }
            },
            {
                "data": {
                    "total": 3,
                    "diff": [
                        {"f12": "600001", "f14": "B duplicate"},
                        {"f12": "300001", "f14": "C退", "f26": "20100101"},
                    ],
                }
            },
        ]
        with patch.object(data_fetcher, "_fetch_eastmoney_json", side_effect=pages):
            stocks, diagnostics = data_fetcher.fetch_all_a_stocks(
                page_size=2, return_diagnostics=True
            )

        self.assertEqual([row["code"] for row in stocks], ["000001", "300001", "600001"])
        self.assertTrue(diagnostics["complete"])
        self.assertEqual(diagnostics["unique"], 3)
        self.assertEqual(diagnostics["pages"], 2)
        by_code = {row["code"]: row for row in stocks}
        self.assertTrue(by_code["600001"]["is_st"])
        self.assertTrue(by_code["300001"]["delisting_risk"])
        self.assertEqual(by_code["000001"]["listed_date"], "19910403")

    def test_eastmoney_minute_fetch_requests_full_500_and_parses_amount(self):
        lines = [
            "2026-07-01 10:00,10,10.1,10.2,9.9,1000,10000",
            "2026-07-01 10:30,10.1,10.2,10.3,10,1100,11000",
        ]
        response = type(
            "Response",
            (),
            {"json": lambda self: {"data": {"klines": lines}}},
        )()
        with patch.object(data_fetcher.SESSION, "get", return_value=response) as get:
            payload = data_fetcher._fetch_eastmoney_minute_kline_remote(
                "600000", scale=30, count=500
            )

        self.assertEqual(get.call_args[1]["params"]["lmt"], "500")
        self.assertEqual(get.call_args[1]["params"]["klt"], "30")
        self.assertEqual(len(payload["dates"]), 2)
        self.assertEqual(payload["amounts"].tolist(), [10000.0, 11000.0])


if __name__ == "__main__":
    unittest.main()
