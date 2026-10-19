#!/usr/bin/env python3
"""Independent, finite 14:45 observation job; never calls the daily publisher."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import signal
import subprocess
import sys
import time as elapsed_clock
from datetime import datetime, time, timedelta
from pathlib import Path

from chanlun.intraday_observation_delivery import (
    SHANGHAI, _validate_snapshot, build_failure_snapshot,
    build_observation_snapshot, content_hash, deliver_observation,
    freeze_json, freeze_observation_snapshot, validate_cutoff,
)

CALCULATION_RESERVE_SECONDS = 30


def _now():
    return datetime.now(SHANGHAI)


def _normalize_clock(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def should_start_scheduled(now, *, market_db, is_trading_day=None):
    if is_trading_day is None:
        from chanlun.preclose_schedule import is_trading_day
    now = _normalize_clock(now)
    return (time(14, 45) <= now.time() < time(14, 58)
            and is_trading_day(now.date().isoformat(), market_db))


def _read_snapshot(path, trade_date=None):
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_snapshot(result)
    if trade_date is not None and result["trade_date"] != trade_date:
        raise ValueError("stored snapshot has a different trade date")
    return result


def computation_deadline(args, now, cutoff):
    if not args.scheduled and args.input and not args.send:
        return now + timedelta(minutes=13)
    return cutoff.replace(minute=58)


def isolated_output_root(root, formal_market_db):
    """Only the dedicated observation directory may own job artifacts."""
    source = Path(root).expanduser()
    resolved = source.resolve()
    formal = Path(formal_market_db).expanduser().resolve()
    if (source.is_symlink() or resolved.name != "intraday-observation"
            or resolved == formal or resolved in formal.parents):
        raise ValueError("output root must be a dedicated intraday-observation directory")
    return resolved


def _collection_usable(payload, trade_date):
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return False
    validate_cutoff(payload.get("cutoff"), trade_date)
    health = payload.get("collection_health")
    if not isinstance(health, dict) or health.get("status") not in {"available", "partial"}:
        return False
    coverage = health.get("coverage")
    return (isinstance(coverage, (int, float)) and not isinstance(coverage, bool)
            and math.isfinite(coverage) and 0.90 <= coverage <= 1
            and type(health.get("timed_out")) is int and health["timed_out"] == 0)


def _live_acquire(*args, **kwargs):
    from chanlun.intraday_observation_data import acquire_observation_payload
    return acquire_observation_payload(*args, **kwargs)


def _evaluate(payload, generated_at):
    from chanlun.intraday_observation_context import ObservationContext
    import run
    context = ObservationContext(payload)
    report = run.main(generated_at=generated_at, observation_context=context, render=False)
    return report, context.snapshot()


def compute_batch(*, batch_dir, trade_date, formal_market_db, deadline,
                  clock=None, acquire=None, evaluate=None, input_path=None):
    """Compute within an already locked date directory, using frozen input only."""
    clock = clock or _now
    acquire, evaluate = acquire or _live_acquire, evaluate or _evaluate
    batch = Path(batch_dir)
    batch.mkdir(parents=True, exist_ok=True)
    result_path = batch / "snapshot.json"
    cutoff = trade_date + "T14:45:00+08:00"
    validate_cutoff(cutoff, trade_date)
    if result_path.exists():
        result = _read_snapshot(result_path)
        if result["trade_date"] != trade_date:
            raise ValueError("stored batch has a different date")
        return result
    payload = None
    stage = "input_acquisition"
    started = phase_started = elapsed_clock.monotonic()
    phase_seconds, acquisition_timings = {}, {}
    acquisition_deadline = None
    try:
        if clock() >= deadline:
            raise TimeoutError("computation deadline")
        frozen_input = batch / "input.json"
        if frozen_input.exists():
            payload = json.loads(frozen_input.read_text(encoding="utf-8"))
        elif input_path is not None:
            payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
            freeze_json(frozen_input, payload)
        else:
            acquisition_deadline = deadline - timedelta(seconds=CALCULATION_RESERVE_SECONDS)
            if clock() >= acquisition_deadline:
                raise TimeoutError("observation acquisition reserve reached")
            payload = acquire(formal_market_db, trade_date, deadline=acquisition_deadline,
                              snapshot_dir=batch / "inputs", clock=clock, timings=acquisition_timings)
            freeze_json(frozen_input, payload)
        if not _collection_usable(payload, trade_date):
            raise ValueError("collection coverage or identity unavailable")
        if clock() >= deadline:
            raise TimeoutError("computation deadline")
        phase_seconds[stage] = elapsed_clock.monotonic() - phase_started
        stage = "calculation"
        phase_started = elapsed_clock.monotonic()
        report, final_payload = evaluate(payload, generated_at=clock())
        if clock() >= deadline:
            raise TimeoutError("computation deadline")
        phase_seconds[stage] = elapsed_clock.monotonic() - phase_started
        stage = "output_validation"
        phase_started = elapsed_clock.monotonic()
        # A run must not extend the frozen input with fresh or post-cutoff data.
        if content_hash(final_payload) != content_hash(payload):
            raise ValueError("calculation changed frozen inputs")
        observation = report.get("intraday_observation", {})
        if observation.get("input_hash") != content_hash(final_payload):
            raise ValueError("report input identity mismatch")
        result = build_observation_snapshot(report)
        freeze_json(batch / "input-final.json", final_payload)
    except Exception as exc:
        failure_code = "deadline_exceeded" if isinstance(exc, TimeoutError) else stage + "_failed"
        result = build_failure_snapshot(trade_date, cutoff=cutoff, failure_code=failure_code,
            input_hash=content_hash(payload) if isinstance(payload, dict) else None)
        freeze_json(batch / "failure.json", {"trade_date": trade_date, "stage": stage,
            "failure_code": failure_code, "error_type": type(exc).__name__})
    freeze_observation_snapshot(result_path, result)
    phase_seconds[stage] = elapsed_clock.monotonic() - phase_started
    freeze_json(batch / "timings.json", {"schema_version": 1, "trade_date": trade_date,
        "status": result["status"], "phase_seconds": phase_seconds,
        "acquisition": acquisition_timings,
        "acquisition_deadline": acquisition_deadline.isoformat() if acquisition_deadline else None,
        "computation_deadline": deadline.isoformat(),
        "elapsed_seconds": elapsed_clock.monotonic() - started})
    return result


def _record_worker_failure(batch, trade_date, failure_code):
    result_path = batch / "snapshot.json"
    if result_path.exists():
        return _read_snapshot(result_path)
    result = build_failure_snapshot(trade_date, cutoff=trade_date + "T14:45:00+08:00",
                                    failure_code=failure_code)
    freeze_observation_snapshot(result_path, result)
    failure_path = batch / "failure.json"
    if not failure_path.exists():
        freeze_json(failure_path, {"trade_date": trade_date, "failure_code": failure_code,
                                  "stage": "worker"})
    return result


def _run_worker(args, batch, trade_date, deadline):
    if (batch / "snapshot.json").exists():
        return _read_snapshot(batch / "snapshot.json", trade_date)
    command = [sys.executable, str(Path(__file__).resolve()), "--compute-worker",
               "--root", str(Path(args.root).expanduser().resolve()), "--date", trade_date,
               "--formal-market-db", str(Path(args.formal_market_db).expanduser().resolve()),
               "--worker-deadline", deadline.isoformat()]
    if args.input:
        command.extend(["--input", str(Path(args.input).expanduser().resolve())])
    # The calculation subprocess receives no delivery or research credentials.
    blocked = ("WXPUSHER_", "WECOM_", "PRECLOSE_", "OPENAI_", "DEEPSEEK_", "ANTHROPIC_", "IWENCAI_", "CLOUDFLARE_")
    env = {key: value for key, value in os.environ.items() if not key.startswith(blocked)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["KLINE_CACHE_ROOT"] = str(batch / "isolated-cache")
    env["CHANLUN_MARKET_HISTORY_DB_PATH"] = str(Path(args.formal_market_db).expanduser().resolve())
    remaining = (deadline - _now()).total_seconds()
    if remaining <= 0:
        return _record_worker_failure(batch, trade_date, "deadline_exceeded")
    with (batch / "calculation.log").open("ab") as log:
        process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parent),
                                   env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            exit_code = process.wait(timeout=remaining)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            # A child may have exited before its own descendants. This group
            # belongs exclusively to this task (start_new_session=True).
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if sys.exc_info()[0] is subprocess.TimeoutExpired:
                return _record_worker_failure(batch, trade_date, "deadline_exceeded")
            raise
    if exit_code != 0 or not (batch / "snapshot.json").is_file():
        return _record_worker_failure(batch, trade_date, "worker_failed")
    return _read_snapshot(batch / "snapshot.json", trade_date)


class _DeliveryDeadline(TimeoutError):
    pass


def deliver_before_deadline(snapshot, *, deadline, clock=None, **kwargs):
    """Bound the complete delivery operation, including a slow response body."""
    clock = clock or _now
    remaining = (deadline - clock()).total_seconds()
    if remaining <= 0:
        return {"status": "deadline_exceeded", "success": False}
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = elapsed_clock.monotonic()
    def expired(_signum, _frame):
        raise _DeliveryDeadline("observation notification deadline")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        return deliver_observation(snapshot, deadline=deadline, clock=clock, **kwargs)
    except _DeliveryDeadline:
        # A durable dispatching receipt remains if the interrupt crossed the
        # provider call or receipt write. Such a part is never auto-retried.
        return {"status": "deadline_exceeded", "success": False}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:
            restored = max(.000001, old_timer[0] - (elapsed_clock.monotonic() - started))
            signal.setitimer(signal.ITIMER_REAL, restored, old_timer[1])


def main(argv=None):
    repo = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(repo / ".cache/chanlun/intraday-observation"))
    parser.add_argument("--formal-market-db", default=str(repo / ".cache/chanlun/market_history.sqlite"))
    parser.add_argument("--env-file", default="~/.config/chanlun-strategy/preclose.env")
    parser.add_argument("--input", help="existing frozen input; never fetch when provided")
    parser.add_argument("--date")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--send", action="store_true", help="send to configured personal WxPusher UID")
    parser.add_argument("--compute-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-deadline", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = isolated_output_root(args.root, args.formal_market_db)
    now = _now()
    trade_date = args.date or now.date().isoformat()
    cutoff = validate_cutoff(trade_date + "T14:45:00+08:00", trade_date)
    compute_deadline = computation_deadline(args, now, cutoff)
    send_deadline = cutoff.replace(minute=59)
    if args.compute_worker:
        if not args.worker_deadline:
            parser.error("worker requires the parent's finite deadline")
        compute_deadline = _normalize_clock(datetime.fromisoformat(args.worker_deadline))
        if not args.input and compute_deadline > cutoff.replace(minute=58):
            parser.error("live worker deadline cannot pass 14:58")
        if compute_deadline > now + timedelta(minutes=13, seconds=1):
            parser.error("worker deadline exceeds finite runtime budget")
        compute_batch(batch_dir=root / trade_date, trade_date=trade_date,
                      formal_market_db=args.formal_market_db, deadline=compute_deadline,
                      input_path=args.input)
        return 0
    if args.worker_deadline:
        parser.error("worker deadline is internal only")
    if args.scheduled:
        if args.date is not None and trade_date != now.date().isoformat():
            parser.error("scheduled date must be today")
        if not should_start_scheduled(now, market_db=args.formal_market_db):
            print(json.dumps({"status": "outside_schedule"}))
            return 0
    elif not args.input:
        parser.error("manual observation requires --input; live collection uses --scheduled")
    if args.send and (trade_date != now.date().isoformat() or not time(14, 45) <= now.time() < time(14, 59)):
        parser.error("notification must be same-day between 14:45 and 14:59")
    batch = root / trade_date
    if batch.is_symlink():
        raise ValueError("observation date directory cannot be a symlink")
    batch.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(batch / "run.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "already_running", "trade_date": trade_date}))
            return 0
        result = _run_worker(args, batch, trade_date, compute_deadline)
        receipt = {"status": "not_requested", "success": False}
        if args.send:
            from chanlun.preclose_notify import load_preclose_env
            values = load_preclose_env(args.env_file)
            receipt = deliver_before_deadline(result, outbox_path=batch / "outbox.json",
                app_token=values.get("WXPUSHER_APP_TOKEN"), uid=values.get("WXPUSHER_UID"),
                deadline=send_deadline)
        print(json.dumps({"trade_date": trade_date, "run_id": result["run_id"],
                          "status": result["status"], "delivery": receipt}, ensure_ascii=False))
        return 0 if result["status"] != "failed" and (not args.send or receipt["success"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
