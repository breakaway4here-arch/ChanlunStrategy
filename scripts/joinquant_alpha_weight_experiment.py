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


def debug_log(message):
    text = "[alpha_weight_exp] %s" % message
    try:
        log.info(text)
    except Exception:
        try:
            print(text)
        except Exception:
            pass


debug_log("module loaded")


def initialize(context):
    debug_log("initialize start current_dt=%s previous_date=%s" % (
        getattr(context, "current_dt", None),
        getattr(context, "previous_date", None),
    ))
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
    g.max_universe = 1800
    g.max_candidate_pool = 500
    g.min_history_bars = 61
    g.history_bars = 90
    g.min_proxy_score = 30.0
    g.main_source_min_score = 45.0
    g.top_k = 10
    g.selection_pool_size = 180
    g.retention_rank = 180
    g.exit_rank = 240
    g.exit_grace_rebalances = 2
    g.rebalance_every_n_days = 3
    g.real_trade_label = "alpha_1_5x"
    g.enable_real_trade = True
    g.min_money20 = 50000000.0
    g.qualified_money20 = 100000000.0
    g.high_money20 = 200000000.0
    g.min_market_cap = 30.0
    g.max_market_cap = 1200.0
    g.preferred_market_cap = 800.0
    g.min_pool_quality_score = 50.0
    g.prefer_growth_boards = True
    g.virtual_open_commission = 0.0003
    g.virtual_close_commission = 0.0003
    g.virtual_close_tax = 0.001
    g.summary_interval = 20
    g.day_count = 0
    g.last_targets = {}
    g.last_real_targets = []
    g.target_miss_counts = {}
    g.real_target_miss_counts = {}
    g.market_cap_by_code = {}
    g.circulating_cap_by_code = {}
    g.current_market_context = {}
    g.market_buy_scale = 1.0
    g.last_candidate_diag = {}
    g.last_rebalance_date = None
    g.debug_first_days = 5
    g.debug_history_fail_samples = []
    g.pending_pick_return_batches = []
    g.pick_return_stats = {}

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

    try:
        run_daily(rebalance, time="open")
        debug_log("scheduled run_daily at open")
    except Exception as exc:
        debug_log("run_daily schedule failed: %s" % exc)
    debug_log("initialize done start_cash=%.2f specs=%s" % (float(start_cash), [x[0] for x in WEIGHT_SPECS]))


def rebalance(context):
    current_dt = getattr(context, "current_dt", None)
    current_date = current_dt.date() if hasattr(current_dt, "date") else current_dt
    if getattr(g, "last_rebalance_date", None) == current_date:
        return
    g.last_rebalance_date = current_date
    g.day_count += 1
    if g.day_count <= getattr(g, "debug_first_days", 5) or g.day_count % getattr(g, "summary_interval", 20) == 0:
        debug_log("rebalance enter day=%s current_dt=%s previous_date=%s" % (
            g.day_count,
            current_dt,
            getattr(context, "previous_date", None),
        ))

    current_data = get_current_data()
    evaluate_pending_pick_returns(context, current_data)
    for label, _weight in WEIGHT_SPECS:
        update_virtual_equity(label, current_data)

    if g.day_count % g.summary_interval == 0:
        log_summary("summary day=%s" % g.day_count)

    if (g.day_count - 1) % g.rebalance_every_n_days != 0:
        debug_log("rebalance skipped by cadence day=%s every_n=%s" % (g.day_count, g.rebalance_every_n_days))
        return

    candidates = build_candidates(context)
    if not candidates:
        log.warn("No candidates on %s diag=%s" % (context.current_dt, g.last_candidate_diag))
        return
    if g.day_count <= getattr(g, "debug_first_days", 5):
        debug_log("candidate sample day=%s codes=%s diag=%s" % (
            g.day_count,
            [c.get("code") for c in candidates[:10]],
            g.last_candidate_diag,
        ))

    ranked_by_label = {}
    for label, weight in WEIGHT_SPECS:
        rows = []
        for candidate in candidates:
            score, trace = compute_weighted_score(candidate, weight)
            rows.append((score, candidate["code"], candidate, trace))
        rows.sort(key=lambda x: (-x[0], x[1]))
        ranked_by_label[label] = rows[: max(g.top_k, g.selection_pool_size, g.retention_rank, g.exit_rank)]

    for label, top_rows in ranked_by_label.items():
        previous_targets = g.last_targets.get(label) or []
        targets, kept_count = select_targets_with_retention(label, top_rows, previous_targets)
        rebalance_virtual_portfolio(label, targets, current_data)
        g.last_targets[label] = targets
        if label == g.real_trade_label:
            debug_log(
                "virtual targets %s kept=%s replaced=%s targets=%s"
                % (label, kept_count, max(0, len(targets) - kept_count), targets)
            )

    if g.enable_real_trade:
        trade_real_portfolio(context, ranked_by_label.get(g.real_trade_label, []), current_data)

    log_top_candidates(ranked_by_label)

    try:
        record(
            base=value_ratio("baseline"),
            a10=value_ratio("alpha_1_0x"),
            a12=value_ratio("alpha_1_2x"),
            a15=value_ratio("alpha_1_5x"),
            a18=value_ratio("alpha_1_8x"),
        )
    except Exception:
        pass


