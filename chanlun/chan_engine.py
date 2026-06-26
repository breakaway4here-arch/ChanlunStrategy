"""ChanLun engine public entrypoint.

This module keeps legacy imports and behavior stable while implementation is
split into dedicated modules.
"""

from config import THIRD_BUY_MAX_CHASE_PCT, USE_SEGMENT_BREAK_BUILDER

from .engine_core import (
    build_segments_by_break,
    build_segments_fixed_window,
    build_strokes,
    calc_macd,
    check_divergence,
    classify_trend,
    ema,
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

def analyze(code, name, dates, opens, highs, lows, closes, volumes):
    """对一只股票进行完整的缠论分析。"""
    n = len(closes)
    if n < 10:
        return None

    # MACD
    dif, dea, hist = calc_macd(closes)

    # 包含处理
    merged_high, merged_low, idx_map = inclusion_process(highs, lows)

    # 分型
    fractals = find_fractals(merged_high, merged_low, idx_map, dates)

    # 笔
    strokes = build_strokes(fractals, merged_high, merged_low)

    # 线段
    segments = build_segments_by_break(strokes) if USE_SEGMENT_BREAK_BUILDER else build_segments_fixed_window(strokes)

    # 中枢（段中枢）—— 仅使用已确认线段
    confirmed_segments = [s for s in segments if s.confirmed]
    pivots = find_pivots(confirmed_segments)

    # 走势类型
    trend_type = classify_trend(pivots, confirmed_segments)

    # 背驰
    divergence = check_divergence(closes, confirmed_segments, dif, dea, hist, pivots=pivots)

    # ── Swing Tracking 笔中枢（辅助展示/评分，不参与正式买卖点）──
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

    # 买卖点
    buy_points, sell_points = locate_buy_sell_points(result)
    result.buy_points = buy_points
    result.sell_points = sell_points

    return result
