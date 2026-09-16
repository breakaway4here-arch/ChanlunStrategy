"""R0: optional review artifacts must not close a valid daily report."""

import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from scripts import validate_today_report


class ValidateTodayReportOptionalComparisonTest(unittest.TestCase):
    @staticmethod
    def _write_required_files(root, report_date):
        data_dir = os.path.join(root, "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(
            os.path.join(data_dir, report_date + ".json"), "w", encoding="utf-8"
        ) as handle:
            json.dump({
                "date": report_date,
                "market": {},
                "workspace": {"views": {
                    "main": [{"code": "600001"}],
                    "h4_t3": [],
                }},
            }, handle)
        with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as handle:
            json.dump({"dates": [report_date]}, handle)

    def test_missing_comparison_artifacts_warn_but_valid_report_continues(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            stderr = io.StringIO()
            with mock.patch.object(
                validate_today_report, "validate_report_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_runtime_cutover", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_manifest_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "fetch_market_indices", return_value={}
            ), redirect_stderr(stderr):
                result = validate_today_report.main([
                    "--docs-dir", root, report_date,
                ])

            self.assertEqual(result, 0)
            self.assertIn("comparison review degraded", stderr.getvalue())
            self.assertIn("missing comparison index", stderr.getvalue())

    def test_required_contract_error_still_blocks_before_market_fetch(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            fetch = mock.Mock(return_value={})
            with mock.patch.object(
                validate_today_report,
                "validate_report_contract",
                return_value=["formal input invalid"],
            ), mock.patch.object(
                validate_today_report, "validate_runtime_cutover", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_manifest_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "fetch_market_indices", fetch
            ), redirect_stderr(io.StringIO()):
                result = validate_today_report.main([
                    "--docs-dir", root, report_date,
                ])

            self.assertEqual(result, 1)
            fetch.assert_not_called()

    def test_stale_comparison_validates_its_real_cutoff_without_impersonating_today(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            data_dir = os.path.join(root, "data")
            with open(
                os.path.join(data_dir, "comparison-index.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({
                    "version": 1,
                    "dates": ["2026-09-15"],
                    "latest_date": "2026-09-15",
                    "reports": {"2026-09-15": {}},
                }, handle)
            os.makedirs(os.path.join(root, "compare"), exist_ok=True)
            with open(
                os.path.join(root, "compare", "index.html"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write('<div id="comparisonApp"></div>')
            validate_comparison = mock.Mock(return_value=[])
            stderr = io.StringIO()
            with mock.patch.object(
                validate_today_report, "validate_report_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_runtime_cutover", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_manifest_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report,
                "validate_comparison_contract",
                validate_comparison,
            ), mock.patch.object(
                validate_today_report, "fetch_market_indices", return_value={}
            ), redirect_stderr(stderr):
                result = validate_today_report.main([
                    "--docs-dir", root, report_date,
                ])

            self.assertEqual(result, 0)
            validate_comparison.assert_called_once()
            self.assertEqual(validate_comparison.call_args.kwargs, {})
            self.assertIn("coverage ends at 2026-09-15", stderr.getvalue())

    def test_invalid_comparison_shape_warns_without_raising_or_blocking(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            with open(
                os.path.join(root, "data", "comparison-index.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump([], handle)
            stderr = io.StringIO()
            with mock.patch.object(
                validate_today_report, "validate_report_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_runtime_cutover", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_manifest_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "fetch_market_indices", return_value={}
            ), redirect_stderr(stderr):
                result = validate_today_report.main([
                    "--docs-dir", root, report_date,
                ])

            self.assertEqual(result, 0)
            self.assertIn("comparison index must be a mapping", stderr.getvalue())

    @staticmethod
    def _comparison_index(report_date, main_codes):
        views = {
            name: [] for name in validate_today_report.COMPARISON_VIEWS
        }
        views["main"] = [{"code": code} for code in main_codes]
        return {
            "version": 1,
            "dates": [report_date],
            "latest_date": report_date,
            "reports": {report_date: {
                "quality": {
                    "is_official": True,
                    "is_trading_day": True,
                    "status": "official",
                },
                "views": views,
                "prices": {code: 10.0 for code in main_codes},
                "benchmark": {"code": "000300"},
            }},
        }

    @staticmethod
    def _available_registry(report_date):
        unknown_horizon = {
            "target_trading_date": None,
            "status": "maturity_unknown",
            "matured": False,
            "base_price": None,
            "endpoint_price": None,
            "price_source": None,
            "price_basis_status": None,
            "return_pct": None,
        }
        return {
            "schema_version": 1,
            "status": "available",
            "review_only": True,
            "window_start": report_date,
            "window_end": report_date,
            "registered_count": 1,
            "instrument_count": 1,
            "calendar_status": "unavailable",
            "price_data_cutoff": None,
            "horizon_summary": {},
            "entries": [{
                "report_date": report_date,
                "instrument_id": "SH600001",
                "identity_status": "verified",
                "code": "600001",
                "sources": [{
                    "view": "main",
                    "role": "formal",
                    "rank": 1,
                    "action": "推荐",
                    "score": 88.0,
                    "strategy_version": "daily-v1",
                    "decision_version": "1",
                    "policy_version": None,
                    "formal_performance_status": "formal_eligible",
                }],
                "horizons": {
                    key: dict(unknown_horizon)
                    for key in ("T+1", "T+3", "T+5")
                },
            }],
        }

    @staticmethod
    def _unavailable_registry(report_date):
        return {
            "schema_version": 1,
            "status": "unavailable",
            "review_only": True,
            "window_start": report_date,
            "window_end": report_date,
            "registered_count": None,
            "instrument_count": None,
            "calendar_status": "unavailable",
            "price_data_cutoff": None,
            "horizon_summary": {},
            "entries": [],
            "unavailable_reason": "review_task_failed",
            "error_type": "RuntimeError",
        }

    def test_comparison_artifact_only_rejects_nonmapping_and_wrong_formal_members(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            comparison_path = os.path.join(
                root, "data", "comparison-index.json"
            )
            for payload, expected in (
                ([], "comparison index must be a mapping"),
                (
                    self._comparison_index(report_date, []),
                    "comparison formal view mismatch: main",
                ),
            ):
                with self.subTest(expected=expected), open(
                    comparison_path, "w", encoding="utf-8"
                ) as handle:
                    json.dump(payload, handle)
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    result = validate_today_report.main([
                        "--comparison-artifact-only",
                        "--docs-dir", root,
                        report_date,
                    ])
                self.assertEqual(result, 1)
                self.assertIn(expected, stderr.getvalue())

    def test_comparison_artifact_only_accepts_current_aligned_index(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            with open(
                os.path.join(root, "data", "comparison-index.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    self._comparison_index(report_date, ["600001"]), handle
                )

            result = validate_today_report.main([
                "--comparison-artifact-only",
                "--docs-dir", root,
                report_date,
            ])

            self.assertEqual(result, 0)

    def test_comparison_artifact_only_accepts_valid_registry_states(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            comparison_path = os.path.join(
                root, "data", "comparison-index.json"
            )
            empty_available = self._available_registry(report_date)
            empty_available["registered_count"] = 0
            empty_available["instrument_count"] = 0
            empty_available["entries"] = []
            for label, registry in (
                ("available", self._available_registry(report_date)),
                ("available_empty", empty_available),
                ("unavailable", self._unavailable_registry(report_date)),
            ):
                with self.subTest(state=label):
                    comparison = self._comparison_index(
                        report_date, ["600001"]
                    )
                    comparison["review_registry"] = registry
                    with open(
                        comparison_path, "w", encoding="utf-8"
                    ) as handle:
                        json.dump(comparison, handle)
                    result = validate_today_report.main([
                        "--comparison-artifact-only",
                        "--docs-dir", root,
                        report_date,
                    ])
                    self.assertEqual(result, 0)

    def test_comparison_artifact_only_rejects_invalid_registry_contracts(self):
        report_date = "2026-09-16"
        available = self._available_registry(report_date)
        unavailable = self._unavailable_registry(report_date)
        cases = []
        value = copy.deepcopy(available)
        value["schema_version"] = 2
        cases.append((value, "review registry schema_version must be 1"))
        value = copy.deepcopy(available)
        value["status"] = "unknown"
        cases.append((value, "review registry status invalid"))
        value = copy.deepcopy(available)
        value["status"] = []
        cases.append((value, "review registry status invalid"))
        value = copy.deepcopy(available)
        value["registered_count"] = 99
        cases.append((value, "review registry registered_count mismatch"))
        value = copy.deepcopy(available)
        value["instrument_count"] = 0
        cases.append((value, "review registry instrument_count mismatch"))
        value = copy.deepcopy(available)
        value["entries"][0]["report_date"] = "2026-09-17"
        cases.append((value, "review registry entry report_date outside index/window"))
        value = copy.deepcopy(available)
        value["entries"][0]["sources"] = []
        cases.append((value, "review registry entry sources must be non-empty array"))
        value = copy.deepcopy(available)
        del value["entries"][0]["horizons"]["T+5"]
        cases.append((value, "review registry entry horizons incomplete"))
        value = copy.deepcopy(available)
        value["entries"][0]["horizons"]["T+1"]["status"] = "not_verified"
        cases.append((value, "review registry horizon status invalid"))
        value = copy.deepcopy(available)
        value["entries"][0]["horizons"]["T+1"]["matured"] = True
        cases.append((
            value,
            "review registry maturity_unknown horizon contradictory",
        ))
        value = copy.deepcopy(unavailable)
        value["registered_count"] = 0
        cases.append((value, "review registry unavailable counts must be null"))
        value = copy.deepcopy(unavailable)
        value["entries"] = [{}]
        cases.append((value, "review registry unavailable entries must be empty"))
        value = copy.deepcopy(unavailable)
        value["unavailable_reason"] = "none"
        cases.append((value, "review registry unavailable reason invalid"))

        with tempfile.TemporaryDirectory() as root:
            self._write_required_files(root, report_date)
            comparison_path = os.path.join(
                root, "data", "comparison-index.json"
            )
            for registry, expected in cases:
                with self.subTest(expected=expected):
                    comparison = self._comparison_index(
                        report_date, ["600001"]
                    )
                    comparison["review_registry"] = registry
                    with open(
                        comparison_path, "w", encoding="utf-8"
                    ) as handle:
                        json.dump(comparison, handle)
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        result = validate_today_report.main([
                            "--comparison-artifact-only",
                            "--docs-dir", root,
                            report_date,
                        ])
                    self.assertEqual(result, 1)
                    self.assertIn(expected, stderr.getvalue())

    def test_invalid_review_registry_warns_in_ordinary_daily_validation(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            self._write_required_files(root, report_date)
            comparison = self._comparison_index(
                report_date, ["600001"]
            )
            comparison["review_registry"] = self._available_registry(
                report_date
            )
            comparison["review_registry"]["registered_count"] = 99
            with open(
                os.path.join(root, "data", "comparison-index.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(comparison, handle)
            os.makedirs(os.path.join(root, "compare"))
            with open(
                os.path.join(root, "compare", "index.html"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write('<div id="comparisonApp"></div>')
            stderr = io.StringIO()
            with mock.patch.object(
                validate_today_report, "validate_report_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_runtime_cutover", return_value=[]
            ), mock.patch.object(
                validate_today_report, "validate_manifest_contract", return_value=[]
            ), mock.patch.object(
                validate_today_report, "fetch_market_indices", return_value={}
            ), redirect_stderr(stderr):
                result = validate_today_report.main([
                    "--docs-dir", root, report_date,
                ])

            self.assertEqual(result, 0)
            self.assertIn(
                "comparison review degraded: "
                "review registry registered_count mismatch",
                stderr.getvalue(),
            )

    def test_bad_review_registry_is_not_staged_and_head_keeps_previous_cutoff(self):
        with tempfile.TemporaryDirectory() as root:
            report_date = "2026-09-16"
            docs_dir = os.path.join(root, "docs")
            self._write_required_files(docs_dir, report_date)
            comparison_path = os.path.join(
                docs_dir, "data", "comparison-index.json"
            )
            previous = self._comparison_index("2026-09-15", ["600001"])
            with open(comparison_path, "w", encoding="utf-8") as handle:
                json.dump(previous, handle)
            subprocess.run(
                ["git", "init"], cwd=root, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "add", "docs"], cwd=root, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "git", "-c", "user.name=R0 Test",
                    "-c", "user.email=r0@example.invalid",
                    "commit", "-m", "baseline",
                ],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            report_path = os.path.join(
                docs_dir, "data", report_date + ".json"
            )
            with open(report_path, encoding="utf-8") as handle:
                report = json.load(handle)
            report["new_daily_payload"] = True
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle)
            candidate = self._comparison_index(
                report_date, ["600001"]
            )
            candidate["review_registry"] = self._available_registry(
                report_date
            )
            candidate["review_registry"]["registered_count"] = 99
            with open(comparison_path, "w", encoding="utf-8") as handle:
                json.dump(candidate, handle)

            with redirect_stderr(io.StringIO()):
                comparison_rc = validate_today_report.main([
                    "--comparison-artifact-only",
                    "--docs-dir", docs_dir,
                    report_date,
                ])
            subprocess.run(
                ["git", "add", "docs/data/" + report_date + ".json"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if comparison_rc == 0:
                subprocess.run(
                    ["git", "add", "docs/data/comparison-index.json"],
                    cwd=root,
                    check=True,
                )

            staged = subprocess.check_output(
                ["git", "diff", "--cached", "--name-only"],
                cwd=root,
                text=True,
            ).splitlines()
            previous_bytes = subprocess.check_output(
                ["git", "show", "HEAD:docs/data/comparison-index.json"],
                cwd=root,
            )

            self.assertEqual(comparison_rc, 1)
            self.assertIn("docs/data/" + report_date + ".json", staged)
            self.assertNotIn("docs/data/comparison-index.json", staged)
            self.assertEqual(
                json.loads(previous_bytes)["latest_date"], "2026-09-15"
            )


if __name__ == "__main__":
    unittest.main()
