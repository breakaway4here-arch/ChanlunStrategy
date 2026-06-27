"""ChanLun engine public entrypoint.

This module keeps legacy imports and behavior stable while implementation is
split into dedicated modules.
"""

from config import (
    BI_MIN_KLINE_COUNT,
    DIVERGENCE_PLATEAU,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    PIVOT_MIN_SEGMENTS,
    SEGMENT_MIN_STROKES,
    THIRD_BUY_MAX_CHASE_PCT,
    USE_SEGMENT_BREAK_BUILDER,
)

from .engine_core import (
    ema,
    build_segments_by_break,
    build_segments_fixed_window,
    build_strokes,
    calc_macd,
    check_divergence,
    classify_trend,
    find_fractals,
    find_pivots,
    inclusion_process,
    stroke_high,
    stroke_low,
)
from .engine_signals import (
    _detect_swing_divergence_ref,
    _find_pivot_buy_points,
    _find_second_buy_point,
    _find_third_buy_point,
    _segment_extreme_index,
    locate_buy_sell_points,
)
from .engine_swing import (
    build_stroke_pivots,
    build_strokes_swing,
    prune_strokes,
)
from .engine_types import ChanResult, Fractal, Pivot, Segment, Stroke
from .engine_compare import compare_chan_results, serialize_chan_result
from .engine_pipeline import LEGACY_PROVIDERS, analyze_with_provider_bundle


__all__ = [
    "BI_MIN_KLINE_COUNT",
    "SEGMENT_MIN_STROKES",
    "PIVOT_MIN_SEGMENTS",
    "MACD_FAST",
    "MACD_SLOW",
    "MACD_SIGNAL",
    "DIVERGENCE_PLATEAU",
    "THIRD_BUY_MAX_CHASE_PCT",
    "USE_SEGMENT_BREAK_BUILDER",
    "Fractal",
    "Stroke",
    "Segment",
    "Pivot",
    "ChanResult",
    "analyze",
    "ema",
    "calc_macd",
    "inclusion_process",
    "find_fractals",
    "build_strokes",
    "stroke_high",
    "stroke_low",
    "build_segments_by_break",
    "build_segments_fixed_window",
    "find_pivots",
    "classify_trend",
    "check_divergence",
    "locate_buy_sell_points",
    "build_strokes_swing",
    "prune_strokes",
    "build_stroke_pivots",
    "compare_chan_results",
    "serialize_chan_result",
    "analyze_dual",
]

def analyze(code, name, dates, opens, highs, lows, closes, volumes):
    """对一只股票进行完整的缠论分析。"""
    return analyze_with_provider_bundle(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        providers=LEGACY_PROVIDERS,
    )


def analyze_dual(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    *,
    candidate_analyzer=None,
):
    """Run legacy analyze() and an opt-in candidate analyzer, then compare outputs."""
    kwargs = {
        "code": code,
        "name": name,
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
    }
    legacy = analyze(**kwargs)
    analyzer = candidate_analyzer or analyze
    candidate = analyzer(**kwargs)
    return {
        "legacy": legacy,
        "candidate": candidate,
        "comparison": compare_chan_results(legacy, candidate),
    }
