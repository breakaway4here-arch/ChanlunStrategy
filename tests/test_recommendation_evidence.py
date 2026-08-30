"""Tests for the HTML-only recommendation evidence projection."""

import copy
import importlib.util
import json
import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)
from chanlun.report_generator import build_formal_output_projection
from chanlun.shadow_evaluation import production_digest


EVIDENCE_SECTION_KEYS = {
    "summary",
    "decision_score",
    "rank_evidence",
    "price_evidence",
    "daily_structure",
    "sublevel_30m",
    "volume_and_capital",
    "market_and_sector",
    "risk_and_next",
    "historical_validation",
    "display_derived",
}


def _workspace_daily(rows, raw_candidates=None):
    return {
        "date": "2026-08-28",
        "workspace": {
            "view_order": ["main"],
            "views": {"main": rows},
        },
        "picks_fusion": list(raw_candidates or []),
    }


def _workspace_row(code="301629", rank=1, opportunity_score=88):
    return {
        "code": code,
        "name": "矽电股份",
        "sector": "半导体",
        "view_rank": rank,
        "opportunity_score": opportunity_score,
        "rank_trace": {"selected_reason": "主推池单源入榜"},
        "action": "可上车",
        "formal_decision_contract": {
            "action": "观察",
            "action_reason": "等待确认",
        },
        "ref": {"pool": "picks_fusion", "code": code},
    }


def _raw_candidate(code="301629", decision=None):
    return {
        "code": code,
        "decision_engine_v1": decision if decision is not None else {
            "decision_code": "recommend",
            "total_score": 62,
            "structure": {"score": 10},
            "position": {"score": 15},
            "sentiment": {"score": 37},
        },
    }


