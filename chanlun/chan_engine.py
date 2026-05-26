"""
缠论计算引擎 — 包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点
纯理论实现，不掺杂策略偏好。两版本共用。
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from config import (
    BI_MIN_KLINE_COUNT, SEGMENT_MIN_STROKES, PIVOT_MIN_SEGMENTS,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    DIVERGENCE_PLATEAU,
)

THIRD_BUY_MAX_CHASE_PCT = 0.08


@dataclass
class Fractal:
    """分型"""
    type: str        # "top" | "bottom"
    index: int       # 原始K线索引
    price: float     # 顶分型取high，底分型取low
    klines: list = field(default_factory=list)  # 构成分型的K线索引列表


@dataclass
class Stroke:
    """笔"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    direction: str   # "up" | "down"
    start_fractal: Optional[Fractal] = None
    end_fractal: Optional[Fractal] = None


@dataclass
class Segment:
    """线段"""
    strokes: list   # list of Stroke
    start_idx: int
    end_idx: int
    direction: str  # "up" | "down"
    high: float
    low: float
    destroyed_by_idx: Optional[int] = None
    confirmed: bool = True


@dataclass
class Pivot:
    """中枢"""
    ZD: float        # 中枢下沿 = max(段低点)
    ZG: float        # 中枢上沿 = min(段高点)
    segments: list   # 构成中枢的线段列表
    start_idx: int
    end_idx: int
    level: str = "本级别"


@dataclass
class ChanResult:
    """单只股票的完整缠论分析结果"""
    code: str
    name: str
    closes: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    opens: np.ndarray
    volumes: np.ndarray
    dates: list
    fractals: list = field(default_factory=list)
    strokes: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    pivots: list = field(default_factory=list)
    swing_waves: list = field(default_factory=list)  # swing tracking 笔
    swing_zones: list = field(default_factory=list)  # 笔中枢（swing tracking）
    divergence: Optional[dict] = None
    buy_points: list = field(default_factory=list)
    sell_points: list = field(default_factory=list)
    trend_type: str = ""  # "盘整" | "上涨趋势" | "下跌趋势"
    macd_dif: np.ndarray = None
    macd_dea: np.ndarray = None
    macd_hist: np.ndarray = None


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


# ============================================================
# 1. 包含处理
# ============================================================
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


