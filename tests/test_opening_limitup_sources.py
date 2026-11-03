import copy
import json
from pathlib import Path
import unittest

from chanlun.opening_limitup import evaluate_opening_limitup
from chanlun.opening_limitup_sources import normalize_index, normalize_pool, normalize_union, collect_opening_evidence, normalize_coverage_quotes, verify_cohort_coverage, opening_facts_from_quotes

FIXTURES = Path(__file__).parent / "fixtures" / "opening_limitup"


def raw(name):
    return json.loads((FIXTURES / name).read_text())


class OpeningSourcesTests(unittest.TestCase):
    def test_real_today_four_environment_gates_are_false(self):
        index, calendar = normalize_index(raw("05-sina-index-5m.json"), "2026-11-03", "")
        r = evaluate_opening_limitup({"trade_date": "2026-11-03", "index": index, "calendar": calendar})
        self.assertEqual(r["status"], "no_trade")
        self.assertEqual(list(r["environment"]["gates"].values()), [False] * 4)
        self.assertEqual(index["sessions"][-1]["amount0940"], "116736598016")
        self.assertEqual(index["sessions"][-2]["amountday"], "847459057664")
        self.assertIsNone(index["sessions"][-1]["amountday"])

    def test_missing_0940_bar_is_unknown_not_latest(self):
        rows = raw("05-sina-index-5m.json")
        rows = [r for r in rows if r["day"] != "2026-11-03 09:40:00"]
        index, _ = normalize_index(rows, "2026-11-03", "")
        self.assertIsNone(index["sessions"][-1]["close0940"])

    def test_duplicate_bar_and_nonfinite_amount_rejected(self):
        for mode in ("duplicate", "nan"):
            rows = raw("05-sina-index-5m.json")
            if mode == "duplicate": rows.append(copy.deepcopy(rows[-1]))
            else: rows[-1]["amount"] = "NaN"
            with self.assertRaises(ValueError):
                normalize_index(rows, "2026-11-03", "")

    def test_prior_day_must_have_all_48_expected_closed_bars(self):
        rows = raw("05-sina-index-5m.json")[1:]
        index, _ = normalize_index(rows, "2026-11-03", "")
        self.assertFalse(index["sessions"][0]["complete_session"])
        self.assertIsNone(index["sessions"][0]["amountday"])

    def test_after_cutoff_unclosed_bar_cannot_destroy_valid_closed_evidence(self):
        rows = raw("05-sina-index-5m.json")
        rows.append({"day": "2026-11-03 09:45:00", "open": "NaN", "amount": "NaN"})
        index, _ = normalize_index(rows, "2026-11-03", "")
        self.assertEqual(index["sessions"][-1]["amount0940"], "116736598016")

    def test_used_bar_ohlc_envelope_must_be_consistent(self):
        rows = raw("05-sina-index-5m.json"); rows[-1]["high"] = "1"
        with self.assertRaises(ValueError): normalize_index(rows, "2026-11-03", "")

    def test_real_complete_live_timelines_are_verified(self):
        u = normalize_union(raw("07-xgb-ZT-live.json"), raw("08-xgb-ZB-live.json"), "2026-11-03")
        self.assertEqual(u["status"], "verified_complete")
        self.assertEqual(len(u["items"]), 59)
        self.assertTrue(all(r["timeline_complete"] for r in u["items"]))

    def test_null_pool_is_unavailable_and_true_empty_is_distinct(self):
        self.assertEqual(normalize_pool({"code": 20000, "data": None}, "2026-11-02")["status"], "unavailable")
        self.assertEqual(normalize_pool({"code": 20000, "data": []}, "2026-11-02")["status"], "verified_empty")

    def test_timeline_inconsistent_native_count_or_epoch_does_not_pass(self):
        for mode in ("count", "date"):
            zt, zb = raw("07-xgb-ZT-live.json"), raw("08-xgb-ZB-live.json")
            if mode == "count": zt["data"][0]["break_limit_up_times"] = 1
            else: zt["data"][0]["first_limit_up"] -= 86400
            self.assertNotEqual(normalize_union(zt, zb, "2026-11-03")["status"], "verified_complete")

    def test_duplicate_across_union_or_pagination_not_silently_complete(self):
        zt, zb = raw("07-xgb-ZT-live.json"), raw("08-xgb-ZB-live.json")
        zb["data"].append(copy.deepcopy(zt["data"][0]))
        self.assertEqual(normalize_union(zt, zb, "2026-11-03")["status"], "unavailable")
        zt["has_more"] = True
        self.assertEqual(normalize_pool(zt, "2026-11-03")["status"], "unavailable")

    def test_environment_false_only_fetches_index_and_no_stock_or_cohort(self):
        calls = []
        def fetch(url, params, timeout):
            calls.append((url, params, timeout))
            return raw("05-sina-index-5m.json"), {"source": "fixture"}
        e = collect_opening_evidence("2026-11-03", "", fetch_json=fetch)
        self.assertEqual(len(calls), 1)
        self.assertEqual(evaluate_opening_limitup(e)["status"], "no_trade")

    def test_real_quote_missing_touched_member_blocks_nonatomic_union(self):
        y = normalize_pool(raw("02-XGB-Y.json"), "2026-11-02")
        cohort = [r for r in y["items"] if r["board"] == 2]
        quotes = normalize_coverage_quotes((FIXTURES/"Tencent-cohort-20261103.raw").read_bytes().decode("gb18030"), "2026-11-03")
        u = normalize_union(raw("07-xgb-ZT-live.json"), raw("08-xgb-ZB-live.json"), "2026-11-03")
        verify_cohort_coverage(u, cohort, quotes)
        self.assertFalse(u["coverage_verified"])
        self.assertEqual(u["coverage_unknown"], ["SZ.000417"])
        self.assertEqual(len(u["no_touch_proven"]), 4)

    def test_native_caps_cover_current_ST_and_twenty_percent_without_name_filter(self):
        qs = normalize_coverage_quotes((FIXTURES/"Tencent-cohort-20261103.raw").read_bytes().decode("gb18030"), "2026-11-03")
        self.assertTrue(qs["SH.600302"]["upper_verified"])
        self.assertEqual(qs["SH.600302"]["upper_limit"], "6.69")
        self.assertTrue(qs["SH.688175"]["upper_verified"])
        self.assertEqual(qs["SH.688175"]["upper_limit"], "30.50")

    def test_real_open_projection_retains_only_immutable_price_facts(self):
        qs = normalize_coverage_quotes((FIXTURES/"Tencent-cohort-20261103.raw").read_bytes().decode("gb18030"), "2026-11-03")
        projection = opening_facts_from_quotes(qs, "2026-11-03")
        q = projection.get("SZ.000995", {})
        self.assertEqual(q.get("open"), "17.16")
        self.assertEqual(q["limit_price"], "17.16")
        self.assertEqual(q["fact_time"], "2026-11-03T09:30:00+08:00")
        self.assertNotIn("last", q); self.assertNotIn("day_high", q); self.assertNotIn("observed_low0940", q)

    def test_coverage_requires_date_identity_upper_and_high_strictly_below(self):
        cohort = [{"identity":"SZ.000001"}]
        good = {"identity":"SZ.000001", "date":"2026-11-03", "quote_at":"2026-11-03T09:40:01+08:00", "day_high":"10", "upper_limit":"11", "upper_verified":True}
        for key, value in (("date","2026-11-02"),("identity","SH.000001"),("upper_verified",False),("day_high","11"),("quote_at","2026-11-03T09:39:59+08:00")):
            u = {"date":"2026-11-03", "status":"verified_empty", "items":[]}
            q = {**good, key:value}; verify_cohort_coverage(u, cohort, {"SZ.000001":q})
            self.assertFalse(u["coverage_verified"])
        u = {"date":"2026-11-03", "status":"verified_empty", "items":[]}
        verify_cohort_coverage(u, cohort, {"SZ.000001":good})
        self.assertTrue(u["coverage_verified"])


if __name__ == "__main__": unittest.main()
