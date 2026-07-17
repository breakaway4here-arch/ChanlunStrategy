"""Tests for the offline report comparison price index."""

import json
import os
import sqlite3
import tempfile
import unittest

from chanlun.report_comparison import build_comparison_index
from scripts.validate_today_report import validate_comparison_contract


class ReportComparisonIndexTest(unittest.TestCase):
    def _write_report(self, data_dir, date, *, official=True):
        with open(os.path.join(data_dir, f"{date}.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "date": date,
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
                (1, "2026-01-02", 10.5, 1),
                (2, "2026-01-02", 20.5, 1),
                (3, "2026-01-02", 99.0, 1),
                (4, "2026-01-02", 88.0, 1),
                (5, "2026-01-02", 4070.94, 1),
            ],
        )
        connection.commit()
        connection.close()

    def test_builds_contract_from_official_reports_and_final_local_prices_only(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.mkdir(data_dir)
            dates = [f"2026-01-{day:02d}" for day in range(1, 29)]
            for date in dates:
                self._write_report(data_dir, date)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": dates,
                    "date_meta": {date: {"is_official": date != "2026-01-28"} for date in dates},
                }, handle)
            db_path = os.path.join(root, "market.sqlite")
            self._create_db(db_path)

            index = build_comparison_index(data_dir, db_path, window_size=26)

            self.assertEqual(index["version"], 1)
            self.assertEqual(index["dates"], dates[1:27])
            self.assertEqual(index["latest_date"], "2026-01-27")
            report = index["reports"]["2026-01-02"]
            self.assertEqual(report["benchmark"], {"code": "000300", "name": "沪深300", "close": 4002.0})
            self.assertEqual(report["prices"], {"600001": 10.5, "000002": None})
            self.assertEqual(report["missing_codes"], ["000002"])
            self.assertEqual(report["views"]["main"], [{
                "code": "600001", "name": "示例股", "industry": "测试行业",
                "rank": 2, "decision": "观察", "decision_code": "observe",
            }])
            self.assertEqual(report["views"]["highlights"][0]["rank"], 1)
            self.assertEqual(report["views"]["baseline"], [])

            self.assertEqual(
                validate_comparison_contract(index, report_date="2026-01-27"),
                [],
            )

            oversized = dict(index)
            oversized["dates"] = [f"2026-02-{day:02d}" for day in range(1, 28)]
            errors = validate_comparison_contract(oversized)
            self.assertIn("comparison index exceeds 26 report days", errors)
