"""
Daily structure pool builder — replaces the old "screen then discard references" flow.

Keeps stocks with formal OR upgradeable reference signals so 30min confirmation
can upgrade them to candidates.
"""

import numpy as np
from config import (
    MIN_LISTED_DAYS, MIN_DAILY_AMOUNT,
    ENABLE_SWING_POSITION_SEEDS,
)
from .data_fetcher import is_st_stock
from .market_sentiment import classify_price_limit
from .signal_policy import (
    is_formal_buy, is_upgradeable_reference, is_blocked_buy,
    is_candidate_seed, is_reference_only,
)
from .signal_quality_classifier import (
    build_signal_context,
    tag_signal_quality_in_place,
)
from .screener_pure import _get_pivot_info, _pick_best_buy_point


def build_daily_structure_pool(chan_results, sector_stocks=None, mode="pure"):
    """Build a daily structure pool containing formal + upgradeable reference signals.

    Base filters (ST, listed days, limit up/down, liquidity) are applied.
    Stocks with only reference-only or blocked signals are excluded,
    unless a swing底背驰参考 passes the daily position guard and becomes a seed.

    Returns:
        (pool, diag) where pool is list of stock dicts and diag is a diagnostics dict.
    """
    pool = []
    diag = {
        "total": len(chan_results),
        "base_pass": 0,
        "with_buy_points": 0,
        "formal_count": 0,
        "upgradeable_count": 0,
        "swing_seed_count": 0,
        "reference_only_count": 0,
        "blocked_only_count": 0,
        "buy_point_type_counts": {},
        "structure_pool_reasons": {
            "formal": 0,
            "upgradeable_reference": 0,
            "swing_position_seed": 0,
        },
        "excluded_reference_type_counts": {},
    }

    for result in chan_results:
        if result is None:
            continue

        code = result.code
        name = result.name

        # --- Base filters ---
        if is_st_stock(name):
            continue
        if len(result.closes) < MIN_LISTED_DAYS:
            continue

        # 真实涨跌停过滤：必须按板块、ST和价格精度判断，禁止用统一涨跌幅阈值。
        if len(result.closes) >= 2:
            prev_close = result.closes[-2]
            curr_close = result.closes[-1]
            if prev_close > 0:
                price_limit_state = classify_price_limit({
                    "code": code,
                    "name": name,
                    "prev_close": prev_close,
                    "close": curr_close,
                })
                if price_limit_state in ("limit_up", "limit_down"):
                    continue

        # Liquidity
        if len(result.volumes) >= 5 and len(result.closes) >= 5:
            amounts = result.volumes[-5:] * result.closes[-5:] * 100
            if np.mean(amounts) < MIN_DAILY_AMOUNT:
                continue

        diag["base_pass"] += 1

        # --- Signal classification ---
        if not result.buy_points:
            continue

        diag["with_buy_points"] += 1

        formal_bps = [bp for bp in result.buy_points if is_formal_buy(bp)]
        upgradeable_bps = [bp for bp in result.buy_points if is_upgradeable_reference(bp)]
        blocked_bps = [bp for bp in result.buy_points if is_blocked_buy(bp)]
        reference_bps = [bp for bp in result.buy_points
                         if not is_formal_buy(bp)
                         and not is_upgradeable_reference(bp)
                         and not is_blocked_buy(bp)
                         and not is_candidate_seed(bp)]

        # Track type distribution
        for bp in result.buy_points:
            t = bp.get("type", "unknown")
            diag["buy_point_type_counts"][t] = diag["buy_point_type_counts"].get(t, 0) + 1

        # Try to build swing seeds from reference bps with position guard
        for bp in result.buy_points:
            bp["context"] = build_signal_context(result, bp)
            tag_signal_quality_in_place(bp)

        pivot_info = _get_pivot_info(result)
        swing_seeds = []
        remaining_reference = []
        if ENABLE_SWING_POSITION_SEEDS:
            for bp in reference_bps:
                seed = _build_swing_position_seed(bp, result, pivot_info)
                if seed:
                    swing_seeds.append(seed)
                else:
                    remaining_reference.append(bp)
                    if is_reference_only(bp):
                        t = bp.get("type", "")
                        diag["excluded_reference_type_counts"][t] = \
                            diag["excluded_reference_type_counts"].get(t, 0) + 1
            reference_bps = remaining_reference

        # Decide whether to include in pool
        has_formal = len(formal_bps) > 0
        has_upgradeable = len(upgradeable_bps) > 0
        has_swing_seed = len(swing_seeds) > 0

        if has_formal:
            diag["formal_count"] += 1
            diag["structure_pool_reasons"]["formal"] += 1
        if has_upgradeable:
            diag["upgradeable_count"] += 1
            diag["structure_pool_reasons"]["upgradeable_reference"] += 1
        if has_swing_seed:
            diag["structure_pool_reasons"]["swing_position_seed"] += 1
            diag["swing_seed_count"] += len(swing_seeds)

        if not has_formal and not has_upgradeable and not has_swing_seed:
            if blocked_bps and not reference_bps:
                diag["blocked_only_count"] += 1
            else:
                diag["reference_only_count"] += 1
            continue

        # --- Build stock entry ---
        sector_name = sector_stocks.get(code, {}).get("sector", "") if sector_stocks else ""

        # Combine formal + upgradeable + seeds as pool buy points
        pool_bps = formal_bps + upgradeable_bps + swing_seeds
        all_bps = formal_bps + upgradeable_bps + swing_seeds + reference_bps + blocked_bps

        # Best from formal+upgradeable only (seeds need 30min upgrade first)
        executable_bps = [bp for bp in formal_bps + upgradeable_bps if bp.get("category") == "A"]
        best_executable_bp = _pick_best_buy_point(executable_bps) if executable_bps else None
        if executable_bps:
            best_bp = best_executable_bp
        else:
            best_bp = _pick_best_buy_point(formal_bps + upgradeable_bps) if (formal_bps or upgradeable_bps) else None

        stock_entry = {
            "code": code,
            "name": name,
            "buy_points": all_bps,             # all buy points for upgrade logic
            "executable_buy_points": executable_bps,
            "best_buy_point": best_bp,
            "best_executable_buy_point": best_executable_bp,
            "pivots": pivot_info,
            "trend_type": result.trend_type,
            "divergence": result.divergence,
            "closes": result.closes,
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
            "version": mode,
        }
        pool.append(stock_entry)

    return pool, diag


