"""Policy experiment metrics for backtest-only experiments."""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, cast

from chanlun.historical_experiment_metrics import (
    _evaluate_pick_sample,
    _fetch_daily_kline_cached,
    _normalize_kline,
    entry_mode_for_pick,
    should_drop_pick_for_experiment,
)
from chanlun.backtest_execution import evaluate_exit_returns
from chanlun.backtest_metrics import summarize_return_samples
from scripts.backtest_recommendation_quality import iter_snapshot_picks

POLICY_EXPERIMENTS = {
    "delay1_v1": {
        "cooldown_days": None,
        "bottom_quality_guard": False,
    },
    "delay1_v1_cooldown3": {
        "cooldown_days": 3,
        "bottom_quality_guard": False,
    },
    "delay1_v1_cooldown5": {
        "cooldown_days": 5,
        "bottom_quality_guard": False,
    },
    "delay1_v1_bottom_quality_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
    },
    "delay1_v1_cooldown3_bottom_quality": {
        "cooldown_days": 3,
        "bottom_quality_reasons": "all",
    },
    "delay1_v1_bottom_missing_key_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": ("missing_key_protection",),
    },
    "delay1_v1_bottom_missing_distance_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": ("missing_distance",),
    },
    "delay1_v1_bottom_invalid_distance_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": ("invalid_distance",),
    },
    "delay1_v1_bottom_distance_gt6_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": ("distance_gt_6",),
    },
    "delay1_v1_bottom_missing_shape_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": ("missing_bottom_shape_or_stop_drop",),
    },
    "delay1_v1_bottom_quality_market_strong_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_not_strong",),
    },
    "delay1_v1_bottom_quality_market_known_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_signal_close": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_signal_close",
        "entry_mode": "immediate_close",
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_next_open": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_next_open",
        "entry_mode": "delay1_open",
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_next_open",
        "entry_mode": "delay1_open",
        "exit_model": "exit_t3",
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_next_open",
        "entry_mode": "delay1_open",
        "exit_model": "exit_stop_loss_5pct",
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_next_open",
        "entry_mode": "delay1_open",
        "exit_model": "exit_take_profit_8pct_or_t3",
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_next_open",
        "entry_mode": "delay1_open",
        "exit_model": "exit_stop5_take8_conservative",
    },
    "delay1_v1_bottom_quality_market_known_guard_entry_confirm_close": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_unknown",),
        "entry_label": "entry_confirm_close",
        "entry_mode": "delay1_close",
    },
    "delay1_v1_bottom_quality_market_or_ma_guard": {
        "cooldown_days": None,
        "bottom_quality_reasons": "all",
        "bottom_trend_reasons": ("market_not_strong_no_ma",),
    },
}

_BASELINE_EXPERIMENT = "signal_delay1_by_type_guard"
_BOTTOM_QUALITY_REASON_LABELS = {
    "missing_key_protection": "bottom_missing_key_protection",
    "missing_distance": "bottom_missing_distance",
    "invalid_distance": "bottom_invalid_distance",
    "distance_gt_6": "bottom_distance_gt_6",
    "missing_bottom_shape_or_stop_drop": "bottom_missing_shape_or_stop_drop",
}
_BOTTOM_TREND_REASON_LABELS = {
    "market_not_strong": "bottom_market_not_strong",
    "market_unknown": "bottom_market_unknown",
    "market_not_strong_no_ma": "bottom_market_not_strong_no_ma",
}


def list_policy_experiments() -> list:
    """Return registered policy experiment names."""
    return list(POLICY_EXPERIMENTS.keys())


def supports_policy_experiment(name: str) -> bool:
    return name in POLICY_EXPERIMENTS


def _as_str_list(values) -> List[str]:
    if values is None:
        return []
    return [str(item) for item in values]


def _market_regime_bucket(pick: Optional[dict]) -> str:
    value = str((pick or {}).get("market_regime") or "").strip().lower()
    return value or "unknown"


