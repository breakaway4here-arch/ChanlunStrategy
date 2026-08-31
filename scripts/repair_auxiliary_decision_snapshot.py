#!/usr/bin/env python3
"""Repair a published auxiliary-decision snapshot without changing picks."""

import argparse
import copy
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.auxiliary_decision import build_decision_brief  # noqa: E402
from chanlun.h4_t3_pool import STRATEGY_VERSION  # noqa: E402
from chanlun.report_generator import (  # noqa: E402
    _build_report_v2_html,
    _escape_inline_json,
    _report_asset_version,
    copy_report_assets,
)
from chanlun.shadow_evaluation import production_digest  # noqa: E402
from scripts import enable_shadow_evaluation_snapshot as atomic  # noqa: E402


EXPERIMENT_ID = "h4-t3-pure-upstream-close-review-v1"
EXPERIMENT_NAME = "H4 T+3 · picks_pure 上游收盘价影子回看"
LEGACY_EXPERIMENT_ID = "h4-t3-close-review-v1"
SUPPORTED_REPORT_DATE = "2026-08-21"
APPROVED_ASSET_SHA256 = {
    "report-v2.js": (
        "d1198f5d3bcefd78f3707e496c0d30c3b63b44ed3b16052cc85710b8ee91cb79"
    ),
    "report-v2.css": (
        "698acaec8b19e940287e679c8378f4590ed69c29cfa0e602c66107c06a197bad"
    ),
}
_TOP_SHADOW_FIELDS = {
    "schema_version",
    "mode",
    "affects_production",
    "status",
    "started_at",
    "production_guard",
    "production_reference",
    "experiments",
    "scorecards",
    "today_entries",
    "review_diagnostics",
    "pending",
}
_EXPERIMENT_FIELDS = {
    "experiment_id",
    "display_name",
    "version",
    "strategy_version",
    "upstream_pool",
    "source_pool",
    "intended_horizon",
    "entry_mode",
    "reference_adjustment",
    "research_tier",
    "mode",
    "status",
    "evaluation_role",
    "affects_production",
    "promotion_eligible",
    "sample_size",
    "excursion_sample_size",
    "active_dates",
    "active_months",
    "mean_close_return",
    "median_close_return",
    "up_rate",
    "hit_rate_ge_5",
    "mean_mfe",
    "mean_mae",
    "worst_close_return",
    "comparison_status",
    "hard_gate_reasons",
    "evaluation_statuses",
    "representative_samples",
    "today",
}
_EMPTY_METRIC_FIELDS = {
    "mean_close_return",
    "median_close_return",
    "up_rate",
    "hit_rate_ge_5",
    "mean_mfe",
    "mean_mae",
    "worst_close_return",
}


def protected_report_digest(report):
    return production_digest({
        key: value
        for key, value in (report or {}).items()
        if key not in {"decision_brief", "shadow_evaluations"}
    })


def formal_report_digest(report):
    return production_digest({
        key: value
        for key, value in (report or {}).items()
        if key != "shadow_evaluations"
    })


def _parse_auxiliary_timestamp(value, report_date, field_name):
    value = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid auxiliary timestamp: {}".format(field_name)
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "invalid auxiliary timestamp timezone: {}".format(field_name)
        )
    if parsed.date().isoformat() != report_date:
        raise ValueError(
            "auxiliary timestamp is outside report date: {}".format(
                field_name
            )
        )
    return parsed.astimezone(timezone.utc), value


def _latest_auxiliary_timestamp(report, report_date):
    candidates = []
    for container_name in (
        "decision_brief",
        "limit_up_snapshot",
        "personal_watchlist",
        "data_quality",
    ):
        container = report.get(container_name)
        if not isinstance(container, dict):
            continue
        for field_name in ("generated_at", "as_of"):
            value = str(container.get(field_name) or "").strip()
            if value:
                candidates.append(_parse_auxiliary_timestamp(
                    value,
                    report_date,
                    "{}.{}".format(container_name, field_name),
                ))
    if not candidates:
        raise ValueError("auxiliary snapshot has no generated_at timestamp")
    return max(candidates, key=lambda item: item[0])[1]


