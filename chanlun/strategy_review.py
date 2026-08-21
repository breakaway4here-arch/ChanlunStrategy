"""Deterministic, attributable strategy scorecards from immutable ledger rows."""

import math
import os
from collections import Counter, defaultdict
from statistics import mean, median

from .market_history_store import MarketHistoryStore


HORIZONS = (1, 3, 5)
EXPECTED_ADJUSTMENT = "qfq"
BENCHMARK_CODE = "000300"


def persist_review_benchmark_kline(
    db_path,
    kline,
    *,
    code=BENCHMARK_CODE,
    name="沪深300",
):
    """Persist a multi-source-verified index series as canonical final bars."""
    kline = kline if isinstance(kline, dict) else {}
    dates = _plain_list(kline.get("dates"))
    arrays = {
        key: _plain_list(kline.get(key))
        for key in ("opens", "closes", "highs", "lows", "volumes")
    }
    size = len(dates)
    if not size or any(len(values) != size for values in arrays.values()):
        raise ValueError("invalid benchmark kline")
    amounts = _plain_list(kline.get("amounts"))
    if len(amounts) != size:
        amounts = [0.0] * size
    bars = []
    for index, trade_date in enumerate(dates):
        amount = _finite(amounts[index])
        bars.append({
            "ts": str(trade_date).split(" ", 1)[0],
            "open": arrays["opens"][index],
            "close": arrays["closes"][index],
            "high": arrays["highs"][index],
            "low": arrays["lows"][index],
            "volume": arrays["volumes"][index],
            "amount": amount if amount is not None and amount >= 0 else 0.0,
            "adjustment": EXPECTED_ADJUSTMENT,
            "is_final": True,
            "source_batch": "verified_index_history",
        })
    with MarketHistoryStore(db_path) as store:
        instrument_id = store.upsert_instrument(
            "index", "SH", code, name
        )
        written = store.upsert_bars("day", instrument_id, bars)
    return {
        "status": "ok",
        "code": code,
        "bars": size,
        "rows_written": written,
        "latest_date": bars[-1]["ts"],
    }


def _exchange(code):
    code = str(code or "")
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    return ""


def load_review_market_context_from_store(db_path, entries, *, as_of=None):
    """Load stocks, an authoritative market calendar and fixed benchmark."""
    resolved_path = os.fspath(db_path)
    codes = sorted({
        str(entry.get("code") or "")
        for entry in entries or []
        if isinstance(entry, dict) and _exchange(entry.get("code"))
    })
    diagnostics = {
        "status": "missing",
        "requested_codes": len(codes),
        "resolved_codes": 0,
        "missing_codes": list(codes),
        "adjustment": "",
    }
    if not codes:
        diagnostics.update(status="empty", missing_codes=[])
        return {}, [], None, diagnostics
    if not os.path.exists(resolved_path):
        diagnostics["reason"] = "market_history_db_missing"
        return {}, [], None, diagnostics
    report_dates = sorted({
        str(entry.get("report_date") or "")
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("report_date")
    })
    start = report_dates[0] if report_dates else None
    try:
        with MarketHistoryStore(resolved_path, readonly=True) as store:
            adjustment = store.get_canonical_adjustment("day") or ""
            diagnostics["adjustment"] = adjustment
            if adjustment != EXPECTED_ADJUSTMENT:
                diagnostics.update(
                    status="adjustment_mismatch",
                    reason="canonical_adjustment_mismatch",
                )
                return {}, [], None, diagnostics
            identities = [(_exchange(code), code) for code in codes]
            instruments = store.resolve_instruments("stock", identities)
            by_id = {
                int(instrument["instrument_id"]): code
                for (exchange, code), instrument in instruments.items()
            }
            rows_by_id = store.query_bars_many(
                "day",
                sorted(by_id),
                start=start,
                end=as_of,
            )
            calendar_rows = store.connection.execute(
                """
                SELECT trade_date
                FROM trade_calendar
                WHERE is_open=1 AND trade_date>=?
                  AND (? IS NULL OR trade_date<=?)
                GROUP BY trade_date
                ORDER BY trade_date
                """,
                (start or "", as_of, as_of),
            ).fetchall()
            calendar_source = "trade_calendar"
            if not calendar_rows:
                calendar_rows = store.connection.execute(
                    """
                    SELECT substr(b.ts, 1, 10) AS trade_date
                    FROM bars_day b
                    JOIN instruments i ON i.instrument_id=b.instrument_id
                    WHERE i.asset_type='stock' AND b.is_final=1
                      AND substr(b.ts, 1, 10)>=?
                      AND (? IS NULL OR substr(b.ts, 1, 10)<=?)
                    GROUP BY substr(b.ts, 1, 10)
                    ORDER BY trade_date
                    """,
                    (start or "", as_of, as_of),
                ).fetchall()
                calendar_source = "canonical_stock_market_dates"
            benchmark_instrument = store.resolve_instrument(
                "index", "SH", "000300"
            )
            benchmark_rows = []
            if benchmark_instrument:
                benchmark_rows = store.query_bars(
                    "day",
                    int(benchmark_instrument["instrument_id"]),
                    start=start,
                    end=as_of,
                )
    except (OSError, ValueError, TypeError) as exc:
        diagnostics.update(
            status="error",
            reason="{}".format(type(exc).__name__),
        )
        return {}, [], None, diagnostics

    klines = {}
    for instrument_id, rows in rows_by_id.items():
        code = by_id.get(int(instrument_id))
        if not code or not rows:
            continue
        klines[code] = {
            "dates": [str(row.get("ts") or "").split(" ", 1)[0] for row in rows],
            "opens": [row.get("open") for row in rows],
            "closes": [row.get("close") for row in rows],
            "highs": [row.get("high") for row in rows],
            "lows": [row.get("low") for row in rows],
            "volumes": [row.get("volume") for row in rows],
            "is_final": [bool(row.get("is_final")) for row in rows],
            "adjustment": adjustment,
            "source": "market_history_db",
        }
    diagnostics.update(
        status="ok" if klines else "missing",
        resolved_codes=len(klines),
        missing_codes=sorted(set(codes) - set(klines)),
        calendar_source=calendar_source,
        calendar_days=len(calendar_rows),
        benchmark_status="ok" if benchmark_rows else "missing",
        benchmark_code="000300",
    )
    trading_calendar = [str(row["trade_date"]) for row in calendar_rows]
    benchmark_kline = None
    if benchmark_rows:
        benchmark_kline = {
            "dates": [
                str(row.get("ts") or "").split(" ", 1)[0]
                for row in benchmark_rows
            ],
            "opens": [row.get("open") for row in benchmark_rows],
            "closes": [row.get("close") for row in benchmark_rows],
            "highs": [row.get("high") for row in benchmark_rows],
            "lows": [row.get("low") for row in benchmark_rows],
            "volumes": [row.get("volume") for row in benchmark_rows],
            "is_final": [bool(row.get("is_final")) for row in benchmark_rows],
            "adjustment": adjustment,
            "source": "market_history_db",
            "code": "000300",
        }
    return klines, trading_calendar, benchmark_kline, diagnostics


