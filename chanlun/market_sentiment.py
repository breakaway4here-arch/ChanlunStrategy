"""Market sentiment V2 pure calculations.

This module deliberately has no network, repository, or report dependencies.
Callers must inject same-day whole-market bars, index changes, turnover, and
trend evidence. Missing evidence remains missing instead of being replaced by
an apparently precise neutral score.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median


COMPONENT_WEIGHTS = {
    "breadth": 0.30,
    "limit_ecology": 0.30,
    "index": 0.15,
    "turnover": 0.15,
    "trend": 0.10,
}


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _round_price(value):
    try:
        return float(
            Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_st(row):
    if row.get("is_st") is True:
        return True
    name = str(row.get("name") or "").upper().replace(" ", "")
    return "ST" in name


def _price_limit_pct(row):
    explicit = _number(row.get("price_limit_pct"))
    if explicit is not None:
        return explicit * 100 if 0 < explicit <= 1 else explicit

    code = str(row.get("code") or "").split(".")[0].zfill(6)
    if code.startswith(("4", "8", "92")):
        return 30.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if _is_st(row):
        return 5.0
    return 10.0


def _has_no_price_limit(row):
    if row.get("no_price_limit") is True or row.get("is_no_price_limit") is True:
        return True
    listing_days = _number(row.get("listing_trade_days"))
    if listing_days is None:
        return False
    code = str(row.get("code") or "").split(".")[0].zfill(6)
    if code.startswith(("4", "8", "92")):
        return listing_days <= 1
    return listing_days <= 5


def classify_price_limit(row):
    """Return ``limit_up``, ``limit_down``, ``normal``, ``excluded`` or ``invalid``.

    Limit prices are derived from the previous close and the applicable board
    rule, rounded to the A-share price tick with half-up rounding. This avoids
    the inaccurate ``change >= 9.5%`` shortcut.
    """

    if not isinstance(row, dict):
        return "invalid"
    if _has_no_price_limit(row):
        return "excluded"

    previous = _number(row.get("prev_close"))
    close = _number(row.get("close"))
    limit_pct = _price_limit_pct(row)
    if previous is None or previous <= 0 or close is None or limit_pct <= 0:
        return "invalid"

    limit_up_price = _round_price(previous * (1 + limit_pct / 100.0))
    limit_down_price = _round_price(previous * (1 - limit_pct / 100.0))
    tolerance = 0.0051
    if abs(close - limit_up_price) <= tolerance:
        return "limit_up"
    if abs(close - limit_down_price) <= tolerance:
        return "limit_down"
    return "normal"


def _valid_returns(stock_bars):
    returns = []
    for row in stock_bars or []:
        if not isinstance(row, dict) or _has_no_price_limit(row):
            continue
        previous = _number(row.get("prev_close"))
        close = _number(row.get("close"))
        if previous is None or previous <= 0 or close is None:
            continue
        returns.append((close / previous - 1) * 100)
    return returns


def compute_market_breadth(stock_bars):
    """Calculate whole-market advance/decline evidence and breadth score."""

    returns = _valid_returns(stock_bars)
    if not returns:
        return {
            "available": False,
            "valid_count": 0,
            "advance_count": 0,
            "decline_count": 0,
            "flat_count": 0,
            "advance_ratio": None,
            "median_change_pct": None,
            "rise_over_3_count": 0,
            "fall_over_3_count": 0,
            "score": None,
        }

    epsilon = 1e-9
    advance_count = sum(value > epsilon for value in returns)
    decline_count = sum(value < -epsilon for value in returns)
    flat_count = len(returns) - advance_count - decline_count
    advance_ratio = advance_count / len(returns) * 100
    median_change = median(returns)
    distribution_score = _clamp(50 + median_change * 12)
    score = _clamp(advance_ratio * 0.7 + distribution_score * 0.3)
    return {
        "available": True,
        "valid_count": len(returns),
        "advance_count": advance_count,
        "decline_count": decline_count,
        "flat_count": flat_count,
        "advance_ratio": round(advance_ratio, 2),
        "median_change_pct": round(median_change, 3),
        "rise_over_3_count": sum(value >= 3 for value in returns),
        "fall_over_3_count": sum(value <= -3 for value in returns),
        "score": round(score, 2),
    }


def historical_percentile(value, prior_values):
    """Mid-rank percentile using only the explicitly supplied prior values."""

    current = _number(value)
    values = [_number(item) for item in (prior_values or [])]
    values = [item for item in values if item is not None]
    if current is None or not values:
        return 50.0
    less = sum(item < current for item in values)
    equal = sum(item == current for item in values)
    return (less + equal * 0.5) / len(values) * 100


def _prior_limit_logs(prior_history):
    values = []
    for item in prior_history or []:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence", item)
        ecology = evidence.get("limit_ecology", {}) if isinstance(evidence, dict) else {}
        value = _number(ecology.get("log_limit_ratio"))
        if value is not None:
            values.append(value)
    return values


def compute_limit_ecology(stock_bars, prior_history=None):
    """Calculate limit-up/down counts, smoothed ratio, and ecology score."""

    valid_count = 0
    excluded_count = 0
    limit_up_count = 0
    limit_down_count = 0
    for row in stock_bars or []:
        status = classify_price_limit(row)
        if status == "excluded":
            excluded_count += 1
            continue
        if status == "invalid":
            continue
        valid_count += 1
        limit_up_count += status == "limit_up"
        limit_down_count += status == "limit_down"

    if valid_count == 0:
        return {
            "available": False,
            "valid_count": 0,
            "excluded_count": excluded_count,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "limit_ratio": None,
            "log_limit_ratio": None,
            "score": None,
        }

    limit_ratio = (limit_up_count + 1.0) / (limit_down_count + 1.0)
    log_limit_ratio = math.log(limit_ratio)
    prior_logs = _prior_limit_logs(prior_history)
    if prior_logs:
        ratio_score = historical_percentile(log_limit_ratio, prior_logs)
    else:
        ratio_score = _clamp(50 + math.tanh(log_limit_ratio) * 35)
    participation = (limit_up_count - limit_down_count) / valid_count
    participation_score = _clamp(50 + participation * 500)
    score = ratio_score * 0.7 + participation_score * 0.3
    return {
        "available": True,
        "valid_count": valid_count,
        "excluded_count": excluded_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "limit_ratio": round(limit_ratio, 4),
        "log_limit_ratio": round(log_limit_ratio, 6),
        "ratio_score": round(ratio_score, 2),
        "score": round(_clamp(score), 2),
    }


def _compute_index(index_bars):
    changes = []
    items = index_bars.values() if isinstance(index_bars, dict) else (index_bars or [])
    for row in items:
        if isinstance(row, dict):
            value = _number(row.get("change_pct"))
            if value is not None:
                changes.append(value)
    if not changes:
        return {"available": False, "average_change_pct": None, "score": None}
    average = sum(changes) / len(changes)
    return {
        "available": True,
        "average_change_pct": round(average, 3),
        "valid_count": len(changes),
        "score": round(_clamp(50 + average * 15), 2),
    }


def _compute_turnover(turnover, turnover_ma5):
    current = _number(turnover)
    baseline = _number(turnover_ma5)
    if current is None or baseline is None or baseline <= 0:
        return {"available": False, "ratio_to_ma5": None, "score": None}
    ratio = current / baseline
    return {
        "available": True,
        "ratio_to_ma5": round(ratio, 4),
        "score": round(_clamp(50 + (ratio - 1) * 100), 2),
    }


def _compute_trend(trend):
    trend = trend if isinstance(trend, dict) else {}
    ratio = _number(trend.get("above_ma20_ratio"))
    if ratio is None:
        return {"available": False, "above_ma20_ratio": None, "score": None}
    if ratio > 1:
        ratio /= 100
    return {
        "available": True,
        "above_ma20_ratio": round(_clamp(ratio, 0, 1), 4),
        "score": round(_clamp(ratio, 0, 1) * 100, 2),
    }


def _sentiment_label(score):
    if score is None:
        return "数据不足"
    if score >= 75:
        return "过热"
    if score >= 60:
        return "偏强"
    if score >= 45:
        return "平衡"
    if score >= 30:
        return "偏冷"
    return "冰点"


def build_market_sentiment(
    date,
    stock_bars,
    index_bars,
    turnover=None,
    turnover_ma5=None,
    trend=None,
    prior_history=None,
    minimum_coverage=0.8,
):
    """Build one day's five-component market sentiment result."""

    evidence = {
        "breadth": compute_market_breadth(stock_bars),
        "limit_ecology": compute_limit_ecology(stock_bars, prior_history),
        "index": _compute_index(index_bars),
        "turnover": _compute_turnover(turnover, turnover_ma5),
        "trend": _compute_trend(trend),
    }
    components = {
        name: item.get("score") if item.get("available") else None
        for name, item in evidence.items()
    }
    available_weight = sum(
        COMPONENT_WEIGHTS[name]
        for name, score in components.items()
        if score is not None
    )
    missing = [name for name in COMPONENT_WEIGHTS if components[name] is None]
    partial_score = None
    if available_weight > 0:
        weighted = sum(
            components[name] * COMPONENT_WEIGHTS[name]
            for name in COMPONENT_WEIGHTS
            if components[name] is not None
        )
        partial_score = round(_clamp(weighted / available_weight))

    coverage = round(available_weight, 2)
    insufficient = coverage < minimum_coverage
    score = None if insufficient else partial_score
    return {
        "version": "v2",
        "date": date,
        "score": score,
        "partial_score": partial_score,
        "label": _sentiment_label(score),
        "weights": dict(COMPONENT_WEIGHTS),
        "components": components,
        "evidence": evidence,
        "coverage": coverage,
        "insufficient": insufficient,
        "missing_components": missing,
    }


