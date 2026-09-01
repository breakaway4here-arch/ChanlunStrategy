"""Pure contracts for the isolated 14:45 pre-close advisory workflow."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


POOL_KEYS = ("main", "h4_t3", "acceleration")
SNAPSHOT_SCHEMA_VERSION = "preclose-selection-v1"
SNAPSHOT_MODE = "preclose_advisory"
PRE_CLOSE_STRATEGY_VERSION = "preclose-1445-v2"


def _parse_iso(value):
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _round_price(value):
    try:
        price = Decimal(str(value)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid reference_price")
    result = float(price)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("invalid reference_price")
    return result


def normalize_preclose_candidate(candidate):
    """Return the only candidate fields permitted on public surfaces."""

    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a mapping")
    code = str(candidate.get("code") or "").strip().upper().split(".")[0]
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise ValueError("invalid candidate code")
    name = str(candidate.get("name") or "").strip()
    if not name:
        raise ValueError("invalid candidate name")
    return {
        "code": code,
        "name": name,
        "reference_price": _round_price(candidate.get("reference_price")),
    }


def _normalize_pools(pools):
    source = pools if isinstance(pools, dict) else {}
    normalized = {}
    errors = []
    for pool_key in POOL_KEYS:
        rows = []
        seen = set()
        raw_rows = source.get(pool_key)
        raw_rows = raw_rows if isinstance(raw_rows, (list, tuple)) else []
        for index, candidate in enumerate(raw_rows):
            try:
                row = normalize_preclose_candidate(candidate)
            except ValueError as exc:
                errors.append({
                    "pool": pool_key,
                    "index": index,
                    "error": str(exc),
                })
                continue
            if row["code"] in seen:
                continue
            seen.add(row["code"])
            rows.append(row)
        normalized[pool_key] = rows
    return normalized, errors


def _content_projection(snapshot):
    source = snapshot if isinstance(snapshot, dict) else {}
    return {
        "schema_version": source.get("schema_version"),
        "mode": source.get("mode"),
        "strategy_version": source.get("strategy_version"),
        "trade_date": source.get("trade_date"),
        "as_of": source.get("as_of"),
        "expires_at": source.get("expires_at"),
        "status": source.get("status"),
        "is_final": source.get("is_final"),
        "affects_formal": source.get("affects_formal"),
        "source_sha": source.get("source_sha"),
        "pools": {
            pool_key: list((source.get("pools") or {}).get(pool_key) or [])
            for pool_key in POOL_KEYS
        },
    }


def snapshot_content_hash(snapshot):
    """Hash stable advisory content while excluding run metadata and diagnostics."""

    encoded = json.dumps(
        _content_projection(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_preclose_snapshot(
    trade_date,
    as_of,
    generated_at,
    pools,
    source_sha,
    status=None,
    diagnostics=None,
    run_id=None,
):
    """Build one frozen internal snapshot for the advisory workflow."""

    trade_date = str(trade_date or "").strip()
    if len(trade_date) != 10:
        raise ValueError("invalid trade_date")
    as_of_dt = _parse_iso(as_of)
    generated_at_dt = _parse_iso(generated_at)
    if as_of_dt.date().isoformat() != trade_date:
        raise ValueError("as_of date mismatch")
    if generated_at_dt.date().isoformat() != trade_date:
        raise ValueError("generated_at date mismatch")
    offset = as_of_dt.strftime("%z")
    offset = offset[:3] + ":" + offset[3:] if offset else "+08:00"
    expires_at = trade_date + "T14:56:30" + offset

    normalized_pools, errors = _normalize_pools(pools)
    has_candidates = any(normalized_pools[pool_key] for pool_key in POOL_KEYS)
    resolved_status = status or ("available" if has_candidates else "empty")
    if resolved_status == "available" and not has_candidates:
        resolved_status = "empty"
    if resolved_status not in {
        "available", "empty", "failed", "deadline_exceeded", "not_run"
    }:
        raise ValueError("invalid preclose status")
    if resolved_status not in {"available", "empty"}:
        normalized_pools = {pool_key: [] for pool_key in POOL_KEYS}

    internal_diagnostics = dict(diagnostics or {})
    if errors:
        internal_diagnostics["normalization_errors"] = errors
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "mode": SNAPSHOT_MODE,
        "strategy_version": PRE_CLOSE_STRATEGY_VERSION,
        "trade_date": trade_date,
        "as_of": str(as_of),
        "generated_at": str(generated_at),
        "expires_at": expires_at,
        "status": resolved_status,
        "is_final": False,
        "affects_formal": False,
        "source_sha": str(source_sha or "").strip(),
        "pools": normalized_pools,
        "diagnostics": internal_diagnostics,
    }
    if run_id is not None:
        snapshot["run_id"] = str(run_id)
    snapshot["content_hash"] = snapshot_content_hash(snapshot)
    snapshot["snapshot_id"] = "preclose:{}:{}".format(
        trade_date,
        snapshot["content_hash"][:16],
    )
    return snapshot


def is_preclose_expired(snapshot_or_expires_at, now):
    """Apply the same inclusive ISO expiry boundary on server and browser inputs."""

    expires_at = (
        snapshot_or_expires_at.get("expires_at")
        if isinstance(snapshot_or_expires_at, dict)
        else snapshot_or_expires_at
    )
    return _parse_iso(now) >= _parse_iso(expires_at)


def build_public_preclose_view(snapshot, now):
    """Strip all diagnostics and fail closed after expiry or internal failures."""

    source = snapshot if isinstance(snapshot, dict) else {}
    expired = is_preclose_expired(source, now)
    available = source.get("status") == "available" and not expired
    replayable = source.get("status") == "available" and expired
    show_pools = available or replayable
    status = "available" if available else ("expired" if expired else "empty")
    pools = {
        pool_key: list((source.get("pools") or {}).get(pool_key) or [])
        if show_pools
        else []
        for pool_key in POOL_KEYS
    }
    if expired:
        message = "预跑已封存，仅供回看；14:57后不再依据预跑清单新增动作"
    elif available:
        message = "14:56:30前有效"
    else:
        message = "本期未选出推荐票"
    return {
        "schema_version": source.get("schema_version"),
        "mode": source.get("mode"),
        "strategy_version": source.get("strategy_version"),
        "snapshot_id": source.get("snapshot_id"),
        "content_hash": source.get("content_hash"),
        "trade_date": source.get("trade_date"),
        "as_of": source.get("as_of"),
        "generated_at": source.get("generated_at"),
        "expires_at": source.get("expires_at"),
        "status": status,
        "is_final": False,
        "affects_formal": False,
        "source_sha": source.get("source_sha"),
        "pools": pools,
        "message": message,
    }


def _formal_candidate(candidate, fallback_version=None):
    source = candidate if isinstance(candidate, dict) else {}
    contract = source.get("formal_decision_contract")
    contract = contract if isinstance(contract, dict) else {}
    decision = source.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    return {
        "code": str(source.get("code") or ""),
        "name": str(source.get("name") or ""),
        "action": str(
            contract.get("action")
            or source.get("effective_action")
            or source.get("action")
            or source.get("page_action")
            or ""
        ),
        "decision_code": str(decision.get("decision_code") or ""),
        "strategy": str(source.get("strategy") or source.get("strategy_id") or ""),
        "version": str(
            source.get("version")
            or source.get("strategy_version")
            or fallback_version
            or ""
        ),
    }


def _formal_pool(candidates, fallback_version=None):
    return [
        _formal_candidate(candidate, fallback_version=fallback_version)
        for candidate in (candidates or [])
        if isinstance(candidate, dict)
    ]


def normalized_formal_summary(report):
    """Project formal pool order, actions and strategy versions for hash checks."""

    source = report if isinstance(report, dict) else {}
    h4 = source.get("h4_t3_pool")
    h4 = h4 if isinstance(h4, dict) else {}
    acceleration = source.get("next_day_boom")
    acceleration = acceleration if isinstance(acceleration, dict) else {}
    return {
        "picks_pure": _formal_pool(source.get("picks_pure")),
        "picks_fusion": _formal_pool(source.get("picks_fusion")),
        "h4_t3": _formal_pool(
            h4.get("candidates"),
            fallback_version=h4.get("model_version") or h4.get("version"),
        ),
        "acceleration": _formal_pool(
            acceleration.get("candidates"),
            fallback_version=acceleration.get("version"),
        ),
    }
