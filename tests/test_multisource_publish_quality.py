"""Regression cases for an active daily report with independent sector failure."""

import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import run
from chanlun import data_fetcher
from scripts.validate_today_report import (
    validate_report_contract, validate_runtime_cutover,
)


REPORT_DATE = "2026-09-29"
CLOSED = datetime(2026, 9, 29, 15, 20, tzinfo=timezone(timedelta(hours=8)))


def active_quality(*, sector_missing=True):
    return {
        "report_date": REPORT_DATE,
        "as_of": CLOSED.isoformat(),
        "bar_state": "closed",
        "market_status": "verified",
        "index_latest_date": REPORT_DATE,
        "sources_trusted": not sector_missing,
        "stock_pool_source": "full_a_db+expanded_base",
        "sector_source": "fallback_static" if sector_missing else "eastmoney",
        "fallback_used": sector_missing,
        "stock_pool_incomplete": sector_missing,
        "market_close_snapshot": {
            "status": "partial",
            "reason": "identity_migration_pending",
            "source": "db",
            "report_date": REPORT_DATE,
            "coverage_numerator": 5450,
            "coverage_denominator": 5878,
            "minimum_coverage": 0.9,
            "meets_minimum_coverage": True,
            "identity_pending_rows": 1,
            "identity_pending_codes": ["920008"],
        },
        "universe_builder": {
            "status": "activated",
            "final_count": 1,
            "base_count": 1,
            "overlay_count": 0,
            "retrieval_mode": "base_expanded_no_overlay"
                if sector_missing else "base_plus_overlay",
        },
    }


def selected_stock():
    return {
        "code": "600000", "exchange": "SH", "asset_type": "stock",
        "klines": {"adjustment": "qfq", "dates": [REPORT_DATE]},
        "data_status": {
            "daily": "verified", "latest_date": REPORT_DATE,
            "source": "market_history_db", "is_final": True,
            "adjustment": "qfq", "stale": False,
        },
    }


def active_report(*, sector_missing=True):
    quality = active_quality(sector_missing=sector_missing)
    quality.update(
        generated_at=CLOSED.isoformat(),
        is_official=True,
        sources_trusted=True,
        stale_stock_count=0,
        missing_daily_count=0,
        official_pool_scope="active_retrieval_pool",
        sector_data_status="unavailable" if sector_missing else "verified",
        runtime_policy={
            "market_history_cutover_mode": "sqlite",
            "recall_strategy_mode": "active",
            "decision_semantics": "v2_missing_position_is_observe",
        },
    )
    return {
        "date": REPORT_DATE,
        "market": {"上证指数": {"date": REPORT_DATE, "source": "tencent", "close": 3830.45}},
        "sector_flow": [],
        "picks_pure": [], "picks_fusion": [],
        "startup_watchlist": [], "observation_watchlist": [],
        "workspace": {"views": {"highlights": [], "main": [], "baseline": []}},
        "data_quality": quality,
        "selection_input_health": {
            "required_date": REPORT_DATE,
            "market_close_snapshot": copy.deepcopy(quality["market_close_snapshot"]),
            "formal": {"required_date": REPORT_DATE, "status": "verified",
                       "formal_actions_allowed": True,
                       "invalid_count": 0,
                       "market_close_snapshot": copy.deepcopy(quality["market_close_snapshot"])},
            "by_strategy": {
                "daily_fusion": {"status": "verified", "formal_actions_allowed": True},
                "h4_t3": {"status": "verified", "formal_actions_allowed": True},
            },
            "sublevels": {"30m": {
                "interval": "30m", "required_date": REPORT_DATE,
                "status": "partial", "requested_count": 2,
                "verified_count": 1, "missing_count": 1,
                "verified_codes": ["600000"], "missing_codes": ["600001"],
                "failure_evidence": {"600001": {"status": "price_basis_unverified"}},
                "blocks_strategy_output": False,
            }},
        },
        "diagnostics": {
            "candidate_funnel": {
                "persist_status": "saved", "report_date": REPORT_DATE,
                "stage_counts": {"retrieval": 1, "daily_channel": 1, "minute30": 0},
            },
            "recall_shadow": {"mode": "active", "new_strategy_controls_publish": True},
        },
    }


