import unittest

from chanlun.report_view_model import build_workspace


class TestH4ProductionBoundary(unittest.TestCase):

    def test_unattested_h4_shadow_pool_is_not_exposed_in_daily_views(self):
        workspace = build_workspace(
            {
                "h4_t3_pool": {
                    "mode": "shadow",
                    "production_attested": False,
                    "reason": "development-only H4 evidence",
                    "candidates": [],
                }
            }
        )

        self.assertNotIn("h4_t3", workspace["view_order"])
        self.assertNotIn("h4_t3", workspace["views"])


if __name__ == "__main__":
    unittest.main()
