"""JoinQuant standalone alpha-weight comparison strategy.

Paste this file into the JoinQuant strategy editor and run a backtest.

What it does:
- Rebuilds a lightweight candidate pool from JoinQuant daily bars.
- Ports the current ChanlunStrategy opportunity scoring formula.
- Compares baseline, 0.8x, 1.0x, 1.2x, 1.5x and 1.8x alpha weights in
  virtual equal-weight portfolios.
- Optionally trades one selected variant as the real JoinQuant portfolio.

Important:
- This is an approximation of the current report-scoring layer. It cannot
  reproduce the local report pools exactly because JoinQuant does not have
  `picks_fusion`, `next_day_boom`, `luojie_pool`, or `startup_watchlist`.
- The purpose is to test whether alpha weighting improves ranking quality on a
  larger and cleaner historical data set.
"""

try:
    from jqdata import *  # type: ignore  # noqa: F401,F403
except Exception:
    # Local syntax checks do not have the JoinQuant runtime.
    pass

import math
from collections import defaultdict


SIGNAL_CAPS = {
    "main": 25.0,
    "acceleration": 18.0,
    "luojie": 15.0,
    "confirming": 10.0,
    "baseline": 8.0,
}

MARKET_BASE = {
    "main": 12.0,
    "acceleration": 10.0,
    "luojie": 9.0,
    "confirming": 8.0,
    "baseline": 6.0,
}

SOURCE_RANK = {
    "main": 0,
    "acceleration": 1,
    "luojie": 2,
    "confirming": 3,
    "baseline": 4,
}

MAX_MOMENTUM_SCORE = 20.0
MAX_MARKET_SCORE = 15.0
MAX_RISK_PENALTY = 30.0
ALPHA_MULTIPLIER_MIN = 1.00
ALPHA_MULTIPLIER_MAX = 1.04
ALPHA_BONUS_LIMIT = 5.0

WEIGHT_SPECS = [
    ("baseline", None),
    ("alpha_0_8x", 0.8),
    ("alpha_1_0x", 1.0),
    ("alpha_1_2x", 1.2),
    ("alpha_1_5x", 1.5),
    ("alpha_1_8x", 1.8),
]


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    try:
        set_order_cost(
            OrderCost(
                close_tax=0.001,
                open_commission=0.0003,
                close_commission=0.0003,
                min_commission=5,
            ),
            type="stock",
        )
    except Exception:
        pass

    g.index_code = "000985.XSHG"
    g.max_universe = 900
    g.min_history_bars = 70
    g.history_bars = 90
    g.top_k = 10
    g.rebalance_every_n_days = 1
    g.real_trade_label = "alpha_1_5x"
    g.enable_real_trade = True
    g.summary_interval = 20
    g.day_count = 0
    g.last_targets = {}

    start_cash = getattr(context.portfolio, "starting_cash", None) or 1000000.0
    g.virtual = {}
    for label, _weight in WEIGHT_SPECS:
        g.virtual[label] = {
            "cash": float(start_cash),
            "positions": {},
            "equity_curve": [],
            "daily_returns": [],
            "wins": 0,
            "days": 0,
            "last_equity": float(start_cash),
        }

    run_daily(rebalance, time="9:30")


def rebalance(context):
    g.day_count += 1
    if g.day_count % g.rebalance_every_n_days != 1:
        return

    current_data = get_current_data()
    for label, _weight in WEIGHT_SPECS:
        update_virtual_equity(label, current_data)

    candidates = build_candidates(context)
    if not candidates:
        log.warn("No candidates on %s" % context.current_dt)
        return

    ranked_by_label = {}
    for label, weight in WEIGHT_SPECS:
        rows = []
        for candidate in candidates:
            score, trace = compute_weighted_score(candidate, weight)
            rows.append((score, candidate["code"], candidate, trace))
        rows.sort(key=lambda x: (-x[0], x[1]))
        ranked_by_label[label] = rows[: g.top_k]

    for label, top_rows in ranked_by_label.items():
        targets = [row[1] for row in top_rows]
        rebalance_virtual_portfolio(label, targets, current_data)
        g.last_targets[label] = targets

    if g.enable_real_trade:
        trade_real_portfolio(context, ranked_by_label.get(g.real_trade_label, []), current_data)

    log_top_candidates(ranked_by_label)

    if g.day_count % g.summary_interval == 0:
        log_summary("summary day=%s" % g.day_count)

    try:
        record(
            base=value_ratio("baseline"),
            a10=value_ratio("alpha_1_0x"),
            a15=value_ratio("alpha_1_5x"),
            a18=value_ratio("alpha_1_8x"),
        )
    except Exception:
        pass