def mixed_source_report():
    """Frozen 9/29 shape: 5477 new quotes plus three independent final bars."""
    report = active_report()
    rows = [
        {
            "identity_key": "stock|{}|{}".format(exchange, code),
            "asset_type": "stock", "exchange": exchange, "code": code,
            "date": REPORT_DATE, "source_batch": "ongoing:tencent",
            "adjustment": "qfq", "is_final": True,
        }
        for exchange, code in (("SH", "601238"), ("SZ", "300211"), ("SH", "605303"))
    ]
    snapshot = report["data_quality"]["market_close_snapshot"]
    snapshot.pop("source")
    snapshot.update(
        coverage_numerator=5480,
        coverage_denominator=5908,
        identity_pending_rows=93,
        identity_pending_codes=["{:06d}".format(code) for code in range(920000, 920093)],
        quote_sources={"sina": 5477},
        quote_identity_keys=[
            "stock|SH|{:06d}".format(code)
            for code in range(600000, 606000)
            if code not in {601238, 605303}
        ][:5477],
        preserved_independent_final_count=3,
        preserved_independent_final_rows=rows,
    )
    report["selection_input_health"]["market_close_snapshot"] = copy.deepcopy(snapshot)
    report["selection_input_health"]["formal"]["market_close_snapshot"] = copy.deepcopy(snapshot)
    return report


