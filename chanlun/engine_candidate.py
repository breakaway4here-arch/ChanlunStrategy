"""Candidate ChanLun engine components for offline dual-compare validation."""

import numpy as np

from config import (
    BI_MIN_KLINE_COUNT,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    SEGMENT_MIN_STROKES,
    PIVOT_MIN_SEGMENTS,
    USE_SEGMENT_BREAK_BUILDER,
)

from .engine_core import (
    build_strokes,
    calc_macd,
    find_fractals,
    inclusion_process,
)
from .engine_pipeline import (
    analyze_with_inclusion_provider,
    analyze_with_macd_provider,
    analyze_with_segment_provider,
    analyze_with_fractal_provider,
    analyze_with_stroke_provider,
    build_segments_with_config,
)
from .engine_types import Fractal, Pivot, Segment, Stroke


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


def _stroke_high_candidate(stroke):
    return max(stroke.start_price, stroke.end_price)


def _stroke_low_candidate(stroke):
    return min(stroke.start_price, stroke.end_price)


def _is_alternating_candidate(strokes):
    return all(strokes[i].direction != strokes[i + 1].direction for i in range(len(strokes) - 1))


def _make_segment_candidate(strokes, confirmed=True, destroyed_by_idx=None):
    return Segment(
        strokes=strokes[:],
        start_idx=strokes[0].start_idx,
        end_idx=strokes[-1].end_idx,
        direction=strokes[0].direction,
        high=max(_stroke_high_candidate(s) for s in strokes),
        low=min(_stroke_low_candidate(s) for s in strokes),
        confirmed=confirmed,
        destroyed_by_idx=destroyed_by_idx,
    )


def _segment_destroyed_candidate(candidate, direction):
    if len(candidate) < 4:
        return False

    last = candidate[-1]

    if direction == "up" and last.direction == "down":
        prior_down_lows = [_stroke_low_candidate(s) for s in candidate[:-1] if s.direction == "down"]
        return bool(prior_down_lows) and _stroke_low_candidate(last) < min(prior_down_lows)

    if direction == "down" and last.direction == "up":
        prior_up_highs = [_stroke_high_candidate(s) for s in candidate[:-1] if s.direction == "up"]
        return bool(prior_up_highs) and _stroke_high_candidate(last) > max(prior_up_highs)

    return False


def build_segments_by_break_candidate(strokes):
    """Candidate break-confirmed segment implementation, currently locked to legacy parity."""
    if len(strokes) < 3:
        return []

    segments = []
    i = 0
    n = len(strokes)

    while i <= n - 3:
        while i <= n - 3 and not _is_alternating_candidate(strokes[i:i + 3]):
            i += 1
        if i > n - 3:
            break

        current = strokes[i:i + 3]
        j = i + 3
        closed = False

        while j < n:
            current.append(strokes[j])
            if not _is_alternating_candidate(current[-3:]):
                j += 1
                continue

            if _segment_destroyed_candidate(current, current[0].direction):
                old = current[:-1]
                segments.append(_make_segment_candidate(old, confirmed=True, destroyed_by_idx=strokes[j].end_idx))
                i = max(j - 2, i + 1)
                closed = True
                break

            j += 1

        if not closed:
            segments.append(_make_segment_candidate(current, confirmed=False))
            break

    return segments


