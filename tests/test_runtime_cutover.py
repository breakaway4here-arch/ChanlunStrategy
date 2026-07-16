import unittest
from pathlib import Path

import config
from run import _apply_recall_publish_mode
from scripts.validate_today_report import validate_runtime_cutover


class RuntimeCutoverTest(unittest.TestCase):
    def test_shadow_keeps_new_candidates_out_of_published_main(self):
        pure = [
            {"code": "000001", "source_channel": "low_position"},
            {"code": "000002", "source_channel": "low_position"},
            {"code": "000003", "source_channel": "trend"},
        ]
        fusion = [
            {"code": "000001", "source_channel": "low_position"},
            {"code": "000003", "source_channel": "trend"},
        ]

        published_pure, published_fusion, diagnostics = (
            _apply_recall_publish_mode(
                pure,
                fusion,
                legacy_codes={"000001", "000003"},
                mode="shadow",
            )
        )

        self.assertEqual(["000001"], [row["code"] for row in published_pure])
        self.assertEqual(["000001"], [row["code"] for row in published_fusion])
        self.assertFalse(diagnostics["new_strategy_controls_publish"])
        self.assertEqual(["000002", "000003"], diagnostics["suppressed_codes"])

    def test_active_mode_publishes_new_strategy_unchanged(self):
        pure = [{"code": "000002", "source_channel": "trend"}]
        fusion = [{"code": "000003", "source_channel": "trend"}]

        published_pure, published_fusion, diagnostics = (
            _apply_recall_publish_mode(
                pure, fusion, legacy_codes=set(), mode="active"
            )
        )

        self.assertIs(published_pure[0], pure[0])
        self.assertIs(published_fusion[0], fusion[0])
        self.assertTrue(diagnostics["new_strategy_controls_publish"])

    def test_cutover_validator_requires_sqlite_funnel_and_shadow_boundary(self):
        report = {
            "data_quality": {
                "runtime_policy": {
                    "market_history_cutover_mode": "sqlite",
                    "recall_strategy_mode": "shadow",
                    "decision_semantics": "v2_missing_position_is_observe",
                }
            },
            "diagnostics": {
                "candidate_funnel": {"persist_status": "saved"},
                "recall_shadow": {
                    "mode": "shadow",
                    "new_strategy_controls_publish": False,
                },
            },
        }
        self.assertEqual([], validate_runtime_cutover(report))

        report["diagnostics"]["recall_shadow"][
            "new_strategy_controls_publish"
        ] = True
        self.assertIn(
            "shadow mode cannot let new strategy control publish",
            validate_runtime_cutover(report),
        )

    def test_defaults_and_daily_runner_are_safe_for_shadow_publish(self):
        self.assertEqual("sqlite", config.MARKET_HISTORY_CUTOVER_MODE)
        self.assertEqual("shadow", config.RECALL_STRATEGY_MODE)
        script = Path("daily_run.sh").read_text(encoding="utf-8")
        self.assertIn("CHANLUN_MARKET_DATA_MODE:=sqlite", script)
        self.assertIn("CHANLUN_RECALL_STRATEGY_MODE:=shadow", script)


if __name__ == "__main__":
    unittest.main()
