"""Signal detection helpers extracted from legacy chan_engine."""

import numpy as np

from .engine_types import Pivot
from config import DIVERGENCE_PLATEAU, THIRD_BUY_MAX_CHASE_PCT


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


def _segment_extreme_index(seg, extreme="low"):
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
    else:
        best_val = float('-inf')
        best_idx = seg.end_idx
        for s in seg.strokes:
            val = max(s.start_price, s.end_price)
            if val > best_val:
                best_val = val
                best_idx = s.end_idx if s.direction == "up" else s.start_idx
        return best_idx
