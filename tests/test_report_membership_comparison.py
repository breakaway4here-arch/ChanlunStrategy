"""Published membership comparison keeps its own evidence boundary."""

import json
import tempfile
import unittest
from pathlib import Path

from chanlun.decision_workbench import _changes
from chanlun.report_comparison import load_published_comparison_snapshot
from chanlun.report_generator import _load_previous_full_projection
from tests.test_report_comparison import ReportComparisonIndexTest


class PublishedMembershipComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.day = "2026-01-05"
        self.helper = ReportComparisonIndexTest()
        self.helper._write_report(str(self.data), self.day)
        self.report = json.loads((self.data / (self.day + ".json")).read_text())
        self.items = [
            self.helper._workbench_item("600001", "原有"),
            self.helper._workbench_item("300890", "翔丰华"),
        ]
        self.helper._write_archived_workbench(str(self.root), self.day, self.items)

    def load(self):
        return load_published_comparison_snapshot(str(self.data), self.day, self.report)

    def test_bound_archive_keeps_complete_members_and_exact_previous_names(self):
        result = self.load()
        self.assertEqual(result["membership_status"], "available")
        self.assertEqual(result["source"], "published_html_bootstrap")
        self.assertEqual({row["code"] for row in result["members"].values()}, {"600001", "300890"})
        self.assertEqual(result["members"]["SZ300890"]["name"], "翔丰华")

    def test_bad_archive_does_not_use_valid_old_receipt(self):
        from chanlun.report_comparison import _published_member_receipt, _workbench_review_entries
        workbench = json.loads((self.root / self.day / "index.html").read_text().split("window.CHANLUN_BOOTSTRAP= ", 1)[1].split(";</script>", 1)[0])["decisionWorkbench"]
        entries = _workbench_review_entries(self.report, self.day, workbench,
                                           "published_html_bootstrap", "confirmed_display_snapshot")
        receipt = _published_member_receipt(self.report, self.day, workbench,
                                            "published_html_bootstrap", entries)
        (self.data / "comparison-index.json").write_text(json.dumps({"review_registry": {
            "published_member_snapshots": {self.day: receipt}}}))
        (self.root / self.day / "index.html").write_text("<script>window.CHANLUN_BOOTSTRAP = {bad};</script>")
        result = self.load()
        self.assertEqual(result["membership_status"], "unavailable")
        self.assertNotEqual(result.get("source"), "published_receipt")
        (self.root / self.day / "index.html").unlink()
        restored = self.load()
        self.assertEqual(restored["membership_status"], "available")
        self.assertEqual(restored["source"], "published_receipt")

    def test_duplicate_bootstrap_blocks_receipt_and_raw_revision(self):
        from chanlun.report_comparison import _published_member_receipt, _workbench_review_entries
        html = (self.root / self.day / "index.html").read_text()
        workbench = json.loads(html.split("window.CHANLUN_BOOTSTRAP= ", 1)[1].split(";</script>", 1)[0])["decisionWorkbench"]
        entries = _workbench_review_entries(self.report, self.day, workbench,
            "published_html_bootstrap", "confirmed_display_snapshot")
        receipt = _published_member_receipt(self.report, self.day, workbench,
            "published_html_bootstrap", entries)
        (self.data / "comparison-index.json").write_text(json.dumps({"review_registry": {
            "published_member_snapshots": {self.day: receipt}}}))
        (self.root / self.day / "index.html").write_text(html.replace("</script>",
            "window.CHANLUN_BOOTSTRAP= {};</script>"))
        self.assertEqual(self.load()["membership_status"], "unavailable")
        (self.root / self.day / "index.html").unlink()
        self.report["workspace"]["views"]["main"][0]["view_rank"] = 99
        self.assertEqual(self.load()["membership_status"], "unavailable")

    def test_bootstrap_text_inside_script_string_is_not_executable_snapshot(self):
        html = (self.root / self.day / "index.html").read_text()
        serialized = html.split("window.CHANLUN_BOOTSTRAP= ", 1)[1].split(";</script>", 1)[0]
        (self.root / self.day / "index.html").write_text(
            "<script>const note = `window.CHANLUN_BOOTSTRAP = " + serialized + ";`;</script>")
        self.assertEqual(self.load()["membership_status"], "unavailable")

    def test_bootstrap_text_inside_regex_literal_is_not_executable_snapshot(self):
        self.report = {"date": self.day}
        (self.data / (self.day + ".json")).write_text(json.dumps(self.report))
        serialized = json.dumps({
            "pageDate": self.day, "inlineReportData": self.report,
            "decisionWorkbench": {
                "schema_version": "decision-workbench-v1", "report_date": self.day,
                "phase": "formal", "snapshot_id": "published", "items": [],
            },
        }, separators=(",", ":"))
        (self.root / self.day / "index.html").write_text(
            "<script>const pattern = /window.CHANLUN_BOOTSTRAP = " + serialized + "/;</script>")
        self.assertEqual(self.load()["membership_status"], "unavailable")

    def test_explicit_formal_receipt_supports_empty_membership(self):
        from chanlun.report_comparison import _published_member_receipt
        workbench = {"schema_version": "decision-workbench-v1",
                     "report_date": self.day, "phase": "formal",
                     "snapshot_id": "empty-bound", "items": [],
                     "comparison_contract": {}}
        receipt = _published_member_receipt(self.report, self.day, workbench,
                                            "current_generation_bootstrap", [])
        (self.data / "comparison-index.json").write_text(json.dumps({"review_registry": {
            "published_member_snapshots": {self.day: receipt}}}))
        (self.root / self.day / "index.html").unlink()
        snapshot = self.load()
        self.assertEqual(snapshot["membership_status"], "available")
        self.assertEqual(snapshot["phase"], "formal")
        self.assertEqual(snapshot["members"], {})

    def test_missing_phase_keeps_member_facts_but_cannot_claim_formal(self):
        snapshot = self.load()
        self.assertEqual(snapshot["membership_status"], "available")
        self.assertIsNone(snapshot["phase"])
        current = {"phase": "formal", "report_date": "2026-01-06",
                   "comparison_contract": {}, "items": self.items}
        previous = {"phase": snapshot["phase"], "report_date": self.day,
                    "comparison_contract": {}, "items": self.items,
                    "membership_status": "available"}
        self.assertEqual(_changes(current, previous)["membership"]["status"], "unavailable")

    def test_noncanonical_current_identity_cannot_claim_complete_membership(self):
        previous = {"phase": "formal", "report_date": self.day,
                    "comparison_contract": {}, "items": self.items,
                    "membership_status": "available"}
        current = {"phase": "formal", "report_date": "2026-01-06",
                   "comparison_contract": {}, "items": [{
                       "instrument_id": "SH300890", "code": "300890"}]}
        self.assertEqual(_changes(current, previous)["membership"]["status"], "unavailable")

    def test_membership_survives_strategy_identity_failure(self):
        current = {"phase": "formal", "report_date": "2026-01-06",
                   "comparison_contract": {}, "items": [
                       {"instrument_id": "SZ300890", "code": "300890"},
                       {"instrument_id": "SZ300001", "code": "300001"}]}
        previous = {"phase": "formal", "report_date": self.day,
                    "comparison_contract": {}, "items": self.items,
                    "membership_status": "available", "comparison_source": "published_html_bootstrap"}
        changes = _changes(current, previous)
        self.assertEqual(changes["status"], "comparison_unavailable")
        self.assertEqual(changes["membership"]["status"], "available")
        self.assertEqual(changes["membership"]["added"], ["300001"])
        self.assertEqual(changes["membership"]["removed"], ["600001"])
        self.assertEqual(changes["membership"]["shared"], ["300890"])
        self.assertEqual(changes["membership"]["previous_items"]["600001"]["name"], "原有")

    def test_no_complete_previous_membership_keeps_unknown_instead_of_zero(self):
        current = {"phase": "formal", "report_date": "2026-01-06",
                   "comparison_contract": {}, "items": [{"instrument_id": "SZ300001", "code": "300001"}]}
        changes = _changes(current, None)
        self.assertEqual(changes["membership"]["status"], "unavailable")
        self.assertIsNone(changes["membership"]["added"])
        self.assertIsNone(changes["membership"]["removed"])
        partial = {"phase": "formal", "report_date": self.day,
                   "membership_status": "unavailable", "comparison_source": "legacy_json_view",
                   "items": [{"instrument_id": "SH600001", "code": "600001",
                              "name": "旧视图名称", "sources": ["main"]}],
                   "comparison_contract": {}}
        partial_changes = _changes(current, partial)["membership"]
        self.assertEqual(partial_changes["status"], "unavailable")
        self.assertIsNone(partial_changes["removed"])
        self.assertEqual(partial_changes["previous_items"]["600001"]["name"], "旧视图名称")

    def test_condition_change_coverage_distinguishes_unknown_partial_and_true_zero(self):
        contract = {"strategy_identities": [{"strategy_id": "luojie_pool",
            "strategy_version": "v1"}], "strategy_version": {"luojie_pool": "v1"}}
        blocked = {"instrument_id": "SZ300890", "code": "300890",
                   "page_status": "evidence_blocked",
                   "strategy_results": [{"strategy_id": "luojie"}]}
        comparable = {"instrument_id": "SH600001", "code": "600001",
                      "page_status": "watch_only",
                      "strategy_results": [{"strategy_id": "luojie"}]}
        def compare(items):
            previous = {"phase": "formal", "report_date": self.day,
                        "items": items, "comparison_contract": contract,
                        "membership_status": "available"}
            current = {"phase": "formal", "report_date": "2026-01-06",
                       "items": items, "comparison_contract": contract}
            return _changes(current, previous)
        blocked_result = compare([blocked])
        self.assertEqual(blocked_result["status"], "partial")
        self.assertEqual(blocked_result["changed"], [])
        self.assertEqual(blocked_result["condition_comparison"], {
            "status": "unavailable", "compared_count": 0, "changed_count": None})
        partial_result = compare([blocked, comparable])
        self.assertEqual(partial_result["status"], "partial")
        self.assertEqual(partial_result["condition_comparison"], {
            "status": "partial", "compared_count": 1, "changed_count": 0})
        empty_result = compare([])
        self.assertEqual(empty_result["status"], "available")
        self.assertEqual(empty_result["condition_comparison"], {
            "status": "available", "compared_count": 0, "changed_count": 0})

    def test_previous_public_summary_projects_only_safe_exact_source_ref_fields(self):
        previous = {"phase": "formal", "report_date": self.day,
            "membership_status": "available", "comparison_contract": {},
            "items": [{"instrument_id": "SZ300890", "code": "300890", "name": "翔丰华",
                "sources": ["luojie", {"view": "observation_top5", "local_path": "/private/secret"}],
                "source_refs": [{"view": "luojie", "local_path": "/private/secret",
                    "ref": {"pool": "luojie_pool", "source_pool": "research", "index": 2,
                            "code": "300890", "local_path": "/private/secret",
                            "candidate": {"kline": [1, 2, 3]}}}],
                "strategy_results": [{"strategy_id": "luojie", "role": "research",
                    "candidate": {"kline": [1, 2, 3]}}]}]}
        current = {"phase": "formal", "report_date": "2026-01-06",
                   "items": [], "comparison_contract": {}}
        summary = _changes(current, previous)["membership"]["previous_items"]["300890"]
        self.assertEqual(summary["sources"], ["luojie", "observation_top5"])
        self.assertEqual(summary["source_refs"], [{"view": "luojie",
            "ref": {"pool": "luojie_pool", "source_pool": "research",
                    "index": 2, "code": "300890"}}])
        self.assertNotIn("/private/secret", json.dumps(summary, ensure_ascii=False))
        self.assertNotIn("kline", json.dumps(summary, ensure_ascii=False))

    def test_real_published_september_snapshot_keeps_xiangfenghua(self):
        fixture_path = Path(__file__).parent / "fixtures" / "a2_published_members_20260930_20261008.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertTrue(fixture["source_commit"].startswith("608457b2"))
        before = fixture["snapshots"]["2026-09-30"]
        after = fixture["snapshots"]["2026-10-08"]
        self.assertEqual((len(before["items"]), len(after["items"])), (30, 42))
        previous = {"report_date": before["report_date"], "phase": before["phase"],
                    "snapshot_id": before["snapshot_id"], "items": before["items"],
                    "comparison_contract": {}, "membership_status": "available",
                    "comparison_source": "published_html_bootstrap"}
        current = {"report_date": after["report_date"], "phase": after["phase"],
                   "items": after["items"], "comparison_contract": {}}
        members = _changes(current, previous)["membership"]
        self.assertEqual((len(members["added"]), len(members["removed"]), len(members["shared"])),
                         (32, 20, 10))
        self.assertIn("300890", members["shared"])
        self.assertNotIn("300890", members["added"])
        self.assertEqual(members["previous_items"]["300890"]["name"], "翔丰华")
        self.assertTrue(members["previous_items"]["300890"]["source_refs"])

    def test_nearest_unknown_phase_is_skipped_for_older_verified_formal(self):
        recent = "2026-01-06"
        self.helper._write_report(str(self.data), recent)
        self.helper._write_archived_workbench(str(self.root), recent,
                                              [self.helper._workbench_item("300001", "近日报")])
        old_html = self.root / self.day / "index.html"
        html = old_html.read_text()
        marker = "window.CHANLUN_BOOTSTRAP= "
        start = html.index(marker) + len(marker)
        payload, end = json.JSONDecoder().raw_decode(html, start)
        payload["decisionWorkbench"]["phase"] = "formal"
        old_html.write_text(html[:start] + json.dumps(payload, ensure_ascii=False) + html[end:])
        chosen = _load_previous_full_projection(str(self.root),
            {self.day: {}, recent: {}}, "2026-01-07")
        self.assertEqual(chosen["report_date"], self.day)
        self.assertEqual(chosen["phase"], "formal")
        self.assertEqual(chosen["comparison_skipped"], [
            {"report_date": recent, "reason": "published_phase_unverified"}])
