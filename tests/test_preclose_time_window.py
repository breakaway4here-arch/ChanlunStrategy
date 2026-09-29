import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from chanlun.preclose_contract import build_preclose_snapshot
from chanlun.preclose_pipeline import PreclosePipelineConfig, run_preclose_pipeline
import preclose_run
from preclose_run import (
    DELIVERY_RESERVE_SECONDS,
    MAX_PRE_CLOSE_RUNTIME_SECONDS,
    PRE_CLOSE_CUTOFF_TIME,
    PRE_CLOSE_START_TIME,
    _prepare_deadline_fallback,
    _promote_prepared_deadline_fallback,
    _run_preclose_locked,
    _scheduled_wall_budget,
    run_scheduled_preclose,
)


PRE_CLOSE_TIMEZONE = getattr(preclose_run, "PRE_CLOSE_TIMEZONE", None)
normalize_preclose_datetime = getattr(
    preclose_run, "normalize_preclose_datetime", lambda value: value
)


TRADE_DATE = "2026-08-28"
CN = timezone(timedelta(hours=8))
TOKYO = timezone(timedelta(hours=9))


def _market_inputs(trade_date=TRADE_DATE, as_of="2026-08-28T14:45:00+08:00"):
    return {
        "schema_version": "preclose-input-v1",
        "mode": "preclose_advisory",
        "trade_date": trade_date,
        "as_of": as_of,
        "bar_state": "intraday",
        "is_final": False,
        "daily": [],
        "target_codes": [],
        "min30": {},
        "market": {},
    }


def _empty_snapshot(config):
    return build_preclose_snapshot(
        trade_date=config.trade_date,
        as_of=config.as_of,
        generated_at=config.generated_at,
        pools={"main": [], "h4_t3": [], "acceleration": []},
        source_sha=config.source_sha,
        run_id=config.run_id,
    )


