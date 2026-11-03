"""Independent 09:40 decision. Canonical evidence in, JSON-safe decision out.

No I/O, current-price substitution, portfolio action, or notification occurs here.
Calendar dates are verified by the source boundary, never inferred from sparse bars.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import re

STRATEGY_ID = "opening-limitup-b-0940-v1"
SHANGHAI = timezone(timedelta(hours=8))


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        v = Decimal(str(value))
        return v if v.is_finite() and v > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _at(value, day):
    try:
        d = datetime.fromisoformat(value)
        if d.utcoffset() != timedelta(hours=8) or d.date().isoformat() != day:
            return None
        return d
    except (TypeError, ValueError):
        return None


def _identity(row):
    return (isinstance(row, dict) and row.get("exchange") in ("SH", "SZ", "BJ")
            and isinstance(row.get("code"), str)
            and re.fullmatch(r"\d{6}", str(row.get("code", ""))) is not None
            and row.get("identity") == row["exchange"] + "." + row["code"])


def _calendar(e):
    c = e.get("calendar", {})
    ds = c.get("dates", [])
    try:
        parsed = [date.fromisoformat(d) for d in ds]
        valid = (c.get("status") == "verified" and bool(c.get("source")) and len(ds) == 6
                 and sorted(set(ds)) == ds and ds[-1] == e.get("trade_date")
                 and all(p.weekday() < 5 and p.isoformat() == d for p, d in zip(parsed, ds)))
    except (ValueError, TypeError):
        valid = False
    return ds if valid else []


def environment(e, ds):
    gates = dict.fromkeys(("opening_allowed", "red0940", "opening_increment", "forecast_increment"))
    result = {"gates": gates, "issues": [], "forecast": None, "opening_minimum_return": "-0.001"}
    idx = e.get("index", {})
    if not ds or any(idx.get(k) != v for k, v in (("identity", "SH.000001"), ("instrument", "index"),
            ("unit", "CNY"), ("amount_scope", "includes_auction"))) or not idx.get("source"):
        result["issues"].append("index_identity_or_calendar_unknown")
        return result
    rows = idx.get("sessions", [])
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows) or len({r.get("date") for r in rows}) != len(rows):
        result["issues"].append("duplicate_or_invalid_index_sessions")
        return result
    sessions = {r.get("date"): r for r in rows}
    d, y = sessions.get(ds[-1], {}), sessions.get(ds[-2], {})
    prev, op, close = positive(y.get("close")), positive(d.get("open")), positive(d.get("close0940"))
    if prev and op:
        # Fixed B: inclusive -0.1%. Integer cross-products avoid division or
        # floating-point thresholds; preserve all input coefficient digits.
        with localcontext() as context:
            context.prec = max(len(op.as_tuple().digits), len(prev.as_tuple().digits)) + 4
            gates["opening_allowed"] = op * 1000 >= prev * 999
    if prev and close:
        gates["red0940"] = close > prev
    opening, previous = positive(d.get("amount0940")), positive(y.get("amount0940"))
    if opening and previous:
        gates["opening_increment"] = opening > previous
    ratios = []
    for day in ds[:-1]:
        s = sessions.get(day, {})
        a, total = positive(s.get("amount0940")), positive(s.get("amountday"))
        if s.get("complete_session") is True and a and total and a <= total:
            ratios.append(Fraction(a) / Fraction(total))
    if len(ratios) == 5 and opening and positive(y.get("amountday")):
        median = sorted(ratios)[2]
        forecast = Fraction(opening) / median
        result["forecast"] = str(Decimal(forecast.numerator) / Decimal(forecast.denominator))
        gates["forecast_increment"] = forecast > Fraction(positive(y["amountday"]))
    for key, value in gates.items():
        if value is None:
            result["issues"].append(key + "_unknown")
    return result


def promotion(e, ds):
    result = {"status": "unknown", "target_board": None, "r2": None, "r3": None, "issues": []}
    if not ds:
        result["issues"] = ["calendar_unknown"]
        return result, {}
    pools, parsed = e.get("pools", {}), {}
    for label, day in (("P", ds[-3]), ("Y", ds[-2])):
        p = pools.get(label, {})
        items = p.get("items")
        valid = (p.get("date") == day and p.get("source") == "XGB"
                 and p.get("status") in ("verified_complete", "verified_empty")
                 and isinstance(items, list) and type(p.get("total")) is int and p["total"] == len(items))
        if valid:
            valid = all(_identity(r) and type(r.get("board")) is int and r["board"] > 0 for r in items)
            valid = valid and len({r["identity"] for r in items}) == len(items)
            valid = valid and ((p["status"] == "verified_empty") == (not items))
        if not valid:
            result["issues"].append(label + "_pool_invalid_or_missing")
            return result, {}
        parsed[label] = {r["identity"]: r for r in items}
    conflict = []
    for height in (2, 3):
        cohort = {k for k, r in parsed["P"].items() if r["board"] == height - 1}
        promoted = {k for k, r in parsed["Y"].items() if r["board"] == height}
        result["r" + str(height)] = {"numerator": len(cohort & promoted), "denominator": len(cohort),
                                   "matched": sorted(cohort & promoted)}
        conflict += sorted(promoted - cohort)
    if conflict:
        result["issues"] += ["cohort_conflict"]
        result["conflict_identities"] = sorted(set(conflict))
        return result, parsed["Y"]
    a, b = result["r2"], result["r3"]
    if not a["denominator"] or not b["denominator"]:
        result["issues"].append("zero_denominator_unknown")
        return result, parsed["Y"]
    result["status"] = "ready"
    if a["numerator"] or b["numerator"]:
        result["target_board"] = 2 if a["numerator"] * b["denominator"] >= b["numerator"] * a["denominator"] else 3
    return result, parsed["Y"]


def _quote(e, identity):
    q = e.get("quotes", {}).get(identity, {})
    return q if (q.get("identity") == identity and q.get("date") == e["trade_date"]
                 and q.get("cutoff") == e["trade_date"] + "T09:40:00+08:00"
                 and q.get("basis") == "raw" and q.get("limit_verified") is True
                 and positive(q.get("limit_price"))) else {}


def _opening_fact(e, identity):
    q = e.get("opening_facts", {}).get(identity, {})
    day = e["trade_date"]
    observed = _at(q.get("observed_at"), day)
    return q if (q.get("identity") == identity and q.get("date") == day and q.get("basis") == "raw"
                 and q.get("fact_time") == day + "T09:30:00+08:00" and observed
                 and observed.time() >= time(9, 40) and q.get("source")
                 and q.get("limit_verified") is True and positive(q.get("limit_price")) and positive(q.get("open"))) else {}


def _event_state(row, e):
    day = e["trade_date"]
    cut = _at(day + "T09:40:00+08:00", day)
    first = _at(row.get("first_at"), day)
    if first is None or not time(9, 25) <= first.time() <= time(15):
        return None, None, "first_time_unknown"
    timeline = row.get("timeline", [])
    seq = []
    for t in timeline:
        if not isinstance(t, dict):
            return first, None, "timeline_invalid"
        at = _at(t.get("at"), day)
        if at is None or t.get("state") not in ("sealed", "open"):
            return first, None, "timeline_invalid"
        seq.append((at, t["state"]))
    complete = (row.get("timeline_complete") is True and seq and seq[0] == (first, "sealed")
                and all(a[0] < b[0] and a[1] != b[1] for a, b in zip(seq, seq[1:])))
    if first > cut:
        return first, "late", None
    q = _quote(e, row["identity"])
    opening = _opening_fact(e, row["identity"])
    opens = [at for at, state in seq if state == "open" and at <= cut] if complete else []
    cap = positive(q.get("limit_price")) or positive(opening.get("limit_price"))
    op = positive(opening.get("open")) or positive(q.get("open"))
    if q and opening and (positive(q["limit_price"]) != positive(opening["limit_price"]) or positive(q.get("open")) and positive(q["open"]) != positive(opening["open"])):
        return first, None, "opening_quote_conflict"
    state = [state for at, state in seq if at <= cut][-1] if complete else None
    price = positive(q.get("close0940"))
    if cap and (op and op > cap or price and price > cap):
        return first, None, "quote_above_verified_upper"
    # Check both same-cutoff facts before any one-word exclusion/early return.
    if complete and price and ((price == cap) != (state == "sealed")):
        return first, None, "cutoff_quote_timeline_conflict"
    if complete and first.time() < time(9, 30) and op and cap and op < cap:
        open_at = _at(day + "T09:30:00+08:00", day)
        if [s for at, s in seq if at <= open_at][-1] == "sealed":
            return first, None, "opening_timeline_conflict"
    below = bool(cap and any(positive(q.get(k)) and positive(q[k]) < cap for k in ("open", "observed_low0940")))
    nonword = bool(opens) or below or bool(op and cap and op < cap)
    # First-seal seconds do not describe the earlier path. For example a 09:31
    # first seal can follow an upper-price opening and a pre-seal dip.
    if not nonword and complete and first.time() <= time(9, 30) and op == cap and cap:
        return first, "oneword", None
    if not nonword:
        return first, None, "oneword_unknown"
    if complete:
        return first, state, None
    # Offline reviewed raw closed-bar branch; no current/latest price fallback.
    if q.get("cutoff") == cut.isoformat() and positive(q.get("close0940")):
        return first, "sealed" if positive(q["close0940"]) == cap else "open", None
    return first, None, "cutoff_state_unknown"


def selection(e, ds, promo, y):
    r = {"status": "unknown", "first": None, "excluded": [], "issues": []}
    target = promo["target_board"]
    if promo["status"] != "ready" or target is None:
        return r
    events = e.get("events", {})
    items = events.get("items")
    if (events.get("date") != e["trade_date"] or events.get("source") != "XGB"
            or events.get("status") not in ("verified_complete", "verified_empty")
            or events.get("coverage_verified") is not True
            or events.get("scope") != "limit_up_union_limit_up_broken" or not isinstance(items, list)
            or not all(_identity(row) for row in items)
            or len({row["identity"] for row in items}) != len(items)):
        r["issues"].append("event_union_incomplete_or_invalid")
        return r
    cohort = {k for k, row in y.items() if row["board"] == target - 1}
    pending = []
    for row in items:
        if row["identity"] not in cohort:
            continue
        first, state, issue = _event_state(row, e)
        if first is None:
            r["issues"].append(row["identity"] + ":" + issue)
            return r
        if state in ("late", "oneword"):
            r["excluded"].append({"identity": row["identity"], "reason": state})
        else:
            pending.append((first, row, state, issue))
    if not pending:
        r["status"] = "no_candidate"
        return r
    earliest = min(p[0] for p in pending)
    group = [p for p in pending if p[0] == earliest]
    if len(group) != 1 or group[0][2] is None:
        r["issues"].append("same_second_tie" if len(group) != 1 else group[0][3])
        return r
    first, row, state, _ = group[0]
    q = _quote(e, row["identity"])
    opening = _opening_fact(e, row["identity"])
    r["first"] = {"identity": row["identity"], "code": row["code"], "name": row.get("name", ""),
                  "first_at": first.isoformat(), "display_price": q.get("limit_price") or opening.get("limit_price"),
                  "cutoff_state": state}
    r["status"] = "candidate" if state == "sealed" else "first_left"
    return r


def evaluate_opening_limitup(evidence):
    """Evaluate canonical schema v1. Missing facts stay unknown, never zero."""
    e = evidence if isinstance(evidence, dict) else {}
    ds = _calendar(e)
    env = environment(e, ds)
    promo, y = promotion(e, ds)
    selected = selection(e, ds, promo, y)
    missing = list(e.get("issues", [])) + env["issues"] + selected["issues"]
    if promo["status"] == "unknown":
        missing += ["promotion_unknown"] + promo["issues"]
    false = [k for k, v in env["gates"].items() if v is False]
    if false or (promo["status"] == "ready" and promo["target_board"] is None) or selected["status"] in ("no_candidate", "first_left"):
        status = "no_trade"
    elif all(v is True for v in env["gates"].values()) and selected["status"] == "candidate":
        status = "candidate"
    else:
        status = "unavailable"
    return {"schema_version": 1, "strategy_id": STRATEGY_ID, "trade_date": e.get("trade_date"),
            "cutoff": str(e.get("trade_date")) + "T09:40:00+08:00", "status": status,
            "environment": env, "promotion": promo, "selection": selected,
            "failed_gates": false, "missing": sorted(set(missing)), "actual_fill": None}
