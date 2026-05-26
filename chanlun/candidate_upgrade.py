"""
Candidate upgrade — uses 30min sub-level confirmation to upgrade daily
reference signals into recommendable candidates.
"""

import numpy as np

from .signal_policy import (
    is_formal_buy, is_upgradeable_reference, is_candidate_seed,
    UPGRADE_OUTPUT_TYPE,
)
from .sublevel_confirm import classify_30min_confirmation


def upgrade_daily_candidates_with_30min(daily_pool, chan_results_30min, mode="pure"):
    """Upgrade daily reference signals using 30min confirmation.

    Args:
        daily_pool: list of stock dicts from build_daily_structure_pool()
        chan_results_30min: list of ChanResult from 30min analysis
        mode: "pure" or "fusion"

    Returns:
        (recommended, diagnostics) where recommended is a list of stock dicts
        with recommendable buy_points only.
    """
    min30_map = {}
    for r in (chan_results_30min or []):
        if r is not None:
            min30_map[r.code] = r

    recommended = []
    diag = {
        "requested_30min": len(daily_pool),
        "fetched_30min": 0,
        "formal_kept": 0,
        "candidate_upgraded": 0,
        "dropped_no_confirm": 0,
        "dropped_no_30min": 0,
        "dropped_risk_guard": 0,
    }

    for stock in daily_pool:
        code = stock["code"]
        min30_result = min30_map.get(code)

        if min30_result is not None:
            diag["fetched_30min"] += 1

        recommendable = []
        upgraded_candidates = []
        reference_buy_points = []
        blocked_buy_points = []

        # Separate all buy points by tier
        all_bp = stock.get("buy_points", [])
        formal_bps = [bp for bp in all_bp if is_formal_buy(bp)]
        upgradeable_bps = [bp for bp in all_bp
                          if is_upgradeable_reference(bp) or is_candidate_seed(bp)]
        other_bps = [bp for bp in all_bp
                     if not is_formal_buy(bp)
                     and not is_upgradeable_reference(bp)
                     and not is_candidate_seed(bp)]

        # Classify others
        for bp in other_bps:
            t = bp.get("type", "")
            if t in ("三买已错过", "类二买"):
                blocked_buy_points.append(bp)
            else:
                reference_buy_points.append(bp)

        # Formal stays formal, attach 30min resonance if available
        for bp in formal_bps:
            bp_copy = dict(bp)
            if min30_result is not None:
                bp_copy["resonance_30min"] = _quick_resonance(bp, min30_result)
            else:
                bp_copy["resonance_30min"] = {
                    "level": "弱", "reason": "30分钟数据缺失，未做次级别确认"
                }
            recommendable.append(bp_copy)
            diag["formal_kept"] += 1

        # Try to upgrade each upgradeable reference (including seeds)
        for bp in upgradeable_bps:
            src_type = bp.get("type", "")
            out_type = UPGRADE_OUTPUT_TYPE.get(src_type)
            if not out_type:
                reference_buy_points.append(bp)
                continue

            if min30_result is None:
                # Cannot upgrade without 30min data
                reference_buy_points.append(bp)
                continue

            # Risk guard before confirmation
            if not _passes_upgrade_risk_guard(stock, bp, min30_result):
                reference_buy_points.append(bp)
                diag["dropped_risk_guard"] += 1
                continue

            confirmation = classify_30min_confirmation(stock, bp, min30_result)
            if confirmation["confirmed"] and confirmation["level"] in ("强", "中"):
                candidate = {
                    **bp,
                    "type": out_type,
                    "tier": "candidate",
                    "source_type": bp.get("source_type", src_type),
                    "seed_type": src_type if is_candidate_seed(bp) else None,
                    "confirmed_by": confirmation["reason"],
                    "confirmations": confirmation["signals"],
                    "strength": confirmation["level"],
                    "reason": bp.get("reason", "") + "；次级别确认：" + confirmation["reason"],
                }
                if candidate["seed_type"] is None:
                    del candidate["seed_type"]
                recommendable.append(candidate)
                upgraded_candidates.append(candidate)
                diag["candidate_upgraded"] += 1
            else:
                reference_buy_points.append(bp)

        # Count drops
        if not recommendable:
            if min30_result is None:
                diag["dropped_no_30min"] += 1
            else:
                diag["dropped_no_confirm"] += 1
            continue

        # Pick best_buy_point from recommendable
        best_bp = _pick_best_from_recommendable(recommendable)

        # Build output stock dict
        out = dict(stock)
        out["buy_points"] = recommendable
        out["best_buy_point"] = best_bp
        out["reference_buy_points"] = reference_buy_points
        out["blocked_buy_points"] = blocked_buy_points
        out["upgraded_candidates"] = upgraded_candidates
        out["signal_tier"] = best_bp.get("tier", "formal")
        if min30_result is not None:
            out["result_30min"] = min30_result
            out["buy_points_30min"] = min30_result.buy_points or []
            if best_bp.get("tier") == "candidate":
                out["resonance"] = {
                    "level": best_bp.get("strength", "中"),
                    "reason": best_bp.get("confirmed_by", "30min确认"),
                }
            else:
                out["resonance"] = best_bp.get("resonance_30min",
                    {"level": "弱", "reason": "30分钟数据缺失"})
        else:
            out["resonance"] = {"level": "弱", "reason": "30分钟数据缺失，未做次级别确认"}

        recommended.append(out)

    return recommended, diag


def _quick_resonance(bp, min30_result):
    """Quick resonance check for a formal daily buy point against 30min."""
    daily_type = bp.get("type", "")
    if min30_result is None:
        return {"level": "弱", "reason": "无30分钟数据"}

    for bp30 in (min30_result.buy_points or []):
        if bp30.get("type") == daily_type:
            return {"level": "强", "reason": f"日线{daily_type}+30分钟{daily_type}共振"}

    div = min30_result.divergence
    if div and div.get("is_divergence") and "底背驰" in div.get("type", ""):
        return {"level": "中", "reason": "日线买点+30分钟底背驰共振"}

    return {"level": "弱", "reason": "30分钟无明确共振信号"}


def _pick_best_from_recommendable(buy_points):
    """Pick best buy point from recommendable list: formal > candidate, then priority."""
    BUY_TYPE_PRIORITY = {
        "三买": 0, "二买": 1, "一买": 2,
        "三买候选": 3, "二买候选": 4,
        "盘整低吸候选": 5, "中枢低吸候选": 6, "底背驰候选": 7,
    }

    def _key(bp):
        tier_order = 0 if bp.get("tier") == "formal" else 1
        type_order = BUY_TYPE_PRIORITY.get(bp.get("type", ""), 9)
        return (tier_order, type_order)

    return min(buy_points, key=_key)


def _passes_upgrade_risk_guard(stock, source_bp, min30_result):
    """Check chase and breakdown risk guards before upgrading a seed/reference.

    Returns False if the daily close has run too far above the source price,
    or if the 30min recent low has broken below the source price by >3%.
    """
    closes = stock.get("closes")
    if closes is None or len(closes) == 0:
        return False
    latest_daily_close = float(closes[-1])
    source_price = float(source_bp.get("price") or 0)
    if source_price > 0 and latest_daily_close > source_price * 1.12:
        return False

    lows_30 = min30_result.lows
    if source_price > 0 and lows_30 is not None and len(lows_30) >= 8:
        recent_low = float(np.min(lows_30[-8:]))
        if recent_low < source_price * 0.97:
            return False

    return True
