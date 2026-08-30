"""Build read-only recommendation evidence for the HTML bootstrap.

This module is deliberately outside the formal daily projection.  Its return
value is presentation data only and must never be written to the formal JSON,
selection stores, ledgers, or pre-close snapshots.
"""

import math
from collections.abc import Mapping
from datetime import date as _calendar_date
from datetime import datetime as _calendar_datetime
from numbers import Real


EVIDENCE_SECTION_KEYS = (
    "summary",
    "decision_score",
    "rank_evidence",
    "price_evidence",
    "daily_structure",
    "sublevel_30m",
    "volume_and_capital",
    "market_and_sector",
    "risk_and_next",
    "historical_validation",
    "display_derived",
)


_RANK_TRACE_FIELDS = (
    "base_source",
    "source_count",
    "signal_score",
    "entry_score",
    "momentum_score",
    "market_score",
    "risk_penalty",
    "data_penalty",
    "alpha_bonus",
    "pool_quality_bonus",
    "pool_quality_score",
    "alpha_multiplier",
    "base_opportunity_score",
    "opportunity_score",
    "distance_from_reference_pct",
    "change_pct",
    "selected_reason",
)

_FORMAL_MARKET_COMPONENTS = (
    "breadth",
    "limit_ecology",
    "index",
    "turnover",
    "trend",
)

_FORMAL_MARKET_EVIDENCE_FIELDS = (
    "available",
    "valid_count",
    "excluded_count",
    "advance_count",
    "decline_count",
    "flat_count",
    "advance_ratio",
    "median_change_pct",
    "rise_over_3_count",
    "fall_over_3_count",
    "limit_up_count",
    "limit_down_count",
    "limit_ratio",
    "log_limit_ratio",
    "ratio_score",
    "limit_up_ratio",
    "limit_down_ratio",
    "limit_up_score",
    "limit_down_score",
    "improvement_score",
    "average_change_pct",
    "ratio_to_ma5",
    "ratio_to_ma20",
    "above_ma20_ratio",
    "score",
    "source",
)

_MAX_SECTOR_SIGNALS_PER_DIRECTION = 3
_MAX_EVIDENCE_TEXT_ITEMS = 8
_MAX_TRAILING_TARGETS = 5
_VERIFIED_SECTOR_DEDUPE_STATUSES = frozenset({
    "checked_unique",
    "deduped_representative",
})

_PSY12_AUDIT_SCALAR_FIELDS = (
    "schema_version",
    "mode",
    "status",
    "reason",
    "as_of_date",
    "required_days",
    "valid_days",
    "stored_complete_days",
    "recomputable_days",
    "complete_days",
    "missing_days",
    "mismatch_days",
    "recalculation_consistency_rate",
    "affects_production",
    "promotion_eligible",
    "promotion_requires_new_authorization",
)

_HISTORICAL_IDENTITY_FIELDS = (
    "strategy",
    "version",
    "source_pool",
    "entry_mode",
    "intended_horizon",
    "research_tier",
)

_POOL_STRATEGY_IDENTITIES = {
    "picks_fusion": "daily_fusion",
    "picks_pure": "daily_pure",
    "h4_t3_pool": "h4_t3",
    "next_day_boom": "next_day_boom",
    "luojie_pool": "luojie_pool",
    "observation_watchlist": "observation_gate",
}

_VALID_SIMULATION_ENTRY_MODES = frozenset({
    "immediate_close",
    "delay1_open",
})

_VALID_SCORECARD_ROLES = frozenset({
    "formal",
    "baseline",
    "research",
    "diagnostic",
})

_HISTORICAL_HORIZONS = ("t1", "t3", "t5")
_HISTORICAL_MATURITY_GATES = {
    "required_mature_samples": 100,
    "required_active_dates": 20,
    "required_calendar_months": 2,
}

_HISTORICAL_METRIC_FIELDS = (
    "n",
    "date_start",
    "date_end",
    "mean",
    "median",
    "win_rate",
    "excess_mean",
    "mean_mfe",
    "mean_mae",
    "max_drawdown",
)


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return str(value)
    return ""


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if isinstance(value, int):
        return value
    return number


def _positive_price(value):
    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    return number