def build_segments_fixed_window_candidate(strokes):
    """Candidate fixed-window segment fallback, currently locked to legacy parity."""
    if len(strokes) < SEGMENT_MIN_STROKES:
        return []

    segments = []
    step = SEGMENT_MIN_STROKES - 1
    i = 0
    while i <= len(strokes) - SEGMENT_MIN_STROKES:
        seg_strokes = strokes[i:i + SEGMENT_MIN_STROKES]

        if any(seg_strokes[k].direction == seg_strokes[k + 1].direction
               for k in range(len(seg_strokes) - 1)):
            i += 1
            continue

        direction = seg_strokes[0].direction

        high = float("-inf")
        low = float("inf")
        for s in seg_strokes:
            if s.start_fractal is not None:
                high = max(high, s.start_fractal.price)
                low = min(low, s.start_fractal.price)
            if s.end_fractal is not None:
                high = max(high, s.end_fractal.price)
                low = min(low, s.end_fractal.price)

        segments.append(Segment(
            strokes=seg_strokes,
            start_idx=seg_strokes[0].start_idx,
            end_idx=seg_strokes[-1].start_idx,
            direction=direction,
            high=high,
            low=low,
        ))
        i += step

    return segments


def build_segments_candidate(strokes):
    """Candidate configured segment implementation, currently locked to legacy parity."""
    if USE_SEGMENT_BREAK_BUILDER:
        return build_segments_by_break_candidate(strokes)
    return build_segments_fixed_window_candidate(strokes)


def find_pivots_candidate(segments):
    """Candidate pivot implementation, currently locked to legacy parity."""
    if len(segments) < PIVOT_MIN_SEGMENTS:
        return []

    pivots = []
    i = 0
    while i <= len(segments) - PIVOT_MIN_SEGMENTS:
        s1, s2, s3 = segments[i], segments[i + 1], segments[i + 2]
        zd = max(s1.low, s2.low, s3.low)
        zg = min(s1.high, s2.high, s3.high)

        if zg > zd:
            pivot_segs = [s1, s2, s3]
            j = i + 3
            while j < len(segments):
                next_seg = segments[j]
                new_zd = max(zd, next_seg.low)
                new_zg = min(zg, next_seg.high)

                if new_zg > new_zd:
                    zd = new_zd
                    zg = new_zg
                    pivot_segs.append(next_seg)
                    j += 1
                    continue

                break

            pivots.append(Pivot(
                ZD=round(zd, 2),
                ZG=round(zg, 2),
                segments=pivot_segs,
                start_idx=pivot_segs[0].start_idx,
                end_idx=pivot_segs[-1].end_idx,
            ))
            i = j
        else:
            i += 1

    return pivots


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
    return analyze_with_fractal_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        find_fractals_candidate,
    )


def build_strokes_candidate(fractals, highs, lows):
    """Candidate stroke implementation, currently locked to legacy parity."""
    strokes = []
    i = 0
    while i < len(fractals) - 1:
        f1 = fractals[i]

        j = i + 1
        found = False
        while j < len(fractals):
            if fractals[j].type == f1.type:
                j += 1
                continue

            f2 = fractals[j]
            kline_count = abs(f2.index - f1.index) + 1
            if kline_count < BI_MIN_KLINE_COUNT:
                j += 1
                continue

            direction = None
            if f1.type == "bottom" and f2.type == "top":
                if f2.price > f1.price and f2.index > f1.index:
                    direction = "up"
                    found = True
                    break
            elif f1.type == "top" and f2.type == "bottom":
                if f2.price < f1.price and f2.index > f1.index:
                    direction = "down"
                    found = True
                    break

            j += 1

        if not found:
            i += 1
            continue

        strokes.append(
            Stroke(
                start_idx=f1.index,
                end_idx=f2.index,
                start_price=f1.price,
                end_price=f2.price,
                direction=direction,
                start_fractal=f1,
                end_fractal=f2,
            )
        )
        i = j

    return strokes


def analyze_with_candidate_segment(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with segments supplied by the candidate component."""
    return analyze_with_segment_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        segment_provider=build_segments_candidate,
    )


def analyze_with_candidate_pivot(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with pivots supplied by the candidate component."""
    return analyze_with_segment_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        segment_provider=build_segments_with_config,
        pivot_provider=find_pivots_candidate,
    )


def analyze_with_candidate_stroke(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with strokes supplied by the candidate component."""
    return analyze_with_stroke_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        stroke_provider=build_strokes_candidate,
    )
