#!/usr/bin/env python3
"""Publish an enabled-but-empty post-deployment shadow snapshot.

This migration intentionally creates no historical samples.  It rebuilds a
complete temporary copy of ``docs`` first and refuses to replace any public
artifact when a non-shadow report field changes.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
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
JOURNAL_SCHEMA_VERSION = 1
LOCK_PATH_ENV = "CHANLUN_DOCS_PUBLISH_LOCK_PATH"
DEFAULT_LOCK_PATH = ROOT_DIR / ".cache" / "chanlun" / "docs-publish.lock"
CONTROLLED_STAGE_PREFIX = ".chanlun-shadow-stage-"
STAGE_OWNER_FILE = ".chanlun-shadow-stage-owner.json"
STAGE_OWNER_NEXT_SUFFIX = ".marker-next"
_TRANSACTION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TEMP_NONCE_PATTERN = r"[a-z0-9_]{8}"
_CONTROLLED_STAGE_PATTERN = re.compile(
    r"^\.chanlun-shadow-stage-([0-9a-f]{32})$"
)
_LEGACY_STAGE_PATTERN = re.compile(
    r"^shadow_snapshot_stage_([a-z0-9_]{8})$"
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


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_transaction_id(value):
    value = str(value or "")
    if not _TRANSACTION_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid shadow publication transaction id")
    return value


def _fsync_file(path):
    with open(path, "rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path):
    descriptor = os.open(os.fspath(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def docs_publish_lock_path(docs_dir):
    configured = os.environ.get(LOCK_PATH_ENV)
    if configured:
        return Path(configured).resolve()
    docs_dir = Path(docs_dir).resolve()
    if docs_dir == (ROOT_DIR / "docs").resolve():
        return DEFAULT_LOCK_PATH.resolve()
    return (docs_dir.parent / ".chanlun-docs-publish.lock").resolve()


def transaction_journal_path(docs_dir):
    return (
        Path(docs_dir).resolve().parent
        / ".chanlun-shadow-snapshot-transaction.json"
    )


@contextmanager
def _exclusive_docs_publish_lock(docs_dir):
    lock_path = docs_publish_lock_path(docs_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield lock_path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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

    data_quality = report.get("data_quality")
    if not isinstance(data_quality, dict):
        raise ValueError("data_quality is missing")
    if str(data_quality.get("report_date") or "") != report_date:
        raise ValueError("data_quality report date mismatch")
    if data_quality.get("is_official") is not True:
        raise ValueError("shadow snapshot requires official data_quality")
    if data_quality.get("bar_state") != "closed":
        raise ValueError("shadow snapshot requires a closed market bar")
    if data_quality.get("sources_trusted") is not True:
        raise ValueError("shadow snapshot requires trusted sources")
    if data_quality.get("market_status") != "verified":
        raise ValueError("shadow snapshot requires verified market status")

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

    js_path = staged_docs / "assets" / "report-v2.js"
    css_path = staged_docs / "assets" / "report-v2.css"
    js = js_path.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8")
    if "function renderShadowEvaluations" not in js:
        raise RuntimeError("shadow renderer missing from public JavaScript")
    if ".shadow-card" not in css:
        raise RuntimeError("shadow styles missing from public CSS")
    source_assets = ROOT_DIR / "chanlun" / "report_assets"
    for staged, source in (
        (js_path, source_assets / "report-v2.js"),
        (css_path, source_assets / "report-v2.css"),
    ):
        if _sha256_file(staged) != _sha256_file(source):
            raise RuntimeError(
                "asset whitelist mismatch: {}".format(staged.name)
            )

    asset_version = _report_asset_version()
    for name, relative, prefix in (
        ("inline", "index.html", ""),
        ("archive", "{}/index.html".format(report_date), "../"),
    ):
        html_path = staged_docs / relative
        bootstrap = _read_bootstrap_envelope(html_path)
        expected_html = _build_report_v2_html(
            report_date,
            _escape_inline_json(bootstrap),
            asset_prefix=prefix,
            asset_version=asset_version,
        )
        if html_path.read_text(encoding="utf-8") != expected_html:
            raise RuntimeError("HTML whitelist mismatch: {}".format(name))
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


def _relative_public_targets(report_date):
    return [
        value.format(report_date=report_date) for value in PUBLIC_TARGETS
    ]


def _owned_public_temp_pattern(target_name, suffix):
    return re.compile(
        r"^\.{}-(?:[0-9a-f]{{32}}-)?{}{}$".format(
            re.escape(target_name),
            _TEMP_NONCE_PATTERN,
            re.escape(suffix),
        )
    )


def _is_owned_public_temp(path, target, suffix, transaction_id=None):
    path = Path(path)
    target = Path(target)
    if path.parent != target.parent:
        return False
    if not _owned_public_temp_pattern(target.name, suffix).fullmatch(path.name):
        return False
    if transaction_id:
        controlled_prefix = ".{}-{}-".format(
            target.name, _validate_transaction_id(transaction_id)
        )
        legacy_prefix = ".{}-".format(target.name)
        if not (
            path.name.startswith(controlled_prefix)
            or (
                path.name.startswith(legacy_prefix)
                and not re.search(r"-[0-9a-f]{32}-", path.name)
            )
        ):
            return False
    return True


def _stage_docs_has_fingerprint(staged_docs):
    if staged_docs.is_symlink() or not staged_docs.is_dir():
        return False
    fingerprints = (
        "index.html",
        "data.json",
        "data/index.json",
        "assets/report-v2.js",
        "assets/report-v2.css",
    )
    return all(
        (staged_docs / relative).is_file()
        and not (staged_docs / relative).is_symlink()
        for relative in fingerprints
    )


def _legacy_stage_is_owned(candidate):
    if not _LEGACY_STAGE_PATTERN.fullmatch(candidate.name):
        return False
    if candidate.is_symlink() or not candidate.is_dir():
        return False
    try:
        entries = list(candidate.iterdir())
    except OSError:
        return False
    if len(entries) != 1 or entries[0].name != "docs":
        return False
    return _stage_docs_has_fingerprint(entries[0])


def _stage_owner_payload(docs_dir, transaction_id):
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "transaction_id": _validate_transaction_id(transaction_id),
        "docs_dir": os.fspath(Path(docs_dir).resolve()),
    }


def _stage_owner_bytes(docs_dir, transaction_id):
    return json.dumps(
        _stage_owner_payload(docs_dir, transaction_id),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def _partial_owner_marker_is_owned(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return False
    try:
        content = path.read_bytes()
    except OSError:
        return False
    return len(content) <= len(expected) and expected.startswith(content)


def _controlled_stage_is_owned(candidate, docs_dir):
    match = _CONTROLLED_STAGE_PATTERN.fullmatch(candidate.name)
    if not match or candidate.is_symlink() or not candidate.is_dir():
        return False
    try:
        entries = list(candidate.iterdir())
    except OSError:
        return False
    if not entries:
        return True
    transaction_id = match.group(1)
    owner_next_name = "{}-{}{}".format(
        STAGE_OWNER_FILE,
        transaction_id,
        STAGE_OWNER_NEXT_SUFFIX,
    )
    allowed = {STAGE_OWNER_FILE, owner_next_name, "docs"}
    if any(entry.name not in allowed for entry in entries):
        return False
    owner = candidate / STAGE_OWNER_FILE
    owner_next = candidate / owner_next_name
    staged_docs = candidate / "docs"
    if staged_docs.exists() and (
        staged_docs.is_symlink() or not staged_docs.is_dir()
    ):
        return False
    expected_payload = _stage_owner_payload(docs_dir, transaction_id)
    expected_bytes = _stage_owner_bytes(docs_dir, transaction_id)
    if owner.is_symlink() or (owner.exists() and not owner.is_file()):
        return False
    if owner_next.is_symlink():
        return False
    if owner_next.exists() and (
        not owner_next.is_file()
        or not _partial_owner_marker_is_owned(owner_next, expected_bytes)
    ):
        return False
    if owner.exists():
        try:
            payload = _read_json(owner)
        except (OSError, ValueError, json.JSONDecodeError):
            payload = None
        if payload == expected_payload:
            return True
        if not staged_docs.exists():
            return _partial_owner_marker_is_owned(owner, expected_bytes)
        return False
    if owner_next.exists() and not staged_docs.exists():
        return True
    if staged_docs.exists() and not owner_next.exists():
        return _stage_docs_has_fingerprint(staged_docs)
    return False


def _remove_controlled_stage_root(
    stage_root, docs_dir, *, assume_owned=False
):
    stage_root = Path(stage_root)
    docs_dir = Path(docs_dir).resolve()
    match = _CONTROLLED_STAGE_PATTERN.fullmatch(stage_root.name)
    if (
        not match
        or stage_root.parent.resolve() != docs_dir.parent
        or stage_root.is_symlink()
        or not stage_root.is_dir()
    ):
        raise ValueError("invalid controlled shadow stage path")
    if not assume_owned and not _controlled_stage_is_owned(
        stage_root, docs_dir
    ):
        raise ValueError("shadow stage ownership mismatch")

    staged_docs = stage_root / "docs"
    if staged_docs.exists():
        if staged_docs.is_symlink() or not staged_docs.is_dir():
            raise ValueError("invalid controlled shadow stage docs")
        shutil.rmtree(staged_docs)
        _fsync_directory(stage_root)

    transaction_id = match.group(1)
    owner_next = stage_root / "{}-{}{}".format(
        STAGE_OWNER_FILE,
        transaction_id,
        STAGE_OWNER_NEXT_SUFFIX,
    )
    if owner_next.exists():
        if owner_next.is_symlink() or not owner_next.is_file():
            raise ValueError("invalid shadow stage owner temporary")
        owner_next.unlink()
        _fsync_directory(stage_root)

    owner = stage_root / STAGE_OWNER_FILE
    if owner.exists():
        if owner.is_symlink() or not owner.is_file():
            raise ValueError("invalid shadow stage owner")
        owner.unlink()
        _fsync_directory(stage_root)
    stage_root.rmdir()
    _fsync_directory(stage_root.parent)


def _create_controlled_stage_root(docs_dir, transaction_id):
    docs_dir = Path(docs_dir).resolve()
    transaction_id = _validate_transaction_id(transaction_id)
    stage_root = docs_dir.parent / "{}{}".format(
        CONTROLLED_STAGE_PREFIX, transaction_id
    )
    stage_root.mkdir(mode=0o700)
    owner = stage_root / STAGE_OWNER_FILE
    owner_next = stage_root / "{}-{}{}".format(
        STAGE_OWNER_FILE,
        transaction_id,
        STAGE_OWNER_NEXT_SUFFIX,
    )
    try:
        _fsync_directory(stage_root.parent)
        with open(owner_next, "xb") as handle:
            handle.write(_stage_owner_bytes(docs_dir, transaction_id))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(stage_root)
        os.replace(os.fspath(owner_next), os.fspath(owner))
        _fsync_file(owner)
        _fsync_directory(stage_root)
        _fsync_directory(stage_root.parent)
    except BaseException:
        try:
            _remove_controlled_stage_root(
                stage_root, docs_dir, assume_owned=True
            )
        except BaseException:
            pass
        raise
    return stage_root


def _cleanup_stale_publication_artifacts(docs_dir, report_date):
    """Remove only artifacts whose names and ownership fingerprints are ours."""

    docs_dir = Path(docs_dir).resolve()
    errors = []
    changed_directories = set()
    for candidate in docs_dir.parent.iterdir():
        try:
            if _controlled_stage_is_owned(candidate, docs_dir):
                _remove_controlled_stage_root(candidate, docs_dir)
                continue
            if _legacy_stage_is_owned(candidate):
                shutil.rmtree(candidate)
                changed_directories.add(candidate.parent)
        except OSError as exc:
            errors.append(exc)

    for relative in _relative_public_targets(report_date):
        target = docs_dir / relative
        try:
            siblings = list(target.parent.iterdir())
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(exc)
            continue
        for candidate in siblings:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not any(
                _is_owned_public_temp(candidate, target, suffix)
                for suffix in (".shadow-backup", ".shadow-next")
            ):
                continue
            try:
                candidate.unlink()
                changed_directories.add(candidate.parent)
            except OSError as exc:
                errors.append(exc)

    journal_path = transaction_journal_path(docs_dir)
    journal_next_pattern = re.compile(
        r"^\.?{}-(?:[0-9a-f]{{32}}-)?{}\.journal\-next$".format(
            re.escape(journal_path.name), _TEMP_NONCE_PATTERN
        )
    )
    for candidate in docs_dir.parent.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if not journal_next_pattern.fullmatch(candidate.name):
            continue
        try:
            candidate.unlink()
            changed_directories.add(candidate.parent)
        except OSError as exc:
            errors.append(exc)

    for directory in changed_directories:
        try:
            _fsync_directory(directory)
        except OSError as exc:
            errors.append(exc)
    if errors:
        raise RuntimeError(
            "stale shadow publication cleanup failed: {}".format(
                "; ".join(str(error) for error in errors)
            )
        )


def _public_target_hashes(docs_dir, report_date):
    hashes = {}
    for relative in _relative_public_targets(report_date):
        target = Path(docs_dir) / relative
        if not target.is_file():
            raise FileNotFoundError(
                "public artifact is missing: {}".format(relative)
            )
        hashes[relative] = _sha256_file(target)
    return hashes


def _write_transaction_journal(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    transaction_id = _validate_transaction_id(
        payload.get("transaction_id") if isinstance(payload, dict) else None
    )
    descriptor, temporary = tempfile.mkstemp(
        prefix="{}-{}-".format(path.name, transaction_id),
        suffix=".journal-next",
        dir=os.fspath(path.parent),
    )
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(os.fspath(temporary), os.fspath(path))
        _fsync_file(path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _remove_transaction_journal(path):
    path.unlink()
    _fsync_directory(path.parent)


def _resolve_journal_artifact(docs_dir, relative, suffix=None):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("transaction journal contains an invalid path")
    docs_dir = Path(docs_dir).resolve()
    resolved = (docs_dir / relative).resolve()
    try:
        resolved.relative_to(docs_dir)
    except ValueError as exc:
        raise ValueError("transaction journal path escapes docs") from exc
    if suffix and not resolved.name.endswith(suffix):
        raise ValueError("transaction journal artifact suffix mismatch")
    return resolved


def _cleanup_transaction_artifacts(items, docs_dir):
    errors = []
    directories = set()
    for item in items:
        for key, suffix in (
            ("next", ".shadow-next"),
            ("backup", ".shadow-backup"),
        ):
            relative = item.get(key)
            if not relative:
                continue
            try:
                path = _resolve_journal_artifact(
                    docs_dir, relative, suffix=suffix
                )
                directories.add(path.parent)
                path.unlink()
            except FileNotFoundError:
                pass
            except BaseException as exc:
                errors.append(exc)
    for directory in directories:
        try:
            _fsync_directory(directory)
        except OSError as exc:
            errors.append(exc)
    return errors


def _validate_journal_artifact_paths(items, docs_dir, transaction_id):
    docs_dir = Path(docs_dir).resolve()
    transaction_id = _validate_transaction_id(transaction_id)
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("transaction journal item is invalid")
        target = _resolve_journal_artifact(docs_dir, item.get("target"))
        for key, suffix in (
            ("backup", ".shadow-backup"),
            ("next", ".shadow-next"),
        ):
            artifact = _resolve_journal_artifact(
                docs_dir, item.get(key), suffix=suffix
            )
            if not _is_owned_public_temp(
                artifact,
                target,
                suffix,
                transaction_id=transaction_id,
            ):
                raise ValueError(
                    "transaction journal artifact ownership mismatch"
                )


def _recover_incomplete_transaction(docs_dir):
    """Recover or finish one durable docs publication transaction."""

    docs_dir = Path(docs_dir).resolve()
    journal_path = transaction_journal_path(docs_dir)
    if not journal_path.exists():
        return False
    journal = _read_json(journal_path)
    if not isinstance(journal, dict) or journal.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise ValueError("unsupported shadow publication journal")
    report_date = str(journal.get("report_date") or "")
    _parse_date(report_date, "journal report_date")
    items = journal.get("items")
    if not isinstance(items, list):
        raise ValueError("transaction journal items are missing")
    expected_targets = _relative_public_targets(report_date)
    if [item.get("target") for item in items if isinstance(item, dict)] != expected_targets:
        raise ValueError("transaction journal target whitelist mismatch")
    transaction_id = _validate_transaction_id(journal.get("transaction_id"))
    _validate_journal_artifact_paths(items, docs_dir, transaction_id)
    status = journal.get("status")
    if status not in {"prepared", "publishing", "committed"}:
        raise ValueError("transaction journal status is invalid")

    recovery_errors = []
    if status == "committed":
        for item in items:
            try:
                target = _resolve_journal_artifact(docs_dir, item["target"])
                if _sha256_file(target) != item.get("staged_sha256"):
                    raise RuntimeError(
                        "committed transaction target digest mismatch: {}".format(
                            item["target"]
                        )
                    )
            except BaseException as exc:
                recovery_errors.append(exc)
    else:
        for item in reversed(items):
            try:
                target = _resolve_journal_artifact(docs_dir, item["target"])
                current_sha = _sha256_file(target)
                original_sha = item.get("original_sha256")
                staged_sha = item.get("staged_sha256")
                if current_sha == original_sha:
                    continue
                if current_sha != staged_sha:
                    raise RuntimeError(
                        "transaction target has an unknown digest: {}".format(
                            item["target"]
                        )
                    )
                backup = _resolve_journal_artifact(
                    docs_dir, item["backup"], suffix=".shadow-backup"
                )
                if _sha256_file(backup) != original_sha:
                    raise RuntimeError(
                        "transaction backup digest mismatch: {}".format(
                            item["target"]
                        )
                    )
                os.replace(os.fspath(backup), os.fspath(target))
                _fsync_file(target)
                _fsync_directory(target.parent)
            except BaseException as exc:
                recovery_errors.append(exc)
        if not recovery_errors:
            try:
                restored = _public_target_hashes(docs_dir, report_date)
                expected = {
                    item["target"]: item["original_sha256"] for item in items
                }
                if restored != expected:
                    raise RuntimeError(
                        "transaction rollback did not restore all targets"
                    )
            except BaseException as exc:
                recovery_errors.append(exc)

    if recovery_errors:
        raise AtomicPublishRollbackError(
            RuntimeError("persistent transaction recovery failed"),
            recovery_errors,
        )
    cleanup_errors = _cleanup_transaction_artifacts(items, docs_dir)
    if cleanup_errors:
        raise AtomicPublishRollbackError(
            RuntimeError("persistent transaction cleanup failed"),
            cleanup_errors,
        )
    _remove_transaction_journal(journal_path)
    return True


def _copy_fsynced_temporary(
    source, target, suffix, transaction_id
):
    transaction_id = _validate_transaction_id(transaction_id)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".{}-{}-".format(target.name, transaction_id),
        suffix=suffix,
        dir=os.fspath(target.parent),
    )
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        shutil.copy2(source, temporary)
        _fsync_file(temporary)
        return temporary
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _atomic_replace_targets(
    staged_docs,
    docs_dir,
    report_date,
    expected_original_hashes=None,
    transaction_id=None,
):
    docs_dir = Path(docs_dir).resolve()
    staged_docs = Path(staged_docs).resolve()
    transaction_id = _validate_transaction_id(
        transaction_id or uuid.uuid4().hex
    )
    relative_targets = _relative_public_targets(report_date)
    actual_original_hashes = _public_target_hashes(docs_dir, report_date)
    if expected_original_hashes is None:
        expected_original_hashes = actual_original_hashes
    if actual_original_hashes != expected_original_hashes:
        raise RuntimeError("public artifact changed during staging")
    journal_path = transaction_journal_path(docs_dir)
    if journal_path.exists():
        raise RuntimeError("unfinished publication journal was not recovered")

    prepared = []
    try:
        for relative in relative_targets:
            source = staged_docs / relative
            target = docs_dir / relative
            if not source.is_file():
                raise FileNotFoundError(
                    "staged public artifact is missing: {}".format(relative)
                )
            item = {
                "target": relative,
                "backup": None,
                "next": None,
                "original_sha256": expected_original_hashes[relative],
                "staged_sha256": _sha256_file(source),
            }
            backup = _copy_fsynced_temporary(
                target,
                target,
                ".shadow-backup",
                transaction_id,
            )
            item["backup"] = os.fspath(backup.relative_to(docs_dir))
            prepared.append(item)
            next_path = _copy_fsynced_temporary(
                source,
                target,
                ".shadow-next",
                transaction_id,
            )
            item["next"] = os.fspath(next_path.relative_to(docs_dir))

        for directory in {
            (docs_dir / item["target"]).parent for item in prepared
        }:
            _fsync_directory(directory)

        journal = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "report_date": report_date,
            "status": "prepared",
            "items": prepared,
        }
        _write_transaction_journal(journal_path, journal)
        journal["status"] = "publishing"
        _write_transaction_journal(journal_path, journal)

        for item in prepared:
            next_path = _resolve_journal_artifact(
                docs_dir, item["next"], suffix=".shadow-next"
            )
            target = _resolve_journal_artifact(docs_dir, item["target"])
            os.replace(os.fspath(next_path), os.fspath(target))
            _fsync_file(target)
            _fsync_directory(target.parent)

        journal["status"] = "committed"
        _write_transaction_journal(journal_path, journal)
        _recover_incomplete_transaction(docs_dir)
    except BaseException as original_error:
        recovery_errors = []
        if journal_path.exists():
            try:
                _recover_incomplete_transaction(docs_dir)
            except BaseException as exc:
                recovery_errors.append(exc)
        else:
            recovery_errors.extend(
                _cleanup_transaction_artifacts(prepared, docs_dir)
            )
        if recovery_errors:
            raise AtomicPublishRollbackError(
                original_error, recovery_errors
            ) from original_error
        raise
    return relative_targets


def enable_shadow_evaluation_snapshot(
    *, docs_dir, report_date, started_at
):
    """Enable the first empty OOT shadow snapshot and rebuild public docs."""

    _parse_date(report_date, "report_date")
    _parse_date(started_at, "started_at")
    docs_dir = Path(docs_dir).resolve()
    docs_dir.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_docs_publish_lock(docs_dir):
        _recover_incomplete_transaction(docs_dir)
        _cleanup_stale_publication_artifacts(docs_dir, report_date)
        return _enable_shadow_evaluation_snapshot_locked(
            docs_dir=docs_dir,
            report_date=report_date,
            started_at=started_at,
        )


def _enable_shadow_evaluation_snapshot_locked(
    *, docs_dir, report_date, started_at
):
    daily_path = docs_dir / "data" / "{}.json".format(report_date)
    if not daily_path.is_file():
        raise ValueError("report date mismatch: missing {}".format(report_date))
    initial_target_hashes = _public_target_hashes(docs_dir, report_date)

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

    transaction_id = uuid.uuid4().hex
    stage_root = _create_controlled_stage_root(
        docs_dir, transaction_id
    )
    try:
        staged_docs = stage_root / "docs"
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
            staged_docs,
            docs_dir,
            report_date,
            expected_original_hashes=initial_target_hashes,
            transaction_id=transaction_id,
        )
    finally:
        if stage_root.exists():
            _remove_controlled_stage_root(
                stage_root, docs_dir, assume_owned=True
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
