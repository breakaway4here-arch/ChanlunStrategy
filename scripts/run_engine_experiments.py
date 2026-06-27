"""Batch report generator for ChanLun experiment compare runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, ROOT)

from chanlun.engine_experiments import get_experiment, list_experiments
from chanlun.experiment_gates import evaluate_promotion_gates


def _normalize_experiments(experiments_arg: str) -> List[str]:
    seen = set()
    experiments: List[str] = []
    for name in experiments_arg.split(","):
        candidate = name.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        experiments.append(candidate)
    return experiments


def _build_markdown_row(result: Dict[str, Any]) -> str:
    summary = result.get("summary", {})
    coverage = result.get("coverage") or summary.get("coverage") or {}
    gate_result = result.get("gate_result", {})
    structure_equal = bool(summary.get("structure_equal", summary.get("all_equal")))
    reasons = gate_result.get("reason") or []
    reason_text = ", ".join(reasons) if isinstance(reasons, list) else str(reasons)
    return (
        f"| {result.get('experiment', 'unknown')} "
        f"| {result.get('risk', 'low')} "
        f"| {'pass' if structure_equal else 'fail'} "
        f"| {coverage.get('evaluated', 'n/a')} "
        f"| {gate_result.get('final_decision', 'unknown')} "
        f"| {reason_text} |"
    )


def _render_markdown(results: List[Dict[str, Any]]) -> str:
    lines = [
        "# ChanLun Engine Experiment Report",
        "",
        f"- Generated: {datetime.now().isoformat()}",
        "",
        "| Experiment | Risk | Structure Equal | Coverage Evaluated | Gate Decision | Reasons |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_build_markdown_row(result) for result in results)
    lines.append("")
    return "\n".join(lines)


def _run_compare(experiment: str, workspace: Path) -> Tuple[Dict[str, Any], Path]:
    script_path = Path(ROOT) / "scripts" / "compare_chan_engine_dual.py"
    output_path = workspace / f"{experiment}_compare.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--experiment",
            experiment,
            "--business-metrics",
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stdout or "") + (completed.stderr or "")
        raise RuntimeError(f"compare run failed for {experiment}: {stderr.strip()}")
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"failed to read compare output for {experiment}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid compare output for {experiment}: {exc}") from exc
    return payload, output_path


def _build_result(payload: Dict[str, Any], experiment_name: str) -> Dict[str, Any]:
    summary = payload.get("summary") or {}
    recommendation_diff = summary.get("recommendation_diff", {})
    return_metrics = summary.get("return_metrics", {})
    coverage = summary.get("coverage")

    experiment_def = get_experiment(experiment_name)
    gate_result = evaluate_promotion_gates(
        (return_metrics or {}).get("legacy") or {},
        (return_metrics or {}).get("experiment") or {},
        coverage=coverage,
    )

    return {
        "experiment": experiment_name,
        "risk": getattr(experiment_def, "risk", "low"),
        "metadata": {
            "module": getattr(experiment_def, "module", ""),
            "description": getattr(experiment_def, "description", ""),
        },
        "summary": {
            "structure_equal": bool(summary.get("structure_equal", summary.get("all_equal"))),
        },
        "recommendation_diff": recommendation_diff,
        "return_metrics": return_metrics,
        "coverage": coverage,
        "gate_result": gate_result,
    }


def _run_payload(experiments: Iterable[str]) -> Dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory(prefix="chanlun_phase5_4_") as tmpdir:
        workspace = Path(tmpdir)
        for experiment in experiments:
            payload, output_path = _run_compare(experiment, workspace)
            result = _build_result(payload, experiment)
            results.append(result)
            try:
                if output_path.exists():
                    output_path.unlink()
            except OSError:
                pass
    return {"experiments": results}


def _write_outputs(output_json: str, output_md: str, payload: Dict[str, Any]) -> None:
    json_path = Path(output_json)
    md_path = Path(output_md)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    with md_path.open("w", encoding="utf-8") as file:
        file.write(_render_markdown(payload["experiments"]))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run experiment compare and gate evaluation")
    parser.add_argument(
        "--experiments",
        required=True,
        help="Comma-separated experiment names, e.g. signal_p0_distance_guard,signal_p0_p1_guard",
    )
    parser.add_argument("--output-json", required=True, help="JSON report output path")
    parser.add_argument("--output-md", required=True, help="Markdown report output path")
    args = parser.parse_args(argv)

    experiments = _normalize_experiments(args.experiments)
    if not experiments:
        print("--experiments must contain at least one experiment name", file=sys.stderr)
        return 2

    known_experiments = set(list_experiments())
    unknown_experiments = [name for name in experiments if name not in known_experiments]
    if unknown_experiments:
        print(f"unknown experiment(s): {', '.join(unknown_experiments)}", file=sys.stderr)
        return 1

    try:
        payload = {"generated_at": datetime.now().isoformat()}
        payload.update(_run_payload(experiments))
        _write_outputs(args.output_json, args.output_md, payload)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
