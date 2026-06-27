"""Filtered-sample audit helpers for signal experiment reviews."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from config import DAY_LOOKBACK
from chanlun.backtest_execution import evaluate_forward_returns
from chanlun.backtest_metrics import summarize_return_samples
from chanlun.data_fetcher import fetch_daily_kline
from chanlun.historical_experiment_metrics import (
    should_drop_pick_for_experiment,
    supports_historical_return_metrics,
)
from scripts.backtest_recommendation_quality import iter_snapshot_picks

DEFAULT_TOP_WINNERS_LIMIT = 20
_ENTRY_MODE = "immediate_close"
_HORIZON = 5


def _as_list(value):
    return list(value) if value is not None else []


def _normalize_kline(kline: dict) -> Dict[str, list]:
    if kline is None:
        return {}

    dates = [str(d).split(" ")[0] for d in _as_list(kline.get("dates"))]
    opens = [float(v) for v in _as_list(kline.get("opens"))]
    closes = [float(v) for v in _as_list(kline.get("closes"))]
    highs = [float(v) for v in _as_list(kline.get("highs"))]
    lows = [float(v) for v in _as_list(kline.get("lows"))]

    if not (len(dates) == len(opens) == len(closes) == len(highs) == len(lows)):
        return {}
    if not dates:
        return {}

    return {
        "dates": dates,
        "opens": opens,
        "closes": closes,
        "highs": highs,
        "lows": lows,
    }


def _fetch_daily_kline_cached(code: str, cache: Dict[str, Optional[dict]]) -> Optional[dict]:
    if code in cache:
        return cache[code]

    try:
        result = fetch_daily_kline(code, count=DAY_LOOKBACK)
    except Exception:
        result = None

    cache[code] = result
    return result


def _distance_bucket(value) -> str:
    if value is None:
        return "unknown"
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return "unknown"

    if distance <= 3:
        return "0-3%"
    if distance <= 6:
        return "3-6%"
    if distance <= 10:
        return "6-10%"
    return ">10%"


def _pick_type(pick: dict) -> str:
    bbp = (pick or {}).get("best_buy_point") or {}
    return str(bbp.get("type") or pick.get("type") or "?")


def _pick_name(pick: dict) -> Optional[str]:
    return (pick or {}).get("name")


def _pick_distance(pick: dict):
    bbp = (pick or {}).get("best_buy_point") or {}
    return bbp.get("distance_from_reference_pct")


def _pick_confirmations(pick: dict) -> List[str]:
    bbp = (pick or {}).get("best_buy_point") or {}
    return list(_as_list(bbp.get("confirmations")))


def _confirmations_bucket(confirmations: List[str]) -> str:
    if not confirmations:
        return "<none>"
    return "+".join(sorted(str(item) for item in confirmations))


def _to_top_winner(item: dict) -> dict:
    return {
        "date": item.get("date"),
        "version": item.get("version"),
        "code": item.get("code"),
        "name": item.get("name"),
        "type": item.get("type"),
        "t3_close_pct": item.get("t3_close_pct"),
        "confirmations": item.get("confirmations"),
        "distance_from_reference_pct": item.get("distance_from_reference_pct"),
        "signal_tier": item.get("signal_tier"),
    }


def collect_filtered_samples(experiment_name: str) -> List[dict]:
    """Collect legacy-evaluable samples filtered by the experiment guard."""
    if not supports_historical_return_metrics(experiment_name):
        raise ValueError(f"unsupported experiment for filtered sample audit: {experiment_name}")

    kline_cache: Dict[str, Optional[dict]] = {}
    filtered_samples: List[dict] = []

    for snap_date, version, pick in iter_snapshot_picks():
        if not isinstance(pick, dict):
            continue
        code = pick.get("code")
        if not code:
            continue

        kline = _fetch_daily_kline_cached(code, kline_cache)
        normalized_kline = _normalize_kline(kline)
        if not normalized_kline:
            continue

        legacy_sample = evaluate_forward_returns(
            normalized_kline,
            snap_date,
            entry_mode=_ENTRY_MODE,
            horizon=_HORIZON,
        )
        if legacy_sample is None:
            continue

        if not should_drop_pick_for_experiment(experiment_name, pick):
            continue

        bbp_type = _pick_type(pick)
        distance = _pick_distance(pick)
        distance_bucket = _distance_bucket(distance)
        confirmations = _pick_confirmations(pick)
        filtered_samples.append(
            {
                "date": str(snap_date),
                "version": str(version),
                "code": code,
                "name": _pick_name(pick),
                "type": bbp_type,
                "distance_from_reference_pct": distance,
                "distance_bucket": distance_bucket,
                "confirmations": confirmations,
                "signal_tier": pick.get("signal_tier"),
                "return_sample": legacy_sample,
                "t3_close_pct": legacy_sample.get("t3_close_pct"),
            }
        )

    return filtered_samples


def _build_summary(samples: List[dict]) -> Dict[str, object]:
    return_summary = summarize_return_samples([s["return_sample"] for s in samples])
    summary = {"filtered": len(samples), "return_summary": return_summary}
    if return_summary is not None:
        summary.update(return_summary)
    return summary


def _top_winners(samples: List[dict], limit: int) -> List[dict]:
    sorted_samples = sorted(
        samples,
        key=lambda item: item.get("t3_close_pct") if item.get("t3_close_pct") is not None else float("-inf"),
        reverse=True,
    )
    return [_to_top_winner(item) for item in sorted_samples[: max(0, limit)]]


def _build_group_summaries(samples: List[dict], bucket_key) -> Dict[str, dict]:
    buckets = defaultdict(list)
    for sample in samples:
        buckets[bucket_key(sample)].append(sample["return_sample"])

    return {
        bucket: summarize_return_samples(return_samples)
        for bucket, return_samples in buckets.items()
    }


def build_filtered_sample_audit(experiment_name: str, top_winners: int = DEFAULT_TOP_WINNERS_LIMIT) -> Dict:
    """Build a filtered-sample audit payload for one experiment."""
    samples = collect_filtered_samples(experiment_name)

    return {
        "experiment": experiment_name,
        "summary": _build_summary(samples),
        "top_winners": _top_winners(samples, top_winners),
        "by_type": _build_group_summaries(samples, lambda sample: sample.get("type", "?")),
        "by_signal_tier": _build_group_summaries(samples, lambda sample: sample.get("signal_tier") or "?"),
        "by_confirmations": _build_group_summaries(
            samples,
            lambda sample: _confirmations_bucket(sample.get("confirmations") or []),
        ),
        "by_distance_bucket": _build_group_summaries(
            samples,
            lambda sample: sample.get("distance_bucket", "unknown"),
        ),
    }
