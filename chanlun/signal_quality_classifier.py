"""Signal quality classification helpers.

This module adds a downstream quality layer (A/B/C) without changing engine
signal detection internals.
"""

from __future__ import annotations

from copy import deepcopy
from statistics import pstdev
from typing import Any, Iterable, List, Mapping, Optional, Tuple

LOW_VOLATILITY_MAX = 0.10
HIGH_VOLATILITY_MIN = 0.18

_LOW_VOLATILITY_MAX = float(LOW_VOLATILITY_MAX)
_HIGH_VOLATILITY_MIN = float(HIGH_VOLATILITY_MIN)
_FUSION_PROFILE_STRICT = "fusion_strict"
_FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1 = "fusion_strict_startup_rescue_v1"
_DEFAULT_FUSION_PROFILE = _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
_FUSION_PROFILE_MID = "fusion_mid"
_FUSION_PROFILE_LOOSE = "fusion_loose"
_FUSION_PROFILE_MID_TREND = "fusion_mid_trend"
_FUSION_PROFILE_MID_VOLATILITY = "fusion_mid_volatility"
_FUSION_PROFILE_MID_STRUCTURE = "fusion_mid_structure"
_FUSION_PROFILE_LOOSE_TREND = "fusion_loose_trend"
_FUSION_PROFILE_LOOSE_VOLATILITY = "fusion_loose_volatility"


def list_quality_profiles() -> list[str]:
    """Return supported quality profiles."""
    return [
        _FUSION_PROFILE_STRICT,
        _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1,
        _FUSION_PROFILE_MID,
        _FUSION_PROFILE_LOOSE,
    ]


def list_quality_profile_variants(profile: str) -> list[str]:
    """Return concrete scan variants for a public quality profile."""
    normalized = _normalize_profile(profile)
    if normalized == _FUSION_PROFILE_MID:
        return [
            _FUSION_PROFILE_MID_TREND,
            _FUSION_PROFILE_MID_VOLATILITY,
            _FUSION_PROFILE_MID_STRUCTURE,
        ]
    if normalized == _FUSION_PROFILE_LOOSE:
        return [_FUSION_PROFILE_LOOSE_TREND, _FUSION_PROFILE_LOOSE_VOLATILITY]
    return [normalized]


def _normalize_profile(profile: str | None) -> str:
    if not profile:
        return _DEFAULT_FUSION_PROFILE
    if profile in {"strict", "fusion"}:
        return _FUSION_PROFILE_STRICT
    if profile in {
        _FUSION_PROFILE_STRICT,
        _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1,
        _FUSION_PROFILE_MID,
        _FUSION_PROFILE_LOOSE,
        _FUSION_PROFILE_MID_TREND,
        _FUSION_PROFILE_MID_VOLATILITY,
        _FUSION_PROFILE_MID_STRUCTURE,
        _FUSION_PROFILE_LOOSE_TREND,
        _FUSION_PROFILE_LOOSE_VOLATILITY,
    }:
        return str(profile)
    raise ValueError(f"unknown quality profile: {profile}")


def _build_signal_profile_config(profile: str) -> dict:
    normalized = _normalize_profile(profile)
    if normalized in {
        _FUSION_PROFILE_STRICT,
        _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1,
    }:
        return {
            "min_trend_strength": 2.0,
            "max_volatility": _LOW_VOLATILITY_MAX,
            "structure_mode": "strict",
        }
    if normalized in {_FUSION_PROFILE_MID, _FUSION_PROFILE_MID_TREND}:
        return {
            "min_trend_strength": 1.5,
            "max_volatility": _LOW_VOLATILITY_MAX,
            "structure_mode": "strict",
        }
    if normalized == _FUSION_PROFILE_MID_VOLATILITY:
        return {
            "min_trend_strength": 2.0,
            "max_volatility": _LOW_VOLATILITY_MAX * 1.15,
            "structure_mode": "strict",
        }
    if normalized == _FUSION_PROFILE_MID_STRUCTURE:
        return {
            "min_trend_strength": 2.0,
            "max_volatility": _LOW_VOLATILITY_MAX,
            "structure_mode": "relaxed",
        }
    if normalized in {_FUSION_PROFILE_LOOSE, _FUSION_PROFILE_LOOSE_TREND}:
        return {
            "min_trend_strength": 1.0,
            "max_volatility": _LOW_VOLATILITY_MAX,
            "structure_mode": "strict",
        }
    # A second loose upper-bound point that only relaxes volatility further.
    return {
        "min_trend_strength": 2.0,
        "max_volatility": _LOW_VOLATILITY_MAX * 1.30,
        "structure_mode": "strict",
    }


