"""Fail-closed position metadata and holding-risk intersection.

Global sell signals remain useful research evidence, but they are not user
actions.  A signal becomes a holding risk only when it intersects a fresh,
explicitly confirmed position from this contract.
"""

import json
import math
import os
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_POSITION_BOOK_PATH = os.path.join(
    BASE_DIR, "config", "position_book.json"
)
POSITION_BOOK_ENV = "CHANLUN_POSITION_BOOK_PATH"
PUBLIC_HOLDING_RISK_ENV = "CHANLUN_PUBLISH_HOLDING_RISK_CODES"


def _parse_time(value, field):
    text = str(value or "").strip()
    if not text:
        raise ValueError("{} is required".format(field))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("{} must be an ISO-8601 timestamp".format(field))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("{} must include a timezone".format(field))
    return parsed, parsed.isoformat(timespec="seconds")


def _finite_number(value, field, *, required=False, positive=False):
    if value is None or value == "":
        if required:
            raise ValueError("{} is required".format(field))
        return None
    if isinstance(value, bool):
        raise ValueError("{} must be numeric".format(field))
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("{} must be numeric".format(field))
    if not math.isfinite(number):
        raise ValueError("{} must be finite".format(field))
    if positive and number <= 0:
        raise ValueError("{} must be positive".format(field))
    return number


def _valid_a_share_code(value):
    code = str(value or "").strip()
    return (
        len(code) == 6
        and code.isdigit()
        and code.startswith(("0", "3", "4", "6", "8", "92"))
    )


def _empty_book(status, reason="", path=""):
    return {
        "schema_version": "1",
        "status": status,
        "reason": str(reason or ""),
        "path": str(path or ""),
        "source": "",
        "as_of": "",
        "confirmed_at": "",
        "stale_after": "",
        "items": [],
        "position_count": 0,
        "confirmed_count": 0,
    }


def normalize_position_book(payload, *, now=None, name_map=None, path=""):
    """Validate a position snapshot and derive its fail-closed status."""
    if not isinstance(payload, dict):
        raise ValueError("position book must be an object")
    if str(payload.get("schema_version") or "") != "1":
        raise ValueError("unsupported position book schema_version")

    source = str(payload.get("source") or "").strip()
    if not source:
        raise ValueError("source is required")
    if len(source) > 100:
        raise ValueError("source is too long")

    as_of_dt, as_of = _parse_time(payload.get("as_of"), "as_of")
    confirmed_dt, confirmed_at = _parse_time(
        payload.get("confirmed_at"), "confirmed_at"
    )
    stale_dt, stale_after = _parse_time(
        payload.get("stale_after"), "stale_after"
    )
    now_dt, _ = _parse_time(
        now or datetime.now().astimezone().isoformat(timespec="seconds"),
        "now",
    )
    if as_of_dt > confirmed_dt:
        raise ValueError("confirmed_at cannot be earlier than as_of")
    if confirmed_dt > stale_dt:
        raise ValueError("stale_after cannot be earlier than confirmed_at")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("position book items must be a list")
    if len(raw_items) > 100:
        raise ValueError("position book cannot contain more than 100 items")

    trusted_names = {
        str(code): str(name)
        for code, name in dict(name_map or {}).items()
        if str(code) and str(name)
    }
    seen = set()
    items = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError("position {} must be an object".format(index))
        code = str(raw.get("code") or "").strip()
        if not _valid_a_share_code(code):
            raise ValueError("invalid A-share code: {}".format(code))
        if code in seen:
            raise ValueError("duplicate position code: {}".format(code))
        seen.add(code)
        confirmed = raw.get("confirmed", False)
        if not isinstance(confirmed, bool):
            raise ValueError("confirmed must be boolean for {}".format(code))
        quantity = _finite_number(
            raw.get("quantity"), "quantity for {}".format(code),
            required=True, positive=True,
        )
        cost_price = _finite_number(
            raw.get("cost_price"), "cost_price for {}".format(code),
            positive=True,
        )
        supplied_name = str(raw.get("name") or "").strip()
        items.append({
            "code": code,
            "name": trusted_names.get(code) or supplied_name or code,
            "quantity": quantity,
            "cost_price": cost_price,
            "confirmed": confirmed,
            "note": str(raw.get("note") or "").strip()[:500],
        })

    confirmed_count = sum(bool(item["confirmed"]) for item in items)
    if now_dt >= stale_dt:
        status = "stale"
        reason = "position snapshot expired"
    elif now_dt < as_of_dt or now_dt < confirmed_dt:
        status = "unconfirmed"
        reason = "position snapshot is not confirmed for this as-of time"
    elif not items:
        status = "empty"
        reason = "confirmed position book is empty"
    elif not confirmed_count:
        status = "unconfirmed"
        reason = "no position item is explicitly confirmed"
    else:
        status = "fresh"
        reason = "fresh confirmed positions available"

    return {
        "schema_version": "1",
        "status": status,
        "reason": reason,
        "path": str(path or ""),
        "source": source,
        "as_of": as_of,
        "confirmed_at": confirmed_at,
        "stale_after": stale_after,
        "items": items,
        "position_count": len(items),
        "confirmed_count": confirmed_count,
    }


def load_position_book(path=None, *, now=None, name_map=None):
    """Load an optional position file; an absent file means unconfigured."""
    resolved = os.fspath(
        path
        or os.environ.get(POSITION_BOOK_ENV)
        or DEFAULT_POSITION_BOOK_PATH
    )
    if not os.path.exists(resolved):
        return _empty_book(
            "unconfigured",
            reason="position book is not configured",
            path=resolved,
        )
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("cannot load position book: {}".format(exc))
    return normalize_position_book(
        payload,
        now=now,
        name_map=name_map,
        path=resolved,
    )


