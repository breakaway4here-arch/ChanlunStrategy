"""Policy experiment metrics for backtest-only experiments."""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from chanlun.historical_experiment_metrics import (
    _evaluate_pick_sample,
    _fetch_daily_kline_cached,
    _normalize_kline,
    entry_mode_for_pick,
    should_drop_pick_for_experiment,
)
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
}

_BASELINE_EXPERIMENT = "signal_delay1_by_type_guard"
_BOTTOM_QUALITY_REASON_LABELS = {
    "missing_key_protection": "bottom_missing_key_protection",
    "missing_distance": "bottom_missing_distance",
    "invalid_distance": "bottom_invalid_distance",
    "distance_gt_6": "bottom_distance_gt_6",
    "missing_bottom_shape_or_stop_drop": "bottom_missing_shape_or_stop_drop",
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


def _bottom_quality_reason_label(reason: str) -> str:
    return _BOTTOM_QUALITY_REASON_LABELS.get(reason, reason)


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


def _run_one_policy(name: str, rows: Sequence[Tuple[str, str, dict]]) -> Dict:
    snapshot_index_map = _build_snapshot_day_index(rows)
    state = {
        "snapshot_index_map": snapshot_index_map,
        "cooldown_last_seen": {},
        "snap_date": None,
    }
    snaps = sorted(snapshot_index_map.keys())

    picks_seen = 0
    kline_cache: Dict[str, Optional[dict]] = {}
    baseline_evaluated = 0
    policy_evaluated = 0
    baseline_filtered = 0
    policy_filtered = 0
    policy_filtered_by_reason = Counter()
    policy_filtered_detail_by_reason = Counter()
    baseline_samples: List[dict] = []
    policy_samples: List[dict] = []

    for snap_date, _version, pick in rows:
        picks_seen += 1
        code = (pick or {}).get("code")
        if not code:
            continue

        kline = _fetch_daily_kline_cached(code, kline_cache)
        if kline is None:
            continue

        normalized_kline = _normalize_kline(kline)
        if normalized_kline is None:
            continue

        if should_drop_pick_for_experiment(_BASELINE_EXPERIMENT, pick):
            baseline_filtered += 1
            continue

        baseline_entry_mode = entry_mode_for_pick(_BASELINE_EXPERIMENT, pick)
        baseline_sample = _evaluate_pick_sample(normalized_kline, snap_date, baseline_entry_mode)
        if baseline_sample is not None:
            baseline_samples.append(baseline_sample)
            baseline_evaluated += 1

        if baseline_sample is None:
            continue

        state["snap_date"] = str(snap_date)
        filtered, reason = should_filter_for_policy(name, pick, state)
        if filtered:
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

        entry_mode = entry_mode_for_pick(_BASELINE_EXPERIMENT, pick)
        policy_sample = _evaluate_pick_sample(normalized_kline, snap_date, entry_mode)
        if policy_sample is not None:
            policy_samples.append(policy_sample)
            policy_evaluated += 1

        _record_cooldown_accept(name, pick, state)

    baseline_summary = summarize_return_samples(baseline_samples)
    policy_summary = summarize_return_samples(policy_samples)
    retained_ratio = round(policy_evaluated / baseline_evaluated * 100, 2) if baseline_evaluated else 0.0

    return {
        "policy": name,
        "coverage": {
            "snapshot_days": len(snaps),
            "picks_seen": picks_seen,
            "baseline_evaluated": baseline_evaluated,
            "policy_evaluated": policy_evaluated,
            "baseline_filtered": baseline_filtered,
            "policy_filtered": policy_filtered,
            "policy_filtered_by_reason": dict(policy_filtered_by_reason),
            "policy_filtered_detail_by_reason": dict(policy_filtered_detail_by_reason),
            "retained_ratio_pct": retained_ratio,
        },
        "baseline_summary": baseline_summary,
        "policy_summary": policy_summary,
        "baseline_policy": _BASELINE_EXPERIMENT,
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
    rows = _build_snapshot_rows()
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
        return {"policies": []}

    base_name = names[0] if names else _BASELINE_EXPERIMENT
    return {
        "policies": [_run_one_policy(name, rows) for name in names],
        "baseline_reference": _BASELINE_EXPERIMENT,
        "requested_policies": names,
        "base_index_name": base_name,
        "snapshot_rows": len(rows),
    }
