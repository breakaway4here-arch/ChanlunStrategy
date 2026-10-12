"""Synthetic published observations remain bound after the short comparison window."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.report_comparison import write_comparison_index
from chanlun.report_generator import update_data_json
from chanlun.selection_performance import (
    _trading_calendar, aggregate_selection_performance,
    build_selection_performance, load_published_observations,
)
from tests.test_selection_performance import _series


class ReviewReceiptRetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-receipt-retention-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.root / "absent.sqlite"
        self.dates = _trading_calendar(self.db, "2026-08-03", "2026-11-30")[:61]
        self.first = self.dates[0]
        self.report = {
            "date": self.first,
            "data_quality": {"is_trading_day": True},
            "kaipanla_context": {
                "status": "available", "source": "kaipanla", "data_date": self.first,
                "fetched_at": self.first + "T14:00:00+08:00",
                "groups": [{"code": "ai", "name": "合成AI题材",
                            "stocks": [{"code": "600001"}]}],
            },
        }
        self.workbench = {
            "schema_version": "decision-workbench-v1", "report_date": self.first,
            "snapshot_id": "synthetic-published-v1", "phase": "formal",
            "as_of": self.first + "T15:20:00+08:00", "comparison_contract": {},
            "items": [{"code": "600001", "instrument_id": "SH600001",
                       "name": "合成甲", "strategy_results": [{
                           "strategy_id": "highlights", "role": "research",
                           "candidate": {"strategy_version": "synthetic-v1"},
                       }]}],
        }
        self.archive = self.root / self.first / "index.html"
        self.archive.parent.mkdir()
        self.archive.write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": self.first, "inlineReportData": self.report,
                "decisionWorkbench": self.workbench,
            }, ensure_ascii=False) + ";</script>", encoding="utf-8")
        (self.data / (self.first + ".json")).write_text(
            json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
        self.price_file = self.root / "synthetic-prices.json"
        self.price_file.write_text(json.dumps({
            "schema_version": "verified-price-series-v1",
            "series": [_series("SH600001", self.dates, {30: 130})],
        }), encoding="utf-8")
        self.network = mock.patch("requests.Session.request", side_effect=AssertionError("network"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.published_count = 0
        self.datasets = {}
        self.keep_archive = False

    def publish_through(self, count):
        for position in range(self.published_count, count):
            day = self.dates[position]
            path = self.data / (day + ".json")
            if not path.exists():
                path.write_text(json.dumps({
                    "date": day, "data_quality": {"is_trading_day": True},
                    "workspace": {"views": {"main": [], "highlights": [], "h4_t3": []}},
                }), encoding="utf-8")
            (self.data / "index.json").write_text(json.dumps({
                "dates": self.dates[:position + 1],
                "date_meta": {date: {"is_trading_day": True}
                              for date in self.dates[:position + 1]},
            }), encoding="utf-8")
            write_comparison_index(str(self.data), str(self.db))
            if day == self.dates[1] and not self.keep_archive:
                with mock.patch("chanlun.report_generator.HISTORY_DAYS", 1):
                    update_data_json({"date": self.first}, output_dir=str(self.root))
                    update_data_json({"date": day}, output_dir=str(self.root))
                self.assertFalse(self.archive.exists())
            self.datasets[position + 1] = self.performance(position + 1)
        self.published_count = count

    def performance(self, count):
        day = self.dates[count - 1]
        return build_selection_performance(
            self.data, self.db, day, day + "T15:20:00+08:00",
            price_series_file=self.price_file,
        )

    def test_first_published_observation_survives_report_27(self):
        self.publish_through(27)
        index = json.loads((self.data / "comparison-index.json").read_text())
        self.assertEqual(len(index["dates"]), 26)
        self.assertNotIn(self.first, index["dates"])
        self.assertIn(self.first, index["review_registry"]["published_member_snapshots"])
        loaded = load_published_observations(self.data, self.dates[26])
        self.assertEqual(len(loaded["observations"]), 1)
        self.assertEqual(loaded["observations"][0]["theme_refs"][0]["theme_id"],
                         "kaipanla:ai")
        self.assertEqual(len(self.performance(27)["observations"]), 1)

    def test_35_and_61_reports_keep_full_cohort_and_short_display_window(self):
        report_bytes = (self.data / (self.first + ".json")).read_bytes()
        price_bytes = self.price_file.read_bytes()
        self.publish_through(35)
        for count in (26, 27, 31, 35):
            with self.subTest(report_count=count):
                dataset = self.datasets[count]
                self.assertEqual(len(dataset["observations"]), 1)
                observation = dataset["observations"][0]
                self.assertEqual(observation["instrument_id"], "SH600001")
                self.assertEqual(observation["theme_refs"][0]["theme_id"], "kaipanla:ai")
                self.assertEqual(dataset["coverage"]["published_report_dates"], 1)
        mature = self.datasets[31]
        self.assertEqual(mature["observations"][0]["outcomes"]["t30"]["status"],
                         "ready")
        self.assertEqual(mature["summary"]["t30"]["counts"]["ready"], 1)
        self.assertEqual(mature["summary"]["t30"]["mean_return_pct"], 30)
        self.assertEqual(mature["summary"]["t30"]["best_observations"][0]
                         ["instrument_id"], "SH600001")
        self.assertEqual(mature["summary"]["t30"]["worst_observations"][0]
                         ["instrument_id"], "SH600001")
        self.assertEqual(mature["groups"]["themes"]["kaipanla:ai"]
                         ["horizons"]["t30"]["counts"]["ready"], 1)
        index = json.loads((self.data / "comparison-index.json").read_text())
        self.assertEqual(index["dates"], self.dates[9:35])
        self.assertEqual(index["reports"].keys(), set(self.dates[9:35]))
        self.assertEqual(index["review_registry"]["registered_count"], 0)
        self.assertEqual(index["review_registry"]["entries"], [])
        self.assertEqual(index["review_registry"]["published_member_snapshots"]
                         [self.first]["binding"]["publication_asof"],
                         self.first + "T15:20:00+08:00")
        self.publish_through(61)
        last = self.datasets[61]
        self.assertEqual(len(last["observations"]), 1)
        self.assertEqual(last["summary"]["t30"]["counts"]["ready"], 1)
        default_start = last["trading_dates"][-60]
        self.assertGreater(default_start, self.first)
        default = aggregate_selection_performance(last, horizon=30,
                                                  report_start=default_start)
        self.assertEqual(default["counts"]["ready"], 0)
        historical = aggregate_selection_performance(last, horizon=30,
                                                     report_start=self.first)
        self.assertEqual(historical["counts"]["ready"], 1)
        index = json.loads((self.data / "comparison-index.json").read_text())
        self.assertEqual(index["dates"], self.dates[35:61])
        self.assertEqual(index["review_registry"]["registered_count"], 0)
        self.assertIn(self.first, index["review_registry"]["published_member_snapshots"])
        self.assertEqual((self.data / (self.first + ".json")).read_bytes(), report_bytes)
        self.assertEqual(self.price_file.read_bytes(), price_bytes)

    def test_valid_old_html_rebuilds_its_receipt_before_archive_cleanup(self):
        self.keep_archive = True
        self.publish_through(27)
        self.assertTrue(self.archive.exists())
        changed = copy.deepcopy(self.workbench)
        changed["snapshot_id"] = "synthetic-republished-v2"
        changed["items"][0]["code"] = "600002"
        changed["items"][0]["instrument_id"] = "SH600002"
        self.archive.write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": self.first, "inlineReportData": self.report,
                "decisionWorkbench": changed,
            }, ensure_ascii=False) + ";</script>", encoding="utf-8")
        write_comparison_index(str(self.data), str(self.db))
        index = json.loads((self.data / "comparison-index.json").read_text())
        receipt = index["review_registry"]["published_member_snapshots"][self.first]
        self.assertEqual(receipt["members"][0]["code"], "600002")
        self.assertEqual(receipt["binding"]["snapshot_id"], "synthetic-republished-v2")
        self.archive.unlink()
        write_comparison_index(str(self.data), str(self.db))
        loaded = load_published_observations(self.data, self.dates[26])
        self.assertEqual([row["code"] for row in loaded["observations"]], ["600002"])
        self.assertEqual(loaded["observations"][0]["theme_refs"], [])

    def test_nonempty_short_window_views_scores_and_order_match_before_and_after_roll(self):
        day = self.dates[25]
        report = {
            "date": day, "data_quality": {"is_trading_day": True},
            "workspace": {"views": {"main": [
                {"code": "600002", "name": "合成正式甲", "view_rank": 1,
                 "score": 88},
                {"code": "600003", "name": "合成正式乙", "view_rank": 2,
                 "score": 76},
            ], "highlights": [], "h4_t3": []}},
        }
        (self.data / (day + ".json")).write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8")
        workbench = {
            "schema_version": "decision-workbench-v1", "report_date": day,
            "snapshot_id": "synthetic-current-formal", "phase": "formal",
            "as_of": day + "T15:20:00+08:00", "comparison_contract": {},
            "items": [{
                "code": code, "instrument_id": "SH" + code, "name": name,
                "strategy_results": [{"strategy_id": "main", "role": "formal",
                                      "view_rank": rank, "score": score,
                                      "formal_action": "recommend"}],
            } for code, name, rank, score in (
                ("600002", "合成正式甲", 1, 88),
                ("600003", "合成正式乙", 2, 76),
            )],
        }
        archive = self.root / day / "index.html"
        archive.parent.mkdir()
        archive.write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": day, "inlineReportData": report,
                "decisionWorkbench": workbench,
            }, ensure_ascii=False) + ";</script>", encoding="utf-8")
        self.publish_through(26)
        before = json.loads((self.data / "comparison-index.json").read_text())
        before_entries = [row for row in before["review_registry"]["entries"]
                          if row["report_date"] == day]
        self.assertEqual([(row["code"], row["sources"][0]["score"])
                          for row in before_entries],
                         [("600002", 88), ("600003", 76)])
        self.publish_through(27)
        after = json.loads((self.data / "comparison-index.json").read_text())
        self.assertEqual(after["dates"], self.dates[1:27])
        self.assertEqual(after["reports"][day]["views"],
                         before["reports"][day]["views"])
        self.assertEqual([after["reports"][day]["prices"][code]
                          for code in ("600002", "600003")],
                         [before["reports"][day]["prices"][code]
                          for code in ("600002", "600003")])
        after_entries = [row for row in after["review_registry"]["entries"]
                         if row["report_date"] == day]
        self.assertEqual([{key: value for key, value in row.items()
                           if key != "horizons"} for row in after_entries],
                         [{key: value for key, value in row.items()
                           if key != "horizons"} for row in before_entries])
        self.assertEqual(after["review_registry"]["registered_count"], 2)
        self.assertEqual(after["review_registry"]["instrument_count"], 2)
        self.assertIn(self.first, after["review_registry"]["published_member_snapshots"])

    def test_invalid_old_receipt_date_keys_cannot_enter_retained_registry(self):
        self.publish_through(27)
        path = self.data / "comparison-index.json"
        index = json.loads(path.read_text())
        old = index["review_registry"]["published_member_snapshots"][self.first]
        invalid_date = "2026-13-01"
        invalid_report = copy.deepcopy(self.report)
        invalid_report["date"] = invalid_date
        (self.data / (invalid_date + ".json")).write_text(
            json.dumps(invalid_report, ensure_ascii=False), encoding="utf-8")
        receipt = copy.deepcopy(old)
        receipt["binding"]["report_date"] = invalid_date
        receipt["binding"]["raw_report_sha256"] = self._digest(invalid_report)
        receipt["members"][0]["report_date"] = invalid_date
        receipt["content_sha256"] = self._digest({
            key: value for key, value in receipt.items() if key != "content_sha256"})
        index["review_registry"]["published_member_snapshots"].update({
            invalid_date: receipt, "../bad-path": old,
        })
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        write_comparison_index(str(self.data), str(self.db))
        after = json.loads(path.read_text())
        self.assertEqual(after["review_registry"]["status"], "available")
        self.assertEqual(set(after["review_registry"]["published_member_snapshots"]),
                         {self.first})

    def test_empty_display_manifest_does_not_erase_bound_old_observation(self):
        self.publish_through(27)
        manifest_path = self.data / "index.json"
        manifest = manifest_path.read_bytes()
        manifest_path.write_text(json.dumps({"dates": [], "date_meta": {}}),
                                 encoding="utf-8")
        write_comparison_index(str(self.data), str(self.db))
        empty = json.loads((self.data / "comparison-index.json").read_text())
        self.assertEqual(empty["dates"], [])
        self.assertEqual(empty["review_registry"]["entries"], [])
        self.assertIn(self.first, empty["review_registry"]["published_member_snapshots"])
        self.assertIn(self.first, empty["review_registry"]["published_theme_contexts"])
        manifest_path.write_bytes(manifest)
        write_comparison_index(str(self.data), str(self.db))
        recovered = self.performance(27)
        self.assertEqual(len(recovered["observations"]), 1)
        self.assertEqual(recovered["observations"][0]["instrument_id"], "SH600001")
        self.assertEqual(recovered["observations"][0]["theme_refs"][0]["theme_id"],
                         "kaipanla:ai")

    def test_bad_old_html_score_does_not_unavailable_healthy_or_current_reports(self):
        self.keep_archive = True
        healthy_day = self.dates[1]
        current_day = self.dates[27]
        for day, code in ((healthy_day, "600002"), (current_day, "600003")):
            report = {
                "date": day, "data_quality": {"is_trading_day": True},
                "workspace": {"views": {"main": [], "highlights": []}},
            }
            workbench = copy.deepcopy(self.workbench)
            workbench["report_date"] = day
            workbench["snapshot_id"] = "synthetic-" + day
            workbench["as_of"] = day + "T15:20:00+08:00"
            workbench["items"][0]["code"] = code
            workbench["items"][0]["instrument_id"] = "SH" + code
            (self.data / (day + ".json")).write_text(
                json.dumps(report, ensure_ascii=False), encoding="utf-8")
            archive = self.root / day / "index.html"
            archive.parent.mkdir()
            archive.write_text(
                "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                    "pageDate": day, "inlineReportData": report,
                    "decisionWorkbench": workbench,
                }, ensure_ascii=False) + ";</script>", encoding="utf-8")
        self.publish_through(28)
        path = self.data / "comparison-index.json"
        before = json.loads(path.read_text())["review_registry"]
        self.assertEqual(before["status"], "available")
        self.assertIn(self.first, before["published_member_snapshots"])
        self.assertIn(healthy_day, before["published_member_snapshots"])
        current_entries = [row for row in before["entries"]
                           if row["report_date"] == current_day]
        self.assertEqual([row["code"] for row in current_entries], ["600003"])
        bad = copy.deepcopy(self.workbench)
        bad["items"][0]["strategy_results"][0]["score"] = 10 ** 400
        self.archive.write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": self.first, "inlineReportData": self.report,
                "decisionWorkbench": bad,
            }, ensure_ascii=False) + ";</script>", encoding="utf-8")
        write_comparison_index(str(self.data), str(self.db))
        after = json.loads(path.read_text())["review_registry"]
        self.assertEqual(after["status"], "available")
        self.assertNotIn(self.first, after["published_member_snapshots"])
        self.assertIn(healthy_day, after["published_member_snapshots"])
        self.assertIn(current_day, after["published_member_snapshots"])
        self.assertEqual([row for row in after["entries"]
                          if row["report_date"] == current_day], current_entries)

    def test_window_external_receipts_still_reject_revisions_conflicts_and_damage(self):
        self.publish_through(27)
        path = self.data / "comparison-index.json"
        original = json.loads(path.read_text())
        raw_path = self.data / (self.first + ".json")
        raw = raw_path.read_bytes()
        cases = ("revised_json", "missing_json", "bad_html", "bad_member",
                 "bad_theme", "old_receipt_without_asof")
        for case in cases:
            with self.subTest(case=case):
                path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
                raw_path.write_bytes(raw)
                self.archive.unlink(missing_ok=True)
                index = copy.deepcopy(original)
                registry = index["review_registry"]
                if case == "revised_json":
                    report = json.loads(raw)
                    report["kaipanla_context"]["groups"][0]["name"] = "修订题材"
                    raw_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
                elif case == "missing_json":
                    raw_path.unlink()
                elif case == "bad_html":
                    self.archive.parent.mkdir(exist_ok=True)
                    self.archive.write_text("<html>broken archive</html>", encoding="utf-8")
                elif case == "bad_member":
                    member = registry["published_member_snapshots"][self.first]["members"][0]
                    member["name"] = "错误成员"
                elif case == "bad_theme":
                    context = registry["published_theme_contexts"][self.first]
                    context["theme_refs_by_instrument"]["SH600001"] = []
                    context["content_sha256"] = self._digest({
                        key: value for key, value in context.items()
                        if key != "content_sha256"})
                else:
                    receipt = registry["published_member_snapshots"][self.first]
                    receipt["binding"].pop("publication_asof")
                    receipt["content_sha256"] = self._digest({
                        key: value for key, value in receipt.items()
                        if key != "content_sha256"})
                path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
                write_comparison_index(str(self.data), str(self.db))
                after = json.loads(path.read_text())["review_registry"]
                loaded = load_published_observations(self.data, self.dates[26])
                if case in {"bad_theme", "old_receipt_without_asof"}:
                    self.assertIn(self.first, after["published_member_snapshots"])
                    self.assertNotIn(self.first, after["published_theme_contexts"])
                    self.assertEqual(len(loaded["observations"]), 1)
                    self.assertEqual(loaded["observations"][0]["theme_refs"], [])
                else:
                    self.assertNotIn(self.first, after["published_member_snapshots"])
                    self.assertNotIn(self.first, after["published_theme_contexts"])
                    self.assertEqual(loaded["observations"], [])
        raw_path.write_bytes(raw)
        self.archive.unlink(missing_ok=True)

    @staticmethod
    def _digest(value):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    unittest.main()
