"""Independent right-side trend-continuation retrieval and confirmation."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import config
from .data_fetcher import is_st_stock
from .market_sentiment import classify_price_limit
from .price_basis import adjustment_factor
from .sublevel_confirm import build_30min_confirmation_evidence


def _float_array(value: Any) -> np.ndarray:
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)


def _field_value(value: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(value, Mapping):
            candidate = value.get(key)
        else:
            candidate = getattr(value, key, None)
        if candidate is not None:
            return candidate
    return None


def _latest_pivot_upper(result: Any) -> Optional[float]:
    pivots = getattr(result, "pivots", None) or []
    for pivot in reversed(list(pivots)):
        try:
            value = float(_field_value(pivot, "ZG", "zg", "upper", "high"))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _base_payload(
    result: Any,
    sector_stocks: Optional[Mapping[str, Mapping[str, Any]]],
) -> Optional[Dict[str, Any]]:
    closes = _float_array(getattr(result, "closes", None))
    highs = _float_array(getattr(result, "highs", None))
    lows = _float_array(getattr(result, "lows", None))
    opens = _float_array(getattr(result, "opens", None))
    volumes = _float_array(getattr(result, "volumes", None))
    if min(len(closes), len(highs), len(lows), len(opens), len(volumes)) < 60:
        return None
    if is_st_stock(str(getattr(result, "name", "") or "")):
        return None

    code = str(getattr(result, "code", "") or "")
    sector = (sector_stocks or {}).get(code, {})
    average_amount = float(np.mean(volumes[-5:] * closes[-5:] * 100.0))
    if average_amount < float(config.MIN_DAILY_AMOUNT):
        return None

    close = float(closes[-1])
    previous_close = float(closes[-2])
    platform_high = float(np.max(highs[-21:-1]))
    ma5 = float(np.mean(closes[-5:]))
    ma10 = float(np.mean(closes[-10:]))
    change_pct = (
        (close / previous_close - 1.0) * 100.0 if previous_close > 0 else 0.0
    )
    price_limit_state = classify_price_limit({
        "code": code,
        "name": str(getattr(result, "name", "") or code),
        "prev_close": previous_close,
        "close": close,
    })
    if price_limit_state == "limit_down":
        return None
    gap_pct = (
        (float(opens[-1]) / previous_close - 1.0) * 100.0
        if previous_close > 0
        else 0.0
    )
    previous_volume = float(np.mean(volumes[-6:-1]))
    volume_ratio = float(volumes[-1] / previous_volume) if previous_volume > 0 else 0.0
    pivot_upper = _latest_pivot_upper(result)
    platform_breakout = close > platform_high
    pivot_breakout = bool(pivot_upper and close > pivot_upper)
    ma_hold = close >= ma5 >= ma10

    reference_type = "platform_high_20d"
    reference_price = platform_high
    if platform_breakout:
        reference_type = "platform_high_20d"
        reference_price = platform_high
    elif pivot_breakout:
        reference_type = "pivot_upper"
        reference_price = float(pivot_upper)
    if reference_price <= 0:
        return None

    distance = (close / reference_price - 1.0) * 100.0
    strong_structure = bool(ma_hold and (platform_breakout or pivot_breakout))
    dates = list(getattr(result, "dates", None) or [])
    startup_index = len(closes) - 1
    return {
        "code": code,
        "name": str(getattr(result, "name", "") or code),
        "sector": sector.get("sector", ""),
        "sector_tags": list(sector.get("sector_tags", []) or []),
        "source_channel": "right_side_startup",
        "tier": "seed",
        "category": "B",
        "quality_tier": "",
        "view": "main",
        "type": "右侧启动种子",
        "source_type": "日线右侧启动",
        "reference_type": reference_type,
        "reference_price": round(reference_price, 6),
        "distance_from_reference_pct": round(distance, 4),
        "change_pct": round(change_pct, 4),
        "price_limit_state": price_limit_state,
        "gap_pct": round(gap_pct, 4),
        "volume_ratio": round(volume_ratio, 4),
        "strong_structure": strong_structure,
        "trend_signals": [
            label
            for enabled, label in (
                (platform_breakout, "20日平台突破"),
                (pivot_breakout, "中枢上沿突破"),
                (ma_hold, "MA5/MA10保持"),
            )
            if enabled
        ],
        "close": close,
        "closes": closes,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "dates": dates,
        "price_basis": (
            dict(sector.get("price_basis") or {})
            if isinstance(sector.get("price_basis"), Mapping)
            else dict(getattr(result, "price_basis", {}) or {})
        ),
        "startup_index": startup_index,
        "startup_date": str(dates[-1]) if dates else "",
        "startup_age_days": 0,
        "data_status": dict(sector.get("data_status") or {}),
    }


def _watch(
    seed: Mapping[str, Any],
    reason_code: str,
    failure_gate: str,
    watch_reason: str,
    actual_value: Any,
    upgrade_conditions: Sequence[str],
    cancel_conditions: Sequence[str],
    threshold: Any = None,
) -> Dict[str, Any]:
    row = dict(seed)
    row.update({
        "type": "趋势延续观察",
        "tier": "watch",
        "category": "C",
        "view": "observation",
        "avoid_chase": True,
        "reason_code": reason_code,
        "failure_gate": failure_gate,
        "watch_reason": watch_reason,
        "actual_value": actual_value,
        "threshold": threshold,
        "upgrade_conditions": list(upgrade_conditions),
        "next_day_conditions": list(upgrade_conditions),
        "cancel_conditions": list(cancel_conditions),
    })
    return row


def build_trend_continuation_pool(
    chan_results: Sequence[Any],
    sector_stocks: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    diagnostics = {
        "enabled": bool(config.ENABLE_TREND_CONTINUATION),
        "scanned": len(chan_results),
        "trend_seed": 0,
        "watch_near_miss": 0,
        "watch_risk": 0,
        "dropped_base_filter": 0,
        "dropped_structure": 0,
        "dropped_volume": 0,
    }
    if not config.ENABLE_TREND_CONTINUATION:
        return [], [], diagnostics

    seeds = []
    watchlist = []
    for result in chan_results:
        if result is None:
            diagnostics["dropped_base_filter"] += 1
            continue
        seed = _base_payload(result, sector_stocks)
        if seed is None:
            diagnostics["dropped_base_filter"] += 1
            continue

        volume_ratio = float(seed["volume_ratio"])
        strong_structure = bool(seed["strong_structure"])
        if not strong_structure:
            if volume_ratio >= float(config.TREND_CONTINUATION_WATCH_VOLUME_RATIO):
                watchlist.append(_watch(
                    seed,
                    "daily_breakout_near_miss",
                    "daily_breakout",
                    "均线状态保持，但尚未有效突破平台或中枢上沿",
                    {
                        "volume_ratio": volume_ratio,
                        "close": seed["close"],
                        "reference_price": seed["reference_price"],
                    },
                    ["有效突破20日平台或中枢上沿"],
                    ["跌破MA10", "放量长阴破坏平台"],
                    threshold={
                        "close_gt_reference_price": seed["reference_price"],
                    },
                ))
                diagnostics["watch_near_miss"] += 1
            else:
                diagnostics["dropped_structure"] += 1
            continue

        if volume_ratio < float(config.TREND_CONTINUATION_CONDITIONAL_VOLUME_RATIO):
            if volume_ratio >= float(
                config.TREND_CONTINUATION_STRONG_STRUCTURE_WATCH_VOLUME_RATIO
            ):
                watchlist.append(_watch(
                    seed,
                    "volume_near_miss",
                    "volume_ratio",
                    "结构完整但量比略低，等待量价持续",
                    volume_ratio,
                    ["量比回到1.3以上", "30min突破位不破并缩量回踩"],
                    ["跌破趋势参考位", "放量滞涨"],
                    threshold=float(
                        config.TREND_CONTINUATION_CONDITIONAL_VOLUME_RATIO
                    ),
                ))
                diagnostics["watch_near_miss"] += 1
            else:
                diagnostics["dropped_volume"] += 1
            continue

        risk_code = ""
        risk_reason = ""
        if seed.get("price_limit_state") == "limit_up":
            risk_code = "limit_up"
            risk_reason = "涨停当日不追，等待回踩确认"
        elif float(seed["gap_pct"]) >= float(config.TREND_CONTINUATION_MAX_GAP_PCT):
            risk_code = "overextended"
            risk_reason = "显著跳空，等待缺口与突破位确认"
        elif float(seed["distance_from_reference_pct"]) > float(
            config.TREND_CONTINUATION_MAX_EXTENSION_PCT
        ):
            risk_code = "overextended"
            risk_reason = "远离趋势参考位，进入加速末端观察"
        if risk_code:
            watchlist.append(_watch(
                seed,
                risk_code,
                "chase_risk",
                risk_reason,
                {
                    "change_pct": seed["change_pct"],
                    "gap_pct": seed["gap_pct"],
                    "distance_from_reference_pct": seed[
                        "distance_from_reference_pct"
                    ],
                },
                ["回踩趋势参考位不破", "30min EMA保持且缩量回踩"],
                ["跌破趋势参考位", "高位放量长阴"],
                threshold={
                    "max_gap_pct": float(
                        config.TREND_CONTINUATION_MAX_GAP_PCT
                    ),
                    "max_extension_pct": float(
                        config.TREND_CONTINUATION_MAX_EXTENSION_PCT
                    ),
                    "price_limit_state": "not_limit_up",
                },
            ))
            diagnostics["watch_risk"] += 1
            continue

        seed["tier"] = "seed"
        seed["category"] = "B"
        seeds.append(seed)
        diagnostics["trend_seed"] += 1
    return seeds, watchlist, diagnostics


def _input_evidence(result: Any, expected_date: str) -> Dict[str, Any]:
    raw = getattr(result, "strategy_input_evidence", None)
    evidence = dict(raw) if isinstance(raw, Mapping) else {}
    latest_date = str(evidence.get("latest_date") or "").split(" ", 1)[0]
    dates = list(getattr(result, "dates", None) or [])
    bar_date = str(dates[-1]).split(" ", 1)[0] if dates else ""
    status = str(evidence.get("status") or "")
    bar_state = str(evidence.get("bar_state") or "")
    is_final = evidence.get("is_final")
    stale = evidence.get("stale")
    as_of_date = str(evidence.get("as_of") or "").split("T", 1)[0]
    formal_valid = bool(
        status == "verified"
        and is_final is True
        and bar_state in {"closed", "final"}
    )
    intraday_valid = bool(
        status in {"available", "intraday_available"}
        and is_final is False
        and bar_state == "intraday"
        and as_of_date == latest_date
    )
    valid = bool(
        evidence.get("interval") == "30m"
        and stale is False
        and latest_date == str(expected_date or "")
        and bar_date == latest_date
        and (formal_valid or intraday_valid)
    )
    return {
        "valid": valid,
        "status": status or "missing",
        "latest_date": latest_date,
        "bar_date": bar_date,
        "bar_state": bar_state,
        "is_final": is_final,
        "stale": stale,
        "expected_date": str(expected_date or ""),
    }


def _volume_contraction(volumes: np.ndarray) -> bool:
    if len(volumes) < 10:
        return False
    recent = float(np.mean(volumes[-3:]))
    previous = float(np.mean(volumes[-10:-3]))
    return bool(previous > 0 and recent <= previous * 0.9)


def _confirm_30min(
    result: Any,
    reference_price: float,
    expected_date: str,
    daily_current_price: Optional[float] = None,
    factor_vs_raw: Optional[float] = None,
) -> Dict[str, Any]:
    closes = _float_array(getattr(result, "closes", None))
    volumes = _float_array(getattr(result, "volumes", None))
    data = _input_evidence(result, expected_date)
    base = build_30min_confirmation_evidence(result)
    sufficient = bool(base.get("sufficient_bars") and len(closes) >= 10)
    price_factor = None
    try:
        if factor_vs_raw is not None:
            price_factor = adjustment_factor(factor_vs_raw, 1.0)
    except ValueError:
        price_factor = None
    aligned_closes = closes * price_factor if price_factor is not None else np.asarray([])
    reference_hold = bool(
        sufficient
        and len(aligned_closes) >= 5
        and float(reference_price) > 0
        and float(np.min(aligned_closes[-5:])) >= float(reference_price) * 0.995
    )

    structure_labels = []
    buy_point = str(base.get("buy_point") or "")
    if buy_point:
        structure_labels.append("30min {}".format(buy_point))
    pattern = str(base.get("fresh_yang_pattern") or "")
    if pattern == "two_yang_one_yin":
        structure_labels.append("30min两阳夹一阴确认")
    elif pattern == "two_yang_two_yin":
        structure_labels.append("30min两阳夹两阴确认")

    quality_labels = []
    if base.get("ema5_reclaim"):
        quality_labels.append("30min EMA5收复")
    elif (
        base.get("close_above_ema5")
        and int(base.get("ema5_rising_bars") or 0) >= 2
    ):
        quality_labels.append("30min EMA5持续上行")
    if _volume_contraction(volumes):
        quality_labels.append("30min缩量回踩")
    if base.get("stop_fall"):
        quality_labels.append("30min止跌结构")
    if base.get("macd_hist_direction") == "improving":
        quality_labels.append("30min MACD改善")

    structure_pass = bool(structure_labels)
    quality_pass = bool(quality_labels)
    passed = bool(
        data["valid"]
        and sufficient
        and reference_hold
        and structure_pass
        and quality_pass
    )
    confirmations = []
    if reference_hold:
        confirmations.append("30min突破位不破")
    confirmations.extend(structure_labels)
    confirmations.extend(quality_labels)
    return {
        "schema_version": 1,
        "data": data,
        "mandatory": {
            "reference_hold": reference_hold,
            "sufficient_bars": sufficient,
        },
        "structure": {
            "fresh_event": structure_pass,
            "labels": structure_labels,
        },
        "quality": {
            "independent_confirm": quality_pass,
            "labels": quality_labels,
            "ema_bullish_alignment": bool(
                base.get("ema_bullish_alignment")
            ),
        },
        "risk": {
            "macd_weakening": (
                base.get("macd_hist_direction") == "weakening"
            ),
            "macd_hist_direction": base.get("macd_hist_direction"),
        },
        "confirmations": confirmations,
        "passed": passed,
    }


def _confirmation_failure(evidence: Mapping[str, Any]) -> Tuple[str, str]:
    if not (evidence.get("data") or {}).get("valid"):
        return "30min_data_contract", "30分钟数据日期或最终状态不符合合同"
    if not (evidence.get("mandatory") or {}).get("sufficient_bars"):
        return "30min_data_contract", "30分钟有效样本不足"
    if not (evidence.get("mandatory") or {}).get("reference_hold"):
        return "30min_reference_hold", "30分钟已跌破右侧突破参考位"
    if not (evidence.get("structure") or {}).get("fresh_event"):
        return "30min_structure", "30分钟只有状态，没有新鲜价格结构"
    return "30min_quality", "30分钟结构已出现，但缺少独立质量确认"


def upgrade_trend_continuation_with_30min(
    seeds: Sequence[Mapping[str, Any]],
    chan_results_30min: Sequence[Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    result_by_code = {
        str(getattr(result, "code", "") or ""): result
        for result in chan_results_30min
        if result is not None
    }
    candidates = []
    watchlist = []
    diagnostics = {
        "input": len(seeds),
        "trend_candidate": 0,
        "watch_due_to_no_30min": 0,
        "watch_due_to_no_confirm": 0,
        "watch_due_to_data_contract": 0,
        "watch_due_to_reference_break": 0,
        "watch_due_to_no_structure": 0,
        "watch_due_to_no_quality": 0,
    }
    for raw in seeds:
        seed = dict(raw)
        result = result_by_code.get(str(seed.get("code") or ""))
        if result is None:
            watchlist.append(_watch(
                seed,
                "waiting_30m_confirm",
                "30min_data",
                "缺少30分钟数据，等待趋势确认",
                None,
                ["获取30min数据", "突破位不破且EMA保持"],
                ["跌破趋势参考位"],
                threshold={
                    "data_contract": "current_trade_date_verified_30m",
                },
            ))
            diagnostics["watch_due_to_no_30min"] += 1
            continue
        confirmation_evidence = _confirm_30min(
            result,
            float(seed["reference_price"]),
            str(seed.get("startup_date") or "").split(" ", 1)[0],
            daily_current_price=seed.get("close"),
            factor_vs_raw=(
                (seed.get("price_basis") or {}).get("factor_vs_raw")
                if isinstance(seed.get("price_basis"), Mapping)
                else None
            ),
        )
        seed["confirmation_evidence"] = confirmation_evidence
        confirmations = list(
            confirmation_evidence.get("confirmations") or []
        )
        if not confirmation_evidence.get("passed"):
            failure_gate, watch_reason = _confirmation_failure(
                confirmation_evidence
            )
            watchlist.append(_watch(
                seed,
                "waiting_30m_confirm",
                failure_gate,
                watch_reason,
                confirmation_evidence,
                ["突破位不破", "出现新鲜价格结构", "获得独立质量确认"],
                ["跌破趋势参考位", "30min EMA转空"],
                threshold={
                    "data_contract": "valid",
                    "reference_hold_min": round(
                        float(seed["reference_price"]) * 0.995, 6
                    ),
                    "fresh_structure": True,
                    "independent_quality": True,
                },
            ))
            diagnostics["watch_due_to_no_confirm"] += 1
            diagnostic_key = {
                "30min_data_contract": "watch_due_to_data_contract",
                "30min_reference_hold": "watch_due_to_reference_break",
                "30min_structure": "watch_due_to_no_structure",
                "30min_quality": "watch_due_to_no_quality",
            }[failure_gate]
            diagnostics[diagnostic_key] += 1
            continue
        seed.update({
            "type": "右侧启动候选",
            "tier": "candidate",
            "category": "A",
            "quality_tier": "A",
            "view": "main",
            "confirmations": confirmations,
            "confirmed_by": "+".join(confirmations),
            "result_30min": result,
        })
        input_evidence = getattr(
            result, "strategy_input_evidence", None
        )
        if isinstance(input_evidence, Mapping):
            seed["strategy_input_evidence"] = dict(input_evidence)
        candidates.append(seed)
        diagnostics["trend_candidate"] += 1
    return candidates, watchlist, diagnostics


def normalize_trend_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert an upgraded trend candidate to the existing pick contract."""
    row = dict(candidate)
    reference_price = float(row.get("reference_price") or 0.0)
    current_price = float(row.get("close") or 0.0)
    confirmations = list(row.get("confirmations") or [])
    closes = row.get("closes")
    close_count = len(closes) if closes is not None else 0
    buy_point = {
        "type": "右侧启动候选",
        "tier": "candidate",
        "index": close_count - 1,
        "price": reference_price,
        "reference_price": reference_price,
        "current_price": current_price,
        "distance_from_reference_pct": row.get(
            "distance_from_reference_pct"
        ),
        "reason": "；".join(row.get("trend_signals") or []),
        "strength": "强" if len(confirmations) >= 3 else "中",
        "source_type": "日线右侧启动",
        "confirmed_by": "+".join(confirmations),
        "confirmations": confirmations,
        "change_pct": row.get("change_pct", 0),
        "volume_ratio": row.get("volume_ratio", 0),
    }
    return {
        **row,
        "signal_tier": "candidate",
        "best_buy_point": buy_point,
        "buy_points": [dict(buy_point)],
        "buy_points_30min": [],
        "reference_buy_points": [],
        "blocked_buy_points": [],
        "pivots": {},
        "trend_type": "up",
        "resonance": {},
        "ma_bullish": True,
        "fusion_admission": {},
        "market_regime": "",
    }
