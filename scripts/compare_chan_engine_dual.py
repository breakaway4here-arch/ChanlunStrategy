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
from chanlun.engine_pipeline import analyze_with_provider_bundle
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="run_outputs/chan_engine_dual_compare.json")
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

    report = {
        "summary": {
            "all_equal": all_equal,
            "scenario_count": len(scenarios),
            "candidate": candidate_name,
        },
        "scenarios": scenarios,
    }

    if experiment_name is not None:
        report["summary"]["experiment"] = experiment_name

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"wrote {args.output}")
    return 0 if all_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
