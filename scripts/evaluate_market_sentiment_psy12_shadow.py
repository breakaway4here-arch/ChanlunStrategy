#!/usr/bin/env python3
"""Read-only PSY12 shadow audit for manual production review."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanlun.market_sentiment import build_market_sentiment_psy12_shadow


PSY12_AUDIT_KEYS = (
    "status",
    "reason",
    "score",
    "up_days",
    "valid_days",
    "window",
    "start_date",
    "end_date",
    "daily_directions",
)
SHADOW_AUDIT_KEYS = (
    "schema_version",
    "mode",
    "status",
    "reason",
    "affects_production",
    "formal_score",
    "raw_shadow_score_with_psy12",
    "shadow_score_with_psy12",
    "delta_vs_formal",
    "formal_label",
    "shadow_label",
    "weight_version",
    "weights",
)


def _projection(value, keys):
    source = value if isinstance(value, dict) else {}
    return {key: source.get(key) for key in keys}


def _pearson(rows, component):
    pairs = [
        (row.get("psy12_score"), row.get("components", {}).get(component))
        for row in rows
    ]
    pairs = [
        (float(left), float(right))
        for left, right in pairs
        if isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and math.isfinite(float(left))
        and math.isfinite(float(right))
    ]
    if len(pairs) < 2:
        return None
    left_mean = sum(left for left, _ in pairs) / len(pairs)
    right_mean = sum(right for _, right in pairs) / len(pairs)
    numerator = sum(
        (left - left_mean) * (right - right_mean)
        for left, right in pairs
    )
    left_scale = math.sqrt(sum((left - left_mean) ** 2 for left, _ in pairs))
    right_scale = math.sqrt(sum((right - right_mean) ** 2 for _, right in pairs))
    if left_scale == 0 or right_scale == 0:
        return None
    return round(numerator / (left_scale * right_scale), 4)


def _hypothetical_changes(rows):
    changes = []
    for row in rows:
        formal_score = row["formal_score"]
        shadow_score = row["shadow_score"]
        day_changes = []
        if shadow_score != formal_score:
            day_changes.append("market_temperature_score")
        if row["formal_label"] != row["shadow_label"]:
            day_changes.append("market_temperature_label")
        if (formal_score < 40) != (shadow_score < 40):
            day_changes.append("decision_gate_cold_market_threshold")
        if day_changes:
            changes.append({
                "date": row["date"],
                "changes": day_changes,
                "formal_score": formal_score,
                "shadow_score": shadow_score,
            })
    return changes


def evaluate_shadow_reports(reports, required_days=20):
    """Recompute stored shadow fields and return a non-promoting audit."""

    required_days = max(1, int(required_days))
    rows = []
    ordered = sorted(
        (report for report in (reports or []) if isinstance(report, dict)),
        key=lambda report: str(report.get("date") or ""),
    )
    for report in ordered:
        formal = report.get("market_sentiment")
        history = report.get("market_sentiment_history")
        if not isinstance(formal, dict) or not isinstance(history, list):
            continue
        recomputed = build_market_sentiment_psy12_shadow(formal, history)
        psy12 = recomputed["psy12"]
        shadow = recomputed["psy12_shadow"]
        if psy12.get("status") != "available" or shadow.get("status") != "available":
            continue
        stored_match = (
            _projection(report.get("psy12"), PSY12_AUDIT_KEYS)
            == _projection(psy12, PSY12_AUDIT_KEYS)
            and _projection(report.get("psy12_shadow"), SHADOW_AUDIT_KEYS)
            == _projection(shadow, SHADOW_AUDIT_KEYS)
        )
        rows.append({
            "date": formal.get("date") or report.get("date"),
            "formal_score": shadow["formal_score"],
            "shadow_score": shadow["shadow_score_with_psy12"],
            "delta": shadow["delta_vs_formal"],
            "formal_label": shadow["formal_label"],
            "shadow_label": shadow["shadow_label"],
            "label_changed": shadow["formal_label"] != shadow["shadow_label"],
            "psy12_score": psy12["score"],
            "psy12_window": [psy12["start_date"], psy12["end_date"]],
            "components": dict(formal.get("components") or {}),
            "recalculation_match": stored_match,
        })

    selected = rows[-required_days:]
    match_count = sum(row["recalculation_match"] for row in selected)
    consistency_rate = (
        round(match_count / len(selected), 4)
        if selected
        else 0.0
    )
    deltas = [float(row["delta"]) for row in selected]
    status = "insufficient_observation_days"
    if len(selected) >= required_days:
        status = (
            "ready_for_manual_review"
            if consistency_rate == 1.0
            else "recalculation_mismatch"
        )
    return {
        "schema_version": 1,
        "mode": "psy12_shadow_audit",
        "status": status,
        "required_days": required_days,
        "valid_days": len(selected),
        "recalculation_consistency_rate": consistency_rate,
        "summary": {
            "average_delta": round(sum(deltas) / len(deltas), 4) if deltas else None,
            "maximum_absolute_delta": round(max(map(abs, deltas)), 4) if deltas else None,
            "label_change_count": sum(row["label_changed"] for row in selected),
        },
        "correlations": {
            "breadth": _pearson(selected, "breadth"),
            "index": _pearson(selected, "index"),
        },
        "hypothetical_changes": _hypothetical_changes(selected),
        "daily": selected,
        "affects_production": False,
        "promotion_eligible": False,
        "promotion_requires_new_authorization": True,
    }


def _load_reports(data_dir, as_of=None):
    reports = []
    for path in sorted(Path(data_dir).glob("????-??-??.json")):
        if as_of and path.stem > as_of:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(report, dict):
            reports.append(report)
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(ROOT / "docs" / "data"))
    parser.add_argument("--as-of")
    parser.add_argument("--required-days", type=int, default=20)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    result = evaluate_shadow_reports(
        _load_reports(args.data_dir, args.as_of),
        required_days=args.required_days,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
