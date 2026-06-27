"""Historical experiment metrics for snapshot-level return evaluation."""

from __future__ import annotations

from numbers import Integral, Real
from typing import Dict, Iterable, List, Optional, Tuple

from config import DAY_LOOKBACK
from chanlun.backtest_execution import evaluate_forward_returns
from chanlun.backtest_metrics import summarize_return_samples
from chanlun.data_fetcher import fetch_daily_kline
from scripts.backtest_recommendation_quality import iter_snapshot_picks


_SUPPORTED_SIGNAL_EXPERIMENTS = {
    "signal_delay1_by_type_guard",
    "signal_p0_distance_guard",
    "signal_p1_confirmation_guard",
    "signal_p0_p1_guard",
}


_ENTRY_MODE_IMMEDIATE = "immediate_close"
_ENTRY_MODE_DELAY1_OPEN = "delay1_open"
_ENTRY_MODE_DELAY1_CLOSE = "delay1_close"


def supports_historical_return_metrics(experiment_name: str) -> bool:
    return experiment_name in _SUPPORTED_SIGNAL_EXPERIMENTS


def _is_signal_newly_formed(point: dict, closes, required_bars: int = 1) -> bool:
    if not isinstance(point, dict) or not isinstance(required_bars, int) or required_bars <= 0:
        return False

    point_index = point.get("index")
    if not isinstance(point_index, Integral):
        return False

    if closes is None:
        return False

    try:
        latest_index = len(closes) - 1
    except TypeError:
        return False

    if latest_index < 0:
        return False

    if point_index < 0 or point_index > latest_index:
        return False

    signal_age = latest_index - point_index
    return signal_age < required_bars


def should_drop_pick_for_signal_delay1_by_type_guard(point: dict, closes) -> bool:
    if not isinstance(point, dict):
        return False
    if point.get("type") != "底背驰候选":
        return False
    return _is_signal_newly_formed(point, closes, required_bars=1)


def _is_str_list(value) -> bool:
    return isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)


def _should_drop_p0_distance(point: dict) -> bool:
    if not isinstance(point, dict):
        return False
    if point.get("type") != "底背驰候选":
        return False
    distance = point.get("distance_from_reference_pct")
    if not isinstance(distance, Real):
        return False
    return distance > 3


def _should_drop_p1_confirmation(point: dict) -> bool:
    if not isinstance(point, dict):
        return False

    confirmations = point.get("confirmations")
    if not _is_str_list(confirmations):
        return False

    contains_stop_drop = "止跌结构" in confirmations
    contains_ema5 = "EMA5收复" in confirmations
    contains_key_protection = "关键位不破" in confirmations
    contains_30m_bottom = "30min底分型" in confirmations
    return (
        contains_stop_drop
        and contains_ema5
        and not contains_key_protection
        and not contains_30m_bottom
    )


def should_drop_pick_for_experiment(experiment_name: str, pick: dict) -> bool:
    if not supports_historical_return_metrics(experiment_name):
        return False

    best_buy_point = (pick or {}).get("best_buy_point")
    if experiment_name == "signal_delay1_by_type_guard":
        closes = (pick or {}).get("closes")
        return should_drop_pick_for_signal_delay1_by_type_guard(best_buy_point, closes)
    if experiment_name == "signal_p0_distance_guard":
        return _should_drop_p0_distance(best_buy_point)
    if experiment_name == "signal_p1_confirmation_guard":
        return _should_drop_p1_confirmation(best_buy_point)
    if experiment_name == "signal_p0_p1_guard":
        return _should_drop_p0_distance(best_buy_point) or _should_drop_p1_confirmation(best_buy_point)
    return False


def _entry_mode_for_pick(experiment_name: str, pick: dict) -> str:
    if experiment_name != "signal_delay1_by_type_guard":
        return _ENTRY_MODE_IMMEDIATE

    if not isinstance(pick, dict):
        return _ENTRY_MODE_IMMEDIATE

    best_buy_point = pick.get("best_buy_point")
    if not isinstance(best_buy_point, dict):
        return _ENTRY_MODE_IMMEDIATE

    point_type = best_buy_point.get("type")
    if point_type == "底背驰候选":
        return _ENTRY_MODE_DELAY1_CLOSE
    if point_type == "强势启动候选":
        return _ENTRY_MODE_DELAY1_OPEN
    return _ENTRY_MODE_IMMEDIATE


def entry_mode_for_pick(experiment_name: str, pick: dict) -> str:
    """Resolve entry mode for a pick by experiment policy."""
    return _entry_mode_for_pick(experiment_name, pick)


