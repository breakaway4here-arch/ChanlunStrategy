import copy
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import run
from chanlun.decision_workbench import _coverage
from chanlun.market_close_snapshot import ingest_market_close_snapshot
from chanlun.market_history_store import MarketHistoryStore
from tests import test_run_shadow_integration as main_fixture
from tests.test_market_close_snapshot import _insert_legacy_stock_with_bar, _row


class IdentityPartialStandardTests(unittest.TestCase):
    def _actual_snapshot(self, healthy_count=11, include_pending=True):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        rows = [_row("600%03d" % index, "SH") for index in range(healthy_count)]
        try:
            with MarketHistoryStore(path) as store:
                for row in rows:
                    instrument_id = store.upsert_instrument(
                        "stock", "SH", row["code"], name=row["name"]
                    )
                    store.upsert_bars("day", instrument_id, [{
                        "ts": "2026-08-21", "open": 10, "high": 10.2,
                        "low": 9.8, "close": 10, "volume": 100,
                        "amount": 1000, "adjustment": "qfq", "is_final": True,
                    }])
                if include_pending:
                    _insert_legacy_stock_with_bar(store, "920001")
                    store.connection.execute(
                        "UPDATE bars_day SET ts='2026-08-21' WHERE ts='2026-09-10'"
                    )
                    store.connection.commit()
            fetched_rows = list(rows)
            if include_pending:
                fetched_rows.append(_row("920001", "BJ"))
            return ingest_market_close_snapshot(
                path,
                "2026-08-22",
                fetch_all_a_stocks=lambda **_kwargs: (
                    fetched_rows,
                    {
                        "complete": True,
                        "requested": len(fetched_rows),
                        "unique": len(fetched_rows),
                    },
                ),
                generated_at=datetime(
                    2026, 8, 22, 15, 5,
                    tzinfo=timezone(timedelta(hours=8)),
                ),
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def _capture_main(self, snapshot, *, include_pending_row=False):
        analyzed_codes = []

        def overrides(original):
            def daily(**kwargs):
                value = original["collect_daily_data"](**kwargs)
                value["data_quality"].update({
                    "is_official": True,
                    "sources_trusted": True,
                    "market_status": "verified",
                    "bar_state": "closed",
                })
                if include_pending_row:
                    pending = copy.deepcopy(value["stocks"][0])
                    pending["code"] = "920001"
                    pending["name"] = "pending-identity"
                    value["stocks"].append(pending)
                return value

            def analyze(**kwargs):
                analyzed_codes.append(str(kwargs["code"]))
                return original["analyze"](**kwargs)

            return {
                "ingest_market_close_snapshot": (
                    lambda *_args, **_kwargs: copy.deepcopy(snapshot)
                ),
                "collect_daily_data": daily,
                "analyze": analyze,
            }

        report = main_fixture.DailyShadowIntegrationTests._capture_real_main_report(
            self,
            "off",
            patch_overrides=overrides,
        )
        return report, analyzed_codes

    def test_actual_main_keeps_healthy_rows_and_discloses_identity_partial(self):
        snapshot = self._actual_snapshot(healthy_count=11)
        report, analyzed_codes = self._capture_main(
            snapshot, include_pending_row=True
        )

        self.assertEqual(snapshot["status"], "partial")
        self.assertNotIn("920001", analyzed_codes)
        self.assertNotIn("920001", [row["code"] for row in report["picks_pure"]])
        self.assertTrue(
            report["selection_input_health"]["formal"]["formal_actions_allowed"]
        )
        self.assertEqual(report["selection_input_health"]["status"], "partial")
        self.assertEqual(
            report["selection_input_health"]["market_close_snapshot"]
            ["identity_pending_codes"],
            ["920001"],
        )
        self.assertEqual(
            report["data_quality"]["market_close_snapshot"]["coverage"],
            0.916667,
        )
        formal_manifest = {
            row["strategy"]: row
            for row in report["strategy_run_manifest"]
            if row.get("evaluation_role") == "formal"
        }
        self.assertEqual(
            formal_manifest["daily_fusion"]["market_close_snapshot"]
            ["status"],
            "partial",
        )
        ui_coverage = _coverage(report)
        self.assertEqual(ui_coverage["market_close_snapshot"]["status"], "partial")
        self.assertEqual(ui_coverage["market_close_snapshot"]["pending"], 1)
        self.assertIn("identity_coverage_partial", ui_coverage["reasons"])

    def test_actual_main_healthy_snapshot_behavior_is_unchanged(self):
        snapshot = self._actual_snapshot(
            healthy_count=12, include_pending=False
        )
        report, analyzed_codes = self._capture_main(snapshot)

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["coverage"], 1.0)
        self.assertTrue(analyzed_codes)
        self.assertTrue(
            report["selection_input_health"]["formal"]["formal_actions_allowed"]
        )
        self.assertEqual(
            report["selection_input_health"]["market_close_snapshot"]["status"],
            "complete",
        )

    def test_main_blocks_below_total_floor_before_collector(self):
        snapshot = {
            "status": "insufficient_coverage",
            "reason": "valid_bar_coverage_below_floor",
            "coverage": 0.891442,
            "coverage_numerator": 5198,
            "coverage_denominator": 5831,
            "minimum_coverage": 0.9,
            "identity_pending_rows": 299,
            "identity_pending_codes": ["920001"],
            "identity_invalid_rows": 0,
        }

        def overrides(_original):
            return {
                "ingest_market_close_snapshot": (
                    lambda *_args, **_kwargs: copy.deepcopy(snapshot)
                ),
                "collect_daily_data": mock.Mock(
                    side_effect=AssertionError("collector must not run")
                ),
            }

        with self.assertRaises(run.MarketDataUnavailable):
            main_fixture.DailyShadowIntegrationTests._capture_real_main_report(
                self, "off", patch_overrides=overrides
            )

    def test_main_blocks_incomplete_source_before_collector(self):
        snapshot = {
            "status": "incomplete",
            "reason": "universe_not_complete",
            "coverage": 1.0,
            "minimum_coverage": 0.9,
            "identity_pending_rows": 0,
            "identity_pending_codes": [],
            "identity_invalid_rows": 0,
        }

        def overrides(_original):
            return {
                "ingest_market_close_snapshot": (
                    lambda *_args, **_kwargs: copy.deepcopy(snapshot)
                ),
                "collect_daily_data": mock.Mock(
                    side_effect=AssertionError("collector must not run")
                ),
            }

        with self.assertRaises(run.MarketDataUnavailable):
            main_fixture.DailyShadowIntegrationTests._capture_real_main_report(
                self, "off", patch_overrides=overrides
            )

    def test_partial_gate_uses_raw_counts_instead_of_rounded_coverage(self):
        snapshot = self._actual_snapshot(healthy_count=11)
        snapshot.update({
            "coverage": 0.9,
            "coverage_numerator": 899999,
            "coverage_denominator": 1000000,
            "identity_pending_rows": 1,
            "identity_pending_codes": ["920001"],
            "minimum_coverage": 0.9,
            "meets_minimum_coverage": True,
        })

        self.assertFalse(run._close_snapshot_allows_daily_run(snapshot))

    def test_partial_gate_requires_coherent_counts_and_ninety_percent_floor(self):
        snapshot = self._actual_snapshot(healthy_count=11)
        snapshot.update({
            "coverage_numerator": 9,
            "coverage_denominator": 10,
            "identity_pending_rows": 1,
            "identity_pending_codes": ["920001"],
            "minimum_coverage": 0.9,
            "meets_minimum_coverage": True,
        })
        self.assertTrue(run._close_snapshot_allows_daily_run(snapshot))

        snapshot["minimum_coverage"] = 0.89
        self.assertFalse(run._close_snapshot_allows_daily_run(snapshot))
        snapshot["minimum_coverage"] = 0.9
        snapshot["coverage_denominator"] = 9
        self.assertFalse(run._close_snapshot_allows_daily_run(snapshot))

    def test_legacy_complete_snapshot_gate_remains_compatible(self):
        self.assertTrue(run._close_snapshot_allows_daily_run({
            "status": "complete"
        }))


if __name__ == "__main__":
    unittest.main()
