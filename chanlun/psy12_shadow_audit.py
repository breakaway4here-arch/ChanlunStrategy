"""Pure, read-only PSY12 shadow audit helpers.

The report generator and the CLI are responsible for loading their inputs.
This module only normalizes already-loaded reports and recomputes the shadow
contract; it never discovers files, reads a checkout, or mutates a report.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from datetime import date as calendar_date
from datetime import datetime as calendar_datetime

from chanlun.market_sentiment import build_market_sentiment_psy12_shadow


SCHEMA_VERSION = 1
AUDIT_MODE = "psy12_shadow_audit"
REQUIRED_DAYS = 20

PSY12_AUDIT_KEYS = (
    "status",
    "reason",
    "score",
    "up_days",
    "valid_days",
    "window",
    "start_date",
    "end_date",
    "daily_directions",
)
SHADOW_AUDIT_KEYS = (
    "schema_version",
    "mode",
    "status",
    "reason",
    "affects_production",
    "promotion_eligible",
    "promotion_requires_new_authorization",
    "formal_score",
    "raw_shadow_score_with_psy12",
    "shadow_score_with_psy12",
    "delta_vs_formal",
    "formal_label",
    "shadow_label",
    "weight_version",
    "weights",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _as_mapping(value):
    return value if isinstance(value, Mapping) else None


def _date_text(value):
    """Return a canonical ISO date or ``None`` for any invalid value."""

    # ``datetime`` subclasses ``date`` but its ISO form contains a time
    # component.  The audit contract accepts trade dates only.
    if isinstance(value, calendar_datetime):
        return None
    if isinstance(value, calendar_date):
        return value.isoformat()
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        return None
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None


def _copy_report(value):
    if not isinstance(value, Mapping):
        return None
    try:
        return copy.deepcopy(dict(value))
    except Exception:
        return None


def _missing_normalized(reason, as_of_date):
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "missing",
        "reason": reason,
        "as_of_date": as_of_date,
        "reports": [],
    }


def _validate_report_dates(report, trade_date):
    """Validate optional report dates without requiring aggregate ``date``."""

    top_level_date = report.get("date")
    if top_level_date is not None:
        normalized = _date_text(top_level_date)
        if normalized is None:
            return "invalid_trade_date"
        if normalized != trade_date:
            return "conflicting_trade_date"

    declared_trade_date = report.get("trade_date")
    if declared_trade_date is not None:
        normalized = _date_text(declared_trade_date)
        if normalized is None:
            return "invalid_trade_date"
        if normalized != trade_date:
            return "conflicting_trade_date"

    sentiment = _as_mapping(report.get("market_sentiment"))
    if sentiment is not None and sentiment.get("date") is not None:
        normalized = _date_text(sentiment.get("date"))
        if normalized is None:
            return "invalid_trade_date"
        if normalized != trade_date:
            return "conflicting_trade_date"
    return None


def _iter_historical_items(historical_reports):
    """Yield ``(date, report, source, ordinal)`` without reading any files."""

    if isinstance(historical_reports, Mapping):
        for ordinal, (raw_date, raw_report) in enumerate(
            historical_reports.items()
        ):
            yield raw_date, raw_report, "aggregate", ordinal
        return

    if isinstance(historical_reports, (list, tuple)):
        for ordinal, item in enumerate(historical_reports):
            if not isinstance(item, Mapping):
                yield None, None, "historical", ordinal
                continue
            if "report" in item:
                yield (
                    item.get("trade_date", item.get("date")),
                    item.get("report"),
                    item.get("source") or "historical",
                    ordinal,
                )
            else:
                yield (
                    item.get("trade_date", item.get("date")),
                    item,
                    "historical",
                    ordinal,
                )
        return

    raise TypeError("historical reports must be a mapping or list")


def normalize_historical_reports(
    historical_reports,
    current_report=None,
    as_of_date=None,
):
    """Normalize aggregate reports and inject an auditable trade date.

    ``historical_reports`` is normally the aggregate ``reports`` mapping.  A
    list of ``{"trade_date": ..., "report": ...}`` envelopes (or legacy raw
    reports carrying ``date``) is accepted for the CLI adapter.  Every source
    object is copied; same-day ``current_report`` replaces one aggregate row.
    Any malformed, duplicate, conflicting, or future input invalidates the
    whole result rather than allowing partial progress to be reported.
    """

    as_of = _date_text(as_of_date)
    if as_of is None:
        return _missing_normalized("invalid_as_of_date", None)
    try:
        as_of_value = calendar_date.fromisoformat(as_of)
    except ValueError:  # defensive; _date_text already validates this
        return _missing_normalized("invalid_as_of_date", None)

    if historical_reports is None or not isinstance(
        historical_reports, (Mapping, list, tuple)
    ):
        return _missing_normalized("historical_reports_not_mapping", as_of)

    entries = {}
    try:
        items = list(_iter_historical_items(historical_reports))
    except (TypeError, ValueError):
        return _missing_normalized("historical_reports_not_mapping", as_of)

    for raw_date, raw_report, source, ordinal in items:
        trade_date = _date_text(raw_date)
        if trade_date is None:
            return _missing_normalized("invalid_trade_date", as_of)
        if calendar_date.fromisoformat(trade_date) > as_of_value:
            return _missing_normalized("future_trade_date", as_of)
        report = _copy_report(raw_report)
        if report is None:
            return _missing_normalized("report_not_mapping", as_of)
        conflict = _validate_report_dates(report, trade_date)
        if conflict:
            return _missing_normalized(conflict, as_of)
        if trade_date in entries:
            return _missing_normalized("duplicate_trade_date", as_of)
        entries[trade_date] = {
            "trade_date": trade_date,
            "report": report,
            "source": source,
            "_ordinal": ordinal,
        }

    if current_report is not None:
        current = _copy_report(current_report)
        if current is None:
            return _missing_normalized("current_report_not_mapping", as_of)
        current_date = _date_text(current.get("date"))
        if current_date is None:
            return _missing_normalized("invalid_trade_date", as_of)
        current_value = calendar_date.fromisoformat(current_date)
        if current_value > as_of_value:
            return _missing_normalized("future_trade_date", as_of)
        if current_date != as_of:
            return _missing_normalized("current_date_mismatch", as_of)
        conflict = _validate_report_dates(current, current_date)
        if conflict:
            return _missing_normalized(conflict, as_of)
        # Current is authoritative for its date and may replace one aggregate
        # row.  A duplicate historical date has already been rejected above.
        entries[current_date] = {
            "trade_date": current_date,
            "report": current,
            "source": "current",
            "_ordinal": len(items),
        }

    normalized_reports = []
    for trade_date in sorted(entries):
        entry = entries[trade_date]
        normalized_reports.append({
            "trade_date": entry["trade_date"],
            "report": entry["report"],
            "source": entry["source"],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "available",
        "reason": None,
        "as_of_date": as_of,
        "reports": normalized_reports,
    }


def _projection(value, keys):
    source = value if isinstance(value, Mapping) else {}
    return {key: source.get(key) for key in keys}


def _finite_pair(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    left = float(left)
    right = float(right)
    if not math.isfinite(left) or not math.isfinite(right):
        return None
    return left, right


def _pearson(rows, component):
    pairs = []
    for row in rows:
        formal_components = row.get("components")
        formal_components = (
            formal_components if isinstance(formal_components, Mapping) else {}
        )
        pair = _finite_pair(
            row.get("psy12_score"),
            formal_components.get(component),
        )
        if pair is not None:
            pairs.append(pair)
    if len(pairs) < 2:
        return None
    left_mean = sum(left for left, _ in pairs) / len(pairs)
    right_mean = sum(right for _, right in pairs) / len(pairs)
    numerator = sum(
        (left - left_mean) * (right - right_mean)
        for left, right in pairs
    )
    left_scale = math.sqrt(
        sum((left - left_mean) ** 2 for left, _ in pairs)
    )
    right_scale = math.sqrt(
        sum((right - right_mean) ** 2 for _, right in pairs)
    )
    if left_scale == 0 or right_scale == 0:
        return None
    return round(numerator / (left_scale * right_scale), 4)


def _hypothetical_changes(rows):
    changes = []
    for row in rows:
        formal_score = row.get("formal_score")
        shadow_score = row.get("shadow_score")
        if formal_score is None or shadow_score is None:
            continue
        day_changes = []
        if shadow_score != formal_score:
            day_changes.append("market_temperature_score")
        if row.get("formal_label") != row.get("shadow_label"):
            day_changes.append("market_temperature_label")
        try:
            threshold_changed = (formal_score < 40) != (shadow_score < 40)
        except TypeError:
            threshold_changed = False
        if threshold_changed:
            day_changes.append("decision_gate_cold_market_threshold")
        if day_changes:
            changes.append({
                "date": row.get("date"),
                "changes": day_changes,
                "formal_score": formal_score,
                "shadow_score": shadow_score,
            })
    return changes


def _required_days(value):
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        value = REQUIRED_DAYS
    return max(1, value)


def _audit_shell(required_days, status, reason, as_of_date):
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": AUDIT_MODE,
        "status": status,
        "reason": reason,
        "as_of_date": as_of_date,
        "required_days": required_days,
        "valid_days": 0,
        "stored_complete_days": 0,
        "recomputable_days": 0,
        "complete_days": 0,
        "missing_days": 0,
        "mismatch_days": 0,
        "recalculation_consistency_rate": 0.0,
        "summary": {
            "average_delta": None,
            "maximum_absolute_delta": None,
            "label_change_count": 0,
        },
        "correlations": {"breadth": None, "index": None},
        "hypothetical_changes": [],
        "daily": [],
        "affects_production": False,
        "promotion_eligible": False,
        "promotion_requires_new_authorization": True,
    }


def _strict_native(value):
    """Make sure an audit result can be serialized with allow_nan=False."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {
            key: _strict_native(item)
            for key, item in value.items()
            if isinstance(key, str)
        }
    if isinstance(value, (list, tuple)):
        return [_strict_native(item) for item in value]
    return None


