"""Lightweight explainable decision engine v1.

This module is intentionally pure and side-effect free: only pure functions and
in-memory calculations based on provided stock and market context data.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

DecisionResult = Dict[str, Any]


RECOMMEND = "recommend"
OBSERVE = "observe"
REJECT = "reject"

REC = "推荐"
WATCH = "观察"
WATCH_MISSING_POSITION = "暂不判断（位置信息不足）"
REJECT_HIGH = "不推荐（高位风险）"
REJECT_NORMAL = "不推荐"

DECISION_VERSION = "1"


def evaluate_stock(
    stock: Mapping[str, Any], market_context: Optional[Mapping[str, Any]] = None
) -> DecisionResult:
    """Evaluate one stock and return explainable structured decision output.

    Args:
        stock: Stock signal dictionary.
        market_context: Optional external context to enrich sentiment evaluation.
    """
    stock_dict = _to_dict(stock)
    context = _to_dict(market_context)
    position_known = _safe_float(_extract_distance(stock_dict), default=None) is not None

    structure_score, structure_reasons = _calc_structure_score(stock_dict, context)
    position_score, position_reasons = _calc_position_score(stock_dict)
    sentiment_score, sentiment_reasons = _calc_sentiment_score(stock_dict, context)

    total_score = structure_score + position_score + sentiment_score

    if not position_known:
        decision = WATCH_MISSING_POSITION
        decision_code = OBSERVE
    elif position_score < -10:
        decision = REJECT_HIGH
        decision_code = REJECT
    elif total_score >= 60:
        decision = REC
        decision_code = RECOMMEND
    elif total_score >= 40:
        decision = WATCH
        decision_code = OBSERVE
    else:
        decision = REJECT_NORMAL
        decision_code = REJECT

    return {
        "version": DECISION_VERSION,
        "code": stock_dict.get("code", "UNKNOWN"),
        "name": stock_dict.get("name", ""),
        "decision": decision,
        "decision_code": decision_code,
        "total_score": total_score,
        "structure": {"score": structure_score, "reasons": structure_reasons},
        "position": {"score": position_score, "reasons": position_reasons},
        "sentiment": {"score": sentiment_score, "reasons": sentiment_reasons},
    }


def _calc_structure_score(stock: Mapping[str, Any], context: Mapping[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if _safe_bool(stock.get("breakout_structure")):
        score += 40
        reasons.append("突破结构")

    trend = stock.get("trend_type") or _resolve_market_trend(context)
    if trend == "上升趋势":
        score += 20
        reasons.append("趋势向上")
    elif trend == "震荡":
        score += 5
        reasons.append("震荡结构")
    elif trend:
        score -= 5
        reasons.append("趋势未定")
    else:
        score -= 5
        reasons.append("趋势信息不足")
        reasons.append("结构信息不足")

    pullback_confirmed = stock.get("pullback_confirmed")
    if _safe_bool(pullback_confirmed):
        score += 15
        reasons.append("回踩确认")
    elif pullback_confirmed is None:
        pullback_confirmed = _is_confirmed_by(stock)
        if _safe_bool(pullback_confirmed):
            score += 15
            reasons.append("回踩确认")

    if _safe_int(stock.get("signal_age_days")) is not None:
        signal_age = _safe_int(stock.get("signal_age_days")) or 0
        if signal_age >= 30:
            score -= 8
            reasons.append("信号持续期过长")

    if _safe_int(stock.get("startup_age_days")) is not None:
        startup_age = _safe_int(stock.get("startup_age_days")) or 0
        if startup_age >= 20:
            score -= 6
            reasons.append("启动时间偏久")

    # Conservative fallback for missing structure-relevant information
    if not reasons:
        reasons.append("结构信息不足")

    return score, reasons


def _calc_position_score(stock: Mapping[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    dist = _safe_float(_extract_distance(stock), default=None)

    if dist is None:
        score -= 15
        reasons.append("位置信息不足")
    elif dist <= 5:
        score += 35
        reasons.append("低位启动区")
    elif dist <= 15:
        score += 15
        reasons.append("中位运行")
    elif dist <= 30:
        score -= 10
        reasons.append("偏高位置")
    else:
        score -= 35
        reasons.append("高位追涨风险")

    if _safe_bool(stock.get("is_extended_move")):
        score -= 25
        reasons.append("加速末端")

    recent_run_days = _safe_int(stock.get("recent_run_days"), default=None)
    if recent_run_days is None:
        recent_run_days = _safe_int(stock.get("startup_age_days"), default=None)
    if recent_run_days is not None and recent_run_days >= 5:
        score -= 15
        reasons.append("连续上涨过久")

    # Conservative fallback for unknown position state.
    if dist is None:
        score -= 5
        reasons.append("位置估计偏保守")

    return score, reasons


def _calc_sentiment_score(stock: Mapping[str, Any], context: Mapping[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if _is_sector_hot(stock, context):
        score += 20
        reasons.append("板块热点")

    if _is_volume_expansion(stock):
        score += 15
        reasons.append("放量启动")

    phase = _resolve_market_phase(stock, context)
    if phase == "主升":
        score += 25
        reasons.append("主升周期")
    elif phase == "震荡":
        score += 5
        reasons.append("震荡市")
    elif phase == "退潮":
        score -= 30
        reasons.append("退潮期风险")
    elif phase:
        score -= 5
        reasons.append("市场不明")

    if _safe_bool(_as_bool(stock.get("overheat"))):
        score -= 25
        reasons.append("情绪过热")

    if _safe_bool(stock.get("limit_up_recent")) or _safe_bool(context.get("limit_up_recent")):
        score += 10
        reasons.append("涨停情绪强化")

    if _safe_bool(stock.get("ma_bullish")):
        score += 8
        reasons.append("MA 均线多头")

    gf_dma_health = stock.get("gf_dma_health")
    if isinstance(gf_dma_health, Mapping):
        health_text = " ".join(
            str(gf_dma_health.get(key) or "")
            for key in ("label", "trend_stage", "fomo_risk", "summary")
        )
    else:
        health_text = str(gf_dma_health or "")
    if health_text:
        health_text_lower = health_text.strip().lower()
        if any(token in health_text_lower for token in ("弱", "破坏", "overheat", "过热", "偏弱", "bad", "broken")):
            score -= 12
            reasons.append("趋势健康度偏弱")

    if _safe_float(stock.get("change_pct")) is not None:
        change_pct = _safe_float(stock.get("change_pct"), 0.0)
        if change_pct is not None and change_pct >= 0:
            score += min(12, int(change_pct // 3))
            if change_pct >= 0:
                reasons.append("动能积极")

    if not reasons:
        reasons.append("情绪信息不足")

    return score, reasons


def _extract_distance(stock: Mapping[str, Any]) -> Any:
    if stock.get("position_data_status") != "verified":
        return None

    dist = _safe_float(stock.get("position_distance_pct"), default=None)
    reference_price = _safe_float(stock.get("position_reference_price"), default=None)
    reference_type = stock.get("position_reference_type")
    evidence_date = stock.get("position_evidence_date")
    if dist is None or reference_price is None or reference_price <= 0:
        return None
    if not isinstance(reference_type, str) or not reference_type.strip():
        return None
    if not _is_iso_date(evidence_date):
        return None
    return dist


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.isoformat() == normalized


def _resolve_market_phase(stock: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    for key in ("market_phase", "market_regime", "market_trend"):
        phase = stock.get(key)
        if isinstance(phase, str) and phase.strip():
            return phase.strip()

    for key in ("market_phase", "market_regime", "market_trend"):
        phase = context.get(key)
        if isinstance(phase, str) and phase.strip():
            return phase.strip()

    market_indices = _to_dict(context.get("market_indices"))
    shanghai = _to_dict(market_indices.get("上证指数"))
    change_pct = _safe_float(shanghai.get("change_pct"), default=None)
    if change_pct is not None:
        if change_pct >= 1.0:
            return "主升"
        if change_pct <= -1.5:
            return "退潮"
        return "震荡"

    return ""


def _resolve_market_trend(context: Mapping[str, Any]) -> str:
    phase = _resolve_market_phase({}, context)
    return phase


def _is_sector_hot(stock: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    sector_strength_label = stock.get("sector_strength_label")
    if isinstance(sector_strength_label, str):
        label = sector_strength_label.strip()
        if label in {"强", "热门", "热", "强势", "强烈", "高", "上行"}:
            return True

    sector_rank = _safe_int(stock.get("sector_rank"), default=None)
    if sector_rank is not None and sector_rank > 0:
        # Rank 越小越好，取前 8 作为强势板块 proxy
        if sector_rank <= 8:
            return True

    sector_flow = stock.get("sector_flow")
    sector_flow_norm = _safe_float(sector_flow, default=None)
    if sector_flow_norm is not None:
        return sector_flow_norm >= 0.6

    context_sector_flow = _safe_float(context.get("sector_flow"), default=None)
    if context_sector_flow is not None:
        return context_sector_flow >= 0.6

    return False


def _is_volume_expansion(stock: Mapping[str, Any]) -> bool:
    volume_ratio = _safe_float(stock.get("volume_ratio"), default=None)
    if volume_ratio is None:
        return False
    return volume_ratio >= 1.2


def _is_confirmed_by(stock: Mapping[str, Any]) -> bool:
    confirmed_by = stock.get("confirmed_by")
    if isinstance(confirmed_by, str) and confirmed_by.strip():
        return True
    bp = _to_dict(stock.get("best_buy_point"))
    confirmed_by_bp = bp.get("confirmed_by")
    if isinstance(confirmed_by_bp, str) and confirmed_by_bp.strip():
        return True
    return _has_nonempty_strings(_to_list(stock.get("confirmations"))) or _has_nonempty_strings(
        _to_list(_to_dict(stock.get("best_buy_point")).get("confirmations"))
    )


def _to_dict(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _to_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "是", "y"}
    if isinstance(value, int):
        return value != 0
    return False


def _as_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered in {"true", "1", "yes", "是", "y", "overheat", "overheated"}
    return bool(value)


def _has_nonempty_strings(values: Iterable[Any]) -> bool:
    for item in values:
        if isinstance(item, str) and item.strip():
            return True
    return False


__all__ = ["evaluate_stock", "DECISION_VERSION"]
