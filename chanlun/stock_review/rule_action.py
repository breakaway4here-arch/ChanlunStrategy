"""Rule-based action engine for stock review.

Generates structured action recommendations (HOLD/WATCH/REDUCE/STOP/ADD_ON_CONFIRM/AVOID_ADD)
based on chanlun structure facts. LLM can explain or dispute, but code determines the base action.
"""

ACTION_PRIORITY = {
    "STOP": 0,
    "REDUCE": 1,
    "WATCH": 2,
    "HOLD": 3,
    "ADD_ON_CONFIRM": 4,
    "AVOID_ADD": 5,
}

ALL_ACTIONS = list(ACTION_PRIORITY.keys())


def generate_rule_action(daily_structure, min30_structure, holding):
    """Generate rule-based action recommendation.

    Args:
        daily_structure: dict from extract_daily_structure()
        min30_structure: dict from extract_30min_structure()
        holding: dict-like with code, name, cost_price, quantity

    Returns:
        dict with action, confidence, reasons, conditions
    """
    close = daily_structure.get("close")
    position = daily_structure.get("position", "")
    daily_div = daily_structure.get("divergence")
    daily_sells = daily_structure.get("sell_points", [])
    daily_buys = daily_structure.get("buy_points", [])
    daily_pivot = daily_structure.get("current_pivot") or {}

    min30_sells = min30_structure.get("sell_points", [])
    min30_buys = min30_structure.get("buy_points", [])
    min30_position = min30_structure.get("position", "")
    above_ema5 = min30_structure.get("above_ema5")

    cost_price = holding.get("cost_price")
    has_cost = cost_price is not None and cost_price > 0

    zd = daily_pivot.get("ZD")
    zg = daily_pivot.get("ZG")

    # ── Risk triggers ──
    below_zd = position == "中枢下方" if zd else False
    top_divergence = bool(daily_div and daily_div.get("is_divergence") and "顶背驰" in daily_div.get("type", ""))
    has_sell_point = len(daily_sells) > 0 or len(min30_sells) > 0
    volume_drop_risk = False  # placeholder for future volume analysis
    below_cost_significant = False
    if has_cost and close is not None:
        pnl_pct = (close - cost_price) / cost_price * 100
        below_cost_significant = pnl_pct < -8  # more than 8% loss

    min30_has_buy = len(min30_buys) > 0
    min30_below_zd = min30_position == "中枢下方"
    daily_has_buy = len(daily_buys) > 0

    # ── Determine action ──
    action = "HOLD"
    confidence = "medium"
    reasons = []

    if below_cost_significant:
        action = "STOP"
        confidence = "high"
        reasons.append(f"跌破成本价超过8%，当前{close}，成本{cost_price}")
    elif below_zd:
        if has_sell_point or top_divergence:
            action = "STOP"
            confidence = "high"
            reasons.append(f"跌破中枢下沿{zd}且出现卖点/顶背驰风险")
        else:
            action = "REDUCE"
            confidence = "medium"
            reasons.append(f"跌破中枢下沿{zd}，建议减仓观察")
    elif top_divergence:
        action = "REDUCE"
        confidence = "medium"
        reasons.append("出现顶背驰信号，上涨力度衰竭")
    elif has_sell_point:
        action = "WATCH"
        confidence = "medium"
        reasons.append("存在卖点信号，需要密切关注")
    elif min30_has_buy and not daily_has_buy:
        action = "ADD_ON_CONFIRM"
        confidence = "low"
        reasons.append("30min出现买点但日线未确认，等待日线确认后再加仓")
    elif min30_below_zd:
        action = "WATCH"
        confidence = "medium"
        reasons.append("30min级别跌破中枢下沿，关注是否传导到日线")
    else:
        action = "HOLD"
        confidence = "medium"
        reasons.append("日线处于中枢内，未见明确卖点")

    # ── Build conditions ──
    hold_condition = ""
    add_condition = ""
    reduce_condition = ""
    stop_condition = ""
    invalidated_by = []

    if zd:
        hold_condition = f"不跌破日线中枢ZD({zd})"
        invalidated_by.append(f"跌破ZD({zd})")
        reduce_condition = f"放量跌破ZD({zd})或出现30min顶背驰"

    if zg:
        add_condition = f"30min底分型确认且收复EMA5，不破ZD({zd})" if zd else "30min底分型确认且收复EMA5"

    if has_cost:
        stop_condition = f"跌破成本价{cost_price}且跌破日线中枢下沿"
    elif zd:
        stop_condition = f"跌破日线中枢下沿ZD({zd})"
    else:
        stop_condition = "跌破关键支撑位"

    if top_divergence:
        invalidated_by.append("顶背驰确认")

    if action == "WATCH":
        invalidated_by.append("放量长阴")

    return {
        "action": action,
        "confidence": confidence,
        "primary_reason": "；".join(reasons) if reasons else "日线处于中枢内，未见明确卖点",
        "hold_condition": hold_condition or "维持当前仓位",
        "add_condition": add_condition or "等待30min确认信号",
        "reduce_condition": reduce_condition or "出现卖点或跌破关键位",
        "stop_condition": stop_condition,
        "invalidated_by": invalidated_by or ["跌破关键位"],
    }
