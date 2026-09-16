"""Tests for the offline report comparison price index."""

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import chanlun.report_comparison as report_comparison
from chanlun.report_comparison import (
    build_comparison_index,
    comparison_review_snapshot,
    write_comparison_index,
)
from scripts.validate_today_report import (
    validate_comparison_contract,
    validate_comparison_formal_alignment,
)


class ReportComparisonIndexTest(unittest.TestCase):
    def _write_report(self, data_dir, date, *, official=True, trading=True):
        with open(os.path.join(data_dir, f"{date}.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "date": date,
                "data_quality": {
                    "is_trading_day": trading,
                    "is_official": official,
                    "missing_daily_count": 7 if not official else 0,
                    "stale_stock_count": 3 if not official else 0,
                },
                "market": {"沪深300": {"close": 4000 + int(date[-2:])}},
                "selection_input_health": {
                    "schema_version": 2,
                    "by_strategy": {
                        "daily_fusion": {
                            "status": "verified",
                            "formal_actions_allowed": True,
                        },
                        "h4_t3": {
                            "status": "verified",
                            "formal_actions_allowed": True,
                        },
                    },
                },
                "workspace": {"views": {
                    "main": [{
                        "code": "600001", "name": "示例股", "sector": "测试行业",
                        "view_rank": 2,
                        "decision_engine_v1": {"decision": "观察", "decision_code": "observe"},
                    }],
                    "highlights": [{"code": "000002", "name": "看点股", "industry": "看点行业", "view_rank": 1}],
                    "h4_t3": [],
                }},
            }, handle, ensure_ascii=False)
        return official

    def _create_db(self, path):
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE instruments (
              instrument_id INTEGER PRIMARY KEY, asset_type TEXT, exchange TEXT,
              code TEXT, name TEXT, updated_at TEXT
            );
            CREATE TABLE bars_day (
              instrument_id INTEGER, ts TEXT, close REAL, is_final INTEGER
            );
        """)
        connection.executemany(
            "INSERT INTO instruments VALUES (?, ?, ?, ?, '', '')",
            [
                (1, "stock", "SH", "600001"),
                (2, "stock", "SZ", "000002"),
                (3, "stock", "SZ", "600001"),
                (4, "index", "SH", "600001"),
                (5, "stock", "SH", "000002"),
            ],
        )
        connection.executemany(
            "INSERT INTO bars_day VALUES (?, ?, ?, ?)",
            [
                (1, "2026-01-03", 10.5, 1),
                (2, "2026-01-03", 20.5, 1),
                (3, "2026-01-03", 99.0, 1),
                (4, "2026-01-03", 88.0, 1),
                (5, "2026-01-03", 4070.94, 1),
            ],
        )
        connection.commit()
        connection.close()

    def _write_archived_workbench(
        self,
        root,
        date,
        items,
        *,
        snapshot_id="published-snapshot",
        inline_report=None,
    ):
        archive_dir = os.path.join(root, date)
        os.makedirs(archive_dir, exist_ok=True)
        if inline_report is None:
            with open(
                os.path.join(root, "data", date + ".json"), encoding="utf-8"
            ) as handle:
                inline_report = json.load(handle)
        bootstrap = {
            "pageDate": date,
            "inlineReportData": inline_report,
            "decisionWorkbench": {
                "schema_version": "decision-workbench-v1",
                "report_date": date,
                "snapshot_id": snapshot_id,
                "comparison_contract": {
                    "strategy_identities": [{
                        "strategy_id": "luojie_pool",
                        "strategy_version": "luojie-15m-research-v2",
                        "policy_version": "decision-v2",
                        "source_pool": "luojie_pool",
                    }],
                },
                "items": items,
            },
            "accessKeyHash": "must-not-be-retained",
            "accessKeySalt": "must-not-be-retained",
        }
        with open(
            os.path.join(archive_dir, "index.html"), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                "<html><script>window.CHANLUN_BOOTSTRAP= "
                + json.dumps(bootstrap, ensure_ascii=False)
                + ";</script></html>"
            )

    @staticmethod
    def _workbench_item(code, name, *, view="luojie", rank=1, score=35):
        return {
            "code": code,
            "instrument_id": ("SH" if code.startswith("6") else "SZ") + code,
            "name": name,
            "execution_status": "waiting",
            "page_status": "watch_only",
            "risk_flags": ["测试风险"],
            "strategy_results": [{
                "strategy_id": view,
                "role": "research",
                "view_rank": rank,
                "formal_action": None,
                "candidate": {
                    "code": code,
                    "name": name,
                    "action": "盯盘",
                    "decision_engine_v1": {
                        "version": "decision-v2",
                        "total_score": score,
                    },
                },
            }],
        }

    def test_keeps_empty_trading_report_in_calendar_window(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            dates = ["2026-01-02", "2026-01-03"]
            for date in dates:
                self._write_report(data_dir, date)
            empty_path = os.path.join(data_dir, dates[0] + ".json")
            with open(empty_path, "r", encoding="utf-8") as handle:
                empty = json.load(handle)
            empty["workspace"]["views"] = {"main": [], "h4_t3": []}
            with open(empty_path, "w", encoding="utf-8") as handle:
                json.dump(empty, handle, ensure_ascii=False)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": dates,
                    "date_meta": {
                        date: {"is_trading_day": True, "is_official": True}
                        for date in dates
                    },
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            self.assertEqual(index["dates"], dates)
            self.assertEqual(index["reports"][dates[0]]["views"]["main"], [])

    def test_archived_display_snapshot_adds_review_registry_without_changing_views(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-03"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root,
                date,
                [
                    self._workbench_item("600001", "正式视图股", view="main"),
                    self._workbench_item("000002", "展示新增股", rank=2),
                ],
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {
                        date: {"is_trading_day": True, "is_official": True}
                    },
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            self.assertEqual(
                [row["code"] for row in index["reports"][date]["views"]["main"]],
                ["600001"],
            )
            registry = index["review_registry"]
            self.assertEqual(registry["status"], "available")
            self.assertEqual(registry["registered_count"], 2)
            self.assertEqual(registry["instrument_count"], 2)
            self.assertEqual(
                {row["code"] for row in registry["entries"]},
                {"600001", "000002"},
            )
            added = next(row for row in registry["entries"] if row["code"] == "000002")
            self.assertEqual(added["snapshot_kind"], "published_html_bootstrap")
            self.assertEqual(added["coverage_status"], "confirmed_display_snapshot")
            self.assertEqual(added["sources"][0]["rank"], 2)
            self.assertEqual(added["sources"][0]["action"], "盯盘")
            self.assertEqual(added["sources"][0]["score"], 35.0)
            self.assertEqual(
                added["sources"][0]["strategy_version"],
                "luojie-15m-research-v2",
            )
            self.assertEqual(added["sources"][0]["decision_version"], "decision-v2")
            self.assertEqual(added["sources"][0]["policy_version"], "decision-v2")
            self.assertEqual(added["risk_flags"], ["测试风险"])
            self.assertEqual(added["current_execution_status"], "waiting")
            self.assertNotIn("must-not-be-retained", json.dumps(registry))

    def test_current_generation_snapshot_wins_over_stale_archived_page(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-03"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root, date, [self._workbench_item("000002", "旧页对象")]
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)
            current = {
                "schema_version": "decision-workbench-v1",
                "report_date": date,
                "snapshot_id": "current-snapshot",
                "items": [self._workbench_item("600001", "本次生成对象", view="main")],
            }

            with comparison_review_snapshot(current):
                index = build_comparison_index(data_dir, db_path)

            entries = index["review_registry"]["entries"]
            self.assertEqual([row["code"] for row in entries], ["600001"])
            self.assertEqual(entries[0]["snapshot_id"], "current-snapshot")
            self.assertEqual(entries[0]["snapshot_kind"], "current_generation_bootstrap")

    def test_same_date_mismatched_archive_is_not_marked_as_confirmed_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-03"
            self._write_report(data_dir, date)
            with open(os.path.join(data_dir, date + ".json"), encoding="utf-8") as handle:
                mismatched = json.load(handle)
            mismatched["market"]["沪深300"]["close"] = 9999
            self._write_archived_workbench(
                root,
                date,
                [self._workbench_item("600001", "后修展示对象", view="main")],
                inline_report=mismatched,
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            entry = index["review_registry"]["entries"][0]
            self.assertEqual(entry["snapshot_kind"], "postprocessed_html_bootstrap")
            self.assertEqual(entry["coverage_status"], "unconfirmed_report_identity")

    def test_same_day_duplicate_identity_merges_sources_without_double_counting(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-03"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root,
                date,
                [
                    self._workbench_item("600001", "重复对象", view="main"),
                    self._workbench_item("600001", "重复对象", view="luojie", rank=2),
                ],
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            registry = index["review_registry"]
            self.assertEqual(registry["registered_count"], 1)
            self.assertEqual(
                {source["view"] for source in registry["entries"][0]["sources"]},
                {"main", "luojie"},
            )

    def test_legacy_workspace_fallback_is_explicit_and_counts_repeats(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            dates = ["2026-01-02", "2026-01-03"]
            for date in dates:
                self._write_report(data_dir, date)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": dates,
                    "date_meta": {
                        date: {"is_trading_day": True, "is_official": True}
                        for date in dates
                    },
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            repeated = [
                row for row in index["review_registry"]["entries"]
                if row["code"] == "600001"
            ]
            self.assertEqual(len(repeated), 2)
            self.assertEqual(
                [row["snapshot_kind"] for row in repeated],
                ["legacy_workspace_fallback", "legacy_workspace_fallback"],
            )
            self.assertEqual(
                [row["coverage_status"] for row in repeated],
                ["unconfirmed_legacy_workspace", "unconfirmed_legacy_workspace"],
            )
            self.assertEqual(
                [row["occurrence_in_window"] for row in repeated], [1, 2]
            )
            self.assertEqual(
                [row["occurrence_count_in_window"] for row in repeated], [2, 2]
            )
            self.assertEqual(
                [row["first_seen_in_window"] for row in repeated],
                [dates[0], dates[0]],
            )

    def test_review_horizons_use_trading_calendar_and_keep_missing_in_denominator(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-05"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root, date, [self._workbench_item("600001", "复盘对象", view="main")]
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)
            connection = sqlite3.connect(db_path)
            connection.execute(
                "ALTER TABLE bars_day ADD COLUMN adjustment TEXT NOT NULL DEFAULT 'qfq'"
            )
            connection.execute(
                "CREATE TABLE trade_calendar ("
                "exchange TEXT, trade_date TEXT, is_open INTEGER, updated_at TEXT)"
            )
            connection.execute(
                "CREATE TABLE bar_table_settings ("
                "table_name TEXT, adjustment TEXT, updated_at TEXT)"
            )
            connection.execute(
                "INSERT INTO bar_table_settings VALUES ('bars_day', 'qfq', '')"
            )
            connection.executemany(
                "INSERT INTO trade_calendar VALUES ('SH', ?, 1, '')",
                [(value,) for value in (
                    "2026-01-05", "2026-01-06", "2026-01-07",
                    "2026-01-08", "2026-01-09", "2026-01-12",
                )],
            )
            connection.executemany(
                "INSERT INTO bars_day (instrument_id, ts, close, is_final, adjustment) "
                "VALUES (?, ?, ?, 1, 'qfq')",
                [
                    (1, "2026-01-05", 10.5),
                    (1, "2026-01-06", 11.55),
                    (2, "2026-01-08", 30.0),
                ],
            )
            connection.commit()
            connection.close()
            with open(
                os.path.join(data_dir, "comparison-index.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({
                    "version": 1,
                    "dates": ["2026-01-05", "2026-01-06"],
                    "latest_date": "2026-01-06",
                    "reports": {
                        "2026-01-05": {"prices": {"600001": 10.5}},
                        "2026-01-06": {"prices": {"600001": 11.55}},
                    },
                }, handle)

            index = build_comparison_index(data_dir, db_path)

            entry = index["review_registry"]["entries"][0]
            self.assertEqual(entry["horizons"]["T+1"]["target_trading_date"], "2026-01-06")
            self.assertEqual(entry["horizons"]["T+1"]["status"], "calculated_legacy_internal")
            self.assertAlmostEqual(entry["horizons"]["T+1"]["return_pct"], 10.0)
            self.assertEqual(entry["horizons"]["T+3"]["target_trading_date"], "2026-01-08")
            self.assertEqual(entry["horizons"]["T+3"]["status"], "missing")
            self.assertIsNone(entry["horizons"]["T+3"]["endpoint_price"])
            self.assertEqual(entry["horizons"]["T+5"]["target_trading_date"], "2026-01-12")
            self.assertEqual(entry["horizons"]["T+5"]["status"], "pending")
            summary = index["review_registry"]["horizon_summary"]
            self.assertEqual(summary["T+3"]["registered"], 1)
            self.assertEqual(summary["T+3"]["matured"], 1)
            self.assertEqual(summary["T+3"]["calculable"], 0)
            self.assertEqual(summary["T+3"]["missing"], 1)
            self.assertNotIn("mean_return_pct", summary["T+1"])
            self.assertNotIn("median_return_pct", summary["T+1"])

    def test_review_return_requires_canonical_price_basis_setting(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-05"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root, date, [self._workbench_item("600001", "价基待证对象", view="main")]
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)
            connection = sqlite3.connect(db_path)
            connection.execute(
                "ALTER TABLE bars_day ADD COLUMN adjustment TEXT NOT NULL DEFAULT 'qfq'"
            )
            connection.execute(
                "CREATE TABLE trade_calendar ("
                "exchange TEXT, trade_date TEXT, is_open INTEGER, updated_at TEXT)"
            )
            connection.execute(
                "CREATE TABLE bar_table_settings ("
                "table_name TEXT, adjustment TEXT, updated_at TEXT)"
            )
            connection.execute(
                "INSERT INTO bar_table_settings VALUES ('bars_day', 'qfq', '')"
            )
            connection.executemany(
                "INSERT INTO trade_calendar VALUES ('SH', ?, 1, '')",
                [("2026-01-05",), ("2026-01-06",)],
            )
            connection.executemany(
                "INSERT INTO bars_day (instrument_id, ts, close, is_final, adjustment) "
                "VALUES (1, ?, ?, 1, 'qfq')",
                [("2026-01-05", 10.5), ("2026-01-06", 11.55)],
            )
            connection.commit()
            connection.close()

            index = build_comparison_index(data_dir, db_path)

            result = index["review_registry"]["entries"][0]["horizons"]["T+1"]
            self.assertEqual(result["status"], "price_basis_unverified")
            self.assertIsNone(result["return_pct"])

    def test_mature_identity_conflict_remains_in_matured_denominator(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-05"
            self._write_report(data_dir, date)
            item = self._workbench_item("600001", "身份冲突对象", view="main")
            item["instrument_id"] = "SZ600001"
            self._write_archived_workbench(root, date, [item])
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)
            connection = sqlite3.connect(db_path)
            connection.execute(
                "INSERT INTO bars_day VALUES (1, '2026-01-06', 11.55, 1)"
            )
            connection.commit()
            connection.close()

            index = build_comparison_index(data_dir, db_path)

            result = index["review_registry"]["entries"][0]["horizons"]["T+1"]
            self.assertEqual(result["status"], "identity_conflict")
            self.assertTrue(result["matured"])
            summary = index["review_registry"]["horizon_summary"]["T+1"]
            self.assertEqual(summary["matured"], 1)
            self.assertEqual(summary["incompatible"], 1)

    def test_unknown_future_calendar_is_not_reported_as_pending_or_zero(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2027-01-04"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root, date, [self._workbench_item("600001", "日历未知对象")]
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            horizons = index["review_registry"]["entries"][0]["horizons"]
            self.assertEqual(horizons["T+1"]["status"], "maturity_unknown")
            self.assertIsNone(horizons["T+1"]["return_pct"])

    def test_sparse_unknown_year_open_rows_do_not_define_t_plus_calendar(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2027-01-04"
            self._write_report(data_dir, date)
            self._write_archived_workbench(
                root, date, [self._workbench_item("600001", "稀疏日历对象")]
            )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE trade_calendar ("
                "exchange TEXT, trade_date TEXT, is_open INTEGER, updated_at TEXT)"
            )
            connection.executemany(
                "INSERT INTO trade_calendar VALUES ('SH', ?, 1, '')",
                [("2027-01-04",), ("2027-01-05",), ("2027-01-07",)],
            )
            connection.executemany(
                "INSERT INTO bars_day VALUES (1, ?, ?, 1)",
                [("2027-01-04", 10.0), ("2027-01-05", 11.0)],
            )
            connection.commit()
            connection.close()

            index = build_comparison_index(data_dir, db_path)

            registry = index["review_registry"]
            self.assertEqual(registry["calendar_status"], "unavailable")
            self.assertTrue(all(
                result["status"] == "maturity_unknown"
                for result in registry["entries"][0]["horizons"].values()
            ))

    def test_includes_nonofficial_trading_reports_with_quality_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            dates = [f"2026-01-{day:02d}" for day in range(1, 29)]
            for date in dates:
                self._write_report(
                    data_dir,
                    date,
                    official=date != "2026-01-28",
                    trading=date != "2026-01-01",
                )
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": dates,
                    "date_meta": {
                        date: {
                            "is_trading_day": date != "2026-01-01",
                            "is_official": date != "2026-01-28",
                        }
                        for date in dates
                    },
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path, window_size=26)

            self.assertEqual(index["version"], 1)
            self.assertEqual(index["dates"], dates[2:])
            self.assertEqual(index["latest_date"], "2026-01-28")
            report = index["reports"]["2026-01-03"]
            self.assertEqual(report["benchmark"], {"code": "000300", "name": "沪深300", "close": 4003.0})
            self.assertEqual(report["prices"], {"600001": 10.5, "000002": None})
            self.assertEqual(report["missing_codes"], ["000002"])
            self.assertEqual(report["views"]["main"], [{
                "code": "600001", "name": "示例股", "industry": "测试行业",
                "rank": 2, "decision": "观察", "decision_code": "observe",
            }])
            self.assertEqual(report["views"]["highlights"][0]["rank"], 1)
            self.assertEqual(report["views"]["h4_t3"], [])
            self.assertEqual(report["views"]["baseline"], [])
            self.assertEqual(index["reports"]["2026-01-28"]["quality"], {
                "is_official": False,
                "is_trading_day": True,
                "missing_daily_count": 7,
                "stale_stock_count": 3,
                "status": "quality_warning",
                "incident_excluded_counts": {},
            })

            self.assertEqual(
                validate_comparison_contract(index, report_date="2026-01-28"),
                [],
            )

            missing_quality = json.loads(json.dumps(index))
            del missing_quality["reports"]["2026-01-28"]["quality"]
            self.assertIn(
                "comparison quality invalid: 2026-01-28",
                validate_comparison_contract(missing_quality),
            )

            oversized = dict(index)
            oversized["dates"] = [f"2026-02-{day:02d}" for day in range(1, 28)]
            errors = validate_comparison_contract(oversized)
            self.assertIn("comparison index exceeds 26 report days", errors)

    def test_rebuilds_legacy_workspace_before_applying_report_window(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-01-03"
            self._write_report(data_dir, date, official=False)
            report_path = os.path.join(data_dir, date + ".json")
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            report.pop("workspace")
            report["picks_pure"] = [{
                "code": "600001", "name": "旧版基准股", "sector": "测试行业",
                "score": 65, "version": "picks_pure",
                "best_buy_point": {
                    "type": "底背驰候选", "reason": "历史榜单",
                    "price": 10.0, "current_price": 10.5,
                },
            }]
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {"is_trading_day": True, "is_official": False}},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path, window_size=26)

            self.assertEqual(index["dates"], [date])
            self.assertEqual(index["reports"][date]["views"]["baseline"][0]["code"], "600001")

    def test_registered_formal_incident_is_excluded_and_h4_is_indexed(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-08-25"
            self._write_report(data_dir, date)
            report_path = os.path.join(data_dir, date + ".json")
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            report["workspace"]["views"]["main"] = [{
                "code": "300473", "name": "事故样本", "view_rank": 1,
            }]
            report["workspace"]["views"]["h4_t3"] = [{
                "code": "600001", "name": "H4样本", "view_rank": 1,
            }]
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {"is_trading_day": True, "is_official": True}},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            snapshot = index["reports"][date]
            self.assertEqual([], snapshot["views"]["main"])
            self.assertEqual(["600001"], [
                row["code"] for row in snapshot["views"]["h4_t3"]
            ])
            self.assertEqual(
                {"main": 1}, snapshot["quality"]["incident_excluded_counts"]
            )
            self.assertEqual(
                [],
                validate_comparison_formal_alignment(
                    {
                        "workspace": {"views": {
                            "main": [],
                            "h4_t3": [{"code": "600001"}],
                        }}
                    },
                    index,
                    date,
                ),
            )

    def test_missing_formal_health_is_excluded_from_comparison(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-08-21"
            self._write_report(data_dir, date)
            report_path = os.path.join(data_dir, date + ".json")
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            report.pop("selection_input_health")
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True,
                        "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path)

            snapshot = index["reports"][date]
            self.assertEqual([], snapshot["views"]["main"])
            self.assertEqual(
                {"main": 1},
                snapshot["quality"]["formal_input_blocked_counts"],
            )

    def test_identical_rebuild_preserves_existing_comparison_index_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-08-31"
            self._write_report(data_dir, date)
            with open(
                os.path.join(data_dir, "index.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "dates": [date],
                        "date_meta": {
                            date: {
                                "is_trading_day": True,
                                "is_official": True,
                            }
                        },
                    },
                    handle,
                )
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            target = write_comparison_index(data_dir, db_path)
            first = Path(target).read_bytes()
            time.sleep(0.001)
            write_comparison_index(data_dir, db_path)
            second = Path(target).read_bytes()

            self.assertEqual(second, first)

    def test_atomic_publish_failure_preserves_previous_index_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            date = "2026-08-31"
            self._write_report(data_dir, date)
            with open(
                os.path.join(data_dir, "index.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({
                    "dates": [date],
                    "date_meta": {date: {
                        "is_trading_day": True, "is_official": True,
                    }},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)
            target = os.path.join(data_dir, "comparison-index.json")
            old = b'{"version":1,"latest_date":"2026-08-30"}'
            Path(target).write_bytes(old)

            with mock.patch(
                "chanlun.report_comparison.os.replace",
                side_effect=OSError("replace failed"),
            ), self.assertRaises(report_comparison.ComparisonIndexUnavailable):
                write_comparison_index(data_dir, db_path)

            self.assertEqual(Path(target).read_bytes(), old)
