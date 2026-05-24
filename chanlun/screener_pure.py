"""
缠论纯净版筛选器 — 仅使用缠论理论自身规则，不掺杂策略偏好。

筛选条件:
1. 基础过滤: 排除ST、上市<60天、涨跌停、日均成交<5000万
2. 缠论买点: 一买/二买/三买/类二买（纯缠论判定，无MA前置）
3. 背驰质量: 背驰力度比 < 阈值
"""

import numpy as np
from config import (
    PURE_DIVERGENCE_THRESHOLD, MIN_LISTED_DAYS, MIN_DAILY_AMOUNT,
    LIMIT_UP_THRESHOLD, LIMIT_DOWN_THRESHOLD,
)
from .data_fetcher import is_st_stock


def _has_macd_bullish_signal(min30_result):
    """检查30分钟是否有MACD金叉或底背驰信号"""
    # 底背驰信号
    if min30_result.divergence and min30_result.divergence.get("is_divergence"):
        div_type = min30_result.divergence.get("type", "")
        if "底背驰" in div_type:
            return True
    # MACD金叉（最近3根内DIF上穿DEA）
    dif = min30_result.macd_dif
    dea = min30_result.macd_dea
    if dif is not None and dea is not None and len(dif) >= 3 and len(dea) >= 3:
        for i in range(max(1, len(dif) - 3), len(dif)):
            if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
                return True
    return False


def screen_daily_pure(chan_results, sector_stocks, sectors):
    """
    纯净版日线初筛。

    参数:
        chan_results: [ChanResult, ...]  缠论分析结果列表
        sector_stocks: dict {code: {"sector": "板块名", "change_pct": 1.5}}
        sectors: 板块列表（用于板块名查找）

    返回:
        目标池: [dict, ...]
    """
    target_pool = []

    for result in chan_results:
        if result is None:
            continue

        code = result.code
        name = result.name

        # --- 基础过滤 ---
        # ST 过滤
        if is_st_stock(name):
            continue

        # 上市天数（K线数量不足）
        if len(result.closes) < MIN_LISTED_DAYS:
            continue

        # 涨跌停过滤（用最近一日涨跌幅判断）
        if len(result.closes) >= 2:
            prev_close = result.closes[-2]
            curr_close = result.closes[-1]
            if prev_close > 0:
                change_pct = (curr_close - prev_close) / prev_close * 100
                if change_pct >= LIMIT_UP_THRESHOLD or change_pct <= LIMIT_DOWN_THRESHOLD:
                    continue

        # 量能过滤：近5日日均成交额 > MIN_DAILY_AMOUNT
        # volumes 是成交量（手），需转为成交额（元）= vol * close * 100
        if len(result.volumes) >= 5 and len(result.closes) >= 5:
            amounts = result.volumes[-5:] * result.closes[-5:] * 100
            avg_amount = np.mean(amounts)
            if avg_amount < MIN_DAILY_AMOUNT:
                continue

        # --- 缠论状态检查 ---
        # 必须有买点信号
        if not result.buy_points:
            continue

        # 背驰质量检查
        valid_buy_points = []
        for bp in result.buy_points:
            # 如果是背驰类买点（一买），检查力度比
            if bp["type"] == "一买" and result.divergence:
                area_ratio = result.divergence.get("area_ratio", 1.0)
                if area_ratio >= PURE_DIVERGENCE_THRESHOLD:
                    continue  # 背驰力度不够，跳过
            valid_buy_points.append(bp)

        if not valid_buy_points:
            continue

        # 选最优买点
        best_bp = _pick_best_buy_point(valid_buy_points)

        # --- 构建输出 ---
        sector_name = sector_stocks.get(code, {}).get("sector", "") if sector_stocks else ""

        # 取最新中枢信息
        pivot_info = _get_pivot_info(result)

        target_pool.append({
            "code": code,
            "name": name,
            "buy_points": valid_buy_points,
            "best_buy_point": best_bp,
            "pivots": pivot_info,
            "trend_type": result.trend_type,
            "divergence": result.divergence,
            "closes": result.closes,
            "opens": result.opens,
            "highs": result.highs,
            "lows": result.lows,
            "dates": result.dates,
            "volumes": result.volumes,
            "fractals": result.fractals,
            "strokes": result.strokes,
            "segments": result.segments,
            "macd_hist": result.macd_hist,
            "sector": sector_name,
            "version": "pure",
        })

    # 按买点类型优先级排序（三买 > 二买 > 类二买 > 一买）
    bp_order = {"三买": 0, "二买": 1, "类二买": 2, "类二买待确认": 3, "一买": 4}
    target_pool.sort(key=lambda x: bp_order.get(x["best_buy_point"]["type"], 9))

    return target_pool


