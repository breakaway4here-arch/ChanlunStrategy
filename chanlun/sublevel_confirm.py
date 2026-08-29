"""
30-minute sub-level confirmation classifier.

For each daily reference signal, checks whether the 30min chart provides
confirming evidence to upgrade it to a candidate recommendation.
"""

import numpy as np
from config import ENABLE_RELAXED_30MIN_CONFIRM
from .signal_policy import is_recommendable_buy

NEAR_PRICE_PCT = 0.03
RECENT_30MIN_BARS = 8
STRONG_STARTUP_BUY_POINT_TYPES = frozenset({
    "二买",
    "二买候选",
    "三买",
    "三买候选",
})


def build_30min_confirmation_evidence(min30_result):
    """Build JSON-safe facts used by 30-minute confirmation policies.

    This function deliberately separates lagging state (for example EMA5 above
    EMA10) from a fresh confirmation event.  Missing inputs fail closed so a
    partially populated result cannot be promoted by accident.
    """
    evidence = {
        "schema_version": 1,
        "sufficient_bars": False,
        "ema_bullish_alignment": False,
        "close_above_ema5": False,
        "ema5_rising_bars": 0,
        "recent_peak_drawdown_pct": None,
        "macd_hist_direction": "unavailable",
        "ema5_reclaim": False,
        "stop_fall": False,
        "buy_point": None,
        "fresh_yang_pattern": None,
        "recovery_bundle_match": False,
    }
    if min30_result is None:
        return evidence

    closes = _finite_array(getattr(min30_result, "closes", None))
    if closes is None or len(closes) < 5:
        return evidence

    from .chan_engine import ema

    ema5 = np.asarray(ema(closes, 5), dtype=float)
    ema10 = np.asarray(ema(closes, 10), dtype=float)
    evidence["sufficient_bars"] = True
    if len(ema5) == len(closes) and np.isfinite(ema5[-1]):
        evidence["close_above_ema5"] = bool(closes[-1] > ema5[-1])
        evidence["ema5_rising_bars"] = _count_rising_tail(ema5)
        evidence["ema5_reclaim"] = _has_recent_ema5_reclaim(closes, ema5)
        if len(ema10) == len(closes) and np.isfinite(ema10[-1]):
            evidence["ema_bullish_alignment"] = bool(ema5[-1] > ema10[-1])

    highs = _finite_array(getattr(min30_result, "highs", None))
    peak_values = highs if highs is not None and len(highs) == len(closes) else closes
    recent_peak = float(np.max(peak_values[-RECENT_30MIN_BARS:]))
    if recent_peak > 0:
        drawdown = max(0.0, (recent_peak - float(closes[-1])) / recent_peak * 100.0)
        evidence["recent_peak_drawdown_pct"] = round(drawdown, 6)

    evidence["macd_hist_direction"] = _macd_hist_direction(
        getattr(min30_result, "macd_hist", None)
    )
    evidence["stop_fall"] = _check_stop_fall_bars(min30_result)
    evidence["buy_point"] = _latest_recommendable_buy_point(
        min30_result, len(closes)
    )
    evidence["fresh_yang_pattern"] = _latest_yang_pattern(min30_result)

    # Initial recovery bundle.  Historical replay may tighten constants, but
    # it may never fall back to EMA alignment as a standalone confirmation.
    evidence["recovery_bundle_match"] = bool(
        evidence["close_above_ema5"]
        and evidence["ema5_rising_bars"] >= 2
        and evidence["stop_fall"]
        and evidence["macd_hist_direction"] == "improving"
    )
    return evidence


def _finite_array(values):
    if values is None:
        return None
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        return None
    if array.ndim != 1 or len(array) == 0 or not np.all(np.isfinite(array)):
        return None
    return array


def _count_rising_tail(values):
    count = 0
    for index in range(len(values) - 1, 0, -1):
        if not np.isfinite(values[index]) or not np.isfinite(values[index - 1]):
            break
        if float(values[index]) <= float(values[index - 1]):
            break
        count += 1
    return count


def _has_recent_ema5_reclaim(closes, ema5):
    start = max(1, len(closes) - 3)
    for index in range(start, len(closes)):
        if not np.isfinite(ema5[index]) or not np.isfinite(ema5[index - 1]):
            continue
        if closes[index] > ema5[index] and closes[index - 1] <= ema5[index - 1]:
            return True
    return False


