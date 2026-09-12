import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from chanlun import data_fetcher
from chanlun.identity import (
    InstrumentIdentity,
    normalize_identity,
    normalize_index_identity,
)
from chanlun.kline_repository import KLineRepository
from chanlun.market_history_store import MarketHistoryStore


class IdentityContractTests(unittest.TestCase):
    def test_provider_routes_are_identity_aware_for_stock_and_index(self):
        stock = InstrumentIdentity("stock", "SZ", "000063")
        index = InstrumentIdentity("index", "SH", "000063")

        self.assertEqual(data_fetcher._tencent_code(stock), "sz000063")
        self.assertEqual(data_fetcher._tencent_code(index), "sh000063")
        self.assertEqual(data_fetcher._em_secid(stock), "0.000063")
        self.assertEqual(data_fetcher._em_secid(index), "1.000063")
        self.assertEqual(data_fetcher._sina_code(stock), "sz000063")
        self.assertEqual(data_fetcher._sina_code(index), "sh000063")

    def test_legacy_stock_code_does_not_become_an_index(self):
        identity = normalize_identity("000063")
        self.assertEqual(identity, InstrumentIdentity("stock", "SZ", "000063"))

    def test_unknown_or_contradictory_identity_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_identity("000063", exchange="SH")
        with self.assertRaises(ValueError):
            normalize_identity("999999")
        with self.assertRaises(ValueError):
            normalize_identity(
                {"asset_type": "index", "exchange": "", "code": "000001"}
            )
        with self.assertRaises(ValueError):
            normalize_identity(
                {"asset_type": "stock", "exchange": "SZ", "code": "000001"},
                exchange="SH",
            )
        with self.assertRaises(ValueError):
            normalize_identity(
                {"asset_type": "banana", "exchange": "SZ", "code": "000001"}
            )
        with self.assertRaises(ValueError):
            normalize_identity("１２３４５６")
        with self.assertRaises(ValueError):
            normalize_identity("600000", code="600001")
        with self.assertRaises(ValueError):
            normalize_identity(
                {"asset_type": "stock", "exchange": "SH", "code": "600000"},
                code="600001",
            )
        with self.assertRaises(ValueError):
            normalize_identity(
                {
                    "identity": {
                        "asset_type": "index",
                        "exchange": "SH",
                        "code": "000001",
                    },
                    "asset_type": "stock",
                }
            )

    def test_beijing_stock_keeps_bj_route_and_does_not_default_to_sz(self):
        identity = normalize_identity("920001")
        self.assertEqual(identity, InstrumentIdentity("stock", "BJ", "920001"))
        self.assertEqual(data_fetcher._tencent_code(identity), "bj920001")

    def test_index_registry_keeps_shenzhen_index_exchange_explicit(self):
        identity = normalize_index_identity("399001")
        self.assertEqual(identity, InstrumentIdentity("index", "SZ", "399001"))
        self.assertEqual(data_fetcher._tencent_code(identity), "sz399001")
        with self.assertRaises(ValueError):
            normalize_index_identity("000063")

    def test_index_nested_identity_and_registered_exchange_are_checked(self):
        self.assertEqual(
            normalize_index_identity(
                {
                    "identity": {
                        "asset_type": "index",
                        "exchange": "SH",
                        "code": "000001",
                    }
                }
            ),
            InstrumentIdentity("index", "SH", "000001"),
        )
        with self.assertRaises(ValueError):
            normalize_index_identity("000001", exchange="SZ")
        with self.assertRaises(ValueError):
            normalize_index_identity(InstrumentIdentity("index", "SZ", "000001"))
        with self.assertRaises(ValueError):
            normalize_index_identity(
                {
                    "identity": {
                        "asset_type": "index",
                        "exchange": "SH",
                        "code": "000001",
                    },
                    "exchange": "SZ",
                }
            )
        # Unknown indexes retain the existing explicit-exchange convention;
        # the index entry point does not guess their market from the code.
        self.assertEqual(
            normalize_index_identity("000063", exchange="SH"),
            InstrumentIdentity("index", "SH", "000063"),
        )
        self.assertEqual(
            normalize_identity(
                {
                    "identity": {"asset_type": "index", "exchange": "SH"},
                    "code": "000001",
                }
            ),
            InstrumentIdentity("index", "SH", "000001"),
        )

    def test_market_cap_result_is_keyed_by_identity_and_keeps_legacy_unique_code(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "data": {
                        "diff": [
                            {"f12": "000001", "f13": "0", "f20": 1000000000, "f21": 500000000}
                        ]
                    }
                }

        identity = InstrumentIdentity("stock", "SZ", "000001")
        with patch.object(data_fetcher.SESSION, "get", return_value=Response()):
            result = data_fetcher.fetch_stock_market_caps([identity], max_workers=1)
        self.assertEqual(result[identity.key]["market_cap"], 10.0)
        self.assertEqual(result["000001"]["circulating_market_cap"], 5.0)

    def test_market_cap_explicit_provider_market_mismatch_is_dropped(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "data": {
                        # Requested stock is SZ, but f13 explicitly says SH.
                        "diff": [
                            {
                                "f12": "000001",
                                "f13": "1",
                                "f20": 1000000000,
                                "f21": 500000000,
                            }
                        ]
                    }
                }

        identity = InstrumentIdentity("stock", "SZ", "000001")
        with patch.object(data_fetcher.SESSION, "get", return_value=Response()):
            result = data_fetcher.fetch_stock_market_caps([identity], max_workers=1)
        self.assertNotIn(identity.key, result)
        self.assertNotIn(identity.code, result)

    def test_market_cap_blank_provider_market_keeps_unique_code_compatibility(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "data": {
                        "diff": [
                            {
                                "f12": "000001",
                                "f13": "",
                                "f20": 1000000000,
                                "f21": 500000000,
                            }
                        ]
                    }
                }

        identity = InstrumentIdentity("stock", "SZ", "000001")
        with patch.object(data_fetcher.SESSION, "get", return_value=Response()):
            result = data_fetcher.fetch_stock_market_caps([identity], max_workers=1)
        self.assertEqual(result[identity.key]["market_cap"], 10.0)

    def test_fetch_entry_points_reject_conflicting_positional_code(self):
        identity = InstrumentIdentity("stock", "SH", "600001")
        calls = []

        def fake_fetch(interval, code, count, **kwargs):
            calls.append((interval, code, count, kwargs))
            return {"dates": [], "closes": []}

        with patch.object(data_fetcher, "_fetch_from_repository", side_effect=fake_fetch):
            for fetcher, interval in (
                (data_fetcher.fetch_daily_kline, "day"),
                (data_fetcher.fetch_30min_kline, "30m"),
                (data_fetcher.fetch_15min_kline, "15m"),
            ):
                with self.assertRaises(ValueError):
                    fetcher("600000", identity=identity)
                fetcher("600001", identity=identity)
            with self.assertRaises(ValueError):
                data_fetcher.fetch_kline("600000", identity=identity)

        self.assertEqual([call[0] for call in calls], ["day", "30m", "15m"])

    def test_repository_keeps_stock_and_index_with_same_code_separate(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path):
                pass
            repository = KLineRepository(path, mode="backtest")
            with MarketHistoryStore(path) as store:
                stock_id = store.upsert_instrument("stock", "SZ", "000001")
                index_id = store.upsert_instrument("index", "SH", "000001")
                self.assertNotEqual(stock_id, index_id)

    def test_store_write_and_normal_lookup_reject_contradictory_stock_identity(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                with self.assertRaises(ValueError):
                    store.upsert_instrument("stock", "SH", "000063")
                with self.assertRaises(ValueError):
                    store.resolve_instrument("stock", "SH", "000063")

    def test_batch_resolve_skips_legacy_contradictory_row_without_blocking_peers(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                stock_id = store.upsert_instrument("stock", "SZ", "000001")
                resolved = store.resolve_instruments(
                    "stock", [("SZ", "000001"), ("SZ", "920001")]
                )
            self.assertEqual(resolved[("SZ", "000001")]["instrument_id"], stock_id)
            self.assertNotIn(("SZ", "920001"), resolved)

    def test_repository_identity_lookup_does_not_collapse_same_code(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path):
                pass
            repository = KLineRepository(path, mode="backtest")
            results = repository.get_many(
                "day",
                [
                    InstrumentIdentity("stock", "SZ", "000001"),
                    InstrumentIdentity("index", "SH", "000001"),
                ],
                count=1,
                as_of="2026-09-11",
            )
            self.assertEqual(
                set(results),
                {
                    InstrumentIdentity("stock", "SZ", "000001"),
                    InstrumentIdentity("index", "SH", "000001"),
                },
            )

    def test_repository_persists_and_reads_same_code_by_full_identity(self):
        def remote(identity, count):
            self.assertIsInstance(identity, InstrumentIdentity)
            close = 10.0 if identity.asset_type == "stock" else 20.0
            dates = ["2026-09-10", "2026-09-11"]
            closes = [close, close + 1.0]
            return {
                "dates": dates,
                "opens": closes,
                "highs": [value + 0.2 for value in closes],
                "lows": [value - 0.2 for value in closes],
                "closes": closes,
                "volumes": [1000.0, 1100.0],
                "amounts": [10000.0, 11000.0],
                "finals": [True, True],
                "source": identity.key,
            }

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path):
                pass
            repository = KLineRepository(
                path,
                remote_fetchers={"day": remote},
            )
            stock = InstrumentIdentity("stock", "SZ", "000001")
            index = InstrumentIdentity("index", "SH", "000001")
            results = repository.get_many(
                "day",
                [stock, index],
                count=2,
                required_date="2026-09-11",
            )
            self.assertEqual(results[stock].status, "verified")
            self.assertEqual(results[index].status, "verified")
            self.assertEqual(float(results[stock].kline["closes"][-1]), 11.0)
            self.assertEqual(float(results[index].kline["closes"][-1]), 21.0)
            with MarketHistoryStore(path, readonly=True) as store:
                stock_row = store.resolve_instrument("stock", "SZ", "000001")
                index_row = store.resolve_instrument("index", "SH", "000001")
                self.assertIsNotNone(stock_row)
                self.assertIsNotNone(index_row)
                self.assertNotEqual(
                    stock_row["instrument_id"], index_row["instrument_id"]
                )


if __name__ == "__main__":
    unittest.main()
