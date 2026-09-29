"""Independent evidence-only extreme-icepoint observation for the daily report."""

from __future__ import annotations

import math
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


SCHEMA_VERSION = 1
RULE_VERSION = "extreme-icepoint-v1"
CN = timezone(timedelta(hours=8))
INDEX_NAMES = ("上证指数", "深证成指", "创业板指", "科创50", "沪深300", "中证500")
ETF_GROUPS = (
    ("银行", "sh512800"), ("医疗", "sh512170"), ("半导体", "sh512480"),
    ("军工", "sh512660"), ("主要消费", "sz159928"),
    ("有色金属", "sh512400"), ("房地产", "sh512200"),
)


def _number(value, *, minimum=None):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        return None
    return result


def _count(value):
    number = _number(value, minimum=0)
    return int(number) if number is not None and number.is_integer() else None


def _stamp(value):
    try:
        item = datetime.fromisoformat(str(value))
        return item.astimezone(CN) if item.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _valid_day(value, report_date):
    return isinstance(value, str) and value == report_date


def _valid_asof(value, report_date, cutoff, *, closed=False):
    instant = _stamp(value)
    return bool(instant and cutoff and instant.date().isoformat() == report_date
                and instant <= cutoff and (not closed or instant.hour >= 15))


def _item(status, actual, threshold, *, source="", as_of="", scope="", reason=""):
    return {"status": status, "actual": actual, "threshold": threshold,
            "source": source, "as_of": as_of, "scope": scope, "reason": reason}


