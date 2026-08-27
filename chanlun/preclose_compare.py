"""Deterministic, read-only comparison of pre-close and formal visible pools."""

from __future__ import annotations

import hashlib
import json
import math


POOL_KEYS = ("main", "h4_t3", "acceleration")
DETAIL_FIELDS = (
    "rank",
    "reference_price",
    "signal_type",
    "input_evidence_at",
)


def _candidate_code(candidate):
    if isinstance(candidate, dict):
        value = candidate.get("code")
    else:
        value = candidate
    code = str(value or "").strip().upper().split(".")[0]
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    return code


def _json_safe(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if isinstance(key, (str, int, float, bool))
        }
    return str(value)


def _safe_price(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return round(number, 4)


def _normalize_candidate(candidate):
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a mapping")
    code = _candidate_code(candidate)
    if not code:
        raise ValueError("candidate code missing")
    result = {
        "code": code,
        "name": str(candidate.get("name") or code).strip(),
    }
    price_value = candidate.get("reference_price")
    formal_contract = candidate.get("formal_decision_contract")
    if price_value is None and isinstance(formal_contract, dict):
        price_value = formal_contract.get("reference_price")
    price = _safe_price(price_value)
    if price is not None:
        result["reference_price"] = price
    rank = candidate.get("view_rank", candidate.get("rank"))
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = None
    if rank is not None and rank > 0:
        result["rank"] = rank
    best = candidate.get("best_buy_point")
    best = best if isinstance(best, dict) else {}
    signal_type = str(
        candidate.get("signal_type")
        or candidate.get("reference_type")
        or best.get("type")
        or ""
    ).strip()
    if signal_type:
        result["signal_type"] = signal_type
    data_status = candidate.get("data_status")
    data_status = data_status if isinstance(data_status, dict) else {}
    evidence_at = str(
        candidate.get("input_evidence_at")
        or data_status.get("latest_date")
        or ""
    ).strip()
    if evidence_at:
        result["input_evidence_at"] = evidence_at
    if isinstance(formal_contract, dict):
        result["formal_decision_contract"] = _json_safe(formal_contract)
    decision = candidate.get("decision_engine_v1")
    if isinstance(decision, dict):
        result["decision_engine_v1"] = {
            key: _json_safe(decision.get(key))
            for key in ("version", "decision_code")
            if decision.get(key) is not None
        }
    strategy_version = str(
        candidate.get("strategy_version") or candidate.get("version") or ""
    ).strip()
    if strategy_version:
        result["strategy_version"] = strategy_version
    return result


def _normalize_pool(rows):
    normalized = []
    seen = set()
    for candidate in rows:
        row = _normalize_candidate(candidate)
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        normalized.append(row)
    return normalized


def normalize_preclose_pools(snapshot_or_pools):
    source = snapshot_or_pools if isinstance(snapshot_or_pools, dict) else {}
    pools = source.get("pools") if "pools" in source else source
    if not isinstance(pools, dict):
        raise ValueError("pre-close pools contract missing")
    result = {}
    for key in POOL_KEYS:
        if key not in pools or not isinstance(pools[key], list):
            raise ValueError("pre-close pool contract missing: {}".format(key))
        result[key] = _normalize_pool(pools[key])
    return result


def normalize_formal_workspace_views(workspace):
    source = workspace if isinstance(workspace, dict) else {}
    views = source.get("views") if "views" in source else source
    if not isinstance(views, dict):
        raise ValueError("formal workspace views missing")
    result = {}
    for key in POOL_KEYS:
        if key not in views or not isinstance(views[key], list):
            raise ValueError("formal workspace view missing: {}".format(key))
        result[key] = _normalize_pool(views[key])
    return result


def _dedupe_items(rows):
    result = []
    seen = set()
    for item in rows or []:
        code = _candidate_code(item)
        if not code or code in seen:
            continue
        seen.add(code)
        result.append((code, item))
    return result


def diff_pool(preclose_rows, formal_rows):
    """Compare membership while preserving pre-close/formal source order."""

    preclose = _dedupe_items(preclose_rows)
    formal = _dedupe_items(formal_rows)
    preclose_codes = {code for code, _item in preclose}
    formal_codes = {code for code, _item in formal}
    retained = [item for code, item in formal if code in preclose_codes]
    added = [item for code, item in formal if code not in preclose_codes]
    removed = [item for code, item in preclose if code not in formal_codes]
    return {
        "retained": retained,
        "added_after_close": added,
        "removed_after_close": removed,
        "unchanged": not added and not removed,
    }


def _pool_details(preclose_rows, formal_rows):
    preclose_by_code = {
        row["code"]: row for row in preclose_rows
    }
    formal_by_code = {
        row["code"]: row for row in formal_rows
    }
    field_changes = []
    for code in [row["code"] for row in formal_rows if row["code"] in preclose_by_code]:
        changes = {}
        for field in DETAIL_FIELDS:
            before = preclose_by_code[code].get(field)
            after = formal_by_code[code].get(field)
            if before != after:
                changes[field] = {"preclose": before, "formal": after}
        if changes:
            field_changes.append({"code": code, "changes": changes})
    return {
        "preclose_order": [row["code"] for row in preclose_rows],
        "formal_order": [row["code"] for row in formal_rows],
        "field_changes": field_changes,
    }


def _canonical_hash(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _formal_content_hash(formal_views):
    return _canonical_hash({key: formal_views[key] for key in POOL_KEYS})


def reconciliation_content_hash(reconciliation):
    source = reconciliation if isinstance(reconciliation, dict) else {}
    projection = {
        "schema_version": source.get("schema_version"),
        "trade_date": source.get("trade_date"),
        "snapshot_id": source.get("snapshot_id"),
        "preclose_content_hash": source.get("preclose_content_hash"),
        "formal_content_hash": source.get("formal_content_hash"),
        "status": source.get("status"),
        "pools": source.get("pools"),
    }
    return _canonical_hash(projection)


def build_reconciliation(
    preclose_snapshot,
    formal_workspace_views,
    generated_at=None,
):
    source = preclose_snapshot if isinstance(preclose_snapshot, dict) else {}
    preclose = normalize_preclose_pools(source)
    formal = normalize_formal_workspace_views(formal_workspace_views)
    trade_date = str(source.get("trade_date") or "").strip()
    snapshot_id = str(source.get("snapshot_id") or "").strip()
    preclose_hash = str(source.get("content_hash") or "").strip()
    if not trade_date or not snapshot_id or len(preclose_hash) != 64:
        raise ValueError("pre-close snapshot identity missing")
    pools = {}
    changed = False
    for key in POOL_KEYS:
        pool_diff = diff_pool(preclose[key], formal[key])
        pool_diff["details"] = _pool_details(preclose[key], formal[key])
        pools[key] = pool_diff
        changed = changed or not pool_diff["unchanged"]
    result = {
        "schema_version": "preclose-reconciliation-v1",
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "preclose_content_hash": preclose_hash,
        "formal_content_hash": _formal_content_hash(formal),
        "status": "changed" if changed else "unchanged",
        "pools": pools,
    }
    if generated_at:
        result["generated_at"] = str(generated_at)
    result["content_hash"] = reconciliation_content_hash(result)
    return result


def build_formal_pending_reconciliation(preclose_snapshot, generated_at=None):
    source = preclose_snapshot if isinstance(preclose_snapshot, dict) else {}
    normalize_preclose_pools(source)
    trade_date = str(source.get("trade_date") or "").strip()
    snapshot_id = str(source.get("snapshot_id") or "").strip()
    preclose_hash = str(source.get("content_hash") or "").strip()
    if not trade_date or not snapshot_id or len(preclose_hash) != 64:
        raise ValueError("pre-close snapshot identity missing")
    result = {
        "schema_version": "preclose-reconciliation-v1",
        "trade_date": trade_date,
        "snapshot_id": snapshot_id,
        "preclose_content_hash": preclose_hash,
        "formal_content_hash": "0" * 64,
        "status": "formal_pending",
        "pools": {
            key: {
                "retained": [],
                "added_after_close": [],
                "removed_after_close": [],
                "unchanged": False,
                "details": {"status": "formal_pending"},
            }
            for key in POOL_KEYS
        },
    }
    if generated_at:
        result["generated_at"] = str(generated_at)
    result["content_hash"] = reconciliation_content_hash(result)
    return result
