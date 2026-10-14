#!/usr/bin/env python3
"""Build an audited, offline correction for one erroneously empty B0 freeze.

This command only writes a new review directory. It never edits the frozen run,
published report, market database, or public sidecar.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Mapping, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chanlun.nextday_research import (
    _archive_candidates,
    _aggregate_registration_status,
    _group_source_hash,
    _hidden_highlights_reason,
    _latest_group_freeze_time,
    _registration_status,
    _run_group,
    _timestamp_value,
    adapt_report,
    evaluate_frozen_selection,
    render_shortlist,
)
from chanlun.report_comparison import _read_archived_workbench as read_archive
from chanlun.report_view_model import build_workspace
from scripts.repair_strategy_scorecard_snapshot import (
    _has_legacy_highlights_upstream_marker,
    _independent_luojie_research_contract,
    _refresh_report_bootstrap,
    _workspace_upstream_contract_violations,
    formal_report_digest,
    protected_report_digest,
)
from scripts.enable_shadow_evaluation_snapshot import _read_bootstrap_envelope


REASON = "upstream_highlights_hidden"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CorrectionError(ValueError):
    """The requested B0 correction is not proven safe by the supplied files."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, name: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CorrectionError("{} is not valid JSON".format(name)) from exc
    if not isinstance(value, dict):
        raise CorrectionError("{} must be an object".format(name))
    return value


def _archive(report: Mapping[str, Any], archive_bytes: bytes, report_date: str) -> dict:
    """Use the production archive identity reader without a live docs write."""
    with tempfile.TemporaryDirectory(prefix="b0-archive-check-") as directory:
        docs = Path(directory) / "docs"
        data = docs / "data"
        archive = docs / report_date / "index.html"
        data.mkdir(parents=True)
        archive.parent.mkdir()
        archive.write_bytes(archive_bytes)
        result = read_archive(str(data), report_date, report)
    if not isinstance(result, dict) or result.get("identity_matches") is not True:
        raise CorrectionError("archive is not bound to the supplied same-day report")
    return result


def _unaffected_facts(report: Mapping[str, Any]) -> dict:
    """Remove only the known highlights-derived fields before exact comparison."""
    value = copy.deepcopy(dict(report))
    shadow = value.get("shadow_evaluations")
    if isinstance(shadow, dict):
        shadow.pop("production_guard", None)
    health = value.get("selection_input_health")
    if isinstance(health, dict) and isinstance(health.get("by_view"), dict):
        health["by_view"].pop("highlights", None)
    workspace = value.get("workspace")
    if isinstance(workspace, dict):
        for field in ("views", "counts", "view_meta"):
            entries = workspace.get(field)
            if isinstance(entries, dict):
                entries.pop("highlights", None)
        diagnostics = workspace.get("diagnostics")
        if isinstance(diagnostics, dict):
            incidents = diagnostics.get("upstream_contract_incidents")
            if isinstance(incidents, list):
                others = [
                    row for row in incidents
                    if not isinstance(row, dict) or row.get("view") != "highlights"
                ]
                if others:
                    diagnostics["upstream_contract_incidents"] = others
                else:
                    diagnostics.pop("upstream_contract_incidents", None)
    return value


def _valid_formal_guard(report: Mapping[str, Any]) -> bool:
    shadow = report.get("shadow_evaluations")
    guard = shadow.get("production_guard") if isinstance(shadow, Mapping) else None
    digest = formal_report_digest(report)
    return bool(
        isinstance(guard, Mapping)
        and guard.get("unchanged") is True
        and guard.get("before_sha256") == digest
        and guard.get("after_sha256") == digest
    )


def _highlight_rows(report: Mapping[str, Any]) -> list:
    workspace = report.get("workspace")
    views = workspace.get("views") if isinstance(workspace, Mapping) else None
    rows = views.get("highlights") if isinstance(views, Mapping) else None
    if not isinstance(rows, list):
        raise CorrectionError("corrected highlights view is missing")
    return rows


