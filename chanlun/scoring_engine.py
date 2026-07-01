"""Unified opportunity scoring for report ranking.

This module owns the report ranking score only. Strategy-native scores such as
``score`` and ``boom_score`` remain raw signal inputs, not final ranking keys.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


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

DATA_PENALTY_STALE = 6.0
DATA_PENALTY_MISSING = 10.0
DATA_PENALTY_FALLBACK = 4.0
DATA_PENALTY_UNVERIFIED = 3.0
MAX_MOMENTUM_SCORE = 20.0
MAX_MARKET_SCORE = 15.0
MAX_RISK_PENALTY = 30.0
MAX_DATA_PENALTY = 20.0
ALPHA_MULTIPLIER_MIN = 1.00
ALPHA_MULTIPLIER_MAX = 1.04
ALPHA_BONUS_LIMIT = 5.0


def compute_opportunity_score(
    item: Mapping[str, Any],
    source: str,
    context: Mapping[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return the unified report ranking score and an explainable trace."""
    ctx = _to_dict(context)
    sources = _normalize_sources(ctx.get("sources"), source)
    by_source = _normalize_by_source(ctx.get("by_source"), item, source)
    metrics = _to_dict(ctx.get("metrics"))
    risk_flags_override = _to_list_of_str(ctx.get("risk_flags"))
    source_count = _safe_int(ctx.get("source_count"))
    if source_count is None:
        source_count = len(sources)
    else:
        source_count = max(source_count, len(sources))

    distance = _safe_float(metrics.get("distance"))
    if distance is None:
        distance = _resolve_distance_pct(item, source)
    if distance is not None and "distance" not in metrics:
        metrics["distance"] = distance

    change_pct = _safe_float(metrics.get("change_pct"))
    if change_pct is None:
        change_pct = _resolve_change_pct(item)

    signal_score = _score_signal(item, source)
    entry_score = _score_entry(distance)
    momentum_score = _score_momentum(change_pct)
    market_score = _score_market(source, source_count)

    risk_flags = _collect_risk_flags(by_source, sources)
    for flag in risk_flags_override:
        if flag not in risk_flags:
            risk_flags.append(flag)
    risk_penalty = _score_risk_penalty(risk_flags)
    data_penalty = _score_data_penalty(ctx.get("data_quality"), by_source, sources)

    raw_score = signal_score + entry_score + momentum_score + market_score - risk_penalty - data_penalty
    base_opportunity_score = max(0, int(round(raw_score)))

    if "alpha_enabled" in ctx:
        alpha_enabled = bool(ctx.get("alpha_enabled"))
    else:
        alpha_enabled = ("alpha_features" in ctx) or _has_alpha_inputs(ctx, item)
    alpha_bonus, alpha_multiplier = 0.0, 1.0
    if alpha_enabled:
        alpha_features = _resolve_alpha_features(ctx, item, metrics, source)
        (
            alpha_bonus,
            pool_quality_bonus,
            pool_quality_score,
            pool_quality_tier,
            pool_quality_tags,
            pool_quality_components,
        ) = _score_alpha_bonus(
            alpha_features,
            by_source,
            source,
            item,
            metrics,
        )
        alpha_multiplier = _resolve_alpha_multiplier(alpha_features, alpha_bonus)
    else:
        alpha_features = {}
        pool_quality_bonus = 0.0
        pool_quality_score = 0.0
        pool_quality_tags: list[str] = []
        pool_quality_tier = "none"
        pool_quality_components: list[dict[str, Any]] = []
    opportunity_score = max(0, int(round(base_opportunity_score * alpha_multiplier + alpha_bonus)))

    trace = {
        "base_source": source,
        "source_count": len(sources),
        "signal_score": signal_score,
        "entry_score": entry_score,
        "momentum_score": momentum_score,
        "market_score": market_score,
        "risk_penalty": risk_penalty,
        "data_penalty": data_penalty,
        "alpha_features": alpha_features,
        "alpha_bonus": round(alpha_bonus, 4),
        "pool_quality_bonus": round(pool_quality_bonus, 4),
        "pool_quality_score": round(pool_quality_score, 4),
        "pool_quality_tags": pool_quality_tags,
        "pool_quality_tier": pool_quality_tier,
        "pool_quality_components": pool_quality_components,
        "alpha_multiplier": round(alpha_multiplier, 4),
        "base_opportunity_score": base_opportunity_score,
        "risk_flags": risk_flags,
        "opportunity_score": opportunity_score,
        "distance_from_reference_pct": distance,
        "change_pct": change_pct,
    }
    for src in sources:
        trace[f"source:{src}"] = trace.get(f"source:{src}", 0) + 1
    return opportunity_score, trace


