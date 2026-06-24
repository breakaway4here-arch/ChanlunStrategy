"""Chanlun structure diagnosis for stock review.

Extracts structured summaries from ChanResult objects produced by chan_engine.analyze().
Handles both daily and 30min timeframes. Code does factual extraction; LLM does interpretation.
"""
import numpy as np


def classify_price_position(close, pivot_zd, pivot_zg):
    """Classify current price relative to pivot zone.

    Returns one of: 中枢下方 / 中枢下沿附近 / 中枢内 / 中枢上沿附近 / 中枢上方 / 无中枢
    """
    if pivot_zd is None or pivot_zg is None:
        return "无中枢"

    margin = (pivot_zg - pivot_zd) * 0.1  # 10% of pivot width as "near" zone

    if close < pivot_zd - margin:
        return "中枢下方"
    elif close <= pivot_zd + margin:
        return "中枢下沿附近"
    elif close < pivot_zg - margin:
        return "中枢内"
    elif close <= pivot_zg + margin:
        return "中枢上沿附近"
    else:
        return "中枢上方"


def _extract_pivot_info(pivots):
    """Extract pivot zones from ChanResult pivots list."""
    result = []
    for p in pivots:
        if isinstance(p, dict):
            zd = p.get('ZD', 0)
            zg = p.get('ZG', 0)
            start_idx = p.get('start_idx', 0)
            end_idx = p.get('end_idx', 0)
        else:
            zd = getattr(p, 'ZD', 0)
            zg = getattr(p, 'ZG', 0)
            start_idx = getattr(p, 'start_idx', 0)
            end_idx = getattr(p, 'end_idx', 0)
        result.append({
            "ZD": round(float(zd), 2),
            "ZG": round(float(zg), 2),
            "start_idx": int(start_idx),
            "end_idx": int(end_idx),
        })
    return result


def _extract_buy_points(buy_points):
    """Extract simplified buy point summaries."""
    return [{
        "type": bp.get("type", bp["type"] if isinstance(bp, dict) else str(bp)),
        "price": round(float(bp.get("price", 0)), 2),
        "date": str(bp.get("date", "")),
        "reason": str(bp.get("reason", "")),
        "strength": str(bp.get("strength", "")),
    } for bp in (buy_points or [])]


def _extract_sell_points(sell_points):
    """Extract simplified sell point summaries."""
    return [{
        "type": sp.get("type", ""),
        "price": round(float(sp.get("price", 0)), 2),
        "date": str(sp.get("date", "")),
        "reason": str(sp.get("reason", "")),
        "strength": str(sp.get("strength", "")),
    } for sp in (sell_points or [])]


def extract_daily_structure(chan_result):
    """Extract daily chanlun structure from ChanResult.

    Returns a dict with pivot info, buy/sell points, trend type, position, etc.
    Returns degraded status dict if data insufficient.
    """
    if chan_result is None:
        return {"status": "data_insufficient", "code": "", "trend_type": ""}

    r = chan_result
    closes = r.closes if hasattr(r, 'closes') else np.array([])
    close_price = round(float(closes[-1]), 2) if len(closes) > 0 else None

    pivots = _extract_pivot_info(r.pivots if hasattr(r, 'pivots') else [])

    # Determine current pivot
    current_pivot = pivots[-1] if pivots else None
    zd = current_pivot["ZD"] if current_pivot else None
    zg = current_pivot["ZG"] if current_pivot else None

    position = classify_price_position(close_price, zd, zg) if close_price is not None else "无中枢"

    # Divergence info
    div = r.divergence if hasattr(r, 'divergence') else None
    divergence_info = None
    if div:
        divergence_info = {
            "type": div.get("type", ""),
            "is_divergence": div.get("is_divergence", False),
            "area_ratio": div.get("area_ratio", 1.0),
        }

    return {
        "status": "ok",
        "code": r.code if hasattr(r, 'code') else "",
        "name": r.name if hasattr(r, 'name') else "",
        "close": close_price,
        "trend_type": r.trend_type if hasattr(r, 'trend_type') else "",
        "pivots": pivots,
        "current_pivot": {"ZD": zd, "ZG": zg} if current_pivot else None,
        "position": position,
        "buy_points": _extract_buy_points(r.buy_points if hasattr(r, 'buy_points') else []),
        "sell_points": _extract_sell_points(r.sell_points if hasattr(r, 'sell_points') else []),
        "divergence": divergence_info,
        "kline_count": len(closes),
    }


def extract_30min_structure(chan_result):
    """Extract 30min chanlun structure from ChanResult.

    Returns a dict with 30min-specific info. Returns degraded status if data insufficient.
    """
    if chan_result is None:
        return {"status": "data_insufficient", "code": "", "trend_type": ""}

    r = chan_result
    closes = r.closes if hasattr(r, 'closes') else np.array([])
    close_price = round(float(closes[-1]), 2) if len(closes) > 0 else None

    pivots = _extract_pivot_info(r.pivots if hasattr(r, 'pivots') else [])

    current_pivot = pivots[-1] if pivots else None
    zd = current_pivot["ZD"] if current_pivot else None
    zg = current_pivot["ZG"] if current_pivot else None

    position = classify_price_position(close_price, zd, zg) if close_price is not None else "无中枢"

    div = r.divergence if hasattr(r, 'divergence') else None
    divergence_info = None
    if div:
        divergence_info = {
            "type": div.get("type", ""),
            "is_divergence": div.get("is_divergence", False),
        }

    # Check EMA5 recovery (for 30min confirmation signals)
    ema5 = None
    if len(closes) >= 5:
        alpha = 2.0 / 6.0
        ema_vals = [closes[0]]
        for i in range(1, len(closes)):
            ema_vals.append(alpha * closes[i] + (1 - alpha) * ema_vals[-1])
        ema5 = round(float(ema_vals[-1]), 2)

    above_ema5 = close_price > ema5 if close_price is not None and ema5 is not None else None

    return {
        "status": "ok",
        "code": r.code if hasattr(r, 'code') else "",
        "close": close_price,
        "trend_type": r.trend_type if hasattr(r, 'trend_type') else "",
        "pivots": pivots,
        "current_pivot": {"ZD": zd, "ZG": zg} if current_pivot else None,
        "position": position,
        "buy_points": _extract_buy_points(r.buy_points if hasattr(r, 'buy_points') else []),
        "sell_points": _extract_sell_points(r.sell_points if hasattr(r, 'sell_points') else []),
        "divergence": divergence_info,
        "ema5": ema5,
        "above_ema5": above_ema5,
        "kline_count": len(closes),
    }


def build_diagnosis(code, name, daily_result, min30_result):
    """Build a complete diagnosis dict from daily and 30min ChanResults."""
    daily = extract_daily_structure(daily_result)
    min30 = extract_30min_structure(min30_result)

    return {
        "code": code,
        "name": name,
        "daily": daily,
        "min30": min30,
    }
