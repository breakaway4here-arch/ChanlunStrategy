"""Audit filtered samples for signal experiments."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chanlun.engine_experiments import list_experiments
from chanlun.historical_experiment_metrics import supports_historical_return_metrics
from chanlun.filtered_sample_audit import build_filtered_sample_audit


def _format_pct(value, default="n/a"):
    if value is None:
        return default
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return default


def _as_markdown_row(cells):
    return "| " + " | ".join(cells) + " |"


def render_markdown(payload: dict) -> str:
    summary = payload.get("summary") or {}
    top_winners = payload.get("top_winners") or []
    by_type = payload.get("by_type") or {}
    by_signal_tier = payload.get("by_signal_tier") or {}
    by_confirmations = payload.get("by_confirmations") or {}
    by_distance = payload.get("by_distance_bucket") or {}

    lines = [
        "# Filtered Sample Audit",
        "",
        f"- Generated: {datetime.now().isoformat()}",
        f"- Experiment: {payload.get('experiment')}",
        "",
        "## Summary",
        f"- Filtered samples: {summary.get('filtered', 0)}",
        f"- T+3 mean: {_format_pct(summary.get('t3_mean'))}",
        f"- T+3 win rate: {summary.get('t3_win_rate', 'n/a')}%",
        f"- T+3 <= -5%: {summary.get('t3_loss_5pct_rate', 'n/a')}%",
        f"- Big run >=5%: {summary.get('big_run_5pct_rate', 'n/a')}%",
        f"- Big drop <=-5%: {summary.get('big_drop_5pct_rate', 'n/a')}%",
        "",
        "## Top Winners",
    ]

    lines.append(_as_markdown_row(["Date", "Version", "Code", "Name", "Type", "T+3%", "Distance", "Confirmations"]))
    lines.append(_as_markdown_row(["---", "---", "---", "---", "---", "---", "---", "---"]))
    for item in top_winners:
        confirmations = item.get("confirmations") or []
        if isinstance(confirmations, (list, tuple)):
            confirmations = ", ".join(confirmations)
        lines.append(
            _as_markdown_row(
                [
                    str(item.get("date", "")),
                    str(item.get("version", "")),
                    str(item.get("code", "")),
                    str(item.get("name", "")),
                    str(item.get("type", "")),
                    _format_pct(item.get("t3_close_pct")),
                    str(item.get("distance_from_reference_pct", "")),
                    str(confirmations),
                ]
            )
        )

    lines.extend(["", "## By Type", ""])
    lines.append(_as_markdown_row(["Type", "N", "T+3 Mean", "T+3 Win Rate", "Big Run >=5%", "Big Drop <=-5%"]))
    lines.append(_as_markdown_row(["---", "---", "---", "---", "---", "---"]))
    for key in sorted(by_type):
        s = by_type[key] or {}
        lines.append(
            _as_markdown_row(
                [
                    str(key),
                    str(s.get("n", 0)),
                    _format_pct(s.get("t3_mean")),
                    f"{s.get('t3_win_rate', 'n/a')}%",
                    f"{s.get('big_run_5pct_rate', 'n/a')}%",
                    f"{s.get('big_drop_5pct_rate', 'n/a')}%",
                ]
            )
        )

    lines.extend(["", "## By Signal Tier", ""])
    lines.append(_as_markdown_row(["Signal Tier", "N", "T+3 Mean", "T+3 Win Rate", "Big Run >=5%", "Big Drop <=-5%"]))
    lines.append(_as_markdown_row(["---", "---", "---", "---", "---", "---"]))
    for key in sorted(by_signal_tier):
        s = by_signal_tier[key] or {}
        lines.append(
            _as_markdown_row(
                [
                    str(key),
                    str(s.get("n", 0)),
                    _format_pct(s.get("t3_mean")),
                    f"{s.get('t3_win_rate', 'n/a')}%",
                    f"{s.get('big_run_5pct_rate', 'n/a')}%",
                    f"{s.get('big_drop_5pct_rate', 'n/a')}%",
                ]
            )
        )

    lines.extend(["", "## By Confirmations", ""])
    lines.append(_as_markdown_row(["Confirmations", "N", "T+3 Mean", "T+3 Win Rate", "Big Run >=5%", "Big Drop <=-5%"]))
    lines.append(_as_markdown_row(["---", "---", "---", "---", "---", "---"]))
    for key in sorted(by_confirmations):
        s = by_confirmations[key] or {}
        lines.append(
            _as_markdown_row(
                [
                    str(key),
                    str(s.get("n", 0)),
                    _format_pct(s.get("t3_mean")),
                    f"{s.get('t3_win_rate', 'n/a')}%",
                    f"{s.get('big_run_5pct_rate', 'n/a')}%",
                    f"{s.get('big_drop_5pct_rate', 'n/a')}%",
                ]
            )
        )

    lines.extend(["", "## By Distance Bucket", ""])
    lines.append(_as_markdown_row(["Distance", "N", "T+3 Mean", "T+3 Win Rate", "Big Run >=5%", "Big Drop <=-5%"]))
    lines.append(_as_markdown_row(["---", "---", "---", "---", "---", "---"]))
    for key in sorted(by_distance):
        s = by_distance[key] or {}
        lines.append(
            _as_markdown_row(
                [
                    str(key),
                    str(s.get("n", 0)),
                    _format_pct(s.get("t3_mean")),
                    f"{s.get('t3_win_rate', 'n/a')}%",
                    f"{s.get('big_run_5pct_rate', 'n/a')}%",
                    f"{s.get('big_drop_5pct_rate', 'n/a')}%",
                ]
            )
        )

    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict, output_json: str, output_md: str) -> None:
    json_path = Path(output_json)
    md_path = Path(output_md)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(payload), encoding="utf-8")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Audit filtered samples for a signal experiment.")
    parser.add_argument("--experiment", required=True, help="Experiment name")
    parser.add_argument("--output-json", required=True, help="Output JSON report path")
    parser.add_argument("--output-md", required=True, help="Output Markdown report path")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    known = set(list_experiments())
    if args.experiment not in known:
        print(f"unknown experiment: {args.experiment}", file=sys.stderr)
        return 1
    if not supports_historical_return_metrics(args.experiment):
        print(
            f"unsupported experiment for filtered sample audit: {args.experiment}",
            file=sys.stderr,
        )
        return 2

    try:
        payload = build_filtered_sample_audit(args.experiment)
        write_outputs(payload, args.output_json, args.output_md)
    except Exception as exc:
        print(f"audit_filtered_samples failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
