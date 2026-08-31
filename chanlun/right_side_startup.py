"""Pure off/shadow/active orchestration for the right-side startup channel."""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, Mapping, Optional, Sequence

import config

from .market_sentiment import classify_price_limit

from .trend_continuation import (
    build_trend_continuation_pool,
    normalize_trend_candidate,
    upgrade_trend_continuation_with_30min,
)


POLICY_VERSION = "right-side-startup-v1"
MAX_PUBLIC_CANDIDATES = 3
VALID_MODES = frozenset({"off", "shadow", "active"})


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    output = []
    for raw in values:
        text = str(raw or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def build_right_side_startup_evidence(
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build the compact public evidence label without another action/score."""

    row = dict(candidate or {})
    if str(row.get("source_channel") or "") != "right_side_startup":
        return {}
    best = row.get("best_buy_point")
    best = dict(best) if isinstance(best, Mapping) else {}
    reference = row.get("reference_price")
    if reference is None:
        reference = best.get("reference_price", best.get("price"))
    try:
        reference = round(float(reference), 2)
    except (TypeError, ValueError):
        reference = None
    if reference is not None and (not math.isfinite(reference) or reference <= 0):
        reference = None

    why = _text_list(row.get("trend_signals"))
    if not why:
        why = _text_list(best.get("reason"))
    confirmations = _text_list(row.get("confirmations"))
    if not confirmations:
        confirmations = _text_list(best.get("confirmations"))
    if not confirmations:
        confirmations = _text_list(best.get("confirmed_by"))
    invalidation = _text_list(row.get("cancel_conditions"))
    if not invalidation and reference is not None:
        invalidation = ["跌破右侧突破参考位 {:.2f}".format(reference)]

    evidence: Dict[str, Any] = {"source_label": "右侧启动"}
    if reference is not None:
        evidence["reference_price"] = reference
    if why:
        evidence["why"] = why[:3]
    if confirmations:
        evidence["confirmations"] = confirmations[:3]
    if invalidation:
        evidence["invalidation"] = invalidation[:3]
    return evidence


def _candidate_code(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("code") or "").strip()
    return str(getattr(item, "code", "") or "").strip()


def _price_limit_state(item: Any) -> str:
    closes = item.get("closes") if isinstance(item, Mapping) else getattr(
        item, "closes", None
    )
    if closes is None or len(closes) < 2:
        return "invalid"
    name = item.get("name") if isinstance(item, Mapping) else getattr(
        item, "name", ""
    )
    return classify_price_limit({
        "code": _candidate_code(item),
        "name": str(name or ""),
        "prev_close": closes[-2],
        "close": closes[-1],
    })


def select_classic_startup_inputs(
    chan_results: Sequence[Any],
    pure_pool: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Keep classic startup on common formal upstream plus limit-up watches."""

    rows = list(chan_results or [])
    upstream_codes = {
        _candidate_code(row) for row in (pure_pool or [])
        if _candidate_code(row)
    }
    kept = [row for row in rows if _candidate_code(row) in upstream_codes]
    kept_codes = {_candidate_code(row) for row in kept}
    limit_up_rows = [
        row for row in rows
        if _candidate_code(row)
        and _candidate_code(row) not in kept_codes
        and _price_limit_state(row) == "limit_up"
    ]
    selected = kept + limit_up_rows
    selected_codes = {_candidate_code(row) for row in selected}
    return {
        "rows": selected,
        "diagnostics": {
            "upstream_pool": "picks_pure",
            "upstream_count": len(upstream_codes),
            "input_count": len(rows),
            "kept_count": len(selected),
            "excluded_count": len(rows) - len(selected),
            "excluded_codes": sorted({
                _candidate_code(row) for row in rows
                if _candidate_code(row) not in selected_codes
            }),
            "limit_up_observation_count": len(limit_up_rows),
            "limit_up_observation_codes": sorted({
                _candidate_code(row) for row in limit_up_rows
            }),
        },
    }


def resolve_right_side_startup_mode(value: Optional[str]) -> str:
    selected = config.RIGHT_SIDE_STARTUP_MODE if value is None else value
    selected = str(selected or "").strip().lower()
    if selected not in VALID_MODES:
        raise ValueError("right-side startup mode must be off, shadow or active")
    return selected


def _score(value: Mapping[str, Any]) -> Optional[float]:
    raw = value.get("score")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        result = float(raw)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def apply_right_side_startup_mode(
    candidates: Sequence[Mapping[str, Any]],
    *,
    existing_candidates: Sequence[Mapping[str, Any]] = (),
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    selected_mode = resolve_right_side_startup_mode(mode)
    frozen_candidates = [copy.deepcopy(dict(row)) for row in candidates or []]
    frozen_existing = [
        copy.deepcopy(dict(row)) for row in existing_candidates or []
    ]
    scored = []
    missing_score_codes = []
    for index, row in enumerate(frozen_candidates):
        unified_score = _score(row)
        if unified_score is None:
            missing_score_codes.append(str(row.get("code") or ""))
            continue
        scored.append((unified_score, index, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    published = []
    if selected_mode == "active":
        published = [
            copy.deepcopy(item[2])
            for item in scored[:MAX_PUBLIC_CANDIDATES]
        ]
    return {
        "mode": selected_mode,
        "policy_version": POLICY_VERSION,
        "candidates": frozen_candidates,
        "published": published,
        "existing_candidates": frozen_existing,
        "diagnostics": {
            "candidate_count": len(frozen_candidates),
            "published_count": len(published),
            "missing_score_codes": missing_score_codes,
            "max_public_candidates": MAX_PUBLIC_CANDIDATES,
        },
    }


def build_right_side_startup_state(
    chan_results: Sequence[Any],
    chan_results_30min: Sequence[Any],
    *,
    sector_stocks: Optional[Mapping[str, Mapping[str, Any]]] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    selected_mode = resolve_right_side_startup_mode(mode)
    if selected_mode == "off":
        return {
            "mode": selected_mode,
            "policy_version": POLICY_VERSION,
            "candidates": [],
            "published": [],
            "watchlist": [],
            "diagnostics": {
                "input_count": 0,
                "daily_seed_count": 0,
                "min30_requested": 0,
                "min30_verified": 0,
                "candidate_count": 0,
                "watch_count": 0,
                "rejected_count": 0,
            },
        }

    seeds, daily_watch, daily_diagnostics = build_trend_continuation_pool(
        list(chan_results or []), sector_stocks or {}
    )
    candidates, min30_watch, upgrade_diagnostics = (
        upgrade_trend_continuation_with_30min(
            seeds, list(chan_results_30min or [])
        )
    )
    normalized = [normalize_trend_candidate(row) for row in candidates]
    mode_state = apply_right_side_startup_mode(normalized, mode=selected_mode)
    watchlist = [
        copy.deepcopy(dict(row))
        for row in list(daily_watch) + list(min30_watch)
    ]
    diagnostics = {
        "input_count": len(chan_results or []),
        "daily_seed_count": len(seeds),
        "min30_requested": len(seeds),
        "min30_verified": len(chan_results_30min or []),
        "candidate_count": len(normalized),
        "watch_count": len(watchlist),
        "rejected_count": max(
            0, len(chan_results or []) - len(seeds) - len(daily_watch)
        ),
        "daily": copy.deepcopy(daily_diagnostics),
        "min30": copy.deepcopy(upgrade_diagnostics),
        "mode": copy.deepcopy(mode_state["diagnostics"]),
    }
    return {
        "mode": selected_mode,
        "policy_version": POLICY_VERSION,
        "candidates": normalized,
        "published": mode_state["published"],
        "watchlist": watchlist,
        "diagnostics": diagnostics,
    }