def _best_buy_point_type_bucket(pick: Optional[dict]) -> str:
    bbp = (pick or {}).get("best_buy_point")
    value = str((bbp or {}).get("type") or "").strip()
    return value or "unknown"


def _confirmations_bucket(pick: Optional[dict]) -> str:
    bbp = (pick or {}).get("best_buy_point")
    values = sorted(_as_str_list((bbp or {}).get("confirmations")))
    return " + ".join(values) if values else "none"


def _new_breakdown_bucket() -> Dict[str, object]:
    return {
        "total": 0,
        "accepted": 0,
        "filtered": 0,
        "filter_reasons": {},
    }


def _record_breakdown(
    breakdown: Dict[str, Dict[str, dict]],
    pick: Optional[dict],
    accepted: bool,
    filter_reason: str = "",
) -> None:
    dimensions = {
        "market_regime": _market_regime_bucket(pick),
        "best_buy_point_type": _best_buy_point_type_bucket(pick),
        "confirmations": _confirmations_bucket(pick),
    }
    for dimension_name, bucket in dimensions.items():
        dimension = breakdown.setdefault(dimension_name, {})
        bucket_value = dimension.setdefault(
            bucket,
            _new_breakdown_bucket(),
        )
        bucket_value["total"] += 1
        if accepted:
            bucket_value["accepted"] += 1
        else:
            bucket_value["filtered"] += 1
            if filter_reason:
                reasons = bucket_value.setdefault("filter_reasons", {})
                reasons[filter_reason] = int(reasons.get(filter_reason, 0)) + 1


def bottom_quality_guard_reasons(pick: Optional[dict]) -> List[str]:
    bbp = (pick or {}).get("best_buy_point")
    if not isinstance(bbp, dict) or bbp.get("type") != "底背驰候选":
        return []

    confirmations = _as_str_list(bbp.get("confirmations"))
    has_key_protection = "关键位不破" in confirmations
    has_30m_bottom = "30min底分型" in confirmations
    has_stop_drop = "止跌结构" in confirmations

    reasons = []

    if not has_key_protection:
        reasons.append("missing_key_protection")

    distance = bbp.get("distance_from_reference_pct")
    if distance is None:
        reasons.append("missing_distance")
    else:
        try:
            distance = float(distance)
        except (TypeError, ValueError):
            reasons.append("invalid_distance")
        else:
            if distance > 6:
                reasons.append("distance_gt_6")

    if (not has_30m_bottom) and (not has_stop_drop):
        reasons.append("missing_bottom_shape_or_stop_drop")

    return reasons


def bottom_trend_guard_reasons(pick: Optional[dict]) -> List[str]:
    bbp = (pick or {}).get("best_buy_point")
    if not isinstance(bbp, dict) or bbp.get("type") != "底背驰候选":
        return []

    regime = (pick or {}).get("market_regime")
    regime_text = str(regime or "").strip().lower()
    ma_bullish = (pick or {}).get("ma_bullish") is True

    reasons = []
    if not regime_text:
        reasons.append("market_unknown")
    if regime_text != "strong":
        reasons.append("market_not_strong")
    if regime_text != "strong" and not ma_bullish:
        reasons.append("market_not_strong_no_ma")
    return reasons


def _bottom_quality_reason_label(reason: str) -> str:
    return _BOTTOM_QUALITY_REASON_LABELS.get(reason, reason)


def _bottom_trend_reason_label(reason: str) -> str:
    return _BOTTOM_TREND_REASON_LABELS.get(reason, reason)


def _pick_type(pick: Optional[dict]) -> str:
    bbp = (pick or {}).get("best_buy_point") or {}
    return str(bbp.get("type") or "")


def _build_snapshot_rows() -> list:
    rows = list(iter_snapshot_picks())
    return sorted(
        rows,
        key=lambda row: (str(row[0]), str(row[1]), str((row[2] or {}).get("code", ""))),
    )


