"""Isolation contract for stock-selection shadow experiments.

The production recommendation list is intentionally treated as read-only here.
Every registered experiment receives its own deep copy and can only produce a
diagnostic payload.  This module does not persist results, evaluate returns, or
change any production consumer; those concerns belong to later implementation
tasks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional


SHADOW_MODE = "shadow"
IMMEDIATE_CLOSE = "immediate_close"
ALLOWED_HORIZONS = frozenset({1, 3, 5})


# The registry is deliberately process-local.  It is a definition registry,
# not a ledger, and therefore has no persistence or production side effects.
_EXPERIMENT_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _json_safe_value(value: Any) -> Any:
    """Validate and copy a JSON-safe value without coercion.

    Coercing arbitrary keys or scalars (for example, ``1`` to ``"1"`` or an
    object to ``repr(object)``) can hide production changes and even create key
    collisions.  The digest therefore accepts only native JSON containers and
    finite native scalar types.
    """

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("production output contains a non-finite float")
        return value
    if type(value) is list:
        return [_json_safe_value(item) for item in value]
    if type(value) is dict:
        normalised = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("production output object keys must be strings")
            normalised[key] = _json_safe_value(item)
        return normalised
    raise ValueError("production output contains a non-JSON-safe value")


def production_digest(production_output: Any) -> str:
    """Calculate the canonical SHA-256 digest of a production output.

    Mapping insertion order and equivalent tuple/list nesting do not affect
    the digest, while list order does.  The function is pure and never mutates
    ``production_output``.
    """

    canonical = _json_safe_value(production_output)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalise_spec(spec: Any) -> Dict[str, Any]:
    """Validate and normalise a public experiment definition."""

    if not isinstance(spec, Mapping):
        raise ValueError("experiment spec must be a mapping")

    raw = dict(spec)
    resolved_id = raw.get("experiment_id")
    version = raw.get("version")
    source_pool = raw.get("source_pool")
    upstream_pool = raw.get("upstream_pool")
    intended_horizon = raw.get("intended_horizon")
    entry_mode = raw.get("entry_mode")
    builder = raw.get("builder")

    if not isinstance(resolved_id, str) or not resolved_id.strip():
        raise ValueError("experiment_id must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version is required")
    if not isinstance(source_pool, str) or not source_pool.strip():
        raise ValueError("source_pool is required")
    if not isinstance(upstream_pool, str) or not upstream_pool.strip():
        raise ValueError("upstream_pool is required")
    if (
        isinstance(intended_horizon, bool)
        or not isinstance(intended_horizon, int)
        or intended_horizon not in ALLOWED_HORIZONS
    ):
        raise ValueError("intended_horizon must be one of 1, 3, or 5")
    if entry_mode != IMMEDIATE_CLOSE:
        raise ValueError("entry_mode must be immediate_close")
    if not callable(builder):
        raise ValueError("builder must be callable")

    normalised: Dict[str, Any] = {
        "experiment_id": resolved_id,
        "version": version,
        # Keep the descriptive alias used by the report contract.
        "strategy_version": version,
        "upstream_pool": upstream_pool,
        "source_pool": source_pool,
        "intended_horizon": intended_horizon,
        "entry_mode": entry_mode,
        "builder": builder,
    }
    for key in ("display_name", "description", "research_tier"):
        if key in raw:
            normalised[key] = copy.deepcopy(raw[key])
    return normalised


def register_experiment(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and register one explicit shadow experiment definition."""

    normalised = _normalise_spec(spec)
    key = normalised["experiment_id"]
    _EXPERIMENT_REGISTRY[key] = normalised
    return copy.deepcopy(normalised)


def clear_experiments() -> None:
    """Clear the process-local registry (primarily useful for tests)."""

    _EXPERIMENT_REGISTRY.clear()


def list_experiments() -> List[str]:
    """Return registered experiment IDs in registration order."""

    return list(_EXPERIMENT_REGISTRY)


def get_experiment(experiment_id: str) -> Dict[str, Any]:
    """Return a defensive copy of one registered definition."""

    try:
        return copy.deepcopy(_EXPERIMENT_REGISTRY[experiment_id])
    except KeyError as exc:
        raise KeyError(f"unknown shadow experiment: {experiment_id}") from exc