def _profile_has_pivot_or_strong_segment(pivot: Any, segment: Any) -> bool:
    if bool(pivot):
        return True
    if isinstance(segment, Mapping):
        signal_trend = _to_float(segment.get("trend_strength"))
        if signal_trend is not None and signal_trend >= 2:
            return True
    return False


def _profile_has_required_structure(pivot: Any, segment: Any, mode: str) -> bool:
    if mode == "strict":
        return bool(pivot) and bool(segment)
    return _profile_has_pivot_or_strong_segment(pivot, segment)


def _is_profile_a_candidate(context: dict, profile: str) -> bool:
    trend_strength = _to_float(context.get("trend_strength"))
    pivot = context.get("pivot")
    segment = context.get("segment")
    volatility = _to_float(context.get("volatility"))
    trend_type = context.get("trend_type")
    signal_type = str((context.get("signal_type") or context.get("type") or ""))
    market_env = context.get("market_env")

    cfg = _build_signal_profile_config(profile)
    is_choppy = _to_bool_choppy(trend_type)
    if is_choppy:
        return False

    if (
        profile == _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
        and trend_strength == 1.0
        and signal_type == "强势启动候选"
    ):
        return not _is_strong_market_env(market_env)

    if trend_strength is not None and trend_strength <= 0:
        return False

    if trend_strength is None:
        return False
    if trend_strength < cfg["min_trend_strength"]:
        return False

    if volatility is not None:
        if volatility > cfg["max_volatility"]:
            return False
        if volatility >= _HIGH_VOLATILITY_MIN:
            return False
    else:
        return False

    return _profile_has_required_structure(pivot, segment, cfg["structure_mode"])


