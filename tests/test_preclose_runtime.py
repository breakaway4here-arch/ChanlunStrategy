import hashlib
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from chanlun.preclose_contract import build_preclose_snapshot
from chanlun.preclose_pipeline import PreclosePipelineComponents
from chanlun.preclose_runtime import (
    MARKET_INDICES,
    _append_intraday_quote,
    build_scheduled_preclose_input,
    fetch_preclose_30m,
    select_preclose_30m_targets,
)
from preclose_run import PrecloseRunLock, run_scheduled_preclose


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
    @staticmethod
    def _minute_payload(trade_date, close, source):
        clocks = (
            "10:00:00", "10:30:00", "11:00:00", "11:30:00",
            "13:30:00", "14:00:00", "14:30:00", "15:00:00",
        )
        dates = []
        for day in (
            "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26",
            "2026-08-27",
        ):
            dates.extend("{} {}".format(day, clock) for clock in clocks)
        dates.extend(
            "{} {}".format(trade_date, clock) for clock in clocks[:7]
        )
        values = [float(close)] * len(dates)
        return {
            "dates": dates,
            "opens": values,
            "highs": [value + 0.1 for value in values],
            "lows": [value - 0.1 for value in values],
            "closes": values,
            "volumes": [1000.0] * len(values),
            "source": source,
        }

    def test_30m_fallback_rejects_stale_truthy_provider(self):
        stale = self._minute_payload("2026-08-27", 10.0, "sina")
        fresh = self._minute_payload(TRADE_DATE, 10.0, "eastmoney")
        with patch(
            "chanlun.data_fetcher._fetch_sina_minute_kline_remote",
            return_value=stale,
        ), patch(
            "chanlun.data_fetcher._fetch_eastmoney_minute_kline_remote",
            return_value=fresh,
        ):
            result = fetch_preclose_30m(
                [{"code": "300900", "name": "广联航空"}],
                TRADE_DATE,
                AS_OF,
                max_workers=1,
            )

        self.assertEqual(result["300900"]["status"], "available")
        self.assertEqual(
            result["300900"]["klines"]["source"], "eastmoney"
        )
    def test_intraday_quote_is_scaled_into_formal_qfq_basis(self):
        history = _history("300900", "广联航空", 3.81)
        history["klines"]["adjustment"] = "qfq"
        adjusted_previous_close = history["klines"]["closes"][-1]
        raw_previous_close = adjusted_previous_close * 2.0
        quote = {
            "code": "300900",
            "name": "广联航空",
            "industry": "航空装备",
            "is_st": False,
            "listed_date": "20201029",
            "prev_close": raw_previous_close,
            "open": raw_previous_close * 0.98,
            "high": raw_previous_close * 1.05,
            "low": raw_previous_close * 0.97,
            "current_price": raw_previous_close * 1.02,
            "volume": 2000,
            "amount": 20000000,
            "change_pct": 2.0,
        }

        row = _append_intraday_quote(history, quote, TRADE_DATE, AS_OF)

        self.assertIsNotNone(row)
        self.assertAlmostEqual(
            row["klines"]["closes"][-1], adjusted_previous_close * 1.02
        )
        self.assertAlmostEqual(row["price_basis"]["factor_vs_raw"], 0.5)
        self.assertEqual(row["price_basis"]["adjustment"], "qfq")
        self.assertEqual(row["klines"]["adjustment"], "qfq")

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

    def test_target_selector_keeps_classic_common_upstream_and_independent_right_side(self):
        rows = [
            _history("300998", "公共上游", 10.0),
            _history("002328", "右侧独立", 11.0),
        ]
        calls = {}

        def analyze(**kwargs):
            closes = np.asarray(kwargs["closes"], dtype=float)
            return SimpleNamespace(
                code=kwargs["code"],
                name=kwargs["name"],
                closes=closes,
            )

        def daily_pool(results, sector_stocks=None, mode="pure"):
            del sector_stocks, mode
            return [{"code": results[0].code}], {}

        def classic_pool(results, sector_stocks=None):
            del sector_stocks
            calls["classic"] = [row.code for row in results]
            return [], [], {}

        def right_pool(results, sector_stocks=None):
            del sector_stocks
            calls["right"] = [row.code for row in results]
            return [{"code": results[1].code}], [], {}

        components = PreclosePipelineComponents(
            analyze=analyze,
            build_daily_structure_pool=daily_pool,
            build_strong_startup_pool=classic_pool,
            build_right_side_startup_pool=right_pool,
            right_side_startup_mode="shadow",
        )
        targets = select_preclose_30m_targets(rows, components=components)

        self.assertEqual(["300998"], calls["classic"])
        self.assertEqual(["300998", "002328"], calls["right"])
        self.assertEqual(
            ["300998", "002328"], [row["code"] for row in targets]
        )

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
        self.assertEqual(
            result["runtime_diagnostics"]["daily_splice"],
            {
                "requested_count": 2,
                "available_count": 2,
                "coverage": 1.0,
                "minimum_coverage": 0.9,
                "excluded_by_reason": {},
                "excluded_codes": [],
            },
        )
        self.assertNotIn("psy12", result)

    def test_daily_splice_below_90_percent_coverage_fails_closed(self):
        histories = [
            _history(str(300000 + index), "样本{}".format(index), 10.0 + index)
            for index in range(10)
        ]
        quotes = []
        for row in histories[:8]:
            previous = row["klines"]["closes"][-1]
            quotes.append({
                "code": row["code"],
                "name": row["name"],
                "industry": "测试行业",
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
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "market.sqlite"
            db.write_bytes(b"formal-read-only-sentinel")
            with self.assertRaisesRegex(RuntimeError, "daily splice coverage"):
                build_scheduled_preclose_input(
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
                    target_selector=lambda _rows: [],
                    min30_fetcher=lambda *_args: {},
                    turnover_loader=lambda *_args: [100.0, 120.0, 140.0],
                )

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
            timings_path = base / "preclose" / TRADE_DATE / "timings.json"
            self.assertTrue(input_path.is_file())
            self.assertTrue(snapshot_path.is_file())
            timings = json.loads(timings_path.read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), hashlib.sha256(b"formal-sentinel").hexdigest())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(configs), 1)
        self.assertLessEqual(configs[0].deadline_seconds, 82.0)
        self.assertEqual(
            set(timings["phase_seconds"]),
            {"input_acquisition", "pipeline", "delivery"},
        )
        self.assertTrue(
            all(value >= 0 for value in timings["phase_seconds"].values())
        )
        self.assertEqual(timings["run_id"], configs[0].run_id)
        self.assertEqual(timings["source_sha"], "release-sha")
        self.assertEqual(timings["status"], "empty")

    def test_1445_start_uses_extended_budget_without_crossing_1449_cutoff(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 45, 2, tzinfo=cn_timezone)
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
        }
        configs = []

        def pipeline_runner(_inputs, config, components=None):
            del _inputs, components
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

        self.assertEqual("completed", result["status"])
        self.assertEqual(1, len(configs))
        self.assertGreater(configs[0].deadline_seconds, 120.0)
        self.assertLessEqual(configs[0].deadline_seconds, 202.0)

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

    def test_scheduled_late_start_skips_acquisition_when_reserve_exhausts_window(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 48, 40, tzinfo=cn_timezone)
        acquisition_calls = []
        pipeline_calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")

            def runtime_builder(*_args, **_kwargs):
                acquisition_calls.append(True)
                return {
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
                }

            def pipeline_runner(*_args, **_kwargs):
                pipeline_calls.append(True)
                raise AssertionError("late start must not enter the pipeline")

            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=runtime_builder,
                pipeline_runner=pipeline_runner,
                skip_publish=True,
            )
            day_root = base / "preclose" / TRADE_DATE
            snapshot = json.loads(
                (day_root / "snapshot.json").read_text(encoding="utf-8")
            )

        self.assertEqual(acquisition_calls, [])
        self.assertEqual(pipeline_calls, [])
        self.assertEqual(result["status"], "deadline_exceeded")
        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(snapshot["status"], "deadline_exceeded")

    def test_scheduled_lock_covers_acquisition_and_preserves_existing_input(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "preclose"
            day_root = root / TRADE_DATE
            day_root.mkdir(parents=True)
            input_path = day_root / "input.json"
            input_path.write_bytes(b"existing-input-sentinel\n")
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            lock = PrecloseRunLock(day_root / "run.lock", run_id="first-run")
            self.assertTrue(lock.acquire())
            try:
                result = run_scheduled_preclose(
                    root=root,
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: fixed_now,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: calls.append("fetch"),
                    skip_publish=True,
                )
            finally:
                lock.release()

            self.assertEqual(result["status"], "locked")
            self.assertEqual(result["exit_code"], 75)
            self.assertEqual(calls, [])
            self.assertEqual(input_path.read_bytes(), b"existing-input-sentinel\n")

    def test_scheduled_entry_fails_closed_when_wall_clock_reaches_1449_before_pipeline(self):
        cn_timezone = timezone(timedelta(hours=8))
        start = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        cutoff = datetime(2026, 8, 28, 14, 49, 0, tzinfo=cn_timezone)
        now_calls = [0]

        def wall_clock():
            now_calls[0] += 1
            return start if now_calls[0] == 1 else cutoff

        market_inputs = {
            "schema_version": "preclose-input-v1",
            "mode": "preclose_advisory",
            "trade_date": TRADE_DATE,
            "as_of": start.isoformat(timespec="seconds"),
            "bar_state": "intraday",
            "is_final": False,
            "daily": [],
            "target_codes": [],
            "min30": {},
            "market": {},
        }
        pipeline_calls = []

        def pipeline_runner(*_args, **_kwargs):
            pipeline_calls.append("pipeline")
            raise AssertionError("pipeline must not start at or after 14:49")

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=wall_clock,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: market_inputs,
                pipeline_runner=pipeline_runner,
                skip_publish=True,
            )
            day_root = base / "preclose" / TRADE_DATE
            snapshot = json.loads(
                (day_root / "snapshot.json").read_text(encoding="utf-8")
            )
            failure = json.loads(
                (day_root / "failure.json").read_text(encoding="utf-8")
            )

        self.assertEqual(pipeline_calls, [])
        self.assertEqual(result["status"], "deadline_exceeded")
        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(snapshot["status"], "deadline_exceeded")
        self.assertEqual(failure["error_type"], "DeliveryReserveReached")
        self.assertEqual(result["snapshot_id"], snapshot["snapshot_id"])

    def test_scheduled_wall_alarm_interrupts_one_stuck_pipeline_stage(self):
        cn_timezone = timezone(timedelta(hours=8))
        near_cutoff = datetime(
            2026, 8, 28, 14, 48, 59, 950000, tzinfo=cn_timezone
        )
        market_inputs = {
            "schema_version": "preclose-input-v1",
            "mode": "preclose_advisory",
            "trade_date": TRADE_DATE,
            "as_of": near_cutoff.isoformat(timespec="seconds"),
            "bar_state": "intraday",
            "is_final": False,
            "daily": [],
            "target_codes": [],
            "min30": {},
            "market": {},
        }

        def stuck_pipeline(*_args, **_kwargs):
            time.sleep(0.20)
            raise AssertionError("wall alarm did not interrupt the pipeline")

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            started = time.monotonic()
            with patch("preclose_run.DELIVERY_RESERVE_SECONDS", 0.0):
                result = run_scheduled_preclose(
                    root=base / "preclose",
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: near_cutoff,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: market_inputs,
                    pipeline_runner=stuck_pipeline,
                    skip_publish=True,
                )
            elapsed = time.monotonic() - started
            snapshot = json.loads(
                (base / "preclose" / TRADE_DATE / "snapshot.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertLess(elapsed, 0.18)
        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)
        self.assertGreaterEqual(snapshot["diagnostics"]["elapsed_seconds"], 0.03)

    def test_scheduled_fallback_freeze_cannot_overrun_1449_hard_cutoff(self):
        cn_timezone = timezone(timedelta(hours=8))
        near_cutoff = datetime(
            2026, 8, 28, 14, 48, 59, 950000, tzinfo=cn_timezone
        )
        market_inputs = {
            "schema_version": "preclose-input-v1",
            "mode": "preclose_advisory",
            "trade_date": TRADE_DATE,
            "as_of": near_cutoff.isoformat(timespec="seconds"),
            "bar_state": "intraday",
            "is_final": False,
            "daily": [],
            "target_codes": [],
            "min30": {},
            "market": {},
        }
        publisher_calls = []

        def blocked_atomic_write(*_args, **_kwargs):
            time.sleep(0.30)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            started = time.monotonic()
            with patch("preclose_run._atomic_json", blocked_atomic_write):
                result = run_scheduled_preclose(
                    root=base / "preclose",
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: near_cutoff,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: market_inputs,
                    publisher=lambda *_args, **_kwargs: publisher_calls.append(True),
                    notify=False,
                    skip_publish=True,
                )
            elapsed = time.monotonic() - started

            snapshot_path = base / "preclose" / TRADE_DATE / "snapshot.json"
            failure_path = base / "preclose" / TRADE_DATE / "failure.json"
            evidence_path = base / "preclose" / TRADE_DATE / "run-evidence.jsonl"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            evidence = [
                json.loads(line)
                for line in evidence_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertLess(elapsed, 0.18)
        self.assertEqual(result["status"], "deadline_exceeded")
        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(
            Path(result["snapshot_path"]).resolve(), snapshot_path.resolve()
        )
        self.assertEqual(snapshot["status"], "deadline_exceeded")
        self.assertEqual(snapshot["source_sha"], "release-sha")
        self.assertEqual(failure["status"], "deadline_exceeded")
        self.assertEqual(failure["source_sha"], "release-sha")
        self.assertEqual(failure["run_id"], snapshot["run_id"])
        self.assertEqual(failure["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(
            [row["event"] for row in evidence],
            ["started", "finished"],
        )
        self.assertEqual(evidence[-1]["status"], "deadline_exceeded")
        self.assertIn("elapsed_seconds", evidence[-1])
        self.assertEqual(publisher_calls, [])

    def test_scheduled_fallback_write_error_promotes_prepared_empty_evidence(self):
        cn_timezone = timezone(timedelta(hours=8))
        near_cutoff = datetime(
            2026, 8, 28, 14, 48, 59, 950000, tzinfo=cn_timezone
        )
        market_inputs = {
            "schema_version": "preclose-input-v1",
            "mode": "preclose_advisory",
            "trade_date": TRADE_DATE,
            "as_of": near_cutoff.isoformat(timespec="seconds"),
            "bar_state": "intraday",
            "is_final": False,
            "daily": [],
            "target_codes": [],
            "min30": {},
            "market": {},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            with patch("preclose_run.DELIVERY_RESERVE_SECONDS", 0.0), patch(
                "preclose_run._atomic_json",
                side_effect=OSError("fixture write failure"),
            ):
                result = run_scheduled_preclose(
                    root=base / "preclose",
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: near_cutoff,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: market_inputs,
                    notify=False,
                    skip_publish=True,
                )
            day_root = base / "preclose" / TRADE_DATE
            snapshot = json.loads(
                (day_root / "snapshot.json").read_text(encoding="utf-8")
            )
            failure = json.loads(
                (day_root / "failure.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(snapshot["status"], "deadline_exceeded")
        self.assertEqual(failure["stage"], "fallback_freeze")
        self.assertEqual(failure["error_type"], "OSError")

    def test_scheduled_delivery_budget_is_bounded_by_monotonic_total(self):
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
        }
        clock_values = iter((0.0, 241.0))
        publisher_calls = []

        def monotonic():
            try:
                return next(clock_values)
            except StopIteration:
                return 241.0

        def publisher(*_args, **_kwargs):
            publisher_calls.append(True)
            return {"publish": {"success": True}, "notifications": {}}

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            with patch("preclose_run.DELIVERY_RESERVE_SECONDS", 0.0):
                result = run_scheduled_preclose(
                    root=base / "preclose",
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: fixed_now,
                    monotonic=monotonic,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: market_inputs,
                    publisher=publisher,
                    notify=False,
                )

            delivery_path = base / "preclose" / TRADE_DATE / "delivery.json"

        self.assertEqual(publisher_calls, [])
        self.assertEqual(result["status"], "deadline_exceeded")
        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(delivery_path.exists())

    def test_scheduled_pipeline_exception_freezes_failed_snapshot_and_releases_lock(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        market_inputs = {
            "schema_version": "preclose-input-v1",
            "mode": "preclose_advisory",
            "trade_date": TRADE_DATE,
            "as_of": fixed_now.isoformat(timespec="seconds"),
        }

        def pipeline_runner(*_args, **_kwargs):
            raise ValueError("pipeline fixture failure")

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
            snapshot_path = base / "preclose" / TRADE_DATE / "snapshot.json"
            failure_path = base / "preclose" / TRADE_DATE / "failure.json"
            prepared_path = (
                base / "preclose" / TRADE_DATE / "prepared-deadline.json"
            )
            lock_path = base / "preclose" / TRADE_DATE / "run.lock"

            self.assertTrue(snapshot_path.is_file())
            self.assertTrue(failure_path.is_file())
            self.assertFalse(prepared_path.exists())
            self.assertFalse(lock_path.exists())
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            failure = json.loads(failure_path.read_text(encoding="utf-8"))

        self.assertEqual(result["snapshot_status"], "failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(snapshot["diagnostics"]["failure"]["type"], "ValueError")
        self.assertEqual(failure["stage"], "pipeline")
        self.assertEqual(failure["error_type"], "ValueError")

    def test_delivery_evidence_write_error_still_records_terminal_run_evidence(self):
        import preclose_run as runtime_module

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
        }

        def pipeline_runner(_inputs, config, components=None):
            del components
            return build_preclose_snapshot(
                trade_date=config.trade_date,
                as_of=config.as_of,
                generated_at=config.generated_at,
                pools={"main": [], "h4_t3": [], "acceleration": []},
                source_sha=config.source_sha,
                run_id=config.run_id,
            )

        durable_json = runtime_module._durable_json

        def selective_evidence_failure(path, payload):
            if Path(path).name == "delivery.json":
                raise OSError("fixture delivery evidence failure")
            return durable_json(path, payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            with patch(
                "preclose_run._durable_json",
                side_effect=selective_evidence_failure,
            ):
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
                    publisher=lambda *_args, **_kwargs: {
                        "publish": {"success": True},
                        "notifications": {},
                    },
                    notify=False,
                )
            day_root = base / "preclose" / TRADE_DATE
            timings = json.loads(
                (day_root / "timings.json").read_text(encoding="utf-8")
            )
            failure = json.loads(
                (day_root / "failure.json").read_text(encoding="utf-8")
            )
            evidence = [
                json.loads(line)
                for line in (day_root / "run-evidence.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["run_status"], "delivery_failed")
        self.assertEqual(result["delivery_evidence_error"], "OSError")
        self.assertEqual(timings["status"], "delivery_failed")
        self.assertEqual(failure["stage"], "delivery_evidence")
        self.assertEqual(failure["error_type"], "OSError")
        self.assertEqual(evidence[-1]["status"], "delivery_failed")

    def test_scheduled_existing_snapshot_retries_publish_without_reacquiring_input(self):
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
        }

        def pipeline_runner(_inputs, config, components=None):
            del components
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
            root = base / "preclose"
            first = run_scheduled_preclose(
                root=root,
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
            publisher_calls = []

            def publisher(*_args, **_kwargs):
                publisher_calls.append(True)
                return {"publish": {"success": True}, "notifications": {}}

            second = run_scheduled_preclose(
                root=root,
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("existing snapshot must skip acquisition")
                ),
                pipeline_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("existing snapshot must skip pipeline")
                ),
                publisher=publisher,
                notify=False,
            )
            delivery = json.loads(
                (root / TRADE_DATE / "delivery.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(first["snapshot_status"], "empty")
        self.assertEqual(publisher_calls, [True])
        self.assertEqual(second["status"], "already_completed")
        self.assertEqual(second["exit_code"], 0)
        self.assertEqual(second["snapshot_status"], first["snapshot_status"])
        self.assertEqual(second["snapshot_id"], first["snapshot_id"])
        self.assertEqual(second["content_hash"], first["content_hash"])
        self.assertEqual(delivery["snapshot_id"], first["snapshot_id"])
        self.assertEqual(delivery["content_hash"], first["content_hash"])

    def test_scheduled_existing_malformed_snapshot_fails_closed_without_publisher(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        publisher_calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            day_root = base / "preclose" / TRADE_DATE
            day_root.mkdir(parents=True)
            snapshot_path = day_root / "snapshot.json"
            snapshot_path.write_text("{malformed-json", encoding="utf-8")

            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("malformed snapshot must skip acquisition")
                ),
                pipeline_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("malformed snapshot must skip pipeline")
                ),
                publisher=lambda *_args, **_kwargs: publisher_calls.append(True),
                notify=False,
            )
            delivery = json.loads(
                (day_root / "delivery.json").read_text(encoding="utf-8")
            )

            self.assertEqual(snapshot_path.read_text(encoding="utf-8"), "{malformed-json")

        self.assertEqual(publisher_calls, [])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["snapshot_status"], "failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(delivery["error"], "InvalidPrecloseSnapshot")

    def test_scheduled_existing_hash_mismatch_fails_closed_without_publisher(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        publisher_calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            day_root = base / "preclose" / TRADE_DATE
            day_root.mkdir(parents=True)
            snapshot = build_preclose_snapshot(
                trade_date=TRADE_DATE,
                as_of=fixed_now.isoformat(timespec="seconds"),
                generated_at=fixed_now.isoformat(timespec="seconds"),
                pools={"main": [], "h4_t3": [], "acceleration": []},
                source_sha="release-sha",
                run_id="forged-retry",
            )
            snapshot["status"] = "available"
            (day_root / "snapshot.json").write_text(
                json.dumps(snapshot), encoding="utf-8"
            )
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                publisher=lambda *_args, **_kwargs: publisher_calls.append(True),
                notify=False,
            )

        self.assertEqual(publisher_calls, [])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 1)

    def test_scheduled_existing_deadline_snapshot_keeps_nonzero_exit_after_publish(self):
        cn_timezone = timezone(timedelta(hours=8))
        fixed_now = datetime(2026, 8, 28, 14, 47, 2, tzinfo=cn_timezone)
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            day_root = base / "preclose" / TRADE_DATE
            day_root.mkdir(parents=True)
            snapshot = build_preclose_snapshot(
                trade_date=TRADE_DATE,
                as_of=fixed_now.isoformat(timespec="seconds"),
                generated_at=fixed_now.isoformat(timespec="seconds"),
                pools={"main": [], "h4_t3": [], "acceleration": []},
                source_sha="release-sha",
                status="deadline_exceeded",
                run_id="deadline-retry",
            )
            (day_root / "snapshot.json").write_text(
                json.dumps(snapshot), encoding="utf-8"
            )
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                publisher=lambda *_args, **_kwargs: {
                    "publish": {"success": True}, "notifications": {}
                },
                notify=False,
            )

        self.assertEqual(result["status"], "already_completed")
        self.assertEqual(result["snapshot_status"], "deadline_exceeded")
        self.assertEqual(result["exit_code"], 1)

    def test_scheduled_lock_remains_held_through_publish(self):
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
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "preclose"
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")

            def pipeline_runner(_inputs, config, components=None):
                del _inputs, components
                return build_preclose_snapshot(
                    trade_date=config.trade_date,
                    as_of=config.as_of,
                    generated_at=config.generated_at,
                    pools={"main": [], "h4_t3": [], "acceleration": []},
                    source_sha=config.source_sha,
                    run_id=config.run_id,
                )

            def publisher(_snapshot_path, **kwargs):
                self.assertGreater(kwargs["timeout"], 0)
                self.assertTrue((root / TRADE_DATE / "run.lock").is_file())
                return {"publish": {"success": True}, "notifications": {}}

            result = run_scheduled_preclose(
                root=root,
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: fixed_now,
                monotonic=lambda: 10.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: market_inputs,
                pipeline_runner=pipeline_runner,
                publisher=publisher,
                notify=False,
            )

            self.assertFalse((root / TRADE_DATE / "run.lock").exists())
        self.assertEqual(result["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