def handle_data(context, data):
    pass


def build_candidates(context):
    universe = get_base_universe(context)
    market = calc_market_context(context, universe)
    raw_candidates = []

    for code in universe:
        item = build_candidate_item(context, code)
        if not item:
            continue
        raw_candidates.append(item)

    attach_sector_strength(context, raw_candidates)

    candidates = []
    for item in raw_candidates:
        sources, by_source = infer_sources(item)
        if not sources:
            continue
        primary = sorted(sources, key=lambda s: SOURCE_RANK.get(s, 99))[0]
        candidate = {
            "code": item["code"],
            "source": primary,
            "item": by_source[primary],
            "sources": sources,
            "by_source": by_source,
            "market": market,
        }
        candidates.append(candidate)

    return candidates


def get_base_universe(context):
    date = context.previous_date
    try:
        stocks = list(get_index_stocks(g.index_code, date=date))
    except Exception:
        stocks = list(get_all_securities(["stock"], date=date).index)

    stocks = filter_current_tradable(stocks, context)
    stocks = filter_by_market_cap(stocks, context)
    return stocks[: g.max_universe]


def filter_current_tradable(stocks, context):
    current_data = get_current_data()
    securities = None
    try:
        securities = get_all_securities(["stock"], date=context.previous_date)
    except Exception:
        pass

    result = []
    for code in stocks:
        cd = current_data_for(current_data, code)
        if cd is None:
            continue
        if getattr(cd, "paused", False):
            continue
        if getattr(cd, "is_st", False):
            continue
        name = getattr(cd, "name", "") or ""
        if "ST" in name or "*" in name or "退" in name:
            continue
        if securities is not None and code in securities.index:
            start_date = securities.loc[code, "start_date"]
            try:
                if (context.previous_date - start_date).days < 120:
                    continue
            except Exception:
                pass
        result.append(code)
    return result


def filter_by_market_cap(stocks, context):
    if not stocks:
        return []
    try:
        q = (
            query(valuation.code, valuation.market_cap)
            .filter(valuation.code.in_(stocks))
            .order_by(valuation.market_cap.desc())
            .limit(g.max_universe)
        )
        df = get_fundamentals(q, date=context.previous_date)
        if df is not None and len(df) > 0:
            return list(df["code"])
    except Exception as exc:
        log.warn("market_cap filter fallback: %s" % exc)
    return stocks[: g.max_universe]