def handle_data(context, data):
    if not hasattr(g, "virtual"):
        return
    rebalance(context)


def build_candidates(context):
    g.debug_history_fail_samples = []
    diag = {
        "universe": 0,
        "index_universe": 0,
        "tradable_universe": 0,
        "cap_universe": 0,
        "history_ok": 0,
        "proxy_candidates": 0,
        "source_candidates": 0,
        "drop_no_history": 0,
        "drop_short_history": 0,
        "drop_bad_close": 0,
        "drop_low_proxy_score": 0,
        "drop_low_liquidity": 0,
        "drop_low_pool_quality": 0,
        "drop_no_source": 0,
    }
    universe = get_base_universe(context)
    base_diag = getattr(g, "last_universe_diag", {})
    diag.update(base_diag)
    diag["universe"] = len(universe)
    market = calc_market_context(context, universe)
    g.current_market_context = market
    g.market_buy_scale = calc_market_buy_scale(market)
    diag["market_buy_scale"] = g.market_buy_scale
    raw_candidates = []

    for code in universe:
        item = build_candidate_item(context, code, diag)
        if not item:
            continue
        raw_candidates.append(item)
    diag["proxy_candidates"] = len(raw_candidates)
    raw_candidates.sort(
        key=lambda x: (
            -x.get("pool_quality_score", 0.0),
            -x.get("universe_growth_score", 0.0),
            -x.get("score", 0.0),
            x.get("code", ""),
        )
    )
    max_candidate_pool = int(getattr(g, "max_candidate_pool", 0) or 0)
    if max_candidate_pool > 0:
        raw_candidates = raw_candidates[:max_candidate_pool]
    diag["growth_pool_candidates"] = len(raw_candidates)

    attach_sector_strength(context, raw_candidates)

    candidates = []
    for item in raw_candidates:
        sources, by_source = infer_sources(item)
        if not sources:
            diag["drop_no_source"] += 1
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

    diag["source_candidates"] = len(candidates)
    if g.debug_history_fail_samples:
        diag["history_fail_samples"] = list(g.debug_history_fail_samples[:5])
    g.last_candidate_diag = diag
    if getattr(g, "day_count", 0) <= getattr(g, "debug_first_days", 5):
        debug_log("build_candidates diag=%s" % diag)
    return candidates


def get_base_universe(context):
    date = context.previous_date
    diag = {"index_universe": 0, "tradable_universe": 0, "cap_universe": 0}
    try:
        stocks = list(get_index_stocks(g.index_code, date=date))
        debug_log("get_index_stocks index=%s date=%s n=%s" % (g.index_code, date, len(stocks)))
    except Exception as exc:
        debug_log("get_index_stocks failed index=%s date=%s err=%s; fallback all securities" % (g.index_code, date, exc))
        stocks = list(get_all_securities(["stock"], date=date).index)
    diag["index_universe"] = len(stocks)

    stocks = filter_current_tradable(stocks, context)
    diag["tradable_universe"] = len(stocks)
    stocks = filter_by_market_cap(stocks, context)
    diag["cap_universe"] = len(stocks)
    result = stocks[: g.max_universe]
    diag["universe"] = len(result)
    g.last_universe_diag = diag
    if getattr(g, "day_count", 0) <= getattr(g, "debug_first_days", 5):
        debug_log("universe diag=%s sample=%s" % (diag, result[:10]))
    return result


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
        if cd is not None and getattr(cd, "paused", False):
            continue
        if cd is not None and getattr(cd, "is_st", False):
            continue
        name = getattr(cd, "name", "") or ""
        if not name and securities is not None and code in securities.index:
            try:
                name = securities.loc[code, "display_name"]
            except Exception:
                name = ""
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
            query(valuation.code, valuation.market_cap, valuation.circulating_market_cap)
            .filter(
                valuation.code.in_(stocks),
                valuation.market_cap >= float(getattr(g, "min_market_cap", 20.0)),
                valuation.market_cap <= float(getattr(g, "max_market_cap", 1200.0)),
            )
        )
        df = get_fundamentals(q, date=context.previous_date)
        if df is not None and len(df) > 0:
            market_cap_by_code = {}
            circulating_cap_by_code = {}
            for _idx, row in df.iterrows():
                code = row["code"]
                market_cap_by_code[code] = _safe_float(row.get("market_cap"), 0.0) or 0.0
                circulating_cap_by_code[code] = _safe_float(row.get("circulating_market_cap"), 0.0) or 0.0
            g.market_cap_by_code = market_cap_by_code
            g.circulating_cap_by_code = circulating_cap_by_code
            ranked = list(df["code"])
            ranked.sort(
                key=lambda code: (
                    -calc_static_universe_preference(code, market_cap_by_code.get(code)),
                    code,
                )
            )
            return ranked
    except Exception as exc:
        log.warn("market_cap filter fallback: %s" % exc)
        g.market_cap_by_code = {}
        g.circulating_cap_by_code = {}
    return stocks[: g.max_universe]


