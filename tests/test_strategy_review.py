import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.market_history_store import MarketHistoryStore
from chanlun.recommendation_ledger import build_recommendation_entries
from chanlun.strategy_review import (
    SCORECARD_THRESHOLDS,
    _card_evaluation_status,
    _sample_exclusion,
    build_strategy_run_manifest,
    build_strategy_scorecards,
    evaluate_recommendation_entry,
    load_strategy_sample_exclusions,
    load_review_klines_from_store,
    load_review_market_context_from_store,
    persist_review_benchmark_kline,
)


def _kline(
    dates=None,
    opens=None,
    closes=None,
    highs=None,
    lows=None,
    volumes=None,
    is_final=None,
    adjustment="qfq",
):
    dates = dates or [
        "2026-08-20",
        "2026-08-21",
        "2026-08-24",
        "2026-08-25",
        "2026-08-26",
        "2026-08-27",
    ]
    opens = opens or [100, 101, 103, 104, 106, 108]
    closes = closes or [100, 102, 104, 105, 108, 110]
    highs = highs or [101, 103, 105, 106, 109, 111]
    lows = lows or [99, 100, 102, 103, 105, 107]
    volumes = volumes or [1000] * len(dates)
    is_final = is_final or [True] * len(dates)
    return {
        "dates": dates,
        "opens": opens,
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "is_final": is_final,
        "adjustment": adjustment,
    }


def _entry(
    report_date="2026-08-20",
    code="300308",
    strategies=None,
    intended_horizon=3,
):
    strategies = strategies or [
        ("daily_pure", "pure-v1", "recommend"),
    ]
    specs = []
    for name, version, decision in strategies:
        specs.append({
            "strategy_name": name,
            "strategy_version": version,
            "source_pool": name,
            "entry_mode": "delay1_open",
            "intended_horizon": intended_horizon,
            "publication_status": "published",
            "user_action_from_decision": True,
            "items": [{
                "code": code,
                "name": "中际旭创",
                "dates": [report_date],
                "closes": [99, 100],
                "data_status": {
                    "daily": "verified",
                    "latest_date": report_date,
                    "is_final": True,
                },
                "best_buy_point": {"type": "三买", "reason": "回踩确认"},
                "decision_engine_v1": {
                    "version": "1",
                    "decision_code": decision,
                    "decision": decision,
                    "total_score": 75,
                    "risk_reasons": [],
                },
            }],
        })
    return build_recommendation_entries(
        report_date,
        report_date + "T15:10:00+08:00",
        specs,
        policy_version="decision-v1",
        config_revision="cfg-1",
        code_version="commit-1",
    )[0]


def _evaluate(entry=None, kline=None, **kwargs):
    entry = entry or _entry()
    kline = kline or _kline()
    contribution = kwargs.pop(
        "contribution", entry["strategy_contributions"][0]
    )
    trading_calendar = kwargs.pop(
        "trading_calendar", _kline()["dates"]
    )
    return evaluate_recommendation_entry(
        entry,
        kline,
        contribution=contribution,
        trading_calendar=trading_calendar,
        **kwargs,
    )


