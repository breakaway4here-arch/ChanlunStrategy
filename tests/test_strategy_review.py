import copy
import tempfile
import unittest
from pathlib import Path

from chanlun.market_history_store import MarketHistoryStore
from chanlun.recommendation_ledger import build_recommendation_entries
from chanlun.strategy_review import (
    build_strategy_scorecards,
    evaluate_recommendation_entry,
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
    entry_mode="delay1_open",
):
    strategies = strategies or [
        ("daily_fusion", "fusion-v2", "recommend"),
    ]
    specs = []
    for name, version, decision in strategies:
        specs.append({
            "strategy_name": name,
            "strategy_version": version,
            "source_pool": name,
            "entry_mode": entry_mode,
            "intended_horizon": intended_horizon,
            "publication_status": "published",
            "user_action_from_decision": True,
            "items": [{
                "code": code,
                "name": "中际旭创",
                "closes": [99, 100],
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
    def test_immediate_close_uses_future_closes_and_excludes_signal_day_range(self):
        kline = _kline(
            dates=[
                "2026-08-20", "2026-08-21", "2026-08-24",
                "2026-08-25", "2026-08-26", "2026-08-27",
            ],
            opens=[9.5, 10.2, 10.6, 10.7, 10.8, 10.9],
            closes=[10.0, 10.5, 10.8, 11.0, 10.9, 11.2],
            highs=[50.0, 11.0, 11.2, 11.4, 11.3, 11.6],
            lows=[1.0, 9.8, 10.1, 10.4, 10.3, 10.5],
        )
        entry = _entry(entry_mode="immediate_close")

        outcome = _evaluate(
            entry=entry,
            kline=kline,
            trading_calendar=kline["dates"],
        )

        self.assertEqual(outcome["entry_mode"], "immediate_close")
        self.assertEqual(outcome["entry_date"], "2026-08-20")
        self.assertEqual(outcome["entry_price"], 10.0)
        self.assertAlmostEqual(outcome["returns"]["t1"], 5.0)
        self.assertAlmostEqual(outcome["mfe"]["t1"], 10.0)
        self.assertAlmostEqual(outcome["mae"]["t1"], -2.0)
        self.assertAlmostEqual(outcome["returns"]["t3"], 10.0)
        self.assertAlmostEqual(outcome["mfe"]["t3"], 14.0)
        self.assertAlmostEqual(outcome["mae"]["t3"], -2.0)
        self.assertEqual(
            outcome["research_results"]["t1"]["close_return"],
            outcome["returns"]["t1"],
        )
        self.assertEqual(outcome["intended_horizon"], 3)
        self.assertEqual(outcome["intended_horizon_label"], "T+3")
        self.assertEqual(outcome["close_return"], outcome["returns"]["t3"])

    def test_uses_next_open_and_reports_t1_t3_t5_after_maturity(self):
        outcome = _evaluate()

        self.assertEqual(outcome["status"], "evaluated")
        self.assertEqual(outcome["entry_date"], "2026-08-21")
        self.assertEqual(outcome["entry_price"], 101.0)
        self.assertAlmostEqual(outcome["returns"]["t1"], 0.990099, places=5)
        self.assertAlmostEqual(outcome["returns"]["t3"], 3.960396, places=5)
        self.assertAlmostEqual(outcome["returns"]["t5"], 8.910891, places=5)
        self.assertEqual(outcome["maturity"]["t5"], "mature")

    def test_immediate_close_marks_missing_stock_trade_day_insufficient(self):
        calendar = _kline()["dates"]
        stock = _kline(
            dates=[calendar[0]] + calendar[2:],
            opens=[100, 103, 104, 106, 108],
            closes=[100, 104, 105, 108, 110],
            highs=[500, 105, 106, 109, 111],
            lows=[1, 102, 103, 105, 107],
        )
        outcome = _evaluate(
            entry=_entry(entry_mode="immediate_close"),
            kline=stock,
            trading_calendar=calendar,
        )

        self.assertEqual(outcome["maturity"]["t1"], "insufficient")
        self.assertIsNone(outcome["returns"]["t1"])
        self.assertIsNone(outcome["mfe"]["t1"])

    def test_immediate_close_explains_zero_volume_as_suspended_window(self):
        stock = _kline(volumes=[1000, 0, 1000, 1000, 1000, 1000])

        outcome = _evaluate(
            entry=_entry(entry_mode="immediate_close"),
            kline=stock,
            trading_calendar=stock["dates"],
        )

        self.assertEqual(outcome["maturity"]["t1"], "insufficient")
        self.assertEqual(
            outcome["maturity_reasons"]["t1"],
            "suspended_or_non_trading_bar",
        )

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
        entry["strategy_contributions"][1]["cohort_eligible"] = True

        outcome = evaluate_recommendation_entry(
            entry,
            _kline(),
            trading_calendar=_kline()["dates"],
        )

        self.assertEqual(outcome["status"], "entry_mode_unknown")


class StrategyScorecardTests(unittest.TestCase):
    def test_scorecards_do_not_mix_entry_modes_for_same_strategy_version(self):
        legacy = _entry(entry_mode="delay1_open")
        immediate = _entry("2026-08-21", entry_mode="immediate_close")
        kline = _kline(
            dates=[
                "2026-08-20", "2026-08-21", "2026-08-24",
                "2026-08-25", "2026-08-26", "2026-08-27",
                "2026-08-28",
            ],
            opens=[100, 101, 102, 103, 104, 105, 106],
            closes=[100, 101, 102, 103, 104, 105, 106],
            highs=[101, 102, 103, 104, 105, 106, 107],
            lows=[99, 100, 101, 102, 103, 104, 105],
        )

        cards = build_strategy_scorecards(
            [legacy, immediate],
            {"300308": kline},
            trading_calendar=kline["dates"],
        )

        self.assertEqual(len(cards), 2)
        self.assertEqual(
            {card["entry_mode"] for card in cards},
            {"delay1_open", "immediate_close"},
        )
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
        by_name = {card["strategy"]: card for card in cards}

        self.assertEqual(by_name["daily_pure"]["sample_size"], 0)
        self.assertEqual(by_name["daily_fusion"]["sample_size"], 1)
        self.assertEqual(by_name["daily_pure"]["gate_outcomes"]["observe"], 1)
        self.assertEqual(by_name["daily_pure"]["gate_outcomes"]["recommend"], 1)
        self.assertIn("median_returns", by_name["daily_pure"])
        self.assertIn("excess_returns", by_name["daily_pure"])
        self.assertIn("mae", by_name["daily_pure"]["excursions"])
        self.assertIsNone(by_name["daily_pure"]["win_rates"]["t1"])

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

        self.assertEqual(cards[0]["episode_count"], 1)
        self.assertEqual(cards[0]["sample_size"], 1)

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

        self.assertEqual(cards[0]["episode_count"], 2)

    def test_representative_samples_are_bounded_and_attributed(self):
        entries = [
            _entry(code="{:06d}".format(300300 + index))
            for index in range(5)
        ]
        klines = {entry["code"]: copy.deepcopy(_kline()) for entry in entries}

        card = build_strategy_scorecards(
            entries, klines, trading_calendar=_kline()["dates"]
        )[0]

        self.assertLessEqual(len(card["representative_samples"]), 3)
        sample = card["representative_samples"][0]
        self.assertIn("recommendation_id", sample)
        self.assertEqual(sample["strategy"], "daily_fusion")
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
                "strategy_name": "daily_fusion",
                "strategy_version": "fusion-t1-v1",
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

        card = build_strategy_scorecards(
            [entry], {"300308": kline},
            trading_calendar=kline["dates"],
        )[0]

        self.assertEqual(card["intended_horizon"], 1)
        self.assertEqual(card["sample_size"], 1)
        self.assertEqual(len(card["representative_samples"]), 1)
        self.assertTrue(
            card["representative_samples"][0]["outcome_label"].startswith(
                "T+1"
            )
        )

    def test_internal_observation_gate_never_enters_recommendation_cohort(self):
        entry = _entry()
        contribution = entry["strategy_contributions"][0]
        contribution["publication_status"] = "internal"
        contribution["user_action"] = "watch"
        contribution["cohort_eligible"] = False

        card = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )[0]

        self.assertEqual(card["episode_count"], 0)
        self.assertEqual(card["sample_size"], 0)
        self.assertEqual(card["gate_outcomes"]["recommend"], 1)
        self.assertEqual(card["publication_outcomes"]["watch"], 1)

    def test_unknown_horizon_is_not_silently_labeled_t3(self):
        entry = _entry(intended_horizon=None)

        card = build_strategy_scorecards(
            [entry],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )[0]

        self.assertIsNone(card["intended_horizon"])
        self.assertIsNone(card["win_rate"])
        self.assertEqual(card["episode_count"], 0)
        self.assertEqual(card["evaluable_episode_count"], 0)

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
        )[0]
        second = build_strategy_scorecards(
            [unknown, verified],
            {"300308": _kline()},
            trading_calendar=_kline()["dates"],
        )[0]

        self.assertEqual(first["attribution_status"], "mixed")
        self.assertEqual(first["attribution_status"], second["attribution_status"])
        self.assertEqual(
            first["attribution_status_counts"],
            second["attribution_status_counts"],
        )

    def test_high_return_scorecard_reports_primary_horizon_support_metrics(self):
        closes = [110.0, 100.0, 95.0]
        entries = []
        klines = {}
        for index, future_close in enumerate(closes):
            code = "300{:03d}".format(501 + index)
            entries.append(_entry(
                code=code,
                intended_horizon=1,
                entry_mode="immediate_close",
            ))
            klines[code] = _kline(
                dates=["2026-08-20", "2026-08-21"],
                opens=[100.0, 100.0],
                closes=[100.0, future_close],
                highs=[101.0, future_close + 2.0],
                lows=[99.0, future_close - 2.0],
            )

        card = build_strategy_scorecards(
            entries,
            klines,
            trading_calendar=["2026-08-20", "2026-08-21"],
        )[0]

        self.assertEqual(card["sample_size"], 3)
        self.assertEqual(card["active_dates"], 1)
        self.assertEqual(card["active_months"], 1)
        self.assertEqual(card["average_daily_count"], 3.0)
        self.assertAlmostEqual(card["mean_close_return"], 5.0 / 3.0)
        self.assertEqual(card["median_close_return"], 0.0)
        self.assertAlmostEqual(card["up_rate"], 100.0 / 3.0)
        self.assertAlmostEqual(card["hit_rate_ge_5"], 100.0 / 3.0)
        self.assertAlmostEqual(card["loss_rate_le_minus_5"], 100.0 / 3.0)
        self.assertEqual(card["worst_close_return"], -5.0)
        self.assertIn("monthly", card["time_stability"])
        self.assertTrue(card["top_k_diagnostics"])
        self.assertFalse(card["selection_cap_applied"])


if __name__ == "__main__":
    unittest.main()