def calc_static_universe_preference(code, market_cap):
    cap = _safe_float(market_cap)
    score = board_growth_bonus(code)
    if cap is None or cap <= 0:
        return score
    if 30.0 <= cap <= 300.0:
        score += 30.0
    elif 300.0 < cap <= 800.0:
        score += 18.0
    elif 800.0 < cap <= 1200.0:
        score += 6.0
    elif 20.0 <= cap < 30.0:
        score += 10.0
    return score


def board_growth_bonus(code):
    if not getattr(g, "prefer_growth_boards", True):
        return 0.0
    raw = str(code or "")
    if raw.startswith("300") or raw.startswith("301"):
        return 25.0
    if raw.startswith("688") or raw.startswith("689"):
        return 15.0
    if raw.startswith("002"):
        return 8.0
    return 0.0


def get_market_cap(code):
    try:
        return _safe_float((getattr(g, "market_cap_by_code", {}) or {}).get(code), 0.0) or 0.0
    except Exception:
        return 0.0


def get_circulating_market_cap(code):
    try:
        return _safe_float((getattr(g, "circulating_cap_by_code", {}) or {}).get(code), 0.0) or 0.0
    except Exception:
        return 0.0


def calc_liquidity_score(money20):
    liquidity = _safe_float(money20, 0.0) or 0.0
    if liquidity >= float(getattr(g, "high_money20", 200000000.0)):
        return 100.0
    if liquidity >= float(getattr(g, "qualified_money20", 100000000.0)):
        return 75.0 + min(20.0, (liquidity - 100000000.0) / 100000000.0 * 20.0)
    if liquidity >= float(getattr(g, "min_money20", 50000000.0)):
        return 50.0 + min(20.0, (liquidity - 50000000.0) / 50000000.0 * 20.0)
    if liquidity >= 30000000.0:
        return min(35.0, (liquidity - 30000000.0) / 20000000.0 * 35.0)
    return 0.0


def calc_market_cap_score(market_cap):
    cap = _safe_float(market_cap, 0.0) or 0.0
    if 30.0 <= cap <= 300.0:
        return 100.0
    if 300.0 < cap <= float(getattr(g, "preferred_market_cap", 800.0)):
        return 70.0
    if float(getattr(g, "preferred_market_cap", 800.0)) < cap <= float(getattr(g, "max_market_cap", 1200.0)):
        return 35.0
    return 0.0


def calc_momentum_quality_score(ret20, ret60, volume_ratio, range_pos20):
    score = 0.0
    r20 = _safe_float(ret20, 0.0) or 0.0
    r60 = _safe_float(ret60, 0.0) or 0.0
    vol = _safe_float(volume_ratio, 0.0) or 0.0
    pos = _safe_float(range_pos20, 0.0) or 0.0
    if 3.0 <= r20 <= 45.0:
        score += 45.0
    elif 0.0 < r20 < 3.0:
        score += 20.0
    elif 45.0 < r20 <= 60.0:
        score += 12.0
    if 8.0 <= r60 <= 100.0:
        score += 20.0
    if 1.05 <= vol <= 3.0:
        score += 20.0
    elif 1.0 <= vol < 1.05:
        score += 8.0
    if pos >= 0.75:
        score += 15.0
    elif pos >= 0.65:
        score += 8.0
    return _clamp(score, 0.0, 100.0)


def calc_pool_quality_score(code, market_cap, money20, ret20, ret60, volume_ratio, range_pos20):
    liquidity_score = calc_liquidity_score(money20)
    market_cap_score = calc_market_cap_score(market_cap)
    board_score = min(100.0, board_growth_bonus(code) * 4.0)
    momentum_score = calc_momentum_quality_score(ret20, ret60, volume_ratio, range_pos20)
    score = (
        liquidity_score * 0.35
        + market_cap_score * 0.30
        + board_score * 0.15
        + momentum_score * 0.20
    )
    return {
        "pool_quality_score": round(score, 4),
        "liquidity_score": round(liquidity_score, 4),
        "market_cap_score": round(market_cap_score, 4),
        "board_growth_score": round(board_score, 4),
        "momentum_quality_score": round(momentum_score, 4),
    }


def calc_universe_growth_score(code, market_cap, money20, ret20, ret60, volume_ratio, range_pos20):
    score = calc_static_universe_preference(code, market_cap)
    cap = _safe_float(market_cap)
    if cap is not None and cap > 0:
        if 30.0 <= cap <= 300.0:
            score += 12.0
        elif 300.0 < cap <= 800.0:
            score += 6.0

    liquidity = _safe_float(money20, 0.0) or 0.0
    if liquidity >= 200000000.0:
        score += 10.0
    elif liquidity >= 100000000.0:
        score += 7.0
    elif liquidity >= 50000000.0:
        score += 4.0

    r20 = _safe_float(ret20, 0.0) or 0.0
    r60 = _safe_float(ret60, 0.0) or 0.0
    vol = _safe_float(volume_ratio, 0.0) or 0.0
    pos = _safe_float(range_pos20, 0.0) or 0.0
    if 3.0 <= r20 <= 45.0:
        score += min(20.0, r20 * 0.8)
    if 8.0 <= r60 <= 100.0:
        score += min(15.0, r60 * 0.25)
    if 1.1 <= vol <= 3.0:
        score += 10.0
    elif 1.0 <= vol < 1.1:
        score += 4.0
    if pos >= 0.75:
        score += 8.0
    elif pos >= 0.65:
        score += 5.0
    return round(score, 4)


