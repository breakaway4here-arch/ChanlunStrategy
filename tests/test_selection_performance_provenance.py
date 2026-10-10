"""Published theme and source-specific performance facts survive their lifecycle."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.report_comparison import comparison_review_snapshot, write_comparison_index
from chanlun.report_generator import update_data_json
from chanlun.selection_price_evidence import capture_eastmoney_historical_response
from chanlun.selection_performance import (
    _theme_refs,
    aggregate_selection_performance,
    build_selection_performance,
    evaluate_observations,
    load_published_observations,
)
from tests.test_selection_performance import _series


DAY = "2026-08-03"
NEXT = "2026-08-04"


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class PublishedThemeLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="published-theme-lifecycle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.archive = self.root / DAY / "index.html"
        self.archive.parent.mkdir()
        self.report = {
            "date": DAY,
            "kaipanla_context": {
                "status": "available", "source": "kaipanla", "data_date": DAY,
                "fetched_at": DAY + "T14:00:00+08:00",
                "groups": [{"code": "ai", "name": "AI应用",
                            "stocks": [{"code": "600001"}]}],
            },
        }
        self.workbench = {
            "schema_version": "decision-workbench-v1", "report_date": DAY,
            "snapshot_id": "published-v1", "phase": "formal",
            "as_of": DAY + "T15:20:00+08:00", "comparison_contract": {},
            "items": [{"code": "600001", "instrument_id": "SH600001",
                       "name": "甲", "strategy_results": [{
                           "strategy_id": "highlights", "role": "research",
                           "candidate": {"strategy_version": "research-v1"},
                       }]}],
        }
        (self.data / "index.json").write_text(json.dumps({
            "dates": [DAY], "date_meta": {DAY: {"is_trading_day": True}},
        }), encoding="utf-8")
        self.db = self.root / "absent.sqlite"

    def publish(self):
        (self.data / (DAY + ".json")).write_text(
            json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
        self.archive.write_text(
            "<script>window.CHANLUN_BOOTSTRAP=" + json.dumps({
                "pageDate": DAY, "inlineReportData": self.report,
                "decisionWorkbench": self.workbench,
            }, ensure_ascii=False) + ";</script>", encoding="utf-8")
        with comparison_review_snapshot(self.workbench):
            write_comparison_index(str(self.data), str(self.db))

    def build(self):
        return build_selection_performance(
            self.data, self.db, DAY, NEXT + "T15:20:00+08:00")

    def cleanup_html(self):
        with mock.patch("chanlun.report_generator.HISTORY_DAYS", 1):
            update_data_json({"date": DAY}, output_dir=str(self.root))
            update_data_json({"date": NEXT}, output_dir=str(self.root))
        self.assertFalse(self.archive.exists())

    def test_theme_and_group_survive_actual_archive_retention_cleanup(self):
        self.publish()
        before = self.build()
        self.assertEqual(before["observations"][0]["theme_refs"][0]["theme_id"],
                         "kaipanla:ai")
        self.cleanup_html()
        after = self.build()
        self.assertEqual(after["observations"][0]["instrument_id"], "SH600001")
        self.assertEqual(after["observations"][0]["theme_refs"],
                         before["observations"][0]["theme_refs"])
        self.assertEqual(after["groups"]["themes"]["kaipanla:ai"]["horizons"]["t1"]
                         ["total_observations"], 1)

    def test_late_context_and_no_theme_never_invent_historical_membership(self):
        for context in ("late", "empty"):
            with self.subTest(context=context):
                if context == "late":
                    self.report["kaipanla_context"]["fetched_at"] = DAY + "T18:00:00+08:00"
                else:
                    self.report["kaipanla_context"]["fetched_at"] = DAY + "T14:00:00+08:00"
                    self.report["kaipanla_context"]["groups"] = []
                self.publish()
                self.assertEqual(self.build()["observations"][0]["theme_refs"], [])
                self.cleanup_html()
                self.assertEqual(self.build()["observations"][0]["theme_refs"], [])
                self.archive.parent.mkdir(exist_ok=True)

    def test_changed_member_receipt_invalidates_only_theme_context(self):
        self.publish()
        self.cleanup_html()
        path = self.data / "comparison-index.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(DAY, index["review_registry"]["published_theme_contexts"])
        receipt = index["review_registry"]["published_member_snapshots"][DAY]
        receipt["members"][0]["sources"][0]["score"] = 7
        receipt["content_sha256"] = _digest({
            key: value for key, value in receipt.items() if key != "content_sha256"
        })
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        loaded = load_published_observations(self.data, DAY)
        self.assertEqual(len(loaded["observations"]), 1)
        self.assertEqual(loaded["observations"][0]["theme_refs"], [])

    def test_corrupt_optional_theme_context_does_not_erase_published_member(self):
        self.publish()
        self.cleanup_html()
        path = self.data / "comparison-index.json"
        original = path.read_text(encoding="utf-8")
        for rehash in (False, True):
            with self.subTest(rehash=rehash):
                index = json.loads(original)
                context = index["review_registry"]["published_theme_contexts"][DAY]
                context["theme_refs_by_instrument"]["SH600001"][0]["name"] = "未来题材"
                if rehash:
                    context["content_sha256"] = _digest({
                        key: value for key, value in context.items()
                        if key != "content_sha256"
                    })
                path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
                loaded = load_published_observations(self.data, DAY)
                self.assertEqual(len(loaded["observations"]), 1)
                self.assertEqual(loaded["observations"][0]["theme_refs"], [])

    def test_resigned_late_theme_context_cannot_change_member_publication_time(self):
        self.report["kaipanla_context"]["fetched_at"] = DAY + "T18:00:00+08:00"
        self.publish()
        self.cleanup_html()
        path = self.data / "comparison-index.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        receipt = index["review_registry"]["published_member_snapshots"][DAY]
        self.assertEqual(receipt["binding"].get("publication_asof"),
                         DAY + "T15:20:00+08:00")
        context = index["review_registry"]["published_theme_contexts"][DAY]
        self.assertEqual(context["theme_refs_by_instrument"]["SH600001"], [])
        context["binding"]["publication_asof"] = DAY + "T18:30:00+08:00"
        context["theme_refs_by_instrument"]["SH600001"] = _theme_refs(
            self.report, context["binding"]["publication_asof"], "600001")
        self.assertEqual(len(context["theme_refs_by_instrument"]["SH600001"]), 1)
        context["content_sha256"] = _digest({
            key: value for key, value in context.items() if key != "content_sha256"
        })
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        loaded = load_published_observations(self.data, DAY)
        self.assertEqual(len(loaded["observations"]), 1)
        self.assertEqual(loaded["observations"][0]["theme_refs"], [])

    def test_legacy_or_invalid_member_time_keeps_members_but_cannot_restore_theme(self):
        self.publish()
        self.cleanup_html()
        path = self.data / "comparison-index.json"
        original = path.read_text(encoding="utf-8")
        for value in (None, "not-zoned"):
            with self.subTest(member_asof=value):
                index = json.loads(original)
                receipt = index["review_registry"]["published_member_snapshots"][DAY]
                if value is None:
                    receipt["binding"].pop("publication_asof", None)
                else:
                    receipt["binding"]["publication_asof"] = value
                receipt["content_sha256"] = _digest({
                    key: item for key, item in receipt.items()
                    if key != "content_sha256"
                })
                context = index["review_registry"]["published_theme_contexts"][DAY]
                context["binding"]["member_receipt_sha256"] = receipt["content_sha256"]
                context["content_sha256"] = _digest({
                    key: item for key, item in context.items()
                    if key != "content_sha256"
                })
                path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
                loaded = load_published_observations(self.data, DAY)
                self.assertEqual(len(loaded["observations"]), 1)
                self.assertEqual(loaded["observations"][0]["theme_refs"], [])

    def test_legacy_member_receipt_without_theme_context_stays_usable(self):
        self.publish()
        self.cleanup_html()
        path = self.data / "comparison-index.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        index["review_registry"].pop("published_theme_contexts", None)
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        loaded = load_published_observations(self.data, DAY)
        self.assertEqual(len(loaded["observations"]), 1)
        self.assertEqual(loaded["observations"][0]["theme_refs"], [])

    def test_revised_report_cannot_reuse_old_members_or_themes(self):
        self.publish()
        self.cleanup_html()
        path = self.data / (DAY + ".json")
        revised = json.loads(path.read_text(encoding="utf-8"))
        revised["kaipanla_context"]["groups"][0]["name"] = "新版题材"
        path.write_text(json.dumps(revised, ensure_ascii=False), encoding="utf-8")
        loaded = load_published_observations(self.data, DAY)
        self.assertEqual(loaded["observations"], [])
        self.assertEqual(loaded["coverage"]["unproven_report_dates"], 1)

    def test_saved_raw_response_enters_normal_builder_without_manual_series_file(self):
        self.publish()
        raw = json.dumps({"data": {"code": "600001", "market": 1,
                                   "klines": [
                                       DAY + ",10,10,11,9,100,1000,0,0,0,0",
                                       NEXT + ",11,11,12,10,100,1100,0,0,0,0",
                                   ]}}, separators=(",", ":")).encode()
        evidence = self.root / "selection-price-evidence"
        capture_eastmoney_historical_response(
            evidence, "SH600001", {"secid": "1.600001", "klt": "101", "fqt": "1",
                                     "beg": "20260803", "end": "20260804", "lmt": "2"},
            raw, fetched_at=NEXT + "T15:20:00+08:00")
        built = build_selection_performance(
            self.data, self.db, DAY, NEXT + "T15:20:00+08:00",
            price_evidence_dir=evidence,
        )
        self.assertEqual(built["summary"]["t1"]["counts"]["ready"], 1)
        self.assertAlmostEqual(built["observations"][0]["outcomes"]["t1"]["return_pct"], 10)
        self.assertEqual(built["coverage"]["verified_series_count"], 1)

    def test_later_price_proof_does_not_advance_frozen_price_cutoff(self):
        self.publish()
        fetched_at = "2026-08-05T15:20:00+08:00"
        evidence = self.root / "late-price-evidence"
        request = {"secid": "1.600001", "klt": "101", "fqt": "1",
                   "beg": "20260803", "end": "20260804", "lmt": "2"}
        raw = json.dumps({"data": {"code": "600001", "market": 1,
                                   "klines": [
                                       DAY + ",10,10,11,9,100,1000,0,0,0,0",
                                       NEXT + ",11,11,12,10,100,1100,0,0,0,0",
                                   ]}}, separators=(",", ":")).encode()
        capture_eastmoney_historical_response(
            evidence, "SH600001", request, raw, fetched_at=fetched_at)
        frozen_eval = NEXT + "T15:20:00+08:00"
        old_strict = build_selection_performance(
            self.data, self.db, DAY, frozen_eval, price_evidence_dir=evidence)
        self.assertEqual(old_strict["summary"]["t1"]["counts"]["ready"], 0)
        after_proof = build_selection_performance(
            self.data, self.db, DAY, frozen_eval, price_evidence_dir=evidence,
            price_evidence_as_of=fetched_at)
        self.assertEqual(after_proof["evaluation_as_of"], frozen_eval)
        self.assertEqual(after_proof["evidence_as_of"], fetched_at)
        self.assertEqual(after_proof["summary"]["t1"]["counts"]["ready"], 1)
        proof = after_proof["observations"][0]["outcomes"]["t1"]["price_evidence"]
        self.assertEqual(proof["fetched_at"], fetched_at)
        self.assertEqual(proof["raw_sha256"], hashlib.sha256(raw).hexdigest())
        repeated = build_selection_performance(
            self.data, self.db, DAY, frozen_eval, price_evidence_dir=evidence,
            price_evidence_as_of="2026-08-06T15:20:00+08:00")
        self.assertEqual(repeated["dataset_id"], after_proof["dataset_id"])
        self.assertEqual(repeated["evidence_as_of"], fetched_at)

        future_dir = self.root / "future-price-evidence"
        future_raw = json.dumps({"data": {"code": "600001", "market": 1,
                                          "klines": [
                                              DAY + ",10,10,11,9,100,1000,0,0,0,0",
                                              NEXT + ",11,11,12,10,100,1100,0,0,0,0",
                                              "2026-08-05,12,12,13,11,100,1200,0,0,0,0",
                                          ]}}, separators=(",", ":")).encode()
        capture_eastmoney_historical_response(
            future_dir, "SH600001", dict(request, end="20260805", lmt="3"),
            future_raw, fetched_at=fetched_at)
        future = build_selection_performance(
            self.data, self.db, DAY, frozen_eval, price_evidence_dir=future_dir,
            price_evidence_as_of=fetched_at)
        self.assertEqual(future["summary"]["t1"]["counts"]["ready"], 0)

    def test_decoder_source_change_invalidates_same_raw_proof_dataset(self):
        self.publish()
        evidence = self.root / "decoder-evidence"
        raw = json.dumps({"data": {"code": "600001", "market": 1,
                                   "klines": [
                                       DAY + ",10,10,11,9,100,1000,0,0,0,0",
                                       NEXT + ",11,11,12,10,100,1100,0,0,0,0",
                                   ]}}, separators=(",", ":")).encode()
        capture_eastmoney_historical_response(
            evidence, "SH600001", {"secid": "1.600001", "klt": "101", "fqt": "1",
                                     "beg": "20260803", "end": "20260804", "lmt": "2"},
            raw, fetched_at=NEXT + "T15:20:00+08:00")
        def build():
            return build_selection_performance(
                self.data, self.db, DAY, NEXT + "T15:20:00+08:00",
                price_evidence_dir=evidence)
        baseline = build()
        self.assertEqual(baseline["summary"]["t1"]["counts"]["ready"], 1)
        original_read_bytes = Path.read_bytes

        def changed_decoder(path):
            content = original_read_bytes(path)
            return (content + b"\n# changed decoder contract"
                    if path.name == "selection_price_evidence.py" else content)

        with mock.patch.object(Path, "read_bytes", changed_decoder):
            changed = build()
        self.assertEqual(changed["observations"], baseline["observations"])
        self.assertNotEqual(changed["dataset_id"], baseline["dataset_id"])

    def test_bound_receipt_mixed_incident_flows_to_source_aggregation(self):
        self.report["selection_input_health"] = {
            "schema_version": 2, "by_strategy": {
                "daily_fusion": {"status": "verified", "formal_actions_allowed": True},
            },
        }
        self.workbench["items"][0]["strategy_results"].insert(0, {
            "strategy_id": "main", "role": "formal",
            "candidate": {"strategy_version": "formal-v1"},
        })
        with mock.patch("chanlun.report_comparison._registered_incident_codes",
                        side_effect=lambda day, view: {"600001"} if view == "main" else set()):
            self.publish()
            self.cleanup_html()
            loaded = load_published_observations(self.data, DAY)
            row = loaded["observations"][0]
            self.assertEqual({ref["view"]: ref["formal_performance_status"]
                              for ref in row["strategy_refs"]},
                             {"main": "incident_excluded", "highlights": "review_only"})
            outcome = evaluate_observations(
                [row], [DAY, NEXT],
                {"SH600001": _series("SH600001", [DAY, NEXT], {1: 110})},
                NEXT + "T15:20:00+08:00")[0]
        by_view = {ref["view"]: ref["strategy_key"] for ref in outcome["strategy_refs"]}
        dataset = {"observations": [outcome]}
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, strategy_key=by_view["highlights"])["counts"]["ready"], 1)
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, strategy_key=by_view["main"])["counts"]["excluded"], 1)
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, recommendation_scope="formal_recommendation")
                         ["total_observations"], 0)


class SourceIncidentTests(unittest.TestCase):
    def make_observation(self, statuses):
        refs = [{"strategy_key": key, "view": key, "role": role,
                 "recommendation_scope": "formal_recommendation"
                 if role == "formal" and status == "formal_eligible"
                 else "published_observation",
                 "formal_performance_status": status}
                for key, role, status in statuses]
        return {"observation_id": "o:1", "instrument_id": "SH600001",
                "code": "600001", "name": "甲", "report_date": DAY,
                "strategy_refs": refs, "theme_refs": []}

    def test_source_incidents_keep_healthy_sources_without_reviving_formal(self):
        cases = [
            ([('bad-formal', 'formal', 'incident_excluded'),
              ('research', 'research', 'review_only')], 'ready',
             {'bad-formal': 'excluded', 'research': 'ready'}),
            ([('bad-formal', 'formal', 'incident_excluded'),
              ('good-formal', 'formal', 'formal_eligible')], 'ready',
             {'bad-formal': 'excluded', 'good-formal': 'ready'}),
            ([('bad-formal', 'formal', 'incident_excluded')], 'excluded',
             {'bad-formal': 'excluded'}),
            ([('good-formal', 'formal', 'formal_eligible')], 'ready',
             {'good-formal': 'ready'}),
        ]
        for sources, expected_global, expected_sources in cases:
            with self.subTest(sources=sources):
                row = self.make_observation(sources)
                result = evaluate_observations(
                    [row], [DAY, NEXT],
                    {"SH600001": _series("SH600001", [DAY, NEXT], {1: 110})},
                    NEXT + "T15:20:00+08:00")[0]
                self.assertEqual(result["outcomes"]["t1"]["status"], expected_global)
                for key, expected in expected_sources.items():
                    self.assertEqual(result["source_outcomes"][key]["t1"]["status"], expected)
                    summary = aggregate_selection_performance(
                        {"observations": [result]}, horizon=1, strategy_key=key)
                    self.assertEqual(summary["counts"][expected], 1)
                    if expected == "excluded":
                        self.assertIsNone(summary["mean_return_pct"])
                formal = aggregate_selection_performance(
                    {"observations": [result]}, horizon=1,
                    recommendation_scope="formal_recommendation")
                has_eligible_formal = any(s[1] == 'formal' and s[2] == 'formal_eligible'
                                          for s in sources)
                self.assertEqual(formal["counts"]["ready"], int(has_eligible_formal))

    def test_independent_responses_must_each_cover_both_endpoints(self):
        start = _series("SH600001", [DAY], {})
        target = _series("SH600001", [NEXT], {0: 110})
        result = evaluate_observations(
            [self.make_observation([('research', 'research', 'review_only')])],
            [DAY, NEXT], {"SH600001": [start, target]},
            NEXT + "T15:20:00+08:00")[0]["outcomes"]["t1"]
        self.assertNotEqual(result["status"], "ready")
        complete = _series("SH600001", [DAY, NEXT], {1: 110})
        result = evaluate_observations(
            [self.make_observation([('research', 'research', 'review_only')])],
            [DAY, NEXT], {"SH600001": [start, target, complete]},
            NEXT + "T15:20:00+08:00")[0]["outcomes"]["t1"]
        self.assertEqual(result["status"], "ready")

    def test_conflicting_complete_responses_fail_closed(self):
        first = _series("SH600001", [DAY, NEXT], {1: 110})
        second = _series("SH600001", [DAY, NEXT], {1: 120})
        row = self.make_observation([('research', 'research', 'review_only')])
        result = evaluate_observations(
            [row], [DAY, NEXT], {"SH600001": [first, second]},
            NEXT + "T15:20:00+08:00")[0]["outcomes"]["t1"]
        self.assertEqual(result["status"], "price_basis_unverified")
        self.assertEqual(result["reason_code"], "conflicting_verified_series")
        self.assertIsNone(result["return_pct"])

    def test_formal_scope_must_reject_same_ref_with_incident_even_if_forged(self):
        row = self.make_observation([('bad-formal', 'formal', 'incident_excluded')])
        row['strategy_refs'][0]['recommendation_scope'] = 'formal_recommendation'
        row['outcomes'] = {'t1': {'status': 'ready', 'return_pct': 10}}
        row['source_outcomes'] = {'bad-formal': {'t1': {
            'status': 'excluded', 'reason_code': 'registered_incident',
            'return_pct': None}}}
        dataset = {'observations': [row]}
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, role='formal')['total_observations'], 0)
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, recommendation_scope='formal_recommendation')
                         ['total_observations'], 0)

    def test_missing_new_source_outcome_fails_closed_and_clean_legacy_stays_readable(self):
        row = self.make_observation([('research', 'research', 'review_only')])
        row['outcomes'] = {'t1': {'status': 'ready', 'return_pct': 10}}
        for malformed in ({}, {'research': {}}):
            with self.subTest(malformed=malformed):
                broken = dict(row, source_outcomes=malformed)
                with self.assertRaises(ValueError):
                    aggregate_selection_performance(
                        {'observations': [broken]}, horizon=1,
                        strategy_key='research')
        self.assertEqual(aggregate_selection_performance(
            {'observations': [row]}, horizon=1, strategy_key='research')
                         ['counts']['ready'], 1)
        mixed_legacy = self.make_observation([
            ('bad-formal', 'formal', 'incident_excluded'),
            ('research', 'research', 'review_only'),
        ])
        mixed_legacy['outcomes'] = row['outcomes']
        with self.assertRaises(ValueError):
            aggregate_selection_performance(
                {'observations': [mixed_legacy]}, horizon=1,
                strategy_key='research')


if __name__ == "__main__":
    unittest.main()
