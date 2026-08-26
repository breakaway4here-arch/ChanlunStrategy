"""Immutable recommendation attribution ledger.

Each report-date/code pair is one recommendation record. Every strategy that
contributed keeps its own frozen decision, version and reason snapshot so later
performance reviews can attribute an outcome without reconstructing history
from today's code.
"""

import hashlib
import json
import math
import os
import fcntl
from datetime import date, datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LEDGER_PATH = os.path.join(
    BASE_DIR, ".cache", "chanlun", "recommendation_ledger.jsonl"
)
DEFAULT_PENDING_DIR = os.path.join(
    BASE_DIR, ".cache", "chanlun", "recommendation_pending"
)
LEDGER_SCHEMA_VERSION = "1"
VALID_DECISIONS = {"recommend", "observe", "reject"}
VALID_PUBLICATION_STATUSES = {"published", "internal", "unknown"}
VALID_USER_ACTIONS = {"recommendation", "watch", "none", "unknown"}
VALID_EVALUATION_ROLES = {"formal", "baseline", "research", "diagnostic"}
VALID_PUBLICATION_SURFACES = {
    "formal_recommendation",
    "baseline_candidates",
    "research_review",
    "gate_diagnostics",
    "technical_detail",
}
_STRATEGY_EVALUATION_ROLES = {
    "daily_fusion": "formal",
    "h4_t3": "formal",
    "daily_pure": "baseline",
    "next_day_boom": "research",
    "luojie_pool": "research",
    "observation_gate": "diagnostic",
}
_ROLE_PUBLICATION_SURFACES = {
    "formal": "formal_recommendation",
    "baseline": "baseline_candidates",
    "research": "research_review",
    "diagnostic": "gate_diagnostics",
}