def load_review_klines_from_store(db_path, entries, *, as_of=None):
    """Backward-compatible stock-bar loader used by focused callers."""
    klines, _calendar, _benchmark, diagnostics = (
        load_review_market_context_from_store(
            db_path, entries, as_of=as_of
        )
    )
    return klines, diagnostics


def _plain_list(value):
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _empty_outcome(entry, status):
    return {
        "recommendation_id": str(entry.get("recommendation_id") or ""),
        "code": str(entry.get("code") or ""),
        "name": str(entry.get("name") or ""),
        "report_date": str(entry.get("report_date") or ""),
        "status": status,
        "entry_mode": "unknown",
        "entry_date": "",
        "entry_price": None,
        "intended_horizon": None,
        "intended_horizon_label": "",
        "close_return": None,
        "primary_mfe": None,
        "primary_mae": None,
        "target_dates": {"t1": "", "t3": "", "t5": ""},
        "returns": {"t1": None, "t3": None, "t5": None},
        "mae": {"t1": None, "t3": None, "t5": None},
        "mfe": {"t1": None, "t3": None, "t5": None},
        "maturity": {
            "t1": "unavailable",
            "t3": "unavailable",
            "t5": "unavailable",
        },
        "benchmark_status": "not_requested",
        "benchmark_alignment": {
            "t1": "not_requested",
            "t3": "not_requested",
            "t5": "not_requested",
        },
        "excess_returns": {"t1": None, "t3": None, "t5": None},
        "research_results": {
            key: {
                "horizon": "T+{}".format(horizon),
                "status": "unavailable",
                "target_date": "",
                "close_return": None,
                "mfe": None,
                "mae": None,
            }
            for key, horizon in (("t1", 1), ("t3", 3), ("t5", 5))
        },
    }


