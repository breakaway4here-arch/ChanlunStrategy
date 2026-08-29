#!/usr/bin/env python3
"""Read-only replay for strong-startup 30-minute confirmation policies."""

import argparse
import glob
import json
import math
import os
import sqlite3
import statistics
import sys
from urllib.parse import quote

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from chanlun.chan_engine import analyze
from chanlun.sublevel_confirm import build_30min_confirmation_evidence


HORIZONS = ("t1", "t3", "t5")


def connect_read_only(path):
    """Open an existing SQLite file in mode=ro with query-only enabled."""
    absolute = os.path.abspath(path)
    uri = "file:{}?mode=ro".format(quote(absolute, safe="/"))
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def dedupe_report_events(rows):
    """Deduplicate report projections without hiding the displayed-row count."""
    by_key = {}
    for row in rows:
        key = (str(row.get("trade_date") or ""), str(row.get("code") or ""))
        if not all(key):
            continue
        if key not in by_key:
            event = dict(row)
            event["sources"] = [str(row.get("source") or "unknown")]
            by_key[key] = event
        else:
            source = str(row.get("source") or "unknown")
            if source not in by_key[key]["sources"]:
                by_key[key]["sources"].append(source)
    events = [by_key[key] for key in sorted(by_key)]
    return events, {
        "report_rows": len(rows),
        "unique_events": len(events),
    }


def summarize_outcomes(events):
    """Summarize forward returns while keeping missing samples explicit."""
    summary = {}
    for horizon in HORIZONS:
        values = []
        missing = 0
        for event in events:
            value = (event.get("returns") or {}).get(horizon)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                missing += 1
                continue
            values.append(float(value))
        summary[horizon] = {
            "evaluable": len(values),
            "missing": missing,
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "flat": sum(value == 0 for value in values),
            "mean_return_pct": _percent(statistics.mean(values)) if values else None,
            "median_return_pct": _percent(statistics.median(values)) if values else None,
            "worst_return_pct": _percent(min(values)) if values else None,
        }
    return summary


def build_policy_flags(evidence):
    """Project evidence into legacy, shadow and production policy flags."""
    evidence = evidence or {}
    structure = bool(evidence.get("buy_point") or evidence.get("fresh_yang_pattern"))
    return {
        "legacy_alignment": bool(evidence.get("ema_bullish_alignment")),
        "structure_only": structure,
        "recovery_bundle": bool(evidence.get("recovery_bundle_match")),
        # The replay did not support promoting the recovery bundle.  Keep it
        # observable as shadow evidence but out of the production proposal.
        "proposed": structure,
    }


def _percent(value):
    return round(float(value) * 100.0, 6)


