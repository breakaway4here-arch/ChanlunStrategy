"""Core ChanLun engine calculations and structure builders."""

import numpy as np

from .engine_types import Fractal, Pivot, Segment, Stroke
from config import (
    BI_MIN_KLINE_COUNT, SEGMENT_MIN_STROKES, PIVOT_MIN_SEGMENTS,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
)


def ema(data, period):
    """指数移动平均，处理 NaN 输入"""
    n = len(data)
    if n < period:
        return np.full_like(data, np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    result = np.full_like(data, np.nan, dtype=float)

    # 找第一个非 NaN 的位置作为起始
    start = 0
    while start < n and np.isnan(data[start]):
        start += 1
    if start >= n:
        return result

    # 初始化：使用第一个有效值之后的 period 个非 NaN 数据的均值
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


def calc_macd(closes):
    """计算 MACD"""
    ema_fast = ema(closes, MACD_FAST)
    ema_slow = ema(closes, MACD_SLOW)
    dif = ema_fast - ema_slow
    dea = ema(dif, MACD_SIGNAL)
    hist = 2.0 * (dif - dea)
    return dif, dea, hist


def inclusion_process(highs, lows):
    """
    合并有包含关系的K线。
    向上趋势时：取高高、高低（合并后取较高者）
    向下趋势时：取低低、低高（合并后取较低者）
    返回: 合并后的 highs, lows, 以及原索引映射
    """
    n = len(highs)
    if n < 3:
        return highs.copy(), lows.copy(), list(range(n))

    merged_high = []
    merged_low = []
    idx_map = []  # merged_idx -> [original_indices]

    direction = 0  # 1=向上, -1=向下, 0=未确定
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

        # 判断包含关系
        is_included = (curr_h <= prev_h and curr_l >= prev_l) or \
                      (curr_h >= prev_h and curr_l <= prev_l)

        if not is_included:
            # 无包含关系，直接加入，并确定方向
            if curr_h > prev_h:
                direction = 1
            elif curr_h < prev_h:
                direction = -1
            merged_high.append(curr_h)
            merged_low.append(curr_l)
            idx_map.append([i])
            i += 1
            continue

        # 有包含关系，需要合并
        if direction == -1:
            # 向下趋势：取低低、低高
            new_low = min(prev_l, curr_l)
            new_high = min(prev_h, curr_h)
            merged_high[-1] = new_high
            merged_low[-1] = new_low
            idx_map[-1].append(i)
        elif direction == 1:
            # 向上趋势：取高高、高低
            new_low = max(prev_l, curr_l)
            new_high = max(prev_h, curr_h)
            merged_high[-1] = new_high
            merged_low[-1] = new_low
            idx_map[-1].append(i)
        else:
            # 方向未确定，跳过包含处理，直接追加
            merged_high.append(curr_h)
            merged_low.append(curr_l)
            idx_map.append([i])

        i += 1

    return np.array(merged_high), np.array(merged_low), idx_map


def find_fractals(highs, lows, idx_map, dates=None):
    """
    识别顶分型和底分型。
    顶分型：中间K线高点最高，低点最高（三根K线中）
    底分型：中间K线低点最低，高点最低（三根K线中）
    需要至少5根K线（处理后）才能构成有效分型序列

    price 使用合并后K线值（反映真实极值），index 通过 idx_map 映射回原始K线索引。
    两个坐标系各有用途：price 用于笔/线段的价位计算，index 用于在原始K线数组（closes/dates）中定位。
    """
    n = len(highs)
    if n < 5:
        return []

    def _orig_idx(merged_i):
        """合并后索引 → 原始K线索引（取中间那根）"""
        indices = idx_map[merged_i] if isinstance(idx_map[merged_i], list) else [idx_map[merged_i]]
        return indices[len(indices) // 2]

    fractals = []
    for i in range(1, n - 1):
        # 顶分型：中间高点 > 左右高点 且 中间低点 > 左右低点
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1] \
           and lows[i] > lows[i - 1] and lows[i] > lows[i + 1]:
            orig_indices = idx_map[i] if isinstance(idx_map[i], list) else [idx_map[i]]
            fractals.append(Fractal(
                type="top",
                index=_orig_idx(i),
                price=highs[i],
                klines=orig_indices,
            ))

        # 底分型：中间低点 < 左右低点 且 中间高点 < 左右高点
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1] \
           and highs[i] < highs[i - 1] and highs[i] < highs[i + 1]:
            orig_indices = idx_map[i] if isinstance(idx_map[i], list) else [idx_map[i]]
            fractals.append(Fractal(
                type="bottom",
                index=_orig_idx(i),
                price=lows[i],
                klines=orig_indices,
            ))

    # 去重 + 距离过滤
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

    # 确保交替排列
    if filtered and filtered[0].type == "bottom":
        filtered.pop(0)
    if filtered and filtered[-1].type == "top":
        filtered.pop()

    return filtered


