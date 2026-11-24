"""Observation acquisition counts one in-scope A-share identity once."""

import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from chanlun import intraday_observation_data as data
from chanlun.market_history_store import MarketHistoryStore
from tests.test_intraday_observation_data import CN, CUTOFF, IDENTITY, fixture


class ObservationCohortTests(unittest.TestCase):
    def collect(self, missing=1, extras=True):
        pair = {adjustment: data.parse_eastmoney_minutes(
            fixture()[1], IDENTITY, adjustment=adjustment, cutoff=CUTOFF,
            fetched_at="2026-10-13T14:46:00+08:00") for adjustment in ("raw", "qfq")}
        pair.update(raw_daily=copy.deepcopy(fixture()[0]), daily=copy.deepcopy(fixture()[0]))
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "market.sqlite"
            with MarketHistoryStore(db) as store:
                for index in range(10):
                    code = "600{:03}".format(index)
                    iid = store.upsert_instrument("stock", "SH", code)
                    if index < 10 - missing:
                        store.upsert_stock_meta(iid, "2026-10-12", dict(
                            name=code, listed_days=500, is_st=False, delisting_risk=False))
                if extras:
                    for exchange, code in (("SH", "900901"), ("SZ", "200002"), ("SZ", "201872"),
                                           ("SZ", "600000")):
                        store.connection.execute(
                            "INSERT INTO instruments(asset_type,exchange,code,updated_at) "
                            "VALUES ('stock',?,?, '2026-10-12')", (exchange, code))
                    store.connection.commit()
                for row in fixture()[0] + [{"ts": "2026-10-13"}]:
                    for exchange in ("SH", "SZ"):
                        store.upsert_trade_calendar(exchange, row["ts"], True)

            def fetch(identity, **kwargs):
                result = copy.deepcopy(pair)
                for adjustment in ("raw", "qfq"):
                    result[adjustment].update(identity_key=identity.key, code=identity.code,
                        asset_type=identity.asset_type, exchange=identity.exchange)
                return result

            return data.acquire_observation_payload(db, "2026-10-13",
                deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN),
                clock=lambda: datetime(2026, 10, 13, 14, 46, tzinfo=CN),
                pair_fetcher=fetch, max_workers=2)["collection_health"]

    def test_out_of_scope_and_duplicate_rows_do_not_hide_ninety_percent_foundation(self):
        health = self.collect()
        self.assertEqual(health["status"], "partial")
        self.assertEqual((health["expected"], health["acquired"]), (9, 9))
        self.assertEqual(health["instrument_count"], 14)
        self.assertEqual(health["foundation_missing"], 1)
        self.assertEqual(health["foundation_coverage"], .9)
        self.assertEqual(health["scope_excluded"], 4)
        self.assertEqual(health["scope_excluded_reasons"], {
            "non_a_share": 3, "duplicate_market_registration": 1})
        self.assertEqual(health["instrument_count"], health["qualified_cohort"]
            + health["business_excluded"] + health["foundation_missing"] + health["scope_excluded"])

    def test_genuine_missing_a_share_metadata_still_blocks_below_ninety_percent(self):
        health = self.collect(missing=2)
        self.assertEqual(health["status"], "failed")
        self.assertEqual(health["foundation_missing"], 2)
        self.assertEqual(health["foundation_coverage"], .8)

    def test_unpaired_wrong_exchange_and_malformed_code_remain_foundation_gaps(self):
        instruments = [
            dict(instrument_id=1, asset_type="stock", exchange="SH", code="000001"),
            dict(instrument_id=2, asset_type="stock", exchange="SH", code="bad123"),
            dict(instrument_id=3, asset_type="stock", exchange="SH", code="600000"),
            dict(instrument_id=4, asset_type="stock", exchange="UNKNOWN", code="600000"),
        ]

        class Store:
            def list_instruments(self, **kwargs):
                return instruments

            def query_stock_meta_many(self, ids, **kwargs):
                return {3: dict(name="测试", listed_days=500, is_st=False, delisting_risk=False)}

        candidates, cohort = data._load_cohort(Store(), CUTOFF)
        self.assertEqual([row["code"] for row in candidates], ["600000"])
        self.assertEqual([row["reason"] for row in cohort["excluded"]],
                         ["invalid_identity", "invalid_identity", "invalid_identity"])
        self.assertEqual(cohort.get("scope_excluded", []), [])


if __name__ == "__main__":
    unittest.main()
