#!/usr/bin/env python3
"""Publish an enabled-but-empty post-deployment shadow snapshot.

This migration intentionally creates no historical samples.  It rebuilds a
complete temporary copy of ``docs`` first and refuses to replace any public
artifact when a non-shadow report field changes.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.h4_t3_pool import STRATEGY_VERSION  # noqa: E402
from chanlun.report_generator import (  # noqa: E402
    _build_report_v2_html,
    _escape_inline_json,
    _report_asset_version,
    copy_report_assets,
)
from chanlun.shadow_evaluation import production_digest  # noqa: E402


EXPERIMENT_ID = "h4-t3-close-review-v1"
PUBLIC_TARGETS = (
    "index.html",
    "data.json",
    "data/{report_date}.json",
    "{report_date}/index.html",
    "assets/report-v2.js",
    "assets/report-v2.css",
)
_BOOTSTRAP_PATTERN = re.compile(
    r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});"
)


class AtomicPublishRollbackError(RuntimeError):
    """A publish failed and one or more rollback/cleanup actions also failed."""

    def __init__(self, original_error, recovery_errors):
        self.original_error = original_error
        self.recovery_errors = tuple(recovery_errors)
        details = "; ".join(
            "{}: {}".format(type(error).__name__, error)
            for error in self.recovery_errors
        )
        super().__init__(
            "atomic publish failed ({}: {}); recovery errors: {}".format(
                type(original_error).__name__, original_error, details
            )
        )


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_bootstrap_envelope(path):
    with open(path, "r", encoding="utf-8") as handle:
        match = _BOOTSTRAP_PATTERN.search(handle.read())
    if not match:
        raise ValueError("missing report bootstrap: {}".format(path))
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("invalid report bootstrap: {}".format(path))
    return payload


def _read_bootstrap(path):
    payload = _read_bootstrap_envelope(path)
    report = payload.get("inlineReportData")
    if not isinstance(report, dict):
        raise ValueError("missing inline report data: {}".format(path))
    return report


def formal_report_digest(report):
    """Digest every report field except the isolated shadow contract."""

    if not isinstance(report, dict):
        raise ValueError("formal report must be a JSON object")
    return production_digest({
        key: value
        for key, value in report.items()
        if key != "shadow_evaluations"
    })


def _parse_date(value, field_name):
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must be YYYY-MM-DD".format(field_name)) from exc
    if parsed.isoformat() != str(value):
        raise ValueError("{} must be YYYY-MM-DD".format(field_name))
    return parsed


def _empty_shadow_contract(report, started_at):
    formal_sha = formal_report_digest(report)
    return {
        "schema_version": 1,
        "mode": "shadow",
        "affects_production": False,
        "status": "collecting",
        "started_at": started_at,
        "production_guard": {
            "unchanged": True,
            "before_sha256": formal_sha,
            "after_sha256": formal_sha,
        },
        "production_reference": {
            "pool": "picks_fusion",
            "today_count": len(report.get("picks_fusion") or []),
            "intended_horizon": None,
            "comparison_eligible": False,
            "reason": "现网主推未声明统一主周期，只作数量与隔离参考",
        },
        "experiments": [{
            "experiment_id": EXPERIMENT_ID,
            "display_name": "H4 T+3 收盘价影子回看",
            "version": STRATEGY_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "upstream_pool": "picks_pure",
            "source_pool": "h4_t3_pool",
            "intended_horizon": 3,
            "entry_mode": "immediate_close",
            "reference_adjustment": "qfq",
            "research_tier": "oot_shadow",
            "mode": "shadow",
            "status": "available",
            "evaluation_role": "shadow_candidate",
            "affects_production": False,
            "promotion_eligible": False,
            "sample_size": 0,
            "excursion_sample_size": 0,
            "active_dates": 0,
            "active_months": 0,
            "mean_close_return": None,
            "median_close_return": None,
            "up_rate": None,
            "hit_rate_ge_5": None,
            "mean_mfe": None,
            "mean_mae": None,
            "worst_close_return": None,
            "comparison_status": "collecting",
            "hard_gate_reasons": [
                "mature_samples_below_100",
                "active_dates_below_20",
                "active_months_below_2",
                "shadow_mode_never_auto_promotes",
            ],
            "evaluation_statuses": {},
            "representative_samples": [],
            "today": {"candidates": []},
        }],
        "scorecards": [],
        "today_entries": [],
        "review_diagnostics": {
            "status": "waiting_for_first_post_deployment_close",
            "historical_backfill": False,
        },
        "pending": {
            "status": "withheld",
            "reason": "awaiting_first_post_deployment_close",
            "entries": 0,
            "finalized": False,
        },
    }


def _validate_source_report(report, report_date, started_at):
    if str(report.get("date") or "") != report_date:
        raise ValueError("report date mismatch")
    report_day = _parse_date(report_date, "report_date")
    deployment_day = _parse_date(started_at, "started_at")
    if deployment_day <= report_day:
        raise ValueError("started_at must be after the historical report date")

    h4 = report.get("h4_t3_pool")
    if not isinstance(h4, dict):
        raise ValueError("h4_t3_pool is missing")
    if h4.get("production_attested") is not True:
        raise ValueError("h4_t3_pool production attestation is missing")
    if h4.get("mode") != "production" or h4.get("status") != "ok":
        raise ValueError("h4_t3_pool is not an available production pool")
    if h4.get("strategy_version") != STRATEGY_VERSION:
        raise ValueError("h4_t3_pool strategy version mismatch")


def _load_public_planes(docs_dir, report_date):
    daily_path = docs_dir / "data" / "{}.json".format(report_date)
    aggregate_path = docs_dir / "data.json"
    aggregate_payload = _read_json(aggregate_path)
    aggregate = aggregate_payload.get("reports", {}).get(report_date)
    if not isinstance(aggregate, dict):
        raise ValueError("aggregate report date mismatch")
    return {
        "daily": _read_json(daily_path),
        "aggregate": aggregate,
        "inline": _read_bootstrap(docs_dir / "index.html"),
        "archive": _read_bootstrap(
            docs_dir / report_date / "index.html"
        ),
    }


def _validate_shadow_payload(payload, expected):
    if payload.get("shadow_evaluations") != expected:
        raise RuntimeError("shadow contract differs between public artifacts")


def _validate_staged_docs(
    staged_docs,
    report_date,
    expected_shadow,
    baseline_digests,
    original_manifest,
):
    planes = _load_public_planes(staged_docs, report_date)
    for name, payload in planes.items():
        actual_digest = formal_report_digest(payload)
        if actual_digest != baseline_digests[name]:
            raise RuntimeError(
                "formal digest drift in {}: {} != {}".format(
                    name, actual_digest, baseline_digests[name]
                )
            )
        _validate_shadow_payload(payload, expected_shadow)

    manifest = _read_json(staged_docs / "data" / "index.json")
    if manifest != original_manifest:
        raise RuntimeError("report manifest changed during shadow rebuild")

    js = (staged_docs / "assets" / "report-v2.js").read_text(
        encoding="utf-8"
    )
    css = (staged_docs / "assets" / "report-v2.css").read_text(
        encoding="utf-8"
    )
    if "function renderShadowEvaluations" not in js:
        raise RuntimeError("shadow renderer missing from public JavaScript")
    if ".shadow-card" not in css:
        raise RuntimeError("shadow styles missing from public CSS")
    return planes


def _with_shadow(formal_report, expected_shadow):
    rebuilt = json.loads(json.dumps(formal_report))
    rebuilt["shadow_evaluations"] = expected_shadow
    return rebuilt


def _rebuild_staged_public_artifacts(
    staged_docs,
    original_planes,
    original_aggregate_payload,
    original_bootstraps,
    report_date,
    expected_shadow,
):
    """Rebuild public artifacts from the already-published canonical data.

    The full report generator accepts raw runtime candidates, not its own
    chart-windowed JSON output.  Feeding a published JSON report back through
    the raw serializer would trim chart arrays a second time and alter formal
    picks.  This migration therefore uses the generator's HTML shell and asset
    builders while treating each verified published plane as canonical.
    """

    daily = _with_shadow(original_planes["daily"], expected_shadow)
    with open(
        staged_docs / "data" / "{}.json".format(report_date),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(daily, handle, ensure_ascii=False, indent=2)

    aggregate = json.loads(json.dumps(original_aggregate_payload))
    day_entry = aggregate.get("reports", {}).get(report_date)
    if not isinstance(day_entry, dict):
        raise ValueError("aggregate report date mismatch")
    day_entry["shadow_evaluations"] = expected_shadow
    with open(staged_docs / "data.json", "w", encoding="utf-8") as handle:
        json.dump(aggregate, handle, ensure_ascii=False, indent=2)

    copy_report_assets(os.fspath(staged_docs))
    asset_version = _report_asset_version()
    for name, relative, prefix in (
        ("inline", "index.html", ""),
        ("archive", "{}/index.html".format(report_date), "../"),
    ):
        bootstrap = json.loads(json.dumps(original_bootstraps[name]))
        bootstrap["inlineReportData"] = _with_shadow(
            original_planes[name], expected_shadow
        )
        html = _build_report_v2_html(
            report_date,
            _escape_inline_json(bootstrap),
            asset_prefix=prefix,
            asset_version=asset_version,
        )
        with open(staged_docs / relative, "w", encoding="utf-8") as handle:
            handle.write(html)


def _atomic_replace_targets(staged_docs, docs_dir, report_date):
    relative_targets = [
        value.format(report_date=report_date) for value in PUBLIC_TARGETS
    ]
    prepared = []
    replaced = []

    def fsync_file(path):
        with open(path, "rb") as handle:
            os.fsync(handle.fileno())

    def fsync_directory(path):
        descriptor = os.open(os.fspath(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def copied_temporary(source, target, suffix):
        descriptor, temporary = tempfile.mkstemp(
            prefix=".{}-".format(target.name),
            suffix=suffix,
            dir=os.fspath(target.parent),
        )
        os.close(descriptor)
        temporary = Path(temporary)
        try:
            shutil.copy2(source, temporary)
            fsync_file(temporary)
            return temporary
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def cleanup_prepared(preserve_backup_ids=None):
        errors = []
        directories = set()
        preserve_backup_ids = preserve_backup_ids or set()
        for item in prepared:
            directories.add(item["target"].parent)
            for key in ("next", "backup"):
                if key == "backup" and id(item) in preserve_backup_ids:
                    continue
                path = item.get(key)
                if path is None:
                    continue
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    errors.append(exc)
        for directory in directories:
            try:
                fsync_directory(directory)
            except OSError as exc:
                errors.append(exc)
        return errors

    try:
        for relative in relative_targets:
            source = staged_docs / relative
            target = docs_dir / relative
            if not source.is_file():
                raise FileNotFoundError(
                    "staged public artifact is missing: {}".format(relative)
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                raise FileNotFoundError(
                    "public artifact is missing: {}".format(relative)
                )
            item = {"target": target, "next": None, "backup": None}
            prepared.append(item)
            item["backup"] = copied_temporary(
                target, target, ".shadow-backup"
            )
            item["next"] = copied_temporary(
                source, target, ".shadow-next"
            )

        for directory in {item["target"].parent for item in prepared}:
            fsync_directory(directory)

        for item in prepared:
            os.replace(
                os.fspath(item["next"]), os.fspath(item["target"])
            )
            replaced.append(item)
            fsync_file(item["target"])
            fsync_directory(item["target"].parent)
    except BaseException as original_error:
        recovery_errors = []
        failed_rollback_ids = set()
        for item in reversed(replaced):
            try:
                os.replace(
                    os.fspath(item["backup"]),
                    os.fspath(item["target"]),
                )
                item["backup"] = None
                fsync_file(item["target"])
                fsync_directory(item["target"].parent)
            except BaseException as exc:
                recovery_errors.append(exc)
                if item.get("backup") is not None:
                    failed_rollback_ids.add(id(item))
        recovery_errors.extend(cleanup_prepared(failed_rollback_ids))
        if recovery_errors:
            raise AtomicPublishRollbackError(
                original_error, recovery_errors
            ) from original_error
        raise

    cleanup_errors = cleanup_prepared()
    if cleanup_errors:
        raise AtomicPublishRollbackError(
            RuntimeError("published but temporary cleanup failed"),
            cleanup_errors,
        )
    return relative_targets


def enable_shadow_evaluation_snapshot(
    *, docs_dir, report_date, started_at
):
    """Enable the first empty OOT shadow snapshot and rebuild public docs."""

    docs_dir = Path(docs_dir).resolve()
    daily_path = docs_dir / "data" / "{}.json".format(report_date)
    if not daily_path.is_file():
        raise ValueError("report date mismatch: missing {}".format(report_date))

    report = _read_json(daily_path)
    _validate_source_report(report, report_date, started_at)
    expected_shadow = _empty_shadow_contract(report, started_at)
    existing_shadow = report.get("shadow_evaluations")
    if existing_shadow is not None and existing_shadow != expected_shadow:
        raise ValueError(
            "existing shadow snapshot is not the expected empty contract"
        )

    before_sha = formal_report_digest(report)
    injected = dict(report)
    injected["shadow_evaluations"] = expected_shadow
    if formal_report_digest(injected) != before_sha:
        raise RuntimeError("formal digest drift during shadow injection")

    original_planes = _load_public_planes(docs_dir, report_date)
    baseline_digests = {
        name: formal_report_digest(payload)
        for name, payload in original_planes.items()
    }
    if baseline_digests["daily"] != before_sha:
        raise RuntimeError("formal digest drift in source daily report")
    original_manifest = _read_json(docs_dir / "data" / "index.json")
    original_aggregate_payload = _read_json(docs_dir / "data.json")
    original_bootstraps = {
        "inline": _read_bootstrap_envelope(docs_dir / "index.html"),
        "archive": _read_bootstrap_envelope(
            docs_dir / report_date / "index.html"
        ),
    }

    docs_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="shadow_snapshot_stage_", dir=os.fspath(docs_dir.parent)
    ) as temporary_root:
        staged_docs = Path(temporary_root) / "docs"
        shutil.copytree(docs_dir, staged_docs)
        _rebuild_staged_public_artifacts(
            staged_docs,
            original_planes,
            original_aggregate_payload,
            original_bootstraps,
            report_date,
            expected_shadow,
        )
        planes = _validate_staged_docs(
            staged_docs,
            report_date,
            expected_shadow,
            baseline_digests,
            original_manifest,
        )
        updated_files = _atomic_replace_targets(
            staged_docs, docs_dir, report_date
        )

    return {
        "status": "enabled_empty",
        "report_date": report_date,
        "started_at": started_at,
        "formal_digest_before": before_sha,
        "formal_digest_after": formal_report_digest(planes["daily"]),
        "historical_backfill": False,
        "updated_files": updated_files,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Publish an enabled-empty stock selection shadow snapshot"
    )
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument(
        "--docs-dir",
        default=os.fspath(ROOT_DIR / "docs"),
    )
    args = parser.parse_args(argv)
    result = enable_shadow_evaluation_snapshot(
        docs_dir=args.docs_dir,
        report_date=args.report_date,
        started_at=args.started_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