def build_candidate_item(context, code):
    try:
        hist = attribute_history(
            code,
            g.history_bars,
            unit="1d",
            fields=["open", "close", "high", "low", "volume", "money"],
            skip_paused=True,
            df=True,
        )
    except Exception:
        return None

    if hist is None or len(hist) < g.min_history_bars:
        return None

    closes = [float(x) for x in list(hist["close"])]
    highs = [float(x) for x in list(hist["high"])]
    lows = [float(x) for x in list(hist["low"])]
    volumes = [float(x) for x in list(hist["volume"])]
    money = [float(x) for x in list(hist["money"])]
    if not closes or closes[-1] <= 0:
        return None

    ma5 = avg(closes[-5:])
    ma10 = avg(closes[-10:])
    ma20 = avg(closes[-20:])
    ma60 = avg(closes[-60:])
    close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else close
    high20 = max(highs[-20:])
    low20 = min(lows[-20:])
    volume_ratio = volumes[-1] / avg(volumes[-20:-1]) if avg(volumes[-20:-1]) > 0 else 0.0
    money20 = avg(money[-20:])
    change_pct = pct(close, prev_close)
    distance_ma20 = pct(close, ma20)
    ret10 = pct(close, closes[-11]) if len(closes) >= 11 else 0.0
    ret20 = pct(close, closes[-21]) if len(closes) >= 21 else 0.0
    ret60 = pct(close, closes[-61]) if len(closes) >= 61 else 0.0
    drawdown20 = pct(close, high20)
    range_pos20 = (close - low20) / (high20 - low20) if high20 > low20 else 0.0

    score = calc_proxy_signal_score(
        close=close,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma60=ma60,
        ret10=ret10,
        ret20=ret20,
        ret60=ret60,
        volume_ratio=volume_ratio,
        distance_ma20=distance_ma20,
        drawdown20=drawdown20,
        range_pos20=range_pos20,
        money20=money20,
    )

    if score < 35:
        return None

    return {
        "code": code,
        "score": score,
        "boom_score": min(100.0, score + max(0.0, volume_ratio - 1.0) * 12.0 + max(0.0, ret10) * 0.8),
        "close": close,
        "closes": closes,
        "change_pct": change_pct,
        "distance_from_reference_pct": distance_ma20,
        "distance_life_pct": distance_ma20,
        "volume_ratio": volume_ratio,
        "money20": money20,
        "ret10": ret10,
        "ret20": ret20,
        "ret60": ret60,
        "drawdown20": drawdown20,
        "range_pos20": range_pos20,
        "confirmed_by": "daily_confirmed" if close > ma20 and ma5 > ma10 else "",
        "sector_key": get_sector_key(code, context),
    }


def calc_proxy_signal_score(**kwargs):
    close = kwargs["close"]
    ma5 = kwargs["ma5"]
    ma10 = kwargs["ma10"]
    ma20 = kwargs["ma20"]
    ma60 = kwargs["ma60"]
    ret10 = kwargs["ret10"]
    ret20 = kwargs["ret20"]
    ret60 = kwargs["ret60"]
    volume_ratio = kwargs["volume_ratio"]
    distance_ma20 = kwargs["distance_ma20"]
    drawdown20 = kwargs["drawdown20"]
    range_pos20 = kwargs["range_pos20"]
    money20 = kwargs["money20"]

    score = 0.0
    if close > ma20:
        score += 16.0
    if ma5 > ma10:
        score += 12.0
    if ma20 > ma60:
        score += 12.0
    if 0.0 < ret10 < 25.0:
        score += min(14.0, ret10 * 0.9)
    if 2.0 < ret20 < 45.0:
        score += min(14.0, ret20 * 0.55)
    if -10.0 < ret60 < 80.0:
        score += 8.0
    if volume_ratio >= 1.0:
        score += min(10.0, (volume_ratio - 1.0) * 8.0)
    if abs(distance_ma20) <= 5.0:
        score += 8.0
    if drawdown20 >= -4.0:
        score += 8.0
    if range_pos20 >= 0.65:
        score += 5.0
    if money20 >= 50000000:
        score += 5.0
    return max(0.0, min(100.0, score))


def infer_sources(item):
    sources = []
    by_source = {}

    if item["score"] >= 45:
        sources.append("main")
        by_source["main"] = dict(item)

    if item["drawdown20"] >= -3.0 and item["volume_ratio"] >= 1.15 and item["ret10"] > 2.0:
        sources.append("acceleration")
        acc = dict(item)
        acc["next_day_reason"] = "breakout"
        by_source["acceleration"] = acc

    if abs(item["distance_from_reference_pct"]) <= 4.0 and item["ret20"] > 0:
        sources.append("luojie")
        lj = dict(item)
        lj["life_line"] = item["close"] / (1.0 + item["distance_from_reference_pct"] / 100.0)
        by_source["luojie"] = lj

    if item["confirmed_by"]:
        sources.append("confirming")
        cf = dict(item)
        cf["startup_age_days"] = 1
        by_source["confirming"] = cf

    deduped = []
    seen = set()
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        deduped.append(source)
    return deduped, by_source