def _normalize_kline(kline):
    if kline is None:
        return None

    dates = kline.get("dates", [])
    opens = kline.get("opens", [])
    highs = kline.get("highs", [])
    lows = kline.get("lows", [])
    closes = kline.get("closes", [])

    norm_dates = [str(d).split(" ")[0] for d in list(dates)]
    norm_opens = [float(v) for v in list(opens)]
    norm_highs = [float(v) for v in list(highs)]
    norm_lows = [float(v) for v in list(lows)]
    norm_closes = [float(v) for v in list(closes)]

    if not (len(norm_dates) == len(norm_opens) == len(norm_highs) == len(norm_lows) == len(norm_closes)):
        return None

    if not norm_dates:
        return None

    return {
        "dates": norm_dates,
        "opens": norm_opens,
        "highs": norm_highs,
        "lows": norm_lows,
        "closes": norm_closes,
    }


def _fetch_daily_kline_cached(code: str, kline_cache: Dict[str, Optional[dict]]) -> Optional[dict]:
    if code in kline_cache:
        return kline_cache[code]

    try:
        result = fetch_daily_kline(code, count=DAY_LOOKBACK)
    except Exception:
        result = None

    kline_cache[code] = result
    return result


def _build_coverage(
    snapshot_count: int,
    picks_seen: int,
    legacy_evaluated: int,
    experiment_evaluated: int,
    skipped_no_code: int,
    skipped_no_kline: int,
    filtered: int,
    not_evaluable: int,
    legacy_not_evaluable: int,
    experiment_not_evaluable: int,
) -> Dict[str, int]:
    return {
        "snapshot_days": snapshot_count,
        "picks_seen": picks_seen,
        "legacy_evaluated": legacy_evaluated,
        "experiment_evaluated": experiment_evaluated,
        "filtered": filtered,
        "skipped_no_code": skipped_no_code,
        "skipped_no_kline": skipped_no_kline,
        "not_evaluable": not_evaluable,
        "not_evaluable_legacy": legacy_not_evaluable,
        "not_evaluable_experiment": experiment_not_evaluable,
        "evaluated": experiment_evaluated,
    }


def _evaluate_pick_sample(kline, snap_date, entry_mode: str):
    return evaluate_forward_returns(kline, snap_date, entry_mode=entry_mode, horizon=5)


def _build_result_payload(
    legacy_samples: List[dict],
    experiment_samples: List[dict],
    coverage: Dict[str, int],
) -> Dict[str, Optional[dict]]:
    return {
        "return_metrics": {
            "legacy": summarize_return_samples(legacy_samples),
            "experiment": summarize_return_samples(experiment_samples),
        },
        "coverage": coverage,
    }


def run_historical_experiment_return_metrics(experiment_name: str):
    if not supports_historical_return_metrics(experiment_name):
        return None

    legacy_samples: List[dict] = []
    experiment_samples: List[dict] = []

    seen_snap_dates = set()
    picks_seen = 0
    legacy_evaluated = 0
    experiment_evaluated = 0
    skipped_no_code = 0
    skipped_no_kline = 0
    filtered = 0
    not_evaluable = 0
    legacy_not_evaluable = 0
    experiment_not_evaluable = 0

    kline_cache: Dict[str, Optional[dict]] = {}

    for snap_date, _version, pick in iter_snapshot_picks():
        picks_seen += 1
        seen_snap_dates.add(str(snap_date))

        code = (pick or {}).get("code")
        if not code:
            skipped_no_code += 1
            continue

        kline = _fetch_daily_kline_cached(code, kline_cache)
        if kline is None:
            skipped_no_kline += 1
            continue

        normalized_kline = _normalize_kline(kline)
        if normalized_kline is None:
            skipped_no_kline += 1
            continue

        legacy_sample = _evaluate_pick_sample(normalized_kline, snap_date, _ENTRY_MODE_IMMEDIATE)
        if legacy_sample is None:
            legacy_not_evaluable += 1
        else:
            legacy_samples.append(legacy_sample)
            legacy_evaluated += 1

        if should_drop_pick_for_experiment(experiment_name, pick):
            filtered += 1
            continue

        entry_mode = _entry_mode_for_pick(experiment_name, pick)
        exp_sample = _evaluate_pick_sample(normalized_kline, snap_date, entry_mode)
        if exp_sample is None:
            experiment_not_evaluable += 1
        else:
            experiment_samples.append(exp_sample)
            experiment_evaluated += 1

    not_evaluable = legacy_not_evaluable + experiment_not_evaluable
    coverage = _build_coverage(
        snapshot_count=len(seen_snap_dates),
        picks_seen=picks_seen,
        legacy_evaluated=legacy_evaluated,
        experiment_evaluated=experiment_evaluated,
        skipped_no_code=skipped_no_code,
        skipped_no_kline=skipped_no_kline,
        filtered=filtered,
        not_evaluable=not_evaluable,
        legacy_not_evaluable=legacy_not_evaluable,
        experiment_not_evaluable=experiment_not_evaluable,
    )

    return _build_result_payload(
        legacy_samples=legacy_samples,
        experiment_samples=experiment_samples,
        coverage=coverage,
    )
