"""Swing helper functions extracted from legacy chan_engine."""

import numpy as np
from .engine_types import Pivot


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
                    zd = new_zd
                    zg = new_zg
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
