"""
强势启动候选检测 — 日线放量突破 + 30min确认升级。

独立于底背驰通道，从原始 chan_results 扫描，避免涨停/无买点但已启动的票被提前过滤。
"""

import numpy as np
import config
from .data_fetcher import is_st_stock
from .market_sentiment import classify_price_limit
from .sublevel_confirm import (
    STRONG_STARTUP_BUY_POINT_TYPES,
    build_30min_confirmation_evidence,
)


def build_strong_startup_pool(chan_results, sector_stocks=None):
    """Scan raw daily chan_results for strong startup signals.

    Returns:
        (startup_seeds, startup_watchlist, diag)
          startup_seeds: list of non-limit-up startup seeds ready for 30min upgrade
          startup_watchlist: list of limit-up startup watch items (no 30min needed today)
          diag: diagnostics dict
    """
    if not config.ENABLE_STRONG_STARTUP_CANDIDATES:
        return [], [], {"scanned": 0, "enabled": False}

    seeds = []
    watchlist = []
    diag = {
        "scanned": len(chan_results),
        "enabled": True,
        "daily_startup_seed": 0,
        "dropped_high_position": 0,
        "dropped_no_volume": 0,
        "dropped_no_breakout": 0,
        "dropped_base_filter": 0,
        "watch_due_to_limit_up": 0,
    }

    for result in chan_results:
        if result is None:
            continue

        code = result.code
        name = result.name
        sector_name = sector_stocks.get(code, {}).get("sector", "") if sector_stocks else ""
        price_basis = (
            dict(sector_stocks.get(code, {}).get("price_basis") or {})
            if sector_stocks else {}
        )
        closes = result.closes
        opens = result.opens
        highs = result.highs
        lows = result.lows
        volumes = result.volumes
        dates = result.dates if hasattr(result, 'dates') else []

        # --- Base filters ---
        if is_st_stock(name):
            diag["dropped_base_filter"] += 1
            continue
        if closes is None or len(closes) < max(60, config.MIN_LISTED_DAYS):
            diag["dropped_base_filter"] += 1
            continue

        price_limit_state = "invalid"
        if len(closes) >= 2:
            prev_close = closes[-2]
            curr_close = closes[-1]
            if prev_close > 0:
                price_limit_state = classify_price_limit({
                    "code": code,
                    "name": name,
                    "prev_close": prev_close,
                    "close": curr_close,
                })
                if price_limit_state == "limit_down":
                    diag["dropped_base_filter"] += 1
                    continue

        # Liquidity
        if len(volumes) >= 5 and len(closes) >= 5:
            amounts = volumes[-5:] * closes[-5:] * 100
            if np.mean(amounts) < config.MIN_DAILY_AMOUNT:
                diag["dropped_base_filter"] += 1
                continue

        # --- Step 1: 日线低位检测 ---
        is_low = _check_low_position(
            closes, highs, lows,
            config.STRONG_STARTUP_LOW_POSITION_60D_RATIO,
            config.STRONG_STARTUP_LOW_POSITION_120D_RATIO,
            config.STRONG_STARTUP_PRE_START_LOW_RATIO,
        )
        if not is_low:
            diag["dropped_high_position"] += 1
            continue

        # --- Step 2: 放量检测 ---
        is_volume_ok = _check_volume_breakout(volumes, closes, config.STRONG_STARTUP_MIN_VOLUME_RATIO)
        if not is_volume_ok:
            diag["dropped_no_volume"] += 1
            continue

        # --- Step 3: 价格启动检测 ---
        startup_signals = _check_price_breakout(
            closes, opens, highs, config.STRONG_STARTUP_MIN_CHANGE_PCT
        )
        if len(startup_signals) < 2:
            diag["dropped_no_breakout"] += 1
            continue

        # --- Build startup seed ---
        curr_close = float(closes[-1])
        prev_close_val = float(closes[-2]) if len(closes) >= 2 else curr_close
        change_pct = (curr_close - prev_close_val) / prev_close_val * 100 if prev_close_val > 0 else 0.0
        avg_vol_5 = float(np.mean(volumes[-6:-1])) if len(volumes) >= 6 else float(volumes[-1])
        today_vol = float(volumes[-1])
        volume_ratio = today_vol / avg_vol_5 if avg_vol_5 > 0 else 1.0

        # Calculate recent pivot info if available
        pivot_info = {}
        if hasattr(result, 'buy_points') and result.buy_points:
            for bp in result.buy_points:
                if 'pivots' in bp and bp['pivots']:
                    zd = bp['pivots'].get('ZD')
                    zg = bp['pivots'].get('ZG')
                    if zd is not None and zg is not None:
                        pivot_info = bp['pivots']
                        break

        # Build startup reason text
        reason_parts = []
        if is_low == "60d_low":
            reason_parts.append("处于60日低位区间")
        elif is_low == "120d_low":
            reason_parts.append("处于120日低位区间")
        elif is_low == "near_start_low":
            reason_parts.append("启动前接近20日低点")
        elif is_low == "near_pivot":
            reason_parts.append("位于中枢ZD/ZG附近")

        if volume_ratio >= 2.0:
            reason_parts.append(f"放量{volume_ratio:.1f}倍")
        else:
            reason_parts.append(f"放量{volume_ratio:.1f}倍")

        if "close_above_ma5" in startup_signals and "close_above_ma10" in startup_signals:
            reason_parts.append("站上MA5/MA10")
        if "break_20d_high" in startup_signals:
            reason_parts.append("突破20日平台")
        if "break_pivot_zg" in startup_signals:
            reason_parts.append("突破中枢ZG")
        if change_pct >= 4.0:
            reason_parts.append(f"涨幅{change_pct:.1f}%")

        startup_reason = "；".join(reason_parts)

        startup_index = len(closes) - 1
        startup_date = str(dates[-1]) if dates else ""
        startup_age_days = 0  # 第一版只识别今天这根日K是否启动

        seed = {
            "code": code,
            "name": name,
            "sector": sector_name,
            "type": "强势启动候选",
            "tier": "candidate",
            "category": "A",
            "quality_tier": "",
            "source_channel": "low_position",
            "view": "main",
            "source_type": "日线强势启动",
            "startup_reason": startup_reason,
            "startup_signals": startup_signals,
            "startup_index": startup_index,
            "startup_date": startup_date,
            "startup_age_days": startup_age_days,
            "change_pct": round(change_pct, 2),
            "price_limit_state": price_limit_state,
            "volume_ratio": round(volume_ratio, 2),
            "close": curr_close,
            "pivot_info": pivot_info,
            "closes": closes,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "dates": dates,
            "buy_points": list(result.buy_points) if hasattr(result, 'buy_points') and result.buy_points else [],
            "result_30min": None,
            "price_basis": price_basis,
        }

        # --- Step 4: 涨停处理 → 当日不进候选，进观察 ---
        if price_limit_state == "limit_up":
            watch_item = _make_watch_item(seed, "低位放量涨停",
                "涨停当日不追，等待次日回踩确认",
                ["回踩不破突破位", "30min二买/三买", "缩量回踩后再放量"])
            watchlist.append(watch_item)
            diag["watch_due_to_limit_up"] += 1
        else:
            seeds.append(seed)
            diag["daily_startup_seed"] += 1

    return seeds, watchlist, diag