def _validated_kline(kline, expected_adjustment):
    if not isinstance(kline, dict):
        return None, "market_data_missing"
    adjustment = str(kline.get("adjustment") or "").strip()
    if adjustment != expected_adjustment:
        return None, "adjustment_mismatch"
    dates = [str(value).split(" ", 1)[0] for value in _plain_list(kline.get("dates"))]
    arrays = {
        key: [_finite(value) for value in _plain_list(kline.get(key))]
        for key in ("opens", "closes", "highs", "lows", "volumes")
    }
    size = len(dates)
    if not size or any(len(values) != size for values in arrays.values()):
        return None, "market_data_invalid"
    if any(
        value is None
        for key in ("opens", "closes", "highs", "lows")
        for value in arrays[key]
    ):
        return None, "market_data_invalid"
    if dates != sorted(set(dates)):
        return None, "market_data_invalid"
    finals = _plain_list(kline.get("is_final"))
    if len(finals) != size:
        return None, "market_data_invalid"
    return {
        "dates": dates,
        "opens": arrays["opens"],
        "closes": arrays["closes"],
        "highs": arrays["highs"],
        "lows": arrays["lows"],
        "volumes": arrays["volumes"],
        "is_final": [bool(value) for value in finals],
        "adjustment": adjustment,
    }, "ok"


def _entry_mode(entry, contribution=None):
    if isinstance(contribution, dict):
        return str(contribution.get("entry_mode") or "").strip() or "unknown"
    modes = {
        str(row.get("entry_mode") or "")
        for row in entry.get("strategy_contributions") or []
        if isinstance(row, dict) and row.get("cohort_eligible") is True
    }
    if len(modes) == 1:
        return next(iter(modes))
    return "unknown"


def _intended_horizon(contribution):
    if not isinstance(contribution, dict):
        return None
    value = contribution.get("intended_horizon")
    if isinstance(value, bool):
        return None
    try:
        horizon = int(value)
    except (TypeError, ValueError):
        return None
    return horizon if horizon in HORIZONS else None


def _attach_research_contract(outcome, contribution):
    horizon = _intended_horizon(contribution)
    outcome["intended_horizon"] = horizon
    outcome["intended_horizon_label"] = (
        "T+{}".format(horizon) if horizon is not None else ""
    )
    outcome["research_results"] = {
        key: {
            "horizon": "T+{}".format(value),
            "status": outcome["maturity"].get(key, "unavailable"),
            "target_date": outcome["target_dates"].get(key, ""),
            "close_return": outcome["returns"].get(key),
            "mfe": outcome["mfe"].get(key),
            "mae": outcome["mae"].get(key),
        }
        for key, value in (("t1", 1), ("t3", 3), ("t5", 5))
    }
    primary_key = "t{}".format(horizon) if horizon is not None else None
    outcome["close_return"] = (
        outcome["returns"].get(primary_key) if primary_key else None
    )
    outcome["primary_mfe"] = (
        outcome["mfe"].get(primary_key) if primary_key else None
    )
    outcome["primary_mae"] = (
        outcome["mae"].get(primary_key) if primary_key else None
    )
    return outcome


def _normalized_calendar(trading_calendar):
    dates = [
        str(value).split(" ", 1)[0]
        for value in _plain_list(trading_calendar)
        if str(value or "").strip()
    ]
    if not dates or dates != sorted(set(dates)):
        return None
    return dates


