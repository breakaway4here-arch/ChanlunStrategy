import unittest
import os
from pathlib import Path
import subprocess
import sys

import config
from run import (
    _apply_recall_publish_mode,
    _refresh_active_universe_quality,
)
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

    def test_cutover_validator_requires_active_strategy_to_control_publish(self):
        report = {
            "data_quality": {
                "runtime_policy": {
                    "market_history_cutover_mode": "sqlite",
                    "recall_strategy_mode": "active",
                    "decision_semantics": "v2_missing_position_is_observe",
                }
            },
            "diagnostics": {
                "candidate_funnel": {"persist_status": "saved"},
                "recall_shadow": {
                    "mode": "active",
                    "new_strategy_controls_publish": False,
                },
            },
        }

        self.assertIn(
            "active mode requires new strategy to control publish",
            validate_runtime_cutover(report),
        )
        report["diagnostics"]["recall_shadow"][
            "new_strategy_controls_publish"
        ] = True
        self.assertEqual([], validate_runtime_cutover(report))

    def test_defaults_and_daily_runner_publish_new_strategy(self):
        self.assertEqual("sqlite", config.MARKET_HISTORY_CUTOVER_MODE)
        self.assertEqual("active", config.RECALL_STRATEGY_MODE)
        self.assertEqual("shadow", config.HIGH_RETURN_SELECTION_MODE)
        script = Path("daily_run.sh").read_text(encoding="utf-8")
        self.assertIn("CHANLUN_MARKET_DATA_MODE:=sqlite", script)
        self.assertIn("CHANLUN_RECALL_STRATEGY_MODE:=active", script)
        self.assertIn("CHANLUN_HIGH_RETURN_SELECTION_MODE:=shadow", script)

    def test_high_return_active_mode_is_blocked_until_runtime_attestation_exists(self):
        env = dict(os.environ)
        env["CHANLUN_HIGH_RETURN_SELECTION_MODE"] = "active"

        completed = subprocess.run(
            [sys.executable, "-c", "import config"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("runtime OOT cutover manifest", completed.stderr)

    def test_active_universe_quality_uses_the_actual_published_pool(self):
        quality = {
            "bar_state": "closed",
            "market_status": "verified",
            "sources_trusted": True,
            "stock_pool_incomplete": False,
            "stale_stock_count": 3,
            "missing_daily_count": 63,
            "is_official": False,
        }
        selected = [
            {
                "code": "600000",
                "data_status": {
                    "daily": "verified",
                    "latest_date": "2026-07-16",
                    "source": "market_history_db",
                },
            }
        ]

        _refresh_active_universe_quality(
            quality,
            selected,
            "2026-07-16",
        )

        self.assertEqual(0, quality["stale_stock_count"])
        self.assertEqual(0, quality["missing_daily_count"])
        self.assertTrue(quality["is_official"])
        self.assertEqual(
            "active_retrieval_pool",
            quality["official_pool_scope"],
        )


if __name__ == "__main__":
    unittest.main()
