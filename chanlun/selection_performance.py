"""Read-only, descriptive price observations for saved published lists.

This module never edits reports, the market database, or the formal strategy
scorecard. A canonical database row supplies a candidate price; a return needs
independent evidence that both closes belong to one comparable price series.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from statistics import mean, median

from chanlun.market_history_store import MarketHistoryStore
from chanlun.preclose_schedule import _SSE_2026_CLOSED
from chanlun.report_comparison import (
    _STRATEGY_ID_BY_VIEW,
    _bound_published_theme_context,
    _theme_refs,
    _workbench_review_entries,
    load_published_comparison_snapshot,
)


HORIZONS = (1, 3, 5, 10, 20, 30)
SCHEMA_VERSION = "selection-performance-v1"
CALC_VERSION = "published-close-six-horizons-v2"
STATUSES = (
    "ready", "waiting", "missing_price", "price_basis_unverified",
    "calendar_unknown", "excluded",
)


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _positive(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _valid_date(value):
    try:
        result = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return result if result.isoformat() == value else None


def _evaluation_cutoff(value):
    if _valid_date(value):
        return value, True
    parsed = _asof_datetime(value)
    if parsed is None:
        raise ValueError("evaluation_as_of must be an ISO date or zoned timestamp")
    local = parsed.astimezone(timezone(timedelta(hours=8)))
    return local.date().isoformat(), local.time() >= wall_time(15, 0)


def _series_bars(series):
    """Return indexed bars and a proof flag without trusting a label alone."""
    if not isinstance(series, dict):
        return {}, False
    bars = series.get("bars")
    if not isinstance(bars, list):
        return {}, False
    indexed = {}
    for bar in bars:
        if not isinstance(bar, dict) or not _valid_date(bar.get("date")):
            return {}, False
        day = bar["date"]
        if day in indexed:
            return {}, False
        indexed[day] = bar
    evidence = series.get("basis_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    digest = evidence.get("content_sha256")
    response = series.get("source_response")
    response = response if isinstance(response, dict) else {}
    response_digest = evidence.get("response_sha256")
    identity = series.get("instrument_id")
    stock_identity = re.fullmatch(
        r"(SH|SZ|BJ)(\d{6})", identity if isinstance(identity, str) else "",
    )
    expected_metadata = {
        "instrument_id": identity,
        "adjustment": series.get("adjustment"),
        "exchange": stock_identity.group(1) if stock_identity else None,
        "code": stock_identity.group(2) if stock_identity else None,
        "asset_type": "stock",
    }
    metadata_consistent = bool(stock_identity) and all(
        all(key not in record or record[key] == expected
            for key, expected in expected_metadata.items())
        for record in [series, response] + bars
    )
    safe_ref = lambda value: isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", value)
    )
    verified = bool(
        metadata_consistent
        and
        safe_ref(series.get("series_ref"))
        and safe_ref(evidence.get("source_ref"))
        and series.get("adjustment") == "qfq"
        and evidence.get("status") == "verified"
        and evidence.get("kind") == "single_historical_response"
        and isinstance(digest, str) and len(digest) == 64
        and digest == _digest(bars)
        and isinstance(response_digest, str) and len(response_digest) == 64
        and response_digest == _digest(response)
        and response.get("instrument_id") == series.get("instrument_id")
        and response.get("adjustment") == "qfq"
        and isinstance(response.get("provider"), str)
        and bool(response["provider"].strip())
        and response.get("bars") == bars
    )
    return indexed, verified


def _empty_outcome(report_date, target_date, status, reason=None, series_ref=None):
    return {
        "status": status, "reason_code": reason or status,
        "start_date": report_date, "target_date": target_date,
        "start_close": None, "end_close": None, "return_pct": None,
        "price_series_ref": series_ref,
    }


def _prepared_series(series):
    candidates = series if isinstance(series, list) else [series]
    return [(*_series_bars(item), item) for item in candidates
            if isinstance(item, dict)]


def _series_for_endpoints(prepared, identity, start_date, target_date):
    """Choose one proved response for both closes; reject conflicting proofs."""
    complete = []
    for bars, verified, series in prepared:
        start = bars.get(start_date)
        end = bars.get(target_date)
        if not verified or series.get("instrument_id") != identity or not start or not end:
            continue
        start_price, end_price = _positive(start.get("close")), _positive(end.get("close"))
        if not start_price or not end_price or start.get("is_final") is not True \
                or end.get("is_final") is not True:
            continue
        if any("volume" in bar and _positive(bar.get("volume")) is None
               for bar in (start, end)):
            continue
        complete.append((start_price, end_price, bars, series))
    if len({(item[0], item[1]) for item in complete}) > 1:
        return ({}, False, {}), True
    if complete:
        chosen = min(complete, key=lambda item: item[3]["series_ref"])
        return (chosen[2], True, chosen[3]), False
    # The canonical DB candidate is appended last to a set of raw responses.
    # It may show closes, but cannot attest to a comparable price basis.
    if prepared:
        bars, verified, series = prepared[-1]
        return (bars, verified, series), False
    return ({}, False, {}), False


def evaluate_observations(observations, trading_calendar, series_by_id,
                          evaluation_as_of):
    """Calculate six fixed trading-day endpoints for already selected members.

    `series_by_id` may contain unverified canonical DB candidates. In that case
    prices remain visible as evidence, but their return is deliberately null.
    """
    cutoff_date, cutoff_closed = _evaluation_cutoff(evaluation_as_of)
    calendar = list(trading_calendar or [])
    if calendar != sorted(set(calendar)) or any(not _valid_date(d) for d in calendar):
        raise ValueError("trading_calendar must be sorted, unique ISO dates")
    positions = {day: index for index, day in enumerate(calendar)}
    loaded = {identity: _prepared_series(series)
              for identity, series in (series_by_id or {}).items()}
    results = []
    for original in observations:
        observation = copy.deepcopy(original)
        report_date = observation.get("report_date")
        identity = observation.get("instrument_id")
        position = positions.get(report_date)
        prepared = loaded.get(identity, [])
        refs_by_key = {}
        for ref in observation.get("strategy_refs") or []:
            if isinstance(ref, dict) and isinstance(ref.get("strategy_key"), str):
                refs_by_key.setdefault(ref["strategy_key"], []).append(ref)
        source_excluded = {key: all(
            ref.get("formal_performance_status") == "incident_excluded"
            for ref in refs) for key, refs in refs_by_key.items()}
        explicit_exclusion = observation.get("excluded_reason")
        if explicit_exclusion == "registered_incident" and refs_by_key \
                and not all(source_excluded.values()):
            explicit_exclusion = None
        if not explicit_exclusion and refs_by_key and all(source_excluded.values()):
            explicit_exclusion = "registered_incident"
        observation["excluded_reason"] = explicit_exclusion
        outcomes = {}
        for horizon in HORIZONS:
            key = "t{}".format(horizon)
            target_date = (
                calendar[position + horizon]
                if position is not None and position + horizon < len(calendar)
                else None
            )
            if explicit_exclusion:
                result = _empty_outcome(report_date, target_date, "excluded",
                                        explicit_exclusion)
            elif target_date is None:
                result = _empty_outcome(report_date, None, "calendar_unknown")
            elif target_date > cutoff_date or (
                    target_date == cutoff_date and not cutoff_closed):
                result = _empty_outcome(report_date, target_date, "waiting",
                                        "target_not_closed")
            else:
                (bars, verified, series), conflict = _series_for_endpoints(
                    prepared, identity, report_date, target_date)
                series_ref = series.get("series_ref") if verified else None
                start = bars.get(report_date)
                end = bars.get(target_date)
                start_price = _positive(start.get("close")) if start else None
                end_price = _positive(end.get("close")) if end else None
                start_final = bool(start and start.get("is_final") is True)
                end_final = bool(end and end.get("is_final") is True)
                start_traded = bool(start and (
                    "volume" not in start or _positive(start.get("volume")) is not None
                ))
                end_traded = bool(end and (
                    "volume" not in end or _positive(end.get("volume")) is not None
                ))
                if conflict:
                    result = _empty_outcome(report_date, target_date,
                                            "price_basis_unverified",
                                            "conflicting_verified_series")
                elif end and not end_final:
                    status = "waiting" if target_date == cutoff_date else "missing_price"
                    result = _empty_outcome(report_date, target_date, status,
                                            "target_close_unconfirmed")
                elif not start or not end or start_price is None or end_price is None \
                        or not start_final:
                    result = _empty_outcome(report_date, target_date,
                                            "missing_price")
                elif not start_traded or not end_traded:
                    result = _empty_outcome(
                        report_date, target_date, "missing_price",
                        "start_no_traded_close" if not start_traded
                        else "target_no_traded_close",
                    )
                elif not verified or series.get("instrument_id") != identity:
                    result = _empty_outcome(report_date, target_date,
                                            "price_basis_unverified")
                else:
                    result = _empty_outcome(report_date, target_date, "ready",
                                            "verified_same_series", series_ref)
                    result["return_pct"] = (
                        (end_price - start_price) / start_price * 100.0
                    )
                    response = series.get("source_response")
                    response = response if isinstance(response, dict) else {}
                    raw_hash = response.get("raw_sha256")
                    fetched_at = response.get("fetched_at")
                    if (isinstance(raw_hash, str)
                            and re.fullmatch(r"[0-9a-f]{64}", raw_hash)
                            and _asof_datetime(fetched_at)):
                        result["price_evidence"] = {
                            "raw_sha256": raw_hash, "fetched_at": fetched_at,
                        }
                result["start_close"] = start_price
                result["end_close"] = end_price
            outcomes[key] = result
        observation["outcomes"] = outcomes
        observation["source_outcomes"] = {
            strategy_key: {
                horizon: (_empty_outcome(report_date, outcome["target_date"],
                                         "excluded", "registered_incident")
                          if is_excluded else copy.deepcopy(outcome))
                for horizon, outcome in outcomes.items()
            }
            for strategy_key, is_excluded in source_excluded.items()
        }
        results.append(observation)
    return results


def _matched(observation, *, report_start=None, report_end=None,
             theme_id=None, strategy_key=None, role=None,
             recommendation_scope=None):
    day = observation.get("report_date") or ""
    if report_start and day < report_start or report_end and day > report_end:
        return False
    if theme_id is not None:
        refs = observation.get("theme_refs") or []
        if theme_id == "unrecorded":
            if refs:
                return False
        elif not any(row.get("theme_id") == theme_id
                     for row in refs if isinstance(row, dict)):
            return False
    if (strategy_key is not None or role is not None
            or recommendation_scope is not None) and not any(
        (strategy_key is None or row.get("strategy_key") == strategy_key)
        and (role is None or row.get("role") == role)
        and (role != "formal" or row.get("recommendation_scope") == "formal_recommendation")
        and (recommendation_scope is None or
             row.get("recommendation_scope") == recommendation_scope)
        and ((role != "formal" and recommendation_scope != "formal_recommendation")
             or row.get("formal_performance_status") != "incident_excluded")
        for row in observation.get("strategy_refs") or [] if isinstance(row, dict)
    ):
        return False
    return True


def aggregate_selection_performance(dataset, *, horizon, report_start=None,
                                    report_end=None, theme_id=None,
                                    strategy_key=None, role=None,
                                    recommendation_scope=None):
    """Use one filtered cohort for cards, counts, and endpoint extrema."""
    if horizon not in HORIZONS:
        raise ValueError("unsupported selection horizon")
    key = "t{}".format(horizon)
    selected = [
        row for row in dataset.get("observations") or []
        if _matched(row, report_start=report_start, report_end=report_end,
                    theme_id=theme_id, strategy_key=strategy_key, role=role,
                    recommendation_scope=recommendation_scope)
    ]
    counts = {status: 0 for status in STATUSES}
    ready = []
    for observation in selected:
        outcome = (observation.get("outcomes") or {}).get(key) or {}
        if strategy_key and "source_outcomes" in observation:
            all_source_outcomes = observation["source_outcomes"]
            source_outcomes = (all_source_outcomes.get(strategy_key)
                               if isinstance(all_source_outcomes, dict) else None)
            if not isinstance(source_outcomes, dict) or key not in source_outcomes:
                raise ValueError("source outcome missing for selected strategy")
            outcome = source_outcomes[key]
            if not isinstance(outcome, dict):
                raise ValueError("invalid source outcome for selected strategy")
        elif strategy_key:
            selected_refs = [ref for ref in observation.get("strategy_refs") or []
                             if isinstance(ref, dict)
                             and ref.get("strategy_key") == strategy_key]
            if selected_refs and all(
                ref.get("formal_performance_status") == "incident_excluded"
                for ref in selected_refs
            ):
                outcome = _empty_outcome(observation.get("report_date"),
                                         outcome.get("target_date"), "excluded",
                                         "registered_incident")
            elif outcome.get("status") == "ready" and any(
                isinstance(ref, dict)
                and ref.get("formal_performance_status") == "incident_excluded"
                for ref in observation.get("strategy_refs") or []
            ):
                raise ValueError("legacy mixed-incident outcome has no source proof")
        status = outcome.get("status")
        if status not in counts:
            raise ValueError("unrecognized outcome status")
        counts[status] += 1
        if status == "ready":
            number = outcome.get("return_pct")
            if isinstance(number, bool) or not isinstance(number, (int, float)) \
                    or not math.isfinite(number):
                raise ValueError("ready outcome has invalid return")
            ready.append((observation, outcome, float(number)))
    values = [item[2] for item in ready]
    ordered = sorted(ready, key=lambda item: (
        item[0].get("report_date") or "",
        item[0].get("instrument_id") or "",
        item[0].get("observation_id") or "",
    ))

    def extrema(value):
        return [{
            "observation_id": row.get("observation_id"),
            "instrument_id": row.get("instrument_id"),
            "code": row.get("code"), "name": row.get("name"),
            "report_date": row.get("report_date"),
            "target_date": outcome.get("target_date"),
            "start_close": outcome.get("start_close"),
            "end_close": outcome.get("end_close"),
            "return_pct": result,
            "publication_ref": row.get("publication_ref"),
            "price_series_ref": outcome.get("price_series_ref"),
        } for row, outcome, result in ordered
                if math.isclose(result, value, rel_tol=1e-12, abs_tol=1e-10)]

    return {
        "horizon": horizon,
        "total_observations": len(selected),
        "counts": counts,
        "expected_results": (counts["ready"] + counts["missing_price"]
                             + counts["price_basis_unverified"]),
        "unique_stocks": len({row.get("instrument_id") for row in selected
                              if row.get("instrument_id")}),
        "report_dates": len({row.get("report_date") for row in selected
                             if row.get("report_date")}),
        "mean_return_pct": mean(values) if values else None,
        "median_return_pct": median(values) if values else None,
        "positive_ratio_pct": (
            sum(value > 0 for value in values) / len(values) * 100.0
            if values else None
        ),
        "best_observations": extrema(max(values)) if values else [],
        "worst_observations": extrema(min(values)) if values else [],
    }


def _asof_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _strategy_refs(sources, contract, report_date, snapshot_id):
    identities = contract.get("strategy_identities") if isinstance(contract, dict) else []
    identities = identities if isinstance(identities, list) else []
    result = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        view = source.get("view")
        strategy_id = _STRATEGY_ID_BY_VIEW.get(view, view)
        matches = [item for item in identities
                   if isinstance(item, dict) and item.get("strategy_id") == strategy_id]
        identity = matches[0] if len(matches) == 1 else {}
        version = source.get("strategy_version") or identity.get("strategy_version")
        policy = source.get("policy_version") or identity.get("policy_version")
        role = source.get("role") or "unknown"
        scope = {
            "strategy_id": strategy_id,
            "strategy_version": version,
            "policy_version": policy,
            "source_pool": identity.get("source_pool"),
            "entry_mode": identity.get("entry_mode"),
            "intended_horizon": identity.get("intended_horizon"),
            "research_tier": identity.get("research_tier"),
            "decision_version": source.get("decision_version"),
            "role": role,
        }
        complete = len(matches) == 1 and all(scope.get(key) is not None for key in (
            "strategy_id", "strategy_version", "policy_version",
            "source_pool", "entry_mode", "decision_version", "role",
        ))
        recommendation_scope = (
            "formal_recommendation"
            if role == "formal"
            and source.get("formal_performance_status") == "formal_eligible"
            and source.get("action") == "可上车"
            else "published_observation"
        )
        strategy_key = (
            _digest(scope)[:20] if complete else
            "partial:" + _digest({
                "report_date": report_date, "snapshot_id": snapshot_id,
                "view": view, "scope": scope,
            })[:20]
        )
        result.append(dict(scope,
                           strategy_key=strategy_key,
                           identity_status="complete" if complete else "partial",
                           view=view,
                           recommendation_scope=recommendation_scope,
                           score=source.get("score"),
                           score_definition=(source.get("score_definition")
                                             if isinstance(source.get("score_definition"), str)
                                             and source["score_definition"].strip() else None),
                           score_name=(source.get("score_name")
                                       if isinstance(source.get("score_name"), str)
                                       and source["score_name"].strip() else None),
                           score_definition_status=(
                               "recorded" if source.get("score_definition")
                               or source.get("score_name") else "unrecorded"
                           ),
                           rank=source.get("rank"),
                           action=source.get("action"),
                           formal_performance_status=source.get("formal_performance_status")))
    return result


def load_published_observations(data_dir, report_as_of):
    """Scan every saved report date, retaining only bound published membership.

    A missing or invalid HTML archive cannot be filled from raw candidate rows.
    The comparison loader itself decides whether a receipt may replace an
    archive that was removed after the original publication.
    """
    if not _valid_date(report_as_of):
        raise ValueError("report_as_of must be an ISO date")
    root = Path(data_dir)
    manifest = json.loads((root / "index.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("dates"), list):
        raise ValueError("invalid saved report index")
    date_meta = manifest.get("date_meta")
    date_meta = date_meta if isinstance(date_meta, dict) else {}
    observations = []
    sources = []
    missing = {}
    missing_files = []
    invalid_reports = []
    nontrading = []
    report_fingerprints = []
    saved = 0
    published = 0
    filename_dates = {
        path.stem for path in root.glob("????-??-??.json")
        if _valid_date(path.stem)
    }
    listed_dates = set(manifest["dates"]) | filename_dates
    for report_date in sorted(listed_dates):
        if not _valid_date(report_date) or report_date > report_as_of:
            continue
        path = root / (report_date + ".json")
        if not path.is_file():
            missing_files.append(report_date)
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("date") != report_date:
            invalid_reports.append(report_date)
            continue
        if (date_meta.get(report_date) or {}).get("is_trading_day") is False \
                or (report.get("data_quality") or {}).get("is_trading_day") is False:
            nontrading.append(report_date)
            continue
        saved += 1
        report_fingerprints.append({"report_date": report_date, "sha256": _digest(report)})
        snapshot = load_published_comparison_snapshot(str(root), report_date, report)
        if snapshot.get("membership_status") != "available":
            missing[report_date] = snapshot.get("reason") or "published_snapshot_unavailable"
            continue
        published += 1
        workbench = snapshot.get("workbench")
        theme_context = None
        if isinstance(workbench, dict):
            rows = _workbench_review_entries(
                report, report_date, workbench, snapshot["source"],
                "confirmed_display_snapshot",
            )
            contract = workbench.get("comparison_contract") or {}
            publication_asof = workbench.get("as_of")
            archive = root.parent / report_date / "index.html"
            version_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        else:
            rows = list(snapshot["members"].values())
            registry = json.loads((root / "comparison-index.json").read_text(encoding="utf-8"))
            receipt = snapshot["member_receipt"]
            contract = (receipt.get("binding") or {}).get("comparison_contract") or {}
            theme_context = _bound_published_theme_context(
                (((registry.get("review_registry") or {})
                  .get("published_theme_contexts") or {}).get(report_date)),
                report, report_date, receipt,
            )
            version_hash = receipt.get("content_sha256")
        report_hash = _digest(report)
        publication_ref = {
            "report_date": report_date,
            "snapshot_id": snapshot["snapshot_id"],
            "source": snapshot["source"],
            "report_sha256": report_hash,
            "publication_sha256": version_hash,
            "theme_context_sha256": (theme_context.get("content_sha256")
                                     if theme_context else None),
        }
        sources.append(publication_ref)
        unique = set()
        for row in rows:
            identity = row.get("instrument_id")
            if row.get("identity_status") != "verified" or not identity \
                    or identity in unique:
                continue
            unique.add(identity)
            code = row.get("code")
            strategies = _strategy_refs(row.get("sources") or [], contract,
                                        report_date, snapshot["snapshot_id"])
            roles = sorted(set(ref["role"] for ref in strategies))
            excluded = bool(strategies) and all(
                ref.get("formal_performance_status") == "incident_excluded"
                for ref in strategies)
            themes = (_theme_refs(report, publication_asof, code)
                      if isinstance(workbench, dict) else
                      (theme_context["theme_refs_by_instrument"].get(identity, [])
                       if theme_context else []))
            observations.append({
                "observation_id": "{}:{}:{}".format(
                    report_date, snapshot["snapshot_id"], identity),
                "instrument_id": identity,
                "code": code,
                "name": row.get("name") or code,
                "report_date": report_date,
                "publication_ref": publication_ref,
                "recommendation_role": roles[0] if len(roles) == 1 else "mixed" if roles else "unknown",
                "source_views": sorted(set(ref.get("view") for ref in strategies if ref.get("view"))),
                "strategy_refs": strategies,
                "theme_refs": themes,
                "excluded_reason": "registered_incident" if excluded else None,
            })
    observations.sort(key=lambda row: (row["report_date"], row["instrument_id"]))
    return {
        "observations": observations,
        "publication_sources": sources,
        "report_fingerprints": report_fingerprints,
        "coverage": {
            "saved_report_dates": saved,
            "listed_report_dates": len([
                value for value in listed_dates
                if _valid_date(value) and value <= report_as_of
            ]),
            "published_report_dates": published,
            "unproven_report_dates": saved - published,
            "unproven_reports": missing,
            "missing_report_files": len(missing_files),
            "missing_file_dates": missing_files,
            "invalid_report_files": len(invalid_reports),
            "invalid_report_dates": invalid_reports,
            "nontrading_report_dates": len(nontrading),
            "nontrading_dates": nontrading,
            "registered_observations": len(observations),
            "unique_stocks": len(set(row["instrument_id"] for row in observations)),
            "theme_at_publication_observations": sum(bool(row["theme_refs"]) for row in observations),
        },
    }


def _trading_calendar(db_path, start, report_as_of):
    first = _valid_date(start)
    last = _valid_date(report_as_of)
    if first is None or last is None:
        return []
    # Seventy calendar days cover 30 trading days even around long holidays.
    end = last + timedelta(days=70)
    dates = []
    connection = None
    if Path(db_path).is_file():
        connection = sqlite3.connect(
            "file:{}?mode=ro".format(Path(db_path).resolve()), uri=True
        )
    try:
        current = first
        while current <= end:
            day = current.isoformat()
            flags = None
            if connection is not None:
                try:
                    rows = connection.execute(
                        "SELECT exchange,is_open FROM trade_calendar "
                        "WHERE trade_date=? AND exchange IN ('SH','SZ')",
                        (day,),
                    ).fetchall()
                except sqlite3.Error:
                    rows = []
                by_exchange = {}
                for exchange, is_open in rows:
                    by_exchange.setdefault(exchange, set()).add(is_open)
                if (set(by_exchange) == {"SH", "SZ"}
                        and all(len(values) == 1 for values in by_exchange.values())):
                    per_exchange = [next(iter(values)) for values in by_exchange.values()]
                    if len(set(per_exchange)) == 1:
                        flags = per_exchange[0] == 1
            if current.year == 2026:
                is_open = (current.weekday() < 5 and
                           (flags if flags is not None else day not in _SSE_2026_CLOSED))
            elif flags is None:
                # A partial unknown-year table cannot jump over missing dates.
                break
            else:
                is_open = current.weekday() < 5 and flags
            if is_open:
                dates.append(day)
            current += timedelta(days=1)
    finally:
        if connection is not None:
            connection.close()
    return dates


def _load_db_series(db_path, observations, cutoff_date):
    """Read canonical candidate bars only; no cross-date basis attestation."""
    path = Path(db_path)
    if not path.is_file() or not observations:
        return {}, {"status": "missing" if not path.is_file() else "empty",
                    "resolved_instruments": 0, "requested_instruments": len({
                        row["instrument_id"] for row in observations}),
                    "canonical_adjustment": None}
    first = min(row["report_date"] for row in observations)
    identities = sorted({row["instrument_id"] for row in observations})
    exchange_codes = [(identity[:2], identity[2:]) for identity in identities]
    with MarketHistoryStore(path, readonly=True) as store:
        adjustment = store.get_canonical_adjustment("day")
        instruments = store.resolve_instruments("stock", exchange_codes)
        ids = sorted({int(row["instrument_id"]) for row in instruments.values()})
        rows_by_id = store.query_bars_many(
            "day", ids, start=first, end=cutoff_date,
        )
    by_database_id = {
        int(row["instrument_id"]): exchange + code
        for (exchange, code), row in instruments.items()
    }
    result = {}
    for database_id, rows in rows_by_id.items():
        identity = by_database_id.get(int(database_id))
        if not identity:
            continue
        result[identity] = {
            "instrument_id": identity,
            "series_ref": "canonical-db:" + identity,
            "adjustment": adjustment,
            "bars": [{
                "date": str(row.get("ts") or "")[:10],
                "close": row.get("close"),
                "volume": row.get("volume"),
                "is_final": row.get("is_final") is True or row.get("is_final") == 1,
                "adjustment": row.get("adjustment"),
                "source_batch": row.get("source_batch"),
            } for row in rows],
            # No per-row common anchor, factor, or one-response ID in this DB.
            "basis_evidence": None,
        }
    return result, {
        "status": "available" if adjustment == "qfq" else "adjustment_unverified",
        "resolved_instruments": len(result),
        "requested_instruments": len(identities),
        "canonical_adjustment": adjustment,
    }


def _load_verified_series(price_series_file):
    if price_series_file is None:
        return {}, None
    path = Path(price_series_file)
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "verified-price-series-v1":
        raise ValueError("invalid verified price series file")
    rows = payload.get("series")
    if not isinstance(rows, list):
        raise ValueError("invalid verified price series list")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("instrument_id"), str):
            raise ValueError("invalid verified price series identity")
        identity = row["instrument_id"]
        if identity in result:
            raise ValueError("duplicate verified price series identity")
        bars, verified = _series_bars(row)
        if not verified or not bars or not identity.startswith(("SH", "SZ", "BJ")):
            raise ValueError("unverified price series evidence")
        result[identity] = row
    return result, hashlib.sha256(raw).hexdigest()


def _group_summaries(dataset):
    themes = {}
    strategies = {}
    for row in dataset["observations"]:
        if not row.get("theme_refs"):
            themes.setdefault("unrecorded", "题材未记录")
        for theme in row.get("theme_refs") or []:
            if isinstance(theme, dict) and theme.get("theme_id"):
                themes.setdefault(theme["theme_id"], theme.get("name"))
        for strategy in row.get("strategy_refs") or []:
            if isinstance(strategy, dict) and strategy.get("strategy_key"):
                strategies.setdefault(strategy["strategy_key"], {
                    "strategy_id": strategy.get("strategy_id"),
                    "strategy_version": strategy.get("strategy_version"),
                    "source_pool": strategy.get("source_pool"),
                    "entry_mode": strategy.get("entry_mode"),
                    "intended_horizon": strategy.get("intended_horizon"),
                    "decision_version": strategy.get("decision_version"),
                    "role": strategy.get("role"),
                })
    groups = {"themes": {}, "strategies": {}}
    for theme_id, name in sorted(themes.items()):
        groups["themes"][theme_id] = {
            "label": name,
            "horizons": {"t{}".format(h): aggregate_selection_performance(
                dataset, horizon=h, theme_id=theme_id,
            ) for h in HORIZONS},
        }
    for strategy_key, identity in sorted(strategies.items()):
        groups["strategies"][strategy_key] = {
            "identity": identity,
            "horizons": {"t{}".format(h): aggregate_selection_performance(
                dataset, horizon=h, strategy_key=strategy_key,
            ) for h in HORIZONS},
        }
    return groups


def build_selection_performance(data_dir, db_path, report_as_of,
                                evaluation_as_of, *, price_series_file=None,
                                price_evidence_dir=None, price_evidence_as_of=None):
    """Build an isolated derived dataset from local saved facts and read-only DB."""
    if not _valid_date(report_as_of):
        raise ValueError("report_as_of must be an ISO date")
    cutoff_date, _cutoff_closed = _evaluation_cutoff(evaluation_as_of)
    loaded = load_published_observations(data_dir, report_as_of)
    observations = loaded["observations"]
    first = min((row["report_date"] for row in observations), default=report_as_of)
    # Include enough proven calendar days for the UI's 60-trading-day default.
    # Unknown years still require the complete exchange calendar in the DB.
    lookback = date.fromisoformat(report_as_of) - timedelta(days=100)
    if lookback.year < 2026 <= date.fromisoformat(report_as_of).year:
        lookback = date(2026, 1, 1)
    calendar = _trading_calendar(db_path, min(first, lookback.isoformat()), report_as_of)
    if first not in calendar:
        calendar = _trading_calendar(db_path, first, report_as_of)
    db_series, db_coverage = _load_db_series(db_path, observations, cutoff_date)
    supplied_series, supplied_hash = _load_verified_series(price_series_file)
    combined_series = dict(db_series)
    combined_series.update(supplied_series)
    evidence_hash = None
    evidence_series = {}
    proof_refs = []
    if price_evidence_dir is not None:
        from chanlun.selection_price_evidence import load_verified_price_series
        identities = sorted({row["instrument_id"] for row in observations})
        evidence_series, evidence_hash = load_verified_price_series(
            price_evidence_dir, identities, evaluation_as_of=evaluation_as_of,
            evidence_as_of=(price_evidence_as_of if price_evidence_as_of is not None
                            else evaluation_as_of))
        for identity, candidates in evidence_series.items():
            candidates = candidates if isinstance(candidates, list) else [candidates]
            for candidate in candidates:
                response = candidate.get("source_response") if isinstance(candidate, dict) else None
                response = response if isinstance(response, dict) else {}
                proof_refs.append({
                    "instrument_id": identity,
                    "raw_sha256": response.get("raw_sha256"),
                    "fetched_at": response.get("fetched_at"),
                })
            combined_series[identity] = (
                list(candidates)
                + ([supplied_series[identity]] if identity in supplied_series else [])
                + ([db_series[identity]] if identity in db_series else [])
            )
    outcomes = evaluate_observations(
        observations, calendar, combined_series, evaluation_as_of,
    )
    proof_refs.sort(key=lambda row: (row["instrument_id"], row["raw_sha256"] or "",
                                     row["fetched_at"] or ""))
    proof_times = [(_asof_datetime(row["fetched_at"]), row["fetched_at"])
                   for row in proof_refs if _asof_datetime(row["fetched_at"])]
    evidence_as_of = max(proof_times)[1] if proof_times else None
    exclusion_path = Path(__file__).resolve().parents[1] / "config" / "strategy_sample_exclusions.json"
    exclusion_hash = (hashlib.sha256(exclusion_path.read_bytes()).hexdigest()
                      if exclusion_path.is_file() else None)
    manifest_path = Path(data_dir) / "index.json"
    fingerprints = {
        "schema_version": SCHEMA_VERSION,
        "calculation_version": CALC_VERSION,
        "calculation_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "published_loader_source_sha256": hashlib.sha256(
            Path(__file__).with_name("report_comparison.py").read_bytes()).hexdigest(),
        "calendar_source_sha256": hashlib.sha256(
            Path(__file__).with_name("preclose_schedule.py").read_bytes()).hexdigest(),
        "report_as_of": report_as_of,
        "evaluation_as_of": evaluation_as_of,
        "report_index_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "saved_reports": loaded["report_fingerprints"],
        "publications": loaded["publication_sources"],
        "calendar_sha256": _digest(calendar),
        "exclusion_registry_sha256": exclusion_hash,
        "candidate_bars_sha256": _digest(db_series),
        "verified_series_file_sha256": supplied_hash,
        "verified_evidence_sha256": evidence_hash,
        "price_evidence_decoder_source_sha256": (
            hashlib.sha256(Path(__file__).with_name("selection_price_evidence.py")
                           .read_bytes()).hexdigest()
            if price_evidence_dir is not None else None
        ),
        "accepted_price_proofs": proof_refs,
    }
    dataset = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": _digest(fingerprints),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report_as_of": report_as_of,
        "evaluation_as_of": evaluation_as_of,
        "evidence_as_of": evidence_as_of,
        "price_proofs": proof_refs,
        "measurement": "published_close_to_close",
        "cohort_policy": "report_date_instrument_dedup",
        "horizons": list(HORIZONS),
        "calendar_source": "sse_2026_schedule_or_local_trade_calendar",
        "calendar_first": calendar[0] if calendar else None,
        "calendar_last": calendar[-1] if calendar else None,
        "trading_dates": [day for day in calendar if day <= report_as_of],
        "coverage": dict(loaded["coverage"], market=db_coverage,
                         verified_series_count=len(supplied_series) + len(evidence_series)),
        "observations": outcomes,
    }
    dataset["summary"] = {
        "t{}".format(h): aggregate_selection_performance(dataset, horizon=h)
        for h in HORIZONS
    }
    dataset["groups"] = _group_summaries(dataset)
    return dataset


def write_selection_performance(dataset, output_dir):
    """Atomically write only the derived result, preserving equal datasets."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "selection-performance.json"
    if target.is_file():
        try:
            prior = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            prior = None
        if isinstance(prior, dict) and prior.get("dataset_id") == dataset.get("dataset_id"):
            old_facts = dict(prior)
            new_facts = dict(dataset)
            old_facts.pop("generated_at", None)
            new_facts.pop("generated_at", None)
            if _digest(old_facts) == _digest(new_facts):
                return target
    content = json.dumps(dataset, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".selection-performance-",
                                         suffix=".tmp", dir=str(output),
                                         delete=False) as handle:
            name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, str(target))
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return target
