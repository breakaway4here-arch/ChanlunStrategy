"""Shared return-metric helpers for backtesting recommendation quality."""

from statistics import mean, median


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

    t1 = [float(s["t1_close_pct"]) for s in samples if s.get("t1_close_pct") is not None]
    t3 = [float(s["t3_close_pct"]) for s in samples if s.get("t3_close_pct") is not None]
    up = [float(s["max_up_3d"]) for s in samples if s.get("max_up_3d") is not None]
    dd = [float(s["max_dd_3d"]) for s in samples if s.get("max_dd_3d") is not None]

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
        "t1_mean": round(mean(t1), 2) if t1 else None,
        "t1_median": round(median(t1), 2) if t1 else None,
        "t3_mean": round(mean(t3), 2) if t3 else None,
        "t3_median": round(median(t3), 2) if t3 else None,
        "t3_win_rate": round(win_t3 / n_evaluable * 100, 1) if n_evaluable else None,
        "t3_loss_5pct_rate": round(loss_5pct / n_evaluable * 100, 1) if n_evaluable else None,
        "max_up_3d_mean": round(mean(up), 2) if up else None,
        "max_dd_3d_mean": round(mean(dd), 2) if dd else None,
        "big_drop_5pct_rate": round(big_drop / len(dd) * 100, 1) if dd else None,
        "big_run_5pct_rate": round(big_run / len(up) * 100, 1) if up else None,
    }
