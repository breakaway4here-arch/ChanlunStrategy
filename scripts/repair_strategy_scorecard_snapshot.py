#!/usr/bin/env python3
"""Repair the review semantics of one already-published official snapshot.

The migration recomputes scorecards from the append-only recommendation
ledger and verified market-history database.  It may rebuild presentation
surfaces, but it refuses to publish when any selection or strategy input
changes.
"""

import argparse
import copy
import json
import os
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.recommendation_ledger import load_recommendation_entries  # noqa: E402
from chanlun.pool_contract import resolve_nested_strategy_pool  # noqa: E402
from chanlun.identity import normalize_identity  # noqa: E402
from chanlun.report_generator import (  # noqa: E402
    _build_report_v2_html,
    _build_report_bootstrap,
    _escape_inline_json,
    _load_previous_full_projection,
    _load_psy12_shadow_history,
    _report_asset_version,
    build_aggregate_day_projection,
    copy_report_assets,
)
from chanlun.report_view_model import build_workspace  # noqa: E402
from chanlun.decision_workbench import build_decision_workbench  # noqa: E402
from chanlun.recommendation_evidence import (  # noqa: E402
    _find_original_candidate,
    _find_serialized_candidate,
    build_recommendation_evidence_projection,
)
from chanlun.report_comparison import write_comparison_index  # noqa: E402
from chanlun.shadow_evaluation import production_digest  # noqa: E402
from chanlun.strategy_review import (  # noqa: E402
    build_strategy_run_manifest,
    build_strategy_scorecards,
    load_strategy_sample_exclusions,
    load_review_market_context_from_store,
)
from scripts import enable_shadow_evaluation_snapshot as atomic  # noqa: E402
from scripts.validate_today_report import (  # noqa: E402
    _luojie_partial_contract_is_safe,
)


RESEARCH_POOLS_WITH_LEGACY_ZERO = ("next_day_boom", "luojie_pool")
COMMON_UPSTREAM_STRATEGY_VIEWS = (
    "main",
    "h4_t3",
    "highlights",
    "observation_top5",
    "acceleration",
    "luojie",
    "confirming",
    "growth_quality",
)
LIMIT_UP_OBSERVATION_EXCEPTION_VIEWS = frozenset(
    view for view in COMMON_UPSTREAM_STRATEGY_VIEWS
    if view not in {"main", "h4_t3"}
)


def _deepcopy_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _candidate_rows(pool):
    if not isinstance(pool, dict):
        return []
    rows = pool.get("candidates")
    return rows if isinstance(rows, list) else []


def _without_review_surfaces(report):
    """Return the selection-protected projection used by the migration."""
    projected = _deepcopy_json(report or {})
    projected.pop("workspace", None)
    projected.pop("strategy_scorecards", None)
    projected.pop("selection_input_health", None)

    diagnostics = projected.get("diagnostics")
    if isinstance(diagnostics, dict):
        diagnostics.pop("strategy_review", None)
        diagnostics.pop("recommendation_ledger", None)

    # The old serializer invented ``0`` for missing research change evidence.
    # Only this display field is exempt; candidate identity, ordering, scores,
    # prices and every selection field remain protected.
    for pool_name in RESEARCH_POOLS_WITH_LEGACY_ZERO:
        for candidate in _candidate_rows(projected.get(pool_name)):
            if isinstance(candidate, dict):
                candidate.pop("change_pct", None)

    shadow = projected.get("shadow_evaluations")
    if isinstance(shadow, dict):
        shadow.pop("production_guard", None)
    return projected


def protected_report_digest(report):
    return production_digest(_without_review_surfaces(report))


def workspace_selection_projection(
    report,
    *,
    ignore_formal=False,
    ignore_views=(),
):
    """Protect user-visible membership/order while allowing semantic labels."""
    workspace = (report or {}).get("workspace")
    if not isinstance(workspace, dict) or not isinstance(
        workspace.get("views"), dict
    ):
        return None
    ignored_views = set(ignore_views or ())
    if ignore_formal:
        ignored_views.update({"main", "h4_t3"})
    return {
        "view_order": [
            name for name in list(workspace.get("view_order") or [])
            if name not in ignored_views
        ],
        "views": {
            name: [
                {
                    "code": str((row or {}).get("code") or ""),
                    "view_rank": (row or {}).get("view_rank"),
                    "sources": list((row or {}).get("sources") or []),
                }
                for row in rows or []
                if isinstance(row, dict)
            ]
            for name, rows in workspace.get("views", {}).items()
            if name not in ignored_views
        },
    }


def _registered_input_incidents(report_date):
    return [
        rule for rule in load_strategy_sample_exclusions()
        if str(report_date) in {
            str(value) for value in rule.get("report_dates") or []
        }
    ]


def _unique_code_list(raw):
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return None
    codes = [str(code or "").strip() for code in raw]
    if any(not code for code in codes) or len(codes) != len(set(codes)):
        return None
    return codes


def _whole_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0 or not number.is_integer():
        return None
    return int(number)


def _luojie_health_contract_is_safe(report, *, allow_budget_exclusions):
    """Validate the producer's per-code research health declaration."""
    pool = report.get("luojie_pool")
    pool = pool if isinstance(pool, dict) else {}
    selection = report.get("selection_input_health")
    selection = selection if isinstance(selection, dict) else {}
    by_strategy = selection.get("by_strategy")
    by_strategy = by_strategy if isinstance(by_strategy, dict) else {}
    embedded = pool.get("input_health")
    fallback = by_strategy.get("luojie_pool")
    health = embedded if isinstance(embedded, dict) else fallback
    if not isinstance(health, dict):
        return False

    if isinstance(embedded, dict) and isinstance(fallback, dict):
        for key in (
            "status", "required_date", "requested_count", "verified_count",
            "missing_count", "invalid_count", "budget_excluded_count",
            "formal_actions_allowed", "research_candidate_output_allowed",
        ):
            if embedded.get(key) != fallback.get(key):
                return False
        for key in (
            "verified_codes", "missing_codes", "invalid_codes",
            "budget_excluded_codes",
        ):
            left = _unique_code_list(embedded.get(key))
            right = _unique_code_list(fallback.get(key))
            if left is None or right is None or set(left) != set(right):
                return False

    requested_count = _whole_number(health.get("requested_count"))
    verified_count = _whole_number(health.get("verified_count"))
    missing_count = _whole_number(health.get("missing_count"))
    invalid_count = _whole_number(health.get("invalid_count"))
    budget_excluded_count = _whole_number(
        health.get("budget_excluded_count")
    )
    verified_codes = _unique_code_list(health.get("verified_codes"))
    missing_codes = _unique_code_list(health.get("missing_codes"))
    invalid_codes = _unique_code_list(health.get("invalid_codes"))
    budget_excluded_codes = _unique_code_list(
        health.get("budget_excluded_codes")
    )
    if any(value is None for value in (
        requested_count,
        verified_count,
        missing_count,
        invalid_count,
        budget_excluded_count,
        verified_codes,
        missing_codes,
        invalid_codes,
        budget_excluded_codes,
    )):
        return False
    verified_set = set(verified_codes)
    missing_set = set(missing_codes)
    invalid_set = set(invalid_codes)
    budget_excluded_set = set(budget_excluded_codes)
    return bool(
        str(health.get("required_date") or "").strip()
        == str(report.get("date") or "").strip()
        and verified_count == len(verified_codes)
        and missing_count == len(missing_codes)
        and invalid_count == len(invalid_codes)
        and budget_excluded_count == len(budget_excluded_codes)
        and requested_count == verified_count + missing_count
        and invalid_count == missing_count
        and invalid_set == missing_set
        and not verified_set.intersection(missing_set)
        and not budget_excluded_set.intersection(
            verified_set | missing_set
        )
        and (allow_budget_exclusions or budget_excluded_count == 0)
    )


def _luojie_research_identity_is_safe(rows):
    """Reject rows that explicitly claim a non-LuoJie/formal identity."""
    watch_actions = {
        "", "盯盘", "仅观察", "观察", "研究观察", "等待确认", "暂无法判断",
    }
    for row in rows:
        if not isinstance(row, dict):
            return False
        if "role" in row and row.get("role") != "research":
            return False
        if "view" in row and row.get("view") != "observation":
            return False
        if (
            "action_semantics" in row
            and row.get("action_semantics") != "watch_only"
        ):
            return False
        if row.get("is_formal_recommendation") is True:
            return False
        if "sources" in row and row.get("sources") != ["luojie"]:
            return False
        for field in ("action", "page_action", "effective_action"):
            if field in row and str(row.get(field) or "").strip() not in watch_actions:
                return False
        formal = row.get("formal_decision_contract")
        if isinstance(formal, dict) and formal:
            return False
    return True


