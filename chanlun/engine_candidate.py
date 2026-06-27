"""Candidate ChanLun engine components for offline dual-compare validation."""

import numpy as np

from config import BI_MIN_KLINE_COUNT, MACD_FAST, MACD_SIGNAL, MACD_SLOW

from .engine_core import calc_macd, inclusion_process
from .engine_pipeline import (
    analyze_with_inclusion_provider,
    analyze_with_macd_provider,
    analyze_with_providers,
)
from .engine_types import Fractal


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


def find_fractals_candidate(highs, lows, idx_map, dates=None):
    """Candidate fractal implementation, currently locked to legacy parity."""
    n = len(highs)
    if n < 5:
        return []

    def _orig_idx(merged_i):
        indices = idx_map[merged_i] if isinstance(idx_map[merged_i], list) else [idx_map[merged_i]]
        return indices[len(indices) // 2]

    fractals = []
    for i in range(1, n - 1):
        # top fractal
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1] \
           and lows[i] > lows[i - 1] and lows[i] > lows[i + 1]:
            orig_indices = idx_map[i] if isinstance(idx_map[i], list) else [idx_map[i]]
            fractals.append(Fractal(
                type="top",
                index=_orig_idx(i),
                price=highs[i],
                klines=orig_indices,
            ))

        # bottom fractal
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1] \
           and highs[i] < highs[i - 1] and highs[i] < highs[i + 1]:
            orig_indices = idx_map[i] if isinstance(idx_map[i], list) else [idx_map[i]]
            fractals.append(Fractal(
                type="bottom",
                index=_orig_idx(i),
                price=lows[i],
                klines=orig_indices,
            ))

    # dedupe and distance filter
    min_dist = max(2, BI_MIN_KLINE_COUNT // 2)
    filtered = []
    i = 0
    while i < len(fractals):
        if not filtered:
            filtered.append(fractals[i])
            i += 1
            continue

        last = filtered[-1]
        curr = fractals[i]

        if last.type == curr.type:
            if curr.type == "top" and curr.price > last.price:
                filtered[-1] = curr
            elif curr.type == "bottom" and curr.price < last.price:
                filtered[-1] = curr
        else:
            if abs(curr.index - last.index) >= min_dist:
                filtered.append(curr)
        i += 1

    if filtered and filtered[0].type == "bottom":
        filtered.pop(0)
    if filtered and filtered[-1].type == "top":
        filtered.pop()

    return filtered


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
    return analyze_with_inclusion_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        inclusion_process_candidate,
    )


def analyze_with_candidate_fractal(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with fractals supplied by the candidate component."""
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
        inclusion_provider=inclusion_process,
        fractal_provider=find_fractals_candidate,
    )
