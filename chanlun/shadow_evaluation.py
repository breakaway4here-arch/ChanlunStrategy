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
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional


SHADOW_MODE = "shadow"
IMMEDIATE_CLOSE = "immediate_close"
ALLOWED_HORIZONS = frozenset({1, 3, 5})


# The registry is deliberately process-local.  It is a definition registry,
# not a ledger, and therefore has no persistence or production side effects.
_EXPERIMENT_REGISTRY: Dict[str, Dict[str, Any]] = {}
EXPERIMENT_REGISTRY = _EXPERIMENT_REGISTRY


def _canonical_value(value: Any) -> Any:
    """Return a JSON-safe, deterministic representation of ``value``.

    Production rows are normally JSON values already.  The small amount of
    defensive handling here keeps the digest deterministic for tuples, sets,
    and mapping implementations without mutating the caller's object.
    """

    if isinstance(value, Mapping):
        # JSON object keys are strings.  Sorting the rendered key avoids a
        # TypeError when a malformed diagnostic payload contains mixed keys.
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        # List order is production-significant (ranking/order of picks).
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        rendered = [_canonical_value(item) for item in value]
        return sorted(rendered, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # This is only a defensive fallback for callers passing a custom scalar;
    # repr is preferable to object identity because it does not mutate state.
    return repr(value)


def production_digest(production_output: Any) -> str:
    """Calculate the canonical SHA-256 digest of a production output.

    Mapping insertion order and equivalent tuple/list nesting do not affect
    the digest, while list order does.  The function is pure and never mutates
    ``production_output``.
    """

    canonical = _canonical_value(production_output)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _first_non_empty(spec: Mapping[str, Any], *keys: str) -> Optional[Any]:
    for key in keys:
        value = spec.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalise_spec(spec: Any, experiment_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate and normalise a public experiment definition."""

    if not isinstance(spec, Mapping):
        raise ValueError("experiment spec must be a mapping")

    raw = dict(spec)
    resolved_id = experiment_id or _first_non_empty(raw, "experiment_id", "id", "name")
    version = _first_non_empty(raw, "version", "strategy_version")
    source_pool = _first_non_empty(raw, "source_pool", "pool", "upstream_pool")
    upstream_pool = _first_non_empty(raw, "upstream_pool", "source_pool", "pool")
    intended_horizon = raw.get("intended_horizon")
    entry_mode = raw.get("entry_mode")
    builder = raw.get("builder", raw.get("build"))

    if resolved_id is None:
        if version and source_pool and isinstance(intended_horizon, int) and not isinstance(intended_horizon, bool):
            resolved_id = f"{source_pool}:{version}:t{intended_horizon}"
        else:
            raise ValueError("experiment_id is required when it cannot be derived")
    if not isinstance(resolved_id, str) or not resolved_id.strip():
        raise ValueError("experiment_id must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version is required")
    if not isinstance(source_pool, str) or not source_pool.strip():
        raise ValueError("source_pool or upstream_pool is required")
    if not isinstance(upstream_pool, str) or not upstream_pool.strip():
        raise ValueError("upstream_pool or source_pool is required")
    if isinstance(intended_horizon, bool) or intended_horizon not in ALLOWED_HORIZONS:
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


def register_experiment(
    spec: Any = None,
    maybe_spec: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Validate and register one shadow experiment.

    The preferred call form is ``register_experiment({...})``.  A name plus a
    mapping (``register_experiment("id", {...})``) and keyword fields are
    accepted as small conveniences for callers building a registry in code.
    """

    if isinstance(spec, str):
        raw: Dict[str, Any] = dict(maybe_spec or {})
        raw["experiment_id"] = spec
        raw.update(kwargs)
    elif spec is None:
        raw = dict(kwargs)
    elif isinstance(spec, Mapping):
        raw = dict(spec)
        raw.update(kwargs)
    else:
        raise ValueError("experiment spec must be a mapping")

    normalised = _normalise_spec(raw)
    key = normalised["experiment_id"]
    _EXPERIMENT_REGISTRY[key] = normalised
    return copy.deepcopy(normalised)


def register_shadow_experiment(
    spec: Any = None,
    maybe_spec: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Alias with an explicit shadow-oriented name."""

    return register_experiment(spec, maybe_spec, **kwargs)


def unregister_experiment(experiment_id: str) -> None:
    _EXPERIMENT_REGISTRY.pop(experiment_id, None)


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


def _coerce_experiments(experiments: Any) -> List[Dict[str, Any]]:
    if experiments is None:
        return [get_experiment(key) for key in list_experiments()]
    if isinstance(experiments, str):
        return [get_experiment(experiments)]
    if isinstance(experiments, Mapping):
        # A single spec is the least surprising interpretation for a mapping
        # containing a builder; a mapping of IDs is also accepted.
        if "builder" in experiments or "build" in experiments:
            return [_normalise_spec(experiments)]
        values = list(experiments.values())
        return [_normalise_spec(value, experiment_id=str(key)) for key, value in experiments.items()] if values else []

    try:
        items = list(experiments)
    except TypeError as exc:
        raise ValueError("experiments must be an iterable of specs") from exc
    result: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            result.append(get_experiment(item))
        else:
            result.append(_normalise_spec(item))
    return result


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


def _error_row(spec: Mapping[str, Any], exc: BaseException) -> Dict[str, Any]:
    row = {
        key: copy.deepcopy(value)
        for key, value in spec.items()
        if key != "builder"
    }
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
    specs = _coerce_experiments(experiments)
    rows: List[Dict[str, Any]] = []

    for spec in specs:
        try:
            # Deep-copy independently for every experiment.  This prevents a
            # mutating experiment from contaminating a later experiment's
            # view, in addition to protecting the official object.
            shadow_input = copy.deepcopy(production_output)
            result = spec["builder"](shadow_input)
            rows.append(_result_row(spec, result))
        except Exception as exc:  # isolate one diagnostic from the rest
            rows.append(_error_row(spec, exc))

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
    "ALLOWED_HORIZONS",
    "EXPERIMENT_REGISTRY",
    "IMMEDIATE_CLOSE",
    "SHADOW_MODE",
    "clear_experiments",
    "get_experiment",
    "list_experiments",
    "production_digest",
    "register_experiment",
    "register_shadow_experiment",
    "run_shadow_evaluations",
    "unregister_experiment",
]
