#!/usr/bin/env python3
"""Read-only post-close reconciliation for the isolated 14:47 advisory."""

from __future__ import annotations

import argparse
import json
import os
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


def load_formal_workspace(trade_date, docs_dir, validator=None):
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
    validator = validator or run_report_validator
    try:
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
    try:
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {"status": "snapshot_invalid", "exit_code": 1}
        if str(snapshot.get("trade_date") or "") != trade_date:
            return {"status": "snapshot_date_mismatch", "exit_code": 1}
        formal = load_formal_workspace(
            trade_date,
            docs_dir=docs_dir,
            validator=validator,
        )
        generated_at = (now or datetime.now().astimezone()).isoformat(
            timespec="seconds"
        )
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
        _atomic_json(reconciliation_path, reconciliation)

        values = load_preclose_env(env_file)
        outbox = NotificationOutbox(root / "reconciliation-outbox.jsonl")
        delivery = publisher(
            reconciliation,
            api_base=values.get("PRECLOSE_API_BASE"),
            write_token=values.get("PRECLOSE_WRITE_TOKEN"),
            wxpusher_app_token=values.get("WXPUSHER_APP_TOKEN"),
            wxpusher_uid=values.get("WXPUSHER_UID"),
            wecom_webhook=values.get("WECOM_BOT_WEBHOOK"),
            outbox=outbox,
            notify=notify,
        )
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
    finally:
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
    result = None
    while True:
        result = runner(trade_date, **runner_kwargs)
        if result.get("status") != "formal_pending":
            return result
        current = now()
        if current.time().replace(tzinfo=None) >= stop_clock:
            result = dict(result)
            result["status"] = "formal_pending_timeout"
            return result
        stop_datetime = datetime.combine(current.date(), stop_clock)
        if current.tzinfo is not None:
            stop_datetime = stop_datetime.replace(tzinfo=current.tzinfo)
        remaining = max(0.0, (stop_datetime - current).total_seconds())
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
