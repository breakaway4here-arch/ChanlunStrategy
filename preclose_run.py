#!/usr/bin/env python3
"""CLI and single-run lock for the isolated 14:47 pre-close pipeline."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime, time as wall_time
from pathlib import Path

from chanlun.preclose_contract import (
    build_preclose_snapshot,
    snapshot_content_hash,
)
from chanlun.preclose_data import PrecloseDataPaths, write_preclose_input_snapshot
from chanlun.preclose_pipeline import (
    PreclosePipelineConfig,
    run_preclose_pipeline,
)
from chanlun.preclose_notify import (
    NotificationOutbox,
    load_preclose_env,
    publish_preclose_and_notify,
)
from chanlun.preclose_runtime import build_scheduled_preclose_input
from chanlun.preclose_schedule import is_trading_day


DELIVERY_RESERVE_SECONDS = 24.0


class PrecloseExecutionDeadline(BaseException):
    """Escape strategy code so the scheduler can still publish a safe empty state."""

    def __init__(self, stage):
        super().__init__("pre-close execution deadline")
        self.stage = str(stage or "execution")


@contextmanager
def _deadline_alarm(seconds, stage="execution"):
    """Interrupt one scheduled phase before the shared 14:49 wall deadline."""

    budget = max(0.001, float(seconds))
    if not hasattr(signal, "setitimer"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def deadline_handler(_signum, _frame):
        raise PrecloseExecutionDeadline(stage)

    signal.signal(signal.SIGALRM, deadline_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, budget)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


class PrecloseRunLock:
    """Small atomic same-day lock that never shares the formal publish lock."""

    def __init__(self, path, run_id):
        self.path = Path(path)
        self.run_id = str(run_id)
        self._held = False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                str(self.path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            return False
        try:
            payload = json.dumps({
                "run_id": self.run_id,
                "pid": os.getpid(),
            }, sort_keys=True).encode("utf-8") + b"\n"
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._held = True
        return True

    def release(self):
        if not self._held:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._held = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("pre-close run is already active")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(str(temporary), str(path))


def _current_source_sha():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=str(Path(__file__).resolve().parent),
        universal_newlines=True,
    ).strip()


def _notify_from_env(env_file):
    values = load_preclose_env(env_file)
    return str(values.get("PRECLOSE_NOTIFY") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _scheduled_wall_budget(current):
    deadline = current.replace(
        hour=14, minute=49, second=0, microsecond=0
    )
    return max(0.0, min(120.0, (deadline - current).total_seconds()))


def _read_frozen_snapshot(snapshot_path, trade_date):
    """Read identity metadata without recalculating or rewriting the snapshot."""

    try:
        snapshot = json.loads(
            Path(snapshot_path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ValueError("invalid frozen snapshot") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("invalid frozen snapshot")
    status = snapshot.get("status")
    snapshot_id = snapshot.get("snapshot_id")
    content_hash = snapshot.get("content_hash")
    if (
        snapshot.get("trade_date") != str(trade_date)
        or status not in {
            "available", "empty", "failed", "deadline_exceeded", "not_run"
        }
        or not isinstance(snapshot_id, str)
        or not snapshot_id.startswith("preclose:{}:".format(trade_date))
        or not isinstance(content_hash, str)
        or len(content_hash) != 64
        or any(character not in "0123456789abcdef" for character in content_hash)
        or snapshot_content_hash(snapshot) != content_hash
        or snapshot_id != "preclose:{}:{}".format(
            trade_date, content_hash[:16]
        )
    ):
        raise ValueError("invalid frozen snapshot")
    return snapshot


def _finalize_scheduled_result(
    result,
    *,
    root,
    trade_date,
    paths,
    env_file,
    publisher,
    skip_publish,
    notify,
    now,
    monotonic,
    started_at,
):
    """Publish a frozen result while enforcing both deadline clocks."""

    result["trade_date"] = trade_date
    input_path = paths.input_path(trade_date)
    if input_path.is_file():
        result["input_path"] = str(input_path)
    snapshot_error = result.pop("_snapshot_error", None)
    if snapshot_error:
        result["exit_code"] = 1
        if not skip_publish:
            _atomic_json(root / trade_date / "delivery.json", {
                "snapshot_id": result.get("snapshot_id"),
                "content_hash": result.get("content_hash"),
                "delivery": None,
                "error": snapshot_error,
            })
        return result
    snapshot_path = result.get("snapshot_path")
    if skip_publish or not snapshot_path:
        return result

    # A monotonic clock protects the 120-second total budget even if the wall
    # clock supplied by the scheduler is stale or moves backwards.
    elapsed = max(0.0, float(monotonic()) - started_at)
    wall_budget = _scheduled_wall_budget(now())
    total_budget = max(0.0, 120.0 - elapsed)
    delivery_budget = min(wall_budget, total_budget)
    if delivery_budget <= 0:
        result["exit_code"] = 1
        _atomic_json(root / trade_date / "delivery.json", {
            "snapshot_id": result.get("snapshot_id"),
            "content_hash": result.get("content_hash"),
            "delivery": None,
            "error": "PrecloseExecutionDeadline",
        })
        return result

    try:
        selected_publisher = publisher or publish_frozen_snapshot
        # Include env loading in the same delivery alarm.  This keeps a
        # blocked local credential file from consuming the whole publish
        # window without a fail-closed result.
        with _deadline_alarm(delivery_budget, "delivery"):
            notify_enabled = (
                _notify_from_env(env_file) if notify is None else bool(notify)
            )
            delivery = selected_publisher(
                snapshot_path,
                root=root,
                env_file=env_file,
                notify=notify_enabled,
                timeout=max(0.25, min(6.0, delivery_budget / 4.0)),
            )
        publish_ok = delivery.get("publish", {}).get("success") is True
        notify_ok = (
            not notify_enabled
            or delivery.get("notifications", {}).get("wxpusher", {}).get(
                "success"
            ) is True
        )
        if not publish_ok or not notify_ok:
            result["exit_code"] = 1
        _atomic_json(root / trade_date / "delivery.json", {
            "snapshot_id": result.get("snapshot_id"),
            "content_hash": result.get("content_hash"),
            "delivery": delivery,
        })
    except PrecloseExecutionDeadline:
        result["exit_code"] = 1
        _atomic_json(root / trade_date / "delivery.json", {
            "snapshot_id": result.get("snapshot_id"),
            "content_hash": result.get("content_hash"),
            "delivery": None,
            "error": "PrecloseExecutionDeadline",
        })
    except Exception as exc:
        result["exit_code"] = 1
        _atomic_json(root / trade_date / "delivery.json", {
            "snapshot_id": result.get("snapshot_id"),
            "content_hash": result.get("content_hash"),
            "delivery": None,
            "error": type(exc).__name__,
        })
    return result


def _freeze_fallback_before_cutoff(
    market_inputs,
    *,
    config,
    root,
    pipeline_runner,
    now,
    monotonic,
    started_at,
):
    """Freeze a non-actionable fallback only while both hard budgets remain."""

    elapsed = max(0.0, float(monotonic()) - started_at)
    budget = min(
        _scheduled_wall_budget(now()),
        max(0.0, 120.0 - elapsed),
    )
    deadline_result = {
        "status": "deadline_exceeded",
        "snapshot_status": "deadline_exceeded",
        "trade_date": config.trade_date,
        "exit_code": 1,
    }
    if budget <= 0:
        return deadline_result
    try:
        with _deadline_alarm(budget, "fallback_freeze"):
            return _run_preclose_locked(
                market_inputs,
                config=config,
                root=root,
                pipeline_runner=pipeline_runner,
            )
    except PrecloseExecutionDeadline:
        return deadline_result


def run_scheduled_preclose(
    *,
    root,
    formal_market_db,
    env_file,
    source_sha,
    now=None,
    monotonic=None,
    trading_day_check=is_trading_day,
    runtime_builder=build_scheduled_preclose_input,
    pipeline_runner=run_preclose_pipeline,
    publisher=None,
    skip_publish=False,
    notify=None,
):
    """Acquire, freeze, publish and optionally notify within one total budget."""

    now = now or (lambda: datetime.now().astimezone())
    monotonic = monotonic or __import__("time").monotonic
    current = now()
    trade_date = current.date().isoformat()
    if not trading_day_check(trade_date, formal_market_db):
        return {
            "status": "skipped_non_trading_day",
            "trade_date": trade_date,
            "exit_code": 0,
        }
    current_clock = current.time().replace(tzinfo=None)
    if not (wall_time(14, 47) <= current_clock < wall_time(14, 49)):
        return {
            "status": "outside_preclose_window",
            "trade_date": trade_date,
            "exit_code": 0,
        }

    root = Path(root).expanduser().resolve()
    formal_market_db = Path(formal_market_db).expanduser().resolve()
    paths = PrecloseDataPaths(root=root, formal_market_db=formal_market_db)
    day_root = root / trade_date
    snapshot_path = day_root / "snapshot.json"
    as_of = current.isoformat(timespec="seconds")
    run_id = "{}-{}".format(as_of, uuid.uuid4().hex[:12])
    started_at = float(monotonic())
    initial_budget = _scheduled_wall_budget(current)
    lock = PrecloseRunLock(day_root / "run.lock", run_id)
    if not lock.acquire():
        return {
            "status": "locked",
            "trade_date": trade_date,
            "exit_code": 75,
            "snapshot_path": str(snapshot_path),
        }

    try:
        if snapshot_path.exists():
            try:
                frozen_snapshot = _read_frozen_snapshot(
                    snapshot_path, trade_date
                )
            except Exception:
                return _finalize_scheduled_result({
                    "status": "failed",
                    "snapshot_status": "failed",
                    "trade_date": trade_date,
                    "exit_code": 1,
                    "snapshot_path": str(snapshot_path),
                    "_snapshot_error": "InvalidPrecloseSnapshot",
                }, root=root, trade_date=trade_date, paths=paths,
                   env_file=env_file, publisher=publisher,
                   skip_publish=skip_publish, notify=notify, now=now,
                   monotonic=monotonic, started_at=started_at)
            return _finalize_scheduled_result({
                "status": "already_completed",
                "snapshot_status": frozen_snapshot["status"],
                "snapshot_id": frozen_snapshot["snapshot_id"],
                "content_hash": frozen_snapshot["content_hash"],
                "trade_date": trade_date,
                "exit_code": (
                    0 if frozen_snapshot["status"] in {"available", "empty"}
                    else 1
                ),
                "snapshot_path": str(snapshot_path),
            }, root=root, trade_date=trade_date, paths=paths,
               env_file=env_file, publisher=publisher,
               skip_publish=skip_publish, notify=notify, now=now,
               monotonic=monotonic, started_at=started_at)

        market_inputs = None
        acquisition_error = None
        acquisition_status = None
        compute_budget = max(
            0.001, initial_budget - DELIVERY_RESERVE_SECONDS
        )
        try:
            with _deadline_alarm(compute_budget, "input_acquisition"):
                market_inputs = runtime_builder(
                    trade_date,
                    as_of,
                    formal_market_db=formal_market_db,
                )
                frozen_input_path = write_preclose_input_snapshot(
                    paths, market_inputs
                )
                market_inputs = json.loads(
                    frozen_input_path.read_text(encoding="utf-8")
                )
        except PrecloseExecutionDeadline:
            acquisition_status = "deadline_exceeded"
            acquisition_error = "PrecloseExecutionDeadline"
        except Exception as exc:
            acquisition_status = "failed"
            acquisition_error = type(exc).__name__

        generated = now()
        elapsed = max(0.0, float(monotonic()) - started_at)
        strategy_remaining = min(
            120.0 - elapsed - DELIVERY_RESERVE_SECONDS,
            _scheduled_wall_budget(generated) - DELIVERY_RESERVE_SECONDS,
        )
        if strategy_remaining <= 0 and not acquisition_status:
            acquisition_status = "deadline_exceeded"
            acquisition_error = "WallClockDeadline"
        config = PreclosePipelineConfig(
            trade_date=trade_date,
            as_of=as_of,
            generated_at=generated.isoformat(timespec="seconds"),
            source_sha=source_sha,
            run_id=run_id,
            deadline_seconds=max(0.001, min(120.0, strategy_remaining)),
            monotonic=monotonic,
        )

        def deadline_runner(stage, error_type):
            actual_elapsed = max(
                0.0, float(monotonic()) - started_at
            )
            frozen = build_preclose_snapshot(
                trade_date=trade_date,
                as_of=as_of,
                generated_at=config.generated_at,
                pools={"main": [], "h4_t3": [], "acceleration": []},
                source_sha=source_sha,
                status="deadline_exceeded",
                diagnostics={
                    "failure": {"stage": stage, "type": error_type},
                    "elapsed_seconds": round(actual_elapsed, 6),
                },
                run_id=config.run_id,
            )
            return lambda *_args, **_kwargs: frozen

        def failure_runner(stage, error_type):
            actual_elapsed = max(
                0.0, float(monotonic()) - started_at
            )
            frozen = build_preclose_snapshot(
                trade_date=trade_date,
                as_of=as_of,
                generated_at=config.generated_at,
                pools={"main": [], "h4_t3": [], "acceleration": []},
                source_sha=source_sha,
                status="failed",
                diagnostics={
                    "failure": {"stage": stage, "type": error_type},
                    "elapsed_seconds": round(actual_elapsed, 6),
                },
                run_id=config.run_id,
            )
            return lambda *_args, **_kwargs: frozen

        if acquisition_status:
            if acquisition_status == "deadline_exceeded":
                selected_runner = deadline_runner(
                    "input_acquisition", acquisition_error
                )
            else:
                frozen = build_preclose_snapshot(
                    trade_date=trade_date,
                    as_of=as_of,
                    generated_at=config.generated_at,
                    pools={"main": [], "h4_t3": [], "acceleration": []},
                    source_sha=source_sha,
                    status="failed",
                    diagnostics={
                        "failure": {
                            "stage": "input_acquisition",
                            "type": acquisition_error,
                        },
                        "elapsed_seconds": round(elapsed, 6),
                    },
                    run_id=config.run_id,
                )
                selected_runner = lambda *_args, **_kwargs: frozen
            result = _freeze_fallback_before_cutoff(
                market_inputs or {"trade_date": trade_date, "as_of": as_of},
                config=config,
                root=root,
                pipeline_runner=selected_runner,
                now=now,
                monotonic=monotonic,
                started_at=started_at,
            )
        else:
            try:
                with _deadline_alarm(strategy_remaining, "pipeline"):
                    result = _run_preclose_locked(
                        market_inputs,
                        config=config,
                        root=root,
                        pipeline_runner=pipeline_runner,
                    )
            except PrecloseExecutionDeadline as exc:
                result = _freeze_fallback_before_cutoff(
                    {"trade_date": trade_date, "as_of": as_of},
                    config=config,
                    root=root,
                    pipeline_runner=deadline_runner(
                        exc.stage, "PrecloseExecutionDeadline"
                    ),
                    now=now,
                    monotonic=monotonic,
                    started_at=started_at,
                )
            except Exception as exc:
                result = _freeze_fallback_before_cutoff(
                    {"trade_date": trade_date, "as_of": as_of},
                    config=config,
                    root=root,
                    pipeline_runner=failure_runner(
                        "pipeline", type(exc).__name__
                    ),
                    now=now,
                    monotonic=monotonic,
                    started_at=started_at,
                )

        return _finalize_scheduled_result(
            result,
            root=root,
            trade_date=trade_date,
            paths=paths,
            env_file=env_file,
            publisher=publisher,
            skip_publish=skip_publish,
            notify=notify,
            now=now,
            monotonic=monotonic,
            started_at=started_at,
        )
    finally:
        lock.release()


def _run_preclose_locked(
    market_inputs,
    *,
    config,
    root,
    components=None,
    pipeline_runner=run_preclose_pipeline
):
    """Freeze one snapshot while the caller owns the same-day run lock."""

    root = Path(root).expanduser().resolve()
    day_root = root / config.trade_date
    snapshot_path = day_root / "snapshot.json"
    diagnostics_path = day_root / "diagnostics.json"
    if snapshot_path.exists():
        return {
            "status": "already_completed",
            "exit_code": 0,
            "snapshot_path": str(snapshot_path),
        }
    snapshot = pipeline_runner(
        market_inputs,
        config=config,
        components=components,
    )
    _atomic_json(snapshot_path, snapshot)
    _atomic_json(diagnostics_path, snapshot.get("diagnostics") or {})
    snapshot_status = snapshot.get("status")
    return {
        "status": "completed",
        "snapshot_status": snapshot_status,
        "snapshot_id": snapshot.get("snapshot_id"),
        "content_hash": snapshot.get("content_hash"),
        "snapshot_path": str(snapshot_path),
        "exit_code": 0 if snapshot_status in {"available", "empty"} else 1,
    }


def run_preclose_once(
    market_inputs,
    *,
    config,
    root,
    components=None,
    pipeline_runner=run_preclose_pipeline
):
    """Acquire the isolated lock, freeze once, and never overwrite a first run."""

    root = Path(root).expanduser().resolve()
    day_root = root / config.trade_date
    snapshot_path = day_root / "snapshot.json"
    lock = PrecloseRunLock(day_root / "run.lock", config.run_id)
    if not lock.acquire():
        return {
            "status": "locked",
            "exit_code": 75,
            "snapshot_path": str(snapshot_path),
        }
    try:
        return _run_preclose_locked(
            market_inputs,
            config=config,
            root=root,
            components=components,
            pipeline_runner=pipeline_runner,
        )
    finally:
        lock.release()


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="isolated pre-close input.json")
    parser.add_argument("--root", default=".cache/chanlun/preclose")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument(
        "--formal-market-db",
        default=".cache/chanlun/market_history.sqlite",
    )
    parser.add_argument("--trade-date")
    parser.add_argument("--as-of")
    parser.add_argument("--generated-at")
    parser.add_argument("--source-sha")
    parser.add_argument("--run-id")
    parser.add_argument("--deadline-seconds", type=float, default=120.0)
    parser.add_argument(
        "--env-file",
        default="~/.config/chanlun-strategy/preclose.env",
        help="dedicated 0600 pre-close credentials file",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="send WxPusher after Worker PUT/GET identity verification",
    )
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="local-only test mode; do not write Worker or notification outbox",
    )
    return parser.parse_args(argv)


def publish_frozen_snapshot(snapshot_path, *, root, env_file, notify, timeout=10):
    """Publish one already-frozen snapshot without touching formal artifacts."""

    snapshot_path = Path(snapshot_path).expanduser().resolve()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot = _read_frozen_snapshot(
        snapshot_path, snapshot.get("trade_date")
    )
    values = load_preclose_env(env_file)
    outbox = NotificationOutbox(
        Path(root).expanduser().resolve() / "notification-outbox.jsonl"
    )
    return publish_preclose_and_notify(
        snapshot,
        api_base=values.get("PRECLOSE_API_BASE"),
        write_token=values.get("PRECLOSE_WRITE_TOKEN"),
        wxpusher_app_token=values.get("WXPUSHER_APP_TOKEN"),
        wxpusher_uid=values.get("WXPUSHER_UID"),
        wecom_webhook=values.get("WECOM_BOT_WEBHOOK"),
        outbox=outbox,
        notify=notify,
        timeout=timeout,
    )


def main(argv=None):
    args = _arguments(argv)
    if args.scheduled:
        source_sha = str(args.source_sha or _current_source_sha())
        result = run_scheduled_preclose(
            root=args.root,
            formal_market_db=args.formal_market_db,
            env_file=args.env_file,
            source_sha=source_sha,
            skip_publish=args.skip_publish,
            notify=True if args.notify else None,
        )
        print(json.dumps({
            key: result.get(key)
            for key in (
                "status",
                "trade_date",
                "snapshot_status",
                "snapshot_id",
                "content_hash",
                "input_path",
                "snapshot_path",
            )
            if result.get(key) is not None
        }, ensure_ascii=False, sort_keys=True))
        return int(result.get("exit_code") or 0)
    if not args.input or not args.source_sha:
        raise SystemExit("--input and --source-sha are required outside --scheduled")
    input_path = Path(args.input).expanduser().resolve()
    market_inputs = json.loads(input_path.read_text(encoding="utf-8"))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    trade_date = str(args.trade_date or market_inputs.get("trade_date") or "")
    as_of = str(args.as_of or market_inputs.get("as_of") or now)
    generated_at = str(args.generated_at or now)
    run_id = str(
        args.run_id
        or "{}-{}".format(as_of, uuid.uuid4().hex[:12])
    )
    config = PreclosePipelineConfig(
        trade_date=trade_date,
        as_of=as_of,
        generated_at=generated_at,
        source_sha=args.source_sha,
        run_id=run_id,
        deadline_seconds=args.deadline_seconds,
    )
    result = run_preclose_once(
        market_inputs,
        config=config,
        root=args.root,
    )
    delivery = None
    delivery_error = None
    if not args.skip_publish and result.get("snapshot_path"):
        try:
            frozen_snapshot = json.loads(
                Path(result["snapshot_path"]).read_text(encoding="utf-8")
            )
            result.setdefault("snapshot_id", frozen_snapshot.get("snapshot_id"))
            result.setdefault("content_hash", frozen_snapshot.get("content_hash"))
            delivery = publish_frozen_snapshot(
                result["snapshot_path"],
                root=args.root,
                env_file=args.env_file,
                notify=args.notify,
            )
            publish_ok = delivery.get("publish", {}).get("success") is True
            notify_ok = not args.notify or delivery.get("notifications", {}).get(
                "wxpusher", {}
            ).get("success") is True
            if not publish_ok or not notify_ok:
                result["exit_code"] = 1
        except Exception as exc:
            delivery_error = type(exc).__name__
            result["exit_code"] = 1
        delivery_path = (
            Path(args.root).expanduser().resolve()
            / trade_date
            / "delivery.json"
        )
        _atomic_json(delivery_path, {
            "snapshot_id": result.get("snapshot_id"),
            "content_hash": result.get("content_hash"),
            "delivery": delivery,
            "error": delivery_error,
        })
    print(json.dumps({
        key: result.get(key)
        for key in (
            "status",
            "snapshot_status",
            "snapshot_id",
            "content_hash",
            "snapshot_path",
        )
        if result.get(key) is not None
    }, ensure_ascii=False, sort_keys=True))
    return int(result.get("exit_code") or 0)


if __name__ == "__main__":
    sys.exit(main())