def _invalid_empty_shadow(reason):
    raise ValueError(
        "non-empty shadow or invalid empty shadow contract: {}".format(
            reason
        )
    )


def _validate_empty_shadow_contract(report, report_date):
    shadow = report.get("shadow_evaluations")
    if not isinstance(shadow, dict):
        _invalid_empty_shadow("shadow_evaluations is missing")
    if set(shadow) != _TOP_SHADOW_FIELDS:
        _invalid_empty_shadow("unexpected top-level fields")
    if (
        shadow.get("schema_version") != 1
        or shadow.get("mode") != "shadow"
        or shadow.get("affects_production") is not False
        or shadow.get("status") != "collecting"
    ):
        _invalid_empty_shadow("top-level isolation state")
    report_day = atomic._parse_date(report_date, "report_date")
    started_at = str(shadow.get("started_at") or "")
    deployment_day = atomic._parse_date(started_at, "started_at")
    if deployment_day <= report_day:
        _invalid_empty_shadow("started_at is not post-deployment")

    guard = shadow.get("production_guard")
    if not isinstance(guard, dict) or set(guard) != {
        "unchanged", "before_sha256", "after_sha256"
    }:
        _invalid_empty_shadow("production guard shape")
    before_sha = str(guard.get("before_sha256") or "")
    if (
        guard.get("unchanged") is not True
        or before_sha != str(guard.get("after_sha256") or "")
        or len(before_sha) != 64
        or any(char not in "0123456789abcdef" for char in before_sha)
    ):
        _invalid_empty_shadow("production guard state")

    production_reference = shadow.get("production_reference")
    if (
        not isinstance(production_reference, dict)
        or set(production_reference) != {
            "pool",
            "today_count",
            "intended_horizon",
            "comparison_eligible",
            "reason",
        }
        or production_reference.get("pool") != "picks_fusion"
        or isinstance(production_reference.get("today_count"), bool)
        or not isinstance(production_reference.get("today_count"), int)
        or production_reference.get("intended_horizon") is not None
        or production_reference.get("comparison_eligible") is not False
    ):
        _invalid_empty_shadow("production reference state")

    experiments = shadow.get("experiments")
    if not isinstance(experiments, list) or len(experiments) != 1:
        _invalid_empty_shadow("expected one experiment")
    experiment = experiments[0]
    if not isinstance(experiment, dict) or set(experiment) != _EXPERIMENT_FIELDS:
        _invalid_empty_shadow("experiment shape")
    source_id = str(experiment.get("experiment_id") or "")
    if source_id not in {LEGACY_EXPERIMENT_ID, EXPERIMENT_ID}:
        _invalid_empty_shadow("source experiment is unrelated")
    if (
        experiment.get("version") != STRATEGY_VERSION
        or experiment.get("strategy_version") != STRATEGY_VERSION
        or experiment.get("upstream_pool") != "picks_pure"
        or experiment.get("source_pool") != "h4_t3_pool"
        or experiment.get("intended_horizon") != 3
        or experiment.get("entry_mode") != "immediate_close"
        or experiment.get("reference_adjustment") != "qfq"
        or experiment.get("research_tier") != "oot_shadow"
        or experiment.get("mode") != "shadow"
        or experiment.get("status") != "available"
        or experiment.get("evaluation_role") != "shadow_candidate"
        or experiment.get("affects_production") is not False
        or experiment.get("promotion_eligible") is not False
        or experiment.get("comparison_status") != "collecting"
    ):
        _invalid_empty_shadow("experiment isolation state")
    for field_name in (
        "sample_size",
        "excursion_sample_size",
        "active_dates",
        "active_months",
    ):
        if experiment.get(field_name) != 0:
            _invalid_empty_shadow("{} is not zero".format(field_name))
    if any(experiment.get(field_name) is not None
           for field_name in _EMPTY_METRIC_FIELDS):
        _invalid_empty_shadow("return metrics already exist")
    if (
        experiment.get("evaluation_statuses") != {}
        or experiment.get("representative_samples") != []
        or experiment.get("today") != {"candidates": []}
        or not isinstance(experiment.get("hard_gate_reasons"), list)
        or not experiment.get("hard_gate_reasons")
    ):
        _invalid_empty_shadow("experiment contains evaluated state")
    if shadow.get("scorecards") != [] or shadow.get("today_entries") != []:
        _invalid_empty_shadow("top-level evaluated rows exist")
    if shadow.get("review_diagnostics") != {
        "status": "waiting_for_first_post_deployment_close",
        "historical_backfill": False,
    }:
        _invalid_empty_shadow("review diagnostics state")
    if shadow.get("pending") != {
        "status": "withheld",
        "reason": "awaiting_first_post_deployment_close",
        "entries": 0,
        "finalized": False,
    }:
        _invalid_empty_shadow("pending state")
    return shadow