def evaluate_icepoint(report_date, as_of, phase, *, indices=None, turnover=None,
                      breadth=None, limits=None, etf=None):
    """Evaluate four fixed conditions, leaving missing evidence explicitly unknown."""
    cutoff = _stamp(as_of)
    valid_context = (phase in ("closed", "intraday") and cutoff is not None
                     and cutoff.date().isoformat() == report_date
                     and (phase != "closed" or cutoff.hour >= 15))
    if not valid_context:
        cutoff = None

    changes = {}
    index_sources = {}
    index_times = {}
    if isinstance(indices, dict):
        for name in INDEX_NAMES:
            row = indices.get(name)
            if (not isinstance(row, dict) or not _valid_day(row.get("date"), report_date)
                    or row.get("status") != "verified"
                    or not _valid_asof(row.get("as_of"), report_date, cutoff,
                                        closed=phase == "closed")):
                continue
            change = _number(row.get("change_pct"))
            if change is None or not str(row.get("source") or "").strip():
                continue
            changes[name] = change
            index_sources[name] = str(row["source"])
            index_times[name] = str(row["as_of"])
    index_complete = valid_context and len(changes) == 6
    index_match = index_complete and all(value <= -2 for value in changes.values())
    index_status = ("matched" if index_match else "not_matched") if index_complete else "unavailable"
    index_item = _item(index_status, {"changes_pct": changes}, "六指数每项≤-2%",
                       source=index_sources, as_of=index_times,
                       scope="six_fixed_indices", reason="" if index_complete else "six_same_day_indices_required")

    amount = turnover if isinstance(turnover, dict) else {}
    current = _number(amount.get("current"), minimum=0)
    prior_raw = amount.get("prior")
    prior = [_number(value, minimum=0) for value in prior_raw] if isinstance(prior_raw, list) else []
    prior_dates = amount.get("prior_dates")
    prior_dates_ok = (isinstance(prior_dates, list) and len(prior_dates) == 5
                      and all(isinstance(day, str) and day < report_date for day in prior_dates)
                      and prior_dates == sorted(set(prior_dates)))
    covered_raw = amount.get("coverage_counts")
    covered = [_count(value) for value in covered_raw] if isinstance(covered_raw, list) else []
    denominator = _count(amount.get("denominator"))
    volume_ready = bool(valid_context and phase == "closed"
                        and _valid_day(amount.get("date"), report_date)
                        and _valid_asof(amount.get("as_of"), report_date, cutoff, closed=True)
                        and amount.get("scope") == "all_a_cny"
                        and str(amount.get("source") or "")
                        and amount.get("quality") == "comparable"
                        and amount.get("complete") is True
                        and amount.get("trading_days_verified") is True
                        and prior_dates_ok
                        and current is not None and len(prior) == 5
                        and all(value is not None and value > 0 for value in prior)
                        and len(covered) == 6 and denominator and denominator > 0
                        and all(value == denominator
                                for value in covered))
    baseline = _number(sum(prior) / 5, minimum=0) if volume_ready else None
    ratio = _number(current / baseline, minimum=0) if baseline and current is not None else None
    volume_ready = bool(volume_ready and baseline and ratio is not None)
    volume_actual = {"current_cny": current, "prior_mean_cny": baseline,
                     "ratio": round(ratio, 4) if ratio is not None else None,
                     "prior_dates": prior_dates if prior_dates_ok else None,
                     "covered_counts": covered if len(covered) == 6 else None,
                     "denominator": denominator}
    volume_status = "unavailable"
    if volume_ready and index_complete:
        volume_status = "matched" if ratio >= 1.2 and index_match else "not_matched"
    volume_item = _item(volume_status, volume_actual, "当日全A金额≥前5日同口径均额1.2倍，且六指数同跌",
                        source=amount.get("source") or "", as_of=str(amount.get("as_of") or ""),
                        scope="all_a_cny", reason="" if volume_status != "unavailable" else
                        ("same_time_history_unavailable" if phase == "intraday" else "comparable_full_market_amount_or_indices_missing"))

    market = breadth if isinstance(breadth, dict) else {}
    rising, falling, flat = (_count(market.get(key)) for key in
                             ("advance_count", "decline_count", "flat_count"))
    valid_count = _count(market.get("valid_count"))
    market_denominator = _count(market.get("denominator"))
    breadth_ready = bool(valid_context and _valid_day(market.get("date"), report_date)
                         and _valid_asof(market.get("as_of"), report_date, cutoff,
                                        closed=phase == "closed")
                         and market.get("scope") == "all_a"
                         and str(market.get("source") or "")
                         and market.get("complete") is True
                         and None not in (rising, falling, flat, valid_count, market_denominator)
                         and market_denominator > 0 and valid_count > 0
                         and rising + falling + flat == valid_count
                         and valid_count == market_denominator)
    breadth_status = ("matched" if falling > 0 and falling >= rising * 9 else
                      "not_matched") if breadth_ready else "unavailable"
    breadth_item = _item(breadth_status,
                         {"advance_count": rising, "decline_count": falling,
                          "flat_count": flat, "valid_count": valid_count,
                          "denominator": market_denominator},
                         "下跌>0且下跌家数≥上涨家数×9",
                         source=str(market.get("source") or ""), as_of=str(market.get("as_of") or ""),
                         scope="all_a", reason="" if breadth_ready else "all_a_breadth_or_coverage_missing")

    pools = limits if isinstance(limits, dict) else {}
    up, down = _count(pools.get("limit_up_count")), _count(pools.get("limit_down_count"))
    limits_ready = bool(valid_context and _valid_day(pools.get("evidence_date"), report_date)
                        and _valid_asof(pools.get("as_of"), report_date, cutoff,
                                       closed=phase == "closed")
                        and pools.get("data_status") == "verified"
                        and pools.get("scope") == "eastmoney_topic_pools"
                        and pools.get("current_sealed") is True
                        and pools.get("source") == "eastmoney_limit_pools"
                        and up is not None and down is not None)
    limits_status = ("matched" if down >= 100 and up <= 10 else
                     "not_matched") if limits_ready else "unavailable"
    limits_item = _item(limits_status, {"limit_up_count": up, "limit_down_count": down},
                        "当前封板跌停≥100且涨停≤10", source=str(pools.get("source") or ""),
                        as_of=str(pools.get("as_of") or ""), scope=str(pools.get("scope") or ""),
                        reason="" if limits_ready else "same_day_sealed_pool_totals_missing")

    sample = etf if isinstance(etf, dict) else {}
    quotes = sample.get("quotes") if isinstance(sample.get("quotes"), list) else []
    expected = dict(ETF_GROUPS)
    observations = {}
    duplicate = set()
    seen = set()
    for row in quotes:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").lower()
        if symbol not in expected.values():
            continue
        if symbol in seen:
            duplicate.add(symbol)
        seen.add(symbol)
        change = _number(row.get("change_pct"))
        if (change is not None and _valid_asof(row.get("as_of"), report_date, cutoff,
                                              closed=phase == "closed")):
            observations[symbol] = {"change_pct": change, "as_of": row["as_of"]}
    for symbol in duplicate:
        observations.pop(symbol, None)
    if (not valid_context or not _valid_day(sample.get("date"), report_date)
            or sample.get("source") != "tencent"
            or not _valid_asof(sample.get("as_of"), report_date, cutoff,
                               closed=phase == "closed")):
        observations = {}
    etf_down = sum(item["change_pct"] < -4 for item in observations.values())
    etf_status = ("matched" if etf_down >= 5 else
                  "not_matched" if len(observations) == 7 else "unavailable")
    etf_item = _item(etf_status,
                     {"below_minus_four_count": etf_down, "verified_count": len(observations),
                      "groups": [{"group": name, "symbol": symbol,
                                  "change_pct": observations.get(symbol, {}).get("change_pct"),
                                  "as_of": observations.get(symbol, {}).get("as_of", "")}
                                 for name, symbol in ETF_GROUPS]},
                     "固定7行业ETF中≥5组跌幅<-4%",
                     source="tencent" if observations else "", scope="fixed_seven_etf_sample",
                     as_of=str(sample.get("as_of") or "") if observations else "",
                     reason="" if etf_status != "unavailable" else "fixed_etf_quotes_incomplete")
    etf_item["verified_count"] = len(observations)

    items = {"volume_drop": volume_item, "six_indices": index_item,
             "breadth": breadth_item, "sealed_limits": limits_item}
    verified = sum(item["status"] != "unavailable" for item in items.values())
    matched = sum(item["status"] == "matched" for item in items.values())
    status = ("insufficient" if verified < 4 else
              "matched" if matched == 4 else "not_matched")
    return {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION,
            "date": report_date, "as_of": as_of, "phase": phase,
            "affects_production": False, "status": status,
            "matched_count": matched, "verified_count": verified,
            "items": items, "etf": etf_item}