def get_daily_history(context, code, count, fields):
    end_date = getattr(context, "previous_date", None)
    try:
        hist = get_price(
            code,
            count=count,
            end_date=end_date,
            frequency="daily",
            fields=fields,
            skip_paused=True,
            fq="pre",
            panel=False,
        )
        if hist is not None and len(hist) > 0:
            return hist
    except Exception as exc:
        remember_history_fail(code, "get_price:%s" % exc)

    try:
        return attribute_history(
            code,
            count,
            unit="1d",
            fields=fields,
            skip_paused=True,
            df=True,
        )
    except Exception as exc:
        remember_history_fail(code, "attribute_history:%s" % exc)
        return None


def build_candidate_item(context, code, diag=None):
    fields = ["open", "close", "high", "low", "volume", "money"]
    hist = get_daily_history(context, code, g.history_bars, fields)
    if hist is None:
        inc_diag(diag, "drop_no_history")
        return None

    if len(hist) < g.min_history_bars:
        inc_diag(diag, "drop_short_history")
        return None

    try:
        closes = [float(x) for x in list(hist["close"])]
        highs = [float(x) for x in list(hist["high"])]
        lows = [float(x) for x in list(hist["low"])]
        volumes = [float(x) for x in list(hist["volume"])]
        money = [float(x) for x in list(hist["money"])]
    except Exception:
        inc_diag(diag, "drop_no_history")
        return None

    if not closes or closes[-1] <= 0:
        inc_diag(diag, "drop_bad_close")
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
    if money20 < float(getattr(g, "min_money20", 0.0)):
        inc_diag(diag, "drop_low_liquidity")
        return None
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

    inc_diag(diag, "history_ok")
    if score < float(getattr(g, "min_proxy_score", 24.0)):
        inc_diag(diag, "drop_low_proxy_score")
        return None
    market_cap = get_market_cap(code)
    circulating_market_cap = get_circulating_market_cap(code)
    pool_quality = calc_pool_quality_score(
        code=code,
        market_cap=market_cap,
        money20=money20,
        ret20=ret20,
        ret60=ret60,
        volume_ratio=volume_ratio,
        range_pos20=range_pos20,
    )
    if pool_quality["pool_quality_score"] < float(getattr(g, "min_pool_quality_score", 0.0)):
        inc_diag(diag, "drop_low_pool_quality")
        return None
    universe_growth_score = calc_universe_growth_score(
        code=code,
        market_cap=market_cap,
        money20=money20,
        ret20=ret20,
        ret60=ret60,
        volume_ratio=volume_ratio,
        range_pos20=range_pos20,
    )

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
        "market_cap": market_cap,
        "circulating_market_cap": circulating_market_cap,
        "universe_growth_score": universe_growth_score,
        "pool_quality_score": pool_quality["pool_quality_score"],
        "liquidity_score": pool_quality["liquidity_score"],
        "market_cap_score": pool_quality["market_cap_score"],
        "board_growth_score": pool_quality["board_growth_score"],
        "momentum_quality_score": pool_quality["momentum_quality_score"],
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

    if item["score"] >= float(getattr(g, "main_source_min_score", 40.0)):
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

    if not sources and item["score"] >= float(getattr(g, "min_proxy_score", 24.0)):
        sources.append("baseline")
        by_source["baseline"] = dict(item)

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
            hist = get_daily_history(context, code, 60, ["close"])
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
            hist = get_daily_history(context, code, 30, ["close"])
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


def calc_market_buy_scale(market):
    regime = _safe_float((market or {}).get("market_regime_factor"), 50.0) or 50.0
    breadth = _safe_float((market or {}).get("breadth_score"), 50.0) or 50.0
    index_trend = _safe_float((market or {}).get("index_trend_score"), 50.0) or 50.0
    if regime < 38.0 and breadth < 42.0:
        return 0.25
    if regime < 45.0 or (breadth < 45.0 and index_trend < 48.0):
        return 0.5
    return 1.0


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
    growth_bonus = calc_universe_growth_bonus(item)
    if alpha_weight is None:
        adjusted_score = max(0, int(round(score + growth_bonus * 0.5)))
        trace = dict(trace)
        trace["universe_growth_bonus"] = round(growth_bonus * 0.5, 4)
        trace["opportunity_score"] = adjusted_score
        return adjusted_score, trace

    base = trace["base_opportunity_score"]
    bonus = trace["alpha_bonus"] * alpha_weight
    multiplier = 1.0 + (trace["alpha_multiplier"] - 1.0) * alpha_weight
    weighted_score = max(0, int(round(base * multiplier + bonus + growth_bonus)))
    trace = dict(trace)
    trace["alpha_weight"] = alpha_weight
    trace["weighted_alpha_bonus"] = round(bonus, 4)
    trace["weighted_alpha_multiplier"] = round(multiplier, 4)
    trace["universe_growth_bonus"] = round(growth_bonus, 4)
    trace["opportunity_score"] = weighted_score
    return weighted_score, trace


