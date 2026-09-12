"""Shared return-metric helpers for backtesting recommendation quality."""

from statistics import mean, median
import math


def _mature_value(sample, field, horizon_key, minimum_days):
    """Return a value only when its own forward horizon is mature.

    Older hand-authored research rows have no maturity metadata; their
    non-null values remain compatible.  Rows produced by the execution helper
    carry ``n_forward_days``/``maturity`` and are filtered per horizon.
    """
    if not isinstance(sample, dict) or sample.get(field) is None:
        return None
    maturity = sample.get("maturity")
    if isinstance(maturity, dict):
        if maturity.get(horizon_key) is not True:
            return None
    forward_days = sample.get("n_forward_days")
    if forward_days is not None:
        try:
            numeric_days = float(forward_days)
            if not math.isfinite(numeric_days) or not numeric_days.is_integer():
                return None
            if int(numeric_days) < minimum_days:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    value = sample[field]
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return value


def summarize_return_samples(samples):
    """Summarize a collection of forward-return samples.

    Args:
        samples: iterable of dicts with optional keys:
            - t1_close_pct
            - t3_close_pct
            - max_up_3d
            - max_dd_3d

    Returns:
        A dict matching the historical script summary shape, or ``None`` when
        no samples exist.
    """

    samples = list(samples)
    if not samples:
        return None

    t1 = [value for s in samples for value in [_mature_value(s, "t1_close_pct", "t1", 1)] if value is not None]
    t3 = [value for s in samples for value in [_mature_value(s, "t3_close_pct", "t3", 3)] if value is not None]
    t5 = [value for s in samples for value in [_mature_value(s, "t5_close_pct", "t5", 5)] if value is not None]
    up = [value for s in samples for value in [_mature_value(s, "max_up_3d", "t3", 3)] if value is not None]
    dd = [value for s in samples for value in [_mature_value(s, "max_dd_3d", "t3", 3)] if value is not None]

    n_total = len(samples)
    n_evaluable = len(t3)

    if n_total == 0:
        return None

    win_t3 = sum(1 for x in t3 if x > 0)
    loss_5pct = sum(1 for x in t3 if x <= -5)
    big_drop = sum(1 for x in dd if x <= -5)
    big_run = sum(1 for x in up if x >= 5)

    return {
        "n": n_total,
        "n_evaluable": n_evaluable,
        "n_t1_evaluable": len(t1),
        "n_t3_evaluable": len(t3),
        "n_t5_evaluable": len(t5),
        "t1_mean": round(mean(t1), 2) if t1 else None,
        "t1_median": round(median(t1), 2) if t1 else None,
        "t3_mean": round(mean(t3), 2) if t3 else None,
        "t3_median": round(median(t3), 2) if t3 else None,
        "t5_mean": round(mean(t5), 2) if t5 else None,
        "t5_median": round(median(t5), 2) if t5 else None,
        "t3_win_rate": round(win_t3 / n_evaluable * 100, 1) if n_evaluable else None,
        "t3_loss_5pct_rate": round(loss_5pct / n_evaluable * 100, 1) if n_evaluable else None,
        "max_up_3d_mean": round(mean(up), 2) if up else None,
        "max_dd_3d_mean": round(mean(dd), 2) if dd else None,
        "big_drop_5pct_rate": round(big_drop / len(dd) * 100, 1) if dd else None,
        "big_run_5pct_rate": round(big_run / len(up) * 100, 1) if up else None,
    }