def _strict_native(value):
    """Copy only strict JSON-native values, replacing non-finite numbers."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        return _finite_number(value)
    if isinstance(value, Mapping):
        return {
            key: _strict_native(item)
            for key, item in value.items()
            if isinstance(key, str)
        }
    if isinstance(value, (list, tuple)):
        return [_strict_native(item) for item in value]
    return None


def _compact_native_fields(value, allowed_fields):
    source = _as_mapping(value)
    result = {}
    for field in allowed_fields:
        if field not in source:
            continue
        raw_value = source.get(field)
        if raw_value is None or isinstance(raw_value, (str, bool)):
            result[field] = raw_value
            continue
        number = _finite_number(raw_value)
        if number is not None:
            result[field] = number
    return result


def _compact_psy12_shadow_audit(value):
    source = _as_mapping(value)
    result = _compact_native_fields(source, _PSY12_AUDIT_SCALAR_FIELDS)
    if isinstance(source.get("summary"), Mapping):
        result["summary"] = _compact_native_fields(
            source.get("summary"),
            (
                "average_delta",
                "maximum_absolute_delta",
                "label_change_count",
            ),
        )
    if isinstance(source.get("correlations"), Mapping):
        result["correlations"] = _compact_native_fields(
            source.get("correlations"),
            ("breadth", "index"),
        )

    changes = source.get("hypothetical_changes")
    if isinstance(changes, (list, tuple)):
        allowed_changes = frozenset({
            "market_temperature_score",
            "market_temperature_label",
            "decision_gate_cold_market_threshold",
        })
        projected_changes = []
        for raw_change in changes[-20:]:
            raw_change = _as_mapping(raw_change)
            item = _compact_native_fields(
                raw_change,
                ("date", "formal_score", "shadow_score"),
            )
            raw_labels = raw_change.get("changes")
            if isinstance(raw_labels, (list, tuple)):
                labels = []
                for raw_label in raw_labels:
                    label = _as_text(raw_label)
                    if label in allowed_changes and label not in labels:
                        labels.append(label)
                        if len(labels) >= len(allowed_changes):
                            break
                item["changes"] = labels
            projected_changes.append(item)
        result["hypothetical_changes"] = projected_changes

    daily = source.get("daily")
    if isinstance(daily, (list, tuple)):
        projected_daily = []
        for raw_day in daily[-20:]:
            raw_day = _as_mapping(raw_day)
            day = _compact_native_fields(
                raw_day,
                (
                    "date",
                    "formal_score",
                    "shadow_score",
                    "delta",
                    "formal_label",
                    "shadow_label",
                    "label_changed",
                    "psy12_score",
                    "recalculation_match",
                    "stored_complete",
                    "recomputable",
                    "status",
                ),
            )
            raw_window = raw_day.get("psy12_window")
            if isinstance(raw_window, (list, tuple)):
                day["psy12_window"] = [
                    text
                    for text in (
                        _as_text(item) for item in raw_window[:2]
                    )
                    if text
                ]
            if isinstance(raw_day.get("components"), Mapping):
                day["components"] = _compact_native_fields(
                    raw_day.get("components"),
                    _FORMAL_MARKET_COMPONENTS,
                )
            projected_daily.append(day)
        result["daily"] = projected_daily
    return result


def _project_psy12_shadow_contract(daily_data):
    """Expose an HTML-only, non-promoting policy for legacy shadow rows."""
    shadow = _as_mapping(daily_data.get("psy12_shadow"))
    contract = {
        "schema_version": 1,
        "mode": "shadow",
        "affects_production": False,
        "promotion_eligible": False,
        "promotion_requires_new_authorization": True,
        "source": "daily.psy12_shadow + fixed shadow policy",
    }
    if not shadow:
        contract.update({
            "status": "missing",
            "reason": "psy12_shadow_not_provided",
            "legacy_boundary_applied": False,
        })
        return contract
    if (
        shadow.get("schema_version") != 1
        or shadow.get("mode") != "shadow"
        or shadow.get("affects_production") is not False
    ):
        contract.update({
            "status": "invalid",
            "reason": "shadow_isolation_contract_invalid",
            "legacy_boundary_applied": False,
        })
        return contract
    if (
        shadow.get("promotion_eligible") is True
        or shadow.get("promotion_requires_new_authorization") is False
    ):
        contract.update({
            "status": "invalid",
            "reason": "promotion_boundary_conflict",
            "legacy_boundary_applied": False,
        })
        return contract
    legacy = (
        "promotion_eligible" not in shadow
        or "promotion_requires_new_authorization" not in shadow
    )
    if not legacy and (
        shadow.get("promotion_eligible") is not False
        or shadow.get("promotion_requires_new_authorization") is not True
    ):
        contract.update({
            "status": "invalid",
            "reason": "promotion_boundary_invalid",
            "legacy_boundary_applied": False,
        })
        return contract
    contract.update({
        "status": "available",
        "reason": None,
        "legacy_boundary_applied": legacy,
    })
    return contract


def _pool_candidates(pool):
    if isinstance(pool, list):
        return pool
    pool = _as_mapping(pool)
    for key in ("candidates", "picks", "items", "rows"):
        candidates = pool.get(key)
        if isinstance(candidates, list):
            return candidates
    return []


def _find_serialized_candidate(daily_data, row):
    ref = _as_mapping(row.get("ref"))
    pool_name = _as_text(ref.get("pool"))
    code = _as_text(ref.get("code")) or _as_text(row.get("code"))
    if not pool_name or not code:
        return None, pool_name
    for candidate in _pool_candidates(daily_data.get(pool_name)):
        candidate = _as_mapping(candidate)
        if _as_text(candidate.get("code")) == code:
            return candidate, pool_name
    return None, pool_name


def _find_original_candidate(formal_report, row):
    candidate, _ = _find_serialized_candidate(formal_report, row)
    return candidate


def _missing_section(source, reason="evidence_not_projected"):
    return {
        "status": "missing",
        "source": source,
        "reason": reason,
    }


def _build_summary(row, raw, view_name, report_date):
    formal_contract = _as_mapping(row.get("formal_decision_contract"))
    decision = _as_mapping(raw.get("decision_engine_v1")) if raw else {}
    code = _as_text(row.get("code"))
    summary = {
        "status": "available" if code else "missing",
        "source": "workspace.views.{}".format(view_name),
        "as_of": report_date,
        "code": code,
        "name": _as_text(row.get("name")),
        "sector": _as_text(row.get("sector")),
        "formal_action": _as_text(formal_contract.get("action")) or None,
        "formal_action_reason": (
            _as_text(formal_contract.get("action_reason")) or None
        ),
        "decision_code": _as_text(decision.get("decision_code")) or None,
    }
    if not code:
        summary["reason"] = "workspace_code_missing"
    return summary


def _decision_component(decision, name):
    component = _as_mapping(decision.get(name))
    reasons = component.get("reasons")
    projected_reasons = [
        text
        for text in (_as_text(item) for item in reasons or [])
        if text
    ][:_MAX_EVIDENCE_TEXT_ITEMS] if isinstance(
        reasons,
        (list, tuple),
    ) else []
    return {
        "score": _finite_number(component.get("score")),
        "reasons": projected_reasons,
        "reasons_truncated": bool(
            isinstance(reasons, (list, tuple))
            and len(reasons) > len(projected_reasons)
        ),
    }


def _build_decision_score(raw, pool_name):
    source = "{}.decision_engine_v1".format(pool_name or "raw_candidate")
    if raw is None:
        section = _missing_section(source, "raw_candidate_not_found")
        section.update({
            "score": None,
            "decision_code": None,
            "components": {
                name: {"score": None, "reasons": []}
                for name in ("structure", "position", "sentiment")
            },
        })
        return section

    decision = _as_mapping(raw.get("decision_engine_v1"))
    score = None
    for key in ("total_score", "score", "final_score"):
        score = _finite_number(decision.get(key))
        if score is not None:
            break
    components = {
        name: _decision_component(decision, name)
        for name in ("structure", "position", "sentiment")
    }
    has_component_score = any(
        component["score"] is not None
        for component in components.values()
    )
    status = "available" if score is not None else (
        "partial" if has_component_score else "missing"
    )
    section = {
        "status": status,
        "source": source,
        "score": score,
        "decision_code": _as_text(decision.get("decision_code")) or None,
        "components": components,
    }
    if status == "missing":
        section["reason"] = "decision_score_not_provided"
    elif status == "partial":
        section["reason"] = "total_score_not_provided"
    return section


def _build_rank_evidence(row, view_name):
    view_rank = _finite_number(row.get("view_rank"))
    opportunity_score = _finite_number(row.get("opportunity_score"))
    rank_trace = _compact_native_fields(
        row.get("rank_trace"),
        _RANK_TRACE_FIELDS,
    )
    status = "available" if (
        view_rank is not None or opportunity_score is not None or rank_trace
    ) else "missing"
    section = {
        "status": status,
        "source": "workspace.views.{}.rank_evidence".format(view_name),
        "view_rank": view_rank,
        "opportunity_score": opportunity_score,
        "rank_trace": rank_trace,
        "scope": "current_view_order_only",
        "note": "仅用于当前池内排序",
    }
    if status == "missing":
        section["reason"] = "rank_evidence_not_provided"
    return section


def _latest_positive_price(values):
    if values is None:
        return None
    try:
        length = len(values)
    except (TypeError, ValueError):
        return None
    if length == 0:
        return None
    try:
        return _positive_price(values[length - 1])
    except (IndexError, KeyError, TypeError):
        return None


def _resolve_current_price(row, raw, original_raw):
    sources = (
        (row.get("current_price"), "workspace.current_price"),
        (_as_mapping(raw).get("current_price"), "serialized.current_price"),
        (
            _as_mapping(_as_mapping(raw).get("best_buy_point")).get(
                "current_price"
            ),
            "serialized.best_buy_point.current_price",
        ),
        (
            _as_mapping(original_raw).get("current_price"),
            "formal_report.current_price",
        ),
        (
            _as_mapping(
                _as_mapping(original_raw).get("best_buy_point")
            ).get("current_price"),
            "formal_report.best_buy_point.current_price",
        ),
    )
    for raw_value, source in sources:
        value = _positive_price(raw_value)
        if value is not None:
            return value, source
    for candidate, source in (
        (raw, "serialized.closes"),
        (original_raw, "formal_report.closes"),
    ):
        value = _latest_positive_price(_as_mapping(candidate).get("closes"))
        if value is not None:
            return value, source
    return None, None


def _formal_contract_price(contract, diagnostics, field, audit_reasons):
    diagnostic = _as_text(diagnostics.get(field))
    if diagnostic and diagnostic != "verified":
        audit_reasons[field] = diagnostic
        return None
    if field not in contract:
        return None
    value = _positive_price(contract.get(field))
    if value is None:
        audit_reasons[field] = "invalid"
    return value


def _project_trailing_targets(raw):
    targets = _as_mapping(raw).get("trailing_targets")
    if not isinstance(targets, (list, tuple)):
        targets = []
    projected = []
    valid_count = 0
    for index, target in enumerate(targets):
        if isinstance(target, Mapping):
            price = _positive_price(target.get("price"))
            if price is None:
                continue
            valid_count += 1
            if len(projected) >= _MAX_TRAILING_TARGETS:
                continue
            item = {
                "price": price,
                "source": "trailing_targets[{}]".format(index),
            }
            pct = _finite_number(target.get("pct"))
            if pct is not None:
                item["pct"] = pct
            label = _as_text(target.get("label"))
            if label:
                item["label"] = label
            projected.append(item)
            continue
        price = _positive_price(target)
        if price is not None:
            valid_count += 1
            if len(projected) >= _MAX_TRAILING_TARGETS:
                continue
            projected.append({
                "price": price,
                "source": "trailing_targets[{}]".format(index),
            })
    omitted_count = max(0, valid_count - len(projected))
    return projected, {
        "max_visible": _MAX_TRAILING_TARGETS,
        "input_count": len(targets),
        "valid_count": valid_count,
        "visible_count": len(projected),
        "omitted_count": omitted_count,
        "truncated": omitted_count > 0,
        "reason": "display_payload_limit" if omitted_count else None,
    }


def _build_price_evidence(row, raw, original_raw, report_date):
    contract = _as_mapping(row.get("formal_decision_contract"))
    diagnostics = _as_mapping(
        row.get("formal_decision_contract_diagnostics")
    )
    audit_reasons = {}
    current_price, current_source = _resolve_current_price(
        row,
        raw,
        original_raw,
    )
    reference_price = _formal_contract_price(
        contract,
        diagnostics,
        "reference_price",
        audit_reasons,
    )
    pressure_price = _formal_contract_price(
        contract,
        diagnostics,
        "pressure_price",
        audit_reasons,
    )
    invalidation_price = _formal_contract_price(
        contract,
        diagnostics,
        "invalidation_price",
        audit_reasons,
    )
    invalidation_source = (
        "workspace.formal_decision_contract.invalidation_price"
        if invalidation_price is not None else None
    )
    invalidation_declared = "invalidation_price" in contract
    invalidation_diagnostic = _as_text(
        diagnostics.get("invalidation_price")
    )
    price_raw = original_raw if original_raw is not None else raw
    if (
        invalidation_price is None
        and not invalidation_declared
        and not invalidation_diagnostic
    ):
        stop_loss = _positive_price(_as_mapping(price_raw).get("stop_loss"))
        if stop_loss is not None:
            invalidation_price = stop_loss
            invalidation_source = (
                "formal_report.stop_loss"
                if original_raw is not None else "serialized.stop_loss"
            )

    trailing_targets, trailing_targets_contract = _project_trailing_targets(
        price_raw
    )
    missing_fields = []
    for name, value in (
        ("current_price", current_price),
        ("reference_price", reference_price),
        ("pressure_price", pressure_price),
        ("invalidation_price", invalidation_price),
        ("trailing_targets", trailing_targets),
    ):
        if value is None or value == []:
            missing_fields.append(name)

    available_count = 5 - len(missing_fields)
    if audit_reasons:
        status = "conflict"
    elif available_count == 0:
        status = "missing"
    elif missing_fields:
        status = "partial"
    else:
        status = "available"
    section = {
        "status": status,
        "source": "workspace.formal_decision_contract + candidate prices",
        "as_of": report_date,
        "current_price": current_price,
        "current_price_source": current_source,
        "reference_price": reference_price,
        "reference_price_source": (
            "workspace.formal_decision_contract.reference_price"
            if reference_price is not None else None
        ),
        "pressure_price": pressure_price,
        "pressure_price_source": (
            "workspace.formal_decision_contract.pressure_price"
            if pressure_price is not None else None
        ),
        "invalidation_price": invalidation_price,
        "invalidation_price_source": invalidation_source,
        "trailing_targets": trailing_targets,
        "trailing_targets_contract": trailing_targets_contract,
        "missing_fields": missing_fields,
        "audit_reasons": audit_reasons,
    }
    if status == "missing":
        section["reason"] = "verified_prices_not_provided"
    elif status == "conflict":
        section["reason"] = "formal_price_conflict_or_invalid"
    return section


def _percent(value):
    number = _finite_number(value)
    return round(number, 4) if number is not None else None


def _chart_series(source, field):
    """Return only finite values for compact chart metadata inspection."""
    values = _field(source, field, None)
    if not isinstance(values, (list, tuple)):
        return []
    result = []
    for value in values:
        number = _finite_number(value)
        if number is not None:
            result.append(number)
    return result


def _chart_macd_metadata(raw, original_raw, report_date):
    """Describe real MACD evidence without copying the histogram array."""
    for source, source_name in (
        (raw, "serialized.macd_hist"),
        (original_raw, "formal_report.macd_hist"),
    ):
        if source is None or "macd_hist" not in source:
            continue
        values = _chart_series(source, "macd_hist")
        # A zero-only array is the legacy placeholder emitted when no real
        # histogram was available.  It must be treated as missing evidence.
        has_real_value = any(abs(value) > 1e-9 for value in values)
        return {
            "status": "available" if has_real_value else "missing",
            "source": source_name,
            "as_of": report_date,
            "value_count": len(values),
            "reason": "" if has_real_value else "macd_hist_not_provided",
        }
    return {
        "status": "missing",
        "source": "candidate.macd_hist",
        "as_of": report_date,
        "value_count": 0,
        "reason": "macd_hist_not_provided",
    }


def _chart_pivot_metadata(raw, original_raw, row, report_date):
    """Describe available ZG/ZD lines while keeping the raw pivots out."""
    values = {}
    sources = {}
    for source, source_name in (
        (raw, "serialized"),
        (original_raw, "formal_report"),
        (row, "workspace"),
    ):
        if source is None:
            continue
        pivots = _as_mapping(_field(source, "pivots", None))
        for key, direct_key in (("ZG", "pivot_zg"), ("ZD", "pivot_zd")):
            if key in values:
                continue
            direct = _positive_price(_field(source, direct_key, None))
            nested = _positive_price(pivots.get(key))
            value = direct if direct is not None else nested
            if value is not None:
                values[key] = value
                sources[key] = "{}.{}".format(source_name, direct_key if direct is not None else "pivots." + key)
    available = [key for key in ("ZG", "ZD") if key in values]
    if len(available) == 2:
        status = "available"
    elif available:
        status = "partial"
    else:
        status = "missing"
    metadata = {
        "status": status,
        "source": "serialized/formal pivot fields",
        "as_of": report_date,
        "available": available,
        "ZG": values.get("ZG"),
        "ZD": values.get("ZD"),
        "field_sources": sources,
    }
    if status == "missing":
        metadata["reason"] = "pivot_lines_not_provided"
    return metadata


def _chart_price_metadata(price_evidence, report_date):
    """Expose price-line availability without inventing numeric boundaries."""
    fields = (
        "current_price",
        "reference_price",
        "pressure_price",
        "invalidation_price",
    )
    scalar_available = [
        field
        for field in fields
        if _positive_price(price_evidence.get(field)) is not None
    ]
    available = list(scalar_available)
    trailing_targets = [
        target
        for target in price_evidence.get("trailing_targets", [])
        if isinstance(target, Mapping)
        and _positive_price(target.get("price")) is not None
    ]
    if trailing_targets:
        available.append("trailing_targets")
    if len(scalar_available) == len(fields):
        status = "available"
    elif available:
        status = "partial"
    else:
        status = "missing"
    field_sources = {
        field: price_evidence.get(field + "_source")
        for field in available
        if field in fields
    }
    if trailing_targets:
        field_sources["trailing_targets"] = [
            target.get("source") for target in trailing_targets
        ]
    metadata = {
        "status": status,
        "source": "price_evidence",
        "as_of": report_date,
        "available": available,
        "field_sources": field_sources,
    }
    if status == "missing":
        metadata["reason"] = "real_price_boundaries_incomplete"
    return metadata


def _chart_annotations_metadata(raw, original_raw, report_date):
    """Summarize annotation counts; do not copy mark arrays to evidence."""
    for source, source_name in (
        (raw, "serialized.chart_annotations"),
        (original_raw, "formal_report.chart_annotations"),
    ):
        annotations = _as_mapping(_field(source, "chart_annotations", None))
        if not annotations:
            continue
        counts = {
            "mark_lines": len(annotations.get("markLines") or []) if isinstance(annotations.get("markLines"), (list, tuple)) else 0,
            "mark_points": len(annotations.get("markPoints") or []) if isinstance(annotations.get("markPoints"), (list, tuple)) else 0,
            "labels": len(annotations.get("labels") or []) if isinstance(annotations.get("labels"), (list, tuple)) else 0,
        }
        available = any(counts.values())
        return {
            "status": "available" if available else "missing",
            "source": source_name,
            "as_of": report_date,
            **counts,
            "reason": "" if available else "chart_annotations_not_provided",
        }
    return {
        "status": "missing",
        "source": "candidate.chart_annotations",
        "as_of": report_date,
        "mark_lines": 0,
        "mark_points": 0,
        "labels": 0,
        "reason": "chart_annotations_not_provided",
    }


def _build_chart_evidence_metadata(row, raw, original_raw, price_evidence, report_date):
    """Build compact, read-only chart provenance for the HTML evidence plane."""
    macd = _chart_macd_metadata(raw, original_raw, report_date)
    prices = _chart_price_metadata(price_evidence, report_date)
    pivots = _chart_pivot_metadata(raw, original_raw, row, report_date)
    annotations = _chart_annotations_metadata(raw, original_raw, report_date)
    statuses = (macd["status"], prices["status"], pivots["status"], annotations["status"])
    status = "available" if all(value == "available" for value in statuses) else (
        "partial" if any(value in {"available", "partial"} for value in statuses) else "missing"
    )
    metadata = {
        "status": status,
        "source": "serialized/formal chart evidence metadata",
        "as_of": report_date,
        "macd": macd,
        "prices": prices,
        "pivots": pivots,
        "annotations": annotations,
    }
    if status == "missing":
        metadata["reason"] = "chart_evidence_not_provided"
    return metadata


def _build_display_derived(price_evidence, chart_evidence=None):
    current = price_evidence.get("current_price")
    reference = price_evidence.get("reference_price")
    pressure = price_evidence.get("pressure_price")
    invalidation = price_evidence.get("invalidation_price")

    distance = None
    if current is not None and reference is not None:
        distance = _percent((current - reference) / reference * 100.0)
    upside = None
    if current is not None and pressure is not None and pressure >= current:
        upside = _percent((pressure - current) / current * 100.0)
    downside = None
    if (
        current is not None
        and invalidation is not None
        and invalidation <= current
    ):
        downside = _percent((current - invalidation) / current * 100.0)
    risk_reward = None
    if upside is not None and downside is not None and downside > 0:
        risk_reward = _percent(upside / downside)

    values = (distance, upside, downside, risk_reward)
    status = "available" if all(value is not None for value in values) else (
        "partial" if any(value is not None for value in values) else "missing"
    )
    section = {
        "status": status,
        "source": "display calculation from price_evidence",
        "distance_from_reference_pct": distance,
        "upside_to_pressure_pct": upside,
        "downside_to_invalidation_pct": downside,
        "risk_reward_ratio": risk_reward,
        "chart_evidence": chart_evidence or {
            "status": "missing",
            "source": "display_derived.chart_evidence",
            "reason": "chart_evidence_not_provided",
        },
    }
    if status != "available":
        section["reason"] = "real_price_boundaries_incomplete"
    return section


def _declared_texts(*values):
    result = []
    for value in values:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            text = _as_text(item)
            if text and text not in result:
                result.append(text)
                if len(result) >= _MAX_EVIDENCE_TEXT_ITEMS:
                    return result
    return result


def _condition_block(items, empty_text, source):
    return {
        "status": "available" if items else "missing",
        "source": source,
        "items": items,
        "empty_text": "" if items else empty_text,
    }


def _build_risk_and_next(row, raw, original_raw, price_evidence):
    source_raw = _as_mapping(
        original_raw if original_raw is not None else raw
    )
    risk_labels = _declared_texts(
        row.get("risk_flags"),
        source_raw.get("risk_flags"),
        source_raw.get("risk_reasons"),
    )
    next_confirmation = _declared_texts(
        source_raw.get("upgrade_conditions"),
        source_raw.get("next_day_conditions"),
        source_raw.get("confirmation_conditions"),
        source_raw.get("next_confirmation"),
    )
    keep_conditions = _declared_texts(source_raw.get("keep_conditions"))
    retest_conditions = _declared_texts(
        source_raw.get("retest_conditions")
    )
    cancel_conditions = _declared_texts(
        source_raw.get("cancel_conditions")
    )
    invalidation_conditions = _declared_texts(
        source_raw.get("invalidation_conditions")
    )
    conditions = {
        "next_confirmation": _condition_block(
            next_confirmation,
            "当前策略未声明下一确认条件",
            "candidate.upgrade/next_day/confirmation_conditions",
        ),
        "keep_conditions": _condition_block(
            keep_conditions,
            "当前策略未声明继续保持条件",
            "candidate.keep_conditions",
        ),
        "retest_conditions": _condition_block(
            retest_conditions,
            "当前策略未声明等待回踩条件",
            "candidate.retest_conditions",
        ),
        "cancel_conditions": _condition_block(
            cancel_conditions,
            "当前策略未声明取消或降级条件",
            "candidate.cancel_conditions",
        ),
        "invalidation_conditions": _condition_block(
            invalidation_conditions,
            "当前策略未声明结构失效条件",
            "candidate.invalidation_conditions",
        ),
    }
    has_condition = any(block["items"] for block in conditions.values())
    status = "available" if (
        risk_labels
        or has_condition
        or price_evidence.get("invalidation_price") is not None
    ) else "missing"
    section = {
        "status": status,
        "source": "workspace risk flags + declared candidate conditions",
        "risk_labels": risk_labels,
        "invalidation_price": price_evidence.get("invalidation_price"),
        **conditions,
    }
    if status == "missing":
        section["reason"] = "strategy_risk_and_conditions_not_declared"
    return section


_MISSING = object()

# Keep this whitelist in sync with ``sublevel_confirm``.  The serialized
# confirmation evidence contains the result of the freshness/recommendability
# checks, whereas ``buy_points_30min`` is only a contextual fallback and does
# not carry enough provenance to authorize a promotion.
_RECOMMENDABLE_30M_BUY_POINTS = frozenset({
    "二买",
    "二买候选",
    "三买",
    "三买候选",
})


def _field(source, key, default=None):
    """Read a field from a serialized mapping or a ChanResult-like object."""
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _declared_value(sources, keys):
    """Return the first non-empty declaration without deriving a value."""
    for source in sources:
        if source is None:
            continue
        for key in keys:
            value = _field(source, key, _MISSING)
            if value is _MISSING or value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, tuple, dict)) and not value:
                continue
            return value
    return None


def _declared_bool(sources, keys):
    for source in sources:
        if source is None:
            continue
        for key in keys:
            value = _field(source, key, _MISSING)
            if value is _MISSING or not isinstance(value, bool):
                continue
            return value
    return None


def _declared_number(sources, keys):
    for source in sources:
        if source is None:
            continue
        for key in keys:
            value = _field(source, key, _MISSING)
            if value is _MISSING:
                continue
            number = _finite_number(value)
            if number is not None:
                return number
    return None


def _declared_text_list(sources, keys):
    for source in sources:
        if source is None:
            continue
        for key in keys:
            value = _field(source, key, _MISSING)
            if value is _MISSING:
                continue
            texts = _declared_texts(value)
            if texts:
                return texts
    return []


def _best_buy_point_sources(raw, original_raw, row):
    sources = []
    for parent in (raw, original_raw, row):
        point = _field(parent, "best_buy_point", None)
        if isinstance(point, Mapping):
            sources.append(point)
    return sources


def _project_pivots(sources):
    """Copy only a compact serialized pivot summary, never raw pivot objects."""
    for source in sources:
        pivots = _field(source, "pivots", None)
        if not isinstance(pivots, Mapping):
            continue
        result = {}
        for key in ("ZG", "ZD", "count"):
            value = pivots.get(key)
            if key == "count":
                number = _finite_number(value)
                if number is not None and number >= 0:
                    result[key] = int(number)
            else:
                number = _finite_number(value)
                if number is not None:
                    result[key] = number
        if result:
            return result
    return None


def _project_daily_structure(row, raw, original_raw, report_date):
    """Project explicit daily structure facts without recomputing indicators."""
    sources = (raw, original_raw, row)
    buy_point_sources = _best_buy_point_sources(raw, original_raw, row)
    bp_and_sources = tuple(buy_point_sources) + tuple(
        source for source in sources if source is not None
    )

    data_status = _declared_value(sources, ("data_status",))
    data_status = data_status if isinstance(data_status, Mapping) else {}
    health = _as_text(data_status.get("daily")) or None
    latest_date = _as_text(data_status.get("latest_date")) or None
    stale = data_status.get("stale") is True
    if (
        report_date
        and latest_date
        and latest_date != report_date
        and health in {"verified", "available", "fresh"}
    ):
        stale = True
        health = "stale"

    trend = _as_text(_declared_value(sources, ("trend_type", "trend"))) or None
    signal = _as_text(
        _declared_value(bp_and_sources, ("signal", "type", "signal_type"))
    ) or None
    summary = _as_text(
        _declared_value(
            bp_and_sources,
            ("summary", "reason", "primary_reason", "startup_reason"),
        )
    ) or None
    stage = _as_text(
        _declared_value(
            bp_and_sources,
            ("stage", "trend_stage", "daily_startup_label"),
        )
    ) or None
    signal_date = _as_text(
        _declared_value(
            bp_and_sources,
            ("signal_date", "date", "startup_date"),
        )
    ) or None
    signal_age_days = _declared_number(
        bp_and_sources,
        ("signal_age_days", "startup_age_days"),
    )
    startup_grade = _as_text(
        _declared_value(bp_and_sources, ("daily_startup_grade",))
    ) or None
    startup_label = _as_text(
        _declared_value(bp_and_sources, ("daily_startup_label",))
    ) or None
    startup_warning = _as_text(
        _declared_value(bp_and_sources, ("daily_startup_warning",))
    ) or None
    startup_signals = _declared_text_list(
        bp_and_sources,
        ("startup_signals",),
    )

    # MA values are copied only when a source explicitly supplied them.  In
    # particular, do not calculate MA5/10/20 from the serialized close array.
    ma_sources = []
    for source in sources:
        nested = _as_mapping(_field(source, "ma"))
        if nested:
            ma_sources.append(nested)
        dma = _as_mapping(_field(source, "gf_dma_health"))
        nested_dma = _as_mapping(dma.get("ma"))
        if nested_dma:
            ma_sources.append(nested_dma)
        ma_sources.append(source)
    ma_values = {
        key: _declared_number(ma_sources, (key,))
        for key in ("ma5", "ma10", "ma20", "ma50", "ma100", "ma200")
    }
    ma_bullish = _declared_bool(sources, ("ma_bullish",))
    macd = _as_text(
        _declared_value(
            sources,
            ("macd_status", "macd_state", "macd"),
        )
    ) or None
    pivots = _project_pivots(sources)

    has_structure = any(
        value is not None
        for value in (
            trend,
            signal,
            summary,
            stage,
            signal_date,
            startup_grade,
            startup_label,
            macd,
            pivots,
        )
    ) or bool(startup_signals) or any(value is not None for value in ma_values.values())
    if stale:
        status = "stale"
        reason = "daily_latest_date_mismatch" if latest_date else "daily_data_stale"
    elif health in {"missing", "unavailable", "error"}:
        status = "missing"
        reason = "daily_data_not_verified"
    elif has_structure and health in {"verified", "available", "fresh"}:
        status = "available"
        reason = None
    elif has_structure:
        status = "partial"
        reason = "daily_data_status_not_declared"
    else:
        status = "missing"
        reason = "daily_structure_not_projected"

    section = {
        "status": status,
        "source": "serialized daily candidate fields",
        "as_of": report_date,
        "trend": trend,
        "stage": stage,
        "signal": signal,
        "summary": summary,
        "signal_date": signal_date,
        "signal_age_days": signal_age_days,
        "health": health,
        "latest_date": latest_date,
        "startup_grade": startup_grade,
        "startup_label": startup_label,
        "startup_warning": startup_warning,
        "startup_signals": startup_signals,
        **ma_values,
        "ma_bullish": ma_bullish,
        "macd": macd,
        "pivots": pivots,
    }
    if reason:
        section["reason"] = reason
    return section


def _normalize_30m_interval(value):
    text = _as_text(value).lower().replace(" ", "")
    if text in {"30m", "30min", "30minute", "30分钟", "30分钟线"}:
        return "30m"
    return None


def _date_prefix(value):
    return _strict_date_value(value) or ""


def _strict_date_value(value):
    """Return a valid ISO trade-date prefix for a date/timestamp value."""
    text = _as_text(value)
    if not text or len(text) < 10:
        return None
    prefix = text[:10]
    if (
        len(prefix) != 10
        or prefix[4] != "-"
        or prefix[7] != "-"
    ):
        return None
    try:
        parsed_date = _calendar_date.fromisoformat(prefix)
    except ValueError:
        return None
    if len(text) == 10:
        return parsed_date.isoformat() if parsed_date.isoformat() == prefix else None
    # Timestamps are accepted for as_of/latest_ts, but their suffix must be
    # a real ISO timestamp.  Python 3.9 does not parse a trailing Z directly.
    if text[10] not in {"T", " "}:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = _calendar_datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return prefix if parsed.date().isoformat() == prefix else None


def _validate_30m_freshness_dates(input_evidence, report_date):
    """Validate every declared 30m date and align it to the report date."""
    input_evidence = _as_mapping(input_evidence)
    expected = _strict_date_value(report_date)
    if expected is None:
        return "invalid"
    declared = False
    for field in ("latest_date", "latest_ts", "as_of"):
        if field not in input_evidence:
            continue
        declared = True
        value = input_evidence.get(field)
        if not _as_text(value):
            return "invalid"
        normalized = _strict_date_value(value)
        if normalized is None:
            return "invalid"
        if normalized != expected:
            return "mismatch"
    return "ok" if declared else "missing"


def _find_30m_input_evidence(raw, original_raw, buy_point_sources):
    for source in (raw, original_raw):
        evidence = _field(source, "strategy_input_evidence", None)
        if isinstance(evidence, Mapping) and evidence:
            return evidence
    for source in (original_raw, raw):
        result = _field(source, "result_30min", None)
        evidence = _field(result, "strategy_input_evidence", None)
        if isinstance(evidence, Mapping) and evidence:
            return evidence
    for source in buy_point_sources:
        evidence = source.get("strategy_input_evidence")
        if isinstance(evidence, Mapping) and evidence:
            return evidence
    return {}


def _find_confirmation_evidence(raw, original_raw, buy_point_sources):
    for source in buy_point_sources + [raw, original_raw]:
        evidence = _field(source, "confirmation_evidence", None)
        if isinstance(evidence, Mapping) and evidence:
            return evidence
    return {}


def _latest_30m_buy_point_type(raw, original_raw):
    for source in (raw, original_raw):
        points = _field(source, "buy_points_30min", None)
        if not isinstance(points, (list, tuple)):
            continue
        for point in reversed(points):
            point_type = _as_text(_field(point, "type", None))
            if point_type:
                return point_type
    return None


def _project_sublevel_30m(row, raw, original_raw, report_date):
    """Project fresh 30m confirmation facts, never the minute arrays."""
    buy_point_sources = _best_buy_point_sources(raw, original_raw, row)
    input_evidence = _find_30m_input_evidence(
        raw,
        original_raw,
        buy_point_sources,
    )
    confirmation = _find_confirmation_evidence(
        raw,
        original_raw,
        buy_point_sources,
    )

    interval = _normalize_30m_interval(input_evidence.get("interval"))
    input_status = _as_text(input_evidence.get("status")).lower() or None
    latest_date = _as_text(input_evidence.get("latest_date")) or None
    latest_ts = _as_text(input_evidence.get("latest_ts")) or None
    input_as_of = _as_text(input_evidence.get("as_of")) or None
    freshness_date = _date_prefix(latest_date or latest_ts or input_as_of)
    freshness_date_state = _validate_30m_freshness_dates(
        input_evidence,
        report_date,
    )
    stale_flag = input_evidence.get("stale") is True
    stale_status = input_status in {"stale", "expired", "unavailable", "error"}
    date_mismatch = freshness_date_state in {"invalid", "mismatch"}
    is_stale = stale_flag or stale_status or date_mismatch
    fresh_status = input_status in {"verified", "available", "intraday_available", "fresh"}
    fresh_input = bool(
        interval
        and fresh_status
        and freshness_date
        and freshness_date_state == "ok"
        and input_evidence.get("is_final") is True
        and not is_stale
    )

    ema_alignment = _declared_bool(
        (confirmation,),
        ("ema_bullish_alignment",),
    )
    close_above_ema5 = _declared_bool(
        (confirmation,),
        ("close_above_ema5",),
    )
    ema5_reclaim = _declared_bool((confirmation,), ("ema5_reclaim",))
    stop_fall = _declared_bool((confirmation,), ("stop_fall",))
    recovery_bundle_match = _declared_bool(
        (confirmation,),
        ("recovery_bundle_match",),
    )
    ema5_rising_bars = _declared_number(
        (confirmation,),
        ("ema5_rising_bars",),
    )
    recent_peak_drawdown_pct = _declared_number(
        (confirmation,),
        ("recent_peak_drawdown_pct",),
    )
    macd_state = _as_text(
        _declared_value(
            (confirmation, raw, original_raw),
            ("macd_hist_direction", "macd_state"),
        )
    ) or None
    declared_buy_point = _as_text(confirmation.get("buy_point")) or None
    contextual_buy_point = _latest_30m_buy_point_type(raw, original_raw)
    buy_point = declared_buy_point or contextual_buy_point
    decision_buy_point = (
        declared_buy_point
        if declared_buy_point in _RECOMMENDABLE_30M_BUY_POINTS
        else None
    )
    fresh_yang_pattern = _as_text(confirmation.get("fresh_yang_pattern")) or None
    confirmations = _declared_text_list(
        tuple(buy_point_sources) + (raw, original_raw),
        ("confirmations",),
    )
    confirmed_by = _as_text(
        _declared_value(
            tuple(buy_point_sources) + (raw, original_raw),
            ("confirmed_by",),
        )
    ) or None
    grade = _as_text(
        _declared_value(
            tuple(buy_point_sources) + (raw, original_raw),
            ("sublevel_confirm_grade",),
        )
    ) or None
    label = _as_text(
        _declared_value(
            tuple(buy_point_sources) + (raw, original_raw),
            ("sublevel_confirm_label",),
        )
    ) or None
    reason = _as_text(
        _declared_value(
            tuple(buy_point_sources) + (raw, original_raw),
            ("sublevel_confirm_reason",),
        )
    ) or None
    confirm_date = _as_text(
        _declared_value(
            tuple(buy_point_sources) + (raw, original_raw),
            ("confirm_date",),
        )
    ) or None
    confirm_age_days = _declared_number(
        tuple(buy_point_sources) + (raw, original_raw),
        ("confirm_age_days",),
    )

    independent_signal = bool(
        decision_buy_point
        or fresh_yang_pattern in {"two_yang_one_yin", "two_yang_two_yin"}
    )
    alignment_only = bool(
        not independent_signal
        and (ema_alignment is True or close_above_ema5 is True)
    )

    if not input_evidence or not interval:
        status = "missing"
        confirmation_status = "missing"
        reason = reason or "本期未提供可验证的30分钟输入证据"
    elif is_stale:
        status = "stale"
        confirmation_status = "stale"
        reason = reason or (
            "30分钟证据已过期，不能作为本期确认"
            if stale_flag or stale_status
            else "30分钟证据日期非法或与本期不一致，不能作为本期确认"
        )
    elif not fresh_input:
        status = "partial"
        confirmation_status = "unavailable"
        reason = reason or (
            "30分钟输入未标记正式收盘，不能作为本期确认"
            if input_evidence.get("is_final") is not True
            else "30分钟输入状态未核验，不能作为本期确认"
        )
    elif independent_signal:
        status = "available"
        confirmation_status = "confirmed"
        reason = reason or confirmed_by or "30分钟形成独立确认信号"
    elif alignment_only:
        status = "partial"
        confirmation_status = "alignment_only"
        reason = reason or "30分钟均线仍为多头排列，但未形成独立确认"
    else:
        status = "partial"
        confirmation_status = "unconfirmed"
        reason = reason or "30分钟未形成独立确认信号"

    section = {
        "status": status,
        "source": "30m strategy_input_evidence + confirmation_evidence",
        "as_of": input_as_of or latest_ts or latest_date or report_date,
        "interval": interval,
        "input_status": input_status,
        "latest_date": latest_date,
        "latest_ts": latest_ts,
        "bars": _declared_number((input_evidence,), ("bars",)),
        "stale": is_stale if input_evidence else None,
        "is_final": _declared_bool((input_evidence,), ("is_final",)),
        "latest_bar_at": latest_ts or latest_date,
        "confirmed": bool(confirmation_status == "confirmed" and fresh_input),
        "confirmation_status": confirmation_status,
        "grade": grade,
        "label": label,
        "reason": reason,
        "confirm_date": confirm_date,
        "confirm_age_days": confirm_age_days,
        "confirmations": confirmations,
        "confirmed_by": confirmed_by,
        "ema_alignment": (
            "EMA5 > EMA10" if ema_alignment is True
            else ("EMA5 <= EMA10" if ema_alignment is False else None)
        ),
        "close_above_ema5": close_above_ema5,
        "ema5_rising_bars": ema5_rising_bars,
        "ema5_reclaim": ema5_reclaim,
        "stop_fall": stop_fall,
        "macd_state": macd_state,
        "recent_peak_drawdown_pct": recent_peak_drawdown_pct,
        "buy_point": buy_point,
        "fresh_yang_pattern": fresh_yang_pattern,
        "recovery_bundle_match": recovery_bundle_match,
    }
    return section


def _positive_metric(value):
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _format_cn_amount(value):
    number = _finite_number(value)
    if number is None:
        return None
    absolute = abs(number)
    if absolute >= 100000000:
        suffix = "亿"
        scaled = number / 100000000.0
    elif absolute >= 10000:
        suffix = "万"
        scaled = number / 10000.0
    else:
        return "{:g}".format(number)
    text = "{:.2f}".format(scaled).rstrip("0").rstrip(".")
    return "{}{}".format(text, suffix)


def _positive_tail(values, count):
    try:
        length = len(values)
    except (TypeError, ValueError):
        return None
    if length < count:
        return None
    result = []
    for index in range(length - count, length):
        try:
            number = _positive_metric(values[index])
        except (IndexError, KeyError, TypeError):
            return None
        if number is None:
            return None
        result.append(number)
    return result


def _average(values):
    if not values:
        return None
    average = 0.0
    for index, value in enumerate(values, start=1):
        number = _finite_number(value)
        if number is None:
            return None
        average += (float(number) - average) / index
        if not math.isfinite(average):
            return None
    return round(average, 4)


def _verified_daily_source(source, report_date):
    source = _as_mapping(source)
    data_status = _as_mapping(source.get("data_status"))
    latest_date = _date_prefix(data_status.get("latest_date"))
    return bool(
        data_status.get("daily") == "verified"
        and data_status.get("stale") is False
        and data_status.get("is_final") is True
        and latest_date
        and (not report_date or latest_date == report_date)
    )


def _declared_date_is_current(value, report_date):
    raw_text = _as_text(value)
    if not raw_text:
        return True
    declared = _date_prefix(raw_text)
    return bool(declared and (not report_date or declared == report_date))


def _declared_dates_are_current(
    source,
    fields,
    report_date,
    require_one=False,
):
    source = _as_mapping(source)
    declared_count = 0
    for field in fields:
        if field not in source or not _as_text(source.get(field)):
            continue
        declared_count += 1
        if not _declared_date_is_current(source.get(field), report_date):
            return False
    return declared_count > 0 if require_one else True


def _dated_series_is_current(source, values, report_date):
    dates = source.get("dates") if isinstance(source, Mapping) else None
    if not isinstance(dates, (list, tuple)):
        return False
    try:
        if len(dates) != len(values) or not dates:
            return False
    except (TypeError, ValueError):
        return False
    normalized = [_date_prefix(value) for value in dates]
    if any(not value for value in normalized):
        return False
    if any(
        normalized[index] >= normalized[index + 1]
        for index in range(len(normalized) - 1)
    ):
        return False
    if report_date and (
        normalized[-1] != report_date
        or any(value > report_date for value in normalized)
    ):
        return False
    return True


def _pool_quality_is_current(row, raw, original_raw, report_date):
    pool_quality = _as_mapping(row.get("pool_quality"))
    if not _declared_dates_are_current(
        pool_quality,
        ("as_of", "date"),
        report_date,
    ):
        return False
    return any(
        _verified_daily_source(source, report_date)
        for source in (row, raw, original_raw)
    )


def _verified_volume_summary(raw, original_raw, report_date):
    for source_name, source in (
        ("formal_report", original_raw),
        ("serialized", raw),
    ):
        if not isinstance(source, Mapping):
            continue
        data_status = _as_mapping(source.get("data_status"))
        latest_date = _date_prefix(data_status.get("latest_date"))
        if not _verified_daily_source(source, report_date):
            continue
        values = source.get("volumes")
        if not _dated_series_is_current(source, values, report_date):
            continue
        latest = _positive_tail(values, 1)
        if latest is None:
            continue
        tail5 = _positive_tail(values, 5)
        tail20 = _positive_tail(values, 20)
        available = [latest[0], _average(tail5), _average(tail20)]
        status = "available" if all(
            value is not None for value in available
        ) else "partial"
        return {
            "status": status,
            "source": "candidate.volumes",
            "source_plane": source_name,
            "as_of": latest_date or report_date,
            "current": latest[0],
            "average_5": _average(tail5),
            "average_20": _average(tail20),
        }
    return {
        "status": "missing",
        "source": "candidate.volumes",
        "as_of": report_date,
        "current": None,
        "average_5": None,
        "average_20": None,
        "reason": "verified_final_volume_series_not_provided",
    }


def _explicit_volume_ratio(row, raw, original_raw, report_date):
    for source_name, source in (
        ("formal_report", original_raw),
        ("serialized", raw),
    ):
        point = _as_mapping(_field(source, "best_buy_point", None))
        if (
            not _verified_daily_source(source, report_date)
            or not _declared_dates_are_current(
                point,
                ("as_of", "date"),
                report_date,
            )
        ):
            continue
        value = _positive_metric(point.get("volume_ratio"))
        if value is not None:
            return value, "candidate.best_buy_point.volume_ratio", source_name
    pool_quality = _as_mapping(row.get("pool_quality"))
    value = _positive_metric(pool_quality.get("volume_ratio20"))
    if (
        value is not None
        and pool_quality.get("quality_evidence_eligible") is True
        and _pool_quality_is_current(row, raw, original_raw, report_date)
    ):
        return value, "workspace.pool_quality.volume_ratio20", "serialized"
    return None, None, None


def _turnover_evidence(row, raw, original_raw, report_date):
    pool_quality = _as_mapping(row.get("pool_quality"))
    amount = _positive_metric(pool_quality.get("money20"))
    source = _as_text(pool_quality.get("liquidity_source"))
    if (
        amount is None
        or not source
        or pool_quality.get("quality_evidence_eligible") is not True
        or not _pool_quality_is_current(
            row,
            raw,
            original_raw,
            report_date,
        )
    ):
        return {
            "status": "missing",
            "source": "workspace.pool_quality.money20",
            "as_of": report_date,
            "average_20": None,
            "liquidity_source": source or None,
            "kind": "average_turnover_amount",
            "reason": "verified_turnover_source_not_provided",
        }
    return {
        "status": "available",
        "source": "workspace.pool_quality.money20",
        "as_of": report_date,
        "average_20": amount,
        "liquidity_source": source,
        "kind": "average_turnover_amount",
        "note": "仅表示成交额与流动性，不代表个股主力净流入",
    }


def _sector_capital_flow(raw, original_raw, report_date):
    for source_name, source in (
        ("serialized", raw),
        ("formal_report", original_raw),
    ):
        if not isinstance(source, Mapping):
            continue
        flow = _finite_number(source.get("sector_flow"))
        if flow == 0:
            flow = None
        rank = _positive_metric(source.get("sector_rank"))
        label = _as_text(source.get("sector_strength_label")) or None
        if flow is None and rank is None and label is None:
            continue
        declared_status = _as_text(source.get("sector_flow_status"))
        data_status = _as_mapping(source.get("data_status"))
        if (
            (data_status and not _verified_daily_source(source, report_date))
            or not _declared_dates_are_current(
                source,
                ("sector_flow_as_of", "date", "as_of"),
                report_date,
            )
        ):
            continue
        complete = (
            declared_status == "verified_complete"
            and _verified_daily_source(source, report_date)
        )
        return {
            "status": "available" if complete else "partial",
            "source": "{}.sector_flow".format(source_name),
            "as_of": report_date,
            "net_flow": flow,
            "rank": rank,
            "label": label,
            "scope": "sector_only",
            **({"reason": "sector_flow_verification_not_current"}
               if not complete else {}),
        }
    return {
        "status": "missing",
        "source": "candidate.sector_flow",
        "as_of": report_date,
        "net_flow": None,
        "rank": None,
        "label": None,
        "scope": "sector_only",
        "reason": "sector_fund_source_not_provided",
    }


def _build_volume_and_capital(row, raw, original_raw, report_date):
    volume = _verified_volume_summary(raw, original_raw, report_date)
    ratio, ratio_source, ratio_plane = _explicit_volume_ratio(
        row,
        raw,
        original_raw,
        report_date,
    )
    turnover = _turnover_evidence(
        row,
        raw,
        original_raw,
        report_date,
    )
    stock_flow = {
        "status": "missing",
        "source": "verified individual-stock fund source",
        "as_of": report_date,
        "net_flow": None,
        "reason": "individual_stock_fund_source_not_provided",
    }
    sector_flow = _sector_capital_flow(raw, original_raw, report_date)
    parts = []
    if volume["status"] != "missing":
        parts.append("量能可验证")
    if turnover["status"] == "available":
        parts.append("20日平均成交额仅表示流动性")
    parts.append("个股资金证据不足")
    if sector_flow["status"] != "missing":
        parts.append("板块资金单独展示")
    has_evidence = (
        volume["status"] != "missing"
        or ratio is not None
        or turnover["status"] == "available"
        or sector_flow["status"] != "missing"
    )
    return {
        "status": "partial" if has_evidence else "missing",
        "source": "candidate volume + explicit turnover/fund sources",
        "as_of": report_date,
        "summary": "；".join(parts),
        "volume": volume,
        "current_volume": volume.get("current"),
        "average_volume_5": volume.get("average_5"),
        "volume20": volume.get("average_20"),
        "volume_ratio": ratio,
        "volume_ratio_source": ratio_source,
        "volume_ratio_source_plane": ratio_plane,
        "ratio20": (
            ratio
            if ratio_source == "workspace.pool_quality.volume_ratio20"
            else None
        ),
        "turnover": turnover,
        "money20": turnover.get("average_20"),
        "money20_text": _format_cn_amount(turnover.get("average_20")),
        "money20_kind": turnover.get("kind"),
        "money20_source": turnover.get("liquidity_source"),
        "stock_capital_flow": stock_flow,
        "stock_money_flow": "个股资金证据不足",
        "sector_capital_flow": sector_flow,
        "sector_money_flow": sector_flow.get("net_flow"),
        "sector_money_flow_text": _format_cn_amount(
            sector_flow.get("net_flow")
        ),
        "capital_state": "个股与板块资金严格分离",
        **({"reason": "volume_and_capital_evidence_not_provided"}
           if not has_evidence else {}),
    }


def _formal_market_sentiment(daily_data, report_date):
    raw = _as_mapping(daily_data.get("market_sentiment"))
    score = _finite_number(raw.get("score"))
    label = _as_text(raw.get("label")) or None
    evidence_date = _as_text(raw.get("date")) or report_date
    valid = (
        score is not None
        and 0 <= score <= 100
        and label is not None
        and raw.get("insufficient") is not True
        and (not report_date or evidence_date == report_date)
    )
    if not valid:
        return {
            "status": "missing",
            "source": "daily.market_sentiment",
            "as_of": report_date,
            "score": None,
            "label": None,
            "version": None,
            "coverage": None,
            "components": {},
            "evidence": {},
            "reason": "formal_market_sentiment_not_provided",
        }
    components = _compact_native_fields(
        raw.get("components"),
        _FORMAL_MARKET_COMPONENTS,
    )
    raw_evidence = _as_mapping(raw.get("evidence"))
    evidence = {
        component: _compact_native_fields(
            raw_evidence.get(component),
            _FORMAL_MARKET_EVIDENCE_FIELDS,
        )
        for component in _FORMAL_MARKET_COMPONENTS
        if isinstance(raw_evidence.get(component), Mapping)
    }
    return {
        "status": "available",
        "source": "daily.market_sentiment",
        "as_of": evidence_date,
        "score": score,
        "label": label,
        "version": _as_text(raw.get("version")) or None,
        "coverage": _finite_number(raw.get("coverage")),
        "components": components,
        "evidence": evidence,
    }


def _matching_sector_item(daily_data, row, raw):
    heat = _as_mapping(daily_data.get("sector_heat"))
    items = heat.get("items")
    if not isinstance(items, list):
        return heat, None
    sector_name = _as_text(row.get("sector")) or _as_text(
        _field(raw, "sector", None)
    )
    code = _as_text(row.get("code"))
    for item in items:
        item = _as_mapping(item)
        refs = item.get("sector_refs")
        refs = refs if isinstance(refs, list) else []
        if (
            (sector_name and _as_text(item.get("sector_name")) == sector_name)
            or (code and code in {_as_text(ref) for ref in refs})
        ):
            return heat, item
    return heat, None


def _matching_flow_items(
    daily_data,
    key,
    sector_name,
    report_date,
    expected_sign,
):
    items = daily_data.get(key)
    if not isinstance(items, list) or not sector_name:
        return []
    matched = []
    seen = set()
    for raw_item in items:
        item = _as_mapping(raw_item)
        if _as_text(item.get("name")) != sector_name:
            continue
        coverage = _finite_number(item.get("component_coverage"))
        dedupe = _as_text(item.get("hierarchy_dedup_status"))
        if (
            coverage != 1
            or dedupe not in _VERIFIED_SECTOR_DEDUPE_STATUSES
        ):
            continue
        if not _declared_dates_are_current(
            item,
            ("as_of", "date"),
            report_date,
        ):
            continue
        flow = _finite_number(item.get("flow"))
        if flow is None or flow * expected_sign <= 0:
            continue
        signature = (
            flow,
            _finite_number(item.get("change_pct")),
            _positive_metric(item.get("rank")),
        )
        if signature in seen:
            continue
        seen.add(signature)
        matched.append(item)
        if len(matched) >= _MAX_SECTOR_SIGNALS_PER_DIRECTION:
            break
    return matched


def _compact_sector_signal(source, direction):
    return {
        "direction": direction,
        "source": source.get("source"),
        "net_flow": _finite_number(
            source.get("net_flow", source.get("flow"))
        ),
        "change_pct": _finite_number(source.get("change_pct")),
        "rank": _positive_metric(source.get("rank")),
    }


def _build_sector_evidence(daily_data, row, raw, report_date):
    heat, item = _matching_sector_item(daily_data, row, raw)
    sector_name = _as_text(row.get("sector")) or _as_text(
        _field(raw, "sector", None)
    )
    if not item:
        return {
            "status": "missing",
            "source": "daily.sector_heat",
            "as_of": report_date,
            "sector": sector_name or None,
            "direction": "unknown",
            "net_flow": None,
            "supporting_evidence": [],
            "opposing_evidence": [],
            "reason": "verified_sector_item_not_provided",
        }

    if (
        not _declared_dates_are_current(
            heat,
            ("date", "as_of"),
            report_date,
            require_one=True,
        )
        or not _declared_dates_are_current(
            item,
            ("date", "as_of"),
            report_date,
        )
    ):
        return {
            "status": "missing",
            "source": "daily.sector_heat",
            "as_of": report_date,
            "sector": sector_name or None,
            "direction": "unknown",
            "net_flow": None,
            "supporting_evidence": [],
            "opposing_evidence": [],
            "reason": "sector_evidence_date_mismatch",
        }

    heat_status = _as_text(heat.get("status"))
    item_status = _as_text(item.get("status"))
    complete = (
        heat_status == "verified_complete"
        and item_status == "verified_complete"
    )
    partial = (
        heat_status.startswith("verified_")
        and item_status.startswith("verified_")
        and not complete
    )
    net_flow = _finite_number(item.get("net_flow"))
    change_pct = _finite_number(item.get("change_pct"))
    supporting = []
    opposing = []
    if complete:
        if (net_flow is not None and net_flow > 0) or (
            change_pct is not None and change_pct > 0
        ):
            supporting.append(_compact_sector_signal(item, "support"))
        if (net_flow is not None and net_flow < 0) or (
            change_pct is not None and change_pct < 0
        ):
            opposing.append(_compact_sector_signal(item, "risk"))
        for flow_item in _matching_flow_items(
            daily_data,
            "sector_flow",
            sector_name,
            report_date,
            1,
        ):
            supporting.append(_compact_sector_signal(
                {**flow_item, "source": "daily.sector_flow"},
                "support",
            ))
        for flow_item in _matching_flow_items(
            daily_data,
            "sector_outflow",
            sector_name,
            report_date,
            -1,
        ):
            opposing.append(_compact_sector_signal(
                {**flow_item, "source": "daily.sector_outflow"},
                "risk",
            ))

    supporting = supporting[:_MAX_SECTOR_SIGNALS_PER_DIRECTION]
    opposing = opposing[:_MAX_SECTOR_SIGNALS_PER_DIRECTION]

    if supporting and opposing:
        direction = "disagreement"
    elif supporting:
        direction = "support"
    elif opposing:
        direction = "risk"
    elif complete:
        direction = "neutral"
    else:
        direction = "unknown"
    status = "available" if complete else ("partial" if partial else "missing")
    return {
        "status": status,
        "source": _as_text(item.get("source"))
        or _as_text(heat.get("source"))
        or "daily.sector_heat",
        "as_of": _as_text(item.get("as_of")) or report_date,
        "sector": sector_name or _as_text(item.get("sector_name")) or None,
        "sector_code": _as_text(item.get("sector_code")) or None,
        "heat_status": heat_status or None,
        "item_status": item_status or None,
        "direction": direction,
        "net_flow": net_flow,
        "change_pct": change_pct,
        "rank": _positive_metric(item.get("rank")),
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        **({"reason": "sector_item_not_fully_verified"} if partial else {}),
    }


def _build_market_and_sector(daily_data, row, raw, report_date):
    market = _formal_market_sentiment(daily_data, report_date)
    sector = _build_sector_evidence(
        daily_data,
        row,
        raw,
        report_date,
    )
    states = {
        "support": "支持",
        "risk": "风险",
        "disagreement": "分歧",
        "neutral": "中性",
        "unknown": "证据部分可用 · 方向未知"
        if sector.get("status") == "partial" else "方向未知",
    }
    direction = sector.get("direction", "unknown")
    market_text = None
    if market["status"] == "available":
        market_text = "{} / 100 · {}".format(
            market["score"],
            market["label"],
        )
    sector_support = (
        "板块证据支持"
        if direction == "support" else None
    )
    sector_risk = "板块风险证据" if direction == "risk" else None
    summary_parts = []
    if market_text:
        summary_parts.append("正式市场{}".format(market["label"]))
    if sector.get("status") == "partial":
        summary_parts.append("板块证据部分可用，暂不判定资金支持")
    elif direction == "disagreement":
        summary_parts.append("板块正反证据分歧")
    elif sector_support:
        summary_parts.append(sector_support)
    elif sector_risk:
        summary_parts.append(sector_risk)
    else:
        summary_parts.append("板块方向未知")
    has_market = market["status"] == "available"
    has_sector = sector["status"] in {"available", "partial"}
    status = "available" if has_market and sector["status"] == "available" else (
        "partial" if has_market or has_sector else "missing"
    )
    return {
        "status": status,
        "source": "daily.market_sentiment + daily.sector_heat",
        "as_of": report_date,
        "summary": "；".join(summary_parts),
        "formal_market_sentiment": market,
        "market": market_text,
        "market_label": market.get("label"),
        "market_sentiment_score": market.get("score"),
        "sector_evidence": sector,
        "sector": sector.get("sector"),
        "sector_state": states.get(direction, "方向未知"),
        "sector_support": sector_support,
        "sector_risk": sector_risk,
        **({"reason": "market_and_sector_evidence_not_provided"}
           if status == "missing" else {}),
    }


def _normalized_historical_horizon(value):
    if isinstance(value, bool):
        return None
    try:
        horizon = int(value)
    except (TypeError, ValueError):
        return None
    return horizon if horizon in (1, 3, 5) else None


def _nonnegative_count(value):
    number = _finite_number(value)
    if number is None or number < 0 or int(number) != number:
        return None
    return int(number)


def _contribution_identity(contribution):
    contribution = _as_mapping(contribution)
    research_tier = _as_text(contribution.get("research_tier"))
    if not research_tier:
        evaluation_role = _as_text(
            contribution.get("evaluation_role")
        ).lower()
        research_tier = (
            "prospective_ledger"
            if evaluation_role in _VALID_SCORECARD_ROLES
            else "legacy_unclassified"
        )
    return {
        "strategy": _as_text(contribution.get("strategy_name")) or None,
        "version": _as_text(contribution.get("strategy_version")) or None,
        "source_pool": _as_text(contribution.get("source_pool")) or None,
        "entry_mode": _as_text(contribution.get("entry_mode")) or "unknown",
        "intended_horizon": _normalized_historical_horizon(
            contribution.get("intended_horizon")
        ),
        "research_tier": research_tier,
    }


def _scorecard_identity(scorecard):
    scorecard = _as_mapping(scorecard)
    raw_identity = scorecard.get("comparison_identity")
    if not isinstance(raw_identity, Mapping):
        return None
    if any(field not in raw_identity for field in _HISTORICAL_IDENTITY_FIELDS):
        return None
    raw_horizon = raw_identity.get("intended_horizon")
    if (
        raw_horizon is not None
        and _normalized_historical_horizon(raw_horizon) is None
    ):
        return None
    identity = {
        "strategy": _as_text(raw_identity.get("strategy")) or None,
        "version": _as_text(raw_identity.get("version")) or None,
        "source_pool": _as_text(raw_identity.get("source_pool")) or None,
        "entry_mode": _as_text(raw_identity.get("entry_mode")) or None,
        "intended_horizon": _normalized_historical_horizon(
            raw_identity.get("intended_horizon")
        ),
        "research_tier": _as_text(raw_identity.get("research_tier")) or None,
    }
    if any(
        not identity[field]
        for field in (
            "strategy", "version", "source_pool", "entry_mode",
            "research_tier",
        )
    ):
        return None
    # A scorecard must not carry two identities: if the duplicated public
    # fields are present they must agree with comparison_identity exactly.
    for field in _HISTORICAL_IDENTITY_FIELDS:
        if field not in scorecard:
            continue
        if (
            field == "intended_horizon"
            and scorecard.get(field) is not None
            and _normalized_historical_horizon(scorecard.get(field)) is None
        ):
            return None
        top_level = (
            _normalized_historical_horizon(scorecard.get(field))
            if field == "intended_horizon"
            else (_as_text(scorecard.get(field)) or None)
        )
        if top_level != identity[field]:
            return None
    return identity


def _candidate_ledger_contract(daily_data, row, pool_name, report_date):
    code = _as_text(row.get("code"))
    expected_strategy = _POOL_STRATEGY_IDENTITIES.get(pool_name)
    if not code or not expected_strategy:
        return [], "candidate_strategy_identity_not_declared"
    ledger = daily_data.get("recommendation_ledger")
    if not isinstance(ledger, list):
        return [], "recommendation_ledger_not_serialized"
    matches = []
    for entry in ledger:
        entry = _as_mapping(entry)
        if _as_text(entry.get("report_date")) != report_date:
            continue
        if _as_text(entry.get("code")) != code:
            continue
        contributions = entry.get("strategy_contributions")
        if not isinstance(contributions, list):
            continue
        for contribution in contributions:
            contribution = _as_mapping(contribution)
            evaluation_role = _as_text(
                contribution.get("evaluation_role")
            )
            if (
                contribution.get("evaluation_eligible") is not True
                or contribution.get("cohort_eligible") is not True
                or _as_text(contribution.get("attribution_status"))
                != "verified"
                or _as_text(contribution.get("decision_code"))
                != "recommend"
                or _as_text(contribution.get("user_action"))
                != "recommendation"
                or _as_text(contribution.get("publication_surface"))
                != "formal_recommendation"
                or evaluation_role != "formal"
            ):
                continue
            if _as_text(contribution.get("strategy_name")) != expected_strategy:
                continue
            if _as_text(contribution.get("source_pool")) != pool_name:
                continue
            matches.append({
                "entry": entry,
                "contribution": contribution,
                "identity": _contribution_identity(contribution),
            })
    if not matches:
        return [], "same_contract_ledger_record_not_found"
    if len(matches) > 1:
        return matches, "same_contract_ledger_identity_ambiguous"
    identity = matches[0]["identity"]
    raw_horizon = matches[0]["contribution"].get("intended_horizon")
    if (
        raw_horizon is not None
        and _normalized_historical_horizon(raw_horizon) is None
    ):
        return matches, "same_contract_ledger_identity_incomplete"
    if any(
        not identity[field]
        for field in ("strategy", "version", "source_pool", "research_tier")
    ):
        return matches, "same_contract_ledger_identity_incomplete"
    return matches, None


def _scorecard_rows(scorecards):
    if not isinstance(scorecards, Mapping):
        return []
    if scorecards.get("schema_version") != 2:
        return []
    rows = []
    for section in ("formal", "baselines", "research", "gates"):
        values = scorecards.get(section)
        if not isinstance(values, list):
            continue
        rows.extend(
            (section, value)
            for value in values
            if isinstance(value, Mapping)
        )
    return rows


def _project_historical_progress(scorecard, horizon):
    raw_progress = _as_mapping(
        _as_mapping(scorecard.get("comparison_progress_by_horizon")).get(
            horizon
        )
    )
    readiness = _as_text(
        _as_mapping(scorecard.get("horizon_readiness")).get(horizon)
    )
    mature = _nonnegative_count(raw_progress.get("mature_samples"))
    waiting = _nonnegative_count(raw_progress.get("waiting_samples"))
    unavailable = _nonnegative_count(
        raw_progress.get("unavailable_samples")
    )
    active_dates = _nonnegative_count(raw_progress.get("active_dates"))
    active_months = _nonnegative_count(raw_progress.get("active_months"))
    complete = all(value is not None for value in (
        mature,
        waiting,
        unavailable,
        active_dates,
        active_months,
    ))
    passes_gate = bool(
        complete
        and mature >= _HISTORICAL_MATURITY_GATES[
            "required_mature_samples"
        ]
        and active_dates >= _HISTORICAL_MATURITY_GATES[
            "required_active_dates"
        ]
        and active_months >= _HISTORICAL_MATURITY_GATES[
            "required_calendar_months"
        ]
    )
    declared_status = _as_text(raw_progress.get("status")) or readiness
    publishable = scorecard.get("metrics_publishable") is True
    blockers = scorecard.get("metrics_blocking_reasons")
    has_blockers = not isinstance(blockers, list) or bool(blockers)
    if (
        publishable
        and not has_blockers
        and readiness == "ready_for_manual_comparison"
        and declared_status == "ready_for_manual_comparison"
        and passes_gate
    ):
        status = "ready_for_manual_comparison"
    elif not complete:
        status = "contract_missing"
    elif declared_status in {
        "collecting",
        "waiting_for_maturity",
        "data_unavailable",
        "no_signals",
        "disabled",
    }:
        status = declared_status
    else:
        # A prematurely advertised ready state is collecting, never ready.
        status = "collecting"
    return {
        "status": status,
        "mature_samples": mature,
        "waiting_samples": waiting,
        "unavailable_samples": unavailable,
        "required_mature_samples": _HISTORICAL_MATURITY_GATES[
            "required_mature_samples"
        ],
        "active_dates": active_dates,
        "required_active_dates": _HISTORICAL_MATURITY_GATES[
            "required_active_dates"
        ],
        "active_months": active_months,
        "required_calendar_months": _HISTORICAL_MATURITY_GATES[
            "required_calendar_months"
        ],
    }


def _project_historical_metrics(scorecard, horizon, progress):
    if progress.get("status") != "ready_for_manual_comparison":
        return {}
    raw_metrics = _as_mapping(
        _as_mapping(scorecard.get("metrics_by_horizon")).get(horizon)
    )
    metric_count = _nonnegative_count(raw_metrics.get("n"))
    if (
        metric_count is None
        or metric_count
        != _nonnegative_count(progress.get("mature_samples"))
        or metric_count
        < _HISTORICAL_MATURITY_GATES["required_mature_samples"]
    ):
        return {}
    projected = {}
    for field in _HISTORICAL_METRIC_FIELDS:
        if field not in raw_metrics:
            continue
        if field in {"date_start", "date_end"}:
            value = _as_text(raw_metrics.get(field))
            if value:
                projected[field] = value
            continue
        if field == "n":
            value = metric_count
        else:
            value = _finite_number(raw_metrics.get(field))
            if field == "win_rate" and value is not None:
                if value < 0 or value > 100:
                    value = None
        if value is not None:
            projected[field] = value
    return projected


def _verified_ledger_entry_price_source(value):
    text = _as_text(value)
    if not text.startswith("ledger."):
        return None
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-[]"
    return text if all(character in allowed for character in text) else None


def _simulation_tracking(contract_match):
    if not contract_match:
        return {
            "status": "missing",
            "label": "暂无同合同历史跟踪记录",
            "entry_price": None,
            "entry_price_source": None,
        }
    entry = contract_match["entry"]
    contribution = contract_match["contribution"]
    identity = contract_match["identity"]
    entry_mode = identity.get("entry_mode")
    base = {
        "status": "missing",
        "label": "策略模拟跟踪",
        "signal_date": _as_text(entry.get("report_date")) or None,
        "entry_mode": entry_mode,
        "entry_price": None,
        "entry_price_source": None,
    }
    if entry_mode not in _VALID_SIMULATION_ENTRY_MODES:
        base["status"] = "entry_mode_unknown"
        base["reason"] = "entry_mode_not_in_display_contract"
        return base
    entry_price = _positive_price(contribution.get("entry_price"))
    entry_price_status = _as_text(contribution.get("entry_price_status"))
    entry_price_source = _verified_ledger_entry_price_source(
        contribution.get("entry_price_source")
    )
    if (
        entry_price is not None
        and entry_price_status == "verified"
        and entry_price_source
    ):
        base.update({
            "status": "available",
            "entry_price": entry_price,
            "entry_price_source": entry_price_source,
        })
        return base
    base["status"] = "entry_price_missing"
    base["reason"] = "verified_simulation_entry_price_not_provided"
    return base


def _historical_summary(status, declared_horizon, progress_by_horizon):
    ready = [
        key for key in _HISTORICAL_HORIZONS
        if progress_by_horizon[key].get("status")
        == "ready_for_manual_comparison"
    ]
    prefix = (
        "策略声明 T+{}；".format(declared_horizon)
        if declared_horizon is not None
        else "策略未声明统一周期；"
    )
    if status == "ambiguous":
        return prefix + "同合同历史验证身份存在歧义"
    if status == "missing":
        return prefix + "暂无同合同历史验证记录"
    if ready:
        labels = "、".join("T+{}".format(key[1:]) for key in ready)
        return prefix + "{} 已达到人工比较门槛".format(labels)
    return prefix + "历史样本仍在收集"


def _build_historical_validation(
    daily_data,
    row,
    pool_name,
    report_date,
):
    matches, ledger_reason = _candidate_ledger_contract(
        daily_data,
        row,
        pool_name,
        report_date,
    )
    empty_metrics = {key: {} for key in _HISTORICAL_HORIZONS}
    empty_progress = {
        key: {
            "status": "contract_missing",
            "mature_samples": None,
            "waiting_samples": None,
            "unavailable_samples": None,
            **_HISTORICAL_MATURITY_GATES,
            "active_dates": None,
            "active_months": None,
        }
        for key in _HISTORICAL_HORIZONS
    }
    if len(matches) != 1 or ledger_reason:
        status = "ambiguous" if len(matches) > 1 else "missing"
        section = {
            "status": status,
            "source": (
                "daily.strategy_scorecards + daily.recommendation_ledger"
            ),
            "as_of": report_date,
            "comparison_identity": None,
            "declared_horizon": None,
            "progress_by_horizon": empty_progress,
            "metrics_by_horizon": empty_metrics,
            "simulation_tracking": _simulation_tracking(None),
            "reason": ledger_reason or "same_contract_identity_not_found",
        }
        section["summary"] = _historical_summary(
            status,
            None,
            empty_progress,
        )
        return section

    contract_match = matches[0]
    identity = contract_match["identity"]
    card_matches = [
        (section, card) for section, card in _scorecard_rows(
            daily_data.get("strategy_scorecards")
        )
        if _scorecard_identity(card) == identity
    ]
    cards = [card for _section, card in card_matches]
    card_role_is_formal = bool(
        len(cards) == 1
        and _as_text(cards[0].get("evaluation_role")) == "formal"
    )
    card_section_is_formal = bool(
        len(card_matches) == 1
        and card_matches[0][0] == "formal"
    )
    if (
        len(cards) != 1
        or not card_role_is_formal
        or not card_section_is_formal
    ):
        status = "ambiguous" if len(cards) > 1 else "missing"
        section = {
            "status": status,
            "source": (
                "daily.strategy_scorecards + daily.recommendation_ledger"
            ),
            "as_of": report_date,
            "comparison_identity": dict(identity),
            "declared_horizon": identity["intended_horizon"],
            "progress_by_horizon": empty_progress,
            "metrics_by_horizon": empty_metrics,
            "simulation_tracking": _simulation_tracking(contract_match),
            "reason": (
                "same_contract_scorecard_ambiguous"
                if len(cards) > 1
                else (
                    "same_contract_scorecard_role_not_formal"
                    if len(cards) == 1 and not card_role_is_formal
                    else (
                        "same_contract_scorecard_section_not_formal"
                        if len(cards) == 1
                        else "same_contract_scorecard_not_found"
                    )
                )
            ),
        }
        section["summary"] = _historical_summary(
            status,
            identity["intended_horizon"],
            empty_progress,
        )
        return section

    card = cards[0]
    progress = {
        key: _project_historical_progress(card, key)
        for key in _HISTORICAL_HORIZONS
    }
    metrics = {
        key: _project_historical_metrics(card, key, progress[key])
        for key in _HISTORICAL_HORIZONS
    }
    if any(
        progress[key]["status"] == "ready_for_manual_comparison"
        for key in _HISTORICAL_HORIZONS
    ):
        status = "ready_for_manual_comparison"
    else:
        declared_status = _as_text(card.get("evaluation_status"))
        status = declared_status if declared_status in {
            "collecting",
            "waiting_for_maturity",
            "data_unavailable",
            "no_signals",
            "disabled",
            "no_formal_recommendations",
            "contract_missing",
        } else "collecting"
    section = {
        "status": status,
        "source": "daily.strategy_scorecards + daily.recommendation_ledger",
        "as_of": report_date,
        "comparison_identity": dict(identity),
        "declared_horizon": identity["intended_horizon"],
        "progress_by_horizon": progress,
        "metrics_by_horizon": metrics,
        "simulation_tracking": _simulation_tracking(contract_match),
    }
    section["summary"] = _historical_summary(
        status,
        identity["intended_horizon"],
        progress,
    )
    return section


def _build_main_rise_clue(
    row,
    raw,
    original_raw,
    pool_name,
    view_name,
    report_date,
):
    """Translate existing strategy signals into a display-only clue."""
    sources = (raw, original_raw, row)
    buy_points = _best_buy_point_sources(raw, original_raw, row)
    signal_sources = tuple(buy_points) + sources

    signal_type = _as_text(
        _declared_value(signal_sources, ("type", "signal_type"))
    )
    source_type = _as_text(
        _declared_value(signal_sources, ("source_type",))
    )
    source_channel = _as_text(
        _declared_value(sources, ("source_channel",))
    )
    startup_grade = _as_text(
        _declared_value(signal_sources, ("daily_startup_grade",))
    )
    startup_label = _as_text(
        _declared_value(signal_sources, ("daily_startup_label",))
    )
    declared_reasons = _declared_texts(
        _declared_value(
            signal_sources,
            ("startup_reason", "boom_reason", "next_day_reason", "reason"),
        ),
        _declared_value(
            signal_sources,
            ("startup_signals", "confirmations"),
        ),
    )
    row_sources = _declared_texts(
        row.get("sources"),
        row.get("source_labels"),
    )
    identity_text = " ".join(
        value for value in (
            signal_type,
            source_type,
            source_channel,
            startup_grade,
            startup_label,
            pool_name,
            view_name,
            " ".join(row_sources),
        ) if value
    ).lower()

    if (
        view_name == "acceleration"
        or pool_name == "next_day_boom"
        or "acceleration" in identity_text
        or "加速" in identity_text
    ):
        clue_type = "acceleration"
        label = "加速线索"
    elif (
        "trend_continuation" in identity_text
        or "趋势延续" in identity_text
    ):
        clue_type = "trend_continuation"
        label = "趋势延续线索"
    elif (
        "强势启动" in identity_text
        or "日线强势启动" in identity_text
        or startup_grade.lower() in {"strong", "confirmed"}
    ):
        clue_type = "startup_confirmation"
        label = "启动确认线索"
    else:
        clue_type = "none"
        label = "尚未形成主升浪线索"

    supporting = []
    if clue_type != "none":
        supporting = _declared_texts(
            signal_type,
            source_type,
            startup_label,
            row_sources,
            declared_reasons,
            source_channel,
            "next_day_boom" if pool_name == "next_day_boom" else "",
        )

    risk_labels = _declared_texts(
        row.get("risk_flags"),
        _field(raw, "risk_flags", None),
        _field(original_raw, "risk_flags", None),
    )
    health = _as_mapping(
        _declared_value(sources, ("gf_dma_health",))
    )
    failure_gate = _as_text(
        _declared_value(sources, ("failure_gate",))
    )
    reason_code = _as_text(
        _declared_value(sources, ("reason_code",))
    )
    structure_values = _declared_texts(
        health.get("label"),
        health.get("trend_stage"),
        health.get("alignment"),
        failure_gate,
        reason_code,
    )
    structure_invalid = any(
        value in {"broken", "trend_structure", "structure_break"}
        or "结构破坏" in value
        for value in structure_values + risk_labels
    )
    heat_risks = [
        value for value in risk_labels
        if any(marker in value for marker in (
            "距参考价过远",
            "距参考位过远",
            "涨幅过热",
        ))
    ]
    opposing = []
    if heat_risks:
        opposing.append("加速过热风险")
        opposing.extend(heat_risks)
    if structure_invalid:
        opposing.extend(_declared_texts("结构破坏", structure_values, risk_labels))
    opposing = _declared_texts(opposing)

    if structure_invalid and supporting:
        status = "invalidated"
        clue_type = "invalidated"
        label = "主升线索失效"
    elif supporting:
        status = "available"
    else:
        status = "missing"
        clue_type = "none"
        label = "尚未形成主升浪线索"
        opposing = []

    section = {
        "status": status,
        "source": "existing candidate strategy signals",
        "as_of": report_date,
        "clue_type": clue_type,
        "label": label,
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        "note": "只翻译现有证据，不生成策略、分数或正式动作",
    }
    if status == "missing":
        section["reason"] = "main_rise_clue_not_provided"
    return section


def _build_candidate_projection(
    row,
    raw,
    original_raw,
    pool_name,
    view_name,
    report_date,
    daily_data,
):
    price_evidence = _build_price_evidence(
        row,
        raw,
        original_raw,
        report_date,
    )
    chart_evidence = _build_chart_evidence_metadata(
        row,
        raw,
        original_raw,
        price_evidence,
        report_date,
    )
    candidate = {
        "view": view_name,
        "code": _as_text(row.get("code")),
        "summary": _build_summary(row, raw, view_name, report_date),
        "decision_score": _build_decision_score(raw, pool_name),
        "rank_evidence": _build_rank_evidence(row, view_name),
        "price_evidence": price_evidence,
        "daily_structure": _project_daily_structure(
            row,
            raw,
            original_raw,
            report_date,
        ),
        "sublevel_30m": _project_sublevel_30m(
            row,
            raw,
            original_raw,
            report_date,
        ),
        "volume_and_capital": _build_volume_and_capital(
            row,
            raw,
            original_raw,
            report_date,
        ),
        "market_and_sector": _build_market_and_sector(
            daily_data,
            row,
            raw,
            report_date,
        ),
        "main_rise_clue": _build_main_rise_clue(
            row,
            raw,
            original_raw,
            pool_name,
            view_name,
            report_date,
        ),
        "risk_and_next": _build_risk_and_next(
            row,
            raw,
            original_raw,
            price_evidence,
        ),
        "historical_validation": _build_historical_validation(
            daily_data,
            row,
            pool_name,
            report_date,
        ),
        "display_derived": _build_display_derived(
            price_evidence,
            chart_evidence=chart_evidence,
        ),
    }
    for section_name in EVIDENCE_SECTION_KEYS:
        if section_name not in candidate:
            candidate[section_name] = _missing_section(
                "recommendation_evidence.{}".format(section_name)
            )
    return candidate


def _build_views(formal_report, daily_data, report_date):
    workspace = _as_mapping(daily_data.get("workspace"))
    workspace_views = _as_mapping(workspace.get("views"))
    declared_order = workspace.get("view_order")
    if not isinstance(declared_order, list):
        declared_order = list(workspace_views.keys())

    views = {}
    seen = set()
    for declared_name in declared_order:
        view_name = _as_text(declared_name)
        if not view_name or view_name in seen:
            continue
        seen.add(view_name)
        rows = workspace_views.get(view_name)
        if not isinstance(rows, list):
            rows = []
        projected = []
        for row in rows:
            row = _as_mapping(row)
            raw, pool_name = _find_serialized_candidate(daily_data, row)
            original_raw = _find_original_candidate(formal_report, row)
            projected.append(_build_candidate_projection(
                row,
                raw,
                original_raw,
                pool_name,
                view_name,
                report_date,
                daily_data,
            ))
        views[view_name] = projected
    return views


def build_recommendation_evidence_projection(
    formal_report,
    daily_data,
    psy12_shadow_audit=None,
):
    """Return the minimal versioned HTML-only evidence envelope."""
    formal_report = formal_report if isinstance(formal_report, dict) else {}
    daily_data = daily_data if isinstance(daily_data, dict) else {}
    report_date = str(
        daily_data.get("date") or formal_report.get("date") or ""
    )
    market_sentiment = {}
    market_sentiment["psy12_shadow_contract"] = (
        _project_psy12_shadow_contract(daily_data)
    )
    if isinstance(psy12_shadow_audit, Mapping):
        market_sentiment["psy12_shadow_audit"] = _compact_psy12_shadow_audit(
            psy12_shadow_audit
        )
    return {
        "schema_version": 1,
        "report_date": report_date,
        "views": _build_views(formal_report, daily_data, report_date),
        "market_sentiment": market_sentiment,
    }
