import tempfile
import unittest
from pathlib import Path

from chanlun.market_history_store import MarketHistoryStore
from scripts.repair_missing_amounts import repair_missing_amounts


class RepairMissingAmountsTest(unittest.TestCase):
    def test_repairs_zero_amount_and_records_ingest_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                instrument_id = store.upsert_instrument(
                    "stock", "SH", "600000", "浦发银行"
                )
                store.upsert_bars(
                    "day",
                    instrument_id,
                    [{
                        "ts": "2026-07-10",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10,
                        "volume": 1234,
                        "amount": 0,
                        "adjustment": "qfq",
                        "is_final": True,
                        "source_batch": "fixture",
                    }],
                    adjustment="qfq",
                )

            result = repair_missing_amounts(
                path, run_id="repair-amount-test", intervals=["day"]
            )

            with MarketHistoryStore(path, readonly=True) as store:
                instrument = store.resolve_instrument(
                    "stock", "SH", "600000"
                )
                bar = store.query_bars(
                    "day", instrument["instrument_id"]
                )[0]
                run = store.get_ingest_run("repair-amount-test")

        self.assertEqual(1, result["rows_repaired"])
        self.assertEqual(1234 * 10 * 100, bar["amount"])
        self.assertEqual("complete", run["status"])
        self.assertEqual(
            "volume_close_100_proxy",
            run["metadata"]["amount_policy"],
        )


if __name__ == "__main__":
    unittest.main()