def calc_universe_growth_bonus(item):
    growth_score = _safe_float(item.get("universe_growth_score"), 0.0) or 0.0
    if growth_score <= 0:
        return 0.0
    return _clamp(growth_score / 12.0, 0.0, 8.0)


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
    pool_quality = {
        "pool_quality_score": _safe_float(item.get("pool_quality_score")),
        "liquidity_score": _safe_float(item.get("liquidity_score")),
        "market_cap_score": _safe_float(item.get("market_cap_score")),
        "board_growth_score": _safe_float(item.get("board_growth_score")),
        "momentum_quality_score": _safe_float(item.get("momentum_quality_score")),
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
        "pool_quality": pool_quality,
    }


def _score_alpha_bonus(alpha_features, by_source, source, item, metrics):
    bonus = 0.0
    bonus += _score_market_regime_bonus(alpha_features.get("market_regime_factor") or {})
    bonus += _score_sector_strength_bonus(alpha_features.get("sector_strength_factor") or {})
    bonus += _score_momentum_persistence_bonus(alpha_features.get("momentum_persistence"), item, source)
    bonus += _score_breakout_quality_bonus(alpha_features.get("breakout_quality") or {}, by_source, source, item, metrics)
    bonus += _score_pool_quality_bonus(alpha_features.get("pool_quality") or {})
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


def _score_pool_quality_bonus(features):
    liquidity = _safe_float(features.get("liquidity_score"), 0.0) or 0.0
    market_cap = _safe_float(features.get("market_cap_score"), 0.0) or 0.0
    board = _safe_float(features.get("board_growth_score"), 0.0) or 0.0
    momentum = _safe_float(features.get("momentum_quality_score"), 0.0) or 0.0
    quality = _safe_float(features.get("pool_quality_score"), 0.0) or 0.0
    if liquidity < 50.0 or market_cap < 35.0:
        return 0.0
    core = liquidity * 0.35 + market_cap * 0.35 + board * 0.10 + momentum * 0.20
    if quality >= 75.0 and liquidity >= 70.0 and market_cap >= 70.0:
        return _clamp(core / 100.0 * 2.2, 0.0, 2.2)
    if quality >= 60.0 and liquidity >= 55.0 and market_cap >= 55.0:
        return _clamp(core / 100.0 * 1.4, 0.0, 1.4)
    if quality >= 50.0:
        return _clamp(core / 100.0 * 0.6, 0.0, 0.6)
    return 0.0


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


def select_targets_with_retention(label, top_rows, previous_targets):
    top_k = int(getattr(g, "top_k", 10))
    retention_rank = int(getattr(g, "retention_rank", getattr(g, "selection_pool_size", top_k)))
    retention_rank = max(top_k, retention_rank)
    exit_rank = int(getattr(g, "exit_rank", retention_rank))
    exit_rank = max(retention_rank, exit_rank)
    exit_grace = max(1, int(getattr(g, "exit_grace_rebalances", 1)))
    retention_codes = set([row[1] for row in top_rows[:retention_rank]])
    exit_codes = set([row[1] for row in top_rows[:exit_rank]])
    miss_counts_by_label = getattr(g, "target_miss_counts", {})
    miss_counts = miss_counts_by_label.setdefault(label, {})
    g.target_miss_counts = miss_counts_by_label
    selected = []

    for code in previous_targets or []:
        if code in retention_codes:
            miss_counts[code] = 0
            if code not in selected:
                selected.append(code)
        elif code in exit_codes:
            miss_counts[code] = int(miss_counts.get(code, 0) or 0) + 1
            if miss_counts[code] < exit_grace and code not in selected:
                selected.append(code)
        else:
            miss_counts.pop(code, None)
        if len(selected) >= top_k:
            break

    kept_count = len(selected)
    for _score, code, _candidate, _trace in top_rows:
        if len(selected) >= top_k:
            break
        if code not in selected:
            miss_counts[code] = 0
            selected.append(code)

    active_codes = set(selected)
    for code in list(miss_counts.keys()):
        if code not in active_codes:
            miss_counts.pop(code, None)

    if len(selected) < top_k:
        debug_log("target shortfall label=%s selected=%s pool=%s" % (label, len(selected), len(top_rows)))
    return selected[:top_k], kept_count