class TestRecommendationEvidenceModule(unittest.TestCase):

    def test_module_exposes_projection_builder(self):
        spec = importlib.util.find_spec("chanlun.recommendation_evidence")
        self.assertIsNotNone(spec, "recommendation evidence module is missing")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(
            callable(
                getattr(
                    module,
                    "build_recommendation_evidence_projection",
                    None,
                )
            )
        )

    def test_evidence_projection_does_not_mutate_formal_or_daily_data(self):
        formal_report = {
            "date": "2026-08-28",
            "market": {"沪深300": {"close": 4210.0}},
            "picks_pure": [],
            "picks_fusion": [],
            "data_quality": {"is_trading_day": True, "is_official": True},
        }
        daily_data = {
            "date": "2026-08-28",
            "workspace": {"views": {"main": []}},
        }
        formal_before = copy.deepcopy(formal_report)
        daily_before = copy.deepcopy(daily_data)

        projection = build_recommendation_evidence_projection(
            formal_report,
            daily_data,
        )

        self.assertEqual(formal_report, formal_before)
        self.assertEqual(daily_data, daily_before)
        self.assertEqual(projection["report_date"], "2026-08-28")

    def test_formal_digest_is_identical_before_and_after_evidence_build(self):
        formal_report = {
            "date": "2026-08-28",
            "market": {},
            "picks_pure": [],
            "picks_fusion": [],
            "data_quality": {"is_trading_day": True, "is_official": True},
        }
        daily_data = {
            "date": "2026-08-28",
            "workspace": {"views": {"main": []}},
        }
        before = production_digest(build_formal_output_projection(formal_report))

        build_recommendation_evidence_projection(formal_report, daily_data)

        after = production_digest(build_formal_output_projection(formal_report))
        self.assertEqual(after, before)

    def test_projection_is_strict_json_without_nan_or_infinity(self):
        projection = build_recommendation_evidence_projection(
            {"date": "2026-08-28", "ignored": float("nan")},
            {"date": "2026-08-28", "ignored": float("inf")},
        )
        encoded = json.dumps(projection, allow_nan=False, sort_keys=True)
        self.assertEqual(json.loads(encoded), projection)

    def test_projection_contains_all_eleven_sections_with_status_metadata(self):
        row = _workspace_row()
        projection = build_recommendation_evidence_projection(
            {"date": "2026-08-28"},
            _workspace_daily([row], [_raw_candidate()]),
        )

        candidate = projection["views"]["main"][0]
        self.assertEqual(EVIDENCE_SECTION_KEYS, EVIDENCE_SECTION_KEYS & candidate.keys())
        for section_name in EVIDENCE_SECTION_KEYS:
            section = candidate[section_name]
            self.assertIn("status", section, section_name)
            self.assertTrue(
                any(key in section for key in ("as_of", "source", "reason")),
                section_name,
            )

    def test_formal_action_only_comes_from_workspace_contract(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw["formal_decision_contract"] = {"action": "可上车"}

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]

        self.assertEqual(candidate["summary"]["formal_action"], "观察")
        self.assertNotEqual(candidate["summary"]["formal_action"], row["action"])

    def test_decision_score_never_falls_back_to_opportunity_score(self):
        row = _workspace_row(opportunity_score=99)
        raw = _raw_candidate(decision={"decision_code": "recommend"})

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]

        self.assertIsNone(candidate["decision_score"]["score"])
        self.assertEqual(candidate["decision_score"]["status"], "missing")
        self.assertEqual(candidate["rank_evidence"]["opportunity_score"], 99)

    def test_rank_evidence_preserves_workspace_order_and_view_rank(self):
        second = _workspace_row("301629", rank=2, opportunity_score=30)
        first = _workspace_row("301266", rank=1, opportunity_score=90)
        projection = build_recommendation_evidence_projection(
            {},
            _workspace_daily(
                [second, first],
                [_raw_candidate("301629"), _raw_candidate("301266")],
            ),
        )

        candidates = projection["views"]["main"]
        self.assertEqual([item["code"] for item in candidates], ["301629", "301266"])
        self.assertEqual(
            [item["rank_evidence"]["view_rank"] for item in candidates],
            [2, 1],
        )

    def test_missing_raw_candidate_keeps_workspace_fact_but_not_default_score(self):
        row = _workspace_row()
        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], []),
        )["views"]["main"][0]

        self.assertEqual(candidate["code"], "301629")
        self.assertEqual(candidate["summary"]["formal_action"], "观察")
        self.assertEqual(candidate["decision_score"]["status"], "missing")
        self.assertIsNone(candidate["decision_score"]["score"])

    def test_non_positive_or_non_finite_prices_are_missing(self):
        row = _workspace_row()
        row["current_price"] = float("nan")
        row["formal_decision_contract"].update({
            "reference_price": -1,
            "pressure_price": float("inf"),
            "invalidation_price": 0,
        })
        raw = _raw_candidate()
        raw.update({
            "current_price": 0,
            "stop_loss": -2,
            "trailing_targets": [
                {"pct": 5, "price": 0},
                {"pct": 10, "price": float("nan")},
            ],
        })

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]
        prices = candidate["price_evidence"]

        self.assertIsNone(prices["current_price"])
        self.assertIsNone(prices["reference_price"])
        self.assertIsNone(prices["pressure_price"])
        self.assertIsNone(prices["invalidation_price"])
        self.assertEqual(prices["trailing_targets"], [])
        json.dumps(candidate, allow_nan=False)

    def test_chart_price_metadata_admits_real_trailing_targets(self):
        row = _workspace_row()
        row["current_price"] = 10.2
        row["formal_decision_contract"].update({
            "reference_price": 10.0,
            "pressure_price": 11.0,
            "invalidation_price": 9.0,
        })
        raw = _raw_candidate()
        raw["trailing_targets"] = [
            {"price": 11.8, "label": "T+1"},
            {"price": 12.6, "label": "T+3"},
            {"price": 13.4, "label": "T+5"},
            {"price": 14.2, "label": "目标4"},
            {"price": 15.0, "label": "目标5"},
            {"price": 15.8, "label": "目标6"},
            {"price": 16.6, "label": "目标7"},
        ]

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]

        self.assertEqual(
            [target["price"] for target in candidate["price_evidence"]["trailing_targets"]],
            [11.8, 12.6, 13.4, 14.2, 15.0],
        )
        self.assertEqual(
            candidate["price_evidence"]["trailing_targets_contract"],
            {
                "max_visible": 5,
                "input_count": 7,
                "valid_count": 7,
                "visible_count": 5,
                "omitted_count": 2,
                "truncated": True,
                "reason": "display_payload_limit",
            },
        )
        self.assertIn(
            "trailing_targets",
            candidate["display_derived"]["chart_evidence"]["prices"]["available"],
        )

    def test_invalid_latest_close_never_falls_back_to_an_older_price(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw["closes"] = [10.0, 0]

        prices = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["price_evidence"]

        self.assertIsNone(prices["current_price"])
        self.assertIsNone(prices["current_price_source"])

    def test_conflicting_formal_price_is_hidden_with_audit_reason(self):
        row = _workspace_row()
        row["current_price"] = 10
        row["formal_decision_contract"].update({
            "reference_price": 9.5,
            "pressure_price": 12,
        })
        row["formal_decision_contract_diagnostics"] = {
            "pressure_price": "conflict",
        }

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]

        self.assertIsNone(candidate["price_evidence"]["pressure_price"])
        self.assertEqual(
            candidate["price_evidence"]["audit_reasons"]["pressure_price"],
            "conflict",
        )
        self.assertEqual(candidate["price_evidence"]["status"], "conflict")

    def test_price_derived_values_require_real_boundaries(self):
        row = _workspace_row()
        row["current_price"] = 10
        row["formal_decision_contract"].update({
            "reference_price": 8,
            "pressure_price": 12,
            "invalidation_price": 9,
        })

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]
        derived = candidate["display_derived"]

        self.assertEqual(derived["distance_from_reference_pct"], 25.0)
        self.assertEqual(derived["upside_to_pressure_pct"], 20.0)
        self.assertEqual(derived["downside_to_invalidation_pct"], 10.0)
        self.assertEqual(derived["risk_reward_ratio"], 2.0)

        row["formal_decision_contract"].pop("pressure_price")
        without_pressure = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]["display_derived"]
        self.assertIsNone(without_pressure["upside_to_pressure_pct"])
        self.assertIsNone(without_pressure["risk_reward_ratio"])

    def test_display_derived_extreme_finite_prices_stay_strict_json(self):
        row = _workspace_row()
        row["current_price"] = 1e308
        row["formal_decision_contract"].update({
            "reference_price": 1e-308,
        })

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]
        derived = candidate["display_derived"]

        self.assertIsNone(derived["distance_from_reference_pct"])
        json.dumps(candidate, ensure_ascii=False, allow_nan=False)

    def test_unbounded_integer_numeric_inputs_fail_closed(self):
        row = _workspace_row()
        row["current_price"] = 10 ** 1000

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]

        self.assertIsNone(candidate["price_evidence"]["current_price"])
        json.dumps(candidate, ensure_ascii=False, allow_nan=False)

    def test_missing_pressure_invalidation_and_targets_do_not_create_defaults(self):
        row = _workspace_row()
        row["current_price"] = 10
        row["formal_decision_contract"]["reference_price"] = 9.8

        prices = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]["price_evidence"]

        self.assertIsNone(prices["pressure_price"])
        self.assertIsNone(prices["invalidation_price"])
        self.assertEqual(prices["trailing_targets"], [])
        self.assertEqual(prices["missing_fields"], [
            "pressure_price",
            "invalidation_price",
            "trailing_targets",
        ])

    def test_daily_structure_maps_explicit_evidence_without_computing_missing_ma(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "trend_type": "上涨趋势",
            "closes": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0],
            "best_buy_point": {
                "type": "二买",
                "reason": "回踩不破关键位",
                "signal_date": "2026-08-28",
                "signal_age_days": 0,
                "daily_startup_grade": "strong",
                "daily_startup_label": "强启动",
                "startup_signals": ["close_above_ma5"],
            },
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "bars": 120,
                "stale": False,
                "is_final": True,
            },
            "pivots": {"ZG": 11.2, "ZD": 10.3, "count": 1},
            "ma_bullish": True,
        })

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]
        daily = candidate["daily_structure"]

        self.assertEqual(daily["status"], "available")
        self.assertEqual(daily["trend"], "上涨趋势")
        self.assertEqual(daily["signal"], "二买")
        self.assertEqual(daily["signal_date"], "2026-08-28")
        self.assertEqual(daily["startup_grade"], "strong")
        self.assertEqual(daily["startup_label"], "强启动")
        self.assertEqual(daily["health"], "verified")
        self.assertEqual(daily["pivots"], {"ZG": 11.2, "ZD": 10.3, "count": 1})
        # Closes and the boolean MA flag do not authorize inventing MA values.
        self.assertIsNone(daily["ma5"])
        self.assertIsNone(daily["ma10"])
        self.assertIsNone(daily["ma20"])

    def test_daily_structure_maps_declared_ma_values_only(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "trend_type": "盘整",
            "ma5": 10.5,
            "ma10": 10.2,
            "ma20": None,
            "ma50": "not-a-number",
            "macd_status": "DIF/DEA 双线0轴上",
        })

        daily = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["daily_structure"]

        self.assertEqual(daily["ma5"], 10.5)
        self.assertEqual(daily["ma10"], 10.2)
        self.assertIsNone(daily["ma20"])
        self.assertIsNone(daily["ma50"])
        self.assertEqual(daily["macd"], "DIF/DEA 双线0轴上")

    def test_daily_summary_cannot_claim_ma5_ma10_hold_when_values_are_missing(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "best_buy_point": {
                "type": "趋势延续候选",
                "source_type": "日线趋势延续",
                "reason": "20日平台突破；MA5/MA10保持",
                "signal_date": "2026-08-28",
            },
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "stale": False,
                "is_final": True,
            },
            "ma20": 302.1,
            "ma50": 286.4,
        })

        daily = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["daily_structure"]

        self.assertIsNone(daily["ma5"])
        self.assertIsNone(daily["ma10"])
        self.assertNotIn("MA5/MA10保持", daily.get("summary") or "")
        explicit_missing = json.dumps(daily, ensure_ascii=False)
        self.assertRegex(
            explicit_missing,
            r"(?:MA5[^\"]*未提供[^\"]*MA10|MA5[^\"]*MA10[^\"]*未提供)",
            "MA5/MA10当前值缺失时，证据对象没有明确的用户可理解缺失语义",
        )

    def test_sublevel_maps_fresh_independent_confirmation_without_minute_arrays(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "best_buy_point": {
                "type": "二买",
                "sublevel_confirm_grade": "S",
                "sublevel_confirm_label": "S级确认",
                "sublevel_confirm_reason": "30min出现二买/三买确认",
                "confirm_date": "2026-08-28",
                "confirm_age_days": 0,
                "confirmations": ["30min 二买"],
            },
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "ema_bullish_alignment": True,
                "close_above_ema5": True,
                "ema5_rising_bars": 3,
                "recent_peak_drawdown_pct": 1.2,
                "macd_hist_direction": "improving",
                "ema5_reclaim": True,
                "stop_fall": True,
                "buy_point": "二买",
                "fresh_yang_pattern": "two_yang_one_yin",
                "recovery_bundle_match": True,
            },
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "source": "market_history_db",
                "bars": 50,
                "stale": False,
                "is_final": True,
            },
            # These arrays must never be copied into the evidence plane.
            "dates_30m": ["2026-08-28 14:00:00"],
            "closes_30m": [11.0],
            "opens_30m": [10.9],
            "highs_30m": [11.1],
            "lows_30m": [10.8],
            "volumes_30m": [1000],
            "macd_hist_30m": [0.1],
        })

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]
        sublevel = candidate["sublevel_30m"]

        self.assertEqual(sublevel["status"], "available")
        self.assertTrue(sublevel["confirmed"])
        self.assertEqual(sublevel["confirmation_status"], "confirmed")
        self.assertEqual(sublevel["interval"], "30m")
        self.assertEqual(sublevel["latest_date"], "2026-08-28")
        self.assertEqual(sublevel["latest_ts"], "2026-08-28 14:30:00")
        self.assertEqual(sublevel["buy_point"], "二买")
        self.assertEqual(sublevel["confirm_date"], "2026-08-28")
        self.assertEqual(sublevel["macd_state"], "improving")
        self.assertEqual(sublevel["ema_alignment"], "EMA5 > EMA10")
        for forbidden in (
            "dates_30m", "closes_30m", "opens_30m", "highs_30m",
            "lows_30m", "volumes_30m", "macd_hist_30m",
        ):
            self.assertNotIn(forbidden, sublevel)

    def test_ema_alignment_alone_is_partial_and_not_a_30m_confirmation(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "sublevel_confirm_grade": "C",
            "sublevel_confirm_label": "C级确认",
            "sublevel_confirm_reason": "30分钟均线仍为多头排列，但未形成独立确认",
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "ema_bullish_alignment": True,
                "close_above_ema5": True,
                "ema5_rising_bars": 2,
                "macd_hist_direction": "weakening",
                "ema5_reclaim": False,
                "stop_fall": False,
                "buy_point": None,
                "fresh_yang_pattern": None,
                "recovery_bundle_match": False,
            },
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "stale": False,
                "is_final": True,
            },
        })

        sublevel = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["sublevel_30m"]

        self.assertEqual(sublevel["status"], "partial")
        self.assertFalse(sublevel["confirmed"])
        self.assertEqual(sublevel["confirmation_status"], "alignment_only")
        self.assertEqual(sublevel["reason"], "30分钟均线仍为多头排列，但未形成独立确认")
        self.assertEqual(sublevel["ema_alignment"], "EMA5 > EMA10")

    def test_recovery_bundle_alone_is_shadow_evidence_not_confirmation(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "ema_bullish_alignment": True,
                "close_above_ema5": True,
                "ema5_rising_bars": 3,
                "macd_hist_direction": "improving",
                "ema5_reclaim": True,
                "stop_fall": True,
                # The recovery bundle is retained for shadow audit only.  It
                # is deliberately not accompanied by a decision-grade event.
                "buy_point": None,
                "fresh_yang_pattern": None,
                "recovery_bundle_match": True,
            },
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "stale": False,
                "is_final": True,
            },
        })

        sublevel = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["sublevel_30m"]

        self.assertEqual(sublevel["status"], "partial")
        self.assertFalse(sublevel["confirmed"])
        self.assertNotEqual(sublevel["confirmation_status"], "confirmed")
        self.assertEqual(sublevel["confirmation_status"], "alignment_only")
        self.assertTrue(sublevel["recovery_bundle_match"])

    def test_raw_30m_buy_point_is_context_only_without_confirmation_evidence(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "buy_points_30min": [{"type": "二买", "index": 49}],
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "stale": False,
                "is_final": True,
            },
        })

        sublevel = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["sublevel_30m"]

        self.assertEqual(sublevel["buy_point"], "二买")
        self.assertEqual(sublevel["status"], "partial")
        self.assertFalse(sublevel["confirmed"])
        self.assertEqual(sublevel["confirmation_status"], "unavailable")
        self.assertEqual(sublevel["confirmation_schema_status"], "invalid")

    def test_stale_or_missing_30m_is_not_confirmed_and_keeps_explicit_reason(self):
        row = _workspace_row()
        stale_raw = _raw_candidate()
        stale_raw.update({
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "ema_bullish_alignment": True,
                "buy_point": "二买",
                "fresh_yang_pattern": "two_yang_one_yin",
            },
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "stale",
                "latest_date": "2026-08-21",
                "latest_ts": "2026-08-21 15:00:00",
                "stale": True,
                "is_final": True,
            },
        })
        stale = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [stale_raw]),
        )["views"]["main"][0]["sublevel_30m"]
        self.assertEqual(stale["status"], "stale")
        self.assertFalse(stale["confirmed"])
        self.assertEqual(stale["confirmation_status"], "stale")
        self.assertIn("过期", stale["reason"])

        missing_raw = _raw_candidate()
        missing = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [missing_raw]),
        )["views"]["main"][0]["sublevel_30m"]
        self.assertEqual(missing["status"], "missing")
        self.assertFalse(missing["confirmed"])
        self.assertEqual(missing["confirmation_status"], "missing")
        self.assertIn("未提供", missing["reason"])

    def test_conflicting_or_invalid_30m_freshness_dates_fail_closed(self):
        row = _workspace_row()
        cases = (
            {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-29 14:30:00",
                "as_of": "2026-08-28",
                "stale": False,
                "is_final": True,
            },
            {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "as_of": "2026-08-29T14:30:00",
                "stale": False,
                "is_final": True,
            },
            {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28garbage",
                "latest_ts": "2026-08-28 14:30:00",
                "stale": False,
                "is_final": True,
            },
        )
        for input_evidence in cases:
            with self.subTest(input_evidence=input_evidence):
                raw = _raw_candidate()
                raw.update({
                    "strategy_input_evidence": input_evidence,
                    "confirmation_evidence": {
                        "buy_point": "二买",
                        "fresh_yang_pattern": "two_yang_one_yin",
                    },
                })
                sublevel = build_recommendation_evidence_projection(
                    {},
                    _workspace_daily([row], [raw]),
                )["views"]["main"][0]["sublevel_30m"]

                self.assertNotEqual(sublevel["status"], "available")
                self.assertNotEqual(
                    sublevel["confirmation_status"],
                    "confirmed",
                )
                self.assertFalse(sublevel["confirmed"])

    def test_30m_missing_final_flag_cannot_be_confirmed(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "verified",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "stale": False,
            },
            "confirmation_evidence": {
                "buy_point": "二买",
                "fresh_yang_pattern": "two_yang_one_yin",
            },
        })

        sublevel = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]["sublevel_30m"]

        self.assertNotEqual(sublevel["status"], "available")
        self.assertNotEqual(sublevel["confirmation_status"], "confirmed")
        self.assertFalse(sublevel["confirmed"])

    def test_strategy_without_next_condition_uses_declared_missing_copy(self):
        row = _workspace_row()
        risk = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [_raw_candidate()]),
        )["views"]["main"][0]["risk_and_next"]

        self.assertEqual(risk["next_confirmation"]["items"], [])
        self.assertEqual(
            risk["next_confirmation"]["empty_text"],
            "当前策略未声明下一确认条件",
        )
        self.assertNotIn("暂无新增确认条件", json.dumps(risk, ensure_ascii=False))

    def test_declared_risk_and_next_conditions_are_preserved_deterministically(self):
        row = _workspace_row()
        row["risk_flags"] = ["距参考价过远"]
        raw = _raw_candidate()
        raw.update({
            "upgrade_conditions": ["30分钟重新确认"],
            "keep_conditions": ["日线结构保持"],
            "retest_conditions": ["缩量回踩参考位"],
            "cancel_conditions": ["放量长阴"],
            "invalidation_conditions": ["跌破正式失效位"],
        })
        daily = _workspace_daily([row], [raw])

        first = build_recommendation_evidence_projection({}, daily)
        second = build_recommendation_evidence_projection({}, daily)
        risk = first["views"]["main"][0]["risk_and_next"]

        self.assertEqual(first, second)
        self.assertEqual(risk["risk_labels"], ["距参考价过远"])
        self.assertEqual(
            risk["next_confirmation"]["items"],
            ["30分钟重新确认"],
        )
        self.assertEqual(
            risk["invalidation_conditions"]["items"],
            ["跌破正式失效位"],
        )

    def test_psy12_audit_is_copied_only_into_html_evidence_plane(self):
        daily = _workspace_daily([], [])
        audit = {
            "schema_version": 1,
            "mode": "psy12_shadow_audit",
            "status": "insufficient_observation_days",
            "required_days": 20,
            "valid_days": 1,
            "stored_complete_days": 1,
            "recomputable_days": 5,
            "complete_days": 1,
            "missing_days": 4,
            "mismatch_days": 0,
            "affects_production": False,
            "promotion_eligible": False,
            "promotion_requires_new_authorization": True,
        }
        daily_before = copy.deepcopy(daily)
        audit_before = copy.deepcopy(audit)

        projection = build_recommendation_evidence_projection(
            {},
            daily,
            psy12_shadow_audit=audit,
        )

        self.assertEqual(
            projection["market_sentiment"]["psy12_shadow_audit"],
            audit,
        )
        self.assertEqual(daily, daily_before)
        self.assertEqual(audit, audit_before)
        self.assertNotIn("psy12_shadow_audit", daily)
        json.dumps(projection, ensure_ascii=False, allow_nan=False)

    def test_psy12_audit_projection_is_whitelisted_and_bounded(self):
        daily = _workspace_daily([], [])
        audit = {
            "schema_version": 1,
            "mode": "psy12_shadow_audit",
            "status": "insufficient_observation_days",
            "required_days": 20,
            "valid_days": 1,
            "daily": [
                {
                    "date": "2026-08-{:02d}".format(index + 1),
                    "formal_score": 50,
                    "shadow_score": 51,
                    "components": {"breadth": 50, "huge": list(range(1000))},
                    "arbitrary": list(range(1000)),
                }
                for index in range(100)
            ],
            "hypothetical_changes": [
                {
                    "date": "2026-08-28",
                    "changes": ["market_temperature_score"] * 1000,
                    "arbitrary": list(range(1000)),
                }
                for _ in range(100)
            ],
            "arbitrary_top_level": list(range(100000)),
            "affects_production": False,
            "promotion_eligible": False,
            "promotion_requires_new_authorization": True,
        }

        projected = build_recommendation_evidence_projection(
            {},
            daily,
            psy12_shadow_audit=audit,
        )["market_sentiment"]["psy12_shadow_audit"]

        self.assertNotIn("arbitrary_top_level", projected)
        self.assertLessEqual(len(projected["daily"]), 20)
        self.assertLessEqual(len(projected["hypothetical_changes"]), 20)
        self.assertNotIn("arbitrary", projected["daily"][0])
        self.assertNotIn("huge", projected["daily"][0]["components"])
        self.assertLessEqual(
            len(projected["hypothetical_changes"][0]["changes"]),
            3,
        )
        self.assertLess(
            len(json.dumps(projected, ensure_ascii=False).encode()),
            32768,
        )
        json.dumps(projected, ensure_ascii=False, allow_nan=False)

    def test_psy12_audit_unbounded_integer_fails_closed(self):
        projected = build_recommendation_evidence_projection(
            {},
            _workspace_daily([], []),
            psy12_shadow_audit={
                "schema_version": 1,
                "mode": "psy12_shadow_audit",
                "valid_days": 10 ** 1000,
                "affects_production": False,
                "promotion_eligible": False,
                "promotion_requires_new_authorization": True,
            },
        )["market_sentiment"]["psy12_shadow_audit"]

        self.assertNotIn("valid_days", projected)
        json.dumps(projected, ensure_ascii=False, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
