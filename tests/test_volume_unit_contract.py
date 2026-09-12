import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from chanlun import data_fetcher
from chanlun.kline_repository import KLineRepository
from chanlun.market_history_store import MarketHistoryStore
from run import _money20_from_amounts, _serialize_amount_list


class _Response:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class VolumeUnitContractTests(unittest.TestCase):
    def test_sina_daily_shares_are_normalized_to_hands_without_rounding(self):
        payload = [
            {
                "day": "2026-08-07",
                "open": "127.14",
                "close": "129.38",
                "high": "130.90",
                "low": "125.23",
                "volume": "2433251",
            }
        ]
        with patch.object(data_fetcher.SESSION, "get", return_value=_Response(payload)):
            kline = data_fetcher._fetch_daily_kline_sina_daily_remote(
                "301682", count=1
            )

        self.assertEqual(float(kline["volumes"][0]), 24332.51)
        self.assertEqual(kline["volume_unit"], "hands")
        self.assertEqual(kline["volume_raw_unit"], "shares")
        self.assertEqual(kline["volume_source"], "sina")

    def test_eastmoney_daily_keeps_hands_and_amount_cny(self):
        payload = {
            "data": {
                "klines": [
                    "2026-08-07,127.14,129.38,130.90,125.23,24333,312529700,0,0,0,0,0"
                ]
            }
        }
        with patch.object(
            data_fetcher.SESSION, "get", return_value=_Response(payload)
        ):
            kline = data_fetcher._fetch_daily_kline_eastmoney_remote(
                "301682", count=1
            )

        self.assertEqual(float(kline["volumes"][0]), 24333.0)
        self.assertEqual(kline["volume_unit"], "hands")
        self.assertEqual(kline["volume_raw_unit"], "hands")
        self.assertEqual(kline["amount_unit"], "CNY")
        self.assertEqual(float(kline["amounts"][0]), 312529700.0)

    def test_daily_repository_prefers_known_hands_source_over_unknown_tencent(self):
        def tencent(identity, count=3):
            return {
                "dates": ["2026-08-07"],
                "opens": [127.14],
                "highs": [130.90],
                "lows": [125.23],
                "closes": [129.38],
                "volumes": [24333.0],
                "volume_unit": "unknown",
                "source": "tencent",
            }

        def eastmoney(identity, count=3):
            return {
                "dates": ["2026-08-07"],
                "opens": [127.14],
                "highs": [130.90],
                "lows": [125.23],
                "closes": [129.38],
                "volumes": [24333.0],
                "amounts": [312529700.0],
                "amount_available": [True],
                "volume_unit": "hands",
                "volume_raw_unit": "hands",
                "volume_source": "eastmoney",
                "amount_unit": "CNY",
                "amount_source": "eastmoney",
                "source": "eastmoney",
            }

        def sina(identity, count=3):
            return None

        with patch.object(data_fetcher, "_fetch_daily_kline_remote", side_effect=tencent), patch.object(
            data_fetcher, "_fetch_daily_kline_eastmoney_remote", side_effect=eastmoney
        ), patch.object(
            data_fetcher, "_fetch_daily_kline_sina_daily_remote", side_effect=sina
        ):
            kline = data_fetcher._fetch_daily_for_repository("301682", 1)

        self.assertEqual(kline["source"], "eastmoney")
        self.assertEqual(kline["volume_unit"], "hands")
        self.assertEqual(float(kline["volumes"][0]), 24333.0)

    def test_daily_repository_validates_date_before_preferring_known_unit(self):
        def tencent(identity, count=3):
            return None

        def eastmoney(identity, count=3):
            return {
                "dates": ["2026-08-07", "2026-08-09"],
                "opens": [127.14, 128.0],
                "highs": [130.90, 131.0],
                "lows": [125.23, 127.0],
                "closes": [129.38, 130.0],
                "volumes": [24333.0, 25000.0],
                "volume_unit": "hands",
                "volume_raw_unit": "hands",
                "volume_source": "eastmoney",
                "source": "eastmoney",
            }

        def sina(identity, count=3):
            return {
                "dates": ["2026-08-09", "2026-08-10"],
                "opens": [128.0, 129.0],
                "highs": [131.0, 132.0],
                "lows": [127.0, 128.0],
                "closes": [130.0, 131.0],
                "volumes": [25000.0, 26000.0],
                "volume_unit": "hands",
                "volume_raw_unit": "shares",
                "volume_source": "sina",
                "source": "sina",
            }

        with patch.object(
            data_fetcher, "_fetch_daily_kline_remote", side_effect=tencent
        ), patch.object(
            data_fetcher,
            "_fetch_daily_kline_eastmoney_remote",
            side_effect=eastmoney,
        ), patch.object(
            data_fetcher,
            "_fetch_daily_kline_sina_daily_remote",
            side_effect=sina,
        ):
            kline = data_fetcher._fetch_daily_for_repository(
                "301682",
                2,
                required_date="2026-08-10",
                as_of="2026-08-10T15:00:00+08:00",
            )

        self.assertEqual(kline["source"], "sina")
        self.assertEqual(kline["volume_unit"], "hands")
        self.assertEqual(kline["_provider_rejections"], [
            {"source": "eastmoney", "reason": "latest_date_mismatch"}
        ])

    def test_daily_repository_prefers_latest_valid_cutoff_before_unit_priority(self):
        def tencent(identity, count=3):
            return None

        def eastmoney(identity, count=3):
            return {
                "dates": ["2026-08-08"],
                "opens": [127.14],
                "highs": [130.90],
                "lows": [125.23],
                "closes": [129.38],
                "volumes": [24333.0],
                "volume_unit": "hands",
                "volume_raw_unit": "hands",
                "volume_source": "eastmoney",
                "source": "eastmoney",
            }

        def sina(identity, count=3):
            return {
                "dates": ["2026-08-08", "2026-08-09"],
                "opens": [127.14, 128.0],
                "highs": [130.90, 131.0],
                "lows": [125.23, 127.0],
                "closes": [129.38, 130.0],
                "volumes": [24333.0, 26000.0],
                "volume_unit": "hands",
                "volume_raw_unit": "shares",
                "volume_source": "sina",
                "source": "sina",
            }

        with patch.object(
            data_fetcher, "_fetch_daily_kline_remote", side_effect=tencent
        ), patch.object(
            data_fetcher,
            "_fetch_daily_kline_eastmoney_remote",
            side_effect=eastmoney,
        ), patch.object(
            data_fetcher,
            "_fetch_daily_kline_sina_daily_remote",
            side_effect=sina,
        ):
            kline = data_fetcher._fetch_daily_for_repository(
                "301682", 1, as_of="2026-08-09T15:00:00+08:00"
            )

        self.assertEqual(kline["source"], "sina")
        self.assertEqual(kline["dates"][-1], "2026-08-09")

    def test_missing_amount_is_unavailable_and_not_a_zero_mean(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite"

            def remote(identity, count):
                return {
                    "dates": ["2026-08-07", "2026-08-10"],
                    "opens": [10.0, 11.0],
                    "highs": [10.2, 11.2],
                    "lows": [9.8, 10.8],
                    "closes": [10.1, 11.1],
                    "volumes": [100.0, 110.0],
                    "volume_unit": "hands",
                    "volume_raw_unit": "hands",
                    "volume_source": "fixture",
                    "source": "fixture",
                }

            repository = KLineRepository(
                db_path,
                remote_fetchers={"day": remote},
            )
            result = repository.get(
                "day", "301682", count=2, required_date="2026-08-10"
            )

            self.assertTrue(np.isnan(result.kline["amounts"]).all())
            with MarketHistoryStore(db_path, readonly=True) as store:
                instrument = store.resolve_instrument("stock", "SZ", "301682")
                rows = store.query_bars("day", instrument["instrument_id"])
            self.assertEqual([row["amount_available"] for row in rows], [0, 0])
            self.assertEqual(_serialize_amount_list([100.0, 0.0, float("nan")]), [100.0, None, None])
            self.assertEqual(_money20_from_amounts([100.0, 0.0, float("nan")]), 100.0)


if __name__ == "__main__":
    unittest.main()