class PrecloseTimeWindowTests(unittest.TestCase):
    def test_scheduled_window_boundaries_allow_only_shanghai_half_open_window(self):
        cases = (
            ("14:44:59", "outside_preclose_window", False, False),
            ("14:45:00", "completed", True, True),
            ("14:55:59", "failed", False, True),
            ("14:56:00", "outside_preclose_window", False, False),
            ("14:56:01", "outside_preclose_window", False, False),
        )
        for clock, status, should_acquire, should_snapshot in cases:
            with self.subTest(clock=clock), tempfile.TemporaryDirectory() as temp_dir:
                current = datetime.fromisoformat(
                    "{}T{}+08:00".format(TRADE_DATE, clock)
                )
                calls = []
                base = Path(temp_dir)
                db = base / "market.sqlite"
                db.write_bytes(b"formal-sentinel")
                result = run_scheduled_preclose(
                    root=base / "preclose",
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: current,
                    monotonic=lambda: 0.0,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: calls.append(True)
                    or _market_inputs(as_of=current.isoformat(timespec="seconds")),
                    pipeline_runner=lambda _inputs, config, components=None: _empty_snapshot(config),
                    skip_publish=True,
                )
                snapshot_path = base / "preclose" / TRADE_DATE / "snapshot.json"
                self.assertEqual(result["status"], status)
                self.assertEqual(bool(calls), should_acquire)
                self.assertEqual(snapshot_path.exists(), should_snapshot)

    def test_candidate_snapshot_remains_available_until_publication_cutoff(self):
        from dataclasses import replace
        from tests.test_preclose_pipeline import _config, _components
        from tests.test_preclose_pipeline import _market_inputs as candidate_inputs

        for clock in ("14:49:00", "14:50:00", "14:55:59", "14:56:00", "14:56:01"):
            with self.subTest(clock=clock):
                config = replace(_config(), generated_at="2026-08-27T" + clock + "+08:00")
                snapshot = run_preclose_pipeline(
                    candidate_inputs(), config=config, components=_components()
                )
                expected = "available" if clock < "14:56:00" else "deadline_exceeded"
                self.assertEqual(snapshot["status"], expected)
                if expected == "available":
                    self.assertEqual([len(pool) for pool in snapshot["pools"].values()], [1, 1, 1])

    def test_pipeline_generated_at_cutoff_rejects_earlier_input(self):
        config = PreclosePipelineConfig(
            trade_date=TRADE_DATE,
            as_of="2026-08-28T14:45:00+08:00",
            generated_at="2026-08-28T14:56:00+08:00",
            source_sha="release-sha", run_id="generated-cutoff",
        )
        snapshot = run_preclose_pipeline(_market_inputs(), config=config)
        self.assertEqual(snapshot["status"], "deadline_exceeded")

    def test_publish_can_finish_at_145559_after_old_cutoff(self):
        phase = ["compute"]
        calls = []
        def clock():
            return datetime.fromisoformat("2026-08-28T" + (
                "14:50:00" if phase[0] == "compute" else "14:55:59"
            ) + "+08:00")
        def pipeline(_inputs, config, components=None):
            phase[0] = "publish"
            return _empty_snapshot(config)
        def publisher(*_args, **_kwargs):
            calls.append(True)
            return {"publish": {"success": True}}
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            result = run_scheduled_preclose(
                root=base / "preclose", formal_market_db=base / "market.sqlite",
                env_file=base / "missing.env", source_sha="release-sha",
                now=clock, monotonic=lambda: 0.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: _market_inputs(
                    as_of="2026-08-28T14:50:00+08:00"),
                pipeline_runner=pipeline, publisher=publisher, notify=False,
            )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(calls, [True])

    def test_window_constants_and_wall_budget_cover_new_boundaries(self):
        self.assertEqual(PRE_CLOSE_START_TIME, datetime.strptime("14:45", "%H:%M").time())
        self.assertEqual(PRE_CLOSE_CUTOFF_TIME, datetime.strptime("14:56", "%H:%M").time())
        self.assertEqual(MAX_PRE_CLOSE_RUNTIME_SECONDS, 660.0)
        self.assertEqual(DELIVERY_RESERVE_SECONDS, 36.0)
        expected = {
            "14:45:00": 660.0,
            "14:50:00": 360.0,
            "14:55:00": 60.0,
            "14:55:24": 36.0,
            "14:55:59": 1.0,
            "14:56:00": 0.0,
            "14:56:01": 0.0,
        }
        for clock, budget in expected.items():
            with self.subTest(clock=clock):
                current = datetime.fromisoformat(
                    "{}T{}+08:00".format(TRADE_DATE, clock)
                )
                self.assertEqual(_scheduled_wall_budget(current), budget)

    def test_injected_tokyo_clock_is_normalized_to_shanghai_window_and_date(self):
        tokyo_start = datetime(2026, 8, 28, 15, 45, 0, tzinfo=TOKYO)
        observed = []

        def runtime_builder(trade_date, as_of, **_kwargs):
            observed.append((trade_date, as_of))
            return _market_inputs(trade_date, as_of)

        def pipeline_runner(_inputs, config, components=None):
            del components
            observed.append((config.trade_date, config.as_of, config.generated_at))
            return _empty_snapshot(config)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: tokyo_start,
                trading_day_check=lambda *_args: True,
                runtime_builder=runtime_builder,
                pipeline_runner=pipeline_runner,
                skip_publish=True,
            )
            timings = json.loads(
                (base / "preclose" / TRADE_DATE / "timings.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(observed[0][0], TRADE_DATE)
        self.assertTrue(all(value.endswith("+08:00") for row in observed for value in row[1:]))
        self.assertTrue(timings["started_at"].endswith("+08:00"))
        self.assertTrue(timings["finished_at"].endswith("+08:00"))

    def test_tokyo_1445_is_before_shanghai_window(self):
        tokyo_before_start = datetime(2026, 8, 28, 14, 45, 0, tzinfo=TOKYO)
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=base / "market.sqlite",
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: tokyo_before_start,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: calls.append("acquire"),
                skip_publish=True,
            )
        self.assertEqual(result["status"], "outside_preclose_window")
        self.assertEqual(calls, [])
        self.assertEqual(result["trade_date"], TRADE_DATE)

    def test_tokyo_midnight_uses_previous_shanghai_trade_date(self):
        tokyo_midnight = datetime(2026, 8, 29, 0, 30, 0, tzinfo=TOKYO)
        observed_trade_dates = []
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scheduled_preclose(
                root=Path(temp_dir) / "preclose",
                formal_market_db=Path(temp_dir) / "market.sqlite",
                env_file=Path(temp_dir) / "missing.env",
                source_sha="release-sha",
                now=lambda: tokyo_midnight,
                trading_day_check=lambda trade_date, *_args: observed_trade_dates.append(
                    trade_date
                ) or False,
                skip_publish=True,
            )
        self.assertEqual(result["status"], "skipped_non_trading_day")
        self.assertEqual(observed_trade_dates, [TRADE_DATE])

    def test_naive_injected_clock_is_interpreted_as_shanghai(self):
        current = datetime(2026, 8, 28, 14, 45, 0)
        self.assertEqual(
            normalize_preclose_datetime(current).isoformat(),
            "2026-08-28T14:45:00+08:00",
        )

    def test_default_clock_requests_shanghai_timezone(self):
        fixed = datetime(2026, 8, 28, 13, 0, 0, tzinfo=CN)
        with patch("preclose_run.datetime") as datetime_class:
            datetime_class.now.return_value = fixed
            with tempfile.TemporaryDirectory() as temp_dir:
                result = run_scheduled_preclose(
                    root=Path(temp_dir) / "preclose",
                    formal_market_db=Path(temp_dir) / "market.sqlite",
                    env_file=Path(temp_dir) / "missing.env",
                    source_sha="release-sha",
                    trading_day_check=lambda *_args: False,
                    skip_publish=True,
                )
        datetime_class.now.assert_called_once_with(PRE_CLOSE_TIMEZONE)
        self.assertEqual(result["status"], "skipped_non_trading_day")

    def test_pipeline_config_default_and_startup_cutoff_use_new_contract(self):
        self.assertEqual(
            PreclosePipelineConfig.__dataclass_fields__["deadline_seconds"].default,
            660.0,
        )
        config = PreclosePipelineConfig(
            trade_date=TRADE_DATE,
            as_of="2026-08-28T15:56:00+09:00",
            generated_at="2026-08-28T15:56:00+09:00",
            source_sha="release-sha",
            run_id="cutoff",
        )
        self.assertEqual(config.as_of, "2026-08-28T14:56:00+08:00")
        self.assertEqual(config.generated_at, "2026-08-28T14:56:00+08:00")
        snapshot = run_preclose_pipeline(
            _market_inputs(as_of=config.as_of), config=config
        )
        self.assertEqual(snapshot["status"], "deadline_exceeded")

    def test_prepared_fallback_promotes_before_cutoff_but_not_at_cutoff(self):
        for clock, should_promote in (("14:55:59", True), ("14:56:00", False)):
            with self.subTest(clock=clock), tempfile.TemporaryDirectory() as temp_dir:
                base = Path(temp_dir)
                day_root = base / TRADE_DATE
                prepared_path, _snapshot = _prepare_deadline_fallback(
                    day_root,
                    trade_date=TRADE_DATE,
                    as_of="2026-08-28T14:45:00+08:00",
                    source_sha="release-sha",
                    run_id="run-1",
                )
                snapshot_path = day_root / "snapshot.json"
                failure_path = day_root / "failure.json"
                current = datetime.fromisoformat(
                    "{}T{}+08:00".format(TRADE_DATE, clock)
                )
                result = _promote_prepared_deadline_fallback(
                    {"status": "deadline_exceeded", "trade_date": TRADE_DATE},
                    prepared_path=prepared_path,
                    snapshot_path=snapshot_path,
                    failure_path=failure_path,
                    source_sha="release-sha",
                    run_id="run-1",
                    started_at_iso="2026-08-28T14:45:00+08:00",
                    now=lambda: current,
                    monotonic=lambda: 1.0,
                    monotonic_started=0.0,
                )
                self.assertEqual(snapshot_path.exists(), should_promote)
                self.assertEqual(result.get("snapshot_path") is not None, should_promote)
                if not should_promote:
                    self.assertTrue(prepared_path.exists())

    def test_snapshot_write_is_skipped_when_clock_reaches_cutoff_after_pipeline(self):
        config = PreclosePipelineConfig(
            trade_date=TRADE_DATE,
            as_of="2026-08-28T14:45:00+08:00",
            generated_at="2026-08-28T14:45:00+08:00",
            source_sha="release-sha",
            run_id="write-guard",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = _run_preclose_locked(
                _market_inputs(),
                config=config,
                root=root,
                pipeline_runner=lambda *_args, **_kwargs: _empty_snapshot(config),
                write_guard=lambda: False,
            )
            self.assertEqual(result["status"], "deadline_exceeded")
            self.assertFalse((root / TRADE_DATE / "snapshot.json").exists())

    def test_scheduled_pipeline_result_is_discarded_if_clock_reaches_cutoff_before_write(self):
        phase = ["before_pipeline"]
        pipeline_calls = []
        start = datetime(2026, 8, 28, 14, 45, 0, tzinfo=CN)
        cutoff = datetime(2026, 8, 28, 14, 56, 0, tzinfo=CN)

        def pipeline_runner(_inputs, config, components=None):
            del components
            pipeline_calls.append(True)
            phase[0] = "after_pipeline"
            return _empty_snapshot(config)

        def wall_clock():
            return cutoff if phase[0] == "after_pipeline" else start

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
                monotonic=lambda: 0.0,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: _market_inputs(),
                pipeline_runner=pipeline_runner,
                skip_publish=True,
            )
            day_root = base / "preclose" / TRADE_DATE
            self.assertFalse((day_root / "snapshot.json").exists())

        self.assertEqual(pipeline_calls, [True])
        self.assertEqual(result["status"], "deadline_exceeded")

    def test_acquisition_alarm_budget_subtracts_initialization_elapsed(self):
        alarms = []

        @contextmanager
        def capture_alarm(seconds, stage):
            alarms.append((seconds, stage))
            yield

        calls = []
        monotonic_values = iter([0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])

        def monotonic():
            try:
                return next(monotonic_values)
            except StopIteration:
                return 5.0

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "preclose_run._deadline_alarm", capture_alarm
        ):
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: datetime(2026, 8, 28, 14, 45, 0, tzinfo=CN),
                monotonic=monotonic,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: calls.append(True) or _market_inputs(),
                pipeline_runner=lambda _inputs, config, components=None: _empty_snapshot(config),
                skip_publish=True,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(calls)
        acquisition = [seconds for seconds, stage in alarms if stage == "input_acquisition"]
        self.assertEqual(len(acquisition), 1)
        self.assertEqual(acquisition[0], 619.0)

    def test_acquisition_reserve_boundary_is_strict(self):
        for clock, should_acquire in (
            ("14:55:23", True),
            ("14:55:24", False),
            ("14:55:25", False),
        ):
            with self.subTest(clock=clock), tempfile.TemporaryDirectory() as temp_dir:
                current = datetime.fromisoformat(
                    "{}T{}+08:00".format(TRADE_DATE, clock)
                )
                calls = []
                base = Path(temp_dir)
                db = base / "market.sqlite"
                db.write_bytes(b"formal-sentinel")
                result = run_scheduled_preclose(
                    root=base / "preclose",
                    formal_market_db=db,
                    env_file=base / "missing.env",
                    source_sha="release-sha",
                    now=lambda: current,
                    monotonic=lambda: 0.0,
                    trading_day_check=lambda *_args: True,
                    runtime_builder=lambda *_args, **_kwargs: calls.append(True) or _market_inputs(
                        as_of=current.isoformat(timespec="seconds")
                    ),
                    pipeline_runner=lambda _inputs, config, components=None: _empty_snapshot(config),
                    skip_publish=True,
                )
                self.assertEqual(result["exit_code"], 0 if should_acquire else 1)
                self.assertEqual(bool(calls), should_acquire)

    def test_delivery_budget_is_rechecked_after_environment_load(self):
        exhausted = [False]
        publisher_calls = []

        def monotonic():
            return 660.0 if exhausted[0] else 0.0

        def load_env(_path):
            exhausted[0] = True
            return False

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "preclose_run._notify_from_env", side_effect=load_env
        ):
            base = Path(temp_dir)
            db = base / "market.sqlite"
            db.write_bytes(b"formal-sentinel")
            result = run_scheduled_preclose(
                root=base / "preclose",
                formal_market_db=db,
                env_file=base / "missing.env",
                source_sha="release-sha",
                now=lambda: datetime(2026, 8, 28, 14, 47, 0, tzinfo=CN),
                monotonic=monotonic,
                trading_day_check=lambda *_args: True,
                runtime_builder=lambda *_args, **_kwargs: _market_inputs(
                    as_of="2026-08-28T14:47:00+08:00"
                ),
                pipeline_runner=lambda _inputs, config, components=None: _empty_snapshot(config),
                publisher=lambda *_args, **_kwargs: publisher_calls.append(True),
                notify=None,
            )

        self.assertEqual(publisher_calls, [])
        self.assertEqual(result["run_status"], "deadline_exceeded")
        self.assertEqual(result["delivery_error"], "PrecloseExecutionDeadline")


if __name__ == "__main__":
    unittest.main()