# ============================================================
# Position guard and swing seed helpers
# ============================================================

def _build_swing_position_seed(bp, result, pivot_info):
    """Try to build a swing底背驰候选种子 from a swing底背驰参考 if position guard passes."""
    if bp.get("type") != "swing底背驰参考":
        return None
    ok, reason = _passes_daily_position_guard(bp, result, pivot_info)
    if not ok:
        return None
    return {
        **bp,
        "type": "swing底背驰候选种子",
        "tier": "seed",
        "source_type": "swing底背驰参考",
        "seed_reason": reason,
    }


def _passes_daily_position_guard(bp, result, pivot_info):
    """Check if a swing reference is in a position where it makes sense to watch.

    Returns (ok: bool, reason: str).
    """
    closes = result.closes
    volumes = result.volumes
    if closes is None or len(closes) < 20:
        return False, "日线样本少于20根"

    close = float(closes[-1])
    recent = np.asarray(closes[-20:], dtype=float)
    recent_low = float(np.min(recent))
    recent_high = float(np.max(recent))
    source_price = float(bp.get("price") or 0)
    zd = pivot_info.get("ZD") if pivot_info else None

    # Risk guard: don't chase high
    if source_price > 0 and close > source_price * 1.12:
        return False, "当前价距离参考价过高"

    # Risk guard: 3-day volume selloff
    if _is_three_day_volume_selloff(closes, volumes):
        return False, "最近3日放量连续下跌"

    reasons = []
    if close <= recent_low * 1.08:
        reasons.append("接近20日低点")
    if close <= recent_high * 0.92:
        reasons.append("相对20日高点回撤充分")
    if zd is not None and close <= float(zd) * 1.05:
        reasons.append("接近日线中枢ZD")
    if source_price > 0 and close <= source_price * 1.08:
        reasons.append("接近swing参考价")

    if not reasons:
        return False, "未处于日线低位或关键位附近"
    return True, "；".join(reasons)


def _is_three_day_volume_selloff(closes, volumes):
    """Check for 3 consecutive down days with volume expansion vs prior 10 days."""
    if closes is None or volumes is None or len(closes) < 13 or len(volumes) < 13:
        return False
    down_3 = closes[-1] < closes[-2] < closes[-3]
    recent_vol = float(np.mean(volumes[-3:]))
    base_vol = float(np.mean(volumes[-13:-3]))
    return down_3 and base_vol > 0 and recent_vol > base_vol * 1.5
