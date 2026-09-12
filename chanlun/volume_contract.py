"""Canonical per-bar volume and turnover evidence helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Optional, Sequence

import numpy as np


def quantity_evidence_observation(
    code: Any,
    consumer: str,
    window: int,
    available: bool,
    reason: str = "",
) -> dict[str, Any]:
    """Build one internal, non-public observation at an actual quantity gate."""
    return {
        "code": str(code or "").strip(),
        "consumer": str(consumer or "").strip(),
        "window": int(window),
        "status": "available" if available else "unavailable",
        "reason": "" if available else str(
            reason or "quantity_evidence_unavailable"
        ),
    }


def build_quantity_input_health(
    input_codes: Sequence[Any],
    diagnostics: Sequence[Any],
    minimum_coverage: float,
) -> dict[str, Any]:
    """Aggregate actual consumer observations without requiring unused bars."""
    codes = sorted({str(code or "").strip() for code in input_codes if str(code or "").strip()})
    records = []
    for diagnostic in diagnostics or []:
        if not isinstance(diagnostic, Mapping):
            continue
        for raw in diagnostic.get("quantity_evidence") or []:
            if not isinstance(raw, Mapping):
                continue
            code = str(raw.get("code") or "").strip()
            if not code or code not in codes:
                continue
            status = str(raw.get("status") or "")
            if status not in ("available", "unavailable"):
                continue
            try:
                window = int(raw.get("window"))
            except (TypeError, ValueError):
                continue
            if window <= 0:
                continue
            records.append({
                "code": code,
                "consumer": str(raw.get("consumer") or "").strip(),
                "window": window,
                "status": status,
                "reason": (
                    "" if status == "available" else str(
                        raw.get("reason") or "quantity_evidence_unavailable"
                    )
                ),
            })

    by_code = {code: [] for code in codes}
    for record in records:
        by_code[record["code"]].append(record)
    required_codes = sorted(code for code, values in by_code.items() if values)
    available_codes = sorted(
        code for code in required_codes
        if any(value["status"] == "available" for value in by_code[code])
    )
    unavailable_codes = sorted(
        code for code in required_codes if code not in available_codes
    )
    pending_codes = sorted(
        code for code in required_codes
        if any(value["status"] == "unavailable" for value in by_code[code])
    )
    details = {
        code: [
            {
                "consumer": value["consumer"],
                "window": value["window"],
                "reason": value["reason"],
            }
            for value in by_code[code]
            if value["status"] == "unavailable"
        ]
        for code in pending_codes
    }
    required_count = len(required_codes)
    coverage = (
        len(available_codes) / float(required_count)
        if required_count else 1.0
    )
    below_floor = bool(required_count and coverage < float(minimum_coverage))
    if below_floor:
        status = "unavailable"
    elif pending_codes:
        status = "partial"
    else:
        status = "verified"
    return {
        "status": status,
        "input_count": len(codes),
        "required_count": required_count,
        "not_evaluated_count": len(codes) - required_count,
        "available_count": len(available_codes),
        "coverage": round(coverage, 6),
        "minimum_coverage": float(minimum_coverage),
        "below_minimum_coverage": below_floor,
        "available_codes": available_codes,
        "unavailable_codes": unavailable_codes,
        "pending_codes": pending_codes,
        "details": details,
    }


def formal_quantity_diagnostics(
    daily_structure: Any,
    daily_fusion: Any,
    strong_startup: Any,
    right_side_daily: Any,
    *,
    right_side_mode: str,
) -> list[dict[str, Any]]:
    """Project actual formal consumers without mutating research diagnostics."""

    def copied(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def without_codes(value: Any, excluded_codes: set[str]) -> dict[str, Any]:
        projected = copied(value)
        projected["quantity_evidence"] = [
            dict(record)
            for record in projected.get("quantity_evidence") or []
            if isinstance(record, Mapping)
            and str(record.get("code") or "").strip() not in excluded_codes
        ]
        return projected

    startup = copied(strong_startup)
    upstream = startup.get("common_upstream")
    upstream = upstream if isinstance(upstream, Mapping) else {}
    observation_only_codes = {
        str(code).strip()
        for code in upstream.get("limit_up_observation_codes") or []
        if str(code).strip()
    }
    projected = [
        copied(daily_structure),
        copied(daily_fusion),
        without_codes(startup, observation_only_codes),
    ]
    if str(right_side_mode or "").strip().lower() == "active":
        projected.append(copied(right_side_daily))
    return projected


def _field(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def metadata_series(
    source: Any,
    plural_key: str,
    scalar_key: str,
    length: int,
    default: str,
) -> Optional[list[str]]:
    """Return row-aligned metadata, or None when no contract was supplied."""
    plural = _field(source, plural_key)
    if plural is not None and not isinstance(plural, (str, bytes)):
        values = _as_list(plural)
        if len(values) == int(length):
            return [str(value if value is not None else default).strip() for value in values]
        return None
    scalar = _field(source, scalar_key)
    if scalar is None or int(length) != 1:
        return None
    return [str(scalar).strip()]


def availability_series(source: Any, length: int) -> Optional[list[bool]]:
    """Return explicit amount availability; absent markers remain unknown."""
    raw = _field(source, "amount_available")
    if raw is None:
        return None
    if isinstance(raw, (str, bytes, bool, int, float)):
        if int(length) != 1:
            return None
        values = [raw]
    else:
        values = _as_list(raw)
        if len(values) != int(length):
            return None
    normalized = []
    for value in values:
        if isinstance(value, bool):
            normalized.append(value)
        elif type(value) is int and value in (0, 1):
            normalized.append(bool(value))
        else:
            return None
    return normalized


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def volume_evidence_status(source: Any, values: Optional[Sequence[Any]] = None) -> str:
    raw_values = _field(source, "volumes") if values is None else values
    numbers = _as_list(raw_values)
    if not numbers:
        return "missing"
    units = metadata_series(source, "volume_units", "volume_unit", len(numbers), "unknown")
    raw_units = metadata_series(
        source, "volume_raw_units", "volume_raw_unit", len(numbers), "unknown"
    )
    sources = metadata_series(
        source, "volume_sources", "volume_source", len(numbers), ""
    )
    if units is None or raw_units is None or sources is None:
        return "incomplete"
    if any(unit.lower() != "hands" for unit in units):
        return "unknown"
    if any(unit.lower() not in ("hands", "shares") for unit in raw_units):
        return "unknown"
    if any(not source for source in sources):
        return "incomplete"
    if any(_finite_number(value) is None or _finite_number(value) < 0 for value in numbers):
        return "invalid"
    return "available"


def canonical_volume_series(
    source: Any,
    values: Optional[Sequence[Any]] = None,
) -> Optional[np.ndarray]:
    raw_values = _field(source, "volumes") if values is None else values
    numbers = _as_list(raw_values)
    if not numbers:
        return None
    units = metadata_series(source, "volume_units", "volume_unit", len(numbers), "unknown")
    raw_units = metadata_series(
        source, "volume_raw_units", "volume_raw_unit", len(numbers), "unknown"
    )
    sources = metadata_series(
        source, "volume_sources", "volume_source", len(numbers), ""
    )
    if (
        units is None
        or raw_units is None
        or sources is None
        or any(unit.lower() != "hands" for unit in units)
        or any(unit.lower() not in ("hands", "shares") for unit in raw_units)
        or any(not source for source in sources)
    ):
        return None
    converted = [_finite_number(value) for value in numbers]
    if any(value is None or value < 0 for value in converted):
        return None
    return np.asarray(converted, dtype=float)


def canonical_volume_window(
    source: Any,
    window: slice,
    values: Optional[Sequence[Any]] = None,
) -> Optional[np.ndarray]:
    """Return one verified canonical-hands slice without judging other bars."""
    raw_values = _field(source, "volumes") if values is None else values
    numbers = _as_list(raw_values)
    if not numbers or not isinstance(window, slice):
        return None
    units = metadata_series(source, "volume_units", "volume_unit", len(numbers), "unknown")
    raw_units = metadata_series(
        source, "volume_raw_units", "volume_raw_unit", len(numbers), "unknown"
    )
    sources = metadata_series(
        source, "volume_sources", "volume_source", len(numbers), ""
    )
    if units is None or raw_units is None or sources is None:
        return None
    window_values = numbers[window]
    window_units = units[window]
    window_raw_units = raw_units[window]
    window_sources = sources[window]
    if not window_values:
        return None
    if (
        len(window_values) != len(window_units)
        or len(window_values) != len(window_raw_units)
        or len(window_values) != len(window_sources)
        or any(unit.lower() != "hands" for unit in window_units)
        or any(unit.lower() not in ("hands", "shares") for unit in window_raw_units)
        or any(not source_name for source_name in window_sources)
    ):
        return None
    converted = [_finite_number(value) for value in window_values]
    if any(value is None or value < 0 for value in converted):
        return None
    return np.asarray(converted, dtype=float)


def amount_evidence_status(source: Any, values: Optional[Sequence[Any]] = None) -> str:
    raw_values = _field(source, "amounts") if values is None else values
    numbers = _as_list(raw_values)
    if not numbers:
        return "missing"
    units = metadata_series(source, "amount_units", "amount_unit", len(numbers), "unknown")
    sources = metadata_series(source, "amount_sources", "amount_source", len(numbers), "")
    available = availability_series(source, len(numbers))
    if units is None or sources is None or available is None:
        return "incomplete"
    if any(unit.upper() != "CNY" for unit in units):
        return "unknown"
    if any(not marker for marker in available):
        return "incomplete"
    if any(not source for source in sources):
        return "incomplete"
    if any((_finite_number(value) is None or _finite_number(value) <= 0) for value in numbers):
        return "invalid"
    return "available"


def canonical_amount_series(
    source: Any,
    values: Optional[Sequence[Any]] = None,
) -> Optional[np.ndarray]:
    raw_values = _field(source, "amounts") if values is None else values
    numbers = _as_list(raw_values)
    if not numbers:
        return None
    units = metadata_series(source, "amount_units", "amount_unit", len(numbers), "unknown")
    sources = metadata_series(source, "amount_sources", "amount_source", len(numbers), "")
    available = availability_series(source, len(numbers))
    if units is None or sources is None or available is None:
        return None
    if (
        any(unit.upper() != "CNY" for unit in units)
        or any(not marker for marker in available)
        or any(not source for source in sources)
    ):
        return None
    converted = [_finite_number(value) for value in numbers]
    if any(value is None or value <= 0 for value in converted):
        return None
    return np.asarray(converted, dtype=float)


def canonical_amount_window(
    source: Any,
    window: slice,
    values: Optional[Sequence[Any]] = None,
) -> Optional[np.ndarray]:
    """Return one verified CNY amount slice without judging other bars."""
    raw_values = _field(source, "amounts") if values is None else values
    numbers = _as_list(raw_values)
    if not numbers or not isinstance(window, slice):
        return None
    units = metadata_series(source, "amount_units", "amount_unit", len(numbers), "unknown")
    sources = metadata_series(source, "amount_sources", "amount_source", len(numbers), "")
    available = availability_series(source, len(numbers))
    if units is None or sources is None or available is None:
        return None
    window_values = numbers[window]
    window_units = units[window]
    window_sources = sources[window]
    window_available = available[window]
    if not window_values:
        return None
    if (
        len(window_values) != len(window_units)
        or len(window_values) != len(window_sources)
        or len(window_values) != len(window_available)
        or any(unit.upper() != "CNY" for unit in window_units)
        or any(not marker for marker in window_available)
        or any(not source_name for source_name in window_sources)
    ):
        return None
    converted = [_finite_number(value) for value in window_values]
    if any(value is None or value <= 0 for value in converted):
        return None
    return np.asarray(converted, dtype=float)
