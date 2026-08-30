#!/usr/bin/env python3
"""Read-only post-close reconciliation for the isolated 14:47 advisory."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanlun.preclose_compare import (  # noqa: E402
    build_formal_pending_reconciliation,
    build_reconciliation,
    normalize_formal_workspace_views,
)
from chanlun.preclose_notify import (  # noqa: E402
    NotificationOutbox,
    load_preclose_env,
    publish_reconciliation_and_notify,
)
from chanlun.preclose_schedule import is_trading_day  # noqa: E402
from chanlun.report_view_model import build_workspace  # noqa: E402


FORMAL_POOL_CONTRACTS = (
    ("picks_fusion", None),
    ("h4_t3_pool", "candidates"),
    ("next_day_boom", "candidates"),
)


class ReconciliationDeadline(BaseException):
    """Stop every reconciliation phase at the shared 15:35 hard deadline."""


def _install_deadline_alarm(seconds):
    if seconds is None or not hasattr(signal, "setitimer"):
        return None
    budget = max(0.001, float(seconds))
    previous_handler = signal.getsignal(signal.SIGALRM)

    def deadline_handler(_signum, _frame):
        raise ReconciliationDeadline("reconciliation hard deadline")

    signal.signal(signal.SIGALRM, deadline_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, budget)
    return previous_handler, previous_timer


def _restore_deadline_alarm(state):
    if state is None:
        return
    previous_handler, previous_timer = state
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, previous_handler)
    if previous_timer[0] > 0:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _pending(reason):
    return {"status": "formal_pending", "reason": str(reason)}


def run_report_validator(trade_date, docs_dir, timeout=180):
    """Run the existing official-report validator without modifying its inputs."""

    command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_today_report.py"),
        "--docs-dir",
        str(Path(docs_dir).resolve()),
        str(trade_date),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _formal_pool_contracts_valid(report):
    for pool_name, candidates_key in FORMAL_POOL_CONTRACTS:
        value = report.get(pool_name)
        if candidates_key is None:
            if not isinstance(value, list):
                return False
            continue
        if not isinstance(value, dict) or not isinstance(
            value.get(candidates_key), list
        ):
            return False
    return True


def load_formal_workspace(
    trade_date,
    docs_dir,
    validator=None,
    validator_timeout=None,
):
    """Admit only a validated, closed official report and rebuild visible views."""

    docs_dir = Path(docs_dir).expanduser().resolve()
    path = docs_dir / "data" / (str(trade_date) + ".json")
    if not path.is_file():
        return _pending("formal_report_missing")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return _pending("formal_report_unreadable")
    if not isinstance(report, dict) or str(report.get("date") or "") != str(
        trade_date
    ):
        return _pending("formal_report_date_mismatch")
    quality = report.get("data_quality")
    quality = quality if isinstance(quality, dict) else {}
    if (
        quality.get("is_official") is not True
        or quality.get("bar_state") != "closed"
        or quality.get("is_trading_day") is False
    ):
        return _pending("formal_report_not_closed")
    if not _formal_pool_contracts_valid(report):
        return _pending("formal_pool_contract_invalid")
    try:
        if validator is None:
            timeout = 180 if validator_timeout is None else max(
                0.001, float(validator_timeout)
            )
            valid = run_report_validator(
                str(trade_date), docs_dir, timeout=timeout
            )
        else:
            valid = validator(str(trade_date), docs_dir)
    except Exception:
        valid = False
    if valid is not True:
        return _pending("formal_report_validation_failed")
    try:
        views = normalize_formal_workspace_views(build_workspace(report))
    except Exception:
        return _pending("formal_workspace_contract_invalid")
    return {
        "status": "ready",
        "views": views,
        "report_path": str(path),
    }


class PrecloseReconcileLock:
    """Atomic lock isolated from both the formal and 14:47 run locks."""

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
            payload = json.dumps(
                {"run_id": self.run_id, "pid": os.getpid()},
                sort_keys=True,
            ).encode("utf-8") + b"\n"
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


def _append_jsonl(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    descriptor = os.open(
        str(path),
        os.O_CREAT | os.O_APPEND | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_reconciliation_once(
    trade_date,
    *,
    root,
    docs_dir,
    env_file,
    notify=False,
    validator=None,
    publisher=publish_reconciliation_and_notify,
    now=None,
    deadline_seconds=None,
    monotonic=None,
):
    """Build, publish and optionally notify without writing any formal path."""

    trade_date = str(trade_date or "").strip()
    root = Path(root).expanduser().resolve()
    day_root = root / trade_date
    snapshot_path = day_root / "snapshot.json"
    if not snapshot_path.is_file():
        return {"status": "snapshot_missing", "exit_code": 1}
    run_id = "{}-{}".format(trade_date, uuid.uuid4().hex[:12])
    lock = PrecloseReconcileLock(day_root / "reconcile.lock", run_id)
    if not lock.acquire():
        return {"status": "locked", "exit_code": 75}
    monotonic = monotonic or time.monotonic
    deadline_started = float(monotonic())
    failure_path = day_root / "reconciliation-failure.json"
    stage = "snapshot_read"

    def current_time():
        current = now() if callable(now) else now
        return current or datetime.now().astimezone()

    def failure_result(status, exit_code, error_type):
        payload = {
            "schema_version": "preclose-reconciliation-failure-v1",
            "trade_date": trade_date,
            "run_id": run_id,
            "observed_at": current_time().isoformat(timespec="seconds"),
            "status": status,
            "stage": stage,
            "error_type": str(error_type),
        }
        evidence_error = None
        try:
            _atomic_json(failure_path, payload)
        except Exception as exc:
            evidence_error = type(exc).__name__
        result = {
            "status": status,
            "exit_code": int(exit_code),
            "error_type": str(error_type),
            "stage": stage,
        }
        if evidence_error:
            result["failure_evidence_error"] = evidence_error
        return result

    def remaining_budget():
        if deadline_seconds is None:
            return None
        return max(
            0.0,
            float(deadline_seconds)
            - max(0.0, float(monotonic()) - deadline_started),
        )

    alarm_state = _install_deadline_alarm(deadline_seconds)
    try:
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {"status": "snapshot_invalid", "exit_code": 1}
        if str(snapshot.get("trade_date") or "") != trade_date:
            return {"status": "snapshot_date_mismatch", "exit_code": 1}
        stage = "formal_validation"
        validator_budget = remaining_budget()
        if validator_budget is not None and validator_budget <= 0:
            raise ReconciliationDeadline("validator deadline")
        formal = load_formal_workspace(
            trade_date,
            docs_dir=docs_dir,
            validator=validator,
            validator_timeout=validator_budget,
        )
        generated_at = current_time().isoformat(
            timespec="seconds"
        )
        stage = "reconciliation_build"
        if formal.get("status") == "ready":
            reconciliation = build_reconciliation(
                snapshot,
                formal["views"],
                generated_at=generated_at,
            )
        else:
            reconciliation = build_formal_pending_reconciliation(
                snapshot,
                generated_at=generated_at,
            )
        reconciliation_path = day_root / "reconciliation.json"
        stage = "reconciliation_evidence"
        _atomic_json(reconciliation_path, reconciliation)

        stage = "environment"
        values = load_preclose_env(env_file)
        outbox = NotificationOutbox(root / "reconciliation-outbox.jsonl")
        publisher_budget = remaining_budget()
        if publisher_budget is not None and publisher_budget <= 0:
            raise ReconciliationDeadline("publisher deadline")
        request_timeout = 10.0 if publisher_budget is None else max(
            0.001, min(10.0, publisher_budget / 5.0)
        )
        stage = "publisher"
        delivery = publisher(
            reconciliation,
            api_base=values.get("PRECLOSE_API_BASE"),
            write_token=values.get("PRECLOSE_WRITE_TOKEN"),
            wxpusher_app_token=values.get("WXPUSHER_APP_TOKEN"),
            wxpusher_uid=values.get("WXPUSHER_UID"),
            wecom_webhook=values.get("WECOM_BOT_WEBHOOK"),
            outbox=outbox,
            notify=notify,
            timeout=request_timeout,
        )
        stage = "delivery_evidence"
        _atomic_json(day_root / "reconciliation-delivery.json", {
            "snapshot_id": reconciliation.get("snapshot_id"),
            "content_hash": reconciliation.get("content_hash"),
            "formal_content_hash": reconciliation.get("formal_content_hash"),
            "delivery": delivery,
        })
        publish_ok = delivery.get("publish", {}).get("success") is True
        notify_ok = (
            not notify
            or delivery.get("notifications", {}).get("wxpusher", {}).get(
                "success"
            ) is True
        )
        return {
            "status": reconciliation.get("status"),
            "snapshot_id": reconciliation.get("snapshot_id"),
            "content_hash": reconciliation.get("content_hash"),
            "formal_content_hash": reconciliation.get("formal_content_hash"),
            "reconciliation_path": str(reconciliation_path),
            "exit_code": 0 if publish_ok and notify_ok else 1,
        }
    except ReconciliationDeadline:
        return failure_result(
            "formal_pending_timeout", 0, "ReconciliationDeadline"
        )
    except Exception as exc:
        return failure_result(
            "reconciliation_failed", 1, type(exc).__name__
        )
    finally:
        _restore_deadline_alarm(alarm_state)
        lock.release()


def poll_reconciliation(
    trade_date,
    *,
    poll_seconds,
    stop_at,
    runner=run_reconciliation_once,
    now=None,
    sleep=None,
    **runner_kwargs
):
    """Poll formal readiness read-only until ready or the same-day hard stop."""

    interval = int(poll_seconds)
    if interval < 1:
        raise ValueError("poll_seconds must be positive")
    try:
        stop_clock = datetime.strptime(str(stop_at), "%H:%M:%S").time()
    except ValueError:
        raise ValueError("invalid stop_at")
    now = now or (lambda: datetime.now().astimezone())
    sleep = sleep or time.sleep
    evidence_path = None
    if runner_kwargs.get("root") is not None:
        evidence_path = (
            Path(runner_kwargs["root"]).expanduser().resolve()
            / str(trade_date)
            / "reconciliation-polls.jsonl"
        )
    result = None

    def record(current, current_result):
        if evidence_path is None:
            return
        _append_jsonl(evidence_path, {
            "schema_version": "preclose-reconciliation-poll-v1",
            "trade_date": str(trade_date),
            "observed_at": current.isoformat(timespec="seconds"),
            "status": current_result.get("status"),
            "snapshot_id": current_result.get("snapshot_id"),
            "content_hash": current_result.get("content_hash"),
            "formal_content_hash": current_result.get("formal_content_hash"),
            "exit_code": int(current_result.get("exit_code") or 0),
        })

    while True:
        current = now()
        stop_datetime = datetime.combine(current.date(), stop_clock)
        if current.tzinfo is not None:
            stop_datetime = stop_datetime.replace(tzinfo=current.tzinfo)
        remaining = max(0.0, (stop_datetime - current).total_seconds())
        if remaining <= 0:
            result = dict(result or {})
            result["status"] = "formal_pending_timeout"
            result.setdefault("exit_code", 0)
            record(current, result)
            return result
        result = runner(
            trade_date,
            deadline_seconds=remaining,
            **runner_kwargs
        )
        record(current, result)
        if result.get("status") != "formal_pending":
            return result
        sleep(min(float(interval), remaining))


def _notify_enabled(env_file, explicit):
    if explicit:
        return True
    values = load_preclose_env(env_file)
    return str(values.get("PRECLOSE_NOTIFY") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--root", default=".cache/chanlun/preclose")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument(
        "--formal-market-db",
        default=".cache/chanlun/market_history.sqlite",
    )
    parser.add_argument(
        "--env-file",
        default="~/.config/chanlun-strategy/preclose.env",
    )
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--stop-at", default="15:35:00")
    return parser.parse_args(argv)


def main(argv=None):
    args = _arguments(argv)
    if not is_trading_day(args.trade_date, args.formal_market_db):
        print(json.dumps({
            "status": "skipped_non_trading_day",
            "trade_date": args.trade_date,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    notify = _notify_enabled(args.env_file, args.notify)
    runner_kwargs = {
        "root": args.root,
        "docs_dir": args.docs_dir,
        "env_file": args.env_file,
        "notify": notify,
    }
    if args.poll:
        result = poll_reconciliation(
            args.trade_date,
            poll_seconds=args.poll_seconds,
            stop_at=args.stop_at,
            **runner_kwargs
        )
    else:
        result = run_reconciliation_once(args.trade_date, **runner_kwargs)
    print(json.dumps({
        key: result.get(key)
        for key in (
            "status",
            "snapshot_id",
            "content_hash",
            "formal_content_hash",
            "reconciliation_path",
        )
        if result.get(key) is not None
    }, ensure_ascii=False, sort_keys=True))
    return int(result.get("exit_code") or 0)


if __name__ == "__main__":
    sys.exit(main())
