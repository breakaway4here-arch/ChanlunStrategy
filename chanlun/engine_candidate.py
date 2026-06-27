"""Candidate ChanLun engine components for offline dual-compare validation."""

import numpy as np

from config import (
    BI_MIN_KLINE_COUNT,
    DIVERGENCE_PLATEAU,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    THIRD_BUY_MAX_CHASE_PCT,
    SEGMENT_MIN_STROKES,
    PIVOT_MIN_SEGMENTS,
    USE_SEGMENT_BREAK_BUILDER,
)

from .engine_core import (
    build_strokes,
    calc_macd,
    classify_trend,
    check_divergence,
    find_pivots,
    find_fractals,
    inclusion_process,
)
from .engine_pipeline import (
    analyze_with_inclusion_provider,
    analyze_with_macd_provider,
    analyze_with_divergence_provider,
    analyze_with_pivot_provider,
    analyze_with_segment_provider,
    analyze_with_fractal_provider,
    analyze_with_stroke_provider,
    analyze_with_trend_provider,
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


def _segment_extreme_index_candidate(seg, extreme="low"):
    """找到线段极值所在的原始K线索引。low 找最低点，high 找最高点。"""
    if not seg.strokes:
        return seg.end_idx

    if extreme == "low":
        best_val = float('inf')
        best_idx = seg.end_idx
        for s in seg.strokes:
            val = min(s.start_price, s.end_price)
            if val < best_val:
                best_val = val
                best_idx = s.end_idx if s.direction == "down" else s.start_idx
        return best_idx

    best_val = float('-inf')
    best_idx = seg.end_idx
    for s in seg.strokes:
        val = max(s.start_price, s.end_price)
        if val > best_val:
            best_val = val
            best_idx = s.end_idx if s.direction == "up" else s.start_idx
    return best_idx


def _detect_swing_divergence_ref_candidate(result, buy_points):
    """基于 swing waves 检测底背驰，仅作为参考标注，不作为正式买点。"""
    strokes = result.swing_waves
    if not strokes or len(strokes) < 3:
        return

    hist = result.macd_hist
    if hist is None:
        return

    down_strokes = [s for s in strokes if s["direction"] == "down"]
    if len(down_strokes) < 2:
        return

    def _stroke_hist_area(s):
        a, b = s["start_idx"], s["end_idx"]
        if a >= len(hist) or b >= len(hist):
            return 0.0
        h = hist[a:b + 1]
        h = h[~np.isnan(h)]
        return float(np.sum(np.abs(h))) if len(h) > 0 else 0.0

    for i in range(len(down_strokes) - 1, 0, -1):
        curr = down_strokes[i]
        prev = down_strokes[i - 1]

        if curr["end_price"] >= prev["end_price"]:
            continue

        curr_area = _stroke_hist_area(curr)
        prev_area = _stroke_hist_area(prev)
        if prev_area == 0:
            continue

        ratio = curr_area / prev_area
        if ratio >= 0.85:
            continue

        idx = curr["end_idx"]
        price = curr["end_price"]

        buy_points.append({
            "type": "swing底背驰参考",
            "tier": "reference",
            "index": idx,
            "price": round(price, 2),
            "date": str(result.dates[idx]) if idx < len(result.dates) else "",
            "reason": f"swing笔底背驰(力度比={ratio:.2%})，仅供参考",
            "strength": "弱",
        })
        return


def _find_second_buy_point_candidate(result, buy_points):
    """二买：需在一买之后，首次回拉不破一买低点。

    正式 二买：上离开 + 回拉必须都是已确认线段。
    二买待确认：使用未确认线段检测，仅用于展示，不进选股。
    """
    first_buys = [bp for bp in buy_points if bp["type"] == "一买"]
    if not first_buys:
        return

    first = max(first_buys, key=lambda x: x["index"])
    first_idx = first["index"]
    first_price = first["price"]

    confirmed = [s for s in result.segments if s.confirmed]

    def _try_find(post_segments, label, strength_suffix):
        del strength_suffix
        if len(post_segments) < 2:
            return None
        saw_up = False
        for seg in post_segments:
            if not saw_up:
                if seg.direction == "up":
                    saw_up = True
                continue
            if seg.direction == "down":
                if seg.low > first_price:
                    buy_idx = _segment_extreme_index_candidate(seg, "low")
                    base_strength = "强" if seg.low > first_price * 1.02 else "中"
                    bp_tier = "formal" if label == "二买" else "reference"
                    return {
                        "type": label,
                        "tier": bp_tier,
                        "index": buy_idx,
                        "price": round(seg.low, 2),
                        "date": str(result.dates[buy_idx]) if buy_idx < len(result.dates) else "",
                        "reason": f"一买后首次回拉, 低点={seg.low:.2f}>{first_price:.2f}(一买低点)",
                        "strength": base_strength if label == "二买" else "弱",
                    }
                return None
        return None

    formal_post = [s for s in confirmed if s.start_idx >= first_idx]
    formal = _try_find(formal_post, "二买", "")
    if formal:
        buy_points.append(formal)
        return

    all_post = [s for s in result.segments if s.start_idx >= first_idx]
    pending = _try_find(all_post, "二买待确认", "_pending")
    if pending:
        buy_points.append(pending)


def _find_third_buy_point_candidate(result, buy_points):
    """三买：标准中枢 + 首次向上离开 + 首次回拉不破 ZG。"""
    if not result.pivots:
        return

    pivot = result.pivots[-1]
    confirmed = [s for s in result.segments if s.confirmed]
    post = [s for s in confirmed if s.start_idx >= pivot.end_idx]
    if len(post) < 2:
        return

    leave_idx = None
    for k, seg in enumerate(post):
        if seg.direction == "up":
            leave_idx = k
            break
    if leave_idx is None:
        return

    pullback = None
    for seg in post[leave_idx + 1:]:
        if seg.direction == "down":
            pullback = seg
            break
    if pullback is None:
        return

    if pullback.low <= pivot.ZG:
        return

    current_price = float(result.closes[-1])
    if (current_price - pullback.low) / pullback.low > THIRD_BUY_MAX_CHASE_PCT:
        buy_type = "三买已错过"
        strength = "弱"
    else:
        buy_type = "三买"
        dist_pct = round((pullback.low - pivot.ZG) / pivot.ZG * 100, 2)
        strength = "强" if dist_pct > 1 else "中"

    buy_idx = _segment_extreme_index_candidate(pullback, "low")
    buy_points.append({
        "type": buy_type,
        "tier": "formal" if buy_type == "三买" else "blocked",
        "index": buy_idx,
        "price": round(pullback.low, 2),
        "date": str(result.dates[buy_idx]) if buy_idx < len(result.dates) else "",
        "reason": f"突破ZG={pivot.ZG}后首次回拉, 回拉低点={pullback.low:.2f}>ZG={pivot.ZG}",
        "strength": strength,
    })


def _find_pivot_buy_points_candidate(result, pivots, buy_points):
    """基于标准中枢的辅助买点参考。"""
    closes = result.closes
    now_price = float(closes[-1])
    n = len(closes)

    def _get(p, key):
        return p[key] if isinstance(p, dict) else getattr(p, key)

    best_p = None
    best_dist = float('inf')
    for p in pivots:
        zd = _get(p, 'ZD')
        dist = abs(now_price - zd) / zd if zd > 0 else float('inf')
        if dist < best_dist:
            best_dist = dist
            best_p = p

    if best_p is None:
        return

    zg = _get(best_p, 'ZG')
    zd = _get(best_p, 'ZD')
    end_idx = _get(best_p, 'end_idx')
    rel = (now_price - zd) / zd if zd > 0 else float('inf')
    pivot_recent = (n - 1 - end_idx) <= 20

    if pivot_recent and -0.05 <= rel <= 0.08:
        buy_points.append({
            "type": "中枢震荡低吸参考",
            "tier": "reference",
            "index": n - 1,
            "price": now_price,
            "date": str(result.dates[-1]) if n > 0 else "",
            "reason": f"中枢下沿附近(ZG={zg}, ZD={zd}), 现价={now_price}, 距ZD={rel*100:+.1f}%",
            "strength": "弱",
        })


def locate_buy_sell_points_candidate(result, divergence_threshold=0.85):
    """Candidate signal detector, currently locked to legacy parity."""
    buy_points = []
    sell_points = []
    div = result.divergence

    if div and div.get("is_divergence"):
        area_ratio = div.get("area_ratio", 1.0)
        is_plateau = "盘整" in div.get("type", "")
        threshold = DIVERGENCE_PLATEAU if is_plateau else divergence_threshold

        div_last = div.get("last_segment")
        div_seg = None
        if div_last and len(div_last) == 2:
            for s in result.segments:
                if s.confirmed and s.start_idx == div_last[0] and s.end_idx == div_last[1]:
                    div_seg = s
                    break

        if "底背驰" in div.get("type", "") and area_ratio < threshold and div_seg and div_seg.direction == "down":
            buy_idx = _segment_extreme_index_candidate(div_seg, "low")
            buy_price = div_seg.low
            div_label = "一买" if "趋势" in div.get("type", "") else "盘整背驰参考"
            div_tier = "formal" if div_label == "一买" else "reference"
            buy_points.append({
                "type": div_label,
                "tier": div_tier,
                "index": buy_idx,
                "price": round(buy_price, 2),
                "date": str(result.dates[buy_idx]) if buy_idx < len(result.dates) else "",
                "reason": f"底背驰(力度比={area_ratio:.2%})，下跌力度衰竭",
                "strength": "强" if area_ratio < 0.6 else "中" if area_ratio < 0.8 else "弱",
            })

        if "顶背驰" in div.get("type", "") and area_ratio < threshold and div_seg and div_seg.direction == "up":
            sell_idx = _segment_extreme_index_candidate(div_seg, "high")
            sell_price = div_seg.high
            sell_points.append({
                "type": "一卖",
                "index": sell_idx,
                "price": round(sell_price, 2),
                "date": str(result.dates[sell_idx]) if sell_idx < len(result.dates) else "",
                "reason": f"顶背驰(力度比={area_ratio:.2%})，上涨力度衰竭",
                "strength": "强" if area_ratio < 0.6 else "中" if area_ratio < 0.8 else "弱",
            })

    _detect_swing_divergence_ref_candidate(result, buy_points)
    _find_second_buy_point_candidate(result, buy_points)

    if result.pivots:
        _find_pivot_buy_points_candidate(result, result.pivots, buy_points)

    _find_third_buy_point_candidate(result, buy_points)

    return buy_points, sell_points


def classify_trend_candidate(pivots, segments):
    """Candidate trend classifier, currently locked to legacy parity."""
    if len(pivots) == 0:
        return "无中枢"
    if len(pivots) == 1:
        return "盘整"

    moves_up = 0
    moves_down = 0
    for i in range(1, len(pivots)):
        if pivots[i].ZD > pivots[i - 1].ZG:
            moves_up += 1
        elif pivots[i].ZG < pivots[i - 1].ZD:
            moves_down += 1

    if moves_up >= 1 and moves_up >= moves_down:
        return "上涨趋势"
    elif moves_down >= 1 and moves_down >= moves_up:
        return "下跌趋势"
    return "盘整"


def check_divergence_candidate(closes, segments, dif, dea, hist, pivots=None):
    """Candidate divergence detector, currently locked to legacy parity."""
    if len(segments) < 2:
        return None

    last_seg = segments[-1]
    prev_seg = None
    for segment in reversed(segments[:-1]):
        if segment.direction == last_seg.direction:
            prev_seg = segment
            break

    if prev_seg is None:
        return None

    def calc_macd_area(segment):
        start, end = segment.start_idx, segment.end_idx
        if start >= len(hist) or end >= len(hist):
            return 0.0
        seg_hist = hist[start:end + 1]
        seg_hist = seg_hist[~np.isnan(seg_hist)]
        if len(seg_hist) == 0:
            return 0.0
        return float(np.sum(np.abs(seg_hist)))

    last_area = calc_macd_area(last_seg)
    prev_area = calc_macd_area(prev_seg)

    if prev_area == 0:
        return None

    area_ratio = last_area / prev_area

    has_trend = pivots and len(pivots) >= 2
    prefix = "趋势" if has_trend else "盘整"

    is_divergence = False
    div_type = ""
    if last_seg.direction == "up":
        if last_seg.high > prev_seg.high and area_ratio < 1.0:
            is_divergence = True
            div_type = prefix + "顶背驰"
    else:
        if last_seg.low < prev_seg.low and area_ratio < 1.0:
            is_divergence = True
            div_type = prefix + "底背驰"

    hist_div = False
    if last_seg.direction == "up":
        last_hist_max = np.max(hist[last_seg.start_idx:last_seg.end_idx + 1])
        prev_hist_max = np.max(hist[prev_seg.start_idx:prev_seg.end_idx + 1])
        if last_seg.high > prev_seg.high and last_hist_max < prev_hist_max:
            hist_div = True
    else:
        last_hist_min = np.min(hist[last_seg.start_idx:last_seg.end_idx + 1])
        prev_hist_min = np.min(hist[prev_seg.start_idx:prev_seg.end_idx + 1])
        if last_seg.low < prev_seg.low and abs(last_hist_min) < abs(prev_hist_min):
            hist_div = True

    return {
        "type": div_type,
        "is_divergence": is_divergence or hist_div,
        "area_ratio": round(area_ratio, 4),
        "hist_divergence": hist_div,
        "prev_segment": (prev_seg.start_idx, prev_seg.end_idx),
        "last_segment": (last_seg.start_idx, last_seg.end_idx),
    }


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
    return analyze_with_pivot_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
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


def analyze_with_candidate_trend(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with trend classification supplied by the candidate component."""
    return analyze_with_trend_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        trend_provider=classify_trend_candidate,
    )


def analyze_with_candidate_divergence(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with divergence detection supplied by the candidate component."""
    return analyze_with_divergence_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        divergence_provider=check_divergence_candidate,
    )


def analyze_with_candidate_signal(code, name, dates, opens, highs, lows, closes, volumes):
    """Run legacy pipeline with signal detection supplied by the candidate component."""
    return analyze_with_divergence_provider(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes,
        divergence_provider=check_divergence,
        signal_provider=locate_buy_sell_points_candidate,
    )