def _json_safe(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _stable_hash(*parts, length=16):
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _revision(value):
    if isinstance(value, str):
        return value.strip() or "unknown"
    if value is None:
        return "unknown"
    payload = json.dumps(
        _json_safe(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:{}".format(
        hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    )


def _valid_code(value):
    code = str(value or "").strip()
    return len(code) == 6 and code.isdigit()


def _latest_close(item, report_date=None):
    close, _source = _resolve_reference_close(item, report_date=report_date)
    return close


def _positive_close(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _resolve_reference_close(item, *, report_date=None):
    """Resolve the signal close without accepting unverified top-level prices."""
    if not isinstance(item, dict):
        return None, "missing"
    values = item.get("closes")
    has_close_series = False
    try:
        if values is not None and len(values) > 0:
            has_close_series = True
            close = _positive_close(values[-1])
            dates = item.get("dates")
            dates = list(dates) if dates is not None else []
            latest_date = (
                str(dates[-1]).split(" ", 1)[0]
                if dates else ""
            )
            status = item.get("data_status")
            status = status if isinstance(status, dict) else {}
            status_latest_date = str(
                status.get("latest_date") or ""
            ).split(" ", 1)[0]
            status_valid = (
                str(status.get("daily") or "").strip().lower()
                == "verified"
                and status.get("is_final") is True
                and (
                    not status_latest_date
                    or status_latest_date == str(report_date or "").strip()
                )
            )
            if (
                close is not None
                and latest_date == str(report_date or "").strip()
                and status_valid
            ):
                return close, "closes[-1]"
    except (TypeError, ValueError, IndexError):
        has_close_series = True

    # If a close series was supplied but failed its signal-day evidence gate,
    # do not silently replace it with a different top-level price.  That
    # would hide a stale or internally inconsistent source snapshot.
    if has_close_series:
        return None, "missing"

    status = item.get("data_status")
    if isinstance(status, dict) and (
        str(status.get("daily") or "").strip().lower() == "verified"
        and status.get("is_final") is True
        and str(status.get("latest_date") or "").split(" ", 1)[0]
        == str(report_date or "").strip()
    ):
        close = _positive_close(item.get("close"))
        if close is not None:
            return close, "top_level_close"
    return None, "missing"


def _evaluation_metadata(strategy, name):
    """Normalize the role/surface contract for a new ledger contribution."""
    role_field_present = "evaluation_role" in strategy
    requested_role = str(strategy.get("evaluation_role") or "").strip().lower()
    registered_role = _STRATEGY_EVALUATION_ROLES.get(name)
    if role_field_present:
        if requested_role not in VALID_EVALUATION_ROLES:
            role = "unknown"
        elif registered_role and requested_role != registered_role:
            role = "unknown"
        else:
            role = requested_role
    elif registered_role:
        role = registered_role
    else:
        role = "unknown"
    requested_surface = str(
        strategy.get("publication_surface") or ""
    ).strip().lower()
    surface = requested_surface if requested_surface in VALID_PUBLICATION_SURFACES else (
        _ROLE_PUBLICATION_SURFACES.get(role, "technical_detail")
    )
    if role in _ROLE_PUBLICATION_SURFACES:
        # Do not let a malformed or cross-role surface silently redefine the
        # page contract.  The role is the source of truth for the surface.
        surface = _ROLE_PUBLICATION_SURFACES[role]
    else:
        surface = "technical_detail"
    return role, surface


def _evaluation_eligibility(
    role,
    *,
    cohort_eligible,
    publication_status,
    user_action,
    decision_code,
):
    if role == "diagnostic":
        return False, "diagnostic_only"
    if role in {"baseline", "research"}:
        return True, "{}_candidate".format(role)
    if role != "formal":
        return False, "unknown_evaluation_role"
    if cohort_eligible:
        return True, "formal_recommendation"
    if publication_status != "published":
        return False, "not_published"
    if user_action != "recommendation":
        return False, "user_action_not_recommendation"
    if decision_code != "recommend":
        return False, "decision_not_recommend"
    return False, "formal_cohort_ineligible"


def _decision_snapshot(item):
    decision = item.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    best_buy = item.get("best_buy_point")
    best_buy = best_buy if isinstance(best_buy, dict) else {}
    return _json_safe({
        "decision_engine_v1": decision,
        "best_buy_point": best_buy,
        "opportunity_score": item.get("opportunity_score"),
        "watch_score": item.get("watch_score"),
        "score": item.get("score"),
        "source_channel": item.get("source_channel"),
        "trend_type": item.get("trend_type"),
        "sector": item.get("sector"),
    })


def _contribution(report_date, code, item, strategy):
    name = str(strategy.get("strategy_name") or "unknown").strip() or "unknown"
    version = str(strategy.get("strategy_version") or "").strip()
    version_status = "verified" if version else "unknown"
    version = version or "unknown"
    decision = item.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    decision_code = str(decision.get("decision_code") or "").strip().lower()
    if decision_code not in VALID_DECISIONS:
        explicit_decision = str(
            strategy.get("published_decision_code") or ""
        ).strip().lower()
        decision_code = (
            explicit_decision
            if explicit_decision in VALID_DECISIONS
            else "unknown"
        )
    attribution_status = (
        "verified"
        if version_status == "verified" and decision_code != "unknown"
        else "legacy_unknown"
    )
    source_pool = str(strategy.get("source_pool") or name).strip() or name
    display_name = str(strategy.get("display_name") or name).strip() or name
    entry_mode = str(strategy.get("entry_mode") or "unknown").strip()
    intended_horizon = strategy.get("intended_horizon")
    if isinstance(intended_horizon, bool):
        intended_horizon = None
    try:
        intended_horizon = int(intended_horizon)
    except (TypeError, ValueError):
        intended_horizon = None
    if intended_horizon not in (1, 3, 5):
        intended_horizon = None
    publication_status = str(
        strategy.get("publication_status") or "unknown"
    ).strip().lower()
    if publication_status not in VALID_PUBLICATION_STATUSES:
        publication_status = "unknown"
    if strategy.get("user_action_from_decision") is True:
        user_action = {
            "recommend": "recommendation",
            "observe": "watch",
            "reject": "none",
        }.get(decision_code, "unknown")
    else:
        user_action = str(
            strategy.get("user_action") or "unknown"
        ).strip().lower()
    if user_action not in VALID_USER_ACTIONS:
        user_action = "unknown"
    evaluation_role, publication_surface = _evaluation_metadata(strategy, name)
    cohort_eligible = bool(
        evaluation_role == "formal"
        and publication_status == "published"
        and user_action == "recommendation"
        and decision_code == "recommend"
    )
    evaluation_eligible, eligibility_reason = _evaluation_eligibility(
        evaluation_role,
        cohort_eligible=cohort_eligible,
        publication_status=publication_status,
        user_action=user_action,
        decision_code=decision_code,
    )
    return {
        "contribution_id": "contrib:{}".format(_stable_hash(
            LEDGER_SCHEMA_VERSION, report_date, code, name, version, source_pool
        )),
        "strategy_name": name,
        "display_name": display_name,
        "strategy_version": version,
        "version_status": version_status,
        "source_pool": source_pool,
        "decision_code": decision_code,
        "decision_label": str(decision.get("decision") or ""),
        "decision_engine_version": str(decision.get("version") or "unknown"),
        "entry_mode": entry_mode,
        "intended_horizon": intended_horizon,
        "publication_status": publication_status,
        "user_action": user_action,
        "cohort_eligible": cohort_eligible,
        "evaluation_role": evaluation_role,
        "publication_surface": publication_surface,
        "evaluation_eligible": evaluation_eligible,
        "eligibility_reason": eligibility_reason,
        "attribution_status": attribution_status,
        "reason_snapshot": _decision_snapshot(item),
    }


def build_recommendation_entries(
    report_date,
    generated_at,
    strategy_inputs,
    *,
    policy_version="",
    config_revision="",
    code_version="",
):
    """Freeze one immutable entry per report-date/code with all contributors."""
    report_date = str(report_date or "").strip()
    generated_at = str(generated_at or "").strip()
    if not report_date or not generated_at:
        raise ValueError("report_date and generated_at are required")
    by_code = {}
    seen_contributions = set()
    specs = [
        row for row in strategy_inputs or [] if isinstance(row, dict)
    ]
    specs.sort(key=lambda row: (
        str(row.get("strategy_name") or ""),
        str(row.get("strategy_version") or ""),
        str(row.get("source_pool") or ""),
    ))
    for strategy in specs:
        for raw_item in strategy.get("items") or []:
            if not isinstance(raw_item, dict):
                continue
            item = _json_safe(raw_item)
            code = str(item.get("code") or "").strip()
            if not _valid_code(code):
                continue
            contribution = _contribution(report_date, code, item, strategy)
            contribution_id = contribution["contribution_id"]
            if contribution_id in seen_contributions:
                continue
            seen_contributions.add(contribution_id)
            reference_close, reference_close_source = _resolve_reference_close(
                item,
                report_date=report_date,
            )
            entry = by_code.setdefault(code, {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "recommendation_id": "rec:{}".format(_stable_hash(
                    LEDGER_SCHEMA_VERSION, report_date, code
                )),
                "report_date": report_date,
                "generated_at": generated_at,
                "code": code,
                "name": str(item.get("name") or code),
                "reference_close": reference_close,
                "reference_close_source": reference_close_source,
                "policy_version": str(policy_version or "unknown"),
                "config_revision": _revision(config_revision),
                "code_version": str(code_version or "unknown"),
                "strategy_contributions": [],
            })
            if entry["name"] == code and item.get("name"):
                entry["name"] = str(item["name"])
            if entry["reference_close"] is None:
                entry["reference_close"] = reference_close
                entry["reference_close_source"] = reference_close_source
            entry["strategy_contributions"].append(contribution)

    entries = []
    for code in sorted(by_code):
        entry = by_code[code]
        entry["strategy_contributions"].sort(key=lambda row: (
            row["strategy_name"], row["strategy_version"], row["source_pool"]
        ))
        entries.append(entry)
    return entries


def load_recommendation_entries(path=None):
    resolved = os.fspath(path or DEFAULT_LEDGER_PATH)
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
                    "invalid recommendation ledger line {}: {}".format(
                        line_number, exc
                    )
                )
            if not isinstance(entry, dict) or not entry.get("recommendation_id"):
                raise ValueError(
                    "invalid recommendation ledger entry at line {}".format(
                        line_number
                    )
                )
            entries.append(entry)
    return entries


def append_recommendation_entries(path, entries):
    """Append new IDs only; an existing ID is never updated or rewritten."""
    resolved = os.fspath(path or DEFAULT_LEDGER_PATH)
    materialized = [
        _json_safe(entry) for entry in entries or [] if isinstance(entry, dict)
    ]
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
                    "invalid recommendation ledger line {}: {}".format(
                        line_number, exc
                    )
                )
            recommendation_id = str(
                existing.get("recommendation_id") or ""
            ) if isinstance(existing, dict) else ""
            if not recommendation_id:
                raise ValueError(
                    "invalid recommendation ledger entry at line {}".format(
                        line_number
                    )
                )
            known_ids.add(recommendation_id)
        new_entries = []
        for entry in materialized:
            recommendation_id = str(
                entry.get("recommendation_id") or ""
            )
            if not recommendation_id or recommendation_id in known_ids:
                continue
            known_ids.add(recommendation_id)
            new_entries.append(entry)
        if not new_entries:
            return 0
        handle.seek(0, os.SEEK_END)
        for entry in new_entries:
            handle.write(json.dumps(
                entry, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(new_entries)


def pending_ledger_path(report_date, pending_dir=None):
    report_date = str(report_date or "").strip()
    if not report_date:
        raise ValueError("report_date is required")
    return os.path.join(
        os.fspath(pending_dir or DEFAULT_PENDING_DIR),
        "{}.json".format(report_date),
    )


def stage_recommendation_entries(path, entries):
    """Write a provisional daily batch; this is not finalized history."""
    resolved = os.fspath(path)
    materialized = [
        _json_safe(entry)
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("recommendation_id")
    ]
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


def load_staged_recommendation_entries(path):
    resolved = os.fspath(path)
    if not os.path.exists(resolved):
        return []
    with open(resolved, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("invalid staged recommendation ledger")
    for entry in payload:
        if not isinstance(entry, dict) or not entry.get("recommendation_id"):
            raise ValueError("invalid staged recommendation entry")
    return payload


def finalize_staged_recommendation_entries(staged_path, ledger_path=None):
    """Append a previously validated provisional batch to immutable history."""
    entries = load_staged_recommendation_entries(staged_path)
    return append_recommendation_entries(
        ledger_path or DEFAULT_LEDGER_PATH,
        entries,
    )


def prepare_recommendation_history(
    ledger_path,
    staged_path,
    current_entries,
    *,
    publication_eligible,
):
    """Build scorecard input without finalizing an unvalidated report."""
    historical = load_recommendation_entries(ledger_path)
    diagnostics = {
        "status": "withheld",
        "today_entries": len(current_entries or []),
        "staged_entries": 0,
        "finalized_entries": len(historical),
    }
    if publication_eligible:
        diagnostics["staged_entries"] = stage_recommendation_entries(
            staged_path, current_entries
        )
        diagnostics["status"] = "pending_report_validation"

    known_ids = {
        str(entry.get("recommendation_id") or "") for entry in historical
    }
    evaluation_entries = list(historical)
    for entry in current_entries or []:
        recommendation_id = str(entry.get("recommendation_id") or "")
        if recommendation_id and recommendation_id not in known_ids:
            evaluation_entries.append(entry)
            known_ids.add(recommendation_id)
    diagnostics["evaluation_entries"] = len(evaluation_entries)
    return evaluation_entries, diagnostics
