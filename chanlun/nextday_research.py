"""Research-only next-session shortlist adapter and immutable input freeze.

This module adapts completed daily reports to the unchanged selector shipped
with ``nextday-strength-exploration-v0``. It never changes formal report data,
rankings, database contents, or notifications.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .identity import InstrumentIdentity, normalize_identity
from .nextday_candidates import METHODS, number, select_day


ALGORITHM_VERSION = "nextday-strength-exploration-v0"
L1_METHOD = "L1_limit_sector"
B0_METHOD = "B0_original_highlights"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORKSPACE_VIEWS = (
    "main",
    "acceleration",
    "luojie",
    "confirming",
    "baseline",
    "h4_t3",
    "highlights",
    "growth_quality",
    "observation_top5",
)
_RAW_LIST_POOLS = (
    "picks_pure",
    "picks_fusion",
    "startup_watchlist",
    "observation_watchlist",
)
_CANDIDATE_POOLS = ("next_day_boom", "luojie_pool", "h4_t3_pool")
_RISK_FIELDS = (
    "avoid_chase",
    "cancel_conditions",
    "confirmation_conditions",
    "confirmation_evidence",
    "confirmations",
    "daily_startup_warning",
    "failure_gate",
    "invalidation",
    "next_confirmation",
    "next_day_conditions",
    "pending_confirmations",
    "price_basis",
    "reason",
    "reference_price",
    "reference_type",
    "risk_flags",
    "risk_reasons",
    "signal_date",
    "source_type",
    "startup_date",
    "startup_reason",
    "startup_signals",
    "stop_loss",
    "stop_loss_pct",
    "upgrade_conditions",
    "watch_anchor",
    "watch_reason",
)
_SOURCE_FIELDS = (
    "change_pct",
    "volume_ratio",
    "close_position",
    "f_alignment",
    "f_fomo",
    "vs_ma20",
    "breakout20",
)


class ResearchInputError(ValueError):
    """A malformed report or invalid command-line input."""


def _date_text(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def _report_date(report: Mapping[str, Any]) -> str:
    primary = report.get("date")
    secondary = report.get("report_date")
    if primary is not None and secondary is not None and primary != secondary:
        raise ResearchInputError("report date fields conflict")
    value = primary if primary is not None else secondary
    normalized = _date_text(value)
    if normalized is None:
        raise ResearchInputError("report must contain an explicit ISO report date")
    return normalized


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _compact_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_value(row: Mapping[str, Any], field: str, nested_field: Optional[str] = None) -> Any:
    if field in row:
        return _json_safe(row.get(field))
    if nested_field:
        actual = row.get("actual_value")
        if isinstance(actual, Mapping) and nested_field in actual:
            return _json_safe(actual.get(nested_field))
    return None


def _nonnegative_count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _sector_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _time_date(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:10] if len(value) >= 10 and _date_text(value[:10]) else None


def _identity_alias(value: Any) -> InstrumentIdentity:
    if isinstance(value, InstrumentIdentity):
        identity = normalize_identity(value)
    elif isinstance(value, Mapping):
        identity = normalize_identity(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.count("|") == 2:
            asset_type, exchange, code = text.split("|", 2)
            identity = normalize_identity(
                {"asset_type": asset_type, "exchange": exchange, "code": code}
            )
        elif re.match(r"^(SH|SZ|BJ)\d{6}$", text):
            identity = normalize_identity(
                {"asset_type": "stock", "exchange": text[:2], "code": text[2:]}
            )
        elif re.match(r"^\d{6}$", text):
            identity = normalize_identity(text)
        else:
            raise ValueError("identity alias has an unsupported format")
    else:
        raise ValueError("identity alias must be a canonical string or object")
    if identity.asset_type != "stock":
        raise ValueError("research candidates must have stock identities")
    return identity


def _identity_for(
    row: Mapping[str, Any], additional_mappings: Iterable[Mapping[str, Any]] = ()
) -> InstrumentIdentity:
    identity = normalize_identity(row)
    if identity.asset_type != "stock":
        raise ValueError("research candidates must have stock identities")
    for mapping in (row,) + tuple(additional_mappings):
        if not isinstance(mapping, Mapping):
            continue
        for field in ("instrument_id", "stock_identity", "identity", "identity_details", "identity_key"):
            value = mapping.get(field)
            if value is None:
                continue
            declared = _identity_alias(value)
            if declared.key != identity.key:
                raise ValueError("{} conflicts with candidate code/exchange".format(field))
        if mapping.get("code") is not None:
            declared_fields = {
                "asset_type": mapping.get("asset_type") or identity.asset_type,
                "exchange": mapping.get("exchange") or identity.exchange,
                "code": mapping.get("code"),
            }
            declared = normalize_identity(declared_fields)
            if declared.key != identity.key:
                raise ValueError("declared code conflicts with candidate identity")
    return identity


def _study_id(identity: InstrumentIdentity) -> str:
    return identity.exchange + identity.code


def _source_risk_fields(row: Mapping[str, Any]) -> Dict[str, Any]:
    result = {}
    for field in _RISK_FIELDS:
        if field in row and row.get(field) is not None:
            result[field] = _json_safe(row.get(field))
    best_buy = row.get("best_buy_point")
    if (
        "confirmation_evidence" not in result
        and isinstance(best_buy, Mapping)
        and best_buy.get("confirmation_evidence") is not None
    ):
        result["confirmation_evidence"] = _json_safe(
            best_buy.get("confirmation_evidence")
        )
    return result


def _candidate_source(
    value: Any,
    *,
    pool: Optional[str] = None,
    view: Optional[str] = None,
    archive_rank: Any = None,
    archive_item: Optional[Mapping[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not isinstance(value, Mapping):
        return None, "candidate row is not an object"
    row = dict(value)
    declared_names = []
    if isinstance(archive_item, Mapping):
        for raw_name in (row.get("name"), archive_item.get("name")):
            if isinstance(raw_name, str) and raw_name.strip() and raw_name.strip() not in declared_names:
                declared_names.append(raw_name.strip())
        for field in ("code", "name", "sector", "industry") + _RISK_FIELDS:
            if row.get(field) is None and archive_item.get(field) is not None:
                row[field] = archive_item.get(field)
    elif isinstance(row.get("name"), str) and row.get("name").strip():
        declared_names.append(row.get("name").strip())
    try:
        identity = _identity_for(row, (archive_item,) if isinstance(archive_item, Mapping) else ())
    except (TypeError, ValueError) as exc:
        return None, "candidate identity invalid: {}".format(str(exc))
    raw_name = row.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else None
    item = {
        "instrument_id": _study_id(identity),
        "identity_key": identity.key,
        "identity_details": identity.as_dict(),
        "code": identity.code,
        "name": name or None,
        "raw": row,
        "source_pool": pool,
        "source_view": view,
        "archive_rank": archive_rank,
        "risk_fields": _source_risk_fields(row),
        "name_variants": declared_names,
    }
    return item, None


def _snapshot_rows(
    report_date: str, snapshot: Any
) -> Tuple[bool, str, str, Dict[str, Dict[str, Any]]]:
    if not isinstance(snapshot, Mapping):
        return False, "limit_up_snapshot_missing", "missing", {}
    status = snapshot.get("status")
    snapshot_date = _date_text(snapshot.get("date"))
    as_of_date = _time_date(snapshot.get("as_of"))
    if snapshot_date != report_date or as_of_date != report_date:
        return False, "limit_up_snapshot_date_mismatch", str(status or "missing"), {}
    raw_total = _nonnegative_count(snapshot.get("raw_total"))
    parsed_count = _nonnegative_count(snapshot.get("parsed_count"))
    error_count = _nonnegative_count(snapshot.get("parse_error_count"))
    items = snapshot.get("items")
    if not isinstance(items, list):
        return False, "limit_up_snapshot_items_missing", str(status or "missing"), {}
    if raw_total is None or parsed_count is None or error_count is None:
        return False, "limit_up_snapshot_counts_missing_or_invalid", str(status or "missing"), {}
    if raw_total != parsed_count or parsed_count != len(items) or error_count != 0:
        return False, "limit_up_snapshot_partial_or_has_errors", str(status or "missing"), {}
    if status == "verified_empty":
        if raw_total != 0 or parsed_count != 0 or items:
            return False, "verified_empty_counts_conflict", status, {}
        return True, "", status, {}
    if status != "verified_complete":
        return False, "limit_up_snapshot_not_verified_complete", str(status or "missing"), {}
    coverage = snapshot.get("coverage")
    if (
        raw_total <= 0
        or not number(coverage)
        or coverage != 1.0
    ):
        return False, "limit_up_snapshot_coverage_incomplete", status, {}
    by_identity: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            return False, "limit_up_snapshot_item_invalid", status, {}
        try:
            identity = _identity_for(item)
        except (TypeError, ValueError):
            return False, "limit_up_snapshot_identity_invalid_at_{}".format(index), status, {}
        key = identity.key
        normalized = {
            "identity_key": key,
            "instrument_id": _study_id(identity),
            "identity_details": identity.as_dict(),
            "code": identity.code,
            "name": item.get("name") if isinstance(item.get("name"), str) else None,
            "sector": _sector_text(item.get("sector", item.get("industry"))),
            "board_n": _json_safe(item.get("lianban")),
            "first_limit_time": _json_safe(item.get("first_time")),
        }
        previous = by_identity.get(key)
        if previous is None:
            by_identity[key] = normalized
            continue
        identity_facts = ("code", "name", "sector", "board_n", "first_limit_time")
        if any(_compact_json(previous.get(field)) != _compact_json(normalized.get(field)) for field in identity_facts):
            return False, "limit_up_snapshot_duplicate_identity_conflict", status, {}
    if len(by_identity) != raw_total:
        return False, "limit_up_snapshot_unique_identity_coverage_incomplete", status, {}
    return True, "", status, by_identity


def _source_lists(report: Mapping[str, Any]) -> Tuple[List[Tuple[str, Any]], List[Tuple[str, Any]], List[str]]:
    pool_rows: List[Tuple[str, Any]] = []
    view_rows: List[Tuple[str, Any]] = []
    errors: List[str] = []
    for pool in _RAW_LIST_POOLS:
        if pool not in report:
            errors.append("{} is missing".format(pool))
            continue
        rows = report.get(pool)
        if not isinstance(rows, list):
            errors.append("{} must be an array".format(pool))
            continue
        pool_rows.extend((pool, row) for row in rows)
    for pool in _CANDIDATE_POOLS:
        if pool not in report:
            errors.append("{} is missing".format(pool))
            continue
        value = report.get(pool)
        if not isinstance(value, Mapping):
            errors.append("{} must be an object".format(pool))
            continue
        if "candidates" not in value:
            errors.append("{}.candidates is missing".format(pool))
            continue
        rows = value.get("candidates")
        if not isinstance(rows, list):
            errors.append("{}.candidates must be an array".format(pool))
            continue
        pool_rows.extend((pool, row) for row in rows)
    workspace = report.get("workspace")
    if workspace is None:
        errors.append("workspace is missing")
    else:
        if not isinstance(workspace, Mapping):
            errors.append("workspace must be an object")
        else:
            views = workspace.get("views")
            if views is None:
                errors.append("workspace.views is missing")
            elif not isinstance(views, Mapping):
                errors.append("workspace.views must be an object")
            elif isinstance(views, Mapping):
                for view in _WORKSPACE_VIEWS:
                    if view not in views:
                        continue
                    rows = views.get(view)
                    if not isinstance(rows, list):
                        errors.append("workspace.views.{} must be an array".format(view))
                        continue
                    view_rows.extend((view, row) for row in rows)
    return pool_rows, view_rows, errors


def _archive_candidates(
    report_date: str, archived_workbench: Any
) -> Tuple[str, str, List[Tuple[Any, Any]], List[str]]:
    if not isinstance(archived_workbench, Mapping):
        return "not_evaluated", "matching_archived_workbench_missing", [], []
    if archived_workbench.get("identity_matches") is not True:
        return "not_evaluated", "archived_workbench_report_mismatch", [], []
    workbench = archived_workbench.get("workbench")
    if not isinstance(workbench, Mapping):
        return "not_evaluated", "archived_workbench_invalid", [], []
    if _date_text(workbench.get("report_date")) != report_date:
        return "not_evaluated", "archived_workbench_report_date_mismatch", [], []
    items = workbench.get("items")
    if not isinstance(items, list):
        return "not_evaluated", "archived_workbench_items_missing", [], []
    result = []
    errors = []
    rank_by_identity = {}
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        strategies = item.get("strategy_results")
        if not isinstance(strategies, list):
            continue
        for strategy in strategies:
            if not isinstance(strategy, Mapping) or strategy.get("strategy_id") != "highlights":
                continue
            rank = strategy.get("view_rank")
            candidate = strategy.get("candidate")
            if not isinstance(candidate, Mapping):
                candidate = item.get("candidate")
            if not isinstance(candidate, Mapping):
                candidate = {}
            merged = dict(candidate)
            for field in ("code", "name", "sector", "industry") + _RISK_FIELDS:
                if merged.get(field) is None and item.get(field) is not None:
                    merged[field] = item.get(field)
            if not number(rank):
                errors.append("archived highlight view_rank missing at item {}".format(index))
            parsed, error = _candidate_source(
                merged,
                view="decisionWorkbench.highlights",
                archive_rank=rank,
                archive_item=item,
            )
            if error:
                errors.append("archived highlight {}: {}".format(index, error))
                continue
            key = parsed["identity_key"]
            prior = rank_by_identity.get(key)
            if prior is not None and _compact_json(prior) != _compact_json(rank):
                errors.append("archived highlights duplicate identity rank conflict")
                continue
            rank_by_identity[key] = rank
            result.append((parsed, rank))
    if errors:
        return "not_evaluated", "archived_highlights_invalid", result, errors
    return "evaluated", "", result, []


def _merge_candidate_records(
    sources: Iterable[Dict[str, Any]],
    snapshot_by_identity: Mapping[str, Dict[str, Any]],
    snapshot_status: str,
    snapshot_valid: bool,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    merged: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for source in sources:
        key = source["identity_key"]
        raw = source["raw"]
        prior = merged.get(key)
        if prior is None:
            item = {
                "report_date": source["report_date"],
                "algorithm_version": ALGORITHM_VERSION,
                "instrument_id": source["instrument_id"],
                "stock_identity": source["instrument_id"],
                "identity": source["instrument_id"],
                "identity_details": source["identity_details"],
                "asset_type": source["identity_details"]["asset_type"],
                "exchange": source["identity_details"]["exchange"],
                "code": source["identity_details"]["code"],
                "name": source["name"],
                "f_change_pct": _source_value(raw, "change_pct", "change_pct"),
                "f_volume_ratio": _source_value(raw, "volume_ratio", "volume_ratio"),
                "close_position": _source_value(raw, "close_position"),
                "f_alignment": _source_value(raw, "f_alignment"),
                "f_fomo": _source_value(raw, "f_fomo"),
                "vs_ma20": _source_value(raw, "vs_ma20"),
                "breakout20": _source_value(raw, "breakout20"),
                "is_highlight": False,
                "highlight_rank": None,
                "source_pools": [],
                "source_views": [],
                "source_evidence": [],
                "name_variants": list(source.get("name_variants") or ([source["name"]] if source.get("name") else [])),
                "sector": _sector_text(raw.get("sector", raw.get("industry"))),
                "limit_sector": None,
                "own_limit_sector_count": None,
                "limit_status": snapshot_status,
                "in_limit_snapshot": False if snapshot_valid else None,
                "board_n": None,
                "first_limit_time": None,
            }
            item.update(copy.deepcopy(source["risk_fields"]))
            item["source_risk_fields"] = []
            merged[key] = item
            prior = item
        else:
            if prior.get("code") != source["identity_details"]["code"]:
                errors.append("identity code conflict for {}".format(source["instrument_id"]))
            prior_name = prior.get("name")
            source_name = source.get("name")
            for variant in source.get("name_variants") or ([source_name] if source_name else []):
                if variant and variant not in prior["name_variants"]:
                    prior["name_variants"].append(variant)
            if prior_name is None and source_name:
                prior["name"] = source_name
            for field in _SOURCE_FIELDS:
                if prior.get({"change_pct": "f_change_pct", "volume_ratio": "f_volume_ratio"}.get(field, field)) is None:
                    target = {"change_pct": "f_change_pct", "volume_ratio": "f_volume_ratio"}.get(field, field)
                    prior[target] = _source_value(raw, field, field if field in ("change_pct", "volume_ratio") else None)
            for field, value in source["risk_fields"].items():
                if prior.get(field) is None:
                    prior[field] = copy.deepcopy(value)
        if source.get("source_pool") and source["source_pool"] not in prior["source_pools"]:
            prior["source_pools"].append(source["source_pool"])
        if source.get("source_view") and source["source_view"] not in prior["source_views"]:
            prior["source_views"].append(source["source_view"])
        evidence = {
            "source_pool": source.get("source_pool"),
            "source_view": source.get("source_view"),
            "name": source.get("name"),
            "risk_fields": source["risk_fields"],
        }
        if source.get("source_pool") or source.get("source_view"):
            prior["source_evidence"].append(evidence)
        if source.get("archive_rank") is not None:
            if prior["is_highlight"] and _compact_json(prior["highlight_rank"]) != _compact_json(source["archive_rank"]):
                errors.append("duplicate archived highlight rank for {}".format(source["instrument_id"]))
            prior["is_highlight"] = True
            prior["highlight_rank"] = source["archive_rank"]
    for item in merged.values():
        item["source_pools"] = sorted(item["source_pools"])
        item["source_views"] = sorted(item["source_views"])
        item["source_evidence"] = sorted(
            item["source_evidence"],
            key=lambda value: (value.get("source_pool") or "", value.get("source_view") or ""),
        )
        snapshot = snapshot_by_identity.get(item["identity_details"]["asset_type"] + "|" + item["identity_details"]["exchange"] + "|" + item["identity_details"]["code"])
        if snapshot is not None:
            item["in_limit_snapshot"] = True
            snapshot_name = snapshot.get("name")
            if snapshot_name and snapshot_name not in item["name_variants"]:
                item["name_variants"].append(snapshot_name)
            item["limit_sector"] = snapshot["sector"]
            item["board_n"] = snapshot["board_n"]
            item["first_limit_time"] = snapshot["first_limit_time"]
            item["name"] = item.get("name") or snapshot.get("name")
        item["name_variants"] = sorted(set(item["name_variants"]))
    sector_count = defaultdict(int)
    for item in snapshot_by_identity.values():
        sector = item.get("sector")
        if sector:
            sector_count[sector] += 1
    for item in merged.values():
        snapshot = snapshot_by_identity.get(item["identity_details"]["asset_type"] + "|" + item["identity_details"]["exchange"] + "|" + item["identity_details"]["code"])
        sector = snapshot.get("sector") if snapshot is not None else None
        item["own_limit_sector_count"] = sector_count.get(sector) if sector else None
    rows = sorted(merged.values(), key=lambda row: row["instrument_id"])
    return rows, errors


def adapt_report(
    report: Mapping[str, Any], archived_workbench: Any = None
) -> Dict[str, Any]:
    """Return minimal normalized inputs and independent L1/B0 selections."""
    if not isinstance(report, Mapping):
        raise ResearchInputError("report must be a JSON object")
    report_date = _report_date(report)
    snapshot_ok, snapshot_reason, snapshot_status, snapshot_by_identity = _snapshot_rows(
        report_date, report.get("limit_up_snapshot")
    )
    pool_rows, view_rows, source_errors = _source_lists(report)
    archive_status, archive_reason, archive_rows, archive_errors = _archive_candidates(
        report_date, archived_workbench
    )
    parsed_sources: List[Dict[str, Any]] = []
    candidate_errors: List[str] = []
    raw_candidate_count = 0
    for pool, raw in pool_rows:
        raw_candidate_count += 1
        parsed, error = _candidate_source(raw, pool=pool)
        if error:
            candidate_errors.append("{}: {}".format(pool, error))
        elif parsed:
            parsed["report_date"] = report_date
            parsed_sources.append(parsed)
    for view, raw in view_rows:
        raw_candidate_count += 1
        parsed, error = _candidate_source(raw, view=view)
        if error:
            candidate_errors.append("workspace.views.{}: {}".format(view, error))
        elif parsed:
            parsed["report_date"] = report_date
            parsed_sources.append(parsed)
    for parsed, rank in archive_rows:
        parsed["report_date"] = report_date
        parsed["source_view"] = "decisionWorkbench.highlights"
        parsed["archive_rank"] = rank
    report_identity_keys = {source["identity_key"] for source in parsed_sources}
    usable_archive_sources = (
        [parsed for parsed, _rank in archive_rows]
        if archive_status == "evaluated" and not archive_errors
        else []
    )
    l1_sources = parsed_sources + [
        source for source in usable_archive_sources
        if source["identity_key"] in report_identity_keys
    ]
    rows, merge_errors = _merge_candidate_records(
        l1_sources, snapshot_by_identity, snapshot_status, snapshot_ok
    )
    archive_identity_keys = {source["identity_key"] for source in usable_archive_sources}
    b0_sources = [
        source for source in parsed_sources
        if source["identity_key"] in archive_identity_keys
    ] + usable_archive_sources
    b0_rows, b0_merge_errors = _merge_candidate_records(
        b0_sources, snapshot_by_identity, snapshot_status, snapshot_ok
    )
    errors = source_errors + candidate_errors + merge_errors + b0_merge_errors + archive_errors
    l1_errors = list(source_errors) + list(candidate_errors) + list(merge_errors)
    if not snapshot_ok:
        l1_errors.append(snapshot_reason)
    l1_ok = snapshot_ok and not l1_errors
    l1_selected = select_day(rows, report_date, L1_METHOD, 5) if l1_ok else []
    if archive_status == "evaluated" and not archive_errors and not b0_merge_errors:
        b0_selected = select_day(b0_rows, report_date, B0_METHOD, 5)
        b0_reason = ""
    else:
        b0_selected = []
        b0_reason = archive_reason or "archived_highlights_invalid"
    snapshot_count = len(snapshot_by_identity)
    intersection_count = sum(
        1 for row in rows if row["identity_details"]["asset_type"] + "|" + row["identity_details"]["exchange"] + "|" + row["identity_details"]["code"] in snapshot_by_identity
    )
    return {
        "schema_version": 1,
        "status": "research_only",
        "report_date": report_date,
        "algorithm_version": ALGORITHM_VERSION,
        "freeze_status": "valid" if l1_ok else "input_insufficient",
        "normalized_candidates": rows,
        "errors": errors,
        "summary": {
            "raw_candidate_count": raw_candidate_count,
            "candidate_count": len(rows),
            "archive_highlights_count": len(usable_archive_sources),
            "snapshot_status": snapshot_status,
            "snapshot_unique_count": snapshot_count if snapshot_ok else None,
            "candidate_snapshot_intersection": intersection_count if snapshot_ok else None,
        },
        "l1": {
            "status": "evaluated" if l1_ok else "not_evaluated",
            "method": L1_METHOD,
            "reason": "" if l1_ok else "; ".join(l1_errors),
            "selected": l1_selected,
        },
        "b0": {
            "status": (
                "evaluated"
                if archive_status == "evaluated" and not archive_errors and not b0_merge_errors
                else "not_evaluated"
            ),
            "method": B0_METHOD,
            "source": "same_report_archived_decisionWorkbench",
            "reason": b0_reason,
            "selected": b0_selected,
        },
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".{}-".format(path.name), dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, str(path))
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _write_json(path: Path, value: Any) -> None:
    content = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    _atomic_write(path, content)


@contextmanager
def _date_lock(date_dir: Path):
    date_dir.mkdir(parents=True, exist_ok=True)
    lock_path = date_dir / ".selection.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _registration_status(report_date: str, frozen_at: str) -> str:
    frozen_date = _date_text(frozen_at[:10]) if isinstance(frozen_at, str) else None
    if frozen_date is None:
        return "retrospective"
    return "prospective" if frozen_date <= report_date else "retrospective"


def _conflict_path(date_dir: Path, source_hash: str) -> Path:
    token = re.sub(r"[^a-fA-F0-9]", "", source_hash)[:16] or "unknown"
    return date_dir / "conflicts" / (token + ".json")


def freeze_selection(
    output_dir: Path,
    prepared: Mapping[str, Any],
    source_hash: str,
    frozen_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Freeze one report date; only an incomplete first attempt can be upgraded."""
    report_date = _date_text(prepared.get("report_date"))
    if report_date is None:
        raise ResearchInputError("prepared selection has no valid report date")
    runs_dir = Path(output_dir)
    date_dir = runs_dir / report_date
    selection_path = date_dir / "selection.json"
    frozen_at = frozen_at or _now_iso()
    incoming = copy.deepcopy(_json_safe(dict(prepared)))
    incoming["source_hash"] = str(source_hash)
    incoming["frozen_at"] = frozen_at
    incoming["registration_status"] = _registration_status(report_date, frozen_at)
    incoming.setdefault("source_hashes", {})
    incoming["freeze_attempted_at"] = frozen_at
    with _date_lock(date_dir):
        if not selection_path.exists():
            _write_json(selection_path, incoming)
            return {"action": "created", "selection_path": str(selection_path)}
        try:
            existing = json.loads(selection_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ResearchInputError("existing frozen selection cannot be read: {}".format(exc))
        if existing.get("freeze_status") == "input_insufficient" and incoming.get("freeze_status") == "valid":
            incoming["supersedes_source_hash"] = existing.get("source_hash")
            incoming["first_attempted_at"] = existing.get("freeze_attempted_at") or existing.get("frozen_at")
            _write_json(selection_path, incoming)
            return {"action": "upgraded", "selection_path": str(selection_path)}
        if existing.get("source_hash") == source_hash:
            return {"action": "unchanged", "selection_path": str(selection_path)}
        conflict = {
            "report_date": report_date,
            "recorded_at": _now_iso(),
            "frozen_source_hash": existing.get("source_hash"),
            "incoming_source_hash": str(source_hash),
            "frozen_status": existing.get("freeze_status"),
            "incoming_status": incoming.get("freeze_status"),
            "reason": "frozen_selection_is_immutable",
        }
        conflict_path = _conflict_path(date_dir, str(source_hash))
        if not conflict_path.exists():
            _write_json(conflict_path, conflict)
        return {"action": "conflict", "selection_path": str(selection_path), "conflict_path": str(conflict_path)}


def _read_archived_workbench(report_path: Path, report: Mapping[str, Any], report_date: str) -> Tuple[Any, Optional[str], Optional[str]]:
    data_dir = report_path.parent
    archive_path = data_dir.resolve().parent / report_date / "index.html"
    archive_hash = None
    try:
        archive_bytes = archive_path.read_bytes()
        archive_hash = _sha256(archive_bytes)
    except OSError:
        pass
    try:
        from .report_comparison import _read_archived_workbench as reader

        result = reader(str(data_dir), report_date, report)
    except Exception:
        return None, archive_hash, "archived_workbench_reader_unavailable"
    if result is None:
        return None, archive_hash, "matching_archived_workbench_missing"
    return result, archive_hash, None


def _process_guard(report: Mapping[str, Any], report_date: str, as_of_date: str) -> List[str]:
    reasons = []
    if as_of_date != report_date:
        reasons.append("requested_as_of_does_not_match_report_date")
    if report_date > as_of_date or report_date > date.today().isoformat():
        reasons.append("future_report_date")
    quality = report.get("data_quality")
    if isinstance(quality, Mapping):
        quality_date = quality.get("report_date")
        if quality_date is not None and quality_date != report_date:
            reasons.append("data_quality_report_date_mismatch")
        quality_as_of = _time_date(quality.get("as_of"))
        if quality_as_of is not None and quality_as_of != report_date:
            reasons.append("data_quality_as_of_mismatch")
        bar_state = quality.get("bar_state")
        if bar_state is not None and bar_state != "closed":
            reasons.append("report_bar_state_not_closed")
        if "is_official" in quality and quality.get("is_official") is not True:
            reasons.append("report_not_official")
    if "is_official" in report and report.get("is_official") is not True:
        reasons.append("report_not_official")
    if report.get("bar_state") is not None and report.get("bar_state") != "closed":
        reasons.append("report_bar_state_not_closed")
    return reasons


def _apply_process_guard(prepared: Dict[str, Any], reasons: List[str]) -> None:
    if not reasons:
        return
    prepared["freeze_status"] = "input_insufficient"
    prepared["guard_errors"] = list(reasons)
    prepared["errors"] = list(prepared.get("errors") or []) + list(reasons)
    prepared["l1"] = dict(prepared["l1"], status="not_evaluated", selected=[], reason="; ".join(reasons))
    prepared["b0"] = dict(prepared["b0"], status="not_evaluated", selected=[], reason="; ".join(reasons))


def _load_evaluator():
    from .nextday_outcomes import evaluate_frozen_selection as evaluator

    return evaluator


def evaluate_frozen_selection(snapshot: Mapping[str, Any], db_path: Path, as_of_date: str) -> Mapping[str, Any]:
    """Lazy public seam for the read-only outcome evaluator."""
    return _load_evaluator()(snapshot, db_path, as_of_date)


def _run_group(
    report_date: str,
    group_name: str,
    selection: Mapping[str, Any],
    db_path: Path,
    as_of_date: str,
    evaluator: Any,
) -> Dict[str, Any]:
    group = selection.get(group_name) or {}
    if group.get("status") != "evaluated":
        return {
            "status": "not_evaluated",
            "reason": group.get("reason") or "selection_not_evaluated",
            "selected": [],
            "outcome_rows": [],
            "metrics": {"selected": 0},
        }
    selected = group.get("selected") or []
    if not selected:
        return {
            "status": "evaluated_empty",
            "report_date": report_date,
            "as_of_date": as_of_date,
            "selected": [],
            "outcome_rows": [],
            "metrics": {"selected": 0, "observed_cc1": 0, "observed_oc1": 0},
        }
    snapshot = {"report_date": report_date, "selected": selected}
    result = evaluator(snapshot, db_path, as_of_date)
    if not isinstance(result, Mapping):
        raise TypeError("nextday outcome evaluator returned a non-object")
    return {
        "status": result.get("status") or "evaluated",
        "report_date": result.get("report_date") or report_date,
        "as_of_date": result.get("as_of_date") or as_of_date,
        "selected": selected,
        "outcome_rows": result.get("outcome_rows") or [],
        "metrics": result.get("metrics") or {},
        "calendar_status": result.get("calendar_status"),
        "target_dates": result.get("target_dates"),
        "interpretation_note": result.get("interpretation_note"),
    }


def _md(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        value = json.dumps(_json_safe(value), ensure_ascii=False, separators=(",", ":"))
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _row_by_identity(outcome_rows: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    result = {}
    for row in outcome_rows:
        if not isinstance(row, Mapping):
            continue
        selection = row.get("selection")
        if isinstance(selection, Mapping):
            identity = selection.get("instrument_id")
        else:
            identity = row.get("instrument_id") or row.get("identity")
        if isinstance(identity, str):
            result[identity] = row
    return result


def _percent(value: Any) -> str:
    if not number(value):
        return "—"
    return "{:.2f}%".format(value)


def _observed_count(metrics: Mapping[str, Any], name: str) -> int:
    value = metrics.get("observed_{}".format(name))
    if value is None and name == "cc1":
        value = metrics.get("observed_T1")
    if value is None and name in ("oc2", "oc3"):
        value = metrics.get("{}_observed".format(name))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _unobserved_status(metrics: Mapping[str, Any], selected: int, horizon: str) -> str:
    parts = []
    for key, label, aliases in (
        ("pending_{}".format(horizon), "未到期", ("pending_T1",) if horizon == "t1" else ()),
        ("basis_unverified_{}".format(horizon), "价基未核验", ("basis_unverified_T1",) if horizon == "t1" else ()),
        ("missing_{}".format(horizon), "数据缺失", ("missing_T1",) if horizon == "t1" else ()),
        ("nonfinal_{}".format(horizon), "未最终确认", ("nonfinal_T1",) if horizon == "t1" else ()),
        ("calendar_unavailable_{}".format(horizon), "交易日历不可用", ("calendar_unavailable",) if horizon == "t1" else ()),
    ):
        count = metrics.get(key)
        if count is None:
            for alias in aliases:
                if metrics.get(alias) is not None:
                    count = metrics.get(alias)
                    break
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            parts.append("{} {}".format(label, count))
    return "、".join(parts) if parts else ("未到期／未核验 {}".format(selected) if selected else "有效空名单")


def _append_metric_lines(lines: List[str], metrics: Mapping[str, Any], selected_count: int) -> None:
    labels = (
        ("cc1", "信号日收盘→次日收盘（CC1）", "cc1_mean", "cc1_median", "t1"),
        ("gap1", "信号日收盘→次日开盘（Gap1）", "gap1_mean", None, "t1"),
        ("oc1", "次日开盘→次日收盘（OC1）", "oc1_mean", "oc1_median", "t1"),
        ("oc2", "次日开盘→T+2收盘（OC2）", "oc2_mean", None, "t2"),
        ("oc3", "次日开盘→T+3收盘（OC3）", "oc3_mean", None, "t3"),
    )
    observed = {}
    for key, label, mean_key, median_key, horizon in labels:
        count = _observed_count(metrics, key)
        observed[key] = count
        pieces = ["可观察 {}/{}".format(count, selected_count)]
        if count:
            mean_value = metrics.get(mean_key)
            if mean_value is not None:
                pieces.append("均值 {}".format(_percent(mean_value)))
            if median_key:
                median_value = metrics.get(median_key)
                if median_value is not None:
                    pieces.append("中位数 {}".format(_percent(median_value)))
        else:
            pieces.append(_unobserved_status(metrics, selected_count, horizon))
        lines.append("- {}：{}。".format(label, "；".join(pieces)))
    if observed["cc1"]:
        gain = metrics.get("nextday_gain_ge5")
        loss = metrics.get("nextday_loss_le_minus5")
        if gain is not None or loss is not None:
            lines.append(
                "- CC1 阈值计数：涨幅 ≥5% {} / {}；跌幅 ≤−5% {} / {}。".format(
                    gain if gain is not None else "—",
                    observed["cc1"],
                    loss if loss is not None else "—",
                    observed["cc1"],
                )
            )
    if observed["oc1"]:
        gain = metrics.get("open_close_gain_ge3")
        loss = metrics.get("open_close_loss_le_minus5")
        if gain is not None or loss is not None:
            lines.append(
                "- OC1 阈值计数：涨幅 ≥3% {} / {}；跌幅 ≤−5% {} / {}。".format(
                    gain if gain is not None else "—",
                    observed["oc1"],
                    loss if loss is not None else "—",
                    observed["oc1"],
                )
            )


def _format_group_markdown(name: str, group: Mapping[str, Any], outcomes: Mapping[str, Any]) -> List[str]:
    rows = group.get("selected") or []
    status = group.get("status") or "not_evaluated"
    lines = ["## {}".format(name), "", "- 评估状态：{}".format(status)]
    if status != "evaluated":
        reason = group.get("reason")
        if reason:
            lines.append("- 未评估原因：{}".format(_md(reason)))
        lines.append("")
        return lines
    lines.append("- 入选数量：{}。".format(len(rows)))
    lines.append("")
    if not rows:
        lines.append("本组没有候选。" if status == "evaluated" else "本组未形成可评估名单。")
        lines.append("")
    else:
        outcome_by_identity = _row_by_identity(outcomes.get("outcome_rows") or [])
        for row in rows:
            identity = row.get("instrument_id")
            outcome = outcome_by_identity.get(identity, {})
            rank = row.get("research_rank", row.get("highlight_rank"))
            sector = row.get("limit_sector") or row.get("sector")
            sources = row.get("source_pools") or row.get("source_views") or []
            lines.append(
                "{}. **{}（{}）** — 行业：{}；板块涨停家数：{}；连板：{}；首封：{}；来源：{}。".format(
                    _md(rank),
                    _md(row.get("name") or row.get("code")),
                    _md(identity),
                    _md(sector),
                    _md(row.get("own_limit_sector_count")),
                    _md(row.get("board_n")),
                    _md(row.get("first_limit_time")),
                    _md(sources),
                )
            )
            pending = row.get("next_confirmation") or row.get("next_day_conditions") or row.get("pending_confirmations")
            cancel = row.get("cancel_conditions") or row.get("invalidation") or row.get("risk_flags")
            if pending:
                lines.append("   - 待确认：{}。".format(_md(pending)))
            if cancel:
                lines.append("   - 风险／取消条件：{}。".format(_md(cancel)))
            if row.get("avoid_chase") is True:
                lines.append("   - 记录的风险提示：避免追高。")
            if outcome:
                status_text = outcome.get("outcome_status") or outcome.get("maturity_status") or outcome.get("basis_status")
                lines.append("   - 结果状态：{}。".format(_md(status_text)))
                outcome_values = "；".join(
                    "{} {}".format(label, _percent(outcome.get(field)))
                    for label, field in (("CC1", "cc1"), ("Gap1", "gap1"), ("OC1", "oc1"), ("OC2", "oc2"), ("OC3", "oc3"))
                )
                lines.append("   - 已核验结果：{}。".format(outcome_values))
        lines.append("")
    metrics = outcomes.get("metrics") or {}
    if metrics:
        selected_count = metrics.get("selected", len(rows))
        _append_metric_lines(lines, metrics, selected_count)
        lines.append("")
    return lines


def render_shortlist(selection: Mapping[str, Any], outcomes: Optional[Mapping[str, Any]] = None) -> str:
    outcomes = outcomes or {}
    date_text = selection.get("report_date", "unknown")
    lines = [
        "# 次日研究记录 | {}".format(date_text),
        "",
        "本记录仅用于研究观察，不构成交易指令；不改变正式候选、排序或日报内容。指标不是实盘盈亏模拟，未计手续费、滑点、排队位置或成交概率。",
        "",
        "- 算法版本：{}".format(_md(selection.get("algorithm_version"))),
        "- 输入冻结状态：{}".format(_md(selection.get("freeze_status"))),
        "- 首次有效登记：{}（{}）".format(
            _md(selection.get("frozen_at")), _md(selection.get("registration_status"))
        ),
    ]
    summary = selection.get("summary") or {}
    lines.extend(
        [
            "- 归一化标的数：{}；涨停快照唯一标的数：{}；交集：{}。".format(
                _md(summary.get("candidate_count")),
                _md(summary.get("snapshot_unique_count")),
                _md(summary.get("candidate_snapshot_intersection")),
            ),
            "",
        ]
    )
    if selection.get("source_run_id"):
        lines.insert(6, "- 来源运行 ID：{}".format(_md(selection.get("source_run_id"))))
    if selection.get("errors"):
        lines.append("输入限制：{}。".format(_md(selection.get("errors"))))
        lines.append("")
    lines.extend(_format_group_markdown("L1 涨停板块排序", selection.get("l1") or {}, outcomes.get("l1") or {}))
    lines.extend(_format_group_markdown("B0 原看点对照", selection.get("b0") or {}, outcomes.get("b0") or {}))
    if outcomes.get("refresh_error"):
        lines.extend(["## 结果刷新", "", "本次结果读取失败：{}。".format(_md(outcomes.get("refresh_error"))), ""])
    return "\n".join(lines).rstrip() + "\n"


def _refresh_date(
    date_dir: Path,
    db_path: Path,
    as_of_date: str,
    evaluator: Any,
) -> Dict[str, Any]:
    selection_path = date_dir / "selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    report_date = _date_text(selection.get("report_date"))
    if report_date is None or report_date != date_dir.name:
        raise ResearchInputError("frozen selection date/path mismatch")
    if report_date > as_of_date:
        return {"report_date": report_date, "status": "future_skipped", "selection": selection}
    result = {
        "schema_version": 1,
        "report_date": report_date,
        "as_of_date": as_of_date,
        "refreshed_at": _now_iso(),
        "l1": _run_group(report_date, "l1", selection, db_path, as_of_date, evaluator),
        "b0": _run_group(report_date, "b0", selection, db_path, as_of_date, evaluator),
    }
    _write_json(date_dir / "outcomes.json", result)
    _atomic_write(date_dir / "shortlist.md", render_shortlist(selection, result))
    return {"report_date": report_date, "status": "refreshed", "selection": selection, "outcomes": result}


def _refresh_all(
    runs_dir: Path,
    db_path: Path,
    as_of_date: str,
    evaluator: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    refreshed = []
    errors = []
    if not runs_dir.exists():
        return refreshed, errors
    for date_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        if not _date_text(date_dir.name) or not (date_dir / "selection.json").is_file():
            continue
        try:
            result = _refresh_date(date_dir, db_path, as_of_date, evaluator)
            refreshed.append({
                "report_date": result["report_date"],
                "status": result["status"],
                "l1_status": (result.get("outcomes") or {}).get("l1", {}).get("status"),
                "b0_status": (result.get("outcomes") or {}).get("b0", {}).get("status"),
                "registration_status": result.get("selection", {}).get("registration_status"),
            })
        except Exception as exc:
            errors.append({"report_date": date_dir.name, "error": "{}: {}".format(type(exc).__name__, str(exc))})
            try:
                selection = json.loads((date_dir / "selection.json").read_text(encoding="utf-8"))
                old_outcomes = {}
                if (date_dir / "outcomes.json").is_file():
                    old_outcomes = json.loads((date_dir / "outcomes.json").read_text(encoding="utf-8"))
                old_outcomes["refresh_error"] = errors[-1]["error"]
                _atomic_write(date_dir / "shortlist.md", render_shortlist(selection, old_outcomes))
            except Exception:
                pass
    index = {
        "schema_version": 1,
        "as_of_date": as_of_date,
        "refreshed_at": _now_iso(),
        "dates": refreshed,
        "errors": errors,
    }
    _write_json(runs_dir / "summary.json", index)
    return refreshed, errors


def process_report(
    report_path: Path,
    output_dir: Path,
    db_path: Path,
    as_of_date: Optional[str] = None,
    *,
    outcome_evaluator: Any = None,
    frozen_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Freeze the completed report, then refresh outcomes for saved dates."""
    report_path = Path(report_path)
    output_dir = Path(output_dir)
    db_path = Path(db_path)
    try:
        report_bytes = report_path.read_bytes()
    except OSError as exc:
        raise ResearchInputError("report cannot be read: {}".format(exc))
    try:
        report = json.loads(report_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ResearchInputError("report JSON is invalid: {}".format(exc))
    if not isinstance(report, Mapping):
        raise ResearchInputError("report JSON must contain an object")
    report_date = _report_date(report)
    as_of_date = _date_text(as_of_date) if as_of_date is not None else report_date
    if as_of_date is None:
        raise ResearchInputError("--as-of must be an ISO date")
    archived, archive_hash, archive_error = _read_archived_workbench(report_path, report, report_date)
    prepared = adapt_report(report, archived_workbench=archived)
    diagnostics = report.get("diagnostics")
    funnel = diagnostics.get("candidate_funnel") if isinstance(diagnostics, Mapping) else None
    if isinstance(funnel, Mapping) and isinstance(funnel.get("run_id"), str):
        prepared["source_run_id"] = funnel.get("run_id")
    guard_errors = _process_guard(report, report_date, as_of_date)
    _apply_process_guard(prepared, guard_errors)
    source_hashes = {
        "report_sha256": _sha256(report_bytes),
        "archive_sha256": archive_hash,
    }
    source_hash = _sha256(_compact_json(source_hashes).encode("utf-8"))
    prepared["source_hashes"] = source_hashes
    if archive_error:
        prepared["archive_read_status"] = archive_error
    freeze = freeze_selection(output_dir, prepared, source_hash, frozen_at=frozen_at)
    evaluator = outcome_evaluator or evaluate_frozen_selection
    refreshed, refresh_errors = _refresh_all(output_dir, db_path, as_of_date, evaluator)
    current = next((row for row in refreshed if row["report_date"] == report_date), None)
    frozen_current = {}
    try:
        frozen_current = json.loads(
            (output_dir / report_date / "selection.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        pass
    if freeze["action"] == "conflict":
        status = "conflict"
    elif refresh_errors:
        status = "partial_refresh"
    elif prepared.get("freeze_status") == "input_insufficient":
        status = "not_evaluated"
    else:
        status = "processed"
    return {
        "status": status,
        "report_date": report_date,
        "as_of_date": as_of_date,
        "freeze_action": freeze["action"],
        "l1_status": (current or {}).get("l1_status") or prepared["l1"]["status"],
        "b0_status": (current or {}).get("b0_status") or prepared["b0"]["status"],
        "selected_l1": len((frozen_current.get("l1") or {}).get("selected") or []),
        "selected_b0": len((frozen_current.get("b0") or {}).get("selected") or []),
        "refreshed_dates": [item["report_date"] for item in refreshed],
        "refresh_errors": refresh_errors,
        "selection_path": freeze["selection_path"],
    }
