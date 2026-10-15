"""Bounded, dated evidence for the observation-only extreme icepoint card.

The market-history database and formal sentiment are deliberately untouched.
Only explicit same-day gateway fields and an existing full-market quote snapshot
can become evidence here; gateway ``latest`` fields are ignored.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .identity import normalize_identity
from .preclose_schedule import is_trading_day
from .quote_sources import symbol, valid_quote


CN = timezone(timedelta(hours=8))
GATEWAY_URL = "https://openapi.iwencai.com/v1/query2data"
INDEX_CODE = "883957.TI"
INDEX_NAME = "同花顺全A(沪深京)"
REQUEST_TIMEOUT = 8
MAX_REQUESTS = 3
_STOCK_SYMBOL = re.compile(r"([0-9]{6})\.(SH|SZ|BJ)\Z")


class IcepointSourceError(ValueError):
    """The supplied result cannot prove the requested dated observation."""


def _stamp(value):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("naive timestamp")
        return stamp.astimezone(CN)
    except (TypeError, ValueError, OverflowError) as exc:
        raise IcepointSourceError("invalid_evidence_timestamp") from exc


def _date_label(day):
    try:
        stamp = datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise IcepointSourceError("invalid_trade_date") from exc
    return "{}年{}月{}日".format(stamp.year, stamp.month, stamp.day)


def _trade_dates(dates):
    if (not isinstance(dates, (list, tuple)) or len(dates) != 6
            or not all(isinstance(day, str) for day in dates)
            or list(dates) != sorted(set(dates))):
        raise IcepointSourceError("six_verified_trade_dates_required")
    for day in dates:
        _date_label(day)
    # Use the existing reviewed exchange closure guard. Unknown calendar years
    # fail closed there; an arbitrary six-date selection cannot self-certify.
    expected = []
    current = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    for _ in range(30):
        if is_trading_day(current.isoformat(), ""):
            expected.append(current.isoformat())
            if len(expected) == 6:
                break
        current -= timedelta(days=1)
    if list(reversed(expected)) != list(dates):
        raise IcepointSourceError("nonconsecutive_trading_dates")
    return list(dates)


def turnover_query(trade_dates):
    days = _trade_dates(trade_dates)
    return "同花顺全A(沪深京)883957，" + "，".join(
        _date_label(day) + "成交额" for day in days)


def breadth_query(report_date):
    label = _date_label(report_date)
    return "同花顺全A(沪深京)的{}上涨家数，{}下跌家数，{}平盘家数".format(
        label, label, label)


def suspended_query(report_date):
    return _date_label(report_date) + "停牌的A股，股票代码，股票简称，" + _date_label(report_date) + "停牌原因"


def _complete_rows(payload, query, *, expected_count=None):
    # The gateway natively returns datas/code_count/chunks_info. CLI-only
    # success/query/page/has_more fields are checked when present, never
    # claimed as native response fields or required from the live endpoint.
    if (not isinstance(payload, dict)
            or ("success" in payload and payload["success"] is not True)
            or ("query" in payload and payload["query"] != query)
            or ("page" in payload and str(payload["page"]) != "1")
            or ("has_more" in payload and payload["has_more"] is not False)
            or not isinstance(payload.get("datas"), list)):
        raise IcepointSourceError("incomplete_gateway_response")
    rows = payload["datas"]
    count, returned = payload.get("code_count"), payload.get("returned_count")
    if (isinstance(count, bool) or not isinstance(count, int) or count != len(rows)
            or ("returned_count" in payload
                and (isinstance(returned, bool) or not isinstance(returned, int)
                     or returned != len(rows)))
            or (expected_count is not None and count != expected_count)):
        raise IcepointSourceError("incomplete_gateway_page")
    if not all(isinstance(row, dict) for row in rows):
        raise IcepointSourceError("invalid_gateway_row")
    return rows


def _index_row(payload, query):
    row = _complete_rows(payload, query, expected_count=1)[0]
    if row.get("指数代码") != INDEX_CODE or row.get("指数简称") != INDEX_NAME:
        raise IcepointSourceError("wrong_gateway_index")
    return row


def _positive_amount(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 10_000_000_000
            or value > 1_000_000_000_000_000):
        # The fixed all-A index returns CNY, not a human-formatted number of
        # 亿元. This broad scale check makes an accidental unit switch unknown.
        raise IcepointSourceError("invalid_dated_cny_amount")
    return value


def _count(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or int(value) != value):
        raise IcepointSourceError("invalid_dated_count")
    return int(value)


def parse_turnover_response(payload, trade_dates, retrieved_at):
    """Use only the six requested full-A date columns, in yuan."""
    days = _trade_dates(trade_dates)
    acquired = _stamp(retrieved_at)
    if acquired.date().isoformat() < days[-1] or acquired.hour < 15 and acquired.date().isoformat() == days[-1]:
        raise IcepointSourceError("turnover_not_closed")
    row = _index_row(payload, turnover_query(days))
    amounts = [_positive_amount(row.get("成交额[{}]".format(day.replace("-", ""))))
               for day in days]
    return {"date": days[-1], "market_date": days[-1], "market_phase": "closed",
            "as_of": acquired.isoformat(), "retrieved_at": acquired.isoformat(),
            "source": "wencai", "source_code": INDEX_CODE,
            "scope": "all_a_cny", "amount_unit": "CNY",
            "evidence_contract": "provider_aggregate_v1",
            "current": amounts[-1], "prior": amounts[:-1], "prior_dates": days[:-1],
            "quality": "comparable", "trading_days_verified": True, "complete": True}


def parse_breadth_response(payload, report_date):
    row = _index_row(payload, breadth_query(report_date))
    compact = report_date.replace("-", "")
    return {key: _count(row.get("{}家数[{}]".format(label, compact)))
            for key, label in (("advance_count", "上涨"),
                               ("decline_count", "下跌"), ("flat_count", "平盘"))}


def parse_suspended_response(payload, report_date):
    rows = _complete_rows(payload, suspended_query(report_date))
    identities = set()
    for row in rows:
        match = _STOCK_SYMBOL.fullmatch(str(row.get("股票代码") or ""))
        if not match or row.get("停牌[{}]".format(report_date.replace("-", ""))) is not True:
            raise IcepointSourceError("invalid_dated_suspension")
        try:
            identity = normalize_identity({"asset_type": "stock", "exchange": match.group(2),
                                           "code": match.group(1)})
            symbol(identity.as_dict())
        except (TypeError, ValueError) as exc:
            raise IcepointSourceError("invalid_suspended_identity") from exc
        if identity.key in identities:
            raise IcepointSourceError("duplicate_suspended_identity")
        identities.add(identity.key)
    return identities


def _verified_quotes(snapshot, report_date, retrieved_at):
    if not isinstance(snapshot, dict):
        raise IcepointSourceError("missing_quote_snapshot")
    rows = snapshot.get("rows")
    diagnostics = snapshot.get("diagnostics")
    acquired = _stamp(retrieved_at)
    stamp = _stamp(snapshot.get("fetched_at"))
    if (not isinstance(rows, list) or not isinstance(diagnostics, dict)
            or snapshot.get("schema_version") != 1
            or snapshot.get("universe_source") not in ("sina_hs_a", "eastmoney")
            or diagnostics.get("universe_source") != snapshot.get("universe_source")
            or diagnostics.get("complete") is not True
            or any(diagnostics.get(key) != len(rows) for key in ("requested", "fetched", "unique"))
            or snapshot.get("requested") != len(rows)
            or stamp.date().isoformat() != report_date or stamp.hour < 15
            or stamp > acquired + timedelta(seconds=60)):
        raise IcepointSourceError("unverified_quote_snapshot")
    valid = {}
    unknown = set()
    seen = set()
    for row in rows:
        try:
            identity = normalize_identity(row)
            symbol(identity.as_dict())
        except (TypeError, ValueError, KeyError) as exc:
            raise IcepointSourceError("invalid_quote_identity") from exc
        if identity.key in seen:
            raise IcepointSourceError("duplicate_quote_identity")
        seen.add(identity.key)
        change = row.get("change_pct")
        if (row.get("quote_status") == "valid" and row.get("price_basis") == "raw"
                and valid_quote(row, stamp)
                and not isinstance(change, bool) and isinstance(change, (int, float))
                and math.isfinite(change)):
            valid[identity.key] = change
        else:
            unknown.add(identity.key)
    return valid, unknown, len(rows), stamp


def build_breadth_evidence(snapshot, breadth_payload, suspended_payload,
                           report_date, retrieved_at):
    """Verify trading breadth against every quote or dated suspension identity."""
    acquired = _stamp(retrieved_at)
    valid, unknown, snapshot_count, quote_stamp = _verified_quotes(
        snapshot, report_date, acquired)
    suspended = parse_suspended_response(suspended_payload, report_date)
    if suspended != unknown or suspended.intersection(valid):
        raise IcepointSourceError("suspension_quote_partition_mismatch")
    observed = {"advance_count": sum(value > 0 for value in valid.values()),
                "decline_count": sum(value < 0 for value in valid.values()),
                "flat_count": sum(value == 0 for value in valid.values())}
    if parse_breadth_response(breadth_payload, report_date) != observed:
        raise IcepointSourceError("aggregate_quote_breadth_mismatch")
    trading_count = len(valid)
    if sum(observed.values()) != trading_count or trading_count + len(suspended) != snapshot_count:
        raise IcepointSourceError("incomplete_trading_breadth")
    return {"date": report_date, "as_of": quote_stamp.isoformat(),
            "retrieved_at": acquired.isoformat(), "source": "quote_snapshot+wencai",
            "scope": "all_a", **observed, "valid_count": trading_count,
            "denominator": trading_count, "trading_count": trading_count,
            "quote_snapshot_count": snapshot_count, "suspended_count": len(suspended),
            "unknown_count": 0, "complete": True}


def _sha(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _gateway_request(query, limit, headers, timeout):
    body = json.dumps({"query": query, "page": "1", "limit": str(limit),
                       "is_cache": "1", "expand_index": "true"}).encode("utf-8")
    request = urllib.request.Request(GATEWAY_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise IcepointSourceError("gateway_response_too_large")
        return json.loads(raw.decode("utf-8"))


def _headers():
    key = os.environ.get("IWENCAI_API_KEY")
    if not key:
        raise IcepointSourceError("iwencai_key_unavailable")
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json",
            "X-Claw-Call-Type": "normal", "X-Claw-Skill-Id": "hithink-market-query",
            "X-Claw-Skill-Version": "1.0.0", "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none", "X-Claw-Trace-Id": secrets.token_hex(32)}


def _cache_path(cache_dir, report_date, kind):
    return Path(cache_dir) / "icepoint-{}-{}.json".format(report_date, kind)


def _read_cache(path, report_date, kind, query, observed_at, historical):
    try:
        record = json.loads(path.read_text())
        stamp = _stamp(record["retrieved_at"])
        if (record.get("schema_version") != 1 or record.get("report_date") != report_date
                or record.get("kind") != kind or record.get("query") != query
                or record.get("sha256") != _sha(record.get("payload"))
                or stamp > observed_at + timedelta(seconds=60)
                or (not historical and (stamp.date().isoformat() != report_date or stamp.hour < 15))):
            return None
        return record["payload"], stamp, record["sha256"]
    except (OSError, ValueError, KeyError, TypeError, IcepointSourceError):
        return None


def _write_cache(path, report_date, kind, query, payload, retrieved_at):
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": 1, "report_date": report_date, "kind": kind,
              "query": query, "retrieved_at": retrieved_at.isoformat(),
              "sha256": _sha(payload), "payload": payload}
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                                         prefix=".icepoint-", suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            json.dump(record, tmp, ensure_ascii=False, sort_keys=True, allow_nan=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def collect_missing_icepoint_evidence(report_date, observed_at, *, trade_dates,
                                       quote_cache_path, cache_dir, need_turnover,
                                       need_breadth, allow_historical=False,
                                       transport=None, clock=None):
    """At most three single-page requests, only for requested closed observations.

    ``trade_dates`` must come from the caller's already verified stock/index
    trading windows, not from a user-supplied date list.
    """
    result = {"turnover": None, "breadth": None, "provenance": {}, "errors": []}
    try:
        now = _stamp(observed_at)
        if (now.date().isoformat() < report_date or
                (not allow_historical and now.date().isoformat() != report_date) or
                (now.date().isoformat() == report_date and now.hour < 15)):
            raise IcepointSourceError("outside_closed_report_date")
    except IcepointSourceError as exc:
        result["errors"].append(str(exc))
        return result
    days = []
    if need_turnover:
        try:
            days = _trade_dates(trade_dates)
            if days[-1] != report_date:
                raise IcepointSourceError("report_trade_date_mismatch")
        except IcepointSourceError as exc:
            result["errors"].append("turnover:{}".format(exc))
            need_turnover = False
    transport = transport or _gateway_request
    clock = clock or (lambda: datetime.now(CN))
    calls = 0

    def obtain(kind, query, limit):
        nonlocal calls
        path = _cache_path(cache_dir, report_date, kind) if cache_dir is not None else None
        cached = _read_cache(path, report_date, kind, query, now, allow_historical) if path else None
        if cached:
            payload, stamp, digest = cached
            result["provenance"][kind] = {"retrieved_at": stamp.isoformat(),
                                          "sha256": digest, "cached": True}
            return payload, stamp, path, True
        if calls >= MAX_REQUESTS:
            raise IcepointSourceError("request_budget_exhausted")
        calls += 1
        payload = transport(query, limit, _headers(), REQUEST_TIMEOUT)
        stamp = _stamp(clock())
        if stamp > now + timedelta(seconds=60):
            raise IcepointSourceError("request_clock_after_observation")
        result["provenance"][kind] = {"retrieved_at": stamp.isoformat(),
                                      "sha256": _sha(payload), "cached": False}
        return payload, stamp, path, False

    def persist(kind, query, payload, stamp, path, was_cached):
        if path and not was_cached:
            _write_cache(path, report_date, kind, query, payload, stamp)

    if need_turnover:
        query = turnover_query(days)
        try:
            payload, stamp, path, cached = obtain("turnover", query, 5)
            result["turnover"] = parse_turnover_response(payload, days, stamp)
            persist("turnover", query, payload, stamp, path, cached)
        except (IcepointSourceError, OSError, ValueError, TypeError,
                TimeoutError, ConnectionError, urllib.error.URLError) as exc:
            reason = str(exc) if isinstance(exc, IcepointSourceError) else type(exc).__name__
            result["errors"].append("turnover:{}".format(reason))

    if need_breadth:
        try:
            snapshot = json.loads(Path(quote_cache_path).read_text())
            _verified_quotes(snapshot, report_date, now)
            query = breadth_query(report_date)
            payload, stamp, path, cached = obtain("breadth", query, 5)
            parse_breadth_response(payload, report_date)
            persist("breadth", query, payload, stamp, path, cached)
            suspended = suspended_query(report_date)
            stopped, stop_stamp, stop_path, stop_cached = obtain("suspended", suspended, 100)
            parse_suspended_response(stopped, report_date)
            persist("suspended", suspended, stopped, stop_stamp, stop_path, stop_cached)
            result["breadth"] = build_breadth_evidence(
                snapshot, payload, stopped, report_date, max(stamp, stop_stamp))
        except (IcepointSourceError, OSError, ValueError, TypeError,
                TimeoutError, ConnectionError, urllib.error.URLError) as exc:
            reason = str(exc) if isinstance(exc, IcepointSourceError) else type(exc).__name__
            result["errors"].append("breadth:{}".format(reason))
    return result