def _evaluate_without_benchmark(
    entry,
    kline,
    expected_adjustment,
    *,
    contribution=None,
    trading_calendar=None,
):
    outcome = _empty_outcome(entry, "market_data_missing")
    normalized, status = _validated_kline(kline, expected_adjustment)
    if normalized is None:
        outcome["status"] = status
        return outcome
    calendar = _normalized_calendar(trading_calendar)
    if calendar is None:
        outcome["status"] = "calendar_missing"
        return outcome
    report_date = str(entry.get("report_date") or "")
    try:
        report_calendar_index = calendar.index(report_date)
    except ValueError:
        outcome["status"] = "recommendation_calendar_missing"
        return outcome
    date_index = {
        trade_date: index
        for index, trade_date in enumerate(normalized["dates"])
    }
    report_index = date_index.get(report_date)
    if report_index is None:
        outcome["status"] = "recommendation_date_missing"
        return outcome
    if not normalized["is_final"][report_index]:
        outcome["status"] = "recommendation_not_final"
        return outcome
    mode = _entry_mode(entry, contribution)
    outcome["entry_mode"] = mode
    if mode == "unknown":
        outcome["status"] = "entry_mode_unknown"
        return outcome
    if mode == "immediate_close":
        return _evaluate_immediate_close(
            outcome,
            normalized,
            calendar,
            report_calendar_index,
            report_index,
            date_index,
            contribution,
        )
    if mode != "delay1_open":
        outcome["status"] = "unsupported_entry_mode"
        return outcome
    entry_calendar_index = report_calendar_index + 1
    if entry_calendar_index >= len(calendar):
        outcome["status"] = "right_censored"
        outcome["maturity"] = {
            "t1": "right_censored",
            "t3": "right_censored",
            "t5": "right_censored",
        }
        return outcome
    entry_date = calendar[entry_calendar_index]
    entry_index = date_index.get(entry_date)
    if entry_index is None:
        outcome["status"] = "suspended_entry"
        return outcome
    if not normalized["is_final"][entry_index]:
        outcome["status"] = "right_censored"
        return outcome
    entry_volume = normalized["volumes"][entry_index]
    if entry_volume is None or entry_volume <= 0:
        outcome["status"] = "suspended_entry"
        return outcome
    entry_price = normalized["opens"][entry_index]
    if entry_price is None or entry_price <= 0:
        outcome["status"] = "market_data_invalid"
        return outcome
    previous_close = normalized["closes"][report_index]
    one_price = (
        normalized["opens"][entry_index]
        == normalized["closes"][entry_index]
        == normalized["highs"][entry_index]
        == normalized["lows"][entry_index]
    )
    locked_move = (
        entry_price / previous_close - 1.0 >= 0.048
        if previous_close and previous_close > 0 else False
    )
    if one_price and locked_move:
        outcome["status"] = "limit_locked_entry"
        return outcome

    outcome["entry_date"] = entry_date
    outcome["entry_price"] = entry_price
    maturity = {}
    returns = {}
    target_dates = {}
    mae = {}
    mfe = {}
    for horizon in HORIZONS:
        key = "t{}".format(horizon)
        target_calendar_index = report_calendar_index + horizon
        if target_calendar_index >= len(calendar):
            target_dates[key] = ""
            maturity[key] = "right_censored"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        target_date = calendar[target_calendar_index]
        target_dates[key] = target_date
        endpoint = date_index.get(target_date)
        if endpoint is None:
            maturity[key] = "unavailable"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        if not normalized["is_final"][endpoint]:
            maturity[key] = "right_censored"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        maturity[key] = "mature"
        returns[key] = (
            (normalized["closes"][endpoint] - entry_price)
            / entry_price * 100.0
        )
        path_indexes = [
            date_index[trade_date]
            for trade_date in calendar[
                entry_calendar_index:target_calendar_index + 1
            ]
            if trade_date in date_index
            and normalized["is_final"][date_index[trade_date]]
        ]
        mae[key] = (
            (min(normalized["lows"][index] for index in path_indexes)
             - entry_price) / entry_price * 100.0
            if path_indexes else None
        )
        mfe[key] = (
            (max(normalized["highs"][index] for index in path_indexes)
             - entry_price) / entry_price * 100.0
            if path_indexes else None
        )
    outcome["target_dates"] = target_dates
    outcome["returns"] = returns
    outcome["mae"] = mae
    outcome["mfe"] = mfe
    outcome["maturity"] = maturity
    if maturity["t5"] == "mature":
        outcome["status"] = "evaluated"
    elif any(value == "mature" for value in maturity.values()):
        outcome["status"] = "partial"
    else:
        outcome["status"] = "right_censored"
    return _attach_research_contract(outcome, contribution)


def _evaluate_immediate_close(
    outcome,
    normalized,
    calendar,
    report_calendar_index,
    report_index,
    date_index,
    contribution,
):
    entry_price = normalized["closes"][report_index]
    if entry_price is None or entry_price <= 0:
        outcome["status"] = "market_data_invalid"
        return _attach_research_contract(outcome, contribution)
    outcome["entry_date"] = calendar[report_calendar_index]
    outcome["entry_price"] = entry_price
    maturity = {}
    returns = {}
    target_dates = {}
    mae = {}
    mfe = {}
    maturity_reasons = {}
    for horizon in HORIZONS:
        key = "t{}".format(horizon)
        target_calendar_index = report_calendar_index + horizon
        if target_calendar_index >= len(calendar):
            target_dates[key] = ""
            maturity[key] = "pending"
            maturity_reasons[key] = "future_horizon_not_available"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        path_dates = calendar[
            report_calendar_index + 1:target_calendar_index + 1
        ]
        target_dates[key] = calendar[target_calendar_index]
        if any(trade_date not in date_index for trade_date in path_dates):
            maturity[key] = "insufficient"
            maturity_reasons[key] = "future_trade_bar_missing"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        path_indexes = [date_index[trade_date] for trade_date in path_dates]
        if any(not normalized["is_final"][index] for index in path_indexes):
            maturity[key] = "pending"
            maturity_reasons[key] = "future_bar_not_final"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        if any(
            normalized["volumes"][index] is None
            or normalized["volumes"][index] <= 0
            for index in path_indexes
        ):
            maturity[key] = "insufficient"
            maturity_reasons[key] = "suspended_or_non_trading_bar"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        endpoint = path_indexes[-1]
        maturity[key] = "mature"
        maturity_reasons[key] = ""
        returns[key] = (
            (normalized["closes"][endpoint] - entry_price)
            / entry_price * 100.0
        )
        mae[key] = (
            min(normalized["lows"][index] for index in path_indexes)
            / entry_price - 1.0
        ) * 100.0
        mfe[key] = (
            max(normalized["highs"][index] for index in path_indexes)
            / entry_price - 1.0
        ) * 100.0
    outcome["target_dates"] = target_dates
    outcome["returns"] = returns
    outcome["mae"] = mae
    outcome["mfe"] = mfe
    outcome["maturity"] = maturity
    outcome["maturity_reasons"] = maturity_reasons
    if maturity["t5"] == "mature":
        outcome["status"] = "evaluated"
    elif any(value == "mature" for value in maturity.values()):
        outcome["status"] = "partial"
    elif any(value == "pending" for value in maturity.values()):
        outcome["status"] = "pending"
    else:
        outcome["status"] = "insufficient"
    return _attach_research_contract(outcome, contribution)


