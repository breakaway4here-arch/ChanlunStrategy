"""Experiment-level business metric helpers."""

import json


def _normalize_any(value):
    if isinstance(value, dict):
        normalized = {}
        for key in sorted(value):
            if key == "confirmations" and isinstance(value.get(key), list):
                try:
                    normalized[key] = sorted([_normalize_any(v) for v in value[key]])
                    continue
                except TypeError:
                    pass
            normalized[key] = _normalize_any(value[key])
        return normalized
    if isinstance(value, list):
        return [_normalize_any(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_any(item) for item in value]
    return value


def _normalize_recommendation(best_buy_point):
    return json.dumps(_normalize_any(best_buy_point or {}), sort_keys=True, ensure_ascii=False)


def _to_code_map(recommendations):
    mapping = {}
    for rec in recommendations or []:
        if not isinstance(rec, dict):
            continue
        code = rec.get("code")
        if not code:
            continue
        mapping[str(code)] = rec.get("best_buy_point")
    return mapping


def compare_recommendations(legacy, experiment):
    """Compare two recommendation-like lists by code + best_buy_point.

    Returns:
        dict with counts and code sets:
        - legacy_count
        - experiment_count
        - added_codes
        - removed_codes
        - kept_codes
        - changed_best_buy_point_codes
    """

    legacy_map = _to_code_map(legacy)
    exp_map = _to_code_map(experiment)

    legacy_codes = set(legacy_map)
    exp_codes = set(exp_map)

    added = sorted(exp_codes - legacy_codes)
    removed = sorted(legacy_codes - exp_codes)
    kept = sorted(legacy_codes & exp_codes)

    changed = []
    for code in kept:
        if _normalize_recommendation(legacy_map[code]) != _normalize_recommendation(exp_map[code]):
            changed.append(code)

    return {
        "legacy_count": len(legacy_map),
        "experiment_count": len(exp_map),
        "added_codes": added,
        "removed_codes": removed,
        "kept_codes": kept,
        "changed_best_buy_point_codes": sorted(changed),
    }
