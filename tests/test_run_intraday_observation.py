"""Offline contracts for the full 14:45 observation pipeline."""

import copy
import importlib.util
import inspect
import io
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import run


def payload():
    # Synthetic prices, used only to exercise the actual shared algorithms.
    dates = []
    day = date(2026, 10, 13)
    while len(dates) < 120:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day -= timedelta(days=1)
    dates.reverse()
    closes = [10 + i * .02 for i in range(120)]
    kline = {
        "dates": dates, "opens": closes, "closes": closes,
        "highs": [x + .1 for x in closes],
        "lows": [x - .1 for x in closes],
        "volumes": [10000000.] * 120,
        "volume_units": ["shares"] * 120,
        "volume_sources": ["synthetic"] * 120,
        "amounts": [100000000.] * 120,
        "amount_available": [True] * 120,
        "amount_units": ["CNY"] * 120,
        "amount_sources": ["synthetic"] * 120,
        "finals": [True] * 119 + [False],
        "adjustment": "qfq", "source": "synthetic_cutoff",
        "as_of": "2026-10-13T14:45:00+08:00",
    }
    return {
        "schema_version": 1, "cutoff": kline["as_of"],
        "daily_data": {
            "sectors": [], "sh_index": copy.deepcopy(kline),
            "stocks": [{
                "code": "600001", "name": "测试股票", "exchange": "SH",
                "asset_type": "stock", "klines": kline,
                "as_of": kline["as_of"], "is_final": False,
                "data_status": {"daily": "verified", "latest_date": dates[-1],
                                "is_final": False},
            }],
            "data_quality": {"stock_pool_source": "frozen_cutoff", "warnings": []},
        },
        "market_indices": {}, "minute_data": {"30m": {}, "15m": {}},
    }


