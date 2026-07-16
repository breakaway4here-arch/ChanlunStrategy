import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from chanlun.market_history_store import MarketHistoryStore
from chanlun.universe_builder import UniverseConfig
from scripts.build_historical_funnel_runs import (
    materialize_historical_meta_proxies,
    replay_historical_funnel,
)


def _bar(ts, close):
    return {
        "ts": ts,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1_000_000,
        "amount": 100_000_000,
        "adjustment": "qfq",
        "is_final": True,
        "source_batch": "fixture",
    }


class HistoricalFunnelReplayTest(unittest.TestCase):
    def test_replay_uses_signal_date_snapshot_and_labels_metadata_proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            signal_date = "2026-07-10"
            with MarketHistoryStore(path) as store:
                instrument_id = store.upsert_instrument(
                    "stock", "SZ", "000001", "平安银行"
                )
                end = date.fromisoformat(signal_date)
                bars = [
                    _bar(
                        (end - timedelta(days=69 - index)).isoformat(),
                        10.0 + index * 0.01,
                    )
                    for index in range(70)
                ]
                bars.append(_bar("2026-07-13", 99.0))
                store.upsert_bars(
                    "day", instrument_id, bars, adjustment="qfq"
                )
                store.upsert_stock_meta(
                    instrument_id,
                    "2026-07-16",
                    {
                        "name": "平安银行",
                        "listed_date": "19910403",
                        "listed_days": 12888,
                        "is_st": False,
                        "delisting_risk": False,
                    },
                )

                proxy = materialize_historical_meta_proxies(
                    store, [signal_date, "2026-07-13"]
                )
                result = replay_historical_funnel(
                    store,
                    signal_date,
                    universe_config=UniverseConfig(
                        low_quota=1,
                        trend_quota=0,
                        neutral_quota=0,
                        base_limit=1,
                        overlay_limit=0,
                        final_limit=1,
                    ),
                    include_30m=False,
                )

                run = store.get_funnel_run(result["run_id"])
                events = store.list_gate_events(result["run_id"])

        self.assertEqual(2, proxy["created"])
        self.assertTrue(run["metadata"]["is_official"])
        self.assertTrue(run["metadata"]["historical_replay"])
        self.assertTrue(run["metadata"]["historical_meta_proxy"])
        self.assertEqual(signal_date, run["as_of"])
        self.assertIn("minute30_target_codes", result)
        self.assertEqual(1, len(events))
        self.assertAlmostEqual(10.69, events[0]["close"], places=6)
        self.assertIn("retrieval", events[0]["passed_stages"])


if __name__ == "__main__":
    unittest.main()