def rebalance_virtual_portfolio(label, targets, current_data):
    portfolio = g.virtual[label]
    cash = float(portfolio.get("cash") or 0.0)
    positions = {}
    target_count = len(targets)
    if target_count <= 0:
        equity = calc_virtual_equity(portfolio, current_data)
        portfolio["cash"] = equity
        portfolio["positions"] = {}
        return

    target_set = set(targets)
    for code, shares in list((portfolio.get("positions") or {}).items()):
        price = get_trade_price(code, current_data)
        if price is None or price <= 0:
            continue
        value = float(shares) * price
        if code in target_set:
            positions[code] = float(shares)
        else:
            close_cost = value * (
                float(getattr(g, "virtual_close_commission", 0.0))
                + float(getattr(g, "virtual_close_tax", 0.0))
            )
            cash += max(0.0, value - close_cost)

    missing_targets = [code for code in targets if code not in positions]
    buy_scale = get_market_buy_scale()
    deploy_cash = cash * buy_scale
    if missing_targets and deploy_cash > 0:
        buy_budget = deploy_cash / float(len(missing_targets))
    else:
        buy_budget = 0.0

    for code in missing_targets:
        price = get_trade_price(code, current_data)
        if price is None or price <= 0:
            continue
        gross_value = min(cash, buy_budget)
        open_cost_rate = float(getattr(g, "virtual_open_commission", 0.0))
        shares = gross_value / (price * (1.0 + open_cost_rate)) if gross_value > 0 else 0.0
        if shares <= 0:
            continue
        used = shares * price * (1.0 + open_cost_rate)
        if used > cash + 0.0001:
            continue
        positions[code] = shares
        cash -= used
    portfolio["positions"] = positions
    portfolio["cash"] = max(0.0, cash)


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
    targets = select_real_trade_targets(context, top_rows, current_data)
    track_pick_return_batch(context, g.real_trade_label, targets, current_data, "real_targets")
    target_set = set(targets)
    for code in list(context.portfolio.positions.keys()):
        if code not in target_set:
            submit_target_value_order(code, 0, current_data, side="sell")

    if not targets:
        g.last_real_targets = []
        return
    current_positions = set(context.portfolio.positions.keys())
    new_targets = [code for code in targets if code not in current_positions or get_position_amount(context, code) <= 0]
    if not new_targets:
        g.last_real_targets = list(targets)
        debug_log("real targets %s %s no_new_targets" % (g.real_trade_label, targets))
        return

    available_cash = get_available_cash(context)
    buy_scale = get_market_buy_scale()
    target_value = available_cash * 0.98 * buy_scale / float(len(new_targets)) if available_cash > 0 else 0.0
    for code in new_targets:
        cd = current_data_for(current_data, code)
        if cd is None or getattr(cd, "paused", False):
            continue
        price = get_trade_price(code, current_data)
        high_limit = getattr(cd, "high_limit", None)
        if high_limit is not None and price is not None and price >= high_limit * 0.999:
            continue
        if not can_open_target_value(code, target_value, price, context):
            debug_log("skip open %s target=%.2f price=%.2f min_shares=%s" % (
                code,
                target_value,
                price,
                min_buy_shares(code),
            ))
            continue
        if not can_submit_target_adjustment(code, target_value, price, context):
            debug_log("skip small adjustment %s target=%.2f price=%.2f min_shares=%s" % (
                code,
                target_value,
                price,
                min_buy_shares(code),
            ))
            continue
        submit_target_value_order(code, target_value, current_data, side="buy")
    g.last_real_targets = list(targets)
    debug_log(
        "real targets %s kept=%s new=%s cash=%.2f buy_scale=%.2f targets=%s"
        % (g.real_trade_label, len(targets) - len(new_targets), len(new_targets), available_cash, buy_scale, targets)
    )


def select_real_trade_targets(context, top_rows, current_data):
    current_positions = set(context.portfolio.positions.keys())
    portfolio_value = context.portfolio.total_value
    target_value = portfolio_value / float(max(1, g.top_k))
    retention_rank = int(getattr(g, "retention_rank", getattr(g, "selection_pool_size", g.top_k)))
    retention_rank = max(int(g.top_k), retention_rank)
    exit_rank = int(getattr(g, "exit_rank", retention_rank))
    exit_rank = max(retention_rank, exit_rank)
    exit_grace = max(1, int(getattr(g, "exit_grace_rebalances", 1)))
    retention_codes = set([row[1] for row in top_rows[:retention_rank]])
    exit_codes = set([row[1] for row in top_rows[:exit_rank]])
    miss_counts = getattr(g, "real_target_miss_counts", {}) or {}
    previous_targets = []
    for code in list(getattr(g, "last_real_targets", []) or []) + list(current_positions):
        if code not in previous_targets:
            previous_targets.append(code)

    selected = []
    for code in previous_targets:
        if len(selected) >= g.top_k:
            break
        if code in selected:
            continue
        if code in retention_codes:
            miss_counts[code] = 0
            if can_hold_real_target(code, current_data):
                selected.append(code)
        elif code in exit_codes:
            miss_counts[code] = int(miss_counts.get(code, 0) or 0) + 1
            if miss_counts[code] < exit_grace and can_hold_real_target(code, current_data):
                selected.append(code)
        else:
            miss_counts.pop(code, None)

    kept_count = len(selected)
    for _score, code, _candidate, _trace in top_rows:
        if len(selected) >= g.top_k:
            break
        if code in selected:
            continue
        miss_counts[code] = 0
        cd = current_data_for(current_data, code)
        if cd is None or getattr(cd, "paused", False):
            continue
        price = get_trade_price(code, current_data)
        if price is None or price <= 0:
            continue
        high_limit = getattr(cd, "high_limit", None)
        if high_limit is not None and price >= high_limit * 0.999:
            continue
        if code not in current_positions and not can_open_target_value(code, target_value, price, context):
            continue
        selected.append(code)
    active_codes = set(selected)
    for code in list(miss_counts.keys()):
        if code not in active_codes:
            miss_counts.pop(code, None)
    g.real_target_miss_counts = miss_counts
    if len(selected) < g.top_k:
        debug_log("real target shortfall label=%s selected=%s pool=%s" % (
            g.real_trade_label,
            len(selected),
            len(top_rows),
        ))
    debug_log(
        "real retention label=%s kept=%s replaced=%s retention_rank=%s exit_rank=%s grace=%s"
        % (g.real_trade_label, kept_count, max(0, len(selected) - kept_count), retention_rank, exit_rank, exit_grace)
    )
    return selected


