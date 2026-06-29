"""Utilities for calculating forward-return metrics for backtests."""

from __future__ import annotations

from .signal_quality_classifier import classify_signal

SUPPORTED_EXIT_MODELS = {
    "exit_t3",
    "exit_stop_loss_5pct",
    "exit_take_profit_8pct_or_t3",
    "exit_stop5_take8_conservative",
}


def _as_list(values):
    """Convert list/tuple/numpy array-like inputs to a plain Python list."""
    return list(values) if values is not None else []


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

    dates = [str(d).split(" ")[0] for d in _as_list((kline or {}).get("dates"))]
    opens = [float(x) for x in _as_list((kline or {}).get("opens"))]
    closes = [float(x) for x in _as_list((kline or {}).get("closes"))]
    highs = [float(x) for x in _as_list((kline or {}).get("highs"))]
    lows = [float(x) for x in _as_list((kline or {}).get("lows"))]

    if not dates or not opens or not closes or not highs or not lows:
        return None
    if not (len(dates) == len(opens) == len(closes) == len(highs) == len(lows)):
        return None

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

    def _pct(v):
        return (v - ref) / ref * 100.0

    horizon3 = min(3, len(forward_closes))
    t1_close_pct = _pct(forward_closes[0]) if len(forward_closes) >= 1 else None
    t3_close_idx = horizon3 - 1
    t3_close_pct = _pct(forward_closes[t3_close_idx]) if horizon3 >= 1 else None
    max_up_3d = max(_pct(x) for x in forward_highs[:horizon3]) if horizon3 else None
    max_dd_3d = min(_pct(x) for x in forward_lows[:horizon3]) if horizon3 else None

    return {
        "t1_close_pct": t1_close_pct,
        "t3_close_pct": t3_close_pct,
        "max_up_3d": max_up_3d,
        "max_dd_3d": max_dd_3d,
        "n_forward_days": len(forward_closes),
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
    horizon3 = min(3, len(forward_closes))
    if horizon3 <= 0:
        return None

    t3_day_idx = horizon3
    t3_close_pct = base_sample["t3_close_pct"] if base_sample.get("t3_close_pct") is not None else None
    exit_return_pct = t3_close_pct
    exit_reason = "t3_close"
    exit_day_index = t3_day_idx
    stop_level = ref * 0.95
    take_level = ref * 1.08

    if exit_model == "exit_t3":
        exit_return_pct = t3_close_pct
    elif exit_model == "exit_stop_loss_5pct":
        for idx in range(horizon3):
            if forward_lows[idx] <= stop_level:
                exit_return_pct = -5.0
                exit_reason = "stop_loss_5pct"
                exit_day_index = idx + 1
                break
    elif exit_model == "exit_take_profit_8pct_or_t3":
        for idx in range(horizon3):
            if forward_highs[idx] >= take_level:
                exit_return_pct = 8.0
                exit_reason = "take_profit_8pct"
                exit_day_index = idx + 1
                break
    elif exit_model == "exit_stop5_take8_conservative":
        for idx in range(horizon3):
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
            "t3_close_pct": exit_return_pct,
            "exit_model": exit_model,
            "exit_reason": exit_reason,
            "exit_return_pct": exit_return_pct,
            "exit_day_index": exit_day_index,
        }
    )
    return sample