def _build_snapshot_day_index(rows: Sequence[Tuple[str, str, dict]]) -> Dict[str, int]:
    dates = sorted({str(item[0]) for item in rows})
    return {snap_date: idx for idx, snap_date in enumerate(dates)}


def _build_shared_baseline_context(
    rows: Sequence[Tuple[str, str, dict]],
    snapshot_index_map: Dict[str, int],
) -> Dict[str, object]:
    kline_cache: Dict[str, Optional[dict]] = {}
    unique_codes = set()
    fetch_attempts = 0
    cache_hits = 0
    kline_missing = 0
    kline_invalid = 0
    picks_seen = 0
    baseline_evaluated = 0
    baseline_filtered = 0
    baseline_samples: List[dict] = []
    evaluated_rows: List[dict] = []

    for snap_date, _version, pick in rows:
        picks_seen += 1
        code = (pick or {}).get("code")
        if not code:
            continue

        code_str = str(code)
        unique_codes.add(code_str)
        if code_str in kline_cache:
            cache_hits += 1
            kline = kline_cache[code_str]
        else:
            fetch_attempts += 1
            kline = _fetch_daily_kline_cached(code_str, kline_cache)
            if code_str not in kline_cache:
                kline_cache[code_str] = kline

        if kline is None:
            kline_missing += 1
            continue

        normalized_kline = _normalize_kline(kline)
        if not normalized_kline:
            kline_invalid += 1
            continue

        if should_drop_pick_for_experiment(_BASELINE_EXPERIMENT, pick):
            baseline_filtered += 1
            continue

        entry_mode = entry_mode_for_pick(_BASELINE_EXPERIMENT, pick)
        baseline_sample = _evaluate_pick_sample(normalized_kline, snap_date, entry_mode)
        if baseline_sample is None:
            continue

        baseline_evaluated += 1
        baseline_samples.append(baseline_sample)
        evaluated_rows.append(
            {
                "snap_date": str(snap_date),
                "pick": pick,
                "baseline_sample": baseline_sample,
                "normalized_kline": normalized_kline,
            },
        )

    coverage = {
        "snapshot_days": len(snapshot_index_map),
        "picks_seen": picks_seen,
        "baseline_evaluated": baseline_evaluated,
        "baseline_filtered": baseline_filtered,
    }
    execution = {
        "shared_baseline": True,
        "snapshot_rows": len(rows),
        "unique_codes": len(unique_codes),
        "fetch_attempts": fetch_attempts,
        "cache_hits": cache_hits,
        "kline_missing": kline_missing,
        "kline_invalid": kline_invalid,
        "baseline_rows": len(evaluated_rows),
    }

    return {
        "coverage": coverage,
        "baseline_samples": baseline_samples,
        "evaluated_rows": evaluated_rows,
        "execution": execution,
    }


def _is_cooldown_hit(name: str, pick: dict, state: dict) -> bool:
    cfg = POLICY_EXPERIMENTS.get(name)
    if not cfg:
        return False

    days = cfg.get("cooldown_days")
    if not days:
        return False

    snap_date = state.get("snap_date")
    if snap_date is None:
        return False

    snap_index = state.get("snapshot_index_map", {}).get(str(snap_date))
    if snap_index is None:
        return False

    code = (pick or {}).get("code")
    pick_type = _pick_type(pick)
    if not code or not pick_type:
        return False

    key = (str(code), pick_type)
    last_seen = state.get("cooldown_last_seen", {}).get(key)
    if last_seen is None:
        return False

    return snap_index - last_seen < days


def _record_cooldown_accept(name: str, pick: dict, state: dict) -> None:
    cfg = POLICY_EXPERIMENTS.get(name)
    if not cfg:
        return

    days = cfg.get("cooldown_days")
    if not days:
        return

    snap_date = state.get("snap_date")
    if snap_date is None:
        return

    snap_index = state.get("snapshot_index_map", {}).get(str(snap_date))
    if snap_index is None:
        return

    code = (pick or {}).get("code")
    pick_type = _pick_type(pick)
    if not code or not pick_type:
        return

    state.setdefault("cooldown_last_seen", {})[(str(code), pick_type)] = snap_index


