import copy
import json
from pathlib import Path
import tempfile
import unittest

from chanlun.nextday_public import PublicProjectionError, project_run, project_runs


REPORT_DATE = "2026-09-17"
ALGORITHM_VERSION = "nextday-strength-exploration-v0"
TARGET_DATES = {"t1": "2026-09-18", "t2": "2026-09-21", "t3": "2026-09-22"}


def candidate(identity, name, rank, method, report_date=REPORT_DATE):
    return {
        "report_date": report_date,
        "algorithm_version": ALGORITHM_VERSION,
        "instrument_id": identity,
        "stock_identity": identity,
        "identity": identity,
        "identity_details": {
            "asset_type": "stock",
            "exchange": identity[:2],
            "code": identity[2:],
        },
        "asset_type": "stock",
        "exchange": identity[:2],
        "code": identity[2:],
        "name": name,
        "research_rank": rank,
        "research_method": method,
        "source_pools": ["observation_watchlist", "startup_watchlist"],
        "sector": "汽车",
        "limit_sector": "汽车零部",
        "own_limit_sector_count": 8,
        "board_n": 1,
        "first_limit_time": "10:58",
        "risk_flags": ["涨幅过热"],
        "avoid_chase": True,
        "invalidation": ["跌破启动参考位"],
        "next_confirmation": ["回踩不破突破位"],
        "cancel_conditions": ["放量长阴破坏结构"],
        "next_day_conditions": ["次日等待回踩"],
        "upgrade_conditions": ["30min二买/三买"],
        "startup_date": REPORT_DATE,
        "startup_reason": "低位放量涨停",
        "watch_reason": "涨停当日不追，等待次日回踩确认",
        # These are deliberately present in the frozen source but forbidden in
        # the public projection.
        "reference_price": 3.6125,
        "f_change_pct": 10.15,
        "source_evidence": [{"private": "raw source detail"}],
        "source_views": ["internal-view"],
    }


def selection_for(l1=None, b0=None, report_date=REPORT_DATE):
    return {
        "schema_version": 1,
        "status": "research_only",
        "report_date": report_date,
        "algorithm_version": ALGORITHM_VERSION,
        "source_run_id": "20260917-aa5eaa7b7a0d",
        "freeze_status": "valid",
        "frozen_at": "2026-09-17T08:51:33Z",
        "registration_status": "prospective",
        "source_hash": "private-source-hash",
        "source_hashes": {"report_sha256": "private-report-hash"},
        "errors": ["private exception path /tmp/private"],
        "summary": {
            "candidate_count": 36,
            "snapshot_unique_count": 47,
            "candidate_snapshot_intersection": 13,
            "raw_candidate_count": 88,
            "archive_highlights_count": 3,
        },
        "l1": {
            "method": "L1_limit_sector",
            "status": "evaluated",
            "reason": "",
            "selected": l1 if l1 is not None else [
                candidate("SH600609", "金杯汽车", 1, "L1_limit_sector")
            ],
        },
        "b0": {
            "method": "B0_original_highlights",
            "status": "evaluated",
            "reason": "",
            "selected": b0 if b0 is not None else [
                candidate("SZ301075", "多瑞医药", 1, "B0_original_highlights")
            ],
        },
    }


def outcome_row(row, *, outcome_status="pending", metric_values=None):
    metric_values = metric_values or {}
    return {
        "selection": copy.deepcopy(row),
        "identity": row["instrument_id"],
        "report_date": row["report_date"],
        "identity_status": "valid",
        "selection_status": "unique",
        "outcome_status": outcome_status,
        "target_dates": dict(TARGET_DATES),
        "maturity_status": {"t1": "pending", "t2": "pending", "t3": "pending"},
        "bar_status": {"signal": "valid", "t1": "not_due", "t2": "not_due", "t3": "not_due"},
        "basis_status_by_metric": {
            "cc1": "pending",
            "gap1": "pending",
            "oc1": "within_bar_invariant",
            "oc2": "pending",
            "oc3": "pending",
        },
        "cc1": metric_values.get("cc1"),
        "gap1": metric_values.get("gap1"),
        "oc1": metric_values.get("oc1"),
        "oc2": metric_values.get("oc2"),
        "oc3": metric_values.get("oc3"),
        # Raw prices and source provenance must never be copied to public JSON.
        "signal_close": 3.61,
        "open1": 3.7,
        "close1": 3.8,
        "entry_one_price": True,
        "bar_provenance": {"signal": {"source_batch": "internal-batch"}},
    }