def screen_30min_pure(daily_pool, chan_results_30min):
    """
    纯净版30分钟精细确认。
    使用简化的30分钟信号确认（底分型、均线位置），
    而非完整缠论分析（30min数据通常不足以形成完整笔段中枢）。
    """
    min30_map = {}
    for r in chan_results_30min:
        if r is not None:
            min30_map[r.code] = r

    confirmed = []
    for stock in daily_pool:
        code = stock["code"]
        min30_result = min30_map.get(code)
        if min30_result is None:
            continue

        # 简化确认：检查30分钟是否有底分型或买点信号
        buy_points_30 = min30_result.buy_points if min30_result.buy_points else []

        # 没有标准买点时，用底分型辅助确认（需附加MACD金叉/底背驰条件）
        if not buy_points_30:
            if _has_macd_bullish_signal(min30_result):
                bottom_fractals = [f for f in min30_result.fractals if f.type == "bottom"]
                if bottom_fractals:
                    # 最近一个底分型
                    last_bottom = bottom_fractals[-1]
                    # 检查底分型价格是否在日线买点价格附近（±3%）
                    daily_bp_price = stock["best_buy_point"]["price"]
                    if abs(last_bottom.price - daily_bp_price) / daily_bp_price < 0.05:
                        buy_points_30 = [{
                            "type": "底分型确认",
                            "index": last_bottom.index,
                            "price": round(last_bottom.price, 2),
                            "date": str(min30_result.dates[last_bottom.index]) if last_bottom.index < len(min30_result.dates) else "",
                            "reason": "30分钟形成底分型+MACD金叉/底背驰确认",
                            "strength": "中",
                        }]

        if not buy_points_30:
            # 30分钟无标准买点也无底分型确认，仍允许通过但标注弱共振
            resonance = {"level": "弱", "reason": "30分钟无明确买点确认"}
        else:
            daily_bp_type = stock["best_buy_point"]["type"]
            resonance = _check_resonance(daily_bp_type, buy_points_30, stock, min30_result)

        stock["buy_points_30min"] = buy_points_30
        stock["resonance"] = resonance
        stock["result_30min"] = min30_result
        confirmed.append(stock)

    return confirmed


def _pick_best_buy_point(buy_points):
    """从多个买点中选最优的（三买 > 二买 > 类二买 > 一买）"""
    priority = {"三买": 0, "二买": 1, "类二买": 2, "类二买待确认": 3, "一买": 4}
    best = buy_points[0]
    for bp in buy_points[1:]:
        if priority.get(bp["type"], 9) < priority.get(best["type"], 9):
            best = bp
    return best


def _get_pivot_info(result):
    """提取中枢信息，优先使用笔中枢"""
    sp = result.stroke_pivots if result.stroke_pivots else result.pivots
    if not sp:
        return {"ZG": None, "ZD": None, "count": 0}
    last = sp[-1]
    zg = last["ZG"] if isinstance(last, dict) else last.ZG
    zd = last["ZD"] if isinstance(last, dict) else last.ZD
    return {"ZG": zg, "ZD": zd, "count": len(sp)}


def _check_resonance(daily_bp_type, bp_30_list, stock, min30_result):
    """
    检查日线和30分钟的区间套共振。
    返回: {"level": "强"|"中"|"弱", "reason": "..."}
    """
    bp_types_30 = [bp["type"] for bp in bp_30_list]

    # 同类型买点同时出现在两个级别 → 强共振
    if daily_bp_type in bp_types_30:
        return {"level": "强", "reason": f"日线{daily_bp_type} + 30分钟{daily_bp_type}共振"}

    # 30分钟有二买/三买配合日线一买 → 中共振
    if daily_bp_type == "一买" and any(t in bp_types_30 for t in ["二买", "三买"]):
        matched = [t for t in bp_types_30 if t in ["二买", "三买"]]
        return {"level": "中", "reason": f"日线一买 + 30分钟{','.join(matched)}确认"}

    # 30分钟有其他买点 → 弱共振
    if bp_types_30:
        return {"level": "弱", "reason": f"日线{daily_bp_type} + 30分钟{'/'.join(bp_types_30)}"}

    return {"level": "无", "reason": "30分钟无买点信号"}
