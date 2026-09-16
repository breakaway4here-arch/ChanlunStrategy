"""R0 regression tests for optional comparison-index generation."""

import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from chanlun.report_comparison import ComparisonIndexUnavailable
from chanlun.report_generator import generate_report


class ReportGeneratorComparisonDegradationTest(unittest.TestCase):
    @staticmethod
    def _report(date="2026-07-17"):
        return {
            "date": date,
            "market": {"沪深300": {"close": 4529.1}},
            "picks_fusion": [{
                "code": "600001",
                "name": "示例股",
                "decision_engine_v1": {
                    "decision": "推荐",
                    "decision_code": "recommend",
                },
            }],
            "data_quality": {
                "is_trading_day": True,
                "is_official": True,
            },
        }

    def test_current_workbench_reaches_index_before_html_is_written(self):
        with tempfile.TemporaryDirectory() as root:
            generate_report(self._report(), output_dir=root, comparison_db_path="")

            with open(
                os.path.join(root, "data", "comparison-index.json"),
                encoding="utf-8",
            ) as handle:
                index = json.load(handle)
            entry = index["review_registry"]["entries"][0]
            self.assertEqual(entry["code"], "600001")
            self.assertEqual(entry["snapshot_kind"], "current_generation_bootstrap")
            self.assertEqual(entry["coverage_status"], "confirmed_display_snapshot")

    def test_optional_comparison_failure_does_not_block_main_report(self):
        with tempfile.TemporaryDirectory() as root, mock.patch(
            "chanlun.report_generator.write_comparison_index",
            side_effect=ComparisonIndexUnavailable("optional I/O failed"),
        ):
            index_path = generate_report(
                self._report(), output_dir=root, comparison_db_path=""
            )

            self.assertTrue(os.path.isfile(index_path))
            self.assertTrue(os.path.isfile(os.path.join(root, "2026-07-17", "index.html")))

    def test_optional_registry_task_failure_keeps_comparison_and_marks_unavailable(self):
        report = self._report()
        report["selection_input_health"] = {
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
        }
        with tempfile.TemporaryDirectory() as root, mock.patch(
            "chanlun.report_comparison._build_review_registry",
            side_effect=RuntimeError("injected optional review task failed"),
        ):
            index_path = generate_report(
                report, output_dir=root, comparison_db_path=""
            )

            self.assertTrue(os.path.isfile(index_path))
            with open(
                os.path.join(root, "data", "comparison-index.json"),
                encoding="utf-8",
            ) as handle:
                comparison = json.load(handle)
            registry = comparison["review_registry"]
            self.assertEqual(registry["status"], "unavailable")
            self.assertIsNone(registry["registered_count"])
            self.assertIsNone(registry["instrument_count"])
            self.assertEqual(registry["entries"], [])
            self.assertEqual(
                [row["code"] for row in comparison["reports"]["2026-07-17"]["views"]["main"]],
                ["600001"],
            )

    def test_optional_price_index_runtime_error_does_not_block_main_report(self):
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "data")
            os.makedirs(data_dir)
            comparison_path = os.path.join(
                data_dir, "comparison-index.json"
            )
            previous_comparison = b'{"latest_date":"2026-07-16"}'
            with open(comparison_path, "wb") as handle:
                handle.write(previous_comparison)
            with mock.patch(
                "chanlun.report_comparison._read_final_prices",
                side_effect=RuntimeError(
                    "injected private path /should/not/appear"
                ),
            ), redirect_stdout(stdout):
                index_path = generate_report(
                    self._report(), output_dir=root, comparison_db_path=""
                )

            with open(comparison_path, "rb") as handle:
                self.assertEqual(handle.read(), previous_comparison)
            self.assertTrue(os.path.isfile(index_path))
            self.assertTrue(os.path.isfile(
                os.path.join(root, "2026-07-17", "index.html")
            ))
            self.assertTrue(os.path.isfile(os.path.join(root, "index.html")))
        self.assertIn("RuntimeError", stdout.getvalue())
        self.assertNotIn("/should/not/appear", stdout.getvalue())

    def test_required_report_write_error_still_propagates(self):
        with tempfile.TemporaryDirectory() as root, mock.patch(
            "chanlun.report_generator.write_daily_data_json",
            side_effect=ValueError("required report invalid"),
        ):
            with self.assertRaisesRegex(ValueError, "required report invalid"):
                generate_report(
                    self._report(), output_dir=root, comparison_db_path=""
                )


if __name__ == "__main__":
    unittest.main()
