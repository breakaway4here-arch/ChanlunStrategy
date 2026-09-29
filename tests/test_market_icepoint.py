"""Contract tests for the independent extreme-icepoint display."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chanlun.market_icepoint import (ETF_GROUPS, evaluate_icepoint, build_existing_evidence,
                                     parse_tencent_etf, fetch_etf_quotes, build_report_icepoint)
from chanlun.report_generator import build_full_daily_projection, build_aggregate_day_projection
from chanlun.market_sentiment import build_daily_inputs_from_windows
from run import _attach_market_icepoint


DAY = "2026-09-29"
AS_OF = "2026-09-29T15:20:00+08:00"
INDEX_NAMES = ("上证指数", "深证成指", "创业板指", "科创50", "沪深300", "中证500")


def evidence():
    return {
        "indices": {
            name: {"date": DAY, "change_pct": -2.0, "source": "verified_index_kline",
                   "status": "verified", "as_of": AS_OF}
            for name in INDEX_NAMES
        },
        "turnover": {
            "date": DAY, "source": "market_history", "scope": "all_a_cny",
            "current": 120.0, "prior": [100.0] * 5,
            "prior_dates": ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"],
            "coverage_counts": [5500] * 6, "denominator": 5500,
            "complete": True, "trading_days_verified": True,
            "quality": "comparable", "as_of": AS_OF,
        },
        "breadth": {
            "date": DAY, "source": "market_history", "scope": "all_a",
            "as_of": AS_OF, "advance_count": 550, "decline_count": 4950,
            "flat_count": 0, "valid_count": 5500, "denominator": 5500,
            "complete": True,
        },
        "limits": {
            "evidence_date": DAY, "source": "eastmoney_limit_pools",
            "scope": "eastmoney_topic_pools", "data_status": "verified",
            "current_sealed": True,
            "as_of": AS_OF, "limit_up_count": 10, "limit_down_count": 100,
        },
        "etf": {"date": DAY, "as_of": AS_OF, "source": "tencent",
                "quotes": [{"symbol": symbol, "change_pct": -4.01, "as_of": AS_OF}
                           for symbol in ("sh512800", "sh512170", "sh512480", "sh512660", "sz159928", "sh512400", "sh512200")]},
    }


def result(values=None, phase="closed"):
    values = evidence() if values is None else values
    return evaluate_icepoint(DAY, AS_OF, phase, **values)


class IcepointRules(unittest.TestCase):
    def test_exact_core_thresholds_and_independent_etf(self):
        item = result()
        self.assertEqual(item["status"], "matched")
        self.assertEqual((item["matched_count"], item["verified_count"]), (4, 4))
        self.assertEqual(list(item["items"]), ["volume_drop", "six_indices", "breadth", "sealed_limits"])
        self.assertEqual(item["etf"]["status"], "matched")
        self.assertFalse(item["affects_production"])
        json.dumps(item, allow_nan=False)

    def test_each_core_negative_prevents_match(self):
        for key, mutate in (
            ("volume_drop", lambda e: e["turnover"].update(current=119.9)),
            ("six_indices", lambda e: e["indices"]["上证指数"].update(change_pct=-1.99)),
            ("breadth", lambda e: e["breadth"].update(decline_count=4949, flat_count=1)),
            ("sealed_limits", lambda e: e["limits"].update(limit_down_count=99)),
        ):
            with self.subTest(key=key):
                data = evidence(); mutate(data)
                got = result(data)
                self.assertEqual(got["status"], "not_matched")
                self.assertEqual(got["items"][key]["status"], "not_matched")

    def test_each_core_missing_is_insufficient_without_losing_facts(self):
        for key, field in (("volume_drop", "turnover"), ("six_indices", "indices"),
                           ("breadth", "breadth"), ("sealed_limits", "limits")):
            with self.subTest(key=key):
                data = evidence(); data[field] = None
                got = result(data)
                self.assertEqual(got["status"], "insufficient")
                self.assertEqual(got["items"][key]["status"], "unavailable")
                self.assertEqual(got["verified_count"], 2 if key == "six_indices" else 3)

    def test_volume_does_not_pass_without_index_drop(self):
        data = evidence(); data["indices"]["上证指数"]["change_pct"] = -1.67
        got = result(data)
        self.assertEqual(got["items"]["six_indices"]["status"], "not_matched")
        self.assertEqual(got["items"]["volume_drop"]["status"], "not_matched")

    def test_partial_indices_never_use_average(self):
        data = evidence(); data["indices"].pop("上证指数")
        got = result(data)
        self.assertEqual(got["items"]["six_indices"]["status"], "unavailable")
        self.assertEqual(got["items"]["volume_drop"]["status"], "unavailable")

    def test_intraday_turnover_cannot_compare_full_days(self):
        self.assertEqual(result(phase="intraday")["items"]["volume_drop"]["status"], "unavailable")

    def test_breadth_zero_advance_and_zero_zero(self):
        data = evidence(); data["breadth"].update(advance_count=0, decline_count=5500)
        self.assertEqual(result(data)["items"]["breadth"]["status"], "matched")
        data["breadth"].update(decline_count=0, flat_count=5500)
        self.assertEqual(result(data)["items"]["breadth"]["status"], "not_matched")

    def test_bad_numbers_and_incomplete_coverage_are_unknown(self):
        for field, value in (("advance_count", True), ("decline_count", -1),
                             ("valid_count", math.inf), ("advance_count", "")):
            with self.subTest(field=field, value=value):
                data = evidence(); data["breadth"][field] = value
                self.assertEqual(result(data)["items"]["breadth"]["status"], "unavailable")
        data = evidence(); data["breadth"]["denominator"] = 7000
        self.assertEqual(result(data)["items"]["breadth"]["status"], "unavailable")
        data = evidence(); data["turnover"]["prior"][0] = math.nan
        self.assertEqual(result(data)["items"]["volume_drop"]["status"], "unavailable")

    def test_old_or_future_date_and_mixed_limit_scope_do_not_pass(self):
        data = evidence(); data["indices"]["科创50"]["date"] = "2026-09-28"
        self.assertEqual(result(data)["items"]["six_indices"]["status"], "unavailable")
        data = evidence(); data["limits"]["scope"] = "top_n"
        self.assertEqual(result(data)["items"]["sealed_limits"]["status"], "unavailable")
        data = evidence(); data["breadth"]["date"] = "2026-09-30"
        self.assertEqual(result(data)["items"]["breadth"]["status"], "unavailable")

    def test_etf_boundary_and_partial_count(self):
        data = evidence()
        for quote in data["etf"]["quotes"][:3]: quote["change_pct"] = -4.0
        got = result(data)
        self.assertEqual(got["etf"]["status"], "not_matched")
        self.assertEqual(got["status"], "matched")
        data["etf"]["quotes"] = data["etf"]["quotes"][:4]
        got = result(data)
        self.assertEqual(got["etf"]["status"], "unavailable")
        self.assertEqual(got["etf"]["verified_count"], 4)

    def test_partial_market_coverage_never_becomes_complete_by_percentage(self):
        data = evidence(); data["breadth"].update(valid_count=5499, decline_count=4949, denominator=5500)
        self.assertEqual(result(data)["items"]["breadth"]["status"], "unavailable")
        data = evidence(); data["turnover"]["coverage_counts"][0] = 5499
        self.assertEqual(result(data)["items"]["volume_drop"]["status"], "unavailable")
        data = evidence(); data["breadth"]["complete"] = False
        self.assertEqual(result(data)["items"]["breadth"]["status"], "unavailable")

    def test_index_status_time_and_source_provenance(self):
        data = evidence(); data["indices"]["科创50"]["status"] = "unverified"
        self.assertEqual(result(data)["items"]["six_indices"]["status"], "unavailable")
        data = evidence(); data["indices"]["科创50"]["as_of"] = "2026-09-29T15:30:00+08:00"
        self.assertEqual(result(data)["items"]["six_indices"]["status"], "unavailable")
        data = evidence(); data["indices"]["科创50"]["source"] = "another_verified_source"
        self.assertEqual(result(data)["items"]["six_indices"]["source"]["科创50"], "another_verified_source")
        self.assertEqual(result(data)["items"]["six_indices"]["source"]["上证指数"], "verified_index_kline")

    def test_missing_amount_dates_and_unsealed_pool_remain_unknown(self):
        data = evidence(); data["turnover"].pop("prior_dates")
        self.assertEqual(result(data)["items"]["volume_drop"]["status"], "unavailable")
        data = evidence(); data["limits"]["current_sealed"] = False
        self.assertEqual(result(data)["items"]["sealed_limits"]["status"], "unavailable")

    def test_duplicate_invalid_etf_and_nan_cannot_escape_to_json(self):
        data = evidence(); data["etf"]["quotes"].append({"symbol": "sh512800", "change_pct": math.nan, "as_of": AS_OF})
        got = result(data)
        self.assertEqual(got["etf"]["verified_count"], 6)
        data = evidence(); data["indices"]["上证指数"]["change_pct"] = math.nan
        data["etf"]["quotes"][0]["change_pct"] = math.inf
        json.dumps(result(data), allow_nan=False)

    def test_finite_inputs_with_overflowing_sum_or_ratio_remain_json_safe(self):
        for current, prior in ((1e308, [1e308] * 5), (1e308, [1e-308] * 5)):
            with self.subTest(current=current, prior=prior[0]):
                data = evidence(); data["turnover"].update(current=current, prior=prior)
                got = result(data)
                self.assertEqual(got["items"]["volume_drop"]["status"], "unavailable")
                json.dumps(got, allow_nan=False)


class ExistingEvidenceTests(unittest.TestCase):
    def test_existing_six_day_history_and_complete_close_are_reused(self):
        dates = ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28", DAY]
        rows = []
        for day in dates:
            for code in ("600000", "000001"):
                rows.append({"ts": day, "code": code, "exchange": "SH" if code.startswith("6") else "SZ",
                             "asset_type": "stock", "amount": 60 if day == DAY else 50,
                             "amount_available": 1, "amount_unit": "CNY", "amount_source": "verified_quote"})
        sentiment = {"date": DAY, "evidence": {"breadth": {
            "available": True, "advance_count": 0, "decline_count": 2,
            "flat_count": 0, "valid_count": 2}}}
        snapshot = {"status": "complete", "coverage_numerator": 2,
                    "coverage_denominator": 2, "identity_pending_rows": 0, "report_date": DAY}
        indices = evidence()["indices"]
        for row in indices.values():
            row.pop("as_of")
            row.pop("status")
        result = build_existing_evidence(DAY, AS_OF, indices=indices,
            index_observed_at=AS_OF, market_data_status="verified", sentiment=sentiment,
            stock_window={"dates": dates, "rows": rows, "invalid_identity_rows": 0},
            index_window={"dates": dates}, close_snapshot=snapshot,
            limit_counts={DAY: evidence()["limits"]}, limit_fetch_times={DAY: AS_OF},
            turnover_quality="comparable",
            turnover_input={"date": DAY, "turnover": 120, "turnover_ma5": 100})
        self.assertEqual(result["turnover"]["prior"], [100] * 5)
        self.assertEqual(result["turnover"]["current"], 120)
        self.assertTrue(result["breadth"]["complete"])
        self.assertEqual(result["limits"]["scope"], "eastmoney_topic_pools")
        self.assertEqual(result["indices"]["上证指数"]["status"], "verified")
        self.assertEqual(build_report_icepoint(DAY, AS_OF, "closed", **result)["status"], "matched")

        cached = build_existing_evidence(DAY, AS_OF, indices=indices,
            index_observed_at=AS_OF, market_data_status="verified", sentiment=sentiment,
            stock_window={"dates": dates, "rows": rows}, index_window={"dates": dates},
            close_snapshot=snapshot, limit_counts={DAY: evidence()["limits"]},
            turnover_quality="comparable",
            turnover_input={"date": DAY, "turnover": 120, "turnover_ma5": 100})
        self.assertEqual(build_report_icepoint(DAY, AS_OF, "closed", **cached)["items"]["sealed_limits"]["status"], "unavailable")
        scale_break = build_existing_evidence(DAY, AS_OF, indices=indices,
            index_observed_at=AS_OF, market_data_status="verified", sentiment=sentiment,
            stock_window={"dates": dates, "rows": rows}, index_window={"dates": dates},
            close_snapshot=snapshot, limit_counts={}, turnover_quality="scale_break",
            turnover_input={"date": DAY, "turnover": 120, "turnover_ma5": 100})
        self.assertFalse(scale_break["turnover"]["complete"])

        # The old report's 90% formal close gate is not whole-market evidence.
        snapshot["coverage_numerator"] = 1
        partial = build_existing_evidence(DAY, AS_OF, indices=indices,
            index_observed_at=AS_OF, market_data_status="verified", sentiment=sentiment,
            stock_window={"dates": dates, "rows": rows}, index_window={"dates": dates},
            close_snapshot=snapshot, limit_counts={}, turnover_quality="comparable",
            turnover_input={"date": DAY, "turnover": 120, "turnover_ma5": 100})
        self.assertFalse(partial["breadth"].get("complete", False))
        self.assertFalse(partial["turnover"].get("complete", False))
        self.assertEqual(build_report_icepoint(DAY, AS_OF, "closed", **partial)["status"], "insufficient")

    def test_missing_trading_day_or_amount_provenance_does_not_invent_volume(self):
        args = dict(indices={}, market_data_status="unverified", sentiment={},
                    stock_window={"dates": ["2026-09-25", DAY], "rows": []},
                    index_window={"dates": ["2026-09-24", DAY]},
                    close_snapshot={"status": "complete", "coverage_numerator": 1,
                                    "coverage_denominator": 1, "report_date": DAY}, limit_counts={})
        got = build_existing_evidence(DAY, AS_OF, **args)
        self.assertFalse(got["turnover"].get("complete", False))

    def test_finite_per_stock_amounts_cannot_overflow_day_total(self):
        rows = [{"ts": DAY, "code": "600000", "exchange": "SH", "asset_type": "stock",
                 "amount": 1e308, "amount_available": 1, "amount_unit": "CNY", "amount_source": "x"},
                {"ts": DAY, "code": "600001", "exchange": "SH", "asset_type": "stock",
                 "amount": 1e308, "amount_available": 1, "amount_unit": "CNY", "amount_source": "x"}]
        got = build_existing_evidence(DAY, AS_OF, stock_window={"dates": [DAY], "rows": rows},
            close_snapshot={"status": "complete", "report_date": DAY,
                            "coverage_numerator": 2, "coverage_denominator": 2},
            index_window={}, sentiment={}, indices={}, limit_counts={})
        self.assertIsNone(got["turnover"]["current"])
        json.dumps(got, allow_nan=False)


class ETFQuoteTests(unittest.TestCase):
    @staticmethod
    def raw(asof="20260929151000"):
        lines = []
        for _, symbol in ETF_GROUPS:
            fields = [""] * 33
            fields[2], fields[3], fields[4] = symbol[2:], "0.95", "1.00"
            fields[30], fields[32] = asof, "-5.00"
            lines.append('v_{}="{}";'.format(symbol, "~".join(fields)))
        return "\n".join(lines)

    def test_one_batch_parses_seven_etf_and_later_quote_than_report_start(self):
        raw = self.raw()
        now = "2026-09-29T15:20:00+08:00"
        parsed = parse_tencent_etf(raw, DAY, now)
        self.assertEqual(len(parsed["quotes"]), 7)
        self.assertEqual(parsed["as_of"], "2026-09-29T15:10:00+08:00")
        self.assertEqual(evaluate_icepoint(DAY, now, "closed", etf=parsed)["etf"]["status"], "matched")

    def test_old_day_and_preclose_quote_do_not_pass_as_new_close(self):
        self.assertEqual(parse_tencent_etf(self.raw(), "2026-09-28", AS_OF)["quotes"], [])
        self.assertEqual(parse_tencent_etf(self.raw("20260929113800"), DAY, AS_OF)["quotes"], [])

    def test_one_request_and_same_day_cache(self):
        calls = []
        def requester(url):
            calls.append(url)
            return self.raw().encode("gb18030")
        with tempfile.TemporaryDirectory() as directory:
            first = fetch_etf_quotes(DAY, now="2026-09-29T15:20:00+08:00",
                                     cache_dir=Path(directory), requester=requester)
            second = fetch_etf_quotes(DAY, now="2026-09-29T15:21:00+08:00",
                                      cache_dir=Path(directory), requester=requester)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["quotes"], second["quotes"])

    def test_failed_batch_has_short_cache_without_in_call_retry(self):
        calls = []
        def requester(url):
            calls.append(url)
            raise OSError("offline")
        with tempfile.TemporaryDirectory() as directory:
            for instant in ("2026-09-29T15:20:00+08:00", "2026-09-29T15:21:00+08:00",
                            "2026-09-29T15:23:00+08:00"):
                fetch_etf_quotes(DAY, now=instant, cache_dir=Path(directory), requester=requester)
        self.assertEqual(len(calls), 2)


class ReportWiringTests(unittest.TestCase):
    def test_turnover_reset_cannot_rebuild_a_discarded_five_day_baseline(self):
        dates = ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28", DAY]
        for amounts, expected_ma5, expected_status in (
            ([100, 100, 100, 100, 100, 120], 100, "matched"),
            ([100, 100, 1000, 1000, 1000, 1200], None, "unavailable"),
        ):
            with self.subTest(amounts=amounts):
                window = {"dates": dates, "rows": [
                    {"ts": day, "code": "600000", "exchange": "SH", "asset_type": "stock",
                     "close": 10, "amount": amount, "amount_available": 1,
                     "amount_unit": "CNY", "amount_source": "verified_quote"}
                    for day, amount in zip(dates, amounts)
                ]}
                original_input = build_daily_inputs_from_windows(window)[-1]
                self.assertEqual(original_input["turnover_quality"], "comparable")
                self.assertEqual(original_input["turnover_ma5"], expected_ma5)
                report = {"date": DAY, "market": evidence()["indices"],
                          "data_quality": {"bar_state": "closed", "as_of": AS_OF,
                            "market_close_snapshot": {"status": "complete", "report_date": DAY,
                              "coverage_numerator": 1, "coverage_denominator": 1}}}
                capture = {"stock_window": window, "index_window": {"dates": dates},
                           "turnover_quality": original_input["turnover_quality"],
                           "turnover_input": {key: original_input[key]
                                              for key in ("date", "turnover", "turnover_ma5")}}
                _attach_market_icepoint(report, capture=capture, index_observed_at=AS_OF,
                                        market_data_status="verified", observed_at=AS_OF, allow_etf=False)
                volume = report["market_icepoint"]["items"]["volume_drop"]
                self.assertEqual(volume["status"], expected_status)
                self.assertEqual(volume["actual"]["prior_mean_cny"], expected_ma5)
                self.assertEqual(volume["actual"]["ratio"], 1.2 if expected_ma5 else None)
                if expected_ma5 is not None:
                    for invalid in (None, {"date": "2026-09-28"}, {"turnover": 121},
                                    {"turnover_ma5": None}, {"turnover_ma5": 99},
                                    {"turnover_ma5": math.nan}, {"turnover_ma5": math.inf}):
                        invalid_capture = copy.deepcopy(capture)
                        if invalid is None:
                            invalid_capture.pop("turnover_input")
                        else:
                            invalid_capture["turnover_input"].update(invalid)
                        _attach_market_icepoint(report, capture=invalid_capture, index_observed_at=AS_OF,
                                                market_data_status="verified", observed_at=AS_OF, allow_etf=False)
                        unavailable = report["market_icepoint"]["items"]["volume_drop"]
                        self.assertEqual(unavailable["status"], "unavailable", invalid)
                        json.dumps(report["market_icepoint"], allow_nan=False)

    def test_late_observation_accepts_quote_after_job_start_without_mutating_old_fields(self):
        report = {"date": DAY, "market": evidence()["indices"],
                  "market_sentiment": {"date": DAY, "score": 5},
                  "picks_pure": [{"code": "600000", "score": 20}],
                  "data_quality": {"as_of": "2026-09-29T15:05:00+08:00",
                                   "bar_state": "closed", "market_close_snapshot": {}}}
        original = copy.deepcopy(report)
        etf = parse_tencent_etf(ETFQuoteTests.raw(), DAY, AS_OF)
        calls = []
        def fetcher(day, **kwargs):
            calls.append(day)
            return etf
        _attach_market_icepoint(report, capture={}, index_observed_at="2026-09-29T15:06:00+08:00",
                                market_data_status="verified", observed_at=AS_OF,
                                etf_fetcher=fetcher)
        self.assertEqual(calls, [DAY])
        self.assertEqual(report["market_icepoint"]["etf"]["status"], "matched")
        self.assertEqual(report["market_icepoint"]["as_of"], AS_OF)
        self.assertEqual({k: v for k, v in report.items() if k != "market_icepoint"}, original)
        self.assertEqual(build_full_daily_projection(report)["market_icepoint"], report["market_icepoint"])
        self.assertEqual(build_aggregate_day_projection(report)["market_icepoint"], report["market_icepoint"])
        utc_report = copy.deepcopy(original)
        _attach_market_icepoint(utc_report, capture={}, index_observed_at="2026-09-29T07:06:00+00:00",
                                market_data_status="verified", observed_at="2026-09-29T07:20:00+00:00",
                                etf_fetcher=fetcher)
        self.assertEqual(utc_report["market_icepoint"]["as_of"], AS_OF)
        self.assertEqual(utc_report["market_icepoint"]["etf"]["status"], "matched")

    def test_replay_and_optional_failure_do_not_block_report(self):
        report = {"date": "2026-09-28", "market": {},
                  "data_quality": {"bar_state": "closed", "as_of": "2026-09-28T15:05:00+08:00"}}
        def fail(*args, **kwargs):
            raise RuntimeError("optional source failed")
        _attach_market_icepoint(report, capture={}, index_observed_at=None,
                                market_data_status="unverified", observed_at="2026-09-29T15:20:00+08:00",
                                etf_fetcher=fail)
        self.assertEqual(report["market_icepoint"]["status"], "insufficient")
        self.assertEqual(report["market_icepoint"]["etf"]["status"], "unavailable")

    def test_intraday_never_uses_late_wallclock_or_future_indices(self):
        report = {"date": DAY, "market": evidence()["indices"],
                  "data_quality": {"bar_state": "intraday", "as_of": "2026-09-29T14:50:00+08:00"}}
        def fail(*args, **kwargs):
            raise AssertionError("intraday must not request ETF")
        _attach_market_icepoint(report, capture={}, index_observed_at=AS_OF,
                                market_data_status="verified", observed_at=AS_OF,
                                etf_fetcher=fail)
        self.assertEqual(report["market_icepoint"]["as_of"], report["data_quality"]["as_of"])
        self.assertEqual(report["market_icepoint"]["verified_count"], 0)

    def test_etf_exception_keeps_all_four_existing_core_facts(self):
        dates = ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28", DAY]
        rows = [{"ts": day, "code": code, "exchange": "SH", "asset_type": "stock",
                 "amount": 60 if day == DAY else 50, "amount_available": 1,
                 "amount_unit": "CNY", "amount_source": "verified_quote"}
                for day in dates for code in ("600000", "600001")]
        base = {"date": DAY, "market": evidence()["indices"],
                "market_sentiment": {"date": DAY, "evidence": {"breadth": {
                    "available": True, "advance_count": 0, "decline_count": 2,
                    "flat_count": 0, "valid_count": 2}}},
                "data_quality": {"bar_state": "closed", "as_of": "2026-09-29T15:05:00+08:00",
                                 "market_close_snapshot": {"status": "complete", "report_date": DAY,
                                     "coverage_numerator": 2, "coverage_denominator": 2}}}
        capture = {"stock_window": {"dates": dates, "rows": rows},
                   "index_window": {"dates": dates},
                   "limit_counts": {DAY: evidence()["limits"]},
                   "limit_fetch_times": {DAY: AS_OF}, "turnover_quality": "comparable",
                   "turnover_input": {"date": DAY, "turnover": 120, "turnover_ma5": 100},
                   "fresh_sentiment": base["market_sentiment"]}
        without_etf = copy.deepcopy(base)
        _attach_market_icepoint(without_etf, capture=capture, index_observed_at=AS_OF,
                                market_data_status="verified", observed_at=AS_OF, allow_etf=False)
        self.assertEqual(without_etf["market_icepoint"]["items"]["volume_drop"]["status"], "matched")
        broken_etf = copy.deepcopy(base)
        def fail(*args, **kwargs):
            raise RuntimeError("Tencent unavailable")
        _attach_market_icepoint(broken_etf, capture=capture, index_observed_at=AS_OF,
                                market_data_status="verified", observed_at=AS_OF, etf_fetcher=fail)
        self.assertEqual(broken_etf["market_icepoint"]["items"], without_etf["market_icepoint"]["items"])
        self.assertEqual(broken_etf["market_icepoint"]["status"], without_etf["market_icepoint"]["status"])
        self.assertEqual(broken_etf["market_icepoint"]["etf"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
