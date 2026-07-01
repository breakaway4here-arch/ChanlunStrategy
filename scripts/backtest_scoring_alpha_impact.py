"""Compare scoring_engine ranking before and after lightweight alpha scoring.

This script answers two questions:
1. Did the alpha-adjusted opportunity_score improve forward returns versus the
   same scoring formula with alpha disabled?
2. Which top-K replacements explain the difference?

It uses historical report snapshots under docs/data and builds a local kline
cache by merging all embedded OHLC rows from those snapshots. No network fetch
is required, and no report files are written by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from glob import glob
from statistics import mean, median
from typing import Any, Iterable, Mapping

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chanlun.backtest_execution import evaluate_forward_returns  # noqa: E402
from chanlun.scoring_engine import compute_opportunity_score  # noqa: E402


SOURCE_RANK = {
    "main": 0,
    "acceleration": 1,
    "luojie": 2,
    "confirming": 3,
    "baseline": 4,
}

DEFAULT_SOURCES = ("main", "acceleration", "luojie", "confirming")
ALL_SOURCES = DEFAULT_SOURCES + ("baseline",)


@dataclass(frozen=True)
class Candidate:
    day: str
    code: str
    name: str
    sources: tuple[str, ...]
    primary_source: str
    before_score: int
    after_score: int
    score_delta: int
    alpha_bonus: float
    alpha_multiplier: float
    alpha_features: Mapping[str, Any]
    returns: dict[str, Any] | None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _load_daily_reports(data_dir: str) -> list[tuple[str, dict[str, Any]]]:
    reports: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(glob(os.path.join(data_dir, "*.json"))):
        name = os.path.basename(path)
        if name == "index.json" or "_" in name:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
            continue
        day = str(payload.get("date") or name.removesuffix(".json"))
        reports.append((day, payload))
    return reports


def _candidate_code(item: Mapping[str, Any]) -> str:
    code = item.get("code")
    return str(code) if code is not None else ""


def _candidate_name(item: Mapping[str, Any]) -> str:
    return str(item.get("name") or "")


def _normalize_source_items(items: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by_code: dict[str, Mapping[str, Any]] = {}
    for item in items:
        row = _to_dict(item)
        code = _candidate_code(row)
        if code and code not in by_code:
            by_code[code] = row
    return by_code


def _source_items(report: Mapping[str, Any]) -> dict[str, dict[str, Mapping[str, Any]]]:
    next_day_boom = _to_dict(report.get("next_day_boom"))
    luojie_pool = _to_dict(report.get("luojie_pool"))
    boom_candidates = _safe_list(next_day_boom.get("candidates"))
    if str(next_day_boom.get("mode") or "") != "enabled":
        boom_candidates = []

    return {
        "main": _normalize_source_items(_safe_list(report.get("picks_fusion"))),
        "acceleration": _normalize_source_items(boom_candidates),
        "luojie": _normalize_source_items(_safe_list(luojie_pool.get("candidates"))),
        "confirming": _normalize_source_items(_safe_list(report.get("startup_watchlist"))),
        "baseline": _normalize_source_items(_safe_list(report.get("picks_pure"))),
    }


def _sorted_sources(sources: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(sources), key=lambda s: SOURCE_RANK.get(s, 99)))


def _merge_candidates(
    report: Mapping[str, Any],
    allowed_sources: Iterable[str],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    allowed = set(allowed_sources)
    merged: dict[str, dict[str, Mapping[str, Any]]] = {}
    for source, rows in _source_items(report).items():
        if source not in allowed:
            continue
        for code, row in rows.items():
            bucket = merged.setdefault(code, {})
            bucket.setdefault(source, row)
    return merged


def _extract_kline(item: Mapping[str, Any]) -> dict[str, dict[str, float]] | None:
    dates = [str(x).split(" ")[0] for x in _safe_list(item.get("dates"))]
    opens = [_safe_float(x) for x in _safe_list(item.get("opens"))]
    highs = [_safe_float(x) for x in _safe_list(item.get("highs"))]
    lows = [_safe_float(x) for x in _safe_list(item.get("lows"))]
    closes = [_safe_float(x) for x in _safe_list(item.get("closes"))]
    if not dates or not (len(dates) == len(opens) == len(highs) == len(lows) == len(closes)):
        return None

    rows: dict[str, dict[str, float]] = {}
    for idx, date in enumerate(dates):
        o, h, l, c = opens[idx], highs[idx], lows[idx], closes[idx]
        if None in (o, h, l, c):
            continue
        rows[date] = {"open": o, "high": h, "low": l, "close": c}
    return rows or None


def _build_kline_cache(reports: Iterable[tuple[str, Mapping[str, Any]]]) -> dict[str, dict[str, dict[str, float]]]:
    cache: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for _, report in reports:
        for rows in _source_items(report).values():
            for code, item in rows.items():
                kline = _extract_kline(item)
                if not kline:
                    continue
                cache[code].update(kline)
    return cache


def _kline_for_code(cache: Mapping[str, Mapping[str, Mapping[str, float]]], code: str) -> dict[str, list[Any]] | None:
    rows = cache.get(code)
    if not rows:
        return None
    dates = sorted(rows)
    return {
        "dates": dates,
        "opens": [rows[d]["open"] for d in dates],
        "highs": [rows[d]["high"] for d in dates],
        "lows": [rows[d]["low"] for d in dates],
        "closes": [rows[d]["close"] for d in dates],
    }


def _score_candidate(
    primary_raw: Mapping[str, Any],
    primary_source: str,
    sources: tuple[str, ...],
    by_source: Mapping[str, Mapping[str, Any]],
    data_quality: Any,
    alpha_enabled: bool,
) -> tuple[int, dict[str, Any]]:
    return compute_opportunity_score(
        primary_raw,
        primary_source,
        {
            "sources": list(sources),
            "by_source": dict(by_source),
            "data_quality": data_quality,
            "source_count": len(sources),
            "alpha_enabled": alpha_enabled,
        },
    )


def _build_candidates(
    day: str,
    report: Mapping[str, Any],
    kline_cache: Mapping[str, Mapping[str, Mapping[str, float]]],
    allowed_sources: Iterable[str],
    entry_mode: str,
    horizon: int,
    min_forward_days: int,
) -> tuple[list[Candidate], int]:
    candidates: list[Candidate] = []
    skipped_no_return = 0
    data_quality = report.get("data_quality")

    for code, by_source in _merge_candidates(report, allowed_sources).items():
        sources = _sorted_sources(by_source.keys())
        if not sources:
            continue
        primary_source = sources[0]
        primary_raw = by_source[primary_source]
        before_score, _ = _score_candidate(
            primary_raw,
            primary_source,
            sources,
            by_source,
            data_quality,
            alpha_enabled=False,
        )
        after_score, after_trace = _score_candidate(
            primary_raw,
            primary_source,
            sources,
            by_source,
            data_quality,
            alpha_enabled=True,
        )

        returns = None
        kline = _kline_for_code(kline_cache, code)
        if kline is not None:
            returns = evaluate_forward_returns(kline, day, entry_mode=entry_mode, horizon=horizon)
            if returns and int(returns.get("n_forward_days") or 0) < min_forward_days:
                returns = None
        if returns is None:
            skipped_no_return += 1

        candidates.append(
            Candidate(
                day=day,
                code=code,
                name=_candidate_name(primary_raw),
                sources=sources,
                primary_source=primary_source,
                before_score=before_score,
                after_score=after_score,
                score_delta=after_score - before_score,
                alpha_bonus=float(after_trace.get("alpha_bonus") or 0.0),
                alpha_multiplier=float(after_trace.get("alpha_multiplier") or 1.0),
                alpha_features=_to_dict(after_trace.get("alpha_features")),
                returns=returns,
            )
        )
    return candidates, skipped_no_return


def _metric(candidate: Candidate, field: str) -> float | None:
    if not candidate.returns:
        return None
    value = candidate.returns.get(field)
    return _safe_float(value)


def _summarize(candidates: Iterable[Candidate], field: str) -> dict[str, Any]:
    rows = list(candidates)
    values: list[float] = []
    drawdowns: list[float] = []
    dd3_values: list[float] = []
    for candidate in rows:
        value = _metric(candidate, field)
        if value is not None:
            values.append(value)
        max_drawdown = _metric(candidate, "max_drawdown")
        if max_drawdown is not None:
            drawdowns.append(max_drawdown)
        max_dd_3d = _metric(candidate, "max_dd_3d")
        if max_dd_3d is not None:
            dd3_values.append(max_dd_3d)
    if not rows:
        return {"n_selected": 0, "n_evaluable": 0}
    wins = sum(1 for v in values if v > 0)
    loss5 = sum(1 for v in values if v <= -5)
    return {
        "n_selected": len(rows),
        "n_evaluable": len(values),
        "mean": round(mean(values), 2) if values else None,
        "median": round(median(values), 2) if values else None,
        "win_rate": round(wins / len(values) * 100, 1) if values else None,
        "loss_5pct_rate": round(loss5 / len(values) * 100, 1) if values else None,
        "max_drawdown": round(min(drawdowns), 2) if drawdowns else None,
        "max_dd_mean": round(mean(dd3_values), 2) if dd3_values else None,
    }


def _mean_metric(candidates: Iterable[Candidate], field: str) -> float | None:
    values: list[float] = []
    for candidate in candidates:
        value = _metric(candidate, field)
        if value is not None:
            values.append(value)
    return mean(values) if values else None


def _format_pct(value: float | None) -> str:
    return "None" if value is None else f"{value:.2f}%"


def _print_summary(title: str, summary: Mapping[str, Any]) -> None:
    print(f"{title}:")
    print(
        "  selected={n_selected} evaluable={n_evaluable} mean={mean}% "
        "median={median}% win={win_rate}% loss<=-5%={loss_5pct_rate}% "
        "max_drawdown={max_drawdown}% max_dd_mean={max_dd_mean}%".format(**summary)
    )


def _top_rows(rows: Iterable[Candidate], score_field: str, top_k: int) -> list[Candidate]:
    return sorted(rows, key=lambda c: (-getattr(c, score_field), c.code))[:top_k]


def _sample_label(candidate: Candidate, field: str) -> str:
    return (
        f"{candidate.day} {candidate.code} {candidate.name} "
        f"src={'+'.join(candidate.sources)} before={candidate.before_score} "
        f"after={candidate.after_score} alpha=+{candidate.alpha_bonus:.2f}/x{candidate.alpha_multiplier:.3f} "
        f"{field}={_format_pct(_metric(candidate, field))}"
    )


def _alpha_factor_hits(features: Mapping[str, Any]) -> dict[str, bool]:
    alpha_features = _to_dict(features)
    market_regime = _to_dict(alpha_features.get("market_regime_factor"))
    sector_strength = _to_dict(alpha_features.get("sector_strength_factor"))
    breakout_quality = _to_dict(alpha_features.get("breakout_quality"))
    momentum = _safe_float(alpha_features.get("momentum_persistence"))

    market_regime_values = [_safe_float(v) for v in market_regime.values()]
    sector_strength_values = [_safe_float(v) for v in sector_strength.values()]

    volume_ratio = _safe_float(breakout_quality.get("volume_ratio"))
    confirmed_by = _safe_str(breakout_quality.get("confirmed_by"))
    distance = _safe_float(breakout_quality.get("distance"))

    breakout_hit = False
    if volume_ratio is not None and volume_ratio >= 1.0:
        breakout_hit = True
    if confirmed_by and ("30" in confirmed_by or "确认" in confirmed_by) and "等待确认" not in confirmed_by:
        breakout_hit = True
    if distance is not None and abs(distance) <= 5.0:
        breakout_hit = True

    return {
        "market_regime": any(v is not None and v > 0 for v in market_regime_values),
        "sector_strength": any(v is not None and v > 0 for v in sector_strength_values),
        "momentum_persistence": momentum is not None and momentum > 0,
        "breakout_quality": breakout_hit,
    }


def _collect_alpha_hits(
    candidates: Iterable[Candidate],
) -> tuple[int, float | None, float | None, dict[str, int], dict[str, list[Candidate]]]:
    rows = list(candidates)
    if not rows:
        return 0, None, None, {"market_regime": 0, "sector_strength": 0, "momentum_persistence": 0, "breakout_quality": 0}, defaultdict(list)

    bonuses = [c.alpha_bonus for c in rows]
    total = len(rows)
    hit_count = sum(1 for c in rows if c.alpha_bonus > 0)
    factor_hits: dict[str, int] = {
        "market_regime": 0,
        "sector_strength": 0,
        "momentum_persistence": 0,
        "breakout_quality": 0,
    }
    factor_samples: dict[str, list[Candidate]] = defaultdict(list)

    for candidate in rows:
        for factor, hit in _alpha_factor_hits(candidate.alpha_features).items():
            if hit:
                factor_hits[factor] += 1
                factor_samples[factor].append(candidate)

    return (
        hit_count,
        round(mean(bonuses), 4) if bonuses else None,
        round(median(bonuses), 4) if bonuses else None,
        factor_hits,
        factor_samples,
    )


def _format_alpha_stats(title: str, candidates: Iterable[Candidate], metric: str) -> None:
    rows = list(candidates)
    if not rows:
        print(f"{title} alpha diagnostics: no candidates")
        print()
        return

    hit_count, avg_bonus, median_bonus, factor_hits, factor_samples = _collect_alpha_hits(rows)
    total = len(rows)
    hit_rate = round(hit_count / total * 100, 1) if total else 0.0
    print(f"{title} alpha diagnostics:")
    print(
        f"  n_candidates={total} alpha_hit={hit_count} hit_rate={hit_rate}% "
        f"avg_alpha_bonus={avg_bonus if avg_bonus is not None else 'None'} "
        f"median_alpha_bonus={median_bonus if median_bonus is not None else 'None'}"
    )
    for factor, count in sorted(factor_hits.items()):
        rate = round(count / total * 100, 1) if total else 0.0
        print(f"  factor={factor} hit={count} hit_rate={rate}%")
        hits = factor_samples.get(factor, [])
        if hits:
            top_samples = sorted(hits, key=lambda c: c.alpha_bonus, reverse=True)[:3]
            for sample in top_samples:
                print(f"    sample: {_sample_label(sample, metric)}")
    print()


def _format_alpha_rank_examples(candidates: Iterable[Candidate], metric: str, top_k: int) -> None:
    rows = [c for c in candidates if c.alpha_bonus != 0]
    if not rows:
        print("Top alpha bonus samples: none")
        return
    print("Top alpha bonus samples:")
    print("  Top winners:")
    for candidate in sorted(rows, key=lambda c: c.alpha_bonus, reverse=True)[:top_k]:
        print(f"  {_sample_label(candidate, metric)}")
    print("  Lowest bonus:")
    for candidate in sorted(rows, key=lambda c: c.alpha_bonus)[:top_k]:
        print(f"  {_sample_label(candidate, metric)}")


def run(args: argparse.Namespace) -> int:
    reports = _load_daily_reports(args.data_dir)
    if args.limit_days:
        reports = reports[-args.limit_days :]

    allowed_sources = ALL_SOURCES if args.include_baseline else DEFAULT_SOURCES
    kline_cache = _build_kline_cache(reports)

    all_before: list[Candidate] = []
    all_after: list[Candidate] = []
    switched_in: list[Candidate] = []
    switched_out: list[Candidate] = []
    day_diffs: list[tuple[str, float, float, float, int]] = []
    total_candidates = 0
    skipped_no_return = 0
    skipped_days = 0

    for day, report in reports:
        candidates, skipped = _build_candidates(
            day,
            report,
            kline_cache,
            allowed_sources,
            args.entry_mode,
            args.horizon,
            args.min_forward_days,
        )
        skipped_no_return += skipped
        total_candidates += len(candidates)
        if not candidates:
            skipped_days += 1
            continue

        before_top = _top_rows(candidates, "before_score", args.top_k)
        after_top = _top_rows(candidates, "after_score", args.top_k)
        all_before.extend(before_top)
        all_after.extend(after_top)

        before_codes = {c.code for c in before_top}
        after_codes = {c.code for c in after_top}
        switched_in.extend([c for c in after_top if c.code not in before_codes])
        switched_out.extend([c for c in before_top if c.code not in after_codes])

        before_mean = _mean_metric(before_top, args.metric)
        after_mean = _mean_metric(after_top, args.metric)
        if before_mean is not None and after_mean is not None:
            overlap = len(before_codes & after_codes)
            day_diffs.append((day, before_mean, after_mean, after_mean - before_mean, overlap))

    print("===== SCORING ALPHA IMPACT BACKTEST =====")
    print(f"data_dir={args.data_dir}")
    print(f"sources={','.join(allowed_sources)} top_k={args.top_k} metric={args.metric}")
    print(f"entry_mode={args.entry_mode} horizon={args.horizon} min_forward_days={args.min_forward_days}")
    print(f"snapshot_days={len(reports)} skipped_empty_days={skipped_days}")
    print(f"candidate_universe={total_candidates} skipped_no_forward_return={skipped_no_return}")
    print()

    before_summary = _summarize(all_before, args.metric)
    after_summary = _summarize(all_after, args.metric)
    _print_summary("Before alpha", before_summary)
    _print_summary("After alpha", after_summary)
    if before_summary.get("mean") is not None and after_summary.get("mean") is not None:
        delta = float(after_summary["mean"]) - float(before_summary["mean"])
        print(f"Mean delta: {delta:+.2f} pct points")
    if before_summary.get("win_rate") is not None and after_summary.get("win_rate") is not None:
        delta = float(after_summary["win_rate"]) - float(before_summary["win_rate"])
        print(f"Win-rate delta: {delta:+.1f} pct points")
    print()

    switched_in_summary = _summarize(switched_in, args.metric)
    switched_out_summary = _summarize(switched_out, args.metric)
    _print_summary("Switched in by alpha", switched_in_summary)
    _print_summary("Switched out by alpha", switched_out_summary)
    if switched_in_summary.get("mean") is not None and switched_out_summary.get("mean") is not None:
        delta = float(switched_in_summary["mean"]) - float(switched_out_summary["mean"])
        print(f"Switch contribution delta: {delta:+.2f} pct points")
    print()

    _format_alpha_stats("Before alpha", all_before, args.metric)
    _format_alpha_stats("After alpha", all_after, args.metric)
    _format_alpha_stats("Switched in by alpha", switched_in, args.metric)
    _format_alpha_stats("Switched out by alpha", switched_out, args.metric)
    print()

    if day_diffs:
        avg_overlap = mean(row[4] for row in day_diffs)
        improved = sum(1 for row in day_diffs if row[3] > 0)
        print(
            f"Day-level: evaluated_days={len(day_diffs)} improved_days={improved} "
            f"({improved / len(day_diffs) * 100:.1f}%) avg_topK_overlap={avg_overlap:.2f}/{args.top_k}"
        )
        print("Best alpha days:")
        for day, before_mean, after_mean, delta, overlap in sorted(day_diffs, key=lambda x: x[3], reverse=True)[: args.details]:
            print(f"  {day}: before={before_mean:.2f}% after={after_mean:.2f}% delta={delta:+.2f}% overlap={overlap}")
        print("Worst alpha days:")
        for day, before_mean, after_mean, delta, overlap in sorted(day_diffs, key=lambda x: x[3])[: args.details]:
            print(f"  {day}: before={before_mean:.2f}% after={after_mean:.2f}% delta={delta:+.2f}% overlap={overlap}")
        print()

    print("Top switched-in winners:")
    switched_in_winners = [c for c in switched_in if _metric(c, args.metric) is not None]
    for candidate in sorted(switched_in_winners, key=lambda c: _metric(c, args.metric) or -999, reverse=True)[: args.details]:
        print(f"  {_sample_label(candidate, args.metric)}")
    print("Top switched-in losers:")
    for candidate in sorted(switched_in_winners, key=lambda c: _metric(c, args.metric) or 999)[: args.details]:
        print(f"  {_sample_label(candidate, args.metric)}")

    _format_alpha_rank_examples(all_after, args.metric, args.details)

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest scoring alpha before/after ranking impact.")
    parser.add_argument("--data-dir", default=os.path.join(ROOT, "docs", "data"))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--metric", default="t3_close_pct", choices=["t1_close_pct", "t3_close_pct", "t5_close_pct", "max_up_3d", "max_dd_3d"])
    parser.add_argument("--entry-mode", default="immediate_close", choices=["immediate_close", "delay1_open", "delay1_close"])
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--min-forward-days", type=int, default=3)
    parser.add_argument("--limit-days", type=int, default=None)
    parser.add_argument("--details", type=int, default=5)
    parser.add_argument("--include-baseline", action="store_true", help="include picks_pure baseline candidates in the top-K universe")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