def can_hold_real_target(code, current_data):
    cd = current_data_for(current_data, code)
    if cd is not None and getattr(cd, "paused", False):
        return True
    price = get_trade_price(code, current_data)
    return price is not None and price > 0


def submit_target_value_order(code, target_value, current_data, side):
    price = get_trade_price(code, current_data)
    style = build_order_style(code, price, current_data, side)
    try:
        if style is None:
            return order_target_value(code, target_value)
        return order_target_value(code, target_value, style=style)
    except TypeError:
        return order_target_value(code, target_value)


def build_order_style(code, price, current_data, side):
    if not is_star_market(code) or price is None or price <= 0:
        return None
    cd = current_data_for(current_data, code)
    if cd is None:
        return None
    if side == "buy":
        limit_price = price * 1.02
        high_limit = _safe_float(getattr(cd, "high_limit", None))
        if high_limit is not None and high_limit > 0:
            limit_price = min(limit_price, high_limit)
    else:
        limit_price = price * 0.98
        low_limit = _safe_float(getattr(cd, "low_limit", None))
        if low_limit is not None and low_limit > 0:
            limit_price = max(limit_price, low_limit)
    try:
        return LimitOrderStyle(round(limit_price, 2))
    except Exception:
        return None


def can_open_target_value(code, target_value, price, context):
    if price is None or price <= 0:
        return False
    current_amount = get_position_amount(context, code)
    if current_amount and current_amount > 0:
        return True
    return target_value >= price * min_buy_shares(code)


def can_submit_target_adjustment(code, target_value, price, context):
    current_amount = get_position_amount(context, code)
    if not current_amount or current_amount <= 0:
        return True
    current_value = current_amount * price
    delta_value = target_value - current_value
    if delta_value <= 0:
        return True
    return delta_value >= price * min_buy_shares(code)


def get_position_amount(context, code):
    try:
        positions = context.portfolio.positions
        if code not in positions:
            return 0.0
        position = positions[code]
    except Exception:
        return 0.0
    return _safe_float(getattr(position, "total_amount", 0), 0.0) or 0.0


def get_available_cash(context):
    for field in ("available_cash", "cash"):
        value = _safe_float(getattr(context.portfolio, field, None))
        if value is not None:
            return max(0.0, value)
    return 0.0


def get_market_buy_scale():
    value = _safe_float(getattr(g, "market_buy_scale", 1.0), 1.0)
    if value is None:
        return 1.0
    return _clamp(value, 0.0, 1.0)


def min_buy_shares(code):
    if is_star_market(code):
        return 200
    return 100


def is_star_market(code):
    raw = str(code or "")
    return raw.endswith(".XSHG") and (raw.startswith("688") or raw.startswith("689"))


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


def track_pick_return_batch(context, label, targets, current_data, source):
    if not targets:
        return
    signal_date = _date_text(getattr(context, "current_dt", None))
    entries = []
    seen = set()
    for code in targets:
        if code in seen:
            continue
        seen.add(code)
        price = get_trade_price(code, current_data)
        if price is None or price <= 0:
            continue
        entries.append({"code": code, "entry_price": float(price)})
    if not entries:
        return

    g.pending_pick_return_batches.append({
        "label": label,
        "source": source,
        "signal_date": signal_date,
        "entries": entries,
    })
    debug_log(
        "next_day_return_track label=%s source=%s signal_date=%s n=%s targets=%s"
        % (label, source, signal_date, len(entries), [row["code"] for row in entries])
    )