def position_book_error_snapshot(error, path=""):
    """Convert a load/validation error into a visible fail-closed diagnostic."""
    if isinstance(error, ValueError):
        error_code = "invalid_config"
    elif isinstance(error, OSError):
        error_code = "read_error"
    else:
        error_code = "unknown_error"
    snapshot = _empty_book(
        "error",
        reason="position book validation failed closed",
        path="",
    )
    snapshot["error_code"] = error_code
    return snapshot


def _signal_reason(signal):
    labels = []
    for point in signal.get("sell_points") or []:
        if not isinstance(point, dict):
            continue
        point_type = str(point.get("type") or "").strip()
        reason = str(point.get("reason") or "").strip()
        label = (
            "{}：{}".format(point_type, reason)
            if point_type and reason
            else point_type or reason
        )
        if label and label not in labels:
            labels.append(label)
    if not labels and signal.get("divergence"):
        labels.append("背驰风险")
    if not labels:
        labels.append("全局结构风险信号")
    return "；".join(labels[:4])


def build_holding_risks(position_book, sell_signals):
    """Return only fresh-confirmed positions intersecting sell signals."""
    book = position_book if isinstance(position_book, dict) else {}
    if book.get("status") != "fresh":
        return []
    held = {
        str(item.get("code") or ""): item
        for item in book.get("items") or []
        if isinstance(item, dict)
        and item.get("confirmed") is True
        and _finite_number(item.get("quantity"), "quantity", positive=True)
        is not None
    }
    by_code = {}
    for signal in sell_signals or []:
        if not isinstance(signal, dict):
            continue
        code = str(signal.get("code") or "").strip()
        if code in held and code not in by_code:
            by_code[code] = signal

    risks = []
    for position in book.get("items") or []:
        code = str(position.get("code") or "")
        signal = by_code.get(code)
        if signal is None:
            continue
        risks.append({
            "code": code,
            "name": str(position.get("name") or signal.get("name") or code),
            "quantity": position.get("quantity"),
            "cost_price": position.get("cost_price"),
            "sector": str(signal.get("sector") or ""),
            "trend_type": str(signal.get("trend_type") or ""),
            "reason": _signal_reason(signal),
            "action": "复核减仓或退出条件",
            "position_source": str(book.get("source") or ""),
            "position_as_of": str(book.get("as_of") or ""),
            "confirmed_at": str(book.get("confirmed_at") or ""),
            "stale_after": str(book.get("stale_after") or ""),
        })
    return risks


def build_public_holding_risks(
    holding_risks, *, allow_identifiers=False
):
    """Project local risks into a static-report-safe, explicit opt-in shape.

    The default publishes no holding identifiers. Even after explicit opt-in,
    position size and cost never enter the static report payload.
    """
    if not allow_identifiers:
        return []
    allowed_fields = (
        "code",
        "name",
        "sector",
        "trend_type",
        "reason",
        "action",
        "position_source",
        "position_as_of",
        "confirmed_at",
        "stale_after",
    )
    projected = []
    for risk in holding_risks or []:
        if not isinstance(risk, dict):
            continue
        code = str(risk.get("code") or "").strip()
        if not _valid_a_share_code(code):
            continue
        row = {
            field: risk.get(field)
            for field in allowed_fields
            if risk.get(field) is not None
        }
        row["code"] = code
        row["privacy_scope"] = "explicit_identifier_opt_in"
        projected.append(row)
    return projected


def build_public_position_diagnostics(
    position_book, holding_risks=None, *, details_published=False
):
    """Explain fail-closed state without leaking private position metadata."""
    book = position_book if isinstance(position_book, dict) else {}
    status = str(book.get("status") or "unconfigured")
    if status == "fresh":
        if details_published:
            return {
                "status": "explicit_opt_in",
                "message": "已显式允许公开风险命中股票标识；数量和成本仍不发布",
                "publication_status": "identifier_only",
                "holding_risk_count": len(holding_risks or []),
            }
        return {
            "status": "private",
            "message": "持仓详情未写入静态报告；命中动作已隐藏",
            "publication_status": "withheld",
        }
    messages = {
        "unconfigured": "未配置已确认持仓；不显示卖出动作",
        "empty": "已确认空持仓；不显示卖出动作",
        "stale": "持仓快照已过期；已禁止输出动作",
        "unconfirmed": "持仓尚未明确确认；已禁止输出动作",
        "error": "持仓配置校验失败；已禁止输出动作",
    }
    result = {
        "status": status,
        "message": messages.get(status, "持仓状态不可用；已禁止输出动作"),
        "publication_status": "none",
    }
    if status == "error":
        result["error_code"] = str(
            book.get("error_code") or "unknown_error"
        )
    return result


def summarize_position_book(position_book, holding_risks=None):
    """Produce diagnostics without creating user-facing placeholder actions."""
    book = position_book if isinstance(position_book, dict) else {}
    risks = (
        holding_risks
        if isinstance(holding_risks, list)
        else build_holding_risks(book, [])
    )
    return {
        "status": str(book.get("status") or "unconfigured"),
        "reason": str(book.get("reason") or ""),
        "source": str(book.get("source") or ""),
        "as_of": str(book.get("as_of") or ""),
        "confirmed_at": str(book.get("confirmed_at") or ""),
        "stale_after": str(book.get("stale_after") or ""),
        "position_count": int(book.get("position_count") or 0),
        "confirmed_count": int(book.get("confirmed_count") or 0),
        "holding_risk_count": len(risks),
    }
