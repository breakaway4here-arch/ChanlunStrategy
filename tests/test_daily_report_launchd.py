import copy
import importlib.util
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.chanlun.daily-report"
RUNTIME = "/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime"


class DailyReportLaunchdTests(unittest.TestCase):
    def template(self):
        with (ROOT / "launchd" / (LABEL + ".plist")).open("rb") as handle:
            return plistlib.load(handle)

    def updater(self):
        spec = importlib.util.spec_from_file_location("daily_launchd_updater", ROOT / "scripts/update_daily_report_launchd.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_finite_weekday_schedule_is_at_four_close_times(self):
        data = self.template()
        self.assertEqual(data["Label"], LABEL)
        self.assertEqual(data["ProgramArguments"], ["/bin/zsh", "-l", "-c", RUNTIME + "/daily_run.sh"])
        self.assertEqual(data["WorkingDirectory"], RUNTIME)
        expected = {(day, 15, minute) for day in range(1, 6) for minute in (5,20,35,50)}
        self.assertEqual({(r["Weekday"],r["Hour"],r["Minute"]) for r in data["StartCalendarInterval"]}, expected)
        self.assertEqual(len(data["StartCalendarInterval"]), 20)
        self.assertFalse(data["RunAtLoad"])
        self.assertFalse(data.get("KeepAlive", False))
        self.assertNotIn("StartInterval", data)
        self.assertEqual(data["EnvironmentVariables"]["TZ"], "Asia/Shanghai")

    def test_prepare_preserves_installed_environment_and_logs(self):
        template = self.template()
        installed = copy.deepcopy(template)
        installed["EnvironmentVariables"] = {"PRIVATE_SETTING":"sensitive-value", "TZ":"UTC"}
        installed["StandardOutPath"] = "/custom/log"
        installed["StartCalendarInterval"] = [{"Weekday":1,"Hour":15,"Minute":5}]
        before = copy.deepcopy(installed)
        candidate = self.updater().prepare_update(template, installed, host_timezone="Asia/Shanghai")
        self.assertEqual(installed, before)
        self.assertEqual(candidate["EnvironmentVariables"], {"PRIVATE_SETTING":"sensitive-value", "TZ":"Asia/Shanghai"})
        self.assertEqual(candidate["StandardOutPath"], "/custom/log")
        self.assertEqual(candidate["StartCalendarInterval"], template["StartCalendarInterval"])

    def test_wrong_timezone_or_runtime_is_rejected(self):
        template = self.template()
        updater = self.updater()
        with self.assertRaises(ValueError):
            updater.prepare_update(template, template, host_timezone="UTC")
        wrong = copy.deepcopy(template)
        wrong["ProgramArguments"][-1] = "/other/daily_run.sh"
        with self.assertRaises(ValueError):
            updater.prepare_update(template, wrong, host_timezone="Asia/Shanghai")

    def test_candidate_cli_never_writes_installed_plist_or_overwrites_output(self):
        template = self.template()
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "installed.plist"
            output = Path(directory) / "candidate.plist"
            template["EnvironmentVariables"]["PRIVATE_SETTING"] = "sensitive-value"
            installed.write_bytes(plistlib.dumps(template))
            before = installed.read_bytes()
            command = ["/usr/bin/python3", str(ROOT / "scripts/update_daily_report_launchd.py"),
                       "--installed", str(installed), "--output", str(output)]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(installed.read_bytes(), before)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("sensitive-value", result.stdout + result.stderr)
            candidate = output.read_bytes()
            second = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), candidate)
            self.assertEqual(installed.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
