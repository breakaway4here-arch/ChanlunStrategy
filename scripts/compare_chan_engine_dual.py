"""Run deterministic ChanLun dual-compare scenarios and write a JSON report."""

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chanlun.chan_engine import analyze_dual
from chanlun.engine_candidate_registry import list_candidate_definitions
from chanlun.engine_dual_metrics import (
    build_aggregate_dual_business_metrics,
    result_to_recommendations,
)
from chanlun.engine_experiments import list_experiments
from tests.test_chan_engine_snapshot import SCENARIOS


def _make_kline(closes):
    closes = np.asarray(closes, dtype=float)
    return {
        "dates": list(range(len(closes))),
        "opens": closes.copy(),
        "highs": closes + 0.6,
        "lows": closes - 0.6,
        "closes": closes,
        "volumes": np.array([1000.0] * len(closes), dtype=float),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="run_outputs/chan_engine_dual_compare.json")
    parser.add_argument(
        "--business-metrics",
        action="store_true",
        help="include recommendation diff and return-metrics placeholders",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--candidate",
        choices=("legacy", *list_candidate_definitions()),
        default=None,
        help=(
            "candidate registry name (e.g. signal, signal_v1, "
            "signal_delay1_by_type_guard)"
        ),
    )
    mode.add_argument(
        "--experiment",
        choices=tuple(list_experiments()),
        default=None,
        help="compatibility alias for experiment registry names",
    )
    args = parser.parse_args()

    candidate_name = args.candidate
    experiment_name = args.experiment

    if candidate_name is None and experiment_name is None:
        candidate_name = "legacy"

    if experiment_name is not None:
        dual_candidate = None if experiment_name == "legacy" else experiment_name
        summary_candidate = "legacy"
    else:
        dual_candidate = None if candidate_name == "legacy" else candidate_name
        summary_candidate = candidate_name

    scenarios = {}
    all_equal = True
    legacy_recommendations = []
    candidate_recommendations = []
    for name, closes in SCENARIOS.items():
        kline = _make_kline(closes)
        payload = analyze_dual(
            code=name,
            name=name,
            dates=kline["dates"],
            opens=kline["opens"],
            highs=kline["highs"],
            lows=kline["lows"],
            closes=kline["closes"],
            volumes=kline["volumes"],
            candidate=dual_candidate,
        )
        comparison = payload["comparison"]
        scenarios[name] = comparison
        all_equal = all_equal and comparison["equal"]
        if args.business_metrics:
            legacy_recommendations.extend(
                result_to_recommendations(payload.get("legacy"))
            )
            candidate_recommendations.extend(
                result_to_recommendations(payload.get("candidate"))
            )

    if args.business_metrics:
        business_metrics = build_aggregate_dual_business_metrics(
            legacy_recommendations,
            candidate_recommendations,
            return_metrics={
                "status": "no_market_data",
                "legacy": None,
                "experiment": None,
            },
            coverage={
                "evaluated": 0,
                "skipped_no_market_data": len(scenarios),
                "reason": "Phase 5.2 runs on in-memory SCENARIOS only; no market fetch",
            },
        )

    report = {
        "summary": {
            "all_equal": all_equal,
            "scenario_count": len(scenarios),
            "candidate": summary_candidate,
        },
        "scenarios": scenarios,
    }

    if dual_candidate is not None:
        report["summary"]["candidate_registry_name"] = dual_candidate

    if args.business_metrics:
        report["summary"].update(
            {
                "structure_equal": all_equal,
                "recommendation_diff": business_metrics["recommendation_diff"],
                "return_metrics": business_metrics["return_metrics"],
                "coverage": business_metrics["coverage"],
            }
        )

    if experiment_name is not None:
        report["summary"]["experiment"] = experiment_name

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"wrote {args.output}")
    return 0 if all_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