def should_filter_for_policy(name: str, pick: dict, state: dict) -> Tuple[bool, str]:
    """Return whether a pick should be filtered under a policy."""
    if not isinstance(state, dict):
        state = {}
    if not supports_policy_experiment(name):
        return False, "unsupported"

    cfg = POLICY_EXPERIMENTS[name]
    quality_reasons = cfg.get("bottom_quality_reasons")
    guard_reasons = bottom_quality_guard_reasons(pick)
    if quality_reasons == "all":
        if guard_reasons:
            return True, "bottom_quality_guard"

    for reason in _as_str_list(quality_reasons):
        if reason in guard_reasons:
            return True, _bottom_quality_reason_label(reason)

    trend_reasons = cfg.get("bottom_trend_reasons")
    trend_guard_reasons = bottom_trend_guard_reasons(pick)
    for reason in _as_str_list(trend_reasons):
        if reason in trend_guard_reasons:
            return True, _bottom_trend_reason_label(reason)

    if _is_cooldown_hit(name, pick, state):
        return True, "cooldown"

    return False, ""


def _summarize_delta(base: Optional[dict], policy: Optional[dict], key: str) -> Optional[float]:
    if base is None or policy is None:
        return None
    base_value = base.get(key)
    policy_value = policy.get(key)
    if base_value is None or policy_value is None:
        return None
    try:
        return round(float(policy_value) - float(base_value), 2)
    except (TypeError, ValueError):
        return None


def _run_one_policy(
    name: str,
    rows: Sequence[dict],
    snapshot_index_map: Dict[str, int],
    baseline_summary: Optional[dict],
    baseline_coverage: Dict[str, int],
) -> Dict:
    state = {
        "snapshot_index_map": snapshot_index_map,
        "cooldown_last_seen": {},
        "snap_date": None,
    }

    picks_seen = baseline_coverage.get("picks_seen", 0)
    baseline_evaluated = baseline_coverage.get("baseline_evaluated", 0)
    baseline_filtered = baseline_coverage.get("baseline_filtered", 0)

    policy_evaluated = 0
    policy_filtered = 0
    policy_filtered_by_reason = Counter()
    policy_filtered_detail_by_reason = Counter()
    policy_samples: List[dict] = []
    policy_not_evaluable = 0
    policy_breakdown: Dict[str, Dict[str, dict]] = {
        "market_regime": {},
        "best_buy_point_type": {},
        "confirmations": {},
    }
    cfg = POLICY_EXPERIMENTS.get(name, {})
    entry_mode = cfg.get("entry_mode")
    entry_label = cfg.get("entry_label")
    exit_model = cfg.get("exit_model")

    for item in rows:
        snap_date = item["snap_date"]
        pick = item.get("pick")

        state["snap_date"] = snap_date
        filtered, reason = should_filter_for_policy(name, pick, state)
        if filtered:
            _record_breakdown(policy_breakdown, pick, accepted=False, filter_reason=reason)
            policy_filtered += 1
            if reason:
                policy_filtered_by_reason[reason] += 1
            if reason == "bottom_quality_guard":
                for detail_reason in bottom_quality_guard_reasons(pick):
                    policy_filtered_detail_by_reason[
                        _bottom_quality_reason_label(detail_reason)
                    ] += 1
            continue
        elif reason:
            policy_filtered_by_reason[reason] += 1

        policy_sample = item.get("baseline_sample")
        _record_breakdown(policy_breakdown, pick, accepted=True)

        if entry_mode:
            if exit_model:
                policy_sample = evaluate_exit_returns(
                    item.get("normalized_kline"),
                    snap_date,
                    entry_mode,
                    exit_model,
                )
            else:
                policy_sample = _evaluate_pick_sample(
                    item.get("normalized_kline"),
                    snap_date,
                    entry_mode,
                )
            if policy_sample is None:
                policy_not_evaluable += 1
                _record_cooldown_accept(name, pick, state)
                continue

        if policy_sample is not None:
            policy_samples.append(policy_sample)
            policy_evaluated += 1

        _record_cooldown_accept(name, pick, state)

    policy_summary = summarize_return_samples(policy_samples)
    retained_ratio = (
        round(policy_evaluated / baseline_evaluated * 100, 2) if baseline_evaluated else 0.0
    )

    return {
        "policy": name,
        "coverage": {
            "snapshot_days": len(snapshot_index_map),
            "picks_seen": picks_seen,
            "baseline_evaluated": baseline_evaluated,
            "policy_evaluated": policy_evaluated,
            "baseline_filtered": baseline_filtered,
            "policy_filtered": policy_filtered,
            "policy_filtered_by_reason": dict(policy_filtered_by_reason),
            "policy_filtered_detail_by_reason": dict(policy_filtered_detail_by_reason),
            "policy_not_evaluable": policy_not_evaluable,
            "retained_ratio_pct": retained_ratio,
        },
        "baseline_summary": dict(baseline_summary) if baseline_summary is not None else None,
        "policy_summary": policy_summary,
        "baseline_policy": _BASELINE_EXPERIMENT,
        "execution_model": {
            "entry_label": entry_label or "baseline_type_guard",
            "entry_mode": entry_mode or "baseline_type_guard",
            "exit_model": exit_model or "exit_t3",
        },
        "breakdown": policy_breakdown,
        "delta": {
            "t3_mean_delta": _summarize_delta(baseline_summary, policy_summary, "t3_mean"),
            "t3_win_rate_delta": _summarize_delta(baseline_summary, policy_summary, "t3_win_rate"),
            "t3_loss_5pct_rate_delta": _summarize_delta(
                baseline_summary,
                policy_summary,
                "t3_loss_5pct_rate",
            ),
            "big_drop_5pct_rate_delta": _summarize_delta(
                baseline_summary,
                policy_summary,
                "big_drop_5pct_rate",
            ),
        },
    }


