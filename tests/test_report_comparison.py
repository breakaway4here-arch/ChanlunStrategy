"""Tests for the offline report comparison price index."""

import json
import os
import sqlite3
import tempfile
import unittest

from chanlun.report_comparison import build_comparison_index
from scripts.validate_today_report import validate_comparison_contract


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
                "workspace": {"views": {
                    "main": [{
                        "code": "600001", "name": "示例股", "sector": "测试行业",
                        "view_rank": 2,
                        "decision_engine_v1": {"decision": "观察", "decision_code": "observe"},
                    }],
                    "highlights": [{"code": "000002", "name": "看点股", "industry": "看点行业", "view_rank": 1}],
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
            self.assertEqual(report["views"]["baseline"], [])
            self.assertEqual(index["reports"]["2026-01-28"]["quality"], {
                "is_official": False,
                "is_trading_day": True,
                "missing_daily_count": 7,
                "stale_stock_count": 3,
                "status": "quality_warning",
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