def calc_market_context(context, universe):
    index_scores = []
    for code in ["000300.XSHG", "000905.XSHG"]:
        try:
            hist = attribute_history(code, 60, "1d", ["close"], skip_paused=True, df=True)
            closes = [float(x) for x in list(hist["close"])]
            if len(closes) >= 20:
                ma20 = avg(closes[-20:])
                score = 50.0 + pct(closes[-1], ma20) / 8.0 * 50.0
                index_scores.append(_clamp(score, 0.0, 100.0))
        except Exception:
            pass

    breadth_values = []
    for code in universe[:250]:
        try:
            hist = attribute_history(code, 30, "1d", ["close"], skip_paused=True, df=True)
            closes = [float(x) for x in list(hist["close"])]
            if len(closes) >= 20:
                breadth_values.append(1.0 if closes[-1] > avg(closes[-20:]) else 0.0)
        except Exception:
            continue

    index_trend_score = avg(index_scores) if index_scores else 50.0
    breadth_score = avg(breadth_values) * 100.0 if breadth_values else 50.0
    return {
        "index_trend_score": index_trend_score,
        "breadth_score": breadth_score,
        "market_regime_factor": (index_trend_score * 0.55 + breadth_score * 0.45),
    }


def get_sector_key(code, context):
    try:
        info = get_industry(code, date=context.previous_date)
        sw_l1 = info.get(code, {}).get("sw_l1", {})
        if sw_l1:
            return sw_l1.get("industry_code") or sw_l1.get("industry_name")
    except Exception:
        pass
    return "unknown"


def attach_sector_strength(context, items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.get("sector_key") or "unknown"].append(item)

    sector_returns = []
    for sector, rows in grouped.items():
        values = [row.get("ret20", 0.0) for row in rows]
        sector_returns.append((sector, avg(values), len(rows)))
    sector_returns.sort(key=lambda x: (-x[1], -x[2], x[0]))

    rank_by_sector = {}
    strength_by_sector = {}
    for idx, (sector, ret, _count) in enumerate(sector_returns):
        rank_by_sector[sector] = idx + 1
        strength_by_sector[sector] = _clamp((ret + 5.0) / 25.0, 0.0, 1.0)

    for item in items:
        sector = item.get("sector_key") or "unknown"
        item["sector_rank"] = rank_by_sector.get(sector)
        item["sector_strength_factor"] = strength_by_sector.get(sector, 0.0)
        item["sector_flow"] = item.get("money20", 0.0) / 1000000.0


def compute_weighted_score(candidate, alpha_weight):
    item = candidate["item"]
    source = candidate["source"]
    context = {
        "sources": candidate["sources"],
        "by_source": candidate["by_source"],
        "source_count": len(candidate["sources"]),
        "market": candidate["market"],
    }
    score, trace = compute_opportunity_score(item, source, context, alpha_enabled=(alpha_weight is not None))
    if alpha_weight is None:
        return score, trace

    base = trace["base_opportunity_score"]
    bonus = trace["alpha_bonus"] * alpha_weight
    multiplier = 1.0 + (trace["alpha_multiplier"] - 1.0) * alpha_weight
    weighted_score = max(0, int(round(base * multiplier + bonus)))
    trace = dict(trace)
    trace["alpha_weight"] = alpha_weight
    trace["weighted_alpha_bonus"] = round(bonus, 4)
    trace["weighted_alpha_multiplier"] = round(multiplier, 4)
    trace["opportunity_score"] = weighted_score
    return weighted_score, trace


