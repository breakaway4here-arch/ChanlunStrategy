"""
Fusion version admission policy — applies MA多头, market regime, and signal-type
thresholds to filter pure-ready picks into the final fusion recommendation set.

This is the decision layer that makes fusion materially different from pure,
not just a re-scoring of the same set.

Reuses the same ema() helpers as screener_fusion.py to keep the two in sync.
"""

import numpy as np
from config import MA_SHORT, MA_MID, MA_LONG, MA_TREND
from .chan_engine import ema


def is_market_strong(sh_closes):
    """上证收盘价 > EMA50 → 强趋势（与旧 screener_fusion 同口径）。"""
    if sh_closes is None or len(sh_closes) < MA_TREND:
        return False
    ema50 = float(ema(sh_closes, MA_TREND)[-1])
    if np.isnan(ema50):
        return False
    return float(sh_closes[-1]) > ema50


def is_ma_bullish(closes):
    """EMA5 > EMA10 > EMA20 多头排列（与旧 screener_fusion 同口径）。"""
    if closes is None or len(closes) < MA_LONG + 1:
        return False
    ema5 = float(ema(closes, MA_SHORT)[-1])
    ema10 = float(ema(closes, MA_MID)[-1])
    ema20 = float(ema(closes, MA_LONG)[-1])
    if np.isnan(ema5) or np.isnan(ema10) or np.isnan(ema20):
        return False
    return bool(ema5 > ema10 > ema20)


def apply_fusion_admission(picks, sh_closes, sector_stocks=None):
    """Filter pure-ready picks through fusion admission policy.

    Returns (fusion_picks, diagnostics).
    """
    market_strong = is_market_strong(sh_closes)
    regime = "strong" if market_strong else "weak"

    diag = {
        "market_regime": regime,
        "input_count": len(picks),
        "dropped_by_ma": 0,
        "dropped_by_market_regime": 0,
        "dropped_by_signal_gate": 0,
        "kept_formal": 0,
        "kept_candidate": 0,
        "drop_details": [],
    }

    fusion_picks = []
    for stock in picks:
        bp = stock.get("best_buy_point", {})
        bp_type = bp.get("type", "")
        tier = bp.get("tier", "")
        closes = stock.get("closes", [])
        ma_ok = is_ma_bullish(closes)
        strength = bp.get("strength", "")
        confirmed_by = bp.get("confirmed_by", "")

        stock["ma_bullish"] = ma_ok
        stock["market_regime"] = regime

        decision, reason = _admit(bp_type, tier, ma_ok, market_strong, strength, confirmed_by)

        if decision:
            stock["fusion_admission"] = {"passed": True, "reason": reason}
            fusion_picks.append(stock)
            if tier == "formal":
                diag["kept_formal"] += 1
            else:
                diag["kept_candidate"] += 1
        else:
            stock["fusion_admission"] = {"passed": False, "reason": reason}
            diag["drop_details"].append({
                "code": stock.get("code", ""),
                "name": stock.get("name", ""),
                "type": bp_type,
                "reason": reason,
            })
            if "MA" in reason:
                diag["dropped_by_ma"] += 1
            elif "弱市" in reason:
                diag["dropped_by_market_regime"] += 1
            else:
                diag["dropped_by_signal_gate"] += 1

    diag["output_count"] = len(fusion_picks)
    diag["pure_fusion_identical"] = (diag["input_count"] == diag["output_count"])
    if diag["pure_fusion_identical"]:
        diag["identical_reason"] = "所有pure推荐均通过融合版门槛" if diag["input_count"] > 0 else "pure无推荐"
    return fusion_picks, diag


def _admit(bp_type, tier, ma_ok, market_strong, strength, confirmed_by):
    """Single-stock admission decision per the fusion threshold matrix.

    Returns (admitted: bool, reason: str).
    """
    # Formal buys (一买/二买/三买)
    if tier == "formal":
        if bp_type == "三买":
            if not ma_ok:
                return False, "三买要求MA多头(MA5>MA10>MA20)"
            if not market_strong:
                # 弱市: 要求 ma_bullish 且 30min 共振非弱
                if strength == "弱":
                    return False, "三买弱市要求MA多头且30min共振非弱"
            return True, "三买formal保留"
        # 一买/二买: always keep
        return True, f"{bp_type}formal保留"

    # Candidates
    if bp_type == "三买候选":
        if not ma_ok:
            return False, "三买候选要求MA多头(MA5>MA10>MA20)"
        if not market_strong and strength not in ("强", "中"):
            return False, "三买候选弱市要求30min确认强度强/中"
        return True, "三买候选通过"

    if bp_type == "二买候选":
        if market_strong:
            if ma_ok:
                return True, "二买候选强市MA多头优先"
            else:
                return True, "二买候选强市降级排序但可保留"
        else:
            if strength not in ("强", "中"):
                return False, "二买候选弱市要求30min确认强度强/中"
            return True, "二买候选弱市通过"

    if bp_type == "中枢低吸候选":
        if market_strong:
            if ma_ok:
                return True, "中枢低吸候选强市MA多头优先"
            elif strength == "强":
                return True, "中枢低吸候选强市确认强度强可保留"
            else:
                return False, "中枢低吸候选强市要求MA多头或确认强度强"
        else:
            if not ma_ok:
                return False, "中枢低吸候选弱市要求MA多头(MA5>MA10>MA20)"
            if strength not in ("强", "中"):
                return False, "中枢低吸候选弱市要求确认强度强/中"
            return True, "中枢低吸候选弱市通过"

    if bp_type == "盘整低吸候选":
        if market_strong:
            if strength not in ("强", "中"):
                return False, "盘整低吸候选要求确认强度强/中"
            return True, "盘整低吸候选通过"
        else:
            if strength != "强":
                return False, "盘整低吸候选弱市要求确认强度强"
            return True, "盘整低吸候选弱市通过"

    if bp_type == "底背驰候选":
        if market_strong:
            if strength not in ("强", "中"):
                return False, "底背驰候选要求确认强度强/中"
            return True, "底背驰候选强市通过"
        else:
            if strength == "强":
                return True, "底背驰候选弱市确认强度强通过"
            has_key_level = "关键位不破" in (confirmed_by or "")
            has_ema5 = "EMA5收复" in (confirmed_by or "")
            if has_key_level and has_ema5:
                return True, "底背驰候选弱市关键位不破+EMA5收复通过"
            return False, "底背驰候选弱市要求确认强度强或(关键位不破且EMA5收复)"

    if bp_type == "强势启动候选":
        if not ma_ok:
            return False, "强势启动候选要求MA多头(MA5>MA10>MA20)"
        if market_strong:
            return True, "强势启动候选强市通过"
        else:
            if strength not in ("强", "中"):
                return False, "强势启动候选弱市要求30min确认强/中"
            return True, "强势启动候选弱市通过"

    # Unknown type — do not admit
    return False, f"未知类型{bp_type}不默认放行"