def _migrate_empty_shadow_contract(report, report_date):
    shadow = _validate_empty_shadow_contract(report, report_date)
    experiments = shadow["experiments"]
    experiment = experiments[0]
    experiment["experiment_id"] = EXPERIMENT_ID
    experiment["display_name"] = EXPERIMENT_NAME
    experiment["upstream_pool"] = "picks_pure"
    experiment["source_pool"] = "h4_t3_pool"
    experiment["entry_mode"] = "immediate_close"
    experiment["intended_horizon"] = 3
    experiment["reference_adjustment"] = "qfq"
    guard_sha = formal_report_digest(report)
    shadow["production_guard"] = {
        "unchanged": True,
        "before_sha256": guard_sha,
        "after_sha256": guard_sha,
    }
    return shadow


def rebuild_auxiliary_report(report, *, report_date=None):
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object")
    rebuilt = copy.deepcopy(report)
    effective_report_date = str(
        rebuilt.get("date") or report_date or ""
    ).strip()
    if not effective_report_date:
        raise ValueError("report date is missing")
    atomic._parse_date(effective_report_date, "report_date")
    quality = rebuilt.get("data_quality")
    quality_date = (
        str(quality.get("report_date") or "")
        if isinstance(quality, dict)
        else ""
    )
    if quality_date and quality_date != effective_report_date:
        raise ValueError("data_quality report date mismatch")
    generated_at = _latest_auxiliary_timestamp(
        rebuilt, effective_report_date
    )
    rebuilt["decision_brief"] = build_decision_brief(
        effective_report_date,
        rebuilt.get("events") or [],
        sector_flow=rebuilt.get("sector_flow") or [],
        limit_up_snapshot=rebuilt.get("limit_up_snapshot") or {},
        personal_watchlist=rebuilt.get("personal_watchlist") or {},
        llm_analyzer=None,
        generated_at=generated_at,
    )
    _migrate_empty_shadow_contract(rebuilt, effective_report_date)
    return rebuilt


