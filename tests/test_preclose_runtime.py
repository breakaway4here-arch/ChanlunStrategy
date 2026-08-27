import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

from chanlun.preclose_contract import build_preclose_snapshot
from chanlun.preclose_runtime import (
    MARKET_INDICES,
    build_scheduled_preclose_input,
    select_preclose_30m_targets,
)
from preclose_run import run_scheduled_preclose


TRADE_DATE = "2026-08-28"
AS_OF = "2026-08-28T14:47:02+08:00"


def _history(code, name, start):
    closes = [start + index * 0.01 for index in range(120)]
    return {
        "code": code,
        "name": name,
        "sector": "测试行业",
        "klines": {
            "dates": ["2026-08-27"] * 120,
            "opens": [value - 0.05 for value in closes],
            "highs": [value + 0.10 for value in closes],
            "lows": [value - 0.10 for value in closes],
            "closes": closes,
            "volumes": [1000.0] * 120,
            "amounts": [value * 100000 for value in closes],
            "finals": [True] * 120,
        },
    }


class PrecloseRuntimeTests(unittest.TestCase):
    def test_default_daily_target_selector_accepts_json_lists(self):
        rows = [_history("300998", "宁波方正", 10.0)]
        rows[0].update({
            "status": "available",
            "bar_state": "intraday",
            "is_final": False,
            "as_of": AS_OF,
        })
        rows[0]["klines"]["finals"][-1] = False
        targets = select_preclose_30m_targets(rows)
        self.assertIsInstance(targets, list)

    def test_live_builder_uses_batch_quotes_and_fetches_30m_only_for_daily_targets(self):
        histories = [
            _history("300998", "宁波方正", 10.0),
            _history("002328", "新朋股份", 11.0),
        ]
        quotes = []
        for row in histories:
            previous = row["klines"]["closes"][-1]
            quotes.append({
                "code": row["code"],
                "name": row["name"],
                "industry": "汽车零部件",
                "is_st": False,
                "listed_date": "20200101",
                "prev_close": previous,
                "open": previous,
                "high": previous + 0.2,
                "low": previous - 0.2,
                "current_price": previous + 0.1,
                "volume": 2000,
                "amount": 20000000,
                "change_pct": 1.0,
            })
        min30_calls = []

        def min30_fetcher(targets, trade_date, as_of):
            min30_calls.extend(row["code"] for row in targets)
            return {
                row["code"]: {
                    "status": "available",
                    "bar_state": "intraday",
                    "is_final": False,
                    "as_of": as_of,
                    "latest_date": trade_date,
                    "latest_ts": trade_date + " 14:30:00",
                    "klines": {
                        "dates": [trade_date + " 14:30:00"],
                        "opens": [10], "highs": [11], "lows": [9],
                        "closes": [10.5], "volumes": [1000],
                        "finals": [False],
                    },
                }
                for row in targets
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "market.sqlite"
            db.write_bytes(b"formal-read-only-sentinel")
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            forbidden = AssertionError("forbidden dependency entered runtime")
            with patch(
                "chanlun.data_fetcher.collect_15min_data", side_effect=forbidden
            ):
                result = build_scheduled_preclose_input(
                    TRADE_DATE,
                    AS_OF,
                    formal_market_db=db,
                    universe_loader=lambda *_args: (histories, {"source": "fixture"}),
                    quote_fetcher=lambda: (
                        quotes,
                        {
                            "complete": True,
                            "requested": len(quotes),
                            "unique": len(quotes),
                        },
                    ),
                    index_fetcher=lambda *_args: {
                        name: {
                            "code": code,
                            "close": 3100,
                            "change_pct": 1.0,
                            "closes": [3000, 3100],
                        }
                        for name, code in MARKET_INDICES.items()
                    },
                    target_selector=lambda rows: [rows[0]],
                    min30_fetcher=min30_fetcher,
                    turnover_loader=lambda *_args: [100.0, 120.0, 140.0],
                )

            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

        self.assertEqual(result["schema_version"], "preclose-input-v1")
        self.assertEqual(result["target_codes"], ["300998"])
        self.assertEqual(min30_calls, ["300998"])
        self.assertEqual(set(result["min30"]), {"300998"})
        self.assertEqual(len(result["daily"]), 2)
        self.assertTrue(all(row["bar_state"] == "intraday" for row in result["daily"]))
        self.assertTrue(all(row["is_final"] is False for row in result["daily"]))
        self.assertTrue(all(row["klines"]["finals"][-1] is False for row in result["daily"]))
        self.assertEqual(len(result["market"]["stock_bars"]), 2)
        self.assertNotIn("psy12", result)

    def test_incomplete_full_market_quote_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "market.sqlite"
            db.write_bytes(b"sentinel")
            with self.assertRaises(RuntimeError):
                build_scheduled_preclose_input(
                    TRADE_DATE,
                    AS_OF,
                    formal_market_db=db,
                    universe_loader=lambda *_args: ([], {}),
                    quote_fetcher=lambda: (
                        [],
                        {"complete": False, "requested": 6000, "unique": 0},
                    ),
                    index_fetcher=lambda *_args: {},
                    target_selector=lambda rows: [],
                    min30_fetcher=lambda *_args: {},
                    turnover_loader=lambda *_args: [],
                )

    def test_scheduled_entry_writes_isolated_input_and_preserves_total_budget(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        market_inputs = {
            "schema_version": "preclose-input-v1",
            "mode": "preclose_advisory",
            "trade_date": TRADE_DATE,
            "as_of": fixed_now.isoformat(timespec="seconds"),
            "bar_state": "intraday",
            "is_final": False,
            "daily": [],
            "target_codes": [],
            "min30": {},
            "market": {},
            "runtime_array": np.array([1.0, 2.0]),
        }
        configs = []

        def pipeline_runner(_inputs, config, components=None):
            del components
            self.assertEqual(_inputs["runtime_array"], [1.0, 2.0])
            configs.append(config)
            return build_preclose_snapshot(
                trade_date=config.trade_date,
                as_of=config.as_of,
                generated_at=config.generated_at,
                pools={"main": [], "h4_t3": [], "acceleration": []},
                source_sha=config.source_sha,
                run_id=config.run_id,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: market_inputs,
                pipeline_runner=pipeline_runner,
                skip_publish=True,
            )
            input_path = base / "preclose" / TRADE_DATE / "input.json"
            snapshot_path = base / "preclose" / TRADE_DATE / "snapshot.json"
            self.assertTrue(input_path.is_file())
            self.assertTrue(snapshot_path.is_file())
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), hashlib.sha256(b"formal-sentinel").hexdigest())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(configs), 1)
        self.assertLessEqual(configs[0].deadline_seconds, 118.0)

    def test_scheduled_entry_skips_non_trading_day_before_acquisition(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 29, 14, 47, 0, tzinfo=cn_timezone)
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                trading_day_check=lambda *_args: False,
                runtime_builder=lambda *_args, **_kwargs: calls.append("fetch"),
                skip_publish=True,
            )
        self.assertEqual(result["status"], "skipped_non_trading_day")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
