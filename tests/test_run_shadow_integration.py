import copy
import io
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import chanlun.shadow_evaluation as shadow_evaluation
import chanlun.strategy_review as strategy_review
import run
from chanlun.h4_t3_pool import STRATEGY_VERSION


def _candidate(index):
    code = "{:06d}".format(300000 + index)
    return {
        "code": code,
        "name": "candidate-{}".format(index),
        "dates": ["2026-08-21", "2026-08-22"],
        "closes": [10.0 + index, 11.0 + index],
        "data_status": {
            "daily": "verified",
            "latest_date": "2026-08-22",
            "source": "market_history_db",
            "is_final": True,
        },
        "decision_engine_v1": {"decision_code": "recommend"},
        "reason": "formal reason {}".format(index),
    }


def _formal_report(candidate_count=7):
    h4_candidates = [_candidate(index) for index in range(candidate_count)]
    return {
        "date": "2026-08-22",
        "picks_pure": [{"code": "000001", "reason": "pure"}],
        "picks_fusion": [{"code": "000002", "reason": "fusion"}],
        "startup_watchlist": [{"code": "000003"}],
        "observation_watchlist": [{"code": "000004"}],
        "next_day_boom": {"candidates": [{"code": "000005"}]},
        "luojie_pool": {"candidates": [{"code": "000006"}]},
        "h4_t3_pool": {
            "production_attested": True,
            "mode": "production",
            "status": "ok",
            "strategy_version": STRATEGY_VERSION,
            "candidates": h4_candidates,
        },
        "decision_brief": {
            "summary": "正式决策摘要",
            "directions": [{"name": "人工智能", "risk": "拥挤"}],
        },
        "holding_risks": [{"code": "000001", "risk": "跌破保护位"}],
        "recommendation_ledger": [{"recommendation_id": "formal:one"}],
        "strategy_scorecards": [{"strategy_name": "formal"}],
        "diagnostics": {
            "candidate_funnel": {"persist_status": "saved", "final": ["000002"]}
        },
        "data_quality": {
            "runtime_policy": {
                "market_history_cutover_mode": "sqlite",
                "recall_strategy_mode": "active",
                "stock_selection_shadow_mode": "shadow",
            }
        },
    }


def _empty_review_context(_db_path, _entries, *, as_of=None):
    return {}, [], None, {"status": "empty", "as_of": as_of}


def _canonical_review_context(_db_path, entries, *, as_of=None):
    by_code = {}
    for entry in entries:
        if entry.get("report_date") != as_of:
            continue
        close = entry.get("reference_close")
        by_code[entry["code"]] = {
            "dates": [as_of],
            "opens": [close],
            "closes": [close],
            "highs": [close],
            "lows": [close],
            "volumes": [1000],
            "is_final": [True],
            "adjustment": "qfq",
        }
    return by_code, [as_of], None, {"status": "ok", "as_of": as_of}


