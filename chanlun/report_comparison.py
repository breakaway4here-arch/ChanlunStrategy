"""Offline price index for comparing published trading-day reports.

The index deliberately reads only generated report JSON and the local canonical
market-history SQLite database.  It never fetches quotes while reports are
being generated or compared.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from chanlun.report_view_model import build_workspace
from chanlun.strategy_review import load_strategy_sample_exclusions


VIEW_NAMES = (
    "main", "h4_t3", "highlights", "observation_top5", "acceleration", "luojie",
    "confirming", "growth_quality", "baseline",
)

_FORMAL_STRATEGY_BY_VIEW = {
    "main": "daily_fusion",
    "h4_t3": "h4_t3",
}


def _registered_incident_codes(report_date, view_name):
    strategy_name = _FORMAL_STRATEGY_BY_VIEW.get(view_name)
    if not strategy_name:
        return set()
    excluded = set()
    for rule in load_strategy_sample_exclusions():
        dates = {str(value) for value in rule.get("report_dates") or []}
        strategies = {
            str(value) for value in rule.get("strategy_names") or []
        }
        if report_date not in dates or strategy_name not in strategies:
            continue
        codes = {str(value) for value in rule.get("codes") or []}
        if codes:
            excluded.update(codes)
        else:
            excluded.add("*")
    return excluded


def _formal_view_allowed(report, view_name):
    strategy_name = _FORMAL_STRATEGY_BY_VIEW.get(view_name)
    if not strategy_name or not isinstance(report, dict):
        return True
    health = report.get("selection_input_health")
    if not isinstance(health, dict) or health.get("schema_version") != 2:
        return False
    by_strategy = health.get("by_strategy")
    by_strategy = by_strategy if isinstance(by_strategy, dict) else {}
    strategy_health = by_strategy.get(strategy_name)
    return bool(
        isinstance(strategy_health, dict)
        and strategy_health.get("status") == "verified"
        and strategy_health.get("formal_actions_allowed") is True
    )


def _as_text(value):
    return str(value or "").strip()


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_views(report):
    workspace = report.get("workspace") if isinstance(report, dict) else {}
    views = workspace.get("views") if isinstance(workspace, dict) else {}
    if isinstance(views, dict) and any(
        isinstance(views.get(view), list) and len(views.get(view)) > 0
        for view in VIEW_NAMES
    ):
        return views
    rebuilt = build_workspace(report if isinstance(report, dict) else {})
    views = rebuilt.get("views") if isinstance(rebuilt, dict) else {}
    return views if isinstance(views, dict) else {}


def _comparison_report_dates(data_dir, window_size):
    manifest_path = os.path.join(data_dir, "index.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    meta = manifest.get("date_meta") if isinstance(manifest, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    dates = []
    for value in manifest.get("dates", []):
        date = _as_text(value)
        if not date or not os.path.isfile(os.path.join(data_dir, date + ".json")):
            continue
        date_meta = meta.get(date, {})
        if isinstance(date_meta, dict) and date_meta.get("is_trading_day") is False:
            continue
        with open(os.path.join(data_dir, date + ".json"), "r", encoding="utf-8") as handle:
            report = json.load(handle)
        data_quality = report.get("data_quality") if isinstance(report, dict) else {}
        if isinstance(data_quality, dict) and data_quality.get("is_trading_day") is False:
            continue
        views = _source_views(report)
        if not any(
            isinstance(views.get(view), list) and len(views.get(view)) > 0
            for view in VIEW_NAMES
        ):
            continue
        dates.append(date)
    return sorted(set(dates))[-int(window_size):]


def _view_row(item, fallback_rank):
    if not isinstance(item, dict):
        return None
    code = _as_text(item.get("code"))
    if not code:
        return None
    decision = item.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    rank = item.get("view_rank", item.get("rank", fallback_rank))
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = fallback_rank
    return {
        "code": code,
        "name": _as_text(item.get("name")),
        "industry": _as_text(item.get("industry") or item.get("sector")),
        "rank": rank,
        "decision": _as_text(decision.get("decision") or item.get("decision")),
        "decision_code": _as_text(decision.get("decision_code") or item.get("decision_code")),
    }


def _read_report(path, date_meta=None):
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    source_views = _source_views(report)
    views = {}
    incident_excluded_counts = {}
    formal_input_blocked_counts = {}
    report_date = _as_text(report.get("date"))
    for view in VIEW_NAMES:
        rows = []
        source_rows = source_views.get(view, [])
        source_rows = source_rows if isinstance(source_rows, list) else []
        if view in _FORMAL_STRATEGY_BY_VIEW and not _formal_view_allowed(
            report, view
        ):
            views[view] = []
            if source_rows:
                formal_input_blocked_counts[view] = len(source_rows)
            continue
        excluded_codes = _registered_incident_codes(report_date, view)
        excluded_count = 0
        for position, item in enumerate(source_rows, start=1):
            item_code = _as_text(item.get("code")) if isinstance(item, dict) else ""
            if "*" in excluded_codes or item_code in excluded_codes:
                excluded_count += 1
                continue
            row = _view_row(item, position)
            if row is not None:
                rows.append(row)
        views[view] = rows
        if excluded_count:
            incident_excluded_counts[view] = excluded_count
    market = report.get("market") if isinstance(report, dict) else {}
    benchmark = market.get("沪深300") if isinstance(market, dict) else {}
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    data_quality = report.get("data_quality") if isinstance(report, dict) else {}
    data_quality = data_quality if isinstance(data_quality, dict) else {}
    date_meta = date_meta if isinstance(date_meta, dict) else {}
    is_official = data_quality.get("is_official")
    if not isinstance(is_official, bool):
        is_official = date_meta.get("is_official") is not False
    is_trading_day = data_quality.get("is_trading_day")
    if not isinstance(is_trading_day, bool):
        is_trading_day = date_meta.get("is_trading_day") is not False
    quality = {
        "is_official": bool(is_official),
        "is_trading_day": bool(is_trading_day),
        "missing_daily_count": int(_as_number(data_quality.get("missing_daily_count")) or 0),
        "stale_stock_count": int(_as_number(data_quality.get("stale_stock_count")) or 0),
        "status": "official" if is_official else "quality_warning",
        "incident_excluded_counts": incident_excluded_counts,
    }
    if formal_input_blocked_counts:
        quality["formal_input_blocked_counts"] = formal_input_blocked_counts
    return {
        "benchmark": {
            "code": "000300",
            "name": "沪深300",
            "close": _as_number(benchmark.get("close")),
        },
        "views": views,
        "quality": quality,
    }


def _expected_stock_exchange(code):
    """Resolve the canonical A-share exchange encoded by a six-digit code."""
    code = _as_text(code)
    if code.startswith("6"):
        return "SH"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZ"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    return ""


def _read_final_prices(db_path, dates, codes):
    prices = {(date, code): None for date in dates for code in codes}
    if not dates or not codes or not os.path.isfile(db_path):
        return prices
    placeholders_dates = ",".join("?" for _ in dates)
    placeholders_codes = ",".join("?" for _ in codes)
    query = """
        SELECT b.ts, i.code, i.exchange, b.close
        FROM bars_day b
        JOIN instruments i ON i.instrument_id = b.instrument_id
        WHERE b.is_final = 1
          AND i.asset_type = 'stock'
          AND b.ts IN ({dates})
          AND i.code IN ({codes})
    """.format(dates=placeholders_dates, codes=placeholders_codes)
    uri = "file:{}?mode=ro".format(os.path.abspath(db_path))
    connection = sqlite3.connect(uri, uri=True)
    try:
        ambiguous_sz_codes = {
            _as_text(row[0])
            for row in connection.execute(
                """
                SELECT code
                FROM instruments
                WHERE asset_type = 'stock' AND exchange IN ('SH', 'SZ')
                  AND code IN ({codes})
                GROUP BY code
                HAVING COUNT(DISTINCT exchange) > 1
                """.format(codes=placeholders_codes),
                list(codes),
            )
        }
        for date, code, exchange, close in connection.execute(query, list(dates) + list(codes)):
            expected_exchange = _expected_stock_exchange(code)
            if expected_exchange == "SZ" and code in ambiguous_sz_codes:
                # Historical ingestion once treated some 000xxx stocks as SH
                # indices and then propagated the bad scale into the SZ row.
                # Fail closed until that identity has been repaired in the DB.
                continue
            if _as_text(exchange).upper() != expected_exchange:
                continue
            prices[(date, code)] = _as_number(close)
    finally:
        connection.close()
    return prices


def build_comparison_index(data_dir, db_path, window_size=26):
    """Return the deterministic local-price comparison contract for reports."""
    dates = _comparison_report_dates(data_dir, window_size)
    with open(os.path.join(data_dir, "index.json"), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    date_meta = manifest.get("date_meta") if isinstance(manifest, dict) else {}
    date_meta = date_meta if isinstance(date_meta, dict) else {}
    snapshots = {
        date: _read_report(os.path.join(data_dir, date + ".json"), date_meta.get(date))
        for date in dates
    }
    codes = sorted({
        row["code"]
        for snapshot in snapshots.values()
        for rows in snapshot["views"].values()
        for row in rows
    })
    final_prices = _read_final_prices(db_path, dates, codes)
    reports = {}
    for date in dates:
        prices = {code: final_prices[(date, code)] for code in codes}
        reports[date] = {
            "benchmark": snapshots[date]["benchmark"],
            "quality": snapshots[date]["quality"],
            "prices": prices,
            "views": snapshots[date]["views"],
            "missing_codes": [code for code in codes if prices[code] is None],
        }
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dates": dates,
        "latest_date": dates[-1] if dates else "",
        "reports": reports,
    }


def write_comparison_index(data_dir, db_path, window_size=26):
    """Rebuild and atomically publish ``comparison-index.json``."""
    index = build_comparison_index(data_dir, db_path, window_size=window_size)
    target = os.path.join(data_dir, "comparison-index.json")
    try:
        with open(target, "r", encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        existing = None
    if isinstance(existing, dict) and isinstance(
        existing.get("generated_at"), str
    ):
        existing_semantic = {
            key: value for key, value in existing.items()
            if key != "generated_at"
        }
        rebuilt_semantic = {
            key: value for key, value in index.items()
            if key != "generated_at"
        }
        if existing_semantic == rebuilt_semantic:
            return target
    fd, temporary = tempfile.mkstemp(prefix=".comparison-index-", suffix=".json", dir=data_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
