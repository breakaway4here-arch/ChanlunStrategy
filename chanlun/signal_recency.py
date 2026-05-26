"""
信号时效过滤 — 所有进入报告的买点/候选/观察信号必须最近 N 个交易日内形成。
"""

import config


def annotate_buy_point_recency(bp, closes, dates=None, max_age=None):
    """Annotate a buy_point dict with recency fields.

    Args:
        bp: buy_point dict with at least 'index' key
        closes: list of closing prices (determines current bar)
        dates: optional list of date strings
        max_age: max allowed age in trading days (default from config)

    Returns:
        bp with added: signal_age_days, is_recent, recency_reason,
        signal_date (if dates available)
    """
    if max_age is None:
        max_age = config.SIGNAL_MAX_AGE_TRADING_DAYS

    bp = dict(bp)
    signal_index = bp.get("index")
    n_bars = len(closes) if closes is not None else 0

    if signal_index is None or n_bars == 0:
        bp["signal_age_days"] = None
        bp["is_recent"] = False
        bp["recency_reason"] = "无法确定信号日期"
        return bp

    current_index = n_bars - 1
    age = current_index - signal_index
    if age < 0:
        bp["signal_age_days"] = None
        bp["is_recent"] = False
        bp["recency_reason"] = "信号index越界（超过当前K线范围），无法确定时效"
        return bp

    bp["signal_age_days"] = age
    bp["is_recent"] = age <= max_age

    if dates and signal_index < len(dates):
        bp["signal_date"] = str(dates[signal_index])

    if age <= max_age:
        bp["recency_reason"] = f"信号发生在最近{age}个交易日内"
    else:
        bp["recency_reason"] = f"信号超过{max_age}个交易日（{age}天前）"

    return bp


def filter_recent_picks(picks, max_age=None):
    """Filter picks list, keeping only those with recent best_buy_point.

    Args:
        picks: list of pick dicts, each with 'best_buy_point' and 'closes'
        max_age: max allowed age in trading days

    Returns:
        (kept_picks, diagnostics_dict)
    """
    if max_age is None:
        max_age = config.SIGNAL_MAX_AGE_TRADING_DAYS

    diag = {
        "max_age_trading_days": max_age,
        "input": len(picks),
        "kept": 0,
        "dropped_expired": 0,
        "dropped_details": [],
    }

    kept = []
    for p in picks:
        bp = p.get("best_buy_point")
        closes = p.get("closes")
        dates = p.get("dates")

        if bp is None:
            diag["dropped_expired"] += 1
            diag["dropped_details"].append({
                "code": p.get("code", "?"),
                "name": p.get("name", "?"),
                "type": "?",
                "reason": "缺少best_buy_point",
            })
            continue

        bp = annotate_buy_point_recency(bp, closes, dates, max_age)
        p = dict(p)
        p["best_buy_point"] = bp

        if bp.get("is_recent"):
            kept.append(p)
            diag["kept"] += 1
        else:
            diag["dropped_expired"] += 1
            diag["dropped_details"].append({
                "code": p.get("code", "?"),
                "name": p.get("name", "?"),
                "type": bp.get("type", "?"),
                "signal_age_days": bp.get("signal_age_days"),
                "reason": bp.get("recency_reason", "信号过期"),
            })

    return kept, diag


def filter_recent_watchlist(watchlist, max_age=None):
    """Filter watchlist, keeping only recent items.

    Checks startup_age_days if present, otherwise derives from closes.

    Args:
        watchlist: list of watch item dicts
        max_age: max allowed age in trading days

    Returns:
        (kept_watchlist, diagnostics_dict)
    """
    if max_age is None:
        max_age = config.SIGNAL_MAX_AGE_TRADING_DAYS

    diag = {
        "max_age_trading_days": max_age,
        "input": len(watchlist),
        "kept": 0,
        "dropped_expired": 0,
        "dropped_details": [],
    }

    kept = []
    for w in watchlist:
        w = dict(w)
        age = w.get("startup_age_days")

        if age is None:
            closes = w.get("closes")
            startup_index = w.get("startup_index")
            if closes is not None and startup_index is not None:
                age = len(closes) - 1 - startup_index
                if age < 0:
                    age = 0
                w["startup_age_days"] = age
            else:
                # 无法确定年龄 → 过滤掉
                diag["dropped_expired"] += 1
                diag["dropped_details"].append({
                    "code": w.get("code", "?"),
                    "name": w.get("name", "?"),
                    "type": w.get("type", "?"),
                    "reason": "无法确定信号日期",
                })
                continue

        if age <= max_age:
            w["is_recent"] = True
            w["recency_reason"] = f"信号发生在最近{age}个交易日内"
            kept.append(w)
            diag["kept"] += 1
        else:
            w["is_recent"] = False
            w["recency_reason"] = f"信号超过{max_age}个交易日（{age}天前）"
            diag["dropped_expired"] += 1
            diag["dropped_details"].append({
                "code": w.get("code", "?"),
                "name": w.get("name", "?"),
                "type": w.get("type", "?"),
                "signal_age_days": age,
                "reason": w["recency_reason"],
            })

    return kept, diag
