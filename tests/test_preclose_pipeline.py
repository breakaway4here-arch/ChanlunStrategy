import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min
from chanlun.preclose_pipeline import (
    PreclosePipelineComponents,
    PreclosePipelineConfig,
    build_preclose_acceleration_pool,
    build_preclose_h4_pool,
    build_preclose_main_pool,
    build_preclose_market_context,
    evaluate_preclose_main_candidates,
    run_preclose_pipeline,
)
from chanlun.report_view_model import build_workspace
from preclose_run import PrecloseRunLock, run_preclose_once


TRADE_DATE = "2026-08-27"
AS_OF = "2026-08-27T14:47:00+08:00"
GENERATED_AT = "2026-08-27T14:48:20+08:00"


def _candidate(code, name, bp_type="一买", tier="formal"):
    closes = np.linspace(8.0, 10.0, 120)
    return {
        "code": code,
        "name": name,
        "sector": "汽车零部件",
        "sector_rank": 2,
        "sector_strength_label": "强",
        "dates": ["2026-04-01"] * 119 + [TRADE_DATE],
        "opens": closes - 0.1,
        "highs": closes + 0.2,
        "lows": closes - 0.2,
        "closes": closes,
        "volumes": np.ones(120) * 2_000_000,
        "buy_points": [{
            "type": bp_type,
            "tier": tier,
            "category": "A",
            "index": 119,
            "price": float(closes[-1]),
        }],
        "best_buy_point": {
            "type": bp_type,
            "tier": tier,
            "category": "A",
            "index": 119,
            "price": float(closes[-1]),
        },
        "pivots": {},
        "trend_type": "上升趋势",
        "divergence": None,
        "fractals": [],
        "strokes": [],
        "segments": [],
        "macd_hist": np.zeros(120),
        "version": "pure",
        "resonance": {"level": "中", "reason": "30min确认"},
        "change_pct": 2.0,
        "volume_ratio": 1.4,
    }


def _analysis(code, name):
    candidate = _candidate(code, name)
    return SimpleNamespace(
        code=code,
        name=name,
        dates=candidate["dates"],
        opens=candidate["opens"],
        highs=candidate["highs"],
        lows=candidate["lows"],
        closes=candidate["closes"],
        volumes=candidate["volumes"],
        buy_points=candidate["buy_points"],
        sell_points=[],
        pivots=[],
        trend_type="上升趋势",
        divergence=None,
        fractals=[],
        strokes=[],
        segments=[],
        macd_hist=np.zeros(120),
    )


def _market_inputs(include_psy12=False):
    closes_a = list(np.linspace(8.0, 10.0, 120))
    closes_b = list(np.linspace(9.0, 11.0, 120))
    rows = []
    for code, name, closes in (
        ("300998", "宁波方正", closes_a),
        ("002328", "新朋股份", closes_b),
    ):
        rows.append({
            "code": code,
            "name": name,
            "sector": "汽车零部件",
            "sector_rank": 2,
            "sector_strength_label": "强",
            "status": "available",
            "bar_state": "intraday",
            "is_final": False,
            "as_of": AS_OF,
            "klines": {
                "dates": ["2026-04-01"] * 119 + [TRADE_DATE],
                "opens": [value - 0.1 for value in closes],
                "highs": [value + 0.2 for value in closes],
                "lows": [value - 0.2 for value in closes],
                "closes": closes,
                "volumes": [2_000_000] * 120,
                "amounts": [200_000_000] * 120,
                "finals": [True] * 119 + [False],
            },
        })
    result = {
        "schema_version": "preclose-input-v1",
        "mode": "preclose_advisory",
        "trade_date": TRADE_DATE,
        "as_of": AS_OF,
        "bar_state": "intraday",
        "is_final": False,
        "daily": rows,
        "target_codes": ["300998", "002328"],
        "min30": {
            code: {
                "status": "available",
                "bar_state": "intraday",
                "is_final": False,
                "as_of": AS_OF,
                "latest_date": TRADE_DATE,
                "klines": {
                    "dates": [TRADE_DATE + " 14:30:00", TRADE_DATE + " 15:00:00"],
                    "opens": [10.0, 10.1],
                    "highs": [10.2, 10.3],
                    "lows": [9.9, 10.0],
                    "closes": [10.1, 10.2],
                    "volumes": [1000, 1200],
                    "finals": [True, False],
                },
            }
            for code in ("300998", "002328")
        },
        "market": {
            "stock_bars": [
                {"code": "300998", "name": "宁波方正", "prev_close": 9.8, "close": 10.0},
                {"code": "002328", "name": "新朋股份", "prev_close": 10.8, "close": 11.0},
            ],
            "market_indices": {
                "上证指数": {"code": "000001", "change_pct": 1.2, "closes": [3000, 3036]},
                "深证成指": {"code": "399001", "change_pct": 0.8},
            },
            "turnover": 9800,
            "turnover_ma5": 9000,
            "turnover_ma20": 8600,
            "trend": {"above_ma20_ratio": 0.62},
            "sectors": [{"name": "汽车零部件", "change_pct": 2.1}],
        },
    }
    if include_psy12:
        result["psy12"] = {"score": 100, "status": "available"}
        result["psy12_shadow"] = {"shadow_score_with_psy12": 100}
    return result


