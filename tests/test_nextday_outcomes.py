import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chanlun.nextday_outcomes import evaluate_frozen_selection


def _create_database(path):
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE instruments (
            instrument_id INTEGER PRIMARY KEY,
            asset_type TEXT NOT NULL,
            exchange TEXT NOT NULL,
            code TEXT NOT NULL
        );
        CREATE TABLE trade_calendar (
            exchange TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            is_open INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE bars_day (
            instrument_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            adjustment TEXT,
            is_final INTEGER,
            source_batch TEXT,
            updated_at TEXT
        );
        """
    )
    connection.commit()
    connection.close()


def _add_instrument(path, instrument_id, exchange, code, asset_type="stock"):
    connection = sqlite3.connect(str(path))
    connection.execute(
        "INSERT INTO instruments VALUES (?, ?, ?, ?)",
        (instrument_id, asset_type, exchange, code),
    )
    connection.commit()
    connection.close()


def _add_bar(
    path,
    instrument_id,
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    adjustment="raw",
    is_final=1,
    source_batch="fixture",
):
    connection = sqlite3.connect(str(path))
    connection.execute(
        "INSERT INTO bars_day VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            instrument_id,
            trade_date,
            open_price,
            high_price,
            low_price,
            close_price,
            adjustment,
            is_final,
            source_batch,
            "2026-09-17T00:00:00Z",
        ),
    )
    connection.commit()
    connection.close()


def _add_qfq_preclose_proof(
    db_path,
    trade_date,
    identity,
    previous_date,
    previous_close,
    factor,
    raw_current_price,
    provisional_ohlc,
    *,
    quote_snapshot_complete=True,
    daily_exchange=None,
):
    exchange, code = identity[:2], identity[2:]
    raw_previous_close = previous_close / factor
    adjusted_current_price = raw_current_price * factor
    as_of = trade_date + "T14:45:00+08:00"
    provisional_open = provisional_ohlc[0]
    provisional_high = provisional_ohlc[1]
    provisional_low = provisional_ohlc[2]
    provisional_close = provisional_ohlc[3]
    row = {
        "asset_type": "stock",
        "exchange": daily_exchange or exchange,
        "code": code,
        "is_final": False,
        "bar_state": "intraday",
        "as_of": as_of,
        "data_status": {
            "adjustment": "qfq",
            "daily": "verified",
            "is_final": True,
            "latest_date": previous_date,
            "source": "market_history_db",
            "stale": False,
        },
        "price_basis": {
            "adjustment": "qfq",
            "factor_vs_raw": factor,
            "adjusted_previous_close": previous_close,
            "raw_previous_close": raw_previous_close,
            "adjusted_current_price": adjusted_current_price,
            "raw_current_price": raw_current_price,
        },
        "klines": {
            "adjustment": "qfq",
            "source": "formal_history+eastmoney_intraday",
            "dates": [previous_date, trade_date],
            "opens": [previous_close, provisional_open],
            "highs": [previous_close, provisional_high],
            "lows": [previous_close, provisional_low],
            "closes": [previous_close, provisional_close],
            "finals": [True, False],
        },
    }
    payload = {
        "schema_version": "preclose-input-v1",
        "mode": "preclose_advisory",
        "trade_date": trade_date,
        "as_of": as_of,
        "bar_state": "intraday",
        "is_final": False,
        "daily": [row],
        "market": {
            "stock_bars": [{
                "code": code,
                "close": raw_current_price,
                "prev_close": raw_previous_close,
            }],
        },
        "runtime_diagnostics": {
            "quote_snapshot": {
                "complete": quote_snapshot_complete,
                "requested": 1,
                "unique": 1,
                "fetched": 1,
            },
        },
    }
    input_path = Path(db_path).parent / "preclose" / trade_date / "input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(payload), encoding="utf-8")


class NextdayOutcomesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_history.sqlite"
        _create_database(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _evaluate(self, identities, as_of_date, report_date="2026-09-11"):
        return evaluate_frozen_selection(
            {"report_date": report_date, "selected": identities},
            str(self.db_path),
            as_of_date,
        )

    def _add_three_days(self, instrument_id, adjustment="raw", source_batch="fixture"):
        _add_bar(
            self.db_path, instrument_id, "2026-09-11", 99, 101, 98, 100,
            adjustment=adjustment, source_batch=source_batch,
        )
        _add_bar(
            self.db_path, instrument_id, "2026-09-14", 105, 112, 104, 109,
            adjustment=adjustment, source_batch=source_batch,
        )
        _add_bar(
            self.db_path, instrument_id, "2026-09-15", 110, 113, 108, 112,
            adjustment=adjustment, source_batch=source_batch,
        )
        _add_bar(
            self.db_path, instrument_id, "2026-09-16", 114, 117, 112, 115,
            adjustment=adjustment, source_batch=source_batch,
        )

    def test_raw_price_paths_match_frozen_denominators_and_thresholds(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        self._add_three_days(1)

        result = self._evaluate(
            [{
                "instrument_id": "stock|SH|600609",
                "stock_identity": "stock|SH|600609",
                "identity": "stock|SH|600609",
                "exchange": None,
                "code": "600609",
                "asset_type": None,
                "identity_details": {
                    "asset_type": "stock", "exchange": "SH", "code": "600609"
                },
            }],
            "2026-09-16",
        )

        self.assertEqual(len(result["outcome_rows"]), 1)
        row = result["outcome_rows"][0]
        self.assertEqual(row["identity"], "SH600609")
        self.assertEqual(row["identity_status"], "valid")
        self.assertEqual(row["target_dates"], {
            "t1": "2026-09-14", "t2": "2026-09-15", "t3": "2026-09-16"
        })
        self.assertAlmostEqual(row["cc1"], 9.0)
        self.assertAlmostEqual(row["gap1"], 5.0)
        self.assertAlmostEqual(row["oc1"], (109.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc2"], (112.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc3"], (115.0 / 105.0 - 1.0) * 100.0)
        self.assertEqual(row["basis_status"], "raw_comparable")
        self.assertFalse(row["entry_one_price"])

        metrics = result["metrics"]
        self.assertEqual(metrics["selected"], 1)
        self.assertEqual(metrics["matured_t1"], 1)
        self.assertEqual(metrics["pending_t1"], 0)
        self.assertEqual(metrics["missing_t1"], 0)
        self.assertEqual(metrics["observed_cc1"], 1)
        self.assertEqual(metrics["nextday_gain_ge5"], 1)
        self.assertEqual(metrics["nextday_loss_le_minus5"], 0)
        self.assertEqual(metrics["observed_oc1"], 1)
        self.assertEqual(metrics["open_close_gain_ge3"], 1)
        self.assertTrue(metrics["not_realized_profit"])

    def test_qfq_paths_keep_same_bar_oc1_but_suppress_unverified_cross_date_returns(self):
        _add_instrument(self.db_path, 1, "SZ", "000504")
        self._add_three_days(
            1, adjustment="qfq", source_batch="official_close_snapshot:eastmoney"
        )

        row = self._evaluate(["SZ000504"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNone(row["cc1"])
        self.assertIsNone(row["gap1"])
        self.assertAlmostEqual(row["oc1"], (109.0 / 105.0 - 1.0) * 100.0)
        self.assertIsNone(row["oc2"])
        self.assertIsNone(row["oc3"])
        self.assertEqual(row["basis_status"], "price_basis_unverified")
        self.assertEqual(row["outcome_status"], "basis_unverified")
        metrics = self._evaluate(["SZ000504"], "2026-09-16")["metrics"]
        self.assertEqual(metrics["selected"], 1)
        self.assertEqual(metrics["basis_unverified_t1"], 1)
        self.assertEqual(metrics["observed_cc1"], 0)
        self.assertEqual(metrics["observed_oc1"], 1)
        self.assertEqual(metrics["missing_T1"], 0)
        self.assertEqual(metrics["unavailable_T1"], 1)

    def test_qfq_factor_bridges_enable_final_cross_date_paths(self):
        _add_instrument(self.db_path, 1, "SZ", "000504")
        self._add_three_days(
            1, adjustment="qfq", source_batch="official_close_snapshot:eastmoney"
        )
        # The factors vary across dates. Each explicit bridge still maps the
        # day's raw previous close to the prior final qfq close.
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-14", "SZ000504", "2026-09-11", 100.0,
            1.1, 99.0, (105.0, 111.0, 103.0, 108.9),
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-15", "SZ000504", "2026-09-14", 109.0,
            0.8, 140.0, (110.0, 114.0, 108.0, 112.0),
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-16", "SZ000504", "2026-09-15", 112.0,
            1.25, 92.8, (114.0, 117.0, 112.0, 116.0),
        )

        row = self._evaluate(["SZ000504"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNotNone(row["cc1"])
        self.assertAlmostEqual(row["cc1"], 9.0)
        self.assertAlmostEqual(row["gap1"], 5.0)
        self.assertAlmostEqual(row["oc1"], (109.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc2"], (112.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc3"], (115.0 / 105.0 - 1.0) * 100.0)
        self.assertEqual(row["basis_status_by_metric"], {
            "cc1": "qfq_comparable",
            "gap1": "qfq_comparable",
            "oc1": "within_bar_invariant",
            "oc2": "qfq_comparable",
            "oc3": "qfq_comparable",
        })
        self.assertEqual(row["basis_status"], "qfq_comparable")
        self.assertEqual(row["outcome_status"], "available")

    def test_missing_intermediate_qfq_bridge_only_disables_later_paths(self):
        _add_instrument(self.db_path, 1, "SZ", "000504")
        self._add_three_days(
            1, adjustment="qfq", source_batch="official_close_snapshot:eastmoney"
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-14", "SZ000504", "2026-09-11", 100.0,
            1.1, 99.0, (105.0, 111.0, 103.0, 108.9),
        )
        # The 9/15 bridge is missing. A valid 9/16 endpoint cannot skip it.
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-16", "SZ000504", "2026-09-15", 112.0,
            1.25, 92.8, (114.0, 117.0, 112.0, 116.0),
        )

        row = self._evaluate(["SZ000504"], "2026-09-16")["outcome_rows"][0]

        self.assertAlmostEqual(row["cc1"], 9.0)
        self.assertAlmostEqual(row["gap1"], 5.0)
        self.assertIsNone(row["oc2"])
        self.assertIsNone(row["oc3"])
        self.assertEqual(row["basis_status_by_metric"]["cc1"], "qfq_comparable")
        self.assertEqual(row["basis_status_by_metric"]["oc2"], "price_basis_unverified")
        self.assertEqual(row["basis_status_by_metric"]["oc3"], "price_basis_unverified")

    def test_missing_t1_qfq_bridge_does_not_disable_later_proven_paths(self):
        _add_instrument(self.db_path, 1, "SZ", "000504")
        self._add_three_days(
            1, adjustment="qfq", source_batch="official_close_snapshot:eastmoney"
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-15", "SZ000504", "2026-09-14", 109.0,
            0.8, 140.0, (110.0, 114.0, 108.0, 112.0),
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-16", "SZ000504", "2026-09-15", 112.0,
            1.25, 92.8, (114.0, 117.0, 112.0, 116.0),
        )

        row = self._evaluate(["SZ000504"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNone(row["cc1"])
        self.assertIsNone(row["gap1"])
        self.assertEqual(row["basis_status_by_metric"]["cc1"], "price_basis_unverified")
        self.assertAlmostEqual(row["oc2"], (112.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc3"], (115.0 / 105.0 - 1.0) * 100.0)
        self.assertEqual(row["basis_status_by_metric"]["oc2"], "qfq_comparable")
        self.assertEqual(row["basis_status_by_metric"]["oc3"], "qfq_comparable")

    def _add_verified_qfq_fixture(self, exchange="SH", code="600609"):
        _add_instrument(self.db_path, 1, exchange, code)
        self._add_three_days(
            1, adjustment="qfq", source_batch="official_close_snapshot:eastmoney"
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-14", exchange + code, "2026-09-11", 100.0,
            1.1, 99.0, (105.0, 111.0, 103.0, 108.9),
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-15", exchange + code, "2026-09-14", 109.0,
            0.8, 140.0, (110.0, 114.0, 108.0, 112.0),
        )
        _add_qfq_preclose_proof(
            self.db_path, "2026-09-16", exchange + code, "2026-09-15", 112.0,
            1.25, 92.8, (114.0, 117.0, 112.0, 116.0),
        )

    def test_qfq_open_mismatch_fails_closed(self):
        self._add_verified_qfq_fixture()
        initial = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]
        self.assertEqual(initial["basis_status_by_metric"]["cc1"], "qfq_comparable")

        proof_path = Path(self.db_path).parent / "preclose" / "2026-09-14" / "input.json"
        payload = json.loads(proof_path.read_text(encoding="utf-8"))
        payload["daily"][0]["klines"]["opens"][-1] = 105.1
        proof_path.write_text(json.dumps(payload), encoding="utf-8")

        row = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNone(row["cc1"])
        self.assertIsNone(row["gap1"])
        self.assertAlmostEqual(row["oc1"], (109.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc2"], (112.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc3"], (115.0 / 105.0 - 1.0) * 100.0)
        self.assertEqual(row["basis_status_by_metric"]["cc1"], "price_basis_unverified")
        self.assertEqual(row["basis_status_by_metric"]["oc2"], "qfq_comparable")
        self.assertEqual(
            row["bar_provenance"]["t1"]["basis_proof"]["reason"],
            "open_anchor_mismatch",
        )

    def test_qfq_source_identity_conflict_fails_closed(self):
        self._add_verified_qfq_fixture()
        initial = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]
        self.assertEqual(initial["basis_status_by_metric"]["cc1"], "qfq_comparable")

        proof_path = Path(self.db_path).parent / "preclose" / "2026-09-14" / "input.json"
        payload = json.loads(proof_path.read_text(encoding="utf-8"))
        payload["daily"][0]["exchange"] = "SZ"
        proof_path.write_text(json.dumps(payload), encoding="utf-8")

        row = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNone(row["cc1"])
        self.assertIsNone(row["gap1"])
        self.assertAlmostEqual(row["oc1"], (109.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc2"], (112.0 / 105.0 - 1.0) * 100.0)
        self.assertAlmostEqual(row["oc3"], (115.0 / 105.0 - 1.0) * 100.0)
        self.assertEqual(row["basis_status_by_metric"]["cc1"], "price_basis_unverified")
        self.assertEqual(row["basis_status_by_metric"]["oc2"], "qfq_comparable")
        self.assertEqual(
            row["bar_provenance"]["t1"]["basis_proof"]["reason"],
            "daily_identity_mismatch",
        )

    def test_missing_intermediate_qfq_bar_does_not_allow_oc3_to_skip_t2(self):
        self._add_verified_qfq_fixture()
        connection = sqlite3.connect(str(self.db_path))
        connection.execute(
            "DELETE FROM bars_day WHERE instrument_id=? AND ts=?", (1, "2026-09-15")
        )
        connection.commit()
        connection.close()

        row = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]

        self.assertAlmostEqual(row["cc1"], 9.0)
        self.assertIsNone(row["oc2"])
        self.assertIsNone(row["oc3"])
        self.assertEqual(row["basis_status_by_metric"]["oc2"], "data_unavailable")
        self.assertEqual(row["basis_status_by_metric"]["oc3"], "data_unavailable")

    def test_raw_oc3_keeps_existing_endpoint_comparison_when_t2_is_missing(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        self._add_three_days(1)
        connection = sqlite3.connect(str(self.db_path))
        connection.execute(
            "DELETE FROM bars_day WHERE instrument_id=? AND ts=?", (1, "2026-09-15")
        )
        connection.commit()
        connection.close()

        row = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNone(row["oc2"])
        self.assertEqual(row["basis_status_by_metric"]["oc2"], "data_unavailable")
        self.assertAlmostEqual(row["oc3"], (115.0 / 105.0 - 1.0) * 100.0)
        self.assertEqual(row["basis_status_by_metric"]["oc3"], "raw_comparable")

    def test_as_of_date_keeps_future_bars_pending_even_if_the_database_has_them(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        self._add_three_days(1)
        before = sqlite3.connect(str(self.db_path)).execute(
            "SELECT COUNT(*) FROM bars_day"
        ).fetchone()[0]

        result = self._evaluate(["SH600609"], "2026-09-11")

        row = result["outcome_rows"][0]
        self.assertEqual(row["maturity_status"]["t1"], "pending")
        self.assertEqual(row["bar_status"]["t1"], "not_due")
        self.assertIsNone(row["cc1"])
        self.assertEqual(result["metrics"]["selected"], 1)
        self.assertEqual(result["metrics"]["pending_t1"], 1)
        self.assertEqual(result["metrics"]["pending_T1"], 1)
        self.assertEqual(result["metrics"]["missing_T1"], 0)
        after = sqlite3.connect(str(self.db_path)).execute(
            "SELECT COUNT(*) FROM bars_day"
        ).fetchone()[0]
        self.assertEqual(before, after)

    def test_missing_t1_is_not_replaced_with_a_later_available_bar(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-09-11", 99, 101, 98, 100)
        _add_bar(self.db_path, 1, "2026-09-15", 105, 112, 104, 109)
        _add_bar(self.db_path, 1, "2026-09-16", 110, 117, 108, 115)

        result = self._evaluate(["SH600609"], "2026-09-16")

        row = result["outcome_rows"][0]
        self.assertEqual(row["target_dates"]["t1"], "2026-09-14")
        self.assertEqual(row["bar_status"]["t1"], "missing")
        self.assertEqual(row["outcome_status"], "missing")
        self.assertIsNone(row["cc1"])
        self.assertEqual(result["metrics"]["selected"], 1)
        self.assertEqual(result["metrics"]["missing_t1"], 1)
        self.assertEqual(len(result["outcome_rows"]), 1)

    def test_nonfinal_bar_has_a_distinct_status_and_no_return(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-09-11", 99, 101, 98, 100)
        _add_bar(
            self.db_path, 1, "2026-09-14", 105, 112, 104, 109, is_final=0
        )

        row = self._evaluate(["SH600609"], "2026-09-14")["outcome_rows"][0]

        self.assertEqual(row["bar_status"]["t1"], "nonfinal")
        self.assertEqual(row["outcome_status"], "nonfinal")
        self.assertIsNone(row["cc1"])
        self.assertIsNone(row["oc1"])

    def test_selection_denominator_and_exact_exchange_identity_are_preserved(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_instrument(self.db_path, 2, "SH", "000504")
        _add_instrument(self.db_path, 3, "SZ", "000504")
        _add_instrument(self.db_path, 4, "SH", "000504", asset_type="index")
        self._add_three_days(1)
        for instrument_id, signal_close, t1_close in (
            (2, 500.0, 550.0),
            (3, 50.0, 55.0),
            (4, 900.0, 990.0),
        ):
            _add_bar(
                self.db_path, instrument_id, "2026-09-11",
                signal_close - 1, signal_close + 1, signal_close - 2,
                signal_close,
            )
            _add_bar(
                self.db_path, instrument_id, "2026-09-14",
                t1_close - 1, t1_close + 2, t1_close - 2, t1_close,
            )
            _add_bar(
                self.db_path, instrument_id, "2026-09-15",
                t1_close, t1_close + 2, t1_close - 1, t1_close + 1,
            )
            _add_bar(
                self.db_path, instrument_id, "2026-09-16",
                t1_close + 1, t1_close + 3, t1_close, t1_close + 2,
            )

        result = self._evaluate(
            ["SH600609", "SH000504", "SZ000504"], "2026-09-16"
        )

        self.assertEqual(len(result["outcome_rows"]), 3)
        self.assertEqual(result["metrics"]["selected"], 3)
        self.assertEqual(
            [row["identity_status"] for row in result["outcome_rows"]],
            ["valid", "malformed", "valid"],
        )
        self.assertEqual(result["metrics"]["identity_malformed"], 1)
        self.assertEqual(result["metrics"]["observed_cc1"], 2)
        self.assertEqual(result["outcome_rows"][1]["identity"], "SH000504")
        self.assertAlmostEqual(result["outcome_rows"][2]["signal_close"], 50.0)
        self.assertAlmostEqual(result["outcome_rows"][2]["cc1"], 10.0)

    def test_outer_and_identity_details_contradictions_are_rejected(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_instrument(self.db_path, 2, "SZ", "000504")
        self._add_three_days(1)
        for trade_date, prices in (
            ("2026-09-11", (199, 202, 198, 200)),
            ("2026-09-14", (219, 225, 218, 220)),
            ("2026-09-15", (220, 225, 218, 222)),
            ("2026-09-16", (222, 227, 220, 225)),
        ):
            _add_bar(self.db_path, 2, trade_date, *prices)

        selected = [
            {
                "instrument_id": "SH600609", "stock_identity": "SH600609",
                "identity": "SH600609", "exchange": "SZ", "code": "000504",
                "asset_type": "stock", "research_rank": 1,
            },
            {
                "instrument_id": "SH600609", "stock_identity": "SH600609",
                "identity": "SH600609", "exchange": "SH", "code": "600609",
                "asset_type": "index", "research_rank": 2,
            },
            {
                "instrument_id": "SH600609", "stock_identity": "SH600609",
                "identity": "SH600609", "exchange": "SH", "code": "600609",
                "asset_type": "stock", "research_rank": 3,
                "identity_details": {
                    "asset_type": "index", "exchange": "SH", "code": "600609"
                },
            },
        ]

        result = self._evaluate(selected, "2026-09-16")

        self.assertEqual(len(result["outcome_rows"]), 3)
        self.assertEqual(
            [row["identity_status"] for row in result["outcome_rows"]],
            ["malformed", "malformed", "malformed"],
        )
        self.assertEqual(
            [row["selection"]["research_rank"] for row in result["outcome_rows"]],
            [1, 2, 3],
        )
        self.assertEqual(result["metrics"]["selected"], 3)
        self.assertEqual(result["metrics"]["identity_malformed"], 3)
        self.assertEqual(result["metrics"]["identity_valid_selected"], 0)
        self.assertEqual(result["metrics"]["observed_cc1"], 0)
        self.assertEqual(result["metrics"]["observed_oc1"], 0)

    def test_partial_outer_identity_fields_are_checked_without_requiring_their_mate(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_instrument(self.db_path, 2, "SH", "600001")
        self._add_three_days(1)
        self._add_three_days(2)

        selected = [
            {
                "instrument_id": "SH600609", "stock_identity": "SH600609",
                "identity": "SH600609", "code": "000504", "research_rank": 1,
            },
            {
                "instrument_id": "SH600001", "stock_identity": "SH600001",
                "identity": "SH600001", "exchange": "SZ", "research_rank": 2,
            },
            {"code": "600609", "research_rank": 3},
        ]

        result = self._evaluate(selected, "2026-09-16")

        self.assertEqual(len(result["outcome_rows"]), 3)
        self.assertEqual(
            [row["identity_status"] for row in result["outcome_rows"]],
            ["malformed", "malformed", "malformed"],
        )
        self.assertEqual(
            [row["selection"]["research_rank"] for row in result["outcome_rows"]],
            [1, 2, 3],
        )
        self.assertEqual(result["metrics"]["identity_valid_selected"], 0)
        self.assertEqual(result["metrics"]["observed_cc1"], 0)

    def test_known_t1_survives_unknown_calendar_at_a_later_horizon(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-12-30", 99, 101, 98, 100)
        _add_bar(self.db_path, 1, "2026-12-31", 100, 107, 99, 105)

        result = self._evaluate(
            ["SH600609"], "2026-12-31", report_date="2026-12-30"
        )

        row = result["outcome_rows"][0]
        self.assertEqual(row["target_dates"]["t1"], "2026-12-31")
        self.assertIsNone(row["target_dates"]["t2"])
        self.assertEqual(row["maturity_status"]["t1"], "matured")
        self.assertEqual(row["maturity_status"]["t2"], "calendar_unavailable")
        self.assertEqual(row["outcome_status"], "available")
        self.assertAlmostEqual(row["cc1"], 5.0)
        self.assertEqual(result["metrics"]["observed_cc1"], 1)
        self.assertEqual(result["metrics"]["missing_T1"], 0)

    def test_conflicting_exchange_calendar_flags_are_unknown_not_closed(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-09-11", 99, 101, 98, 100)
        connection = sqlite3.connect(str(self.db_path))
        connection.executemany(
            "INSERT INTO trade_calendar VALUES (?, ?, ?, ?)",
            [
                ("SH", "2026-09-14", 1, "fixture"),
                ("SZ", "2026-09-14", 0, "fixture"),
            ],
        )
        connection.commit()
        connection.close()

        result = self._evaluate(["SH600609"], "2026-09-16")

        row = result["outcome_rows"][0]
        self.assertIsNone(row["target_dates"]["t1"])
        self.assertEqual(row["maturity_status"]["t1"], "calendar_unavailable")
        self.assertEqual(row["outcome_status"], "calendar_unavailable")

    def test_weekend_open_flag_cannot_create_a_trading_day(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-09-11", 99, 101, 98, 100)
        connection = sqlite3.connect(str(self.db_path))
        connection.executemany(
            "INSERT INTO trade_calendar VALUES (?, ?, ?, ?)",
            [
                ("SH", "2026-09-12", 1, "fixture"),
                ("SZ", "2026-09-12", 1, "fixture"),
            ],
        )
        connection.commit()
        connection.close()

        row = self._evaluate(["SH600609"], "2026-09-16")["outcome_rows"][0]

        self.assertIsNone(row["target_dates"]["t1"])
        self.assertEqual(row["maturity_status"]["t1"], "calendar_unavailable")

    def test_known_2026_holiday_and_weekend_calendar_are_skipped(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-09-24", 99, 101, 98, 100)

        row = self._evaluate(
            ["SH600609"], "2026-09-24", report_date="2026-09-24"
        )["outcome_rows"][0]

        self.assertEqual(row["target_dates"]["t1"], "2026-09-28")
        self.assertEqual(row["maturity_status"]["t1"], "pending")

    def test_invalid_or_partial_ohlc_never_produces_returns(self):
        identities = [
            (1, "SZ", "000504", (105, 108, 104, 109)),
            (2, "SH", "600609", (105, 112, 104, -1)),
            (3, "SZ", "300750", (105, 112, None, 109)),
            (4, "SZ", "300001", (float("nan"), 112, 104, 109)),
        ]
        for instrument_id, exchange, code, _ in identities:
            _add_instrument(self.db_path, instrument_id, exchange, code)
            _add_bar(
                self.db_path, instrument_id, "2026-09-11", 99, 101, 98, 100
            )
        for instrument_id, _, _, prices in identities:
            _add_bar(
                self.db_path, instrument_id, "2026-09-14", *prices
            )

        selected = [exchange + code for _, exchange, code, _ in identities]
        result = self._evaluate(selected, "2026-09-14")

        self.assertEqual(
            [row["bar_status"]["t1"] for row in result["outcome_rows"]],
            ["invalid_ohlc"] * 4,
        )
        self.assertTrue(all(row["oc1"] is None for row in result["outcome_rows"]))
        self.assertTrue(all(row["cc1"] is None for row in result["outcome_rows"]))
        self.assertEqual(result["metrics"]["observed_oc1"], 0)
        self.assertEqual(result["metrics"]["observed_cc1"], 0)

    def test_malformed_and_ambiguous_identities_are_reported_per_selection(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_instrument(self.db_path, 2, "SH", "600609")

        result = self._evaluate(
            ["SH60060", "SH600609", {"identity": "SH600609", "instrument_id": "SZ000504"}],
            "2026-09-16",
        )

        self.assertEqual(len(result["outcome_rows"]), 3)
        self.assertEqual(
            [row["identity_status"] for row in result["outcome_rows"]],
            ["malformed", "ambiguous", "malformed"],
        )
        self.assertEqual(result["metrics"]["selected"], 3)
        self.assertEqual(result["metrics"]["identity_ambiguous"], 1)
        self.assertEqual(result["metrics"]["identity_malformed"], 2)

    def test_conflicting_duplicate_bars_are_not_silently_merged(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2026-09-11", 99, 101, 98, 100)
        _add_bar(self.db_path, 1, "2026-09-14", 105, 112, 104, 109)
        _add_bar(self.db_path, 1, "2026-09-14", 106, 112, 104, 109)

        row = self._evaluate(["SH600609"], "2026-09-14")["outcome_rows"][0]

        self.assertEqual(row["bar_status"]["t1"], "duplicate_inconsistent")
        self.assertIsNone(row["oc1"])
        self.assertEqual(self._evaluate(["SH600609"], "2026-09-14")["metrics"]["duplicate_rows"], 1)

    def test_unsupported_calendar_year_is_explicitly_unavailable(self):
        _add_instrument(self.db_path, 1, "SH", "600609")
        _add_bar(self.db_path, 1, "2027-01-04", 99, 101, 98, 100)

        result = self._evaluate(
            ["SH600609"], "2027-01-10", report_date="2027-01-04"
        )

        row = result["outcome_rows"][0]
        self.assertEqual(row["maturity_status"]["t1"], "calendar_unavailable")
        self.assertEqual(row["outcome_status"], "calendar_unavailable")
        self.assertIsNone(row["target_dates"]["t1"])
        self.assertEqual(result["metrics"]["selected"], 1)
        self.assertEqual(result["metrics"]["calendar_unavailable"], 1)

    def test_one_price_bar_is_counted_as_execution_uncertainty(self):
        _add_instrument(self.db_path, 1, "SZ", "000504")
        _add_bar(self.db_path, 1, "2026-09-11", 99, 101, 98, 100)
        _add_bar(self.db_path, 1, "2026-09-14", 110, 110, 110, 110)

        result = self._evaluate(["SZ000504"], "2026-09-14")

        row = result["outcome_rows"][0]
        self.assertTrue(row["entry_one_price"])
        self.assertTrue(row["entry_one_price_uncertain"])
        self.assertEqual(result["metrics"]["entry_one_price_count"], 1)


if __name__ == "__main__":
    unittest.main()