def load_report_rows(report_dir, as_of):
    rows = []
    pattern = os.path.join(report_dir, "20??-??-??.json")
    for path in sorted(glob.glob(pattern)):
        filename_date = os.path.basename(path)[:10]
        if filename_date > as_of:
            continue
        with open(path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        trade_date = str(report.get("date") or filename_date)
        if trade_date > as_of:
            continue
        for source in ("picks_pure", "picks_fusion"):
            for pick in report.get(source, []) or []:
                best = pick.get("best_buy_point") or {}
                if best.get("type") != "强势启动候选":
                    continue
                rows.append({
                    "trade_date": trade_date,
                    "code": str(pick.get("code") or "").zfill(6),
                    "name": str(pick.get("name") or ""),
                    "source": source,
                    "legacy_confirmations": list(best.get("confirmations") or []),
                    "legacy_grade": best.get("sublevel_confirm_grade"),
                })
    return rows


def _load_instrument_ids(connection, codes):
    mapping = {}
    ordered = sorted(set(codes))
    for start in range(0, len(ordered), 500):
        chunk = ordered[start:start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            "SELECT code, instrument_id FROM instruments "
            "WHERE asset_type = 'stock' AND code IN ({})".format(placeholders),
            chunk,
        ).fetchall()
        for row in rows:
            mapping[str(row["code"]).zfill(6)] = int(row["instrument_id"])
    return mapping


def _load_30m_bars(connection, instrument_id, trade_date, limit=160):
    rows = connection.execute(
        """
        SELECT b.ts, b.open, b.high, b.low, b.close, b.volume
        FROM bars_30m AS b
        WHERE b.instrument_id = ?
          AND b.ts < ?
          AND b.is_final = 1
        ORDER BY b.ts DESC
        LIMIT ?
        """,
        (int(instrument_id), trade_date + " 23:59:59", int(limit)),
    ).fetchall()
    return list(reversed(rows))


def _load_forward_returns(connection, instrument_id, trade_date):
    rows = connection.execute(
        """
        SELECT substr(b.ts, 1, 10) AS trade_date, b.close
        FROM bars_day AS b
        WHERE b.instrument_id = ?
          AND b.ts >= ?
          AND b.is_final = 1
        ORDER BY b.ts
        LIMIT 6
        """,
        (int(instrument_id), trade_date),
    ).fetchall()
    if not rows or rows[0]["trade_date"] != trade_date:
        return {horizon: None for horizon in HORIZONS}
    base = float(rows[0]["close"])
    result = {}
    for days in (1, 3, 5):
        result["t{}".format(days)] = (
            round(float(rows[days]["close"]) / base - 1.0, 10)
            if len(rows) > days and base > 0
            else None
        )
    return result


def evaluate_event(connection, event, instrument_ids):
    evaluated = dict(event)
    instrument_id = instrument_ids.get(event["code"])
    if instrument_id is None:
        evaluated.update({
            "bars_30m": 0,
            "evidence": None,
            "policies": {
                "legacy_alignment": False,
                "structure_only": False,
                "recovery_bundle": False,
                "proposed": False,
            },
            "returns": {horizon: None for horizon in HORIZONS},
        })
        return evaluated
    bars = _load_30m_bars(connection, instrument_id, event["trade_date"])
    if len(bars) < 10:
        evaluated.update({
            "bars_30m": len(bars),
            "evidence": None,
            "policies": {
                "legacy_alignment": False,
                "structure_only": False,
                "recovery_bundle": False,
                "proposed": False,
            },
            "returns": _load_forward_returns(
                connection, instrument_id, event["trade_date"]
            ),
        })
        return evaluated

    result = analyze(
        event["code"],
        event.get("name") or event["code"],
        [row["ts"] for row in bars],
        [row["open"] for row in bars],
        [row["high"] for row in bars],
        [row["low"] for row in bars],
        [row["close"] for row in bars],
        [row["volume"] for row in bars],
    )
    evidence = build_30min_confirmation_evidence(result)
    evaluated.update({
        "bars_30m": len(bars),
        "evidence": evidence,
        "policies": build_policy_flags(evidence),
        "returns": _load_forward_returns(
            connection, instrument_id, event["trade_date"]
        ),
    })
    return evaluated


def build_replay(report_dir, market_db, as_of):
    report_rows = load_report_rows(report_dir, as_of)
    events, counts = dedupe_report_events(report_rows)
    connection = connect_read_only(market_db)
    try:
        instrument_ids = _load_instrument_ids(
            connection, [event["code"] for event in events]
        )
        evaluated = [
            evaluate_event(connection, event, instrument_ids) for event in events
        ]
    finally:
        connection.close()

    counts["events_with_30m"] = sum(event.get("evidence") is not None for event in evaluated)
    counts["events_missing_30m"] = counts["unique_events"] - counts["events_with_30m"]
    policies = {}
    for policy in ("legacy_alignment", "structure_only", "recovery_bundle", "proposed"):
        selected = [event for event in evaluated if event["policies"][policy]]
        policies[policy] = {
            "selected_events": len(selected),
            "outcomes": summarize_outcomes(selected),
        }

    focus = [
        event for event in evaluated
        if event["code"] == "301629" and event["trade_date"] == "2026-08-28"
    ]
    return {
        "schema_version": 1,
        "as_of": as_of,
        "database_path": os.path.abspath(market_db),
        "database_read_only": True,
        "counts": counts,
        "missing_forward_returns": {
            horizon: sum((event.get("returns") or {}).get(horizon) is None for event in evaluated)
            for horizon in HORIZONS
        },
        "policies": policies,
        "focus_301629_2026_08_28": focus,
        "events": evaluated,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", required=True)
    parser.add_argument("--market-db", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    replay = build_replay(args.reports, args.market_db, args.as_of)
    payload = json.dumps(replay, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