def upgrade_strong_startup_with_30min(startup_seeds, chan_results_30min):
    """Upgrade startup seeds with 30min confirmation analysis.

    Non-limit-up seeds that get 30min confirmation → 强势启动候选
    Seeds without enough 30min confirmation → 强势启动观察

    Args:
        startup_seeds: list of startup seed dicts from build_strong_startup_pool
        chan_results_30min: list of 30min chan analysis result objects

    Returns:
        (candidates, new_watchlist, diag)
    """
    diag = {
        "startup_candidate": 0,
        "startup_watch": 0,
        "dropped_no_30min_confirm": 0,
        "watch_due_to_no_30min_confirm": 0,
    }

    # Index 30min results by code
    min30_by_code = {}
    for r in chan_results_30min:
        if r is not None:
            min30_by_code[r.code] = r

    candidates = []
    new_watchlist = []

    for seed in startup_seeds:
        code = seed["code"]
        min30_result = min30_by_code.get(code)

        if min30_result is None:
            # No 30min data → watch
            diag["watch_due_to_no_30min_confirm"] += 1
            seed["confirmation_evidence"] = build_30min_confirmation_evidence(None)
            watch_item = _make_watch_item(seed, seed["startup_reason"],
                "缺少30分钟数据，等待次日确认",
                ["30分钟数据可用", "30分钟出现二买/三买", "30分钟最新窗口出现两阳结构"],
                reason_code="missing_30m_data")
            new_watchlist.append(watch_item)
            continue

        # Keep lagging state evidence separate from decision-grade signals.
        confirmation_evidence = build_30min_confirmation_evidence(min30_result)
        seed["confirmation_evidence"] = confirmation_evidence
        confirmations = _check_30min_confirmations(
            min30_result, seed, evidence=confirmation_evidence
        )
        seed["confirmations"] = confirmations

        if confirmations:
            # Has 30min confirmation → candidate
            diag["startup_candidate"] += 1
            seed["result_30min"] = min30_result
            seed["type"] = "强势启动候选"
            seed["tier"] = "candidate"
            seed["category"] = "A"
            seed["source_channel"] = "low_position"
            seed["view"] = "main"
            seed["avoid_chase"] = False
            input_evidence = getattr(
                min30_result, "strategy_input_evidence", None
            )
            if isinstance(input_evidence, dict):
                seed["strategy_input_evidence"] = dict(input_evidence)

            closes_30 = min30_result.closes
            dates_30 = min30_result.dates if hasattr(min30_result, 'dates') else []
            if closes_30 is not None and len(closes_30) > 0:
                seed["confirm_index"] = len(closes_30) - 1
                seed["confirm_date"] = str(dates_30[-1]) if dates_30 else ""
                seed["confirm_age_days"] = 0
            else:
                seed["confirm_index"] = seed.get("startup_index")
                seed["confirm_date"] = seed.get("startup_date", "")
                seed["confirm_age_days"] = seed.get("startup_age_days", 0)

            candidates.append(seed)
        else:
            # No 30min confirmation → watch
            diag["watch_due_to_no_30min_confirm"] += 1
            if confirmation_evidence.get("ema_bullish_alignment"):
                watch_reason = "30分钟均线仍为多头排列，但未形成独立确认，继续观察"
            else:
                watch_reason = "日线启动但30分钟未形成独立确认，继续观察"
            watch_item = _make_watch_item(seed, seed["startup_reason"],
                watch_reason,
                ["30分钟出现二买/三买", "30分钟最新窗口出现两阳结构"],
                reason_code=(
                    "alignment_without_confirmation"
                    if confirmation_evidence.get("ema_bullish_alignment")
                    else "waiting_30m_confirm"
                ))
            new_watchlist.append(watch_item)

    return candidates, new_watchlist, diag