def _expected_original_codes(report: Mapping[str, Any]) -> list:
    workspace = report.get("workspace")
    diagnostics = workspace.get("diagnostics") if isinstance(workspace, Mapping) else None
    highlights = diagnostics.get("highlights") if isinstance(diagnostics, Mapping) else None
    overlap = diagnostics.get("growth_quality_overlap") if isinstance(diagnostics, Mapping) else None
    codes = overlap.get("highlights_codes") if isinstance(overlap, Mapping) else None
    count = highlights.get("selected_count") if isinstance(highlights, Mapping) else None
    if (
        not isinstance(codes, list)
        or not codes
        or any(not isinstance(code, str) or not code for code in codes)
        or len(codes) != len(set(codes))
        or type(count) is not int
        or count != len(codes)
    ):
        raise CorrectionError("original highlights member/order evidence is unavailable")
    return codes


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def build_corrected_b0(
    *,
    old_report_path: Path,
    old_archive_path: Path,
    corrected_report_path: Path,
    corrected_archive_path: Path,
    selection_path: Path,
    outcomes_path: Path,
    db_path: Path,
    output_dir: Path,
    expected_selection_sha256: str,
    expected_outcomes_sha256: str,
    corrected_at: Optional[str] = None,
    outcome_evaluator: Any = None,
    report_date: Optional[str] = None,
    docs_dir: Optional[Path] = None,
) -> dict:
    """Produce reviewable corrected files with exact-input CAS; never apply them."""
    if not SHA256.fullmatch(expected_selection_sha256) or not SHA256.fullmatch(expected_outcomes_sha256):
        raise CorrectionError("expected SHA256 values are required")
    paths = {
        "old-report.json": Path(old_report_path),
        "old-archive.html": Path(old_archive_path),
        "new-report.json": Path(corrected_report_path),
        "new-archive.html": Path(corrected_archive_path),
        "selection.json": Path(selection_path),
        "outcomes.json": Path(outcomes_path),
    }
    original_bytes = {}
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise CorrectionError("{} is unavailable".format(name))
        original_bytes[name] = path.read_bytes()
    if _sha(original_bytes["selection.json"]) != expected_selection_sha256:
        raise CorrectionError("selection CAS does not match")
    if _sha(original_bytes["outcomes.json"]) != expected_outcomes_sha256:
        raise CorrectionError("outcomes CAS does not match")

    old_report = _json(original_bytes["old-report.json"], "old report")
    new_report = _json(original_bytes["new-report.json"], "corrected report")
    old_selection = _json(original_bytes["selection.json"], "selection")
    old_outcomes = _json(original_bytes["outcomes.json"], "outcomes")
    day = report_date or old_report.get("date")
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise CorrectionError("report date is invalid")
    if any(source.get(key) != day for source, key in (
        (old_report, "date"), (new_report, "date"),
        (old_selection, "report_date"), (old_outcomes, "report_date"),
    )):
        raise CorrectionError("report dates do not match")
    if not _valid_formal_guard(old_report) or not _valid_formal_guard(new_report):
        raise CorrectionError("formal report guard does not match its own source")
    if protected_report_digest(old_report) != protected_report_digest(new_report):
        raise CorrectionError("protected report facts changed")
    if _unaffected_facts(old_report) != _unaffected_facts(new_report):
        raise CorrectionError("corrected report changes facts outside highlights")
    if not _hidden_highlights_reason(old_report) or _hidden_highlights_reason(new_report):
        raise CorrectionError("old hidden and corrected available states are unproven")
    if _highlight_rows(old_report) != []:
        raise CorrectionError("old report was not a hidden empty highlights view")
    original_contract = _independent_luojie_research_contract(old_report)
    if not _has_legacy_highlights_upstream_marker(
        old_report, day, build_workspace(old_report), original_contract
    ):
        raise CorrectionError("original report lacks the exact legacy highlights closure receipt")
    expected_codes = _expected_original_codes(old_report)
    new_rows = _highlight_rows(new_report)
    if new_rows != build_workspace(new_report)["views"]["highlights"]:
        raise CorrectionError("corrected highlights differ from source-derived rows")
    if "highlights" in _workspace_upstream_contract_violations(new_report):
        raise CorrectionError("corrected highlights still violate their source contract")
    if (
        [row.get("code") for row in new_rows if isinstance(row, Mapping)] != expected_codes
        or len(new_rows) != len(expected_codes)
        or [row.get("view_rank") for row in new_rows] != list(range(1, len(new_rows) + 1))
    ):
        raise CorrectionError("corrected highlights do not match original membership/order evidence")
    old_archive = _archive(old_report, original_bytes["old-archive.html"], day)
    new_archive = _archive(new_report, original_bytes["new-archive.html"], day)
    try:
        old_envelope = _read_bootstrap_envelope(paths["old-archive.html"])
        new_envelope = _read_bootstrap_envelope(paths["new-archive.html"])
        expected_envelope = _refresh_report_bootstrap(
            old_envelope, new_report,
            Path(docs_dir) if docs_dir is not None else ROOT_DIR / "docs", day,
        )
    except Exception as exc:
        raise CorrectionError("archive evidence cannot be replayed from its source") from exc
    if new_envelope != expected_envelope:
        raise CorrectionError("corrected archive differs from source-replayed workbench or evidence")
    old_archive_status, _, old_archive_rows, _ = _archive_candidates(day, old_archive)
    new_archive_status, _, new_archive_rows, new_archive_errors = _archive_candidates(day, new_archive)
    if old_archive_status != "evaluated" or old_archive_rows:
        raise CorrectionError("original archive was not evaluated empty")
    if new_archive_status != "evaluated" or new_archive_errors:
        raise CorrectionError("corrected archive is invalid")
    archive_pairs = sorted(
        ((rank, row["identity_details"]["code"]) for row, rank in new_archive_rows),
        key=lambda item: item[0],
    )
    if archive_pairs != list(enumerate(expected_codes, 1)):
        raise CorrectionError("corrected archive does not match highlights order")

    old_source_hashes = old_selection.get("source_hashes")
    if not isinstance(old_source_hashes, Mapping) or old_source_hashes.get("report_sha256") != _sha(original_bytes["old-report.json"]) or old_source_hashes.get("archive_sha256") != _sha(original_bytes["old-archive.html"]):
        raise CorrectionError("old freeze is not bound to original report and archive")
    old_b0 = old_selection.get("b0")
    old_groups = old_selection.get("group_freezes")
    old_b0_freeze = old_groups.get("b0") if isinstance(old_groups, Mapping) else None
    if (
        not isinstance(old_b0, Mapping) or old_b0.get("status") != "evaluated"
        or old_b0.get("selected") != [] or "correction" in old_b0
        or not isinstance(old_b0_freeze, Mapping) or old_b0_freeze.get("status") != "evaluated"
        or not isinstance(old_selection.get("l1"), Mapping)
        or not isinstance(old_groups.get("l1"), Mapping)
    ):
        raise CorrectionError("selection is not the original evaluated-empty freeze")
    old_outcome_b0 = old_outcomes.get("b0")
    as_of_date = old_outcomes.get("as_of_date")
    if (
        not isinstance(old_outcome_b0, Mapping)
        or old_outcome_b0.get("status") != "evaluated_empty"
        or old_outcome_b0.get("selected") != []
        or not isinstance(as_of_date, str) or as_of_date < day
    ):
        raise CorrectionError("original B0 outcome is not evaluated empty")
    corrected_at = corrected_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    correction_time = _timestamp_value(corrected_at)
    original_time = _timestamp_value(old_b0_freeze.get("frozen_at"))
    if correction_time is None or original_time is None or correction_time < original_time:
        raise CorrectionError("correction time is invalid or precedes original freeze")

    prepared = adapt_report(new_report, archived_workbench=new_archive)
    b0 = prepared.get("b0") or {}
    if b0.get("status") != "evaluated" or not b0.get("selected"):
        raise CorrectionError("corrected B0 is not an evaluated non-empty selection")
    if [row["code"] for row in b0["selected"]] != expected_codes[:5]:
        raise CorrectionError("corrected B0 changed original Top5 order")

    corrected = copy.deepcopy(old_selection)
    corrected["b0"] = copy.deepcopy(b0)
    new_report_sha = _sha(original_bytes["new-report.json"])
    new_archive_sha = _sha(original_bytes["new-archive.html"])
    new_group_hash = _group_source_hash("b0", prepared, new_report_sha)
    corrected["b0"]["correction"] = {
        "reason": REASON,
        "corrected_at": corrected_at,
        "original_selection_sha256": expected_selection_sha256,
        "original_outcomes_sha256": expected_outcomes_sha256,
        "corrected_report_sha256": new_report_sha,
        "corrected_archive_sha256": new_archive_sha,
    }
    new_freeze = copy.deepcopy(old_b0_freeze)
    new_freeze.update(
        source_hash=new_group_hash,
        report_identity=new_report_sha,
        attempted_at=corrected_at,
        frozen_at=corrected_at,
        registration_status=_registration_status(day, corrected_at),
        supersedes={
            "source_hash": old_b0_freeze.get("source_hash"),
            "report_identity": old_b0_freeze.get("report_identity"),
            "frozen_at": old_b0_freeze.get("frozen_at"),
        },
    )
    corrected["group_freezes"]["b0"] = new_freeze
    corrected["frozen_at"] = _latest_group_freeze_time(corrected["group_freezes"], corrected_at)
    corrected["registration_status"] = _aggregate_registration_status(corrected["group_freezes"], day, corrected_at)
    if isinstance(corrected.get("summary"), dict):
        corrected["summary"]["archive_highlights_count"] = len(new_archive_rows)
    new_outcomes = copy.deepcopy(old_outcomes)
    evaluator = outcome_evaluator or evaluate_frozen_selection
    new_outcomes["b0"] = _run_group(day, "b0", corrected, Path(db_path), as_of_date, evaluator)
    if corrected["l1"] != old_selection["l1"] or corrected["group_freezes"]["l1"] != old_groups["l1"] or new_outcomes["l1"] != old_outcomes["l1"]:
        raise CorrectionError("L1 changed during B0 correction")
    if not isinstance(new_outcomes["b0"], Mapping) or new_outcomes["b0"].get("status") not in {"evaluated", "research_only"}:
        raise CorrectionError("corrected B0 outcomes are unavailable")

    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise CorrectionError("review output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".b0-correction-", dir=str(output_dir.parent)))
    try:
        original_dir = temporary / "original"
        corrected_dir = temporary / "corrected"
        original_dir.mkdir()
        corrected_dir.mkdir()
        for name, content in original_bytes.items():
            (original_dir / name).write_bytes(content)
        _write_json(corrected_dir / "selection.json", corrected)
        _write_json(corrected_dir / "outcomes.json", new_outcomes)
        (corrected_dir / "shortlist.md").write_text(render_shortlist(corrected, new_outcomes), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "report_date": day,
            "reason": REASON,
            "corrected_at": corrected_at,
            "original_sha256": {name: _sha(content) for name, content in original_bytes.items()},
            "corrected_sha256": {
                name: _sha((corrected_dir / name).read_bytes())
                for name in ("selection.json", "outcomes.json", "shortlist.md")
            },
            "original_highlights_codes": expected_codes,
            "corrected_b0_codes": [row["code"] for row in b0["selected"]],
            "l1_selection_unchanged": True,
            "l1_freeze_unchanged": True,
            "l1_outcomes_unchanged": True,
            "applied_to_run": False,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(str(temporary), str(output_dir))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("old-report", "old-archive", "corrected-report", "corrected-archive", "selection", "outcomes", "db", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--docs-dir", type=Path, required=True)
    parser.add_argument("--expected-selection-sha256", required=True)
    parser.add_argument("--expected-outcomes-sha256", required=True)
    arguments = parser.parse_args()
    result = build_corrected_b0(
        old_report_path=arguments.old_report,
        old_archive_path=arguments.old_archive,
        corrected_report_path=arguments.corrected_report,
        corrected_archive_path=arguments.corrected_archive,
        selection_path=arguments.selection,
        outcomes_path=arguments.outcomes,
        db_path=arguments.db,
        output_dir=arguments.output_dir,
        expected_selection_sha256=arguments.expected_selection_sha256,
        expected_outcomes_sha256=arguments.expected_outcomes_sha256,
        report_date=arguments.report_date,
        docs_dir=arguments.docs_dir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
