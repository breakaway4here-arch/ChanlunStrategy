"""Policy experiment metrics for backtest-only experiments."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, cast

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
from chanlun.signal_quality_classifier import (
    build_signal_context,
    classify_signal,
    explain_signal_rejection,
    list_quality_profile_variants,
)

FUSION_PROFILES = (
    "fusion_strict_startup_rescue_v1",
    "fusion_strict",
    "fusion_mid",
    "fusion_loose",
)
_FUSION_STRICT = "fusion_strict"
_FUSION_STRICT_STARTUP_RESCUE_V1 = "fusion_strict_startup_rescue_v1"
_FUSION_MID = "fusion_mid"
_FUSION_LOOSE = "fusion_loose"
_ENTRY_MODE_IMMEDIATE = "immediate_close"

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
    return list(POLICY_EXPERIMENTS.keys()) + list(FUSION_PROFILES)


def supports_policy_experiment(name: str) -> bool:
    if name in POLICY_EXPERIMENTS:
        return True
    return name in FUSION_PROFILES


def _is_fusion_profile(name: str) -> bool:
    return name in FUSION_PROFILES


def _to_ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 4)


def _to_pct(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total * 100, 2)


def _build_fusion_pick_signal(pick: Optional[dict]) -> dict:
    if not isinstance(pick, dict):
        return {}
    best_buy_point = pick.get("best_buy_point")
    if isinstance(best_buy_point, dict):
        signal = dict(best_buy_point)
        signal["context"] = build_signal_context(pick, signal)
        return signal
    return {}


def _is_fusion_profile_a(pick: Optional[dict], profile: str) -> bool:
    signal = _build_fusion_pick_signal(pick)
    if not signal:
        return False
    return classify_signal(signal, profile=profile) == "A"


def _fusion_profile_reject_reasons(pick: Optional[dict], profile: str) -> List[str]:
    signal = _build_fusion_pick_signal(pick)
    if not signal:
        return ["missing_best_buy_point"]
    return explain_signal_rejection(signal, profile=profile)


def _build_picks_fusion_snapshot_rows() -> list:
    return [
        (snap_date, version, pick)
        for snap_date, version, pick in iter_snapshot_picks()
        if version == "picks_fusion"
    ]


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


def _build_fusion_baseline_context(
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
    baseline_samples: List[dict] = []
    evaluated_rows: List[dict] = []

    for snap_date, version, pick in rows:
        if version != "picks_fusion":
            continue

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

        baseline_sample = _evaluate_pick_sample(
            normalized_kline,
            snap_date,
            _ENTRY_MODE_IMMEDIATE,
        )
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
        "baseline_filtered": 0,
        "version": "picks_fusion",
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


def _is_fusion_profile_accepted(profile_summary: Optional[dict]) -> bool:
    if not isinstance(profile_summary, dict):
        return False

    coverage = profile_summary.get("coverage", 0.0) or 0.0
    t3_mean = profile_summary.get("t3_mean_after")
    win_rate = profile_summary.get("t3_win_rate_after")
    drawdown = profile_summary.get("drawdown_mean_after")
    return (
        0.25 <= coverage <= 0.35
        and t3_mean is not None
        and t3_mean > 0.80
        and win_rate is not None
        and win_rate >= 49.0
        and drawdown is not None
        and drawdown >= -4.60
    )


def _fusion_reject_reason(profile_summary: dict) -> str:
    reasons = []
    coverage = profile_summary.get("coverage", 0.0) or 0.0
    t3_mean = profile_summary.get("t3_mean_after")
    win_rate = profile_summary.get("t3_win_rate_after")
    drawdown = profile_summary.get("drawdown_mean_after")
    if coverage < 0.25:
        reasons.append("coverage below 25%")
    elif coverage > 0.35:
        reasons.append("coverage above 35%")
    if t3_mean is None or t3_mean <= 0.80:
        reasons.append("T+3 mean <= 0.80")
    if win_rate is None or win_rate < 49.0:
        reasons.append("T+3 win rate < 49%")
    if drawdown is None or drawdown < -4.60:
        reasons.append("drawdown worse than -4.60")
    return ", ".join(reasons) if reasons else "accepted"


def _pareto_frontier(items: List[dict]) -> List[str]:
    candidates = [item for item in items if item.get("n_after", 0) > 0]
    frontier: List[str] = []

    for item in candidates:
        dominated = False
        for other in candidates:
            if item is other:
                continue
            if _dominates(other, item):
                dominated = True
                break
        if not dominated:
            frontier.append(item.get("candidate"))

    return frontier


def _dominates(left: dict, right: dict) -> bool:
    left_cov = _to_float(left.get("coverage"))
    right_cov = _to_float(right.get("coverage"))
    left_t3 = left.get("t3_mean_after")
    right_t3 = right.get("t3_mean_after")
    if None in (left_cov, right_cov, left_t3, right_t3):
        return False

    better_or_equal = (
        float(left_cov) >= float(right_cov)
        and float(left_t3) >= float(right_t3)
    )
    strictly_better = (
        float(left_cov) > float(right_cov)
        or float(left_t3) > float(right_t3)
    )
    return better_or_equal and strictly_better


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _rank_fusion_profiles(items: List[dict], prefer_coverage: bool = False) -> List[dict]:
    if prefer_coverage:
        return sorted(
            items,
            key=lambda item: (
                item.get("coverage") or 0.0,
                item.get("t3_mean_after") if item.get("t3_mean_after") is not None else -999,
                item.get("drawdown_mean_after") if item.get("drawdown_mean_after") is not None else -999,
            ),
            reverse=True,
        )
    return sorted(
        items,
        key=lambda item: (
            1 if item.get("accepted") else 0,
            item.get("t3_mean_after") if item.get("t3_mean_after") is not None else -999,
            item.get("coverage") or 0.0,
            item.get("drawdown_mean_after") if item.get("drawdown_mean_after") is not None else -999,
        ),
        reverse=True,
    )


def _summarize_fusion_variant(
    candidate_name: str,
    variant_name: str,
    baseline_rows: Sequence[dict],
    baseline_n: int,
    t3_mean_before: Optional[float],
    t3_win_rate_before: Optional[float],
    drawdown_before: Optional[float],
) -> dict:
    profile_samples: List[dict] = []
    reject_reasons = Counter()
    rejected_samples = 0
    for item in baseline_rows:
        pick = item.get("pick")
        if _is_fusion_profile_a(pick, variant_name):
            profile_samples.append(item["baseline_sample"])
            continue

        rejected_samples += 1
        for reason in _fusion_profile_reject_reasons(pick, variant_name):
            reject_reasons[reason] += 1

    profile_summary = summarize_return_samples(profile_samples)
    samples_after = profile_summary.get("n") if profile_summary else 0
    coverage = _to_ratio(samples_after, baseline_n)
    coverage_pct = _to_pct(samples_after, baseline_n)
    t3_mean_after = profile_summary.get("t3_mean") if profile_summary else None
    t3_win_rate_after = profile_summary.get("t3_win_rate") if profile_summary else None
    drawdown_after = profile_summary.get("max_dd_3d_mean") if profile_summary else None

    row = {
        "candidate": candidate_name,
        "variant": variant_name,
        "samples_before": baseline_n,
        "samples_after": samples_after,
        "coverage": coverage,
        "coverage_pct": coverage_pct,
        "t3_mean_before": t3_mean_before,
        "t3_mean_after": t3_mean_after,
        "t3_win_rate_before": t3_win_rate_before,
        "t3_win_rate_after": t3_win_rate_after,
        "drawdown_mean_before": drawdown_before,
        "drawdown_mean_after": drawdown_after,
        "n_after": samples_after,
        "rejected_samples": rejected_samples,
        "reject_reason_distribution": dict(sorted(reject_reasons.items())),
        "top_reject_reason": (
            reject_reasons.most_common(1)[0][0] if reject_reasons else None
        ),
    }
    row["accepted"] = _is_fusion_profile_accepted(row)
    return row


def _run_fusion_threshold_scan(profile_names: List[str]) -> Dict[str, object]:
    names = [name for name in profile_names if name in FUSION_PROFILES]
    rows = _build_picks_fusion_snapshot_rows()
    snapshot_index_map = _build_snapshot_day_index(rows)
    baseline_context = _build_fusion_baseline_context(rows, snapshot_index_map)
    baseline_samples = cast(List[dict], baseline_context["baseline_samples"])
    baseline_rows = cast(List[dict], baseline_context["evaluated_rows"])
    baseline_coverage = cast(Dict[str, int], baseline_context["coverage"])
    execution = cast(Dict[str, object], baseline_context.get("execution", {}))

    baseline_summary = summarize_return_samples(baseline_samples)
    baseline_n = baseline_summary.get("n") if baseline_summary else 0
    t3_mean_before = baseline_summary.get("t3_mean") if baseline_summary else None
    t3_win_rate_before = baseline_summary.get("t3_win_rate") if baseline_summary else None
    drawdown_before = baseline_summary.get("max_dd_3d_mean") if baseline_summary else None

    variant_results: Dict[str, List[dict]] = {}
    profile_rows: List[dict] = []
    for name in names:
        variants = list_quality_profile_variants(name)
        variant_rows = [
            _summarize_fusion_variant(
                name,
                variant,
                baseline_rows,
                baseline_n,
                t3_mean_before,
                t3_win_rate_before,
                drawdown_before,
            )
            for variant in variants
        ]
        variant_results[name] = variant_rows
        if not variant_rows:
            continue
        best = _rank_fusion_profiles(
            variant_rows,
            prefer_coverage=(name == _FUSION_LOOSE),
        )[0]
        profile_rows.append(dict(best))

    baseline_metrics = {
        "samples": baseline_n,
        "t3_mean_before": t3_mean_before,
        "t3_win_rate_before": t3_win_rate_before,
        "drawdown_mean_before": drawdown_before,
    }

    pareto = _pareto_frontier(profile_rows)
    accepted_profiles = [
        item for item in profile_rows
        if item.get("accepted") and item.get("candidate") in pareto
    ]
    if accepted_profiles:
        ranked = _rank_fusion_profiles(accepted_profiles)
        selected = ranked[0]["candidate"]
        rejected = [item.get("candidate") for item in profile_rows if not item.get("accepted")]
        selected_reason = "meets target criteria"
    else:
        if _FUSION_STRICT_STARTUP_RESCUE_V1 in names:
            selected = _FUSION_STRICT_STARTUP_RESCUE_V1
        elif names:
            selected = names[0]
        else:
            selected = _FUSION_STRICT
        accepted_profiles = []
        rejected = [item.get("candidate") for item in profile_rows if item.get("candidate") != selected]
        selected_reason = "no profile met all target criteria"
    rejected_reasons = {
        item.get("candidate"): _fusion_reject_reason(item)
        for item in profile_rows
        if item.get("candidate") in rejected
    }

    return {
        "profiles": profile_rows,
        "variant_results": variant_results,
        "baseline_reference": "picks_fusion",
        "snapshot_rows": len(rows),
        "snapshot_coverage": baseline_coverage,
        "baseline_metrics": baseline_metrics,
        "selected": {
            "candidate": selected,
            "reason": selected_reason,
            "accepted": selected in [item.get("candidate") for item in accepted_profiles],
        },
        "rejected": rejected,
        "rejected_reasons": rejected_reasons,
        "pareto_frontier": pareto,
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
    if _is_fusion_profile(name):
        return False, ""

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
            "fusion_threshold_scan": {
                "profiles": [],
                "selected": {},
                "rejected": [],
                "pareto_frontier": [],
            },
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
    legacy_names = [name for name in names if not _is_fusion_profile(name)]
    fusion_names = [name for name in names if _is_fusion_profile(name)]

    payload: Dict[str, object] = {
        "policies": [],
        "fusion_threshold_scan": {
            "profiles": [],
            "selected": {},
            "rejected": [],
            "pareto_frontier": [],
        },
    }
    payload["requested_policies"] = names

    if legacy_names:
        baseline_context = _build_shared_baseline_context(rows, snapshot_index_map)
        baseline_samples = cast(List[dict], baseline_context["baseline_samples"])
        baseline_rows = cast(List[dict], baseline_context["evaluated_rows"])
        baseline_coverage = cast(Dict[str, int], baseline_context["coverage"])
        baseline_summary = summarize_return_samples(baseline_samples)
        execution = cast(Dict[str, object], baseline_context.get("execution", {}))
        payload["execution"] = execution

        payload["policies"] = [
            _run_one_policy(
                name,
                baseline_rows,
                snapshot_index_map,
                baseline_summary,
                baseline_coverage,
            )
            for name in legacy_names
        ]

    if fusion_names:
        payload["fusion_threshold_scan"] = _run_fusion_threshold_scan(fusion_names)
        # For pure fusion scans, keep execution aligned with fusion path.
        if not legacy_names:
            payload["execution"] = payload["fusion_threshold_scan"].get("execution", {})

    if "baseline_reference" not in payload:
        if legacy_names:
            payload["baseline_reference"] = _BASELINE_EXPERIMENT
        else:
            payload["baseline_reference"] = "picks_fusion"

    if "base_index_name" not in payload:
        if payload.get("policies"):
            payload["base_index_name"] = legacy_names[0] if legacy_names else _BASELINE_EXPERIMENT
        elif fusion_names:
            payload["base_index_name"] = "picks_fusion"

    if not payload.get("snapshot_rows"):
        if fusion_names:
            payload["snapshot_rows"] = payload["fusion_threshold_scan"].get("snapshot_rows", len(rows))
        else:
            payload["snapshot_rows"] = len(rows)

    if "execution" not in payload:
        payload["execution"] = {
            "shared_baseline": True,
            "snapshot_rows": len(rows),
            "unique_codes": 0,
            "fetch_attempts": 0,
            "cache_hits": 0,
            "kline_missing": 0,
            "kline_invalid": 0,
            "baseline_rows": 0,
        }

    return payload
