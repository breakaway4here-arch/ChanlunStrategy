"""Utilities for calculating forward-return metrics for backtests."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Integral, Real

from .signal_quality_classifier import classify_signal

SUPPORTED_EXIT_MODELS = {
    "exit_t3",
    "exit_stop_loss_5pct",
    "exit_take_profit_8pct_or_t3",
    "exit_stop5_take8_conservative",
}

# A caller may omit per-row finality only when it carries this explicit
# contract.  Fetchers with row-level status should always provide the flags
# instead; an unmarked kline is not evidence of a closed bar sequence.
ALL_BARS_CLOSED_CONTRACT = "all_bars_closed_v1"


def _as_list(values):
    """Convert list/tuple/numpy array-like inputs to a plain Python list."""
    if values is None:
        return []
    tolist = getattr(values, "tolist", None)
    if callable(tolist):
        converted = tolist()
        return converted if isinstance(converted, list) else [converted]
    return list(values)


def _positive_finite_series(values):
    try:
        raw_values = _as_list(values)
    except (TypeError, ValueError):
        return None
    normalized = []
    for value in raw_values:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        normalized.append(number)
    return normalized


def _finality_flags(values, size):
    try:
        raw_values = _as_list(values)
    except (TypeError, ValueError):
        return None
    if len(raw_values) != size:
        return None
    flags = []
    for value in raw_values:
        if isinstance(value, bool):
            flags.append(value)
        elif isinstance(value, Integral) and int(value) in (0, 1):
            flags.append(bool(int(value)))
        elif (
            isinstance(value, Real)
            and math.isfinite(float(value))
            and float(value) in (0.0, 1.0)
        ):
            flags.append(bool(float(value)))
        else:
            return None
    return flags


def _has_explicit_all_bars_closed_contract(kline):
    if not isinstance(kline, Mapping):
        return False
    if kline.get("finality_contract") == ALL_BARS_CLOSED_CONTRACT:
        return True
    status = kline.get("_data_status")
    return (
        isinstance(status, Mapping)
        and status.get("finality_contract") == ALL_BARS_CLOSED_CONTRACT
    )


def normalize_backtest_kline(kline):
    """Normalize and validate one backtest kline, including row finality.

    Historical callers often rebuild a kline from parallel arrays.  This
    helper is the single contract for those rebuilds: it rejects unknown
    finality, malformed numeric values, and impossible OHLC geometry.  The
    explicit all-bars-closed marker is reserved for a producer that has
    independently established that every row is closed.
    """
    if not isinstance(kline, Mapping):
        return None

    try:
        dates = [
            str(value).split(" ")[0]
            for value in _as_list(kline.get("dates"))
        ]
        opens = _positive_finite_series(kline.get("opens"))
        highs = _positive_finite_series(kline.get("highs"))
        lows = _positive_finite_series(kline.get("lows"))
        closes = _positive_finite_series(kline.get("closes"))
    except (TypeError, ValueError):
        return None

    if any(series is None for series in (opens, highs, lows, closes)):
        return None
    if not dates or not (
        len(dates)
        == len(opens)
        == len(highs)
        == len(lows)
        == len(closes)
    ):
        return None

    for open_price, high, low, close in zip(opens, highs, lows, closes):
        if (
            high < max(open_price, close)
            or low > min(open_price, close)
            or high < low
        ):
            return None

    raw_is_final = kline.get("is_final")
    raw_finals = kline.get("finals")
    if raw_is_final is not None and raw_finals is not None:
        is_final = _finality_flags(raw_is_final, len(dates))
        finals = _finality_flags(raw_finals, len(dates))
        if is_final is None or finals is None or is_final != finals:
            return None
    else:
        raw_finality = raw_is_final if raw_is_final is not None else raw_finals
        if raw_finality is None:
            if not _has_explicit_all_bars_closed_contract(kline):
                return None
            is_final = [True] * len(dates)
        else:
            is_final = _finality_flags(raw_finality, len(dates))
            if is_final is None:
                return None

    return {
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "is_final": is_final,
    }


def execute_signal(signal):
    """Resolve side-effect-free execution intent from signal quality category.

    Returns a plain intent dict and never triggers external actions.
    """
    if signal is None:
        category = "C"
    else:
        category = signal.get("category")
        if category is None:
            category = classify_signal(signal)
    if category == "A":
        return {"action": "place_order", "category": "A", "execute": True}
    if category == "B":
        return {"action": "log_only", "category": "B", "execute": False}
    return {"action": "ignore", "category": "C", "execute": False}


def _find_snap_index(dates, snap_date):
    try:
        return dates.index(snap_date)
    except ValueError:
        return None


def _prepare_entry_context(kline, snap_date, entry_mode, horizon=5):
    if kline is None:
        return None
    if entry_mode not in {"immediate_close", "delay1_open", "delay1_close"}:
        return None
    if horizon is None or horizon <= 0:
        return None

    normalized = normalize_backtest_kline(kline)
    if normalized is None:
        return None

    dates = normalized["dates"]
    opens = normalized["opens"]
    closes = normalized["closes"]
    highs = normalized["highs"]
    lows = normalized["lows"]
    if dates != sorted(set(dates)):
        return None
    is_final = normalized["is_final"]

    snap_idx = _find_snap_index(dates, str(snap_date))
    if snap_idx is None:
        return None

    if entry_mode == "immediate_close":
        entry_idx = snap_idx
        entry_ref_idx = snap_idx
        forward_start = snap_idx + 1
        ref_date = dates[snap_idx]
        entry_date = dates[snap_idx]
    elif entry_mode == "delay1_open":
        entry_ref_idx = snap_idx + 1
        if entry_ref_idx >= len(dates):
            return None
        entry_idx = entry_ref_idx
        forward_start = entry_ref_idx
        ref_date = dates[entry_ref_idx]
        entry_date = dates[entry_ref_idx]
    else:
        # delay1_close
        entry_ref_idx = snap_idx + 1
        forward_start = snap_idx + 2
        if forward_start >= len(dates):
            return None
        entry_idx = entry_ref_idx
        ref_date = dates[entry_ref_idx]
        entry_date = dates[entry_ref_idx]

    if entry_idx >= len(closes):
        return None
    if not is_final[entry_ref_idx]:
        return None

    end_idx = min(forward_start + horizon, len(dates))
    forward_closes = closes[forward_start:end_idx]
    forward_highs = highs[forward_start:end_idx]
    forward_lows = lows[forward_start:end_idx]
    if not forward_closes:
        return None

    if entry_mode == "immediate_close":
        ref = closes[entry_idx]
    elif entry_mode == "delay1_open":
        ref = opens[entry_ref_idx]
    else:
        ref = closes[entry_ref_idx]

    if ref <= 0:
        return None

    return {
        "entry_mode": entry_mode,
        "entry_date": entry_date,
        "ref_date": ref_date,
        "entry_idx": entry_idx,
        "entry_ref_idx": entry_ref_idx,
        "ref": ref,
        "forward_closes": forward_closes,
        "forward_highs": forward_highs,
        "forward_lows": forward_lows,
        "forward_is_final": is_final[forward_start:end_idx],
    }


def evaluate_forward_returns(kline, snap_date, entry_mode, horizon=5):
    """Evaluate forward returns for one recommendation snapshot."""
    context = _prepare_entry_context(kline, snap_date, entry_mode, horizon=horizon)
    if context is None:
        return None

    ref = context["ref"]
    forward_closes = context["forward_closes"]
    forward_highs = context["forward_highs"]
    forward_lows = context["forward_lows"]
    forward_is_final = context["forward_is_final"]

    def _pct(v):
        return (v - ref) / ref * 100.0

    forward_days = len(forward_closes)
    t1_mature = forward_days >= 1 and all(forward_is_final[:1])
    t3_mature = forward_days >= 3 and all(forward_is_final[:3])
    t5_mature = forward_days >= 5 and all(forward_is_final[:5])
    t1_close_pct = _pct(forward_closes[0]) if t1_mature else None
    t3_close_pct = _pct(forward_closes[2]) if t3_mature else None
    t5_close_pct = _pct(forward_closes[4]) if t5_mature else None
    max_up_3d = max(_pct(x) for x in forward_highs[:3]) if t3_mature else None
    max_dd_3d = min(_pct(x) for x in forward_lows[:3]) if t3_mature else None
    completed_forward_count = 0
    for final in forward_is_final:
        if final is not True:
            break
        completed_forward_count += 1
    completed_forward_lows = forward_lows[:completed_forward_count]
    auxiliary_complete = completed_forward_count == forward_days
    auxiliary_status = (
        "complete"
        if auxiliary_complete
        else ("partial" if completed_forward_lows else "unavailable")
    )
    max_drawdown = (
        min(_pct(x) for x in completed_forward_lows)
        if completed_forward_lows
        else None
    )
    stop_level = ref * 0.95
    hit_stop = (
        any(low <= stop_level for low in completed_forward_lows)
        if completed_forward_lows
        else None
    )

    return {
        "t1_close_pct": t1_close_pct,
        "t3_close_pct": t3_close_pct,
        "t5_close_pct": t5_close_pct,
        "max_up_3d": max_up_3d,
        "max_dd_3d": max_dd_3d,
        "max_drawdown": max_drawdown,
        "t1_return": t1_close_pct,
        "t3_return": t3_close_pct,
        "t5_return": t5_close_pct,
        "hit_stop": hit_stop,
        "auxiliary_metrics": {
            "status": auxiliary_status,
            "completed_forward_days": completed_forward_count,
        },
        "n_forward_days": len(forward_closes),
        "maturity": {"t1": t1_mature, "t3": t3_mature, "t5": t5_mature},
        "entry_mode": context["entry_mode"],
        "entry_date": context["entry_date"],
        "ref_date": context["ref_date"],
    }


def evaluate_exit_returns(kline, snap_date, entry_mode, exit_model, horizon=5):
    """Evaluate forward returns with an explicit exit model.

    Args:
        kline: dict containing keys: dates, opens, closes, highs, lows
        snap_date: snapshot date (string)
        entry_mode: one of {"immediate_close", "delay1_open", "delay1_close"}
        exit_model: one of SUPPORTED_EXIT_MODELS
        horizon: number of trading days to evaluate, defaults to 5
    """
    if exit_model not in SUPPORTED_EXIT_MODELS:
        return None

    base_sample = evaluate_forward_returns(
        kline,
        snap_date,
        entry_mode,
        horizon=horizon,
    )
    if base_sample is None:
        return None

    context = _prepare_entry_context(kline, snap_date, entry_mode, horizon=horizon)
    if context is None:
        return None

    ref = context["ref"]
    forward_closes = context["forward_closes"]
    forward_highs = context["forward_highs"]
    forward_lows = context["forward_lows"]
    forward_is_final = context["forward_is_final"]
    horizon3 = min(3, len(forward_closes))
    if horizon3 <= 0:
        return None

    t3_mature = bool((base_sample.get("maturity") or {}).get("t3"))
    t3_day_idx = 3 if t3_mature else None
    t3_close_pct = base_sample["t3_close_pct"] if t3_mature else None
    exit_return_pct = t3_close_pct
    exit_reason = "t3_close"
    exit_day_index = t3_day_idx
    stop_level = ref * 0.95
    take_level = ref * 1.08

    if exit_model == "exit_t3":
        if not t3_mature:
            exit_reason = "t3_not_matured"
    elif exit_model == "exit_stop_loss_5pct":
        for idx in range(horizon3):
            if not forward_is_final[idx]:
                continue
            if forward_lows[idx] <= stop_level:
                exit_return_pct = -5.0
                exit_reason = "stop_loss_5pct"
                exit_day_index = idx + 1
                break
    elif exit_model == "exit_take_profit_8pct_or_t3":
        for idx in range(horizon3):
            if not forward_is_final[idx]:
                continue
            if forward_highs[idx] >= take_level:
                exit_return_pct = 8.0
                exit_reason = "take_profit_8pct"
                exit_day_index = idx + 1
                break
    elif exit_model == "exit_stop5_take8_conservative":
        for idx in range(horizon3):
            if not forward_is_final[idx]:
                continue
            if forward_lows[idx] <= stop_level:
                exit_return_pct = -5.0
                exit_reason = "stop_loss_5pct"
                exit_day_index = idx + 1
                break
            if forward_highs[idx] >= take_level:
                exit_return_pct = 8.0
                exit_reason = "take_profit_8pct"
                exit_day_index = idx + 1
                break

    sample = dict(base_sample)
    sample.update(
        {
            "t3_close_pct": exit_return_pct if t3_mature else None,
            "t3_return": exit_return_pct if t3_mature else None,
            "exit_model": exit_model,
            "exit_reason": exit_reason,
            "exit_return_pct": exit_return_pct,
            "exit_day_index": exit_day_index,
        }
    )
    return sample