def _coerce_experiments(experiments: Any) -> List[Any]:
    if experiments is None:
        return list(list_experiments())
    if isinstance(experiments, str):
        return [experiments]
    if isinstance(experiments, Mapping):
        # A mapping is allowed only as one inline spec.  In particular, do not
        # interpret ``{"id": spec}`` as a registry: that form is ambiguous and
        # otherwise lets invalid items fail before the per-experiment guard.
        if "experiment_id" not in experiments:
            raise ValueError("experiment collections must be a sequence of specs or registered IDs")
        return [experiments]

    try:
        items = list(experiments)
    except TypeError as exc:
        raise ValueError("experiments must be an iterable of specs") from exc
    return items


def _candidate_count(production_output: Any) -> int:
    if isinstance(production_output, Mapping):
        candidates = production_output.get("picks_fusion")
        if isinstance(candidates, list):
            return len(candidates)
    if isinstance(production_output, list):
        return len(production_output)
    return 0


def _result_row(spec: Mapping[str, Any], result: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in spec.items()
        if key != "builder"
    }
    row.update(
        {
            "mode": SHADOW_MODE,
            "status": "available",
            "evaluation_role": "shadow_candidate",
            "affects_production": False,
            "promotion_eligible": False,
            "result": copy.deepcopy(result),
            # ``output`` is intentionally an alias for callers that use the
            # more generic experiment vocabulary.
            "output": copy.deepcopy(result),
        }
    )
    if isinstance(result, Mapping):
        if "today" in result:
            row["today"] = copy.deepcopy(result["today"])
        elif "candidates" in result:
            row["today"] = {"candidates": copy.deepcopy(result["candidates"])}
    elif isinstance(result, list):
        row["today"] = {"candidates": copy.deepcopy(result)}
    return row


def _error_row(spec: Any, exc: BaseException) -> Dict[str, Any]:
    if isinstance(spec, Mapping):
        row = {
            key: copy.deepcopy(value)
            for key, value in spec.items()
            if key != "builder"
        }
    else:
        row = {"experiment_id": spec} if isinstance(spec, str) else {}
    row.update(
        {
            "mode": SHADOW_MODE,
            "status": "unavailable",
            "evaluation_role": "shadow_candidate",
            "affects_production": False,
            "promotion_eligible": False,
            "error": str(exc) or exc.__class__.__name__,
            "error_type": exc.__class__.__name__,
        }
    )
    return row


def run_shadow_evaluations(
    production_output: Any,
    experiments: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Run registered diagnostic builders behind a production guard.

    Each builder receives a fresh deep copy of ``production_output``.  A
    builder failure is isolated to its row; the caller still receives a valid
    top-level shadow contract.  No returned value can authorize a production
    cutover: both the top-level and per-experiment ``affects_production`` are
    forced to ``False``.
    """

    before_sha = production_digest(production_output)
    raw_experiments = _coerce_experiments(experiments)
    rows: List[Dict[str, Any]] = []

    for raw_spec in raw_experiments:
        try:
            spec = get_experiment(raw_spec) if isinstance(raw_spec, str) else _normalise_spec(raw_spec)
            # Deep-copy independently for every experiment.  This prevents a
            # mutating experiment from contaminating a later experiment's
            # view, in addition to protecting the official object.
            shadow_input = copy.deepcopy(production_output)
            result = spec["builder"](shadow_input)
            rows.append(_result_row(spec, result))
        except Exception as exc:  # isolate one diagnostic from the rest
            rows.append(_error_row(raw_spec, exc))

    after_sha = production_digest(production_output)
    unchanged = before_sha == after_sha
    return {
        "schema_version": 1,
        "mode": SHADOW_MODE,
        "affects_production": False,
        "status": "collecting" if unchanged else "production_guard_failed",
        "production_guard": {
            "unchanged": unchanged,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
        },
        "production_reference": {
            "pool": "picks_fusion",
            "today_count": _candidate_count(production_output),
            "comparison_eligible": False,
        },
        "experiments": rows,
    }


__all__ = [
    "clear_experiments",
    "get_experiment",
    "list_experiments",
    "production_digest",
    "register_experiment",
    "run_shadow_evaluations",
]
