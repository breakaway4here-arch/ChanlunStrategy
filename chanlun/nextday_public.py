"""Whitelist-only, deterministic projection of frozen next-day research runs."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PUBLIC_SCHEMA_VERSION = "nextday-research-public-v1"
GROUPS = ("l1", "b0")
GROUP_METHODS = {
    "l1": "L1_limit_sector",
    "b0": "B0_original_highlights",
}
PUBLIC_PATHS = ("cc1", "gap1", "oc1", "oc2", "oc3")
_IDENTITY = re.compile(r"^(SH|SZ|BJ)([0-9]{6})$")
_ALGORITHM_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_REGISTRATION_STATUSES = {"prospective", "historical"}
_BASIS_STATUSES = {
    "pending",
    "not_matured",
    "calendar_unavailable",
    "raw_comparable",
    "within_bar_invariant",
    "price_basis_unverified",
    "data_unavailable",
    "signal_bar_unavailable",
}
_MATURITY_STATUSES = {"pending", "matured", "calendar_unavailable"}
_BAR_FAILURE_STATUSES = {
    "missing",
    "nonfinal",
    "invalid_status",
    "invalid_ohlc",
    "duplicate_inconsistent",
}
_OUTCOME_STATUSES = {
    "pending",
    "available",
    "basis_unverified",
    "calendar_unavailable",
    *_BAR_FAILURE_STATUSES,
}
_OUTCOME_GROUP_STATUSES = {"research_only", "evaluated", "evaluated_empty"}


class PublicProjectionError(ValueError):
    """Frozen selection or outcome data cannot safely back a public snapshot."""


def _date_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise PublicProjectionError("{} is unavailable".format(label))
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise PublicProjectionError("{} is unavailable".format(label))
    if parsed.isoformat() != value:
        raise PublicProjectionError("{} is unavailable".format(label))
    return value


def _identity(row: Mapping[str, Any]) -> str:
    aliases = []
    for key in ("stock_identity", "instrument_id", "identity"):
        value = row.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
            raise PublicProjectionError("stock identity is unavailable")
        aliases.append(value)

    exchange = row.get("exchange")
    code = row.get("code")
    if exchange is not None or code is not None:
        if not isinstance(exchange, str) or not isinstance(code, str):
            raise PublicProjectionError("stock identity is unavailable")
        direct = exchange + code
        if _IDENTITY.fullmatch(direct) is None:
            raise PublicProjectionError("stock identity is unavailable")
        aliases.append(direct)

    details = row.get("identity_details")
    if details is not None:
        if not isinstance(details, Mapping) or details.get("asset_type") != "stock":
            raise PublicProjectionError("stock identity is unavailable")
        detail_exchange = details.get("exchange")
        detail_code = details.get("code")
        if not isinstance(detail_exchange, str) or not isinstance(detail_code, str):
            raise PublicProjectionError("stock identity is unavailable")
        detail_identity = detail_exchange + detail_code
        if _IDENTITY.fullmatch(detail_identity) is None:
            raise PublicProjectionError("stock identity is unavailable")
        aliases.append(detail_identity)

    if row.get("asset_type") not in (None, "stock"):
        raise PublicProjectionError("stock identity is unavailable")
    if not aliases or len(set(aliases)) != 1:
        raise PublicProjectionError("stock identity is unavailable")
    return aliases[0]


def _string(value: Any, *, maximum: int = 240) -> Optional[str]:
    if not isinstance(value, str):
        return None
    clean = "".join(char for char in value if char >= " " and char != "\x7f").strip()
    if not clean or len(clean) > maximum:
        return None
    return clean


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        clean = _string(item)
        if clean is not None and clean not in result:
            result.append(clean)
    return result


def _nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _positive_int(value: Any, fallback: int) -> int:
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PublicProjectionError("research rank is unavailable")
    return value


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, 4)


def _summary_count(summary: Mapping[str, Any], key: str) -> Optional[int]:
    return _nonnegative_int(summary.get(key))


def _public_candidate(
    row: Mapping[str, Any],
    group_name: str,
    method: str,
    algorithm_version: str,
    report_date: str,
    position: int,
) -> Dict[str, Any]:
    if row.get("report_date") not in (None, report_date):
        raise PublicProjectionError("selection row date is unavailable")
    row_version = row.get("algorithm_version")
    if row_version not in (None, algorithm_version):
        raise PublicProjectionError("selection row version is unavailable")
    row_method = row.get("research_method")
    if row_method not in (None, method):
        raise PublicProjectionError("selection method is unavailable")

    identity = _identity(row)
    rank = _positive_int(row.get("research_rank", row.get("highlight_rank")), position)
    sector = _string(row.get("sector"))
    limit_sector = _string(row.get("limit_sector"))
    first_limit_time = _string(row.get("first_limit_time"), maximum=5)
    if first_limit_time is not None and re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", first_limit_time) is None:
        first_limit_time = None

    startup_date = row.get("startup_date")
    if startup_date is not None:
        try:
            startup_date = _date_text(startup_date, "startup date")
        except PublicProjectionError:
            startup_date = None

    result = {
        "stock_identity": identity,
        "exchange": identity[:2],
        "code": identity[2:],
        "name": _string(row.get("name"), maximum=80),
        "rank": rank,
        "method": method,
        "algorithm_version": algorithm_version,
        "source_pools": _string_list(row.get("source_pools")),
        "industry": sector,
        "limit_sector": limit_sector,
        "industry_count": _nonnegative_int(row.get("own_limit_sector_count")),
        "board_n": _nonnegative_int(row.get("board_n")),
        "first_limit_time": first_limit_time,
        "risk_flags": _string_list(row.get("risk_flags")),
        "avoid_chase": row.get("avoid_chase") if isinstance(row.get("avoid_chase"), bool) else None,
        "invalidation": _string_list(row.get("invalidation")),
        "next_confirmation": _string_list(row.get("next_confirmation")),
        "cancel_conditions": _string_list(row.get("cancel_conditions")),
        "next_day_conditions": _string_list(row.get("next_day_conditions")),
        "upgrade_conditions": _string_list(row.get("upgrade_conditions")),
        "startup_date": startup_date,
        "startup_reason": _string(row.get("startup_reason")),
        "watch_reason": _string(row.get("watch_reason")),
    }
    return result


def _selection_group(
    selection: Mapping[str, Any],
    group_name: str,
    report_date: str,
    algorithm_version: str,
) -> Dict[str, Any]:
    source = selection.get(group_name)
    if not isinstance(source, Mapping) or source.get("status") != "evaluated":
        return {
            "status": "not_evaluated",
            "reason": "输入不完整或研究来源未就绪，暂未评估",
            "selected": [],
        }

    method = source.get("method")
    if method != GROUP_METHODS[group_name]:
        raise PublicProjectionError("selection method is unavailable")
    rows = source.get("selected")
    if not isinstance(rows, list):
        raise PublicProjectionError("selection rows are unavailable")
    selected = []
    identities = set()
    for position, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise PublicProjectionError("selection row is unavailable")
        public = _public_candidate(row, group_name, method, algorithm_version, report_date, position)
        if public["stock_identity"] in identities:
            raise PublicProjectionError("selection identity is unavailable")
        identities.add(public["stock_identity"])
        selected.append(public)
    return {"status": "evaluated", "reason": "", "selected": selected}


def _group_reason(group_name: str) -> str:
    return "{} 结果尚未刷新".format("L1" if group_name == "l1" else "B0")


def _group_metric(
    raw: Mapping[str, Any],
    observed_key: str,
    mean_key: str,
    median_key: Optional[str] = None,
    gain_key: Optional[str] = None,
    loss_key: Optional[str] = None,
    gain_label: str = "gain_ge_5",
) -> Dict[str, Any]:
    result = {
        "observed": _nonnegative_int(raw.get(observed_key)),
        "mean_pct": _finite_number(raw.get(mean_key)),
    }
    if median_key is not None:
        result["median_pct"] = _finite_number(raw.get(median_key))
    if gain_key is not None:
        result[gain_label] = _nonnegative_int(raw.get(gain_key))
    if loss_key is not None:
        result["loss_le_minus5"] = _nonnegative_int(raw.get(loss_key))
    return result


def _public_metrics(metrics: Mapping[str, Any], selected_count: int) -> Dict[str, Any]:
    return {
        "selected": selected_count,
        "cc1": _group_metric(metrics, "observed_cc1", "cc1_mean", "cc1_median", "nextday_gain_ge5", "nextday_loss_le_minus5"),
        "gap1": _group_metric(metrics, "observed_gap1", "gap1_mean"),
        "oc1": _group_metric(metrics, "observed_oc1", "oc1_mean", "oc1_median", "open_close_gain_ge3", "open_close_loss_le_minus5", "gain_ge_3"),
        "oc2": _group_metric(metrics, "observed_oc2", "oc2_mean"),
        "oc3": _group_metric(metrics, "observed_oc3", "oc3_mean"),
    }


def _metric_status(row: Mapping[str, Any], metric: str, horizon: str) -> Tuple[str, str]:
    value = row.get(metric)
    basis_by_metric = row.get("basis_status_by_metric")
    basis = basis_by_metric.get(metric) if isinstance(basis_by_metric, Mapping) else None
    basis_status = basis if basis in _BASIS_STATUSES else "unknown"
    if value is not None:
        return ("observed", basis_status) if _finite_number(value) is not None else ("unknown", basis_status)

    maturity = row.get("maturity_status")
    maturity_status = maturity.get(horizon) if isinstance(maturity, Mapping) else None
    if maturity_status == "pending":
        return "pending", basis_status
    if maturity_status == "calendar_unavailable":
        return "calendar_unavailable", basis_status
    if basis_status == "price_basis_unverified":
        return "basis_unverified", basis_status

    bars = row.get("bar_status")
    bar_status = bars.get(horizon) if isinstance(bars, Mapping) else None
    if bar_status in _BAR_FAILURE_STATUSES:
        return bar_status, basis_status
    if basis_status in ("data_unavailable", "signal_bar_unavailable"):
        return basis_status, basis_status
    if basis_status in ("not_matured", "pending"):
        return "pending", basis_status
    if basis_status == "calendar_unavailable":
        return "calendar_unavailable", basis_status
    return "unavailable", basis_status


def _outcome_status(row: Mapping[str, Any]) -> str:
    value = row.get("outcome_status")
    if value in _OUTCOME_STATUSES:
        return value
    if value in ("identity_not_found", "identity_ambiguous", "identity_malformed", "identity_unavailable"):
        return "unavailable"
    return "unknown"


def _target_dates(row: Mapping[str, Any], group: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    targets = row.get("target_dates")
    if not isinstance(targets, Mapping):
        targets = group.get("target_dates")
    if not isinstance(targets, Mapping):
        targets = {}
    result = {}
    for horizon in ("t1", "t2", "t3"):
        value = targets.get(horizon)
        if value is None:
            result[horizon] = None
        else:
            result[horizon] = _date_text(value, "outcome target date")
    return result


def _public_outcome_row(
    row: Mapping[str, Any],
    candidate: Mapping[str, Any],
    group: Mapping[str, Any],
    report_date: str,
) -> Dict[str, Any]:
    if row.get("report_date") not in (None, report_date):
        raise PublicProjectionError("outcome row date is unavailable")
    if row.get("identity") != candidate["stock_identity"]:
        raise PublicProjectionError("outcome row identity is unavailable")
    source_selection = row.get("selection")
    if not isinstance(source_selection, Mapping):
        raise PublicProjectionError("outcome selection is unavailable")
    if _identity(source_selection) != candidate["stock_identity"]:
        raise PublicProjectionError("outcome selection identity is unavailable")
    if source_selection.get("report_date") not in (None, report_date):
        raise PublicProjectionError("outcome selection date is unavailable")

    maturity_raw = row.get("maturity_status")
    maturity_raw = maturity_raw if isinstance(maturity_raw, Mapping) else {}
    maturity = {
        horizon: (
            maturity_raw.get(horizon)
            if maturity_raw.get(horizon) in _MATURITY_STATUSES
            else "unknown"
        )
        for horizon in ("t1", "t2", "t3")
    }
    metric_horizons = {
        "cc1": "t1",
        "gap1": "t1",
        "oc1": "t1",
        "oc2": "t2",
        "oc3": "t3",
    }
    paths = {}
    for metric, horizon in metric_horizons.items():
        status, basis_status = _metric_status(row, metric, horizon)
        paths[metric] = {
            "status": status,
            "price_basis_status": basis_status,
            "value_pct": _finite_number(row.get(metric)),
        }
    return {
        "stock_identity": candidate["stock_identity"],
        "name": candidate.get("name"),
        "rank": candidate["rank"],
        "status": _outcome_status(row),
        "entry_one_price": row.get("entry_one_price") if isinstance(row.get("entry_one_price"), bool) else None,
        "target_dates": _target_dates(row, group),
        "maturity_status": maturity,
        "path_metrics": paths,
    }


def _outcomes_group(
    outcomes: Optional[Mapping[str, Any]],
    selection_source: Mapping[str, Any],
    public_selection: Mapping[str, Any],
    group_name: str,
    report_date: str,
) -> Dict[str, Any]:
    if public_selection["status"] != "evaluated":
        return {
            "status": "not_evaluated",
            "reason": "研究组未评估，结果暂不可用",
            "metrics": {},
            "outcome_rows": [],
        }
    if outcomes is None:
        return {"status": "not_evaluated", "reason": _group_reason(group_name), "metrics": {}, "outcome_rows": []}
    source = outcomes.get(group_name)
    if not isinstance(source, Mapping) or source.get("status") not in _OUTCOME_GROUP_STATUSES:
        return {"status": "not_evaluated", "reason": _group_reason(group_name), "metrics": {}, "outcome_rows": []}
    if source.get("report_date") not in (None, report_date):
        raise PublicProjectionError("outcome group date is unavailable")
    if outcomes.get("as_of_date") is not None and source.get("as_of_date") not in (None, outcomes.get("as_of_date")):
        raise PublicProjectionError("outcome group date is unavailable")

    candidates = public_selection["selected"]
    source_selected = source.get("selected")
    rows = source.get("outcome_rows")
    if not isinstance(source_selected, list) or not isinstance(rows, list):
        raise PublicProjectionError("outcome rows are unavailable")
    if len(source_selected) != len(candidates) or len(rows) != len(candidates):
        raise PublicProjectionError("outcome identities are unavailable")
    expected_identities = [item["stock_identity"] for item in candidates]
    selected_identities = [_identity(item) if isinstance(item, Mapping) else None for item in source_selected]
    if selected_identities != expected_identities:
        raise PublicProjectionError("outcome identities are unavailable")

    rows_by_identity = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise PublicProjectionError("outcome row is unavailable")
        identity = row.get("identity")
        if not isinstance(identity, str) or identity in rows_by_identity:
            raise PublicProjectionError("outcome identities are unavailable")
        rows_by_identity[identity] = row
    if set(rows_by_identity) != set(expected_identities):
        raise PublicProjectionError("outcome identities are unavailable")

    raw_metrics = source.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        return {"status": "not_evaluated", "reason": _group_reason(group_name), "metrics": {}, "outcome_rows": []}
    metric_selected = raw_metrics.get("selected")
    if metric_selected is not None and _nonnegative_int(metric_selected) != len(candidates):
        raise PublicProjectionError("outcome count is unavailable")

    public_rows = [
        _public_outcome_row(rows_by_identity[item["stock_identity"]], item, source, report_date)
        for item in candidates
    ]
    return {
        "status": "evaluated",
        "reason": "",
        "metrics": _public_metrics(raw_metrics, len(candidates)),
        "outcome_rows": public_rows,
    }


def project_run(selection: Mapping[str, Any], outcomes: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Project one frozen run without exposing raw selection or outcome data."""
    if not isinstance(selection, Mapping):
        raise PublicProjectionError("selection is unavailable")
    report_date = _date_text(selection.get("report_date"), "report date")
    algorithm_version = selection.get("algorithm_version")
    if not isinstance(algorithm_version, str) or _ALGORITHM_VERSION.fullmatch(algorithm_version) is None:
        raise PublicProjectionError("algorithm version is unavailable")
    if outcomes is not None:
        if not isinstance(outcomes, Mapping):
            raise PublicProjectionError("outcomes are unavailable")
        if outcomes.get("report_date") != report_date:
            raise PublicProjectionError("outcomes date is unavailable")
        as_of_date = _date_text(outcomes.get("as_of_date"), "outcomes as-of date")
        if as_of_date < report_date:
            raise PublicProjectionError("outcomes date is unavailable")
    else:
        as_of_date = None

    selected_groups = {
        group_name: _selection_group(selection, group_name, report_date, algorithm_version)
        for group_name in GROUPS
    }
    source_groups = {
        group_name: selection.get(group_name) if isinstance(selection.get(group_name), Mapping) else {}
        for group_name in GROUPS
    }
    outcomes_groups = {
        group_name: _outcomes_group(
            outcomes,
            source_groups[group_name],
            selected_groups[group_name],
            group_name,
            report_date,
        )
        for group_name in GROUPS
    }
    selection_complete = all(group["status"] == "evaluated" for group in selected_groups.values())
    outcomes_complete = all(group["status"] == "evaluated" for group in outcomes_groups.values())
    status = "available" if selection_complete and outcomes_complete else "partial"
    reason = "" if status == "available" else (
        "部分研究组输入未就绪，暂未评估" if not selection_complete else "部分结果数据尚未就绪"
    )

    source_summary = selection.get("summary")
    source_summary = source_summary if isinstance(source_summary, Mapping) else {}
    frozen_at = selection.get("frozen_at")
    if not isinstance(frozen_at, str) or len(frozen_at) > 40 or re.fullmatch(r"[0-9T:+.Z-]+", frozen_at) is None:
        frozen_at = None
    registration_status = selection.get("registration_status")
    if registration_status not in _REGISTRATION_STATUSES:
        registration_status = "unknown"
    source_run_id = _string(selection.get("source_run_id"), maximum=80)

    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "report_date": report_date,
        "algorithm_version": algorithm_version,
        "source_run_id": source_run_id,
        "status": status,
        "reason": reason,
        "frozen_at": frozen_at,
        "registration_status": registration_status,
        "summary": {
            "candidate_count": _summary_count(source_summary, "candidate_count"),
            "snapshot_unique_count": _summary_count(source_summary, "snapshot_unique_count"),
            "candidate_snapshot_intersection": _summary_count(source_summary, "candidate_snapshot_intersection"),
        },
        "l1": selected_groups["l1"],
        "b0": selected_groups["b0"],
        "outcomes": {
            "as_of_date": as_of_date,
            "l1": outcomes_groups["l1"],
            "b0": outcomes_groups["b0"],
        },
    }


