import plistlib
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OpeningTemplateTests(unittest.TestCase):
    def test_template_is_once_per_weekday_without_run_at_load(self):
        path = ROOT / "launchd/com.breakaway4here.chanlun-opening-limitup.plist"
        self.assertTrue(path.is_file())
        body = plistlib.loads(path.read_bytes())
        self.assertFalse(body["RunAtLoad"])
        self.assertIn("--scheduled", body["ProgramArguments"])
        self.assertIn("--send", body["ProgramArguments"])
        self.assertEqual(body["StartCalendarInterval"], [{"Weekday": d, "Hour": 9, "Minute": 40} for d in range(1, 6)])
        self.assertNotIn("KeepAlive", body)

    def test_new_runtime_is_independent_and_uses_existing_readonly_calendar(self):
        body = plistlib.loads((ROOT/"launchd/com.breakaway4here.chanlun-opening-limitup.plist").read_bytes())
        runtime="/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/opening-limitup-runtime"
        self.assertEqual(body["WorkingDirectory"],runtime)
        self.assertEqual(body["ProgramArguments"][1],runtime+"/scripts/opening_limitup_run.sh")
        index=body["ProgramArguments"].index("--market-db")
        self.assertEqual(body["ProgramArguments"][index+1],"/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime/.cache/chanlun/market_history.sqlite")
        installer=(ROOT/"scripts/opening_limitup_install_launchd.sh").read_text()
        self.assertIn('RUNTIME="'+runtime+'"',installer)

    def test_wrapper_preserves_explicit_dryrun_and_installer_defaults_to_preview(self):
        wrapper = ROOT / "scripts/opening_limitup_run.sh"
        installer = ROOT / "scripts/opening_limitup_install_launchd.sh"
        self.assertTrue(wrapper.is_file()); self.assertTrue(installer.is_file())
        result = subprocess.run(["/bin/zsh", str(wrapper), "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(["/bin/zsh", str(installer)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("仅预览，未安装", result.stdout)


if __name__ == "__main__": unittest.main()
