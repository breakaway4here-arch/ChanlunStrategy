"""Same-report published membership survives archive cleanup, without old facts."""

import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.report_comparison import (
    build_comparison_index, comparison_review_snapshot, write_comparison_index,
)
from tests import test_report_comparison as comparison_tests


class ReviewSnapshotBindingTests(unittest.TestCase):
    DATE = "2026-01-05"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="review-binding-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.fixture = comparison_tests.ReportComparisonIndexTest()
        self.fixture._write_report(str(self.data), self.DATE)
        self.raw_path = self.data / (self.DATE + ".json")
        self.raw = json.loads(self.raw_path.read_text())
        self.raw["workspace"]["views"]["highlights"] = []
        self.raw_path.write_text(json.dumps(self.raw), encoding="utf-8")
        (self.data / "index.json").write_text(json.dumps({
            "dates": [self.DATE], "date_meta": {
                self.DATE: {"is_trading_day": True, "is_official": True},
            },
        }), encoding="utf-8")
        self.database = self.root / "market.sqlite"
        self.fixture._create_db(str(self.database))
        self.network = mock.patch("requests.Session.request", side_effect=AssertionError("real network"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.items = [
            self.fixture._workbench_item("600001", "正式股", view="main"),
            self.fixture._workbench_item("300456", "研究股", rank=2),
        ]
        self.publish(self.items)

    @property
    def html(self):
        return self.root / self.DATE / "index.html"

    def publish(self, items, **kwargs):
        self.fixture._write_archived_workbench(
            str(self.root), self.DATE, items, **kwargs
        )

    def build(self):
        return build_comparison_index(str(self.data), str(self.database))

    def persist(self, index):
        (self.data / "comparison-index.json").write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def codes(index):
        return [entry["code"] for entry in index["review_registry"]["entries"]]

    def test_cleaned_html_preserves_members_sources_and_formal_views(self):
        before = self.build()
        self.persist(before)
        self.html.unlink()
        after = self.build()
        self.assertEqual(self.codes(after), ["600001", "300456"])
        self.assertEqual(after["review_registry"]["entries"], before["review_registry"]["entries"])
        self.assertEqual(after["reports"], before["reports"])
        self.assertEqual(after["review_registry"]["horizon_summary"], before["review_registry"]["horizon_summary"])

    def test_authoritative_empty_snapshot_survives_cleanup(self):
        self.persist(self.build())
        self.publish([], snapshot_id="empty-published")
        empty = self.build()
        self.assertEqual(self.codes(empty), [])
        self.persist(empty)
        self.html.unlink()
        after = self.build()
        self.assertEqual(self.codes(after), [])
        self.assertEqual(after["review_registry"]["registered_count"], 0)

    def test_current_generation_replaces_stale_html_and_preserves_unknown_versions(self):
        current = {
            "schema_version": "decision-workbench-v1", "report_date": self.DATE,
            "snapshot_id": "current", "items": [
                self.fixture._workbench_item("300789", "当前研究股"),
            ],
        }
        with comparison_review_snapshot(current):
            before = self.build()
        self.persist(before)
        self.html.unlink()
        after = self.build()
        self.assertEqual(self.codes(after), ["300789"])
        source = after["review_registry"]["entries"][0]["sources"][0]
        self.assertIsNone(source["strategy_version"])
        self.assertIsNone(source["policy_version"])

    def test_raw_revision_and_missing_raw_never_restore_old_receipt(self):
        self.persist(self.build())
        self.html.unlink()
        self.raw["strategy_version"] = "new-strategy"
        self.raw_path.write_text(json.dumps(self.raw), encoding="utf-8")
        revised = self.build()
        self.assertEqual(self.codes(revised), ["600001"])
        self.assertEqual(revised["review_registry"].get("published_member_snapshots"), {})
        self.raw_path.unlink()
        self.assertEqual(self.codes(self.build()), [])

    def test_nonversion_raw_revision_invalidates_receipt(self):
        self.persist(self.build())
        self.html.unlink()
        self.assertEqual(self.raw["workspace"]["views"]["main"][0]["view_rank"], 2)
        self.raw["workspace"]["views"]["main"][0]["view_rank"] = 3
        self.raw_path.write_text(json.dumps(self.raw), encoding="utf-8")
        revised = self.build()
        self.assertEqual(self.codes(revised), ["600001"])
        self.assertEqual(revised["review_registry"]["published_member_snapshots"], {})
        self.assertEqual(revised["review_registry"]["entries"][0]["coverage_status"],
                         "unconfirmed_legacy_workspace")

    def test_malformed_receipt_enum_types_keep_legacy_registry_available(self):
        healthy_date = "2026-01-06"
        self.fixture._write_report(str(self.data), healthy_date)
        healthy_raw_path = self.data / (healthy_date + ".json")
        healthy_raw = json.loads(healthy_raw_path.read_text())
        healthy_raw["workspace"]["views"]["highlights"] = []
        healthy_raw_path.write_text(json.dumps(healthy_raw), encoding="utf-8")
        self.fixture._write_archived_workbench(str(self.root), healthy_date, self.items)
        (self.data / "index.json").write_text(json.dumps({
            "dates": [self.DATE, healthy_date], "date_meta": {
                date: {"is_trading_day": True, "is_official": True}
                for date in (self.DATE, healthy_date)
            },
        }), encoding="utf-8")
        valid = self.build()
        self.html.unlink()
        (self.root / healthy_date / "index.html").unlink()
        for field in ("snapshot_kind", "source_view"):
            for value in ([], {}):
                with self.subTest(field=field, value=value):
                    stored = copy.deepcopy(valid)
                    receipt = stored["review_registry"]["published_member_snapshots"][self.DATE]
                    if field == "snapshot_kind":
                        receipt[field] = value
                    else:
                        receipt["members"][1]["sources"][0]["view"] = value
                    # An internally matching digest does not make malformed types valid.
                    unsigned = {key: item for key, item in receipt.items()
                                if key != "content_sha256"}
                    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False)
                    receipt["content_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                    self.persist(stored)
                    after = self.build()
                    self.assertEqual(after["review_registry"]["status"], "available")
                    self.assertEqual([(row["report_date"], row["code"])
                                      for row in after["review_registry"]["entries"]],
                                     [(self.DATE, "600001"), (healthy_date, "600001"),
                                      (healthy_date, "300456")])
                    self.assertEqual(set(after["review_registry"]["published_member_snapshots"]),
                                     {healthy_date})
                    self.assertEqual(after["reports"][healthy_date]["views"],
                                     valid["reports"][healthy_date]["views"])

    def test_member_and_version_damage_invalidates_whole_receipt(self):
        valid = self.build()
        self.html.unlink()
        for field in ("member_order", "partial_members", "source_version", "raw_hash"):
            with self.subTest(field=field):
                stored = copy.deepcopy(valid)
                receipt = stored["review_registry"]["published_member_snapshots"][self.DATE]
                if field == "member_order":
                    receipt["members"].reverse()
                elif field == "partial_members":
                    receipt["members"].pop()
                elif field == "source_version":
                    receipt["members"][1]["sources"][0]["strategy_version"] = "wrong-version"
                else:
                    receipt["binding"]["raw_report_sha256"] = "0" * 64
                self.persist(stored)
                after = self.build()
                self.assertEqual(self.codes(after), ["600001"])
                self.assertEqual(after["review_registry"]["published_member_snapshots"], {})

    def test_restored_members_recompute_current_formal_incident_eligibility(self):
        before = self.build()
        self.assertEqual(before["review_registry"]["entries"][0]["sources"][0]
                         ["formal_performance_status"], "formal_eligible")
        self.persist(before)
        self.html.unlink()
        with mock.patch("chanlun.report_comparison._registered_incident_codes",
                        return_value={"600001"}):
            after = self.build()
        self.assertEqual(self.codes(after), ["600001", "300456"])
        self.assertEqual(after["review_registry"]["entries"][0]["sources"][0]
                         ["formal_performance_status"], "incident_excluded")
        self.assertEqual(after["reports"][self.DATE]["views"]["main"], [])

    def test_atomic_receipt_writer_is_stable_after_cleanup_and_preserves_failed_update(self):
        with sqlite3.connect(str(self.database)) as connection:
            connection.execute("INSERT INTO bars_day VALUES (?, ?, ?, ?)",
                               (1, self.DATE, 10.5, 1))
        target = Path(write_comparison_index(str(self.data), str(self.database)))
        published = target.read_bytes()
        self.html.unlink()
        write_comparison_index(str(self.data), str(self.database))
        self.assertEqual(target.read_bytes(), published)
        with sqlite3.connect(str(self.database)) as connection:
            connection.execute("UPDATE bars_day SET close=11.5 WHERE instrument_id=1")
        with mock.patch("chanlun.report_comparison.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(comparison_tests.report_comparison.ComparisonIndexUnavailable):
                write_comparison_index(str(self.data), str(self.database))
        self.assertEqual(target.read_bytes(), published)
        self.assertEqual(list(self.data.glob(".comparison-index-*.json")), [])

    def test_existing_invalid_html_invalidates_persisted_receipt(self):
        for invalid in ("<html>no bootstrap</html>", "<script>window.CHANLUN_BOOTSTRAP={broken};</script>"):
            with self.subTest(html=invalid):
                self.publish(self.items)
                self.persist(self.build())
                self.html.write_text(invalid, encoding="utf-8")
                invalid_index = self.build()
                self.assertEqual(self.codes(invalid_index), ["600001"])
                self.assertEqual(invalid_index["review_registry"].get("published_member_snapshots"), {})
                self.persist(invalid_index)
                self.html.unlink()
                self.assertEqual(self.codes(self.build()), ["600001"])

    def test_conflicting_html_does_not_resurrect_after_cleanup(self):
        self.persist(self.build())
        foreign = copy.deepcopy(self.raw)
        foreign["snapshot_id"] = "foreign-report"
        self.publish(self.items, inline_report=foreign)
        conflict = self.build()
        self.assertTrue(all(entry["coverage_status"] == "unconfirmed_report_identity"
                            for entry in conflict["review_registry"]["entries"]))
        self.assertEqual(conflict["review_registry"].get("published_member_snapshots"), {})
        self.persist(conflict)
        self.html.unlink()
        self.assertEqual(self.codes(self.build()), ["600001"])

    def test_light_receipt_contains_no_candidate_access_or_derived_return(self):
        self.items[1]["candidate"] = {"private_secret": "not-a-receipt-fact"}
        self.items[1]["chart"] = {"closes": [999]}
        self.publish(self.items)
        registry = self.build()["review_registry"]
        receipt = registry["published_member_snapshots"][self.DATE]
        serialized = json.dumps(receipt)
        for excluded in ("candidate", "private_secret", "chart", "accessKey", "must-not-be-retained",
                         "horizons", "return_pct", "formal_performance_status"):
            self.assertNotIn(excluded, serialized)
        self.assertEqual(receipt["binding"]["comparison_contract"]["strategy_identities"][0]["policy_version"], "decision-v2")


if __name__ == "__main__":
    unittest.main()
