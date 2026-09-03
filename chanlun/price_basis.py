"""Small price-basis helpers shared by daily and intraday strategy gates."""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional


def _positive(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def adjustment_factor(target_anchor: Any, source_anchor: Any) -> float:
    """Return the multiplicative factor that maps source prices to target basis."""

    target = _positive(target_anchor)
    source = _positive(source_anchor)
    if target is None or source is None:
        raise ValueError("price basis anchors must be finite and positive")
    factor = target / source
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("price basis factor must be finite and positive")
    return factor


def scale_price(value: Any, factor: Any) -> float:
    price = _positive(value)
    multiplier = _positive(factor)
    if price is None or multiplier is None:
        raise ValueError("price and factor must be finite and positive")
    result = price * multiplier
    if not math.isfinite(result) or result <= 0:
        raise ValueError("scaled price must be finite and positive")
    return result


def daily_intraday_factor(
    daily_stock: Mapping[str, Any],
    min30_result: Any,
) -> Optional[float]:
    """Resolve the factor that maps a 30m value into the daily stock basis.

    Pre-close rows carry the exact prior-close factor.  Formal close processing
    falls back to the same-day daily/minute closing anchors.
    """

    basis = daily_stock.get("price_basis")
    basis = basis if isinstance(basis, Mapping) else {}
    explicit = _positive(basis.get("factor_vs_raw"))
    if explicit is not None:
        return explicit
    return None


def align_intraday_price(
    value: Any,
    daily_stock: Mapping[str, Any],
    min30_result: Any,
) -> Optional[float]:
    factor = daily_intraday_factor(daily_stock, min30_result)
    if factor is None:
        return None
    try:
        return scale_price(value, factor)
    except ValueError:
        return None