def compute_opportunity_score(item, source, context, alpha_enabled=False):
    sources = normalize_sources(context.get("sources"), source)
    by_source = normalize_by_source(context.get("by_source"), item, source)
    source_count = max(int(context.get("source_count") or len(sources)), len(sources))

    distance = _safe_float(item.get("distance_from_reference_pct"))
    if distance is None:
        distance = _resolve_distance_pct(item, source)
    change_pct = _resolve_change_pct(item)

    signal_score = _score_signal(item, source)
    entry_score = _score_entry(distance)
    momentum_score = _score_momentum(change_pct)
    market_score = _score_market(source, source_count)
    risk_flags = _collect_risk_flags(by_source, sources)
    risk_penalty = _score_risk_penalty(risk_flags)

    raw_score = signal_score + entry_score + momentum_score + market_score - risk_penalty
    base_opportunity_score = max(0, int(round(raw_score)))

    alpha_bonus = 0.0
    alpha_multiplier = 1.0
    alpha_features = {}
    if alpha_enabled:
        alpha_features = _resolve_alpha_features(context, item, {"distance": distance}, source)
        alpha_bonus = _score_alpha_bonus(alpha_features, by_source, source, item, {"distance": distance})
        alpha_multiplier = _resolve_alpha_multiplier(alpha_features, alpha_bonus)

    opportunity_score = max(0, int(round(base_opportunity_score * alpha_multiplier + alpha_bonus)))
    trace = {
        "base_source": source,
        "source_count": len(sources),
        "signal_score": signal_score,
        "entry_score": entry_score,
        "momentum_score": momentum_score,
        "market_score": market_score,
        "risk_penalty": risk_penalty,
        "alpha_features": alpha_features,
        "alpha_bonus": round(alpha_bonus, 4),
        "alpha_multiplier": round(alpha_multiplier, 4),
        "base_opportunity_score": base_opportunity_score,
        "risk_flags": risk_flags,
        "opportunity_score": opportunity_score,
        "distance_from_reference_pct": distance,
        "change_pct": change_pct,
    }
    return opportunity_score, trace


def normalize_sources(value, fallback):
    if isinstance(value, (list, tuple, set)):
        sources = [str(v) for v in value if v]
    else:
        sources = [fallback]
    result = []
    seen = set()
    for source in sources:
        if source not in seen:
            seen.add(source)
            result.append(source)
    return result or [fallback]


def normalize_by_source(value, item, source):
    if isinstance(value, dict) and value:
        return value
    return {source: item}


def _score_signal(item, source):
    cap = SIGNAL_CAPS.get(source, 0.0)
    if source == "confirming":
        return cap
    raw_key = "boom_score" if source == "acceleration" else "score"
    raw = _safe_float(item.get(raw_key), 0.0) or 0.0
    if raw <= 0:
        return 0.0
    return round(min(cap, max(0.0, raw / 100.0 * cap)), 2)


def _score_entry(distance_pct):
    if distance_pct is None:
        return 4.0
    distance = abs(distance_pct)
    if distance <= 1.0:
        return 16.0
    if distance <= 2.0:
        return 14.0
    if distance <= 3.0:
        return 11.0
    if distance <= 5.0:
        return 8.0
    if distance <= 8.0:
        return 4.0
    return 0.0


def _score_momentum(change_pct):
    if change_pct is None or change_pct <= 0:
        return 0.0
    return round(min(MAX_MOMENTUM_SCORE, change_pct * 1.5), 2)


def _score_market(source, source_count):
    base = MARKET_BASE.get(source, 5.0)
    multi_source_bonus = max(0, source_count - 1) * 2.0
    return min(MAX_MARKET_SCORE, base + multi_source_bonus)


def _resolve_alpha_features(context, item, metrics, source):
    market_ctx = context.get("market") or {}
    sector_strength = {
        "sector_flow": _safe_float(item.get("sector_flow")),
        "sector_rank": _safe_float(item.get("sector_rank")),
        "sector_strength_factor": _safe_float(item.get("sector_strength_factor")),
    }
    breakout_quality = {
        "volume_ratio": _safe_float(item.get("volume_ratio")),
        "confirmed_by": str(item.get("confirmed_by") or ""),
        "distance": _safe_float(metrics.get("distance")),
    }
    return {
        "market_regime_factor": {
            "index_trend_score": _safe_float(market_ctx.get("index_trend_score")),
            "breadth_score": _safe_float(market_ctx.get("breadth_score")),
            "market_regime_factor": _safe_float(market_ctx.get("market_regime_factor")),
        },
        "sector_strength_factor": sector_strength,
        "momentum_persistence": _calc_momentum_persistence_from_closes(item.get("closes") or []),
        "breakout_quality": breakout_quality,
    }


