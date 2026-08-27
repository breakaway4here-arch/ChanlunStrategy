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
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.recommendation_ledger import load_recommendation_entries  # noqa: E402
from chanlun.report_generator import (  # noqa: E402
    _build_report_v2_html,
    _escape_inline_json,
    _report_asset_version,
    copy_report_assets,
)
from chanlun.report_view_model import build_workspace  # noqa: E402
from chanlun.report_comparison import write_comparison_index  # noqa: E402
from chanlun.shadow_evaluation import production_digest  # noqa: E402
from chanlun.strategy_review import (  # noqa: E402
    build_strategy_run_manifest,
    build_strategy_scorecards,
    load_strategy_sample_exclusions,
    load_review_market_context_from_store,
)
from scripts import enable_shadow_evaluation_snapshot as atomic  # noqa: E402


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


def _workspace_upstream_contract_violations(report):
    report = report if isinstance(report, dict) else {}
    pure_codes = {
        str(row.get("code") or "")
        for row in report.get("picks_pure") or []
        if isinstance(row, dict) and row.get("code")
    }
    workspace = report.get("workspace")
    views = workspace.get("views") if isinstance(workspace, dict) else {}
    views = views if isinstance(views, dict) else {}
    violations = {}
    for view_name in COMMON_UPSTREAM_STRATEGY_VIEWS:
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

        invalid_codes = sorted({
            str(row.get("code") or "")
            for row in rows
            if isinstance(row, dict)
            and row.get("code")
            and str(row.get("code") or "") not in pure_codes
            and not _is_limit_up_observation_exception(row)
        })
        if invalid_codes:
            violations[view_name] = invalid_codes
    return violations


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
    original_contract_views = set(
        _workspace_upstream_contract_violations(report)
    )
    rebuilt = _deepcopy_json(report)
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
    rebuilt_contract_views = set(
        _workspace_upstream_contract_violations(rebuilt)
    )
    ignored_contract_views = original_contract_views | rebuilt_contract_views
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
    for name, relative, prefix in (
        ("inline", "index.html", ""),
        ("archive", "{}/index.html".format(report_date), "../"),
    ):
        envelope = copy.deepcopy(original_bootstraps[name])
        envelope["inlineReportData"] = rebuilt_planes[name]
        html = _build_report_v2_html(
            report_date,
            _escape_inline_json(envelope),
            asset_prefix=prefix,
            asset_version=asset_version,
        )
        with open(staged_docs / relative, "w", encoding="utf-8") as handle:
            handle.write(html)
    write_comparison_index(
        os.fspath(staged_docs / "data"), market_db_path, window_size=26
    )


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
        if html_path.read_text(encoding="utf-8") != expected_html:
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
        )
        original_planes = atomic._load_public_planes(docs_dir, report_date)
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
        workspace_projections = {
            name: workspace_selection_projection(
                payload,
                ignore_formal=bool(
                    _registered_input_incidents(report_date)
                ),
                ignore_views=set(
                    _workspace_upstream_contract_violations(payload)
                ),
            )
            for name, payload in original_planes.items()
        }
        workspace_ignored_views = {
            name: set(_workspace_upstream_contract_violations(payload))
            for name, payload in original_planes.items()
        }
        rebuilt_planes = {}
        repair_counts = {}
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

        original_manifest = atomic._read_json(
            docs_dir / "data" / "index.json"
        )
        original_aggregate = atomic._read_json(docs_dir / "data.json")
        original_bootstraps = {
            "inline": atomic._read_bootstrap_envelope(docs_dir / "index.html"),
            "archive": atomic._read_bootstrap_envelope(
                docs_dir / report_date / "index.html"
            ),
        }
        transaction_id = uuid.uuid4().hex
        stage_root = atomic._create_controlled_stage_root(
            docs_dir, transaction_id
        )
        try:
            staged_docs = stage_root / "docs"
            shutil.copytree(docs_dir, staged_docs)
            _rebuild_staged_artifacts(
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
            updated_files = atomic._atomic_replace_targets(
                staged_docs,
                docs_dir,
                report_date,
                expected_original_hashes=initial_hashes,
                transaction_id=transaction_id,
                extra_targets=(comparison_target,),
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
