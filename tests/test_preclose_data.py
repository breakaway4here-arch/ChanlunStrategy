import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chanlun.preclose_data import (
    PrecloseDataPaths,
    build_intraday_daily_snapshot,
    build_preclose_market_inputs,
    fetch_target_30m_snapshots,
    write_preclose_input_snapshot,
)


TRADE_DATE = "2026-08-27"
AS_OF = "2026-08-27T14:47:08+08:00"


def _kline(dates, start=10.0, finals=None):
    size = len(dates)
    payload = {
        "dates": list(dates),
        "opens": [start + index for index in range(size)],
        "highs": [start + index + 1 for index in range(size)],
        "lows": [start + index - 1 for index in range(size)],
        "closes": [start + index + 0.5 for index in range(size)],
        "volumes": [1000 + index for index in range(size)],
        "source": "spy-market",
    }
    if finals is not None:
        payload["finals"] = list(finals)
    return payload


class SpyFetcher:
    def __init__(self, stale_30m=False):
        self.events = []
        self.stale_30m = stale_30m

    def fetch_daily_history(self, code, count):
        self.events.append(("daily_history", code, count))
        return _kline(["2026-08-25", "2026-08-26"])

    def fetch_intraday_daily(self, code, as_of):
        self.events.append(("intraday_daily", code, as_of))
        return _kline([TRADE_DATE], start=12.0, finals=[False])

    def fetch_30m(self, code, count, as_of):
        self.events.append(("30m", code, count, as_of))
        date = "2026-08-26" if self.stale_30m else TRADE_DATE
        return _kline(
            [date + " 14:30:00", date + " 15:00:00"],
            start=13.0,
            finals=[True, False],
        )

    def fetch_1m(self, *args, **kwargs):
        raise AssertionError("1m must not enter the pre-close data path")

    def fetch_5m(self, *args, **kwargs):
        raise AssertionError("5m must not enter the pre-close data path")

    def fetch_15m(self, *args, **kwargs):
        raise AssertionError("15m must not enter the pre-close data path")

    def fetch_news(self, *args, **kwargs):
        raise AssertionError("news must not enter the pre-close data path")

    def fetch_llm(self, *args, **kwargs):
        raise AssertionError("LLM must not enter the pre-close data path")

    def fetch_iwencai(self, *args, **kwargs):
        raise AssertionError("iWencai must not enter the pre-close data path")