class ActivePublishQualityTests(unittest.TestCase):
    def test_sector_outage_does_not_veto_verified_active_close(self):
        quality = active_quality()
        run._refresh_active_universe_quality(quality, [selected_stock()], REPORT_DATE)

        self.assertTrue(quality["is_official"])
        self.assertTrue(quality["sources_trusted"])
        self.assertEqual(quality["official_pool_scope"], "active_retrieval_pool")
        self.assertTrue(quality["fallback_used"])
        self.assertTrue(quality["stock_pool_incomplete"])
        self.assertEqual(quality["sector_source"], "fallback_static")

    def test_original_eastmoney_close_stays_official(self):
        quality = active_quality(sector_missing=False)
        run._refresh_active_universe_quality(quality, [selected_stock()], REPORT_DATE)
        self.assertTrue(quality["is_official"])
        self.assertTrue(quality["sources_trusted"])
        self.assertFalse(quality["fallback_used"])

    def test_active_close_rejects_bad_primary_evidence(self):
        cases = {
            "no_snapshot": lambda q, s: q.pop("market_close_snapshot"),
            "malformed_snapshot": lambda q, s: q.update(market_close_snapshot="bad"),
            "wrong_snapshot_day": lambda q, s: q["market_close_snapshot"].update(report_date="2026-09-28"),
            "complete_snapshot_with_pending_identity": lambda q, s: q["market_close_snapshot"].update(status="complete", reason="", identity_pending_rows=1),
            "low_coverage": lambda q, s: q["market_close_snapshot"].update(coverage_numerator=5000, meets_minimum_coverage=False),
            "unknown_snapshot_status": lambda q, s: q["market_close_snapshot"].update(status="incomplete"),
            "boolean_snapshot_count": lambda q, s: q["market_close_snapshot"].update(coverage_numerator=True),
            "fractional_snapshot_count": lambda q, s: q["market_close_snapshot"].update(coverage_numerator=5450.5),
            "float_snapshot_denominator": lambda q, s: q["market_close_snapshot"].update(coverage_denominator=5878.0),
            "boolean_pending_count": lambda q, s: q["market_close_snapshot"].update(identity_pending_rows=True),
            "wrong_index_day": lambda q, s: q.update(index_latest_date="2026-09-28"),
            "wrong_quality_day": lambda q, s: q.update(report_date="2026-09-28"),
            "intraday": lambda q, s: q.update(bar_state="intraday"),
            "wrong_asof_day": lambda q, s: q.update(as_of="2026-09-28T15:20:00+08:00"),
            "pool_not_activated": lambda q, s: q["universe_builder"].update(status="fallback"),
            "malformed_pool": lambda q, s: q.update(universe_builder="bad"),
            "pool_count_mismatch": lambda q, s: q["universe_builder"].update(final_count=2),
            "unknown_sector_source": lambda q, s: q.update(sector_source="mystery"),
            "primary_sector_with_fallback": lambda q, s: q.update(sector_source="eastmoney"),
            "static_sector_without_fallback": lambda q, s: q.update(fallback_used=False),
            "unknown_source": lambda q, s: s[0]["data_status"].update(source="unknown"),
            "malformed_status": lambda q, s: s[0].update(data_status="bad"),
            "malformed_kline": lambda q, s: s[0].update(klines="bad"),
            "malformed_selected": lambda q, s: s.__setitem__(0, "bad"),
            "unknown_identity": lambda q, s: s[0].update(exchange="SZ"),
            "unknown_price_basis": lambda q, s: s[0]["klines"].update(adjustment=""),
            "raw_price_basis": lambda q, s: (s[0]["klines"].update(adjustment="raw"), s[0]["data_status"].update(adjustment="raw")),
            "unverified_daily": lambda q, s: s[0]["data_status"].update(daily="missing"),
            "nonfinal_daily": lambda q, s: s[0]["data_status"].update(is_final=False),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                quality, selected = active_quality(), [selected_stock()]
                mutate(quality, selected)
                run._refresh_active_universe_quality(quality, selected, REPORT_DATE)
                self.assertFalse(quality["is_official"], quality)

    def test_unknown_sector_is_not_marked_verified(self):
        for sector_source in ("empty", "mystery", "eastmoney"):
            with self.subTest(sector_source=sector_source):
                quality = active_quality()
                quality["sector_source"] = sector_source
                run._refresh_active_universe_quality(
                    quality, [selected_stock()], REPORT_DATE
                )
                self.assertNotEqual(quality["sector_data_status"], "verified")

    def test_static_sector_lookup_does_not_claim_fund_flow_rank(self):
        def missing_component(code, *, return_diagnostics=False):
            diag = {"sector_code": code, "complete": False,
                    "error": "request_failed:ConnectionError"}
            return ([], diag) if return_diagnostics else []

        def verified_stock(stocks, **kwargs):
            return [{
                **stock,
                "klines": {"dates": [REPORT_DATE], "closes": [10.0]},
                "data_status": {"daily": "verified", "latest_date": REPORT_DATE,
                                "source": "market_history_db"},
            } for stock in stocks]

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=[]), \
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=missing_component), \
             patch.object(data_fetcher, "_get_kline_repository") as repository, \
             patch.object(data_fetcher, "batch_fetch_daily_klines", side_effect=verified_stock), \
             patch.object(data_fetcher, "fetch_shanghai_index", return_value={"dates": [REPORT_DATE], "closes": [3.0]}):
            repository.return_value.list_instruments.return_value = [
                {"code": "600000", "name": "浦发银行"}
            ]
            result = data_fetcher.collect_daily_data(
                required_date=REPORT_DATE, generated_at=CLOSED
            )

        self.assertEqual(result["sectors"], [])
        self.assertEqual(result["stocks"][0]["sector_rank"], None)
        self.assertEqual(result["stocks"][0]["sector_flow"], None)
        self.assertEqual(result["stocks"][0]["sector_strength_label"], "")
        self.assertEqual(result["data_quality"]["sector_source"], "fallback_static")
        self.assertTrue(result["data_quality"]["fallback_used"])
        self.assertTrue(result["data_quality"]["stock_pool_incomplete"])

    def test_static_sector_component_names_do_not_become_top_rank(self):
        def complete_component(code, *, return_diagnostics=False):
            rows = [{"code": "600000", "name": "浦发银行"}] if code == "BK0480" else []
            diag = {"sector_code": code, "complete": True, "error": ""}
            return (rows, diag) if return_diagnostics else rows

        with patch.object(data_fetcher, "fetch_sector_flow", return_value=[]), \
             patch.object(data_fetcher, "fetch_sector_stocks", side_effect=complete_component), \
             patch.object(data_fetcher, "batch_fetch_daily_klines", side_effect=lambda stocks, **kwargs: stocks), \
             patch.object(data_fetcher, "fetch_shanghai_index", return_value={"dates": [REPORT_DATE], "closes": [3.0]}):
            result = data_fetcher.collect_daily_data(
                required_date=REPORT_DATE, generated_at=CLOSED
            )

        self.assertEqual(result["sectors"], [])
        self.assertEqual(result["stocks"][0]["sector_rank"], None)
        self.assertEqual(result["stocks"][0]["sector_flow"], None)
        self.assertEqual(result["stocks"][0]["sector_strength_label"], "")
        self.assertTrue(result["data_quality"]["fallback_used"])


