"""Luojie pool: hardcoded national-team themes + 15min lifeline setup."""

import numpy as np


DEFAULT_TOP_N = 30
MA_SHORT = 13
MA_MID = 77
MA_LIFE_A = 155
MA_LIFE_B = 177
BREAK_BUFFER_PCT = 0.3
RECOVERY_WINDOW_BARS = 5
PULLBACK_WINDOW_BARS = 8
PULLBACK_TOLERANCE_PCT = 1.0
GOLDEN_CROSS_LOOKBACK = 20


LUOJIE_THEMES = {
    "六网": {
        "水网": ["水网", "水利", "水务", "节水", "管网", "供水", "排水"],
        "新型电网": ["新型电网", "智能电网", "电网", "特高压", "输变电", "电力设备", "储能"],
        "算力网": ["算力", "数据中心", "IDC", "服务器", "液冷", "云计算"],
        "新一代通信网": ["通信", "5G", "6G", "光通信", "光模块", "光纤", "运营商"],
        "城市地下管网": ["地下管网", "城市管网", "管材", "燃气", "排水", "环保"],
        "物流网": ["物流", "仓储", "航运", "铁路", "公路", "快递", "供应链"],
    },
    "质量层": {
        "高ROE": ["高ROE"],
        "高自由现金流": ["自由现金流"],
        "分红稳定": ["分红"],
        "毛利率稳定": ["毛利率"],
        "龙头市占率高": ["龙头", "市占率"],
    },
    "赛道层": {
        "光模块": ["光模块", "光通信", "光迅", "中际", "新易盛", "天孚"],
        "算力": ["算力", "服务器", "数据中心", "IDC", "液冷", "云计算"],
        "芯片": ["芯片", "半导体", "集成电路", "存储", "先进封装"],
        "运营商": ["运营商", "中国移动", "中国电信", "中国联通", "通信服务"],
        "IDC": ["IDC", "数据中心"],
        "工业互联网": ["工业互联网", "工业软件", "智能制造"],
    },
    "数字货币": {
        "移动支付": ["移动支付", "支付"],
        "金融IT": ["金融IT", "金融科技", "软件开发", "银行IT"],
        "密码安全": ["密码", "网络安全", "信息安全", "安全"],
        "终端设备": ["终端设备", "POS", "智能终端"],
        "清算支付链路": ["清算", "支付链路", "跨境支付"],
    },
}


def match_luojie_themes(stock):
    """Match stock name/sector/concept fields to hardcoded LuoJie themes."""
    haystack = " ".join(str(stock.get(k, "")) for k in (
        "name", "sector", "industry", "concept", "concepts", "theme", "themes"
    ))
    matched = {}
    for category, themes in LUOJIE_THEMES.items():
        for theme, keywords in themes.items():
            if any(k and k in haystack for k in keywords):
                matched.setdefault(category, []).append(theme)
    return matched


def prefilter_luojie_theme_candidates(stocks):
    """Keep stocks with at least one hardcoded policy-theme match."""
    result = []
    for stock in stocks or []:
        themes = match_luojie_themes(stock)
        if not themes:
            continue
        s = dict(stock)
        s["luojie_themes"] = themes
        result.append(s)
    return result


def build_luojie_pool(stocks, min15_results, top_n=DEFAULT_TOP_N):
    """Build LuoJie pool from 15min ChanResult objects."""
    stock_map = {s.get("code"): s for s in (stocks or [])}
    result_map = {r.code: r for r in (min15_results or []) if r is not None}
    diagnostics = {
        "input": len(stocks or []),
        "theme_candidates": 0,
        "with_15min": 0,
        "dropped_no_theme": 0,
        "dropped_no_15min": 0,
        "dropped_insufficient_bars": 0,
        "dropped_lifeline_break": 0,
        "dropped_macd_below_zero": 0,
        "dropped_77_break_timeout": 0,
        "candidates": 0,
    }

    candidates = []
    for stock in stocks or []:
        code = stock.get("code", "")
        themes = stock.get("luojie_themes") or match_luojie_themes(stock)
        if not themes:
            diagnostics["dropped_no_theme"] += 1
            continue
        diagnostics["theme_candidates"] += 1

        min15 = result_map.get(code)
        if min15 is None:
            diagnostics["dropped_no_15min"] += 1
            continue
        diagnostics["with_15min"] += 1

        candidate = _build_candidate(stock_map.get(code, stock), min15, themes)
        if candidate.get("drop_reason") == "insufficient_bars":
            diagnostics["dropped_insufficient_bars"] += 1
            continue
        if candidate.get("drop_reason") == "lifeline_break":
            diagnostics["dropped_lifeline_break"] += 1
            continue
        if candidate.get("drop_reason") == "macd_below_zero":
            diagnostics["dropped_macd_below_zero"] += 1
            continue
        if candidate.get("drop_reason") == "ma77_break_timeout":
            diagnostics["dropped_77_break_timeout"] += 1
            continue
        candidates.append(candidate)

    candidates.sort(key=_sort_key)
    ranked = candidates[:top_n]
    for idx, c in enumerate(ranked, 1):
        c["rank"] = idx
    diagnostics["candidates"] = len(ranked)

    return {
        "mode": "enabled",
        "reason": "硬编码国家队方向 + 15min生命线筛选",
        "params": {
            "life_line": "15min MA155/MA177 加权平均",
            "ma_short": MA_SHORT,
            "ma_mid": MA_MID,
            "break_buffer_pct": BREAK_BUFFER_PCT,
            "recovery_window_bars": RECOVERY_WINDOW_BARS,
        },
        "diagnostics": diagnostics,
        "candidates": ranked,
    }