def _fully_verified_luojie_contract_is_safe(report, state):
    pool = report.get("luojie_pool")
    if not isinstance(pool, dict) or not (
        str(pool.get("mode") or "").strip().lower() == "enabled"
        and str(pool.get("status") or "").strip().lower()
        in {"ok", "verified"}
        and state.get("state") in {"ran", "verified_empty"}
        and state.get("contract_valid") is True
    ):
        return False
    selection = report.get("selection_input_health")
    selection = selection if isinstance(selection, dict) else {}
    by_strategy = selection.get("by_strategy")
    by_strategy = by_strategy if isinstance(by_strategy, dict) else {}
    embedded = pool.get("input_health")
    fallback = by_strategy.get("luojie_pool")
    health = embedded if isinstance(embedded, dict) else fallback
    if not isinstance(health, dict) or not (
        str(health.get("status") or "").strip().lower() == "verified"
        and str(health.get("required_date") or "").strip()
        == str(report.get("date") or "").strip()
        and health.get("formal_actions_allowed") is False
        and health.get("research_candidate_output_allowed") is True
    ):
        return False
    if isinstance(embedded, dict) and isinstance(fallback, dict):
        for key in (
            "status", "required_date", "requested_count", "verified_count",
            "missing_count", "formal_actions_allowed",
            "research_candidate_output_allowed",
        ):
            if embedded.get(key) != fallback.get(key):
                return False
        for key in ("verified_codes", "missing_codes"):
            left = _unique_code_list(embedded.get(key))
            right = _unique_code_list(fallback.get(key))
            if left is None or right is None or set(left) != set(right):
                return False
    verified_codes = _unique_code_list(health.get("verified_codes"))
    missing_codes = _unique_code_list(health.get("missing_codes"))
    requested_count = _whole_number(health.get("requested_count"))
    verified_count = _whole_number(health.get("verified_count"))
    missing_count = _whole_number(health.get("missing_count"))
    if None in {
        requested_count, verified_count, missing_count,
    } or verified_codes is None or missing_codes is None:
        return False
    if not (
        verified_count == len(verified_codes)
        and missing_count == 0
        and missing_codes == []
        and requested_count == verified_count
    ):
        return False
    candidate_codes = {
        str(row.get("code") or "").strip()
        for row in state.get("candidates") or []
        if isinstance(row, dict)
    }
    return candidate_codes.issubset(set(verified_codes))


def _independent_luojie_research_contract(report):
    """Return a verified independent-research contract or ``None``."""
    report = report if isinstance(report, dict) else {}
    state = resolve_nested_strategy_pool(report, "luojie_pool")
    partial = state.get("state") == "partial"
    contract_safe = _luojie_health_contract_is_safe(
        report,
        allow_budget_exclusions=partial,
    ) and (
        partial and _luojie_partial_contract_is_safe(report, state)
        or _fully_verified_luojie_contract_is_safe(report, state)
    )
    if not contract_safe:
        return None
    pool = report.get("luojie_pool")
    diagnostics = pool.get("diagnostics") if isinstance(pool, dict) else {}
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    upstream = diagnostics.get("final_common_upstream")
    if not isinstance(upstream, dict) or not (
        upstream.get("upstream_pool") == "picks_pure"
        and upstream.get("enforced") is False
        and upstream.get("reason") == "research_independent_candidate_set"
    ):
        return None

    rows = list(state.get("candidates") or [])
    if not _luojie_research_identity_is_safe(rows):
        return None
    candidate_codes = [
        str(row.get("code") or "").strip()
        for row in rows
        if isinstance(row, dict)
    ]
    if (
        len(candidate_codes) != len(rows)
        or any(not code for code in candidate_codes)
        or len(candidate_codes) != len(set(candidate_codes))
    ):
        return None
    pure_codes = {
        str(row.get("code") or "").strip()
        for row in report.get("picks_pure") or []
        if isinstance(row, dict) and str(row.get("code") or "").strip()
    }
    excluded_codes = sorted(set(candidate_codes) - pure_codes)
    declared_excluded = upstream.get("excluded_codes")
    if not isinstance(declared_excluded, list) or (
        declared_excluded != excluded_codes
        or len(declared_excluded) != len(set(declared_excluded))
    ):
        return None

    expected_counts = {
        "upstream_count": len(pure_codes),
        "input_count": len(candidate_codes),
        "candidate_count": len(candidate_codes),
        "kept_count": len(set(candidate_codes) & pure_codes),
        "excluded_count": len(excluded_codes),
    }
    for key, expected in expected_counts.items():
        value = upstream.get(key)
        if isinstance(value, bool) or value != expected:
            return None
    return {
        "state": state,
        "candidate_codes": candidate_codes,
        "excluded_codes": excluded_codes,
    }


def _has_legacy_luojie_upstream_marker(
    report,
    report_date,
    independent_contract,
):
    """Prove that an empty LuoJie view was closed by this repair script."""
    if not independent_contract:
        return False
    invalid_codes = independent_contract["excluded_codes"]
    expected_marker = {
        "status": "unavailable",
        "required_date": report_date,
        "blocking_reason": "strategy_upstream_contract_mismatch",
        "invalid_count": len(invalid_codes),
        "invalid_codes": invalid_codes,
        "output_hidden": True,
    }
    health = report.get("selection_input_health")
    by_view = health.get("by_view") if isinstance(health, dict) else {}
    if not isinstance(by_view, dict) or by_view.get("luojie") != expected_marker:
        return False

    workspace = report.get("workspace")
    if not isinstance(workspace, dict):
        return False
    views = workspace.get("views")
    counts = workspace.get("counts")
    view_meta = workspace.get("view_meta")
    diagnostics = workspace.get("diagnostics")
    if not (
        isinstance(views, dict)
        and views.get("luojie") == []
        and isinstance(counts, dict)
        and counts.get("luojie") == 0
        and isinstance(view_meta, dict)
        and isinstance(diagnostics, dict)
    ):
        return False
    meta = view_meta.get("luojie")
    if not isinstance(meta, dict) or not (
        meta.get("role") == "research"
        and meta.get("source_pool") == "luojie_pool"
        and meta.get("action_semantics") == "watch_only"
        and meta.get("upstream_contract") == expected_marker
        and meta.get("availability") == {
            "state": "unavailable",
            "reason": (
                "历史输出含 {} 只不在 picks_pure 共同上游全集；"
                "该视图已封闭，保留原始池追溯但不重排。"
            ).format(len(invalid_codes)),
        }
    ):
        return False
    incidents = diagnostics.get("upstream_contract_incidents")
    expected_incident = {
        "view": "luojie",
        "blocking_reason": "strategy_upstream_contract_mismatch",
        "invalid_count": len(invalid_codes),
        "invalid_codes": invalid_codes,
    }
    if not isinstance(incidents, list):
        return False
    luojie_incidents = [
        row for row in incidents
        if isinstance(row, dict) and row.get("view") == "luojie"
    ]
    return luojie_incidents == [expected_incident]


def _remove_legacy_luojie_upstream_marker(report):
    health = report.get("selection_input_health")
    by_view = health.get("by_view") if isinstance(health, dict) else None
    if isinstance(by_view, dict):
        by_view.pop("luojie", None)