class FixedClock:
    def __init__(self, value=0.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def _components(
    events=None,
    clock=None,
    deadline_during_daily=False,
    right_side_mode="shadow",
    include_right_side=False,
):
    events = events if events is not None else []

    def analyze(**kwargs):
        events.append(("analyze", kwargs["code"]))
        return _analysis(kwargs["code"], kwargs.get("name", ""))

    def daily_pool(results, sector_stocks=None, mode="pure"):
        events.append(("daily_pool", mode, tuple(result.code for result in results)))
        if deadline_during_daily:
            clock.advance(121)
        return (
            [_candidate(result.code, result.name) for result in results],
            {"mode": mode, "input": len(results)},
        )

    def upgrade(pool, min30_results, mode="pure"):
        events.append(("upgrade", mode, len(min30_results)))
        return [dict(item) for item in pool], {"formal_kept": len(pool)}

    def startup_pool(results, sector_stocks=None):
        events.append(("startup_pool", len(results)))
        return [], [{
            "code": "600001",
            "name": "启动观察",
            "close": 12.0,
            "change_pct": 4.2,
            "volume_ratio": 1.8,
        }], {"startup_watch": 1}

    def startup_upgrade(seeds, min30_results):
        events.append(("startup_upgrade", len(seeds), len(min30_results)))
        return [], [], {"startup_candidate": 0}

    def right_side_pool(results, sector_stocks=None):
        del sector_stocks
        events.append((
            "right_side_pool", tuple(result.code for result in results)
        ))
        if not include_right_side:
            return [], [], {"trend_seed": 0}
        return [{
            "code": "002328",
            "name": "新朋股份",
            "reference_price": 11.0,
        }], [], {"trend_seed": 1}

    def right_side_upgrade(seeds, min30_results):
        events.append((
            "right_side_upgrade", len(seeds), len(min30_results)
        ))
        if not seeds:
            return [], [], {"trend_candidate": 0}
        candidate = _candidate("002328", "新朋股份")
        candidate.update({
            "close": 11.0,
            "reference_price": 11.0,
            "source_channel": "right_side_startup",
            "source_type": "日线右侧启动",
            "trend_signals": ["平台突破"],
            "confirmations": ["30分钟结构确认", "30分钟量能确认"],
        })
        return [candidate], [], {"trend_candidate": 1}

    def fusion(picks, sh_closes, sector_stocks=None):
        events.append(("fusion", tuple(item["code"] for item in picks)))
        return [dict(item) for item in picks], {"output_count": len(picks)}

    def score(picks, version="pure", sector_rank_map=None):
        events.append(("score", version))
        output = [dict(item) for item in picks]
        for index, item in enumerate(output):
            item["score"] = 90 - index
        return output

    def evaluate(stock, market_context=None):
        events.append(("decision", stock["code"]))
        code = "recommend" if stock["code"] == "300998" else "observe"
        return {"version": "1", "decision_code": code, "decision": "推荐" if code == "recommend" else "观察"}

    def h4(picks, trade_date, upstream_pool="picks_fusion"):
        events.append(("h4", upstream_pool, tuple(item["code"] for item in picks)))
        return {
            "status": "ok",
            "mode": "production",
            "production_attested": True,
            "strategy_version": "h4-test-v1",
            "diagnostics": {"upstream_pool": upstream_pool},
            "candidates": [{
                "code": picks[0]["code"],
                "name": picks[0]["name"],
                "reference_price": 10.0,
            }] if picks else [],
        }

    def acceleration(picks_fusion, startup_watchlist, market, top_n=5):
        events.append((
            "acceleration",
            tuple(item["code"] for item in picks_fusion),
            tuple(item["code"] for item in startup_watchlist),
        ))
        return {
            "mode": "enabled",
            "action_semantics": "research_observation",
            "candidates": [{
                "code": "600001",
                "name": "启动观察",
                "reference_price": 12.0,
            }],
        }

    return PreclosePipelineComponents(
        analyze=analyze,
        build_daily_structure_pool=daily_pool,
        upgrade_daily_candidates=upgrade,
        build_strong_startup_pool=startup_pool,
        upgrade_strong_startup=startup_upgrade,
        build_right_side_startup_pool=right_side_pool,
        upgrade_right_side_startup=right_side_upgrade,
        right_side_startup_mode=right_side_mode,
        apply_fusion_admission=fusion,
        apply_scores=score,
        evaluate_stock=evaluate,
        build_h4_t3_pool=h4,
        build_next_day_boom_candidates=acceleration,
    )


def _config(clock=None, run_id="run-a"):
    return PreclosePipelineConfig(
        trade_date=TRADE_DATE,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_sha="6412624c",
        run_id=run_id,
        deadline_seconds=120,
        monotonic=clock or FixedClock(),
    )


class PreclosePipelineTests(unittest.TestCase):
    def test_pipeline_executes_only_three_pools_in_fixed_stage_order(self):
        events = []
        forbidden = AssertionError("forbidden dependency entered the 14:47 path")
        with patch("chanlun.data_fetcher.collect_15min_data", side_effect=forbidden), patch(
            "chanlun.market_news.fetch_cls_news", side_effect=forbidden
        ), patch("chanlun.market_news.enrich_events", side_effect=forbidden), patch(
            "chanlun.report_generator.generate_report", side_effect=forbidden
        ), patch(
            "chanlun.recommendation_ledger.finalize_staged_recommendation_entries",
            side_effect=forbidden,
        ):
            result = run_preclose_pipeline(
                _market_inputs(),
                config=_config(),
                components=_components(events),
            )

        self.assertEqual(set(result["pools"]), {"main", "h4_t3", "acceleration"})
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["diagnostics"]["executed_stages"], [
            "daily_structure",
            "target_30m_confirm",
            "market_context",
            "decision_engine",
            "main_public_view",
            "h4_t3",
            "acceleration",
        ])
        self.assertEqual([item["code"] for item in result["pools"]["main"]], ["300998"])
        self.assertIn(("h4", "picks_pure", ("300998", "002328")), events)
        self.assertIn(("acceleration", ("300998",), ("600001",)), events)

    def test_formal_daily_buy_survives_missing_30m_but_reference_does_not_upgrade(self):
        formal = _candidate("300998", "正式票")
        reference = _candidate(
            "002328", "待确认票", bp_type="二买待确认", tier="reference"
        )
        recommended, diagnostics = upgrade_daily_candidates_with_30min(
            [formal, reference], [], mode="pure"
        )

        self.assertEqual([item["code"] for item in recommended], ["300998"])
        self.assertEqual(diagnostics["formal_kept"], 1)
        self.assertEqual(diagnostics["dropped_no_30min"], 1)

    def test_main_pool_calls_daily_upgrade_fusion_and_unified_scoring(self):
        events = []
        components = _components(events)
        result = build_preclose_main_pool(
            [_analysis("300998", "宁波方正")],
            [_analysis("300998", "宁波方正")],
            sector_stocks={"300998": {"sector": "汽车零部件"}},
            sh_closes=[3000, 3036],
            components=components,
        )

        self.assertEqual([item["code"] for item in result["picks_pure"]], ["300998"])
        self.assertEqual([item["code"] for item in result["picks_fusion"]], ["300998"])
        self.assertEqual([event[0] for event in events if event[0] in {
            "daily_pool", "startup_pool", "right_side_pool", "upgrade",
            "startup_upgrade", "right_side_upgrade", "fusion", "score"
        }], [
            "daily_pool", "startup_pool", "right_side_pool", "upgrade",
            "startup_upgrade", "right_side_upgrade", "fusion", "score", "score",
        ])

    def test_right_side_shadow_scans_full_daily_set_without_changing_formal_picks(self):
        events = []
        result = build_preclose_main_pool(
            [_analysis("300998", "宁波方正"), _analysis("002328", "新朋股份")],
            [_analysis("300998", "宁波方正"), _analysis("002328", "新朋股份")],
            sector_stocks={
                "300998": {"sector": "汽车零部件"},
                "002328": {"sector": "汽车零部件"},
            },
            sh_closes=[3000, 3036],
            components=_components(
                events,
                right_side_mode="shadow",
                include_right_side=True,
            ),
        )

        self.assertEqual(["300998", "002328"], [
            item["code"] for item in result["picks_fusion"]
        ])
        self.assertIn(
            ("right_side_pool", ("300998", "002328")), events
        )
        self.assertEqual(
            [], result["diagnostics"]["right_side_startup"]["published_codes"]
        )

    def test_right_side_active_appends_only_scored_independent_candidates(self):
        events = []

        def daily_pool_first(results, sector_stocks=None, mode="pure"):
            del sector_stocks
            events.append(("daily_pool", mode, tuple(
                result.code for result in results
            )))
            return [_candidate(results[0].code, results[0].name)], {"mode": mode}

        components = _components(
            events,
            right_side_mode="active",
            include_right_side=True,
        )
        components = PreclosePipelineComponents(
            **{
                **components.__dict__,
                "build_daily_structure_pool": daily_pool_first,
            }
        )
        result = build_preclose_main_pool(
            [_analysis("300998", "宁波方正"), _analysis("002328", "新朋股份")],
            [_analysis("300998", "宁波方正"), _analysis("002328", "新朋股份")],
            sector_stocks={
                "300998": {"sector": "汽车零部件"},
                "002328": {"sector": "汽车零部件"},
            },
            sh_closes=[3000, 3036],
            components=components,
        )

        self.assertEqual(
            ["300998", "002328"],
            [item["code"] for item in result["picks_fusion"]],
        )
        self.assertEqual(
            ["002328"],
            result["diagnostics"]["right_side_startup"]["published_codes"],
        )
        self.assertIn(("startup_pool", 1), events)
        self.assertIn(
            ("right_side_pool", ("300998", "002328")), events
        )

    def test_market_context_uses_current_deterministic_components_and_ignores_psy12(self):
        plain = build_preclose_market_context(_market_inputs())
        shadow = build_preclose_market_context(_market_inputs(include_psy12=True))

        self.assertEqual(plain["market_sentiment"], shadow["market_sentiment"])
        self.assertEqual(plain["market_sentiment"]["weights"], {
            "breadth": 0.30,
            "limit_ecology": 0.30,
            "index": 0.15,
            "turnover": 0.15,
            "trend": 0.10,
        })
        self.assertFalse(plain["psy12_used"])
        self.assertEqual(set(plain["deterministic_evidence"]), {
            "breadth", "limit_ecology", "index", "turnover", "trend", "sectors"
        })

    def test_main_public_filter_matches_formal_workspace_recommend_semantics(self):
        candidates = [
            _candidate("300998", "宁波方正"),
            _candidate("002328", "新朋股份"),
        ]

        def evaluator(stock, market_context=None):
            code = "recommend" if stock["code"] == "300998" else "observe"
            return {"decision_code": code, "decision": code}

        result = evaluate_preclose_main_candidates(
            candidates,
            market_context={"market_sentiment": {"score": 61}},
            trade_date=TRADE_DATE,
            evaluator=evaluator,
        )
        report = {
            "picks_fusion": result["evaluated"],
            "picks_pure": [],
            "selection_input_health": {
                "schema_version": 2,
                "status": "verified",
                "formal": {"status": "verified", "formal_actions_allowed": True},
                "by_strategy": {
                    "daily_fusion": {"status": "verified", "formal_actions_allowed": True}
                },
            },
        }
        workspace = build_workspace(report)

        self.assertEqual(
            [item["code"] for item in result["main"]],
            [item["code"] for item in workspace["views"]["main"]],
        )
        self.assertEqual([item["code"] for item in result["main"]], ["300998"])

    def test_h4_and_acceleration_keep_their_declared_upstreams_and_semantics(self):
        events = []
        components = _components(events)
        pure = [_candidate("300998", "宁波方正")]
        main = [_candidate("002328", "新朋股份")]
        watch = [{"code": "600001", "name": "启动观察", "close": 12.0}]

        h4 = build_preclose_h4_pool(pure, TRADE_DATE, components=components)
        acceleration = build_preclose_acceleration_pool(
            main, watch, {"上证指数": {"change_pct": 1.2}}, components=components
        )

        self.assertEqual(h4["diagnostics"]["upstream_pool"], "picks_pure")
        self.assertEqual(acceleration["action_semantics"], "research_observation")
        self.assertIn(("h4", "picks_pure", ("300998",)), events)
        self.assertIn(("acceleration", ("002328",), ("600001",)), events)

    def test_h4_excludes_active_right_side_candidates_before_component_call(self):
        events = []
        components = _components(events)
        pure = [
            _candidate("300998", "宁波方正"),
            {
                **_candidate("002328", "新朋股份"),
                "source_channel": "right_side_startup",
            },
        ]

        result = build_preclose_h4_pool(
            pure, TRADE_DATE, components=components
        )

        self.assertIn(("h4", "picks_pure", ("300998",)), events)
        source_filter = result["diagnostics"]["right_side_source_filter"]
        self.assertEqual(1, source_filter["right_side_excluded_count"])
        self.assertEqual(["002328"], source_filter["right_side_excluded_codes"])

    def test_deadline_is_hard_and_same_content_has_stable_hash_across_run_ids(self):
        first = run_preclose_pipeline(
            _market_inputs(), config=_config(run_id="run-a"), components=_components([])
        )
        second = run_preclose_pipeline(
            _market_inputs(), config=_config(run_id="run-b"), components=_components([])
        )
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertNotEqual(first["run_id"], second["run_id"])

        clock = FixedClock()
        events = []
        timeout = run_preclose_pipeline(
            _market_inputs(),
            config=_config(clock=clock, run_id="run-timeout"),
            components=_components(
                events, clock=clock, deadline_during_daily=True
            ),
        )
        self.assertEqual(timeout["status"], "deadline_exceeded")
        self.assertEqual(timeout["pools"], {"main": [], "h4_t3": [], "acceleration": []})
        self.assertEqual(timeout["diagnostics"]["executed_stages"], ["daily_structure"])
        self.assertFalse(any(event[0] in {"decision", "h4", "acceleration"} for event in events))

    def test_active_same_day_lock_never_overwrites_first_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            day_root = root / TRADE_DATE
            day_root.mkdir(parents=True)
            snapshot_path = day_root / "snapshot.json"
            snapshot_path.write_text('{"snapshot_id":"first"}\n', encoding="utf-8")
            before = snapshot_path.read_bytes()
            lock = PrecloseRunLock(day_root / "run.lock", run_id="first-run")
            lock.acquire()
            try:
                result = run_preclose_once(
                    _market_inputs(),
                    config=_config(run_id="second-run"),
                    root=root,
                    components=_components([]),
                )
            finally:
                lock.release()

            self.assertEqual(result["status"], "locked")
            self.assertEqual(snapshot_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