class DailyShadowIntegrationTests(unittest.TestCase):
    def _capture_real_main_report(self, mode):
        candidate = _candidate(0)
        candidate.update({
            "best_buy_point": {
                "type": "三买",
                "price": 11.0,
                "index": 1,
                "reason": "回踩确认",
            },
            "score": 88,
            "action": "buy",
            "source_channel": "low_position",
        })
        kline = {
            "dates": ["2026-08-21", "2026-08-22"],
            "opens": [10.0, 10.8],
            "closes": [10.0, 11.0],
            "highs": [10.2, 11.2],
            "lows": [9.8, 10.7],
            "volumes": [1000, 1200],
        }
        stock = {
            "code": candidate["code"],
            "name": candidate["name"],
            "klines": kline,
            "data_status": candidate["data_status"],
        }
        analysis = SimpleNamespace(
            code=candidate["code"],
            name=candidate["name"],
            buy_points=[],
            sell_points=[],
            trend_type="up",
            divergence=None,
        )

        class Funnel:
            def __init__(self, *_args, **_kwargs):
                self.codes = set()
                self.events = []

            def register_many(self, rows):
                self.codes.update(
                    str(row.get("code")) for row in rows or []
                    if isinstance(row, dict) and row.get("code")
                )

            def mark_membership(self, *_args, **_kwargs):
                return None

            def fail_stage(self, *_args, **_kwargs):
                return None

            def finalize(self, *_args, **_kwargs):
                return None

            def run_record(self, **_kwargs):
                return {"run_id": "fixed-shadow-boundary"}

            def summary(self):
                return {"run_id": "fixed-shadow-boundary", "total": 1}

        class Store:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def save_candidate_funnel(self, *_args, **_kwargs):
                return None

        def recency(rows, _max_age):
            rows = copy.deepcopy(rows)
            return rows, {
                "input": len(rows),
                "kept": len(rows),
                "dropped_expired": 0,
                "dropped_details": [],
            }

        def h4(rows, _today):
            return {
                "production_attested": True,
                "mode": "production",
                "status": "ok",
                "strategy_version": STRATEGY_VERSION,
                "diagnostics": {"microstate_count": len(rows), "eligible_count": len(rows)},
                "candidates": copy.deepcopy(rows),
            }

        reports = []
        daily_data = {
            "sectors": [],
            "sh_index": kline,
            "stocks": [stock],
            "sector_component_evidence": {},
            "data_quality": {
                "is_official": False,
                "sources_trusted": True,
                "warnings": [],
            },
        }
        time_metadata = {
            "generated_at": "2026-08-22T15:10:00+08:00",
            "as_of": "2026-08-22T15:10:00+08:00",
            "bar_state": "closed",
        }
        market_sentiment = {
            "score": 50,
            "label": "中性",
            "coverage": 1.0,
            "insufficient": False,
            "components": {},
            "evidence": {"limit_ecology": {}},
        }
        admission_diag = {
            "input_count": 1,
            "market_regime": "neutral",
            "kept_formal": 1,
            "kept_candidate": 0,
            "dropped_by_ma": 0,
            "dropped_by_market_regime": 0,
            "dropped_by_signal_gate": 0,
            "output_count": 1,
        }

        patch_values = {
            "STOCK_SELECTION_SHADOW_MODE": mode,
            "CandidateFunnel": Funnel,
            "MarketHistoryStore": Store,
            "build_market_time_metadata": lambda generated_at=None: copy.deepcopy(time_metadata),
            "resolve_personal_watchlist": lambda remote_url=None: ({}, {"status": "ok", "revision": "test"}),
            "ingest_market_close_snapshot": lambda *_args, **_kwargs: {"status": "complete"},
            "collect_daily_data": lambda **_kwargs: copy.deepcopy(daily_data),
            "_apply_full_a_universe": lambda rows, *_args, **_kwargs: rows,
            "ensure_watchlist_stocks": lambda rows, *_args, **_kwargs: (rows, {"by_code": {}}),
            "_hydrate_market_cap_evidence": lambda *_args, **_kwargs: {},
            "analyze": lambda **_kwargs: analysis,
            "build_daily_structure_pool": lambda *_args, **_kwargs: (copy.deepcopy([candidate]), {"base_pass": 1, "with_buy_points": 1, "formal_count": 1, "upgradeable_count": 0, "reference_only_count": 0}),
            "build_strong_startup_pool": lambda *_args, **_kwargs: ([], [], {}),
            "build_trend_continuation_pool": lambda *_args, **_kwargs: ([], [], {}),
            "prefilter_luojie_theme_candidates": lambda *_args, **_kwargs: [],
            "collect_15min_data": lambda *_args, **_kwargs: [],
            "build_luojie_pool": lambda *_args, **_kwargs: {"candidates": [], "diagnostics": {}},
            "collect_30min_data": lambda *_args, **_kwargs: [],
            "_downgrade_to_formal_only": lambda rows: copy.deepcopy(rows),
            "apply_fusion_admission": lambda rows, *_args, **_kwargs: (copy.deepcopy(rows), copy.deepcopy(admission_diag)),
            "filter_recent_picks": recency,
            "filter_recent_watchlist": recency,
            "apply_scores": lambda rows, **_kwargs: copy.deepcopy(rows),
            "_attach_gf_dma_health": lambda rows: rows,
            "_attach_signal_dimensions": lambda row: row,
            "fetch_market_indices": lambda **_kwargs: ({}, None),
            "build_next_day_boom_candidates": lambda **_kwargs: {"mode": "production", "reason": "fixture", "candidates": copy.deepcopy([candidate])},
            "analyze_shanghai_chanlun": lambda *_args, **_kwargs: {},
            "fetch_limit_up_pool": lambda *_args, **_kwargs: ([], {"status": "ok"}),
            "fetch_cls_news": lambda *_args, **_kwargs: [],
            "rank_market_impact_events": lambda *_args, **_kwargs: [],
            "enrich_events": lambda rows: rows,
            "_build_market_sentiment_history": lambda *_args, **_kwargs: (copy.deepcopy(market_sentiment), []),
            "build_limit_up_snapshot": lambda *_args, **_kwargs: {},
            "_get_decision_engine": lambda: None,
            "_build_daily_h4_t3_pool": h4,
            "fetch_sector_outflow": lambda *_args, **_kwargs: [],
            "_complete_sector_component_evidence": lambda *_args, **_kwargs: {},
            "deduplicate_sector_hierarchy": lambda rows, *_args, **_kwargs: rows,
            "build_watchlist_fact_index": lambda *_args, **_kwargs: {},
            "load_previous_personal_watchlist": lambda *_args, **_kwargs: None,
            "build_personal_watchlist_snapshot": lambda *_args, **_kwargs: {},
            "build_decision_brief": lambda *_args, **_kwargs: {"summary": "正式摘要"},
            "load_position_book": lambda **_kwargs: {},
            "build_holding_risks": lambda *_args, **_kwargs: [],
            "build_public_holding_risks": lambda *_args, **_kwargs: [],
            "build_public_position_diagnostics": lambda *_args, **_kwargs: {},
            "prepare_recommendation_history": lambda _ledger, _pending, entries, **_kwargs: (copy.deepcopy(entries), {"status": "withheld"}),
            "load_review_market_context_from_store": _canonical_review_context,
            "build_strategy_scorecards": lambda *_args, **_kwargs: [{"strategy_name": "formal", "sample_size": 1}],
            "generate_forecast": lambda *_args, **_kwargs: {"summary": "fixture"},
            "generate_report": lambda report, _output: reports.append(copy.deepcopy(report)),
            "update_data_json": lambda *_args, **_kwargs: None,
        }
        with ExitStack() as stack:
            for name, value in patch_values.items():
                stack.enter_context(mock.patch.object(run, name, value))
            stack.enter_context(
                mock.patch.object(
                    strategy_review,
                    "load_review_market_context_from_store",
                    _canonical_review_context,
                )
            )
            stack.enter_context(
                mock.patch.object(
                    shadow_evaluation,
                    "load_shadow_evaluation_entries",
                    return_value=[],
                )
            )
            stack.enter_context(
                mock.patch("chanlun.kline_cache.get_cache_stats", return_value={})
            )
            with redirect_stdout(io.StringIO()):
                run.main(
                    debug=False,
                    preview=False,
                    generated_at=datetime(2026, 8, 22, 15, 10),
                )
        self.assertEqual(len(reports), 1)
        return reports[0]

    def test_real_main_off_and_shadow_preserve_every_formal_consumer(self):
        off = self._capture_real_main_report("off")
        shadow = self._capture_real_main_report("shadow")
        self.assertEqual(off["shadow_evaluations"]["status"], "disabled")
        self.assertEqual(shadow["shadow_evaluations"]["status"], "collecting")

        def formal(report):
            result = copy.deepcopy(report)
            result.pop("shadow_evaluations", None)
            result["data_quality"]["runtime_policy"].pop(
                "stock_selection_shadow_mode", None
            )
            return result

        self.assertEqual(formal(off), formal(shadow))
        for key in (
            "picks_pure",
            "picks_fusion",
            "h4_t3_pool",
            "next_day_boom",
            "recommendation_ledger",
            "strategy_scorecards",
        ):
            self.assertEqual(off[key], shadow[key])
        self.assertEqual(
            off["diagnostics"]["candidate_funnel"],
            shadow["diagnostics"]["candidate_funnel"],
        )
        shadow_ids = {
            row["shadow_evaluation_id"]
            for row in shadow["shadow_evaluations"]["today_entries"]
        }
        formal_consumers = repr({
            key: shadow[key]
            for key in (
                "picks_pure",
                "picks_fusion",
                "h4_t3_pool",
                "next_day_boom",
                "recommendation_ledger",
                "strategy_scorecards",
            )
        })
        self.assertTrue(shadow_ids)
        self.assertTrue(all(value not in formal_consumers for value in shadow_ids))

    def test_shadow_integrates_only_h4_all_candidates_and_preserves_formal_snapshot(self):
        report = _formal_report(candidate_count=7)
        before = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=True,
                ledger_path=Path(tmpdir) / "ledger.jsonl",
                pending_dir=Path(tmpdir) / "pending",
                db_path=Path(tmpdir) / "market.sqlite",
                review_context_loader=_canonical_review_context,
            )

            pending = shadow_evaluation.shadow_pending_ledger_path(
                "2026-08-22", pending_dir=Path(tmpdir) / "pending"
            )
            self.assertTrue(Path(pending).exists())

        self.assertEqual(report, before)
        self.assertEqual(payload["mode"], "shadow")
        self.assertEqual(payload["status"], "collecting")
        self.assertTrue(payload["production_guard"]["unchanged"])
        self.assertFalse(payload["affects_production"])
        self.assertEqual(len(payload["experiments"]), 1)
        experiment = payload["experiments"][0]
        self.assertEqual(experiment["experiment_id"], "h4-t3-close-review-v1")
        self.assertEqual(experiment["display_name"], "H4 T+3 收盘价影子回看")
        self.assertEqual(experiment["version"], STRATEGY_VERSION)
        self.assertEqual(experiment["upstream_pool"], "picks_pure")
        self.assertEqual(experiment["source_pool"], "h4_t3_pool")
        self.assertEqual(experiment["intended_horizon"], 3)
        self.assertEqual(experiment["entry_mode"], "immediate_close")
        self.assertEqual(experiment["reference_adjustment"], "qfq")
        candidates = experiment["today"]["candidates"]
        self.assertEqual(len(candidates), 7)
        self.assertEqual(
            [row["code"] for row in candidates],
            [row["code"] for row in before["h4_t3_pool"]["candidates"]],
        )
        self.assertTrue(all(row["reference_is_final"] for row in candidates))
        self.assertTrue(all(row["reference_adjustment"] == "qfq" for row in candidates))
        self.assertNotIn("next_day_boom", [row["experiment_id"] for row in payload["experiments"]])
        shadow_ids = {row["shadow_evaluation_id"] for row in payload["today_entries"]}
        formal_text = repr(before)
        self.assertTrue(shadow_ids)
        self.assertTrue(all(shadow_id not in formal_text for shadow_id in shadow_ids))

    def test_same_day_retry_returns_the_actual_reused_staged_batch(self):
        report = _formal_report(candidate_count=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            kwargs = {
                "mode": "shadow",
                "publication_eligible": True,
                "ledger_path": Path(tmpdir) / "ledger.jsonl",
                "pending_dir": Path(tmpdir) / "pending",
                "db_path": Path(tmpdir) / "market.sqlite",
                "review_context_loader": _canonical_review_context,
            }
            first = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                generated_at="2026-08-22T15:10:00+08:00",
                **kwargs,
            )
            shadow_evaluation.append_shadow_evaluation_entries(
                kwargs["ledger_path"], first["today_entries"]
            )
            second = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                generated_at="2026-08-22T15:20:00+08:00",
                **kwargs,
            )

        self.assertEqual(first["status"], "collecting")
        self.assertEqual(second["status"], "collecting")
        self.assertEqual(second["today_entries"], first["today_entries"])
        self.assertEqual(
            second["today_entries"][0]["generated_at"],
            "2026-08-22T15:10:00+08:00",
        )

    def test_canonical_kline_evidence_controls_eligibility_and_staging(self):
        def context(kind):
            def loader(_db_path, entries, *, as_of=None):
                entry = entries[-1]
                close = entry["reference_close"]
                if kind == "missing":
                    return {}, [as_of], None, {"status": "missing"}
                return {
                    entry["code"]: {
                        "dates": [as_of],
                        "opens": [close],
                        "closes": [close + (1 if kind == "close_mismatch" else 0)],
                        "highs": [close + 1],
                        "lows": [close - 1],
                        "volumes": [1000],
                        "is_final": [True],
                        "adjustment": "raw" if kind == "raw" else "qfq",
                    }
                }, [as_of], None, {"status": "ok"}
            return loader

        for kind, expected_reason in (
            ("missing", "canonical_kline_missing"),
            ("raw", "canonical_adjustment_mismatch"),
            ("close_mismatch", "canonical_reference_close_mismatch"),
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmpdir:
                payload = shadow_evaluation.build_daily_shadow_evaluations(
                    _formal_report(candidate_count=1),
                    mode="shadow",
                    generated_at="2026-08-22T15:10:00+08:00",
                    publication_eligible=True,
                    ledger_path=Path(tmpdir) / "ledger.jsonl",
                    pending_dir=Path(tmpdir) / "pending",
                    db_path=Path(tmpdir) / "market.sqlite",
                    review_context_loader=context(kind),
                )
                pending = shadow_evaluation.shadow_pending_ledger_path(
                    "2026-08-22", pending_dir=Path(tmpdir) / "pending"
                )
                staged = shadow_evaluation.load_staged_shadow_evaluation_entries(
                    pending
                )

            self.assertEqual(payload["status"], "collecting")
            self.assertEqual(payload["pending"]["entries"], 0)
            self.assertEqual(payload["today_entries"], [])
            self.assertEqual(staged, [])
            candidate = payload["experiments"][0]["today"]["candidates"][0]
            self.assertFalse(candidate["evaluation_eligible"])
            self.assertIn(
                expected_reason, candidate["evaluation_ineligible_reasons"]
            )

    def test_off_mode_does_not_run_load_or_stage(self):
        report = _formal_report()
        with mock.patch.object(
            shadow_evaluation, "run_shadow_evaluations"
        ) as runner, mock.patch.object(
            shadow_evaluation, "load_shadow_evaluation_entries"
        ) as loader, mock.patch.object(
            shadow_evaluation, "stage_shadow_evaluation_entries"
        ) as stage:
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="off",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=True,
            )

        self.assertEqual(payload["mode"], "off")
        self.assertEqual(payload["status"], "disabled")
        runner.assert_not_called()
        loader.assert_not_called()
        stage.assert_not_called()

    def test_runner_builder_guard_stage_and_scorecard_failures_degrade_without_formal_mutation(self):
        failure_cases = (
            ("run_shadow_evaluations", RuntimeError("runner failed")),
            ("_build_h4_shadow_result", RuntimeError("builder failed")),
            ("stage_shadow_evaluation_entries", OSError("stage failed")),
            ("build_shadow_scorecards", RuntimeError("scorecard failed")),
        )
        for target, error in failure_cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmpdir:
                report = _formal_report()
                before = copy.deepcopy(report)
                with mock.patch.object(shadow_evaluation, target, side_effect=error):
                    payload = shadow_evaluation.build_daily_shadow_evaluations(
                        report,
                        mode="shadow",
                        generated_at="2026-08-22T15:10:00+08:00",
                        publication_eligible=True,
                        ledger_path=Path(tmpdir) / "ledger.jsonl",
                        pending_dir=Path(tmpdir) / "pending",
                        db_path=Path(tmpdir) / "market.sqlite",
                        review_context_loader=_empty_review_context,
                    )
                self.assertEqual(report, before)
                self.assertEqual(payload["status"], "unavailable")
                self.assertEqual(payload["experiments"], [])

        report = _formal_report()
        guard_failed = {
            "schema_version": 1,
            "mode": "shadow",
            "affects_production": False,
            "status": "production_guard_failed",
            "production_guard": {
                "unchanged": False,
                "before_sha256": "before",
                "after_sha256": "after",
            },
            "production_reference": {},
            "experiments": [{
                "experiment_id": "h4-t3-close-review-v1",
                "status": "available",
                "today": {"candidates": [_candidate(1)]},
            }],
        }
        with mock.patch.object(
            shadow_evaluation, "run_shadow_evaluations", return_value=guard_failed
        ), mock.patch.object(
            shadow_evaluation, "stage_shadow_evaluation_entries"
        ) as stage:
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=True,
            )
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["experiments"], [])
        stage.assert_not_called()

    def test_h4_shadow_requires_full_production_attestation_before_staging(self):
        invalid_pools = []
        for key, value in (
            ("production_attested", None),
            ("production_attested", False),
            ("mode", "shadow"),
            ("status", "unavailable"),
        ):
            report = _formal_report()
            if value is None:
                report["h4_t3_pool"].pop(key)
            else:
                report["h4_t3_pool"][key] = value
            invalid_pools.append((key, value, report))

        for key, value, report in invalid_pools:
            with self.subTest(key=key, value=value), mock.patch.object(
                shadow_evaluation, "stage_shadow_evaluation_entries"
            ) as stage:
                payload = shadow_evaluation.build_daily_shadow_evaluations(
                    report,
                    mode="shadow",
                    generated_at="2026-08-22T15:10:00+08:00",
                    publication_eligible=True,
                    review_context_loader=_empty_review_context,
                )
            self.assertEqual(payload["status"], "unavailable")
            self.assertEqual(payload["experiments"], [])
            stage.assert_not_called()

    def test_decision_and_holding_outputs_are_inside_formal_guard(self):
        report = _formal_report()
        original_guard = shadow_evaluation.production_digest(
            shadow_evaluation._build_shadow_guard_snapshot(report)
        )
        report["decision_brief"]["summary"] = "被篡改的决策摘要"
        self.assertNotEqual(
            original_guard,
            shadow_evaluation.production_digest(
                shadow_evaluation._build_shadow_guard_snapshot(report)
            ),
        )

        report = _formal_report()
        report["future_formal_output"] = {"value": 1}
        original_guard = shadow_evaluation.production_digest(
            shadow_evaluation._build_shadow_guard_snapshot(report)
        )
        report["future_formal_output"]["value"] = 2
        self.assertNotEqual(
            original_guard,
            shadow_evaluation.production_digest(
                shadow_evaluation._build_shadow_guard_snapshot(report)
            ),
        )
        report["shadow_evaluations"] = {"runtime_only": object()}
        self.assertEqual(
            shadow_evaluation.production_digest(
                shadow_evaluation._build_shadow_guard_snapshot(report)
            ),
            shadow_evaluation.production_digest(
                shadow_evaluation._build_shadow_guard_snapshot(
                    {key: value for key, value in report.items()
                     if key != "shadow_evaluations"}
                )
            ),
        )

    def test_partial_experiment_failure_keeps_available_rows(self):
        report = _formal_report(candidate_count=0)
        base_payload = {
            "schema_version": 1,
            "mode": "shadow",
            "affects_production": False,
            "status": "collecting",
            "production_guard": {
                "unchanged": True,
                "before_sha256": "same",
                "after_sha256": "same",
            },
            "production_reference": {},
            "experiments": [
                {
                    "experiment_id": "available",
                    "display_name": "可用实验",
                    "version": "v1",
                    "strategy_version": "v1",
                    "upstream_pool": "picks_pure",
                    "source_pool": "h4_t3_pool",
                    "intended_horizon": 3,
                    "entry_mode": "immediate_close",
                    "reference_adjustment": "qfq",
                    "status": "available",
                    "today": {"candidates": []},
                },
                {
                    "experiment_id": "broken",
                    "status": "unavailable",
                    "error": "builder failed",
                },
            ],
        }
        with mock.patch.object(
            shadow_evaluation,
            "run_shadow_evaluations",
            return_value=base_payload,
        ):
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=False,
                review_context_loader=_empty_review_context,
            )
        self.assertEqual(payload["status"], "collecting")
        self.assertEqual(
            [row["status"] for row in payload["experiments"]],
            ["available", "unavailable"],
        )

        report = _formal_report()
        original_guard = shadow_evaluation.production_digest(
            shadow_evaluation._build_shadow_guard_snapshot(report)
        )
        report["holding_risks"][0]["risk"] = "被篡改的持仓风险"
        self.assertNotEqual(
            original_guard,
            shadow_evaluation.production_digest(
                shadow_evaluation._build_shadow_guard_snapshot(report)
            ),
        )

    def test_builder_receives_copy_and_projection_failure_is_unavailable(self):
        report = _formal_report()
        before = copy.deepcopy(report)

        def mutating_runner(snapshot, experiments):
            snapshot["picks_pure"].clear()
            return {
                "schema_version": 1,
                "mode": "shadow",
                "affects_production": False,
                "status": "collecting",
                "production_guard": {
                    "unchanged": True,
                    "before_sha256": "same",
                    "after_sha256": "same",
                },
                "production_reference": {},
                "experiments": [{
                    "experiment_id": "copy-check",
                    "display_name": "复制隔离检查",
                    "version": "v1",
                    "strategy_version": "v1",
                    "upstream_pool": "picks_pure",
                    "source_pool": "h4_t3_pool",
                    "intended_horizon": 3,
                    "entry_mode": "immediate_close",
                    "reference_adjustment": "qfq",
                    "status": "available",
                    "today": {"candidates": []},
                }],
            }

        with mock.patch.object(
            shadow_evaluation, "run_shadow_evaluations", side_effect=mutating_runner
        ):
            payload = shadow_evaluation.build_daily_shadow_evaluations(
                report,
                mode="shadow",
                generated_at="2026-08-22T15:10:00+08:00",
                publication_eligible=False,
                review_context_loader=_empty_review_context,
            )
        self.assertEqual(report, before)
        self.assertEqual(payload["status"], "collecting")

        report["diagnostics"]["candidate_funnel"]["bad"] = object()
        payload = shadow_evaluation.build_daily_shadow_evaluations(
            report,
            mode="shadow",
            generated_at="2026-08-22T15:10:00+08:00",
            publication_eligible=False,
        )
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["experiments"], [])

    def test_run_hook_is_after_formal_report_and_before_report_generation(self):
        source = Path("run.py").read_text(encoding="utf-8")
        report_index = source.index("report_data = {")
        shadow_index = source.index("build_daily_shadow_evaluations(", report_index)
        generate_index = source.index("generate_report(report_data", report_index)
        for formal_token in (
            "recommendation_entries = build_recommendation_entries(",
            "strategy_scorecards = build_strategy_scorecards(",
            '"h4_t3_pool": h4_t3_pool',
            '"next_day_boom": next_day_boom',
            '"decision_brief": decision_brief',
        ):
            self.assertLess(source.index(formal_token), shadow_index)
        self.assertLess(report_index, shadow_index)
        self.assertLess(shadow_index, generate_index)


if __name__ == "__main__":
    unittest.main()