class PrecloseDataTests(unittest.TestCase):
    def setUp(self):
        self.universe = [
            {"code": "300998", "name": "宁波方正", "sector": "汽车零部件"},
            {"code": "002328", "name": "新朋股份", "sector": "机械"},
        ]

    def test_daily_snapshot_is_intraday_and_non_final(self):
        fetcher = SpyFetcher()
        rows = build_intraday_daily_snapshot(
            self.universe,
            fetcher=fetcher,
            trade_date=TRADE_DATE,
            as_of=AS_OF,
            history_count=120,
        )

        self.assertEqual([row["code"] for row in rows], ["300998", "002328"])
        self.assertTrue(all(row["status"] == "available" for row in rows))
        self.assertTrue(all(row["bar_state"] == "intraday" for row in rows))
        self.assertTrue(all(row["is_final"] is False for row in rows))
        self.assertTrue(all(row["as_of"] == AS_OF for row in rows))
        self.assertTrue(all(row["klines"]["dates"][-1] == TRADE_DATE for row in rows))
        self.assertTrue(all(row["klines"]["finals"][-1] is False for row in rows))

    def test_daily_filter_runs_before_30m_and_only_targets_are_fetched(self):
        fetcher = SpyFetcher()

        def select_daily_targets(rows):
            fetcher.events.append(("daily_filter", tuple(row["code"] for row in rows)))
            return [rows[1]]

        result = build_preclose_market_inputs(
            self.universe,
            fetcher=fetcher,
            select_daily_targets=select_daily_targets,
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )

        event_names = [event[0] for event in fetcher.events]
        self.assertEqual(event_names.count("daily_history"), 2)
        self.assertEqual(event_names.count("intraday_daily"), 2)
        self.assertEqual(event_names.count("30m"), 1)
        self.assertLess(event_names.index("daily_filter"), event_names.index("30m"))
        self.assertEqual(fetcher.events[-1][1], "002328")
        self.assertEqual(result["target_codes"], ["002328"])
        self.assertEqual(list(result["min30"]), ["002328"])
        self.assertEqual(result["min30"]["002328"]["status"], "available")
        self.assertEqual(
            result["min30"]["002328"]["klines"]["dates"],
            [f"{TRADE_DATE} 14:30:00"],
        )
        self.assertEqual(
            result["min30"]["002328"]["klines"]["finals"],
            [True],
        )
        self.assertFalse(result["min30"]["002328"]["is_final"])

    def test_missing_current_30m_is_auditable_and_never_uses_stale_cache(self):
        fetcher = SpyFetcher(stale_30m=True)
        result = fetch_target_30m_snapshots(
            self.universe[:1],
            fetcher=fetcher,
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )

        evidence = result["300998"]
        self.assertEqual(evidence["status"], "unavailable")
        self.assertEqual(evidence["reason_code"], "current_trade_date_missing")
        self.assertEqual(evidence["latest_date"], "2026-08-26")
        self.assertNotIn("klines", evidence)

    def test_future_only_30m_is_unavailable_after_as_of_cutoff(self):
        class FutureOnlyFetcher(SpyFetcher):
            def fetch_30m(self, code, count, as_of):
                self.events.append(("30m", code, count, as_of))
                return _kline([TRADE_DATE + " 15:00:00"], start=13.0, finals=[False])

        result = fetch_target_30m_snapshots(
            self.universe[:1],
            fetcher=FutureOnlyFetcher(),
            trade_date=TRADE_DATE,
            as_of=AS_OF,
        )

        evidence = result["300998"]
        self.assertEqual(evidence["status"], "unavailable")
        self.assertEqual(evidence["reason_code"], "current_trade_date_missing")
        self.assertNotIn("klines", evidence)

    def test_isolated_paths_write_only_preclose_namespace_and_open_formal_db_readonly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            formal_db = root / "market_history.sqlite"
            connection = sqlite3.connect(str(formal_db))
            connection.execute("CREATE TABLE sentinel (value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES ('formal')")
            connection.commit()
            connection.close()
            before = hashlib.sha256(formal_db.read_bytes()).hexdigest()

            paths = PrecloseDataPaths(
                root=root / ".cache/chanlun/preclose",
                formal_market_db=formal_db,
            )
            with paths.open_formal_market_db() as readonly:
                self.assertEqual(readonly.execute("SELECT value FROM sentinel").fetchone()[0], "formal")
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO sentinel VALUES ('mutated')")

            payload = {
                "schema_version": "preclose-input-v1",
                "trade_date": TRADE_DATE,
                "as_of": AS_OF,
                "bar_state": "intraday",
                "is_final": False,
            }
            written = write_preclose_input_snapshot(paths, payload)
            self.assertEqual(written, paths.root / TRADE_DATE / "input.json")
            self.assertEqual(json.loads(written.read_text(encoding="utf-8")), payload)
            self.assertEqual(hashlib.sha256(formal_db.read_bytes()).hexdigest(), before)

            with self.assertRaises(ValueError):
                PrecloseDataPaths(root=root / "docs/preclose", formal_market_db=formal_db)
            with self.assertRaises(ValueError):
                PrecloseDataPaths(root=formal_db, formal_market_db=formal_db)
            with self.assertRaises(ValueError):
                PrecloseDataPaths(
                    root=root / "recommendation_ledger.jsonl",
                    formal_market_db=formal_db,
                )


if __name__ == "__main__":
    unittest.main()