# ------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------

def _check_low_position(closes, highs, lows, ratio_60d, ratio_120d, pre_start_ratio):
    """Check if the stock is in a low position on daily timeframe.

    Returns:
        "60d_low" | "120d_low" | "near_start_low" | "near_pivot" | None
    """
    curr_close = closes[-1]
    n = len(closes)

    # 60-day high check
    if n >= 60:
        high_60 = np.max(highs[-60:])
        if high_60 > 0 and curr_close <= high_60 * ratio_60d:
            return "60d_low"

    # 120-day high check
    if n >= 120:
        high_120 = np.max(highs[-120:])
        if high_120 > 0 and curr_close <= high_120 * ratio_120d:
            return "120d_low"

    # Near 20-day low
    if n >= 20:
        low_20 = np.min(lows[-20:-1]) if n >= 21 else np.min(lows[-20:])
        if low_20 > 0 and closes[-2] <= low_20 * pre_start_ratio if n >= 2 else True:
            start_low = np.min(lows[-20:])
            if start_low > 0 and closes[-2] <= start_low * pre_start_ratio if n >= 2 else True:
                return "near_start_low"

    return None


def _check_volume_breakout(volumes, closes, min_ratio):
    """Check if today's volume is significantly above recent average."""
    if len(volumes) < 6:
        return False
    avg_vol_5 = np.mean(volumes[-6:-1])
    if avg_vol_5 <= 0:
        return False
    today_vol = volumes[-1]
    if today_vol / avg_vol_5 >= min_ratio:
        return True
    # Also check amount ratio as fallback
    if len(closes) >= 6:
        avg_amount_5 = np.mean(volumes[-6:-1] * closes[-6:-1])
        today_amount = volumes[-1] * closes[-1]
        if avg_amount_5 > 0 and today_amount / avg_amount_5 >= min_ratio:
            return True
    return False


