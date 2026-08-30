"""Market sentiment V2 pure calculations.

This module deliberately has no network, repository, or report dependencies.
Callers must inject same-day whole-market bars, index changes, turnover, and
trend evidence. Missing evidence remains missing instead of being replaced by
an apparently precise neutral score.
"""

from __future__ import annotations

import math
from datetime import date as calendar_date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median


COMPONENT_WEIGHTS = {
    "breadth": 0.30,
    "limit_ecology": 0.30,
    "index": 0.15,
    "turnover": 0.15,
    "trend": 0.10,
}

PSY12_SHADOW_WEIGHTS = {
    "breadth": 0.25,
    "limit_ecology": 0.30,
    "index": 0.10,
    "turnover": 0.15,
    "trend": 0.10,
    "psy12": 0.10,
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

    return _score_limit_ecology_counts(
        limit_up_count,
        limit_down_count,
        valid_count,
        excluded_count,
        prior_history=prior_history,
        source="derived_from_daily_bars",
    )


def _score_limit_ecology_counts(
    limit_up_count,
    limit_down_count,
    valid_count,
    excluded_count=0,
    *,
    prior_history=None,
    source="",
):
    limit_ratio = (limit_up_count + 1.0) / (limit_down_count + 1.0)
    log_limit_ratio = math.log(limit_ratio)
    prior_logs = _prior_limit_logs(prior_history)
    if prior_logs:
        ratio_score = historical_percentile(log_limit_ratio, prior_logs)
    else:
        ratio_score = _clamp(50 + math.tanh(log_limit_ratio) * 35)
    limit_up_ratio = limit_up_count / valid_count
    limit_down_ratio = limit_down_count / valid_count
    limit_up_score = _clamp(limit_up_ratio / 0.02 * 100)
    limit_down_score = _clamp(100 - limit_down_ratio / 0.02 * 100)
    improvement_score = 50.0
    if prior_logs:
        comparison = prior_logs[-5:]
        prior_average = sum(comparison) / len(comparison)
        improvement_score = _clamp(
            50 + math.tanh(log_limit_ratio - prior_average) * 40
        )
    score = (
        ratio_score * 0.40
        + limit_up_score * 0.25
        + limit_down_score * 0.25
        + improvement_score * 0.10
    )
    return {
        "available": True,
        "valid_count": valid_count,
        "excluded_count": excluded_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "limit_ratio": round(limit_ratio, 4),
        "log_limit_ratio": round(log_limit_ratio, 6),
        "ratio_score": round(ratio_score, 2),
        "limit_up_ratio": round(limit_up_ratio, 6),
        "limit_down_ratio": round(limit_down_ratio, 6),
        "limit_up_score": round(limit_up_score, 2),
        "limit_down_score": round(limit_down_score, 2),
        "improvement_score": round(improvement_score, 2),
        "source": source,
        "score": round(_clamp(score), 2),
    }


def compute_limit_ecology_from_counts(
    limit_counts,
    valid_count,
    prior_history=None,
):
    evidence = limit_counts if isinstance(limit_counts, dict) else {}
    if evidence.get("data_status") != "verified":
        return {
            "available": False,
            "valid_count": int(valid_count or 0),
            "excluded_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "limit_ratio": None,
            "log_limit_ratio": None,
            "score": None,
            "source": evidence.get("source", ""),
        }
    up_count = _number(evidence.get("limit_up_count"))
    down_count = _number(evidence.get("limit_down_count"))
    market_count = _number(evidence.get("market_count"))
    denominator = market_count if market_count is not None else _number(valid_count)
    if (
        up_count is None
        or down_count is None
        or denominator is None
        or denominator <= 0
        or up_count < 0
        or down_count < 0
    ):
        return {
            "available": False,
            "valid_count": int(valid_count or 0),
            "excluded_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "limit_ratio": None,
            "log_limit_ratio": None,
            "score": None,
            "source": evidence.get("source", ""),
        }
    return _score_limit_ecology_counts(
        int(up_count),
        int(down_count),
        int(denominator),
        prior_history=prior_history,
        source=evidence.get("source", ""),
    )


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


def _compute_turnover(turnover, turnover_ma5, turnover_ma20=None):
    current = _number(turnover)
    baseline5 = _number(turnover_ma5)
    baseline20 = _number(turnover_ma20)
    ratios = []
    ratio5 = None
    ratio20 = None
    if current is not None and baseline5 is not None and baseline5 > 0:
        ratio5 = current / baseline5
        ratios.append(ratio5)
    if current is not None and baseline20 is not None and baseline20 > 0:
        ratio20 = current / baseline20
        ratios.append(ratio20)
    if not ratios:
        return {
            "available": False,
            "ratio_to_ma5": None,
            "ratio_to_ma20": None,
            "score": None,
        }
    ratio_scores = [_clamp(50 + (ratio - 1) * 100) for ratio in ratios]
    return {
        "available": True,
        "ratio_to_ma5": round(ratio5, 4) if ratio5 is not None else None,
        "ratio_to_ma20": round(ratio20, 4) if ratio20 is not None else None,
        "score": round(sum(ratio_scores) / len(ratio_scores), 2),
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


def _unavailable_psy12(reason, *, valid_days=0):
    return {
        "status": "unavailable",
        "reason": reason,
        "score": None,
        "up_days": None,
        "valid_days": valid_days,
        "window": 12,
        "start_date": None,
        "end_date": None,
        "daily_directions": [],
    }


def build_psy12_evidence(report_date, market_sentiment_history):
    """Build an auditable PSY12 window without sorting or filling evidence."""

    try:
        cutoff = calendar_date.fromisoformat(str(report_date or ""))
    except (TypeError, ValueError):
        return _unavailable_psy12("invalid_report_date")

    history = list(market_sentiment_history or [])
    parsed = []
    seen = set()
    for item in history:
        if not isinstance(item, dict):
            return _unavailable_psy12("unverifiable_index_evidence")
        trade_date = str(item.get("date") or "")
        try:
            parsed_date = calendar_date.fromisoformat(trade_date)
        except ValueError:
            return _unavailable_psy12("unverifiable_index_evidence")
        if trade_date in seen:
            return _unavailable_psy12("duplicate_date")
        seen.add(trade_date)
        if parsed_date > cutoff:
            return _unavailable_psy12("future_date")
        parsed.append((parsed_date, trade_date, item))

    if any(parsed[index][0] >= parsed[index + 1][0] for index in range(len(parsed) - 1)):
        return _unavailable_psy12("unordered_dates")
    if len(parsed) < 12:
        return _unavailable_psy12("insufficient_history", valid_days=len(parsed))

    selected = parsed[-12:]
    directions = []
    for _, trade_date, item in selected:
        evidence = item.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        index_evidence = evidence.get("index")
        index_evidence = index_evidence if isinstance(index_evidence, dict) else {}
        change = _number(index_evidence.get("average_change_pct"))
        if index_evidence.get("available") is not True or change is None:
            return _unavailable_psy12(
                "unverifiable_index_evidence",
                valid_days=len(directions),
            )
        directions.append({
            "date": trade_date,
            "average_change_pct": round(change, 3),
            "direction": "up" if change > 0 else "non_up",
        })

    up_days = sum(item["direction"] == "up" for item in directions)
    return {
        "status": "available",
        "reason": None,
        "score": round(up_days / 12.0 * 100.0, 2),
        "up_days": up_days,
        "valid_days": 12,
        "window": 12,
        "start_date": directions[0]["date"],
        "end_date": directions[-1]["date"],
        "daily_directions": directions,
    }


def build_market_sentiment_psy12_shadow(
    market_sentiment,
    market_sentiment_history,
):
    """Return PSY12 research fields without mutating formal sentiment."""

    formal = market_sentiment if isinstance(market_sentiment, dict) else {}
    psy12 = build_psy12_evidence(
        formal.get("date"),
        market_sentiment_history,
    )
    components = formal.get("components")
    components = components if isinstance(components, dict) else {}
    formal_score = _number(formal.get("score"))
    formal_label = formal.get("label") or _sentiment_label(formal_score)
    shadow_components = {
        name: _number(components.get(name))
        for name in COMPONENT_WEIGHTS
    }
    unavailable_reason = psy12.get("reason")
    if unavailable_reason is None and any(
        value is None for value in shadow_components.values()
    ):
        unavailable_reason = "missing_formal_components"
    if unavailable_reason is None and formal_score is None:
        unavailable_reason = "formal_score_unavailable"

    raw_shadow_score = None
    shadow_score = None
    shadow_label = None
    delta = None
    if unavailable_reason is None:
        raw_shadow_score = sum(
            shadow_components[name] * PSY12_SHADOW_WEIGHTS[name]
            for name in COMPONENT_WEIGHTS
        ) + psy12["score"] * PSY12_SHADOW_WEIGHTS["psy12"]
        raw_shadow_score = round(_clamp(raw_shadow_score), 3)
        shadow_score = round(raw_shadow_score)
        shadow_label = _sentiment_label(shadow_score)
        delta = round(shadow_score - formal_score, 2)

    return {
        "psy12": psy12,
        "psy12_shadow": {
            "schema_version": 1,
            "mode": "shadow",
            "status": "available" if unavailable_reason is None else "unavailable",
            "reason": unavailable_reason,
            "affects_production": False,
            "promotion_eligible": False,
            "promotion_requires_new_authorization": True,
            "formal_score": formal.get("score"),
            "raw_shadow_score_with_psy12": raw_shadow_score,
            "shadow_score_with_psy12": shadow_score,
            "delta_vs_formal": delta,
            "formal_label": formal_label,
            "shadow_label": shadow_label,
            "weight_version": "psy12-shadow-v1",
            "weights": dict(PSY12_SHADOW_WEIGHTS),
        },
    }


def build_market_sentiment(
    date,
    stock_bars,
    index_bars,
    turnover=None,
    turnover_ma5=None,
    turnover_ma20=None,
    trend=None,
    prior_history=None,
    limit_counts=None,
    minimum_coverage=0.8,
):
    """Build one day's five-component market sentiment result."""

    breadth = compute_market_breadth(stock_bars)
    if (
        isinstance(limit_counts, dict)
        and limit_counts.get("data_status") == "verified"
        and str(limit_counts.get("evidence_date") or "") == str(date or "")
    ):
        limit_ecology = compute_limit_ecology_from_counts(
            limit_counts,
            breadth.get("valid_count"),
            prior_history=prior_history,
        )
    else:
        limit_ecology = compute_limit_ecology(stock_bars, prior_history)
    evidence = {
        "breadth": breadth,
        "limit_ecology": limit_ecology,
        "index": _compute_index(index_bars),
        "turnover": _compute_turnover(
            turnover,
            turnover_ma5,
            turnover_ma20,
        ),
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


def build_daily_inputs_from_windows(
    stock_window,
    index_window=None,
    limit_counts_by_date=None,
):
    """Transform one DB window into sequential, no-future daily inputs."""
    stock_window = stock_window if isinstance(stock_window, dict) else {}
    index_window = index_window if isinstance(index_window, dict) else {}
    dates = sorted(
        str(value)
        for value in (stock_window.get("dates") or [])
        if str(value)
    )
    date_set = set(dates)

    def _group_rows(rows):
        grouped = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "")
            trade_date = str(row.get("ts") or "")[:10]
            if not code or trade_date not in date_set:
                continue
            grouped.setdefault(code, {})[trade_date] = row
        return grouped

    stock_by_code = _group_rows(stock_window.get("rows"))
    index_by_code = _group_rows(index_window.get("rows"))

    def _listing_trade_days(listed_date, trade_date):
        normalized = str(listed_date or "").replace("-", "")[:8]
        if len(normalized) != 8 or not normalized.isdigit():
            return None
        normalized_trade_date = str(trade_date).replace("-", "")[:8]
        if normalized > normalized_trade_date:
            return None
        first_window_date = str(dates[0]).replace("-", "")[:8] if dates else ""
        if normalized < first_window_date:
            return 999
        return sum(
            1
            for value in dates
            if normalized <= str(value).replace("-", "")[:8]
            <= normalized_trade_date
        )

    raw_turnover_by_date = {}
    for trade_date in dates:
        raw_turnover_by_date[trade_date] = sum(
            _number(rows[trade_date].get("amount")) or 0.0
            for rows in stock_by_code.values()
            if trade_date in rows
        )

    # Amount provenance can change at a provider cutover (for example an old
    # volume-derived proxy versus a verified close snapshot).  A discontinuity
    # in units must reset the moving-average baseline instead of being scored as
    # a real collapse or explosion in market turnover.
    turnover_inputs = {}
    turnover_segment = []
    for trade_date in dates:
        current_turnover = raw_turnover_by_date[trade_date]
        quality = "comparable"
        if turnover_segment:
            reference = median(turnover_segment[-5:])
            ratio = (
                current_turnover / reference
                if reference and current_turnover > 0
                else None
            )
            if ratio is None or ratio < 0.2 or ratio > 5.0:
                turnover_segment = []
                quality = "scale_break"
        turnover_inputs[trade_date] = {
            "turnover": current_turnover,
            "turnover_ma5": (
                sum(turnover_segment[-5:]) / 5
                if len(turnover_segment) >= 5
                else None
            ),
            "turnover_ma20": (
                sum(turnover_segment[-20:]) / 20
                if len(turnover_segment) >= 20
                else None
            ),
            "turnover_quality": quality,
        }
        turnover_segment.append(current_turnover)

    daily = []
    for date_index, trade_date in enumerate(dates):
        stock_bars = []
        trend_total = 0
        trend_above = 0
        for code in sorted(stock_by_code):
            rows_by_date = stock_by_code[code]
            current = rows_by_date.get(trade_date)
            if current is None:
                continue
            available_dates = [
                value
                for value in dates[:date_index + 1]
                if value in rows_by_date
            ]
            closes = [
                _number(rows_by_date[value].get("close"))
                for value in available_dates
            ]
            closes = [value for value in closes if value is not None]
            if len(closes) >= 20:
                ma20 = sum(closes[-20:]) / 20
                trend_total += 1
                trend_above += closes[-1] >= ma20
            if len(available_dates) < 2:
                continue
            previous = rows_by_date[available_dates[-2]]
            meta = current.get("stock_meta_asof")
            meta = meta if isinstance(meta, dict) else {}
            stock_bars.append({
                "code": code,
                "name": current.get("name") or meta.get("name") or "",
                "prev_close": previous.get("close"),
                "close": current.get("close"),
                "is_st": meta.get("is_st"),
                "listed_date": meta.get("listed_date"),
                "listing_trade_days": _listing_trade_days(
                    meta.get("listed_date"), trade_date
                ),
            })

        turnover_input = turnover_inputs[trade_date]

        index_bars = []
        for code in sorted(index_by_code):
            rows_by_date = index_by_code[code]
            current = rows_by_date.get(trade_date)
            if current is None:
                continue
            available_dates = [
                value
                for value in dates[:date_index + 1]
                if value in rows_by_date
            ]
            if len(available_dates) < 2:
                continue
            previous = rows_by_date[available_dates[-2]]
            previous_close = _number(previous.get("close"))
            current_close = _number(current.get("close"))
            if previous_close in (None, 0) or current_close is None:
                continue
            index_bars.append({
                "code": code,
                "change_pct": (
                    current_close / previous_close - 1.0
                ) * 100.0,
            })

        daily.append({
            "date": trade_date,
            "stock_bars": stock_bars,
            "index_bars": index_bars,
            "turnover": turnover_input["turnover"],
            "turnover_ma5": turnover_input["turnover_ma5"],
            "turnover_ma20": turnover_input["turnover_ma20"],
            "turnover_quality": turnover_input["turnover_quality"],
            "trend": {
                "above_ma20_ratio": (
                    trend_above / float(trend_total)
                    if trend_total
                    else None
                )
            },
            "limit_counts": (
                (limit_counts_by_date or {}).get(trade_date)
                if isinstance(limit_counts_by_date, dict)
                else None
            ),
        })
    return daily


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
            turnover_ma20=day.get("turnover_ma20"),
            trend=day.get("trend"),
            prior_history=results,
            limit_counts=day.get("limit_counts"),
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