def _canonical_date_directory(path: Path) -> bool:
    try:
        return date.fromisoformat(path.name).isoformat() == path.name
    except ValueError:
        return False


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        raise PublicProjectionError("source unavailable")
    if not isinstance(value, Mapping):
        raise PublicProjectionError("source unavailable")
    return value


def project_runs(
    runs_dir: Path,
    report_dates: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    """Project available dates and locally summarize malformed dates.

    A bad historical directory is isolated so healthy dates can still refresh.
    Its existing public sidecar is left untouched by the caller.
    """
    runs_dir = Path(runs_dir)
    if report_dates is None:
        if not runs_dir.is_dir():
            return {}, []
        date_dirs = sorted(
            (path for path in runs_dir.iterdir() if path.is_dir() and _canonical_date_directory(path)),
            key=lambda path: path.name,
        )
    else:
        date_dirs = []
        for value in report_dates:
            report_date = _date_text(value, "requested report date")
            date_dirs.append(runs_dir / report_date)

    projected: Dict[str, Dict[str, Any]] = {}
    errors: List[Dict[str, str]] = []
    for date_dir in date_dirs:
        report_date = date_dir.name
        selection_path = date_dir / "selection.json"
        outcomes_path = date_dir / "outcomes.json"
        try:
            if not selection_path.is_file():
                raise PublicProjectionError("source unavailable")
            selection = _load_json(selection_path)
            outcomes = _load_json(outcomes_path) if outcomes_path.is_file() else None
            if selection.get("report_date") != report_date:
                raise PublicProjectionError("source unavailable")
            if outcomes is not None and outcomes.get("report_date") != report_date:
                raise PublicProjectionError("source unavailable")
            projected[report_date] = project_run(selection, outcomes)
        except PublicProjectionError:
            errors.append({"report_date": report_date, "status": "source_unavailable"})
    return projected, errors


def serialize_public_json(payload: Mapping[str, Any]) -> bytes:
    """Return canonical bytes for stable content-addressed sidecars."""
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_public_sidecars(
    projections: Mapping[str, Mapping[str, Any]], output_dir: Path
) -> List[Path]:
    """Atomically write projected JSON files, leaving byte-identical files alone."""
    output_dir = Path(output_dir)
    written = []
    if not projections:
        return written
    output_dir.mkdir(parents=True, exist_ok=True)
    for report_date in sorted(projections):
        report_date = _date_text(report_date, "report date")
        payload = projections[report_date]
        if payload.get("report_date") != report_date:
            raise PublicProjectionError("projected date is unavailable")
        target = output_dir / (report_date + ".json")
        data = serialize_public_json(payload)
        try:
            if target.read_bytes() == data:
                continue
        except FileNotFoundError:
            pass
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=str(output_dir), prefix=".nextday-public.", suffix=".tmp", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary_path), str(target))
            written.append(target)
        except Exception:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            raise
    return written
