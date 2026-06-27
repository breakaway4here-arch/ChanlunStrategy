"""Shared ChanLun analysis pipeline used by legacy and candidate analyzers."""

from config import USE_SEGMENT_BREAK_BUILDER

from .engine_core import (
    calc_macd,
    build_segments_by_break,
    build_segments_fixed_window,
    build_strokes,
    check_divergence,
    classify_trend,
    find_fractals,
    find_pivots,
    inclusion_process,
)
from .engine_signals import locate_buy_sell_points
from .engine_swing import (
    build_stroke_pivots,
    build_strokes_swing,
    prune_strokes,
)
from .engine_types import ChanResult


def analyze_with_macd_provider(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    macd_provider,
):
    """Backward-compatible entry using legacy inclusion behavior."""
    return analyze_with_providers(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        macd_provider=macd_provider,
        inclusion_provider=inclusion_process,
        fractal_provider=find_fractals,
    )


def analyze_with_inclusion_provider(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    inclusion_provider,
):
    """Backward-compatible entry using legacy MACD behavior."""
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
        inclusion_provider=inclusion_provider,
        fractal_provider=find_fractals,
    )


def analyze_with_providers(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    *,
    macd_provider,
    inclusion_provider,
    fractal_provider,
):
    n = len(closes)
    if n < 10:
        return None

    dif, dea, hist = macd_provider(closes)

    merged_high, merged_low, idx_map = inclusion_provider(highs, lows)
    fractals = fractal_provider(merged_high, merged_low, idx_map, dates)
    strokes = build_strokes(fractals, merged_high, merged_low)
    segments = build_segments_by_break(strokes) if USE_SEGMENT_BREAK_BUILDER else build_segments_fixed_window(strokes)
    confirmed_segments = [s for s in segments if s.confirmed]
    pivots = find_pivots(confirmed_segments)
    trend_type = classify_trend(pivots, confirmed_segments)
    divergence = check_divergence(closes, confirmed_segments, dif, dea, hist, pivots=pivots)

    swing_waves_raw = build_strokes_swing(highs, lows, closes, min_bars=2, min_swing_pct=0.06)
    swing_waves = prune_strokes(swing_waves_raw, min_pct=0.06)
    swing_zones = build_stroke_pivots(swing_waves)

    result = ChanResult(
        code=code,
        name=name,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        volumes=volumes,
        dates=list(dates),
        fractals=fractals,
        strokes=strokes,
        segments=segments,
        pivots=pivots,
        swing_waves=swing_waves,
        swing_zones=swing_zones,
        divergence=divergence,
        trend_type=trend_type,
        macd_dif=dif,
        macd_dea=dea,
        macd_hist=hist,
    )

    buy_points, sell_points = locate_buy_sell_points(result)
    result.buy_points = buy_points
    result.sell_points = sell_points
    return result
