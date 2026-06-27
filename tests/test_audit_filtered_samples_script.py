import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from scripts.audit_filtered_samples import main
import unittest


class AuditFilteredSamplesScriptTests(TestCase):
    @patch("scripts.audit_filtered_samples.build_filtered_sample_audit")
    def test_script_writes_json_and_markdown(self, build_audit_mock):
        payload = {
            "experiment": "signal_delay1_by_type_guard",
            "summary": {
                "filtered": 2,
                "return_summary": {
                    "n": 2,
                    "t3_mean": 12.0,
                    "t3_win_rate": 100.0,
                },
            },
            "top_winners": [
                {
                    "date": "2026-01-03",
                    "version": "picks_pure",
                    "code": "000001",
                    "name": "AAA",
                    "type": "底背驰候选",
                    "t3_close_pct": 15.0,
                    "confirmations": ["止跌结构", "EMA5收复"],
                    "distance_from_reference_pct": 2.1,
                },
                {
                    "date": "2026-01-04",
                    "version": "picks_fusion",
                    "code": "000002",
                    "name": "BBB",
                    "type": "底背驰候选",
                    "t3_close_pct": 9.0,
                    "confirmations": ["EMA5收复", "关键位不破"],
                    "distance_from_reference_pct": 7.2,
                },
            ],
            "by_type": {
                "底背驰候选": {"n": 2, "t3_mean": 12.0},
            },
            "by_signal_tier": {
                "candidate": {"n": 2, "t3_mean": 12.0},
            },
            "by_confirmations": {
                "EMA5收复+止跌结构": {"n": 1, "t3_mean": 15.0},
                "EMA5收复+关键位不破": {"n": 1, "t3_mean": 9.0},
            },
            "by_distance_bucket": {
                "0-3%": {"n": 1, "t3_mean": 15.0},
                "6-10%": {"n": 1, "t3_mean": 9.0},
            },
        }
        build_audit_mock.return_value = payload

        with tempfile.TemporaryDirectory() as tmpdir:
            json_output = Path(tmpdir) / "filtered_audit.json"
            md_output = Path(tmpdir) / "filtered_audit.md"

            code = main(
                [
                    "--experiment",
                    "signal_delay1_by_type_guard",
                    "--output-json",
                    str(json_output),
                    "--output-md",
                    str(md_output),
                ]
            )

            md_text = md_output.read_text(encoding="utf-8")
            self.assertIn("Filtered Sample Audit", md_text)
            self.assertIn("By Signal Tier", md_text)
            self.assertIn("By Confirmations", md_text)
            self.assertIn("picks_pure", md_text)
            self.assertEqual(code, 0)
            saved = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(saved["experiment"], "signal_delay1_by_type_guard")
            self.assertEqual(saved["summary"]["filtered"], 2)
            self.assertEqual(len(saved["top_winners"]), 2)

    def test_unknown_experiment_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_output = Path(tmpdir) / "filtered_audit.json"
            md_output = Path(tmpdir) / "filtered_audit.md"
            code = main(
                [
                    "--experiment",
                    "not_exists",
                    "--output-json",
                    str(json_output),
                    "--output-md",
                    str(md_output),
                ]
            )
            self.assertNotEqual(code, 0)

    def test_unsupported_experiment_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_output = Path(tmpdir) / "filtered_audit.json"
            md_output = Path(tmpdir) / "filtered_audit.md"
            code = main(
                [
                    "--experiment",
                    "signal_v1",
                    "--output-json",
                    str(json_output),
                    "--output-md",
                    str(md_output),
                ]
            )
            self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