def _macd_hist_direction(values):
    if values is None:
        return "unavailable"
    try:
        hist = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        return "unavailable"
    if hist.ndim != 1 or len(hist) < 3 or not np.all(np.isfinite(hist[-3:])):
        return "unavailable"
    recent = hist[-3:]
    scale = max(1.0, float(np.max(np.abs(recent))))
    tolerance = scale * 1e-6
    if recent[-1] > recent[-2] + tolerance and recent[-2] >= recent[-3] - tolerance:
        return "improving"
    if recent[-1] < recent[-2] - tolerance and recent[-2] <= recent[-3] + tolerance:
        return "weakening"
    return "mixed"


def _latest_recommendable_buy_point(min30_result, total_bars):
    recent_start = max(0, int(total_bars) - RECENT_30MIN_BARS)
    for bp in reversed(getattr(min30_result, "buy_points", None) or []):
        try:
            signal_index = int(bp.get("index"))
        except (TypeError, ValueError):
            continue
        if (
            recent_start <= signal_index < int(total_bars)
            and str(bp.get("type") or "") in STRONG_STARTUP_BUY_POINT_TYPES
            and is_recommendable_buy(bp)
        ):
            return str(bp.get("type"))
    return None


def _latest_yang_pattern(min30_result):
    closes = _finite_array(getattr(min30_result, "closes", None))
    opens = _finite_array(getattr(min30_result, "opens", None))
    if closes is None or opens is None or len(closes) != len(opens):
        return None
    if len(closes) >= 3:
        if closes[-3] > opens[-3] and closes[-2] < opens[-2] and closes[-1] > opens[-1]:
            return "two_yang_one_yin"
    if len(closes) >= 4:
        if (
            closes[-4] > opens[-4]
            and closes[-3] < opens[-3]
            and closes[-2] < opens[-2]
            and closes[-1] > opens[-1]
        ):
            return "two_yang_two_yin"
    return None


def classify_30min_confirmation(daily_stock, source_bp, min30_result):
    """Classify 30min confirmation strength for a daily reference buy point.

    Args:
        daily_stock: dict with daily pool entry (has pivots, closes, etc.)
        source_bp: dict, the daily reference buy point being evaluated
        min30_result: ChanResult from 30min analysis

    Returns:
        dict with keys: confirmed (bool), level (强|中|弱|无),
                        signals (list[str]), reason (str)
    """
    if min30_result is None:
        return _no_confirm("30分钟数据缺失")

    signals = []
    reasons = []

    # 1. 30min bottom divergence
    div = min30_result.divergence
    if div and div.get("is_divergence") and "底背驰" in div.get("type", ""):
        signals.append("30min底背驰")
        reasons.append("30分钟底背驰")

    # 2. 30min formal/recommendable buy point
    has_30min_buy = False
    for bp in (min30_result.buy_points or []):
        if is_recommendable_buy(bp):
            has_30min_buy = True
            signals.append(f"30min{bp['type']}")
            reasons.append(f"30分钟{bp['type']}信号")
            break

    # 3. Bottom fractal + MACD golden cross
    has_fractal_macd = _check_bottom_fractal_macd(min30_result)
    if has_fractal_macd:
        signals.append("30min底分型")
        reasons.append("30分钟底分型+MACD金叉")

    # 4. Key level not broken
    key_level_ok = _check_key_level(daily_stock, source_bp, min30_result)
    if key_level_ok:
        signals.append("关键位不破")
        reasons.append("30分钟回拉不破日线关键位")

    # 5. EMA5 reclaim
    ema5_reclaim = _check_ema5_reclaim(min30_result)
    if ema5_reclaim:
        signals.append("EMA5收复")
        reasons.append("30分钟收盘重新站上EMA5")

    # 6. Stop-fall bar structure
    stop_fall_bars = _check_stop_fall_bars(min30_result)
    if stop_fall_bars:
        signals.append("止跌结构")
        reasons.append("30分钟出现止跌K线结构")

    # Determine strength
    if "30min底背驰" in signals or has_30min_buy:
        level = "强"
        confirmed = True
    elif ENABLE_RELAXED_30MIN_CONFIRM:
        if has_fractal_macd or (key_level_ok and ema5_reclaim):
            level = "中"
            confirmed = True
        elif key_level_ok or ema5_reclaim:
            level = "弱"
            confirmed = False
        else:
            level = "无"
            confirmed = False
    else:
        # Old rule: 底分型 + MACD金叉 + 关键位不破 all required
        if has_fractal_macd and key_level_ok:
            level = "中"
            confirmed = True
        elif key_level_ok:
            level = "弱"
            confirmed = False
        else:
            level = "无"
            confirmed = False

    return {
        "confirmed": confirmed,
        "level": level,
        "signals": signals,
        "reason": " + ".join(reasons) if reasons else "30分钟无确认信号",
    }


