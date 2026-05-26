"""
融合版筛选器 — 缠论 + 现有JoinQuant策略验证有效的想法。

在纯净版基础上叠加:
1. MA5>MA10>MA20 多头排列（一买除外）
2. 大盘趋势双参数（上证>MA50 → 强/弱）
3. 三买额外确认：次级别回踩不破ZG + 站上MA5
4. 止损/止盈目标
5. 活跃度标记
"""

import numpy as np
from config import (
    FUSION_DIVERGENCE_TREND, FUSION_DIVERGENCE_WEAK,
    FUSION_BUY_POINTS_TREND, FUSION_BUY_POINTS_WEAK,
    FUSION_TRAILING_TIERS, FUSION_HARD_STOP,
    FUSION_ACTIVE_DAYS, FUSION_ACTIVE_THRESHOLD,
    MA_SHORT, MA_MID, MA_LONG, MA_TREND,
    MIN_DAILY_AMOUNT, LIMIT_UP_THRESHOLD, LIMIT_DOWN_THRESHOLD,
)
from .chan_engine import ema
from .data_fetcher import is_st_stock
from .screener_pure import _get_pivot_info, _has_macd_bullish_signal


def is_ma_bullish(closes):
    """检查 EMA5 > EMA10 > EMA20 多头排列"""
    if len(closes) < MA_LONG + 1:
        return False
    ema5 = float(ema(closes, MA_SHORT)[-1])
    ema10 = float(ema(closes, MA_MID)[-1])
    ema20 = float(ema(closes, MA_LONG)[-1])
    if np.isnan(ema5) or np.isnan(ema10) or np.isnan(ema20):
        return False
    return ema5 > ema10 > ema20


def is_market_strong(sh_closes):
    """上证 > EMA50 → 强趋势"""
    if sh_closes is None or len(sh_closes) < MA_TREND:
        return False
    ema50 = float(ema(sh_closes, MA_TREND)[-1])
    if np.isnan(ema50):
        return False
    return sh_closes[-1] > ema50


def calc_trailing_targets(entry_price):
    """计算移动止盈三档目标价"""
    targets = []
    for tier_pct in FUSION_TRAILING_TIERS:
        targets.append({
            "pct": tier_pct,
            "price": round(entry_price * (1 + tier_pct / 100), 2),
        })
    return targets


def check_active_flag(closes):
    """检查近N日是否有单日涨>阈值，标记活跃"""
    if len(closes) < FUSION_ACTIVE_DAYS + 1:
        return False
    recent = closes[-(FUSION_ACTIVE_DAYS + 1):]
    for i in range(1, len(recent)):
        if recent[i - 1] > 0:
            chg = (recent[i] - recent[i - 1]) / recent[i - 1] * 100
            if chg > FUSION_ACTIVE_THRESHOLD:
                return True
    return False


def screen_daily_fusion(chan_results, sh_closes, sector_stocks=None):
    """
    融合版日线初筛。

    参数:
        chan_results: [ChanResult, ...]
        sh_closes: 上证收盘价数组
        sector_stocks: dict {code: {"sector": ..., "change_pct": ...}}

    返回:
        目标池: [dict, ...]
    """
    market_strong = is_market_strong(sh_closes)
    div_threshold = FUSION_DIVERGENCE_TREND if market_strong else FUSION_DIVERGENCE_WEAK
    preferred_bp = FUSION_BUY_POINTS_TREND if market_strong else FUSION_BUY_POINTS_WEAK

    trend_label = "强趋势" if market_strong else "弱市"
    print(f"  大盘状态: {trend_label}, 背驰阈值={div_threshold}, 优先买卖点={preferred_bp}")

    target_pool = []

    for result in chan_results:
        if result is None:
            continue

        code = result.code
        name = result.name
        closes = result.closes

        # --- 基础过滤 ---
        if is_st_stock(name):
            continue
        if len(closes) < MA_LONG + 1:
            continue

        # 涨跌停
        if len(closes) >= 2 and closes[-2] > 0:
            change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100
            if change_pct >= LIMIT_UP_THRESHOLD or change_pct <= LIMIT_DOWN_THRESHOLD:
                continue

        # 量能：成交量（手）→ 成交额（元）
        if len(result.volumes) >= 5 and len(closes) >= 5:
            amounts = result.volumes[-5:] * closes[-5:] * 100
            if np.mean(amounts) < MIN_DAILY_AMOUNT:
                continue

        # --- 缠论买点 ---
        if not result.buy_points:
            continue

        # 过滤不可选类型
        selectable_bp = [bp for bp in result.buy_points
                         if bp["type"] not in ("三买已错过", "中枢震荡低吸参考",
                                                "swing底背驰参考", "盘整背驰参考",
                                                "二买待确认")]
        if not selectable_bp:
            continue

        # MA 多头检查（一买除外）
        ma_bullish = is_ma_bullish(closes)

        # 背驰质量检查（使用双参数阈值）
        valid_buy_points = []
        for bp in selectable_bp:
            if bp["type"] == "一买":
                # 一买不需要MA多头
                if result.divergence:
                    area_ratio = result.divergence.get("area_ratio", 1.0)
                    if area_ratio >= div_threshold:
                        continue
                valid_buy_points.append(bp)
            elif bp["type"] in ("二买", "三买"):
                # 需要一个条件：MA多头 或 是优先买卖点
                if ma_bullish or bp["type"] in preferred_bp:
                    valid_buy_points.append(bp)
            else:
                valid_buy_points.append(bp)

        if not valid_buy_points:
            continue

        # 选最优买点
        best_bp = _pick_best_fusion(valid_buy_points, preferred_bp)

        # 三买特殊确认：需要MA多头
        if best_bp["type"] == "三买" and not ma_bullish:
            continue

        # --- 止损/止盈计算 ---
        entry_price = best_bp["price"]
        stop_loss = round(entry_price * (1 + FUSION_HARD_STOP / 100), 2)
        trailing_targets = calc_trailing_targets(entry_price)

        # --- 活跃度标记 ---
        is_active = check_active_flag(closes)

        # --- 构建输出 ---
        sector_name = sector_stocks.get(code, {}).get("sector", "") if sector_stocks else ""

        pivot_info = _get_pivot_info(result)

        target_pool.append({
            "code": code,
            "name": name,
            "buy_points": valid_buy_points,
            "best_buy_point": best_bp,
            "pivots": pivot_info,
            "trend_type": result.trend_type,
            "divergence": result.divergence,
            "closes": closes,
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
            "ma_bullish": ma_bullish,
            "stop_loss": stop_loss,
            "stop_loss_pct": FUSION_HARD_STOP,
            "trailing_targets": trailing_targets,
            "is_active": is_active,
            "market_trend": trend_label,
            "version": "fusion",
        })

    # 排序：优先买卖点 > MA多头 > 买点优先级
    bp_order = {"三买": 0, "二买": 1, "一买": 2}

    def sort_key(x):
        bp = x["best_buy_point"]
        is_preferred = 0 if bp["type"] in preferred_bp else 1
        bp_rank = bp_order.get(bp["type"], 9)
        ma_boost = 0 if x["ma_bullish"] else 1
        return (is_preferred, ma_boost, bp_rank)

    target_pool.sort(key=sort_key)
    return target_pool


