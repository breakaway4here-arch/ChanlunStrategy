#!/usr/bin/env python3
"""Strict as-of, network-free walk-forward scan for recall thresholds."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from chanlun.market_history_store import MarketHistoryStore
from chanlun.policy_experiment_metrics import (
    evaluate_recall_acceptance_gates,
    threshold_selection_stability,
)


DEFAULT_THRESHOLD_GRID = {
    "low_distance_pct": (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0),
    "chase_guard_pct": (8.0, 10.0, 12.0, 14.0, 16.0, 20.0),
    "volume_ratio": (1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0),
    "ma_policy": (
        "strict_bull",
        "gap_neg025_ema5_up",
        "gap_neg05_above_ema10",
        "rank_only",
    ),
}

BASELINE_THRESHOLDS = {
    "low_distance_pct": 3.0,
    "chase_guard_pct": 12.0,
    "volume_ratio": 1.5,
    "ma_policy": "strict_bull",
}

_MA_STRENGTH = {
    "rank_only": 0,
    "gap_neg05_above_ema10": 1,
    "gap_neg025_ema5_up": 2,
    "strict_bull": 3,
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_walkforward_blocks(
    trading_dates: Sequence[str],
    train_days: int = 30,
    embargo_days: int = 3,
    test_block_days: int = 4,
    block_count: int = 5,
) -> List[Dict[str, Any]]:
    dates = sorted(dict.fromkeys(str(value) for value in trading_dates))
    required = train_days + embargo_days + test_block_days * block_count
    if len(dates) < required:
        raise ValueError(
            "walk-forward requires at least {} trading dates".format(required)
        )
    dates = dates[-required:]
    blocks = []
    for index in range(block_count):
        test_start = train_days + embargo_days + index * test_block_days
        train_end = test_start - embargo_days
        blocks.append({
            "fold": index + 1,
            "train_dates": dates[:train_end],
            "embargo_dates": dates[train_end:test_start],
            "test_dates": dates[test_start:test_start + test_block_days],
        })
    return blocks


def _sample_ma_policy(sample: Mapping[str, Any]) -> str:
    explicit = str(sample.get("ma_policy") or "")
    if explicit in _MA_STRENGTH:
        return explicit
    try:
        ma5 = float(sample.get("ma5"))
        ma10 = float(sample.get("ma10"))
        ma20 = float(sample.get("ma20"))
        gap = float(sample.get("ma_gap_pct"))
        close = float(sample.get("close"))
        ema5_slope = float(sample.get("ema5_slope"))
    except (TypeError, ValueError):
        return "rank_only"
    if ma5 >= ma10 >= ma20:
        return "strict_bull"
    if gap > -0.25 and ema5_slope > 0:
        return "gap_neg025_ema5_up"
    if gap > -0.5 and close >= ma10:
        return "gap_neg05_above_ema10"
    return "rank_only"


def _accepted(sample: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    try:
        distance = abs(float(
            sample.get("distance_from_reference_pct")
        ))
        chase_distance = float(
            sample.get("chase_distance_pct", distance)
        )
        volume_ratio = float(sample.get("volume_ratio"))
    except (TypeError, ValueError):
        return False
    channel = str(sample.get("source_channel") or "low_position")
    if channel == "trend":
        if chase_distance > float(config["chase_guard_pct"]):
            return False
    elif distance > float(config["low_distance_pct"]):
        return False
    if volume_ratio < float(config["volume_ratio"]):
        return False
    actual_ma = _MA_STRENGTH.get(_sample_ma_policy(sample), 0)
    required_ma = _MA_STRENGTH[str(config["ma_policy"])]
    return actual_ma >= required_ma


def _metrics(
    samples: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    accepted = [sample for sample in samples if _accepted(sample, config)]
    main_accepted = [
        sample for sample in accepted
        if not bool(sample.get("is_observation"))
    ]
    top20_total = sum(bool(sample.get("is_top20")) for sample in samples)
    top30_total = sum(bool(sample.get("is_top30")) for sample in samples)
    top20_hit = sum(bool(sample.get("is_top20")) for sample in accepted)
    top30_hit = sum(bool(sample.get("is_top30")) for sample in accepted)
    returns = [float(sample["t3_return_pct"]) for sample in main_accepted]
    drawdowns = [float(sample["max_dd_3d"]) for sample in main_accepted]
    median_return = float(statistics.median(returns)) if returns else -999.0
    tail_rate = (
        sum(value <= -5.0 for value in drawdowns) / len(drawdowns)
        if drawdowns else 1.0
    )
    top20_recall = top20_hit / top20_total if top20_total else 0.0
    top30_recall = top30_hit / top30_total if top30_total else 0.0
    objective = (
        top20_recall
        + 0.5 * top30_recall
        + 0.01 * median_return
        - 0.25 * tail_rate
    )
    return {
        "accepted": len(accepted),
        "main_accepted": len(main_accepted),
        "observation_count": len(accepted) - len(main_accepted),
        "top20_hit": top20_hit,
        "top20_total": top20_total,
        "top20_recall": round(top20_recall, 6),
        "top30_hit": top30_hit,
        "top30_total": top30_total,
        "top30_recall": round(top30_recall, 6),
        "t3_median": None if not returns else round(median_return, 6),
        "tail_risk_rate": round(tail_rate, 6),
        "objective": round(objective, 9),
    }


def _scan_factor(
    samples: Sequence[Mapping[str, Any]],
    factor: str,
    grid: Mapping[str, Sequence[Any]],
) -> List[Dict[str, Any]]:
    results = []
    for value in grid[factor]:
        config = dict(BASELINE_THRESHOLDS)
        config[factor] = value
        results.append({
            "value": value,
            "config": config,
            "metrics": _metrics(samples, config),
        })
    return results


def _best_adjacent(
    scan: Sequence[Mapping[str, Any]],
    ordered_values: Sequence[Any],
) -> List[Any]:
    ranked = sorted(
        scan,
        key=lambda row: (
            -float(row["metrics"]["objective"]),
            ordered_values.index(row["value"]),
        ),
    )
    best = ranked[0]["value"]
    best_index = ordered_values.index(best)
    neighbors = {
        ordered_values[index]
        for index in (best_index - 1, best_index + 1)
        if 0 <= index < len(ordered_values)
    }
    neighbor = next(
        (
            row["value"]
            for row in ranked[1:]
            if row["value"] in neighbors
        ),
        best,
    )
    return [best, neighbor] if neighbor != best else [best]


def _candidate_combinations(
    adjacent: Mapping[str, Sequence[Any]],
) -> List[Dict[str, Any]]:
    factors = list(DEFAULT_THRESHOLD_GRID)
    candidates = []
    for position in (0, 1):
        config = dict(BASELINE_THRESHOLDS)
        for factor in factors:
            values = list(adjacent[factor])
            config[factor] = values[min(position, len(values) - 1)]
        candidates.append(config)
    for factor in factors:
        for value in adjacent[factor]:
            config = dict(BASELINE_THRESHOLDS)
            config[factor] = value
            candidates.append(config)
    unique = []
    seen = set()
    for config in candidates:
        key = _canonical_json(config)
        if key in seen:
            continue
        seen.add(key)
        unique.append(config)
    return unique


def _select_config(
    samples: Sequence[Mapping[str, Any]],
    grid: Mapping[str, Sequence[Any]],
) -> Dict[str, Any]:
    scans = {
        factor: _scan_factor(samples, factor, grid)
        for factor in grid
    }
    adjacent = {
        factor: _best_adjacent(scans[factor], list(grid[factor]))
        for factor in grid
    }
    combinations = _candidate_combinations(adjacent)
    scored = [
        {"config": config, "metrics": _metrics(samples, config)}
        for config in combinations
    ]
    selected = sorted(
        scored,
        key=lambda row: (
            -float(row["metrics"]["objective"]),
            _canonical_json(row["config"]),
        ),
    )[0]
    return {
        "single_factor_scan": scans,
        "adjacent": adjacent,
        "combinations": scored,
        "selected": selected,
    }


def _git_version() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_recall_walkforward(
    samples: Sequence[Mapping[str, Any]],
    threshold_grid: Mapping[str, Sequence[Any]] = DEFAULT_THRESHOLD_GRID,
    bootstrap_iterations: int = 1000,
    random_seed: int = 0,
    code_version: Optional[str] = None,
) -> Dict[str, Any]:
    rows = [dict(sample) for sample in samples]
    if any(row.get("t3_return_pct") is None for row in rows):
        raise ValueError("all walk-forward samples require strict T+3 labels")
    if any(row.get("max_dd_3d") is None for row in rows):
        raise ValueError("all walk-forward samples require T+3 drawdown labels")
    dates = sorted({str(row["signal_date"]) for row in rows})
    blocks = build_walkforward_blocks(dates)
    block_results = []
    selected_by_factor = defaultdict(list)
    candidate_test_rows = []
    baseline_test_rows = []
    observation_counts = []
    for block in blocks:
        train_set = set(block["train_dates"])
        test_set = set(block["test_dates"])
        train_rows = [
            row for row in rows if row["signal_date"] in train_set
        ]
        test_rows = [
            row for row in rows if row["signal_date"] in test_set
        ]
        selection = _select_config(train_rows, threshold_grid)
        selected_config = selection["selected"]["config"]
        for factor, value in selected_config.items():
            selected_by_factor[factor].append(value)
        accepted_test = [
            row for row in test_rows if _accepted(row, selected_config)
        ]
        candidate_test_rows.extend(
            row
            for row in accepted_test
            if not bool(row.get("is_observation"))
        )
        baseline_test_rows.extend(
            row for row in test_rows if bool(row.get("baseline_accepted"))
        )
        by_date = defaultdict(int)
        for row in accepted_test:
            if bool(row.get("is_observation")):
                by_date[row["signal_date"]] += 1
        observation_counts.extend(
            by_date.get(signal_date, 0)
            for signal_date in block["test_dates"]
        )
        block_results.append({
            **block,
            "selected_config": selected_config,
            "train_metrics": selection["selected"]["metrics"],
            "test_metrics": _metrics(test_rows, selected_config),
        })

    stability_by_factor = {
        factor: threshold_selection_stability(
            selected_by_factor[factor],
            threshold_grid[factor],
        )
        for factor in threshold_grid
    }
    volume_stability = stability_by_factor["volume_ratio"]
    gates = evaluate_recall_acceptance_gates(
        baseline_returns=[
            float(row["t3_return_pct"]) for row in baseline_test_rows
        ],
        candidate_returns=[
            float(row["t3_return_pct"]) for row in candidate_test_rows
        ],
        baseline_drawdowns=[
            float(row["max_dd_3d"]) for row in baseline_test_rows
        ],
        candidate_drawdowns=[
            float(row["max_dd_3d"]) for row in candidate_test_rows
        ],
        observation_counts=observation_counts,
        selected_thresholds=selected_by_factor["volume_ratio"],
        ordered_thresholds=threshold_grid["volume_ratio"],
        bootstrap_iterations=bootstrap_iterations,
        seed=random_seed,
    )
    gates["threshold_stability"] = {
        **volume_stability,
        "by_factor": stability_by_factor,
    }
    gates["accepted"] = (
        gates["accepted"]
        and all(item["accepted"] for item in stability_by_factor.values())
    )
    baseline_low = [
        row for row in baseline_test_rows
        if str(row.get("source_channel") or "") == "low_position"
    ]
    candidate_low = [
        row for row in candidate_test_rows
        if str(row.get("source_channel") or "") == "low_position"
    ]
    baseline_low_tail = (
        100.0 * sum(float(row["max_dd_3d"]) <= -5.0 for row in baseline_low)
        / len(baseline_low)
        if baseline_low else 0.0
    )
    candidate_low_tail = (
        100.0 * sum(float(row["max_dd_3d"]) <= -5.0 for row in candidate_low)
        / len(candidate_low)
        if candidate_low else 0.0
    )
    low_tail_delta = round(candidate_low_tail - baseline_low_tail, 6)
    gates["low_position_tail_risk"] = {
        "baseline_pct": round(baseline_low_tail, 6),
        "candidate_pct": round(candidate_low_tail, 6),
        "delta_pp": low_tail_delta,
        "accepted": low_tail_delta <= 2.0,
    }
    gates["checks"]["low_position_tail_risk"] = (
        low_tail_delta <= 2.0
    )
    gates["accepted"] = (
        gates["accepted"] and low_tail_delta <= 2.0
    )

    overall_selection = _select_config(rows, threshold_grid)
    config_payload = {
        "threshold_grid": {
            key: list(values) for key, values in threshold_grid.items()
        },
        "baseline": BASELINE_THRESHOLDS,
        "train_days": 30,
        "embargo_days": 3,
        "test_block_days": 4,
        "block_count": 5,
    }
    return {
        "schema_version": 1,
        "network_requests": 0,
        "sample_count": len(rows),
        "date_count": len(dates),
        "coverage": {
            "samples": len(rows),
            "dates": len(dates),
            "codes": len({str(row.get("code")) for row in rows}),
            "top20_labels": sum(bool(row.get("is_top20")) for row in rows),
            "top30_labels": sum(bool(row.get("is_top30")) for row in rows),
            "baseline_main": sum(
                bool(row.get("baseline_accepted")) for row in rows
            ),
            "observations": sum(
                bool(row.get("is_observation")) for row in rows
            ),
        },
        "data_hash": _hash(rows),
        "config_hash": _hash(config_payload),
        "code_version": code_version or _git_version(),
        "single_factor_scan": overall_selection["single_factor_scan"],
        "adjacent_thresholds": overall_selection["adjacent"],
        "adjacent_combinations": overall_selection["combinations"],
        "blocks": block_results,
        "acceptance_gates": gates,
    }


def load_walkforward_samples(database_path: Any) -> List[Dict[str, Any]]:
    """Build strictly labeled samples from official funnel runs and final bars."""
    with MarketHistoryStore(
        database_path, readonly=True, immutable=True
    ) as store:
        run_rows = store.connection.execute(
            """
            SELECT * FROM funnel_runs
            ORDER BY report_date, updated_at
            """
        ).fetchall()
        official_runs = {}
        for raw in run_rows:
            row = dict(raw)
            metadata = json.loads(row["metadata_json"])
            if bool(metadata.get("is_official")) and row["as_of"] <= row["report_date"]:
                official_runs[str(row["report_date"])] = row
        trading_dates = [
            str(row["ts"]).split(" ", 1)[0]
            for row in store.connection.execute(
                """
                SELECT DISTINCT ts FROM bars_day
                WHERE is_final=1 ORDER BY ts
                """
            ).fetchall()
        ]
        trading_dates = sorted(dict.fromkeys(trading_dates))
        date_index = {value: index for index, value in enumerate(trading_dates)}
        instruments = store.list_instruments(asset_type="stock")
        by_code = {
            str(row["code"]): int(row["instrument_id"])
            for row in instruments
        }
        samples = []
        for signal_date, run in sorted(official_runs.items()):
            index = date_index.get(signal_date)
            if index is None or index + 3 >= len(trading_dates):
                continue
            next_date = trading_dates[index + 1]
            t3_date = trading_dates[index + 3]
            events = store.list_gate_events(run["run_id"])
            ids = [
                by_code[event["code"]]
                for event in events
                if event.get("code") in by_code
            ]
            bars_by_id = store.query_bars_many(
                "day",
                ids,
                start=signal_date,
                end=t3_date,
                as_of=t3_date,
            )
            provisional = []
            for event in events:
                instrument_id = by_code.get(str(event.get("code")))
                if instrument_id is None:
                    continue
                bars = {
                    str(row["ts"]).split(" ", 1)[0]: row
                    for row in bars_by_id.get(instrument_id, [])
                    if bool(row.get("is_final"))
                }
                if signal_date not in bars or next_date not in bars or t3_date not in bars:
                    continue
                signal_close = float(bars[signal_date]["close"])
                if signal_close <= 0:
                    continue
                next_gain = (
                    float(bars[next_date]["close"]) / signal_close - 1.0
                ) * 100.0
                path = [
                    float(row["low"])
                    for row in bars_by_id[instrument_id]
                    if signal_date < str(row["ts"]).split(" ", 1)[0] <= t3_date
                ]
                t3_return = (
                    float(bars[t3_date]["close"]) / signal_close - 1.0
                ) * 100.0
                max_drawdown = min(
                    ((value / signal_close - 1.0) * 100.0 for value in path),
                    default=0.0,
                )
                provisional.append({
                    **event,
                    "signal_date": signal_date,
                    "next_gain_pct": next_gain,
                    "t3_return_pct": t3_return,
                    "max_dd_3d": max_drawdown,
                    "chase_distance_pct": event.get(
                        "distance_from_reference_pct"
                    ),
                    "is_observation": event.get("final_state") == "observe",
                    "baseline_accepted": event.get("final_state") == "main",
                })
            ranked = sorted(
                provisional,
                key=lambda row: (
                    -float(row["next_gain_pct"]),
                    str(row["code"]),
                ),
            )
            for rank, sample in enumerate(ranked, start=1):
                sample["next_day_rank"] = rank
                sample["is_top20"] = rank <= 20
                sample["is_top30"] = rank <= 30
                samples.append(sample)
    return samples


def render_markdown(result: Mapping[str, Any]) -> str:
    gates = result["acceptance_gates"]
    lines = [
        "# 召回阈值 Walk-forward",
        "",
        "- 样本数：{}".format(result["sample_count"]),
        "- 日期数：{}".format(result["date_count"]),
        "- 网络请求：{}".format(result["network_requests"]),
        "- 最终门禁：{}".format("通过" if gates["accepted"] else "未通过"),
        "- 观察数 P95：{}".format(gates["attention_p95"]),
        "- 尾部风险变化：{}pp".format(gates["tail_risk_delta_pp"]),
        "",
        "| 折 | 训练截止 | 测试区间 | Top20召回 | T+3中位数 |",
        "| ---: | --- | --- | ---: | ---: |",
    ]
    for block in result["blocks"]:
        lines.append(
            "| {fold} | {train_end} | {test_start}~{test_end} | "
            "{recall} | {median} |".format(
                fold=block["fold"],
                train_end=block["train_dates"][-1],
                test_start=block["test_dates"][0],
                test_end=block["test_dates"][-1],
                recall=block["test_metrics"]["top20_recall"],
                median=block["test_metrics"]["t3_median"],
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: Iterable[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行门前召回阈值的20日样本外walk-forward"
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args(list(argv) if argv is not None else None)
    samples = load_walkforward_samples(args.db)
    result = run_recall_walkforward(
        samples,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    Path(args.output_json).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.output_md).write_text(
        render_markdown(result),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
