#!/usr/bin/env python3
"""Stage the bounded 2026-09-14 MA evidence correction for two pages.

The official JSON and both source HTML files are read-only.  The command
recovers the already-published source workspace from ``decisionWorkbench``,
proves that it replays the old workbench, applies only the display-sequence
MA correction, and atomically writes an independent staging directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.decision_workbench import build_decision_workbench  # noqa: E402
from chanlun.recommendation_evidence import (  # noqa: E402
    correct_published_display_ma_evidence,
)
from chanlun.report_generator import replace_report_asset_versions  # noqa: E402
from scripts.stage_recommendation_evidence_pages import (  # noqa: E402
    REPORT_ASSETS,
    StageRecommendationEvidenceError,
    _asset_version,
    _assert_asset_queries,
    _assert_html_allowlist_equivalent,
    _assert_snapshot_unchanged,
    _copy_asset,
    _insert_or_replace_evidence,
    _parse_top_level_key_span,
    _read_bootstrap_info,
    _snapshot_inputs,
    _write_bytes,
)


SUPPORTED_REPORT_DATE = "2026-09-14"
EXPECTED_ENTITY_COUNT = 42
EXPECTED_SOURCE_COUNT = 56
EXPECTED_CORRECTED_SOURCE_COUNT = 20
EXPECTED_CORRECTED_ENTITY_COUNT = 13
EXPECTED_LUOJIE_COUNT = 30
EXPECTED_HIGHLIGHTS_COUNT = 10


class StageMaEvidenceCorrectionError(ValueError):
    """Raised when the bounded page migration cannot be proven safe."""


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StageMaEvidenceCorrectionError(
            "cannot read UTF-8 input: {}".format(path)
        ) from exc


def _read_json(path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageMaEvidenceCorrectionError(
            "cannot read JSON input: {}".format(path)
        ) from exc


def _inside(parent, child):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _raw_top_level_value(html, info, key):
    raw = html[info["json_start"]:info["json_end"]]
    span = _parse_top_level_key_span(raw, key)
    if span is None:
        raise StageMaEvidenceCorrectionError(
            "bootstrap key is missing: {}".format(key)
        )
    return raw[span[1]:span[2]]


def _recover_published_workspace(daily, evidence, workbench):
    if not isinstance(daily.get("workspace"), dict):
        raise StageMaEvidenceCorrectionError("published workspace is missing")
    if not isinstance(evidence, dict) or not isinstance(
        evidence.get("views"), dict
    ):
        raise StageMaEvidenceCorrectionError("published evidence is missing")
    if not isinstance(workbench, dict) or not isinstance(
        workbench.get("items"), list
    ):
        raise StageMaEvidenceCorrectionError("published workbench is missing")
    if not (
        evidence.get("schema_version") == 1
        and evidence.get("report_date") == SUPPORTED_REPORT_DATE
        and workbench.get("report_date") == SUPPORTED_REPORT_DATE
    ):
        raise StageMaEvidenceCorrectionError("published projection date mismatch")

    view_order = list(evidence["views"])
    recovered = {view: [] for view in view_order}
    evidence_by_identity = {}
    for view, rows in evidence["views"].items():
        if not isinstance(rows, list):
            raise StageMaEvidenceCorrectionError("published evidence view is invalid")
        for row in rows:
            if not isinstance(row, dict):
                raise StageMaEvidenceCorrectionError("published evidence row is invalid")
            summary = row.get("summary")
            summary = summary if isinstance(summary, dict) else {}
            identity = (
                view,
                str(row.get("code") or ""),
                summary.get("view_rank"),
            )
            if (
                not identity[1]
                or not isinstance(identity[2], int)
                or isinstance(identity[2], bool)
                or identity in evidence_by_identity
            ):
                raise StageMaEvidenceCorrectionError(
                    "published evidence identity is invalid"
                )
            evidence_by_identity[identity] = row

    seen_items = set()
    seen_sources = set()
    for item in workbench["items"]:
        if not isinstance(item, dict) or not item.get("id"):
            raise StageMaEvidenceCorrectionError("published workbench item is invalid")
        if item["id"] in seen_items:
            raise StageMaEvidenceCorrectionError("duplicate workbench item")
        seen_items.add(item["id"])
        results = item.get("strategy_results")
        if not isinstance(results, list):
            raise StageMaEvidenceCorrectionError(
                "published strategy results are missing"
            )
        for result in results:
            if not isinstance(result, dict):
                raise StageMaEvidenceCorrectionError(
                    "published strategy result is invalid"
                )
            view = str(result.get("strategy_id") or "")
            candidate = result.get("candidate")
            if view not in recovered or not isinstance(candidate, dict):
                raise StageMaEvidenceCorrectionError(
                    "published strategy source identity is invalid"
                )
            code = str(candidate.get("code") or "")
            rank = candidate.get("view_rank")
            identity = (view, code, rank)
            ref = candidate.get("ref")
            ref = ref if isinstance(ref, dict) else {}
            if not (
                code == str(item.get("code") or "")
                and isinstance(rank, int)
                and not isinstance(rank, bool)
                and rank == result.get("view_rank")
                and str(ref.get("code") or "") == code
                and str(ref.get("pool") or "")
                and identity in evidence_by_identity
                and result.get("evidence") == evidence_by_identity[identity]
                and identity not in seen_sources
            ):
                raise StageMaEvidenceCorrectionError(
                    "published strategy source cannot be replayed"
                )
            seen_sources.add(identity)
            recovered[view].append(copy.deepcopy(candidate))
    if seen_sources != set(evidence_by_identity):
        raise StageMaEvidenceCorrectionError(
            "published evidence and strategy source sets differ"
        )
    for view, rows in recovered.items():
        rows.sort(key=lambda row: row["view_rank"])
        if [row["view_rank"] for row in rows] != list(
            range(1, len(rows) + 1)
        ):
            raise StageMaEvidenceCorrectionError(
                "published source ranks are not contiguous: {}".format(view)
            )

    workspace = copy.deepcopy(daily["workspace"])
    workspace["view_order"] = view_order
    workspace["views"] = recovered
    workspace["counts"] = {
        view: len(rows) for view, rows in recovered.items()
    }
    return workspace


def _without_changes(value):
    return {
        key: item for key, item in value.items() if key != "changes"
    }


def _build_and_verify_old_replay(daily, workspace, evidence, workbench):
    phase = str(workbench.get("phase") or "")
    snapshot_id = str(workbench.get("snapshot_id") or "")
    if (
        not phase
        or not snapshot_id
        or not isinstance(workbench.get("changes"), dict)
    ):
        raise StageMaEvidenceCorrectionError(
            "published workbench identity is incomplete"
        )
    replayed = build_decision_workbench(
        daily,
        workspace,
        evidence,
        phase=phase,
        snapshot_id=snapshot_id,
    )
    if _without_changes(replayed) != _without_changes(workbench):
        raise StageMaEvidenceCorrectionError(
            "old evidence does not replay the old workbench"
        )
    return phase, snapshot_id


def _selection_projection(workbench):
    projection = {}
    for item in workbench.get("items") or []:
        if not isinstance(item, dict) or not item.get("id"):
            raise StageMaEvidenceCorrectionError("workbench item is invalid")
        item_id = item["id"]
        if item_id in projection:
            raise StageMaEvidenceCorrectionError("duplicate workbench item")
        projection[item_id] = {
            key: copy.deepcopy(item.get(key))
            for key in (
                "code", "formal_action", "score", "is_executable",
                "sources", "source_refs", "strategy_actions",
                "strategy_contracts", "contracts", "candidate",
            )
        }
        projection[item_id]["strategy_results"] = [
            {
                key: copy.deepcopy(result.get(key))
                for key in (
                    "strategy_id", "role", "action_semantics", "view_rank",
                    "formal_action", "contract", "score", "candidate",
                )
            }
            for result in item.get("strategy_results") or []
            if isinstance(result, dict)
        ]
    return projection


def _validate_current_result(old_workbench, workbench, evidence, diagnostics):
    items = workbench.get("items")
    if not isinstance(items, list) or len(items) != EXPECTED_ENTITY_COUNT:
        raise StageMaEvidenceCorrectionError("unexpected entity count")
    source_count = sum(
        len(item.get("strategy_results") or [])
        for item in items if isinstance(item, dict)
    )
    if source_count != EXPECTED_SOURCE_COUNT:
        raise StageMaEvidenceCorrectionError("unexpected source count")
    if _selection_projection(old_workbench) != _selection_projection(workbench):
        raise StageMaEvidenceCorrectionError(
            "formal score/action/source projection changed"
        )
    old_items = {
        item.get("id"): item for item in old_workbench.get("items") or []
        if isinstance(item, dict)
    }
    for item in items:
        old = old_items.get(item.get("id"), {})
        if old.get("formal_action") and old.get("action") != item.get("action"):
            raise StageMaEvidenceCorrectionError("formal action changed")
    if any(item.get("is_executable") is True for item in items):
        raise StageMaEvidenceCorrectionError("new executable item was produced")
    if diagnostics.get("corrected_source_count") != EXPECTED_CORRECTED_SOURCE_COUNT:
        raise StageMaEvidenceCorrectionError("unexpected corrected source count")
    if diagnostics.get("corrected_entity_count") != EXPECTED_CORRECTED_ENTITY_COUNT:
        raise StageMaEvidenceCorrectionError("unexpected corrected entity count")
    views = evidence.get("views")
    if not (
        isinstance(views, dict)
        and len(views.get("luojie") or []) == EXPECTED_LUOJIE_COUNT
        and len(views.get("highlights") or []) == EXPECTED_HIGHLIGHTS_COUNT
    ):
        raise StageMaEvidenceCorrectionError(
            "published LuoJie/highlights sources were lost"
        )
    star = next(
        (item for item in items if str(item.get("code") or "") == "603344"),
        None,
    )
    if not isinstance(star, dict) or not (
        star.get("score") == 62.0
        and star.get("formal_action") == "可上车"
        and star.get("page_status") == "formal_incomplete"
        and star.get("is_executable") is False
        and star.get("reference_price") is None
    ):
        raise StageMaEvidenceCorrectionError(
            "StarPower score/action/price guard changed"
        )


def _updated_page(html, info, path, evidence, workbench, asset_version):
    original_inline = _raw_top_level_value(
        html, info, "inlineReportData"
    )
    raw = html[info["json_start"]:info["json_end"]]
    updated_raw = _insert_or_replace_evidence(
        raw, evidence, "recommendationEvidence"
    )
    updated_raw = _insert_or_replace_evidence(
        updated_raw, workbench, "decisionWorkbench"
    )
    updated = (
        html[:info["json_start"]]
        + updated_raw
        + html[info["json_end"]:]
    )
    updated = replace_report_asset_versions(updated, asset_version)
    updated_info = _read_bootstrap_info(updated, path)
    if _raw_top_level_value(
        updated, updated_info, "inlineReportData"
    ) != original_inline:
        raise StageMaEvidenceCorrectionError("inlineReportData bytes changed")
    if not (
        updated_info["payload"].get("recommendationEvidence") == evidence
        and updated_info["payload"].get("decisionWorkbench") == workbench
    ):
        raise StageMaEvidenceCorrectionError("staged projection mismatch")
    _assert_html_allowlist_equivalent(
        html, updated, path, bootstrap=True
    )
    _assert_asset_queries(updated, asset_version, path)
    return updated


def stage_ma_evidence_correction(
    *,
    repo_root,
    docs_dir,
    report_date,
    stage_root,
    source_assets_dir=None,
):
    """Create an atomic, independent staging tree for the bounded fix."""
    try:
        repo_root = Path(repo_root).resolve()
        docs_dir = Path(docs_dir)
        if not docs_dir.is_absolute():
            docs_dir = repo_root / docs_dir
        docs_dir = docs_dir.resolve()
        if not _inside(repo_root, docs_dir) or not docs_dir.is_dir():
            raise StageMaEvidenceCorrectionError(
                "docs_dir must be an existing directory inside repo_root"
            )
        if str(report_date) != SUPPORTED_REPORT_DATE:
            raise StageMaEvidenceCorrectionError(
                "only {} is supported".format(SUPPORTED_REPORT_DATE)
            )
        if stage_root is None:
            raise StageMaEvidenceCorrectionError("stage_root is required")
        stage_root = Path(stage_root)
        if not stage_root.is_absolute():
            stage_root = repo_root / stage_root
        stage_root = stage_root.resolve()
        if _inside(docs_dir, stage_root):
            raise StageMaEvidenceCorrectionError(
                "stage_root must be outside docs_dir"
            )
        if stage_root.exists():
            raise StageMaEvidenceCorrectionError("stage_root already exists")
        source_assets_dir = (
            Path(source_assets_dir).resolve()
            if source_assets_dir is not None
            else (repo_root / "chanlun" / "report_assets").resolve()
        )

        daily_path = docs_dir / "data" / (SUPPORTED_REPORT_DATE + ".json")
        home_path = docs_dir / "index.html"
        archive_path = docs_dir / SUPPORTED_REPORT_DATE / "index.html"
        required = [daily_path, home_path, archive_path]
        required.extend(source_assets_dir / name for name in REPORT_ASSETS)
        if any(not path.is_file() for path in required):
            raise StageMaEvidenceCorrectionError("required input is missing")
        snapshot = _snapshot_inputs(required)

        daily = _read_json(daily_path)
        quality = daily.get("data_quality") if isinstance(daily, dict) else {}
        quality = quality if isinstance(quality, dict) else {}
        if not (
            isinstance(daily, dict)
            and daily.get("date") == SUPPORTED_REPORT_DATE
            and quality.get("report_date") == SUPPORTED_REPORT_DATE
            and quality.get("bar_state") == "closed"
            and quality.get("is_official") is True
        ):
            raise StageMaEvidenceCorrectionError(
                "official closed daily snapshot mismatch"
            )
        home_html = _read_text(home_path)
        archive_html = _read_text(archive_path)
        home_info = _read_bootstrap_info(home_html, home_path)
        archive_info = _read_bootstrap_info(archive_html, archive_path)
        for info in (home_info, archive_info):
            payload = info["payload"]
            if not (
                payload.get("pageDate") == SUPPORTED_REPORT_DATE
                and payload.get("inlineReportData") == daily
                and isinstance(payload.get("recommendationEvidence"), dict)
                and isinstance(payload.get("decisionWorkbench"), dict)
            ):
                raise StageMaEvidenceCorrectionError(
                    "page bootstrap does not match the official snapshot"
                )
        for key in ("recommendationEvidence", "decisionWorkbench"):
            if home_info["payload"][key] != archive_info["payload"][key]:
                raise StageMaEvidenceCorrectionError(
                    "home/archive published projections diverged"
                )

        evidence = home_info["payload"]["recommendationEvidence"]
        old_workbench = home_info["payload"]["decisionWorkbench"]
        workspace = _recover_published_workspace(
            daily, evidence, old_workbench
        )
        phase, snapshot_id = _build_and_verify_old_replay(
            daily, workspace, evidence, old_workbench
        )
        corrected_evidence, diagnostics = (
            correct_published_display_ma_evidence(
                daily,
                daily,
                workspace,
                evidence,
            )
        )
        corrected_workbench = build_decision_workbench(
            daily,
            workspace,
            corrected_evidence,
            phase=phase,
            snapshot_id=snapshot_id,
        )
        corrected_workbench["changes"] = copy.deepcopy(
            old_workbench.get("changes")
        )
        _validate_current_result(
            old_workbench,
            corrected_workbench,
            corrected_evidence,
            diagnostics,
        )
        try:
            json.dumps(corrected_evidence, ensure_ascii=False, allow_nan=False)
            json.dumps(corrected_workbench, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise StageMaEvidenceCorrectionError(
                "corrected projections are not strict JSON"
            ) from exc

        asset_version = _asset_version(source_assets_dir)
        updated_home = _updated_page(
            home_html,
            home_info,
            home_path,
            corrected_evidence,
            corrected_workbench,
            asset_version,
        )
        updated_archive = _updated_page(
            archive_html,
            archive_info,
            archive_path,
            corrected_evidence,
            corrected_workbench,
            asset_version,
        )
        _assert_snapshot_unchanged(snapshot)

        stage_root.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(
            prefix=".ma-evidence-correction-",
            dir=os.fspath(stage_root.parent),
        ))
        handed_off = False
        try:
            _write_bytes(temporary / "index.html", updated_home.encode("utf-8"))
            _write_bytes(
                temporary / SUPPORTED_REPORT_DATE / "index.html",
                updated_archive.encode("utf-8"),
            )
            for name in REPORT_ASSETS:
                _copy_asset(
                    source_assets_dir / name,
                    temporary / "assets" / name,
                )
            _assert_snapshot_unchanged(snapshot)
            if _asset_version(source_assets_dir) != asset_version:
                raise StageMaEvidenceCorrectionError(
                    "source asset changed during staging"
                )
            os.replace(os.fspath(temporary), os.fspath(stage_root))
            handed_off = True
            _assert_asset_queries(
                _read_text(stage_root / "index.html"),
                asset_version,
                stage_root / "index.html",
            )
            _assert_asset_queries(
                _read_text(stage_root / SUPPORTED_REPORT_DATE / "index.html"),
                asset_version,
                stage_root / SUPPORTED_REPORT_DATE / "index.html",
            )
        except Exception:
            target = stage_root if handed_off else temporary
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise

        return {
            "status": "staged",
            "report_date": SUPPORTED_REPORT_DATE,
            "stage_dir": os.fspath(stage_root),
            "asset_version": asset_version,
            "staged_files": [
                "assets/report-v2.css",
                "assets/report-v2.js",
                SUPPORTED_REPORT_DATE + "/index.html",
                "index.html",
            ],
            "old_projection_replayed": True,
            "entity_count": EXPECTED_ENTITY_COUNT,
            "source_count": EXPECTED_SOURCE_COUNT,
            "corrected_source_count": diagnostics[
                "corrected_source_count"
            ],
            "corrected_entity_count": diagnostics[
                "corrected_entity_count"
            ],
            "corrected_sources": diagnostics["corrected_sources"],
        }
    except StageMaEvidenceCorrectionError:
        raise
    except StageRecommendationEvidenceError as exc:
        raise StageMaEvidenceCorrectionError(str(exc)) from exc
    except ValueError as exc:
        raise StageMaEvidenceCorrectionError(str(exc)) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--stage-root", required=True)
    parser.add_argument("--source-assets-dir")
    args = parser.parse_args(argv)
    result = stage_ma_evidence_correction(
        repo_root=args.repo_root,
        docs_dir=args.docs_dir,
        report_date=args.report_date,
        stage_root=args.stage_root,
        source_assets_dir=args.source_assets_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
