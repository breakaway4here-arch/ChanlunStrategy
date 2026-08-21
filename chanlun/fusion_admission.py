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


def _source_status(stock):
    explicit = str(stock.get("source_status") or "").strip().lower()
    if explicit:
        return explicit
    source_rows = stock.get("strategy_sources")
    if isinstance(source_rows, (list, tuple)) and source_rows:
        statuses = {
            str(row.get("source_status") or "").strip().lower()
            for row in source_rows
            if isinstance(row, dict)
        }
        statuses.discard("")
        if "candidate" in statuses:
            return "candidate"
        if statuses:
            return sorted(statuses)[0]
    if str(stock.get("view") or "").strip().lower() == "observation":
        return "observe"
    if str(stock.get("tier") or "").strip().lower() == "watch":
        return "observe"
    return "candidate"


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
        trend_confirmations = []
        if bp_type == "趋势延续候选":
            trend_confirmations = list(dict.fromkeys(
                str(value).strip()
                for value in (stock.get("confirmations") or [])
                if str(value).strip()
            ))
            if trend_confirmations:
                confirmed_by = "+".join(trend_confirmations)
        confirmation_facts = _confirmation_facts(
            stock, bp, bp_type, trend_confirmations
        )
        if confirmation_facts:
            stock["confirmation_facts"] = confirmation_facts
            bp["confirmation_facts"] = confirmation_facts

        stock["ma_bullish"] = ma_ok
        stock["market_regime"] = regime
        stock["market_facts"] = [{
            "fact_code": "index_above_ema50",
            "value": bool(market_strong),
            "source": "shanghai_close_vs_ema50",
        }]

        source_status = _source_status(stock)
        if source_status != "candidate":
            decision = False
            reason = "来源池状态{}不可晋级".format(source_status or "unknown")
        elif bp_type == "趋势延续候选" and len(trend_confirmations) < 2:
            decision = False
            reason = "趋势延续候选要求至少两项30min确认"
        elif bp_type == "强势启动候选" and not _has_eligible_confirmation(
            confirmation_facts, "strong_startup"
        ):
            decision = False
            reason = "强势启动要求日线strong且30min为S/A"
        else:
            decision, reason = _admit(
                bp_type,
                tier,
                ma_ok,
                market_strong,
                strength,
                confirmed_by,
            )

        existing_effects = [
            row for row in (stock.get("market_effects") or [])
            if not (
                isinstance(row, dict)
                and row.get("fact_code") == "index_above_ema50"
                and row.get("stage") == "fusion_admission"
            )
        ]
        existing_effects.append(_fusion_market_effect(
            bp_type=bp_type,
            tier=tier,
            market_strong=market_strong,
            admitted=decision,
        ))
        stock["market_effects"] = existing_effects

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
                "strategy_source": stock.get("strategy_source", ""),
                "source_channel": stock.get("source_channel", ""),
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


def _confirmation_facts(stock, bp, bp_type, trend_confirmations):
    existing = stock.get("confirmation_facts") or bp.get("confirmation_facts")
    if isinstance(existing, list) and existing:
        return [dict(row) for row in existing if isinstance(row, dict)]
    if bp_type == "强势启动候选":
        daily_grade = str(bp.get("daily_startup_grade") or "")
        confirm_grade = str(bp.get("sublevel_confirm_grade") or "")
        eligible = daily_grade == "strong" and confirm_grade in {"S", "A"}
        if eligible:
            reason_code = "strong_startup_sa_confirmed"
        elif daily_grade != "strong":
            reason_code = "strong_startup_daily_not_strong"
        else:
            reason_code = "strong_startup_sublevel_insufficient"
        return [{
            "owner_pool": "strong_startup",
            "stage": "30min_confirmation",
            "effect": "candidate" if eligible else "observe",
            "reason_code": reason_code,
            "eligible": eligible,
            "quality_grade": confirm_grade,
            "signals": list(bp.get("confirmations") or []),
        }]
    if bp_type == "趋势延续候选":
        eligible = len(trend_confirmations) >= 2
        return [{
            "owner_pool": "trend_continuation",
            "stage": "30min_confirmation",
            "effect": "candidate" if eligible else "observe",
            "reason_code": (
                "trend_two_confirmations_met"
                if eligible
                else "trend_confirmation_insufficient"
            ),
            "eligible": eligible,
            "confirmation_count": len(trend_confirmations),
            "required_count": 2,
            "signals": list(trend_confirmations),
        }]
    return []


def _has_eligible_confirmation(facts, owner_pool):
    return any(
        isinstance(row, dict)
        and row.get("owner_pool") == owner_pool
        and row.get("stage") == "30min_confirmation"
        and row.get("eligible") is True
        for row in facts or []
    )


def _fusion_market_effect(
    *, bp_type, tier, market_strong, admitted
):
    market_owned_candidates = {
        "三买候选",
        "二买候选",
        "中枢低吸候选",
        "盘整低吸候选",
        "底背驰候选",
        "强势启动候选",
    }
    uses_market_gate = (
        bp_type in market_owned_candidates
        or (bp_type == "三买" and tier == "formal")
    )
    return {
        "fact_code": "index_above_ema50",
        "owner_pool": "picks_fusion",
        "stage": "fusion_admission",
        "effect": "gate" if uses_market_gate else "ignored",
        "reason_code": (
            "fusion_strong_market_gate"
            if uses_market_gate and market_strong
            else "fusion_weak_market_gate"
            if uses_market_gate
            else "fusion_market_fact_not_used"
        ),
        "outcome": "admitted" if admitted else "rejected",
    }


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

    if bp_type == "趋势延续候选":
        if not ma_ok:
            return False, "趋势延续候选要求MA多头(MA5>MA10>MA20)"
        if not confirmed_by:
            return False, "趋势延续候选要求30min趋势确认"
        return True, "趋势延续候选独立通道通过"

    # Unknown type — do not admit
    return False, f"未知类型{bp_type}不默认放行"
