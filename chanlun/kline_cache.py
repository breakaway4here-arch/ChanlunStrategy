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


# ---- record <-> kline dict conversion ----


def kline_dict_to_records(kline):
    if not kline:
        return []
    records = []
    for i, date in enumerate(kline.get("dates", [])):
        records.append({
            "date": str(date),
            "open": float(kline["opens"][i]),
            "high": float(kline["highs"][i]),
            "low": float(kline["lows"][i]),
            "close": float(kline["closes"][i]),
            "volume": float(kline["volumes"][i]),
        })
    return records


def records_to_kline_dict(records):
    records = sorted(records, key=lambda r: r["date"])
    return {
        "dates": [r["date"] for r in records],
        "opens": np.array([float(r["open"]) for r in records]),
        "highs": np.array([float(r["high"]) for r in records]),
        "lows": np.array([float(r["low"]) for r in records]),
        "closes": np.array([float(r["close"]) for r in records]),
        "volumes": np.array([float(r["volume"]) for r in records]),
    }


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


def read_cached_records(period, code):
    if not KLINE_CACHE_ENABLED:
        return []
    path = cache_path(period, code)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("klines", [])
    except Exception:
        return []


def write_cached_records(period, code, records, source, keep_trading_days):
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
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cached_kline_if_sufficient(period, code, count):
    records = read_cached_records(period, code)
    records = sorted(records, key=lambda r: r["date"])
    if len(records) < count:
        return None
    latest = records[-count:]
    if KLINE_CACHE_VERBOSE:
        print(f"  [CACHE HIT] {period} {code} {len(latest)} bars")
    return records_to_kline_dict(latest)