def detect_turning_signal(points):
    """Detect a directional turn without making claims on fewer than five days."""

    scores = [
        _number(item.get("score"))
        for item in (points or [])
        if isinstance(item, dict) and _number(item.get("score")) is not None
    ]
    if len(scores) < 5:
        return None
    recent = scores[-5:]
    short_delta = recent[-1] - recent[-3]
    full_delta = recent[-1] - recent[0]
    if short_delta >= 8 and full_delta >= 12:
        return "turning_stronger"
    if short_delta <= -8 and full_delta <= -12:
        return "turning_weaker"
    return None


def build_sentiment_history(daily_inputs, window=20):
    """Sequentially score days, then return a chart-ready recent window.

    Every day receives only previously calculated results for percentile
    normalization. Appending future data therefore cannot rewrite old scores.
    """

    results = []
    for day in sorted(daily_inputs or [], key=lambda item: str(item.get("date") or "")):
        result = build_market_sentiment(
            date=day.get("date"),
            stock_bars=day.get("stock_bars") or [],
            index_bars=day.get("index_bars") or [],
            turnover=day.get("turnover"),
            turnover_ma5=day.get("turnover_ma5"),
            trend=day.get("trend"),
            prior_history=results,
        )
        results.append(result)

    visible = [dict(item) for item in results[-max(1, int(window)):]]
    for index, item in enumerate(visible):
        valid = [
            _number(point.get("score"))
            for point in visible[max(0, index - 2):index + 1]
        ]
        valid = [value for value in valid if value is not None]
        item["ma3"] = round(sum(valid) / 3, 2) if len(valid) == 3 else None
        item["turning_signal"] = detect_turning_signal(visible[:index + 1])
    return visible
