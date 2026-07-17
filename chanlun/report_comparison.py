"""Offline price index for comparing formal daily reports.

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


VIEW_NAMES = (
    "main", "highlights", "observation_top5", "acceleration", "luojie",
    "confirming", "growth_quality", "baseline",
)


def _as_text(value):
    return str(value or "").strip()


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _official_report_dates(data_dir, window_size):
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
        if isinstance(date_meta, dict) and date_meta.get("is_official") is False:
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


def _read_report(path):
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    workspace = report.get("workspace") if isinstance(report, dict) else {}
    workspace = workspace if isinstance(workspace, dict) else {}
    source_views = workspace.get("views") if isinstance(workspace.get("views"), dict) else {}
    views = {}
    for view in VIEW_NAMES:
        rows = []
        for position, item in enumerate(source_views.get(view, []), start=1):
            row = _view_row(item, position)
            if row is not None:
                rows.append(row)
        views[view] = rows
    market = report.get("market") if isinstance(report, dict) else {}
    benchmark = market.get("沪深300") if isinstance(market, dict) else {}
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    return {
        "benchmark": {
            "code": "000300",
            "name": "沪深300",
            "close": _as_number(benchmark.get("close")),
        },
        "views": views,
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
    dates = _official_report_dates(data_dir, window_size)
    snapshots = {
        date: _read_report(os.path.join(data_dir, date + ".json"))
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