def _build_candidate(stock, min15, themes):
    closes = _arr(min15.closes)
    lows = _arr(min15.lows)
    if len(closes) < MA_LIFE_B or len(lows) < MA_LIFE_B:
        return {"drop_reason": "insufficient_bars"}

    ma13 = _sma(closes, MA_SHORT)
    ma77 = _sma(closes, MA_MID)
    ma155 = _sma(closes, MA_LIFE_A)
    ma177 = _sma(closes, MA_LIFE_B)
    life_line_series = (ma155 + ma177) / 2.0

    latest_close = float(closes[-1])
    latest_life = float(life_line_series[-1])
    latest_ma77 = float(ma77[-1])
    latest_ma13 = float(ma13[-1])
    if not all(np.isfinite(x) for x in [latest_life, latest_ma77, latest_ma13]):
        return {"drop_reason": "insufficient_bars"}

    break_factor = 1 - BREAK_BUFFER_PCT / 100.0
    if latest_close < latest_life * break_factor:
        return {"drop_reason": "lifeline_break"}

    dif = _arr(getattr(min15, "macd_dif", []))
    dea = _arr(getattr(min15, "macd_dea", []))
    if len(dif) == 0 or len(dea) == 0 or float(dif[-1]) <= 0 or float(dea[-1]) <= 0:
        return {"drop_reason": "macd_below_zero"}

    last_77_break = _last_break_index(closes, ma77, 1.0)
    if last_77_break is not None:
        bars_since_break = len(closes) - 1 - last_77_break
        if bars_since_break >= RECOVERY_WINDOW_BARS and latest_close < latest_ma77:
            return {"drop_reason": "ma77_break_timeout"}
    else:
        bars_since_break = None

    golden_cross_recent = _has_golden_cross(ma13, ma77, GOLDEN_CROSS_LOOKBACK)
    ma_bullish = latest_ma13 > latest_ma77
    pullback_ok = _is_pullback_77_unbroken(lows, closes, ma77)
    buy_point_type = _best_buy_point_type(getattr(min15, "buy_points", []) or [])
    pivot_status = _pivot_status(getattr(min15, "pivots", []) or [], latest_life)
    ascending = _ascending_on_life(closes, lows, life_line_series)

    tier = _classify_tier(
        buy_point_type=buy_point_type,
        ma_bullish=ma_bullish,
        golden_cross_recent=golden_cross_recent,
        pullback_ok=pullback_ok,
        bars_since_break=bars_since_break,
    )
    score, reasons = _score(
        themes=themes,
        tier=tier,
        buy_point_type=buy_point_type,
        ma_bullish=ma_bullish,
        golden_cross_recent=golden_cross_recent,
        pullback_ok=pullback_ok,
        ascending=ascending,
        pivot_status=pivot_status,
        bars_since_break=bars_since_break,
    )

    return {
        "code": stock.get("code", ""),
        "name": stock.get("name", ""),
        "sector": stock.get("sector", ""),
        "sector_tags": stock.get("sector_tags", []),
        "sector_rank": stock.get("sector_rank"),
        "sector_flow": stock.get("sector_flow"),
        "sector_strength_label": stock.get("sector_strength_label", ""),
        "data_status": stock.get("data_status", {}),
        "theme_labels": _theme_labels(themes),
        "themes": themes,
        "tier": tier,
        "score": score,
        "close": round(latest_close, 2),
        "life_line": round(latest_life, 2),
        "ma13": round(latest_ma13, 2),
        "ma77": round(latest_ma77, 2),
        "distance_life_pct": _pct(latest_close, latest_life),
        "distance_ma77_pct": _pct(latest_close, latest_ma77),
        "macd_above_zero": True,
        "macd_status": "DIF/DEA双线0轴上",
        "buy_point_type": buy_point_type or "-",
        "pivot_status": pivot_status,
        "risk_line": round(latest_life, 2),
        "reduce_line": round(latest_ma77, 2),
        "ma_bullish": ma_bullish,
        "golden_cross_recent": golden_cross_recent,
        "pullback_77_unbroken": pullback_ok,
        "bars_since_77_break": bars_since_break,
        "reason": "；".join(reasons),
    }


def _arr(values):
    return np.asarray(values, dtype=float)


def _sma(values, period):
    result = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return result
    for i in range(period - 1, len(values)):
        result[i] = float(np.mean(values[i - period + 1:i + 1]))
    return result