def evaluate_pending_pick_returns(context, current_data):
    pending = list(getattr(g, "pending_pick_return_batches", []) or [])
    if not pending:
        return

    eval_date = _date_text(getattr(context, "current_dt", None))
    remaining = []
    for batch in pending:
        signal_date = str(batch.get("signal_date") or "")
        if signal_date == eval_date:
            remaining.append(batch)
            continue

        label = batch.get("label") or "unknown"
        source = batch.get("source") or "unknown"
        returns = []
        missing = 0
        for entry in batch.get("entries") or []:
            code = entry.get("code")
            entry_price = _safe_float(entry.get("entry_price"))
            exit_price = get_trade_price(code, current_data)
            if entry_price is None or entry_price <= 0 or exit_price is None or exit_price <= 0:
                missing += 1
                continue
            return_pct = calc_adjusted_next_day_return(code, signal_date, eval_date, entry_price, exit_price)
            returns.append((code, return_pct))

        if not returns:
            debug_log(
                "next_day_return label=%s source=%s signal_date=%s eval_date=%s n=0 missing=%s"
                % (label, source, signal_date, eval_date, missing)
            )
            continue

        values = [row[1] for row in returns]
        up_count = sum(1 for value in values if value > 0)
        down_count = sum(1 for value in values if value < 0)
        flat_count = len(values) - up_count - down_count
        win_rate = up_count / float(len(values)) * 100.0
        mean_return = avg(values)
        median_return = median_value(values)
        best = max(returns, key=lambda row: row[1])
        worst = min(returns, key=lambda row: row[1])

        update_pick_return_stats(label, values, up_count, down_count, flat_count)
        log.info(
            "[alpha_weight_exp] next_day_return label=%s source=%s signal_date=%s eval_date=%s "
            "n=%d up=%d down=%d flat=%d win=%.1f%% avg=%.2f%% median=%.2f%% "
            "best=%s:%.2f%% worst=%s:%.2f%% missing=%d"
            % (
                label,
                source,
                signal_date,
                eval_date,
                len(values),
                up_count,
                down_count,
                flat_count,
                win_rate,
                mean_return,
                median_return,
                best[0],
                best[1],
                worst[0],
                worst[1],
                missing,
            )
        )
    g.pending_pick_return_batches = remaining


def calc_adjusted_next_day_return(code, signal_date, eval_date, entry_price, exit_price):
    try:
        hist = get_price(
            code,
            start_date=signal_date,
            end_date=eval_date,
            frequency="daily",
            fields=["open"],
            skip_paused=False,
            fq="pre",
            panel=False,
        )
        if hist is not None and len(hist) >= 2:
            opens = [float(x) for x in list(hist["open"])]
            start_open = opens[0]
            end_open = opens[-1]
            if start_open > 0 and end_open > 0:
                return pct(end_open, start_open)
    except Exception:
        pass
    return pct(exit_price, entry_price)


def update_pick_return_stats(label, values, up_count, down_count, flat_count):
    stats = g.pick_return_stats.get(label)
    if not stats:
        stats = {
            "batches": 0,
            "stocks": 0,
            "up": 0,
            "down": 0,
            "flat": 0,
            "return_sum": 0.0,
            "returns": [],
        }
        g.pick_return_stats[label] = stats
    stats["batches"] += 1
    stats["stocks"] += len(values)
    stats["up"] += up_count
    stats["down"] += down_count
    stats["flat"] += flat_count
    stats["return_sum"] += sum(values)
    stats["returns"].extend(values)


def log_pick_return_summary():
    stats_by_label = getattr(g, "pick_return_stats", {}) or {}
    for label in sorted(stats_by_label.keys()):
        stats = stats_by_label[label]
        values = stats.get("returns") or []
        if not values:
            continue
        best = max(values)
        worst = min(values)
        win_rate = stats.get("up", 0) / float(len(values)) * 100.0
        mean_return = avg(values)
        median_return = median_value(values)
        log.info(
            "[alpha_weight_exp] next_day_return_summary label=%s batches=%d stocks=%d "
            "up=%d down=%d flat=%d win=%.1f%% avg=%.2f%% median=%.2f%% best=%.2f%% worst=%.2f%%"
            % (
                label,
                stats.get("batches", 0),
                len(values),
                stats.get("up", 0),
                stats.get("down", 0),
                stats.get("flat", 0),
                win_rate,
                mean_return,
                median_return,
                best,
                worst,
            )
        )


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
    log_pick_return_summary()


def avg(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def median_value(values):
    numeric = sorted([float(x) for x in values if x is not None])
    if not numeric:
        return 0.0
    middle = len(numeric) // 2
    if len(numeric) % 2:
        return numeric[middle]
    return (numeric[middle - 1] + numeric[middle]) / 2.0


def _date_text(value):
    if hasattr(value, "date"):
        return str(value.date())
    return str(value)


def inc_diag(diag, key):
    if isinstance(diag, dict):
        diag[key] = int(diag.get(key) or 0) + 1


def remember_history_fail(code, reason):
    try:
        samples = getattr(g, "debug_history_fail_samples", None)
        if isinstance(samples, list) and len(samples) < 5:
            samples.append("%s:%s" % (code, reason))
    except Exception:
        pass


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