class StrategyReviewEvaluationTests(unittest.TestCase):
    def test_immediate_close_uses_signal_close_and_future_only_excursions(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        kline = _kline(
            opens=[100, 101, 103, 104, 106, 108],
            closes=[100, 105, 98, 110, 107, 112],
            # The signal-day extremes must not leak into MFE/MAE.
            highs=[150, 106, 104, 111, 109, 113],
            lows=[50, 99, 96, 97, 105, 106],
        )

        outcome = _evaluate(
            entry=entry,
            kline=kline,
            contribution=contribution,
            trading_calendar=kline["dates"],
        )

        self.assertEqual(outcome["status"], "evaluated")
        self.assertEqual(outcome["entry_date"], "2026-08-20")
        self.assertEqual(outcome["entry_price"], 100.0)
        self.assertEqual(outcome["target_dates"], {
            "t1": "2026-08-21",
            "t3": "2026-08-25",
            "t5": "2026-08-27",
        })
        self.assertAlmostEqual(outcome["returns"]["t1"], 5.0)
        self.assertAlmostEqual(outcome["returns"]["t3"], 10.0)
        self.assertAlmostEqual(outcome["returns"]["t5"], 12.0)
        self.assertAlmostEqual(outcome["mfe"]["t1"], 6.0)
        self.assertAlmostEqual(outcome["mae"]["t1"], -1.0)
        self.assertAlmostEqual(outcome["mfe"]["t3"], 11.0)
        self.assertAlmostEqual(outcome["mae"]["t3"], -4.0)

    def test_immediate_close_preserves_suspension_and_final_bar_gates(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        calendar = _kline()["dates"]
        suspended = _kline(
            dates=[calendar[0], calendar[2], calendar[3], calendar[4], calendar[5]],
            opens=[100, 103, 104, 106, 108],
            closes=[100, 104, 105, 108, 110],
            highs=[101, 105, 106, 109, 111],
            lows=[99, 102, 103, 105, 107],
        )
        nonfinal = _kline(is_final=[True, False, True, True, True, True])

        suspended_outcome = _evaluate(
            entry=entry,
            kline=suspended,
            contribution=contribution,
            trading_calendar=calendar,
        )
        nonfinal_outcome = _evaluate(
            entry=entry,
            kline=nonfinal,
            contribution=contribution,
            trading_calendar=calendar,
        )

        self.assertEqual(suspended_outcome["maturity"]["t1"], "unavailable")
        self.assertIsNone(suspended_outcome["returns"]["t1"])
        self.assertEqual(nonfinal_outcome["maturity"]["t1"], "right_censored")
        self.assertIsNone(nonfinal_outcome["returns"]["t1"])

    def test_immediate_close_does_not_compute_excursions_across_missing_path_bar(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        calendar = _kline()["dates"]
        kline = _kline(
            dates=[calendar[0], calendar[1], calendar[3], calendar[4], calendar[5]],
            opens=[100, 101, 104, 106, 108],
            closes=[100, 105, 110, 107, 112],
            highs=[150, 106, 111, 109, 113],
            lows=[50, 99, 97, 105, 106],
        )

        outcome = _evaluate(
            entry=entry,
            kline=kline,
            contribution=contribution,
            trading_calendar=calendar,
        )

        self.assertAlmostEqual(outcome["returns"]["t3"], 10.0)
        self.assertIsNone(outcome["mfe"]["t3"])
        self.assertIsNone(outcome["mae"]["t3"])

    def test_immediate_close_treats_suspended_target_and_path_as_unavailable(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        kline = _kline(
            volumes=[1000, 0, 1000, 1000, 1000, 1000]
        )

        outcome = _evaluate(
            entry=entry,
            kline=kline,
            contribution=contribution,
            trading_calendar=kline["dates"],
        )

        self.assertEqual(outcome["maturity"]["t1"], "unavailable")
        self.assertIsNone(outcome["returns"]["t1"])
        self.assertIsNotNone(outcome["returns"]["t3"])
        self.assertIsNone(outcome["mfe"]["t3"])
        self.assertIsNone(outcome["mae"]["t3"])

    def test_delay1_open_keeps_legacy_return_when_later_target_volume_is_zero(self):
        kline = _kline(
            volumes=[1000, 1000, 1000, 0, 1000, 1000]
        )

        outcome = _evaluate(kline=kline, trading_calendar=kline["dates"])

        self.assertEqual(outcome["maturity"]["t3"], "mature")
        self.assertIsNotNone(outcome["returns"]["t3"])
        self.assertIsNotNone(outcome["mfe"]["t3"])
        self.assertIsNotNone(outcome["mae"]["t3"])

    def test_immediate_close_fails_closed_when_frozen_close_or_adjustment_differs(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        entry["reference_close"] = 101.0
        entry["reference_adjustment"] = "qfq"

        close_mismatch = _evaluate(
            entry=entry,
            contribution=contribution,
        )
        entry["reference_close"] = 100.0
        entry["reference_adjustment"] = "none"
        adjustment_mismatch = _evaluate(
            entry=entry,
            contribution=contribution,
        )

        self.assertEqual(close_mismatch["status"], "reference_close_mismatch")
        self.assertEqual(
            close_mismatch["returns"],
            {"t1": None, "t3": None, "t5": None},
        )
        self.assertEqual(
            adjustment_mismatch["status"],
            "reference_adjustment_mismatch",
        )

    def test_immediate_close_benchmark_uses_same_signal_close_and_target_dates(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        entry["reference_adjustment"] = "qfq"
        benchmark = _kline(
            opens=[200, 200, 202, 204, 206, 208],
            closes=[200, 202, 204, 206, 208, 210],
            highs=[201, 203, 205, 207, 209, 211],
            lows=[199, 199, 201, 203, 205, 207],
        )

        outcome = _evaluate(
            entry=entry,
            contribution=contribution,
            benchmark_kline=benchmark,
        )

        self.assertEqual(outcome["benchmark_status"], "aligned")
        self.assertAlmostEqual(
            outcome["excess_returns"]["t1"],
            outcome["returns"]["t1"] - 1.0,
        )

    def test_uses_next_open_and_reports_t1_t3_t5_after_maturity(self):
        outcome = _evaluate()

        self.assertEqual(outcome["status"], "evaluated")
        self.assertEqual(outcome["entry_date"], "2026-08-21")
        self.assertEqual(outcome["entry_price"], 101.0)
        self.assertAlmostEqual(outcome["returns"]["t1"], 0.990099, places=5)
        self.assertAlmostEqual(outcome["returns"]["t3"], 3.960396, places=5)
        self.assertAlmostEqual(outcome["returns"]["t5"], 8.910891, places=5)
        self.assertEqual(outcome["maturity"]["t5"], "mature")

    def test_right_censoring_does_not_turn_immature_horizon_into_loss(self):
        kline = _kline(
            dates=["2026-08-20", "2026-08-21", "2026-08-24"],
            opens=[100, 101, 103],
            closes=[100, 102, 104],
            highs=[101, 103, 105],
            lows=[99, 100, 102],
        )
        outcome = _evaluate(
            kline=kline,
            trading_calendar=kline["dates"],
        )

        self.assertEqual(outcome["status"], "partial")
        self.assertIsNotNone(outcome["returns"]["t1"])
        self.assertIsNone(outcome["returns"]["t3"])
        self.assertIsNone(outcome["returns"]["t5"])
        self.assertEqual(outcome["maturity"]["t3"], "right_censored")

    def test_suspended_or_one_price_locked_entry_is_not_executable(self):
        suspended = _kline(volumes=[1000, 0, 1000, 1000, 1000, 1000])
        locked = _kline(
            opens=[100, 110, 111, 112, 113, 114],
            closes=[100, 110, 111, 112, 113, 114],
            highs=[101, 110, 112, 113, 114, 115],
            lows=[99, 110, 110, 111, 112, 113],
        )

        self.assertEqual(
            _evaluate(kline=suspended)["status"],
            "suspended_entry",
        )
        self.assertEqual(
            _evaluate(kline=locked)["status"],
            "limit_locked_entry",
        )

    def test_one_price_limit_down_is_not_filtered_as_an_unexecutable_buy(self):
        limit_down = _kline(
            opens=[100, 90, 91, 92, 93, 94],
            closes=[100, 90, 91, 92, 93, 94],
            highs=[101, 90, 92, 93, 94, 95],
            lows=[99, 90, 90, 91, 92, 93],
        )

        outcome = _evaluate(kline=limit_down)

        self.assertIn(outcome["status"], {"partial", "evaluated"})
        self.assertEqual(outcome["entry_price"], 90.0)

    def test_adjustment_mismatch_fails_closed(self):
        outcome = _evaluate(
            kline=_kline(adjustment="none")
        )

        self.assertEqual(outcome["status"], "adjustment_mismatch")
        self.assertEqual(outcome["returns"], {"t1": None, "t3": None, "t5": None})

    def test_missing_finality_fails_closed(self):
        kline = _kline()
        kline.pop("is_final")

        outcome = _evaluate(kline=kline)

        self.assertEqual(outcome["status"], "market_data_invalid")
        self.assertEqual(outcome["returns"], {"t1": None, "t3": None, "t5": None})

    def test_nonfinal_recommendation_bar_is_not_evaluated(self):
        kline = _kline(is_final=[False, True, True, True, True, True])

        outcome = _evaluate(kline=kline)

        self.assertEqual(outcome["status"], "recommendation_not_final")
        self.assertEqual(outcome["returns"], {"t1": None, "t3": None, "t5": None})

    def test_benchmark_requires_aligned_dates_and_exposes_excess_returns(self):
        benchmark = _kline(
            opens=[100, 100, 100, 100, 100, 100],
            closes=[100, 101, 101, 102, 102, 103],
            highs=[101, 102, 102, 103, 103, 104],
            lows=[99, 99, 99, 99, 99, 99],
        )
        outcome = _evaluate(
            benchmark_kline=benchmark
        )

        self.assertEqual(outcome["benchmark_status"], "aligned")
        self.assertAlmostEqual(
            outcome["excess_returns"]["t1"],
            outcome["returns"]["t1"] - 1.0,
            places=5,
        )

    def test_missing_stock_bar_does_not_shift_entry_to_the_next_available_day(self):
        calendar = _kline()["dates"]
        stock = _kline(
            dates=[calendar[0]] + calendar[2:],
            opens=[100, 103, 104, 106, 108],
            closes=[100, 104, 105, 108, 110],
            highs=[101, 105, 106, 109, 111],
            lows=[99, 102, 103, 105, 107],
        )

        outcome = _evaluate(kline=stock, trading_calendar=calendar)

        self.assertEqual(outcome["status"], "suspended_entry")
        self.assertEqual(outcome["entry_date"], "")

    def test_benchmark_alignment_is_checked_for_each_horizon(self):
        calendar = _kline()["dates"]
        benchmark = _kline()
        stock = _kline(
            dates=[calendar[0], calendar[1], calendar[2], calendar[4], calendar[5]],
            opens=[100, 101, 103, 106, 108],
            closes=[100, 102, 104, 108, 110],
            highs=[101, 103, 105, 109, 111],
            lows=[99, 100, 102, 105, 107],
        )

        outcome = _evaluate(
            kline=stock,
            trading_calendar=calendar,
            benchmark_kline=benchmark,
        )

        self.assertEqual(outcome["maturity"]["t3"], "unavailable")
        self.assertIsNone(outcome["excess_returns"]["t3"])

    def test_multiple_entry_modes_require_the_current_contribution(self):
        entry = _entry(strategies=[
            ("daily_pure", "pure-v1", "recommend"),
            ("daily_fusion", "fusion-v2", "recommend"),
        ])
        entry["strategy_contributions"][1]["entry_mode"] = "same_close"

        outcome = evaluate_recommendation_entry(
            entry,
            _kline(),
            trading_calendar=_kline()["dates"],
        )

        self.assertEqual(outcome["status"], "entry_mode_unknown")


class StrategyScorecardTests(unittest.TestCase):
    def test_price_basis_incident_excludes_exact_20260903_baseline_rows(self):
        exclusions = load_strategy_sample_exclusions()
        incident_id = "price-basis-mismatch-2026-09-03-daily-pure"
        incident = next(
            row for row in exclusions
            if row.get("incident_id") == incident_id
        )
        invalid_codes = {
            "000935", "300115", "300308", "600350", "601100",
            "603271", "603341", "688006", "688525", "688800",
        }

        self.assertEqual(set(incident["codes"]), invalid_codes)
        contribution = {
            "strategy_name": "daily_pure",
            "source_pool": "picks_pure",
        }
        for code in invalid_codes:
            self.assertEqual(
                _sample_exclusion(
                    {"report_date": "2026-09-03", "code": code},
                    contribution,
                    exclusions,
                ),
                {
                    "incident_id": incident_id,
                    "reason": "strategy_input_stale_or_unverified",
                },
            )
        self.assertIsNone(_sample_exclusion(
            {"report_date": "2026-09-03", "code": "002272"},
            contribution,
            exclusions,
        ))
        self.assertIsNone(_sample_exclusion(
            {"report_date": "2026-09-02", "code": "300115"},
            contribution,
            exclusions,
        ))

    def test_explicit_input_incident_excludes_sample_without_rewriting_ledger(self):
        valid = _entry(
            report_date="2026-08-20",
            code="300308",
            strategies=[("daily_fusion", "fusion-v2", "recommend")],
        )
        invalid = _entry(
            report_date="2026-08-21",
            code="300139",
            strategies=[("daily_fusion", "fusion-v2", "recommend")],
        )
        for entry in (valid, invalid):
            entry["reference_close"] = 100.0
            entry["reference_adjustment"] = "qfq"
            entry["strategy_contributions"][0]["entry_mode"] = "immediate_close"

        card = build_strategy_scorecards(
            [valid, invalid],
            {"300308": _kline(), "300139": _kline()},
            trading_calendar=_kline()["dates"],
            sample_exclusions=[{
                "incident_id": "test-stale-30m",
                "report_dates": ["2026-08-21"],
                "strategy_names": ["daily_fusion"],
                "source_pools": ["daily_fusion"],
                "codes": ["300139"],
                "reason": "strategy_input_stale_or_unverified",
            }],
        )["formal"][0]

        self.assertEqual(card["signal_count"], 2)
        self.assertEqual(card["eligible_signal_count"], 1)
        self.assertEqual(card["excluded_signal_count"], 1)
        self.assertEqual(card["episode_count"], 1)
        self.assertEqual(card["sample_exclusions"], [{
            "incident_id": "test-stale-30m",
            "reason": "strategy_input_stale_or_unverified",
            "count": 1,
        }])

    def test_all_eligible_samples_excluded_by_input_incident_is_data_unavailable(self):
        entry = _entry(
            report_date="2026-08-21",
            code="300139",
            strategies=[("daily_fusion", "fusion-v2", "recommend")],
        )
        entry["reference_close"] = 100.0
        entry["reference_adjustment"] = "qfq"
        entry["strategy_contributions"][0]["entry_mode"] = "immediate_close"

        card = build_strategy_scorecards(
            [entry],
            {"300139": _kline()},
            trading_calendar=_kline()["dates"],
            sample_exclusions=[{
                "incident_id": "test-stale-30m",
                "report_dates": ["2026-08-21"],
                "strategy_names": ["daily_fusion"],
                "source_pools": ["daily_fusion"],
                "codes": ["300139"],
                "reason": "strategy_input_stale_or_unverified",
            }],
        )["formal"][0]

        self.assertEqual(0, card["eligible_signal_count"])
        self.assertEqual(1, card["excluded_signal_count"])
        self.assertEqual("data_unavailable", card["evaluation_status"])

    def test_v2_sections_keep_pool_roles_and_source_pool_identity(self):
        entries = [
            _entry(
                code="300308",
                strategies=[("daily_fusion", "fusion-v2", "recommend")],
            ),
            _entry(
                code="300139",
                strategies=[("daily_pure", "pure-v1", "recommend")],
            ),
            _entry(
                code="688041",
                strategies=[("next_day_boom", "boom-v1", "observe")],
                intended_horizon=1,
            ),
            _entry(
                code="600001",
                strategies=[("observation_gate", "gate-v1", "recommend")],
            ),
        ]

        scorecards = build_strategy_scorecards(
            entries,
            {entry["code"]: _kline() for entry in entries},
            trading_calendar=_kline()["dates"],
        )

        self.assertEqual(scorecards["schema_version"], 2)
        self.assertEqual(
            scorecards["thresholds"],
            {"mature_samples": 100, "active_dates": 20, "calendar_months": 2},
        )
        self.assertEqual(
            {row["evaluation_role"] for row in scorecards["formal"]},
            {"formal"},
        )
        self.assertEqual(
            {row["evaluation_role"] for row in scorecards["baselines"]},
            {"baseline"},
        )
        self.assertEqual(
            {row["evaluation_role"] for row in scorecards["research"]},
            {"research"},
        )
        self.assertEqual(
            {row["evaluation_role"] for row in scorecards["gates"]},
            {"diagnostic"},
        )
        for section in ("formal", "baselines", "research"):
            for card in scorecards[section]:
                self.assertIn("source_pool", card)
                self.assertIn("signal_count", card)
                self.assertIn("eligible_signal_count", card)
                self.assertIn("episode_count", card)
                self.assertIn("maturity_by_horizon", card)
                self.assertIn("metrics_by_horizon", card)

    def test_v2_horizon_metrics_disclose_maturity_and_independent_denominators(self):
        entry = _entry(intended_horizon=None)
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        entry["reference_close"] = 100.0
        entry["reference_adjustment"] = "qfq"
        scorecards = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )
        card = scorecards["baselines"][0]

        self.assertIsNone(card["intended_horizon"])
        self.assertIsNone(card["overall_verdict"])
        self.assertEqual(card["signal_count"], 1)
        self.assertEqual(card["eligible_signal_count"], 1)
        self.assertEqual(card["episode_count"], 1)
        for horizon in ("t1", "t3", "t5"):
            maturity = card["maturity_by_horizon"][horizon]
            self.assertEqual(set(maturity), {"mature", "waiting", "unavailable"})
            progress = card["comparison_progress_by_horizon"][horizon]
            self.assertEqual(progress["mature_samples"], maturity["mature"])
            self.assertEqual(progress["required_mature_samples"], 100)
            self.assertEqual(progress["required_active_dates"], 20)
            self.assertEqual(progress["required_calendar_months"], 2)
            self.assertEqual(card["metrics_by_horizon"][horizon], {})
        self.assertIsNone(card["returns"]["t1"])
        self.assertIsNone(card["win_rates"]["t1"])
        self.assertEqual(card["representative_samples"], [])

    def test_scorecards_separate_exact_comparison_identity_by_research_tier(self):
        historical = _entry(report_date="2026-08-20")
        prospective = _entry(report_date="2026-08-21")
        historical["strategy_contributions"][0]["research_tier"] = (
            "historical_replay"
        )
        prospective["strategy_contributions"][0]["research_tier"] = (
            "prospective_oot"
        )

        cards = build_strategy_scorecards(
            [historical, prospective],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["baselines"]

        self.assertEqual(len(cards), 2)
        self.assertEqual(
            {card["research_tier"] for card in cards},
            {"historical_replay", "prospective_oot"},
        )
        for card in cards:
            self.assertEqual(
                set(card["comparison_identity"]),
                {
                    "strategy", "version", "source_pool", "entry_mode",
                    "intended_horizon", "research_tier",
                },
            )
            self.assertEqual(
                card["comparison_identity"]["research_tier"],
                card["research_tier"],
            )

    def test_mature_comparison_exposes_only_explainable_metrics(self):
        entry = _entry(intended_horizon=3)
        with mock.patch.dict(
            SCORECARD_THRESHOLDS,
            {"mature_samples": 1, "active_dates": 1, "calendar_months": 1},
            clear=True,
        ):
            card = build_strategy_scorecards(
                [entry],
                {"300308": _kline()},
                trading_calendar=_kline()["dates"],
                benchmark_kline=_kline(),
            )["baselines"][0]

        self.assertEqual(
            card["horizon_readiness"]["t3"],
            "ready_for_manual_comparison",
        )
        metrics = card["metrics_by_horizon"]["t3"]
        for field in (
            "n", "date_start", "date_end", "median", "mean",
            "excess_mean", "max_drawdown", "mean_mfe", "mean_mae",
        ):
            self.assertIn(field, metrics)
            self.assertIsNotNone(metrics[field])
        self.assertNotIn("composite_score", metrics)
        self.assertEqual(metrics["n"], 1)
        self.assertEqual(len(card["representative_samples"]), 1)

    def test_right_censored_rows_do_not_inflate_mature_comparison_coverage(self):
        mature = _entry(report_date="2026-08-20", code="300308")
        waiting = _entry(report_date="2026-08-27", code="300139")
        with mock.patch.dict(
            SCORECARD_THRESHOLDS,
            {"mature_samples": 1, "active_dates": 1, "calendar_months": 1},
            clear=True,
        ):
            card = build_strategy_scorecards(
                [mature, waiting],
                {"300308": _kline(), "300139": _kline()},
                trading_calendar=_kline()["dates"],
            )["baselines"][0]

        progress = card["comparison_progress_by_horizon"]["t3"]
        self.assertEqual(progress["mature_samples"], 1)
        self.assertEqual(progress["waiting_samples"], 1)
        self.assertEqual(progress["active_dates"], 1)
        self.assertEqual(progress["active_months"], 1)
        self.assertEqual(card["metrics_by_horizon"]["t3"]["n"], 1)

    def test_legacy_roles_are_corrected_and_unknown_rows_fail_closed(self):
        known = _entry(
            strategies=[("daily_pure", "pure-v1", "recommend")]
        )
        unknown = _entry(
            code="300139",
            strategies=[("renamed_strategy", "v9", "recommend")],
        )
        for row in known["strategy_contributions"] + unknown["strategy_contributions"]:
            for field in (
                "evaluation_role", "publication_surface",
                "evaluation_eligible", "eligibility_reason",
            ):
                row.pop(field, None)

        scorecards = build_strategy_scorecards(
            [known, unknown],
            {"300308": _kline(), "300139": _kline()},
            trading_calendar=_kline()["dates"],
        )

        self.assertEqual(len(scorecards["baselines"]), 1)
        self.assertEqual(
            scorecards["baselines"][0]["classification_status"],
            "legacy_corrected",
        )
        self.assertFalse(scorecards["formal"])
        self.assertTrue(scorecards["classification_failures"])
        self.assertEqual(
            scorecards["classification_failures"][0]["strategy"],
            "renamed_strategy",
        )

    def test_research_reference_close_gap_withholds_partial_metrics(self):
        entry = _entry(
            strategies=[("luojie_pool", "luojie-v1", "observe")],
            intended_horizon=None,
        )
        contribution = entry["strategy_contributions"][0]
        contribution["entry_mode"] = "immediate_close"
        entry["reference_close"] = None
        entry["reference_close_source"] = "missing"
        entry["reference_adjustment"] = "qfq"

        scorecards = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )
        card = scorecards["research"][0]

        self.assertFalse(card["metrics_publishable"])
        self.assertIn("reference_close_missing", card["metrics_blocking_reasons"])
        self.assertNotIn("market_data_unavailable", card["metrics_blocking_reasons"])
        self.assertTrue(all(
            metric == {}
            for metric in card["metrics_by_horizon"].values()
        ))
        self.assertEqual(card["returns"], {"t1": None, "t3": None, "t5": None})
        self.assertEqual(card["median_returns"], {"t1": None, "t3": None, "t5": None})
        self.assertEqual(card["excess_returns"], {"t1": None, "t3": None, "t5": None})
        self.assertEqual(card["win_rates"], {"t1": None, "t3": None, "t5": None})
        self.assertEqual(card["excursions"], {
            "mae": {"t1": None, "t3": None, "t5": None},
            "mfe": {"t1": None, "t3": None, "t5": None},
        })
        self.assertEqual(card["representative_samples"], [])

    def test_explicit_invalid_or_conflicting_role_is_classification_failure(self):
        invalid = _entry(
            strategies=[("daily_pure", "pure-v1", "recommend")],
        )
        invalid["strategy_contributions"][0]["evaluation_role"] = "unknown"
        conflict = _entry(
            code="300139",
            strategies=[("daily_pure", "pure-v1", "recommend")],
        )
        conflict["strategy_contributions"][0]["evaluation_role"] = "formal"

        scorecards = build_strategy_scorecards(
            [invalid, conflict],
            {"300308": _kline(), "300139": _kline()},
            trading_calendar=_kline()["dates"],
        )

        self.assertFalse(scorecards["baselines"])
        self.assertFalse(scorecards["formal"])
        reasons = {row["reason"] for row in scorecards["classification_failures"]}
        self.assertIn("evaluation_role_invalid", reasons)
        self.assertIn("evaluation_role_conflict", reasons)

    def test_formal_candidates_without_eligible_recommendations_are_normal_empty(self):
        entry = _entry(
            strategies=[("daily_fusion", "fusion-v2", "observe")],
        )
        card = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["formal"][0]

        self.assertEqual(card["signal_count"], 1)
        self.assertEqual(card["eligible_signal_count"], 0)
        self.assertEqual(card["evaluation_status"], "no_formal_recommendations")

    def test_gate_status_is_independent_from_return_readiness(self):
        entry = _entry(
            strategies=[("observation_gate", "gate-v1", "observe")],
        )
        card = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["gates"][0]

        self.assertEqual(card["evaluation_status"], "running")
        self.assertEqual(card["gate_status"], "running")

    def test_readiness_uses_intended_horizon_and_exposes_each_horizon(self):
        maturity = {
            "t1": {"mature": 100, "waiting": 0, "unavailable": 0},
            "t3": {"mature": 0, "waiting": 100, "unavailable": 0},
            "t5": {"mature": 0, "waiting": 100, "unavailable": 0},
        }
        status_t3 = _card_evaluation_status(
            role="research",
            signal_count=100,
            eligible_signal_count=100,
            maturity=maturity,
            metrics_publishable=True,
            metrics_blocking_reasons=[],
            active_dates=20,
            active_months=2,
            intended_horizon=3,
        )
        status_unspecified = _card_evaluation_status(
            role="baseline",
            signal_count=100,
            eligible_signal_count=100,
            maturity=maturity,
            metrics_publishable=True,
            metrics_blocking_reasons=[],
            active_dates=20,
            active_months=2,
            intended_horizon=None,
        )

        self.assertEqual(status_t3, "waiting_for_maturity")
        self.assertNotEqual(status_unspecified, "ready_for_manual_comparison")

    def test_gate_section_only_contains_decision_and_user_action_counts(self):
        entry = _entry(
            strategies=[("observation_gate", "gate-v1", "recommend")]
        )
        scorecards = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )
        card = scorecards["gates"][0]

        self.assertIn("gate_outcomes", card)
        self.assertIn("publication_outcomes", card)
        for forbidden in (
            "returns", "win_rate", "sample_size", "metrics_by_horizon",
        ):
            self.assertNotIn(forbidden, card)
        self.assertEqual(card["ledger_active_dates"], 1)
        self.assertEqual(card["ledger_date_start"], "2026-08-20")
        self.assertEqual(card["ledger_date_end"], "2026-08-20")

    def test_verified_benchmark_history_is_persisted_for_runtime_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "market-history.sqlite"
            with MarketHistoryStore(db_path) as store:
                stock_id = store.upsert_instrument(
                    "stock", "SZ", "300308", "中际旭创"
                )
                source = _kline()
                store.upsert_bars("day", stock_id, [
                    {
                        "ts": trade_date,
                        "open": source["opens"][index],
                        "close": source["closes"][index],
                        "high": source["highs"][index],
                        "low": source["lows"][index],
                        "volume": source["volumes"][index],
                        "amount": 1000000,
                        "adjustment": "qfq",
                        "is_final": True,
                    }
                    for index, trade_date in enumerate(source["dates"])
                ])

            diagnostics = persist_review_benchmark_kline(db_path, _kline())
            _stocks, calendar, benchmark, review_diagnostics = (
                load_review_market_context_from_store(
                    db_path, [_entry()], as_of="2026-08-27"
                )
            )

        self.assertEqual(diagnostics["status"], "ok")
        self.assertEqual(review_diagnostics["benchmark_status"], "ok")
        self.assertEqual(benchmark["code"], "000300")
        self.assertEqual(calendar, _kline()["dates"])

    def test_market_history_loader_preserves_canonical_adjustment_and_finality(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "market-history.sqlite"
            with MarketHistoryStore(db_path) as store:
                instrument_id = store.upsert_instrument(
                    "stock", "SZ", "300308", "中际旭创"
                )
                benchmark_id = store.upsert_instrument(
                    "index", "SH", "000300", "沪深300"
                )
                bars = []
                source = _kline()
                for index, trade_date in enumerate(source["dates"]):
                    bars.append({
                        "ts": trade_date,
                        "open": source["opens"][index],
                        "close": source["closes"][index],
                        "high": source["highs"][index],
                        "low": source["lows"][index],
                        "volume": source["volumes"][index],
                        "amount": 1000000,
                        "adjustment": "qfq",
                        "is_final": True,
                    })
                store.upsert_bars("day", instrument_id, bars)
                store.upsert_bars("day", benchmark_id, bars)
                for trade_date in source["dates"]:
                    store.upsert_trade_calendar("SH", trade_date, True)

            klines, calendar, benchmark, diagnostics = (
                load_review_market_context_from_store(
                db_path, [_entry()], as_of="2026-08-27"
                )
            )

        self.assertEqual(diagnostics["status"], "ok")
        self.assertEqual(diagnostics["resolved_codes"], 1)
        self.assertEqual(klines["300308"]["adjustment"], "qfq")
        self.assertTrue(all(klines["300308"]["is_final"]))
        self.assertEqual(calendar, source["dates"])
        self.assertEqual(benchmark["code"], "000300")
        self.assertEqual(diagnostics["benchmark_status"], "ok")

    def test_cross_strategy_attribution_and_gate_outcomes_are_separate(self):
        recommend = _entry(strategies=[
            ("daily_pure", "pure-v1", "recommend"),
            ("daily_fusion", "fusion-v2", "recommend"),
        ])
        observe = _entry(
            code="300139",
            strategies=[("daily_pure", "pure-v1", "observe")],
        )

        cards = build_strategy_scorecards(
            [recommend, observe],
            {"300308": _kline(), "300139": _kline()},
            trading_calendar=_kline()["dates"],
        )
        by_name = {
            card["strategy"]: card
            for section in ("formal", "baselines", "research")
            for card in cards[section]
        }

        self.assertEqual(by_name["daily_pure"]["sample_size"], 2)
        self.assertEqual(by_name["daily_fusion"]["sample_size"], 1)
        self.assertEqual(
            by_name["daily_pure"]["evaluation_contract_signal_count"], 2
        )
        self.assertEqual(
            by_name["daily_pure"]["non_evaluation_signal_count"], 0
        )
        self.assertEqual(by_name["daily_pure"]["gate_outcomes"]["observe"], 1)
        self.assertEqual(by_name["daily_pure"]["gate_outcomes"]["recommend"], 1)
        self.assertIn("median_returns", by_name["daily_pure"])
        self.assertIn("excess_returns", by_name["daily_pure"])
        self.assertIn("mae", by_name["daily_pure"]["excursions"])
        self.assertIsNone(by_name["daily_pure"]["win_rates"]["t1"])
        self.assertEqual(
            by_name["daily_pure"]["comparison_progress_by_horizon"]["t1"][
                "mature_samples"
            ],
            2,
        )
        self.assertEqual(by_name["daily_pure"]["ledger_active_dates"], 1)
        self.assertEqual(by_name["daily_pure"]["ledger_date_start"], "2026-08-20")
        self.assertEqual(by_name["daily_pure"]["ledger_date_end"], "2026-08-20")

    def test_consecutive_recommendations_are_deduped_into_one_episode(self):
        first = _entry("2026-08-20")
        second = _entry("2026-08-21")
        kline = _kline(
            dates=[
                "2026-08-20", "2026-08-21", "2026-08-24",
                "2026-08-25", "2026-08-26", "2026-08-27",
                "2026-08-28",
            ],
            opens=[100, 101, 103, 104, 106, 108, 109],
            closes=[100, 102, 104, 105, 108, 110, 111],
            highs=[101, 103, 105, 106, 109, 111, 112],
            lows=[99, 100, 102, 103, 105, 107, 108],
        )

        cards = build_strategy_scorecards(
            [first, second], {"300308": kline},
            trading_calendar=kline["dates"],
        )

        self.assertEqual(cards["baselines"][0]["episode_count"], 1)
        self.assertEqual(cards["baselines"][0]["sample_size"], 1)

    def test_trading_day_gap_starts_a_new_episode_even_without_other_ledger_rows(self):
        first = _entry("2026-08-20")
        second = _entry("2026-08-25")
        kline = _kline(
            dates=[
                "2026-08-20", "2026-08-21", "2026-08-24",
                "2026-08-25", "2026-08-26", "2026-08-27",
                "2026-08-28", "2026-08-31", "2026-09-01",
            ],
            opens=[100, 101, 102, 103, 104, 105, 106, 107, 108],
            closes=[100, 101, 102, 103, 104, 105, 106, 107, 108],
            highs=[101, 102, 103, 104, 105, 106, 107, 108, 109],
            lows=[99, 100, 101, 102, 103, 104, 105, 106, 107],
        )

        cards = build_strategy_scorecards(
            [first, second], {"300308": kline},
            trading_calendar=kline["dates"],
        )

        self.assertEqual(cards["baselines"][0]["episode_count"], 2)

    def test_representative_samples_are_bounded_and_attributed(self):
        entries = [
            _entry(code="{:06d}".format(300300 + index))
            for index in range(5)
        ]
        klines = {entry["code"]: copy.deepcopy(_kline()) for entry in entries}

        with mock.patch.dict(
            SCORECARD_THRESHOLDS,
            {"mature_samples": 1, "active_dates": 1, "calendar_months": 1},
            clear=True,
        ):
            card = build_strategy_scorecards(
                entries, klines, trading_calendar=_kline()["dates"]
            )["baselines"][0]

        self.assertLessEqual(len(card["representative_samples"]), 3)
        sample = card["representative_samples"][0]
        self.assertIn("recommendation_id", sample)
        self.assertEqual(sample["strategy"], "daily_pure")
        self.assertIn("reason_summary", sample)

    def test_intended_t1_strategy_uses_mature_t1_representative_sample(self):
        item = {
            "code": "300308",
            "name": "中际旭创",
            "closes": [99, 100],
            "best_buy_point": {"type": "启动", "reason": "次日策略"},
            "decision_engine_v1": {
                "version": "1",
                "decision_code": "recommend",
                "decision": "推荐",
            },
        }
        entry = build_recommendation_entries(
            "2026-08-20",
            "2026-08-20T15:10:00+08:00",
            [{
                "strategy_name": "next_day_boom",
                "strategy_version": "boom-v1",
                "entry_mode": "delay1_open",
                "intended_horizon": 1,
                "publication_status": "published",
                "user_action": "recommendation",
                "items": [item],
            }],
            policy_version="decision-v1",
            config_revision="cfg-1",
            code_version="commit-1",
        )[0]
        kline = _kline(
            dates=["2026-08-20", "2026-08-21"],
            opens=[100, 101],
            closes=[100, 102],
            highs=[101, 103],
            lows=[99, 100],
        )

        with mock.patch.dict(
            SCORECARD_THRESHOLDS,
            {"mature_samples": 1, "active_dates": 1, "calendar_months": 1},
            clear=True,
        ):
            card = build_strategy_scorecards(
                [entry], {"300308": kline},
                trading_calendar=kline["dates"],
            )["research"][0]

        self.assertEqual(card["intended_horizon"], 1)
        self.assertEqual(card["sample_size"], 1)
        self.assertEqual(len(card["representative_samples"]), 1)
        self.assertTrue(
            card["representative_samples"][0]["outcome_label"].startswith(
                "T+1"
            )
        )

    def test_internal_observation_gate_never_enters_recommendation_cohort(self):
        entry = _entry(
            strategies=[("observation_gate", "gate-v1", "recommend")]
        )
        contribution = entry["strategy_contributions"][0]
        contribution["publication_status"] = "internal"
        contribution["user_action"] = "watch"
        contribution["cohort_eligible"] = False

        card = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["gates"][0]

        self.assertEqual(card["signal_count"], 1)
        self.assertNotIn("sample_size", card)
        self.assertEqual(card["gate_outcomes"]["recommend"], 1)
        self.assertEqual(card["publication_outcomes"]["watch"], 1)

    def test_unknown_horizon_is_not_silently_labeled_t3(self):
        entry = _entry(intended_horizon=None)

        card = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["baselines"][0]

        self.assertIsNone(card["intended_horizon"])
        self.assertIsNone(card["win_rate"])
        self.assertGreater(card["evaluable_episode_count"], 0)

    def test_attribution_status_is_order_independent_and_reports_mixed(self):
        verified = _entry()
        unknown = copy.deepcopy(verified)
        unknown["report_date"] = "2026-08-21"
        unknown["recommendation_id"] = "rec:unknown"
        unknown["strategy_contributions"][0]["attribution_status"] = (
            "legacy_unknown"
        )

        first = build_strategy_scorecards(
            [verified, unknown],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["baselines"][0]
        second = build_strategy_scorecards(
            [unknown, verified],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )["baselines"][0]

        self.assertEqual(first["attribution_status"], "mixed")
        self.assertEqual(first["attribution_status"], second["attribution_status"])
        self.assertEqual(
            first["attribution_status_counts"],
            second["attribution_status_counts"],
        )

    def test_scorecards_separate_entry_mode_and_intended_horizon(self):
        close_entry = _entry(intended_horizon=3)
        close_contribution = close_entry["strategy_contributions"][0]
        close_contribution["entry_mode"] = "immediate_close"
        open_entry = copy.deepcopy(close_entry)
        open_entry["report_date"] = "2026-08-21"
        open_entry["recommendation_id"] = "rec:delay1-open"
        open_contribution = open_entry["strategy_contributions"][0]
        open_contribution["entry_mode"] = "delay1_open"
        open_contribution["intended_horizon"] = 1

        cards = build_strategy_scorecards(
            [close_entry, open_entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )

        identities = {
            (
                card["strategy"],
                card["version"],
                card["entry_mode"],
                card["intended_horizon"],
            )
            for card in cards["baselines"]
        }
        self.assertEqual(identities, {
            ("daily_pure", "pure-v1", "immediate_close", 3),
            ("daily_pure", "pure-v1", "delay1_open", 1),
        })

    def test_run_manifest_keeps_zero_signal_and_disabled_strategies_visible(self):
        manifest = build_strategy_run_manifest({
            "date": "2026-08-26",
            "selection_input_health": {
                "schema_version": 2,
                "formal": {"formal_actions_allowed": True},
                "by_strategy": {
                    "daily_fusion": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "luojie_pool": {"status": "verified"},
                },
            },
            "picks_pure": [],
            "picks_fusion": [],
            "observation_watchlist": [],
            "next_day_boom": {
                "mode": "disabled",
                "reason": "市场条件未触发",
                "candidates": [],
            },
            "luojie_pool": {"mode": "enabled", "candidates": []},
            "h4_t3_pool": {
                "mode": "production",
                "status": "ok",
                "production_attested": True,
                "strategy_version": "h4_t3_k30_tail_safe_v1",
                "candidates": [],
            },
        })

        cards = build_strategy_scorecards(
            [], {}, trading_calendar=[], run_manifest=manifest
        )
        formal = {card["strategy"]: card for card in cards["formal"]}
        research = {card["strategy"]: card for card in cards["research"]}

        self.assertEqual(formal["h4_t3"]["evaluation_status"], "no_signals")
        self.assertEqual(formal["h4_t3"]["latest_run_status"], "verified_empty")
        self.assertEqual(formal["h4_t3"]["signal_count"], 0)
        self.assertEqual(
            research["next_day_boom"]["evaluation_status"], "disabled"
        )
        self.assertEqual(
            research["next_day_boom"]["latest_run_reason"],
            "市场条件未触发",
        )
        self.assertEqual(cards["gates"][0]["evaluation_status"], "normal_empty")

    def test_fusion_input_incident_does_not_block_healthy_h4_empty_run(self):
        manifest = build_strategy_run_manifest({
            "date": "2026-08-26",
            "selection_input_health": {
                "schema_version": 2,
                "formal": {
                    "status": "partial",
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": False,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "unavailable",
                        "formal_actions_allowed": False,
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "luojie_pool": {"status": "verified"},
                },
            },
            "picks_pure": [],
            "picks_fusion": [{"code": "300697"}],
            "observation_watchlist": [],
            "next_day_boom": {"mode": "disabled", "candidates": []},
            "luojie_pool": {"mode": "enabled", "candidates": []},
            "h4_t3_pool": {
                "mode": "production",
                "status": "ok",
                "production_attested": True,
                "strategy_version": "h4_t3_k30_tail_safe_v1",
                "candidates": [],
            },
        })

        by_strategy = {row["strategy"]: row for row in manifest}
        self.assertEqual("unavailable", by_strategy["daily_fusion"]["run_status"])
        self.assertEqual("verified_empty", by_strategy["h4_t3"]["run_status"])

        cards = build_strategy_scorecards(
            [], {}, trading_calendar=[], run_manifest=manifest
        )
        formal = {card["strategy"]: card for card in cards["formal"]}
        self.assertEqual("data_unavailable", formal["daily_fusion"]["evaluation_status"])
        self.assertEqual(
            ["strategy_input_stale_or_unverified"],
            formal["daily_fusion"]["metrics_blocking_reasons"],
        )
        self.assertEqual("no_signals", formal["h4_t3"]["evaluation_status"])

    def test_h4_upstream_contract_mismatch_has_its_own_scorecard_blocker(self):
        manifest = build_strategy_run_manifest({
            "date": "2026-08-26",
            "selection_input_health": {
                "schema_version": 2,
                "formal": {
                    "status": "partial",
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": False,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "h4_t3": {
                        "status": "unavailable",
                        "formal_actions_allowed": False,
                        "blocking_reason": "strategy_upstream_contract_mismatch",
                    },
                    "luojie_pool": {"status": "verified"},
                },
            },
            "picks_pure": [],
            "picks_fusion": [],
            "observation_watchlist": [],
            "next_day_boom": {"mode": "disabled", "candidates": []},
            "luojie_pool": {"mode": "enabled", "candidates": []},
            "h4_t3_pool": {
                "mode": "production",
                "status": "ok",
                "production_attested": True,
                "strategy_version": "h4_t3_k30_tail_safe_v1",
                "candidates": [],
            },
        })

        cards = build_strategy_scorecards(
            [], {}, trading_calendar=[], run_manifest=manifest
        )
        h4 = next(row for row in cards["formal"] if row["strategy"] == "h4_t3")
        self.assertEqual("data_unavailable", h4["evaluation_status"])
        self.assertEqual(
            ["strategy_upstream_contract_mismatch"],
            h4["metrics_blocking_reasons"],
        )

    def test_run_manifest_attaches_latest_state_to_historical_card(self):
        manifest = build_strategy_run_manifest({
            "date": "2026-08-26",
            "selection_input_health": {
                "schema_version": 2,
                "status": "verified",
                "formal": {
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": True,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "luojie_pool": {"status": "verified"},
                },
            },
            "picks_pure": [],
            "picks_fusion": [],
            "observation_watchlist": [],
            "next_day_boom": {"mode": "enabled", "candidates": []},
            "luojie_pool": {"mode": "enabled", "candidates": []},
            "h4_t3_pool": {
                "mode": "production", "status": "error",
                "production_attested": False, "reason": "生产证明失败",
                "strategy_version": "h4_t3_k30_tail_safe_v1",
                "candidates": [],
            },
        })
        pure_manifest = next(
            item for item in manifest if item["strategy"] == "daily_pure"
        )
        pure_manifest["version"] = "pure-v1"
        pure_manifest["source_pool"] = "daily_pure"
        pure_manifest["entry_mode"] = "delay1_open"
        pure_manifest["intended_horizon"] = 3
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution.pop("evaluation_role", None)
        contribution.pop("publication_surface", None)
        contribution.pop("evaluation_eligible", None)
        contribution.pop("eligibility_reason", None)

        cards = build_strategy_scorecards(
            [entry], {"300308": _kline()},
            trading_calendar=_kline()["dates"],
            run_manifest=manifest,
        )["baselines"]

        self.assertEqual(len(cards), 2)
        legacy = next(
            card for card in cards
            if card["research_tier"] == "legacy_unclassified"
        )
        current = next(
            card for card in cards
            if card["research_tier"] == "prospective_ledger"
        )
        self.assertEqual(legacy["latest_run_status"], "unrecorded")
        self.assertEqual(legacy["evidence_tier"], "legacy_inferred")
        self.assertEqual(current["latest_run_status"], "verified_empty")
        self.assertEqual(current["latest_signal_count"], 0)
        self.assertEqual(current["latest_report_date"], "2026-08-26")

    def test_run_manifest_never_treats_invalid_pool_shapes_as_zero_signal(self):
        manifest = build_strategy_run_manifest({
            "date": "2026-08-26",
            "picks_pure": {"bad": "shape"},
            "picks_fusion": None,
            "observation_watchlist": "bad",
            "next_day_boom": {"mode": "enabled", "candidates": None},
            "luojie_pool": {"mode": "enabled"},
            "h4_t3_pool": {
                "mode": "production",
                "status": "ok",
                "production_attested": True,
            },
        })

        states = {item["strategy"]: item for item in manifest}
        for strategy in (
            "daily_pure", "daily_fusion", "observation_gate",
            "next_day_boom", "luojie_pool", "h4_t3",
        ):
            self.assertEqual(states[strategy]["run_status"], "unavailable")
            self.assertNotIn("运行正常", states[strategy]["reason"])

    def test_formal_manifest_separates_fusion_candidates_from_published_recommendations(self):
        manifest = build_strategy_run_manifest({
            "date": "2026-08-26",
            "selection_input_health": {
                "schema_version": 2,
                "status": "verified",
                "formal": {
                    "formal_actions_allowed": True,
                    "all_formal_actions_allowed": True,
                },
                "by_strategy": {
                    "daily_fusion": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "h4_t3": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                    "luojie_pool": {"status": "verified"},
                },
            },
            "picks_pure": [],
            "picks_fusion": [
                {"decision_engine_v1": {"decision_code": "recommend"}},
                {"decision_engine_v1": {"decision_code": "observe"}},
                {"decision_engine_v1": {"decision_code": "reject"}},
            ],
            "observation_watchlist": [],
            "next_day_boom": {"mode": "disabled", "candidates": []},
            "luojie_pool": {"mode": "enabled", "candidates": []},
            "h4_t3_pool": {
                "mode": "production", "status": "ok",
                "production_attested": True, "candidates": [],
            },
        })
        fusion = next(
            item for item in manifest if item["strategy"] == "daily_fusion"
        )
        self.assertEqual(fusion["source_candidate_count"], 3)
        self.assertEqual(fusion["published_count"], 1)


if __name__ == "__main__":
    unittest.main()
