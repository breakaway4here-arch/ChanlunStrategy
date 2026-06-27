import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ChanEngineDualScriptTests(unittest.TestCase):
    def test_script_writes_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dual_compare.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_chan_engine_dual.py",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("wrote", completed.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("scenarios", payload)
            self.assertGreaterEqual(len(payload["scenarios"]), 5)
            self.assertTrue(payload["summary"]["all_equal"])


if __name__ == "__main__":
    unittest.main()