def _score_alpha_bonus(alpha_features, by_source, source, item, metrics):
    bonus = 0.0
    bonus += _score_market_regime_bonus(alpha_features.get("market_regime_factor") or {})
    bonus += _score_sector_strength_bonus(alpha_features.get("sector_strength_factor") or {})
    bonus += _score_momentum_persistence_bonus(alpha_features.get("momentum_persistence"), item, source)
    bonus += _score_breakout_quality_bonus(alpha_features.get("breakout_quality") or {}, by_source, source, item, metrics)
    return round(_clamp(bonus, 0.0, ALPHA_BONUS_LIMIT), 4)


def _resolve_alpha_multiplier(alpha_features, bonus):
    market_bonus = _score_market_regime_bonus(alpha_features.get("market_regime_factor") or {})
    sector_bonus = _score_sector_strength_bonus(alpha_features.get("sector_strength_factor") or {})
    momentum_bonus = _score_momentum_persistence_bonus(alpha_features.get("momentum_persistence"), {}, "")
    weighted = (market_bonus + sector_bonus + momentum_bonus) / 300.0
    return _clamp(1.0 + weighted + (bonus / 800.0), ALPHA_MULTIPLIER_MIN, ALPHA_MULTIPLIER_MAX)


def _score_market_regime_bonus(features):
    index_score = _safe_float(features.get("index_trend_score"))
    breadth_score = _safe_float(features.get("breadth_score"))
    regime_factor = _safe_float(features.get("market_regime_factor"))
    parts = []
    if index_score is not None:
        parts.append(_norm_percent_score(index_score))
    if breadth_score is not None:
        parts.append(_norm_percent_score(breadth_score))
    score = 0.0
    if parts:
        score += sum(parts) / len(parts) * 2.0
    if regime_factor is not None:
        score += _norm_percent_score(regime_factor) * 1.5
    return _clamp(score, 0.0, 3.0)


def _score_sector_strength_bonus(features):
    sector_flow = _safe_float(features.get("sector_flow"))
    sector_rank = _safe_float(features.get("sector_rank"))
    sector_strength_factor = _safe_float(features.get("sector_strength_factor"))
    flow_signal = _clamp(sector_flow / 2000.0, 0.0, 1.0) if sector_flow is not None else 0.0
    rank_signal = 0.0
    if sector_rank is not None and sector_rank > 0:
        rank_signal = _clamp((10.0 - min(10.0, sector_rank)) / 10.0, 0.0, 1.0)
    direct_signal = _clamp(sector_strength_factor, 0.0, 1.0) if sector_strength_factor is not None else 0.0
    return _clamp((flow_signal * 0.45 + rank_signal * 0.35 + direct_signal * 0.2) * 2.5, 0.0, 2.5)


def _score_momentum_persistence_bonus(momentum_persistence, item, source):
    persistence = _safe_float(momentum_persistence)
    if persistence is None and isinstance(item, dict):
        persistence = _calc_momentum_persistence_from_closes(item.get("closes") or [])
    if persistence is None:
        return 0.0
    if abs(persistence) > 1:
        persistence = persistence / 100.0
    return _clamp(persistence * 3.0, 0.0, 2.5)


def _score_breakout_quality_bonus(features, by_source, source, item, metrics):
    volume_ratio = _safe_float(features.get("volume_ratio")) or _safe_float(item.get("volume_ratio"))
    confirmed_by = str(features.get("confirmed_by") or item.get("confirmed_by") or "")
    distance = _safe_float(features.get("distance"))
    if distance is None:
        distance = _safe_float(metrics.get("distance"))

    score = 0.0
    if volume_ratio is not None and volume_ratio >= 1.0:
        score += _clamp((volume_ratio - 1.0) * 0.9, 0.0, 1.5)
    if confirmed_by and "waiting" not in confirmed_by:
        score += 1.0
    if distance is not None:
        if abs(distance) <= 2.0:
            score += 1.0
        elif abs(distance) <= 5.0:
            score += 0.5
    return _clamp(score, 0.0, 2.8)