class ActivePublishValidatorTests(unittest.TestCase):
    def test_mixed_source_snapshot_counts_verified_independent_rows(self):
        report = mixed_source_report()
        self.assertEqual(validate_report_contract(report, require_official=True), [])
        self.assertEqual(validate_runtime_cutover(report), [])

    def test_mixed_source_snapshot_rejects_unproved_or_duplicate_rows(self):
        cases = {
            "scalar_only": lambda s: s.pop("preserved_independent_final_rows"),
            "missing_quote_identity_keys": lambda s: s.pop("quote_identity_keys"),
            "duplicate_quote_identity": lambda s: s["quote_identity_keys"].__setitem__(1, s["quote_identity_keys"][0]),
            "malformed_quote_identity": lambda s: s["quote_identity_keys"].__setitem__(0, "not_an_identity"),
            "overlapping_identity": lambda s: s["quote_identity_keys"].__setitem__(0, "stock|SH|601238"),
            "unknown_source": lambda s: s["preserved_independent_final_rows"][0].update(source_batch="manual:unknown"),
            "source_prefix_spoof": lambda s: s["preserved_independent_final_rows"][0].update(source_batch="ongoing:tencent_unverified"),
            "wrong_date": lambda s: s["preserved_independent_final_rows"][0].update(date="2026-09-28"),
            "raw_basis": lambda s: s["preserved_independent_final_rows"][0].update(adjustment="raw"),
            "nonfinal": lambda s: s["preserved_independent_final_rows"][0].update(is_final=False),
            "wrong_identity": lambda s: s["preserved_independent_final_rows"][0].update(identity_key="stock|SZ|601238"),
            "duplicate": lambda s: s["preserved_independent_final_rows"].__setitem__(1, copy.deepcopy(s["preserved_independent_final_rows"][0])),
            "count_only": lambda s: s.update(preserved_independent_final_count=4),
            "quote_count_tamper": lambda s: s.update(quote_sources={"sina": 5478}),
            "numerator_tamper": lambda s: s.update(coverage_numerator=5479),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                report = mixed_source_report()
                snapshot = report["data_quality"]["market_close_snapshot"]
                mutate(snapshot)
                report["selection_input_health"]["market_close_snapshot"] = copy.deepcopy(snapshot)
                report["selection_input_health"]["formal"]["market_close_snapshot"] = copy.deepcopy(snapshot)
                self.assertTrue(validate_report_contract(report, require_official=True), label)

    def test_index_sources_from_verified_fetch_contract_are_accepted(self):
        # These names are emitted by fetch_verified_index_kline, including
        # today's real tencent_plain fallback. Do not accept arbitrary prefixes.
        for source in (
            "tencent", "tencent_plain", "eastmoney", "sina_daily",
            "sina_quote", "sina_daily+sina_quote",
        ):
            with self.subTest(source=source):
                report = active_report()
                report["market"]["上证指数"]["source"] = source
                self.assertEqual(
                    validate_report_contract(report, require_official=True), []
                )

    def test_verified_active_close_with_sector_only_outage_passes_full_checks(self):
        report = active_report()
        self.assertEqual(validate_report_contract(report, require_official=True), [])
        self.assertEqual(validate_runtime_cutover(report), [])

    def test_original_primary_source_report_stays_valid(self):
        report = active_report(sector_missing=False)
        self.assertEqual(validate_report_contract(report, require_official=True), [])
        self.assertEqual(validate_runtime_cutover(report), [])

    def test_verified_qfq_pick_keeps_normal_formal_path(self):
        report = active_report()
        pick = {
            "code": "600000", "change_pct": 1.0,
            "current_price": 10.5,
            "data_status": {"daily": "verified", "latest_date": REPORT_DATE,
                            "source": "market_history_db", "adjustment": "qfq",
                            "is_final": True, "stale": False},
        }
        report["picks_pure"] = [pick]
        report["workspace"]["views"]["baseline"] = [dict(pick)]
        self.assertEqual(validate_report_contract(report, require_official=True), [])

    def test_sector_degradation_requires_independent_evidence(self):
        def forged_db_as_quote_source(report):
            snapshots = (
                report["data_quality"]["market_close_snapshot"],
                report["selection_input_health"]["market_close_snapshot"],
                report["selection_input_health"]["formal"]["market_close_snapshot"],
            )
            for snapshot in snapshots:
                snapshot.pop("source", None)
                snapshot["quote_sources"] = {"market_history_db": 5450}

        cases = {
            "static_zero_rank": lambda r: r.update(sector_flow=[{"name": "静态板块", "flow": 0}]),
            "untrusted_quality": lambda r: r["data_quality"].update(sources_trusted=False),
            "wrong_snapshot_day": lambda r: r["data_quality"]["market_close_snapshot"].update(report_date="2026-09-28"),
            "unknown_snapshot_source": lambda r: r["data_quality"]["market_close_snapshot"].update(source="mystery"),
            "db_masquerading_as_remote_quote": forged_db_as_quote_source,
            "low_real_coverage": lambda r: r["data_quality"]["market_close_snapshot"].update(coverage_numerator=5000),
            "boolean_coverage": lambda r: r["data_quality"]["market_close_snapshot"].update(coverage_numerator=True),
            "fractional_denominator": lambda r: r["data_quality"]["market_close_snapshot"].update(coverage_denominator=5878.5),
            "malformed_pending_codes": lambda r: r["data_quality"]["market_close_snapshot"].update(identity_pending_codes=[{}]),
            "unknown_index_day": lambda r: r["data_quality"].update(index_latest_date="2026-09-28"),
            "wrong_market_index_day": lambda r: r["market"]["上证指数"].update(date="2026-09-28"),
            "unknown_market_index_source": lambda r: r["market"]["上证指数"].update(source="mystery"),
            "fake_tencent_prefix": lambda r: r["market"]["上证指数"].update(source="tencent_plain_unverified"),
            "missing_index_close": lambda r: r["market"]["上证指数"].update(close=None),
            "unknown_sector_source": lambda r: r["data_quality"].update(sector_source="mystery"),
            "false_verified_sector": lambda r: r["data_quality"].update(sector_data_status="verified"),
            "suppressed_fallback_flags": lambda r: r["data_quality"].update(fallback_used=False, stock_pool_incomplete=False),
            "wrong_pool_source": lambda r: r["data_quality"].update(stock_pool_source="sector_components"),
            "inactive_universe": lambda r: r["data_quality"]["universe_builder"].update(status="fallback"),
            "forged_final_count": lambda r: r["data_quality"]["universe_builder"].update(final_count=2),
            "mismatched_retrieval_count": lambda r: r["diagnostics"]["candidate_funnel"]["stage_counts"].update(retrieval=2),
            "fake_overlay": lambda r: r["data_quality"]["universe_builder"].update(overlay_count=1),
            "shadow_runtime": lambda r: r["data_quality"]["runtime_policy"].update(recall_strategy_mode="shadow"),
            "unpersisted_funnel": lambda r: r["diagnostics"]["candidate_funnel"].update(persist_status="pending"),
            "missing_formal_dependency": lambda r: r["selection_input_health"]["formal"].update(formal_actions_allowed=False),
            "blocked_fusion_strategy": lambda r: r["selection_input_health"]["by_strategy"]["daily_fusion"].update(formal_actions_allowed=False),
            "all_minutes_unverified": lambda r: r["selection_input_health"]["sublevels"]["30m"].update(status="unavailable", verified_count=0, missing_count=2, blocks_strategy_output=True),
            "forged_minute_codes": lambda r: r["selection_input_health"]["sublevels"]["30m"].update(verified_codes=[]),
            "malformed_minute_codes": lambda r: r["selection_input_health"]["sublevels"]["30m"].update(verified_codes=[{}]),
            "verified_minute_still_has_failure": lambda r: r["selection_input_health"]["sublevels"]["30m"].update(failure_evidence={"600000": {"status": "price_basis_unverified"}}),
            "missing_minute_evidence": lambda r: r["selection_input_health"].update(sublevels={}),
            "stale_ai_zero_claim": lambda r: r.update(forecast={"core_judgment": "板块资金全为0，市场偏弱", "risks": ["板块正流入为0/20"]}),
            "raw_formal_price": lambda r: r.update(picks_pure=[{"code":"600000", "data_status":{"daily":"verified", "latest_date":REPORT_DATE, "adjustment":"raw", "source":"market_history_db", "is_final":True}}]),
            "bad_formal_identity": lambda r: r.update(picks_pure=[{"code":"BAD", "data_status":{"daily":"verified", "latest_date":REPORT_DATE, "adjustment":"qfq", "source":"market_history_db", "is_final":True}}]),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                report = copy.deepcopy(active_report())
                mutate(report)
                errors = validate_report_contract(report, require_official=True)
                self.assertTrue(errors, label)


if __name__ == "__main__":
    unittest.main()
