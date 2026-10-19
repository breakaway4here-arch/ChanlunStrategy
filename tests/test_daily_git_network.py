import os
import signal
import subprocess
import tempfile
import time
import unittest
import importlib.util
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DailyGitNetworkTests(unittest.TestCase):
    def test_explicit_main_push_preserves_daily_default_and_recovers_third_attempt(self):
        spec = importlib.util.spec_from_file_location("git_transport", ROOT / "scripts/run_daily_git_network.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        commands = []
        def attempt(command, _timeout):
            commands.append(command)
            return 0 if len(commands) == 3 else 1
        with patch.object(helper, "run_attempt", side_effect=attempt), patch.object(helper.time, "sleep"):
            self.assertEqual(helper.main(["push", "--push-ref", "a" * 40 + ":refs/heads/main"]), 0)
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[-1][-3:], ["push", "origin", "a" * 40 + ":refs/heads/main"])
        with patch.object(helper, "run_attempt", return_value=0) as run:
            self.assertEqual(helper.main(["push"]), 0)
        self.assertEqual(run.call_args[0][0][-1:], ["push"])

    def run_hanging_git(self, interrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            executable = base / "git"
            pid_file = base / "pid"
            child_source = (
                "import os,signal,time\n"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                "with open(os.environ['TEST_GIT_PID'],'a') as out:\n"
                "    out.write(str(os.getppid())+' '+str(os.getpid())+'\\n')\n"
                "time.sleep(30)\n"
            )
            executable.write_text(
                "#!/usr/bin/python3\nimport subprocess,time\n"
                "subprocess.Popen(['/usr/bin/python3','-c'," + repr(child_source) + "])\n"
                "time.sleep(30)\n")
            executable.chmod(0o755)
            env = dict(os.environ, PATH=directory+":"+os.environ["PATH"], TEST_GIT_PID=str(pid_file))
            command = ["/usr/bin/python3", str(ROOT / "scripts/run_daily_git_network.py"),
                       "fetch", "--rounds", "1", "--timeout-seconds", "1" if not interrupt else "10",
                       "--retry-delay-seconds", "0"]
            process = subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            try:
                if interrupt:
                    deadline = time.monotonic() + 3
                    while not pid_file.exists() or not pid_file.read_text().strip():
                        self.assertLess(time.monotonic(), deadline, "fake Git helper never became ready")
                        time.sleep(0.01)
                    process.send_signal(signal.SIGTERM)
                # Every helper inherits these pipes. A leaked helper that ignores TERM
                # keeps them open, so communicate cannot finish until it is killed.
                stdout, stderr = process.communicate(timeout=6)
                self.assertEqual(process.returncode, 143 if interrupt else 124, stdout + stderr)
                self.assertEqual(process.wait(timeout=1), process.returncode)
                if not interrupt:
                    self.assertIn("deadline", stdout + stderr)
                pids = [int(value) for value in pid_file.read_text().split()]
                self.assertEqual(len(pids), 2 if interrupt else 4, stdout + stderr)
            finally:
                # On assertion/timeout failure, clean only groups recorded by this test.
                pairs = pid_file.read_text().splitlines() if pid_file.exists() else []
                for pair in pairs:
                    try:
                        os.killpg(int(pair.split()[0]), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=3)

    def test_hanging_git_attempt_has_deadline_and_is_reaped(self):
        self.run_hanging_git()

    def test_interrupted_git_attempt_reaps_transport_helpers(self):
        self.run_hanging_git(interrupt=True)

    def test_invalid_retry_budget_never_calls_git(self):
        command = ["/usr/bin/python3", str(ROOT / "scripts/run_daily_git_network.py"), "fetch", "--rounds", "100"]
        result = subprocess.run(command, text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertIn("between 1 and 3", result.stderr)


if __name__ == "__main__":
    unittest.main()
