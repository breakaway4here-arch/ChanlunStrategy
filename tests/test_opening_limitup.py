"""Synthetic boundary fixtures; all prices and sessions here are explicitly synthetic."""
import copy
import unittest
import json
from pathlib import Path
from datetime import datetime, timedelta

from chanlun.opening_limitup import evaluate_opening_limitup


DATES = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03"]


def stock(code, board, exchange="SZ"):
    return {"identity": exchange + "." + code, "code": code, "exchange": exchange,
            "name": "合成测试", "board": board}


def event(code="000003", first="09:31:00", transitions=None, exchange="SZ"):
    if transitions is None:
        at = datetime.strptime(first, "%H:%M:%S")
        transitions = [(first, "sealed")] if first <= "09:30:00" else [(first, "sealed"), ((at+timedelta(seconds=1)).strftime("%H:%M:%S"), "open"), ((at+timedelta(seconds=2)).strftime("%H:%M:%S"), "sealed")]
    timeline = [{"at": DATES[-1] + "T" + t + "+08:00", "state": s} for t, s in transitions]
    return {**stock(code, 2, exchange), "first_at": DATES[-1] + "T" + first + "+08:00",
            "timeline_complete": True, "timeline": timeline}


def evidence():
    sessions = [{"date": d, "open": "10", "close": "10", "close0940": "10",
                 "amount0940": "100", "amountday": "1000", "complete_session": True}
                for d in DATES[:-1]]
    sessions.append({"date": DATES[-1], "open": "11", "close0940": "11",
                     "amount0940": "200", "amountday": None, "complete_session": False})
    p = [stock("000001", 1), stock("000002", 1), stock("000003", 2)]
    y = [stock("000001", 2), stock("000003", 1)]
    return {"schema_version": 1, "trade_date": DATES[-1],
            "calendar": {"status": "verified", "source": "synthetic-calendar", "dates": DATES},
            "index": {"identity": "SH.000001", "instrument": "index", "unit": "CNY",
                      "amount_scope": "includes_auction", "source": "synthetic", "sessions": sessions},
            "pools": {"P": {"date": DATES[-3], "source": "XGB", "status": "verified_complete", "total": 3, "items": p},
                      "Y": {"date": DATES[-2], "source": "XGB", "status": "verified_complete", "total": 2, "items": y}},
            "events": {"date": DATES[-1], "source": "XGB", "status": "verified_complete",
                       "scope": "limit_up_union_limit_up_broken", "coverage_verified": True, "items": [event()]}}


def opening_fact(open_price="11"):
    return {"identity":"SZ.000003", "date":DATES[-1], "basis":"raw", "fact_time":DATES[-1]+"T09:30:00+08:00", "observed_at":DATES[-1]+"T09:40:10+08:00", "limit_verified":True, "limit_price":"11", "open":open_price, "source":"synthetic-native-open-upper"}


