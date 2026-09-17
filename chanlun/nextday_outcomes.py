"""Bounded, read-only outcome paths for a frozen L1 research selection.

This module does not select candidates and does not make formal strategy
decisions. It reads only the frozen signal date and up to three calendar-known
trading dates for each of at most five selected identities.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from numbers import Real
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from chanlun.identity import infer_stock_exchange
from chanlun.preclose_schedule import _SSE_2026_CLOSED


MAX_SELECTIONS = 5
_IDENTITY_RE = re.compile(r"^(SH|SZ|BJ)([0-9]{6})$")
_IDENTITY_KEY_RE = re.compile(r"^stock\|(SH|SZ|BJ)\|([0-9]{6})$")
_OHLC_COLUMNS = ("open", "high", "low", "close")
_OFFICIAL_CLOSE_SOURCE = "official_close_snapshot:eastmoney"
_PRECLOSE_MAX_BYTES = 64 * 1024 * 1024
_BAR_COLUMNS = (
    "instrument_id",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "adjustment",
    "is_final",
    "source_batch",
    "updated_at",
)
_OUTCOME_NOTES = (
    "Price paths are not realized profit. Fees, slippage, queue position, "
    "intraday execution, and A-share T+1 constraints are not modeled."
)


class OutcomeDataError(RuntimeError):
    """The read-only market-history database cannot satisfy this contract."""


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError("{} must be a YYYY-MM-DD string".format(label))
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("{} must be a YYYY-MM-DD string".format(label))
    if parsed.isoformat() != value:
        raise ValueError("{} must be a canonical YYYY-MM-DD date".format(label))
    return parsed


def _extract_identity(selection: Any) -> Tuple[Optional[str], Optional[dict]]:
    if isinstance(selection, str):
        exchange, code, status = _parse_identity(selection)
        return (exchange + code if status == "valid" else selection), {
            "instrument_id": selection
        }
    if not isinstance(selection, Mapping):
        return None, None

    candidates = []
    for key in ("stock_identity", "identity", "instrument_id"):
        value = selection.get(key)
        if value is None:
            continue
        if isinstance(value, Mapping) and key == "identity":
            detail_identity = _identity_from_details(value)
            if detail_identity is None:
                return None, dict(selection)
            candidates.append(detail_identity)
            continue
        if not isinstance(value, str):
            return None, dict(selection)
        normalized = _canonical_identity(value)
        if normalized is None:
            return None, dict(selection)
        candidates.append(normalized)

    if "identity_details" in selection and selection["identity_details"] is not None:
        detail_identity = _identity_from_details(selection["identity_details"])
        if detail_identity is None:
            return None, dict(selection)
        candidates.append(detail_identity)

    direct_exchange = selection.get("exchange")
    direct_code = selection.get("code")
    if direct_exchange is not None and not isinstance(direct_exchange, str):
        return None, dict(selection)
    if direct_code is not None and not isinstance(direct_code, str):
        return None, dict(selection)
    if candidates:
        normalized_base = set(candidates)
        if len(normalized_base) != 1:
            return None, dict(selection)
        canonical = next(iter(normalized_base))
        canonical_exchange, canonical_code, _ = _parse_identity(canonical)
        if direct_exchange is not None and direct_exchange != canonical_exchange:
            return None, dict(selection)
        if direct_code is not None and direct_code != canonical_code:
            return None, dict(selection)
    elif direct_exchange is not None and direct_code is not None:
        direct_identity = _canonical_identity(direct_exchange + direct_code)
        if direct_identity is None:
            return None, dict(selection)
        candidates.append(direct_identity)
    elif direct_exchange is not None or direct_code is not None:
        # A lone exchange or code cannot establish exact identity by itself.
        return None, dict(selection)

    if selection.get("asset_type") is not None:
        asset_type = selection["asset_type"]
        if not isinstance(asset_type, str) or asset_type.strip().lower() != "stock":
            return None, dict(selection)

    if not candidates or len(set(candidates)) != 1:
        return None, dict(selection)
    return candidates[0], dict(selection)


def _canonical_identity(value: str) -> Optional[str]:
    exchange, code, status = _parse_identity(value)
    return exchange + code if status == "valid" else None


def _identity_from_details(value: Any) -> Optional[str]:
    if not isinstance(value, Mapping):
        return None
    asset_type = value.get("asset_type")
    exchange = value.get("exchange")
    code = value.get("code")
    if (
        not isinstance(asset_type, str)
        or asset_type.strip().lower() != "stock"
        or not isinstance(exchange, str)
        or not isinstance(code, str)
    ):
        return None
    return _canonical_identity(exchange + code)


def _parse_identity(value: Optional[str]) -> Tuple[Optional[str], Optional[str], str]:
    if not isinstance(value, str):
        return None, None, "malformed"
    match = _IDENTITY_RE.fullmatch(value)
    if match is None:
        keyed = _IDENTITY_KEY_RE.fullmatch(value)
        if keyed is not None:
            match = keyed
    if not match:
        return None, None, "malformed"
    exchange, code = match.groups()
    expected_exchange = infer_stock_exchange(code)
    # Exchange prefixes that the stock identity registry cannot establish are
    # not guessed from an index row or from a six-digit code alone.
    if expected_exchange is None or expected_exchange != exchange:
        return exchange, code, "malformed"
    return exchange, code, "valid"


def _calendar_state(trade_date: date, connection: sqlite3.Connection) -> str:
    """Return open, closed, or unknown within the pinned SQLite snapshot.

    This mirrors preclose_schedule.is_trading_day while reading explicit
    calendar rows from the same transaction as bars. That avoids classifying
    bars against a second, potentially newer SQLite snapshot.
    """
    iso = trade_date.isoformat()
    try:
        rows = connection.execute(
            "SELECT exchange, is_open FROM trade_calendar "
            "WHERE trade_date=? AND exchange IN ('SH', 'SZ')",
            (iso,),
        ).fetchall()
    except sqlite3.Error:
        return "unknown"
    if rows:
        flags = {}
        for exchange, raw_flag in rows:
            if raw_flag not in (0, 1):
                return "unknown"
            flag = int(raw_flag)
            if exchange in flags and flags[exchange] != flag:
                return "unknown"
            flags[exchange] = flag
        if len(set(flags.values())) != 1:
            return "unknown"
        if trade_date.weekday() >= 5:
            # The reviewed calendar treats weekends as closed. An explicit
            # weekend-open flag conflicts with that rule, so do not use it.
            return "closed" if next(iter(flags.values())) == 0 else "unknown"
        return "open" if next(iter(flags.values())) == 1 else "closed"
    if trade_date.weekday() >= 5:
        return "closed"
    # Use the reviewed fallback set from preclose_schedule.is_trading_day.
    # No calendar is guessed for unsupported years.
    if trade_date.year == 2026:
        return "closed" if iso in _SSE_2026_CLOSED else "open"
    return "unknown"


def _target_dates(
    report_date: date, connection: sqlite3.Connection
) -> Tuple[Dict[str, Optional[str]], str]:
    targets = {"t1": None, "t2": None, "t3": None}
    index = 1
    for offset in range(1, 22):
        candidate = report_date + timedelta(days=offset)
        state = _calendar_state(candidate, connection)
        if state == "unknown":
            return targets, (
                "partial_calendar_unavailable" if index > 1 else "calendar_unavailable"
            )
        if state != "open":
            continue
        targets["t{}".format(index)] = candidate.isoformat()
        index += 1
        if index == 4:
            return targets, "available"
    return targets, "calendar_unavailable"


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _positive_price(value: Any) -> bool:
    return _is_number(value) and float(value) > 0.0


def _close_enough(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12 * max(1.0, abs(left), abs(right))


def _bar_fingerprint(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return tuple(row.get(column) for column in _BAR_COLUMNS[2:])


def _validate_bar(rows: Sequence[Mapping[str, Any]]) -> Tuple[str, Optional[dict], int]:
    if not rows:
        return "missing", None, 0
    duplicate_count = max(0, len(rows) - 1)
    fingerprints = {_bar_fingerprint(row) for row in rows}
    if len(fingerprints) > 1:
        return "duplicate_inconsistent", None, duplicate_count
    row = dict(rows[0])
    final_flag = row.get("is_final")
    if final_flag not in (0, 1, False, True):
        return "invalid_status", None, duplicate_count
    if final_flag != 1:
        return "nonfinal", None, duplicate_count
    prices = [row.get(column) for column in _OHLC_COLUMNS]
    if not all(_positive_price(value) for value in prices):
        return "invalid_ohlc", None, duplicate_count
    open_price, high_price, low_price, close_price = [float(v) for v in prices]
    if (
        high_price < low_price
        or low_price > open_price
        or open_price > high_price
        or low_price > close_price
        or close_price > high_price
    ):
        return "invalid_ohlc", None, duplicate_count
    row["open"] = open_price
    row["high"] = high_price
    row["low"] = low_price
    row["close"] = close_price
    row["adjustment"] = str(row.get("adjustment") or "").strip().lower()
    return "valid", row, duplicate_count


def _basis_is_raw(*bars: Optional[Mapping[str, Any]]) -> bool:
    return all(bar is not None and bar.get("adjustment") == "raw" for bar in bars)


def _read_preclose_input(
    evidence_root: Path,
    trade_date: str,
    cache: Dict[str, Optional[Mapping[str, Any]]],
) -> Optional[Mapping[str, Any]]:
    if trade_date in cache:
        return cache[trade_date]
    path = evidence_root / "preclose" / trade_date / "input.json"
    try:
        if not path.is_file() or path.stat().st_size > _PRECLOSE_MAX_BYTES:
            cache[trade_date] = None
            return None
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        cache[trade_date] = None
        return None
    cache[trade_date] = payload if isinstance(payload, Mapping) else None
    return cache[trade_date]


def _qfq_bridge_proof(
    evidence_root: Path,
    preclose_cache: Dict[str, Optional[Mapping[str, Any]]],
    exchange: str,
    code: str,
    trade_date: str,
    previous_date: str,
    previous_bar: Optional[Mapping[str, Any]],
    final_bar: Mapping[str, Any],
) -> dict:
    """Verify one final qfq bar against its retained same-day quote bridge.

    The preclose input is evidence only. The final ``bars_day`` row remains the
    evaluated bar; only its same-day open must match the provisional qfq open,
    because the official-close writer applies one factor to the full raw OHLC
    while later high, low, and close values may legitimately move after 14:45.
    """

    def rejected(reason: str) -> dict:
        return {"status": "unverified", "reason": reason}

    if final_bar.get("adjustment") != "qfq":
        return rejected("adjustment_chain_mismatch")
    if final_bar.get("source_batch") != _OFFICIAL_CLOSE_SOURCE:
        return rejected("final_bar_source_mismatch")
    if previous_bar is None:
        return rejected("previous_final_bar_missing")
    if previous_bar.get("adjustment") != "qfq":
        return rejected("adjustment_chain_mismatch")

    payload = _read_preclose_input(evidence_root, trade_date, preclose_cache)
    if payload is None:
        return rejected("preclose_input_missing")
    if (
        payload.get("schema_version") != "preclose-input-v1"
        or payload.get("mode") != "preclose_advisory"
        or payload.get("trade_date") != trade_date
        or payload.get("bar_state") != "intraday"
        or payload.get("is_final") is not False
    ):
        return rejected("preclose_header_mismatch")
    as_of = payload.get("as_of")
    if not isinstance(as_of, str):
        return rejected("preclose_header_mismatch")
    try:
        parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        return rejected("preclose_header_mismatch")
    if (
        parsed_as_of.date().isoformat() != trade_date
        or parsed_as_of.utcoffset() is None
    ):
        return rejected("preclose_header_mismatch")

    diagnostics = payload.get("runtime_diagnostics")
    quote_snapshot = diagnostics.get("quote_snapshot") if isinstance(diagnostics, Mapping) else None
    if not isinstance(quote_snapshot, Mapping) or quote_snapshot.get("complete") is not True:
        return rejected("quote_snapshot_incomplete")
    counters = [quote_snapshot.get(key) for key in ("requested", "unique", "fetched")]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in counters):
        return rejected("quote_snapshot_incomplete")
    if len(set(counters)) != 1:
        return rejected("quote_snapshot_incomplete")

    daily_rows = payload.get("daily")
    if not isinstance(daily_rows, list) or any(not isinstance(item, Mapping) for item in daily_rows):
        return rejected("daily_identity_mismatch")
    same_code_rows = [item for item in daily_rows if item.get("code") == code]
    if (
        len(same_code_rows) != 1
        or same_code_rows[0].get("asset_type") != "stock"
        or same_code_rows[0].get("exchange") != exchange
        or same_code_rows[0].get("as_of") != as_of
    ):
        return rejected("daily_identity_mismatch")
    daily = same_code_rows[0]
    if daily.get("is_final") is not False or daily.get("bar_state") != "intraday":
        return rejected("daily_evidence_unverified")

    data_status = daily.get("data_status")
    if (
        not isinstance(data_status, Mapping)
        or data_status.get("adjustment") != "qfq"
        or data_status.get("daily") != "verified"
        or data_status.get("is_final") is not True
        or data_status.get("latest_date") != previous_date
        or data_status.get("source") != "market_history_db"
        or data_status.get("stale") is not False
    ):
        return rejected("daily_evidence_unverified")

    basis = daily.get("price_basis")
    if not isinstance(basis, Mapping) or basis.get("adjustment") != "qfq":
        return rejected("price_basis_invalid")
    factor = basis.get("factor_vs_raw")
    adjusted_previous = basis.get("adjusted_previous_close")
    raw_previous = basis.get("raw_previous_close")
    adjusted_current = basis.get("adjusted_current_price")
    raw_current = basis.get("raw_current_price")
    if not _positive_price(factor) or not all(
        _positive_price(value)
        for value in (adjusted_previous, raw_previous, adjusted_current, raw_current)
    ):
        return rejected("price_basis_invalid")

    market = payload.get("market")
    stock_bars = market.get("stock_bars") if isinstance(market, Mapping) else None
    if not isinstance(stock_bars, list) or any(not isinstance(item, Mapping) for item in stock_bars):
        return rejected("raw_quote_mismatch")
    raw_quote_rows = [item for item in stock_bars if item.get("code") == code]
    if len(raw_quote_rows) != 1:
        return rejected("raw_quote_mismatch")
    raw_quote = raw_quote_rows[0]
    if (
        not _positive_price(raw_quote.get("prev_close"))
        or not _positive_price(raw_quote.get("close"))
        or not _close_enough(float(raw_quote["prev_close"]), float(raw_previous))
        or not _close_enough(float(raw_quote["close"]), float(raw_current))
        or not _close_enough(float(raw_previous) * float(factor), float(adjusted_previous))
        or not _close_enough(float(raw_current) * float(factor), float(adjusted_current))
        or not _close_enough(float(adjusted_previous), float(previous_bar.get("close")))
    ):
        return rejected("prior_close_anchor_mismatch")

    klines = daily.get("klines")
    if (
        not isinstance(klines, Mapping)
        or klines.get("adjustment") != "qfq"
        or klines.get("source") != "formal_history+eastmoney_intraday"
    ):
        return rejected("intraday_kline_invalid")
    dates = klines.get("dates")
    arrays = {
        key: klines.get(key)
        for key in ("opens", "highs", "lows", "closes", "finals")
    }
    if (
        not isinstance(dates, list)
        or len(dates) < 2
        or any(not isinstance(values, list) or len(values) != len(dates) for values in arrays.values())
        or dates[-2] != previous_date
        or dates[-1] != trade_date
        or arrays["finals"][-2] is not True
        or arrays["finals"][-1] is not False
    ):
        return rejected("intraday_kline_invalid")
    prior_close = arrays["closes"][-2]
    provisional_ohlc = [arrays[key][-1] for key in ("opens", "highs", "lows", "closes")]
    if (
        not _positive_price(prior_close)
        or not _close_enough(float(prior_close), float(previous_bar.get("close")))
        or not all(_positive_price(value) for value in provisional_ohlc)
        or not _close_enough(float(arrays["closes"][-1]), float(adjusted_current))
    ):
        return rejected("intraday_kline_invalid")
    provisional_open, provisional_high, provisional_low, provisional_close = map(float, provisional_ohlc)
    if (
        provisional_high < provisional_low
        or provisional_low > provisional_open
        or provisional_open > provisional_high
        or provisional_low > provisional_close
        or provisional_close > provisional_high
    ):
        return rejected("intraday_kline_invalid")
    if not _close_enough(provisional_open, float(final_bar.get("open"))):
        return rejected("open_anchor_mismatch")

    return {
        "status": "verified",
        "method": "preclose-qfq-factor-open-anchor-v1",
        "trade_date": trade_date,
        "previous_date": previous_date,
        "factor_vs_raw": float(factor),
        "preclose_as_of": as_of,
    }


def _percent_change(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None or start <= 0.0:
        return None
    return (end / start - 1.0) * 100.0


def _new_row(
    selection: Any,
    identity: Optional[str],
    identity_status: str,
    report_date: str,
    target_dates: Mapping[str, Optional[str]],
    as_of_date: date,
    duplicate_selection: bool = False,
) -> dict:
    selection_copy = copy.deepcopy(selection) if isinstance(selection, Mapping) else {
        "instrument_id": identity
    }
    maturity = {}
    bar_status = {"signal": "not_read"}
    for label in ("t1", "t2", "t3"):
        target = target_dates.get(label)
        if target is None:
            maturity[label] = "calendar_unavailable"
            bar_status[label] = "calendar_unavailable"
        elif _iso_date(target, label) > as_of_date:
            maturity[label] = "pending"
            bar_status[label] = "not_due"
        else:
            maturity[label] = "matured"
            bar_status[label] = "not_read"
    basis_by_metric = {
        "cc1": "not_matured",
        "gap1": "not_matured",
        "oc1": "within_bar_invariant",
        "oc2": "not_matured",
        "oc3": "not_matured",
    }
    for horizon, metrics in (
        ("t1", ("cc1", "gap1")),
        ("t2", ("oc2",)),
        ("t3", ("oc3",)),
    ):
        status = maturity[horizon]
        if status in ("pending", "calendar_unavailable"):
            for metric in metrics:
                basis_by_metric[metric] = status
    result = {
        "selection": selection_copy,
        "identity": identity,
        "report_date": report_date,
        "identity_status": identity_status,
        "selection_status": "duplicate_selection" if duplicate_selection else "unique",
        "target_dates": dict(target_dates),
        "maturity_status": maturity,
        "bar_status": bar_status,
        "basis_status": "not_matured",
        "basis_status_by_metric": basis_by_metric,
        "outcome_status": "pending",
        "signal_close": None,
        "open1": None,
        "close1": None,
        "cc1": None,
        "gap1": None,
        "oc1": None,
        "oc2": None,
        "oc3": None,
        "entry_one_price": None,
        "entry_one_price_uncertain": None,
        "bar_provenance": {},
    }
    if identity_status != "valid":
        result["outcome_status"] = {
            "ambiguous": "identity_ambiguous",
            "not_found": "identity_not_found",
            "duplicate_selection": "duplicate_selection",
            "date_mismatch": "selection_date_mismatch",
            "malformed": "identity_malformed",
        }.get(identity_status, "identity_unavailable")
        return result
    if duplicate_selection:
        result["outcome_status"] = "duplicate_selection"
    elif not target_dates.get("t1"):
        result["outcome_status"] = "calendar_unavailable"
    elif maturity["t1"] == "pending":
        result["outcome_status"] = "pending"
    return result


def _aggregate(rows: Sequence[Mapping[str, Any]], duplicate_rows: int) -> dict:
    valid_identity_rows = [row for row in rows if row["identity_status"] == "valid"]
    metric_values = {
        key: [row[key] for row in valid_identity_rows if _is_number(row.get(key))]
        for key in ("cc1", "gap1", "oc1", "oc2", "oc3")
    }

    def mean(key: str) -> Optional[float]:
        values = metric_values[key]
        return statistics.mean(values) if values else None

    def median(key: str) -> Optional[float]:
        values = metric_values[key]
        return statistics.median(values) if values else None

    cc = metric_values["cc1"]
    oc = metric_values["oc1"]
    counts_by_status = Counter(row["outcome_status"] for row in rows)
    missing_t1_bar = sum(
        row["maturity_status"]["t1"] == "matured"
        and row["bar_status"]["t1"] == "missing"
        for row in valid_identity_rows
    )
    missing_signal_bar = sum(
        row["maturity_status"]["t1"] == "matured"
        and row["bar_status"]["signal"] == "missing"
        for row in valid_identity_rows
    )
    missing_cc1_rows = sum(
        row["maturity_status"]["t1"] == "matured"
        and (
            row["bar_status"]["t1"] == "missing"
            or row["bar_status"]["signal"] == "missing"
        )
        for row in valid_identity_rows
    )
    pending_t1 = sum(
        row["maturity_status"]["t1"] == "pending" for row in valid_identity_rows
    )
    matured_t1 = sum(
        row["maturity_status"]["t1"] == "matured" for row in valid_identity_rows
    )
    outcome = {
        "selected": len(rows),
        "identity_valid_selected": len(valid_identity_rows),
        "active_signal_dates": 1 if rows else 0,
        "identity_malformed": sum(row["identity_status"] == "malformed" for row in rows),
        "identity_not_found": sum(row["identity_status"] == "not_found" for row in rows),
        "identity_ambiguous": sum(row["identity_status"] == "ambiguous" for row in rows),
        "duplicate_selection_identity": sum(
            row["selection_status"] == "duplicate_selection" for row in rows
        ),
        "matured_t1": matured_t1,
        "pending_t1": pending_t1,
        "missing_t1": missing_t1_bar,
        "missing_t1_bar": missing_t1_bar,
        "missing_signal_bar": missing_signal_bar,
        "invalid_t1": sum(
            row["maturity_status"]["t1"] == "matured"
            and row["bar_status"]["t1"] in ("invalid_ohlc", "invalid_status")
            for row in valid_identity_rows
        ),
        "nonfinal_t1": sum(
            row["maturity_status"]["t1"] == "matured"
            and row["bar_status"]["t1"] == "nonfinal"
            for row in valid_identity_rows
        ),
        "basis_unverified_t1": sum(
            row["basis_status_by_metric"]["cc1"] == "price_basis_unverified"
            for row in valid_identity_rows
        ),
        "calendar_unavailable": sum(
            row["maturity_status"]["t1"] == "calendar_unavailable"
            for row in valid_identity_rows
        ),
        "duplicate_rows": duplicate_rows,
        "observed_cc1": len(cc),
        "observed_gap1": len(metric_values["gap1"]),
        "observed_oc1": len(oc),
        "observed_oc2": len(metric_values["oc2"]),
        "observed_oc3": len(metric_values["oc3"]),
        "cc1_mean": mean("cc1"),
        "cc1_median": median("cc1"),
        "gap1_mean": mean("gap1"),
        "oc1_mean": mean("oc1"),
        "oc1_median": median("oc1"),
        "oc2_mean": mean("oc2"),
        "oc3_mean": mean("oc3"),
        "nextday_gain_ge5": sum(value >= 5.0 for value in cc),
        "nextday_loss_le_minus5": sum(value <= -5.0 for value in cc),
        "nextday_gain_ge5_ratio": (
            sum(value >= 5.0 for value in cc) / len(cc) if cc else None
        ),
        "open_close_gain_ge3": sum(value >= 3.0 for value in oc),
        "open_close_loss_le_minus5": sum(value <= -5.0 for value in oc),
        "entry_one_price_count": sum(
            row.get("entry_one_price") is True for row in valid_identity_rows
        ),
        "outcome_status_counts": dict(counts_by_status),
        "not_realized_profit": True,
        "interpretation_note": _OUTCOME_NOTES,
        "denominators": {
            "selected": len(rows),
            "identity_valid_selected": len(valid_identity_rows),
            "matured_t1": matured_t1,
            "observed_cc1": len(cc),
            "observed_gap1": len(metric_values["gap1"]),
            "observed_oc1": len(oc),
            "observed_oc2": len(metric_values["oc2"]),
            "observed_oc3": len(metric_values["oc3"]),
        },
    }
    # Preserve the package's familiar sample-size names, while retaining the
    # explicit pending/missing/basis counts above so those causes stay distinct.
    outcome["denominators"]["t1"] = {
        "selected": len(rows),
        "identity_valid_selected": len(valid_identity_rows),
        "matured": matured_t1,
        "pending": pending_t1,
        "missing": missing_cc1_rows,
        "nonfinal": outcome["nonfinal_t1"],
        "basis_unverified": outcome["basis_unverified_t1"],
        "observed": len(metric_values["cc1"]),
    }
    outcome["observed_T1"] = outcome["observed_cc1"]
    outcome["pending_T1"] = outcome["pending_t1"]
    outcome["matured_T1"] = outcome["matured_t1"]
    outcome["basis_unverified_T1"] = outcome["basis_unverified_t1"]
    outcome["missing_T1"] = missing_cc1_rows
    outcome["unavailable_T1"] = outcome["selected"] - outcome["observed_cc1"]
    outcome["oc2_observed"] = outcome["observed_oc2"]
    outcome["oc3_observed"] = outcome["observed_oc3"]
    for horizon, metric in (("t2", "oc2"), ("t3", "oc3")):
        horizon_rows = valid_identity_rows
        outcome["matured_{}".format(horizon)] = sum(
            row["maturity_status"][horizon] == "matured" for row in horizon_rows
        )
        outcome["pending_{}".format(horizon)] = sum(
            row["maturity_status"][horizon] == "pending" for row in horizon_rows
        )
        outcome["missing_{}".format(horizon)] = sum(
            row["maturity_status"][horizon] == "matured"
            and row["bar_status"][horizon] == "missing"
            for row in horizon_rows
        )
        outcome["nonfinal_{}".format(horizon)] = sum(
            row["maturity_status"][horizon] == "matured"
            and row["bar_status"][horizon] == "nonfinal"
            for row in horizon_rows
        )
        outcome["invalid_{}".format(horizon)] = sum(
            row["maturity_status"][horizon] == "matured"
            and row["bar_status"][horizon] in ("invalid_ohlc", "invalid_status")
            for row in horizon_rows
        )
        outcome["basis_unverified_{}".format(horizon)] = sum(
            row["basis_status_by_metric"][metric] == "price_basis_unverified"
            for row in horizon_rows
        )
        outcome["calendar_unavailable_{}".format(horizon)] = sum(
            row["maturity_status"][horizon] == "calendar_unavailable"
            for row in horizon_rows
        )
        denominator_observed = {
            "t1": len(metric_values["cc1"]),
            "t2": len(metric_values["oc2"]),
            "t3": len(metric_values["oc3"]),
        }[horizon]
        missing_count = (
            missing_cc1_rows
            if horizon == "t1"
            else outcome["missing_{}".format(horizon)]
        )
        outcome["denominators"][horizon] = {
            "selected": len(rows),
            "identity_valid_selected": len(valid_identity_rows),
            "matured": outcome["matured_{}".format(horizon)],
            "pending": outcome["pending_{}".format(horizon)] if horizon != "t1" else pending_t1,
            "missing": missing_count,
            "nonfinal": outcome["nonfinal_{}".format(horizon)],
            "basis_unverified": outcome["basis_unverified_{}".format(horizon)]
            if horizon != "t1"
            else outcome["basis_unverified_t1"],
            "observed": denominator_observed,
        }
    return outcome


def _evaluate_cohort(
    entries: Sequence[Any],
    report_date: date,
    as_of_date: date,
    connection: sqlite3.Connection,
    target_dates: Mapping[str, Optional[str]],
    registered: Mapping[Tuple[str, str], Sequence[int]],
    evidence_root: Path,
    preclose_cache: Dict[str, Optional[Mapping[str, Any]]],
) -> Tuple[List[dict], dict]:
    identities = []
    extracted = []
    for selection in entries:
        identity, selection_copy = _extract_identity(selection)
        identities.append(identity)
        extracted.append((identity, selection_copy))
    identity_counts = Counter(
        identity for identity in identities if _parse_identity(identity)[2] == "valid"
    )

    outcome_rows = []
    instruments = []
    for selection, (identity, _) in zip(entries, extracted):
        exchange, code, identity_status = _parse_identity(identity)
        mismatch = (
            isinstance(selection, Mapping)
            and selection.get("report_date") is not None
            and selection.get("report_date") != report_date.isoformat()
        )
        if mismatch and identity_status == "valid":
            identity_status = "date_mismatch"
        duplicate_selection = bool(
            identity and identity_counts.get(identity, 0) > 1
        )
        row = _new_row(
            selection,
            identity,
            identity_status,
            report_date.isoformat(),
            target_dates,
            as_of_date,
            duplicate_selection=duplicate_selection,
        )
        if duplicate_selection and identity_status == "valid":
            row["identity_status"] = "duplicate_selection"
            row["outcome_status"] = "duplicate_selection"
        elif identity_status == "valid":
            registered_ids = list(registered.get((exchange, code), ()))
            if len(registered_ids) == 0:
                row["identity_status"] = "not_found"
                row["outcome_status"] = "identity_not_found"
            elif len(registered_ids) > 1:
                row["identity_status"] = "ambiguous"
                row["outcome_status"] = "identity_ambiguous"
            else:
                instruments.append((row, registered_ids[0]))
        outcome_rows.append(row)

    # Candidate count is capped before this query; dates are exact and no
    # unselected identity or later available trading date can enter the scan.
    due_dates = {report_date.isoformat()}
    for label in ("t1", "t2", "t3"):
        value = target_dates.get(label)
        if value and _iso_date(value, label) <= as_of_date:
            due_dates.add(value)
    instrument_ids = sorted({instrument_id for _, instrument_id in instruments})
    grouped_bars = defaultdict(list)
    duplicate_rows = 0
    if instrument_ids and due_dates:
        instrument_marks = ",".join("?" for _ in instrument_ids)
        date_marks = ",".join("?" for _ in due_dates)
        sql = (
            "SELECT {} FROM bars_day WHERE instrument_id IN ({}) "
            "AND ts IN ({}) ORDER BY instrument_id, ts"
        ).format(", ".join(_BAR_COLUMNS), instrument_marks, date_marks)
        try:
            fetched = connection.execute(
                sql, tuple(instrument_ids) + tuple(sorted(due_dates))
            ).fetchall()
        except sqlite3.Error as exc:
            raise OutcomeDataError("bounded bars_day read failed") from exc
        for fetched_row in fetched:
            item = dict(zip(_BAR_COLUMNS, fetched_row))
            grouped_bars[(item["instrument_id"], item["ts"])].append(item)

    for row, instrument_id in instruments:
        bars = {}
        signal_key = (instrument_id, report_date.isoformat())
        signal_status, signal_bar, duplicates = _validate_bar(
            grouped_bars.get(signal_key, ())
        )
        duplicate_rows += duplicates
        row["bar_status"]["signal"] = signal_status
        if signal_bar:
            bars["signal"] = signal_bar
            row["signal_close"] = signal_bar["close"]
            row["bar_provenance"]["signal"] = {
                "adjustment": signal_bar.get("adjustment"),
                "source_batch": signal_bar.get("source_batch"),
                "updated_at": signal_bar.get("updated_at"),
            }

        for label in ("t1", "t2", "t3"):
            target = target_dates.get(label)
            if not target or row["maturity_status"][label] != "matured":
                continue
            bar_status, bar, duplicates = _validate_bar(
                grouped_bars.get((instrument_id, target), ())
            )
            duplicate_rows += duplicates
            row["bar_status"][label] = bar_status
            if bar:
                bars[label] = bar
                row["bar_provenance"][label] = {
                    "adjustment": bar.get("adjustment"),
                    "source_batch": bar.get("source_batch"),
                    "updated_at": bar.get("updated_at"),
                }

        signal = bars.get("signal")
        t1 = bars.get("t1")
        t2 = bars.get("t2")
        t3 = bars.get("t3")
        qfq_bridges = {}
        exchange, code = row["identity"][:2], row["identity"][2:]
        previous_labels = {
            "t1": (report_date.isoformat(), signal),
            "t2": (target_dates.get("t1"), t1),
            "t3": (target_dates.get("t2"), t2),
        }
        for label, current_bar in (("t1", t1), ("t2", t2), ("t3", t3)):
            if current_bar is None or current_bar.get("adjustment") != "qfq":
                continue
            previous_date, previous_bar = previous_labels[label]
            if not isinstance(previous_date, str):
                proof = {"status": "unverified", "reason": "previous_final_bar_missing"}
            else:
                proof = _qfq_bridge_proof(
                    evidence_root,
                    preclose_cache,
                    exchange,
                    code,
                    current_bar["ts"],
                    previous_date,
                    previous_bar,
                    current_bar,
                )
            qfq_bridges[label] = proof
            row["bar_provenance"].setdefault(label, {})["basis_proof"] = proof
        if t1:
            row["open1"] = t1["open"]
            row["close1"] = t1["close"]
            row["oc1"] = _percent_change(t1["open"], t1["close"])
            row["entry_one_price"] = all(
                _close_enough(t1["open"], t1[key])
                for key in ("high", "low", "close")
            )
            row["entry_one_price_uncertain"] = row["entry_one_price"]
            row["basis_status_by_metric"]["oc1"] = "within_bar_invariant"
        if signal and t1:
            if _basis_is_raw(signal, t1):
                row["cc1"] = _percent_change(signal["close"], t1["close"])
                row["gap1"] = _percent_change(signal["close"], t1["open"])
                row["basis_status_by_metric"]["cc1"] = "raw_comparable"
                row["basis_status_by_metric"]["gap1"] = "raw_comparable"
            elif (
                signal.get("adjustment") == "qfq"
                and t1.get("adjustment") == "qfq"
                and qfq_bridges.get("t1", {}).get("status") == "verified"
            ):
                row["cc1"] = _percent_change(signal["close"], t1["close"])
                row["gap1"] = _percent_change(signal["close"], t1["open"])
                row["basis_status_by_metric"]["cc1"] = "qfq_comparable"
                row["basis_status_by_metric"]["gap1"] = "qfq_comparable"
            else:
                row["basis_status_by_metric"]["cc1"] = "price_basis_unverified"
                row["basis_status_by_metric"]["gap1"] = "price_basis_unverified"
        elif row["maturity_status"]["t1"] == "matured":
            basis_status = "data_unavailable"
            if t1 and not signal:
                basis_status = "signal_bar_unavailable"
            row["basis_status_by_metric"]["cc1"] = basis_status
            row["basis_status_by_metric"]["gap1"] = basis_status
        for label, target_label in (("oc2", "t2"), ("oc3", "t3")):
            if row["maturity_status"][target_label] != "matured":
                continue
            target_bar = bars.get(target_label)
            if not t1 or not target_bar:
                row["basis_status_by_metric"][label] = "data_unavailable"
            elif _basis_is_raw(t1, target_bar):
                # Retain the existing raw-endpoint path contract. Intermediate
                # raw bars are not needed to compare these unchanged raw prices.
                row[label] = _percent_change(t1["open"], target_bar["close"])
                row["basis_status_by_metric"][label] = "raw_comparable"
            elif t1.get("adjustment") == "qfq" and target_bar.get("adjustment") == "qfq":
                bridge_labels = ("t2",) if label == "oc2" else ("t2", "t3")
                if label == "oc3" and not t2:
                    row["basis_status_by_metric"][label] = "data_unavailable"
                elif all(
                    qfq_bridges.get(bridge_label, {}).get("status") == "verified"
                    for bridge_label in bridge_labels
                ):
                    row[label] = _percent_change(t1["open"], target_bar["close"])
                    row["basis_status_by_metric"][label] = "qfq_comparable"
                else:
                    row["basis_status_by_metric"][label] = "price_basis_unverified"
            else:
                row["basis_status_by_metric"][label] = "price_basis_unverified"

        crossdate_basis = [
            row["basis_status_by_metric"][key]
            for key in ("cc1", "gap1", "oc2", "oc3")
        ]
        if "price_basis_unverified" in crossdate_basis:
            row["basis_status"] = "price_basis_unverified"
        elif "qfq_comparable" in crossdate_basis:
            row["basis_status"] = "qfq_comparable"
        elif "raw_comparable" in crossdate_basis:
            row["basis_status"] = "raw_comparable"
        elif row["maturity_status"]["t1"] == "pending":
            row["basis_status"] = "not_matured"
        elif row["maturity_status"]["t1"] == "calendar_unavailable":
            row["basis_status"] = "calendar_unavailable"
        else:
            row["basis_status"] = "data_unavailable"

        if row["selection_status"] == "duplicate_selection":
            row["outcome_status"] = "duplicate_selection"
        elif row["maturity_status"]["t1"] == "calendar_unavailable":
            row["outcome_status"] = "calendar_unavailable"
        elif row["maturity_status"]["t1"] == "pending":
            row["outcome_status"] = "pending"
        elif row["bar_status"]["signal"] != "valid":
            row["outcome_status"] = row["bar_status"]["signal"]
        elif row["bar_status"]["t1"] != "valid":
            row["outcome_status"] = row["bar_status"]["t1"]
        elif row["basis_status_by_metric"]["cc1"] == "price_basis_unverified":
            row["outcome_status"] = "basis_unverified"
        else:
            row["outcome_status"] = "available"

    aggregate = _aggregate(outcome_rows, duplicate_rows)
    return outcome_rows, aggregate


def _cohort_entries(snapshot: Mapping[str, Any], key: str) -> Sequence[Any]:
    entries = snapshot.get(key, [])
    if not isinstance(entries, (list, tuple)):
        raise ValueError("snapshot {} must be a list".format(key))
    if len(entries) > MAX_SELECTIONS:
        raise ValueError(
            "snapshot {} exceeds bounded {}-selection limit".format(
                key, MAX_SELECTIONS
            )
        )
    return entries


def _required_columns(
    connection: sqlite3.Connection, table: str, required: Iterable[str]
) -> None:
    try:
        actual = {row[1] for row in connection.execute("PRAGMA table_info({})".format(table))}
    except sqlite3.Error as exc:
        raise OutcomeDataError("could not inspect {} schema".format(table)) from exc
    missing = set(required) - actual
    if missing:
        raise OutcomeDataError(
            "{} schema is missing required columns: {}".format(
                table, ", ".join(sorted(missing))
            )
        )


def evaluate_frozen_selection(
    snapshot: Mapping[str, Any], db_path: Any, as_of_date: str
) -> dict:
    """Evaluate only frozen selected identities against exact final daily bars.

    ``snapshot`` must contain ``report_date`` and a frozen ``selected`` list.
    An optional ``baseline_selected`` list is evaluated independently with the
    same data and denominator rules. Each cohort is capped at five entries.
    ``as_of_date`` is an explicit completed-report date; database rows after it
    are never queried, even when already present in the local database.
    """
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping")
    report_day = _iso_date(snapshot.get("report_date"), "report_date")
    as_of_day = _iso_date(as_of_date, "as_of_date")
    if report_day > as_of_day:
        raise ValueError("report_date must not be after as_of_date")
    selected = _cohort_entries(snapshot, "selected")
    baseline = _cohort_entries(snapshot, "baseline_selected")
    database_path = str(Path(db_path).expanduser().resolve())
    uri = "file:{}?mode=ro".format(quote(database_path, safe="/:"))
    try:
        connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
    except sqlite3.Error as exc:
        raise OutcomeDataError("could not open market history read-only") from exc
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        preclose_cache = {}
        _required_columns(
            connection,
            "instruments",
            ("instrument_id", "asset_type", "exchange", "code"),
        )
        _required_columns(
            connection, "trade_calendar", ("exchange", "trade_date", "is_open")
        )
        _required_columns(connection, "bars_day", _BAR_COLUMNS)
        # Pin the SQLite snapshot before reading calendar and bar records.
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()

        state = _calendar_state(report_day, connection)
        if state == "closed":
            raise ValueError("report_date is not an open trading day")
        schedule_status = "available"
        target_dates = {"t1": None, "t2": None, "t3": None}
        if state == "unknown":
            schedule_status = "calendar_unavailable"
        else:
            target_dates, schedule_status = _target_dates(
                report_day, connection
            )

        needed_identities = set()
        for entries in (selected, baseline):
            for selection in entries:
                identity, _ = _extract_identity(selection)
                exchange, code, status = _parse_identity(identity)
                if status == "valid":
                    needed_identities.add((exchange, code))
        registered = {}
        for exchange, code in sorted(needed_identities):
            try:
                found = connection.execute(
                    "SELECT instrument_id, asset_type FROM instruments "
                    "WHERE exchange=? AND code=?",
                    (exchange, code),
                ).fetchall()
            except sqlite3.Error as exc:
                raise OutcomeDataError("bounded instrument identity read failed") from exc
            stock_ids = [
                int(item[0])
                for item in found
                if str(item[1]).strip().lower() == "stock"
            ]
            registered[(exchange, code)] = stock_ids

        selected_rows, metrics = _evaluate_cohort(
            selected,
            report_day,
            as_of_day,
            connection,
            target_dates,
            registered,
            Path(database_path).parent,
            preclose_cache,
        )
        result = {
            "status": "research_only",
            "report_date": report_day.isoformat(),
            "as_of_date": as_of_day.isoformat(),
            "target_dates": dict(target_dates),
            "calendar_status": schedule_status,
            "outcome_rows": selected_rows,
            "metrics": metrics,
            "not_a_trade_instruction": True,
            "interpretation_note": _OUTCOME_NOTES,
        }
        if "baseline_selected" in snapshot:
            baseline_rows, baseline_metrics = _evaluate_cohort(
                baseline,
                report_day,
                as_of_day,
                connection,
                target_dates,
                registered,
                Path(database_path).parent,
                preclose_cache,
            )
            result["baseline_outcome_rows"] = baseline_rows
            result["baseline_metrics"] = baseline_metrics
        return result
    except sqlite3.Error as exc:
        raise OutcomeDataError("read-only outcome snapshot failed") from exc
    finally:
        try:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        connection.close()
