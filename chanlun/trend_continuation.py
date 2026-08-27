"""Independent right-side trend-continuation retrieval and confirmation."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import config
from .chan_engine import ema
from .data_fetcher import is_st_stock
from .market_sentiment import classify_price_limit


def _float_array(value: Any) -> np.ndarray:
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)


def _latest_pivot_upper(result: Any) -> Optional[float]:
    pivots = getattr(result, "pivots", None) or []
    for pivot in reversed(list(pivots)):
        if not isinstance(pivot, Mapping):
            continue
        for key in ("ZG", "zg", "upper", "high"):
            try:
                value = float(pivot.get(key))
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

    reference_type = ""
    reference_price = 0.0
    if platform_breakout:
        reference_type = "platform_high_20d"
        reference_price = platform_high
    elif pivot_breakout:
        reference_type = "pivot_upper"
        reference_price = float(pivot_upper)
    elif close >= ma10:
        reference_type = "ma10"
        reference_price = ma10
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
        "source_channel": "trend_continuation",
        "tier": "seed",
        "category": "B",
        "quality_tier": "",
        "view": "main",
        "type": "趋势延续种子",
        "source_type": "日线趋势延续",
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
                    "ma_near_miss",
                    "trend_structure",
                    "趋势结构接近成立，但平台突破或MA保持仍差一项",
                    {
                        "volume_ratio": volume_ratio,
                        "strong_structure": False,
                    },
                    ["站稳MA5/MA10", "有效突破20日平台或中枢上沿"],
                    ["跌破MA10", "放量长阴破坏平台"],
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
            ))
            diagnostics["watch_risk"] += 1
            continue

        seed["tier"] = "seed"
        seed["category"] = "B"
        seeds.append(seed)
        diagnostics["trend_seed"] += 1
    return seeds, watchlist, diagnostics


def _confirm_30min(result: Any, reference_price: float) -> List[str]:
    closes = _float_array(getattr(result, "closes", None))
    volumes = _float_array(getattr(result, "volumes", None))
    if len(closes) < 10:
        return []
    confirmations = []
    if float(np.min(closes[-5:])) >= float(reference_price) * 0.995:
        confirmations.append("30min突破位不破")
    ema5 = ema(closes, 5)
    ema10 = ema(closes, 10)
    if len(ema5) and len(ema10) and float(ema5[-1]) >= float(ema10[-1]):
        confirmations.append("30min EMA5维持")
    if len(volumes) >= 10:
        recent = float(np.mean(volumes[-3:]))
        previous = float(np.mean(volumes[-10:-3]))
        if previous > 0 and recent <= previous:
            confirmations.append("30min缩量回踩")
    return confirmations


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
            ))
            diagnostics["watch_due_to_no_30min"] += 1
            continue
        confirmations = _confirm_30min(
            result, float(seed["reference_price"])
        )
        if len(confirmations) < 2:
            watchlist.append(_watch(
                seed,
                "waiting_30m_confirm",
                "30min_confirm",
                "日线趋势成立，但30min确认不足",
                confirmations,
                ["突破位不破", "EMA5维持", "缩量回踩满足两项"],
                ["跌破趋势参考位", "30min EMA转空"],
            ))
            diagnostics["watch_due_to_no_confirm"] += 1
            continue
        seed.update({
            "type": "趋势延续候选",
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
        "type": "趋势延续候选",
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
        "source_type": "日线趋势延续",
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
        "score": 0,
        "resonance": {},
        "ma_bullish": True,
        "fusion_admission": {},
        "market_regime": "",
    }
