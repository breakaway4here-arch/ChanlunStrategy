"""
K-line incremental cache — avoids re-fetching already-collected K-line data
during QA and debugging. Retains data per effective trading days, not calendar
days, so weekends and holidays do not consume the retention window.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from config import (
    KLINE_CACHE_DIR, KLINE_CACHE_ENABLED, KLINE_CACHE_VERBOSE,
)

TZ_CN = timezone(timedelta(hours=8))

# Cache statistics (populated by fetch wrappers)
CACHE_STATS = {
    "day_hit": 0,
    "day_miss": 0,
    "day_write": 0,
    "30min_hit": 0,
    "30min_miss": 0,
    "30min_write": 0,
    "pruned_records": 0,
}


def reset_cache_stats():
    for k in CACHE_STATS:
        CACHE_STATS[k] = 0


def get_cache_stats():
    return dict(CACHE_STATS)


def _to_python_scalar(value):
    """Keep NumPy scalar metadata JSON-serializable at cache boundaries."""
    return value.item() if isinstance(value, np.generic) else value


# ---- record <-> kline dict conversion ----


def _value_at(value, index, default=None):
    """Read a scalar or sequence field without losing per-bar metadata."""
    if value is None:
        return default
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return value[index] if index < len(value) else default
    return value


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


def kline_dict_to_records(kline):
    if not kline:
        return []
    finality = kline.get("is_final")
    if finality is None:
        finality = kline.get("finals")
    if finality is not None:
        try:
            finality = list(finality)
        except TypeError:
            finality = None
        if finality is not None and len(finality) != len(kline.get("dates", [])):
            finality = None
        if finality is not None:
            finality = [_to_python_scalar(value) for value in finality]
    records = []
    amounts = kline.get("amounts")
    amount_available = kline.get("amount_available")
    has_amounts = amounts is not None
    for i, date in enumerate(kline.get("dates", [])):
        record = {
            "date": str(date),
            "open": float(kline["opens"][i]),
            "high": float(kline["highs"][i]),
            "low": float(kline["lows"][i]),
            "close": float(kline["closes"][i]),
            "volume": float(kline["volumes"][i]),
            "volume_unit": str(
                _value_at(kline.get("volume_units"), i, kline.get("volume_unit", "unknown"))
                or "unknown"
            ).strip().lower(),
            "volume_raw_unit": str(
                _value_at(
                    kline.get("volume_raw_units"),
                    i,
                    kline.get("volume_raw_unit", "unknown"),
                )
                or "unknown"
            ).strip().lower(),
            "volume_source": str(
                _value_at(kline.get("volume_sources"), i, kline.get("volume_source", ""))
                or ""
            ).strip(),
        }
        if finality is not None:
            record["is_final"] = _to_python_scalar(finality[i])
        if has_amounts:
            raw_amount = _value_at(amounts, i)
            amount = _finite_positive(raw_amount)
            marker = _value_at(amount_available, i) if amount_available is not None else None
            available = (
                bool(marker) if marker is not None else amount is not None
            )
            record.update({
                "amount": amount if available and amount is not None else None,
                "amount_available": bool(available and amount is not None),
                "amount_unit": str(
                    _value_at(kline.get("amount_units"), i, kline.get("amount_unit", "unknown"))
                    or "unknown"
                ).strip().upper(),
                "amount_source": str(
                    _value_at(kline.get("amount_sources"), i, kline.get("amount_source", ""))
                    or ""
                ).strip(),
            })
        records.append(record)
    return records


def records_to_kline_dict(records):
    records = sorted(records, key=lambda r: r["date"])
    result = {
        "dates": [r["date"] for r in records],
        "opens": np.array([float(r["open"]) for r in records]),
        "highs": np.array([float(r["high"]) for r in records]),
        "lows": np.array([float(r["low"]) for r in records]),
        "closes": np.array([float(r["close"]) for r in records]),
        "volumes": np.array([float(r["volume"]) for r in records]),
    }
    if records and all("is_final" in record for record in records):
        result["is_final"] = [
            _to_python_scalar(record["is_final"]) for record in records
        ]
    volume_units = [
        str(record.get("volume_unit") or "unknown").strip().lower()
        for record in records
    ]
    volume_raw_units = [
        str(record.get("volume_raw_unit") or "unknown").strip().lower()
        for record in records
    ]
    volume_sources = [str(record.get("volume_source") or "").strip() for record in records]
    result.update({
        "volume_units": volume_units,
        "volume_raw_units": volume_raw_units,
        "volume_sources": volume_sources,
        "volume_unit": volume_units[-1] if len(set(volume_units)) <= 1 and volume_units else "mixed",
        "volume_raw_unit": (
            volume_raw_units[-1]
            if len(set(volume_raw_units)) <= 1 and volume_raw_units
            else "mixed"
        ),
        "volume_source": (
            volume_sources[-1]
            if len(set(volume_sources)) <= 1 and volume_sources
            else "mixed"
        ),
    })
    if any("amount" in record or "amount_available" in record for record in records):
        amounts = []
        availability = []
        amount_units = []
        amount_sources = []
        for record in records:
            amount = _finite_positive(record.get("amount"))
            marker = record.get("amount_available")
            available = bool(marker) if marker is not None else amount is not None
            amounts.append(amount if available and amount is not None else np.nan)
            availability.append(bool(available and amount is not None))
            amount_units.append(
                str(record.get("amount_unit") or "unknown").strip().upper()
            )
            amount_sources.append(str(record.get("amount_source") or "").strip())
        result.update({
            "amounts": np.array(amounts, dtype=float),
            "amount_available": np.array(availability, dtype=bool),
            "amount_units": amount_units,
            "amount_sources": amount_sources,
            "amount_unit": amount_units[-1] if len(set(amount_units)) <= 1 else "mixed",
            "amount_source": (
                amount_sources[-1]
                if len(set(amount_sources)) <= 1
                else "mixed"
            ),
        })
    return result


# ---- merge & prune ----


def merge_kline_records(old_records, new_records):
    by_date = {}
    for r in (old_records or []):
        by_date[str(r["date"])] = r
    for r in (new_records or []):
        by_date[str(r["date"])] = r
    return [by_date[k] for k in sorted(by_date)]


def _trading_day(date_str):
    return str(date_str).split(" ")[0]


def prune_records_by_trading_days(records, keep_trading_days):
    if not records:
        return []
    trading_days = sorted({_trading_day(r["date"]) for r in records})
    keep_days = set(trading_days[-keep_trading_days:])
    return [r for r in sorted(records, key=lambda x: x["date"])
            if _trading_day(r["date"]) in keep_days]


# ---- file I/O ----


def cache_path(period, code):
    return Path(KLINE_CACHE_DIR) / "klines" / period / f"{code}.json"


def read_cached_payload(period, code):
    """Read a cache envelope without treating a code-only file as canonical."""
    if not KLINE_CACHE_ENABLED:
        return None
    path = cache_path(period, code)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_cached_identity(period, code):
    payload = read_cached_payload(period, code)
    identity = payload.get("identity") if payload else None
    return dict(identity) if isinstance(identity, dict) else None


def _cache_identity_matches(period, code, identity):
    """Reject identity-less or mismatched envelopes at identity-aware reads."""
    cached_identity = read_cached_identity(period, code)
    if cached_identity is None:
        return False
    try:
        from .identity import normalize_identity

        return normalize_identity(cached_identity) == normalize_identity(identity)
    except (TypeError, ValueError):
        return False


def read_cached_records(period, code, identity=None):
    if identity is not None and not _cache_identity_matches(period, code, identity):
        return []
    payload = read_cached_payload(period, code)
    records = payload.get("klines", []) if payload else []
    if not isinstance(records, list):
        return []
    # Old cache files carry no trustworthy unit metadata.  Preserve that
    # uncertainty explicitly; a top-level source label alone cannot
    # distinguish an old Sina shares payload from an Eastmoney hands one.
    return [dict(record) for record in records if isinstance(record, dict)]


def write_cached_records(
    period, code, records, source, keep_trading_days, identity=None
):
    if not KLINE_CACHE_ENABLED:
        return
    path = cache_path(period, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    pruned = prune_records_by_trading_days(records, keep_trading_days)
    CACHE_STATS["pruned_records"] += len(records) - len(pruned)
    payload = {
        "code": code,
        "period": period,
        "updated_at": datetime.now(TZ_CN).isoformat(timespec="seconds"),
        "source": source,
        "klines": pruned,
    }
    if identity is not None:
        if hasattr(identity, "as_dict"):
            identity = identity.as_dict()
        if isinstance(identity, dict):
            payload["identity"] = dict(identity)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cached_kline_if_sufficient(period, code, count, identity=None):
    records = read_cached_records(period, code, identity=identity)
    records = sorted(records, key=lambda r: r["date"])
    if len(records) < count:
        return None
    latest = records[-count:]
    if KLINE_CACHE_VERBOSE:
        print(f"  [CACHE HIT] {period} {code} {len(latest)} bars")
    return records_to_kline_dict(latest)
