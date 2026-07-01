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

ViewOrder = List[str]


VIEW_ORDER: ViewOrder = [
    "highlights",
    "main",
    "acceleration",
    "luojie",
    "confirming",
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
    "baseline": {
        "label": "基准",
        "description": "纯净缠论结构参考池，不参与Top10。",
    },
}


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
        if item.get("avoid_chase"):
            reasons.append("仅观察")
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
    if not primary_reason:
        primary_reason = _safe_str(primary_raw_metrics.get("primary_reason"))

    opportunity_score, rank_trace = _compute_watch_score(
        preferred_raw,
        ordered_sources,
        by_source,
        data_quality=data_quality,
        risk_flags=all_risk_flags,
    )

    action, action_reason = _action_and_reason(ordered_sources, all_risk_flags, "main" in ordered_sources)

    item = {
        "code": code,
        "name": name,
        "sector": sector,
        "sources": ordered_sources,
        "info_tags": _build_info_tags(preferred_raw, preferred, all_risk_flags),
        "data_badges": _build_data_badges(preferred_raw, data_quality),
        "source_labels": [_safe_str(SOURCE_LABELS[s]) for s in ordered_sources if s in SOURCE_LABELS],
        "resonance_label": _resonance_label(ordered_sources),
        "view_rank": 0,
        "watch_score": opportunity_score,
        "opportunity_score": opportunity_score,
        "action": action,
        "action_reason": action_reason,
        "change_pct": metrics.get("change_pct"),
        "reference_price": metrics.get("reference_price"),
        "current_price": metrics.get("current_price"),
        "distance_from_reference_pct": metrics.get("distance"),
        "primary_reason": primary_reason,
        "risk_flags": all_risk_flags,
        "rank_trace": rank_trace,
        "ref": {"pool": SOURCE_POOLS.get(preferred, ""), "code": code},
    }
    return item


def _compute_watch_score(
    primary_raw: Mapping[str, Any],
    sources: Iterable[str],
    by_source: dict[str, Mapping[str, Any]],
    data_quality: Mapping[str, Any] | None = None,
    risk_flags: Iterable[str] | None = None,
) -> tuple[int, Dict[str, Any]]:
    ordered_sources = _sorted_sources(sources)
    base_source = ordered_sources[0]
    primary_metrics = _primary_metric_bundle(primary_raw, base_source)
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
        "acceleration": {},
        "luojie": {},
        "confirming": {},
        "baseline": {},
    }

    views["main"] = _normalize_pool_items(
        _get_list(report_data.get("picks_fusion")), "main"
    )

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
        "main": views["main"],
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
    rows.sort(key=lambda row: (-row["opportunity_score"], row["code"]))
    top_rows = rows[:10]
    for rank, row in enumerate(top_rows, start=1):
        row["view_rank"] = rank
    return top_rows


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
    }

    highlights = _build_highlights(views, data_quality=data_quality)
    view_items["highlights"] = highlights

    # Re-rank highlights and each view after dedupe/sorting.
    for name in VIEW_ORDER:
        rows = view_items[name]
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
    }

    return {
        "default_view": "highlights",
        "view_order": list(VIEW_ORDER),
        "view_meta": VIEW_META,
        "views": view_items,
        "counts": counts,
        "diagnostics": diagnostics,
    }
