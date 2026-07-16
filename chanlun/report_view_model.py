"""Utilities for generating the v2 report workspace model.

The report generator keeps raw pool payloads untouched for chart/detail use and
builds a compact, view-oriented workspace for the UI layer. The contract is:
  - merge and dedupe candidate pools used for the highlights view
  - keep each pool view independent for direct filtering
  - attach lightweight action/risk/score metadata for UI rendering
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from chanlun.scoring_engine import compute_opportunity_score
from config import (
    OBSERVATION_MAX_PER_REASON,
    OBSERVATION_MAX_PER_SECTOR,
    OBSERVATION_TOP_N,
)

ViewOrder = List[str]


VIEW_ORDER: ViewOrder = [
    "highlights",
    "main",
    "observation_top5",
    "acceleration",
    "luojie",
    "confirming",
    "growth_quality",
    "baseline",
]

SOURCE_LABELS = {
    "main": "主推",
    "acceleration": "加速",
    "luojie": "罗姐池",
    "confirming": "等确认",
    "baseline": "基准",
}

SOURCE_POOLS = {
    "main": "picks_fusion",
    "acceleration": "next_day_boom",
    "luojie": "luojie_pool",
    "confirming": "startup_watchlist",
    "baseline": "picks_pure",
}

SOURCE_RANK = {
    "main": 0,
    "acceleration": 1,
    "luojie": 2,
    "confirming": 3,
    "baseline": 4,
}

EXCLUDED_FIELDS = {
    "dates",
    "opens",
    "highs",
    "lows",
    "closes",
    "volumes",
    "macd_hist",
    "chart_annotations",
    "buy_points",
    "reference_buy_points",
    "blocked_buy_points",
}

VIEW_META = {
    "highlights": {
        "label": "看点 Top10",
        "short_label": "看点",
        "description": "跨池混合优先观察榜，不等于全部可立即买入。",
    },
    "main": {
        "label": "主推",
        "description": "融合推荐池，可执行优先。",
    },
    "observation_top5": {
        "label": "观察 Top5",
        "short_label": "观察",
        "description": "近失样本观察榜，不计入主推荐，不代表可立即买入。",
    },
    "acceleration": {
        "label": "加速",
        "description": "强市场下的情绪加速榜。",
    },
    "luojie": {
        "label": "罗姐池",
        "description": "硬方向 + 15min生命线观察，不等同于主推。",
    },
    "confirming": {
        "label": "等确认",
        "description": "日线已有启动线索，但等待确认。",
    },
    "growth_quality": {
        "label": "成长质量 Top10",
        "short_label": "成长质量",
        "description": "按成长质量层级筛选的跨池高质量观察榜。",
    },
    "baseline": {
        "label": "基准",
        "description": "纯净缠论结构参考池，不参与Top10。",
    },
}


def _to_tier_score(tier: Any) -> int:
    normalized = _safe_str(tier)
    if normalized == "elite":
        return 0
    if normalized == "strong":
        return 1
    if normalized == "partial":
        return 2
    return 3


def _decision_code_from_raw(item: Mapping[str, Any]) -> str:
    return _safe_str(_to_dict(item).get("decision_engine_v1", {}).get("decision_code")).lower()


def _decision_code_from_view_item(item: Mapping[str, Any]) -> str:
    return _safe_str(_to_dict(item.get("decision_engine_v1")).get("decision_code")).lower()


def _decision_priority(item: Mapping[str, Any]) -> int:
    decision_code = _decision_code_from_view_item(item)
    if decision_code == "recommend":
        return 0
    if decision_code == "observe":
        return 1
    return 2


def _safe_float(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        i = int(value)
    except (TypeError, ValueError):
        return default
    return i


def _clamp(value: float | int, low: float, high: float) -> float:
    return max(low, min(float(high), float(value)))


def _normalize_market_cap_yi(value: Any) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    if abs(number) > 10000:
        return round(number / 100_000_000.0, 4)
    return number


def _resolve_ret20(row: Mapping[str, Any]) -> float | None:
    explicit = _safe_float(row.get("ret20"))
    if explicit is not None:
        return explicit
    closes = _to_float_list(row.get("closes"))
    if len(closes) < 21:
        return None
    base = closes[-21]
    if base == 0:
        return None
    return round((closes[-1] - base) / base * 100.0, 4)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _to_float_list(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        source = value
    elif hasattr(value, "tolist"):
        try:
            source = list(value.tolist())  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            return []
    else:
        return []

    result: list[float] = []
    for item in source:
        num = _safe_float(item)
        if num is not None:
            result.append(num)
    return result


def _resolve_change_pct(item: Mapping[str, Any], best_buy_point: Mapping[str, Any] | None = None) -> float | None:
    row = _to_dict(item)
    direct = _safe_float(row.get("change_pct"))
    if direct is not None:
        return direct

    bp = _to_dict(best_buy_point or row.get("best_buy_point"))
    bp_change = _safe_float(bp.get("change_pct"))
    if bp_change is not None:
        return bp_change

    closes = _to_float_list(row.get("closes", []))
    if len(closes) < 2:
        return None
    prev_close = closes[-2]
    latest_close = closes[-1]
    if prev_close is None or latest_close is None or prev_close == 0:
        return None
    return round((latest_close - prev_close) / prev_close * 100, 2)


def _resolve_current_price(item: Mapping[str, Any]) -> float | None:
    row = _to_dict(item)
    current_price = _safe_float(row.get("current_price"))
    if current_price is not None:
        return current_price

    bp = _to_dict(row.get("best_buy_point"))
    bp_price = _safe_float(bp.get("current_price"))
    if bp_price is not None:
        return bp_price

    close_price = _safe_float(row.get("close"))
    if close_price is not None:
        return close_price

    closes = _to_float_list(row.get("closes", []))
    if closes:
        return closes[-1]
    return None


def _resolve_reference_price(item: Mapping[str, Any], source: str | None = None) -> float | None:
    row = _to_dict(item)
    reference_price = _safe_float(row.get("reference_price"))
    if reference_price is not None:
        return reference_price

    bp = _to_dict(row.get("best_buy_point"))
    bp_reference = _safe_float(bp.get("reference_price"))
    if bp_reference is not None:
        return bp_reference

    source_price = _safe_float(bp.get("source_price"))
    if source_price is not None:
        return source_price

    bp_price = _safe_float(bp.get("price"))
    if bp_price is not None:
        return bp_price

    if source == "luojie":
        life_line = _safe_float(row.get("life_line"))
        if life_line is not None:
            return life_line
        reduce_line = _safe_float(row.get("reduce_line"))
        if reduce_line is not None:
            return reduce_line
    return None


def _resolve_distance_pct(item: Mapping[str, Any], source: str | None = None) -> float | None:
    row = _to_dict(item)
    distance = _safe_float(row.get("distance_from_reference_pct"))
    if distance is None:
        distance = _safe_float(row.get("distance_life_pct"))
    if distance is None and source == "main":
        bp = _to_dict(row.get("best_buy_point"))
        distance = _safe_float(bp.get("distance_from_reference_pct"))
    if distance is not None:
        return distance

    current_price = _resolve_current_price(row)
    reference_price = _resolve_reference_price(row, source=source)
    if current_price is None or reference_price in (None, 0):
        return None
    return round((current_price - reference_price) / reference_price * 100, 2)


def _sorted_sources(sources: Iterable[str]) -> list[str]:
    return sorted(set(sources), key=lambda s: SOURCE_RANK.get(s, 99))


def _get_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _candidate_source_code(item: Mapping[str, Any], fallback: str = "") -> str:
    code = _to_dict(item).get("code")
    if code is None:
        return fallback
    return str(code)


def _candidate_source_name(item: Mapping[str, Any], fallback: str = "") -> str:
    return str(_to_dict(item).get("name") or fallback or "")


def _extract_main_metrics(item: Mapping[str, Any]) -> dict[str, float | None]:
    buy_point = _to_dict(item.get("best_buy_point"))
    return {
        "change_pct": _resolve_change_pct(item, buy_point),
        "current_price": _resolve_current_price(item),
        "reference_price": _resolve_reference_price(item),
        "distance": _resolve_distance_pct(item, source="main"),
        "primary_reason": _safe_str(_to_dict(item).get("resonance", {}).get("reason"))
        or _safe_str(buy_point.get("reason"))
        or _safe_str(item.get("fusion_admission", {}).get("reason"))
        or _safe_str(item.get("reason")),
    }


def _extract_accel_metrics(item: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "change_pct": _safe_float(item.get("change_pct")),
        "current_price": _safe_float(item.get("current_price")),
        "reference_price": _safe_float(item.get("reference_price")),
        "distance": _safe_float(item.get("distance_from_reference_pct")),
        "primary_reason": _safe_str(item.get("boom_reason")) or _safe_str(item.get("reason")),
    }


def _extract_luojie_metrics(item: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "change_pct": _resolve_change_pct(item),
        "current_price": _resolve_current_price(item),
        "reference_price": _resolve_reference_price(item, source="luojie"),
        "distance": _resolve_distance_pct(item, source="luojie"),
        "primary_reason": _safe_str(item.get("reason")),
    }


def _extract_confirming_metrics(item: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "change_pct": _resolve_change_pct(item),
        "current_price": _resolve_current_price(item),
        "reference_price": _resolve_reference_price(item),
        "distance": _resolve_distance_pct(item),
        "primary_reason": _safe_str(item.get("watch_reason")) or _safe_str(item.get("startup_reason")) or _safe_str(item.get("reason")),
    }


def _build_pool_quality_features(item: Mapping[str, Any], source: str | None = None) -> dict[str, Any]:
    row = _to_dict(item)

    code = _safe_str(row.get("code"))
    volumes = _to_float_list(row.get("volumes"))
    recent = volumes[-20:] if volumes else []
    volume20 = round(sum(recent) / len(recent), 4) if recent else 0.0

    volume_ratio20 = _safe_float(row.get("volume_ratio"), default=0.0)
    if volume_ratio20 is None:
        volume_ratio20 = 0.0
    if volume_ratio20 <= 0 and len(recent) >= 2:
        prev20 = recent[:-1]
        prev_avg = sum(prev20) / len(prev20) if prev20 else 0.0
        if prev_avg > 0:
            volume_ratio20 = round(recent[-1] / prev_avg, 4)

    money20 = _safe_float(row.get("money20"))
    liquidity_source = _safe_str(row.get("liquidity_source"))
    liquidity_score = 0.0
    liquidity_label = "低流动性"
    if money20 is not None and money20 > 0:
        if money20 < 30_000_000:
            liquidity_score = 0.0
            liquidity_label = "低流动性"
        elif money20 < 50_000_000:
            liquidity_score = round(_clamp((money20 - 30_000_000) / 20_000_000 * 20.0, 0.0, 20.0), 4)
            liquidity_label = "勉强可交易"
        elif money20 < 100_000_000:
            liquidity_score = round(45.0 + _clamp((money20 - 50_000_000) / 50_000_000 * 24.0, 0.0, 24.0), 4)
            liquidity_label = "流动性合格"
        elif money20 < 200_000_000:
            liquidity_score = round(70.0 + _clamp((money20 - 100_000_000) / 100_000_000 * 20.0, 0.0, 20.0), 4)
            liquidity_label = "流动性良好"
        else:
            liquidity_score = 100.0
            liquidity_label = "高流动性"
        if not liquidity_source:
            liquidity_source = "amounts"
    elif volume_ratio20 > 0 and volume20 > 0:
        # Without real turnover, volume only proves activity and must not become high liquidity.
        liquidity_score = round(_clamp((volume_ratio20 - 0.2) / 2.0 * 25.0, 0.0, 25.0), 4)
        liquidity_label = "量能活跃"
        liquidity_source = liquidity_source or "volume_proxy"
    elif volume20 > 0:
        liquidity_score = round(_clamp(volume20 / 2_000_000.0 * 20.0, 0.0, 20.0), 4)
        liquidity_label = "量能活跃"
        liquidity_source = liquidity_source or "volume_proxy"

    code_style_score = 0.0
    growth_board_label = ""
    if code.startswith(("300", "301")):
        code_style_score = 100.0
        growth_board_label = "创业板弹性"
    elif code.startswith(("688", "689")):
        code_style_score = 90.0
        growth_board_label = "科创弹性"
    elif code.startswith("002"):
        code_style_score = 75.0
        growth_board_label = "中小成长"

    market_cap = _normalize_market_cap_yi(row.get("market_cap"))
    circulating_market_cap = _normalize_market_cap_yi(row.get("circulating_market_cap"))
    if circulating_market_cap is None:
        circulating_market_cap = _normalize_market_cap_yi(row.get("float_market_cap"))

    market_cap_for_score = circulating_market_cap if circulating_market_cap is not None else market_cap
    market_cap_source = "circulating_market_cap" if circulating_market_cap is not None else ("market_cap" if market_cap is not None else "")
    market_cap_score = 0.0
    market_cap_label = ""
    if market_cap_for_score is not None:
        if market_cap_source == "circulating_market_cap":
            if 20 <= market_cap_for_score <= 200:
                market_cap_score = 100.0
                market_cap_label = "强弹性流通市值"
            elif 200 < market_cap_for_score <= 500:
                market_cap_score = 70.0
                market_cap_label = "中等流通弹性"
            elif 500 < market_cap_for_score <= 800:
                market_cap_score = 35.0
                market_cap_label = "轻微流通弹性"
            else:
                market_cap_label = "流通市值弹性不足"
        else:
            if 30 <= market_cap_for_score <= 300:
                market_cap_score = 100.0
                market_cap_label = "强成长市值"
            elif 300 < market_cap_for_score <= 800:
                market_cap_score = 70.0
                market_cap_label = "中等成长市值"
            elif 800 < market_cap_for_score <= 1200:
                market_cap_score = 35.0
                market_cap_label = "轻微成长市值"
            else:
                market_cap_label = "市值弹性不足"

    ret20 = _resolve_ret20(row)
    ret20_score = 0.0
    if ret20 is None:
        ret20_score = 40.0
    elif 3.0 <= ret20 <= 45.0:
        ret20_score = 100.0
    elif 0.0 < ret20 < 3.0:
        ret20_score = 45.0
    elif 45.0 < ret20 <= 60.0:
        ret20_score = 25.0

    growth_board_score = round(
        code_style_score * 0.35 + market_cap_score * 0.45 + ret20_score * 0.20,
        4,
    )
    if code_style_score <= 0:
        growth_board_score = 0.0
    if market_cap_for_score is None:
        growth_board_score = min(growth_board_score, 45.0)

    sector_rank = _safe_float(row.get("sector_rank"))
    sector_flow = _safe_float(row.get("sector_flow"))
    change_pct = _safe_float(row.get("change_pct"))

    sector_rank_score = 0.0
    if sector_rank is not None:
        if sector_rank <= 1:
            sector_rank_score = 100.0
        elif sector_rank <= 3:
            sector_rank_score = 90.0
        elif sector_rank <= 6:
            sector_rank_score = 70.0
        elif sector_rank <= 10:
            sector_rank_score = 50.0
        elif sector_rank <= 20:
            sector_rank_score = 30.0

    # 资金流是绝对值口径，使用轻度归一化。
    sector_flow_score = 0.0
    if sector_flow is not None and sector_flow > 0:
        sector_flow_score = round(_clamp((sector_flow / 3_000_000_000.0) * 100.0, 0.0, 100.0), 4)

    sector_momentum_score = 0.0
    if change_pct is not None and change_pct > 0:
        sector_momentum_score = round(_clamp(change_pct * 12.0, 0.0, 100.0), 4)

    sector_quality_score = round(
        (sector_rank_score * 0.45 + sector_flow_score * 0.35 + sector_momentum_score * 0.20),
        4,
    )

    pool_quality_score = round((liquidity_score * 0.40 + growth_board_score * 0.35 + sector_quality_score * 0.25), 4)

    def _to_tier(score_value: float) -> str:
        if score_value >= 70.0 and growth_board_score >= 55.0 and sector_quality_score >= 70.0:
            return "elite"
        if score_value >= 55.0 and growth_board_score >= 55.0 and sector_quality_score >= 55.0:
            return "strong"
        pass_count = 0
        if score_value >= 55.0:
            pass_count += 1
        if growth_board_score >= 55.0:
            pass_count += 1
        if sector_quality_score >= 55.0:
            pass_count += 1
        if pass_count >= 2:
            return "partial"
        return "none"

    pool_quality_tier = _to_tier(liquidity_score)
    quality_evidence_eligible = (
        market_cap_for_score is not None
        and (
            (money20 is not None and money20 > 0)
            or volume20 > 0
        )
    )
    pool_quality_components = [
        {
            "name": "liquidity",
            "score": round(_clamp(liquidity_score, 0.0, 100.0), 4),
            "threshold_elite": 70.0,
            "threshold_strong": 55.0,
        },
        {
            "name": "growth",
            "score": round(_clamp(growth_board_score, 0.0, 100.0), 4),
            "threshold_elite": 55.0,
            "threshold_strong": 55.0,
        },
        {
            "name": "market_cap",
            "score": round(_clamp(market_cap_score, 0.0, 100.0), 4),
            "source": market_cap_source,
        },
        {
            "name": "ret20",
            "score": round(_clamp(ret20_score, 0.0, 100.0), 4),
        },
        {
            "name": "sector",
            "score": round(_clamp(sector_quality_score, 0.0, 100.0), 4),
            "threshold_elite": 70.0,
            "threshold_strong": 55.0,
        },
    ]

    pool_quality_tags: list[str] = []
    if liquidity_score >= 90:
        pool_quality_tags.append("高流动性")
    elif liquidity_score >= 70:
        pool_quality_tags.append("流动性良好")
    elif liquidity_score >= 45:
        pool_quality_tags.append("流动性合格")
    if growth_board_label:
        pool_quality_tags.append(growth_board_label)
    if market_cap_label and market_cap_score > 0:
        pool_quality_tags.append(market_cap_label)
    if sector_quality_score >= 70:
        pool_quality_tags.append("板块质量上行")

    # Keep source param for compatibility with potential caller expectations.
    return {
        "volume20": volume20,
        "volume_ratio20": volume_ratio20,
        "liquidity_label": liquidity_label,
        "liquidity_score": liquidity_score,
        "code_style_score": code_style_score,
        "growth_board_score": growth_board_score,
        "growth_board_label": growth_board_label,
        "market_cap_score": market_cap_score,
        "market_cap_label": market_cap_label,
        "market_cap_source": market_cap_source,
        "ret20": ret20,
        "ret20_score": ret20_score,
        "sector_quality_score": sector_quality_score,
        "pool_quality_tier": pool_quality_tier,
        "pool_quality_components": pool_quality_components,
        "pool_quality_score": pool_quality_score,
        "pool_quality_tags": pool_quality_tags,
        "market_cap": market_cap,
        "circulating_market_cap": circulating_market_cap,
        "float_market_cap": circulating_market_cap,
        "liquidity_source": liquidity_source,
        "money20": money20,
        "quality_evidence_eligible": quality_evidence_eligible,
        "quality_evidence_status": (
            "eligible" if quality_evidence_eligible else "insufficient"
        ),
    }


def _build_info_tags(
    raw: Mapping[str, Any],
    source: str,
    risk_flags: list[str],
) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add_tag(tag_type: str, label: str) -> None:
        if not tag_type or not label:
            return
        key = (tag_type, label)
        if key in seen:
            return
        seen.add(key)
        tags.append({"type": tag_type, "label": label})

    _add_tag("sector", _safe_str(raw.get("sector")))

    extra_sectors = [
        _safe_str(tag)
        for tag in (_get_list(raw.get("sector_tags")))
        if _safe_str(tag) and _safe_str(tag) != _safe_str(raw.get("sector"))
    ]
    for sector in extra_sectors[:2]:
        _add_tag("sector", sector)

    source_label = _safe_str(SOURCE_LABELS.get(source, ""))
    _add_tag("source", source_label)

    bp = _to_dict(raw.get("best_buy_point"))
    signal = _safe_str(bp.get("type")) or _safe_str(raw.get("type")) or _safe_str(raw.get("source_type"))
    _add_tag("signal", signal)

    confirm = _safe_str(bp.get("sublevel_confirm_label")) or _safe_str(raw.get("sublevel_confirm_label"))
    if confirm:
        confirm = confirm.strip()
        if confirm and not confirm.startswith("30min"):
            confirm = f"30min {confirm}"
    else:
        confirmed_by = _safe_str(bp.get("confirmed_by"))
        if confirmed_by and len(confirmed_by) <= 12:
            confirm = confirmed_by
    _add_tag("confirm", confirm)

    for risk in risk_flags[:2]:
        _add_tag("risk", risk)

    return tags


def _build_data_badges(raw: Mapping[str, Any], data_quality: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add_badge(badge_type: str, label: str) -> None:
        if not badge_type or not label:
            return
        key = (badge_type, label)
        if key in seen:
            return
        seen.add(key)
        badges.append({"type": badge_type, "label": label})

    data_status = _to_dict(raw.get("data_status"))
    row_daily_status = _safe_str(data_status.get("daily"))
    dq = _to_dict(data_quality)
    market_status = _safe_str(dq.get("market_status"))
    fallback_used = bool(dq.get("fallback_used"))

    if row_daily_status == "verified":
        _add_badge("quality", "数据已校验")
        return badges
    if row_daily_status == "stale_cache":
        _add_badge("quality", "缓存兜底")
        _add_badge("risk", "数据非最新")
        return badges
    if row_daily_status == "missing":
        _add_badge("quality", "日线缺失")
        return badges

    if not data_status and fallback_used:
        _add_badge("quality", "含兜底数据")
    elif market_status == "unverified":
        _add_badge("quality", "数据未校验")
    else:
        _add_badge("quality", "数据状态未标记")

    return badges


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _extract_risk_flags(item: Mapping[str, Any], source: str) -> list[str]:
    reasons: list[str] = []
    change_pct = _safe_float(item.get("change_pct"))
    distance = _safe_float(item.get("distance_from_reference_pct"))
    if distance is None:
        distance = _safe_float(item.get("distance_life_pct"))
        if distance is None and source == "main":
            distance = _safe_float(_to_dict(item.get("best_buy_point")).get("distance_from_reference_pct"))

    change_pct = _resolve_change_pct(item) or 0.0

    if distance is None:
        distance = _resolve_distance_pct(item, source=source)

    if distance is not None and abs(distance) > 6.0:
        reasons.append("距参考价偏高")
    if change_pct >= 7.5:
        reasons.append("涨幅过热")

    if source == "main":
        bp = _to_dict(item.get("best_buy_point"))
        if bp.get("signal_age_days") is not None:
            age = _safe_float(bp.get("signal_age_days"))
            if age is not None and age >= 8:
                reasons.append("信号接近过期")
        if not bp and not _to_dict(item.get("resonance")).get("level"):
            reasons.append("30min确认弱")

    if source == "acceleration":
        if item.get("next_day_reason") in {"高位", "过热"}:
            reasons.append("涨幅过热")

    if source == "luojie":
        if _safe_float(item.get("distance_ma77_pct")) is not None and _safe_float(item.get("distance_ma77_pct"), default=0.0) < -10:
            reasons.append("下跌压力")

    if source == "confirming":
        age = _safe_int(item.get("startup_age_days"), default=0)
        if age is not None and age >= 8:
            reasons.append("信号接近过期")
        if item.get("confirmed_by") == "等待确认":
            reasons.append("确认信号未完成")

    # De-duplicate with stable order.
    seen: set[str] = set()
    unique_flags = []
    for reason in reasons:
        if reason and reason not in seen:
            seen.add(reason)
            unique_flags.append(reason)
    return unique_flags


def _resonance_label(sources: list[str]) -> str:
    source_set = set(sources)
    if len(source_set) >= 3:
        return "强共振"
    if source_set == {"main", "acceleration"}:
        return "共振·进攻"
    if source_set == {"main", "luojie"}:
        return "共振·主线"
    if "confirming" in source_set:
        if source_set in ({"acceleration", "confirming"}, {"luojie", "confirming"}, {"main", "confirming"}, {"main", "acceleration", "confirming"}, {"main", "luojie", "confirming"}, {"acceleration", "luojie", "confirming"}):
            return "共振·启动"
        if source_set == {"luojie", "acceleration", "confirming"}:
            return "共振·启动"
    return ""


def _action_and_reason(
    sources: list[str],
    risk_flags: list[str],
    has_main: bool,
) -> tuple[str, str]:
    has_acceleration = "acceleration" in sources
    has_luojie = "luojie" in sources
    has_confirming = "confirming" in sources
    risk_flags_set = set(risk_flags)
    high_risk = bool(risk_flags_set.intersection({"距参考价偏高", "涨幅过热", "信号接近过期", "30min确认弱", "确认信号未完成"}))

    if has_main:
        if high_risk and len(risk_flags_set) >= 2:
            return "慎追", "主推命中，但存在高风险标签，先观察再执行。"
        if high_risk:
            return "等回踩", "主推命中，当前位置不够理想，建议回踩确认。"
        return "可上车", "主推命中，确认与结构条件已满足，偏执行优先。"

    if has_acceleration and not has_main:
        if high_risk:
            return "慎追", "加速信号强但位置/热度偏高，先盯盘。"
        return "盯盘", "加速信号待观察，当前仅用于二次关注。"

    if has_luojie and not has_main:
        if high_risk:
            return "盯盘", "罗姐池方向成立但结构风险存在，先盯盘。"
        return "盯盘", "罗姐池观察信号，先确认方向后考虑进场。"

    if has_confirming and not (has_main or has_acceleration or has_luojie):
        if high_risk:
            return "仅观察", "等确认池位置信号受限，当前仅观察。"
        return "等回踩", "等确认池，等待确认后再考虑。"

    # Fallback, should rarely occur.
    return "仅观察", "暂不满足交易条件，仅观察。"


_EXECUTABLE_ACTIONS = {"可上车", "等回踩", "慎追"}


def _apply_decision_action_cap(
    action: str,
    action_reason: str,
    decision_payload: Any,
) -> tuple[str, str]:
    """Cap source/risk-derived actions using only the structured decision code."""
    decision = _to_dict(decision_payload)
    decision_code = _safe_str(decision.get("decision_code")).lower()
    if decision_code == "reject":
        return (
            "仅观察",
            f"决策上限（reject）：最多仅观察。原动作依据：{action_reason}",
        )
    if decision_code == "observe" and action in _EXECUTABLE_ACTIONS:
        return (
            "仅观察",
            f"决策上限（observe）：不得执行上车动作。原动作依据：{action_reason}",
        )
    return action, action_reason


def _primary_metric_bundle(
    raw: Mapping[str, Any],
    source: str,
) -> dict[str, float | str | list[str] | None]:
    if source == "main":
        return _extract_main_metrics(raw)
    if source == "acceleration":
        return _extract_accel_metrics(raw)
    if source == "luojie":
        return _extract_luojie_metrics(raw)
    if source == "confirming":
        return _extract_confirming_metrics(raw)
    return {
        "change_pct": _resolve_change_pct(raw),
        "current_price": _resolve_current_price(raw),
        "reference_price": _resolve_reference_price(raw, source=source),
        "distance": _resolve_distance_pct(raw, source=source),
        "primary_reason": _safe_str(raw.get("reason")),
    }


_COMPACT_DATA_STATUS_FIELDS = (
    "daily",
    "latest_date",
    "source",
    "bars",
    "stale",
)


def _compact_data_status(raw: Mapping[str, Any]) -> dict[str, Any]:
    data_status = _to_dict(raw.get("data_status"))
    return {
        field: data_status[field]
        for field in _COMPACT_DATA_STATUS_FIELDS
        if field in data_status
    }


def _build_item(
    sources: Iterable[str],
    by_source: dict[str, Mapping[str, Any]],
    data_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ordered_sources = _sorted_sources(sources)
    code = ""
    name = ""
    sector = ""
    all_risk_flags: list[str] = []
    primary_reason = ""

    for source in ordered_sources:
        raw = by_source.get(source) or {}
        if not code:
            code = _candidate_source_code(raw, code)
            name = _candidate_source_name(raw, name)
            sector = _safe_str(raw.get("sector")) or sector
        for risk in _extract_risk_flags(raw, source):
            if risk not in all_risk_flags:
                all_risk_flags.append(risk)
        reason = _primary_metric_bundle(raw, source).get("primary_reason")
        if reason and not primary_reason:
            primary_reason = str(reason)

    metrics = _primary_metric_bundle(by_source[ordered_sources[0]], ordered_sources[0])
    # Prefer the first/source-priority candidate for chart/detail linkage and price fields.
    preferred = ordered_sources[0]
    preferred_raw = by_source[preferred]

    primary_raw_metrics = _primary_metric_bundle(preferred_raw, preferred)
    pool_quality = _build_pool_quality_features(preferred_raw, preferred)
    if not primary_reason:
        primary_reason = _safe_str(primary_raw_metrics.get("primary_reason"))

    opportunity_score, rank_trace = _compute_watch_score(
        preferred_raw,
        ordered_sources,
        by_source,
        data_quality=data_quality,
        risk_flags=all_risk_flags,
        pool_quality=pool_quality,
    )

    action, action_reason = _action_and_reason(ordered_sources, all_risk_flags, "main" in ordered_sources)
    decision_payload = preferred_raw.get("decision_engine_v1")
    action, action_reason = _apply_decision_action_cap(
        action,
        action_reason,
        decision_payload,
    )

    item = {
        "code": code,
        "name": name,
        "sector": sector,
        "sources": ordered_sources,
        "info_tags": _build_info_tags(preferred_raw, preferred, all_risk_flags),
        "data_badges": _build_data_badges(preferred_raw, data_quality),
        "data_status": _compact_data_status(preferred_raw),
        "source_labels": [_safe_str(SOURCE_LABELS[s]) for s in ordered_sources if s in SOURCE_LABELS],
        "resonance_label": _resonance_label(ordered_sources),
        "view_rank": 0,
        "watch_score": opportunity_score,
        "opportunity_score": opportunity_score,
        "action": action,
        "action_reason": action_reason,
        "pool_quality": pool_quality,
        "change_pct": metrics.get("change_pct"),
        "reference_price": metrics.get("reference_price"),
        "current_price": metrics.get("current_price"),
        "distance_from_reference_pct": metrics.get("distance"),
        "primary_reason": primary_reason,
        "risk_flags": all_risk_flags,
        "rank_trace": rank_trace,
        "decision_engine_v1": decision_payload,
        "source_channel": _safe_str(preferred_raw.get("source_channel")),
        "tier": _safe_str(preferred_raw.get("tier"))
        or _safe_str(_to_dict(preferred_raw.get("best_buy_point")).get("tier")),
        "category": _safe_str(preferred_raw.get("category"))
        or _safe_str(_to_dict(preferred_raw.get("best_buy_point")).get("category")),
        "quality_tier": _safe_str(preferred_raw.get("quality_tier"))
        or _safe_str(_to_dict(preferred_raw.get("best_buy_point")).get("quality_tier")),
        "view": _safe_str(preferred_raw.get("view"))
        or ("main" if "main" in ordered_sources else "observation"),
        "ref": {"pool": SOURCE_POOLS.get(preferred, ""), "code": code},
    }
    return item


def _compute_watch_score(
    primary_raw: Mapping[str, Any],
    sources: Iterable[str],
    by_source: dict[str, Mapping[str, Any]],
    data_quality: Mapping[str, Any] | None = None,
    risk_flags: Iterable[str] | None = None,
    pool_quality: Mapping[str, Any] | None = None,
) -> tuple[int, Dict[str, Any]]:
    ordered_sources = _sorted_sources(sources)
    base_source = ordered_sources[0]
    primary_metrics = _primary_metric_bundle(primary_raw, base_source)
    pool_quality_dict = _to_dict(pool_quality)

    watch_score, trace = compute_opportunity_score(
        primary_raw,
        base_source,
        {
            "sources": ordered_sources,
            "by_source": by_source,
            "data_quality": data_quality,
            "metrics": primary_metrics,
            "risk_flags": list(risk_flags or []),
            "source_count": len(ordered_sources),
            "alpha_features": {"pool_quality": pool_quality_dict},
        },
    )
    trace["selected_reason"] = _build_selected_reason(base_source, ordered_sources)
    return watch_score, trace


def _build_selected_reason(base_source: str, sources: Iterable[str]) -> str:
    ordered_sources = _sorted_sources(sources)
    if len(ordered_sources) == 1:
        if base_source == "main":
            return "主推池单源入榜"
        if base_source == "acceleration":
            return "加速池单源入榜"
        if base_source == "luojie":
            return "罗姐池单源入榜"
        if base_source == "confirming":
            return "等确认池单源入榜"
        return "基准池单源入榜"

    if _resonance_label(ordered_sources):
        return f"{_resonance_label(ordered_sources)}，多池共振上提"
    return "多池命中，质量上提"


def _normalize_pool_items(raw_items: Iterable[Mapping[str, Any]], source: str) -> dict[str, Mapping[str, Any]]:
    by_code: dict[str, Mapping[str, Any]] = {}
    for raw in raw_items:
        candidate = _to_dict(raw)
        code = _candidate_source_code(candidate, fallback="")
        if not code:
            continue
        # Keep first appearance; conservative dedupe in order.
        if code not in by_code:
            by_code[code] = candidate
    return by_code


def _collect_views(
    report_data: Mapping[str, Any],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    views: dict[str, dict[str, Mapping[str, Any]]] = {
        "main": {},
        "main_all": {},
        "acceleration": {},
        "luojie": {},
        "confirming": {},
        "baseline": {},
    }

    views["main_all"] = _normalize_pool_items(
        _get_list(report_data.get("picks_fusion")), "main"
    )
    views["main"] = {
        code: raw
        for code, raw in views["main_all"].items()
        if _decision_code_from_raw(raw) == "recommend"
    }

    next_day_boom = _to_dict(report_data.get("next_day_boom"))
    boom_mode = _safe_str(next_day_boom.get("mode"))
    if boom_mode == "enabled":
        views["acceleration"] = _normalize_pool_items(
            _get_list(next_day_boom.get("candidates")),
            "acceleration",
        )
    else:
        views["acceleration"] = {}

    luojie = _to_dict(report_data.get("luojie_pool"))
    views["luojie"] = _normalize_pool_items(
        _get_list(luojie.get("candidates")), "luojie"
    )

    views["confirming"] = _normalize_pool_items(
        _get_list(report_data.get("startup_watchlist")), "confirming"
    )
    views["baseline"] = _normalize_pool_items(
        _get_list(report_data.get("picks_pure")), "baseline"
    )
    return views


def _build_view_items(
    view_source: str,
    source_to_item: dict[str, Mapping[str, Any]],
    source_for_ranking: str | None = None,
    data_quality: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, raw in source_to_item.items():
        row = _build_item(
            [source_for_ranking or view_source],
            {source_for_ranking or view_source: raw},
            data_quality=data_quality,
        )
        row["view_rank"] = 0
        rows.append(row)
    rows.sort(key=lambda row: (-row["opportunity_score"], row["code"]))
    for rank, row in enumerate(rows, start=1):
        row["view_rank"] = rank
    return rows


def _build_highlights(
    views: dict[str, dict[str, Mapping[str, Any]]],
    data_quality: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Mapping[str, Any]]] = {}
    source_map = {
        "main": views.get("main_all", views["main"]),
        "acceleration": views["acceleration"],
        "luojie": views["luojie"],
        "confirming": views["confirming"],
    }

    for source, source_items in source_map.items():
        for code, raw in source_items.items():
            bucket = merged.setdefault(code, {"by_source": {}, "base_code": code})
            if source not in bucket["by_source"]:
                bucket["by_source"][source] = raw

    rows = [
        _build_item(list(bucket["by_source"].keys()), bucket["by_source"], data_quality=data_quality)
        for bucket in merged.values()
    ]
    rows = [
        row
        for row in rows
        if _decision_code_from_view_item(row) != "reject"
    ]
    rows.sort(
        key=lambda row: (
            _decision_priority(row),
            -row["opportunity_score"],
            row["code"],
        )
    )
    top_rows = rows[:10]
    for rank, row in enumerate(top_rows, start=1):
        row["view_rank"] = rank
    return top_rows


def _build_growth_quality(
    views: dict[str, dict[str, Mapping[str, Any]]],
    data_quality: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Mapping[str, Any]]] = {}
    source_map = {
        "main": views.get("main_all", views["main"]),
        "acceleration": views["acceleration"],
        "luojie": views["luojie"],
        "confirming": views["confirming"],
    }
    for source, source_items in source_map.items():
        for code, raw in source_items.items():
            bucket = merged.setdefault(code, {"by_source": {}})
            if source not in bucket["by_source"]:
                bucket["by_source"][source] = raw

    rows = [
        _build_item(list(bucket["by_source"].keys()), bucket["by_source"], data_quality=data_quality)
        for bucket in merged.values()
    ]
    rows = [
        row
        for row in rows
        if _decision_code_from_view_item(row) != "reject"
        and bool(_to_dict(row.get("pool_quality")).get("quality_evidence_eligible"))
    ]

    def _growth_quality_sort_key(item: Mapping[str, Any]) -> tuple[float, float, float, str]:
        item_pool_quality = _to_dict(item.get("pool_quality"))
        return (
            _to_tier_score(_safe_str(item_pool_quality.get("pool_quality_tier"))),
            -_safe_float(item_pool_quality.get("pool_quality_score"), default=0.0),
            -_safe_float(item.get("opportunity_score"), default=0.0),
            _safe_str(item.get("code")),
        )

    rows.sort(key=_growth_quality_sort_key)
    top_rows = rows[:10]
    for rank, row in enumerate(top_rows, start=1):
        row["view_rank"] = rank
    return top_rows


def _build_observation_top5(
    report_data: Mapping[str, Any],
    data_quality: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_items = _get_list(report_data.get("observation_watchlist"))
    if not raw_items:
        raw_items = _get_list(report_data.get("startup_watchlist"))
    normalized = _normalize_pool_items(raw_items, "confirming")
    ranked = []
    for code, raw in normalized.items():
        row = _build_item(
            ["confirming"],
            {"confirming": raw},
            data_quality=data_quality,
        )
        row.update({
            "view": "observation",
            "tier": _safe_str(raw.get("tier")) or "watch",
            "source_channel": _safe_str(raw.get("source_channel")),
            "reason_code": _safe_str(raw.get("reason_code")) or "waiting_30m_confirm",
            "failure_gate": _safe_str(raw.get("failure_gate")) or "30min_confirm",
            "actual_value": raw.get("actual_value"),
            "upgrade_conditions": list(raw.get("upgrade_conditions") or raw.get("next_day_conditions") or []),
            "cancel_conditions": list(raw.get("cancel_conditions") or []),
            "ref": {"pool": "observation_watchlist", "code": code},
        })
        ranked.append(row)
    ranked.sort(key=lambda row: (-row["opportunity_score"], row["code"]))

    selected = []
    sector_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for row in ranked:
        if len(selected) >= int(OBSERVATION_TOP_N):
            break
        sector = _safe_str(row.get("sector")) or "未分类"
        reason = _safe_str(row.get("reason_code")) or "unknown"
        if sector_counts.get(sector, 0) >= int(OBSERVATION_MAX_PER_SECTOR):
            continue
        if reason_counts.get(reason, 0) >= int(OBSERVATION_MAX_PER_REASON):
            continue
        selected.append(row)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for rank, row in enumerate(selected, start=1):
        row["view_rank"] = rank
    return selected, {
        "input_count": len(ranked),
        "selected_count": len(selected),
        "max_total": int(OBSERVATION_TOP_N),
        "max_per_sector": int(OBSERVATION_MAX_PER_SECTOR),
        "max_per_reason": int(OBSERVATION_MAX_PER_REASON),
    }


def build_workspace(report_data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a compact v2 workspace from serialized report payload.

    Returns a deterministic dictionary with:
      - default_view / view_order / view_meta
      - per-view rows
      - counts and diagnostics
    """
    data = _to_dict(report_data)
    views = _collect_views(data)
    data_quality = data.get("data_quality")

    view_items = {
        view: _build_view_items(view, source_data, data_quality=data_quality)
        for view, source_data in views.items()
        if view in SOURCE_POOLS
    }

    highlights = _build_highlights(views, data_quality=data_quality)
    view_items["highlights"] = highlights
    growth_quality_input_count = len(
        set().union(
            views.get("main_all", {}).keys(),
            views["acceleration"].keys(),
            views["luojie"].keys(),
            views["confirming"].keys(),
        )
    )
    growth_quality = _build_growth_quality(views, data_quality=data_quality)
    view_items["growth_quality"] = growth_quality
    observation_top5, observation_diagnostics = _build_observation_top5(
        data, data_quality=data_quality
    )
    view_items["observation_top5"] = observation_top5

    # Re-rank opportunity-score views after dedupe/sorting. growth_quality keeps
    # its tier/quality-first order by design.
    for name in VIEW_ORDER:
        rows = view_items[name]
        if name == "highlights":
            rows.sort(
                key=lambda row: (
                    _decision_priority(row),
                    -row["opportunity_score"],
                    row["code"],
                )
            )
        elif name != "growth_quality":
            rows.sort(key=lambda row: (-row["opportunity_score"], row["code"]))
        for rank, row in enumerate(rows, start=1):
            row["view_rank"] = rank

    counts = {
        view: len(items)
        for view, items in view_items.items()
    }

    diagnostics = {
        "source_counts": {
            "main": len(views["main"]),
            "acceleration": len(views["acceleration"]),
            "luojie": len(views["luojie"]),
            "confirming": len(views["confirming"]),
            "baseline": len(views["baseline"]),
        },
        "highlights": {
            "input_counts": {
                "main": len(views["main"]),
                "acceleration": len(views["acceleration"]),
                "luojie": len(views["luojie"]),
                "confirming": len(views["confirming"]),
            },
            "deduped_count": counts["highlights"],
            "selected_count": counts["highlights"],
            "selection_policy": "soft_reserve_quality_first",
            "baseline_included": False,
        },
        "growth_quality_overlap": {
            "highlights_codes": [item["code"] for item in view_items["highlights"]],
            "growth_quality_codes": [item["code"] for item in view_items["growth_quality"]],
            "overlap_codes": sorted(
                set(item["code"] for item in view_items["highlights"])
                & set(item["code"] for item in view_items["growth_quality"])
            ),
        },
        "growth_quality": {
            "input_count": growth_quality_input_count,
            "eligible_count": counts["growth_quality"],
            "excluded_insufficient_evidence": max(
                0, growth_quality_input_count - counts["growth_quality"]
            ),
        },
        "observation_top5": observation_diagnostics,
    }

    return {
        "default_view": "main",
        "view_order": list(VIEW_ORDER),
        "view_meta": VIEW_META,
        "views": view_items,
        "counts": counts,
        "diagnostics": diagnostics,
    }
