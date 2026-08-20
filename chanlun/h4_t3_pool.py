"""Production H4 T+3 pool built from the frozen K30 tail-safe model."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np


STRATEGY_VERSION = "h4_t3_k30_tail_safe_v1"
MODEL_PATH = Path(__file__).resolve().parent / "data" / "h4_t3_model_v1.json"
NEIGHBOR_COUNT = 30
TAIL_LOSS_MAX = 0.10
Q10_MIN = -5.0

_NUMERIC_FEATURES = (
    "score", "change_pct", "volume_ratio", "log_amount", "log_money20",
    "log_market_cap", "log_float_market_cap", "log_circulating_market_cap",
    "position_absolute_percentile", "position_distance_pct",
    "decision_total_score", "decision_sentiment_score",
    "decision_structure_score", "decision_position_score", "health_score",
    "health_vs_ma20", "health_vs_ma50", "health_vs_ma100", "health_vs_ma200",
    "best_change_pct", "best_volume_ratio", "best_signal_age_days",
    "best_confirm_age_days", "best_startup_age_days", "best_confirmation_count",
    "best_startup_signal_count", "decision_risk_reason_count",
    "health_risk_flag_count", "health_positive_flag_count", "buy_point_count",
    "buy_point_30min_count", "blocked_buy_point_count",
    "reference_buy_point_count", "pivot_count", "trailing_target_count",
)
_CATEGORICAL_FEATURES = (
    ("decision", ("reject", "observe", "recommend")),
    ("source", ("low_position", "trend_continuation")),
    ("category", ("A", "B")),
    ("regime", ("strong", "weak", "neutral")),
    ("health_alignment", ("bullish", "repairing", "neutral", "broken")),
    ("health_extension", ("normal", "warm", "hot")),
    ("health_fomo", ("low", "medium", "high")),
    ("health_pullback", ("healthy", "broken_down")),
    ("health_trend", ("uptrend", "neutral", "broken")),
    ("health_quality", ("sufficient", "insufficient_200")),
    ("best_strength", ("强", "中", "弱")),
)
_BOOLEAN_FEATURES = ("ma_bullish", "fusion_passed", "best_present")
WIDE_FEATURE_DIMENSION = (
    len(_NUMERIC_FEATURES) * 2
    + sum(len(values) + 1 for _, values in _CATEGORICAL_FEATURES)
    + len(_BOOLEAN_FEATURES) * 3
)
FEATURE_DIMENSION = WIDE_FEATURE_DIMENSION + 28


class H4T3PoolError(ValueError):
    """Raised when H4 cannot produce a truthful daily result."""


def _mapping(value):
    return value if isinstance(value, Mapping) else None


def _features(row):
    nested = _mapping(row.get("features")) if isinstance(row, Mapping) else None
    return nested if nested is not None else row


def _finite(value):
    if value is None or isinstance(value, (bool, np.bool_, str, bytes, bytearray)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _number(value, log1p=False):
    number = _finite(value)
    if number is None:
        return 0.0, 1.0
    if log1p:
        number = math.log1p(max(number, 0.0))
    return float(number), 0.0


def _list(value, name):
    if value is None:
        return []
    if not isinstance(value, list):
        raise H4T3PoolError(name + " is not a list")
    return value


def _pivot_count(value):
    if value is None:
        return 0.0, 1.0
    if isinstance(value, list):
        return float(len(value)), 0.0
    if isinstance(value, Mapping):
        if not value:
            return 0.0, 0.0
        count = _finite(value.get("count"))
        if count is None or count < 0.0:
            raise H4T3PoolError("pivots summary count is invalid")
        return float(count), 0.0
    raise H4T3PoolError("pivots is neither a summary nor a list")


def _category(values, value, names):
    matched = False
    for name in names:
        flag = value == name
        values.append(float(flag))
        matched = matched or flag
    values.append(float(not matched))


def _boolean(values, value):
    values.extend((float(value is True), float(value is False), float(value is None)))


def _derived_average_amount(features):
    closes = features.get("closes")
    volumes = features.get("volumes")
    if not isinstance(closes, list) or not isinstance(volumes, list):
        return None
    size = min(len(closes), len(volumes), 5)
    if size <= 0:
        return None
    values = []
    for close, volume in zip(closes[-size:], volumes[-size:]):
        close_value = _finite(close)
        volume_value = _finite(volume)
        if close_value is None or volume_value is None:
            return None
        values.append(close_value * volume_value * 100.0)
    return sum(values) / len(values)


def _wide_feature_vector(row):
    if not isinstance(row, Mapping):
        raise H4T3PoolError("candidate is invalid")
    features = _features(row)
    if not isinstance(features, Mapping):
        raise H4T3PoolError("candidate features are missing")
    decision = _mapping(features.get("decision_engine_v1")) or {}
    sentiment = _mapping(decision.get("sentiment")) or {}
    structure = _mapping(decision.get("structure")) or {}
    position = _mapping(decision.get("position")) or {}
    health = _mapping(features.get("gf_dma_health")) or {}
    distance = _mapping(health.get("distance_pct")) or {}
    best = _mapping(features.get("best_buy_point"))
    best_value = best or {}
    admission = _mapping(features.get("fusion_admission")) or {}
    amount = features.get("amount")
    if _finite(amount) is None:
        amount = _derived_average_amount(features)
    volume_ratio = features.get("volume_ratio")
    if _finite(volume_ratio) is None:
        volume_ratio = best_value.get("volume_ratio")

    numeric_values = (
        _number(features.get("score")), _number(features.get("change_pct")),
        _number(volume_ratio), _number(amount, log1p=True),
        _number(features.get("money20"), log1p=True),
        _number(features.get("market_cap"), log1p=True),
        _number(features.get("float_market_cap"), log1p=True),
        _number(features.get("circulating_market_cap"), log1p=True),
        _number(features.get("position_absolute_percentile")),
        _number(features.get("position_distance_pct")),
        _number(decision.get("total_score")), _number(sentiment.get("score")),
        _number(structure.get("score")), _number(position.get("score")),
        _number(health.get("score")), _number(distance.get("vs_ma20")),
        _number(distance.get("vs_ma50")), _number(distance.get("vs_ma100")),
        _number(distance.get("vs_ma200")), _number(best_value.get("change_pct")),
        _number(best_value.get("volume_ratio")),
        _number(best_value.get("signal_age_days")),
        _number(best_value.get("confirm_age_days")),
        _number(best_value.get("startup_age_days")),
        (float(len(_list(best_value.get("confirmations"), "confirmations"))), 0.0),
        (float(len(_list(best_value.get("startup_signals"), "startup_signals"))), 0.0),
        (float(len(_list(decision.get("risk_reasons"), "risk_reasons"))), 0.0),
        (float(len(_list(health.get("risk_flags"), "risk_flags"))), 0.0),
        (float(len(_list(health.get("positive_flags"), "positive_flags"))), 0.0),
        (float(len(_list(features.get("buy_points"), "buy_points"))), 0.0),
        (float(len(_list(features.get("buy_points_30min"), "buy_points_30min"))), 0.0),
        (float(len(_list(features.get("blocked_buy_points"), "blocked_buy_points"))), 0.0),
        (float(len(_list(features.get("reference_buy_points"), "reference_buy_points"))), 0.0),
        _pivot_count(features.get("pivots")),
        (float(len(_list(features.get("trailing_targets"), "trailing_targets"))), 0.0),
    )
    values = [item for pair in numeric_values for item in pair]
    categorical_values = (
        decision.get("decision_code"), features.get("source_channel"),
        features.get("category"), features.get("market_regime"),
        health.get("alignment"), health.get("extension_level"),
        health.get("fomo_risk"), health.get("pullback_health"),
        health.get("trend_stage"), health.get("data_quality"),
        best_value.get("strength"),
    )
    for value, (_, names) in zip(categorical_values, _CATEGORICAL_FEATURES):
        _category(values, value, names)
    _boolean(values, features.get("ma_bullish"))
    _boolean(values, admission.get("passed"))
    _boolean(values, best is not None)
    vector = np.asarray(values, dtype=float)
    if vector.shape != (WIDE_FEATURE_DIMENSION,) or not np.isfinite(vector).all():
        raise H4T3PoolError("wide feature vector is invalid")
    return vector


def build_tail_feature_vector(row):
    base = _wide_feature_vector(row)
    features = _features(row)
    health = _mapping(features.get("gf_dma_health")) or {}
    distance = _mapping(health.get("distance_pct")) or {}
    best = _mapping(features.get("best_buy_point")) or {}
    position = _mapping(features.get("decision_engine_v1")) or {}
    position = _mapping(position.get("position")) or {}
    change, change_missing = _number(best.get("change_pct", features.get("change_pct")))
    volume, volume_missing = _number(best.get("volume_ratio", features.get("volume_ratio")))
    vs20, vs20_missing = _number(distance.get("vs_ma20"))
    vs50, vs50_missing = _number(distance.get("vs_ma50"))
    vs100, vs100_missing = _number(distance.get("vs_ma100"))
    pos, pos_missing = _number(features.get("position_absolute_percentile", position.get("score")))
    pos_distance, pos_distance_missing = _number(features.get("position_distance_pct"))
    risk_flags = health.get("risk_flags")
    positive_flags = health.get("positive_flags")
    if risk_flags is not None and not isinstance(risk_flags, list):
        raise H4T3PoolError("risk_flags is invalid")
    if positive_flags is not None and not isinstance(positive_flags, list):
        raise H4T3PoolError("positive_flags is invalid")
    risk_count = float(len(risk_flags or []))
    positive_count = float(len(positive_flags or []))
    interactions = np.asarray((
        vs20 * volume, vs50 * volume, vs100 * volume,
        vs20 * change, vs50 * change, vs100 * change,
        change * volume, change * change, volume * volume,
        pos * change, pos * volume, pos_distance * change,
        pos_distance * volume, pos * pos_distance,
        risk_count * max(-change, 0.0), risk_count * max(volume, 0.0),
        positive_count * max(change, 0.0), positive_count * max(volume, 0.0),
        change_missing, volume_missing, vs20_missing, vs50_missing,
        vs100_missing, pos_missing, pos_distance_missing,
        float(health.get("alignment") == "bullish") * max(change, 0.0),
        float(health.get("extension_level") == "overheated") * max(volume, 0.0),
        float(health.get("fomo_risk") == "high") * max(-change, 0.0),
    ), dtype=float)
    vector = np.concatenate((base, interactions))
    if vector.shape != (FEATURE_DIMENSION,) or not np.isfinite(vector).all():
        raise H4T3PoolError("tail feature vector is invalid")
    return vector


def is_continuation_microstate(row):
    if not isinstance(row, Mapping):
        return False
    features = _features(row)
    health = _mapping(features.get("gf_dma_health")) or {}
    best = _mapping(features.get("best_buy_point")) or {}
    return bool(
        features.get("source_channel") == "trend_continuation"
        and health.get("alignment") == "bullish"
        and health.get("extension_level") == "overheated"
        and best.get("strength") == "强"
        and health.get("fomo_risk") == "medium"
    )


def _canonical_date(value, name):
    if not isinstance(value, str):
        raise H4T3PoolError(name + " is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise H4T3PoolError(name + " is invalid") from exc
    if parsed.isoformat() != value:
        raise H4T3PoolError(name + " is invalid")
    return value


def load_model(model_path=None):
    path = Path(model_path or MODEL_PATH)
    try:
        with path.open("r", encoding="utf-8") as handle:
            model = json.load(handle)
    except (OSError, ValueError) as exc:
        raise H4T3PoolError("H4 production model is unavailable") from exc
    rows = model.get("training_rows") if isinstance(model, Mapping) else None
    if (
        model.get("artifact_type") != "h4_t3_production_model"
        or model.get("schema_version") != 1
        or model.get("strategy_version") != STRATEGY_VERSION
        or model.get("feature_dimension") != FEATURE_DIMENSION
        or model.get("neighbor_count") != NEIGHBOR_COUNT
        or not isinstance(rows, list)
        or not rows
    ):
        raise H4T3PoolError("H4 production model contract is invalid")
    for row in rows:
        vector = row.get("vector") if isinstance(row, Mapping) else None
        if not isinstance(vector, list) or len(vector) != FEATURE_DIMENSION:
            raise H4T3PoolError("H4 production model row is invalid")
        if not all(_finite(value) is not None for value in vector):
            raise H4T3PoolError("H4 production model vector is invalid")
        _canonical_date(row.get("trade_date"), "model trade_date")
        _canonical_date(row.get("exit_date"), "model exit_date")
        if _finite(row.get("return_pct")) is None:
            raise H4T3PoolError("H4 production model return is invalid")
    return model


def _date_equal_standardize(matrix, dates):
    counts = Counter(str(value) for value in dates)
    weights = np.asarray([1.0 / counts[str(value)] for value in dates], dtype=float)
    mean = np.average(matrix, axis=0, weights=weights)
    variance = np.average((matrix - mean) ** 2, axis=0, weights=weights)
    scale = np.sqrt(np.maximum(variance, 0.0))
    scale = np.where(scale > 1e-12, scale, 1.0)
    return mean, scale, np.clip((matrix - mean) / scale, -5.0, 5.0)


def _neighbor_weights(chosen, rows):
    by_date = defaultdict(list)
    for distance, index in chosen:
        by_date[str(rows[index]["trade_date"])].append((distance, index))
    date_mass = 1.0 / float(len(by_date))
    output = {}
    for values in by_date.values():
        zeros = [index for distance, index in values if distance <= 1e-12]
        if zeros:
            fractions = {index: 1.0 / len(zeros) for index in zeros}
        else:
            inverse = {index: 1.0 / max(distance, 1e-12) for distance, index in values}
            denominator = sum(inverse.values())
            fractions = {index: value / denominator for index, value in inverse.items()}
        for index, fraction in fractions.items():
            output[index] = date_mass * fraction
    return output


def _weighted_quantile(values, weights, quantile):
    order = sorted(range(len(values)), key=lambda index: (float(values[index]), index))
    cumulative = 0.0
    for index in order:
        cumulative += float(weights[index])
        if cumulative >= quantile:
            return float(values[index])
    return float(values[order[-1]])


def _fit_predictor(rows, current_date):
    mature = [
        row for row in rows
        if str(row["trade_date"]) < current_date and str(row["exit_date"]) <= current_date
    ]
    if not mature:
        raise H4T3PoolError("H4 production model has no mature training rows")
    matrix = np.vstack([np.asarray(row["vector"], dtype=float) for row in mature])
    mean, scale, standardized = _date_equal_standardize(
        matrix, [str(row["trade_date"]) for row in mature]
    )

    def predict(candidate):
        query = np.clip((build_tail_feature_vector(candidate) - mean) / scale, -5.0, 5.0)
        distances = np.sqrt(np.sum((standardized - query) ** 2, axis=1))
        ordered = sorted(
            ((float(distance), index) for index, distance in enumerate(distances)),
            key=lambda item: (
                item[0], str(mature[item[1]]["trade_date"]),
                str(mature[item[1]]["code"]), int(mature[item[1]]["record_index"]),
            ),
        )[: min(NEIGHBOR_COUNT, len(mature))]
        weights_by_index = _neighbor_weights(ordered, mature)
        chosen = [index for _, index in ordered]
        weights = [weights_by_index[index] for index in chosen]
        returns = [float(mature[index]["return_pct"]) for index in chosen]
        denominator = sum(weights)
        normalized = [weight / denominator for weight in weights]
        return {
            "pred_return": float(np.clip(np.dot(normalized, returns), -10.0, 10.0)),
            "pred_down": float(np.clip(np.dot(normalized, [float(v < 0.0) for v in returns]), 0.0, 1.0)),
            "pred_hit5": float(np.clip(np.dot(normalized, [float(v >= 5.0) for v in returns]), 0.0, 1.0)),
            "pred_tail_loss5": float(np.clip(np.dot(normalized, [float(v <= -5.0) for v in returns]), 0.0, 1.0)),
            "pred_q10_return": float(np.clip(_weighted_quantile(returns, normalized, 0.10), -10.0, 10.0)),
        }

    return predict, mature


def build_h4_t3_pool(picks_fusion, trade_date, model_path=None):
    _canonical_date(trade_date, "trade_date")
    if not isinstance(picks_fusion, list):
        raise H4T3PoolError("picks_fusion is invalid")
    model = load_model(model_path)
    predict, mature = _fit_predictor(model["training_rows"], trade_date)
    microstate = [row for row in picks_fusion if is_continuation_microstate(row)]
    eligible = []
    rejected_base = rejected_tail = rejected_q10 = 0
    for candidate in microstate:
        prediction = predict(candidate)
        failed_base = prediction["pred_return"] <= 0.0
        failed_tail = prediction["pred_tail_loss5"] > TAIL_LOSS_MAX
        failed_q10 = prediction["pred_q10_return"] < Q10_MIN
        rejected_base += int(failed_base)
        rejected_tail += int(failed_tail)
        rejected_q10 += int(failed_q10)
        if failed_base or failed_tail or failed_q10:
            continue
        item = dict(candidate)
        item["h4_predictions"] = {
            key: round(float(value), 6) for key, value in prediction.items()
        }
        item["reason"] = "H4 T+3 K30 tail-safe 全部门槛通过"
        eligible.append(item)
    eligible.sort(
        key=lambda row: (
            -float(_finite(row.get("score")) or 0.0),
            float(row["h4_predictions"]["pred_tail_loss5"]),
            -float(row["h4_predictions"]["pred_return"]),
            str(row.get("code") or ""),
        )
    )
    return {
        "status": "ok",
        "production_attested": True,
        "mode": "production",
        "strategy": "H4",
        "horizon": "T+3",
        "strategy_version": STRATEGY_VERSION,
        "model_date": max(str(row["trade_date"]) for row in mature),
        "daily_cap": None,
        "no_backfill": True,
        "score_policy": "existing_unified_score_no_h4_bonus",
        "policy": {
            "neighbor_count": NEIGHBOR_COUNT,
            "base_return_min_exclusive": 0.0,
            "tail_loss5_max": TAIL_LOSS_MAX,
            "q10_min_return": Q10_MIN,
            "all_eligible": True,
        },
        "reason": (
            "全部满足H4 T+3门槛的候选，按现有统一分排序。"
            if eligible else "今日没有候选通过H4 T+3全部门槛。"
        ),
        "diagnostics": {
            "fusion_count": len(picks_fusion),
            "microstate_count": len(microstate),
            "eligible_count": len(eligible),
            "selected_count": len(eligible),
            "base_return_rejected_count": rejected_base,
            "tail_loss5_rejected_count": rejected_tail,
            "q10_rejected_count": rejected_q10,
            "training_row_count": len(mature),
            "training_date_count": len(set(str(row["trade_date"]) for row in mature)),
        },
        "candidates": eligible,
    }