def evaluate_recommendation_entry(
    entry,
    kline,
    *,
    contribution=None,
    trading_calendar=None,
    benchmark_kline=None,
    expected_adjustment=EXPECTED_ADJUSTMENT,
):
    """Evaluate one record under its declared research entry contract."""
    entry = entry if isinstance(entry, dict) else {}
    outcome = _evaluate_without_benchmark(
        entry,
        kline,
        expected_adjustment,
        contribution=contribution,
        trading_calendar=trading_calendar,
    )
    if benchmark_kline is None:
        return outcome
    benchmark = _evaluate_without_benchmark(
        entry,
        benchmark_kline,
        expected_adjustment,
        contribution=contribution,
        trading_calendar=trading_calendar,
    )
    if (
        benchmark.get("status") not in {"evaluated", "partial"}
        or benchmark.get("entry_date") != outcome.get("entry_date")
    ):
        outcome["benchmark_status"] = "unaligned"
        outcome["benchmark_alignment"] = {
            key: "unaligned" for key in ("t1", "t3", "t5")
        }
        return outcome
    alignment = {}
    excess = {}
    for key in ("t1", "t3", "t5"):
        if outcome["returns"].get(key) is None:
            alignment[key] = "unavailable"
            excess[key] = None
        elif (
            benchmark["returns"].get(key) is not None
            and benchmark["target_dates"].get(key)
            == outcome["target_dates"].get(key)
        ):
            alignment[key] = "aligned"
            excess[key] = (
                outcome["returns"][key] - benchmark["returns"][key]
            )
        else:
            alignment[key] = "unaligned"
            excess[key] = None
    outcome["benchmark_alignment"] = alignment
    aligned_count = sum(value == "aligned" for value in alignment.values())
    outcome["benchmark_status"] = (
        "aligned" if aligned_count == len(HORIZONS)
        else ("partial" if aligned_count else "unaligned")
    )
    outcome["excess_returns"] = excess
    return outcome


