from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from chanlun.report_generator import _escape_inline_json
from chanlun.recommendation_evidence import (
    correct_published_display_ma_evidence,
)
from scripts.stage_ma_evidence_correction import (
    StageMaEvidenceCorrectionError,
    _recover_published_workspace,
    stage_ma_evidence_correction,
)
from scripts.stage_recommendation_evidence_pages import (
    _insert_or_replace_evidence,
    _parse_top_level_key_span,
    _read_bootstrap_info,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DATE = "2026-09-14"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "chanlun-c8-ma-before"
PROVENANCE_PATH = FIXTURE_ROOT / "provenance.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_provenance(label: str, content: bytes, expected: dict):
    actual_hash = hashlib.sha256(content).hexdigest()
    if len(content) != expected["size"] or actual_hash != expected["sha256"]:
        raise AssertionError(
            "{} fixture provenance mismatch: size={}, sha256={}".format(
                label, len(content), actual_hash
            )
        )


def _frozen_input_bytes():
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    if provenance["report_date"] != REPORT_DATE:
        raise AssertionError("fixture report date mismatch")

    packed = (FIXTURE_ROOT / provenance["fixture"]["file"]).read_bytes()
    _assert_provenance("compressed page", packed, provenance["fixture"])
    home = gzip.decompress(packed)
    _assert_provenance("home page", home, provenance["home"])

    archive = home
    for replacement in provenance["archive"]["replacements"]:
        old = replacement["old"].encode("utf-8")
        new = replacement["new"].encode("utf-8")
        if archive.count(old) != replacement["count"]:
            raise AssertionError(
                "archive fixture replacement count mismatch: {}".format(
                    replacement["old"]
                )
            )
        archive = archive.replace(old, new)
    _assert_provenance("archive page", archive, provenance["archive"])

    daily = (REPO_ROOT / provenance["daily"]["committed_path"]).read_bytes()
    _assert_provenance("daily JSON", daily, provenance["daily"])
    return daily, home, archive


def _materialize_frozen_inputs(root: Path):
    daily, home, archive = _frozen_input_bytes()
    docs = root / "docs"
    (docs / "data").mkdir(parents=True)
    (docs / REPORT_DATE).mkdir(parents=True)
    (docs / "data" / f"{REPORT_DATE}.json").write_bytes(daily)
    (docs / "index.html").write_bytes(home)
    (docs / REPORT_DATE / "index.html").write_bytes(archive)
    return docs


def _bootstrap(path: Path):
    html = path.read_text(encoding="utf-8")
    return _read_bootstrap_info(html, path)["payload"]


def _raw_bootstrap_value(path: Path, key: str) -> str:
    html = path.read_text(encoding="utf-8")
    info = _read_bootstrap_info(html, path)
    raw = html[info["json_start"]:info["json_end"]]
    span = _parse_top_level_key_span(raw, key)
    if span is None:
        raise AssertionError("missing bootstrap key: {}".format(key))
    return raw[span[1]:span[2]]


def _protected_workbench_projection(workbench):
    projected = {}
    for item in workbench["items"]:
        projected[item["id"]] = {
            key: copy.deepcopy(item.get(key))
            for key in (
                "code", "formal_action", "score", "is_executable",
                "sources", "source_refs", "strategy_actions",
                "strategy_contracts", "contracts", "candidate",
            )
        }
        projected[item["id"]]["strategy_results"] = [
            {
                key: copy.deepcopy(result.get(key))
                for key in (
                    "strategy_id", "role", "action_semantics", "view_rank",
                    "formal_action", "contract", "score", "candidate",
                )
            }
            for result in item["strategy_results"]
        ]
    return projected


class StageMaEvidenceCorrectionTests(unittest.TestCase):
    def _stage(self, root, docs, stage_root):
        return stage_ma_evidence_correction(
            repo_root=root,
            docs_dir=docs,
            report_date=REPORT_DATE,
            stage_root=stage_root,
            source_assets_dir=REPO_ROOT / "chanlun" / "report_assets",
        )

    def test_stages_frozen_two_pages_with_only_bounded_derived_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs = _materialize_frozen_inputs(root)
            stage_root = root / "stage"
            daily_path = docs / "data" / f"{REPORT_DATE}.json"
            home_path = docs / "index.html"
            archive_path = docs / REPORT_DATE / "index.html"
            source_hashes = {
                path: _sha256(path)
                for path in (daily_path, home_path, archive_path)
            }
            old_home = _bootstrap(home_path)
            old_archive = _bootstrap(archive_path)
            self.assertEqual(
                old_home["recommendationEvidence"],
                old_archive["recommendationEvidence"],
            )
            self.assertEqual(
                old_home["decisionWorkbench"],
                old_archive["decisionWorkbench"],
            )

            result = self._stage(root, docs, stage_root)

            self.assertEqual(result["status"], "staged")
            self.assertTrue(result["old_projection_replayed"])
            self.assertEqual(result["corrected_source_count"], 20)
            self.assertEqual(result["corrected_entity_count"], 13)
            self.assertEqual(result["staged_files"], [
                "assets/report-v2.css",
                "assets/report-v2.js",
                f"{REPORT_DATE}/index.html",
                "index.html",
            ])
            self.assertEqual(
                source_hashes,
                {path: _sha256(path) for path in source_hashes},
            )

            staged_home_path = stage_root / "index.html"
            staged_archive_path = stage_root / REPORT_DATE / "index.html"
            new_home = _bootstrap(staged_home_path)
            new_archive = _bootstrap(staged_archive_path)
            self.assertEqual(
                new_home["recommendationEvidence"],
                new_archive["recommendationEvidence"],
            )
            self.assertEqual(
                new_home["decisionWorkbench"],
                new_archive["decisionWorkbench"],
            )
            self.assertEqual(
                _raw_bootstrap_value(home_path, "inlineReportData"),
                _raw_bootstrap_value(staged_home_path, "inlineReportData"),
            )
            self.assertEqual(
                _raw_bootstrap_value(archive_path, "inlineReportData"),
                _raw_bootstrap_value(staged_archive_path, "inlineReportData"),
            )

            old_evidence = old_home["recommendationEvidence"]
            new_evidence = new_home["recommendationEvidence"]
            self.assertEqual(
                old_evidence["market_sentiment"],
                new_evidence["market_sentiment"],
            )
            changed = []
            for view, old_rows in old_evidence["views"].items():
                new_rows = new_evidence["views"][view]
                self.assertEqual(len(old_rows), len(new_rows))
                for old, new in zip(old_rows, new_rows):
                    if old == new:
                        continue
                    changed.append((view, old["code"]))
                    self.assertEqual(
                        {
                            key: value for key, value in old.items()
                            if key not in {"summary", "daily_structure", "main_rise_clue"}
                        },
                        {
                            key: value for key, value in new.items()
                            if key not in {"summary", "daily_structure", "main_rise_clue"}
                        },
                    )
                    self.assertEqual(old["sublevel_30m"], new["sublevel_30m"])
                    self.assertEqual(
                        [
                            key for key in set(old["summary"]) | set(new["summary"])
                            if old["summary"].get(key) != new["summary"].get(key)
                        ],
                        ["status"],
                    )
                    self.assertEqual(new["summary"]["status"], "available")
                    self.assertEqual(new["daily_structure"]["audit_reasons"], {})
                    self.assertEqual(new["daily_structure"]["status"], "available")
            self.assertEqual(len(changed), 20)
            self.assertEqual(len({code for _, code in changed}), 13)

            old_workbench = old_home["decisionWorkbench"]
            new_workbench = new_home["decisionWorkbench"]
            self.assertEqual(
                old_workbench["changes"], new_workbench["changes"]
            )
            self.assertEqual(len(new_workbench["items"]), 42)
            self.assertEqual(
                sum(
                    len(item["strategy_results"])
                    for item in new_workbench["items"]
                ),
                56,
            )
            self.assertEqual(
                _protected_workbench_projection(old_workbench),
                _protected_workbench_projection(new_workbench),
            )
            self.assertEqual(
                sum(bool(item["is_executable"]) for item in new_workbench["items"]),
                0,
            )
            star = next(
                item for item in new_workbench["items"]
                if item["code"] == "603344"
            )
            self.assertEqual(star["score"], 62.0)
            self.assertEqual(star["formal_action"], "可上车")
            self.assertEqual(star["page_status"], "formal_incomplete")
            self.assertFalse(star["is_executable"])
            self.assertIsNone(star["reference_price"])
            old_star_evidence = next(
                row for row in old_evidence["views"]["main"]
                if row["code"] == "603344"
            )
            new_star_evidence = next(
                row for row in new_evidence["views"]["main"]
                if row["code"] == "603344"
            )
            self.assertEqual(23.7819, new_star_evidence["daily_structure"]["ma20"])
            self.assertEqual(
                old_star_evidence["price_evidence"],
                new_star_evidence["price_evidence"],
            )
            self.assertEqual(
                old_star_evidence["sublevel_30m"],
                new_star_evidence["sublevel_30m"],
            )
            self.assertEqual(len(new_evidence["views"]["luojie"]), 30)
            self.assertEqual(len(new_evidence["views"]["highlights"]), 10)

            for name in ("report-v2.css", "report-v2.js"):
                self.assertEqual(
                    _sha256(REPO_ROOT / "chanlun" / "report_assets" / name),
                    _sha256(stage_root / "assets" / name),
                )

    @staticmethod
    def _replace_inline(path: Path, daily: dict):
        html = path.read_text(encoding="utf-8")
        info = _read_bootstrap_info(html, path)
        raw = html[info["json_start"]:info["json_end"]]
        span = _parse_top_level_key_span(raw, "inlineReportData")
        updated = raw[:span[1]] + _escape_inline_json(daily) + raw[span[2]:]
        path.write_text(
            html[:info["json_start"]] + updated + html[info["json_end"]:],
            encoding="utf-8",
        )

    @staticmethod
    def _replace_workbench(path: Path, workbench: dict):
        html = path.read_text(encoding="utf-8")
        info = _read_bootstrap_info(html, path)
        raw = html[info["json_start"]:info["json_end"]]
        updated = _insert_or_replace_evidence(
            raw, workbench, "decisionWorkbench"
        )
        path.write_text(
            html[:info["json_start"]] + updated + html[info["json_end"]:],
            encoding="utf-8",
        )

    @staticmethod
    def _replace_recommendation_evidence(path: Path, evidence: dict):
        html = path.read_text(encoding="utf-8")
        info = _read_bootstrap_info(html, path)
        raw = html[info["json_start"]:info["json_end"]]
        updated = _insert_or_replace_evidence(raw, evidence)
        path.write_text(
            html[:info["json_start"]] + updated + html[info["json_end"]:],
            encoding="utf-8",
        )

    def _assert_rejected(self, mutate):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs = _materialize_frozen_inputs(root)
            mutate(docs)
            before = {
                path: path.read_bytes()
                for path in docs.rglob("*")
                if path.is_file()
            }
            stage_root = root / "stage"
            with self.assertRaises(StageMaEvidenceCorrectionError):
                stage_ma_evidence_correction(
                    repo_root=root,
                    docs_dir=docs,
                    report_date=REPORT_DATE,
                    stage_root=stage_root,
                    source_assets_dir=REPO_ROOT / "chanlun" / "report_assets",
                )
            self.assertFalse(stage_root.exists())
            self.assertEqual(
                before,
                {path: path.read_bytes() for path in before},
            )

    def test_rejects_coherent_published_daily_fact_conflicts_with_raw_source(self):
        def mutate_source(docs, field, value):
            for relative in ("index.html", f"{REPORT_DATE}/index.html"):
                path = docs / relative
                payload = _bootstrap(path)
                evidence = copy.deepcopy(payload["recommendationEvidence"])
                source = next(
                    row for row in evidence["views"]["main"]
                    if row["code"] == "603344"
                )
                source["daily_structure"][field] = value

                workbench = copy.deepcopy(payload["decisionWorkbench"])
                item = next(
                    row for row in workbench["items"]
                    if row["code"] == "603344"
                )
                strategy = next(
                    row for row in item["strategy_results"]
                    if row["strategy_id"] == "main"
                )
                strategy["evidence"] = copy.deepcopy(source)
                self._replace_recommendation_evidence(path, evidence)
                self._replace_workbench(path, workbench)

        self._assert_rejected(
            lambda docs: mutate_source(docs, "ma20", 999)
        )

    def test_helper_rejects_affected_daily_as_of_outside_report_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = _materialize_frozen_inputs(Path(tmpdir))
            daily = json.loads(
                (docs / "data" / f"{REPORT_DATE}.json").read_text(
                    encoding="utf-8"
                )
            )
            payload = _bootstrap(docs / "index.html")
            evidence = copy.deepcopy(payload["recommendationEvidence"])
            source = next(
                row for row in evidence["views"]["main"]
                if row["code"] == "603344"
            )
            source["daily_structure"]["as_of"] = "2026-09-13"
            workspace = _recover_published_workspace(
                daily,
                payload["recommendationEvidence"],
                payload["decisionWorkbench"],
            )

            with self.assertRaises(ValueError):
                correct_published_display_ma_evidence(
                    daily, daily, workspace, evidence
                )

    def test_rejects_wrong_source_date_and_missing_evidence(self):
        def wrong_source(docs):
            for relative in ("index.html", f"{REPORT_DATE}/index.html"):
                path = docs / relative
                workbench = copy.deepcopy(_bootstrap(path)["decisionWorkbench"])
                workbench["items"][0]["strategy_results"][0]["candidate"][
                    "ref"
                ]["pool"] = "missing_pool"
                self._replace_workbench(path, workbench)

        self._assert_rejected(wrong_source)

        def wrong_date(docs):
            daily_path = docs / "data" / f"{REPORT_DATE}.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            daily["date"] = "2026-09-13"
            daily_path.write_text(json.dumps(daily, ensure_ascii=False), encoding="utf-8")

        self._assert_rejected(wrong_date)

        def missing_evidence(docs):
            path = docs / "index.html"
            html = path.read_text(encoding="utf-8")
            info = _read_bootstrap_info(html, path)
            raw = html[info["json_start"]:info["json_end"]]
            updated = _insert_or_replace_evidence(raw, None)
            path.write_text(
                html[:info["json_start"]] + updated + html[info["json_end"]:],
                encoding="utf-8",
            )

        self._assert_rejected(missing_evidence)

    def test_rejects_invalid_scalar_and_extra_nested_conflict(self):
        def mutate_candidate(docs, mutation):
            daily_path = docs / "data" / f"{REPORT_DATE}.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            candidate = next(
                row for row in daily["picks_fusion"]
                if str(row["code"]) == "603344"
            )
            mutation(candidate)
            daily_path.write_text(json.dumps(daily, ensure_ascii=False), encoding="utf-8")
            for relative in ("index.html", f"{REPORT_DATE}/index.html"):
                self._replace_inline(docs / relative, daily)

        self._assert_rejected(
            lambda docs: mutate_candidate(
                docs, lambda candidate: candidate.__setitem__("ma5", "bad")
            )
        )
        self._assert_rejected(
            lambda docs: mutate_candidate(
                docs, lambda candidate: candidate.__setitem__("ma", {"ma5": [1]})
            )
        )


if __name__ == "__main__":
    unittest.main()