def _no_confirm(reason):
    return {"confirmed": False, "level": "无", "signals": [], "reason": reason}


def _check_bottom_fractal_macd(min30_result):
    """Check for recent bottom fractal + MACD golden cross within 3 bars."""
    fractals = min30_result.fractals or []
    bottoms = [f for f in fractals if f.type == "bottom"]
    if not bottoms:
        return False

    last_bottom = bottoms[-1]
    dif = min30_result.macd_dif
    dea = min30_result.macd_dea
    if dif is None or dea is None or len(dif) < 3:
        return False

    n = len(dif)
    # Check MACD golden cross within recent 3 bars after the fractal
    for i in range(max(last_bottom.index, n - 3), n):
        if i > 0 and dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
            return True
    return False


def _check_key_level(daily_stock, source_bp, min30_result):
    """Check if recent 30min lows respect the daily key level for this source_bp type."""
    src_type = source_bp.get("type", "")
    lows_30 = min30_result.lows
    if lows_30 is None or len(lows_30) < RECENT_30MIN_BARS:
        return False

    recent_low = float(np.min(lows_30[-RECENT_30MIN_BARS:]))

    if src_type == "二买待确认":
        # Daily first-buy price is the key level
        key_price = _find_first_buy_price(daily_stock)
        if key_price is None:
            return False
        return recent_low > key_price

    elif src_type == "中枢震荡低吸参考":
        pivots = daily_stock.get("pivots", {})
        zd = pivots.get("ZD")
        if zd is None:
            return False
        return recent_low >= zd * (1 - NEAR_PRICE_PCT)

    elif src_type == "盘整背驰参考":
        bp_price = source_bp.get("price", 0)
        if bp_price <= 0:
            return False
        return recent_low >= bp_price * (1 - NEAR_PRICE_PCT)

    elif src_type == "三买待确认":
        pivots = daily_stock.get("pivots", {})
        zg = pivots.get("ZG")
        if zg is None:
            return False
        return recent_low > zg

    elif src_type == "swing底背驰候选种子":
        bp_price = source_bp.get("price", 0)
        if bp_price <= 0:
            return False
        return recent_low >= bp_price * (1 - NEAR_PRICE_PCT)

    return False


def _find_first_buy_price(daily_stock):
    """Find the 一买 price from daily stock's buy points or best_buy_point."""
    for bp in daily_stock.get("buy_points", []):
        if bp.get("type") == "一买":
            return bp.get("price")
    best = daily_stock.get("best_buy_point", {})
    if best.get("type") == "一买":
        return best.get("price")
    return None


def _check_ema5_reclaim(min30_result):
    """Check if close reclaimed above 5-period approximate EMA."""
    closes = min30_result.closes
    if closes is None or len(closes) < 6:
        return False
    recent = np.asarray(closes[-5:], dtype=float)
    ema5 = float(np.mean(recent))
    latest_close = float(closes[-1])
    prev_close = float(closes[-2])
    return latest_close > ema5 and latest_close >= prev_close


def _check_stop_fall_bars(min30_result):
    """Check for stop-fall K-line structure: higher lows + repair closes."""
    lows = _finite_array(getattr(min30_result, "lows", None))
    closes = _finite_array(getattr(min30_result, "closes", None))
    opens = _finite_array(getattr(min30_result, "opens", None))
    if lows is None or closes is None or opens is None:
        return False
    if len(lows) != len(closes) or len(opens) != len(closes) or len(closes) < 4:
        return False

    higher_lows = lows[-1] >= lows[-2] >= min(lows[-4:-2])
    two_repair_closes = closes[-1] >= opens[-1] and closes[-2] >= opens[-2]
    close_repair = closes[-1] > closes[-3]
    return bool(higher_lows and two_repair_closes and close_repair)