def _reason_summary(contribution):
    snapshot = contribution.get("reason_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    decision = snapshot.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    best_buy = snapshot.get("best_buy_point")
    best_buy = best_buy if isinstance(best_buy, dict) else {}
    parts = [
        str(decision.get("decision") or "").strip(),
        str(best_buy.get("type") or "").strip(),
        str(best_buy.get("reason") or "").strip(),
    ]
    return " · ".join(part for part in parts if part) or "推荐理由未知"


def _representative_samples(samples, *, contracted):
    if not samples:
        return []
    if not contracted:
        return sorted(
            samples,
            key=lambda row: (
                str(row.get("rec_date") or ""),
                str(row.get("recommendation_id") or ""),
            ),
            reverse=True,
        )[:3]
    ordered = sorted(samples, key=lambda row: (
        row.get("return_pct") is None,
        row.get("return_pct") if row.get("return_pct") is not None else 0,
        row.get("recommendation_id"),
    ))
    indexes = [0, len(ordered) // 2, len(ordered) - 1]
    selected = []
    seen = set()
    for index in indexes:
        row = ordered[index]
        key = row.get("recommendation_id")
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected[:3]


def _episode_rows(rows, trading_calendar):
    calendar = _normalized_calendar(trading_calendar) or []
    date_index = {value: index for index, value in enumerate(calendar)}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["entry"]["code"]].append(row)
    episodes = []
    for code in sorted(grouped):
        ordered = sorted(
            grouped[code],
            key=lambda row: (
                row["entry"]["report_date"],
                row["contribution"].get("contribution_id") or "",
            ),
        )
        previous_index = None
        previous_date = None
        for row in ordered:
            current_date = row["entry"]["report_date"]
            if current_date == previous_date:
                continue
            current_index = date_index.get(current_date)
            if (
                previous_index is not None
                and current_index is not None
                and current_index == previous_index + 1
            ):
                previous_index = current_index
                previous_date = current_date
                continue
            episodes.append(row)
            previous_index = current_index
            previous_date = current_date
    return episodes


def _percentage(values, predicate):
    if not values:
        return None
    return sum(1 for value in values if predicate(value)) / len(values) * 100.0


def _return_summary(rows):
    values = [
        float(row["return_pct"])
        for row in rows
        if row.get("return_pct") is not None
    ]
    return {
        "sample_size": len(values),
        "mean_close_return": mean(values) if values else None,
        "median_close_return": median(values) if values else None,
        "up_rate": _percentage(values, lambda value: value > 0),
        "hit_rate_ge_5": _percentage(values, lambda value: value >= 5),
        "loss_rate_le_minus_5": _percentage(
            values, lambda value: value <= -5
        ),
        "worst_close_return": min(values) if values else None,
    }


def _time_stability(rows):
    by_month = defaultdict(list)
    by_date = defaultdict(list)
    for row in rows:
        rec_date = str(row.get("rec_date") or "")
        if row.get("return_pct") is None or not rec_date:
            continue
        by_month[rec_date[:7]].append(row)
        by_date[rec_date].append(row)

    monthly = []
    for month_name in sorted(by_month):
        summary = _return_summary(by_month[month_name])
        summary["month"] = month_name
        monthly.append(summary)

    rolling = []
    active_dates = sorted(by_date)
    window_size = 20
    for start in range(0, len(active_dates), window_size):
        window_dates = active_dates[start:start + window_size]
        if not window_dates:
            continue
        window_rows = [
            row for trade_date in window_dates for row in by_date[trade_date]
        ]
        summary = _return_summary(window_rows)
        summary.update({
            "start_date": window_dates[0],
            "end_date": window_dates[-1],
            "active_dates": len(window_dates),
        })
        rolling.append(summary)

    month_means = [
        item["mean_close_return"]
        for item in monthly
        if item.get("mean_close_return") is not None
    ]
    return {
        "monthly": monthly,
        "rolling_20_active_dates": rolling,
        "positive_month_rate": _percentage(
            month_means, lambda value: value > 0
        ),
        "worst_month_mean": min(month_means) if month_means else None,
    }


def _top_k_diagnostics(rows):
    by_date = defaultdict(list)
    for row in rows:
        if row.get("return_pct") is None:
            continue
        by_date[str(row.get("rec_date") or "")].append(row)
    if not by_date:
        return []

    diagnostics = []
    for limit in (1, 3, 5, 10):
        selected = []
        for rec_date in sorted(by_date):
            ranked = sorted(
                by_date[rec_date],
                key=lambda row: (
                    -_recommendation_score(row),
                    str(row.get("code") or ""),
                ),
            )
            selected.extend(ranked[:limit])
        summary = _return_summary(selected)
        summary.update({
            "top_k": limit,
            "active_dates": len(by_date),
            "diagnostic_only": True,
        })
        diagnostics.append(summary)

    all_summary = _return_summary([
        row for rec_date in sorted(by_date) for row in by_date[rec_date]
    ])
    all_summary.update({
        "top_k": "all",
        "active_dates": len(by_date),
        "diagnostic_only": True,
    })
    diagnostics.append(all_summary)
    return diagnostics


def _recommendation_score(row):
    value = row.get("recommendation_score")
    if isinstance(value, bool):
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _market_regime_slices(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row.get("market_regime") or "unknown")].append(row)
    return {
        regime: _return_summary(grouped[regime])
        for regime in sorted(grouped)
    }