def _assert_restored_luojie_workspace(workspace, independent_contract):
    views = workspace.get("views") if isinstance(workspace, dict) else {}
    rows = views.get("luojie") if isinstance(views, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("independent luojie workspace restoration failed")
    expected_codes = independent_contract["candidate_codes"]
    if [str(row.get("code") or "") for row in rows] != expected_codes:
        raise RuntimeError("independent luojie workspace restoration failed")
    for rank, row in enumerate(rows, 1):
        code = expected_codes[rank - 1]
        if not (
            row.get("view_rank") == rank
            and row.get("sources") == ["luojie"]
            and row.get("action_semantics") == "watch_only"
            and row.get("ref") == {"pool": "luojie_pool", "code": code}
        ):
            raise RuntimeError("independent luojie workspace restoration failed")


def _bound_research_observation_is_safe(row, originals):
    """Authenticate the B projection against its actual source member."""
    if not isinstance(row, dict):
        return False
    code = row.get('code')
    ref = row.get('ref')
    if not isinstance(ref, dict) or ref.get('pool') != 'observation_watchlist' or ref.get('code') != code:
        return False
    matched = [item for item in originals if isinstance(item, dict) and item.get('code') == code]
    if not matched or any(item != matched[0] for item in matched[1:]):
        return False
    try:
        canonical = normalize_identity({'asset_type': 'stock', 'code': code})
    except (TypeError, ValueError):
        return False
    if code != canonical.code:
        return False
    state_contracts = {
        'missing_30m_data': ('minute_data_insufficient', 'missing', 'not_evaluated'),
        'waiting_30m_confirm': ('pending_confirmation', 'verified', 'pending'),
        'alignment_without_confirmation': ('pending_confirmation', 'verified', 'pending'),
    }
    fields = ('source_channel', 'reason_code', 'observation_status',
              'minute30_input_status', 'minute30_confirmation_status')
    for item in [row] + matched:
        try:
            if normalize_identity(item).key != canonical.key:
                return False
        except (TypeError, ValueError):
            return False
        if item.get('research_observation_projection') is not True or any(
                item.get(flag) is not False for flag in ('affects_formal', 'is_executable',
                    'eligible_for_l1_v0', 'formal_actions_allowed')):
            return False
        if item.get('view') != 'observation' or item.get('tier') != 'watch' or item.get('source_channel') != 'low_position':
            return False
        reason = item.get('reason_code')
        expected = state_contracts.get(reason) if isinstance(reason, str) else None
        actual = tuple(item.get(field) for field in fields[2:])
        if expected is None or actual != expected:
            return False
        if 'identity_key' in item and item.get('identity_key') != canonical.key:
            return False
        if 'final_display_state' in item and item.get('final_display_state') != 'observe':
            return False
    if any(item.get('identity_key') != canonical.key for item in matched):
        return False
    return all(row.get(field) == matched[0].get(field) for field in fields)


def _bound_independent_luojie_highlight_is_safe(row, contract, canonical_rows):
    """Accept only the actual watch-only projection of a verified LuoJie row."""
    if not isinstance(row, dict) or not contract:
        return False
    code = row.get("code")
    if not isinstance(code, str) or code not in contract["candidate_codes"]:
        return False
    if not (
        row.get("sources") == ["luojie"]
        and row.get("ref") == {"pool": "luojie_pool", "code": code}
        and row.get("view") == "observation"
        and row.get("action_semantics") == "watch_only"
        and row.get("is_formal_recommendation") is False
        and not row.get("formal_decision_contract")
    ):
        return False
    source = next(
        (item for item in contract["state"]["candidates"] if item["code"] == code),
        None,
    )
    canonical = next((item for item in canonical_rows if item.get("code") == code), None)
    if source is None or canonical is None or row != canonical:
        return False
    try:
        identity = normalize_identity({"asset_type": "stock", "code": code})
        return (
            normalize_identity(source, asset_type="stock").key == identity.key
            and normalize_identity(row, asset_type="stock").key == identity.key
        )
    except (TypeError, ValueError):
        return False


def _workspace_upstream_contract_violations(report):
    report = report if isinstance(report, dict) else {}
    independent_luojie = _independent_luojie_research_contract(report)
    observation_originals = report.get('observation_watchlist')
    observation_originals = observation_originals if isinstance(observation_originals, list) else []
    pure_codes = {
        str(row.get("code") or "")
        for row in report.get("picks_pure") or []
        if isinstance(row, dict) and row.get("code")
    }
    workspace = report.get("workspace")
    views = workspace.get("views") if isinstance(workspace, dict) else {}
    views = views if isinstance(views, dict) else {}
    canonical_highlights = (
        build_workspace(report)["views"]["highlights"]
        if independent_luojie is not None and views.get("highlights") else []
    )
    violations = {}
    for view_name in COMMON_UPSTREAM_STRATEGY_VIEWS:
        if view_name == "luojie" and independent_luojie is not None:
            continue
        rows = views.get(view_name)
        rows = rows if isinstance(rows, list) else []

        def _is_limit_up_observation_exception(row):
            return bool(
                view_name in LIMIT_UP_OBSERVATION_EXCEPTION_VIEWS
                and isinstance(row, dict)
                and row.get("view") == "observation"
                and row.get("tier") == "watch"
                and row.get("price_limit_state") == "limit_up"
            )

        def _violates(row):
            if not isinstance(row, dict) or not row.get('code'):
                return False
            code = row.get('code')
            source_rows = [item for item in observation_originals
                           if isinstance(item, dict) and item.get('code') == code]
            declares_b = any(item.get('research_observation_projection') is not None
                             and item.get('research_observation_projection') is not False
                             for item in [row] + source_rows)
            if view_name == 'observation_top5' and declares_b:
                return not _bound_research_observation_is_safe(row, observation_originals)
            if view_name == "highlights" and _bound_independent_luojie_highlight_is_safe(
                row, independent_luojie, canonical_highlights
            ):
                return False
            return str(code) not in pure_codes and not _is_limit_up_observation_exception(row)

        invalid_codes = sorted({
            str(row.get("code") or "")
            for row in rows
            if _violates(row)
        })
        if invalid_codes:
            violations[view_name] = invalid_codes
    return violations


def _has_legacy_observation_upstream_marker(report, report_date, workspace):
    """Only remove the exact old common-pool rejection of now-valid B rows."""
    current = dict(report, workspace=workspace)
    rows = (workspace.get('views') or {}).get('observation_top5') or []
    if not rows or 'observation_top5' in _workspace_upstream_contract_violations(current):
        return False
    originals = report.get('observation_watchlist') or []
    pure_codes = {str(r.get('code') or '') for r in report.get('picks_pure') or [] if isinstance(r, dict)}
    invalid_codes = sorted({row['code'] for row in rows
        if _bound_research_observation_is_safe(row, originals)
        and row['code'] not in pure_codes and row.get('price_limit_state') != 'limit_up'})
    if not invalid_codes:
        return False
    health = report.get('selection_input_health')
    by_view = health.get('by_view') if isinstance(health, dict) else None
    if not isinstance(by_view, dict):
        return False
    marker = by_view.get('observation_top5')
    expected = dict(status='unavailable', required_date=report_date,
        blocking_reason='strategy_upstream_contract_mismatch', invalid_count=len(invalid_codes),
        invalid_codes=invalid_codes, output_hidden=True)
    if (not isinstance(marker, dict) or marker != expected
            or type(marker.get('invalid_count')) is not int or marker.get('output_hidden') is not True):
        return False
    old_workspace = report.get('workspace') or {}
    if not isinstance(old_workspace, dict):
        return False
    old_rows = (old_workspace.get('views') or {}).get('observation_top5')
    if old_rows:
        return 'observation_top5' not in _workspace_upstream_contract_violations(report)
    # A stored empty view needs the original finalizer's matching closing receipt.
    meta = (old_workspace.get('view_meta') or {}).get('observation_top5') or {}
    incidents = (old_workspace.get('diagnostics') or {}).get('upstream_contract_incidents') or []
    observation_incidents = [r for r in incidents if isinstance(r, dict) and r.get('view') == 'observation_top5']
    return (old_rows == [] and (old_workspace.get('counts') or {}).get('observation_top5') == 0
        and meta.get('role') == 'research' and meta.get('source_pool') == 'observation_watchlist'
        and meta.get('action_semantics') == 'watch_only' and meta.get('upstream_contract') == expected
        and meta.get('availability') == dict(state='unavailable', reason=(
            '历史输出含 {} 只不在 picks_pure 共同上游全集；该视图已封闭，保留原始池追溯但不重排。'
        ).format(len(invalid_codes)))
        and observation_incidents == [dict(view='observation_top5',
            blocking_reason=expected['blocking_reason'], invalid_count=len(invalid_codes), invalid_codes=invalid_codes)])


def _has_legacy_highlights_upstream_marker(report, report_date, workspace, contract):
    """Prove that the old guard alone hid a reconstructible mixed view."""
    if not contract:
        return False
    rows = (workspace.get("views") or {}).get("highlights") or []
    if not rows or "highlights" in _workspace_upstream_contract_violations(
        dict(report, workspace=workspace)
    ):
        return False
    pure_codes = {
        str(item.get("code") or "") for item in report.get("picks_pure") or []
        if isinstance(item, dict)
    }
    invalid_codes = sorted({
        row["code"] for row in rows
        if row["code"] not in pure_codes
        and row.get("price_limit_state") != "limit_up"
        and _bound_independent_luojie_highlight_is_safe(row, contract, rows)
    })
    if not invalid_codes:
        return False
    marker = ((report.get("selection_input_health") or {}).get("by_view") or {}).get("highlights")
    expected = {
        "status": "unavailable",
        "required_date": report_date,
        "blocking_reason": "strategy_upstream_contract_mismatch",
        "invalid_count": len(invalid_codes),
        "invalid_codes": invalid_codes,
        "output_hidden": True,
    }
    if marker != expected or type(marker.get("invalid_count")) is not int:
        return False
    old_workspace = report.get("workspace")
    if not isinstance(old_workspace, dict):
        return False
    old_views = old_workspace.get("views")
    old_meta = old_workspace.get("view_meta")
    old_counts = old_workspace.get("counts")
    old_diagnostics = old_workspace.get("diagnostics")
    if not all(isinstance(part, dict) for part in (old_views, old_meta, old_counts, old_diagnostics)):
        return False
    meta = old_meta.get("highlights")
    if not (
        old_views.get("highlights") == []
        and old_counts.get("highlights") == 0
        and isinstance(meta, dict)
        and meta.get("role") == "research"
        and meta.get("source_pool") == "picks_fusion + next_day_boom + luojie_pool + startup_watchlist"
        and meta.get("action_semantics") == "watch_only"
        and meta.get("upstream_contract") == expected
        and meta.get("availability") == {
            "state": "unavailable",
            "reason": (
                "历史输出含 {} 只不在 picks_pure 共同上游全集；"
                "该视图已封闭，保留原始池追溯但不重排。"
            ).format(len(invalid_codes)),
        }
    ):
        return False
    incidents = old_diagnostics.get("upstream_contract_incidents")
    if not isinstance(incidents, list):
        return False
    highlighted = [item for item in incidents if isinstance(item, dict) and item.get("view") == "highlights"]
    return highlighted == [{
        "view": "highlights",
        "blocking_reason": "strategy_upstream_contract_mismatch",
        "invalid_count": len(invalid_codes),
        "invalid_codes": invalid_codes,
    }]


def _apply_workspace_upstream_contract_health(report, report_date):
    violations = _workspace_upstream_contract_violations(report)
    if not violations:
        return {}
    health = report.get("selection_input_health")
    health = health if isinstance(health, dict) else {
        "schema_version": 2,
        "required_date": report_date,
        "status": "unavailable",
        "formal": {
            "status": "unavailable",
            "formal_actions_allowed": False,
            "all_formal_actions_allowed": False,
            "allowed_strategies": [],
            "blocked_strategies": ["daily_fusion", "h4_t3"],
            "invalid_codes": [],
        },
        "by_strategy": {},
    }
    report["selection_input_health"] = health
    by_view = health.get("by_view")
    by_view = by_view if isinstance(by_view, dict) else {}
    health["by_view"] = by_view
    workspace = report.get("workspace")
    if not isinstance(workspace, dict):
        return violations
    views = workspace.get("views")
    views = views if isinstance(views, dict) else {}
    view_meta = workspace.get("view_meta")
    view_meta = view_meta if isinstance(view_meta, dict) else {}
    workspace["view_meta"] = view_meta
    counts = workspace.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    workspace["counts"] = counts
    diagnostics = workspace.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    workspace["diagnostics"] = diagnostics
    incidents = []
    for view_name, invalid_codes in violations.items():
        reason = (
            "历史输出含 {} 只不在 picks_pure 共同上游全集；该视图已封闭，"
            "保留原始池追溯但不重排。"
        ).format(len(invalid_codes))
        by_view[view_name] = {
            "status": "unavailable",
            "required_date": report_date,
            "blocking_reason": "strategy_upstream_contract_mismatch",
            "invalid_count": len(invalid_codes),
            "invalid_codes": invalid_codes,
            "output_hidden": True,
        }
        views[view_name] = []
        counts[view_name] = 0
        meta = view_meta.get(view_name)
        meta = meta if isinstance(meta, dict) else {}
        meta["availability"] = {
            "state": "unavailable",
            "reason": reason,
        }
        meta["upstream_contract"] = by_view[view_name]
        view_meta[view_name] = meta
        incidents.append({
            "view": view_name,
            "blocking_reason": "strategy_upstream_contract_mismatch",
            "invalid_count": len(invalid_codes),
            "invalid_codes": invalid_codes,
        })
    diagnostics["upstream_contract_incidents"] = incidents
    return violations


def _apply_registered_input_health(report, report_date):
    rules = _registered_input_incidents(report_date)
    if not rules:
        return False
    formal_rules = [
        rule for rule in rules
        if "daily_fusion" in set(rule.get("strategy_names") or [])
    ]
    min15_rules = [
        rule for rule in rules
        if "luojie_pool" in set(rule.get("strategy_names") or [])
    ]
    h4_rules = [
        rule for rule in rules
        if "h4_t3" in set(rule.get("strategy_names") or [])
    ]
    invalid_codes = sorted({
        str(code)
        for rule in formal_rules
        for code in rule.get("codes") or []
    })
    existing_health = report.get("selection_input_health")
    existing_health = existing_health if isinstance(existing_health, dict) else {}
    existing_by_strategy = existing_health.get("by_strategy")
    existing_by_strategy = (
        existing_by_strategy if isinstance(existing_by_strategy, dict) else {}
    )
    existing_fusion = existing_by_strategy.get("daily_fusion")
    existing_fusion = existing_fusion if isinstance(existing_fusion, dict) else {}
    fusion_allowed = bool(
        not invalid_codes
        and existing_fusion.get("status") == "verified"
        and existing_fusion.get("formal_actions_allowed") is True
    )
    h4_payload = report.get("h4_t3_pool")
    h4_payload = h4_payload if isinstance(h4_payload, dict) else {}
    h4_diagnostics = h4_payload.get("diagnostics")
    h4_diagnostics = (
        h4_diagnostics if isinstance(h4_diagnostics, dict) else {}
    )
    h4_allowed = bool(
        not h4_rules
        and h4_payload.get("status") == "ok"
        and h4_payload.get("mode") == "production"
        and h4_payload.get("production_attested") is True
        and h4_diagnostics.get("upstream_pool") == "picks_pure"
    )
    luojie_candidates = _candidate_rows(report.get("luojie_pool"))
    luojie_invalid_codes = sorted({
        str(candidate.get("code") or "")
        for candidate in luojie_candidates
        if isinstance(candidate, dict) and candidate.get("code")
    }) if min15_rules else []
    allowed_strategies = [
        name for name, allowed in (
            ("daily_fusion", fusion_allowed),
            ("h4_t3", h4_allowed),
        )
        if allowed
    ]
    blocked_strategies = [
        name for name in ("daily_fusion", "h4_t3")
        if name not in allowed_strategies
    ]
    formal_status = (
        "verified"
        if not blocked_strategies
        else ("unavailable" if not allowed_strategies else "partial")
    )
    report["selection_input_health"] = {
        "schema_version": 2,
        "required_date": report_date,
        "status": (
            formal_status
            if formal_status != "verified"
            else ("partial" if min15_rules else "verified")
        ),
        "formal": {
            "status": formal_status,
            "required_date": report_date,
            "formal_actions_allowed": bool(allowed_strategies),
            "all_formal_actions_allowed": not blocked_strategies,
            "allowed_strategies": allowed_strategies,
            "blocked_strategies": blocked_strategies,
            "invalid_count": len(invalid_codes),
            "invalid_codes": invalid_codes,
            "blocking_reason": (
                "" if not blocked_strategies
                else "strategy_input_stale_or_unverified"
            ),
        },
        "by_strategy": {
            "daily_fusion": {
                "status": "verified" if fusion_allowed else "unavailable",
                "required_date": report_date,
                "dependent_candidate_count": len(invalid_codes),
                "invalid_count": len(invalid_codes),
                "invalid_codes": invalid_codes,
                "formal_actions_allowed": fusion_allowed,
                "blocking_reason": (
                    "" if fusion_allowed
                    else "strategy_input_stale_or_unverified"
                ),
            },
            "h4_t3": {
                "status": "verified" if h4_allowed else "unavailable",
                "required_date": report_date,
                "dependent_candidate_count": int(
                    h4_diagnostics.get("upstream_count") or 0
                ),
                "invalid_count": 0 if h4_allowed else 1,
                "invalid_codes": [],
                "formal_actions_allowed": h4_allowed,
                "blocking_reason": (
                    "" if h4_allowed
                    else (
                        "strategy_upstream_contract_mismatch"
                        if h4_rules else "strategy_run_unattested"
                    )
                ),
            },
            "luojie_pool": {
                "status": "unavailable" if min15_rules else "verified",
                "required_date": report_date,
                "invalid_count": len(luojie_invalid_codes),
                "invalid_codes": luojie_invalid_codes,
                "formal_actions_allowed": False,
                "research_output_trusted": not min15_rules,
                "blocking_reason": (
                    "strategy_input_stale_or_unverified"
                    if min15_rules else ""
                ),
            },
        },
        "sublevels": {
            "15m": {
                "interval": "15m",
                "required_date": report_date,
                "status": "unavailable" if min15_rules else "not_required",
                "blocking_reason": (
                    "strategy_input_stale_or_unverified"
                    if min15_rules else ""
                ),
            },
            "30m": {
                "interval": "30m",
                "required_date": report_date,
                "status": "unavailable" if formal_rules else "not_required",
                "blocking_reason": (
                    "strategy_input_stale_or_unverified"
                    if formal_rules else ""
                ),
            },
        },
        "incident_ids": [
            str(rule.get("incident_id") or "") for rule in rules
        ],
    }
    return True


def formal_report_digest(report):
    return atomic.formal_report_digest(report)


def _is_finite_number(value):
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def _has_change_evidence(candidate):
    closes = candidate.get("closes")
    dates = candidate.get("dates")
    if (
        isinstance(closes, list)
        and isinstance(dates, list)
        and len(closes) >= 2
        and len(dates) == len(closes)
        and _is_finite_number(closes[-1])
        and _is_finite_number(closes[-2])
        and float(closes[-2]) != 0
    ):
        return True
    buy_point = candidate.get("best_buy_point")
    if isinstance(buy_point, dict) and _is_finite_number(
        buy_point.get("change_pct")
    ):
        return True
    return any(
        _is_finite_number(candidate.get(key))
        for key in ("previous_close", "prev_close", "pre_close")
    )


def _remove_unproven_zero_changes(report):
    removed = 0
    for pool_name in RESEARCH_POOLS_WITH_LEGACY_ZERO:
        for candidate in _candidate_rows(report.get(pool_name)):
            if not isinstance(candidate, dict):
                continue
            value = candidate.get("change_pct")
            if (
                _is_finite_number(value)
                and float(value) == 0
                and not _has_change_evidence(candidate)
            ):
                candidate["change_pct"] = None
                removed += 1
    return removed


def _validate_official_snapshot(report, report_date):
    payload_date = str((report or {}).get("date") or "")
    if payload_date and payload_date != report_date:
        raise ValueError("report date mismatch")
    quality = (report or {}).get("data_quality")
    if not isinstance(quality, dict):
        raise ValueError("official closed snapshot is missing data_quality")
    if str(quality.get("report_date") or "") != report_date:
        raise ValueError("report date mismatch in data_quality")
    if not (
        quality.get("is_official") is True
        and quality.get("bar_state") == "closed"
        and quality.get("market_status") == "verified"
    ):
        raise ValueError("repair requires an official closed snapshot")


def _validate_scorecard_contract(scorecards, review_diagnostics):
    if not isinstance(scorecards, dict) or scorecards.get("schema_version") != 2:
        raise ValueError("strategy scorecard schema v2 is required")
    for key in (
        "formal", "baselines", "research", "gates", "classification_failures"
    ):
        if not isinstance(scorecards.get(key), list):
            raise ValueError("invalid strategy scorecard section: {}".format(key))
    if not isinstance(review_diagnostics, dict) or (
        review_diagnostics.get("status") != "ok"
    ):
        raise ValueError("verified strategy review market context is required")


def _ledger_finalization_receipt(report, ledger_entries, report_date):
    report_rows = [
        row for row in (report or {}).get("recommendation_ledger") or []
        if isinstance(row, dict) and row.get("recommendation_id")
    ]
    ledger_ids = {
        str(row.get("recommendation_id") or "")
        for row in ledger_entries
        if isinstance(row, dict)
    }
    report_ids = {
        str(row.get("recommendation_id") or "") for row in report_rows
    }
    finalized_today = len(report_ids & ledger_ids)
    missing = sorted(report_ids - ledger_ids)
    return {
        "status": "finalized" if not missing else "finalization_incomplete",
        "report_date": report_date,
        "today_entries": len(report_ids),
        "finalized_today_entries": finalized_today,
        "missing_today_entries": len(missing),
        "finalized_entries": len(ledger_entries),
        "evaluation_entries": len(ledger_entries),
        "evidence": "immutable_ledger_membership",
    }


def _validate_ledger_finalization(receipt):
    value = receipt if isinstance(receipt, dict) else {}
    today = value.get("today_entries")
    finalized_today = value.get("finalized_today_entries")
    missing = value.get("missing_today_entries")
    if not (
        value.get("status") == "finalized"
        and isinstance(today, int)
        and isinstance(finalized_today, int)
        and isinstance(missing, int)
        and missing == 0
        and finalized_today == today
    ):
        raise ValueError("ledger finalization incomplete")


def _refresh_shadow_guard(report):
    shadow = report.get("shadow_evaluations")
    if not isinstance(shadow, dict):
        return
    guard = shadow.get("production_guard")
    if not isinstance(guard, dict):
        raise ValueError("shadow production guard is missing")
    digest = formal_report_digest(report)
    shadow["production_guard"] = {
        "unchanged": True,
        "before_sha256": digest,
        "after_sha256": digest,
    }


def rebuild_strategy_scorecard_report(
    report,
    *,
    report_date,
    scorecards,
    review_diagnostics,
    ledger_finalization=None,
):
    """Rebuild review-only surfaces while preserving the protected digest."""
    _validate_official_snapshot(report, report_date)
    _validate_scorecard_contract(scorecards, review_diagnostics)
    baseline = protected_report_digest(report)
    incident_correction = bool(_registered_input_incidents(report_date))
    independent_luojie = _independent_luojie_research_contract(report)
    restore_luojie = _has_legacy_luojie_upstream_marker(
        report,
        report_date,
        independent_luojie,
    )
    rebuilt_observation_workspace = build_workspace(report)
    restore_highlights = _has_legacy_highlights_upstream_marker(
        report, report_date, rebuilt_observation_workspace, independent_luojie
    )
    restore_observation = _has_legacy_observation_upstream_marker(
        report, report_date, rebuilt_observation_workspace)
    restore_empty_observation = (restore_observation and
        report.get('workspace', {}).get('views', {}).get('observation_top5') == [])
    original_contract_views = set(
        _workspace_upstream_contract_violations(report)
    )
    rebuilt = _deepcopy_json(report)
    if restore_luojie:
        _remove_legacy_luojie_upstream_marker(rebuilt)
    if restore_highlights:
        rebuilt["selection_input_health"]["by_view"].pop("highlights")
    if restore_observation:
        rebuilt['selection_input_health']['by_view'].pop('observation_top5')
    _apply_registered_input_health(rebuilt, report_date)
    removed = _remove_unproven_zero_changes(rebuilt)
    rebuilt["strategy_scorecards"] = _deepcopy_json(scorecards)
    diagnostics = rebuilt.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        rebuilt["diagnostics"] = diagnostics
    diagnostics["strategy_review"] = _deepcopy_json(review_diagnostics)
    if ledger_finalization is not None:
        _validate_ledger_finalization(ledger_finalization)
        diagnostics["recommendation_ledger"] = _deepcopy_json(
            ledger_finalization
        )
    if "workspace" in rebuilt:
        rebuilt["workspace"] = build_workspace(rebuilt)
        if restore_luojie:
            _assert_restored_luojie_workspace(
                rebuilt["workspace"], independent_luojie
            )
    rebuilt_contract_views = set(
        _workspace_upstream_contract_violations(rebuilt)
    )
    ignored_contract_views = original_contract_views | rebuilt_contract_views
    if restore_luojie:
        ignored_contract_views.add("luojie")
    if restore_highlights:
        ignored_contract_views.add("highlights")
    if restore_empty_observation:
        ignored_contract_views.add('observation_top5')
    baseline_workspace = workspace_selection_projection(
        report,
        ignore_formal=incident_correction,
        ignore_views=ignored_contract_views,
    )
    _apply_workspace_upstream_contract_health(rebuilt, report_date)
    rebuilt_workspace = workspace_selection_projection(
        rebuilt,
        ignore_formal=incident_correction,
        ignore_views=ignored_contract_views,
    )
    if (
        baseline_workspace is not None
        and rebuilt_workspace != baseline_workspace
    ):
        raise RuntimeError("workspace membership or ordering changed")
    _refresh_shadow_guard(rebuilt)
    if protected_report_digest(rebuilt) != baseline:
        raise RuntimeError("protected stock-selection output changed")
    return rebuilt, {
        "unproven_zero_changes_removed": removed,
        "protected_digest": baseline,
        "workspace_selection_digest": (
            production_digest(baseline_workspace)
            if baseline_workspace is not None else None
        ),
        "upstream_contract_blocked_views": sorted(
            rebuilt_contract_views
        ),
        "restored_independent_views": ["luojie"] if restore_luojie else [],
        "restored_highlights_views": ["highlights"] if restore_highlights else [],
        "restored_observation_views": ['observation_top5'] if restore_observation else [],
    }


def compute_scorecards(*, ledger_path, market_db_path, report_date, report_data):
    entries = [
        entry
        for entry in load_recommendation_entries(ledger_path)
        if str(entry.get("report_date") or "") <= report_date
    ]
    if not entries:
        raise ValueError("recommendation ledger is empty through report date")
    klines, calendar, benchmark, diagnostics = (
        load_review_market_context_from_store(
            market_db_path,
            entries,
            as_of=report_date,
        )
    )
    if diagnostics.get("status") != "ok":
        raise ValueError(
            "strategy review market context is not verified: {}".format(
                diagnostics.get("status")
            )
        )
    manifest_report = _deepcopy_json(report_data)
    _apply_registered_input_health(manifest_report, report_date)
    scorecards = build_strategy_scorecards(
        entries,
        klines,
        trading_calendar=calendar,
        benchmark_kline=benchmark,
        run_manifest=build_strategy_run_manifest(manifest_report),
    )
    _validate_scorecard_contract(scorecards, diagnostics)
    ledger_finalization = _ledger_finalization_receipt(
        report_data, entries, report_date
    )
    _validate_ledger_finalization(ledger_finalization)
    return (
        scorecards,
        diagnostics,
        len(entries),
        ledger_finalization,
    )


@contextmanager
def _publication_lock(docs_dir):
    # daily_run.sh already owns this exact inter-process lock.  Reacquiring it
    # from the child repair process would deadlock, so only skip when the
    # trusted wrapper explicitly attests ownership.
    if os.environ.get("CHANLUN_DOCS_PUBLISH_LOCK_HELD") == "1":
        yield
        return
    with atomic._exclusive_docs_publish_lock(docs_dir):
        yield


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _report_generated_at(report, report_date, name):
    if not isinstance(report, dict):
        raise ValueError("{} report is not an object".format(name))
    quality = report.get("data_quality") or {}
    if not isinstance(quality, dict):
        raise ValueError("{} report data_quality is not an object".format(name))
    if (report.get("date", report_date) != report_date
            or quality.get("report_date") != report_date):
        raise ValueError("{} report date mismatch".format(name))
    try:
        generated = datetime.fromisoformat(str(quality.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("{} report generation is unknown".format(name)) from exc
    if generated.utcoffset() is None:
        raise ValueError("{} report generation timezone is unknown".format(name))
    return generated


def _aggregate_projection(source, original):
    """Keep independent supplements; replace report fields from the full source."""
    projected = copy.deepcopy(original)
    report_fields = build_aggregate_day_projection(
        source, include_right_side_shadow="right_side_startup" in source,
    )
    projected.update(report_fields)
    # Optional pools can disappear on a later run. Never retain their old data.
    for key in ("picks_pure", "picks_fusion", "next_day_boom", "luojie_pool",
                "selection_input_health", "strategy_run_manifest", "right_side_startup",
                "psy12", "psy12_shadow"):
        if key not in source:
            projected.pop(key, None)
    for key in set(original).intersection(source):
        if key not in report_fields:
            projected[key] = copy.deepcopy(source[key])
    return projected


def _aggregate_matches_source(aggregate, source):
    source_pools = {}
    for pool in ("picks_pure", "picks_fusion"):
        for report in (aggregate, source):
            rows = report.get(pool) or []
            if not isinstance(rows, list):
                return False
            by_code = {}
            for row in rows:
                if not isinstance(row, dict):
                    return False
                code = row.get("code")
                if not isinstance(code, str) or not code.strip() or code in by_code:
                    return False
                by_code[code] = row
            if report is source:
                source_pools[pool] = by_code
    if aggregate == source:
        return True
    expected = _aggregate_projection(source, aggregate)
    # Legacy light entries were built before chart-window truncation. Their
    # point indexes use the original window, and contextual prices may be
    # absent. These representation differences do not change selection facts.
    for pool in ("picks_pure", "picks_fusion"):
        actual_rows = aggregate.get(pool) or []
        expected_rows = expected.get(pool) or []
        if not isinstance(actual_rows, list) or not isinstance(expected_rows, list):
            return False
        for old, new in zip(actual_rows, expected_rows):
            if not isinstance(old, dict) or not isinstance(new, dict) or old.get("code") != new.get("code"):
                continue
            # Light projection can reorder rows during workspace score
            # backfill. Bind chart-window evidence to the same stock while
            # keeping actual/expected order protected by the final digest.
            full = source_pools[pool].get(new.get("code"))
            if full is None:
                return False
            old_best = old.get("best_buy_point") or {}
            full_best = full.get("best_buy_point") or {}
            dates = full.get("dates") or []
            offset = None
            full_index = full_best.get("index")
            original_index = full_best.get("startup_index")
            signal_date = full_best.get("signal_date")
            if (type(full_index) is int and type(original_index) is int
                    and 0 <= full_index < len(dates) and original_index >= full_index
                    and signal_date and dates[full_index] == signal_date
                    and full_best.get("startup_date") == signal_date
                    and old_best.get("signal_date") == signal_date
                    and old_best.get("index") == original_index):
                offset = original_index - full_index
            pairs = [(old.get("best_buy_point"), new.get("best_buy_point"))]
            for field in ("buy_points", "reference_buy_points", "blocked_buy_points"):
                pairs.extend(zip(old.get(field) or [], new.get(field) or []))
            for old_point, new_point in pairs:
                if not isinstance(old_point, dict) or not isinstance(new_point, dict):
                    continue
                if (offset is not None and type(new_point.get("index")) is int
                        and old_point.get("index") == new_point["index"] + offset):
                    new_point["index"] = old_point["index"]
                for field in ("reference_price", "current_price", "distance_from_reference_pct"):
                    if old_point.get(field) is None:
                        new_point[field] = old_point.get(field)
    return _publication_facts_digest(aggregate) == _publication_facts_digest(expected)


def _publication_facts_digest(report):
    projected = _without_review_surfaces(report)
    health = copy.deepcopy(report.get("selection_input_health"))
    if isinstance(health, dict):
        # This repair has always derived per-view incident visibility. Formal
        # and strategy health are source facts and must still agree.
        health.pop("by_view", None)
    projected["selection_input_health"] = health
    return production_digest(projected)


def _load_latest_public_inputs(docs_dir, report_date):
    """Select one verified daily source; never use file mtimes as precedence."""
    from scripts.validate_today_report import validate_report_contract, validate_runtime_cutover

    source = atomic._read_json(docs_dir / "data" / (report_date + ".json"))
    generated = _report_generated_at(source, report_date, "daily")
    if source.get("date") != report_date:
        raise ValueError("daily report date mismatch")
    errors = validate_report_contract(source, require_official=True) + validate_runtime_cutover(source)
    if errors:
        raise ValueError("daily source is invalid: " + "; ".join(errors))
    try:
        aggregate = atomic._read_json(docs_dir / "data.json")
    except (OSError, ValueError) as exc:
        raise ValueError("aggregate history is unreadable; restore its trusted copy before publishing") from exc
    if (not isinstance(aggregate, dict) or not isinstance(aggregate.get("reports"), dict)
            or not isinstance(aggregate.get("dates"), list)):
        raise ValueError("aggregate history structure is invalid; restore its trusted copy before publishing")
    original_day = aggregate["reports"].get(report_date)
    if not isinstance(original_day, dict):
        raise ValueError("aggregate history has no matching report date; restore its trusted copy before publishing")

    bootstraps = {}
    for name, relative in (("inline", "index.html"), ("archive", report_date + "/index.html")):
        try:
            envelope = atomic._read_bootstrap_envelope(docs_dir / relative)
        except (OSError, ValueError):
            continue
        if envelope.get("pageDate") != report_date:
            raise ValueError("{} page date mismatch".format(name))
        if not isinstance(envelope.get("inlineReportData"), dict):
            raise ValueError("{} inline report is missing".format(name))
        bootstraps[name] = envelope
    if not bootstraps:
        raise ValueError("report shell configuration is unavailable; restore a trusted same-date page before publishing")
    for name in ("inline", "archive"):
        if name not in bootstraps:
            bootstraps[name] = copy.deepcopy(next(iter(bootstraps.values())))

    previous = {"aggregate": original_day,
                **{name: envelope["inlineReportData"] for name, envelope in bootstraps.items()}}
    for name, report in previous.items():
        previous_generation = _report_generated_at(report, report_date, name)
        if previous_generation > generated:
            raise ValueError("{} report is newer than the daily source".format(name))
        if previous_generation == generated:
            matches = (_aggregate_matches_source(report, source) if name == "aggregate"
                       else _publication_facts_digest(report) == _publication_facts_digest(source))
            if not matches:
                raise ValueError("{} conflicts with daily source at the same generation".format(name))
    day = _aggregate_projection(source, original_day)
    # Preserve the original light representation on an already-consistent run.
    if _report_generated_at(original_day, report_date, "aggregate") == generated and _aggregate_matches_source(original_day, source):
        day = copy.deepcopy(original_day)
    return {"daily": source, "aggregate": day,
            "inline": copy.deepcopy(source), "archive": copy.deepcopy(source)}, aggregate, bootstraps


def _bootstrap_receipt(source, evidence, workbench):
    # The independent KPL updater changes only this supplement and its card.
    # Evidence/workbench do not consume it; full four-plane alignment still
    # checks it, but refreshing it must not invalidate unchanged evidence.
    evidence_source = {key: value for key, value in source.items()
                       if key != "kaipanla_context"}
    return {
        "schema_version": 1, "report_date": source.get("date"),
        "source_sha256": _publication_facts_digest(evidence_source),
        "workspace_sha256": production_digest(source.get("workspace")),
        "evidence_sha256": production_digest(evidence),
        "workbench_sha256": production_digest(workbench),
    }


def _bound_published_evidence(envelope, source, *, project_hidden=False):
    """Replay published identities before retaining HTML-only minute evidence.

    This follows the existing bounded MA migration's published-workspace replay;
    it does not recreate independent minute facts from the serialized daily file.
    """
    old_source = envelope.get("inlineReportData") or {}
    evidence = envelope.get("recommendationEvidence")
    workbench = envelope.get("decisionWorkbench")
    workspace = source.get("workspace") or {}
    report_date = source.get("date")
    if not (isinstance(evidence, dict) and evidence.get("schema_version") == 1
            and evidence.get("report_date") == report_date
            and isinstance(evidence.get("views"), dict)
            and isinstance(evidence.get("market_sentiment"), dict)
            and list(evidence["views"]) == workspace.get("view_order")
            and isinstance(workbench, dict) and workbench.get("phase") == "formal"
            and workbench.get("report_date") == report_date
            and isinstance(workbench.get("items"), list)):
        raise ValueError("published bootstrap evidence identity mismatch")
    receipt = envelope.get("reportPublication")
    if receipt is not None and receipt != _bootstrap_receipt(old_source, evidence, workbench):
        raise ValueError("published bootstrap receipt mismatch")
    published = {view: [] for view in evidence["views"]}
    seen = set()
    for item in workbench["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("strategy_results"), list):
            raise ValueError("published workbench item is invalid")
        for result in item["strategy_results"]:
            if not isinstance(result, dict):
                raise ValueError("published strategy source is invalid")
            view, row = result.get("strategy_id"), result.get("candidate")
            if view not in published or not isinstance(row, dict):
                raise ValueError("published strategy view/ref mismatch")
            rank, code = row.get("view_rank"), row.get("code")
            ref = row.get("ref") or {}
            rows = evidence["views"][view]
            identity = (view, code, rank)
            if not (isinstance(ref, dict) and isinstance(rows, list) and type(rank) is int and 1 <= rank <= len(rows)
                    and identity not in seen and item.get("code") == code
                    and result.get("view_rank") == rank and ref.get("code") == code):
                raise ValueError("published strategy source identity mismatch")
            old = rows[rank - 1]
            if not isinstance(old, dict):
                raise ValueError("published evidence row is invalid")
            summary, declared = old.get("summary") or {}, old.get("source_identity") or {}
            if not isinstance(summary, dict) or not isinstance(declared, dict):
                raise ValueError("published evidence source declaration is invalid")
            raw, pool, diagnostic = _find_serialized_candidate(source, row)
            original_raw, original_diagnostic = _find_original_candidate(old_source, row)
            if not (old.get("view") == view and old.get("code") == code
                    and summary.get("code") == code
                    and summary.get("as_of") == report_date
                    and summary.get("pool_identity") == pool
                    and summary.get("view_identity") == view and summary.get("view_rank") == rank
                    and declared.get("status") == "available" and not declared.get("reason")
                    and isinstance(raw, dict) and isinstance(original_raw, dict)
                    and not diagnostic and not original_diagnostic
                    and result.get("evidence") == old):
                raise ValueError("published evidence source binding mismatch")
            seen.add(identity)
            published[view].append(row)
    for view, rows in published.items():
        rows.sort(key=lambda row: row["view_rank"])
        old_rows = evidence["views"][view]
        if not isinstance(old_rows, list) or len(rows) != len(old_rows):
            raise ValueError("published evidence/workbench member sets differ")
    recovered = copy.deepcopy(old_source.get("workspace") or {})
    recovered.update(views=published, counts={view: len(rows) for view, rows in published.items()},
                     view_order=list(published))
    replayed = build_decision_workbench(old_source, recovered, evidence, phase="formal",
                                       snapshot_id=workbench.get("snapshot_id", ""))
    if ({key: value for key, value in replayed.items() if key != "changes"}
            != {key: value for key, value in workbench.items() if key != "changes"}):
        raise ValueError("published evidence cannot replay its workbench")

    selected = copy.deepcopy(evidence)
    for view, old_rows in published.items():
        current = (workspace.get("views") or {}).get(view)
        if not isinstance(current, list):
            raise ValueError("current workspace view is invalid")
        if old_rows and not current:
            meta = ((workspace.get("view_meta") or {}).get(view) or {}).get("upstream_contract") or {}
            health = ((source.get("selection_input_health") or {}).get("by_view") or {}).get(view) or {}
            if not (project_hidden and meta.get("output_hidden") is True
                    and health.get("output_hidden") is True):
                raise ValueError("published evidence includes a closed or stale view")
            selected["views"][view] = []
            continue
        expected = [(row.get("code"), row.get("view_rank"), row.get("ref")) for row in current]
        actual = [(row.get("code"), row.get("view_rank"), row.get("ref")) for row in old_rows]
        if actual != expected:
            raise ValueError("published evidence view/ref membership mismatch")
    return selected


def _same_report_generation(envelope, source, report_date):
    old = envelope.get("inlineReportData") or {}
    return (_report_generated_at(old, report_date, "inline") == _report_generated_at(source, report_date, "daily")
            and _publication_facts_digest(old) == _publication_facts_digest(source))


def _refresh_report_bootstrap(envelope, source, docs_dir, report_date):
    rebuilt = copy.deepcopy(envelope)
    if _same_report_generation(envelope, source, report_date):
        old_source = envelope.get("inlineReportData") or {}
        old_contract = _independent_luojie_research_contract(old_source)
        restore_highlights = _has_legacy_highlights_upstream_marker(
            old_source, report_date, build_workspace(old_source), old_contract
        )
        if restore_highlights:
            current_rows = (source.get("workspace") or {}).get("views", {}).get("highlights")
            expected_rows = build_workspace(source)["views"]["highlights"]
            current_health = ((source.get("selection_input_health") or {}).get("by_view") or {})
            if not (
                current_rows == expected_rows
                and current_rows
                and "highlights" not in current_health
                and "highlights" not in _workspace_upstream_contract_violations(source)
                and protected_report_digest(old_source) == protected_report_digest(source)
            ):
                raise ValueError("restored highlights source binding mismatch")
            # Replay every previously published row against the new source with
            # only the old closed highlights view projected back to its receipt.
            binding_source = copy.deepcopy(source)
            binding_source["workspace"]["views"]["highlights"] = []
            binding_source["workspace"]["counts"]["highlights"] = 0
            binding_source["workspace"]["view_meta"]["highlights"] = copy.deepcopy(
                old_source["workspace"]["view_meta"]["highlights"]
            )
            binding_source["selection_input_health"].setdefault("by_view", {})["highlights"] = copy.deepcopy(
                old_source["selection_input_health"]["by_view"]["highlights"]
            )
            evidence = _bound_published_evidence(envelope, binding_source, project_hidden=True)
            regenerated = build_recommendation_evidence_projection(source, source)
            evidence["views"]["highlights"] = regenerated["views"]["highlights"]
        else:
            evidence = _bound_published_evidence(envelope, source, project_hidden=True)
        history = _load_psy12_shadow_history(docs_dir, as_of_date=report_date)
        workbench = build_decision_workbench(
            source, source.get("workspace", {}), evidence, phase="formal",
            snapshot_id=source.get("snapshot_id", ""),
            previous=_load_previous_full_projection(os.fspath(docs_dir), history, report_date),
        )
        refreshed = {"pageDate": report_date, "inlineReportData": source,
                     "recommendationEvidence": evidence, "decisionWorkbench": workbench}
    else:
        refreshed = _build_report_bootstrap(
            source, source, envelope.get("top10ApiBase", ""),
            envelope.get("precloseApiBase", ""), envelope.get("decisionWatchlistUrl", ""),
            envelope.get("accessKeyHash", ""),
            historical_reports=_load_psy12_shadow_history(docs_dir, as_of_date=report_date),
            output_dir=os.fspath(docs_dir),
        )
    for key in ("pageDate", "inlineReportData", "recommendationEvidence", "decisionWorkbench"):
        rebuilt[key] = refreshed[key]
    rebuilt["reportPublication"] = _bootstrap_receipt(
        source, rebuilt["recommendationEvidence"], rebuilt["decisionWorkbench"])
    return rebuilt


def reconcile_report_bootstraps(envelopes, source, docs_dir, report_date):
    """Choose same-source evidence once and retain each page's shell settings."""
    current = []
    for envelope in envelopes.values():
        if envelope.get("pageDate") != report_date:
            raise ValueError("bootstrap page date mismatch")
        if _same_report_generation(envelope, source, report_date):
            current.append(_refresh_report_bootstrap(envelope, source, docs_dir, report_date))
    if not current:
        current.append(_refresh_report_bootstrap(next(iter(envelopes.values())), source, docs_dir, report_date))
    selected = current[0]
    keys = ("pageDate", "inlineReportData", "recommendationEvidence", "decisionWorkbench", "reportPublication")
    for candidate in current[1:]:
        if any(candidate[key] != selected[key] for key in keys):
            raise ValueError("published pages have conflicting same-generation evidence")
    result = {}
    for name, envelope in envelopes.items():
        result[name] = copy.deepcopy(envelope)
        for key in keys:
            result[name][key] = copy.deepcopy(selected[key])
    return result


def validate_public_report_alignment(docs_dir, report_date):
    docs_dir = Path(docs_dir)
    planes = atomic._load_public_planes(docs_dir, report_date)
    source = planes["daily"]
    _report_generated_at(source, report_date, "daily")
    for name in ("inline", "archive"):
        if planes[name] != source:
            raise ValueError("{} report differs from the daily source".format(name))
    if not _aggregate_matches_source(planes["aggregate"], source):
        raise ValueError("aggregate report differs from the daily source")
    evidence_digests = set()
    for name, relative in (("inline", "index.html"), ("archive", report_date + "/index.html")):
        envelope = atomic._read_bootstrap_envelope(docs_dir / relative)
        if envelope.get("pageDate") != report_date:
            raise ValueError("{} page date mismatch".format(name))
        selected = _bound_published_evidence(envelope, source)
        evidence_digests.add(production_digest(selected))
    if len(evidence_digests) != 1:
        raise ValueError("published pages have conflicting same-generation evidence")
    return planes


def _rebuild_staged_artifacts(
    staged_docs,
    report_date,
    rebuilt_planes,
    original_aggregate,
    original_bootstraps,
    market_db_path,
):
    _write_json(
        staged_docs / "data" / "{}.json".format(report_date),
        rebuilt_planes["daily"],
    )
    aggregate = copy.deepcopy(original_aggregate)
    reports = aggregate.get("reports")
    if not isinstance(reports, dict) or report_date not in reports:
        raise ValueError("aggregate report date mismatch")
    reports[report_date] = rebuilt_planes["aggregate"]
    _write_json(staged_docs / "data.json", aggregate)

    copy_report_assets(os.fspath(staged_docs))
    asset_version = _report_asset_version()
    bootstraps = reconcile_report_bootstraps(
        original_bootstraps, rebuilt_planes["daily"], staged_docs, report_date,
    )
    for name, relative, prefix in (
        ("inline", "index.html", ""),
        ("archive", "{}/index.html".format(report_date), "../"),
    ):
        envelope = bootstraps[name]
        html = _build_report_v2_html(
            report_date,
            _escape_inline_json(envelope),
            asset_prefix=prefix,
            asset_version=asset_version,
        )
        (staged_docs / relative).parent.mkdir(parents=True, exist_ok=True)
        with open(staged_docs / relative, "w", encoding="utf-8") as handle:
            handle.write(html)
    write_comparison_index(
        os.fspath(staged_docs / "data"), market_db_path, window_size=26
    )
    return bootstraps


def _validate_staged_artifacts(
    staged_docs,
    report_date,
    protected_digests,
    workspace_projections,
    workspace_ignored_views,
    expected_scorecards,
    expected_review_diagnostics,
    expected_ledger_finalization,
    original_manifest,
):
    planes = atomic._load_public_planes(staged_docs, report_date)
    for name, payload in planes.items():
        if protected_report_digest(payload) != protected_digests[name]:
            raise RuntimeError("protected report drift in {}".format(name))
        if (
            workspace_projections[name] is not None
            and workspace_selection_projection(
                payload,
                ignore_formal=bool(
                    _registered_input_incidents(report_date)
                ),
                ignore_views=workspace_ignored_views[name],
            )
            != workspace_projections[name]
        ):
            raise RuntimeError(
                "workspace membership or ordering drift in {}".format(name)
            )
        if payload.get("strategy_scorecards") != expected_scorecards:
            raise RuntimeError("scorecards differ in {}".format(name))
        if (payload.get("diagnostics") or {}).get("strategy_review") != (
            expected_review_diagnostics
        ):
            raise RuntimeError("review diagnostics differ in {}".format(name))
        if (payload.get("diagnostics") or {}).get("recommendation_ledger") != (
            expected_ledger_finalization
        ):
            raise RuntimeError(
                "ledger finalization differs in {}".format(name)
            )
        remaining_contract_violations = (
            _workspace_upstream_contract_violations(payload)
        )
        if remaining_contract_violations:
            raise RuntimeError(
                "workspace contains codes outside picks_pure in {}: {}".format(
                    name,
                    sorted(remaining_contract_violations),
                )
            )
        shadow = payload.get("shadow_evaluations") or {}
        guard = shadow.get("production_guard") or {}
        formal_sha = formal_report_digest(payload)
        if not (
            guard.get("unchanged") is True
            and guard.get("before_sha256") == formal_sha
            and guard.get("after_sha256") == formal_sha
        ):
            raise RuntimeError("production guard mismatch in {}".format(name))

    manifest = atomic._read_json(staged_docs / "data" / "index.json")
    if manifest != original_manifest:
        raise RuntimeError("report manifest changed during scorecard repair")
    comparison = atomic._read_json(
        staged_docs / "data" / "comparison-index.json"
    )
    comparison_report = (
        (comparison.get("reports") or {}).get(report_date) or {}
    )
    comparison_views = comparison_report.get("views") or {}
    daily_views = (planes["daily"].get("workspace") or {}).get("views") or {}
    for view_name in ("main", "h4_t3"):
        comparison_codes = [
            str((row or {}).get("code") or "")
            for row in comparison_views.get(view_name) or []
        ]
        daily_codes = [
            str((row or {}).get("code") or "")
            for row in daily_views.get(view_name) or []
        ]
        if comparison_codes != daily_codes:
            raise RuntimeError(
                "formal comparison view mismatch: {}".format(view_name)
            )
    source_assets = ROOT_DIR / "chanlun" / "report_assets"
    for relative in ("report-v2.js", "report-v2.css"):
        if atomic._sha256_file(staged_docs / "assets" / relative) != (
            atomic._sha256_file(source_assets / relative)
        ):
            raise RuntimeError("asset mismatch: {}".format(relative))
    asset_version = _report_asset_version()
    for name, relative, prefix in (
        ("inline", "index.html", ""),
        ("archive", "{}/index.html".format(report_date), "../"),
    ):
        html_path = staged_docs / relative
        envelope = atomic._read_bootstrap_envelope(html_path)
        expected_html = _build_report_v2_html(
            report_date,
            _escape_inline_json(envelope),
            asset_prefix=prefix,
            asset_version=asset_version,
        )
        if html_path.read_bytes().decode("utf-8") != expected_html:
            raise RuntimeError("HTML mismatch: {}".format(name))
    return planes


def publish_strategy_scorecard_snapshot(
    *, docs_dir, report_date, ledger_path, market_db_path
):
    atomic._parse_date(report_date, "report_date")
    docs_dir = Path(docs_dir).resolve()
    with _publication_lock(docs_dir):
        atomic._recover_incomplete_transaction(docs_dir)
        atomic._cleanup_stale_publication_artifacts(docs_dir, report_date)
        comparison_target = "data/comparison-index.json"
        initial_hashes = atomic._public_target_hashes(
            docs_dir,
            report_date,
            extra_targets=(comparison_target,),
            allow_missing=True,
        )
        original_planes, original_aggregate, original_bootstraps = _load_latest_public_inputs(docs_dir, report_date)
        (
            scorecards,
            review_diagnostics,
            ledger_entry_count,
            ledger_finalization,
        ) = compute_scorecards(
                ledger_path=ledger_path,
                market_db_path=market_db_path,
                report_date=report_date,
                report_data=original_planes["daily"],
            )
        protected_digests = {
            name: protected_report_digest(payload)
            for name, payload in original_planes.items()
        }
        rebuilt_planes = {}
        repair_counts = {}
        restored_views = {}
        for name, payload in original_planes.items():
            rebuilt, diagnostics = rebuild_strategy_scorecard_report(
                payload,
                report_date=report_date,
                scorecards=scorecards,
                review_diagnostics=review_diagnostics,
                ledger_finalization=ledger_finalization,
            )
            rebuilt_planes[name] = rebuilt
            repair_counts[name] = diagnostics[
                "unproven_zero_changes_removed"
            ]
            restored_views[name] = set(
                diagnostics["restored_independent_views"]
                + diagnostics["restored_observation_views"]
                + diagnostics["restored_highlights_views"]
            )

        workspace_ignored_views = {
            name: set(_workspace_upstream_contract_violations(payload))
            | restored_views[name]
            for name, payload in original_planes.items()
        }
        workspace_projections = {
            name: workspace_selection_projection(
                payload,
                ignore_formal=bool(_registered_input_incidents(report_date)),
                ignore_views=workspace_ignored_views[name],
            )
            for name, payload in original_planes.items()
        }

        original_manifest = atomic._read_json(
            docs_dir / "data" / "index.json"
        )
        transaction_id = uuid.uuid4().hex
        stage_root = atomic._create_controlled_stage_root(
            docs_dir, transaction_id
        )
        try:
            staged_docs = stage_root / "docs"
            shutil.copytree(docs_dir, staged_docs)
            expected_bootstraps = _rebuild_staged_artifacts(
                staged_docs,
                report_date,
                rebuilt_planes,
                original_aggregate,
                original_bootstraps,
                market_db_path,
            )
            planes = _validate_staged_artifacts(
                staged_docs,
                report_date,
                protected_digests,
                workspace_projections,
                workspace_ignored_views,
                scorecards,
                review_diagnostics,
                ledger_finalization,
                original_manifest,
            )
            validate_public_report_alignment(staged_docs, report_date)
            for name, relative in (("inline", "index.html"), ("archive", report_date + "/index.html")):
                if atomic._read_bootstrap_envelope(staged_docs / relative) != expected_bootstraps[name]:
                    raise RuntimeError("staged bootstrap differs from the selected source evidence")
            updated_files = atomic._atomic_replace_targets(
                staged_docs,
                docs_dir,
                report_date,
                expected_original_hashes=initial_hashes,
                transaction_id=transaction_id,
                extra_targets=(comparison_target,),
                allow_missing=True,
            )
        finally:
            if stage_root.exists():
                atomic._remove_controlled_stage_root(
                    stage_root, docs_dir, assume_owned=True
                )

    return {
        "status": "repaired",
        "report_date": report_date,
        "ledger_entry_count": ledger_entry_count,
        "scorecard_sections": {
            key: len(scorecards[key])
            for key in ("formal", "baselines", "research", "gates")
        },
        "classification_failures": len(scorecards["classification_failures"]),
        "review_diagnostics": review_diagnostics,
        "ledger_finalization": ledger_finalization,
        "research_zero_repairs": repair_counts,
        "protected_digests_before": protected_digests,
        "protected_digests_after": {
            name: protected_report_digest(payload)
            for name, payload in planes.items()
        },
        "formal_digest_after": formal_report_digest(planes["daily"]),
        "updated_files": updated_files,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Repair the published strategy scorecard snapshot"
    )
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--ledger-path", required=True)
    parser.add_argument("--market-db-path", required=True)
    parser.add_argument(
        "--docs-dir", default=os.fspath(ROOT_DIR / "docs")
    )
    args = parser.parse_args(argv)
    result = publish_strategy_scorecard_snapshot(
        docs_dir=args.docs_dir,
        report_date=args.report_date,
        ledger_path=args.ledger_path,
        market_db_path=args.market_db_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
