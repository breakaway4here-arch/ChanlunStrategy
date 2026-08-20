import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(ROOT, "daily_run.sh")


class TestDailyRunScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            cls.script = handle.read()

    def test_remote_is_synchronized_before_ready_output_can_short_circuit(self):
        self.assertIn("if ! sync_with_remote; then", self.script)
        sync_call = self.script.index("if ! sync_with_remote; then")
        ready_check = self.script.index("if is_today_output_ready; then")

        self.assertLess(sync_call, ready_check)

    def test_ready_output_path_retries_pending_commits(self):
        ready_check = self.script.index("if is_today_output_ready; then")
        generation_start = self.script.index(
            "export CHANLUN_DAILY_RETRY_MISSING_ONLY",
            ready_check,
        )
        ready_block = self.script[ready_check:generation_start]

        self.assertIn("push_pending_commits", ready_block)

    def test_automatic_sync_is_fast_forward_only(self):
        self.assertIn("sync_with_remote() {", self.script)
        sync_start = self.script.index("sync_with_remote() {")
        sync_end = self.script.index("\n}\n", sync_start)
        sync_body = self.script[sync_start:sync_end]

        self.assertIn("fetch_with_proxy_fallback", sync_body)
        self.assertIn("merge-base --is-ancestor", sync_body)
        self.assertIn("merge --ff-only", sync_body)
        self.assertNotIn("reset --hard", sync_body)
        self.assertNotIn("pull --rebase", sync_body)


if __name__ == "__main__":
    unittest.main()