def _strict_result(result):
    try:
        native = _strict_native(result)
        return json.loads(json.dumps(
            native,
            ensure_ascii=False,
            allow_nan=False,
        ))
    except Exception:
        return None


def _stored_complete(psy12, shadow):
    if not isinstance(psy12, Mapping) or not isinstance(shadow, Mapping):
        return False
    if psy12.get("status") != "available":
        return False
    if shadow.get("schema_version") != SCHEMA_VERSION:
        return False
    if shadow.get("mode") != "shadow":
        return False
    if shadow.get("status") != "available":
        return False
    if shadow.get("affects_production") is not False:
        return False
    if shadow.get("promotion_eligible") is not False:
        return False
    if shadow.get("promotion_requires_new_authorization") is not True:
        return False
    required_psy = ("score", "up_days", "valid_days", "start_date", "end_date")
    if any(psy12.get(key) is None for key in required_psy):
        return False
    required_shadow = (
        "formal_score",
        "shadow_score_with_psy12",
        "delta_vs_formal",
        "formal_label",
        "shadow_label",
    )
    return not any(shadow.get(key) is None for key in required_shadow)


def _invalid_normalized(required_days, reason="invalid_normalized_report"):
    return _audit_shell(required_days, "missing", reason, None)


def evaluate_psy12_shadow_audit(normalized_reports, required_days=REQUIRED_DAYS):
    """Recompute a non-promoting audit from normalized report envelopes.

    ``valid_days``/``stored_complete_days`` count only rows that contain a
    complete stored PSY12 + shadow contract.  ``recomputable_days`` counts
    rows for which the formal sentiment and history can be recomputed.  A
    mismatch remains an observed day but is counted separately and blocks the
    manual-review-ready status.
    """

    required = _required_days(required_days)
    if not isinstance(normalized_reports, Mapping):
        return _invalid_normalized(required)
    status = normalized_reports.get("status")
    as_of = _date_text(normalized_reports.get("as_of_date"))
    if status != "available":
        result = _audit_shell(
            required,
            "missing",
            normalized_reports.get("reason") or "normalized_reports_missing",
            as_of,
        )
        return _strict_result(result) or _audit_shell(
            required, "missing", "audit_serialization_failure", as_of
        )
    entries = normalized_reports.get("reports")
    if not isinstance(entries, list):
        return _invalid_normalized(required)
    if not entries:
        result = _audit_shell(required, "missing", "no_historical_reports", as_of)
        return _strict_result(result) or _audit_shell(
            required, "missing", "audit_serialization_failure", as_of
        )

    eligible_rows = []
    missing_rows = 0
    try:
        for entry in entries:
            if not isinstance(entry, Mapping):
                return _invalid_normalized(required)
            trade_date = _date_text(entry.get("trade_date"))
            report = _as_mapping(entry.get("report"))
            if trade_date is None or report is None:
                return _invalid_normalized(required)
            formal = _as_mapping(report.get("market_sentiment"))
            history = report.get("market_sentiment_history")
            if formal is None or not isinstance(history, list):
                missing_rows += 1
                continue
            formal_for_recompute = copy.deepcopy(dict(formal))
            formal_date = formal_for_recompute.get("date")
            if formal_date is None:
                formal_for_recompute["date"] = trade_date
            elif _date_text(formal_date) != trade_date:
                return _invalid_normalized(required, "conflicting_trade_date")
            recomputed = build_market_sentiment_psy12_shadow(
                formal_for_recompute,
                copy.deepcopy(history),
            )
            psy12 = _as_mapping(recomputed.get("psy12"))
            shadow = _as_mapping(recomputed.get("psy12_shadow"))
            if (
                psy12 is None
                or shadow is None
                or psy12.get("status") != "available"
                or shadow.get("status") != "available"
            ):
                missing_rows += 1
                continue

            stored_psy12 = report.get("psy12")
            stored_shadow = report.get("psy12_shadow")
            stored_complete = _stored_complete(stored_psy12, stored_shadow)
            matches = stored_complete and (
                _projection(stored_psy12, PSY12_AUDIT_KEYS)
                == _projection(psy12, PSY12_AUDIT_KEYS)
                and _projection(stored_shadow, SHADOW_AUDIT_KEYS)
                == _projection(shadow, SHADOW_AUDIT_KEYS)
            )
            if not stored_complete:
                missing_rows += 1
            formal_components = formal_for_recompute.get("components")
            formal_components = (
                dict(formal_components)
                if isinstance(formal_components, Mapping) else {}
            )
            eligible_rows.append({
                "date": trade_date,
                "formal_score": shadow.get("formal_score"),
                "shadow_score": shadow.get("shadow_score_with_psy12"),
                "delta": shadow.get("delta_vs_formal"),
                "formal_label": shadow.get("formal_label"),
                "shadow_label": shadow.get("shadow_label"),
                "label_changed": (
                    shadow.get("formal_label") != shadow.get("shadow_label")
                ),
                "psy12_score": psy12.get("score"),
                "psy12_window": [
                    psy12.get("start_date"),
                    psy12.get("end_date"),
                ],
                "components": formal_components,
                "recalculation_match": bool(matches),
                "stored_complete": bool(stored_complete),
                "recomputable": True,
                "status": "complete" if matches else (
                    "mismatch" if stored_complete else "missing"
                ),
            })
    except Exception:
        result = _audit_shell(required, "missing", "audit_exception", as_of)
        return _strict_result(result) or _audit_shell(
            required, "missing", "audit_serialization_failure", as_of
        )

    selected = eligible_rows[-required:]
    # ``missing_rows`` includes rows outside the selected tail; expose only
    # selected-window progress so X/20 cannot be inflated by stale history.
    selected_missing = sum(
        1 for row in selected if not row.get("stored_complete")
    )
    selected_stored = sum(
        1 for row in selected if row.get("stored_complete")
    )
    selected_matches = sum(
        1 for row in selected if row.get("recalculation_match")
    )
    selected_mismatch = sum(
        1
        for row in selected
        if row.get("stored_complete") and not row.get("recalculation_match")
    )
    deltas = [
        float(row["delta"])
        for row in selected
        if isinstance(row.get("delta"), (int, float))
        and not isinstance(row.get("delta"), bool)
        and math.isfinite(float(row["delta"]))
    ]
    if not selected:
        status = "insufficient_observation_days"
    elif selected_stored < required:
        status = "insufficient_observation_days"
    elif selected_mismatch:
        status = "recalculation_mismatch"
    else:
        status = "ready_for_manual_review"

    result = _audit_shell(required, status, None, as_of)
    result.update({
        "valid_days": selected_stored,
        "stored_complete_days": selected_stored,
        "recomputable_days": len(selected),
        "complete_days": selected_matches,
        "missing_days": selected_missing,
        "mismatch_days": selected_mismatch,
        "recalculation_consistency_rate": (
            round(selected_matches / len(selected), 4) if selected else 0.0
        ),
        "summary": {
            "average_delta": round(sum(deltas) / len(deltas), 4)
            if deltas else None,
            "maximum_absolute_delta": round(max(map(abs, deltas)), 4)
            if deltas else None,
            "label_change_count": sum(
                bool(row.get("label_changed")) for row in selected
            ),
        },
        "correlations": {
            "breadth": _pearson(selected, "breadth"),
            "index": _pearson(selected, "index"),
        },
        "hypothetical_changes": _hypothetical_changes(selected),
        "daily": selected,
    })
    # ``missing_rows`` intentionally does not affect the gate directly; rows
    # outside the rolling required-day tail are not current audit progress.
    del missing_rows
    native = _strict_result(result)
    if native is not None:
        return native
    return _audit_shell(required, "missing", "audit_serialization_failure", as_of)