def screen_30min_fusion(daily_pool, chan_results_30min):
    """
    融合版30分钟精细确认。
    使用简化的30分钟信号确认。
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

        buy_points_30 = min30_result.buy_points if min30_result.buy_points else []

        # 没有标准买点时，用底分型辅助确认（需附加MACD金叉/底背驰条件）
        if not buy_points_30:
            if _has_macd_bullish_signal(min30_result):
                bottom_fractals = [f for f in min30_result.fractals if f.type == "bottom"]
                if bottom_fractals:
                    last_bottom = bottom_fractals[-1]
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

        daily_bp_type = stock["best_buy_point"]["type"]

        # 三买特殊确认
        if daily_bp_type == "三买":
            if not _confirm_third_buy_30min(stock, min30_result):
                continue

        if not buy_points_30:
            resonance = {"level": "弱", "reason": "30分钟无明确买点确认"}
        else:
            resonance = _check_resonance_fusion(daily_bp_type, buy_points_30, stock, min30_result)

        stock["buy_points_30min"] = buy_points_30
        stock["resonance"] = resonance
        stock["result_30min"] = min30_result
        confirmed.append(stock)

    return confirmed


def _confirm_third_buy_30min(stock, min30_result):
    """
    三买30分钟确认：
    1. 30分钟回抽低点不破日线中枢ZG
    2. 回抽后站上MA5
    """
    zg = stock["pivots"].get("ZG")
    if zg is None:
        return False  # 无中枢ZG无法确认三买

    closes_30 = min30_result.closes
    lows_30 = min30_result.lows

    if len(closes_30) < 5:
        return False

    # 检查30分钟回抽最低点 > ZG
    if len(lows_30) >= 5:
        recent_low = np.min(lows_30[-5:])
        if recent_low <= zg:
            return False  # 回抽跌破ZG，三买不成立

    # 检查站上EMA5
    ema5_30 = float(ema(closes_30, 5)[-1]) if len(closes_30) >= 5 else closes_30[-1]
    if closes_30[-1] < ema5_30:
        return False

    return True


def _check_resonance_fusion(daily_bp_type, bp_30_list, stock, min30_result):
    """融合版区间套确认（与纯净版相同逻辑）"""
    bp_types_30 = [bp["type"] for bp in bp_30_list]

    if daily_bp_type in bp_types_30:
        return {"level": "强", "reason": f"日线{daily_bp_type} + 30分钟{daily_bp_type}共振"}
    if daily_bp_type == "一买" and any(t in bp_types_30 for t in ["二买", "三买"]):
        matched = [t for t in bp_types_30 if t in ["二买", "三买"]]
        return {"level": "中", "reason": f"日线一买 + 30分钟{','.join(matched)}确认"}
    if bp_types_30:
        return {"level": "弱", "reason": f"日线{daily_bp_type} + 30分钟{'/'.join(bp_types_30)}"}
    return {"level": "无", "reason": "30分钟无买点信号"}


def _pick_best_fusion(buy_points, preferred_types):
    """融合版选最优买点（优先考虑市场偏好类型）"""
    # 先找 preferred 类型
    for bp in buy_points:
        if bp["type"] in preferred_types:
            # 同类型选 strength 更强的
            best = bp
            for b2 in buy_points:
                if b2["type"] == bp["type"] and b2.get("strength") == "强":
                    best = b2
            return best

    # 按优先级选（三买 > 二买 > 一买）
    priority = {"三买": 0, "二买": 1, "一买": 2}
    best = buy_points[0]
    for bp in buy_points[1:]:
        if priority.get(bp["type"], 9) < priority.get(best["type"], 9):
            best = bp
    return best
