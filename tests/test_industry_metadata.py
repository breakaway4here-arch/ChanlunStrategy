import tempfile
import unittest
from pathlib import Path

from chanlun.industry_metadata import _is_a_share_identity, hydrate_industry_metadata
from chanlun.market_history_store import MarketHistoryStore


class IndustryMetadataHydrationTests(unittest.TestCase):
    def test_new_beijing_920_identity_is_a_share_but_shanghai_900_is_not(self):
        self.assertTrue(_is_a_share_identity({"exchange": "BJ", "code": "920003"}))
        self.assertFalse(_is_a_share_identity({"exchange": "SH", "code": "900913"}))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "market_history.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def _stock(self, code, metadata):
        with MarketHistoryStore(self.path) as store:
            exchange = "SH" if code.startswith(("6", "68")) else "SZ"
            instrument_id = store.upsert_instrument("stock", exchange, code)
            store.upsert_stock_meta(instrument_id, "2026-07-16", metadata)

    def _meta(self, code):
        with MarketHistoryStore(self.path, readonly=True) as store:
            exchange = "SH" if code.startswith(("6", "68")) else "SZ"
            instrument = store.resolve_instrument("stock", exchange, code)
            return store.query_stock_meta(instrument["instrument_id"], "2026-07-17")

    def test_complete_industry_coverage_uses_database_without_remote_call(self):
        self._stock("600000", {"industry": "银行", "listed_days": 5000})
        with MarketHistoryStore(self.path) as store:
            invalid_id = store.upsert_instrument(
                "stock", "SH", "000002", name="错误交易所历史重复项"
            )
            store.upsert_stock_meta(
                invalid_id, "2026-07-16", {"listed_days": 5000}
            )
        calls = []

        result = hydrate_industry_metadata(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda: calls.append(True),
        )

        self.assertEqual(calls, [])
        self.assertEqual(result["remote_calls"], 0)
        self.assertTrue(result["industry_complete"])
        self.assertEqual(result["db_complete"], 1)
        self.assertEqual(result["ignored_non_a_instruments"], 1)

    def test_hydrates_only_missing_industry_and_preserves_existing_metadata(self):
        self._stock("600000", {
            "name": "浦发银行", "listed_days": 5000, "market_cap": 1234.5,
        })
        self._stock("000001", {
            "name": "平安银行", "industry": "银行", "listed_days": 4000,
        })
        calls = []

        def fetch_all_a_stocks():
            calls.append(True)
            return [
                {"code": "600000", "industry": "银行", "name": "浦发银行新名"},
                {"code": "000001", "industry": "不应覆盖"},
            ]

        result = hydrate_industry_metadata(
            self.path, "2026-07-17", fetch_all_a_stocks=fetch_all_a_stocks
        )

        self.assertEqual(calls, [True])
        self.assertEqual(result["remote_calls"], 1)
        self.assertEqual(result["missing_before"], 1)
        self.assertEqual(result["hydrated"], 1)
        self.assertTrue(result["industry_complete"])
        meta = self._meta("600000")
        self.assertEqual(meta["industry"], "银行")
        self.assertEqual(meta["listed_days"], 5000)
        self.assertEqual(meta["market_cap"], 1234.5)
        self.assertEqual(self._meta("000001")["industry"], "银行")

    def test_incomplete_remote_result_does_not_claim_industry_coverage_complete(self):
        self._stock("600000", {"name": "浦发银行", "listed_days": 5000})
        self._stock("000001", {"name": "平安银行", "listed_days": 4000})

        result = hydrate_industry_metadata(
            self.path,
            "2026-07-17",
            fetch_all_a_stocks=lambda: [{"code": "600000", "industry": "银行"}],
        )

        self.assertEqual(result["hydrated"], 1)
        self.assertEqual(result["missing_after"], 1)
        self.assertFalse(result["industry_complete"])
        self.assertEqual(result["status"], "partial")