def _normalize_sources(value: Any, fallback: str) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        sources = [str(v) for v in value if v]
    else:
        sources = [fallback]
    deduped: list[str] = []
    seen: set[str] = set()
    for source_name in sources or []:
        if source_name in seen:
            continue
        seen.add(source_name)
        deduped.append(source_name)
    return deduped or [fallback]


def _normalize_by_source(value: Any, item: Mapping[str, Any], source: str) -> dict[str, Mapping[str, Any]]:
    if isinstance(value, Mapping):
        result = {}
        for key, row in value.items():
            if isinstance(row, Mapping):
                result[str(key)] = row
        if result:
            return result
    return {source: item}


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _score_signal(item: Mapping[str, Any], source: str) -> float:
    cap = SIGNAL_CAPS.get(source, 0.0)
    if source == "confirming":
        return cap
    raw_key = "boom_score" if source == "acceleration" else "score"
    raw = _safe_float(item.get(raw_key), 0.0) or 0.0
    if raw <= 0:
        return 0.0
    return round(min(cap, max(0.0, raw / 100.0 * cap)), 2)


def _score_entry(distance_pct: float | None) -> float:
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


def _score_momentum(change_pct: float | None) -> float:
    if change_pct is None:
        return 0.0
    if change_pct <= 0:
        return 0.0
    return round(min(MAX_MOMENTUM_SCORE, change_pct * 1.5), 2)


def _score_market(source: str, source_count: int) -> float:
    base = MARKET_BASE.get(source, 5.0)
    multi_source_bonus = max(0, source_count - 1) * 2.0
    return min(MAX_MARKET_SCORE, base + multi_source_bonus)


def _resolve_alpha_features(
    context: Mapping[str, Any],
    item: Mapping[str, Any],
    metrics: Mapping[str, Any],
    source: str,
) -> dict[str, Any]:
    market_ctx = _to_dict(context.get("market"))
    alpha_ctx = _to_dict(context.get("alpha_features"))
    bp = _to_dict(item.get("best_buy_point"))
    confirmations = _merge_unique_str_lists(
        _to_list_of_str(item.get("confirmations")),
        _to_list_of_str(bp.get("confirmations")),
    )
    startup_signals = _merge_unique_str_lists(
        _to_list_of_str(item.get("startup_signals")),
        _to_list_of_str(bp.get("startup_signals")),
    )
    confirmed_by = _safe_str(item.get("confirmed_by")) or _safe_str(bp.get("confirmed_by"))
    ma_bullish = _to_bool(item.get("ma_bullish"))

    features = {
        "market_regime_factor": {},
        "sector_strength_factor": {},
        "momentum_persistence": None,
        "breakout_quality": {},
        "alpha_multiplier": _safe_float(alpha_ctx.get("alpha_multiplier")),
    }

    # 1) Market regime: from market context first, then alpha features.
    market_regime = {}
    for source_dict in (market_ctx, alpha_ctx):
        index_trend_score = _safe_float(source_dict.get("index_trend_score"))
        breadth_score = _safe_float(source_dict.get("breadth_score"))
        regime_factor = _safe_float(source_dict.get("market_regime_factor"))
        if index_trend_score is not None:
            market_regime["index_trend_score"] = index_trend_score
        if breadth_score is not None:
            market_regime["breadth_score"] = breadth_score
        if regime_factor is not None:
            market_regime["market_regime_factor"] = regime_factor

    # 2) Sector strength: item first, then alpha features.
    sector_strength = {
        "sector_flow": _safe_float(item.get("sector_flow")),
        "sector_rank": _safe_float(item.get("sector_rank")),
        "sector_strength_factor": _safe_float(item.get("sector_strength_factor")),
    }
    for key in ("sector_flow", "sector_rank", "sector_strength_factor"):
        val = _safe_float(alpha_ctx.get(key))
        if val is not None:
            sector_strength[key] = val

    # 3) Momentum persistence from explicit signal first, fallback to closes slope.
    momentum_persistence = _safe_float(alpha_ctx.get("momentum_persistence"))
    if momentum_persistence is None:
        momentum_persistence = _safe_float(item.get("momentum_persistence"))

    # 4) Breakout quality from price structure.
    breakout_quality = {
        "volume_ratio": _safe_float(item.get("volume_ratio")),
        "confirmed_by": confirmed_by,
        "ma_bullish": ma_bullish,
        "confirmations": confirmations,
        "startup_signals": startup_signals,
        "distance": _safe_float(metrics.get("distance")),
    }

    features["market_regime_factor"] = market_regime
    features["sector_strength_factor"] = sector_strength
    features["momentum_persistence"] = momentum_persistence
    features["breakout_quality"] = breakout_quality
    features["pool_quality"] = _to_dict(alpha_ctx.get("pool_quality"))
    features["ma_bullish"] = ma_bullish
    features["confirmed_by"] = confirmed_by
    features["confirmations"] = confirmations
    features["startup_signals"] = startup_signals
    return features


