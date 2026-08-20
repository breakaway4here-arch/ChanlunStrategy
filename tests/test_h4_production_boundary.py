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

    def test_attested_production_pool_exposes_every_candidate(self):
        candidates = [
            {
                "code": "600001",
                "name": "H4甲",
                "score": 81,
                "decision_engine_v1": {"decision_code": "observe"},
                "h4_predictions": {"pred_return": 4.2},
            },
            {
                "code": "600002",
                "name": "H4乙",
                "score": 73,
                "decision_engine_v1": {"decision_code": "observe"},
                "h4_predictions": {"pred_return": 3.1},
            },
        ]
        workspace = build_workspace(
            {
                "h4_t3_pool": {
                    "status": "ok",
                    "mode": "production",
                    "production_attested": True,
                    "reason": "all eligible",
                    "candidates": candidates,
                }
            }
        )

        self.assertIn("h4_t3", workspace["view_order"])
        self.assertEqual(
            {"600001", "600002"},
            {row["code"] for row in workspace["views"]["h4_t3"]},
        )

    def test_h4_membership_does_not_bonus_or_block_main_score(self):
        candidate = {
            "code": "600001",
            "name": "统一分主推",
            "score": 81,
            "decision_engine_v1": {
                "decision_code": "recommend",
                "decision": "推荐",
            },
            "best_buy_point": {},
        }
        baseline = build_workspace({"picks_fusion": [candidate]})
        with_h4 = build_workspace(
            {
                "picks_fusion": [candidate],
                "h4_t3_pool": {
                    "status": "ok",
                    "mode": "production",
                    "production_attested": True,
                    "candidates": [dict(candidate, h4_predictions={"pred_return": 4.2})],
                },
            }
        )

        self.assertEqual(
            baseline["views"]["main"][0]["opportunity_score"],
            with_h4["views"]["main"][0]["opportunity_score"],
        )
        self.assertEqual(
            baseline["views"]["main"][0]["action"],
            with_h4["views"]["main"][0]["action"],
        )


if __name__ == "__main__":
    unittest.main()