# ============================================================
# 2. 分型识别
# ============================================================
def find_fractals(highs, lows, idx_map, dates=None):
    """
    识别顶分型和底分型。
    顶分型：中间K线高点最高，低点最高（三根K线中）
    底分型：中间K线低点最低，高点最低（三根K线中）
    需要至少5根K线（处理后）才能构成有效分型序列

    price 使用合并后K线值（反映真实极值），index 通过 idx_map 映射回原始K线索引。
    两个坐标系各有用途：price 用于笔/线段的价位计算，
    index 用于在原始K线数组（closes/dates）中定位。
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


# ============================================================
# 3. 笔划分
# ============================================================
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


# ============================================================
# 3b. Swing Tracking 笔划分（替代方案：纯线性扫描）
# ============================================================
def build_strokes_swing(highs, lows, closes, min_bars=2, min_swing_pct=0.03):
    """
    Zigzag 笔划分：找交替的显著转折点。不依赖分型，纯价格结构驱动。

    算法：
    - 从当前点出发，沿趋势方向持续更新极值
    - 当反向运动持续 min_bars 根K线 且 反向幅度 >= min_swing_pct → 确认转折
    - 记录一笔，从转折点继续沿新方向跟踪
    - 不回溯：新笔从上一笔终点开始，只向前扫描
    """
    n = len(highs)
    if n < min_bars + 2:
        return []

    if closes[min_bars] >= closes[0]:
        direction = "up"
    else:
        direction = "down"

    strokes = []
    stroke_start_idx = 0

    if direction == "up":
        running_extreme = highs[0]
        stroke_start_price = highs[0]
    else:
        running_extreme = lows[0]
        stroke_start_price = lows[0]

    extreme_idx = 0
    bars_since_extreme = 0
    opposit_extreme = None

    i = 1
    while i < n:
        if direction == "up":
            if highs[i] > running_extreme:
                running_extreme = highs[i]
                extreme_idx = i
                bars_since_extreme = 0
                opposit_extreme = None
            else:
                bars_since_extreme += 1
                if opposit_extreme is None or lows[i] < opposit_extreme:
                    opposit_extreme = lows[i]

            if bars_since_extreme >= min_bars and opposit_extreme is not None and running_extreme > 0:
                swing_down = (running_extreme - opposit_extreme) / running_extreme
                if swing_down >= min_swing_pct and extreme_idx > stroke_start_idx:
                    strokes.append({
                        "start_idx": stroke_start_idx,
                        "end_idx": extreme_idx,
                        "start_price": round(stroke_start_price, 2),
                        "end_price": round(running_extreme, 2),
                        "direction": "up",
                    })
                    direction = "down"
                    stroke_start_idx = extreme_idx
                    stroke_start_price = running_extreme
                    running_extreme = opposit_extreme
                    for j in range(extreme_idx, i + 1):
                        if lows[j] == opposit_extreme:
                            extreme_idx = j
                            break
                    bars_since_extreme = i - extreme_idx
                    opposit_extreme = None
        else:
            if lows[i] < running_extreme:
                running_extreme = lows[i]
                extreme_idx = i
                bars_since_extreme = 0
                opposit_extreme = None
            else:
                bars_since_extreme += 1
                if opposit_extreme is None or highs[i] > opposit_extreme:
                    opposit_extreme = highs[i]

            if bars_since_extreme >= min_bars and opposit_extreme is not None and running_extreme > 0:
                swing_up = (opposit_extreme - running_extreme) / running_extreme
                if swing_up >= min_swing_pct and extreme_idx > stroke_start_idx:
                    strokes.append({
                        "start_idx": stroke_start_idx,
                        "end_idx": extreme_idx,
                        "start_price": round(stroke_start_price, 2),
                        "end_price": round(running_extreme, 2),
                        "direction": "down",
                    })
                    direction = "up"
                    stroke_start_idx = extreme_idx
                    stroke_start_price = running_extreme
                    running_extreme = opposit_extreme
                    for j in range(extreme_idx, i + 1):
                        if highs[j] == opposit_extreme:
                            extreme_idx = j
                            break
                    bars_since_extreme = i - extreme_idx
                    opposit_extreme = None
        i += 1

    if extreme_idx > stroke_start_idx:
        strokes.append({
            "start_idx": stroke_start_idx,
            "end_idx": extreme_idx,
            "start_price": round(stroke_start_price, 2),
            "end_price": round(running_extreme, 2),
            "direction": direction,
        })

    return strokes


def prune_strokes(strokes, min_pct=0.04):
    """合并微小笔：反复找到幅度最小的笔并合并。"""
    if len(strokes) < 3:
        return strokes

    for _ in range(len(strokes)):
        best_i = -1
        best_pct = float('inf')
        for i in range(1, len(strokes) - 1):
            s = strokes[i]
            pct = abs(s["end_price"] - s["start_price"]) / s["start_price"] if s["start_price"] > 0 else 0
            if pct < min_pct and pct < best_pct:
                best_pct = pct
                best_i = i

        if best_i < 0:
            break

        i = best_i
        prev = strokes[i - 1]
        nxt = strokes[i + 1]
        if prev["direction"] == nxt["direction"]:
            prev["end_idx"] = nxt["end_idx"]
            prev["end_price"] = nxt["end_price"]
            del strokes[i + 1]
            del strokes[i]
        else:
            break

    return strokes


def build_stroke_pivots(strokes, min_strokes=3):
    """笔中枢：至少3笔重叠区间，持续扩展模式。"""
    if len(strokes) < min_strokes:
        return []

    pivots = []
    i = 0
    while i <= len(strokes) - min_strokes:
        s3 = strokes[i:i + min_strokes]
        ranges = []
        for s in s3:
            lo = min(s["start_price"], s["end_price"])
            hi = max(s["start_price"], s["end_price"])
            ranges.append((lo, hi))
        zd = max(r[0] for r in ranges)
        zg = min(r[1] for r in ranges)
        if zg > zd:
            j = i + min_strokes
            while j < len(strokes):
                s = strokes[j]
                lo = min(s["start_price"], s["end_price"])
                hi = max(s["start_price"], s["end_price"])
                new_zd = max(zd, lo)
                new_zg = min(zg, hi)
                if new_zg > new_zd:
                    zd, zg = new_zd, new_zg
                    j += 1
                else:
                    break
            pivots.append(Pivot(
                ZD=round(zd, 2), ZG=round(zg, 2),
                segments=[],  # 笔中枢不依赖段
                start_idx=s3[0]["start_idx"],
                end_idx=strokes[j - 1]["end_idx"],
                level="笔中枢",
            ))
            i = j
        else:
            i += 1
    return pivots


# ============================================================
# 4. 线段划分
# ============================================================

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


def _segment_extreme_index(seg, extreme="low"):
    """找到线段极值所在的原始K线索引。low 找最低点，high 找最高点。"""
    if not seg.strokes:
        return seg.end_idx

    if extreme == "low":
        best_val = float('inf')
        best_idx = seg.end_idx
        for s in seg.strokes:
            val = stroke_low(s)
            if val < best_val:
                best_val = val
                best_idx = s.end_idx if s.direction == "down" else s.start_idx
        return best_idx
    else:
        best_val = float('-inf')
        best_idx = seg.end_idx
        for s in seg.strokes:
            val = stroke_high(s)
            if val > best_val:
                best_val = val
                best_idx = s.end_idx if s.direction == "up" else s.start_idx
        return best_idx


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


# ============================================================
# 5. 中枢识别
# ============================================================
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
                new_zd = max(zd, next_seg.low)
                new_zg = min(zg, next_seg.high)
                if new_zg > new_zd:
                    zd = new_zd
                    zg = new_zg
                    pivot_segs.append(next_seg)
                    j += 1
                else:
                    break  # 不再重叠，中枢结束

            pivots.append(Pivot(
                ZD=round(zd, 2),
                ZG=round(zg, 2),
                segments=pivot_segs,
                start_idx=pivot_segs[0].start_idx,
                end_idx=pivot_segs[-1].end_idx,
            ))
            i = j  # 跳过已纳入中枢的段
        else:
            i += 1

    return pivots


# ============================================================
# 6. 走势类型分类
# ============================================================
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


# ============================================================
# 7. 背驰判断
# ============================================================
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


# ============================================================
# 8. 买卖点定位
# ============================================================
def locate_buy_sell_points(result, divergence_threshold=0.85):
    """
    定位三类买卖点。
    仅使用标准段中枢（result.pivots），不使用 swing 中枢。
    """
    buy_points = []
    sell_points = []
    div = result.divergence

    # ── 一买/一卖：背驰驱动（仅使用已确认线段）──
    if div and div.get("is_divergence"):
        area_ratio = div.get("area_ratio", 1.0)
        is_plateau = "盘整" in div.get("type", "")
        threshold = DIVERGENCE_PLATEAU if is_plateau else divergence_threshold

        # 通过 divergence 的 last_segment 索引定位背驰发生的实际线段
        div_last = div.get("last_segment")
        div_seg = None
        if div_last and len(div_last) == 2:
            for s in result.segments:
                if s.confirmed and s.start_idx == div_last[0] and s.end_idx == div_last[1]:
                    div_seg = s
                    break

        if "底背驰" in div["type"] and area_ratio < threshold and div_seg and div_seg.direction == "down":
            buy_idx = _segment_extreme_index(div_seg, "low")
            buy_price = div_seg.low
            div_label = "一买" if "趋势" in div["type"] else "盘整背驰参考"
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

        if "顶背驰" in div["type"] and area_ratio < threshold and div_seg and div_seg.direction == "up":
            sell_idx = _segment_extreme_index(div_seg, "high")
            sell_price = div_seg.high
            sell_points.append({
                "type": "一卖",
                "index": sell_idx,
                "price": round(sell_price, 2),
                "date": str(result.dates[sell_idx]) if sell_idx < len(result.dates) else "",
                "reason": f"顶背驰(力度比={area_ratio:.2%})，上涨力度衰竭",
                "strength": "强" if area_ratio < 0.6 else "中" if area_ratio < 0.8 else "弱",
            })

    # ── Swing 底背驰参考（非正式买点）──
    _detect_swing_divergence_ref(result, buy_points)

    # ── 二买：需在一买之后 ──
    _find_second_buy_point(result, buy_points)

    # ── 中枢结构买点（仅标准中枢）──
    if result.pivots:
        _find_pivot_buy_points(result, result.pivots, buy_points)

    # ── 三买（标准中枢破坏确认）──
    _find_third_buy_point(result, buy_points)

    return buy_points, sell_points


def _detect_swing_divergence_ref(result, buy_points):
    """
    基于 swing waves 检测底背驰，仅作为参考标注，不作为正式买点。
    """
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


def _find_second_buy_point(result, buy_points):
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
        """在给定段列表中搜索 二买 形态，返回找到的买点 dict 或 None。"""
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
                    buy_idx = _segment_extreme_index(seg, "low")
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
                return None  # 首次回拉跌破一买低点，不再继续
        return None

    # 1) 正式二买：只用已确认线段
    formal_post = [s for s in confirmed if s.start_idx >= first_idx]
    formal = _try_find(formal_post, "二买", "")
    if formal:
        buy_points.append(formal)
        return

    # 2) 待确认二买：含未确认线段，仅供展示
    all_post = [s for s in result.segments if s.start_idx >= first_idx]
    pending = _try_find(all_post, "二买待确认", "_pending")
    if pending:
        buy_points.append(pending)


def _find_third_buy_point(result, buy_points):
    """三买：标准中枢 + 首次向上离开 + 首次回拉不破 ZG。"""
    if not result.pivots:
        return

    pivot = result.pivots[-1]
    confirmed = [s for s in result.segments if s.confirmed]
    post = [s for s in confirmed if s.start_idx >= pivot.end_idx]
    if len(post) < 2:
        return

    # 找到中枢后第一段向上的离开
    leave_idx = None
    for k, seg in enumerate(post):
        if seg.direction == "up":
            leave_idx = k
            break
    if leave_idx is None:
        return

    # 找到离开后的第一段向下回拉
    pullback = None
    for seg in post[leave_idx + 1:]:
        if seg.direction == "down":
            pullback = seg
            break
    if pullback is None:
        return

    leave = post[leave_idx]
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

    buy_idx = _segment_extreme_index(pullback, "low")
    buy_points.append({
        "type": buy_type,
        "tier": "formal" if buy_type == "三买" else "blocked",
        "index": buy_idx,
        "price": round(pullback.low, 2),
        "date": str(result.dates[buy_idx]) if buy_idx < len(result.dates) else "",
        "reason": f"突破ZG={pivot.ZG}后首次回拉, 回拉低点={pullback.low:.2f}>ZG={pivot.ZG}",
        "strength": strength,
    })


def _find_pivot_buy_points(result, pivots, buy_points):
    """
    基于标准中枢的辅助买点参考。
    类二买在 phase 1 禁用，仅输出 中枢震荡低吸参考（不参与选股）。
    """
    closes = result.closes
    now_price = float(closes[-1])
    n = len(closes)

    def _get(p, key):
        return p[key] if isinstance(p, dict) else getattr(p, key)

    # ── 找 ZD 最接近当前价格的中枢 ──
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

    # 中枢时效性
    pivot_recent = (n - 1 - end_idx) <= 20

    # ── 中枢震荡低吸参考（非正式买点，不参与选股）──
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


# ============================================================
# 主分析函数
# ============================================================
def analyze(code, name, dates, opens, highs, lows, closes, volumes):
    """
    对一只股票进行完整的缠论分析。
    返回 ChanResult 对象。
    """
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
    from config import USE_SEGMENT_BREAK_BUILDER
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
