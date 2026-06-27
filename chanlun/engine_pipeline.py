"""Shared ChanLun analysis pipeline used by legacy and candidate analyzers."""

from dataclasses import dataclass, replace

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


def build_segments_with_config(strokes):
    return build_segments_by_break(strokes) if USE_SEGMENT_BREAK_BUILDER else build_segments_fixed_window(strokes)


@dataclass(frozen=True)
class EngineProviders:
    macd_provider: object
    inclusion_provider: object
    fractal_provider: object
    stroke_provider: object
    segment_provider: object
    pivot_provider: object
    trend_provider: object
    divergence_provider: object
    signal_provider: object


LEGACY_PROVIDERS = EngineProviders(
    macd_provider=calc_macd,
    inclusion_provider=inclusion_process,
    fractal_provider=find_fractals,
    stroke_provider=build_strokes,
    segment_provider=build_segments_with_config,
    pivot_provider=find_pivots,
    trend_provider=classify_trend,
    divergence_provider=check_divergence,
    signal_provider=locate_buy_sell_points,
)


def with_provider_overrides(providers, **overrides):
    """Return a provider bundle with selected provider fields replaced."""
    return replace(providers, **overrides)


def analyze_with_provider_bundle(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    *,
    providers: EngineProviders,
):
    """Run analysis using a named provider bundle."""
    return analyze_with_providers(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        macd_provider=providers.macd_provider,
        inclusion_provider=providers.inclusion_provider,
        fractal_provider=providers.fractal_provider,
        stroke_provider=providers.stroke_provider,
        segment_provider=providers.segment_provider,
        pivot_provider=providers.pivot_provider,
        trend_provider=providers.trend_provider,
        divergence_provider=providers.divergence_provider,
        signal_provider=providers.signal_provider,
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
    stroke_provider,
    segment_provider,
    pivot_provider,
    trend_provider,
    divergence_provider,
    signal_provider,
):
    n = len(closes)
    if n < 10:
        return None

    dif, dea, hist = macd_provider(closes)

    merged_high, merged_low, idx_map = inclusion_provider(highs, lows)
    fractals = fractal_provider(merged_high, merged_low, idx_map, dates)
    strokes = stroke_provider(fractals, merged_high, merged_low)
    segments = segment_provider(strokes)
    confirmed_segments = [s for s in segments if s.confirmed]
    pivots = pivot_provider(confirmed_segments)
    trend_type = trend_provider(pivots, confirmed_segments)
    divergence = divergence_provider(closes, confirmed_segments, dif, dea, hist, pivots=pivots)

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

    buy_points, sell_points = signal_provider(result)
    result.buy_points = buy_points
    result.sell_points = sell_points
    return result