def _collect_risk_flags(by_source, sources):
    seen = set()
    flags = []
    for source in sources:
        row = by_source.get(source, {})
        for flag in _extract_risk_flags(row, source):
            if flag and flag not in seen:
                seen.add(flag)
                flags.append(flag)
    return flags


def _extract_risk_flags(item, source):
    flags = []
    distance = _resolve_distance_pct(item, source)
    change_pct = _resolve_change_pct(item) or 0.0
    if distance is not None and abs(distance) > 6.0:
        flags.append("distance_high")
    if change_pct >= 7.5:
        flags.append("overheated")
    if source == "confirming" and item.get("confirmed_by") == "waiting":
        flags.append("unconfirmed")
    return flags


def _score_risk_penalty(risk_flags):
    unique = set(risk_flags)
    penalty = 0.0
    if "distance_high" in unique:
        penalty += 12.0
    if "overheated" in unique:
        penalty += 10.0
    if "unconfirmed" in unique:
        penalty += 8.0
    return min(MAX_RISK_PENALTY, penalty)


def _resolve_change_pct(item):
    direct = _safe_float(item.get("change_pct"))
    if direct is not None:
        return direct
    closes = item.get("closes")
    if not isinstance(closes, (list, tuple)) or len(closes) < 2:
        return None
    return pct(closes[-1], closes[-2])


def _resolve_distance_pct(item, source):
    direct = _safe_float(item.get("distance_from_reference_pct"))
    if direct is not None:
        return direct
    life_distance = _safe_float(item.get("distance_life_pct"))
    if life_distance is not None:
        return life_distance
    if source == "luojie":
        close = _safe_float(item.get("close"))
        life_line = _safe_float(item.get("life_line"))
        if close is not None and life_line not in (None, 0):
            return pct(close, life_line)
    return None


def _calc_momentum_persistence_from_closes(closes):
    numeric = [_safe_float(x) for x in closes]
    numeric = [x for x in numeric if x not in (None, 0)]
    if len(numeric) < 4:
        return 0.0

    windows = (3, 5, 10)
    weighted = []
    for window in windows:
        if len(numeric) < window + 1:
            continue
        end = numeric[-1]
        start = numeric[-(window + 1)]
        pct_change = pct(end, start)
        up_days = 0
        total = 0
        for i in range(-window + 1, 0):
            total += 1
            if numeric[i] >= numeric[i - 1]:
                up_days += 1
        ratio = up_days / float(total) if total else 0.0
        score = _clamp((pct_change / 20.0) * 0.65 + (ratio * 2.0 - 1.0) * 0.35, -1.0, 1.0)
        weighted.append(score)

    if not weighted:
        return 0.0
    weights = (0.4, 0.35, 0.25)
    if len(weighted) == 1:
        return weighted[0]
    if len(weighted) == 2:
        return weighted[0] * weights[0] + weighted[1] * (1.0 - weights[0])
    return weighted[0] * weights[0] + weighted[1] * weights[1] + weighted[2] * weights[2]


def rebalance_virtual_portfolio(label, targets, current_data):
    portfolio = g.virtual[label]
    equity = calc_virtual_equity(portfolio, current_data)
    positions = {}
    target_count = len(targets)
    if target_count <= 0 or equity <= 0:
        portfolio["cash"] = equity
        portfolio["positions"] = {}
        return

    target_value = equity / float(target_count)
    used = 0.0
    for code in targets:
        price = get_trade_price(code, current_data)
        if price is None or price <= 0:
            continue
        shares = target_value / price
        positions[code] = shares
        used += shares * price
    portfolio["positions"] = positions
    portfolio["cash"] = max(0.0, equity - used)


def update_virtual_equity(label, current_data):
    portfolio = g.virtual[label]
    equity = calc_virtual_equity(portfolio, current_data)
    last = portfolio.get("last_equity") or equity
    daily_return = (equity / last - 1.0) * 100.0 if last > 0 else 0.0
    portfolio["daily_returns"].append(daily_return)
    portfolio["equity_curve"].append(equity)
    portfolio["last_equity"] = equity
    portfolio["days"] += 1
    if daily_return > 0:
        portfolio["wins"] += 1


