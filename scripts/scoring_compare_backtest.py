"""
Scoring Compare Backtest Script

Purpose:
- Compare old scoring (baseline score) vs new scoring_engine.opportunity_score
- Evaluate whether alpha changes improve selection quality

Usage:
    python scripts/scoring_compare_backtest.py

Output:
- console summary
- optional json report in docs/backtest/
"""

import os
import json
from glob import glob
from typing import Any, Dict

from chanlun.scoring_engine import compute_opportunity_score

DATA_PATH = "docs/data/*.json"
TOP_K = 10


def load_data_files():
    files = sorted(glob(DATA_PATH))
    datasets = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                datasets.append(json.load(fp))
        except Exception as e:
            print(f"skip {f}: {e}")
    return datasets


def extract_picks(day_data: Dict[str, Any]):
    """Extract all candidate pools into unified list"""
    picks = []

    for key in ["picks_pure", "picks_fusion"]:
        if key in day_data:
            for item in day_data[key]:
                item["_source"] = key
                picks.append(item)

    # luojie pool
    if "luojie_pool" in day_data and "candidates" in day_data["luojie_pool"]:
        for item in day_data["luojie_pool"]["candidates"]:
            item["_source"] = "luojie"
            picks.append(item)

    return picks


def get_baseline_score(item: Dict[str, Any]) -> float:
    """old scoring fallback"""
    return float(item.get("score", 0) or item.get("watch_score", 0))


def get_forward_return(item: Dict[str, Any]) -> float:
    """simple proxy: last - first close return"""
    closes = item.get("closes", [])
    if not closes or len(closes) < 2:
        return 0.0
    try:
        return (closes[-1] - closes[0]) / closes[0] * 100
    except:
        return 0.0


def evaluate():
    datasets = load_data_files()

    baseline_hits = 0
    new_hits = 0

    baseline_total = 0
    new_total = 0

    for day in datasets:
        picks = extract_picks(day)

        scored = []

        for p in picks:
            baseline = get_baseline_score(p)

            new_score, _ = compute_opportunity_score(
                p,
                p.get("_source", "main"),
                {"sources": [p.get("_source", "main")], "by_source": {p.get("_source", "main"): p}}
            )

            forward_ret = get_forward_return(p)

            scored.append((baseline, new_score, forward_ret))

        # topK selection
        baseline_top = sorted(scored, key=lambda x: x[0], reverse=True)[:TOP_K]
        new_top = sorted(scored, key=lambda x: x[1], reverse=True)[:TOP_K]

        baseline_total += sum(r for _, _, r in baseline_top)
        new_total += sum(r for _, _, r in new_top)

        baseline_hits += sum(1 for _, _, r in baseline_top if r > 0)
        new_hits += sum(1 for _, _, r in new_top if r > 0)

    print("\n===== BACKTEST RESULT =====")
    print(f"Baseline avg return: {baseline_total / max(len(datasets),1):.2f}%")
    print(f"New score avg return: {new_total / max(len(datasets),1):.2f}%")
    print(f"Baseline hit rate: {baseline_hits / max(len(datasets)*TOP_K,1):.2%}")
    print(f"New hit rate: {new_hits / max(len(datasets)*TOP_K,1):.2%}")


if __name__ == "__main__":
    evaluate()