def _last_break_index(closes, line, break_factor):
    start = max(0, len(closes) - RECOVERY_WINDOW_BARS)
    for i in range(len(closes) - 1, start - 1, -1):
        if np.isfinite(line[i]) and closes[i] < line[i] * break_factor:
            return i
    return None


def _has_golden_cross(short_ma, mid_ma, lookback):
    start = max(1, len(short_ma) - lookback)
    for i in range(start, len(short_ma)):
        if not all(np.isfinite(x) for x in [short_ma[i], mid_ma[i], short_ma[i - 1], mid_ma[i - 1]]):
            continue
        if short_ma[i] > mid_ma[i] and short_ma[i - 1] <= mid_ma[i - 1]:
            return True
    return bool(short_ma[-1] > mid_ma[-1])


def _is_pullback_77_unbroken(lows, closes, ma77):
    start = max(0, len(closes) - PULLBACK_WINDOW_BARS)
    recent_lows = lows[start:]
    recent_closes = closes[start:]
    recent_ma = ma77[start:]
    valid = np.isfinite(recent_ma)
    if not valid.any():
        return False
    low_touch = np.min(recent_lows[valid] / recent_ma[valid]) <= 1 + PULLBACK_TOLERANCE_PCT / 100.0
    close_not_break = recent_closes[-1] >= recent_ma[-1] * (1 - BREAK_BUFFER_PCT / 100.0)
    return bool(low_touch and close_not_break)


def _best_buy_point_type(buy_points):
    priority = {"三买": 3, "二买": 2, "一买": 1}
    best = ""
    best_score = 0
    for bp in buy_points:
        t = bp.get("type", "") if isinstance(bp, dict) else getattr(bp, "type", "")
        score = priority.get(t, 0)
        if score > best_score:
            best = t
            best_score = score
    return best


def _pivot_status(pivots, life_line):
    if not pivots:
        return "未形成中枢"
    p = pivots[-1]
    zd = _get_attr_or_key(p, "ZD")
    zg = _get_attr_or_key(p, "ZG")
    if zd is None or zg is None:
        return "中枢待确认"
    zd = float(zd)
    zg = float(zg)
    if zd <= life_line <= zg:
        return "围绕生命线形成中枢"
    if zd > life_line:
        return "中枢在生命线上"
    return "中枢跌破生命线"


def _get_attr_or_key(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _ascending_on_life(closes, lows, life_line):
    if len(closes) < 6:
        return False
    close_ok = np.all(closes[-5:] >= life_line[-5:] * (1 - BREAK_BUFFER_PCT / 100.0))
    low_ok = np.all(lows[-5:] >= life_line[-5:] * (1 - 2 * BREAK_BUFFER_PCT / 100.0))
    slope_ok = closes[-1] > closes[-5]
    return bool(close_ok and low_ok and slope_ok)


def _classify_tier(buy_point_type, ma_bullish, golden_cross_recent, pullback_ok, bars_since_break):
    if bars_since_break is not None and bars_since_break < RECOVERY_WINDOW_BARS:
        return "风控观察"
    if buy_point_type == "三买" and ma_bullish:
        return "主升候选"
    if pullback_ok or buy_point_type in ("一买", "二买", "三买"):
        return "买点候选"
    if ma_bullish or golden_cross_recent:
        return "生命线观察"
    return "生命线观察"


def _score(themes, tier, buy_point_type, ma_bullish, golden_cross_recent,
           pullback_ok, ascending, pivot_status, bars_since_break):
    score = 0
    reasons = []
    theme_count = sum(len(v) for v in themes.values())
    score += min(theme_count * 4, 20)
    reasons.append("国家队硬方向: " + "、".join(_theme_labels(themes)[:4]))

    tier_score = {"主升候选": 40, "买点候选": 28, "生命线观察": 18, "风控观察": 8}
    score += tier_score.get(tier, 0)
    reasons.append(tier)

    if buy_point_type and buy_point_type != "-":
        score += {"三买": 18, "二买": 12, "一买": 10}.get(buy_point_type, 6)
        reasons.append(f"15min{buy_point_type}")
    if ma_bullish:
        score += 10
        reasons.append("13/77多头")
    if golden_cross_recent:
        score += 8
        reasons.append("13/77金叉保持")
    if pullback_ok:
        score += 12
        reasons.append("回踩77线不破")
    if ascending:
        score += 8
        reasons.append("踩生命线向上")
    if "生命线" in pivot_status:
        score += 6
        reasons.append(pivot_status)
    if bars_since_break is not None and bars_since_break < RECOVERY_WINDOW_BARS:
        reasons.append("跌破77线后5根K内修复观察")

    return score, reasons


def _theme_labels(themes):
    labels = []
    for category, items in themes.items():
        for item in items:
            labels.append(f"{category}/{item}")
    return labels


def _pct(value, base):
    if not base:
        return 0
    return round((value - base) / base * 100, 2)


def _sort_key(candidate):
    tier_order = {"主升候选": 0, "买点候选": 1, "生命线观察": 2, "风控观察": 3}
    return (
        tier_order.get(candidate.get("tier"), 9),
        -float(candidate.get("score", 0)),
        candidate.get("code", ""),
    )
