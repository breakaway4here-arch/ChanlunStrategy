"""Run Phase 6.7 policy-only backtest experiments."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chanlun.policy_experiment_metrics import (
    run_policy_experiment_metrics,
    supports_policy_experiment,
)


def _normalize_policies(policies_arg: str) -> List[str]:
    seen = set()
    policies: List[str] = []
    for name in policies_arg.split(","):
        clean = name.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        policies.append(clean)
    return policies


def _table_row(name: str, result: Dict[str, Any]) -> str:
    coverage = result.get("coverage") or {}
    baseline = result.get("baseline_summary") or {}
    policy = result.get("policy_summary") or {}
    delta = result.get("delta") or {}
    reasons = ", ".join(
        f"{key}:{value}" for key, value in sorted(
            (result.get("coverage", {}).get("policy_filtered_by_reason", {}) or {}).items(),
        )
    )
    return (
        f"| {name}"
        f"| {coverage.get('snapshot_days', 'n/a')}"
        f"| {coverage.get('picks_seen', 'n/a')}"
        f"| {baseline.get('n') if baseline is not None else 'n/a'}"
        f"| {baseline.get('t3_mean') if baseline is not None else 'n/a'}"
        f"| {policy.get('n') if policy is not None else 'n/a'}"
        f"| {policy.get('t3_mean') if policy is not None else 'n/a'}"
        f"| {delta.get('t3_mean_delta') if delta else 'n/a'}"
        f"| {delta.get('t3_win_rate_delta') if delta else 'n/a'}"
        f"| {coverage.get('policy_filtered', 'n/a')}"
        f"| {coverage.get('retained_ratio_pct', 'n/a')}"
        f"| {reasons or '-'} |"
    )


def _render_markdown(payload: Dict[str, Any]) -> str:
    results = payload.get("policies", []) if isinstance(payload, dict) else []
    execution = (payload or {}).get("execution") or {}

    lines = [
        "# ChanLun Policy Backtest",
        "",
        f"- Generated: {datetime.now().isoformat()}",
        "",
        "| Policy | Snapshot Days | Picks Seen | Baseline n | Baseline T+3 | Policy n | Policy T+3 | ΔT+3 | ΔT+3 Win Rate | Filtered | Retained % | Filtered By Reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_table_row(item.get("policy"), item) for item in results)
    lines.append("")

    lines.append("## Filter Reason Summary")
    for item in results:
        name = item.get("policy", "unknown")
        coverage = (item.get("coverage") or {}).get("policy_filtered_by_reason", {})
        if not coverage:
            lines.append(f"- {name}: none")
            continue
        reason_text = ", ".join(f"{k}:{v}" for k, v in sorted(coverage.items()))
        lines.append(f"- {name}: {reason_text}")
    if not results:
        lines.append("- no policy results")
    lines.append("")

    has_detail_reasons = any(
        (item.get("coverage") or {}).get("policy_filtered_detail_by_reason")
        for item in results
    )
    if has_detail_reasons:
        lines.append("## Filter Detail Reason Summary")
        for item in results:
            name = item.get("policy", "unknown")
            coverage = (item.get("coverage") or {}).get("policy_filtered_detail_by_reason", {})
            if not coverage:
                lines.append(f"- {name}: none")
                continue
            reason_text = ", ".join(f"{k}:{v}" for k, v in sorted(coverage.items()))
            lines.append(f"- {name}: {reason_text}")
        lines.append("")

    if execution:
        lines.append("## Execution Summary")
        lines.extend(
            [
                f"- shared_baseline: {execution.get('shared_baseline', 'n/a')}",
                f"- snapshot_rows: {execution.get('snapshot_rows', 'n/a')}",
                f"- unique_codes: {execution.get('unique_codes', 'n/a')}",
                f"- fetch_attempts: {execution.get('fetch_attempts', 'n/a')}",
                f"- cache_hits: {execution.get('cache_hits', 'n/a')}",
                f"- kline_missing: {execution.get('kline_missing', 'n/a')}",
                f"- kline_invalid: {execution.get('kline_invalid', 'n/a')}",
                f"- baseline_rows: {execution.get('baseline_rows', 'n/a')}",
                "",
            ],
        )
    return "\n".join(lines)


def _write_outputs(output_json: str, output_md: str, payload: Dict[str, Any]) -> None:
    json_path = Path(output_json)
    md_path = Path(output_md)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with md_path.open("w", encoding="utf-8") as f:
        f.write(_render_markdown(payload))


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run phase 6.7 policy backtest experiments.")
    parser.add_argument("--policies", required=True, help="Comma-separated policy names")
    parser.add_argument("--output-json", required=True, help="Output JSON path")
    parser.add_argument("--output-md", required=True, help="Output Markdown path")

    args = parser.parse_args(argv)
    policies = _normalize_policies(args.policies)

    if not policies:
        print("--policies must contain at least one policy", file=sys.stderr)
        return 2

    unknown = [name for name in policies if not supports_policy_experiment(name)]
    if unknown:
        print(f"unknown policy: {', '.join(unknown)}", file=sys.stderr)
        return 1

    try:
        payload = {"generated_at": datetime.now().isoformat()}
        payload.update(run_policy_experiment_metrics(policies))
    except Exception as exc:
        print(f"failed to run policies: {exc}", file=sys.stderr)
        return 1

    try:
        _write_outputs(args.output_json, args.output_md, payload)
    except OSError as exc:
        print(f"failed to write output: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