def outcomes_for(selection, *, as_of_date=REPORT_DATE, l1_rows=None, b0_rows=None):
    l1_selected = selection["l1"]["selected"]
    b0_selected = selection["b0"]["selected"]
    l1_rows = l1_rows if l1_rows is not None else [outcome_row(row) for row in l1_selected]
    b0_rows = b0_rows if b0_rows is not None else [outcome_row(row) for row in b0_selected]

    def group(rows, selected):
        observed = len([row for row in rows if row.get("cc1") is not None])
        return {
            "status": "research_only" if selected else "evaluated_empty",
            "report_date": selection["report_date"],
            "as_of_date": as_of_date,
            "selected": copy.deepcopy(selected),
            "outcome_rows": rows,
            "metrics": {
                "selected": len(selected),
                "observed_cc1": observed,
                "cc1_mean": 2.5 if observed else None,
                "cc1_median": 2.5 if observed else None,
                "nextday_gain_ge5": 1 if observed else 0,
                "nextday_loss_le_minus5": 0,
                "observed_gap1": 0,
                "gap1_mean": None,
                "observed_oc1": observed,
                "oc1_mean": 2.5 if observed else None,
                "oc1_median": 2.5 if observed else None,
                "open_close_gain_ge3": 1 if observed else 0,
                "open_close_loss_le_minus5": 0,
                "observed_oc2": 0,
                "oc2_mean": None,
                "observed_oc3": 0,
                "oc3_mean": None,
            },
        }

    return {
        "schema_version": 1,
        "report_date": selection["report_date"],
        "as_of_date": as_of_date,
        "refreshed_at": "2026-09-17T08:51:33Z",
        "l1": group(l1_rows, l1_selected),
        "b0": group(b0_rows, b0_selected),
    }