def run_policy_experiment_metrics(policy_names: Optional[Iterable[str]] = None) -> Dict:
    if policy_names is None:
        policy_names = list_policy_experiments()

    names: List[str] = []
    for name in policy_names:
        if name in names:
            continue
        names.append(name)

    unknown = [name for name in names if not supports_policy_experiment(name)]
    if unknown:
        raise ValueError(f"unsupported policies: {', '.join(unknown)}")

    if not names:
        return {
            "policies": [],
            "execution": {
                "shared_baseline": True,
                "snapshot_rows": 0,
                "unique_codes": 0,
                "fetch_attempts": 0,
                "cache_hits": 0,
                "kline_missing": 0,
                "kline_invalid": 0,
                "baseline_rows": 0,
            },
        }

    rows = _build_snapshot_rows()
    snapshot_index_map = _build_snapshot_day_index(rows)

    baseline_context = _build_shared_baseline_context(rows, snapshot_index_map)
    baseline_samples = cast(List[dict], baseline_context["baseline_samples"])
    baseline_rows = cast(List[dict], baseline_context["evaluated_rows"])
    baseline_coverage = cast(Dict[str, int], baseline_context["coverage"])
    execution = cast(Dict[str, object], baseline_context.get("execution", {}))

    baseline_summary = summarize_return_samples(baseline_samples)

    policy_results = [
        _run_one_policy(
            name,
            baseline_rows,
            snapshot_index_map,
            baseline_summary,
            baseline_coverage,
        )
        for name in names
    ]

    base_name = names[0] if names else _BASELINE_EXPERIMENT
    return {
        "policies": policy_results,
        "baseline_reference": _BASELINE_EXPERIMENT,
        "requested_policies": names,
        "base_index_name": base_name,
        "snapshot_rows": len(rows),
        "execution": execution,
    }