class OpeningLimitupTests(unittest.TestCase):
    def test_b_exact_minus_point_one_percent_is_allowed_but_lower_is_rejected(self):
        for op, allowed in (("9.990", True), ("9.989999999999", False)):
            e = evidence(); e["index"]["sessions"][-1]["open"] = op
            r = evaluate_opening_limitup(e)
            self.assertEqual(r["environment"]["gates"].get("opening_allowed"), allowed)
            self.assertNotIn("red_open", r["environment"]["gates"])
            self.assertEqual(r["status"], "candidate" if allowed else "no_trade")

    def test_b_flat_and_small_negative_openings_are_allowed(self):
        for op in ("10", "9.999", "9.995"):
            e = evidence(); e["index"]["sessions"][-1]["open"] = op
            self.assertEqual(evaluate_opening_limitup(e)["status"], "candidate")

    def test_b_does_not_relax_strict_red0940(self):
        for close in ("10", "9.999"):
            e = evidence(); e["index"]["sessions"][-1].update(open="9.99", close0940=close)
            r = evaluate_opening_limitup(e)
            self.assertTrue(r["environment"]["gates"].get("opening_allowed"))
            self.assertFalse(r["environment"]["gates"]["red0940"])
            self.assertEqual(r["status"], "no_trade")

    def test_b_missing_opening_price_stays_unknown(self):
        for op in (None, "bad"):
            e = evidence(); e["index"]["sessions"][-1]["open"] = op
            r = evaluate_opening_limitup(e)
            self.assertIn("opening_allowed", r["environment"]["gates"])
            self.assertIsNone(r["environment"]["gates"]["opening_allowed"])
            self.assertEqual(r["status"], "unavailable")

    def test_b_has_an_independent_strategy_identity_and_explicit_opening_rule(self):
        r = evaluate_opening_limitup(evidence())
        self.assertEqual(r["strategy_id"], "opening-limitup-b-0940-v1")
        self.assertEqual(r["environment"].get("opening_minimum_return"), "-0.001")

    def test_real_frozen_v4_microgreen_dates_pass_b_environment_only(self):
        # Exact necessary values extracted from frozen v4/data/index/index-normalized.json.
        # Source SHA256:631d961c3b7568202b52c0cf4a77bbfb2f2691d6ff36128dfc458c1969f22cea.
        # Columns:date/open/close/close0940/amount0940/amountday. D full-day values
        # are deliberately absent; no source file or research module is imported.
        controls = [
            [
                ["2026-08-20","3907.2058","3903.7210","3909.63","192634800000.0","1018568353176.8000"],
                ["2026-08-21","3891.1751","3905.2026","3887.9","157033440000.0","883423480098.6000"],
                ["2026-08-24","3902.6963","3882.0079","3897.74","170868360000.0","952039262500.5000"],
                ["2026-08-25","3863.3695","3889.4449","3865.75","141859920000.0","858874228921.8000"],
                ["2026-08-26","3881.7408","3912.5235","3896.13","144074320000.0","857223487993.3000"],
                ["2026-08-27","3911.8908",None,"3918.31","159409320000.0",None],
            ],
            [
                ["2026-09-23","3951.3663","3936.5199","3947.591","142547140608.0000","834132862985.2000"],
                ["2026-09-24","3925.3230","3888.3738","3925.041","133921079296.0000","783613001376.2000"],
                ["2026-09-28","3878.4088","3823.6206","3857.706","145594695680.0000","804543704707.9000"],
                ["2026-09-29","3816.1536","3830.4513","3823.230","110139629568.0000","661704292800.7000"],
                ["2026-09-30","3839.2527","3842.1946","3839.791","107338989568.0000","679398992444.8000"],
                ["2026-10-08","3838.9774",None,"3853.720","144322199552.0000",None],
            ],
        ]
        for rows in controls:
            day = rows[-1][0]
            sessions = [{**dict(zip(("date","open","close","close0940","amount0940","amountday"), row)), "complete_session": row[0] != day} for row in rows]
            e = {"trade_date":day, "calendar":{"status":"verified", "source":"frozen_v4_verified_calendar", "dates":[row[0] for row in rows]},
                 "index":{"identity":"SH.000001", "instrument":"index", "unit":"CNY", "amount_scope":"includes_auction", "source":"frozen_v4_verified_multisource", "sessions":sessions}}
            with self.subTest(day=day):
                r = evaluate_opening_limitup(e)
                self.assertEqual(list(r["environment"]["gates"].values()), [True] * 4)
                self.assertEqual(r["status"], "unavailable")  # Environment-only fixture has no stock evidence.

    def test_real_frozen_july31_uses_raw_closed_bars_without_invented_timeline(self):
        e = json.loads((Path(__file__).parent / "fixtures/opening_limitup/2026-07-31-real-evidence.json").read_text())
        self.assertFalse(any(row["timeline_complete"] for row in e["events"]["items"]))
        r = evaluate_opening_limitup(e)
        self.assertEqual(r["status"], "candidate")
        self.assertEqual(r["promotion"]["target_board"], 3)
        self.assertEqual(r["selection"]["first"]["identity"], "SZ.002827")
        self.assertEqual(r["selection"]["first"]["display_price"], "34.60")
    def test_complete_evidence_has_conditional_candidate_without_display_price(self):
        r = evaluate_opening_limitup(evidence())
        self.assertEqual(r["status"], "candidate")
        self.assertEqual(r["selection"]["first"]["identity"], "SZ.000003")
        self.assertIsNone(r["selection"]["first"]["display_price"])
        self.assertIsNone(r["actual_fill"])

    def test_known_false_gate_wins_over_missing_other_data(self):
        e = evidence(); e["index"]["sessions"][-1]["open"] = "9"
        e.pop("pools"); e.pop("events")
        r = evaluate_opening_limitup(e)
        self.assertEqual(r["status"], "no_trade")
        self.assertIn("promotion_unknown", r["missing"])

    def test_current_full_day_never_enters_forecast(self):
        e = evidence(); before = evaluate_opening_limitup(e)
        e["index"]["sessions"][-1]["amountday"] = "99999999999"
        self.assertEqual(before["environment"], evaluate_opening_limitup(e)["environment"])

    def test_missing_adjacent_session_does_not_bridge(self):
        e = evidence(); e["index"]["sessions"].pop(3)
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_source_unit_and_index_instrument_are_required(self):
        for key, value in [("unit", "shares"), ("instrument", "stock"), ("identity", "SZ.000001")]:
            with self.subTest(key=key):
                e = evidence(); e["index"][key] = value
                self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_three_board_rate_uses_same_stock_matching(self):
        e = evidence(); e["pools"]["Y"]["items"][1]["board"] = 3
        r = evaluate_opening_limitup(e)
        self.assertEqual(r["promotion"]["target_board"], 3)
        self.assertEqual(r["promotion"]["r3"]["matched"], ["SZ.000003"])

    def test_positive_tie_selects_two_and_true_zero_no_trade(self):
        e = evidence(); e["pools"]["P"]["items"][1]["board"] = 2
        e["pools"]["Y"]["items"][1]["board"] = 3
        self.assertEqual(evaluate_opening_limitup(e)["promotion"]["target_board"], 2)
        e["pools"]["Y"]["items"] = []; e["pools"]["Y"]["total"] = 0
        e["pools"]["Y"]["status"] = "verified_empty"
        self.assertEqual(evaluate_opening_limitup(e)["status"], "no_trade")

    def test_exact_positive_half_tie_selects_two(self):
        e = evidence(); e["pools"]["P"]["items"].append(stock("000004", 2)); e["pools"]["P"]["total"] = 4
        e["pools"]["Y"]["items"][1]["board"] = 3
        p = evaluate_opening_limitup(e)["promotion"]
        self.assertEqual((p["r2"]["numerator"], p["r2"]["denominator"]), (1, 2))
        self.assertEqual((p["r3"]["numerator"], p["r3"]["denominator"]), (1, 2))
        self.assertEqual(p["target_board"], 2)

    def test_zero_denominator_is_unknown(self):
        e = evidence(); e["pools"]["P"]["items"][2]["board"] = 1
        self.assertEqual(evaluate_opening_limitup(e)["promotion"]["status"], "unknown")

    def test_duplicate_wrong_date_bad_board_and_missing_pool_are_unknown(self):
        cases = []
        e = evidence(); e["pools"]["P"]["items"].append(copy.deepcopy(e["pools"]["P"]["items"][0])); cases.append(e)
        e = evidence(); e["pools"]["Y"]["date"] = DATES[-3]; cases.append(e)
        e = evidence(); e["pools"]["Y"]["items"][0]["board"] = 0; cases.append(e)
        e = evidence(); e["pools"]["Y"]["status"] = "unavailable"; cases.append(e)
        for e in cases:
            self.assertEqual(evaluate_opening_limitup(e)["promotion"]["status"], "unknown")

    def test_unmatched_y_promotion_conflicts_instead_of_claiming_rate(self):
        e = evidence(); e["pools"]["Y"]["items"][0]["code"] = "002860"
        e["pools"]["Y"]["items"][0]["identity"] = "SZ.002860"
        r = evaluate_opening_limitup(e)
        self.assertIn("cohort_conflict", r["promotion"]["issues"])
        self.assertEqual(r["status"], "unavailable")

    def test_first_left_does_not_substitute_later_sealed(self):
        e = evidence(); e["pools"]["Y"]["items"].append(stock("000002", 1)); e["pools"]["Y"]["total"] = 3
        e["events"]["items"] = [event(transitions=[("09:31:00", "sealed"), ("09:35:00", "open")]), event("000002", "09:32:00")]
        r = evaluate_opening_limitup(e)
        self.assertEqual(r["status"], "no_trade")
        self.assertEqual(r["selection"]["first"]["identity"], "SZ.000003")

    def test_preopen_oneword_excluded_and_t_allowed_using_cutoff_events(self):
        e = evidence(); e["pools"]["Y"]["items"].append(stock("000002", 1)); e["pools"]["Y"]["total"] = 3
        e["events"]["items"] = [event(first="09:25:00"), event("000002", "09:25:00", [("09:25:00", "sealed"), ("09:32:00", "open"), ("09:34:00", "sealed")])]
        e["opening_facts"] = {"SZ.000003": opening_fact()}
        self.assertEqual(evaluate_opening_limitup(e)["selection"]["first"]["identity"], "SZ.000002")

    def test_after_cutoff_break_does_not_turn_oneword_into_t(self):
        e = evidence(); e["events"]["items"] = [event(first="09:25:00", transitions=[("09:25:00", "sealed"), ("10:00:00", "open")])]
        e["opening_facts"] = {"SZ.000003": opening_fact()}
        self.assertEqual(evaluate_opening_limitup(e)["status"], "no_trade")

    def test_exact_open_first_without_price_proof_is_unknown(self):
        e = evidence(); e["events"]["items"] = [event(first="09:30:00")]
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_raw_open_below_verified_limit_resolves_exact_open_case(self):
        e = evidence(); e["events"]["items"] = [event(first="09:30:00")]
        e["quotes"] = {"SZ.000003": {"identity": "SZ.000003", "date": DATES[-1], "cutoff": DATES[-1] + "T09:40:00+08:00", "basis": "raw", "limit_verified": True, "limit_price": "6.09", "open": "6.00"}}
        self.assertEqual(evaluate_opening_limitup(e)["status"], "candidate")

    def test_same_second_unknown_and_earlier_incomplete_cannot_be_skipped(self):
        e = evidence(); e["pools"]["Y"]["items"].append(stock("000002", 1)); e["pools"]["Y"]["total"] = 3
        e["events"]["items"] = [event(), event("000002")]
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")
        e["events"]["items"][0]["timeline_complete"] = False
        e["events"]["items"][1] = event("000002", "09:32:00")
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_incomplete_or_wrong_date_union_is_unknown_not_empty(self):
        for key, value in [("status", "unavailable"), ("date", DATES[-2])]:
            e = evidence(); e["events"][key] = value
            self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_mixed_source_universe_includes_star_growth_st(self):
        for code, exchange in [("300333", "SZ"), ("688001", "SH"), ("600001", "SH")]:
            e = evidence()
            for day in ("P", "Y"):
                e["pools"][day]["items"][2 if day == "P" else 1] = stock(code, 2 if day == "P" else 1, exchange)
            e["events"]["items"] = [event(code, exchange=exchange)]
            self.assertEqual(evaluate_opening_limitup(e)["status"], "candidate")

    def test_future_quote_cannot_change_cutoff_oneword(self):
        e = evidence(); e["events"]["items"] = [event(first="09:25:00", transitions=[("09:25:00", "sealed"), ("10:00:00", "open")])]
        e["quotes"] = {"SZ.000003": {"identity": "SZ.000003", "date": DATES[-1], "cutoff": DATES[-1] + "T10:00:00+08:00", "basis": "raw", "limit_verified": True, "limit_price": "11", "open": "11", "observed_low0940": "10", "close0940": "10"}}
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_malformed_stock_code_and_index_row_are_unknown_without_crash(self):
        e = evidence(); e["pools"]["P"]["items"][0]["code"] = 100001
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_same_cutoff_quote_and_native_seal_conflict_is_unknown(self):
        e = evidence()
        e["quotes"] = {"SZ.000003": {"identity": "SZ.000003", "date": DATES[-1], "cutoff": DATES[-1] + "T09:40:00+08:00", "basis": "raw", "limit_verified": True, "limit_price": "11", "open": "10", "observed_low0940": "10", "close0940": "10.5"}}
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_nonatomic_union_cannot_claim_candidate_or_first_left_or_no_candidate(self):
        for events in ([event()], [event(transitions=[("09:31:00", "sealed"), ("09:35:00", "open")])], []):
            e = evidence(); e["events"]["items"] = events; e["events"]["coverage_verified"] = False
            self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_immutable_open_projection_resolves_exact_open_without_current_price(self):
        for op, expected in (("11", "no_trade"), ("10", "candidate")):
            e = evidence(); e["events"]["items"] = [event(first="09:30:00")]
            e["opening_facts"] = {"SZ.000003": opening_fact(op)}
            self.assertEqual(evaluate_opening_limitup(e)["status"], expected)

    def test_preopen_sealed_timeline_conflicts_with_native_open_below_upper(self):
        e = evidence(); e["events"]["items"] = [event(first="09:25:00")]
        e["opening_facts"] = {"SZ.000003": opening_fact("10")}
        r = evaluate_opening_limitup(e)
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("opening_timeline_conflict", r["selection"]["issues"])

    def test_later_first_and_open_at_upper_without_preseal_path_is_unknown(self):
        e = evidence(); e["events"]["items"] = [event(first="09:31:00", transitions=[("09:31:00", "sealed")])]
        e["opening_facts"] = {"SZ.000003": opening_fact()}
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")

    def test_quote_conflict_cannot_be_hidden_by_oneword_early_return(self):
        e = evidence(); e["events"]["items"] = [event(first="09:25:00")]
        e["quotes"] = {"SZ.000003": {"identity":"SZ.000003", "date":DATES[-1], "basis":"raw", "cutoff":DATES[-1]+"T09:40:00+08:00", "limit_verified":True, "limit_price":"11", "open":"11", "close0940":"10.5"}}
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")
        e = evidence(); e["index"]["sessions"] = [None]
        self.assertEqual(evaluate_opening_limitup(e)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
