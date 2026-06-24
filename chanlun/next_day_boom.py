"""
Next-day boom selector.

This is a narrow, second-pass ranking layer for the user's "次日大涨" goal.
It does not change the base Chanlun pools; it only re-ranks existing startup
signals when market breadth is strong enough for chase-style setups.
"""


DEFAULT_TOP_N = 5
MARKET_ENABLE_THRESHOLD = 1.0


def build_next_day_boom_candidates(picks_fusion, startup_watchlist, market, top_n=DEFAULT_TOP_N):
    """Build a TopN list for next-day big-gain candidates.

    Backtest-driven guard:
    - Enable only when Shanghai Composite daily change is above +1%.
    - Candidate universe: fusion strong-startup candidates + startup watchlist.
    - Deduplicate by code, keeping the highest boom score.
    """
    sh_change = _market_change_pct(market)
    if sh_change <= MARKET_ENABLE_THRESHOLD:
        return {
            "mode": "disabled",
            "reason": "上证涨幅未超过1%，次日大涨模式关闭",
            "market_change_pct": sh_change,
            "enable_threshold_pct": MARKET_ENABLE_THRESHOLD,
            "top_n": top_n,
            "source_counts": {
                "fusion_startup": _count_fusion_startups(picks_fusion),
                "startup_watch": len(startup_watchlist or []),
            },
            "candidates": [],
        }

    raw = []
    for pick in picks_fusion or []:
        bp = pick.get("best_buy_point") or {}
        if bp.get("type") != "强势启动候选":
            continue
        raw.append(_build_candidate_from_fusion(pick, bp, sh_change))

    for item in startup_watchlist or []:
        raw.append(_build_candidate_from_watch(item, sh_change))

    deduped = {}
    for c in raw:
        code = c.get("code", "")
        if not code:
            continue
        old = deduped.get(code)
        if old is None or _sort_key(c) < _sort_key(old):
            deduped[code] = c

    ranked = sorted(deduped.values(), key=_sort_key)[:top_n]
    for idx, c in enumerate(ranked, 1):
        c["rank"] = idx

    return {
        "mode": "enabled",
        "reason": "上证涨幅超过1%，开启次日大涨模式",
        "market_change_pct": sh_change,
        "enable_threshold_pct": MARKET_ENABLE_THRESHOLD,
        "top_n": top_n,
        "source_counts": {
            "fusion_startup": _count_fusion_startups(picks_fusion),
            "startup_watch": len(startup_watchlist or []),
            "raw": len(raw),
            "deduped": len(deduped),
        },
        "candidates": ranked,
    }


def _market_change_pct(market):
    try:
        return float((market or {}).get("上证指数", {}).get("change_pct", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _count_fusion_startups(picks_fusion):
    return sum(
        1 for p in (picks_fusion or [])
        if (p.get("best_buy_point") or {}).get("type") == "强势启动候选"
    )


def _build_candidate_from_fusion(pick, bp, market_change_pct):
    change_pct = _num(bp.get("change_pct"))
    volume_ratio = _num(bp.get("volume_ratio"))
    score, reasons = _score_startup(
        source_pool="fusion",
        change_pct=change_pct,
        volume_ratio=volume_ratio,
        ma_bullish=bool(pick.get("ma_bullish")),
        startup_signals=bp.get("startup_signals") or [],
    )
    return {
        "code": pick.get("code", ""),
        "name": pick.get("name", ""),
        "sector": pick.get("sector", ""),
        "source_pool": "fusion",
        "source_type": bp.get("type", "强势启动候选"),
        "boom_score": score,
        "boom_reason": "；".join(reasons),
        "change_pct": change_pct,
        "volume_ratio": volume_ratio,
        "market_change_pct": market_change_pct,
        "ma_bullish": bool(pick.get("ma_bullish")),
        "startup_reason": bp.get("startup_reason") or bp.get("reason", ""),
        "confirmed_by": bp.get("confirmed_by", ""),
        "confirmations": bp.get("confirmations", []),
        "reference_price": bp.get("price"),
    }


def _build_candidate_from_watch(item, market_change_pct):
    change_pct = _num(item.get("change_pct"))
    volume_ratio = _num(item.get("volume_ratio"))
    score, reasons = _score_startup(
        source_pool="watch",
        change_pct=change_pct,
        volume_ratio=volume_ratio,
        ma_bullish=False,
        startup_signals=item.get("startup_signals") or [],
    )
    return {
        "code": item.get("code", ""),
        "name": item.get("name", ""),
        "sector": item.get("sector", ""),
        "source_pool": "watch",
        "source_type": item.get("type", "强势启动观察"),
        "boom_score": score,
        "boom_reason": "；".join(reasons),
        "change_pct": change_pct,
        "volume_ratio": volume_ratio,
        "market_change_pct": market_change_pct,
        "ma_bullish": False,
        "startup_reason": item.get("startup_reason", ""),
        "confirmed_by": item.get("confirmed_by", ""),
        "confirmations": item.get("confirmations", []),
        "reference_price": item.get("close"),
    }


def _score_startup(source_pool, change_pct, volume_ratio, ma_bullish, startup_signals):
    score = 0
    reasons = []

    if source_pool == "fusion":
        score += 18
        reasons.append("融合强势启动")
    else:
        score += 14
        reasons.append("启动观察异动")

    if ma_bullish:
        score += 10
        reasons.append("MA多头")

    if 1.3 <= volume_ratio < 1.6:
        score += 16
        reasons.append("量比甜区1.3-1.6")
    elif 1.6 <= volume_ratio < 2.0:
        score += 10
        reasons.append("量比健康1.6-2.0")
    elif 2.0 <= volume_ratio < 3.0:
        score += 6
        reasons.append("量能偏热2.0-3.0")
    elif volume_ratio >= 3.0:
        score -= 4
        reasons.append("量能过热降权")

    if 4.0 <= change_pct < 7.0:
        score += 12
        reasons.append("涨幅4-7%启动")
    elif 7.0 <= change_pct < 9.5:
        score += 10
        reasons.append("涨幅7-9.5%启动")
    elif 9.5 <= change_pct < 12.0:
        score += 12
        reasons.append("温和涨停区")
    elif 12.0 <= change_pct < 16.0:
        score += 6
        reasons.append("高弹性启动")
    elif change_pct >= 16.0:
        score -= 3
        reasons.append("涨幅过大降权")

    if any("实体阳线" in str(s) for s in startup_signals):
        score += 4
        reasons.append("实体阳线")
    if "break_20d_high" in startup_signals:
        score += 2
        reasons.append("突破20日平台")

    return score, reasons


def _sort_key(candidate):
    return (-_num(candidate.get("boom_score")), candidate.get("code", ""))


def _num(value):
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