def build_strokes(fractals, highs, lows):
    """
    连接相邻的顶底分型成笔。
    条件:
    1. 顶底交替
    2. 至少 BI_MIN_KLINE_COUNT 根K线（处理后的）含两端
    3. 顶分型高点 > 相邻底分型低点（向上笔）
    4. 底分型低点 < 相邻顶分型高点（向下笔）
    """
    strokes = []
    i = 0
    while i < len(fractals) - 1:
        f1 = fractals[i]

        # 从 f1 出发，搜索满足全部条件的 f2
        j = i + 1
        found = False
        while j < len(fractals):
            if fractals[j].type == f1.type:
                j += 1
                continue

            f2 = fractals[j]
            kline_count = abs(f2.index - f1.index) + 1
            if kline_count < BI_MIN_KLINE_COUNT:
                j += 1  # 间距不够，继续找下一个同向分型
                continue

            # 检查价格条件
            if f1.type == "bottom" and f2.type == "top":
                if f2.price > f1.price and f2.index > f1.index:
                    found = True
                    direction = "up"
                    break
            elif f1.type == "top" and f2.type == "bottom":
                if f2.price < f1.price and f2.index > f1.index:
                    found = True
                    direction = "down"
                    break

            j += 1  # 价格条件不满足，继续找

        if not found:
            i += 1  # f1 无法形成任何笔，跳过
            continue

        strokes.append(Stroke(
            start_idx=f1.index, end_idx=f2.index,
            start_price=f1.price, end_price=f2.price,
            direction=direction,
            start_fractal=f1, end_fractal=f2,
        ))

        i = j

    return strokes


def stroke_high(stroke):
    return max(stroke.start_price, stroke.end_price)


def stroke_low(stroke):
    return min(stroke.start_price, stroke.end_price)


def _is_alternating(strokes):
    return all(strokes[i].direction != strokes[i + 1].direction for i in range(len(strokes) - 1))


def _make_segment(strokes, confirmed=True, destroyed_by_idx=None):
    return Segment(
        strokes=strokes[:],
        start_idx=strokes[0].start_idx,
        end_idx=strokes[-1].end_idx,
        direction=strokes[0].direction,
        high=max(stroke_high(s) for s in strokes),
        low=min(stroke_low(s) for s in strokes),
        confirmed=confirmed,
        destroyed_by_idx=destroyed_by_idx,
    )


def _segment_destroyed(candidate, direction):
    if len(candidate) < 4:
        return False

    last = candidate[-1]

    if direction == "up" and last.direction == "down":
        prior_down_lows = [stroke_low(s) for s in candidate[:-1] if s.direction == "down"]
        return bool(prior_down_lows) and stroke_low(last) < min(prior_down_lows)

    if direction == "down" and last.direction == "up":
        prior_up_highs = [stroke_high(s) for s in candidate[:-1] if s.direction == "up"]
        return bool(prior_up_highs) and stroke_high(last) > max(prior_up_highs)

    return False


def build_segments_by_break(strokes):
    if len(strokes) < 3:
        return []

    segments = []
    i = 0
    n = len(strokes)

    while i <= n - 3:
        while i <= n - 3 and not _is_alternating(strokes[i:i + 3]):
            i += 1
        if i > n - 3:
            break

        current = strokes[i:i + 3]
        j = i + 3
        closed = False

        while j < n:
            current.append(strokes[j])
            if not _is_alternating(current[-3:]):
                j += 1
                continue

            if _segment_destroyed(current, current[0].direction):
                old = current[:-1]
                segments.append(_make_segment(old, confirmed=True, destroyed_by_idx=strokes[j].end_idx))
                i = max(j - 2, i + 1)
                closed = True
                break

            j += 1

        if not closed:
            segments.append(_make_segment(current, confirmed=False))
            break

    return segments


def build_segments_fixed_window(strokes):
    """
    由笔划分线段。线段首尾相连（前一段终点=后一段起点）。
    每 SEGMENT_MIN_STROKES 笔构成一段，以步长 (SEGMENT_MIN_STROKES-1) 滑动，
    确保段间首尾相连无重叠。

    保留作为回退方案。
    """
    if len(strokes) < SEGMENT_MIN_STROKES:
        return []

    segments = []
    step = SEGMENT_MIN_STROKES - 1  # 首尾相连：段[i]的最后一笔 = 段[i+1]的第一笔
    i = 0
    while i <= len(strokes) - SEGMENT_MIN_STROKES:
        seg_strokes = strokes[i:i + SEGMENT_MIN_STROKES]

        # 方向交替检查
        if any(seg_strokes[k].direction == seg_strokes[k + 1].direction
               for k in range(len(seg_strokes) - 1)):
            i += 1
            continue

        direction = seg_strokes[0].direction

        # 极值（从分型取实际高低点）
        high = float('-inf')
        low = float('inf')
        for s in seg_strokes:
            if s.start_fractal:
                high = max(high, s.start_fractal.price)
                low = min(low, s.start_fractal.price)
            if s.end_fractal:
                high = max(high, s.end_fractal.price)
                low = min(low, s.end_fractal.price)

        segments.append(Segment(
            strokes=seg_strokes,
            start_idx=seg_strokes[0].start_idx,
            end_idx=seg_strokes[-1].start_idx,  # 用最后一笔的起点，保证首尾相连
            direction=direction,
            high=high,
            low=low,
        ))
        i += step

    return segments


