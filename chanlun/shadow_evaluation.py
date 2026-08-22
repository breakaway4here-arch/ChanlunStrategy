"""Isolation contract for stock-selection shadow experiments.

The production recommendation list is intentionally treated as read-only here.
Every registered experiment receives its own deep copy and can only produce a
diagnostic payload.  Shadow candidates persist only to their own pending and
immutable ledgers, and their return scorecards remain separate from every
production consumer and recommendation cohort.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # NumPy is present in the research runtime but keep this module optional.
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in minimal runtimes
    np = None


SHADOW_MODE = "shadow"
IMMEDIATE_CLOSE = "immediate_close"
ALLOWED_HORIZONS = frozenset({1, 3, 5})
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SHADOW_LEDGER_PATH = os.path.join(
    BASE_DIR, ".cache", "chanlun", "shadow_evaluation_ledger.jsonl"
)
DEFAULT_SHADOW_PENDING_DIR = os.path.join(
    BASE_DIR, ".cache", "chanlun", "shadow_evaluation_pending"
)
SHADOW_LEDGER_SCHEMA_VERSION = "1"


# The registry is deliberately process-local.  It is a definition registry,
# not a ledger, and therefore has no persistence or production side effects.
_EXPERIMENT_REGISTRY: Dict[str, Dict[str, Any]] = {}


def json_native_projection(value: Any) -> Any:
    """Project supported research values to strict native JSON values.

    NumPy arrays/scalars and standard-library dataclass instances are the
    explicit compatibility exceptions because real ``picks_fusion`` rows carry
    them.  NumPy values are converted through ``tolist``/``item``; dataclasses
    are traversed by their declared fields.  Tuples are represented as JSON
    lists.  All projected values are then validated recursively.  Everything
    else is accepted only when it is already a native JSON container or finite
    scalar; arbitrary values are rejected rather than coerced.
    """

    if np is not None:
        if isinstance(value, np.ndarray):
            try:
                return json_native_projection(value.tolist())
            except Exception as exc:
                raise ValueError("production output contains an invalid NumPy array") from exc
        if isinstance(value, np.generic):
            try:
                return json_native_projection(value.item())
            except Exception as exc:
                raise ValueError("production output contains an invalid NumPy scalar") from exc

    # ``dataclasses.asdict`` performs a recursive deepcopy and can therefore
    # execute user-defined ``__deepcopy__`` hooks.  Walk only declared fields
    # so the projection remains explicit and fail-closed.
    if is_dataclass(value):
        if isinstance(value, type):
            raise ValueError("production output contains a non-JSON-safe value")
        try:
            return {
                field.name: json_native_projection(getattr(value, field.name))
                for field in fields(value)
            }
        except Exception as exc:
            raise ValueError("production output contains an invalid dataclass") from exc

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("production output contains a non-finite float")
        return value
    if type(value) is list:
        return [json_native_projection(item) for item in value]
    if type(value) is tuple:
        return [json_native_projection(item) for item in value]
    if type(value) is dict:
        normalised = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("production output object keys must be strings")
            normalised[key] = json_native_projection(item)
        return normalised
    raise ValueError("production output contains a non-JSON-safe value")


def production_digest(production_output: Any) -> str:
    """Calculate the canonical SHA-256 digest of a production output.

    Dictionary insertion order does not affect the digest, while list order
    does.  Unsupported values are rejected instead of being coerced.  The
    function is pure and never mutates ``production_output``.
    """

    canonical = json_native_projection(production_output)
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


_ERROR_METADATA_KEYS = (
    "experiment_id",
    "version",
    "upstream_pool",
    "source_pool",
    "intended_horizon",
    "entry_mode",
)


def _is_safe_error_scalar(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    return type(value) is float and math.isfinite(value)


def _error_row(spec: Any, exc: BaseException) -> Dict[str, Any]:
    if isinstance(spec, Mapping):
        # Do not deepcopy arbitrary metadata here: malformed specs may carry
        # objects whose deepcopy raises and must still become an isolated row.
        row = {}
        for key in _ERROR_METADATA_KEYS:
            try:
                value = spec.get(key)
            except Exception:
                continue
            if _is_safe_error_scalar(value):
                row[key] = value
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

    projected_production = json_native_projection(production_output)
    # Project the raw object at each guard edge.  This keeps the official
    # ndarray-backed rows untouched while ensuring both digests use the same
    # native JSON contract.
    before_sha = production_digest(projected_production)
    raw_experiments = _coerce_experiments(experiments)
    rows: List[Dict[str, Any]] = []

    for raw_spec in raw_experiments:
        try:
            spec = get_experiment(raw_spec) if isinstance(raw_spec, str) else _normalise_spec(raw_spec)
            # Deep-copy independently for every experiment.  This prevents a
            # mutating experiment from contaminating a later experiment's
            # view, in addition to protecting the official object.
            shadow_input = copy.deepcopy(projected_production)
            result = spec["builder"](shadow_input)
            rows.append(_result_row(spec, result))
        except Exception as exc:  # isolate one diagnostic from the rest
            rows.append(_error_row(raw_spec, exc))

    after_sha = production_digest(json_native_projection(production_output))
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
            "today_count": _candidate_count(projected_production),
            "comparison_eligible": False,
        },
        "experiments": rows,
    }


def _stable_shadow_hash(*parts: Any, length: int = 20) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _valid_stock_code(value: Any) -> bool:
    code = str(value or "").strip()
    return len(code) == 6 and code.isdigit()


def _positive_close(value: Any) -> Optional[float]:
    raw = value
    if raw is None or isinstance(raw, bool):
        return None
    try:
        close = float(raw)
    except (TypeError, ValueError):
        return None
    return close if math.isfinite(close) and close > 0 else None


def _reference_close_proof(
    candidate: Mapping[str, Any],
    report_date: str,
) -> Tuple[Optional[float], str, bool, bool]:
    """Resolve a close together with evidence that it is the final signal bar."""

    dates = candidate.get("dates")
    closes = candidate.get("closes")
    finals = candidate.get("is_final")
    if (
        isinstance(dates, list)
        and isinstance(closes, list)
        and isinstance(finals, list)
    ):
        if len(dates) == len(closes) == len(finals):
            normalized_dates = [
                str(value or "").split(" ", 1)[0] for value in dates
            ]
            matches = [
                index for index, value in enumerate(normalized_dates)
                if value == report_date
            ]
            if len(matches) == 1:
                index = matches[0]
                close = _positive_close(closes[index])
                is_final = finals[index] is True
                return close, report_date, is_final, bool(
                    close is not None and is_final
                )

    explicit_close = _positive_close(candidate.get("reference_close"))
    explicit_date = str(candidate.get("reference_date") or "").split(" ", 1)[0]
    explicit_final = candidate.get("reference_is_final") is True
    proven = bool(
        explicit_close is not None
        and explicit_date == report_date
        and explicit_final
    )
    return explicit_close, explicit_date, explicit_final, proven


def _shadow_reason_snapshot(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    keys = (
        "decision_engine_v1",
        "best_buy_point",
        "opportunity_score",
        "watch_score",
        "score",
        "source_channel",
        "trend_type",
        "sector",
    )
    return json_native_projection({
        key: candidate.get(key)
        for key in keys
        if key in candidate
    })


def _experiment_candidates(experiment: Mapping[str, Any]) -> List[Any]:
    today = experiment.get("today")
    if isinstance(today, Mapping):
        candidates = today.get("candidates")
        return candidates if isinstance(candidates, list) else []
    result = experiment.get("result")
    if isinstance(result, Mapping):
        candidates = result.get("candidates")
        return candidates if isinstance(candidates, list) else []
    return result if isinstance(result, list) else []


def build_shadow_evaluation_entries(
    report_date: Any,
    generated_at: Any,
    experiments: Iterable[Any],
) -> List[Dict[str, Any]]:
    """Freeze independent candidate rows for later shadow-only review.

    These rows intentionally have no ``recommendation_id``, contribution, or
    formal cohort field.  A missing/invalid reference close remains visible as
    an ineligible research row instead of being converted to a zero return.
    """

    resolved_date = str(report_date or "").strip()
    resolved_generated_at = str(generated_at or "").strip()
    if not resolved_date or not resolved_generated_at:
        raise ValueError("report_date and generated_at are required")
    entries: List[Dict[str, Any]] = []
    seen_ids = set()
    for experiment in experiments or []:
        if not isinstance(experiment, Mapping):
            continue
        experiment_id = str(experiment.get("experiment_id") or "").strip()
        version = str(
            experiment.get("version")
            or experiment.get("strategy_version")
            or ""
        ).strip()
        upstream_pool = str(experiment.get("upstream_pool") or "").strip()
        source_pool = str(experiment.get("source_pool") or "").strip()
        horizon = experiment.get("intended_horizon")
        entry_mode = str(experiment.get("entry_mode") or "").strip()
        valid_contract = bool(
            experiment.get("status") == "available"
            and experiment_id
            and version
            and upstream_pool
            and source_pool
            and not isinstance(horizon, bool)
            and isinstance(horizon, int)
            and horizon in ALLOWED_HORIZONS
            and entry_mode == IMMEDIATE_CLOSE
        )
        for raw_candidate in _experiment_candidates(experiment):
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate = json_native_projection(raw_candidate)
            code = str(candidate.get("code") or "").strip()
            if not _valid_stock_code(code):
                continue
            shadow_id = "shadow:{}".format(_stable_shadow_hash(
                SHADOW_LEDGER_SCHEMA_VERSION,
                resolved_date,
                code,
                experiment_id,
                version,
                source_pool,
                horizon,
                entry_mode,
            ))
            if shadow_id in seen_ids:
                continue
            seen_ids.add(shadow_id)
            (
                reference_close,
                reference_date,
                reference_is_final,
                reference_proven,
            ) = _reference_close_proof(candidate, resolved_date)
            evaluation_eligible = bool(
                valid_contract
                and reference_proven
                and candidate.get("evaluation_eligible") is not False
            )
            entries.append({
                "schema_version": SHADOW_LEDGER_SCHEMA_VERSION,
                "shadow_evaluation_id": shadow_id,
                "evaluation_role": "shadow_candidate",
                "publication_effect": False,
                "evaluation_eligible": evaluation_eligible,
                "report_date": resolved_date,
                "generated_at": resolved_generated_at,
                "code": code,
                "name": str(candidate.get("name") or code),
                "experiment_id": experiment_id,
                "version": version,
                "display_name": str(
                    experiment.get("display_name") or experiment_id
                ),
                "upstream_pool": upstream_pool,
                "source_pool": source_pool,
                "intended_horizon": horizon,
                "entry_mode": entry_mode,
                "reference_close": reference_close,
                "reference_date": reference_date,
                "reference_is_final": reference_is_final,
                "reason_snapshot": _shadow_reason_snapshot(candidate),
                "research_tier": experiment.get("research_tier"),
            })
    entries.sort(key=lambda row: (
        row["experiment_id"], row["version"], row["code"]
    ))
    return entries


def _validate_shadow_entry(entry: Any, *, line_number: Optional[int] = None) -> Dict[str, Any]:
    location = " at line {}".format(line_number) if line_number else ""
    if not isinstance(entry, dict):
        raise ValueError("invalid shadow evaluation entry{}".format(location))
    shadow_id = str(entry.get("shadow_evaluation_id") or "")
    if not shadow_id.startswith("shadow:"):
        raise ValueError("invalid shadow evaluation id{}".format(location))
    if entry.get("recommendation_id") or "cohort_eligible" in entry:
        raise ValueError("formal recommendation fields forbidden in shadow ledger{}".format(location))
    if (
        entry.get("evaluation_role") != "shadow_candidate"
        or entry.get("publication_effect") is not False
    ):
        raise ValueError("invalid shadow isolation fields{}".format(location))
    if not isinstance(entry.get("evaluation_eligible"), bool):
        raise ValueError("invalid shadow eligibility field{}".format(location))
    if entry["evaluation_eligible"] is True:
        required_strings = (
            "experiment_id",
            "version",
            "source_pool",
            "upstream_pool",
        )
        if any(
            not isinstance(entry.get(key), str)
            or not entry.get(key).strip()
            for key in required_strings
        ):
            raise ValueError(
                "incomplete eligible shadow contract{}".format(location)
            )
        horizon = entry.get("intended_horizon")
        if (
            isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or horizon not in ALLOWED_HORIZONS
            or entry.get("entry_mode") != IMMEDIATE_CLOSE
        ):
            raise ValueError(
                "invalid eligible shadow evaluation rule{}".format(location)
            )
        reference_close = _positive_close(entry.get("reference_close"))
        report_date = str(entry.get("report_date") or "").strip()
        if (
            reference_close is None
            or str(entry.get("reference_date") or "").strip() != report_date
            or entry.get("reference_is_final") is not True
        ):
            raise ValueError(
                "unproven eligible shadow reference close{}".format(location)
            )
        if not isinstance(entry.get("reason_snapshot"), dict):
            raise ValueError(
                "invalid eligible shadow reason snapshot{}".format(location)
            )
    return json_native_projection(entry)


def load_shadow_evaluation_entries(path: Any = None) -> List[Dict[str, Any]]:
    resolved = os.fspath(path or DEFAULT_SHADOW_LEDGER_PATH)
    if not os.path.exists(resolved):
        return []
    entries = []
    with open(resolved, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                entry = json.loads(text)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "invalid shadow evaluation ledger line {}: {}".format(
                        line_number, exc
                    )
                )
            entries.append(_validate_shadow_entry(
                entry, line_number=line_number
            ))
    return entries


def append_shadow_evaluation_entries(
    path: Any,
    entries: Iterable[Any],
) -> int:
    """Append unseen shadow IDs to a shadow-only immutable JSONL file."""

    resolved = os.fspath(path or DEFAULT_SHADOW_LEDGER_PATH)
    materialized = [_validate_shadow_entry(entry) for entry in entries or []]
    parent = os.path.dirname(os.path.abspath(resolved))
    os.makedirs(parent, exist_ok=True)
    with open(resolved, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        known_ids = set()
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                existing = json.loads(text)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "invalid shadow evaluation ledger line {}: {}".format(
                        line_number, exc
                    )
                )
            validated = _validate_shadow_entry(
                existing, line_number=line_number
            )
            known_ids.add(validated["shadow_evaluation_id"])
        new_entries = []
        for entry in materialized:
            shadow_id = entry["shadow_evaluation_id"]
            if shadow_id in known_ids:
                continue
            known_ids.add(shadow_id)
            new_entries.append(entry)
        if not new_entries:
            return 0
        handle.seek(0, os.SEEK_END)
        for entry in new_entries:
            handle.write(json.dumps(
                entry,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(new_entries)


def shadow_pending_ledger_path(
    report_date: Any,
    pending_dir: Any = None,
) -> str:
    resolved_date = str(report_date or "").strip()
    if not resolved_date:
        raise ValueError("report_date is required")
    return os.path.join(
        os.fspath(pending_dir or DEFAULT_SHADOW_PENDING_DIR),
        "{}.json".format(resolved_date),
    )


def stage_shadow_evaluation_entries(
    path: Any,
    entries: Iterable[Any],
) -> int:
    """Stage a provisional shadow batch without touching immutable history."""

    resolved = os.fspath(path)
    materialized = [_validate_shadow_entry(entry) for entry in entries or []]
    parent = os.path.dirname(os.path.abspath(resolved))
    os.makedirs(parent, exist_ok=True)
    temporary = "{}.tmp.{}".format(resolved, os.getpid())
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(
            materialized,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        handle.write("\n")
    os.replace(temporary, resolved)
    return len(materialized)


def load_staged_shadow_evaluation_entries(path: Any) -> List[Dict[str, Any]]:
    resolved = os.fspath(path)
    if not os.path.exists(resolved):
        return []
    with open(resolved, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("invalid staged shadow evaluation ledger")
    return [_validate_shadow_entry(entry) for entry in payload]


def finalize_staged_shadow_evaluation_entries(
    staged_path: Any,
    ledger_path: Any = None,
) -> int:
    """Finalize a shadow batch only after the caller validated the report."""

    return append_shadow_evaluation_entries(
        ledger_path or DEFAULT_SHADOW_LEDGER_PATH,
        load_staged_shadow_evaluation_entries(staged_path),
    )


def _shadow_sample_rows(outcomes: List[Dict[str, Any]], horizon_key: str) -> List[Dict[str, Any]]:
    rows = []
    for entry, outcome in outcomes:
        value = outcome["returns"].get(horizon_key)
        if value is None:
            continue
        rows.append({
            "shadow_evaluation_id": entry["shadow_evaluation_id"],
            "rec_date": entry.get("report_date"),
            "code": entry.get("code"),
            "name": entry.get("name"),
            "entry_date": outcome.get("entry_date"),
            "entry_price": outcome.get("entry_price"),
            "target_date": outcome["target_dates"].get(horizon_key),
            "close_return": value,
            "mfe": outcome["mfe"].get(horizon_key),
            "mae": outcome["mae"].get(horizon_key),
            "reason_snapshot": copy.deepcopy(entry.get("reason_snapshot") or {}),
        })
    rows.sort(key=lambda row: (
        row["close_return"], row["shadow_evaluation_id"]
    ))
    if len(rows) <= 3:
        return rows
    selected = [rows[0], rows[len(rows) // 2], rows[-1]]
    return selected


def build_shadow_scorecards(
    entries: Iterable[Any],
    kline_by_code: Mapping[str, Any],
    *,
    trading_calendar: Any = None,
    benchmark_kline: Any = None,
    expected_adjustment: str = "qfq",
) -> List[Dict[str, Any]]:
    """Aggregate only explicit shadow candidates by experiment and horizon."""

    # Local import avoids making the production review module depend on the
    # optional shadow lane.
    from .strategy_review import evaluate_recommendation_entry

    grouped: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("evaluation_role") != "shadow_candidate"
            or entry.get("publication_effect") is not False
            or entry.get("evaluation_eligible") is not True
        ):
            continue
        horizon = entry.get("intended_horizon")
        if (
            isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or horizon not in ALLOWED_HORIZONS
            or entry.get("entry_mode") != IMMEDIATE_CLOSE
        ):
            continue
        key = (
            str(entry.get("experiment_id") or ""),
            str(entry.get("version") or ""),
            horizon,
        )
        if key[0] and key[1]:
            grouped[key].append(entry)

    cards = []
    for (experiment_id, version, horizon), rows in sorted(grouped.items()):
        horizon_key = "t{}".format(horizon)
        evaluated = []
        statuses: Dict[str, int] = defaultdict(int)
        for entry in rows:
            outcome = evaluate_recommendation_entry(
                entry,
                (kline_by_code or {}).get(str(entry.get("code") or "")),
                contribution=entry,
                trading_calendar=trading_calendar,
                benchmark_kline=benchmark_kline,
                expected_adjustment=expected_adjustment,
            )
            evaluated.append((entry, outcome))
            statuses[outcome["status"]] += 1
        close_returns = [
            outcome["returns"][horizon_key]
            for _entry, outcome in evaluated
            if outcome["returns"].get(horizon_key) is not None
        ]
        mfes = [
            outcome["mfe"][horizon_key]
            for _entry, outcome in evaluated
            if outcome["mfe"].get(horizon_key) is not None
        ]
        maes = [
            outcome["mae"][horizon_key]
            for _entry, outcome in evaluated
            if outcome["mae"].get(horizon_key) is not None
        ]
        mature_rows = [
            entry for entry, outcome in evaluated
            if outcome["returns"].get(horizon_key) is not None
        ]
        active_date_values = {
            str(row.get("report_date") or "") for row in mature_rows
            if row.get("report_date")
        }
        active_month_values = {
            value[:7] for value in active_date_values if len(value) >= 7
        }
        sample_size = len(close_returns)
        active_dates = len(active_date_values)
        active_months = len(active_month_values)
        hard_gate_reasons = []
        if sample_size < 100:
            hard_gate_reasons.append("mature_samples_below_100")
        if active_dates < 20:
            hard_gate_reasons.append("active_dates_below_20")
        if active_months < 2:
            hard_gate_reasons.append("active_months_below_2")
        hard_gate_reasons.append("shadow_mode_never_auto_promotes")
        first = rows[0]
        cards.append({
            "experiment_id": experiment_id,
            "display_name": str(first.get("display_name") or experiment_id),
            "strategy_version": version,
            "version": version,
            "upstream_pool": first.get("upstream_pool"),
            "source_pool": first.get("source_pool"),
            "intended_horizon": horizon,
            "entry_mode": IMMEDIATE_CLOSE,
            "sample_size": sample_size,
            "active_dates": active_dates,
            "active_months": active_months,
            "mean_close_return": mean(close_returns) if close_returns else None,
            "median_close_return": median(close_returns) if close_returns else None,
            "up_rate": (
                sum(value > 0 for value in close_returns)
                / sample_size * 100.0
                if sample_size else None
            ),
            "hit_rate_ge_5": (
                sum(value >= 5.0 for value in close_returns)
                / sample_size * 100.0
                if sample_size else None
            ),
            "mean_mfe": mean(mfes) if mfes else None,
            "mean_mae": mean(maes) if maes else None,
            "worst_close_return": min(close_returns) if close_returns else None,
            "research_tier": first.get("research_tier"),
            "comparison_status": "collecting",
            "promotion_eligible": False,
            "hard_gate_reasons": hard_gate_reasons,
            "evaluation_statuses": dict(statuses),
            "representative_samples": _shadow_sample_rows(
                evaluated, horizon_key
            ),
        })
    return cards


__all__ = [
    "DEFAULT_SHADOW_LEDGER_PATH",
    "DEFAULT_SHADOW_PENDING_DIR",
    "append_shadow_evaluation_entries",
    "build_shadow_evaluation_entries",
    "build_shadow_scorecards",
    "clear_experiments",
    "finalize_staged_shadow_evaluation_entries",
    "get_experiment",
    "json_native_projection",
    "list_experiments",
    "load_shadow_evaluation_entries",
    "load_staged_shadow_evaluation_entries",
    "production_digest",
    "register_experiment",
    "run_shadow_evaluations",
    "shadow_pending_ledger_path",
    "stage_shadow_evaluation_entries",
]
