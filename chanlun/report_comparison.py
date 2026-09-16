"""Offline price index for comparing published trading-day reports.

The index deliberately reads only generated report JSON and the local canonical
market-history SQLite database.  It never fetches quotes while reports are
being generated or compared.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from chanlun.preclose_schedule import is_trading_day
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

_STRATEGY_ID_BY_VIEW = {
    "main": "daily_fusion",
    "h4_t3": "h4_t3",
    "acceleration": "next_day_boom",
    "luojie": "luojie_pool",
    "confirming": "observation_gate",
    "observation_top5": "observation_gate",
    "baseline": "daily_pure",
}

_CURRENT_REVIEW_SNAPSHOTS = ContextVar(
    "comparison_review_snapshots", default={}
)
_BOOTSTRAP_ASSIGNMENT_RE = re.compile(
    r"window\s*\.\s*CHANLUN_BOOTSTRAP\s*="
)


class ComparisonIndexUnavailable(RuntimeError):
    """Known optional I/O/data failure while rebuilding the review index."""


@contextmanager
def comparison_review_snapshot(workbench):
    """Expose one in-memory workbench only while its report index is built."""
    report_date = _as_text(workbench.get("report_date")) \
        if isinstance(workbench, dict) else ""
    snapshots = {report_date: workbench} if report_date else {}
    token = _CURRENT_REVIEW_SNAPSHOTS.set(snapshots)
    try:
        yield
    finally:
        _CURRENT_REVIEW_SNAPSHOTS.reset(token)


class _InlineScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._inside_inline_script = False
        self._chunks = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "script":
            return
        attributes = {str(key).lower(): value for key, value in attrs}
        self._inside_inline_script = not attributes.get("src")
        self._chunks = []

    def handle_data(self, data):
        if self._inside_inline_script:
            self._chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._inside_inline_script:
            self.scripts.append("".join(self._chunks))
            self._inside_inline_script = False
            self._chunks = []


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


def _as_list(value):
    return value if isinstance(value, list) else []


def _workbench_views(workbench):
    views = {}
    if not isinstance(workbench, dict):
        return views
    for item in _as_list(workbench.get("items")):
        if not isinstance(item, dict):
            continue
        for strategy in _as_list(item.get("strategy_results")):
            if not isinstance(strategy, dict):
                continue
            view = _as_text(strategy.get("strategy_id"))
            candidate = strategy.get("candidate")
            if view not in VIEW_NAMES or not isinstance(candidate, dict):
                continue
            views.setdefault(view, []).append(candidate)
    return views


def _source_views(report, workbench=None):
    display_workbench = workbench
    if display_workbench is None and isinstance(report, dict):
        display_workbench = report.get("decisionWorkbench")
    display_views = _workbench_views(display_workbench)
    if any(display_views.values()):
        return display_views
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
        dates.append(date)
    return sorted(set(dates))[-int(window_size):]


def _read_archived_workbench(data_dir, report_date, source_report):
    archive_path = os.path.join(
        os.path.dirname(os.path.abspath(data_dir)), report_date, "index.html"
    )
    try:
        with open(archive_path, "r", encoding="utf-8") as handle:
            html = handle.read()
    except (OSError, UnicodeDecodeError):
        return None
    parser = _InlineScriptParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    decoder = json.JSONDecoder()
    workbenches = []
    for script in parser.scripts:
        for match in _BOOTSTRAP_ASSIGNMENT_RE.finditer(script):
            json_start = match.end()
            while json_start < len(script) and script[json_start] in " \t\r\n":
                json_start += 1
            try:
                bootstrap, _ = decoder.raw_decode(script, json_start)
            except (TypeError, ValueError):
                continue
            workbench = bootstrap.get("decisionWorkbench") \
                if isinstance(bootstrap, dict) else None
            if not isinstance(workbench, dict):
                continue
            if _as_text(workbench.get("report_date")) != report_date:
                continue
            if not isinstance(workbench.get("items"), list):
                continue
            inline_report = bootstrap.get("inlineReportData")
            identity_matches = (
                bootstrap.get("pageDate") == report_date
                and isinstance(inline_report, dict)
                and inline_report == source_report
            )
            workbenches.append({
                "workbench": workbench,
                "identity_matches": identity_matches,
            })
    if len(workbenches) != 1:
        return None
    return workbenches[0]


def _finite_number(value):
    number = _as_number(value)
    return number if number is not None and math.isfinite(number) else None


def _strategy_metadata_by_view(workbench):
    contract = workbench.get("comparison_contract") \
        if isinstance(workbench, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    versions = contract.get("strategy_version")
    versions = dict(versions) if isinstance(versions, dict) else {}
    identities = contract.get("strategy_identities")
    identities = identities if isinstance(identities, list) else []
    metadata = {}
    for identity in identities:
        if not isinstance(identity, dict):
            continue
        strategy_id = _as_text(identity.get("strategy_id"))
        version = _as_text(identity.get("strategy_version"))
        if strategy_id and version and strategy_id not in versions:
            versions[strategy_id] = version
        if strategy_id:
            metadata[strategy_id] = {
                "strategy_version": version or None,
                "policy_version": _as_text(identity.get("policy_version")) or None,
            }
    return {
        view: {
            "strategy_version": (
                _as_text(versions.get(strategy_id))
                or metadata.get(strategy_id, {}).get("strategy_version")
                or None
            ),
            "policy_version": metadata.get(strategy_id, {}).get("policy_version"),
        }
        for view, strategy_id in _STRATEGY_ID_BY_VIEW.items()
    }


def _source_performance_status(report, report_date, view, code):
    if view not in _FORMAL_STRATEGY_BY_VIEW:
        return "review_only"
    if not _formal_view_allowed(report, view):
        return "formal_input_blocked"
    excluded = _registered_incident_codes(report_date, view)
    if "*" in excluded or code in excluded:
        return "incident_excluded"
    return "formal_eligible"


def _review_source(strategy, metadata, report, report_date, code):
    if not isinstance(strategy, dict):
        return None
    view = _as_text(strategy.get("strategy_id"))
    if not view:
        return None
    candidate = strategy.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    decision = candidate.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    rank = strategy.get("view_rank")
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = None
    score = _finite_number(strategy.get("score"))
    if score is None:
        score = _finite_number(
            decision.get("total_score", decision.get("score"))
        )
    action = _as_text(
        strategy.get("formal_action")
        or candidate.get("strategy_action")
        or candidate.get("action")
        or decision.get("decision")
        or candidate.get("effective_action")
        or candidate.get("page_action")
    )
    version = _as_text(
        candidate.get("strategy_version")
        or candidate.get("version")
        or decision.get("strategy_version")
        or metadata.get(view, {}).get("strategy_version")
    )
    return {
        "view": view,
        "role": _as_text(strategy.get("role")) or "unknown",
        "rank": rank,
        "action": action or None,
        "score": score,
        "strategy_version": version or None,
        "decision_version": _as_text(decision.get("version")) or None,
        "policy_version": metadata.get(view, {}).get("policy_version"),
        "formal_performance_status": _source_performance_status(
            report, report_date, view, code
        ),
    }


def _review_identity(code, declared_instrument):
    expected_exchange = _expected_stock_exchange(code)
    expected = expected_exchange + code if expected_exchange else ""
    declared = _as_text(declared_instrument)
    if not expected:
        return None, "unresolved"
    accepted = {
        expected,
        expected_exchange + "." + code,
        "stock:{}:{}".format(expected_exchange, code),
    }
    if declared and declared not in accepted:
        return None, "conflict"
    return expected, "verified"


def _workbench_review_entries(report, report_date, workbench, snapshot_kind, coverage_status):
    metadata = _strategy_metadata_by_view(workbench)
    snapshot_id = _as_text(workbench.get("snapshot_id")) or None
    entries = []
    for item in _as_list(workbench.get("items")):
        if not isinstance(item, dict):
            continue
        code = _as_text(item.get("code"))
        if not code:
            continue
        instrument_id, identity_status = _review_identity(
            code, item.get("instrument_id")
        )
        sources = []
        strategies = _as_list(item.get("strategy_results"))
        for strategy in strategies:
            source = _review_source(
                strategy, metadata, report, report_date, code
            )
            if source is not None:
                sources.append(source)
        signal_dates = {
            _as_text((strategy.get("candidate") or {}).get("signal_date"))
            for strategy in strategies
            if isinstance(strategy, dict)
            and isinstance(strategy.get("candidate"), dict)
            and _as_text(strategy.get("candidate", {}).get("signal_date"))
        }
        entries.append({
            "report_date": report_date,
            "snapshot_id": snapshot_id,
            "snapshot_kind": snapshot_kind,
            "coverage_status": coverage_status,
            "instrument_id": instrument_id,
            "identity_status": identity_status,
            "code": code,
            "name": _as_text(item.get("name")),
            "sources": sources,
            "current_execution_status": _as_text(
                item.get("execution_status")
            ) or "unknown",
            "current_page_status": _as_text(item.get("page_status")) or None,
            "risk_flags": [
                _as_text(value) for value in _as_list(item.get("risk_flags"))
                if _as_text(value)
            ],
            "signal_date": next(iter(signal_dates))
                if len(signal_dates) == 1 else None,
        })
    return entries


def _legacy_review_entries(report, report_date):
    grouped = {}
    views = _source_views(report)
    for view in VIEW_NAMES:
        rows = views.get(view, []) if isinstance(views, dict) else []
        for position, item in enumerate(rows if isinstance(rows, list) else [], 1):
            if not isinstance(item, dict):
                continue
            code = _as_text(item.get("code"))
            if not code:
                continue
            instrument_id, identity_status = _review_identity(code, "")
            entry = grouped.setdefault(code, {
                "report_date": report_date,
                "snapshot_id": _as_text(report.get("snapshot_id")) or None,
                "snapshot_kind": "legacy_workspace_fallback",
                "coverage_status": "unconfirmed_legacy_workspace",
                "instrument_id": instrument_id,
                "identity_status": identity_status,
                "code": code,
                "name": _as_text(item.get("name")),
                "sources": [],
                "current_execution_status": "unknown",
                "current_page_status": None,
                "risk_flags": [],
                "signal_date": _as_text(item.get("signal_date")) or None,
            })
            source = _review_source({
                "strategy_id": view,
                "role": "formal" if view in _FORMAL_STRATEGY_BY_VIEW else "research",
                "view_rank": item.get("view_rank", item.get("rank", position)),
                "formal_action": item.get("action"),
                "candidate": item,
            }, {}, report, report_date, code)
            if source is not None:
                entry["sources"].append(source)
            entry["risk_flags"] = list(dict.fromkeys(
                entry["risk_flags"] + [
                    _as_text(value) for value in _as_list(item.get("risk_flags"))
                    if _as_text(value)
                ]
            ))
    return list(grouped.values())


def _deduplicate_review_entries(entries):
    """Merge same-day verified identities while retaining distinct sources."""
    merged = []
    by_identity = {}
    for entry in entries:
        instrument_id = entry.get("instrument_id")
        if entry.get("identity_status") != "verified" or not instrument_id:
            merged.append(entry)
            continue
        key = (entry.get("report_date"), instrument_id)
        existing = by_identity.get(key)
        if existing is None:
            by_identity[key] = entry
            merged.append(entry)
            continue
        source_keys = {
            json.dumps(source, ensure_ascii=False, sort_keys=True)
            for source in existing.get("sources", [])
        }
        for source in entry.get("sources", []):
            source_key = json.dumps(source, ensure_ascii=False, sort_keys=True)
            if source_key not in source_keys:
                existing.setdefault("sources", []).append(source)
                source_keys.add(source_key)
        existing["risk_flags"] = list(dict.fromkeys(
            _as_list(existing.get("risk_flags"))
            + _as_list(entry.get("risk_flags"))
        ))
        if existing.get("signal_date") != entry.get("signal_date"):
            existing["signal_date"] = None
        if (
            existing.get("snapshot_id") != entry.get("snapshot_id")
            or existing.get("snapshot_kind") != entry.get("snapshot_kind")
        ):
            existing["snapshot_kind"] = "mixed_same_day_snapshots"
            existing["coverage_status"] = "unconfirmed_report_identity"
    return merged


def _table_columns(connection, table_name):
    try:
        return {
            _as_text(row[1])
            for row in connection.execute("PRAGMA table_info({})".format(table_name))
        }
    except sqlite3.Error:
        return set()


def _review_calendar_and_cutoff(db_path, report_dates, date_meta):
    del date_meta  # report metadata is not a complete exchange calendar.
    calendar = set()
    calendar_status = "unavailable"
    data_cutoff = max(report_dates) if report_dates else ""
    if report_dates:
        try:
            start = datetime.strptime(min(report_dates), "%Y-%m-%d").date()
            end = datetime.strptime(max(report_dates), "%Y-%m-%d").date()
        except ValueError:
            start = end = None
        if start is not None and end is not None and {
            value.year for value in (start, end)
        } == {2026}:
            current = start
            limit = end + timedelta(days=21)
            while current <= limit:
                if is_trading_day(current.isoformat(), db_path):
                    calendar.add(current.isoformat())
                current += timedelta(days=1)
            calendar_status = "supported_2026_exchange_calendar"
    if db_path and os.path.isfile(db_path):
        connection = sqlite3.connect(
            "file:{}?mode=ro".format(os.path.abspath(db_path)), uri=True
        )
        try:
            if (
                calendar_status == "unavailable"
                and _table_columns(connection, "trade_calendar")
                and report_dates
                and start is not None
                and end is not None
            ):
                start_text = start.isoformat()
                calendar_end = end + timedelta(days=21)
                end_text = calendar_end.isoformat()
                rows = connection.execute(
                    "SELECT trade_date, is_open FROM trade_calendar "
                    "WHERE exchange='SH' "
                    "AND trade_date>=? AND trade_date<=?",
                    (start_text, end_text),
                ).fetchall()
                by_date = {
                    _as_text(row[0]): bool(row[1])
                    for row in rows if _as_text(row[0])
                }
                expected_dates = []
                current = start
                while current <= calendar_end:
                    expected_dates.append(current.isoformat())
                    current += timedelta(days=1)
                if expected_dates and all(
                    value in by_date for value in expected_dates
                ):
                    calendar.update(
                        value for value in expected_dates if by_date[value]
                    )
                    calendar_status = "local_trade_calendar"
            if _table_columns(connection, "bars_day"):
                row = connection.execute(
                    "SELECT MAX(ts) FROM bars_day WHERE is_final=1"
                ).fetchone()
                bar_cutoff = _as_text(row[0]) if row else ""
                if bar_cutoff:
                    data_cutoff = bar_cutoff
        finally:
            connection.close()
    return sorted(calendar), data_cutoff, calendar_status


def _review_target_dates(entries, calendar):
    positions = {value: index for index, value in enumerate(calendar)}
    targets = {}
    for entry in entries:
        report_date = entry["report_date"]
        start = positions.get(report_date)
        for horizon in (1, 3, 5):
            target = None
            if start is not None and start + horizon < len(calendar):
                target = calendar[start + horizon]
            targets[(report_date, horizon)] = target
    return targets


def _read_review_price_evidence(db_path, dates, codes):
    evidence = {}
    if not dates or not codes or not db_path or not os.path.isfile(db_path):
        return evidence
    connection = sqlite3.connect(
        "file:{}?mode=ro".format(os.path.abspath(db_path)), uri=True
    )
    try:
        columns = _table_columns(connection, "bars_day")
        adjustment_sql = "b.adjustment" if "adjustment" in columns else "NULL"
        canonical_adjustment = ""
        if _table_columns(connection, "bar_table_settings"):
            row = connection.execute(
                "SELECT adjustment FROM bar_table_settings "
                "WHERE table_name='bars_day'"
            ).fetchone()
            canonical_adjustment = _as_text(row[0]) if row else ""
        placeholders_dates = ",".join("?" for _ in dates)
        placeholders_codes = ",".join("?" for _ in codes)
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
        query = """
            SELECT b.ts, i.code, i.exchange, b.close, {adjustment}
            FROM bars_day b
            JOIN instruments i ON i.instrument_id = b.instrument_id
            WHERE b.is_final = 1
              AND i.asset_type = 'stock'
              AND b.ts IN ({dates})
              AND i.code IN ({codes})
        """.format(
            adjustment=adjustment_sql,
            dates=placeholders_dates,
            codes=placeholders_codes,
        )
        for trade_date, code, exchange, close, adjustment in connection.execute(
            query, list(dates) + list(codes)
        ):
            code = _as_text(code)
            expected_exchange = _expected_stock_exchange(code)
            if expected_exchange == "SZ" and code in ambiguous_sz_codes:
                continue
            if _as_text(exchange).upper() != expected_exchange:
                continue
            evidence[(_as_text(trade_date), code)] = {
                "price": _finite_number(close),
                "adjustment": _as_text(adjustment) or None,
                "canonical_basis_verified": bool(
                    canonical_adjustment
                    and _as_text(adjustment) == canonical_adjustment
                ),
            }
    finally:
        connection.close()
    return evidence


def _read_existing_comparison_index(data_dir):
    path = os.path.join(data_dir, "comparison-index.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _legacy_pair_is_comparable(
    existing_index, entry, horizon_key, target_date, base_price, endpoint_price
):
    if not isinstance(existing_index, dict):
        return False
    prior_registry = existing_index.get("review_registry")
    if isinstance(prior_registry, dict):
        for prior in _as_list(prior_registry.get("entries")):
            if not isinstance(prior, dict):
                continue
            if (
                prior.get("report_date") != entry.get("report_date")
                or prior.get("instrument_id") != entry.get("instrument_id")
            ):
                continue
            horizons = prior.get("horizons")
            horizons = horizons if isinstance(horizons, dict) else {}
            result = horizons.get(horizon_key, {})
            if not isinstance(result, dict):
                return False
            return bool(
                result.get("status") == "calculated_legacy_internal"
                and result.get("target_trading_date") == target_date
                and _finite_number(result.get("base_price")) == base_price
                and _finite_number(result.get("endpoint_price")) == endpoint_price
            )
        return False
    reports = existing_index.get("reports")
    reports = reports if isinstance(reports, dict) else {}
    base_report = reports.get(entry.get("report_date"))
    endpoint_report = reports.get(target_date)
    base_prices = base_report.get("prices") if isinstance(base_report, dict) else {}
    endpoint_prices = (
        endpoint_report.get("prices") if isinstance(endpoint_report, dict) else {}
    )
    base_prices = base_prices if isinstance(base_prices, dict) else {}
    endpoint_prices = endpoint_prices if isinstance(endpoint_prices, dict) else {}
    code = entry.get("code")
    return bool(
        code in base_prices
        and code in endpoint_prices
        and _finite_number(base_prices.get(code)) == base_price
        and _finite_number(endpoint_prices.get(code)) == endpoint_price
    )


def _horizon_result(
    entry, horizon, target_date, data_cutoff, prices, existing_index
):
    code = entry["code"]
    report_date = entry["report_date"]
    base = prices.get((report_date, code), {})
    endpoint = prices.get((target_date, code), {}) if target_date else {}
    result = {
        "target_trading_date": target_date,
        "status": "maturity_unknown",
        "matured": False,
        "base_price": base.get("price"),
        "endpoint_price": endpoint.get("price"),
        "price_source": "local_market_history" if base or endpoint else None,
        "price_basis_status": None,
        "return_pct": None,
    }
    if not target_date:
        return result
    if not data_cutoff or target_date > data_cutoff:
        result["status"] = "pending"
        return result
    result["matured"] = True
    if entry.get("identity_status") != "verified":
        result["status"] = "identity_conflict"
        return result
    base_price = base.get("price")
    endpoint_price = endpoint.get("price")
    if base_price is None or endpoint_price is None:
        result["status"] = "missing"
        return result
    if base_price <= 0 or endpoint_price <= 0:
        result["status"] = "invalid_price"
        return result
    base_adjustment = _as_text(base.get("adjustment"))
    endpoint_adjustment = _as_text(endpoint.get("adjustment"))
    if (
        base_adjustment not in {"raw", "qfq", "hfq"}
        or endpoint_adjustment != base_adjustment
        or base.get("canonical_basis_verified") is not True
        or endpoint.get("canonical_basis_verified") is not True
    ):
        result["status"] = "price_basis_unverified"
        return result
    horizon_key = "T+{}".format(horizon)
    if not _legacy_pair_is_comparable(
        existing_index,
        entry,
        horizon_key,
        target_date,
        base_price,
        endpoint_price,
    ):
        result["status"] = "price_basis_unverified"
        result["price_basis_status"] = (
            "new_pair_same_adjustment_not_independently_proven"
        )
        return result
    result["status"] = "calculated_legacy_internal"
    result["price_basis_status"] = (
        "legacy_same_index_{}_metadata_incomplete".format(base_adjustment)
    )
    result["return_pct"] = round(
        (endpoint_price - base_price) / base_price * 100.0, 6
    )
    return result


def _attach_review_horizons(
    entries, db_path, report_dates, date_meta, existing_index
):
    calendar, data_cutoff, calendar_status = _review_calendar_and_cutoff(
        db_path, report_dates, date_meta
    )
    targets = _review_target_dates(entries, calendar)
    price_dates = set(report_dates)
    for target in targets.values():
        if target:
            price_dates.add(target)
    codes = {
        entry["code"] for entry in entries
        if entry.get("identity_status") == "verified"
    }
    prices = _read_review_price_evidence(
        db_path, sorted(price_dates), sorted(codes)
    )
    summary = {}
    for horizon in (1, 3, 5):
        key = "T+{}".format(horizon)
        counts = {
            "registered": len(entries),
            "matured": 0,
            "calculable": 0,
            "missing": 0,
            "pending": 0,
            "maturity_unknown": 0,
            "incompatible": 0,
        }
        for entry in entries:
            target = targets.get((entry["report_date"], horizon))
            result = _horizon_result(
                entry, horizon, target, data_cutoff, prices, existing_index
            )
            entry.setdefault("horizons", {})[key] = result
            status = result["status"]
            if result["matured"]:
                counts["matured"] += 1
            if status == "calculated_legacy_internal":
                counts["calculable"] += 1
            elif status == "missing":
                counts["missing"] += 1
            elif status == "pending":
                counts["pending"] += 1
            elif status == "maturity_unknown":
                counts["maturity_unknown"] += 1
            else:
                counts["incompatible"] += 1
        counts["coverage_of_matured"] = (
            round(counts["calculable"] / counts["matured"], 6)
            if counts["matured"] else None
        )
        summary[key] = counts
    return summary, calendar_status, data_cutoff


def _build_review_registry(
    data_dir, reports, dates, db_path, date_meta, existing_index
):
    current = _CURRENT_REVIEW_SNAPSHOTS.get()
    entries = []
    for report_date in dates:
        report = reports[report_date]
        workbench = current.get(report_date) if isinstance(current, dict) else None
        if isinstance(workbench, dict):
            entries.extend(_workbench_review_entries(
                report, report_date, workbench,
                "current_generation_bootstrap", "confirmed_display_snapshot",
            ))
            continue
        archived = _read_archived_workbench(data_dir, report_date, report)
        if isinstance(archived, dict):
            identity_matches = archived.get("identity_matches") is True
            entries.extend(_workbench_review_entries(
                report,
                report_date,
                archived["workbench"],
                (
                    "published_html_bootstrap"
                    if identity_matches else "postprocessed_html_bootstrap"
                ),
                (
                    "confirmed_display_snapshot"
                    if identity_matches else "unconfirmed_report_identity"
                ),
            ))
        else:
            entries.extend(_legacy_review_entries(report, report_date))
    entries = _deduplicate_review_entries(entries)
    occurrences = {}
    totals = {}
    for entry in entries:
        instrument_id = entry.get("instrument_id")
        if instrument_id:
            totals[instrument_id] = totals.get(instrument_id, 0) + 1
    for entry in entries:
        instrument_id = entry.get("instrument_id")
        if not instrument_id:
            entry["first_seen_in_window"] = None
            entry["occurrence_in_window"] = None
            entry["occurrence_count_in_window"] = None
            continue
        state = occurrences.setdefault(instrument_id, {
            "first": entry["report_date"], "count": 0,
        })
        state["count"] += 1
        entry["first_seen_in_window"] = state["first"]
        entry["occurrence_in_window"] = state["count"]
        entry["occurrence_count_in_window"] = totals[instrument_id]
    horizon_summary, calendar_status, data_cutoff = _attach_review_horizons(
        entries, db_path, dates, date_meta, existing_index
    )
    return {
        "schema_version": 1,
        "status": "available",
        "review_only": True,
        "window_start": dates[0] if dates else "",
        "window_end": dates[-1] if dates else "",
        "registered_count": len(entries),
        "instrument_count": len(totals),
        "calendar_status": calendar_status,
        "price_data_cutoff": data_cutoff or None,
        "horizon_summary": horizon_summary,
        "entries": entries,
    }


def _unavailable_review_registry(dates, error):
    return {
        "schema_version": 1,
        "status": "unavailable",
        "review_only": True,
        "window_start": dates[0] if dates else "",
        "window_end": dates[-1] if dates else "",
        "registered_count": None,
        "instrument_count": None,
        "calendar_status": "unavailable",
        "price_data_cutoff": None,
        "horizon_summary": {},
        "entries": [],
        "unavailable_reason": "review_task_failed",
        "error_type": type(error).__name__,
    }


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
    source_reports = {}
    for date in dates:
        with open(
            os.path.join(data_dir, date + ".json"), "r", encoding="utf-8"
        ) as handle:
            source_reports[date] = json.load(handle)
    snapshots = {
        date: _read_report(os.path.join(data_dir, date + ".json"), date_meta.get(date))
        for date in dates
    }
    existing_index = _read_existing_comparison_index(data_dir)
    try:
        review_registry = _build_review_registry(
            data_dir, source_reports, dates, db_path, date_meta, existing_index
        )
    except Exception as exc:
        review_registry = _unavailable_review_registry(dates, exc)
    codes = sorted({
        row["code"]
        for snapshot in snapshots.values()
        for rows in snapshot["views"].values()
        for row in rows
    } | {
        entry["code"]
        for entry in review_registry["entries"]
        if entry.get("identity_status") == "verified"
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
        "review_registry": review_registry,
    }


def write_comparison_index(data_dir, db_path, window_size=26):
    """Rebuild and atomically publish ``comparison-index.json``."""
    try:
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
        fd, temporary = tempfile.mkstemp(
            prefix=".comparison-index-", suffix=".json", dir=data_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    index, handle, ensure_ascii=False, separators=(",", ":")
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise ComparisonIndexUnavailable(str(exc)) from exc
