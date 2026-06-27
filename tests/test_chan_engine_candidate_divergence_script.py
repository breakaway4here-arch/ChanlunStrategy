import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ChanEngineCandidateDivergenceScriptTests(unittest.TestCase):
    def test_script_can_run_divergence_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidate_divergence.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_chan_engine_dual.py",
                    "--candidate",
                    "divergence",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("wrote", completed.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["candidate"], "divergence")
            self.assertTrue(payload["summary"]["all_equal"])


if __name__ == "__main__":
    unittest.main()
