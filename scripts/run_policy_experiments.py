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
    execution_model = result.get("execution_model") or {}
    reasons = ", ".join(
        f"{key}:{value}" for key, value in sorted(
            (result.get("coverage", {}).get("policy_filtered_by_reason", {}) or {}).items(),
        )
    )
    entry_label = execution_model.get("entry_label", "-")
    entry_mode = execution_model.get("entry_mode", "-")
    exit_model = execution_model.get("exit_model", "-")
    not_evaluable = coverage.get("policy_not_evaluable", "-")
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
        f"| {entry_label}"
        f"| {entry_mode}"
        f"| {exit_model}"
        f"| {not_evaluable}"
        f"| {coverage.get('retained_ratio_pct', 'n/a')}"
        f"| {reasons or '-'} |"
    )


def _format_reason_counts(reasons: Dict[str, Any]) -> str:
    if not reasons:
        return "-"
    return ", ".join(
        f"{reason}:{count}" for reason, count in sorted(reasons.items(), key=lambda item: item[0])
    )


def _render_breakdown_section(results: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    if not any((result.get("breakdown") for result in results)):
        return lines

    lines.append("## Breakdown Summary")

    for result in results:
        breakdown = result.get("breakdown") or {}
        if not breakdown:
            continue

        policy_name = result.get("policy", "unknown")
        lines.append(f"### {policy_name}")

        for dimension in ("market_regime", "best_buy_point_type", "confirmations"):
            dimension_data = breakdown.get(dimension) or {}
            lines.append(f"#### {dimension}")
            if not dimension_data:
                lines.append("- no buckets")
                continue

            items = list(dimension_data.items())
            if dimension == "confirmations":
                items = sorted(
                    items,
                    key=lambda item: (-int(item[1].get("total", 0)), str(item[0])),
                )[:10]
            else:
                items = sorted(items, key=lambda item: str(item[0]))

            for bucket, stats in items:
                lines.append(
                    "- {bucket}: total={total}, accepted={accepted}, filtered={filtered}, reasons={reasons}".format(
                        bucket=bucket,
                        total=stats.get("total", 0),
                        accepted=stats.get("accepted", 0),
                        filtered=stats.get("filtered", 0),
                        reasons=_format_reason_counts(stats.get("filter_reasons") or {}),
                    )
                )

    lines.append("")
    return lines


def _render_fusion_threshold_section(scan: Dict[str, Any]) -> List[str]:
    profiles = scan.get("profiles") or []
    if not isinstance(profiles, list) or not profiles:
        return ["## Fusion Threshold Scan", "- no profiles"]

    lines: List[str] = [
        "## Fusion Threshold Scan",
        "",
        "| Candidate | Variant | samples_before | samples_after | coverage | coverage_pct | "
        "t3_mean_before | t3_mean_after | t3_win_rate_before | t3_win_rate_after | "
        "drawdown_mean_before | drawdown_mean_after | accepted |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for profile in profiles:
        lines.append(
            "| {candidate} | {variant} | {samples_before} | {samples_after} | {coverage} | {coverage_pct} | "
            "{t3_mean_before} | {t3_mean_after} | {t3_win_rate_before} | {t3_win_rate_after} | "
            "{drawdown_mean_before} | {drawdown_mean_after} | {accepted} |".format(
                candidate=profile.get("candidate", "-"),
                variant=profile.get("variant", "-"),
                samples_before=profile.get("samples_before", "n/a"),
                samples_after=profile.get("samples_after", "n/a"),
                coverage=profile.get("coverage", "n/a"),
                coverage_pct=profile.get("coverage_pct", "n/a"),
                t3_mean_before=profile.get("t3_mean_before", "n/a"),
                t3_mean_after=profile.get("t3_mean_after", "n/a"),
                t3_win_rate_before=profile.get("t3_win_rate_before", "n/a"),
                t3_win_rate_after=profile.get("t3_win_rate_after", "n/a"),
                drawdown_mean_before=profile.get("drawdown_mean_before", "n/a"),
                drawdown_mean_after=profile.get("drawdown_mean_after", "n/a"),
                accepted=profile.get("accepted", False),
            )
        )
    lines.append("")

    lines.append("### Reject Reason Distribution")
    for profile in profiles:
        candidate = profile.get("candidate", "-")
        variant = profile.get("variant", "-")
        reasons = profile.get("reject_reason_distribution") or {}
        if not reasons:
            lines.append(f"- {candidate} ({variant}): none")
            continue
        reason_text = ", ".join(
            f"{reason}:{count}" for reason, count in sorted(reasons.items())
        )
        lines.append(f"- {candidate} ({variant}): {reason_text}")
    lines.append("")

    selected = scan.get("selected") or {}
    lines.append("### Selected Candidate")
    if selected:
        lines.append(
            f"- {selected.get('candidate', '-')}: {selected.get('reason', '-')}, "
            f"accepted={selected.get('accepted', False)}"
        )
    else:
        lines.append("- no selected candidate")

    pareto = scan.get("pareto_frontier") or []
    lines.append("### Pareto Frontier")
    if pareto:
        lines.append("- " + ", ".join(str(item) for item in pareto))
    else:
        lines.append("- none")

    rejected = scan.get("rejected") or []
    rejected_reasons = scan.get("rejected_reasons") or {}
    lines.append("### Rejected")
    if rejected:
        for item in rejected:
            reason = rejected_reasons.get(item, "rejected")
            lines.append(f"- {item}: {reason}")
    else:
        lines.append("- none")
    lines.append("")
    return lines


def _render_markdown(payload: Dict[str, Any]) -> str:
    results = payload.get("policies", []) if isinstance(payload, dict) else []
    execution = (payload or {}).get("execution") or {}
    fusion_threshold_scan = (payload or {}).get("fusion_threshold_scan") if isinstance(payload, dict) else None
    recall_walkforward = (
        (payload or {}).get("recall_walkforward")
        if isinstance(payload, dict)
        else None
    )

    lines = [
        "# ChanLun Policy Backtest",
        "",
        f"- Generated: {datetime.now().isoformat()}",
        "",
        "| Policy | Snapshot Days | Picks Seen | Baseline n | Baseline T+3 | Policy n | Policy T+3 | ΔT+3 | ΔT+3 Win Rate | Filtered | Entry Model | Entry Mode | Exit Model | Not Evaluable | Retained % | Filtered By Reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_table_row(item.get("policy"), item) for item in results)
    lines.append("")
    lines.extend(_render_breakdown_section(results))
    if isinstance(fusion_threshold_scan, dict):
        lines.extend(_render_fusion_threshold_section(fusion_threshold_scan))
    if isinstance(recall_walkforward, dict):
        gates = recall_walkforward.get("acceptance_gates") or {}
        lines.extend([
            "## Recall Walk-forward",
            "",
            f"- sample_count: {recall_walkforward.get('sample_count', 'n/a')}",
            f"- network_requests: {recall_walkforward.get('network_requests', 'n/a')}",
            f"- accepted: {gates.get('accepted', False)}",
            f"- attention_p95: {gates.get('attention_p95', 'n/a')}",
            f"- tail_risk_delta_pp: {gates.get('tail_risk_delta_pp', 'n/a')}",
            "",
        ])

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
    parser.add_argument(
        "--recall-walkforward-json",
        help="Optional recall walk-forward JSON to attach to the report",
    )
    parser.add_argument(
        "--business-metrics",
        action="store_true",
        help="Compatibility flag; currently no-op.",
    )

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
        if args.recall_walkforward_json:
            payload["recall_walkforward"] = json.loads(
                Path(args.recall_walkforward_json).read_text(
                    encoding="utf-8"
                )
            )
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