def _validate_approved_source_assets():
    source_assets = ROOT_DIR / "chanlun" / "report_assets"
    for asset_name, expected_sha in APPROVED_ASSET_SHA256.items():
        actual_sha = atomic._sha256_file(source_assets / asset_name)
        if actual_sha != expected_sha:
            raise RuntimeError(
                "unapproved report asset: {}".format(asset_name)
            )


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _rebuild_staged_artifacts(
    staged_docs,
    report_date,
    rebuilt_planes,
    original_aggregate,
    original_bootstraps,
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


def _validate_staged_artifacts(
    staged_docs,
    report_date,
    baseline_protected_digests,
    expected_brief,
    expected_shadow,
    original_manifest,
):
    planes = atomic._load_public_planes(staged_docs, report_date)
    for name, payload in planes.items():
        if protected_report_digest(payload) != baseline_protected_digests[name]:
            raise RuntimeError(
                "protected report drift in {}".format(name)
            )
        if payload.get("decision_brief") != expected_brief:
            raise RuntimeError(
                "decision brief differs in {}".format(name)
            )
        if payload.get("shadow_evaluations") != expected_shadow:
            raise RuntimeError("shadow contract differs in {}".format(name))

    guard = expected_shadow.get("production_guard") or {}
    expected_guard = formal_report_digest(planes["daily"])
    if (
        guard.get("unchanged") is not True
        or guard.get("before_sha256") != expected_guard
        or guard.get("after_sha256") != expected_guard
    ):
        raise RuntimeError("canonical production guard mismatch")

    manifest = atomic._read_json(staged_docs / "data" / "index.json")
    if manifest != original_manifest:
        raise RuntimeError("report manifest changed during auxiliary repair")
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
            raise RuntimeError("HTML whitelist mismatch: {}".format(name))
    return planes


def publish_auxiliary_decision_snapshot(*, docs_dir, report_date):
    if str(report_date) != SUPPORTED_REPORT_DATE:
        raise ValueError("unsupported repair date: {}".format(report_date))
    atomic._parse_date(report_date, "report_date")
    _validate_approved_source_assets()
    docs_dir = Path(docs_dir).resolve()
    with atomic._exclusive_docs_publish_lock(docs_dir):
        atomic._recover_incomplete_transaction(docs_dir)
        atomic._cleanup_stale_publication_artifacts(docs_dir, report_date)
        initial_hashes = atomic._public_target_hashes(docs_dir, report_date)
        original_planes = atomic._load_public_planes(docs_dir, report_date)
        for name, payload in original_planes.items():
            payload_date = str(payload.get("date") or "")
            if payload_date and payload_date != report_date:
                raise ValueError("report date mismatch in {}".format(name))
            quality = payload.get("data_quality")
            quality_date = (
                str(quality.get("report_date") or "")
                if isinstance(quality, dict)
                else ""
            )
            if quality_date != report_date:
                raise ValueError(
                    "data_quality report date mismatch in {}".format(name)
                )
        baseline_protected_digests = {
            name: protected_report_digest(payload)
            for name, payload in original_planes.items()
        }
        rebuilt_planes = {}
        rebuilt_planes["daily"] = rebuild_auxiliary_report(
            original_planes["daily"], report_date=report_date
        )
        expected_shadow = copy.deepcopy(
            rebuilt_planes["daily"]["shadow_evaluations"]
        )
        for name in ("aggregate", "inline", "archive"):
            rebuilt = rebuild_auxiliary_report(
                original_planes[name], report_date=report_date
            )
            rebuilt["shadow_evaluations"] = copy.deepcopy(expected_shadow)
            rebuilt_planes[name] = rebuilt
        expected_brief = rebuilt_planes["daily"]["decision_brief"]
        for name, payload in rebuilt_planes.items():
            if payload.get("decision_brief") != expected_brief:
                raise RuntimeError(
                    "rebuilt decision brief differs in {}".format(name)
                )

        original_manifest = atomic._read_json(
            docs_dir / "data" / "index.json"
        )
        original_aggregate = atomic._read_json(docs_dir / "data.json")
        original_bootstraps = {
            "inline": atomic._read_bootstrap_envelope(
                docs_dir / "index.html"
            ),
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
            )
            planes = _validate_staged_artifacts(
                staged_docs,
                report_date,
                baseline_protected_digests,
                expected_brief,
                expected_shadow,
                original_manifest,
            )
            updated_files = atomic._atomic_replace_targets(
                staged_docs,
                docs_dir,
                report_date,
                expected_original_hashes=initial_hashes,
                transaction_id=transaction_id,
            )
        finally:
            if stage_root.exists():
                atomic._remove_controlled_stage_root(
                    stage_root, docs_dir, assume_owned=True
                )
    protected_digests_after = {
        name: protected_report_digest(payload)
        for name, payload in planes.items()
    }
    return {
        "status": "repaired",
        "report_date": report_date,
        "protected_digest_before": baseline_protected_digests["daily"],
        "protected_digest_after": protected_report_digest(planes["daily"]),
        "protected_digests_before": baseline_protected_digests,
        "protected_digests_after": protected_digests_after,
        "formal_digest_after": formal_report_digest(planes["daily"]),
        "shadow_digest": production_digest(expected_shadow),
        "updated_files": updated_files,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Repair a published auxiliary-decision snapshot"
    )
    parser.add_argument("--report-date", required=True)
    parser.add_argument(
        "--docs-dir",
        default=os.fspath(ROOT_DIR / "docs"),
    )
    args = parser.parse_args(argv)
    result = publish_auxiliary_decision_snapshot(
        docs_dir=args.docs_dir,
        report_date=args.report_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