def calc_virtual_equity(portfolio, current_data):
    equity = float(portfolio.get("cash") or 0.0)
    for code, shares in list((portfolio.get("positions") or {}).items()):
        price = get_trade_price(code, current_data)
        if price is None or price <= 0:
            continue
        equity += float(shares) * price
    return equity


def trade_real_portfolio(context, top_rows, current_data):
    targets = [row[1] for row in top_rows]
    target_set = set(targets)
    for code in list(context.portfolio.positions.keys()):
        if code not in target_set:
            order_target_value(code, 0)

    if not targets:
        return
    total_value = context.portfolio.total_value
    target_value = total_value / float(len(targets))
    for code in targets:
        cd = current_data_for(current_data, code)
        if cd is None or getattr(cd, "paused", False):
            continue
        price = get_trade_price(code, current_data)
        high_limit = getattr(cd, "high_limit", None)
        if high_limit is not None and price is not None and price >= high_limit * 0.999:
            continue
        order_target_value(code, target_value)


def get_trade_price(code, current_data):
    cd = current_data_for(current_data, code)
    if cd is None:
        return None
    for field in ("last_price", "day_open"):
        value = getattr(cd, field, None)
        value = _safe_float(value)
        if value is not None and value > 0 and not math.isnan(value):
            return value
    return None


def current_data_for(current_data, code):
    try:
        return current_data[code]
    except Exception:
        return None


def value_ratio(label):
    portfolio = g.virtual[label]
    curve = portfolio.get("equity_curve") or []
    if not curve:
        return 1.0
    start = curve[0] if curve[0] else 1.0
    return curve[-1] / start


def calc_metrics(label):
    portfolio = g.virtual[label]
    curve = portfolio.get("equity_curve") or []
    returns = portfolio.get("daily_returns") or []
    total_return = 0.0
    if curve:
        start = curve[0]
        total_return = (curve[-1] / start - 1.0) * 100.0 if start > 0 else 0.0
    mean_return = avg(returns) if returns else 0.0
    win_rate = (sum(1 for x in returns if x > 0) / float(len(returns)) * 100.0) if returns else 0.0
    max_dd = calc_max_drawdown(curve)
    return total_return, mean_return, win_rate, max_dd


def calc_max_drawdown(curve):
    if not curve:
        return 0.0
    peak = curve[0]
    mdd = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            mdd = min(mdd, (value / peak - 1.0) * 100.0)
    return mdd


def log_top_candidates(ranked_by_label):
    rows = ranked_by_label.get(g.real_trade_label) or []
    preview = []
    for score, code, candidate, trace in rows[:5]:
        preview.append("%s:%s" % (code, score))
    log.info("top %s %s" % (g.real_trade_label, ", ".join(preview)))


def log_summary(title):
    log.info("===== %s =====" % title)
    for label, _weight in WEIGHT_SPECS:
        total_return, mean_return, win_rate, max_dd = calc_metrics(label)
        log.info(
            "%s total=%.2f%% mean_daily=%.3f%% win=%.1f%% max_dd=%.2f%% holdings=%d"
            % (
                label,
                total_return,
                mean_return,
                win_rate,
                max_dd,
                len(g.virtual[label].get("positions") or {}),
            )
        )


def avg(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def pct(value, base):
    if base in (None, 0):
        return 0.0
    return (float(value) - float(base)) / float(base) * 100.0


def _safe_float(value, default=None):
    if value is None:
        return default
    try:
        result = float(value)
    except Exception:
        return default
    if math.isnan(result):
        return default
    return result


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _norm_percent_score(value):
    if 0.0 <= value <= 1.2:
        return _clamp(value, 0.0, 1.0)
    if 0.0 <= value <= 100.0:
        return _clamp(value / 100.0, 0.0, 1.0)
    return _clamp(value, 0.0, 1.0)