class PublicProjectionTests(unittest.TestCase):
    def test_legacy_research_only_group_without_freeze_fields_stays_unannotated(self):
        selection = selection_for()
        outcomes = outcomes_for(selection)
        self.assertEqual(outcomes["l1"]["status"], "research_only")
        self.assertNotIn("registration_status", outcomes["l1"])
        self.assertNotIn("frozen_at", outcomes["l1"])

        projected = project_run(selection, outcomes)

        self.assertNotIn("registration_status", projected["l1"])
        self.assertNotIn("frozen_at", projected["l1"])
        self.assertNotIn("registration_status", projected["outcomes"]["l1"])
        self.assertNotIn("frozen_at", projected["outcomes"]["l1"])

    def test_projects_group_registration_time_without_private_freeze_metadata(self):
        selection = selection_for()
        selection["registration_status"] = "retrospective"
        selection["group_freezes"] = {
            "l1": {
                "status": "evaluated",
                "registration_status": "prospective",
                "frozen_at": "2026-09-17T08:30:00Z",
                "source_hash": "private-l1-hash",
                "source_path": "/private/l1/selection.json",
            },
            "b0": {
                "status": "evaluated",
                "registration_status": "retrospective",
                "frozen_at": "2026-09-18T09:15:00Z",
                "source_hash": "private-b0-hash",
                "source_path": "/private/b0/selection.json",
            },
        }
        outcomes = outcomes_for(selection)
        outcomes["l1"].update({
            "registration_status": "prospective",
            "frozen_at": "2026-09-17T08:30:00Z",
        })
        outcomes["b0"].update({
            "registration_status": "retrospective",
            "frozen_at": "2026-09-18T09:15:00Z",
        })

        projected = project_run(selection, outcomes)

        self.assertEqual(projected["registration_status"], "historical")
        self.assertEqual(projected["l1"]["registration_status"], "prospective")
        self.assertEqual(projected["l1"]["frozen_at"], "2026-09-17T08:30:00Z")
        self.assertEqual(projected["b0"]["registration_status"], "historical")
        self.assertEqual(projected["b0"]["frozen_at"], "2026-09-18T09:15:00Z")
        self.assertEqual(projected["outcomes"]["b0"]["registration_status"], "historical")
        self.assertEqual(projected["outcomes"]["b0"]["frozen_at"], "2026-09-18T09:15:00Z")
        serialized = json.dumps(projected, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private-l1-hash", serialized)
        self.assertNotIn("private-b0-hash", serialized)
        self.assertNotIn("source_path", serialized)
        self.assertNotIn("/private/", serialized)

    def test_qfq_comparability_status_is_public_without_local_proof_metadata(self):
        selection = selection_for()
        l1_row = outcome_row(selection["l1"]["selected"][0], outcome_status="available")
        l1_row.update({
            "cc1": 2.5,
            "outcome_status": "available",
        })
        l1_row["basis_status_by_metric"]["cc1"] = "qfq_comparable"
        outcomes = outcomes_for(selection, l1_rows=[l1_row])

        projected = project_run(selection, outcomes)
        row = projected["outcomes"]["l1"]["outcome_rows"][0]
        self.assertEqual(row["path_metrics"]["cc1"]["status"], "observed")
        self.assertEqual(
            row["path_metrics"]["cc1"]["price_basis_status"], "qfq_comparable"
        )
        serialized = json.dumps(projected, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("basis_proof", serialized)
        self.assertNotIn("factor_vs_raw", serialized)

    def test_projects_whitelisted_public_fields_and_path_metrics(self):
        selection = selection_for()
        outcomes = outcomes_for(selection)
        projected = project_run(selection, outcomes)

        self.assertEqual(projected["schema_version"], "nextday-research-public-v1")
        self.assertEqual(projected["report_date"], REPORT_DATE)
        self.assertEqual(projected["source_run_id"], "20260917-aa5eaa7b7a0d")
        self.assertEqual(projected["summary"], {
            "candidate_count": 36,
            "snapshot_unique_count": 47,
            "candidate_snapshot_intersection": 13,
        })
        self.assertEqual(projected["status"], "available")
        self.assertNotIn("registration_status", projected["l1"])

        l1 = projected["l1"]["selected"][0]
        self.assertEqual(l1["stock_identity"], "SH600609")
        self.assertEqual(l1["rank"], 1)
        self.assertEqual(l1["method"], "L1_limit_sector")
        self.assertEqual(l1["source_pools"], ["observation_watchlist", "startup_watchlist"])
        self.assertEqual(l1["industry"], "汽车")
        self.assertEqual(l1["industry_count"], 8)
        self.assertTrue(l1["avoid_chase"])
        self.assertNotIn("reference_price", l1)

        metrics = projected["outcomes"]["l1"]["metrics"]
        self.assertEqual(metrics["selected"], 1)
        self.assertEqual(metrics["cc1"]["observed"], 0)
        self.assertIsNone(metrics["cc1"]["mean_pct"])
        self.assertEqual(metrics["oc1"]["gain_ge_3"], 0)
        row = projected["outcomes"]["l1"]["outcome_rows"][0]
        self.assertEqual(row["status"], "pending")
        self.assertTrue(row["entry_one_price"])
        self.assertEqual(row["target_dates"], TARGET_DATES)
        self.assertEqual(row["path_metrics"]["cc1"]["status"], "pending")
        self.assertEqual(row["path_metrics"]["oc1"]["price_basis_status"], "within_bar_invariant")
        self.assertIsNone(row["path_metrics"]["oc1"]["value_pct"])

        serialized = json.dumps(projected, ensure_ascii=False, sort_keys=True)
        for private_field in (
            "source_hash",
            "source_evidence",
            "source_views",
            "reference_price",
            "signal_close",
            "open1",
            "bar_provenance",
            "refreshed_at",
            "raw_candidate_count",
            "private exception path",
            "internal-batch",
        ):
            self.assertNotIn(private_field, serialized)

    def test_identical_frozen_inputs_have_identical_projection_bytes(self):
        selection = selection_for()
        outcomes = outcomes_for(selection)
        first = json.dumps(project_run(selection, outcomes), ensure_ascii=False, sort_keys=True)
        outcomes["refreshed_at"] = "2026-09-18T09:00:00Z"
        second = json.dumps(project_run(selection, outcomes), ensure_ascii=False, sort_keys=True)
        self.assertEqual(first, second)

    def test_evaluated_empty_stays_distinct_from_not_evaluated(self):
        selection = selection_for(l1=[], b0=[])
        outcomes = outcomes_for(selection)
        projected = project_run(selection, outcomes)

        self.assertEqual(projected["l1"]["status"], "evaluated")
        self.assertEqual(projected["l1"]["selected"], [])
        self.assertEqual(projected["outcomes"]["l1"]["status"], "evaluated")
        self.assertEqual(projected["outcomes"]["l1"]["metrics"]["selected"], 0)

        selection["l1"].update(status="not_evaluated", reason="raw input detail", selected=[])
        outcomes = outcomes_for(selection)
        projected = project_run(selection, outcomes)
        self.assertEqual(projected["l1"]["status"], "not_evaluated")
        self.assertEqual(projected["l1"]["selected"], [])
        self.assertNotEqual(projected["l1"]["reason"], "raw input detail")
        self.assertEqual(projected["outcomes"]["l1"]["status"], "not_evaluated")
        self.assertEqual(projected["status"], "partial")

    def test_missing_outcomes_marks_results_not_evaluated(self):
        projected = project_run(selection_for(), None)
        self.assertEqual(projected["status"], "partial")
        self.assertEqual(projected["l1"]["status"], "evaluated")
        self.assertEqual(projected["outcomes"]["l1"]["status"], "not_evaluated")
        self.assertEqual(projected["outcomes"]["l1"]["outcome_rows"], [])

    def test_unknown_selection_status_fails_closed_as_not_evaluated(self):
        selection = selection_for()
        selection["l1"].update(status="future_state", reason="private raw detail")
        projected = project_run(selection, outcomes_for(selection))
        self.assertEqual(projected["l1"]["status"], "not_evaluated")
        self.assertEqual(projected["l1"]["selected"], [])
        self.assertEqual(projected["status"], "partial")

    def test_date_mismatch_is_a_hard_projection_error(self):
        selection = selection_for()
        outcomes = outcomes_for(selection, as_of_date="2026-09-18")
        outcomes["report_date"] = "2026-09-16"
        with self.assertRaises(PublicProjectionError):
            project_run(selection, outcomes)

    def test_identity_mismatch_is_a_hard_projection_error(self):
        selection = selection_for()
        outcomes = outcomes_for(selection)
        outcomes["l1"]["outcome_rows"][0]["identity"] = "SH600610"
        with self.assertRaises(PublicProjectionError):
            project_run(selection, outcomes)

    def test_selection_identity_alias_conflict_is_a_hard_projection_error(self):
        selection = selection_for()
        selection["l1"]["selected"][0]["identity"] = "SH600610"
        with self.assertRaises(PublicProjectionError):
            project_run(selection, outcomes_for(selection))

    def test_project_runs_preserves_source_and_projects_matching_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary) / "runs"
            frozen = runs / REPORT_DATE
            frozen.mkdir(parents=True)
            selection = selection_for()
            outcomes = outcomes_for(selection)
            selection_bytes = json.dumps(selection, ensure_ascii=False).encode("utf-8")
            outcomes_bytes = json.dumps(outcomes, ensure_ascii=False).encode("utf-8")
            (frozen / "selection.json").write_bytes(selection_bytes)
            (frozen / "outcomes.json").write_bytes(outcomes_bytes)

            projected, errors = project_runs(runs)

            self.assertEqual(list(projected), [REPORT_DATE])
            self.assertEqual(errors, [])
            self.assertEqual((frozen / "selection.json").read_bytes(), selection_bytes)
            self.assertEqual((frozen / "outcomes.json").read_bytes(), outcomes_bytes)

    def test_file_date_mismatch_is_summarized_and_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            date_dir = Path(temporary) / "2026-09-18"
            date_dir.mkdir()
            selection = selection_for()
            (date_dir / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
            (date_dir / "outcomes.json").write_text(json.dumps(outcomes_for(selection)), encoding="utf-8")
            projected, errors = project_runs(Path(temporary))
            self.assertEqual(projected, {})
            self.assertEqual(errors, [{"report_date": "2026-09-18", "status": "source_unavailable"}])

    def test_bad_historical_date_does_not_block_a_healthy_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary)
            good_date = "2026-09-17"
            bad_date = "2026-09-18"
            good_selection = selection_for()
            good = runs / good_date
            good.mkdir()
            (good / "selection.json").write_text(json.dumps(good_selection), encoding="utf-8")
            (good / "outcomes.json").write_text(json.dumps(outcomes_for(good_selection)), encoding="utf-8")

            bad_selection = selection_for(
                l1=[candidate("SH600610", "测试标的", 1, "L1_limit_sector", report_date=bad_date)],
                b0=[],
                report_date=bad_date,
            )
            bad = runs / bad_date
            bad.mkdir()
            (bad / "selection.json").write_text(json.dumps(bad_selection), encoding="utf-8")
            bad_outcomes = outcomes_for(bad_selection, as_of_date=bad_date)
            bad_outcomes["report_date"] = good_date
            (bad / "outcomes.json").write_text(json.dumps(bad_outcomes), encoding="utf-8")

            projected, errors = project_runs(runs)

            self.assertEqual(set(projected), {good_date})
            self.assertEqual(errors, [{"report_date": bad_date, "status": "source_unavailable"}])


if __name__ == "__main__":
    unittest.main()