def find_pivots(segments):
    """
    中枢：至少3个连续次级别段的重叠区间，持续扩展模式。
    从第一个3段重叠开始，后续每新增一段检查是否仍与当前中枢重叠，
    是则扩展（ZD取max, ZG取min），否则中枢结束，继续往后找下一个中枢。
    """
    if len(segments) < PIVOT_MIN_SEGMENTS:
        return []

    pivots = []
    i = 0
    while i <= len(segments) - PIVOT_MIN_SEGMENTS:
        s1, s2, s3 = segments[i], segments[i + 1], segments[i + 2]
        zd = max(s1.low, s2.low, s3.low)
        zg = min(s1.high, s2.high, s3.high)

        if zg > zd:
            # 持续扩展：后续段仍与当前中枢区间重叠则纳入
            pivot_segs = [s1, s2, s3]
            j = i + 3
            while j < len(segments):
                next_seg = segments[j]
                lo = next_seg.low
                hi = next_seg.high
                new_zd = max(zd, lo)
                new_zg = min(zg, hi)
                if new_zg > new_zd:
                    zd = new_zd
                    zg = new_zg
                    pivot_segs.append(next_seg)
                    j += 1
                else:
                    break

            pivots.append(Pivot(
                ZD=round(zd, 2), ZG=round(zg, 2),
                segments=pivot_segs,
                start_idx=pivot_segs[0].start_idx,
                end_idx=pivot_segs[-1].end_idx,
            ))
            i = j  # 跳过已纳入中枢的段
        else:
            i += 1

    return pivots


def classify_trend(pivots, segments):
    """
    走势类型：
    - 盘整：只有一个中枢
    - 上涨趋势：两个或以上中枢，中枢上移（后中枢ZD > 前中枢ZG）
    - 下跌趋势：两个或以上中枢，中枢下移（后中枢ZG < 前中枢ZD）
    """
    if len(pivots) == 0:
        return "无中枢"
    if len(pivots) == 1:
        return "盘整"

    # 检查中枢位置关系
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


def check_divergence(closes, segments, dif, dea, hist, pivots=None):
    """
    背驰判断：比较相邻两段同向走势的力度。
    力度 = MACD面积（dif柱面积）或 MACD柱子面积。
    背驰条件：价格创新高/低但力度减弱。
    pivots 不为空时区分趋势背驰 vs 盘整背驰。
    返回背驰信息字典。
    """
    if len(segments) < 2:
        return None

    # 取最后两个同向段
    last_seg = segments[-1]
    prev_seg = None
    for s in reversed(segments[:-1]):
        if s.direction == last_seg.direction:
            prev_seg = s
            break

    if prev_seg is None:
        return None

    # 计算两段对应的 MACD 面积
    def calc_macd_area(seg):
        start, end = seg.start_idx, seg.end_idx
        if start >= len(hist) or end >= len(hist):
            return 0.0
        # 用 hist 绝对值面积，跳过 NaN
        seg_hist = hist[start:end + 1]
        seg_hist = seg_hist[~np.isnan(seg_hist)]
        if len(seg_hist) == 0:
            return 0.0
        area = np.sum(np.abs(seg_hist))
        return float(area)

    last_area = calc_macd_area(last_seg)
    prev_area = calc_macd_area(prev_seg)

    if prev_area == 0:
        return None

    area_ratio = last_area / prev_area

    # 判断背驰，区分趋势/盘整
    has_trend = pivots and len(pivots) >= 2
    prefix = "趋势" if has_trend else "盘整"

    is_divergence = False
    div_type = ""
    if last_seg.direction == "up":
        # 上涨背驰：价格新高但力度减弱（顶背驰）
        if last_seg.high > prev_seg.high and area_ratio < 1.0:
            is_divergence = True
            div_type = prefix + "顶背驰"
    else:
        # 下跌背驰：价格新低但力度减弱（底背驰）
        if last_seg.low < prev_seg.low and area_ratio < 1.0:
            is_divergence = True
            div_type = prefix + "底背驰"

    # MACD柱子背驰：价格新高/低但柱子缩短
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
