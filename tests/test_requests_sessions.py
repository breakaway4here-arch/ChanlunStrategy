import unittest

from chanlun import data_fetcher


class TestRequestsSessions(unittest.TestCase):

    def test_daily_report_sessions_ignore_system_proxy(self):
        self.assertFalse(data_fetcher.SESSION.trust_env)

    def test_daily_run_bootstrap_disables_proxy_for_all_sessions(self):
        with open("daily_run.sh", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("df.SESSION.trust_env = False", content)
        self.assertIn("mn.SESSION.trust_env = False", content)
