"""Optional post-publication performance update keeps reports usable on failure."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun import report_generator


class SelectionPerformancePublishTests(unittest.TestCase):
    def _published_output(self, root, day):
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / f"{day}.json").write_text('{}', encoding="utf-8")
        (root / "data" / "comparison-index.json").write_text('{}', encoding="utf-8")
        archive = root / day / "index.html"
        archive.parent.mkdir(exist_ok=True)
        archive.write_text("<html>published</html>", encoding="utf-8")

    def _dataset(self, day, evaluation, dataset_id):
        return {"schema_version": "selection-performance-v1", "dataset_id": dataset_id,
                "report_as_of": day, "evaluation_as_of": evaluation,
                "horizons": [1, 3, 5, 10, 20, 30], "observations": []}

    def test_success_writes_only_derived_dated_result_after_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = "2026-10-09"
            asof = "2026-10-09T15:20:00+08:00"
            self._published_output(root, day)
            original = (root / "data" / f"{day}.json").read_bytes()
            with mock.patch.object(report_generator, "build_selection_performance",
                                   return_value=self._dataset(day, asof, "one")) as build:
                result = report_generator.refresh_selection_performance_after_publish(
                    root, "read-only-market.sqlite", day, asof)
            self.assertEqual(result["status"], "ready")
            build.assert_called_once_with(
                root / "data", "read-only-market.sqlite", day, asof,
                price_evidence_dir=(Path("read-only-market.sqlite").resolve().parent /
                                    "selection-price-evidence"),
                price_evidence_as_of=mock.ANY,
            )
            derived = root / "data" / "selection-performance"
            self.assertEqual(json.loads((derived / f"{day}.json").read_text())["dataset_id"], "one")
            self.assertEqual(json.loads((derived / "index.json").read_text())["dates"], [day])
            self.assertEqual((root / "data" / f"{day}.json").read_bytes(), original)

    def test_failure_preserves_old_derived_bytes_and_records_safe_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = "2026-10-09"
            asof = "2026-10-09T15:20:00+08:00"
            self._published_output(root, day)
            with mock.patch.object(report_generator, "build_selection_performance",
                                   return_value=self._dataset(day, asof, "one")):
                report_generator.refresh_selection_performance_after_publish(
                    root, "read-only-market.sqlite", day, asof)
            derived = root / "data" / "selection-performance"
            original = (derived / f"{day}.json").read_bytes()
            with mock.patch.object(report_generator, "build_selection_performance",
                                   side_effect=RuntimeError("/private/secret token")):
                result = report_generator.refresh_selection_performance_after_publish(
                    root, "read-only-market.sqlite", day, asof)
            self.assertEqual(result["status"], "update_failed")
            self.assertEqual((derived / f"{day}.json").read_bytes(), original)
            state = json.loads((derived / "status.json").read_text())
            self.assertEqual(state["last_success"]["dataset_id"], "one")
            self.assertNotIn("secret", json.dumps(state))

    def test_manifest_write_failure_restores_exact_prior_derived_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = "2026-10-09"
            asof = "2026-10-09T15:20:00+08:00"
            self._published_output(root, day)
            with mock.patch.object(report_generator, "build_selection_performance",
                                   return_value=self._dataset(day, asof, "one")):
                report_generator.refresh_selection_performance_after_publish(
                    root, "read-only-market.sqlite", day, asof)
            derived = root / "data" / "selection-performance"
            dated = derived / f"{day}.json"
            index = derived / "index.json"
            dated.write_bytes(dated.read_bytes() + b"\n")
            dated_before, index_before = dated.read_bytes(), index.read_bytes()
            writer = report_generator._write_derived_json_atomically
            def fail_index(path, value):
                if Path(path) == index:
                    raise OSError("simulated index write failure")
                return writer(path, value)
            with mock.patch.object(report_generator, "build_selection_performance",
                                   return_value=self._dataset(day, asof, "two")), \
                    mock.patch.object(report_generator, "_write_derived_json_atomically",
                                      side_effect=fail_index):
                result = report_generator.refresh_selection_performance_after_publish(
                    root, "read-only-market.sqlite", day, asof)
            self.assertEqual(result["status"], "update_failed")
            self.assertEqual(dated.read_bytes(), dated_before)
            self.assertEqual(index.read_bytes(), index_before)

    def test_post_close_hook_requires_real_published_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                report_generator.refresh_selection_performance_after_publish(
                    root, "read-only-market.sqlite", "2026-10-09",
                    "2026-10-09T15:20:00+08:00")
            self.assertFalse((root / "data" / "selection-performance").exists())

    def test_generator_runs_optional_step_only_after_official_close(self):
        day = "2026-10-09"
        asof = "2026-10-09T15:20:00+08:00"
        base = {"date": day, "market": {"沪深300": {"close": 4529.1}},
                "picks_fusion": [], "data_quality": {
                    "is_trading_day": True, "is_official": True,
                    "bar_state": "closed", "as_of": asof}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(report_generator, "build_selection_performance",
                                   return_value=self._dataset(day, asof, "close")) as build:
                report_generator.generate_report(base, output_dir=root,
                                                 comparison_db_path="read-only-market.sqlite")
            self.assertEqual(build.call_count, 1)
            self.assertTrue((root / "data" / "selection-performance" /
                             f"{day}.json").is_file())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intraday = json.loads(json.dumps(base))
            intraday["data_quality"]["bar_state"] = "intraday"
            with mock.patch.object(report_generator, "build_selection_performance") as build:
                report_generator.generate_report(intraday, output_dir=root,
                                                 comparison_db_path="read-only-market.sqlite")
            build.assert_not_called()
            self.assertFalse((root / "data" / "selection-performance").exists())

    def test_old_shell_asset_refresh_adds_performance_resources_once(self):
        old = ('<!doctype html><link href="assets/report-v2.css?v=old" rel="stylesheet">'
               '<script>window.CHANLUN_BOOTSTRAP={"note":"assets/report-v2.js"};</script>'
               '<script src="assets/report-v2.js?v=old" defer></script>')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text(old, encoding="utf-8")
            report_generator.refresh_report_asset_versions(root, "a" * 12)
            current = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn('assets/selection-performance.css?v=' + 'a' * 12, current)
            self.assertIn('assets/selection-performance.js?v=' + 'a' * 12, current)
            self.assertLess(current.index('assets/selection-performance.js?v='),
                            current.index('src="assets/report-v2.js?v='))
            self.assertIn('window.CHANLUN_BOOTSTRAP={"note":"assets/report-v2.js"}', current)
            report_generator.refresh_report_asset_versions(root, "a" * 12)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), current)


if __name__ == "__main__":
    unittest.main()