class IntradayObservationRunTests(unittest.TestCase):
    def context(self, value=None, **kwargs):
        self.assertIsNotNone(
            importlib.util.find_spec("chanlun.intraday_observation_context"),
            "a frozen observation context must exist",
        )
        from chanlun.intraday_observation_context import ObservationContext
        return ObservationContext(value if value is not None else payload(), **kwargs)

    def test_main_has_opt_in_context_without_changing_default_render(self):
        params = inspect.signature(run.main).parameters
        self.assertIn("observation_context", params)
        self.assertIsNone(params["observation_context"].default)
        self.assertIs(params["render"].default, True)

    def test_rejects_wrong_cutoff_and_final_today(self):
        for mutation in ("time", "final", "future"):
            value = payload()
            if mutation == "time":
                value["cutoff"] = "2026-10-13T14:47:00+08:00"
            elif mutation == "final":
                value["daily_data"]["stocks"][0]["klines"]["finals"][-1] = True
            else:
                value["daily_data"]["stocks"][0]["as_of"] = "2026-10-13T14:46:00+08:00"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.context(value)

    def test_context_is_copy_isolated_and_missing_minutes_are_explicit(self):
        value = payload()
        context = self.context(value)
        original_hash = context.input_hash
        value["daily_data"]["stocks"][0]["code"] = "WRONG"
        failures = {}
        self.assertEqual(context.collect_minutes("30m", [{"code": "600001"}],
            required_date="2026-10-13", as_of=context.cutoff,
            failure_evidence=failures), [])
        self.assertTrue(failures)
        self.assertEqual(context.input_hash, original_hash)
        self.assertEqual(context.snapshot()["daily_data"]["stocks"][0]["code"], "600001")

    def test_minute_boundary_rejects_late_or_unfinished_rows(self):
        for interval, end in (("15m", "14:45:00"), ("30m", "14:30:00")):
            value = payload()
            count = 180 if interval == "15m" else 40
            finish = datetime.fromisoformat("2026-10-13 " + end)
            stamps = [(finish - timedelta(minutes=15 * i)).isoformat(sep=" ") for i in reversed(range(count))]
            row = {"code": "600001", "klines": {"dates": stamps, "closes": [10.] * count},
                   "input_evidence": {"interval": interval, "status": "verified", "stale": False,
                       "is_final": True, "latest_date": "2026-10-13", "as_of": value["cutoff"]}}
            value["minute_data"][interval]["600001"] = row
            context = self.context(value)
            self.assertEqual(len(context.collect_minutes(interval, [{"code": "600001"}],
                required_date="2026-10-13", as_of=context.cutoff)), 1)
            for mutation in ("late", "nonfinal", "short", "wrong_code"):
                bad = copy.deepcopy(value)
                bad_row = bad["minute_data"][interval]["600001"]
                if mutation == "late":
                    bad_row["klines"]["dates"] = ["2026-10-13 15:00:00"]
                elif mutation == "nonfinal":
                    bad_row["input_evidence"]["is_final"] = False
                elif mutation == "short":
                    bad_row["klines"]["dates"] = stamps[-1:]
                    bad_row["klines"]["closes"] = [10.]
                else:
                    bad_row["code"] = "600002"
                context = self.context(bad)
                with self.subTest(interval=interval, mutation=mutation):
                    self.assertEqual(context.collect_minutes(interval, [{"code": "600001"}],
                        required_date="2026-10-13", as_of=context.cutoff), [])

    def test_projection_keeps_nonempty_rank_and_decisions_but_is_not_executable(self):
        context = self.context()
        source = [{"code": "600002", "decision_engine_v1": {"decision_code": "recommend"}},
                  {"code": "600001", "decision_engine_v1": {"decision_code": "observe"}}]
        report = {
            "date": "2026-10-13", "picks_pure": copy.deepcopy(source),
            "picks_fusion": copy.deepcopy(source), "startup_watchlist": [], "observation_watchlist": [],
            "next_day_boom": {"candidates": copy.deepcopy(source)},
            "luojie_pool": {"candidates": []}, "h4_t3_pool": {"candidates": copy.deepcopy(source)},
            "right_side_startup": {"candidates": [], "watchlist": []},
            "data_quality": {"generated_at": "2026-10-13T14:47:00+08:00"},
            "selection_input_health": {"by_strategy": {"daily_fusion": {"formal_actions_allowed": True}},
                "formal": {"formal_actions_allowed": True, "all_formal_actions_allowed": True,
                           "allowed_strategies": ["daily_fusion"]}, "sublevels": {}},
        }
        result = context.finalize_report(report)
        self.assertEqual([x["code"] for x in result["picks_fusion"]], ["600002", "600001"])
        self.assertEqual(result["picks_fusion"][0]["decision_engine_v1"], source[0]["decision_engine_v1"])
        self.assertFalse(result["picks_fusion"][0]["is_executable"])
        self.assertFalse(result["selection_input_health"]["formal"]["all_formal_actions_allowed"])
        self.assertEqual(result["selection_input_health"]["formal"]["allowed_strategies"], [])

    def test_all_pools_run_with_no_external_io_and_no_formal_output(self):
        context = self.context()
        forbidden = [
            "resolve_personal_watchlist", "ingest_market_close_snapshot",
            "collect_daily_data", "_apply_full_a_universe", "ensure_watchlist_stocks",
            "_hydrate_market_cap_evidence", "collect_30min_data", "collect_15min_data",
            "load_30min_data_readonly", "fetch_market_indices", "fetch_limit_up_pool",
            "fetch_cls_news", "enrich_events", "_build_market_sentiment_history",
            "MarketHistoryStore", "fetch_sector_outflow", "_complete_sector_component_evidence",
            "load_previous_personal_watchlist", "load_position_book",
            "prepare_recommendation_history", "persist_review_benchmark_kline",
            "load_review_market_context_from_store", "build_daily_shadow_evaluations",
            "generate_report", "update_data_json", "write_right_side_startup_audit",
            "generate_forecast", "_attach_market_icepoint",
        ]
        with ExitStack() as stack:
            blocked_calls = {}
            for name in forbidden:
                blocked_calls[name] = stack.enter_context(mock.patch.object(run, name, side_effect=AssertionError(name)))
            blocked_calls["fetch_themes"] = stack.enter_context(mock.patch("chanlun.kaipanla.fetch_themes", side_effect=AssertionError("themes")))
            pool_calls = {}
            for name in ("build_daily_structure_pool", "_build_independent_daily_channels",
                         "build_luojie_pool", "build_next_day_boom_candidates", "_build_daily_h4_t3_pool"):
                pool_calls[name] = stack.enter_context(mock.patch.object(run, name, wraps=getattr(run, name)))
            with redirect_stdout(io.StringIO()):
                result = run.main(generated_at=datetime(2026, 10, 13, 15, 12,
                    tzinfo=timezone(timedelta(hours=8))), observation_context=context, render=False)
        for name, blocked in blocked_calls.items():
            self.assertEqual(blocked.call_count, 0, name)
        self.assertEqual(result["as_of"], context.cutoff)
        self.assertEqual(result["generated_at"], "2026-10-13T15:12:00+08:00")
        self.assertFalse(result["is_official"])
        self.assertEqual(result["bar_state"], "intraday")
        self.assertEqual(result["intraday_observation"]["input_hash"], context.input_hash)
        self.assertEqual(result["diagnostics"]["candidate_funnel"]["persist_status"], "observation_only")
        self.assertEqual(result["recommendation_ledger"], [])
        for name, called in pool_calls.items():
            self.assertTrue(called.called, name)
        for key in ("picks_pure", "picks_fusion", "startup_watchlist", "observation_watchlist",
                    "luojie_pool", "next_day_boom", "h4_t3_pool", "right_side_startup"):
            self.assertIn(key, result)
            self.assertIn(key, result["intraday_observation"]["pool_status"])

    def test_observation_cannot_render_into_formal_report(self):
        with self.assertRaises(ValueError):
            run.main(observation_context=self.context(), render=True)


if __name__ == "__main__":
    unittest.main()
