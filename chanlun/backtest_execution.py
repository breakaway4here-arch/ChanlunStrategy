"""Utilities for calculating forward-return metrics for backtests."""

from __future__ import annotations


def _as_list(values):
    """Convert list/tuple/numpy array-like inputs to a plain Python list."""
    return list(values) if values is not None else []


def _find_snap_index(dates, snap_date):
    try:
        return dates.index(snap_date)
    except ValueError:
        return None


def evaluate_forward_returns(kline, snap_date, entry_mode, horizon=5):
    """Evaluate forward returns for one recommendation snapshot.

    Args:
        kline: dict containing keys: dates, opens, closes, highs, lows
        snap_date: snapshot date (string)
        entry_mode: one of {"immediate_close", "delay1_open", "delay1_close"}
        horizon: number of trading days to evaluate, defaults to 5

    Returns:
        dict with keys:
          - t1_close_pct
          - t3_close_pct
          - max_up_3d
          - max_dd_3d
          - n_forward_days
          - entry_mode
          - entry_date
          - ref_date
        or None when data is insufficient.
    """
    if kline is None:
        return None
    if entry_mode not in {"immediate_close", "delay1_open", "delay1_close"}:
        return None
    if horizon is None or horizon <= 0:
        return None

    dates = _as_list((kline or {}).get("dates"))
    opens = [float(x) for x in _as_list((kline or {}).get("opens"))]
    closes = [float(x) for x in _as_list((kline or {}).get("closes"))]
    highs = [float(x) for x in _as_list((kline or {}).get("highs"))]
    lows = [float(x) for x in _as_list((kline or {}).get("lows"))]

    if not dates or not opens or not closes or not highs or not lows:
        return None
    if not (len(dates) == len(opens) == len(closes) == len(highs) == len(lows)):
        return None

    # Dates in source snapshots are sometimes full datetime strings.
    dates = [str(d).split(" ")[0] for d in dates]
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
        "entry_mode": entry_mode,
        "entry_date": entry_date,
        "ref_date": ref_date,
    }