def build_strategy_scorecards(
    entries,
    kline_by_code,
    *,
    trading_calendar=None,
    benchmark_kline=None,
    expected_adjustment=EXPECTED_ADJUSTMENT,
):
    """Aggregate mature recommend episodes separately from gate outcomes."""
    entries = [entry for entry in entries or [] if isinstance(entry, dict)]
    cards = {}
    recommend_rows = defaultdict(list)
    for entry in entries:
        for contribution in entry.get("strategy_contributions") or []:
            if not isinstance(contribution, dict):
                continue
            strategy = str(contribution.get("strategy_name") or "unknown")
            version = str(contribution.get("strategy_version") or "unknown")
            source_pool = str(
                contribution.get("source_pool") or strategy
            )
            entry_mode = str(
                contribution.get("entry_mode") or "unknown"
            )
            intended_horizon = _intended_horizon(contribution)
            key = (
                strategy, version, source_pool, entry_mode, intended_horizon
            )
            card = cards.setdefault(key, {
                "strategy": strategy,
                "version": version,
                "source_pool": source_pool,
                "entry_mode": entry_mode,
                "intended_horizon": intended_horizon,
                "display_names": Counter(),
                "attribution_statuses": Counter(),
                "gate_outcomes": Counter(),
                "publication_outcomes": Counter(),
            })
            card["display_names"][
                str(contribution.get("display_name") or strategy)
            ] += 1
            card["attribution_statuses"][
                str(
                    contribution.get("attribution_status")
                    or "legacy_unknown"
                )
            ] += 1
            decision = str(contribution.get("decision_code") or "unknown")
            card["gate_outcomes"][decision] += 1
            user_action = str(
                contribution.get("user_action") or "unknown"
            )
            card["publication_outcomes"][user_action] += 1
            if contribution.get("cohort_eligible") is True:
                recommend_rows[key].append({
                    "entry": entry,
                    "contribution": contribution,
                })

    result = []
    for key in sorted(
        cards,
        key=lambda row: (row[0], row[1], row[2], row[3], row[4] or 0),
    ):
        card = cards[key]
        primary_horizon = card["intended_horizon"]
        primary_key = (
            "t{}".format(primary_horizon) if primary_horizon else None
        )
        episodes = _episode_rows(
            recommend_rows.get(key, []), trading_calendar
        )
        outcomes = []
        sample_rows = []
        status_counts = Counter()
        for row in episodes:
            entry = row["entry"]
            outcome = evaluate_recommendation_entry(
                entry,
                (kline_by_code or {}).get(str(entry.get("code") or "")),
                contribution=row["contribution"],
                trading_calendar=trading_calendar,
                benchmark_kline=benchmark_kline,
                expected_adjustment=expected_adjustment,
            )
            outcomes.append(outcome)
            status_counts[outcome["status"]] += 1
            primary_return = (
                outcome["returns"].get(primary_key)
                if primary_key else None
            )
            if primary_return is not None or any(
                value is not None for value in outcome["returns"].values()
            ):
                reason_snapshot = row["contribution"].get(
                    "reason_snapshot"
                )
                reason_snapshot = (
                    reason_snapshot
                    if isinstance(reason_snapshot, dict) else {}
                )
                decision_snapshot = reason_snapshot.get(
                    "decision_engine_v1"
                )
                decision_snapshot = (
                    decision_snapshot
                    if isinstance(decision_snapshot, dict) else {}
                )
                sample_rows.append({
                    "recommendation_id": entry.get("recommendation_id"),
                    "rec_date": entry.get("report_date"),
                    "code": entry.get("code"),
                    "name": entry.get("name"),
                    "strategy": card["strategy"],
                    "strategy_version": card["version"],
                    "return_pct": primary_return,
                    "returns": dict(outcome["returns"]),
                    "excess_returns": dict(outcome["excess_returns"]),
                    "outcome_label": (
                        "T+{} {:+.2f}%".format(
                            primary_horizon, primary_return
                        )
                        if primary_return is not None
                        else "主周期未声明"
                    ),
                    "reason_summary": _reason_summary(row["contribution"]),
                    "entry_date": outcome.get("entry_date"),
                    "entry_price": outcome.get("entry_price"),
                    "mae": (
                        outcome["mae"].get(primary_key)
                        if primary_key else None
                    ),
                    "mfe": (
                        outcome["mfe"].get(primary_key)
                        if primary_key else None
                    ),
                    "recommendation_score": decision_snapshot.get(
                        "total_score"
                    ),
                    "market_regime": (
                        reason_snapshot.get("market_regime")
                        or decision_snapshot.get("market_regime")
                        or "unknown"
                    ),
                    "maturity_status": (
                        outcome["maturity"].get(primary_key)
                        if primary_key else None
                    ),
                })

        values = {
            key_name: [
                outcome["returns"][key_name]
                for outcome in outcomes
                if outcome["returns"].get(key_name) is not None
            ]
            for key_name in ("t1", "t3", "t5")
        }
        returns = {
            key_name: (mean(rows) if rows else None)
            for key_name, rows in values.items()
        }
        median_returns = {
            key_name: (median(rows) if rows else None)
            for key_name, rows in values.items()
        }
        excess_values = {
            key_name: [
                outcome["excess_returns"][key_name]
                for outcome in outcomes
                if outcome["excess_returns"].get(key_name) is not None
            ]
            for key_name in ("t1", "t3", "t5")
        }
        excess_returns = {
            key_name: (mean(rows) if rows else None)
            for key_name, rows in excess_values.items()
        }
        median_excess_returns = {
            key_name: (median(rows) if rows else None)
            for key_name, rows in excess_values.items()
        }
        excursions = {
            metric: {
                key_name: (
                    mean([
                        outcome[metric][key_name]
                        for outcome in outcomes
                        if outcome[metric].get(key_name) is not None
                    ])
                    if any(
                        outcome[metric].get(key_name) is not None
                        for outcome in outcomes
                    ) else None
                )
                for key_name in ("t1", "t3", "t5")
            }
            for metric in ("mae", "mfe")
        }
        win_rates = {
            key_name: (
                sum(value > 0 for value in rows) / len(rows) * 100.0
                if rows else None
            )
            for key_name, rows in values.items()
        }
        attribution_status_counts = dict(card["attribution_statuses"])
        attribution_status = (
            next(iter(attribution_status_counts))
            if len(attribution_status_counts) == 1
            else "mixed"
        )
        display_name = sorted(
            card["display_names"],
            key=lambda value: (-card["display_names"][value], value),
        )[0]
        evaluable_episode_count = sum(
            any(value is not None for value in outcome["returns"].values())
            for outcome in outcomes
        )
        primary_samples = [
            row for row in sample_rows if row.get("return_pct") is not None
        ]
        high_return_summary = _return_summary(primary_samples)
        active_dates = len({
            str(row.get("rec_date") or "") for row in primary_samples
            if row.get("rec_date")
        })
        active_months = len({
            str(row.get("rec_date") or "")[:7] for row in primary_samples
            if row.get("rec_date")
        })
        primary_mae = [
            float(row["mae"]) for row in primary_samples
            if row.get("mae") is not None
        ]
        primary_mfe = [
            float(row["mfe"]) for row in primary_samples
            if row.get("mfe") is not None
        ]
        gate_count_by_date = Counter(
            str(row["entry"].get("report_date") or "")
            for row in recommend_rows.get(key, [])
            if row["entry"].get("report_date")
        )
        gate_counts = list(gate_count_by_date.values())
        result.append({
            "strategy": card["strategy"],
            "name": display_name,
            "version": card["version"],
            "entry_mode": card["entry_mode"],
            "attribution_status": attribution_status,
            "attribution_status_counts": attribution_status_counts,
            "intended_horizon": primary_horizon,
            "active_dates": active_dates,
            "active_months": active_months,
            "average_daily_count": (
                mean(gate_counts) if gate_counts else 0.0
            ),
            "daily_gate_count_distribution": dict(
                sorted(gate_count_by_date.items())
            ),
            "mean_close_return": high_return_summary[
                "mean_close_return"
            ],
            "median_close_return": high_return_summary[
                "median_close_return"
            ],
            "up_rate": high_return_summary["up_rate"],
            "hit_rate_ge_5": high_return_summary["hit_rate_ge_5"],
            "loss_rate_le_minus_5": high_return_summary[
                "loss_rate_le_minus_5"
            ],
            "worst_close_return": high_return_summary[
                "worst_close_return"
            ],
            "mean_mae": mean(primary_mae) if primary_mae else None,
            "mean_mfe": mean(primary_mfe) if primary_mfe else None,
            "time_stability": _time_stability(primary_samples),
            "market_regime_slices": _market_regime_slices(
                primary_samples
            ),
            "top_k_diagnostics": _top_k_diagnostics(primary_samples),
            "selection_cap_applied": False,
            "research_evidence": {
                "truth_verified": None,
                "leakage_free": card["entry_mode"] == "immediate_close",
                "maturity_verified": (
                    bool(primary_samples)
                    and all(
                        row.get("maturity_status") == "mature"
                        for row in primary_samples
                    )
                ),
                "oot_locked": False,
            },
            "episode_count": len(episodes),
            "evaluable_episode_count": evaluable_episode_count,
            "sample_size": (
                len(values[primary_key])
                if primary_key else evaluable_episode_count
            ),
            "matured_by_horizon": {
                key_name: len(rows) for key_name, rows in values.items()
            },
            "returns": returns,
            "median_returns": median_returns,
            "excess_returns": excess_returns,
            "median_excess_returns": median_excess_returns,
            "excursions": excursions,
            "win_rates": win_rates,
            "win_rate": win_rates[primary_key] if primary_key else None,
            "gate_outcomes": dict(card["gate_outcomes"]),
            "publication_outcomes": dict(card["publication_outcomes"]),
            "evaluation_statuses": dict(status_counts),
            "representative_samples": _representative_samples(
                sample_rows,
                contracted=primary_key is not None,
            ),
        })
    return result
