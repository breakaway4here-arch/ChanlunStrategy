"""The mixed highlights view may carry verified independent research rows."""

import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chanlun.report_view_model import build_workspace
from scripts import repair_strategy_scorecard_snapshot as repair
from scripts.repair_strategy_scorecard_snapshot import (
    _workspace_upstream_contract_violations,
    protected_report_digest,
    rebuild_strategy_scorecard_report,
)


ROOT = Path(__file__).resolve().parents[1]


class FinalizerHighlightsSourcesTests(unittest.TestCase):
    @staticmethod
    def _legacy_fixture():
        """Freeze the original report and HTML-only evidence before correction."""
        path = ROOT / "tests/fixtures/b0_legacy_2026-10-14.json.gz"
        value = json.loads(gzip.decompress(path.read_bytes()))
        envelope = value["bootstrap_without_inline_report"]
        envelope["inlineReportData"] = copy.deepcopy(value["report"])
        return value["report"], envelope

    @classmethod
    def _today(cls):
        return cls._legacy_fixture()[0]

    @staticmethod
    def _scorecards():
        return {
            "schema_version": 2,
            "thresholds": {},
            "formal": [],
            "baselines": [],
            "research": [],
            "gates": [],
            "classification_failures": [],
        }

    def test_today_verified_luojie_rows_keep_original_highlights_order(self):
        report = self._today()
        report["workspace"] = build_workspace(report)
        expected = [
            "002404", "600570", "688111", "601858", "603992",
            "000573", "600252", "603656", "000601",
        ]
        self.assertEqual(expected, [row["code"] for row in report["workspace"]["views"]["highlights"]])

        violations = _workspace_upstream_contract_violations(report)

        self.assertNotIn("highlights", violations)

    def test_only_exact_source_bound_research_row_is_exempt(self):
        original = self._today()
        original["workspace"] = build_workspace(original)
        source_row = next(row for row in original["workspace"]["views"]["highlights"]
                          if row["code"] == "600570")

        changes = {
            "wrong_ref": lambda row: row["ref"].update(pool="picks_fusion"),
            "wrong_ref_code": lambda row: row["ref"].update(code="688111"),
            "wrong_sources": lambda row: row.update(sources=["main", "luojie"]),
            "wrong_code": lambda row: row.update(code="600571"),
            "formal_flag": lambda row: row.update(is_formal_recommendation=True),
            "formal_action": lambda row: row.update(action_semantics="formal"),
            "wrong_view": lambda row: row.update(view="main"),
            "wrong_identity": lambda row: row.update(identity={"asset_type": "index", "exchange": "SH", "code": "600570"}),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                report = copy.deepcopy(original)
                row = next(item for item in report["workspace"]["views"]["highlights"]
                           if item["code"] == "600570")
                change(row)
                self.assertIn(row["code"], _workspace_upstream_contract_violations(report).get("highlights", []))

        self.assertEqual("watch_only", source_row["action_semantics"])

    def test_unverified_source_and_formal_siblings_still_block(self):
        report = self._today()
        report["workspace"] = build_workspace(report)
        report["workspace"]["views"]["main"] = [{"code": "600570"}]
        report["workspace"]["views"]["h4_t3"] = [{"code": "688111"}]
        violations = _workspace_upstream_contract_violations(report)
        self.assertEqual(["600570"], violations["main"])
        self.assertEqual(["688111"], violations["h4_t3"])

        report["luojie_pool"]["diagnostics"].pop("final_common_upstream")
        self.assertEqual(["600570", "688111"],
                         _workspace_upstream_contract_violations(report)["highlights"])

    def test_rebuild_removes_only_matching_old_highlights_closure(self):
        report = self._today()
        report["selection_input_health"]["by_view"]["unrelated_research"] = {
            "status": "unavailable", "reason": "independent_failure",
        }
        old = copy.deepcopy(report)
        old_digest = protected_report_digest(report)
        other_markers = {key: copy.deepcopy(value)
                         for key, value in report["selection_input_health"]["by_view"].items()
                         if key != "highlights"}

        rebuilt, diagnostics = rebuild_strategy_scorecard_report(
            report,
            report_date=report["date"],
            scorecards=self._scorecards(),
            review_diagnostics={"status": "ok"},
        )

        self.assertEqual(old, report)
        self.assertEqual(old_digest, protected_report_digest(rebuilt))
        self.assertEqual(other_markers, rebuilt["selection_input_health"]["by_view"])
        self.assertEqual(["002404", "600570", "688111", "601858", "603992",
                          "000573", "600252", "603656", "000601"],
                         [row["code"] for row in rebuilt["workspace"]["views"]["highlights"]])
        self.assertNotIn("highlights", diagnostics["upstream_contract_blocked_views"])
        self.assertFalse(any(row.get("view") == "highlights" for row in
                             rebuilt["workspace"]["diagnostics"].get("upstream_contract_incidents", [])))

    def test_unrelated_or_tampered_highlights_closure_is_not_removed(self):
        report = self._today()
        report["selection_input_health"]["by_view"]["highlights"]["invalid_codes"] = ["600570"]
        with self.assertRaisesRegex(RuntimeError, "workspace membership or ordering changed"):
            rebuild_strategy_scorecard_report(
                report,
                report_date=report["date"],
                scorecards=self._scorecards(),
                review_diagnostics={"status": "ok"},
            )

    def test_same_generation_bootstrap_restores_only_highlights_evidence(self):
        report = self._today()
        rebuilt, _ = rebuild_strategy_scorecard_report(
            report, report_date=report["date"], scorecards=self._scorecards(),
            review_diagnostics={"status": "ok"},
        )
        _, envelope = self._legacy_fixture()
        self.assertTrue(repair._same_report_generation(envelope, rebuilt, report["date"]))
        old_evidence = envelope["recommendationEvidence"]
        with patch.object(repair, "_load_psy12_shadow_history", return_value=[]), patch.object(
            repair, "_load_previous_full_projection", return_value=None
        ):
            refreshed = repair._refresh_report_bootstrap(envelope, rebuilt, ROOT / "docs", report["date"])

        for view, rows in old_evidence["views"].items():
            if view != "highlights":
                self.assertEqual(rows, refreshed["recommendationEvidence"]["views"][view], view)
        self.assertEqual(
            [row["code"] for row in rebuilt["workspace"]["views"]["highlights"]],
            [row["code"] for row in refreshed["recommendationEvidence"]["views"]["highlights"]],
        )
        self.assertEqual(refreshed["recommendationEvidence"],
                         repair._bound_published_evidence(refreshed, rebuilt))

    def test_staged_consumer_uses_precisely_the_restored_view_allowance(self):
        report = self._today()
        rebuilt, diagnostics = rebuild_strategy_scorecard_report(
            report, report_date=report["date"], scorecards=self._scorecards(),
            review_diagnostics={"status": "ok"},
        )
        _, envelope = self._legacy_fixture()
        with patch.object(repair, "_load_psy12_shadow_history", return_value=[]), patch.object(
            repair, "_load_previous_full_projection", return_value=None
        ):
            refreshed = repair._refresh_report_bootstrap(envelope, rebuilt, ROOT / "docs", report["date"])
        ignored = set(diagnostics["restored_highlights_views"])
        self.assertEqual({"highlights"}, ignored)
        projection = repair.workspace_selection_projection(report, ignore_views=ignored)
        with tempfile.TemporaryDirectory() as temp:
            docs = Path(temp) / "docs"
            (docs / "data").mkdir(parents=True)
            (docs / report["date"]).mkdir()
            manifest = {"dates": [report["date"]]}
            (docs / "data/index.json").write_text(json.dumps(manifest), encoding="utf-8")
            (docs / "data/comparison-index.json").write_text(json.dumps({
                "reports": {report["date"]: {"views": {"main": [], "h4_t3": []}}}
            }), encoding="utf-8")
            (docs / "data" / (report["date"] + ".json")).write_text(
                json.dumps(rebuilt, ensure_ascii=False), encoding="utf-8")
            (docs / "data.json").write_text(json.dumps({
                "dates": [report["date"]], "reports": {report["date"]: rebuilt},
            }, ensure_ascii=False), encoding="utf-8")
            repair.copy_report_assets(str(docs))
            for relative, prefix in (("index.html", ""), (report["date"] + "/index.html", "../")):
                html = repair._build_report_v2_html(
                    report["date"], repair._escape_inline_json(refreshed),
                    asset_prefix=prefix, asset_version=repair._report_asset_version(),
                )
                (docs / relative).write_text(html, encoding="utf-8")
            names = ("daily", "aggregate", "inline", "archive")
            args = (
                docs, report["date"],
                {name: protected_report_digest(report) for name in names},
                {name: projection for name in names},
            )
            with self.assertRaisesRegex(RuntimeError, "workspace membership or ordering drift"):
                repair._validate_staged_artifacts(
                    args[0], args[1], args[2],
                    {name: repair.workspace_selection_projection(report) for name in names},
                    {name: set() for name in names},
                    self._scorecards(), {"status": "ok"},
                    (rebuilt.get("diagnostics") or {}).get("recommendation_ledger"), manifest,
                )
            planes = repair._validate_staged_artifacts(
                *args, {name: ignored for name in names},
                self._scorecards(), {"status": "ok"},
                (rebuilt.get("diagnostics") or {}).get("recommendation_ledger"), manifest,
            )
            self.assertEqual([row["code"] for row in rebuilt["workspace"]["views"]["highlights"]],
                             [row["code"] for row in planes["inline"]["workspace"]["views"]["highlights"]])


if __name__ == "__main__":
    unittest.main()
