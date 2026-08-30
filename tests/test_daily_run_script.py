import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(ROOT, "daily_run.sh")


class TestDailyRunScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            cls.script = handle.read()

    def test_remote_is_synchronized_before_journal_prepare_and_generation(self):
        main_start = self.script.index("main() {")
        preflight = self.script.index("if ! preflight_formal_publish_state; then", main_start)
        sync_call = self.script.index("if ! sync_with_remote; then", preflight)
        prepare = self.script.index("if ! prepare_formal_publish_state; then", sync_call)
        ready_check = self.script.index("if is_today_output_ready; then", prepare)

        self.assertLess(preflight, sync_call)
        self.assertLess(sync_call, prepare)
        self.assertLess(prepare, ready_check)

    def test_daily_analysis_defaults_to_local_codex_cli(self):
        self.assertIn("CHANLUN_LLM_PROVIDER:=codex", self.script)
        self.assertIn("CHANLUN_CODEX_MODEL:=gpt-5.6-luna", self.script)
        self.assertIn("export CHANLUN_LLM_PROVIDER", self.script)
        self.assertIn("export CHANLUN_CODEX_MODEL", self.script)

    def test_ready_output_path_retries_pending_commits(self):
        ready_check = self.script.index("if is_today_output_ready; then")
        generation_start = self.script.index(
            "export CHANLUN_DAILY_RETRY_MISSING_ONLY",
            ready_check,
        )
        ready_block = self.script[ready_check:generation_start]

        self.assertIn("publish_ready_report", ready_block)
        self.assertIn("--needs-sublevel-retry", ready_block)
        self.assertIn("分钟级研究输入仍缺失", ready_block)

    def test_main_runs_only_after_all_called_functions_are_defined(self):
        self.assertGreater(
            self.script.rfind('main "$@"'),
            self.script.index("publish_ready_report() {"),
        )

    def test_publish_guard_prepares_before_paths_and_records_generated_retry_hashes(self):
        self.assertIn("prepare_formal_publish_state() {", self.script)
        self.assertIn("record_formal_publish_targets() {", self.script)
        self.assertIn("scripts/formal_publish_guard.py prepare", self.script)
        self.assertIn("scripts/formal_publish_guard.py record", self.script)
        self.assertIn('--journal-path "$FORMAL_PUBLISH_JOURNAL_PATH"', self.script)
        main_start = self.script.index("main() {")
        preflight_call = self.script.index(
            "if ! preflight_formal_publish_state; then",
            main_start,
        )
        sync_call = self.script.index("if ! sync_with_remote; then", preflight_call)
        prepare_call = self.script.index("if ! prepare_formal_publish_state; then", sync_call)
        ready_check = self.script.index("if is_today_output_ready; then", prepare_call)
        run_command = self.script.index("if /usr/bin/python3 -c", ready_check)
        record_call = self.script.index(
            "if ! record_formal_publish_targets; then",
            run_command,
        )
        run_status = self.script.index("if [ $run_status -eq 0 ]; then", record_call)
        final_validation = self.script.index(
            'if ! /usr/bin/python3 scripts/validate_today_report.py "$TODAY"; then',
            run_status,
        )
        self.assertLess(preflight_call, sync_call)
        self.assertLess(sync_call, prepare_call)
        self.assertLess(prepare_call, ready_check)
        self.assertLess(run_command, record_call)
        self.assertLess(record_call, run_status)
        self.assertLess(run_status, final_validation)

    def test_automatic_sync_is_fast_forward_only(self):
        self.assertIn("sync_with_remote() {", self.script)
        sync_start = self.script.index("sync_with_remote() {")
        sync_end = self.script.index("\n}\n", sync_start)
        sync_body = self.script[sync_start:sync_end]

        self.assertIn("fetch_with_proxy_fallback", sync_body)
        self.assertIn("merge-base --is-ancestor", sync_body)
        self.assertIn("merge --ff-only", sync_body)
        self.assertIn("git status --porcelain=v1 --untracked-files=all", sync_body)
        self.assertIn("运行目录含未提交内容，拒绝在正式重试期间快进", sync_body)
        self.assertNotIn("reset --hard", sync_body)
        self.assertNotIn("pull --rebase", sync_body)

    def test_finalized_ledger_status_is_rebuilt_into_public_snapshot(self):
        self.assertIn("finalize_review_snapshot() {", self.script)
        self.assertIn(
            "scripts/repair_strategy_scorecard_snapshot.py",
            self.script,
        )
        finalizer = self.script.rfind(
            '/usr/bin/python3 scripts/finalize_recommendation_ledger.py "$TODAY"'
        )
        repair = self.script.rfind("if ! finalize_and_record_review_snapshot; then")
        publish = self.script.rfind("if ! publish_ready_report; then")
        self.assertLess(finalizer, repair)
        self.assertLess(repair, publish)

        wrapper_start = self.script.index("finalize_and_record_review_snapshot() {")
        wrapper_end = self.script.index("\n}\n", wrapper_start)
        wrapper = self.script[wrapper_start:wrapper_end]
        self.assertLess(
            wrapper.index("if finalize_review_snapshot; then"),
            wrapper.index("if ! record_formal_publish_targets; then"),
        )


if __name__ == "__main__":
    unittest.main()
