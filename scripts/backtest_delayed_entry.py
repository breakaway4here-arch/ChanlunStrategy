"""Backtest delayed-entry modes on historical recommendation snapshots."""

import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import DAY_LOOKBACK
from chanlun.backtest_execution import evaluate_forward_returns
from chanlun.backtest_metrics import summarize_return_samples
from chanlun.data_fetcher import fetch_daily_kline
from scripts.backtest_recommendation_quality import iter_snapshot_picks

ENTRY_MODES = ("immediate_close", "delay1_open", "delay1_close")


def _as_list(values):
    if values is None:
        return []
    return list(values)


def summarize_samples(samples):
    return summarize_return_samples(samples)


def load_kline(code):
    return fetch_daily_kline(code, count=DAY_LOOKBACK)


def evaluate_pick(pick, snap_date, kline):
    result = {}

    for mode in ENTRY_MODES:
        try:
            sample = evaluate_forward_returns(
                kline,
                snap_date,
                entry_mode=mode,
                horizon=5,
            )
        except Exception:
            sample = None

        if sample is not None:
            result[mode] = sample
        else:
            result[mode] = None

    return result


def _build_empty_summary():
    return {
        "snapshot_days": 0,
        "picks_seen": 0,
        "evaluated_by_mode": {mode: 0 for mode in ENTRY_MODES},
        "skipped": 0,
        "skipped_no_code": 0,
        "skipped_no_kline": 0,
        "not_evaluable_by_mode": {mode: 0 for mode in ENTRY_MODES},
    }


def run(limit_days=None):
    picks = list(iter_snapshot_picks())

    if limit_days is not None:
        dates = sorted({snap_date for snap_date, _, _ in picks}, reverse=True)
        date_limit = set(dates[: max(0, int(limit_days))])
        picks = [item for item in picks if item[0] in date_limit]

    seen_snapshots = []
    seen_set = set()
    for snap_date, _, _ in picks:
        if snap_date not in seen_set:
            seen_snapshots.append(snap_date)
            seen_set.add(snap_date)

    summary = _build_empty_summary()
    summary["snapshot_days"] = len(seen_snapshots)

    overall_samples = {ver: {mode: [] for mode in ENTRY_MODES} for ver in ("picks_pure", "picks_fusion")}
    by_type_samples = {
        ver: defaultdict(lambda: {mode: [] for mode in ENTRY_MODES})
        for ver in ("picks_pure", "picks_fusion")
    }
    kline_cache = {}

    for snap_date, ver, pick in picks:
        summary["picks_seen"] += 1
        code = pick.get("code")
        if not code:
            summary["skipped_no_code"] += 1
            summary["skipped"] += 1
            continue

        if code not in kline_cache:
            try:
                kline_cache[code] = load_kline(code)
            except Exception:
                kline_cache[code] = None

        kline = kline_cache[code]

        if not kline:
            summary["skipped_no_kline"] += 1
            summary["skipped"] += 1
            continue

        # Normalize for forward-return evaluator.
        normalized_kline = {
            "dates": [str(d).split(" ")[0] for d in _as_list(kline.get("dates"))],
            "opens": [float(x) for x in _as_list(kline.get("opens"))],
            "highs": [float(x) for x in _as_list(kline.get("highs"))],
            "lows": [float(x) for x in _as_list(kline.get("lows"))],
            "closes": [float(x) for x in _as_list(kline.get("closes"))],
        }

        samples = evaluate_pick(pick, snap_date, normalized_kline)
        bbp = pick.get("best_buy_point") or {}
        btype = str(bbp.get("type", "?"))

        for mode in ENTRY_MODES:
            sample = samples.get(mode)
            if sample is None:
                summary["not_evaluable_by_mode"][mode] += 1
                continue
            summary["evaluated_by_mode"][mode] += 1
            overall_samples[ver][mode].append(sample)
            by_type_samples[ver][btype][mode].append(sample)

    overall = {
        ver: {mode: summarize_samples(samples) for mode, samples in modes.items()}
        for ver, modes in overall_samples.items()
    }
    by_type = {
        ver: {
            btype: {mode: summarize_samples(samples) for mode, samples in modes.items()}
            for btype, modes in btypes.items()
        }
        for ver, btypes in by_type_samples.items()
    }

    return {"summary": summary, "overall": overall, "by_type": by_type}


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Backtest delayed-entry strategy modes.")
    parser.add_argument("--output-json", required=True, help="Output JSON report path")
    parser.add_argument("--limit-days", type=int, default=None, help="Limit snapshot days for smoke testing")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        payload = run(limit_days=args.limit_days)
        path = args.output_json
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return 0
    except Exception as exc:
        print(f"backtest_delayed_entry failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