def _check_price_breakout(closes, opens, highs, min_change_pct):
    """Check price breakout conditions. Returns list of satisfied signal names."""
    signals = []
    n = len(closes)

    if n < 2:
        return signals

    curr_close = closes[-1]
    prev_close = closes[-2]
    change_pct = (curr_close - prev_close) / prev_close * 100 if prev_close > 0 else 0

    # change_pct >= min
    if change_pct >= min_change_pct:
        signals.append(f"涨幅≥{min_change_pct}%")

    # close > MA5
    if n >= 5:
        ma5 = np.mean(closes[-5:])
        if curr_close > ma5:
            signals.append("close_above_ma5")

    # close > MA10
    if n >= 10:
        ma10 = np.mean(closes[-10:])
        if curr_close > ma10:
            signals.append("close_above_ma10")

    # close > recent_20_high_prev (excluding today)
    if n >= 21:
        high_20_prev = np.max(highs[-21:-1])
        if curr_close > high_20_prev:
            signals.append("break_20d_high")

    # candle body >= 3%
    if n >= 2:
        body_pct = abs(curr_close - opens[-1]) / prev_close * 100 if prev_close > 0 else 0
        if body_pct >= 3.0:
            signals.append("实体阳线≥3%")

    return signals


def _check_30min_confirmations(min30_result, seed, evidence=None):
    """Return only fresh, decision-grade 30-minute confirmation events."""
    confirms = []

    if min30_result is None:
        return confirms
    evidence = evidence or build_30min_confirmation_evidence(min30_result)
    if not evidence.get("sufficient_bars"):
        return confirms

    pattern = evidence.get("fresh_yang_pattern")
    if pattern == "two_yang_one_yin":
        confirms.append("30min两阳夹一阴确认")
    elif pattern == "two_yang_two_yin":
        confirms.append("30min两阳夹两阴确认")

    buy_point = evidence.get("buy_point")
    if buy_point:
        confirms.append(f"30min {buy_point}")

    return confirms


def _make_watch_item(
    seed,
    startup_reason,
    watch_reason,
    next_day_conditions,
    reason_code=None,
):
    """Build a startup watchlist item."""
    if seed.get("price_limit_state") == "limit_up":
        derived_reason_code = "limit_up"
        failure_gate = "chase_risk"
    else:
        derived_reason_code = "waiting_30m_confirm"
        failure_gate = "30min_confirm"
    reason_code = reason_code or derived_reason_code
    return {
        "code": seed["code"],
        "name": seed["name"],
        "sector": seed.get("sector", ""),
        "type": "强势启动观察",
        "tier": "watch",
        "category": "C",
        "quality_tier": "",
        "source_channel": "low_position",
        "view": "observation",
        "source_type": "日线强势启动",
        "startup_reason": startup_reason,
        "startup_signals": seed.get("startup_signals", []),
        "startup_index": seed.get("startup_index"),
        "startup_date": seed.get("startup_date", ""),
        "startup_age_days": seed.get("startup_age_days", 0),
        "change_pct": seed.get("change_pct", 0),
        "price_limit_state": seed.get("price_limit_state", "invalid"),
        "volume_ratio": seed.get("volume_ratio", 0),
        "close": seed.get("close", 0),
        "avoid_chase": True,
        "watch_reason": watch_reason,
        "reason_code": reason_code,
        "failure_gate": failure_gate,
        "actual_value": {
            "change_pct": seed.get("change_pct", 0),
            "volume_ratio": seed.get("volume_ratio", 0),
        },
        "upgrade_conditions": list(next_day_conditions),
        "next_day_conditions": next_day_conditions,
        "cancel_conditions": ["跌破启动参考位", "放量长阴破坏结构"],
        "confirmations": list(seed.get("confirmations", [])),
        "confirmation_evidence": dict(seed.get("confirmation_evidence") or {}),
        "pivot_info": seed.get("pivot_info", {}),
        "buy_points": [],
        "closes": seed.get("closes", []),
        "opens": seed.get("opens", []),
        "highs": seed.get("highs", []),
        "lows": seed.get("lows", []),
        "volumes": seed.get("volumes", []),
        "dates": seed.get("dates", []),
        "result_30min": None,
    }


