"""Evaluate phase 5 experiment promotion gates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_COVERAGE_EVALUATED_KEYS = ("evaluated", "sample_count")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _pick_metric(metrics: Dict[str, Any], candidates: List[str], fallback: Optional[float] = None) -> Optional[float]:
    for key in candidates:
        if key in metrics and metrics.get(key) is not None:
            value = _to_float(metrics[key])
            if value is not None:
                return value
    if fallback is not None:
        return float(fallback)
    return None


def _extract_coverage_evaluated(coverage: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(coverage, dict):
        return None
    return _pick_metric(coverage, list(_COVERAGE_EVALUATED_KEYS))


def _build_gate(
    name: str,
    status: str,
    threshold: str,
    delta: Optional[float],
    passed: Optional[bool],
    before: Optional[float],
    after: Optional[float],
) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "threshold": threshold,
        "before": before,
        "after": after,
        "delta": delta,
        "passed": passed,
    }


def evaluate_promotion_gates(
    before_metrics: Dict[str, Any],
    after_metrics: Dict[str, Any],
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate experiment promotion gates.

    Returns a machine-readable dict:
    {
        "gates": {...},
        "final_decision": "pass|fail|insufficient_data",
        "reason": [...],
    }
    """

    required_keys = [
        "sample_count",
        "t3_mean",
        "t3_win_rate",
        "t3_loss_5pct_rate",
        "big_drop_5pct_rate",
    ]

    if not isinstance(before_metrics, dict):
        before_metrics = {}
    if not isinstance(after_metrics, dict):
        after_metrics = {}

    reasons: List[str] = []
    gates: Dict[str, Dict[str, Any]] = {}

    evaluated = _extract_coverage_evaluated(coverage)
    coverage_gate_pass = evaluated is not None and evaluated > 0
    if evaluated is None:
        reasons.append("coverage.evaluated missing")
    elif not coverage_gate_pass:
        reasons.append(f"coverage.evaluated={evaluated} <= 0")

    gates["coverage_evaluated"] = _build_gate(
        name="coverage_evaluated",
        status="pass" if coverage_gate_pass else "insufficient",
        threshold="> 0",
        delta=None,
        passed=coverage_gate_pass if evaluated is not None else None,
        before=None,
        after=evaluated,
    )

    missing_metric = False
    before_values: Dict[str, Optional[float]] = {}
    after_values: Dict[str, Optional[float]] = {}

    for key in required_keys:
        metric_keys = [key, key.replace("_", "")]
        if key == "sample_count":
            metric_keys.append("n")
        before_value = _pick_metric(before_metrics, metric_keys)
        after_value = _pick_metric(after_metrics, metric_keys)
        before_values[key] = before_value
        after_values[key] = after_value
        if before_value is None or after_value is None:
            missing_metric = True

    sample_count = None
    if before_values["sample_count"] is not None and after_values["sample_count"] is not None:
        sample_count = min(before_values["sample_count"], after_values["sample_count"])
    if sample_count is None:
        gates["sample_count"] = _build_gate(
            name="sample_count",
            status="insufficient",
            threshold=">= 100",
            delta=None,
            passed=None,
            before=before_values["sample_count"],
            after=after_values["sample_count"],
        )
    else:
        sample_count_pass = sample_count >= 100
        gates["sample_count"] = _build_gate(
            name="sample_count",
            status="pass" if sample_count_pass else "fail",
            threshold=">= 100",
            delta=None,
            passed=sample_count_pass,
            before=before_values["sample_count"],
            after=after_values["sample_count"],
        )

    for key, threshold_name, comparator, threshold in (
        ("t3_mean", "t3_mean_delta", ">=", 0.5),
        ("t3_win_rate", "t3_win_rate_delta", ">=", 3.0),
        ("t3_loss_5pct_rate", "t3_loss_5pct_rate_delta", "<=", -3.0),
        ("big_drop_5pct_rate", "big_drop_5pct_rate_delta", "<=", -5.0),
    ):
        before = before_values.get(key)
        after = after_values.get(key)
        if before is None or after is None:
            gates[threshold_name] = _build_gate(
                name=threshold_name,
                status="insufficient",
                threshold=f"{comparator} {threshold}",
                delta=None,
                passed=None,
                before=before,
                after=after,
            )
            continue
        delta = after - before
        passed = comparator == ">=" and delta >= threshold or comparator == "<=" and delta <= threshold
        gates[threshold_name] = _build_gate(
            name=threshold_name,
            status="pass" if passed else "fail",
            threshold=f"{comparator} {threshold}",
            delta=delta,
            passed=passed,
            before=before,
            after=after,
        )

    if missing_metric or not coverage_gate_pass:
        final_decision = "insufficient_data"
        if missing_metric:
            missing = [
                key
                for key in required_keys
                if before_values.get(key) is None or after_values.get(key) is None
            ]
            if missing:
                reasons.append(f"missing metrics: {', '.join(sorted(set(missing)))}")
        if not reasons:
            reasons.append("insufficient_data")
        for gate in gates.values():
            gate["status"] = "insufficient" if gate["passed"] is None else gate["status"]
        return {
            "gates": gates,
            "final_decision": final_decision,
            "reason": reasons,
        }

    failed = [name for name, gate in gates.items() if gate["status"] != "pass"]
    if failed:
        final_decision = "fail"
        reasons.append("failed gates: " + ", ".join(sorted(failed)))
    else:
        final_decision = "pass"
        reasons.append("all gates pass")

    return {
        "gates": gates,
        "final_decision": final_decision,
        "reason": reasons,
    }
