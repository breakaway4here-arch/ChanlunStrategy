"""Candidate ChanLun engine components for offline dual-compare validation."""

import numpy as np

from config import MACD_FAST, MACD_SIGNAL, MACD_SLOW

from .engine_pipeline import analyze_with_macd_provider


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
