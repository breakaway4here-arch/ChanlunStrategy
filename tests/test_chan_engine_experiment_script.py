import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ChanEngineExperimentScriptTests(unittest.TestCase):
    def test_script_can_run_experiment_signal_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "experiment_signal_v1.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_chan_engine_dual.py",
                    "--experiment",
                    "signal_v1",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("wrote", completed.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"].get("experiment"), "signal_v1")
            self.assertTrue(payload["summary"]["all_equal"])

    def test_script_rejects_candidate_and_experiment_together(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/compare_chan_engine_dual.py",
                "--candidate",
                "signal",
                "--experiment",
                "signal_v1",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        output = completed.stdout + completed.stderr
        self.assertIn("not allowed with argument", output)

    def test_candidate_signal_still_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidate_signal.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_chan_engine_dual.py",
                    "--candidate",
                    "signal",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("wrote", completed.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["candidate"], "signal")
            self.assertTrue(payload["summary"]["all_equal"])


if __name__ == "__main__":
    unittest.main()

