import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scripts.run_engine_experiments import main


class EngineExperimentRunnerScriptTests(TestCase):
    def _run_script(self, experiments: str, json_output: Path, md_output: Path):
        return subprocess.run(
            [
                sys.executable,
                "scripts/run_engine_experiments.py",
                "--experiments",
                experiments,
                "--output-json",
                str(json_output),
                "--output-md",
                str(md_output),
            ],
            capture_output=True,
            text=True,
        )

    def test_script_generates_batch_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_output = Path(tmpdir) / "engine_experiments.json"
            md_output = Path(tmpdir) / "engine_experiments.md"
            completed = self._run_script(
                "signal_p0_distance_guard,signal_p0_p1_guard",
                json_output,
                md_output,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertIn("experiments", payload)
            self.assertEqual(len(payload["experiments"]), 2)

            first = payload["experiments"][0]
            self.assertIn("experiment", first)
            self.assertIn("risk", first)
            self.assertIn("recommendation_diff", first)
            self.assertIn("return_metrics", first)
            self.assertIn("coverage", first)
            self.assertIn("gate_result", first)

            md_text = md_output.read_text(encoding="utf-8")
            self.assertIn("ChanLun Engine Experiment Report", md_text)
            self.assertIn("signal_p0_distance_guard", md_text)
            self.assertIn("signal_p0_p1_guard", md_text)

            lines = md_text.splitlines()
            guard_line = next(
                line for line in lines if line.strip().startswith("| signal_p0_distance_guard ")
            )
            guard2_line = next(
                line for line in lines if line.strip().startswith("| signal_p0_p1_guard ")
            )
            guard_columns = [cell.strip() for cell in guard_line.strip().strip("|").split("|")]
            guard2_columns = [cell.strip() for cell in guard2_line.strip().strip("|").split("|")]
            self.assertEqual(guard_columns[3], "0")
            self.assertEqual(guard2_columns[3], "0")

    def test_gates_not_fail_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_output = Path(tmpdir) / "engine_experiments.json"
            md_output = Path(tmpdir) / "engine_experiments.md"
            completed = self._run_script("signal_p0_distance_guard", json_output, md_output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(json_output.read_text(encoding="utf-8"))
            result = payload["experiments"][0]["gate_result"]
            self.assertEqual(result["final_decision"], "insufficient_data")
            self.assertTrue(
                any("coverage.evaluated" in reason for reason in result["reason"]),
            )

    def test_unknown_experiment_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_output = Path(tmpdir) / "engine_experiments.json"
            md_output = Path(tmpdir) / "engine_experiments.md"
            completed = self._run_script("not_exists", json_output, md_output)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("unknown experiment", completed.stderr + completed.stdout)

    def test_write_failure_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "engine_experiments.json"
            output_md = Path(tmpdir) / "engine_experiments.md"
            with patch("scripts.run_engine_experiments._write_outputs", side_effect=OSError("blocked")):
                code = main(
                    [
                        "--experiments",
                        "signal_p0_distance_guard",
                        "--output-json",
                        str(output_json),
                        "--output-md",
                        str(output_md),
                    ]
                )
                self.assertEqual(code, 1)
