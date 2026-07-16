import tempfile
import unittest
from pathlib import Path

from chanlun.market_history_store import MarketHistoryStore
from run import _hydrate_market_cap_evidence


class RunMarketCapEvidenceTests(unittest.TestCase):
    def test_uses_shared_db_first_and_fetches_only_missing_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                cached_id = store.upsert_instrument(
                    "stock", "SH", "600001", name="缓存股票"
                )
                missing_id = store.upsert_instrument(
                    "stock", "SZ", "000001", name="缺失股票"
                )
                store.upsert_stock_meta(
                    cached_id,
                    "2026-07-16",
                    {
                        "name": "缓存股票",
                        "market_cap": 120,
                        "circulating_market_cap": 80,
                    },
                )
                store.upsert_stock_meta(
                    missing_id,
                    "2026-07-16",
                    {"name": "缺失股票"},
                )

            calls = []

            def fetcher(codes, max_workers=20):
                calls.append((list(codes), max_workers))
                return {
                    "000001": {
                        "market_cap": 200,
                        "circulating_market_cap": 160,
                        "float_market_cap": 160,
                    },
                }

            stocks = [{"code": "600001"}, {"code": "000001"}]
            diagnostics = _hydrate_market_cap_evidence(
                stocks,
                "2026-07-16",
                db_path=str(path),
                fetcher=fetcher,
                max_workers=20,
            )

            with MarketHistoryStore(path) as store:
                persisted = store.query_stock_meta(
                    missing_id, as_of="2026-07-16"
                )

        self.assertEqual(calls, [(["000001"], 20)])
        self.assertEqual(stocks[0]["market_cap"], 120)
        self.assertEqual(stocks[1]["circulating_market_cap"], 160)
        self.assertEqual(persisted["market_cap"], 200)
        self.assertEqual(diagnostics["db_hits"], 1)
        self.assertEqual(diagnostics["hydrated"], 2)


if __name__ == "__main__":
    unittest.main()
