"""Candidate ChanLun engine components for offline dual-compare validation."""

import numpy as np

from config import MACD_FAST, MACD_SIGNAL, MACD_SLOW

from .engine_core import calc_macd
from .engine_pipeline import analyze_with_macd_provider, analyze_with_providers


def _ema_candidate(data, period):
    n = len(data)
    if n < period:
        return np.full_like(data, np.nan, dtype=float)

    alpha = 2.0 / (period + 1)
    result = np.full_like(data, np.nan, dtype=float)

    start = 0
    while start < n and np.isnan(data[start]):
        start += 1
    if start >= n:
        return result

    valid_data = data[start:]
    if len(valid_data) < period:
        return result

    result[start + period - 1] = np.mean(valid_data[:period])
    for i in range(start + period, n):
        if np.isnan(data[i]):
            result[i] = result[i - 1]
        else:
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def calc_macd_candidate(closes):
    """Candidate MACD implementation, currently locked to legacy parity."""
    ema_fast = _ema_candidate(closes, MACD_FAST)
    ema_slow = _ema_candidate(closes, MACD_SLOW)
    dif = ema_fast - ema_slow
    dea = _ema_candidate(dif, MACD_SIGNAL)
    hist = 2.0 * (dif - dea)
    return dif, dea, hist


def inclusion_process_candidate(highs, lows):
    """Candidate inclusion implementation, currently locked to legacy parity."""
    n = len(highs)
    if n < 3:
        return np.asarray(highs).copy(), np.asarray(lows).copy(), list(range(n))

    merged_high = []
    merged_low = []
    idx_map = []

    direction = 0
    i = 0
    while i < n:
        if not merged_high:
            merged_high.append(highs[i])
            merged_low.append(lows[i])
            idx_map.append([i])
            i += 1
            continue

        prev_h = merged_high[-1]
        prev_l = merged_low[-1]
        curr_h = highs[i]
        curr_l = lows[i]

        is_included = (curr_h <= prev_h and curr_l >= prev_l) or (
            curr_h >= prev_h and curr_l <= prev_l
        )

        if not is_included:
            if curr_h > prev_h:
                direction = 1
            elif curr_h < prev_h:
                direction = -1
            merged_high.append(curr_h)
            merged_low.append(curr_l)
            idx_map.append([i])
            i += 1
            continue

        if direction == -1:
            merged_high[-1] = min(prev_h, curr_h)
            merged_low[-1] = min(prev_l, curr_l)
            idx_map[-1].append(i)
        elif direction == 1:
            merged_high[-1] = max(prev_h, curr_h)
            merged_low[-1] = max(prev_l, curr_l)
            idx_map[-1].append(i)
        else:
            merged_high.append(curr_h)
            merged_low.append(curr_l)
            idx_map.append([i])

        i += 1

    return np.array(merged_high), np.array(merged_low), idx_map


def analyze_with_candidate_macd(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with MACD supplied by the candidate component."""
    return analyze_with_macd_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        calc_macd_candidate,
    )


def analyze_with_candidate_inclusion(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with inclusion supplied by the candidate component."""
    return analyze_with_providers(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        macd_provider=calc_macd,
        inclusion_provider=inclusion_process_candidate,
    )
