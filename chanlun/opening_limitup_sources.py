"""Finite public-source adapters; no credentials, application imports or workers.

Coverage means the complete source-as-delivered XGB arrays, not a certified
exchange-wide census. Sina historical full-day amounts are sums of exactly 48
native 5m CNY bars (overlap rounding error < 4.54e-8 relative in the pilot).
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import signal
import re
import time as clock

from chanlun.opening_limitup import SHANGHAI, evaluate_opening_limitup, positive
from chanlun.preclose_schedule import is_trading_day

SINA_URL = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
XGB_URL = "https://flash-api.xuangubao.com.cn/api/pool/detail"
TENCENT_URL = "https://qt.gtimg.cn/"


def opening_facts_from_quotes(quotes, day):
    return {key: {"identity": key, "date": day, "basis": "raw", "fact_time": day + "T09:30:00+08:00",
                  "observed_at": q["quote_at"], "limit_verified": True, "limit_price": q["upper_limit"],
                  "open": q["open"], "source": "Tencent_native_open_f5_upper_f47",
                  "permitted_use": "immutable_open_and_static_upper_only_not_0940_quote"}
            for key, q in quotes.items() if q.get("date") == day and q.get("upper_verified") is True}


def normalize_coverage_quotes(text, day):
    """Native Tencent high/upper are only a monotone no-touch coverage check.

    They are NEVER a 09:40 stock price, first-seal timestamp or open-board proof.
    Current SH/SZ band crosscheck is enabled only for reviewed 2026-07-06 onward
    rules: main-board (including risk-warning)10%, STAR/ChiNext20%.
    Other periods/instruments stay unknown; no ST-name inference.
    """
    result = {}
    for variable, body in re.findall(r'v_((?:sh|sz|bj)\d{6})="([^"]*)";', text):
        fields = body.split("~")
        if len(fields) != 88 or fields[2] != variable[2:]:
            continue
        exchange, code = variable[:2].upper(), variable[2:]
        identity = exchange + "." + code
        if identity in result:
            return {}
        try:
            at = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
            prev, high, upper, op = (positive(fields[i]) for i in (4, 33, 47, 5))
            rate = None
            if "2026-07-06" <= day <= "2026-12-31":
                if exchange == "SH" and code.startswith(("600", "601", "603", "605")) or exchange == "SZ" and code.startswith(("000", "001", "002", "003")):
                    rate = Decimal("0.10")
                elif exchange == "SH" and code.startswith("688") or exchange == "SZ" and code.startswith(("300", "301")):
                    rate = Decimal("0.20")
            valid = bool(prev and prev >= Decimal("0.10") and high and upper and op and high >= op and high <= upper and rate
                         and (prev * (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == upper)
            if at.date().isoformat() != day:
                valid = False
            result[identity] = {"identity": identity, "date": at.date().isoformat(), "quote_at": at.isoformat(),
                                "day_high": fields[33], "upper_limit": fields[47], "upper_verified": valid, "open": fields[5], "prevclose": fields[4],
                                "source": "Tencent_native_f33_f47", "field_count": len(fields),
                                "permitted_use": "missing_event_no_touch_only_not_cutoff_quote"}
        except (ValueError, TypeError, ArithmeticError):
            continue
    return result


def verify_cohort_coverage(events, cohort, quotes):
    covered = {r["identity"] for r in events.get("items", [])}
    unknown, no_touch = [], []
    for row in cohort:
        key = row["identity"]
        if key in covered:
            continue
        q = quotes.get(key, {})
        try:
            at = datetime.fromisoformat(q.get("quote_at", ""))
            valid = (q.get("identity") == key and q.get("date") == events["date"]
                     and at.utcoffset() == timedelta(hours=8) and at.date().isoformat() == events["date"]
                     and at.time() >= time(9, 40) and q.get("upper_verified") is True
                     and positive(q.get("day_high")) and positive(q.get("upper_limit"))
                     and positive(q["day_high"]) < positive(q["upper_limit"]))
        except (ValueError, TypeError):
            valid = False
        (no_touch if valid else unknown).append(key)
    events.update(coverage_verified=not unknown and events.get("status") in ("verified_complete", "verified_empty"),
                  coverage_unknown=sorted(unknown), no_touch_proven=sorted(no_touch),
                  coverage_method="union_plus_missing_cohort_native_high_below_native_upper")


def _sessions(day, market_db):
    d = date.fromisoformat(day)
    if d.isoformat() != day or not is_trading_day(day, market_db):
        raise ValueError("unsupported_or_closed_calendar")
    dates = [day]
    for _ in range(45):
        if len(dates) == 6:
            return list(reversed(dates))
        d -= timedelta(days=1)
        if is_trading_day(d.isoformat(), market_db):
            dates.append(d.isoformat())
    raise ValueError("calendar_warmup_unavailable")


def _bar_times():
    return [t.strftime("%H:%M:%S") for start in (datetime(2000, 1, 1, 9, 35), datetime(2000, 1, 1, 13, 5))
            for t in (start + timedelta(minutes=5 * i) for i in range(24))]


def normalize_index(rows, day, market_db):
    dates = _sessions(day, market_db)
    if not isinstance(rows, list):
        raise ValueError("index_not_array")
    bars = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("day"), str):
            raise ValueError("invalid_index_row")
        at = row["day"]
        if at[:10] not in dates:
            continue
        if at[:10] == day and at[11:19] > "09:40:00":
            continue
        if at in bars or len(at) != 19:
            raise ValueError("duplicate_or_invalid_index_bar")
        try:
            parsed = datetime.strptime(at, "%Y-%m-%d %H:%M:%S")
            amount = Decimal(str(row.get("amount")))
        except (ValueError, ArithmeticError):
            raise ValueError("invalid_index_amount_or_date")
        if not amount.is_finite() or amount < 0 or not all(positive(row.get(k)) for k in ("open", "high", "low", "close")):
            raise ValueError("invalid_index_price_or_amount")
        if not positive(row["low"]) <= min(positive(row["open"]), positive(row["close"])) <= max(positive(row["open"]), positive(row["close"])) <= positive(row["high"]):
            raise ValueError("index_ohlc_conflict")
        if parsed.strftime("%H:%M:%S") not in _bar_times():
            raise ValueError("unexpected_index_bar_boundary")
        bars[at] = row
    sessions = []
    for d in dates:
        a, b = bars.get(d + " 09:35:00"), bars.get(d + " 09:40:00")
        expected = [d + " " + t for t in _bar_times()]
        complete = d < day and all(t in bars for t in expected)
        sessions.append({"date": d, "open": str(a["open"]) if a else None,
                         "close0940": str(b["close"]) if b else None,
                         "amount0940": format((Decimal(str(a["amount"])) + Decimal(str(b["amount"]))).normalize(), "f") if a and b else None,
                         "close": str(bars[expected[-1]]["close"]) if complete else None,
                         "amountday": format(sum((Decimal(str(bars[t]["amount"])) for t in expected), Decimal(0)).normalize(), "f") if complete else None,
                         "complete_session": complete,
                         "field_sources": {"opening": "native09:35+09:40", "amountday": "sum48_native_CNY_bars" if complete else None}})
    return ({"identity": "SH.000001", "instrument": "index", "source": "Sina_CN_MarketDataService_5m",
             "unit": "CNY", "amount_scope": "includes_auction", "sessions": sessions},
            {"status": "verified", "source": "preclose_schedule_readonly_calendar", "dates": dates})


def _identity(symbol):
    if not isinstance(symbol, str) or len(symbol) != 9 or not symbol[:6].isdigit():
        raise ValueError("invalid_native_symbol")
    exchange = {"SS": "SH", "SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(symbol[7:]) if symbol[6] == "." else None
    if exchange is None:
        raise ValueError("invalid_native_exchange")
    return {"identity": exchange + "." + symbol[:6], "code": symbol[:6], "exchange": exchange}


def _epoch(value, day, allow_zero=False):
    if allow_zero and value == 0:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError("invalid_native_epoch")
    at = datetime.fromtimestamp(value, SHANGHAI)
    if at.date().isoformat() != day or not time(9, 25) <= at.time() <= time(15):
        raise ValueError("wrong_event_session")
    return at.isoformat()


def _rows(payload):
    if not isinstance(payload, dict) or payload.get("code") != 20000 or not isinstance(payload.get("data"), list):
        raise ValueError("source_null_or_error")
    if payload.get("has_more") or payload.get("next_page"):
        raise ValueError("source_pagination_incomplete")
    rows = payload["data"]
    for key in ("total", "count"):
        if key in payload and payload[key] != len(rows):
            raise ValueError("source_count_mismatch")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("invalid_pool_row")
    return rows


def normalize_pool(payload, day):
    result = {"date": day, "source": "XGB", "coverage": "source_as_delivered", "status": "unavailable", "items": [], "total": None}
    try:
        items = []
        for row in _rows(payload):
            identity = _identity(row.get("symbol"))
            if type(row.get("limit_up_days")) is not int or row["limit_up_days"] <= 0:
                raise ValueError("invalid_board")
            _epoch(row.get("first_limit_up"), day)
            items.append({**identity, "name": str(row.get("stock_chi_name", "")), "board": row["limit_up_days"]})
        if len({r["identity"] for r in items}) != len(items):
            raise ValueError("duplicate_pool_identity")
        result.update(status="verified_complete" if items else "verified_empty", items=items, total=len(items))
    except (ValueError, TypeError, OverflowError) as exc:
        result["issues"] = [str(exc)]
    return result


def normalize_union(zt, zb, day):
    result = {"date": day, "source": "XGB", "coverage": "source_as_delivered", "coverage_verified": False, "scope": "limit_up_union_limit_up_broken", "status": "unavailable", "items": []}
    try:
        items = []
        for payload, end_state in ((zt, 1), (zb, 2)):
            for row in _rows(payload):
                identity = _identity(row.get("symbol"))
                first = _epoch(row.get("first_limit_up"), day)
                native = row.get("limit_timeline")
                timeline = native.get("items") if isinstance(native, dict) else None
                normalized = []
                if timeline is not None:
                    if not isinstance(timeline, list) or not timeline:
                        raise ValueError("empty_or_invalid_native_timeline")
                    stamps = []
                    for t in timeline:
                        if not isinstance(t, dict) or type(t.get("status")) is not int or t["status"] not in (1, 2):
                            raise ValueError("invalid_native_transition")
                        stamp = t.get("timestamp")
                        normalized.append({"at": _epoch(stamp, day), "state": "sealed" if t["status"] == 1 else "open"})
                        stamps.append((stamp, t["status"]))
                    if stamps[0][1] != 1 or stamps[-1][1] != end_state or any(a[0] >= b[0] or a[1] == b[1] for a, b in zip(stamps, stamps[1:])):
                        raise ValueError("native_timeline_order_or_pool_conflict")
                    seals = [at for at, state in stamps if state == 1]
                    breaks = [at for at, state in stamps if state == 2]
                    if (seals[0] != row.get("first_limit_up") or seals[-1] != row.get("last_limit_up")
                            or (breaks[0] if breaks else 0) != row.get("first_break_limit_up")
                            or (breaks[-1] if breaks else 0) != row.get("last_break_limit_up")
                            or type(row.get("break_limit_up_times")) is not int or len(breaks) != row["break_limit_up_times"]):
                        raise ValueError("native_timeline_summary_conflict")
                items.append({**identity, "name": str(row.get("stock_chi_name", "")), "first_at": first,
                              "timeline_complete": timeline is not None, "timeline": normalized})
        if len({r["identity"] for r in items}) != len(items):
            raise ValueError("duplicate_union_identity")
        result.update(status="verified_complete" if items else "verified_empty", items=items)
    except (ValueError, TypeError, OverflowError) as exc:
        result["issues"] = [str(exc)]
    return result


def _public_json(url, params, timeout):
    import requests
    started = datetime.now(SHANGHAI).isoformat()
    referer = "https://finance.sina.com.cn" if url == SINA_URL else "https://gu.qq.com" if url == TENCENT_URL else "https://xuangubao.cn"
    with requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0", "Referer": referer}, timeout=timeout, allow_redirects=False) as response:
        response.raise_for_status()
        body = response.content
        text = body.decode("gb18030" if url == TENCENT_URL else "utf-8")
        return (text if url == TENCENT_URL else json.loads(text, parse_float=str)), {"url": url, "params": params, "requested_at": started,
                                  "sha256": hashlib.sha256(body).hexdigest(), "raw_text": text, "encoding": "gb18030" if url == TENCENT_URL else "utf-8", "bytes": len(body)}


def collect_opening_evidence(day, market_db, *, fetch_json=None, monotonic=None, budget_seconds=45, live_day=None):
    """At most six requests, no retries. False environment stops after one.

    The CLI additionally enforces the absolute 09:40:45 collection deadline.
    SIGALRM gives each blocking request a real finite deadline without workers.
    """
    fetch = fetch_json or _public_json
    tick = monotonic or clock.monotonic
    start = tick()
    e = {"schema_version": 1, "trade_date": day, "issues": [], "sources": []}

    def get(url, params):
        remaining = budget_seconds - (tick() - start)
        if remaining <= 0:
            raise TimeoutError("collection_budget_exhausted")
        timeout = min(10.0, remaining)
        # Main CLI is one-shot Unix execution; no timeout background thread.
        previous = signal.getsignal(signal.SIGALRM)
        def expired(_signal, _frame):
            raise TimeoutError("source_deadline")
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            data, meta = fetch(url, params, timeout)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        e["sources"].append(meta)
        if tick() - start > budget_seconds:
            raise TimeoutError("collection_budget_exhausted")
        return data

    try:
        rows = get(SINA_URL, {"symbol": "sh000001", "scale": 5, "ma": "no", "datalen": 1023})
        e["index"], e["calendar"] = normalize_index(rows, day, market_db)
    except Exception as exc:
        e["issues"].append("index_unavailable:" + type(exc).__name__)
    if any(v is False for v in evaluate_opening_limitup(e)["environment"]["gates"].values()):
        e["issues"].append("cohorts_events_not_collected_environment_false")
        return e
    try:
        ds = e.get("calendar", {}).get("dates") or _sessions(day, market_db)
        e["calendar"] = {"status": "verified", "source": "preclose_schedule_readonly_calendar", "dates": ds}
        e["pools"] = {}
        for key, d in (("P", ds[-3]), ("Y", ds[-2])):
            e["pools"][key] = normalize_pool(get(XGB_URL, {"pool_name": "limit_up", "date": d}), d)
        p = evaluate_opening_limitup(e)["promotion"]
        if p["status"] != "ready" or p["target_board"] is None:
            return e
        today = live_day or datetime.now(SHANGHAI).date().isoformat()
        params = {} if day == today else {"date": day}
        zt = get(XGB_URL, {"pool_name": "limit_up", **params})
        zb = get(XGB_URL, {"pool_name": "limit_up_broken", **params})
        e["events"] = normalize_union(zt, zb, day)
        target = p["target_board"]
        cohort = [r for r in e["pools"]["Y"]["items"] if r["board"] == target - 1]
        if cohort:
            query = ",".join(r["exchange"].lower() + r["code"] for r in cohort)
            text = get(TENCENT_URL, {"q": query})
            e["coverage_quotes"] = normalize_coverage_quotes(text, day)
        else:
            e["coverage_quotes"] = {}
        e["opening_facts"] = opening_facts_from_quotes(e["coverage_quotes"], day)
        verify_cohort_coverage(e["events"], cohort, e["coverage_quotes"])
    except Exception as exc:
        e["issues"].append("pool_or_events_unavailable:" + type(exc).__name__)
    return e
