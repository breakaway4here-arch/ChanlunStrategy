"""Run deterministic ChanLun dual-compare scenarios and write a JSON report."""

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chanlun.chan_engine import analyze_dual
from chanlun.engine_candidate import (
    analyze_with_candidate_inclusion,
    analyze_with_candidate_macd,
)
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
        "--candidate",
        choices=("legacy", "macd", "inclusion"),
        default="legacy",
    )
    args = parser.parse_args()

    scenarios = {}
    all_equal = True
    candidate_analyzers = {
        "legacy": None,
        "macd": analyze_with_candidate_macd,
        "inclusion": analyze_with_candidate_inclusion,
    }
    candidate_analyzer = candidate_analyzers[args.candidate]

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
            "candidate": args.candidate,
        },
        "scenarios": scenarios,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"wrote {args.output}")
    return 0 if all_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
