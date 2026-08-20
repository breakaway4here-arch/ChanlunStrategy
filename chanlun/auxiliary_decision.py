"""Deterministic fact contracts for the auxiliary decision cockpit."""

from collections import defaultdict
from datetime import datetime


LIMIT_UP_STATUSES = {
    "verified_complete",
    "verified_empty",
    "partial",
    "missing",
    "error",
}


def _non_negative_int(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _compact_date(value):
    return str(value or "").strip().replace("-", "")


def _theme_groups(items):
    grouped = defaultdict(list)
    for item in items:
        sector = str(item.get("sector") or "").strip()
        if sector:
            grouped[sector].append(str(item.get("code") or ""))
    result = [
        {"name": name, "count": len(codes), "codes": sorted(codes)}
        for name, codes in grouped.items()
    ]
    result.sort(key=lambda row: (-row["count"], row["name"]))
    return result


def _leader_rows(report_date, items, limit=6):
    def sort_key(item):
        boards = _non_negative_int(item.get("lianban")) or 0
        first_time = str(item.get("first_time") or "99:99")
        fund = item.get("fund") or 0
        try:
            fund = float(fund)
        except (TypeError, ValueError):
            fund = 0
        return (-boards, first_time, -fund, str(item.get("code") or ""))

    leaders = []
    for item in sorted(items, key=sort_key)[:limit]:
        code = str(item.get("code") or "")
        leaders.append({
            "code": code,
            "name": str(item.get("name") or ""),
            "sector": str(item.get("sector") or ""),
            "lianban": _non_negative_int(item.get("lianban")) or 0,
            "first_time": str(item.get("first_time") or ""),
            "link_type": "limit_up_leader",
            "evidence_ref": "limit-up:{}:{}".format(report_date, code),
        })
    return leaders


def build_limit_up_snapshot(
    report_date,
    items,
    diagnostics,
    limit_down_total=None,
    as_of=None,
    generated_at=None,
):
    """Build an auditable limit-up fact snapshot without inferring missing data.

    ``verified_empty`` is emitted only when the upstream total is verified as
    zero. A non-zero total with no parsed rows is an error, not an empty market.
    """
    items = [dict(item) for item in (items or []) if isinstance(item, dict)]
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    raw_total = _non_negative_int(diagnostics.get("raw_total"))
    parsed_count = len(items)
    parse_error_count = _non_negative_int(
        diagnostics.get("parse_error_count")
    ) or 0
    evidence_date = str(diagnostics.get("evidence_date") or "")
    data_status = str(diagnostics.get("data_status") or "missing")
    errors = []
    if diagnostics.get("error"):
        errors.append(str(diagnostics["error"]))

    if evidence_date and _compact_date(evidence_date) != _compact_date(report_date):
        status = "error"
        errors.append(
            "date mismatch: expected {}, got {}".format(
                report_date, evidence_date
            )
        )
    elif data_status != "verified":
        status = "missing" if data_status == "missing" else "error"
    elif raw_total is None:
        status = "missing"
        errors.append("verified upstream total is missing")
    elif raw_total == 0:
        if parsed_count == 0 and parse_error_count == 0:
            status = "verified_empty"
        else:
            status = "error"
            errors.append("zero total conflicts with parsed rows or errors")
    elif parsed_count == 0:
        status = "error"
        errors.append("non-zero total has no parsed items")
    elif parsed_count > raw_total:
        status = "error"
        errors.append("parsed item count exceeds upstream total")
    elif parsed_count == raw_total and parse_error_count == 0:
        status = "verified_complete"
    else:
        status = "partial"

    if raw_total is None:
        coverage = 0.0
    elif raw_total == 0:
        coverage = 1.0 if status == "verified_empty" else 0.0
    else:
        coverage = round(parsed_count / float(raw_total), 4)

    generated_at = generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    snapshot = {
        "date": str(report_date or ""),
        "as_of": as_of or diagnostics.get("as_of") or str(report_date or ""),
        "generated_at": generated_at,
        "source": diagnostics.get("source") or "eastmoney_limit_pools",
        "status": status,
        "raw_total": raw_total,
        "limit_down_total": _non_negative_int(limit_down_total),
        "parsed_count": parsed_count,
        "parse_error_count": parse_error_count,
        "coverage": coverage,
        "items": items,
        "theme_groups": _theme_groups(items),
        "leaders": _leader_rows(str(report_date or ""), items),
        "error": "; ".join(dict.fromkeys(errors)),
    }
    assert snapshot["status"] in LIMIT_UP_STATUSES
    return snapshot