def _to_float(value: Any) -> Optional[float]:
    """Coerce common numeric/string inputs into float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value == value and abs(value) != float("inf"):
            return float(value)
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # 中文强弱映射
        if value in {"弱", "低", "差", "差弱", "差强", "差-", "very_weak"}:
            return 0.0
        if value in {"中", "中等", "medium", "median"}:
            return 1.0
        if value in {"强", "高", "强烈", "high"}:
            return 2.0
        if value.upper() == "A":
            return 2.0
        if value.upper() == "B":
            return 1.0
        if value.upper() == "C":
            return 0.0
        if value.lower() == "strong":
            return 2.0
        if value.lower() in {"weak", "very weak"}:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_last_item(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    try:
        if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
            if len(value) == 0:
                return None
            return value[-1]
    except TypeError:
        return None
    return value


def _to_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _get_from_obj(obj: Any, field: str, default=None):
    if isinstance(obj, Mapping):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _to_bool_choppy(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    choppy_tokens = {"盘整", "震荡", "震荡整理", "range", "震荡区", "中枢震荡", "中枢震荡区间"}
    for token in choppy_tokens:
        if token in s:
            return True
    return False


def _get_sequence_value(values: Any, idx: int, default=None):
    if values is None:
        return default
    try:
        return list(values)[idx]
    except Exception:
        return default


def _build_volatility(closes: Any) -> Optional[float]:
    closes_list = _to_list(closes)
    if len(closes_list) < 3:
        return None

    nums = []
    for x in closes_list:
        fx = _to_float(x)
        if fx is None or fx <= 0:
            continue
        nums.append(fx)
    if len(nums) < 3:
        return None

    rets = []
    for i in range(1, len(nums)):
        p = nums[i - 1]
        c = nums[i]
        if p > 0:
            rets.append((c - p) / p)
    if len(rets) < 2:
        return None

    mean_abs = sum(abs(v) for v in rets) / len(rets)
    if mean_abs == 0:
        return 0.0

    return pstdev(rets)


def _build_segment_proxy(source: Any, signal: Mapping[str, Any]) -> Optional[dict]:
    """Build a lightweight segment proxy when snapshots did not persist segments."""
    idx = _to_float(signal.get("index"))
    if idx is None:
        idx = _to_float(signal.get("confirm_index"))
    if idx is None:
        return None

    idx = int(idx)
    highs = _to_list(_get_from_obj(source, "highs", None))
    lows = _to_list(_get_from_obj(source, "lows", None))
    closes = _to_list(_get_from_obj(source, "closes", None))
    n = max(len(highs), len(lows), len(closes))
    if n <= 0 or idx < 0:
        return None

    idx = min(idx, n - 1)
    start_idx = max(0, idx - 5)
    end_idx = idx

    window_highs = [_to_float(x) for x in highs[start_idx:end_idx + 1]]
    window_lows = [_to_float(x) for x in lows[start_idx:end_idx + 1]]
    window_closes = [_to_float(x) for x in closes[start_idx:end_idx + 1]]
    window_highs = [x for x in window_highs if x is not None]
    window_lows = [x for x in window_lows if x is not None]
    window_closes = [x for x in window_closes if x is not None]

    high = max(window_highs or window_closes or [None])
    low = min(window_lows or window_closes or [None])
    if high is None or low is None:
        return None

    return {
        "source": "price_window_proxy",
        "start_idx": start_idx,
        "end_idx": end_idx,
        "high": high,
        "low": low,
    }


def _build_pivot_proxy(signal: Mapping[str, Any]) -> Optional[dict]:
    """Build a persisted-snapshot structure anchor for confirmed startup signals."""
    if signal.get("type") != "强势启动候选":
        return None
    confirm_strength = _to_float(signal.get("sublevel_confirm_grade"))
    if confirm_strength is None or confirm_strength < 2:
        return None

    reference = _to_float(signal.get("reference_price"))
    current = _to_float(signal.get("current_price"))
    price = _to_float(signal.get("price"))
    anchor = reference or price or current
    if anchor is None or anchor <= 0:
        return None

    distance = _to_float(signal.get("distance_from_reference_pct"))
    if distance is not None and distance > 3:
        return None

    return {
        "source": "startup_reference_proxy",
        "ZD": anchor,
        "ZG": current or price or anchor,
    }


def build_signal_context(result_or_pick: Any, signal: Optional[Mapping[str, Any]]) -> dict:
    """Build context used by signal quality classification.

    `result_or_pick` may be a ChanResult-like object or a historical pick dict.
    """
    source = result_or_pick or {}

    closes = _get_from_obj(source, "closes", None)
    highs = _get_from_obj(source, "highs", None)
    lows = _get_from_obj(source, "lows", None)
    pivots = _get_from_obj(source, "pivots", None)
    segments = _get_from_obj(source, "segments", None)
    trend_type = _get_from_obj(source, "trend_type", "")
    trend_strength = _to_float(_get_from_obj(source, "trend_strength", None))
    if trend_strength is None:
        trend_strength = _to_float(_get_from_obj(source, "strength", None))

    signal_obj = signal or {}
    if not isinstance(signal_obj, Mapping):
        signal_obj = {}

    # Prefer explicit signal fields when present
    explicit_strength = _to_float(signal_obj.get("trend_strength"))
    explicit_strength_values = [
        explicit_strength,
        _to_float(signal_obj.get("sublevel_confirm_grade")),
        _to_float(signal_obj.get("daily_startup_grade")),
        _to_float(signal_obj.get("strength")),
    ]
    explicit_strength_values = [x for x in explicit_strength_values if x is not None]
    explicit_strength = max(explicit_strength_values) if explicit_strength_values else None
    if explicit_strength is None:
        explicit_strength = _to_float(signal_obj.get("signal_strength"))

    if explicit_strength is not None:
        trend_strength = explicit_strength

    if not trend_strength:
        signal_strength = signal_obj.get("strength") if signal_obj else None
        if signal_strength is not None:
            trend_strength = _to_float(signal_strength)

    explicit_pivot = signal_obj.get("pivot")
    explicit_segment = signal_obj.get("segment")
    if explicit_pivot is not None:
        pivot = deepcopy(explicit_pivot)
    else:
        pivot = _extract_last_item(pivots)
    if not pivot:
        pivot = _build_pivot_proxy(signal_obj)
    if explicit_segment is not None:
        segment = deepcopy(explicit_segment)
    else:
        segment = _extract_last_item(segments)
    if not segment:
        segment = _build_segment_proxy(source, signal_obj)

    explicit_volatility = _to_float(signal_obj.get("volatility"))
    if explicit_volatility is None:
        explicit_volatility = _to_float(signal_obj.get("volatility_ratio"))

    if explicit_volatility is None:
        explicit_volatility = _build_volatility(closes)

    market_env = (
        signal_obj.get("market_env")
        or signal_obj.get("market_regime")
        or signal_obj.get("market_trend")
        or _get_from_obj(source, "market_env", None)
        or _get_from_obj(source, "market_regime", None)
        or _get_from_obj(source, "market_trend", None)
    )

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "pivots": pivots,
        "segments": segments,
        "pivot": pivot,
        "segment": segment,
        "trend_type": trend_type,
        "trend_strength": trend_strength,
        "strength": trend_strength,
        "volatility": explicit_volatility,
        "market_env": market_env,
        "signal_index": signal_obj.get("index") if isinstance(signal_obj, Mapping) else None,
    }


def _is_strong_market_env(value: Any) -> bool:
    return str(value or "").strip().lower() == "strong"


def _context_for_signal(signal: Any) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(signal, Mapping):
        return {}, {}
    context = signal.get("context")
    if not isinstance(context, Mapping):
        context = build_signal_context(signal, signal)
    return signal, context


def _is_startup_rescue_candidate(
    context: Mapping[str, Any],
    signal: Mapping[str, Any],
    profile: str,
) -> bool:
    signal_type = str(signal.get("type", context.get("type", "")))
    market_env = (
        context.get("market_env")
        or signal.get("market_env")
        or signal.get("market_regime")
        or signal.get("market_trend")
    )
    trend_strength = _to_float(context.get("trend_strength"))
    trend_type = context.get("trend_type")
    return (
        profile == _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
        and trend_strength == 1.0
        and signal_type == "强势启动候选"
        and not _is_strong_market_env(market_env)
        and not _to_bool_choppy(trend_type)
    )


def classify_signal(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> str:
    """Classify signal quality: A (trade), B (observe), C (filtered)."""
    if not isinstance(signal, Mapping):
        return "B"

    context = signal.get("context")
    if not isinstance(context, Mapping):
        context = build_signal_context(signal, signal)
    normalized_profile = _normalize_profile(profile)

    if _is_profile_a_candidate(
        {
            "trend_strength": context.get("trend_strength"),
            "pivot": context.get("pivot"),
            "segment": context.get("segment"),
            "volatility": context.get("volatility"),
            "trend_type": context.get("trend_type"),
            "type": context.get("type"),
            "signal_type": signal.get("type", context.get("type", "")),
            "market_env": (
                context.get("market_env")
                or signal.get("market_env")
                or signal.get("market_regime")
                or signal.get("market_trend")
            ),
        },
        normalized_profile,
    ):
        return "A"

    trend_strength = _to_float(context.get("trend_strength"))
    pivot = context.get("pivot")
    segment = context.get("segment")
    volatility = _to_float(context.get("volatility"))
    trend_type = context.get("trend_type")
    signal_type = str(signal.get("type", context.get("type", "")))

    # Explicitly blocked / known-candidate types can still be ranked
    # by strength and market structure, with choppy and weak ones demoted.
    is_choppy = _to_bool_choppy(trend_type)
    has_pivot = bool(pivot)
    has_segment = bool(segment)
    structure_incomplete = not has_pivot or not has_segment

    if trend_strength is not None:
        if trend_strength <= 0:
            return "C"

    if is_choppy:
        return "C"

    cfg = _build_signal_profile_config(normalized_profile)
    if not structure_incomplete:
        if trend_strength is not None and trend_strength >= cfg["min_trend_strength"] and volatility is not None:
            if volatility >= _HIGH_VOLATILITY_MIN:
                return "C" if signal_type == "震荡区" else "B"

    if trend_strength == 1 or trend_strength < cfg["min_trend_strength"]:
        return "B"

    if structure_incomplete:
        if volatility is not None and volatility >= _HIGH_VOLATILITY_MIN:
            return "C"
        if signal_type in {"三买", "二买", "一买", "底背驰候选", "强势启动候选"}:
            return "B"

    if trend_strength is None:
        return "B"

    return "B"


def explain_signal_rejection(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> list[str]:
    """Return reasons why a signal is not A-class under a quality profile."""
    if not isinstance(signal, Mapping):
        return ["invalid_signal"]

    context = signal.get("context")
    if not isinstance(context, Mapping):
        context = build_signal_context(signal, signal)

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) == "A":
        return []

    trend_strength = _to_float(context.get("trend_strength"))
    pivot = context.get("pivot")
    segment = context.get("segment")
    volatility = _to_float(context.get("volatility"))
    trend_type = context.get("trend_type")
    market_env = (
        context.get("market_env")
        or signal.get("market_env")
        or signal.get("market_regime")
        or signal.get("market_trend")
    )
    cfg = _build_signal_profile_config(normalized_profile)
    reasons = []

    if _to_bool_choppy(trend_type):
        reasons.append("choppy_trend")

    if trend_strength is None:
        reasons.append("missing_trend_strength")
    elif trend_strength <= 0:
        reasons.append("trend_strength_lte_0")
    elif trend_strength < cfg["min_trend_strength"]:
        reasons.append("trend_strength_below_min")

    if volatility is None:
        reasons.append("missing_volatility")
    else:
        if volatility > cfg["max_volatility"]:
            reasons.append("volatility_above_max")
        if volatility >= _HIGH_VOLATILITY_MIN:
            reasons.append("high_volatility")

    structure_mode = cfg["structure_mode"]
    if structure_mode == "strict":
        if not pivot:
            reasons.append("missing_pivot")
        if not segment:
            reasons.append("missing_segment")
    elif not _profile_has_required_structure(pivot, segment, structure_mode):
        reasons.append("missing_pivot_or_strong_segment")

    signal_type = str(signal.get("type", context.get("type", "")))
    if (
        normalized_profile == _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
        and trend_strength == 1.0
        and signal_type == "强势启动候选"
        and _is_strong_market_env(market_env)
    ):
        reasons.append("strong_market_rescue_guard")

    return reasons or ["not_a"]


def explain_signal_tier(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> List[str]:
    if not isinstance(signal, Mapping):
        return []

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) != "A":
        return []

    signal_obj, context = _context_for_signal(signal)
    trend_strength = _to_float(context.get("trend_strength"))
    volatility = _to_float(context.get("volatility"))
    pivot = context.get("pivot")
    segment = context.get("segment")
    trend_type = context.get("trend_type")

    reasons: List[str] = []
    if _is_startup_rescue_candidate(context, signal_obj, normalized_profile):
        reasons.append("startup_rescue")

    if volatility is not None and _LOW_VOLATILITY_MAX >= volatility > 0.08:
        reasons.append("volatility_near_limit")

    if reasons:
        return reasons

    if (
        trend_strength is not None
        and trend_strength >= 2.5
        and volatility is not None
        and volatility <= _LOW_VOLATILITY_MAX
        and bool(pivot)
        and bool(segment)
        and not _to_bool_choppy(trend_type)
    ):
        return ["strong_trend", "low_volatility", "complete_structure"]

    return ["standard_a"]


def explain_signal_expected_horizon(
    signal: Any,
    profile: str = _DEFAULT_FUSION_PROFILE,
) -> List[str]:
    if not isinstance(signal, Mapping):
        return []

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) != "A":
        return []

    tier = signal.get("quality_tier")
    if tier not in {"A+", "A", "A-"}:
        tier = classify_signal_tier(signal, profile=normalized_profile)

    if tier == "A+":
        return ["high_confidence_hold"]
    if tier == "A-":
        return ["fast_confirm_or_exit"]
    if tier == "A":
        return ["standard_swing"]
    return ["default_swing"]


def classify_signal_tier(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> Optional[str]:
    reasons = explain_signal_tier(signal, profile=profile)
    if not reasons:
        return None
    if "startup_rescue" in reasons or "volatility_near_limit" in reasons:
        return "A-"
    if reasons == ["strong_trend", "low_volatility", "complete_structure"]:
        return "A+"
    return "A"


def classify_signal_expected_horizon(
    signal: Any,
    profile: str = _DEFAULT_FUSION_PROFILE,
) -> Optional[str]:
    reasons = explain_signal_expected_horizon(signal, profile=profile)
    if not reasons:
        return None
    if "high_confidence_hold" in reasons:
        return "T+5"
    if "fast_confirm_or_exit" in reasons:
        return "T+1"
    return "T+3"


def tag_signal_quality(signal: Mapping[str, Any], profile: str = _DEFAULT_FUSION_PROFILE) -> dict:
    """Return a copy of signal with additive `category` field."""
    if not isinstance(signal, Mapping):
        return signal
    out = dict(signal)
    if not isinstance(out.get("context"), Mapping):
        out["context"] = build_signal_context(signal, signal)
    else:
        out["context"] = dict(out["context"])
    out["category"] = classify_signal(out, profile=_normalize_profile(profile))
    if out["category"] == "A":
        tier = classify_signal_tier(out, profile=_normalize_profile(profile))
        if tier:
            out["quality_tier"] = tier
            out["quality_tier_reasons"] = explain_signal_tier(
                out,
                profile=_normalize_profile(profile),
            )
        else:
            out.pop("quality_tier", None)
            out.pop("quality_tier_reasons", None)
        horizon = classify_signal_expected_horizon(
            out,
            profile=_normalize_profile(profile),
        )
        if horizon:
            out["expected_horizon"] = horizon
            out["expected_horizon_reasons"] = explain_signal_expected_horizon(
                out,
                profile=_normalize_profile(profile),
            )
        else:
            out.pop("expected_horizon", None)
            out.pop("expected_horizon_reasons", None)
    else:
        out.pop("quality_tier", None)
        out.pop("quality_tier_reasons", None)
        out.pop("expected_horizon", None)
        out.pop("expected_horizon_reasons", None)
    return out


def tag_signal_quality_in_place(
    signal: Mapping[str, Any],
    profile: str = _DEFAULT_FUSION_PROFILE,
) -> Mapping[str, Any]:
    """Mutate and return signal with additive `category` field."""
    if not isinstance(signal, dict):
        return signal

    if not isinstance(signal.get("context"), Mapping):
        signal["context"] = build_signal_context(signal, signal)
    signal["category"] = classify_signal(signal, profile=_normalize_profile(profile))
    if signal["category"] == "A":
        tier = classify_signal_tier(signal, profile=_normalize_profile(profile))
        if tier:
            signal["quality_tier"] = tier
            signal["quality_tier_reasons"] = explain_signal_tier(
                signal,
                profile=_normalize_profile(profile),
            )
        else:
            signal.pop("quality_tier", None)
            signal.pop("quality_tier_reasons", None)
        horizon = classify_signal_expected_horizon(
            signal,
            profile=_normalize_profile(profile),
        )
        if horizon:
            signal["expected_horizon"] = horizon
            signal["expected_horizon_reasons"] = explain_signal_expected_horizon(
                signal,
                profile=_normalize_profile(profile),
            )
        else:
            signal.pop("expected_horizon", None)
            signal.pop("expected_horizon_reasons", None)
    else:
        signal.pop("quality_tier", None)
        signal.pop("quality_tier_reasons", None)
        signal.pop("expected_horizon", None)
        signal.pop("expected_horizon_reasons", None)
    return signal


def tag_signal_quality_many(
    signals: Iterable[Mapping[str, Any]],
    in_place: bool = False,
    profile: str = _DEFAULT_FUSION_PROFILE,
):
    """Tag a collection of signals and return list of tagged signals."""
    out = []
    if signals is None:
        return out

    for signal in signals:
        if in_place:
            if isinstance(signal, dict):
                out.append(tag_signal_quality_in_place(signal, profile=profile))
            else:
                out.append(tag_signal_quality(signal, profile=profile))
        else:
            out.append(tag_signal_quality(signal, profile=profile))
    return out


def filter_executable_signals(
    signals: Iterable[Mapping[str, Any]],
    profile: str = _DEFAULT_FUSION_PROFILE,
):
    """Keep only A-class signals for execution intent."""
    if signals is None:
        return []

    actionable = []
    for signal in signals:
        if not isinstance(signal, Mapping):
            continue
        sig = tag_signal_quality(signal, profile=profile)
        if sig.get("category") == "A":
            actionable.append(sig)
    return actionable
