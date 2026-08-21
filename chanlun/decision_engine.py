"""Lightweight explainable decision engine v1.

This module is intentionally pure and side-effect free: only pure functions and
in-memory calculations based on provided stock and market context data.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import config

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
    position_known = _has_verified_position_evidence(stock_dict)

    structure_score, structure_reasons = _calc_structure_score(stock_dict, context)
    position_score, position_reasons = _calc_position_score(stock_dict)
    sentiment_score, sentiment_reasons = _calc_sentiment_score(
        stock_dict, context, respect_market_ownership=True
    )

    total_score = structure_score + position_score + sentiment_score
    source_status_cap = _source_status_cap(stock_dict)
    decision, decision_code, risk_reasons = _classify_decision(
        position_known=position_known,
        position_score=position_score,
        structure_score=structure_score,
        total_score=total_score,
        context=context,
        source_status_cap=source_status_cap,
    )

    legacy_stock = dict(stock_dict)
    if str(stock_dict.get("source_channel") or "").strip() == "trend_continuation":
        legacy_stock["trend_type"] = "up"
    legacy_structure_score, legacy_structure_reasons = _calc_structure_score(
        legacy_stock, context, normalize_trend=False
    )
    legacy_position_score, legacy_position_reasons = _calc_low_position_score(
        legacy_stock
    )
    legacy_sentiment_score, legacy_sentiment_reasons = _calc_sentiment_score(
        legacy_stock, context, respect_market_ownership=False
    )
    legacy_total_score = (
        legacy_structure_score + legacy_position_score + legacy_sentiment_score
    )
    _, legacy_decision_code, legacy_risk_reasons = _classify_decision(
        position_known=_safe_float(
            _extract_absolute_position_percentile(stock_dict), default=None
        ) is not None,
        position_score=legacy_position_score,
        structure_score=legacy_structure_score,
        total_score=legacy_total_score,
        context=context,
        source_status_cap=source_status_cap,
    )

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
        "risk_reasons": risk_reasons,
        "source_status_cap": source_status_cap,
        "market_effects": _collect_market_effects(
            stock_dict, context, risk_reasons
        ),
        "legacy_h4_v1": {
            "decision_code": legacy_decision_code,
            "total_score": legacy_total_score,
            "structure": {
                "score": legacy_structure_score,
                "reasons": legacy_structure_reasons,
            },
            "position": {
                "score": legacy_position_score,
                "reasons": legacy_position_reasons,
            },
            "sentiment": {
                "score": legacy_sentiment_score,
                "reasons": legacy_sentiment_reasons,
            },
            "risk_reasons": legacy_risk_reasons,
        },
    }


def _classify_decision(
    *,
    position_known: bool,
    position_score: int,
    structure_score: int,
    total_score: int,
    context: Mapping[str, Any],
    source_status_cap: str,
) -> Tuple[str, str, List[str]]:
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

    risk_reasons = _market_sentiment_risk_reasons(context)
    if decision_code == RECOMMEND and risk_reasons:
        decision = WATCH
        decision_code = OBSERVE
    elif (
        decision_code == REJECT
        and risk_reasons
        and position_score >= 15
        and structure_score >= 0
        and total_score >= 20
    ):
        decision = WATCH
        decision_code = OBSERVE
        risk_reasons.append("弱市只观察")

    if source_status_cap == OBSERVE and decision_code == RECOMMEND:
        decision = "观察（来源池未取得推荐资格）"
        decision_code = OBSERVE
    elif source_status_cap == REJECT and decision_code != REJECT:
        decision = "不推荐（来源池已拒绝）"
        decision_code = REJECT
    return decision, decision_code, risk_reasons


def _source_status_cap(stock: Mapping[str, Any]) -> str:
    explicit = str(stock.get("source_status") or "").strip().lower()
    if explicit == REJECT:
        return REJECT
    if explicit in {OBSERVE, "insufficient", "watch", "internal"}:
        return OBSERVE
    source_rows = _to_list(stock.get("strategy_sources"))
    statuses = {
        str(_to_dict(row).get("source_status") or "").strip().lower()
        for row in source_rows
    }
    statuses.discard("")
    if statuses and "candidate" not in statuses:
        return REJECT if REJECT in statuses else OBSERVE
    if str(stock.get("view") or "").strip().lower() == "observation":
        return OBSERVE
    if str(stock.get("tier") or "").strip().lower() == "watch":
        return OBSERVE
    best_buy = _to_dict(stock.get("best_buy_point"))
    if (
        best_buy.get("daily_startup_grade") in {"weak", "pullback"}
        or best_buy.get("sublevel_confirm_grade") in {"B", "C"}
    ):
        return OBSERVE
    return "candidate"


def _calc_structure_score(
    stock: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    normalize_trend: bool = True,
) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if _safe_bool(stock.get("breakout_structure")):
        score += 40
        reasons.append("突破结构")

    trend = stock.get("trend_type") or _resolve_market_trend(context)
    if normalize_trend:
        trend = _normalize_trend_type(trend)
    if trend in {"上升趋势", "uptrend"}:
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
    if str(stock.get("source_channel") or "").strip() == "trend_continuation":
        return _calc_trend_position_score(stock)
    return _calc_low_position_score(stock)


def _calc_low_position_score(stock: Mapping[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    percentile = _safe_float(
        _extract_absolute_position_percentile(stock), default=None
    )

    if percentile is None:
        score -= 15
        reasons.append("位置信息不足")
    elif percentile <= 25:
        score += 35
        reasons.append("120日收盘分位低位")
    elif percentile <= 60:
        score += 15
        reasons.append("120日收盘分位中位")
    elif percentile <= 80:
        score -= 10
        reasons.append("120日收盘分位偏高")
    else:
        score -= 35
        reasons.append("120日收盘分位高位风险")

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
    if percentile is None:
        score -= 5
        reasons.append("位置估计偏保守")

    return score, reasons


def _calc_trend_position_score(stock: Mapping[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    distance = _safe_float(stock.get("position_distance_pct"), default=None)
    gap_pct = _safe_float(stock.get("gap_pct"), default=0.0) or 0.0
    change_pct = _safe_float(stock.get("change_pct"), default=0.0) or 0.0

    if distance is None:
        score -= 20
        reasons.append("趋势参考位信息不足")
    elif distance < -0.5:
        score -= 35
        reasons.append("跌破趋势参考位")
    elif distance <= 4.0:
        score += 30
        reasons.append("趋势参考位附近")
    elif distance <= float(config.TREND_CONTINUATION_MAX_EXTENSION_PCT):
        score += 10
        reasons.append("趋势延伸可控")
    else:
        score -= 35
        reasons.append("远离趋势参考位")

    if gap_pct >= float(config.TREND_CONTINUATION_MAX_GAP_PCT):
        score -= 20
        reasons.append("趋势跳空过大")
    if change_pct >= float(config.LIMIT_UP_THRESHOLD):
        score -= 25
        reasons.append("涨停当日不追")
    if _safe_bool(stock.get("is_extended_move")) or _safe_bool(stock.get("overheat")):
        score -= 25
        reasons.append("趋势加速过热")

    recent_run_days = _safe_int(stock.get("recent_run_days"), default=None)
    if recent_run_days is not None and recent_run_days >= 5:
        score -= 15
        reasons.append("趋势连续拉升过久")
    return score, reasons


def _calc_sentiment_score(
    stock: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    respect_market_ownership: bool = True,
) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if _is_sector_hot(stock, context):
        score += 20
        reasons.append("板块热点")

    if _is_volume_expansion(stock):
        score += 15
        reasons.append("放量启动")

    phase, _ = _resolve_market_phase_detail(
        stock, context, respect_market_ownership=respect_market_ownership
    )
    if phase == "主升":
        score += 25
        reasons.append("主升周期")
    elif phase == "震荡":
        score += 5
        reasons.append("震荡市")
    elif phase == "退潮":
        score -= 30
        reasons.append("退潮期风险")
    elif phase == "弱市":
        score -= 10
        reasons.append("弱市风险")
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


def _extract_absolute_position_percentile(stock: Mapping[str, Any]) -> Any:
    if stock.get("position_data_status") != "verified":
        return None

    percentile = _safe_float(stock.get("position_absolute_percentile"), default=None)
    window = _safe_int(stock.get("position_absolute_window"), default=None)
    evidence_date = stock.get("position_evidence_date")
    if percentile is None or percentile < 0 or percentile > 100:
        return None
    if window is None or window < 120:
        return None
    if not _is_iso_date(evidence_date):
        return None
    return percentile


def _has_verified_position_evidence(stock: Mapping[str, Any]) -> bool:
    if str(stock.get("source_channel") or "").strip() != "trend_continuation":
        return _safe_float(
            _extract_absolute_position_percentile(stock), default=None
        ) is not None
    return bool(
        stock.get("position_data_status") == "verified"
        and _safe_float(stock.get("position_distance_pct"), default=None) is not None
        and (_safe_float(stock.get("position_reference_price"), default=0.0) or 0.0) > 0
        and str(stock.get("position_reference_type") or "").strip()
        and _is_iso_date(stock.get("position_evidence_date"))
    )


def _normalize_trend_type(value: Any) -> str:
    normalized = str(value or "").strip()
    lowered = normalized.lower()
    if lowered in {"up", "uptrend", "bull", "bullish"} or normalized in {
        "上升趋势", "上涨趋势", "趋势向上",
    }:
        return "uptrend"
    if lowered in {"range", "sideways", "neutral"} or normalized == "震荡":
        return "震荡"
    return normalized


def _market_sentiment_risk_reasons(context: Mapping[str, Any]) -> List[str]:
    sentiment = _to_dict(context.get("market_sentiment"))
    reasons: List[str] = []
    score = _safe_float(sentiment.get("score"), default=None)
    if score is not None and score < 40:
        reasons.append("市场情绪偏冷")
    turning_signal = str(sentiment.get("turning_signal") or "").strip().lower()
    if turning_signal == "turning_weaker":
        reasons.append("市场情绪转弱")
    return reasons


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.isoformat() == normalized


def _resolve_market_phase_detail(
    stock: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    respect_market_ownership: bool = True,
) -> Tuple[str, str]:
    owned_index_fact = (
        respect_market_ownership
        and _has_owned_market_fact(stock, "index_above_ema50")
    )
    for key in ("market_phase", "market_regime", "market_trend"):
        if key == "market_regime" and owned_index_fact:
            continue
        phase = stock.get(key)
        if isinstance(phase, str) and phase.strip():
            fact_code = (
                "index_above_ema50"
                if key == "market_regime" and phase.strip().lower() in {"strong", "weak"}
                else "explicit_{}".format(key)
            )
            return _normalize_market_phase(phase), fact_code

    for key in ("market_phase", "market_regime", "market_trend"):
        phase = context.get(key)
        if isinstance(phase, str) and phase.strip():
            return _normalize_market_phase(phase), "context_{}".format(key)

    market_indices = _to_dict(context.get("market_indices"))
    shanghai = _to_dict(market_indices.get("上证指数"))
    change_pct = _safe_float(shanghai.get("change_pct"), default=None)
    if change_pct is not None:
        if change_pct >= 1.0:
            return "主升", "shanghai_change_pct"
        if change_pct <= -1.5:
            return "退潮", "shanghai_change_pct"
        return "震荡", "shanghai_change_pct"

    return "", ""


def _resolve_market_phase(stock: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    phase, _ = _resolve_market_phase_detail(stock, context)
    return phase


def _normalize_market_phase(phase: str) -> str:
    normalized = str(phase).strip()
    lowered = normalized.lower()
    if lowered == "weak" or normalized in {"弱", "偏弱"}:
        return "弱市"
    if lowered in {"weaker", "bear", "bearish"} or normalized in {"走弱", "退潮"}:
        return "退潮"
    if lowered in {"strong", "bull", "bullish"} or normalized in {"强", "偏强", "走强", "主升"}:
        return "主升"
    if lowered in {"neutral", "range", "sideways"} or normalized in {"中性", "震荡"}:
        return "震荡"
    return normalized


def _resolve_market_trend(context: Mapping[str, Any]) -> str:
    phase = _resolve_market_phase({}, context)
    return phase


def _has_owned_market_fact(stock: Mapping[str, Any], fact_code: str) -> bool:
    return any(
        isinstance(row, Mapping)
        and row.get("fact_code") == fact_code
        and str(row.get("owner_pool") or "").strip()
        and str(row.get("stage") or "").strip()
        and str(row.get("effect") or "").strip()
        and str(row.get("reason_code") or "").strip()
        for row in _to_list(stock.get("market_effects"))
    )


def _collect_market_effects(
    stock: Mapping[str, Any],
    context: Mapping[str, Any],
    risk_reasons: Iterable[str],
) -> List[Dict[str, Any]]:
    effects = [
        dict(row)
        for row in _to_list(stock.get("market_effects"))
        if isinstance(row, Mapping)
    ]
    phase, fact_code = _resolve_market_phase_detail(stock, context)
    if phase and fact_code:
        delta = {
            "主升": 25,
            "震荡": 5,
            "退潮": -30,
            "弱市": -10,
        }.get(phase, -5)
        effects.append({
            "fact_code": fact_code,
            "owner_pool": _decision_owner_pool(stock),
            "stage": "decision_score",
            "effect": "bonus" if delta > 0 else "penalty",
            "reason_code": "decision_market_phase_{}".format(
                "positive" if delta > 0 else "negative"
            ),
            "score_delta": delta,
        })
    for reason in risk_reasons:
        if reason not in {"市场情绪偏冷", "市场情绪转弱"}:
            continue
        effects.append({
            "fact_code": (
                "market_sentiment_score"
                if reason == "市场情绪偏冷"
                else "market_sentiment_turning_signal"
            ),
            "owner_pool": _decision_owner_pool(stock),
            "stage": "decision_gate",
            "effect": "gate",
            "reason_code": (
                "market_sentiment_cold_cap"
                if reason == "市场情绪偏冷"
                else "market_sentiment_weakening_cap"
            ),
        })
    return effects


def _decision_owner_pool(stock: Mapping[str, Any]) -> str:
    return str(
        stock.get("strategy_source")
        or stock.get("source_channel")
        or "general_decision"
    ).strip()


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
    bp = _to_dict(stock.get("best_buy_point"))
    facts = _to_list(stock.get("confirmation_facts")) + _to_list(
        bp.get("confirmation_facts")
    )
    typed_facts = [row for row in facts if isinstance(row, Mapping)]
    if typed_facts:
        return any(row.get("eligible") is True for row in typed_facts)

    texts = [stock.get("confirmed_by"), bp.get("confirmed_by")]
    texts.extend(_to_list(stock.get("confirmations")))
    texts.extend(_to_list(bp.get("confirmations")))
    accepted_tokens = (
        "底分型",
        "MACD金叉",
        "关键位不破",
        "EMA5收复",
        "回踩不破",
        "二买",
        "三买",
        "两阳夹",
        "突破位不破",
        "EMA5维持",
        "缩量回踩",
    )
    return any(
        any(token in str(text or "") for token in accepted_tokens)
        for text in texts
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
