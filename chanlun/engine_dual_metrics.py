"""Helpers to build dual-analyze business-metrics payloads."""

from chanlun.experiment_metrics import compare_recommendations


def result_to_recommendations(result):
    """Convert a ChanResult-like object into recommendation records."""
    buy_points = getattr(result, "buy_points", None)
    if not buy_points or result is None:
        return []

    return [
        {"code": getattr(result, "code", None), "best_buy_point": buy_point}
        for buy_point in buy_points
        if isinstance(buy_point, dict)
    ]


def _default_return_metrics():
    return {
        "status": "not_provided",
        "legacy": None,
        "candidate": None,
    }


def _default_coverage():
    return {
        "status": "not_provided",
    }


def _extract_structure_summary(comparison):
    if not isinstance(comparison, dict):
        return None
    return comparison.get("summary")


def build_dual_business_metrics(
    legacy,
    candidate,
    comparison,
    *,
    return_metrics=None,
    coverage=None,
):
    """Build business metrics from a single analyze_dual payload."""
    return {
        "structure": _extract_structure_summary(comparison),
        "recommendation_diff": compare_recommendations(
            result_to_recommendations(legacy),
            result_to_recommendations(candidate),
        ),
        "return_metrics": _default_return_metrics() if return_metrics is None else return_metrics,
        "coverage": _default_coverage() if coverage is None else coverage,
    }


def build_aggregate_dual_business_metrics(
    legacy_recommendations,
    candidate_recommendations,
    *,
    return_metrics=None,
    coverage=None,
):
    """Build aggregate business metrics from scenario-level recommendation lists."""
    return {
        "structure": None,
        "recommendation_diff": compare_recommendations(
            legacy_recommendations,
            candidate_recommendations,
        ),
        "return_metrics": _default_return_metrics() if return_metrics is None else return_metrics,
        "coverage": _default_coverage() if coverage is None else coverage,
    }
