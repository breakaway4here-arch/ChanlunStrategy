"""Tests for the read-only review-registry derivation CLI."""

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts.build_report_review_registry import main


class BuildReportReviewRegistryTest(unittest.TestCase):
    @staticmethod
    def _write_complete_sources(root):
        docs_dir = os.path.join(root, "docs")
        data_dir = os.path.join(docs_dir, "data")
        report_date = "2027-01-04"
        report_dir = os.path.join(docs_dir, report_date)
        os.makedirs(data_dir)
        os.makedirs(report_dir)
        report_path = os.path.join(data_dir, report_date + ".json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump({
                "date": report_date,
                "data_quality": {
                    "is_trading_day": True,
                    "is_official": True,
                },
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
                    "main": [{"code": "600001", "name": "示例股"}],
                }},
            }, handle, ensure_ascii=False)
        manifest_path = os.path.join(data_dir, "index.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump({
                "dates": [report_date],
                "date_meta": {report_date: {
                    "is_trading_day": True,
                    "is_official": True,
                }},
            }, handle)
        source_index = os.path.join(data_dir, "comparison-index.json")
        with open(source_index, "w", encoding="utf-8") as handle:
            json.dump({
                "version": 1,
                "dates": [report_date],
                "latest_date": report_date,
                "reports": {},
            }, handle)
        html_path = os.path.join(report_dir, "index.html")
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write("<!doctype html><title>archived report</title>")
        market_db = os.path.join(root, "market.sqlite")
        connection = sqlite3.connect(market_db)
        try:
            connection.executescript("""
                CREATE TABLE instruments (
                    instrument_id INTEGER PRIMARY KEY,
                    code TEXT,
                    exchange TEXT,
                    asset_type TEXT
                );
                CREATE TABLE bars_day (
                    instrument_id INTEGER,
                    ts TEXT,
                    close REAL,
                    is_final INTEGER,
                    adjustment TEXT
                );
                CREATE TABLE bar_table_settings (
                    table_name TEXT,
                    adjustment TEXT
                );
            """)
            connection.commit()
        finally:
            connection.close()
        return {
            "docs_dir": docs_dir,
            "report": report_path,
            "manifest": manifest_path,
            "source_index": source_index,
            "html": html_path,
            "market_db": market_db,
        }

    @staticmethod
    def _hash_bytes(value):
        return hashlib.sha256(value).hexdigest()

    @classmethod
    def _protected_state(cls, sources, aliases=()):
        with open(sources["market_db"], "rb") as handle:
            state = {"market_db": cls._hash_bytes(handle.read())}
        for current_root, directories, files in os.walk(sources["docs_dir"]):
            directories.sort()
            for filename in sorted(files):
                path = os.path.join(current_root, filename)
                relative = os.path.relpath(path, sources["docs_dir"])
                with open(path, "rb") as handle:
                    state["docs/" + relative] = cls._hash_bytes(handle.read())
        for alias in aliases:
            state["symlink/" + os.path.basename(alias)] = cls._hash_bytes(
                os.readlink(alias).encode("utf-8")
            )
        return state

    def test_writes_derived_output_without_touching_source_index(self):
        with tempfile.TemporaryDirectory() as root:
            docs_dir = os.path.join(root, "docs")
            data_dir = os.path.join(docs_dir, "data")
            os.makedirs(data_dir)
            report_date = "2027-01-04"
            report = {
                "date": report_date,
                "data_quality": {
                    "is_trading_day": True,
                    "is_official": True,
                },
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
                    "main": [{"code": "600001", "name": "示例股"}],
                }},
            }
            with open(
                os.path.join(data_dir, report_date + ".json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(report, handle, ensure_ascii=False)
            with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "dates": [report_date],
                    "date_meta": {report_date: {
                        "is_trading_day": True,
                        "is_official": True,
                    }},
                }, handle)
            source_index = os.path.join(data_dir, "comparison-index.json")
            with open(source_index, "wb") as handle:
                handle.write(b"legacy-index-bytes")
            output = os.path.join(root, "derived.json")

            result = main([
                "--docs-dir", docs_dir,
                "--market-db", os.path.join(root, "missing.sqlite"),
                "--output", output,
                "--window-size", "1",
            ])

            self.assertEqual(result, 0)
            with open(output, encoding="utf-8") as handle:
                derived = json.load(handle)
            self.assertEqual(derived["review_registry"]["registered_count"], 1)
            with open(source_index, "rb") as handle:
                self.assertEqual(handle.read(), b"legacy-index-bytes")

    def test_refuses_to_overwrite_source_comparison_index(self):
        with tempfile.TemporaryDirectory() as root:
            docs_dir = os.path.join(root, "docs")
            os.makedirs(os.path.join(docs_dir, "data"))
            with self.assertRaisesRegex(ValueError, "read-only derivation"):
                main([
                    "--docs-dir", docs_dir,
                    "--market-db", os.path.join(root, "missing.sqlite"),
                    "--output", os.path.join(
                        docs_dir, "data", "comparison-index.json"
                    ),
                ])

    def test_rejects_market_database_alias_before_building(self):
        with tempfile.TemporaryDirectory() as root:
            sources = self._write_complete_sources(root)
            with mock.patch(
                "scripts.build_report_review_registry.build_comparison_index"
            ) as build:
                with self.assertRaisesRegex(
                    ValueError, "read-only derivation"
                ):
                    main([
                        "--docs-dir", sources["docs_dir"],
                        "--market-db", sources["market_db"],
                        "--output", sources["market_db"],
                    ])
            build.assert_not_called()

    def test_rejects_direct_and_symlinked_source_outputs_without_mutation(self):
        cases = (
            "market_db",
            "new_file_in_docs",
            "symlink_to_market_db",
            "symlink_to_report",
            "symlinked_docs_directory",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as root:
                sources = self._write_complete_sources(root)
                aliases = []
                if case == "market_db":
                    output = sources["market_db"]
                elif case == "new_file_in_docs":
                    output = os.path.join(sources["docs_dir"], "derived.json")
                elif case == "symlink_to_market_db":
                    output = os.path.join(root, "market-alias")
                    os.symlink(sources["market_db"], output)
                    aliases.append(output)
                elif case == "symlink_to_report":
                    output = os.path.join(root, "report-alias")
                    os.symlink(sources["report"], output)
                    aliases.append(output)
                else:
                    docs_alias = os.path.join(root, "docs-alias")
                    os.symlink(sources["docs_dir"], docs_alias)
                    aliases.append(docs_alias)
                    output = os.path.join(docs_alias, "derived.json")
                before = self._protected_state(sources, aliases)
                error = None
                try:
                    main([
                        "--docs-dir", sources["docs_dir"],
                        "--market-db", sources["market_db"],
                        "--output", output,
                        "--window-size", "1",
                    ])
                except ValueError as exc:
                    error = exc
                after = self._protected_state(sources, aliases)

                self.assertEqual(after, before)
                self.assertIsNotNone(error)
                self.assertIn("read-only derivation", str(error))

    def test_external_output_with_temporary_database_remains_supported(self):
        with tempfile.TemporaryDirectory() as root:
            sources = self._write_complete_sources(root)
            output_dir = os.path.join(root, "derived")
            output = os.path.join(output_dir, "comparison.json")
            before = self._protected_state(sources)

            result = main([
                "--docs-dir", sources["docs_dir"],
                "--market-db", sources["market_db"],
                "--output", output,
                "--window-size", "1",
            ])

            self.assertEqual(result, 0)
            self.assertEqual(self._protected_state(sources), before)
            with open(output, encoding="utf-8") as handle:
                derived = json.load(handle)
            self.assertEqual(derived["review_registry"]["registered_count"], 1)


if __name__ == "__main__":
    unittest.main()
