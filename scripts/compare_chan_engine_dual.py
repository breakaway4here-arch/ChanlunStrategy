"""Run deterministic ChanLun dual-compare scenarios and write a JSON report."""

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chanlun.chan_engine import analyze_dual
from chanlun.engine_candidate import CANDIDATE_ANALYZERS
from chanlun.engine_experiments import build_experiment_provider_bundle, list_experiments
from chanlun.experiment_metrics import compare_recommendations
from chanlun.engine_pipeline import analyze_with_provider_bundle
from tests.test_chan_engine_snapshot import SCENARIOS


def _to_recommendations(result):
    if result is None or not getattr(result, "buy_points", None):
        return []
    return [
        {"code": result.code, "best_buy_point": bp}
        for bp in result.buy_points
        if isinstance(bp, dict)
    ]


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


def _analyze_with_experiment_bundle(providers):
    def analyze(code, name, dates, opens, highs, lows, closes, volumes):
        return analyze_with_provider_bundle(
            code,
            name,
            dates,
            opens,
            highs,
            lows,
            closes,
            volumes,
            providers=providers,
        )

    return analyze


def _calculate_business_metrics(legacy_results, candidate_results, scenario_count):
    return {
        "recommendation_diff": compare_recommendations(
            legacy_results,
            candidate_results,
        ),
        "return_metrics": {
            "status": "no_market_data",
            "legacy": None,
            "experiment": None,
        },
        "coverage": {
            "evaluated": 0,
            "skipped_no_market_data": scenario_count,
            "reason": "Phase 5.2 runs on in-memory SCENARIOS only; no market fetch",
        },
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
        choices=("legacy", *CANDIDATE_ANALYZERS.keys()),
        default=None,
    )
    mode.add_argument(
        "--experiment",
        choices=tuple(list_experiments()),
        default=None,
    )
    args = parser.parse_args()

    candidate_name = args.candidate
    experiment_name = args.experiment

    if candidate_name is None and experiment_name is None:
        candidate_name = "legacy"

    scenarios = {}
    all_equal = True
    candidate_analyzer = None
    if experiment_name is not None:
        experiment_providers = build_experiment_provider_bundle(experiment_name)
        candidate_analyzer = _analyze_with_experiment_bundle(experiment_providers)
        candidate_name = "legacy"
    elif candidate_name != "legacy":
        candidate_analyzer = CANDIDATE_ANALYZERS[candidate_name]

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
            candidate_analyzer=candidate_analyzer,
        )
        comparison = payload["comparison"]
        scenarios[name] = comparison
        all_equal = all_equal and comparison["equal"]
        if args.business_metrics:
            legacy_recommendations.extend(_to_recommendations(payload.get("legacy")))
            candidate_recommendations.extend(_to_recommendations(payload.get("candidate")))

    if args.business_metrics:
        business_metrics = _calculate_business_metrics(
            legacy_recommendations,
            candidate_recommendations,
            scenario_count=len(scenarios),
        )

    report = {
        "summary": {
            "all_equal": all_equal,
            "scenario_count": len(scenarios),
            "candidate": candidate_name,
        },
        "scenarios": scenarios,
    }

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