def annotate_startup_quality(bp):
    """Annotate a startup buy_point with daily startup grade and sublevel confirm grade.

    Does NOT filter — only adds labels for display and sorting.
    """
    bp = dict(bp)

    change_pct = bp.get("change_pct", 0) or 0
    startup_signals = bp.get("startup_signals", []) or []
    startup_reason = bp.get("startup_reason", "") or ""
    confirmations = bp.get("confirmations", []) or []
    confirmation_evidence = bp.get("confirmation_evidence") or {}

    # --- daily_startup_grade ---
    is_strong = (
        change_pct >= 4
        or "break_20d_high" in startup_signals
        or "突破20日平台" in startup_reason
        or "突破中枢" in startup_reason
    )
    if is_strong:
        bp["daily_startup_grade"] = "strong"
        bp["daily_startup_label"] = "强启动"
    elif change_pct >= 0:
        bp["daily_startup_grade"] = "weak"
        bp["daily_startup_label"] = "弱启动确认"
        bp["daily_startup_warning"] = "涨幅较小，属于观察型启动，不是追涨启动"
    else:
        bp["daily_startup_grade"] = "pullback"
        bp["daily_startup_label"] = "回踩型启动观察"
        bp["daily_startup_warning"] = f"当日收跌{abs(change_pct):.1f}%，属于观察型启动，不是追涨启动"

    # --- sublevel_confirm_grade ---
    buy_point_type = str(confirmation_evidence.get("buy_point") or "")
    has_buy23 = buy_point_type in STRONG_STARTUP_BUY_POINT_TYPES
    has_fresh_yang = confirmation_evidence.get("fresh_yang_pattern") in {
        "two_yang_one_yin",
        "two_yang_two_yin",
    }
    decision_confirmations = []
    if has_buy23:
        decision_confirmations = [
            c for c in confirmations if "二买" in c or "三买" in c
        ]
    elif has_fresh_yang:
        decision_confirmations = [c for c in confirmations if "两阳夹" in c]

    if has_buy23:
        bp["sublevel_confirm_grade"] = "S"
        bp["sublevel_confirm_label"] = "S级确认"
        bp["sublevel_confirm_reason"] = "30min出现二买/三买确认"
    elif bp["daily_startup_grade"] == "strong" and has_fresh_yang:
        bp["sublevel_confirm_grade"] = "A"
        bp["sublevel_confirm_label"] = "A级确认"
        bp["sublevel_confirm_reason"] = "日线强启动+30分钟最新两阳结构"
    elif decision_confirmations:
        bp["sublevel_confirm_grade"] = "B"
        bp["sublevel_confirm_label"] = "B级确认"
        bp["sublevel_confirm_reason"] = f"30分钟结构确认: {', '.join(decision_confirmations[:2])}"
    else:
        bp["sublevel_confirm_grade"] = "C"
        bp["sublevel_confirm_label"] = "C级确认"
        if confirmation_evidence.get("ema_bullish_alignment"):
            bp["sublevel_confirm_reason"] = "30分钟均线仍为多头排列，但未形成独立确认"
        else:
            bp["sublevel_confirm_reason"] = "暂无30分钟独立确认信号"

    return bp
