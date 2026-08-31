"""Isolated persistent audit for formal-run right-side shadow evidence."""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional


SCHEMA_VERSION = "right-side-startup-formal-audit-v1"
DEFAULT_AUDIT_ROOT = (
    Path(__file__).resolve().parents[1]
    / ".cache"
    / "chanlun"
    / "right-side-startup"
    / "formal"
)


def current_source_sha(project_root: Optional[Any] = None) -> str:
    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    source_sha = result.stdout.strip()
    if len(source_sha) != 40:
        raise ValueError("git source SHA is unavailable")
    return source_sha


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _safe_value(item_method())
        except (TypeError, ValueError):
            pass
    return str(value)


def _compact_evidence(row: Mapping[str, Any], lane: str) -> Mapping[str, Any]:
    confirmation = row.get("confirmation_evidence")
    if not isinstance(confirmation, Mapping):
        actual = row.get("actual_value")
        confirmation = actual if isinstance(actual, Mapping) else {}
    return {
        "lane": lane,
        "code": str(row.get("code") or ""),
        "name": str(row.get("name") or ""),
        "source_channel": str(row.get("source_channel") or ""),
        "reference_type": row.get("reference_type"),
        "reference_price": _safe_value(row.get("reference_price")),
        "distance_from_reference_pct": _safe_value(
            row.get("distance_from_reference_pct")
        ),
        "volume_ratio": _safe_value(row.get("volume_ratio")),
        "change_pct": _safe_value(row.get("change_pct")),
        "price_limit_state": row.get("price_limit_state"),
        "confirmation_30m": {
            "data": _safe_value(confirmation.get("data") or {}),
            "mandatory": _safe_value(
                confirmation.get("mandatory") or {}
            ),
            "structure": _safe_value(
                confirmation.get("structure") or {}
            ),
            "quality": _safe_value(confirmation.get("quality") or {}),
            "risk": _safe_value(confirmation.get("risk") or {}),
            "passed": bool(confirmation.get("passed") is True),
        },
        "failure_gate": row.get("failure_gate"),
        "reason_code": row.get("reason_code"),
        "actual_value": _safe_value(row.get("actual_value")),
        "threshold": _safe_value(row.get("threshold")),
        "confirmations": _safe_value(row.get("confirmations") or []),
        "upgrade_conditions": _safe_value(
            row.get("upgrade_conditions") or []
        ),
        "cancel_conditions": _safe_value(
            row.get("cancel_conditions") or []
        ),
    }


def write_right_side_startup_audit(
    state: Mapping[str, Any],
    *,
    trade_date: str,
    generated_at: str,
    as_of: str,
    candidates: Any = (),
    watchlist: Any = (),
    run_identity: Optional[Mapping[str, Any]] = None,
    source_sha: Optional[str] = None,
    audit_root: Optional[Any] = None,
) -> Mapping[str, Any]:
    """Atomically persist shadow evidence outside every formal artifact plane."""

    if str(state.get("mode") or "") != "shadow":
        return {"status": "skipped", "reason": "mode_not_shadow"}
    resolved_source_sha = str(source_sha or current_source_sha()).strip()
    if len(resolved_source_sha) != 40:
        raise ValueError("source_sha must be a full Git SHA")
    if not str(as_of or "").strip():
        raise ValueError("as_of is required")
    root = Path(audit_root or DEFAULT_AUDIT_ROOT).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "{}.json".format(trade_date)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": str(trade_date),
        "generated_at": str(generated_at),
        "as_of": str(as_of),
        "source_sha": resolved_source_sha,
        "run_identity": _safe_value(run_identity or {}),
        "mode": "shadow",
        "policy_version": state.get("policy_version"),
        "affects_production": False,
        "published_codes": [],
        "candidates": [
            _compact_evidence(row, "candidate")
            for row in candidates or []
            if isinstance(row, Mapping)
        ],
        "watchlist": [
            _compact_evidence(row, "watch")
            for row in watchlist or []
            if isinstance(row, Mapping)
        ],
        "diagnostics": state.get("diagnostics") or {},
    }
    payload["candidate_count"] = len(payload["candidates"])
    payload["watch_count"] = len(payload["watchlist"])
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{}-".format(trade_date),
        suffix=".tmp",
        dir=str(root),
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return {
        "status": "written",
        "path": str(target),
        "trade_date": str(trade_date),
        "source_sha": resolved_source_sha,
    }
