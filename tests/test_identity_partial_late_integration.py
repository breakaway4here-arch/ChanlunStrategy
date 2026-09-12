import copy
import json
import os
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import run
from chanlun.market_close_snapshot import ingest_market_close_snapshot
from chanlun.market_history_store import MarketHistoryStore
from tests import test_run_shadow_integration as main_fixture
from tests import test_identity_partial_standard as identity_standard
from tests.test_market_close_snapshot import _insert_legacy_stock_with_bar, _row


def _artifact(name, payload):
    phase = os.environ.get("CHANLUN_R01_BOUNDARY_PHASE", "test")
    path = pathlib.Path("/private/tmp/chanlun-main-validation") / (
        "{}-{}.json".format(name, phase)
    )
    path.write_text(json.dumps(payload, indent=2) + "\n")


class IdentityPartialLateIntegrationTests(unittest.TestCase):
    def _snapshot_with_known_non_a_rows(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        rows = [_row("600%03d" % index, "SH") for index in range(11)]
        try:
            with MarketHistoryStore(path) as store:
                for row in rows:
                    instrument_id = store.upsert_instrument(
                        "stock", "SH", row["code"], name=row["name"]
                    )
                    store.upsert_bars("day", instrument_id, [{
                        "ts": "2026-09-11", "open": 10, "high": 10.2,
                        "low": 9.8, "close": 10, "volume": 100,
                        "amount": 1000, "adjustment": "qfq",
                        "is_final": True,
                    }])
                _insert_legacy_stock_with_bar(store, "920001")
                _insert_legacy_stock_with_bar(store, "900901", exchange="SH")
                _insert_legacy_stock_with_bar(store, "920999", exchange="SH")
            return ingest_market_close_snapshot(
                path,
                "2026-09-11",
                fetch_all_a_stocks=lambda **_kwargs: self.fail(
                    "DB partial fast path must not fetch"
                ),
                min_coverage=0.9,
                generated_at=datetime(
                    2026, 9, 11, 15, 5,
                    tzinfo=timezone(timedelta(hours=8)),
                ),
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_known_non_a_db_rows_do_not_block_above_floor_partial(self):
        snapshot = self._snapshot_with_known_non_a_rows()
        allows_run = run._close_snapshot_allows_daily_run(snapshot)
        _artifact("r01-known-nona-boundary", {
            "snapshot": snapshot,
            "allows_run": allows_run,
        })

        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["coverage_numerator"], 11)
        self.assertEqual(snapshot["coverage_denominator"], 12)
        self.assertEqual(snapshot["identity_pending_rows"], 1)
        self.assertEqual(snapshot["identity_invalid_rows"], 2)
        self.assertEqual(snapshot["registered_non_a_rows_ignored"], 2)
        self.assertTrue(allows_run)

    def test_late_full_a_injection_cannot_reintroduce_pending_identity(self):
        snapshot = identity_standard.IdentityPartialStandardTests._actual_snapshot(
            self, healthy_count=11
        )
        analyzed = []

        def overrides(original):
            def inject(rows, *_args, **_kwargs):
                output = list(rows)
                pending = copy.deepcopy(output[0])
                pending["code"] = "920001"
                output.append(pending)
                return output

            def analyze(**kwargs):
                analyzed.append(kwargs["code"])
                return original["analyze"](**kwargs)

            return {
                "ingest_market_close_snapshot": (
                    lambda *_args, **_kwargs: copy.deepcopy(snapshot)
                ),
                "_apply_full_a_universe": inject,
                "analyze": analyze,
                "RECALL_STRATEGY_MODE": "active",
            }

        report = main_fixture.DailyShadowIntegrationTests._capture_real_main_report(
            self, "off", patch_overrides=overrides
        )
        _artifact("r01-late-full-a-boundary", {
            "analyzed_codes": analyzed,
            "excluded_codes": report["data_quality"].get(
                "identity_pending_excluded_codes"
            ),
        })

        self.assertNotIn("920001", analyzed)
        self.assertEqual(
            report["data_quality"]["identity_pending_excluded_codes"],
            ["920001"],
        )

    def test_personal_watchlist_injection_retains_unavailable_identity_fact(self):
        snapshot = identity_standard.IdentityPartialStandardTests._actual_snapshot(
            self, healthy_count=11
        )
        analyzed = []

        def overrides(original):
            def inject(rows, *_args, **_kwargs):
                output = list(rows)
                pending = copy.deepcopy(output[0])
                pending["code"] = "920001"
                output.append(pending)
                return output, {
                    "requested_codes": ["920001"],
                    "added_codes": ["920001"],
                    "stale_codes": [],
                    "missing_codes": [],
                    "by_code": {
                        "920001": {
                            "code": "920001",
                            "evidence_date": "2026-08-22",
                            "data_status": "verified",
                            "error": "",
                        }
                    },
                }

            def analyze(**kwargs):
                analyzed.append(kwargs["code"])
                return original["analyze"](**kwargs)

            return {
                "ingest_market_close_snapshot": (
                    lambda *_args, **_kwargs: copy.deepcopy(snapshot)
                ),
                "resolve_personal_watchlist": lambda remote_url=None: (
                    {
                        "revision": "identity-test",
                        "items": [{
                            "code": "920001", "name": "pending-watch",
                            "enabled": True,
                        }],
                    },
                    {"status": "ok", "revision": "identity-test"},
                ),
                "ensure_watchlist_stocks": inject,
                "analyze": analyze,
            }

        report = main_fixture.DailyShadowIntegrationTests._capture_real_main_report(
            self, "off", patch_overrides=overrides
        )
        acquisition = report["data_quality"]["personal_watchlist_acquisition"]
        _artifact("r01-late-watchlist-boundary", {
            "analyzed_codes": analyzed,
            "acquisition": acquisition,
            "config": report["data_quality"]["personal_watchlist_config"],
        })

        self.assertNotIn("920001", analyzed)
        self.assertEqual(acquisition["added_codes"], [])
        self.assertEqual(acquisition["unavailable_codes"], ["920001"])
        self.assertEqual(
            report["data_quality"]["personal_watchlist_config"]["status"],
            "ok",
        )


if __name__ == "__main__":
    unittest.main()