def _derive_as_of_date(reports, current_report=None):
    if isinstance(current_report, Mapping):
        current_date = _date_text(current_report.get("date"))
        if current_date is not None:
            return current_date
    dates = []
    if isinstance(reports, Mapping):
        dates.extend(reports.keys())
    elif isinstance(reports, (list, tuple)):
        for item in reports:
            if not isinstance(item, Mapping):
                continue
            if "report" in item:
                dates.append(item.get("trade_date", item.get("date")))
            else:
                dates.append(item.get("trade_date", item.get("date")))
    normalized = [value for value in (_date_text(item) for item in dates) if value]
    return max(normalized) if normalized else None


def evaluate_shadow_reports(
    reports,
    required_days=REQUIRED_DAYS,
    *,
    current_report=None,
    as_of_date=None,
):
    """Compatibility adapter for the legacy list-based evaluator.

    It deliberately delegates to the same normalizer and audit implementation
    used by the report page; no file-system access is performed here.
    """

    as_of = _date_text(as_of_date) or _derive_as_of_date(
        reports,
        current_report=current_report,
    )
    normalized = normalize_historical_reports(
        reports,
        current_report=current_report,
        as_of_date=as_of,
    )
    return evaluate_psy12_shadow_audit(normalized, required_days=required_days)


__all__ = [
    "normalize_historical_reports",
    "evaluate_psy12_shadow_audit",
    "evaluate_shadow_reports",
    "PSY12_AUDIT_KEYS",
    "SHADOW_AUDIT_KEYS",
]