def build_existing_evidence(report_date, observed_at, *, indices=None,
                            index_observed_at=None, market_data_status="",
                            sentiment=None, stock_window=None, index_window=None,
                            close_snapshot=None, limit_counts=None,
                            limit_fetch_times=None, turnover_quality=None,
                            turnover_input=None):
    """Adapt only data already read by this report; never fetch market-wide data."""
    index_rows = {}
    if isinstance(indices, dict) and market_data_status == "verified":
        for name in INDEX_NAMES:
            row = indices.get(name)
            if isinstance(row, dict):
                index_rows[name] = {
                    "date": row.get("date"), "change_pct": row.get("change_pct"),
                    "source": row.get("source"), "status": row.get("status", "verified"),
                    "as_of": row.get("as_of") or index_observed_at,
                }

    window = stock_window if isinstance(stock_window, dict) else {}
    index_window = index_window if isinstance(index_window, dict) else {}
    snapshot = close_snapshot if isinstance(close_snapshot, dict) else {}
    dates = sorted(set(str(day) for day in window.get("dates") or []))
    index_dates = sorted(set(str(day) for day in index_window.get("dates") or []))
    count = _count(snapshot.get("coverage_denominator"))
    full_close = bool(snapshot.get("status") == "complete"
                      and snapshot.get("report_date") == report_date
                      and count and count > 0
                      and _count(snapshot.get("coverage_numerator")) == count
                      and _count(snapshot.get("identity_pending_rows", 0)) == 0
                      and dates and dates[-1] == report_date)
    last_six = dates[-6:]
    same_trade_dates = (len(last_six) == 6 and index_dates[-6:] == last_six)
    grouped = {day: {} for day in last_six}
    duplicate = False
    for row in window.get("rows") or []:
        if not isinstance(row, dict):
            continue
        day = str(row.get("ts") or "")[:10]
        if day not in grouped or row.get("asset_type") != "stock":
            continue
        key = (str(row.get("exchange") or ""), str(row.get("code") or ""))
        if not all(key):
            continue
        if key in grouped[day]:
            duplicate = True
        grouped[day][key] = row
    current_set = set(grouped.get(report_date, {}))
    complete_set = bool(full_close and not duplicate and len(current_set) == count)
    value = sentiment if isinstance(sentiment, dict) else {}
    breadth_raw = (value.get("evidence") or {}).get("breadth") or {}
    breadth_raw = breadth_raw if value.get("date") == report_date and isinstance(breadth_raw, dict) else {}
    breadth = {
        "date": report_date, "as_of": observed_at, "source": "market_history",
        "scope": "all_a", "advance_count": breadth_raw.get("advance_count"),
        "decline_count": breadth_raw.get("decline_count"),
        "flat_count": breadth_raw.get("flat_count"),
        "valid_count": breadth_raw.get("valid_count"), "denominator": count,
        "complete": bool(complete_set and breadth_raw.get("available") is True
                         and _count(breadth_raw.get("valid_count")) == count),
    }

    totals = []
    sources = {}
    amount_complete = bool(complete_set and same_trade_dates
                           and turnover_quality == "comparable"
                           and all(set(grouped[day]) == current_set for day in last_six))
    if amount_complete:
        for day in last_six:
            values = []
            day_sources = set()
            for row in grouped[day].values():
                amount = _number(row.get("amount"), minimum=0)
                source = str(row.get("amount_source") or "").strip()
                if (amount is None or amount <= 0
                        or row.get("amount_available") not in (True, 1)
                        or str(row.get("amount_unit") or "").upper() != "CNY"
                        or not source):
                    amount_complete = False
                    break
                values.append(amount)
                day_sources.add(source)
            if not amount_complete:
                break
            day_total = sum(values)
            if not math.isfinite(day_total):
                amount_complete = False
                break
            totals.append(day_total)
            sources[day] = sorted(day_sources)
    # The daily calculator resets its history at a scale break. Today's
    # "comparable" flag alone cannot prove that the preceding five days survived.
    trusted_turnover = turnover_input if isinstance(turnover_input, dict) else {}
    trusted_current = _number(trusted_turnover.get("turnover"), minimum=0)
    trusted_ma5 = _number(trusted_turnover.get("turnover_ma5"), minimum=0)
    candidate_ma5 = _number(sum(totals[:-1]) / 5, minimum=0) if amount_complete else None
    amount_complete = bool(
        amount_complete and trusted_turnover.get("date") == report_date
        and trusted_current is not None and trusted_ma5 and candidate_ma5
        and math.isclose(trusted_current, totals[-1], rel_tol=1e-12)
        and math.isclose(trusted_ma5, candidate_ma5, rel_tol=1e-12)
    )
    turnover = {
        "date": report_date, "as_of": observed_at, "scope": "all_a_cny",
        "source": {"database": "market_history", "amount_by_date": sources},
        "current": totals[-1] if amount_complete else None,
        "prior": totals[:-1] if amount_complete else [],
        "prior_dates": last_six[:-1] if amount_complete else [],
        "coverage_counts": [count] * 6 if amount_complete else [],
        "denominator": count, "complete": amount_complete,
        "trading_days_verified": same_trade_dates,
        "quality": "comparable" if amount_complete else "missing_amount_evidence",
    }

    raw = (limit_counts or {}).get(report_date) if isinstance(limit_counts, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    fetch_time = (limit_fetch_times or {}).get(report_date) if isinstance(limit_fetch_times, dict) else None
    stamp = _stamp(fetch_time)
    limits = {
        "evidence_date": raw.get("evidence_date"),
        "as_of": fetch_time or "", "source": raw.get("source"),
        "scope": "eastmoney_topic_pools" if raw.get("source") == "eastmoney_limit_pools" else "",
        "data_status": raw.get("data_status"),
        "current_sealed": bool(stamp and stamp.date().isoformat() == report_date and stamp.hour >= 15),
        "limit_up_count": raw.get("limit_up_count"),
        "limit_down_count": raw.get("limit_down_count"),
    }
    return {"indices": index_rows, "turnover": turnover, "breadth": breadth,
            "limits": limits}


def build_report_icepoint(report_date, observed_at, phase, *, etf=None, **existing):
    return evaluate_icepoint(report_date, observed_at, phase, etf=etf, **existing)


def parse_tencent_etf(raw, report_date, now):
    """Parse seven fixed ETF identities from one GB18030 Tencent quote batch."""
    cutoff = _stamp(now)
    result = {"date": report_date, "source": "tencent", "as_of": "", "quotes": []}
    if cutoff is None or cutoff.date().isoformat() != report_date:
        return result
    if isinstance(raw, bytes):
        raw = raw.decode("gb18030", errors="replace")
    if not isinstance(raw, str):
        return result
    expected = {symbol for _, symbol in ETF_GROUPS}
    seen = set()
    duplicated = set()
    quotes = {}
    for symbol, body in re.findall(r'v_((?:sh|sz)\d{6})="([^"\r\n]*)"\s*;', raw):
        if symbol not in expected:
            continue
        if symbol in seen:
            duplicated.add(symbol)
        seen.add(symbol)
        parts = body.split("~")
        if len(parts) < 33 or parts[2] != symbol[2:]:
            continue
        price = _number(parts[3], minimum=0)
        previous = _number(parts[4], minimum=0)
        change = _number(parts[32])
        try:
            source_time = datetime.strptime(parts[30], "%Y%m%d%H%M%S").replace(tzinfo=CN)
        except ValueError:
            continue
        if (not price or not previous or change is None
                or source_time.date().isoformat() != report_date
                or source_time > cutoff + timedelta(seconds=60)
                or (cutoff.hour >= 15 and source_time.hour < 15)
                or (cutoff.hour < 15 and (cutoff-source_time).total_seconds() > 180)
                or abs((price / previous - 1) * 100 - change) > 0.03):
            continue
        quotes[symbol] = {"symbol": symbol, "change_pct": change,
                          "as_of": source_time.isoformat()}
    for symbol in duplicated:
        quotes.pop(symbol, None)
    result["quotes"] = list(quotes.values())
    if quotes:
        result["as_of"] = max(row["as_of"] for row in quotes.values())
    return result


def _etf_cache_root():
    from config import MARKET_HISTORY_DB_PATH
    return Path(MARKET_HISTORY_DB_PATH).parent / "market_icepoint"


def fetch_etf_quotes(report_date, *, now=None, cache_dir=None, requester=None):
    """One free batch, no retry; cache same-day phase to avoid repeated calls."""
    cutoff = _stamp(now or datetime.now(CN).isoformat())
    empty = {"date": report_date, "source": "tencent", "as_of": "", "quotes": []}
    if cutoff is None or cutoff.date().isoformat() != report_date:
        return empty
    root = Path(cache_dir) if cache_dir is not None else _etf_cache_root()
    path = root / (report_date + ("-closed" if cutoff.hour >= 15 else "-intraday") + ".json")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        stamp = _stamp(saved.get("fetched_at"))
        age = (cutoff-stamp).total_seconds() if stamp else -1
        saved_payload = saved.get("payload") if isinstance(saved.get("payload"), dict) else empty
        complete = len(saved_payload.get("quotes") or []) == len(ETF_GROUPS)
        if (stamp and stamp.date() == cutoff.date() and age >= 0
                and ((cutoff.hour >= 15 and complete) or age < 120)):
            return saved_payload
    except (OSError, ValueError, TypeError):
        pass
    url = "https://qt.gtimg.cn/q=" + ",".join(symbol for _, symbol in ETF_GROUPS)
    payload = empty
    try:
        if requester is None:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(url, timeout=(2, 4), headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                raw = response.content
        else:
            raw = requester(url)
        payload = parse_tencent_etf(raw, report_date, cutoff.isoformat())
    except (requests.RequestException, OSError, ValueError, TypeError):
        pass
    temporary = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"fetched_at": cutoff.isoformat(), "payload": payload}, handle, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return payload
