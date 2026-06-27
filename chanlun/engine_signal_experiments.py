"""Signal provider experiments for optional buy/sell-point filtering."""

from __future__ import annotations

from numbers import Real

from .engine_signals import locate_buy_sell_points


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


def _apply_filter(points, should_drop):
    if not isinstance(points, list):
        return points
    return [point for point in points if not should_drop(point)]


def locate_buy_sell_points_p0_distance_guard(result):
    """Stable signal provider with opt-in P0 distance guard."""
    buy_points, sell_points = locate_buy_sell_points(result)
    filtered_buy_points = _apply_filter(buy_points, _should_drop_p0_distance)
    return filtered_buy_points, sell_points


def locate_buy_sell_points_p1_confirmation_guard(result):
    """Stable signal provider with opt-in P1 confirmation guard."""
    buy_points, sell_points = locate_buy_sell_points(result)
    filtered_buy_points = _apply_filter(
        buy_points,
        _should_drop_p1_confirmation,
    )
    return filtered_buy_points, sell_points


def locate_buy_sell_points_p0_p1_guard(result):
    """Stable signal provider with both P0 and P1 guards enabled."""
    buy_points, sell_points = locate_buy_sell_points(result)
    filtered_buy_points = _apply_filter(buy_points, _should_drop_p0_distance)
    filtered_buy_points = _apply_filter(
        filtered_buy_points,
        _should_drop_p1_confirmation,
    )
    return filtered_buy_points, sell_points
