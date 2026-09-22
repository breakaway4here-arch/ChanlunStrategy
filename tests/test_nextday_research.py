import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.nextday_candidates import load_rows, select_day
from chanlun.nextday_outcomes import evaluate_frozen_selection
from chanlun.nextday_research import (
    _source_lists,
    adapt_report,
    freeze_selection,
    process_report,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "research" / "nextday-strength-v0" / "source-package"
REPORT_DATE = "2026-09-17"


def _snapshot(items, date=REPORT_DATE, status="verified_complete"):
    count = len(items)
    return {
        "status": status,
        "date": date,
        "as_of": date + "T15:00:00+08:00",
        "raw_total": count,
        "parsed_count": count,
        "parse_error_count": 0,
        "coverage": 1.0,
        "items": items,
    }


def _limit_row(code, name, sector="测试行业", board=1, first_time="09:31"):
    return {
        "code": code,
        "name": name,
        "sector": sector,
        "lianban": board,
        "first_time": first_time,
    }


def _candidate(code="600609", name="金杯汽车", **fields):
    row = {"code": code, "name": name, "change_pct": 5.5, "sector": "测试行业"}
    row.update(fields)
    return row


def _report(candidates=None, snapshot=None):
    return {
        "date": REPORT_DATE,
        "picks_pure": list(candidates or []),
        "picks_fusion": [],
        "startup_watchlist": [],
        "observation_watchlist": [],
        "next_day_boom": {"candidates": []},
        "luojie_pool": {"candidates": []},
        "h4_t3_pool": {"candidates": []},
        "workspace": {"views": {}},
        "limit_up_snapshot": snapshot if snapshot is not None else _snapshot([]),
    }


def _archived_workbench(candidates):
    items = []
    for rank, candidate in enumerate(candidates, 1):
        items.append(
            {
                "code": candidate.get("code"),
                "name": candidate.get("name"),
                "candidate": candidate,
                "strategy_results": [
                    {"strategy_id": "highlights", "view_rank": rank}
                ],
            }
        )
    return {
        "identity_matches": True,
        "workbench": {"report_date": REPORT_DATE, "items": items},
    }


def _with_report_identity(prepared, identity="a" * 64):
    prepared["report_identity"] = identity
    return prepared


def _create_outcome_database(path, rows):
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE instruments (
            instrument_id INTEGER PRIMARY KEY,
            asset_type TEXT NOT NULL,
            exchange TEXT NOT NULL,
            code TEXT NOT NULL
        );
        CREATE TABLE trade_calendar (
            exchange TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            is_open INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE bars_day (
            instrument_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            adjustment TEXT,
            is_final INTEGER,
            source_batch TEXT,
            updated_at TEXT
        );
        """
    )
    for instrument_id, row in enumerate(rows, 1):
        identity = row["identity_details"]
        connection.execute(
            "INSERT INTO instruments VALUES (?, ?, ?, ?)",
            (
                instrument_id,
                identity["asset_type"],
                identity["exchange"],
                identity["code"],
            ),
        )
    connection.commit()
    connection.close()


class NextdayResearchTests(unittest.TestCase):
    def test_research_observation_projection_is_excluded_from_l1_sources(self):
        report = _report()
        projected = _candidate(
            "002845",
            "同兴达",
            eligible_for_l1_v0=False,
            research_observation_projection=True,
            affects_formal=False,
        )
        report["observation_watchlist"] = [projected]
        report["workspace"]["views"] = {
            "observation_top5": [dict(projected)],
        }

        pool_rows, view_rows, errors = _source_lists(report)

        self.assertFalse(errors)
        self.assertNotIn("002845", [row.get("code") for _, row in pool_rows])
        self.assertNotIn("002845", [row.get("code") for _, row in view_rows])

    def test_vendor_l1_selection_preserves_all_25_day_identity_order(self):
        signals = load_rows(PACKAGE / "data" / "signal_features.jsonl.gz")
        with gzip.open(
            str(PACKAGE / "results" / "selected_before_outcomes.json.gz"),
            "rt",
            encoding="utf-8",
        ) as handle:
            expected = json.load(handle)["L1_limit_sector"]
        dates = sorted({row["report_date"] for row in signals})
        expected_by_date = {}
        for row in expected:
            expected_by_date.setdefault(row["report_date"], []).append(
                row["instrument_id"]
            )
        self.assertEqual(len(dates), 25)
        self.assertTrue(set(expected_by_date).issubset(set(dates)))
        for date in dates:
            with self.subTest(date=date):
                selected = select_day(signals, date, "L1_limit_sector", 5)
                self.assertEqual(
                    [row["instrument_id"] for row in selected],
                    expected_by_date.get(date, []),
                )

    def test_candidate_union_deduplicates_identity_and_merges_source_labels(self):
        candidate = _candidate(cancel_conditions=["跌破启动参考位"])
        report = _report([candidate], _snapshot([_limit_row("600609", "金杯汽车")]))
        report["startup_watchlist"] = [dict(candidate)]
        report["workspace"]["views"]["main"] = [dict(candidate)]

        prepared = adapt_report(report)
        self.assertEqual(prepared["freeze_status"], "valid")
        self.assertEqual(prepared["summary"]["candidate_count"], 1)
        row = prepared["normalized_candidates"][0]
        self.assertEqual(row["instrument_id"], "SH600609")
        self.assertEqual(row["source_pools"], ["picks_pure", "startup_watchlist"])
        self.assertEqual(row["source_views"], ["main"])
        self.assertEqual(row["cancel_conditions"], ["跌破启动参考位"])
        self.assertEqual([item["instrument_id"] for item in prepared["l1"]["selected"]], ["SH600609"])

    def test_sector_counts_use_unique_full_snapshot_not_candidate_intersection(self):
        items = [
            _limit_row("600609", "金杯汽车", "汽车零部"),
            _limit_row("603960", "克来机电", "汽车零部"),
            _limit_row("600293", "三峡新材", "玻璃玻纤"),
            _limit_row("603248", "锡华科技", "汽车零部"),
        ]
        report = _report([_candidate()], _snapshot(items))
        prepared = adapt_report(report)
        row = prepared["normalized_candidates"][0]
        self.assertEqual(prepared["summary"]["snapshot_unique_count"], 4)
        self.assertEqual(prepared["summary"]["candidate_snapshot_intersection"], 1)
        self.assertEqual(row["own_limit_sector_count"], 3)

    def test_duplicate_identity_in_snapshot_cannot_claim_complete_coverage(self):
        items = [
            _limit_row("600609", "金杯汽车", "汽车零部"),
            _limit_row("603960", "克来机电", "汽车零部"),
            _limit_row("603960", "克来机电", "汽车零部"),
        ]
        prepared = adapt_report(_report([_candidate()], _snapshot(items)))
        self.assertEqual(prepared["freeze_status"], "input_insufficient")
        self.assertEqual(prepared["l1"]["status"], "not_evaluated")

    def test_partial_snapshot_membership_stays_unknown(self):
        snapshot = _snapshot([_limit_row("600609", "金杯汽车")])
        snapshot["status"] = "partial"
        prepared = adapt_report(_report([_candidate()], snapshot))
        self.assertIsNone(prepared["normalized_candidates"][0]["in_limit_snapshot"])
        self.assertIsNone(prepared["summary"]["snapshot_unique_count"])
        self.assertIsNone(prepared["summary"]["candidate_snapshot_intersection"])

    def test_verified_empty_snapshot_is_valid_and_selects_no_candidates(self):
        snapshot = {
            "status": "verified_empty",
            "date": REPORT_DATE,
            "as_of": REPORT_DATE + "T15:00:00+08:00",
            "raw_total": 0,
            "parsed_count": 0,
            "parse_error_count": 0,
            "items": [],
        }
        prepared = adapt_report(_report([_candidate()], snapshot))
        self.assertEqual(prepared["freeze_status"], "valid")
        self.assertEqual(prepared["l1"]["status"], "evaluated")
        self.assertEqual(prepared["l1"]["selected"], [])
        self.assertEqual(prepared["summary"]["snapshot_unique_count"], 0)

    def test_inconsistent_empty_snapshot_is_not_evaluated(self):
        snapshot = {
            "status": "verified_empty",
            "date": REPORT_DATE,
            "as_of": REPORT_DATE + "T15:00:00+08:00",
            "raw_total": 1,
            "parsed_count": 0,
            "parse_error_count": 0,
            "items": [],
        }
        prepared = adapt_report(_report([_candidate()], snapshot))
        self.assertEqual(prepared["freeze_status"], "input_insufficient")
        self.assertEqual(prepared["l1"]["status"], "not_evaluated")

    def test_partial_or_wrong_date_snapshot_is_not_evaluated(self):
        cases = (
            dict(status="partial"),
            dict(date="2026-09-16"),
            dict(as_of="2026-09-16T15:00:00+08:00"),
            dict(parse_error_count=1),
        )
        for change in cases:
            with self.subTest(change=change):
                snapshot = _snapshot([_limit_row("600609", "金杯汽车")])
                snapshot.update(change)
                prepared = adapt_report(_report([_candidate()], snapshot))
                self.assertEqual(prepared["l1"]["status"], "not_evaluated")

    def test_missing_sector_and_string_board_are_not_invented_or_coerced(self):
        snapshot = _snapshot([_limit_row("600609", "金杯汽车", "   ", "2", "09:31")])
        report = _report([_candidate(change_pct=None)], snapshot)
        prepared = adapt_report(report)
        row = prepared["normalized_candidates"][0]
        self.assertIsNone(row["limit_sector"])
        self.assertIsNone(row["own_limit_sector_count"])
        self.assertEqual(row["board_n"], "2")
        self.assertEqual(row["first_limit_time"], "09:31")
        self.assertIsNone(row["f_change_pct"])
        self.assertEqual(prepared["l1"]["selected"], [])

    def test_identity_conflict_fails_closed(self):
        row = _candidate()
        row["identity"] = {"asset_type": "stock", "exchange": "SZ", "code": "600609"}
        report = _report([row], _snapshot([_limit_row("600609", "金杯汽车")]))
        prepared = adapt_report(report)
        self.assertEqual(prepared["freeze_status"], "input_insufficient")
        self.assertEqual(prepared["l1"]["status"], "not_evaluated")
        self.assertTrue(prepared["errors"])

    def test_declared_instrument_id_must_match_code_identity(self):
        row = _candidate()
        row["instrument_id"] = "SZ000504"
        report = _report([row], _snapshot([_limit_row("600609", "金杯汽车")]))
        prepared = adapt_report(report)
        self.assertEqual(prepared["freeze_status"], "input_insufficient")
        self.assertIn("identity", " ".join(prepared["errors"]))

    def test_display_name_variants_do_not_reject_same_security(self):
        first = _candidate(name="金杯汽车")
        second = _candidate(name="金杯汽车（更名）")
        report = _report([first], _snapshot([_limit_row("600609", "金杯汽车")]))
        report["startup_watchlist"] = [second]
        prepared = adapt_report(report)
        self.assertEqual(prepared["freeze_status"], "valid")
        self.assertEqual(prepared["l1"]["selected"][0]["name"], "金杯汽车")
        self.assertEqual(
            prepared["l1"]["selected"][0]["name_variants"],
            ["金杯汽车", "金杯汽车（更名）"],
        )

    def test_required_pool_schema_cannot_be_claimed_as_empty_universe(self):
        report = _report([], _snapshot([]))
        report.pop("startup_watchlist")
        prepared = adapt_report(report)
        self.assertEqual(prepared["freeze_status"], "input_insufficient")
        self.assertEqual(prepared["l1"]["status"], "not_evaluated")

    def test_b0_uses_matching_archive_and_strategy_view_rank(self):
        report = _report([], _snapshot([]))
        report["workspace"]["views"]["highlights"] = [_candidate("688521", "芯原股份")]
        archived = {
            "identity_matches": True,
            "workbench": {
                "report_date": REPORT_DATE,
                "items": [
                    {
                        "code": "688521",
                        "name": "芯原股份",
                        "candidate": _candidate("688521", "芯原股份"),
                        "strategy_results": [{"strategy_id": "highlights", "view_rank": 3}],
                    },
                    {
                        "code": "603960",
                        "name": "克来机电",
                        "candidate": _candidate("603960", "克来机电"),
                        "strategy_results": [{"strategy_id": "highlights", "view_rank": 2}],
                    },
                    {
                        "code": "301075",
                        "name": "多瑞医药",
                        "candidate": _candidate("301075", "多瑞医药"),
                        "strategy_results": [{"strategy_id": "highlights", "view_rank": 1}],
                    },
                ],
            },
        }
        prepared = adapt_report(report, archived_workbench=archived)
        self.assertEqual(prepared["b0"]["status"], "evaluated")
        self.assertEqual(
            [(row["code"], row["highlight_rank"]) for row in prepared["b0"]["selected"]],
            [("301075", 1), ("603960", 2), ("688521", 3)],
        )

        mismatch = dict(archived, identity_matches=False)
        no_baseline = adapt_report(report, archived_workbench=mismatch)
        self.assertEqual(no_baseline["b0"]["status"], "not_evaluated")
        self.assertEqual(no_baseline["b0"]["selected"], [])

        conflicting_item = copy_archive = json.loads(json.dumps(archived))
        conflicting_item["workbench"]["items"][0]["code"] = "600609"
        conflicting = adapt_report(report, archived_workbench=conflicting_item)
        self.assertEqual(conflicting["b0"]["status"], "not_evaluated")

    def test_archive_only_comparator_row_does_not_widen_l1_universe(self):
        report = _report(
            [],
            _snapshot([_limit_row("603960", "克来机电", "汽车零部", 1, "14:17")]),
        )
        archived = {
            "identity_matches": True,
            "workbench": {
                "report_date": REPORT_DATE,
                "items": [
                    {
                        "code": "603960",
                        "name": "克来机电",
                        "candidate": _candidate("603960", "克来机电"),
                        "strategy_results": [{"strategy_id": "highlights", "view_rank": 1}],
                    }
                ],
            },
        }
        prepared = adapt_report(report, archived_workbench=archived)
        self.assertEqual(prepared["l1"]["status"], "evaluated")
        self.assertEqual(prepared["l1"]["selected"], [])
        self.assertEqual(prepared["summary"]["candidate_count"], 0)
        self.assertEqual(
            [row["instrument_id"] for row in prepared["b0"]["selected"]],
            ["SH603960"],
        )

    def test_future_noise_and_personal_views_are_excluded(self):
        report = _report([_candidate()], _snapshot([_limit_row("600609", "金杯汽车")]))
        report["personal_watchlist"] = [_candidate("000001", "个人自选")]
        report["globalhotspot"] = [_candidate("000002", "全市场热点")]
        report["shadow_watch330"] = [_candidate("000003", "隐藏审计项")]
        report["workspace"]["views"].update(
            {
                "holdings": [_candidate("000004", "持仓")],
                "personal_watchlist": [_candidate("000005", "个人观察")],
                "globalhotspot": [_candidate("000006", "热点")],
                "shadow_watch330": [_candidate("000007", "审计影子")],
            }
        )
        report["future_unrelated_field"] = {"secret": "must not be copied"}
        prepared = adapt_report(report)
        self.assertEqual([row["code"] for row in prepared["normalized_candidates"]], ["600609"])
        self.assertNotIn("future_unrelated_field", prepared["normalized_candidates"][0])

    def test_future_candidate_fields_do_not_change_l1_identity_order(self):
        candidates = [
            _candidate("600609", "金杯汽车", score=999999, volume_ratio=9000, outcomes={"cc1": 999}),
            _candidate("603960", "克来机电", score=-999999, volume_ratio=0, outcomes={"cc1": -999}),
        ]
        snapshot = _snapshot(
            [
                _limit_row("600609", "金杯汽车", "汽车零部", 1, "10:58"),
                _limit_row("603960", "克来机电", "汽车零部", 1, "14:17"),
            ]
        )
        prepared = adapt_report(_report(candidates, snapshot))
        self.assertEqual(
            [row["instrument_id"] for row in prepared["l1"]["selected"]],
            ["SH600609", "SH603960"],
        )
        self.assertNotIn("outcomes", prepared["normalized_candidates"][0])
        self.assertNotIn("score", prepared["normalized_candidates"][0])

    def test_freeze_is_idempotent_and_changed_valid_source_cannot_replace(self):
        report = _report([_candidate()], _snapshot([_limit_row("600609", "金杯汽车")]))
        prepared = adapt_report(report)
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            first = freeze_selection(runs, prepared, source_hash="source-a", frozen_at="2026-09-17T00:00:00Z")
            frozen_path = runs / REPORT_DATE / "selection.json"
            original = frozen_path.read_text(encoding="utf-8")
            same = freeze_selection(runs, prepared, source_hash="source-a", frozen_at="2026-09-17T00:01:00Z")
            self.assertEqual(first["action"], "created")
            self.assertEqual(same["action"], "unchanged")
            self.assertEqual(frozen_path.read_text(encoding="utf-8"), original)

            changed = freeze_selection(runs, prepared, source_hash="source-b", frozen_at="2026-09-17T00:02:00Z")
            self.assertEqual(changed["action"], "conflict")
            self.assertEqual(frozen_path.read_text(encoding="utf-8"), original)
            self.assertTrue(list((runs / REPORT_DATE / "conflicts").glob("*.json")))

    def test_input_insufficient_attempt_can_upgrade_once_to_valid_freeze(self):
        partial = _snapshot([_limit_row("600609", "金杯汽车")])
        partial["status"] = "partial"
        invalid = _with_report_identity(adapt_report(_report([_candidate()], partial)))
        valid = _with_report_identity(
            adapt_report(_report([_candidate()], _snapshot([_limit_row("600609", "金杯汽车")]))),
        )
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            first = freeze_selection(runs, invalid, source_hash="partial-source")
            upgraded = freeze_selection(runs, valid, source_hash="valid-source")
            saved = json.loads((runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(first["action"], "created")
            self.assertEqual(upgraded["action"], "upgraded")
            self.assertEqual(saved["freeze_status"], "valid")
            self.assertEqual(saved["source_hash"], "valid-source")

    def test_l1_fill_preserves_evaluated_b0_a_and_records_conflict_for_b0_b(self):
        partial = _snapshot([_limit_row("600609", "金杯汽车")])
        partial["status"] = "partial"
        first = _with_report_identity(
            adapt_report(
                _report([_candidate()], partial),
                archived_workbench=_archived_workbench([_candidate("600609", "B0_A")]),
            )
        )
        valid = _with_report_identity(
            adapt_report(
                _report([_candidate()], _snapshot([_limit_row("600609", "金杯汽车")])),
                archived_workbench=_archived_workbench([_candidate("603960", "B0_B")]),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            freeze_selection(runs, first, "partial", frozen_at="2026-09-17T08:00:00Z")
            path = runs / REPORT_DATE / "selection.json"
            original = json.loads(path.read_text(encoding="utf-8"))
            original_b0 = original["b0"]
            original_b0_freeze = original["group_freezes"]["b0"]

            result = freeze_selection(
                runs, valid, "completed", frozen_at="2026-09-18T08:00:00Z"
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(result["action"], "upgraded_with_conflict")
            self.assertEqual(saved["l1"]["status"], "evaluated")
            self.assertEqual(saved["b0"], original_b0)
            self.assertEqual(saved["group_freezes"]["b0"], original_b0_freeze)
            self.assertEqual(saved["group_freezes"]["b0"]["status"], "evaluated")
            self.assertEqual(saved["group_freezes"]["b0"]["registration_status"], "prospective")
            self.assertEqual(saved["group_freezes"]["l1"]["registration_status"], "retrospective")
            self.assertEqual(saved["registration_status"], "retrospective")
            self.assertIn("conflict_path", result)
            self.assertTrue(Path(result["conflict_path"]).is_file())

    def test_b0_same_report_first_fill_preserves_frozen_l1_and_marks_late_registration(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        first = _with_report_identity(adapt_report(report))
        completed = _with_report_identity(
            adapt_report(
                report,
                archived_workbench=_archived_workbench([_candidate("603960", "克来机电")]),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            freeze_selection(runs, first, "report-and-missing-archive", frozen_at="2026-09-17T08:00:00Z")
            path = runs / REPORT_DATE / "selection.json"
            original = json.loads(path.read_text(encoding="utf-8"))
            original_l1 = original["l1"]
            original_l1_freeze = original["group_freezes"]["l1"]

            result = freeze_selection(
                runs,
                completed,
                "report-and-archive-assets-v2",
                frozen_at="2026-09-18T08:00:00Z",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(result["action"], "upgraded")
            self.assertEqual(saved["l1"], original_l1)
            self.assertEqual(saved["group_freezes"]["l1"], original_l1_freeze)
            self.assertEqual(saved["b0"]["status"], "evaluated")
            self.assertEqual(saved["group_freezes"]["b0"]["frozen_at"], "2026-09-18T08:00:00Z")
            self.assertEqual(saved["group_freezes"]["b0"]["registration_status"], "retrospective")
            self.assertEqual(saved["registration_status"], "retrospective")

    def test_process_keeps_legacy_conflict_status_when_safe_group_fills(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        archived = _archived_workbench([_candidate("600609", "金杯汽车")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            runs = root / "runs"

            def fake_evaluator(snapshot, db_path, as_of_date):
                return {
                    "status": "pending",
                    "report_date": snapshot["report_date"],
                    "as_of_date": as_of_date,
                    "outcome_rows": [],
                    "metrics": {"selected": len(snapshot["selected"])},
                }

            with mock.patch(
                "chanlun.nextday_research._read_archived_workbench",
                side_effect=[
                    (None, None, "matching_archived_workbench_missing"),
                    (archived, "same-report-workbench", None),
                ],
            ):
                process_report(
                    report_path,
                    runs,
                    root / "unused.db",
                    as_of_date=REPORT_DATE,
                    outcome_evaluator=fake_evaluator,
                    frozen_at="2026-09-17T08:00:00Z",
                )
                before = json.loads(
                    (runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8")
                )
                second = process_report(
                    report_path,
                    runs,
                    root / "unused.db",
                    as_of_date=REPORT_DATE,
                    outcome_evaluator=fake_evaluator,
                    frozen_at="2026-09-18T08:00:00Z",
                )

            saved = json.loads((runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(second["status"], "conflict")
            self.assertEqual(second["freeze_action"], "upgraded_with_conflict")
            self.assertTrue(Path(second["conflict_path"]).is_file())
            self.assertEqual(saved["l1"], before["l1"])
            self.assertEqual(saved["group_freezes"]["l1"], before["group_freezes"]["l1"])
            self.assertEqual(saved["b0"]["status"], "evaluated")
            self.assertEqual(saved["group_freezes"]["b0"]["registration_status"], "retrospective")

    def test_both_insufficient_groups_can_first_freeze_from_same_report_bytes(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        report["data_quality"] = {
            "report_date": REPORT_DATE,
            "bar_state": "closed",
            "is_official": True,
        }
        archived = _archived_workbench([_candidate("600609", "金杯汽车")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            original_report_bytes = report_path.read_bytes()
            runs = root / "runs"

            def fake_evaluator(snapshot, db_path, as_of_date):
                return {
                    "status": "pending",
                    "report_date": snapshot["report_date"],
                    "as_of_date": as_of_date,
                    "outcome_rows": [],
                    "metrics": {"selected": len(snapshot["selected"])},
                }

            with mock.patch(
                "chanlun.nextday_research._read_archived_workbench",
                side_effect=[
                    (None, None, "matching_archived_workbench_missing"),
                    (archived, "asset-query-v2", None),
                ],
            ):
                first = process_report(
                    report_path,
                    runs,
                    root / "unused.db",
                    as_of_date="2026-09-16",
                    outcome_evaluator=fake_evaluator,
                    frozen_at="2026-09-17T08:00:00Z",
                )
                first_saved = json.loads(
                    (runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8")
                )
                second = process_report(
                    report_path,
                    runs,
                    root / "unused.db",
                    as_of_date=REPORT_DATE,
                    outcome_evaluator=fake_evaluator,
                    frozen_at="2026-09-18T08:00:00Z",
                )

            saved = json.loads((runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8"))
            summary = json.loads((runs / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(report_path.read_bytes(), original_report_bytes)
            self.assertEqual(first["status"], "not_evaluated")
            self.assertEqual(first_saved["l1"]["status"], "not_evaluated")
            self.assertEqual(first_saved["b0"]["status"], "not_evaluated")
            self.assertEqual(second["freeze_action"], "upgraded")
            self.assertEqual(second["status"], "processed")
            self.assertEqual(saved["l1"]["status"], "evaluated")
            self.assertEqual(saved["b0"]["status"], "evaluated")
            self.assertEqual(saved["group_freezes"]["l1"]["report_identity"], saved["report_identity"])
            self.assertEqual(saved["group_freezes"]["b0"]["report_identity"], saved["report_identity"])
            self.assertEqual(second["l1_registration_status"], "retrospective")
            self.assertEqual(second["b0_registration_status"], "retrospective")
            self.assertEqual(second["registration_status"], "retrospective")
            self.assertEqual(summary["dates"][0]["l1_registration_status"], "retrospective")
            self.assertEqual(summary["dates"][0]["b0_registration_status"], "retrospective")

    def test_initial_no_valid_group_can_recover_from_strong_new_report_identity(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        initial = adapt_report(report)
        initial["freeze_status"] = "input_insufficient"
        initial["l1"] = {"status": "not_evaluated", "reason": "initial_input_missing", "selected": []}
        initial["b0"] = {"status": "not_evaluated", "reason": "archive_missing", "selected": []}
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            freeze_selection(runs, initial, "legacy-failed-attempt", frozen_at="2026-09-17T08:00:00Z")
            completed = _with_report_identity(
                adapt_report(
                    report,
                    archived_workbench=_archived_workbench([_candidate("600609", "金杯汽车")]),
                ),
                "c" * 64,
            )
            result = freeze_selection(
                runs, completed, "strong-current-report", frozen_at="2026-09-18T08:00:00Z"
            )
            saved = json.loads(
                (runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result["action"], "upgraded")
            self.assertEqual(saved["report_identity"], "c" * 64)
            self.assertEqual(saved["l1"]["status"], "evaluated")
            self.assertEqual(saved["b0"]["status"], "evaluated")
            for group in ("l1", "b0"):
                self.assertEqual(saved["group_freezes"][group]["first_attempted_at"], "2026-09-17T08:00:00Z")
                self.assertEqual(saved["group_freezes"][group]["frozen_at"], "2026-09-18T08:00:00Z")
                self.assertIsNone(saved["group_freezes"][group]["supersedes"]["report_identity"])
            self.assertEqual(saved["first_attempted_at"], "2026-09-17T08:00:00Z")
            self.assertEqual(saved["registration_status"], "retrospective")

    def test_registration_uses_shanghai_trading_date_not_utc_date(self):
        prepared = _with_report_identity(
            adapt_report(
                _report(
                    [_candidate("600609", "金杯汽车")],
                    _snapshot([_limit_row("600609", "金杯汽车")]),
                ),
                archived_workbench=_archived_workbench([_candidate("600609", "金杯汽车")]),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            freeze_selection(
                runs, prepared, "source-before-china-midnight", frozen_at="2026-09-17T15:59:00Z"
            )
            before = json.loads((runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(before["registration_status"], "prospective")
            self.assertEqual(before["group_freezes"]["l1"]["registration_status"], "prospective")

            next_runs = Path(tmp) / "next"
            freeze_selection(
                next_runs, prepared, "source-after-china-midnight", frozen_at="2026-09-17T16:30:00Z"
            )
            after = json.loads(
                (next_runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8")
            )
            self.assertEqual(after["registration_status"], "retrospective")
            self.assertEqual(after["group_freezes"]["b0"]["registration_status"], "retrospective")

    def test_revised_or_unknown_report_identity_cannot_fill_a_missing_group(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        for incoming_identity in ("b" * 64, None):
            with self.subTest(incoming_identity=incoming_identity):
                first = _with_report_identity(adapt_report(report), "a" * 64)
                completed = _with_report_identity(
                    adapt_report(
                        report,
                        archived_workbench=_archived_workbench([_candidate("600609", "金杯汽车")]),
                    ),
                    incoming_identity or "a" * 64,
                )
                if incoming_identity is None:
                    completed.pop("report_identity", None)
                with tempfile.TemporaryDirectory() as tmp:
                    runs = Path(tmp)
                    freeze_selection(runs, first, "first-source", frozen_at="2026-09-17T08:00:00Z")
                    path = runs / REPORT_DATE / "selection.json"
                    before = path.read_bytes()
                    result = freeze_selection(
                        runs, completed, "revised-or-unknown", frozen_at="2026-09-18T08:00:00Z"
                    )
                    self.assertEqual(result["action"], "conflict")
                    self.assertEqual(path.read_bytes(), before)

    def test_changed_algorithm_or_group_method_cannot_mix_freeze_versions(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        for changed_contract in ("algorithm", "l1_method", "b0_method"):
            with self.subTest(changed_contract=changed_contract):
                first = _with_report_identity(adapt_report(report), "d" * 64)
                completed = _with_report_identity(
                    adapt_report(
                        report,
                        archived_workbench=_archived_workbench([_candidate("603960", "克来机电")]),
                    ),
                    "d" * 64,
                )
                if changed_contract == "algorithm":
                    completed["algorithm_version"] = "nextday-research-v-next"
                else:
                    group_name = "l1" if changed_contract == "l1_method" else "b0"
                    completed[group_name]["method"] = "changed-method"
                with tempfile.TemporaryDirectory() as tmp:
                    runs = Path(tmp)
                    freeze_selection(runs, first, "initial", frozen_at="2026-09-17T08:00:00Z")
                    path = runs / REPORT_DATE / "selection.json"
                    before = path.read_bytes()
                    result = freeze_selection(
                        runs, completed, "same-raw-report-new-contract", frozen_at="2026-09-18T08:00:00Z"
                    )
                    self.assertEqual(result["action"], "conflict")
                    self.assertEqual(path.read_bytes(), before)

    def test_conflicting_report_identity_and_report_sha_are_not_proof(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        first = adapt_report(report)
        first["report_identity"] = "e" * 64
        first["source_hashes"] = {"report_sha256": "e" * 64}
        completed = adapt_report(
            report,
            archived_workbench=_archived_workbench([_candidate("603960", "克来机电")]),
        )
        completed["report_identity"] = "f" * 64
        completed["source_hashes"] = {"report_sha256": "e" * 64}
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            freeze_selection(runs, first, "original", frozen_at="2026-09-17T08:00:00Z")
            path = runs / REPORT_DATE / "selection.json"
            before = path.read_bytes()
            result = freeze_selection(
                runs, completed, "inconsistent-identities", frozen_at="2026-09-18T08:00:00Z"
            )
            self.assertEqual(result["action"], "conflict")
            self.assertEqual(path.read_bytes(), before)

    def test_same_report_and_group_inputs_ignore_archive_html_asset_query_change(self):
        report = _report(
            [_candidate("600609", "金杯汽车")],
            _snapshot([_limit_row("600609", "金杯汽车")]),
        )
        archived = _archived_workbench([_candidate("600609", "金杯汽车")])
        first = _with_report_identity(adapt_report(report, archived_workbench=archived))
        rerun = _with_report_identity(adapt_report(report, archived_workbench=archived))
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            freeze_selection(runs, first, "html-query-v1", frozen_at="2026-09-17T08:00:00Z")
            path = runs / REPORT_DATE / "selection.json"
            original = path.read_bytes()
            result = freeze_selection(
                runs, rerun, "html-query-v2", frozen_at="2026-09-17T08:01:00Z"
            )
            self.assertEqual(result["action"], "unchanged")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list((runs / REPORT_DATE / "conflicts").glob("*.json"))), 0)

    def test_outcomes_are_read_only_to_selection_and_markdown_shows_pending(self):
        report = _report([_candidate()], _snapshot([_limit_row("600609", "金杯汽车")]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            runs = root / "runs"
            frozen = runs / REPORT_DATE / "selection.json"

            def fake_evaluator(snapshot, db_path, as_of_date):
                self.assertTrue(frozen.exists(), "selection must be frozen before outcome access")
                self.assertEqual(snapshot["report_date"], REPORT_DATE)
                return {
                    "status": "pending",
                    "report_date": REPORT_DATE,
                    "as_of_date": as_of_date,
                    "outcome_rows": [
                        {
                            "selection": row,
                            "outcome_status": "pending",
                            "maturity_status": {"t1": "pending", "t2": "pending", "t3": "pending"},
                            "basis_status": "verified",
                            "cc1": None,
                        }
                        for row in snapshot["selected"]
                    ],
                    "metrics": {
                        "selected": len(snapshot["selected"]),
                        "observed_cc1": 0,
                        "pending_t1": len(snapshot["selected"]),
                    },
                }

            result = process_report(
                report_path,
                runs,
                Path("unused.db"),
                as_of_date=REPORT_DATE,
                outcome_evaluator=fake_evaluator,
            )
            self.assertEqual(result["status"], "processed")
            md_path = runs / REPORT_DATE / "shortlist.md"
            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("未到期", markdown)
            self.assertIn("可观察 0/1", markdown)
            self.assertNotIn("大涨率 0%", markdown)
            self.assertEqual(
                json.loads(frozen.read_text(encoding="utf-8"))["freeze_status"],
                "valid",
            )

    def test_adapter_selection_integrates_with_real_outcome_evaluator(self):
        candidates = [
            _candidate("600609", "金杯汽车"),
            _candidate("603960", "克来机电"),
        ]
        snapshot = _snapshot(
            [
                _limit_row("600609", "金杯汽车", "汽车零部", 1, "10:58"),
                _limit_row("603960", "克来机电", "汽车零部", 1, "14:17"),
            ]
        )
        report = _report(candidates, snapshot)
        archived = {
            "identity_matches": True,
            "workbench": {
                "report_date": REPORT_DATE,
                "items": [
                    {
                        "code": "603960",
                        "name": "克来机电",
                        "candidate": _candidate("603960", "克来机电"),
                        "strategy_results": [{"strategy_id": "highlights", "view_rank": 1}],
                    }
                ],
            },
        }
        prepared = adapt_report(report, archived_workbench=archived)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market_history.sqlite"
            _create_outcome_database(db_path, prepared["normalized_candidates"])
            l1 = evaluate_frozen_selection(
                {"report_date": REPORT_DATE, "selected": prepared["l1"]["selected"]},
                db_path,
                REPORT_DATE,
            )
            b0 = evaluate_frozen_selection(
                {"report_date": REPORT_DATE, "selected": prepared["b0"]["selected"]},
                db_path,
                REPORT_DATE,
            )
            self.assertEqual(l1["metrics"]["identity_valid_selected"], 2)
            self.assertEqual(l1["metrics"]["identity_malformed"], 0)
            self.assertEqual(l1["metrics"]["pending_t1"], 2)
            self.assertEqual(l1["metrics"]["observed_cc1"], 0)
            self.assertTrue(all(row["identity_status"] == "valid" for row in l1["outcome_rows"]))
            self.assertEqual(b0["metrics"]["identity_valid_selected"], 1)
            self.assertEqual(b0["metrics"]["pending_t1"], 1)
            self.assertEqual(b0["metrics"]["observed_cc1"], 0)

            aliases_without_outer_exchange = [
                {key: value for key, value in row.items() if key not in ("exchange", "asset_type")}
                for row in prepared["l1"]["selected"]
            ]
            subset = evaluate_frozen_selection(
                {"report_date": REPORT_DATE, "selected": aliases_without_outer_exchange},
                db_path,
                REPORT_DATE,
            )
            self.assertEqual(subset["metrics"]["identity_valid_selected"], 2)
            self.assertEqual(subset["metrics"]["identity_malformed"], 0)

    def test_process_upgrades_initial_incomplete_attempt_when_snapshot_becomes_valid(self):
        partial = _snapshot([_limit_row("600609", "金杯汽车")])
        partial["status"] = "partial"
        report = _report([_candidate()], partial)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            runs = root / "runs"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            first = process_report(report_path, runs, Path("unused.db"), as_of_date=REPORT_DATE)
            selection_path = runs / REPORT_DATE / "selection.json"
            self.assertEqual(first["freeze_action"], "created")
            self.assertEqual(json.loads(selection_path.read_text())["freeze_status"], "input_insufficient")

            report["limit_up_snapshot"] = _snapshot([_limit_row("600609", "金杯汽车")])
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            with mock.patch(
                "chanlun.nextday_research.evaluate_frozen_selection",
                return_value={"status": "pending", "outcome_rows": [], "metrics": {"selected": 1}},
            ) as evaluator:
                second = process_report(report_path, runs, Path("unused.db"), as_of_date=REPORT_DATE)
            self.assertEqual(second["freeze_action"], "upgraded")
            self.assertEqual(json.loads(selection_path.read_text())["freeze_status"], "valid")
            evaluator.assert_called_once()

    def test_same_source_guard_failure_can_upgrade_when_asof_matches(self):
        report = _report([_candidate()], _snapshot([_limit_row("600609", "金杯汽车")]))
        report["data_quality"] = {
            "report_date": REPORT_DATE,
            "bar_state": "closed",
            "is_official": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            runs = root / "runs"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            first = process_report(
                report_path,
                runs,
                Path("unused.db"),
                as_of_date="2026-09-16",
            )
            selection_path = runs / REPORT_DATE / "selection.json"
            first_saved = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertEqual(first["freeze_action"], "created")
            self.assertEqual(first_saved["freeze_status"], "input_insufficient")
            source_hash = first_saved["source_hash"]

            def fake_evaluator(snapshot, db_path, as_of_date):
                return {
                    "status": "pending",
                    "report_date": snapshot["report_date"],
                    "as_of_date": as_of_date,
                    "outcome_rows": [],
                    "metrics": {"selected": len(snapshot["selected"]), "observed_cc1": 0},
                }

            second = process_report(
                report_path,
                runs,
                Path("unused.db"),
                as_of_date=REPORT_DATE,
                outcome_evaluator=fake_evaluator,
            )
            saved = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertEqual(second["freeze_action"], "upgraded")
            self.assertEqual(saved["source_hash"], source_hash)
            self.assertEqual(saved["freeze_status"], "valid")

    def test_empty_valid_selection_is_immutable(self):
        empty = {
            "status": "verified_empty",
            "date": REPORT_DATE,
            "as_of": REPORT_DATE + "T15:00:00+08:00",
            "raw_total": 0,
            "parsed_count": 0,
            "parse_error_count": 0,
            "items": [],
        }
        prepared = adapt_report(_report([_candidate()], empty))
        self.assertEqual(prepared["freeze_status"], "valid")
        self.assertEqual(prepared["l1"]["selected"], [])
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            first = freeze_selection(runs, prepared, source_hash="empty-a")
            changed = freeze_selection(runs, prepared, source_hash="empty-b")
            saved = json.loads((runs / REPORT_DATE / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(first["action"], "created")
            self.assertEqual(changed["action"], "conflict")
            self.assertEqual(saved["l1"]["selected"], [])


if __name__ == "__main__":
    unittest.main()