def _score_alpha_bonus(
    alpha_features: Mapping[str, Any],
    by_source: Mapping[str, Mapping[str, Any]],
    source: str,
    item: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> tuple[float, float, float, str, list[str], list[dict[str, Any]]]:
    bonus = 0.0
    bonus += _score_market_regime_bonus(_to_dict(alpha_features.get("market_regime_factor")))
    bonus += _score_sector_strength_bonus(_to_dict(alpha_features.get("sector_strength_factor")))
    bonus += _score_momentum_persistence_bonus(
        alpha_features.get("momentum_persistence"),
        item,
        source,
    )
    bonus += _score_breakout_quality_bonus(_to_dict(alpha_features.get("breakout_quality")), by_source, source, item, metrics)
    (
        pool_quality_bonus,
        pool_quality_score,
        pool_quality_tier,
        pool_quality_tags,
        pool_quality_components,
    ) = _score_pool_quality_bonus(_to_dict(alpha_features.get("pool_quality")))
    bonus += pool_quality_bonus

    bonus = _clamp(bonus, 0.0, ALPHA_BONUS_LIMIT)
    return (
        round(bonus, 4),
        pool_quality_bonus,
        pool_quality_score,
        pool_quality_tier,
        pool_quality_tags,
        pool_quality_components,
    )


def _score_pool_quality_bonus(pool_quality: Mapping[str, Any]) -> tuple[float, float, str, list[str], list[dict[str, Any]]]:
    def _to_unit(value: float | None) -> float:
        if value is None:
            return 0.0
        normalized = value if abs(value) <= 1.2 else value / 100.0
        return _clamp(normalized, 0.0, 1.0)

    def _to_percent(value: float | None) -> float:
        return _to_unit(value) * 100.0

    liquidity_pct = _to_percent(_safe_float(pool_quality.get("liquidity_score")))
    growth_pct = _to_percent(_safe_float(pool_quality.get("growth_board_score")))
    sector_pct = _to_percent(_safe_float(pool_quality.get("sector_quality_score")))

    def _passes(value: float, threshold: float) -> bool:
        return value >= threshold

    elite_tier = _passes(liquidity_pct, 70.0) and _passes(growth_pct, 55.0) and _passes(sector_pct, 70.0)
    strong_tier = _passes(liquidity_pct, 55.0) and _passes(growth_pct, 55.0) and _passes(sector_pct, 55.0)

    tier = "none"
    pool_quality_bonus = 0.0
    if elite_tier:
        tier = "elite"
        avg_pct = (liquidity_pct + growth_pct + sector_pct) / 3.0
        pool_quality_bonus = _clamp(avg_pct / 100.0 * 3.0, 0.0, 3.0)
    elif strong_tier:
        tier = "strong"
        avg_pct = (liquidity_pct + growth_pct + sector_pct) / 3.0
        pool_quality_bonus = _clamp(avg_pct / 100.0 * 1.8, 0.0, 1.8)
    else:
        pass_count = sum(
            1
            for value in (liquidity_pct, growth_pct, sector_pct)
            if _passes(value, 55.0)
        )
        if pass_count >= 2:
            tier = "partial"
            top_two = sorted([liquidity_pct, growth_pct, sector_pct], reverse=True)[:2]
            avg_top_two = (top_two[0] + top_two[1]) / 2.0
            pool_quality_bonus = _clamp(avg_top_two / 100.0 * 0.7, 0.0, 0.7)

    pool_quality_score = _safe_float(pool_quality.get("pool_quality_score"))
    if pool_quality_score is None:
        pool_quality_score = _clamp((liquidity_pct + growth_pct + sector_pct) / 3.0, 0.0, 100.0)
    else:
        pool_quality_score = _clamp(pool_quality_score, 0.0, 100.0)

    pool_quality_tags = _to_list_of_str(pool_quality.get("pool_quality_tags"))
    pool_quality_components = [
        {
            "name": "liquidity",
            "score": round(liquidity_pct, 4),
            "threshold_elite": 70.0,
            "threshold_strong": 55.0,
        },
        {
            "name": "growth",
            "score": round(growth_pct, 4),
            "threshold_elite": 55.0,
            "threshold_strong": 55.0,
        },
        {
            "name": "sector",
            "score": round(sector_pct, 4),
            "threshold_elite": 70.0,
            "threshold_strong": 55.0,
        },
    ]
    return pool_quality_bonus, round(pool_quality_score, 4), tier, pool_quality_tags, pool_quality_components


def _resolve_alpha_multiplier(alpha_features: Mapping[str, Any], bonus: float) -> float:
    explicit = _safe_float(alpha_features.get("alpha_multiplier"))
    if explicit is not None:
        return _clamp(explicit, ALPHA_MULTIPLIER_MIN, ALPHA_MULTIPLIER_MAX)

    market_bonus = _score_market_regime_bonus(_to_dict(alpha_features.get("market_regime_factor")))
    sector_bonus = _score_sector_strength_bonus(_to_dict(alpha_features.get("sector_strength_factor")))
    momentum_source = alpha_features.get("momentum_persistence")
    if _safe_float(momentum_source) is not None:
        momentum_bonus = _score_momentum_persistence_bonus(momentum_source, {}, "")
    else:
        momentum_bonus = 0.0

    weighted = (market_bonus + sector_bonus + momentum_bonus) / 300.0
    return _clamp(1.0 + weighted + (bonus / 800.0), ALPHA_MULTIPLIER_MIN, ALPHA_MULTIPLIER_MAX)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _has_alpha_inputs(context: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    market = _to_dict(context.get("market"))
    if any(_safe_float(market.get(key)) is not None for key in ("index_trend_score", "breadth_score", "market_regime_factor")):
        return True
    if _safe_float(item.get("sector_flow")) is not None:
        return True
    if _safe_float(item.get("sector_strength_factor")) is not None:
        return True
    if _safe_float(item.get("momentum_persistence")) is not None:
        return True
    if _to_list_of_str(item.get("confirmations")):
        return True
    if _to_list_of_str(item.get("startup_signals")):
        return True
    if _safe_float(item.get("volume_ratio")) is not None and _safe_float(item.get("volume_ratio")) > 0:
        return True

    sector_rank = _safe_float(item.get("sector_rank"))
    if sector_rank is not None and sector_rank > 0:
        return True
    if _safe_str(item.get("confirmed_by")).strip():
        return True
    if _to_bool(item.get("ma_bullish"), default=False):
        return True
    bp = _to_dict(item.get("best_buy_point"))
    if _to_list_of_str(bp.get("confirmations")):
        return True
    if _to_list_of_str(bp.get("startup_signals")):
        return True
    if _safe_str(bp.get("confirmed_by")).strip():
        return True
    if _to_bool(bp.get("ma_bullish"), default=False):
        return True

    return False


def _score_market_regime_bonus(features: Mapping[str, Any]) -> float:
    index_score = _safe_float(features.get("index_trend_score"))
    breadth_score = _safe_float(features.get("breadth_score"))
    regime_factor = _safe_float(features.get("market_regime_factor"))

    regime_parts: list[float] = []
    if index_score is not None:
        regime_parts.append(_norm_percent_score(index_score))
    if breadth_score is not None:
        regime_parts.append(_norm_percent_score(breadth_score))

    score = 0.0
    if regime_parts:
        score += sum(regime_parts) / len(regime_parts) * 2.0
    if regime_factor is not None:
        score += _norm_percent_score(regime_factor) * 1.5
    return _clamp(score, 0.0, 3.0)


def _score_sector_strength_bonus(features: Mapping[str, Any]) -> float:
    sector_flow = _safe_float(features.get("sector_flow"))
    sector_rank = _safe_float(features.get("sector_rank"))
    sector_strength_factor = _safe_float(features.get("sector_strength_factor"))

    flow_signal = 0.0
    if sector_flow is not None:
        flow_signal = _clamp(sector_flow / 2000.0, 0.0, 1.0)

    rank_signal = 0.0
    if sector_rank is not None and sector_rank > 0:
        rank_signal = _clamp((10.0 - min(10.0, sector_rank)) / 10.0, 0.0, 1.0)

    direct_signal = 0.0
    if sector_strength_factor is not None:
        direct_signal = _clamp(
            sector_strength_factor if abs(sector_strength_factor) <= 1.2 else sector_strength_factor / 100.0,
            0.0,
            1.0,
        )

    score = flow_signal * 0.45 + rank_signal * 0.35 + direct_signal * 0.2
    score *= 2.5
    return _clamp(score, 0.0, 2.5)


def _score_momentum_persistence_bonus(
    momentum_persistence: Any,
    item: Mapping[str, Any],
    source: str,
) -> float:
    closes = []
    if isinstance(item, Mapping):
        closes = _to_list(item.get("closes"))

    persistence = _safe_float(momentum_persistence)
    if persistence is None and closes:
        persistence = _calc_momentum_persistence_from_closes(closes)
    if persistence is None:
        return 0.0

    if abs(persistence) > 1:
        persistence = persistence / 100.0
    return _clamp(persistence * 3.0, 0.0, 2.5)


def _score_breakout_quality_bonus(
    features: Mapping[str, Any],
    by_source: Mapping[str, Mapping[str, Any]],
    source: str,
    item: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> float:
    _ = by_source
    _ = source
    volume_ratio = _safe_float(features.get("volume_ratio")) or _safe_float(item.get("volume_ratio"))
    confirmed_by = (
        _safe_str(features.get("confirmed_by"))
        or _safe_str(item.get("confirmed_by"))
        or _safe_str(_to_dict(item.get("best_buy_point")).get("confirmed_by"))
    )
    ma_bullish = _to_bool(features.get("ma_bullish"))
    confirmations = _to_list_of_str(features.get("confirmations"))
    startup_signals = _to_list_of_str(features.get("startup_signals"))
    startup_signal_score = _score_startup_signal_quality(startup_signals)
    distance = _safe_float(features.get("distance"))
    if distance is None:
        distance = _safe_float(metrics.get("distance"))

    score = 0.0
    if volume_ratio is not None:
        if volume_ratio >= 1.0:
            score += _clamp((volume_ratio - 1.0) * 0.9, 0.0, 1.5)

    if confirmed_by:
        if _is_two_yang_confirmation_string(confirmed_by):
            score += 1.2
        elif "等待确认" not in confirmed_by and ("30" in confirmed_by or "确认" in confirmed_by):
            score += 1.0
    if ma_bullish:
        score += 0.25
    if confirmations and _is_two_yang_confirmation_string(",".join(confirmations)):
        score += 0.2
    score += startup_signal_score

    if distance is not None:
        abs_distance = abs(distance)
        if abs_distance <= 2.0:
            score += 1.0
        elif abs_distance <= 5.0:
            score += 0.5

    return _clamp(score, 0.0, 2.8)


def _score_startup_signal_quality(startup_signals: list[str]) -> float:
    if not startup_signals:
        return 0.0

    score = 0.0
    if any("实体阳线" in s for s in startup_signals):
        score += 0.3
    if any("close_above_ma5" in s or "ma5" in s for s in startup_signals):
        score += 0.2
    if any("close_above_ma10" in s or "ma10" in s for s in startup_signals):
        score += 0.2
    if any("break_20d_high" in s or "20d" in s or "20日" in s for s in startup_signals):
        score += 0.1
    return _clamp(score, 0.0, 0.8)


def _calc_momentum_persistence_from_closes(closes: list[float]) -> float:
    if len(closes) < 4:
        return 0.0

    numeric = [_safe_float(x) for x in closes]
    numeric = [x for x in numeric if x not in (None, 0)]
    if len(numeric) < 4:
        return 0.0

    windows = (3, 5, 10)
    weighted: list[float] = []
    for w in windows:
        if len(numeric) < w + 1:
            continue
        end = numeric[-1]
        start = numeric[-(w + 1)]
        if start in (None, 0):
            continue
        pct = (end - start) / start * 100.0
        changes = 0
        total = 0
        for i in range(-w + 1, 0):
            if numeric[i - 1] is None or numeric[i] is None:
                continue
            total += 1
            if numeric[i] >= numeric[i - 1]:
                changes += 1
        if total == 0:
            continue
        ratio = changes / float(total)
        score = _clamp((pct / 20.0) * 0.65 + (ratio * 2.0 - 1.0) * 0.35, -1.0, 1.0)
        weighted.append(score)

    if not weighted:
        return 0.0
    weights = (0.4, 0.35, 0.25)
    if len(weighted) == 1:
        return weighted[0]
    if len(weighted) == 2:
        return weighted[0] * weights[0] + weighted[1] * (1.0 - weights[0])
    if len(weighted) == 3:
        return weighted[0] * weights[0] + weighted[1] * weights[1] + weighted[2] * weights[2]
    return sum(weighted) / len(weighted)


def _norm_percent_score(value: float) -> float:
    if 0.0 <= value <= 1.2:
        return _clamp(value, 0.0, 1.0)
    if 0.0 <= value <= 100.0:
        return _clamp(value / 100.0, 0.0, 1.0)
    return _clamp(value, 0.0, 1.0)


def _to_list(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[float] = []
    for item in value:
        num = _safe_float(item)
        if num is not None:
            result.append(num)
    return result


def _normalize_confirmation_text(text: Any) -> str:
    return _safe_str(text).replace(" ", "").replace("分钟", "min")


def _is_two_yang_confirmation_string(text: Any) -> bool:
    norm = _normalize_confirmation_text(text)
    return "两阳夹一阴确认" in norm or "两阳夹两阴确认" in norm


def _to_list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (tuple, set)):
        value = list(value)
    if isinstance(value, str):
        return [_safe_str(value)]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if item is None:
            continue
        result.append(_safe_str(item))
    return result


def _merge_unique_str_lists(*lists: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for items in lists:
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
    return result


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y", "是"}
    if value is None:
        return default
    return bool(value)


def _collect_risk_flags(
    by_source: Mapping[str, Mapping[str, Any]],
    sources: Iterable[str],
) -> list[str]:
    seen: set[str] = set()
    flags: list[str] = []
    for source in sources:
        row = by_source.get(source, {})
        for flag in _extract_risk_flags(row, source):
            if flag and flag not in seen:
                seen.add(flag)
                flags.append(flag)
    return flags


def _extract_risk_flags(item: Mapping[str, Any], source: str) -> list[str]:
    flags: list[str] = []
    distance = _resolve_distance_pct(item, source)
    change_pct = _resolve_change_pct(item) or 0.0

    if distance is not None and abs(distance) > 6.0:
        flags.append("距参考价偏高")
    if change_pct >= 7.5:
        flags.append("涨幅过热")

    if source == "main":
        bp = _to_dict(item.get("best_buy_point"))
        age = _safe_float(bp.get("signal_age_days"))
        if age is not None and age >= 8:
            flags.append("信号接近过期")
        if not bp and not _to_dict(item.get("resonance")).get("level"):
            flags.append("30min确认弱")

    if source == "acceleration" and item.get("next_day_reason") in {"高位", "过热"}:
        flags.append("涨幅过热")

    if source == "confirming":
        age = _safe_int(item.get("startup_age_days"), 0)
        if age is not None and age >= 8:
            flags.append("信号接近过期")
        if item.get("confirmed_by") == "等待确认":
            flags.append("确认信号未完成")

    return flags


def _score_risk_penalty(risk_flags: Iterable[str]) -> float:
    unique = set(risk_flags)
    penalty = 0.0
    if "距参考价偏高" in unique:
        penalty += 12.0
    if "涨幅过热" in unique:
        penalty += 10.0
    if "信号接近过期" in unique:
        penalty += 8.0
    if "30min确认弱" in unique:
        penalty += 6.0
    if "确认信号未完成" in unique:
        penalty += 8.0
    return min(MAX_RISK_PENALTY, penalty)


def _score_data_penalty(
    data_quality: Any,
    by_source: Mapping[str, Mapping[str, Any]],
    sources: Iterable[str],
) -> float:
    penalty = 0.0
    dq = _to_dict(data_quality)
    if str(dq.get("market_status") or "") == "unverified":
        penalty += DATA_PENALTY_UNVERIFIED
    if bool(dq.get("fallback_used")):
        penalty += DATA_PENALTY_FALLBACK

    observed_status = False
    for source in sources:
        row = by_source.get(source, {})
        data_status = _to_dict(row.get("data_status"))
        if data_status:
            observed_status = True
        daily_status = str(data_status.get("daily") or "")
        if daily_status == "stale_cache":
            penalty += DATA_PENALTY_STALE
        elif daily_status == "missing":
            penalty += DATA_PENALTY_MISSING

    if not observed_status and not bool(dq.get("fallback_used")) and dq.get("market_status") != "verified":
        penalty += DATA_PENALTY_UNVERIFIED

    return min(MAX_DATA_PENALTY, penalty)


def _resolve_change_pct(item: Mapping[str, Any]) -> float | None:
    direct = _safe_float(item.get("change_pct"))
    if direct is not None:
        return direct
    bp = _to_dict(item.get("best_buy_point"))
    bp_change = _safe_float(bp.get("change_pct"))
    if bp_change is not None:
        return bp_change
    closes = item.get("closes")
    if not isinstance(closes, (list, tuple)) or len(closes) < 2:
        return None
    prev_close = _safe_float(closes[-2])
    latest_close = _safe_float(closes[-1])
    if prev_close in (None, 0) or latest_close is None:
        return None
    return round((latest_close - prev_close) / prev_close * 100, 2)


def _resolve_distance_pct(item: Mapping[str, Any], source: str) -> float | None:
    direct = _safe_float(item.get("distance_from_reference_pct"))
    if direct is not None:
        return direct
    life_distance = _safe_float(item.get("distance_life_pct"))
    if life_distance is not None:
        return life_distance
    bp = _to_dict(item.get("best_buy_point"))
    bp_distance = _safe_float(bp.get("distance_from_reference_pct"))
    if bp_distance is not None:
        return bp_distance
    if source == "luojie":
        close = _safe_float(item.get("close"))
        life_line = _safe_float(item.get("life_line"))
        if close is not None and life_line not in (None, 0):
            return round((close - life_line) / life_line * 100, 2)
    return None
