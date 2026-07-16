import unittest
from pathlib import Path

from config import _resolve_shared_market_history_db_path


class SharedMarketHistoryPathTests(unittest.TestCase):
    def test_worktree_uses_main_repository_cache(self):
        project_root = Path(
            "/srv/ChanlunStrategy/.worktrees/feature-a"
        )

        result = _resolve_shared_market_history_db_path(project_root)

        self.assertEqual(
            result,
            "/srv/ChanlunStrategy/.cache/chanlun/market_history.sqlite",
        )

    def test_normal_checkout_keeps_its_repository_cache(self):
        project_root = Path("/volume1/web/chanlun_strategy")

        result = _resolve_shared_market_history_db_path(project_root)

        self.assertEqual(
            result,
            "/volume1/web/chanlun_strategy/.cache/chanlun/market_history.sqlite",
        )

    def test_environment_override_wins(self):
        result = _resolve_shared_market_history_db_path(
            Path("/srv/ChanlunStrategy/.worktrees/feature-a"),
            override="/data/shared/market.sqlite",
        )

        self.assertEqual(result, "/data/shared/market.sqlite")


if __name__ == "__main__":
    unittest.main()
