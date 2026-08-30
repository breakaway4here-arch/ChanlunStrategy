"""Completion contracts for the recommendation evidence display plane."""

import copy
import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)
from tests.test_recommendation_evidence import (
    _raw_candidate,
    _workspace_daily,
    _workspace_row,
)


class _Verified30mResult:
    def __init__(self):
        self.dates = [
            "2026-08-27 13:00:00",
            "2026-08-27 13:30:00",
            "2026-08-27 14:00:00",
            "2026-08-27 14:30:00",
            "2026-08-28 09:30:00",
            "2026-08-28 10:00:00",
            "2026-08-28 10:30:00",
            "2026-08-28 11:00:00",
            "2026-08-28 13:00:00",
            "2026-08-28 13:30:00",
            "2026-08-28 14:00:00",
            "2026-08-28 14:30:00",
        ]
        self.closes = [10.0 + index * 0.2 for index in range(len(self.dates))]
        self.macd_dif = [0.1 + index * 0.03 for index in range(len(self.dates))]
        self.macd_dea = [0.08 + index * 0.02 for index in range(len(self.dates))]
        self.macd_hist = [
            -0.30, -0.25, -0.20, -0.15, -0.10, -0.08,
            -0.06, -0.04, -0.03, 0.01, 0.04, 0.08,
        ]


class RecommendationEvidenceCompletionTests(unittest.TestCase):
    def _candidate(self, raw_updates=None, row_updates=None, daily_updates=None):
        row = _workspace_row()
        raw = _raw_candidate()
        row.update(copy.deepcopy(row_updates or {}))
        raw.update(copy.deepcopy(raw_updates or {}))
        daily = _workspace_daily([row], [raw])
        daily.update(copy.deepcopy(daily_updates or {}))
        return build_recommendation_evidence_projection({}, daily)["views"]["main"][0]

    def test_recommendation_conclusion_has_signal_horizon_and_final_data_metadata(self):
        candidate = self._candidate(
            raw_updates={
                "best_buy_point": {
                "type": "二买",
                "price": 18.6,
                "signal_date": "2026-08-28",
                "signal_age_days": 0,
                "reason": "回踩中枢后确认",
                },
                "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
                },
            },
            row_updates={
                "formal_decision_contract": {
                    "action": "观察",
                    "action_reason": "等待确认",
                    "intended_horizon": "T+3",
                },
            },
        )

        summary = candidate["summary"]
        self.assertEqual(summary["pool_identity"], "picks_fusion")
        self.assertEqual(summary["view_rank"], 1)
        self.assertEqual(summary["signal_type"], "二买")
        self.assertEqual(summary["signal_date"], "2026-08-28")
        self.assertEqual(summary["signal_age_days"], 0)
        self.assertEqual(summary["applicable_horizon"], 3)
        self.assertEqual(summary["data_latest_date"], "2026-08-28")
        self.assertEqual(summary["data_source"], "market_history_db")
        self.assertIs(summary["data_is_final"], True)
        self.assertIs(summary["data_stale"], False)

    def test_recommendation_conclusion_uses_same_validated_daily_freshness(self):
        candidate = self._candidate({
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-27",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
        })

        summary = candidate["summary"]
        daily = candidate["daily_structure"]
        self.assertEqual(daily["status"], "stale")
        self.assertEqual(summary["data_health"], daily["health"])
        self.assertEqual(summary["data_latest_date"], daily["latest_date"])
        self.assertEqual(summary["data_stale"], daily["stale"])

    def test_daily_freshness_is_unknown_when_not_declared(self):
        candidate = self._candidate({
            "best_buy_point": {"type": "二买", "signal_date": "2026-08-28"},
        })

        daily = candidate["daily_structure"]
        self.assertIsNone(daily["stale"])
        self.assertEqual(daily["freshness_status"], "unknown")
        self.assertIsNone(candidate["summary"]["data_stale"])

    def test_verified_daily_without_current_latest_date_is_not_available(self):
        candidate = self._candidate({
            "best_buy_point": {"type": "二买", "signal_date": "2026-08-28"},
            "data_status": {
                "daily": "verified",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
        })

        daily = candidate["daily_structure"]
        self.assertEqual(daily["status"], "partial")
        self.assertEqual(daily["freshness_status"], "missing")
        self.assertIsNone(daily["stale"])
        self.assertIn("日线最后日期未提供", daily["missing_evidence"])

    def test_verified_daily_without_source_is_not_available(self):
        candidate = self._candidate({
            "best_buy_point": {"type": "二买", "signal_date": "2026-08-28"},
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "stale": False,
                "is_final": True,
            },
        })

        daily = candidate["daily_structure"]
        self.assertEqual(daily["status"], "partial")
        self.assertIsNone(daily["data_source"])
        self.assertIn("日线数据来源未提供", daily["missing_evidence"])

    def test_invalid_future_or_inconsistent_signal_dates_fail_closed(self):
        cases = (
            ("garbage", 0, "invalid"),
            ("2026-08-29", 0, "future"),
            ("2026-08-28", 2, "conflict"),
            ("2026-08-27", 0, "conflict"),
        )
        for signal_date, age_days, expected_status in cases:
            with self.subTest(signal_date=signal_date, age_days=age_days):
                candidate = self._candidate({
                    "best_buy_point": {
                        "type": "二买",
                        "signal_date": signal_date,
                        "signal_age_days": age_days,
                    },
                    "data_status": {
                        "daily": "verified",
                        "latest_date": "2026-08-28",
                        "source": "market_history_db",
                        "stale": False,
                        "is_final": True,
                    },
                })

                daily = candidate["daily_structure"]
                self.assertIsNone(daily["signal_date"])
                self.assertIsNone(daily["signal_age_days"])
                self.assertEqual(
                    daily["signal_freshness_status"],
                    expected_status,
                )
                self.assertIsNone(candidate["summary"]["signal_date"])

    def test_price_and_daily_modules_expose_real_structure_positions_with_sources(self):
        candidate = self._candidate({
            "pivot_zg": 20.5,
            "pivot_zd": 17.8,
            "pivots": {"ZG": 20.5, "ZD": 17.8, "count": 2},
            "platform_high": 21.2,
            "best_buy_point": {
                "type": "三买",
                "price": 18.6,
                "signal_date": "2026-08-28",
                "reason": "中枢上沿回踩",
            },
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
        })

        prices = candidate["price_evidence"]
        self.assertEqual(prices["pivot_zg"], 20.5)
        self.assertEqual(prices["pivot_zd"], 17.8)
        self.assertEqual(prices["platform_high"], 21.2)
        self.assertEqual(prices["buy_point_price"], 18.6)
        for field in ("pivot_zg", "pivot_zd", "platform_high", "buy_point_price"):
            self.assertTrue(prices[field + "_source"])

        daily = candidate["daily_structure"]
        self.assertEqual(daily["buy_point_price"], 18.6)
        self.assertEqual(daily["signal_reason"], "中枢上沿回踩")
        self.assertEqual(daily["pivots"]["count"], 2)

    def test_conflicting_pivot_is_hidden_from_price_and_chart_evidence(self):
        row = _workspace_row()
        serialized = _raw_candidate()
        serialized.update({"pivot_zg": 20.5, "pivot_zd": 17.8})
        formal = copy.deepcopy(serialized)
        formal["pivot_zg"] = 21.5
        daily = _workspace_daily([row], [serialized])

        candidate = build_recommendation_evidence_projection(
            {"picks_fusion": [formal]},
            daily,
        )["views"]["main"][0]

        prices = candidate["price_evidence"]
        pivots = candidate["display_derived"]["chart_evidence"]["pivots"]
        self.assertEqual(prices["audit_reasons"]["pivot_zg"], "conflict")
        self.assertIsNone(prices["pivot_zg"])
        self.assertEqual(pivots["status"], "conflict")
        self.assertNotIn("ZG", pivots["available"])
        self.assertIsNone(pivots["ZG"])
        self.assertNotIn("ZG", candidate["daily_structure"].get("pivots") or {})
        self.assertEqual(
            candidate["daily_structure"]["audit_reasons"]["pivot_zg"],
            "conflict",
        )

    def test_conflicting_daily_signal_sources_are_hidden_and_audited(self):
        row = _workspace_row()
        serialized = _raw_candidate()
        serialized["best_buy_point"] = {
            "type": "二买",
            "reason": "序列化理由",
            "signal_date": "2026-08-28",
        }
        formal = copy.deepcopy(serialized)
        formal["best_buy_point"] = {
            "type": "三买",
            "reason": "正式理由",
            "signal_date": "2026-08-28",
        }

        candidate = build_recommendation_evidence_projection(
            {"picks_fusion": [formal]},
            _workspace_daily([row], [serialized]),
        )["views"]["main"][0]

        daily = candidate["daily_structure"]
        self.assertIsNone(daily["signal"])
        self.assertIsNone(daily["summary"])
        self.assertEqual(daily["audit_reasons"]["signal"], "conflict")
        self.assertEqual(daily["audit_reasons"]["summary"], "conflict")
        self.assertEqual(daily["status"], "conflict")

    def test_complete_contract_prices_without_structure_positions_are_partial(self):
        candidate = self._candidate(
            raw_updates={
                "trailing_targets": [{"price": 22.5, "label": "目标1"}],
            },
            row_updates={
                "current_price": 20.1,
                "formal_decision_contract": {
                    "action": "可上车",
                    "reference_price": 19.5,
                    "pressure_price": 21.8,
                    "invalidation_price": 18.2,
                },
            },
        )

        prices = candidate["price_evidence"]
        self.assertEqual(prices["status"], "partial")
        self.assertEqual(
            prices["structure_missing_fields"],
            ["pivot_zg", "pivot_zd", "platform_high", "buy_point_price"],
        )

    def test_missing_ma5_guard_does_not_remove_a_supported_ma50_statement(self):
        candidate = self._candidate({
            "best_buy_point": {
                "type": "趋势延续候选",
                "reason": "MA50保持",
                "signal_date": "2026-08-28",
            },
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
            "ma50": 18.3,
        })

        daily = candidate["daily_structure"]
        self.assertEqual(daily["ma50"], 18.3)
        self.assertEqual(daily["summary"], "MA50保持")

    def test_daily_structure_rejects_non_positive_structure_prices(self):
        candidate = self._candidate({
            "pivot_zg": -1,
            "pivot_zd": 0,
            "pivots": {"ZG": -1, "ZD": 0, "count": 1},
            "best_buy_point": {
                "type": "二买",
                "price": -3,
                "signal_date": "2026-08-28",
            },
        })

        daily = candidate["daily_structure"]
        self.assertIsNone(daily["buy_point_price"])
        self.assertNotIn("ZG", daily.get("pivots") or {})
        self.assertNotIn("ZD", daily.get("pivots") or {})
        self.assertIn("买点价格未提供", daily["missing_evidence"])

    def test_daily_structure_rejects_non_positive_ma_prices(self):
        candidate = self._candidate({
            "ma5": -1,
            "ma10": 0,
            "best_buy_point": {
                "type": "二买",
                "signal_date": "2026-08-28",
            },
        })

        daily = candidate["daily_structure"]
        self.assertIsNone(daily["ma5"])
        self.assertIsNone(daily["ma10"])
        self.assertEqual(daily["audit_reasons"]["ma5"], "invalid")
        self.assertEqual(daily["audit_reasons"]["ma10"], "invalid")

    def test_30m_module_declares_every_requested_fact_or_explicit_missing(self):
        candidate = self._candidate({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "available",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "bars": 32,
                "is_final": True,
                "stale": False,
            },
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "ema_bullish_alignment": True,
                "close_above_ema5": True,
                "ema5_rising_bars": 2,
                "macd_hist_direction": "improving",
                "buy_point": "二买",
            },
        })

        sublevel = candidate["sublevel_30m"]
        for field in (
            "ema5", "ema10", "close", "macd_dif", "macd_dea",
            "breakout_holds", "pullback_volume_state",
        ):
            self.assertIn(field, sublevel)
        self.assertIn("EMA5 当前值未提供", sublevel["missing_evidence"])
        self.assertIn("EMA10 当前值未提供", sublevel["missing_evidence"])
        self.assertEqual(sublevel["latest_bar_at"], "2026-08-28 14:30:00")
        self.assertEqual(sublevel["bars"], 32)

    def test_verified_final_30m_result_projects_only_scalars_and_real_classifier_signals(self):
        result = _Verified30mResult()
        formal = _raw_candidate()
        formal.update({
            "result_30min": result,
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "verified",
                "source": "market_history_db",
                "latest_date": "2026-08-28",
                "latest_ts": result.dates[-1],
                "bars": len(result.dates),
                "stale": False,
                "is_final": True,
            },
            "signal_tier": "candidate",
            "best_buy_point": {
                "type": "底背驰候选",
                "tier": "candidate",
                "strength": "中",
                "confirmations": ["30min底分型", "关键位不破"],
                "confirmed_by": "30分钟底分型+关键位不破",
            },
            "upgraded_candidates": [{
                "type": "底背驰候选",
                "tier": "candidate",
                "strength": "中",
                "confirmations": ["30min底分型", "关键位不破"],
                "confirmed_by": "30分钟底分型+关键位不破",
            }],
        })

        candidate = build_recommendation_evidence_projection(
            {"picks_fusion": [formal]},
            _workspace_daily([_workspace_row()], [_raw_candidate()]),
        )["views"]["main"][0]
        sublevel = candidate["sublevel_30m"]

        self.assertEqual(sublevel["status"], "available")
        self.assertEqual(sublevel["confirmation_status"], "confirmed")
        self.assertTrue(sublevel["confirmed"])
        self.assertEqual(sublevel["latest_ts"], result.dates[-1])
        self.assertEqual(sublevel["bars"], len(result.dates))
        self.assertAlmostEqual(sublevel["close"], result.closes[-1])
        self.assertGreater(sublevel["close"], sublevel["ema5"])
        self.assertGreater(sublevel["ema5"], sublevel["ema10"])
        self.assertAlmostEqual(sublevel["macd_dif"], result.macd_dif[-1])
        self.assertAlmostEqual(sublevel["macd_dea"], result.macd_dea[-1])
        self.assertEqual(sublevel["macd_state"], "improving")
        self.assertEqual(sublevel["ema5_direction"], "上行")
        self.assertEqual(sublevel["ema10_direction"], "上行")
        self.assertEqual(
            sublevel["confirmations"],
            ["30min底分型", "关键位不破"],
        )
        self.assertEqual(
            sublevel["confirmed_by"],
            "30分钟底分型+关键位不破",
        )
        for forbidden_array in (
            "dates", "closes", "macd_dif_series", "macd_dea_series", "macd_hist",
        ):
            self.assertNotIn(forbidden_array, sublevel)

    def test_30m_serializer_never_promotes_alignment_or_arbitrary_candidate_confirmations(self):
        for name, confirmations in (
            ("ema_alignment_only", ["30min EMA5维持"]),
            ("arbitrary_text", ["任意未审计确认"]),
        ):
            with self.subTest(name=name):
                result = _Verified30mResult()
                formal = _raw_candidate()
                formal.update({
                    "result_30min": result,
                    "strategy_input_evidence": {
                        "interval": "30m",
                        "status": "verified",
                        "source": "market_history_db",
                        "latest_date": "2026-08-28",
                        "latest_ts": result.dates[-1],
                        "bars": len(result.dates),
                        "stale": False,
                        "is_final": True,
                    },
                    "signal_tier": "candidate",
                    "best_buy_point": {
                        "type": "底背驰候选",
                        "tier": "candidate",
                        "strength": "中",
                        "confirmations": confirmations,
                        "confirmed_by": "+".join(confirmations),
                    },
                    "upgraded_candidates": [{
                        "type": "底背驰候选",
                        "tier": "candidate",
                        "strength": "中",
                        "confirmations": confirmations,
                        "confirmed_by": "+".join(confirmations),
                    }],
                })

                sublevel = build_recommendation_evidence_projection(
                    {"picks_fusion": [formal]},
                    _workspace_daily([_workspace_row()], [_raw_candidate()]),
                )["views"]["main"][0]["sublevel_30m"]

                self.assertEqual(sublevel["status"], "partial")
                self.assertEqual(sublevel["confirmation_status"], "alignment_only")
                self.assertFalse(sublevel["confirmed"])
                self.assertEqual(sublevel["confirmations"], [])
                self.assertIsNone(sublevel["confirmed_by"])
                self.assertEqual(sublevel["ema_alignment"], "EMA5 > EMA10")
                self.assertGreater(sublevel["ema5"], sublevel["ema10"])
                self.assertNotIn("任意未审计确认", sublevel["confirmations"])

    def test_30m_scalar_projection_fails_closed_on_unverified_input_contract(self):
        cases = {
            "bar_count_mismatch": {"bars_delta": 1},
            "latest_timestamp_mismatch": {"latest_ts": "2026-08-28 15:00:00"},
            "not_final": {"is_final": False},
            "stale": {"stale": True},
        }
        for name, changes in cases.items():
            with self.subTest(name=name):
                result = _Verified30mResult()
                evidence = {
                    "interval": "30m",
                    "status": "verified",
                    "source": "market_history_db",
                    "latest_date": "2026-08-28",
                    "latest_ts": result.dates[-1],
                    "bars": len(result.dates),
                    "stale": False,
                    "is_final": True,
                }
                if "bars_delta" in changes:
                    evidence["bars"] += changes["bars_delta"]
                else:
                    evidence.update(changes)
                formal = _raw_candidate()
                formal.update({
                    "result_30min": result,
                    "strategy_input_evidence": evidence,
                    "signal_tier": "candidate",
                    "best_buy_point": {
                        "type": "底背驰候选",
                        "tier": "candidate",
                        "confirmations": ["30min底分型"],
                        "confirmed_by": "30分钟底分型",
                    },
                })

                sublevel = build_recommendation_evidence_projection(
                    {"picks_fusion": [formal]},
                    _workspace_daily([_workspace_row()], [_raw_candidate()]),
                )["views"]["main"][0]["sublevel_30m"]

                self.assertNotEqual(sublevel["status"], "available")
                self.assertFalse(sublevel["confirmed"])
                self.assertIsNone(sublevel["ema5"])
                self.assertIsNone(sublevel["macd_dif"])
                self.assertEqual(sublevel["confirmations"], [])

    def test_missing_30m_does_not_publish_legacy_confirmation_claims(self):
        candidate = self._candidate({
            "best_buy_point": {
                "type": "趋势延续候选",
                "confirmed_by": "30min突破位不破+30min EMA5维持",
                "confirmations": ["30min突破位不破", "30min EMA5维持"],
                "signal_date": "2026-08-28",
            },
        })

        sublevel = candidate["sublevel_30m"]
        self.assertEqual(sublevel["status"], "missing")
        self.assertEqual(sublevel["confirmations"], [])
        self.assertIsNone(sublevel["confirmed_by"])

    def test_non_final_30m_hides_legacy_confirmation_grade_and_date(self):
        candidate = self._candidate({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "available",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "stale": False,
                "is_final": False,
            },
            "sublevel_confirm_grade": "S",
            "sublevel_confirm_label": "S级确认",
            "confirm_date": "2026-08-28",
            "confirm_age_days": 0,
            "confirmation_evidence": {"buy_point": "二买"},
        })

        sublevel = candidate["sublevel_30m"]
        self.assertEqual(sublevel["confirmation_status"], "unavailable")
        self.assertIsNone(sublevel["grade"])
        self.assertIsNone(sublevel["label"])
        self.assertIsNone(sublevel["confirm_date"])
        self.assertIsNone(sublevel["confirm_age_days"])

    def test_30m_confirmation_requires_explicit_sufficient_bars(self):
        for sufficient_bars in (None, False):
            with self.subTest(sufficient_bars=sufficient_bars):
                confirmation = {
                    "schema_version": 1,
                    "buy_point": "二买",
                    "fresh_yang_pattern": "two_yang_one_yin",
                }
                if sufficient_bars is not None:
                    confirmation["sufficient_bars"] = sufficient_bars
                candidate = self._candidate({
                    "strategy_input_evidence": {
                        "interval": "30m",
                        "status": "available",
                        "latest_date": "2026-08-28",
                        "latest_ts": "2026-08-28 14:30:00",
                        "is_final": True,
                        "stale": False,
                    },
                    "confirmation_evidence": confirmation,
                })

                sublevel = candidate["sublevel_30m"]
                self.assertFalse(sublevel["confirmed"])
                self.assertNotEqual(sublevel["status"], "available")
                self.assertIn(
                    "30分钟确认样本数量不足或未声明",
                    sublevel["missing_evidence"],
                )

    def test_30m_confirmation_requires_explicit_not_stale_state(self):
        candidate = self._candidate({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "available",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "is_final": True,
            },
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "buy_point": "二买",
            },
            "confirm_date": "2026-08-28",
            "confirm_age_days": 0,
        })

        sublevel = candidate["sublevel_30m"]
        self.assertIsNone(sublevel["stale"])
        self.assertFalse(sublevel["confirmed"])
        self.assertIn("30分钟陈旧状态未声明", sublevel["missing_evidence"])

    def test_30m_confirmation_requires_supported_schema_version(self):
        for schema_version in (None, 999):
            with self.subTest(schema_version=schema_version):
                confirmation = {
                    "sufficient_bars": True,
                    "buy_point": "二买",
                }
                if schema_version is not None:
                    confirmation["schema_version"] = schema_version
                candidate = self._candidate({
                    "strategy_input_evidence": {
                        "interval": "30m",
                        "status": "available",
                        "latest_date": "2026-08-28",
                        "latest_ts": "2026-08-28 14:30:00",
                        "is_final": True,
                        "stale": False,
                    },
                    "confirmation_evidence": confirmation,
                })

                sublevel = candidate["sublevel_30m"]
                self.assertFalse(sublevel["confirmed"])
                self.assertEqual(sublevel["confirmation_schema_status"], "invalid")

    def test_30m_prices_and_alignment_are_conflict_checked(self):
        candidate = self._candidate({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "available",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "is_final": True,
                "stale": False,
            },
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "buy_point": "二买",
                "ema5": -1,
                "ema10": 10,
                "close": 0,
                "ema_bullish_alignment": True,
            },
        })

        sublevel = candidate["sublevel_30m"]
        self.assertIsNone(sublevel["ema5"])
        self.assertIsNone(sublevel["close"])
        self.assertFalse(sublevel["confirmed"])
        self.assertEqual(sublevel["confirmation_status"], "conflict")

    def test_30m_raw_and_formal_source_conflicts_fail_closed(self):
        row = _workspace_row()
        serialized = _raw_candidate()
        serialized.update({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "available",
                "latest_date": "2026-08-28",
                "latest_ts": "2026-08-28 14:30:00",
                "is_final": True,
                "stale": False,
            },
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "buy_point": "二买",
            },
            "confirm_date": "2026-08-28",
            "confirm_age_days": 0,
        })
        formal = copy.deepcopy(serialized)
        formal["strategy_input_evidence"]["latest_date"] = "2026-08-27"
        formal["confirmation_evidence"]["buy_point"] = "三买"

        sublevel = build_recommendation_evidence_projection(
            {"picks_fusion": [formal]},
            _workspace_daily([row], [serialized]),
        )["views"]["main"][0]["sublevel_30m"]

        self.assertEqual(sublevel["status"], "conflict")
        self.assertFalse(sublevel["confirmed"])
        self.assertTrue(sublevel["source_conflicts"])

    def test_30m_confirmation_date_must_be_current_and_valid(self):
        for confirm_date in ("garbage", "2026-08-29", "2026-08-21"):
            with self.subTest(confirm_date=confirm_date):
                candidate = self._candidate({
                    "strategy_input_evidence": {
                        "interval": "30m",
                        "status": "available",
                        "latest_date": "2026-08-28",
                        "latest_ts": "2026-08-28 14:30:00",
                        "is_final": True,
                        "stale": False,
                    },
                    "confirmation_evidence": {
                        "schema_version": 1,
                        "sufficient_bars": True,
                        "buy_point": "二买",
                    },
                    "confirm_date": confirm_date,
                    "confirm_age_days": 0,
                })

                sublevel = candidate["sublevel_30m"]
                self.assertFalse(sublevel["confirmed"])
                self.assertNotEqual(sublevel["status"], "available")
                self.assertIsNone(sublevel["confirm_date"])
                self.assertEqual(
                    sublevel["confirmation_date_status"],
                    "invalid" if confirm_date == "garbage" else "mismatch",
                )

    def test_stale_30m_never_reuses_historical_technical_fields(self):
        candidate = self._candidate({
            "strategy_input_evidence": {
                "interval": "30m",
                "status": "stale",
                "latest_date": "2026-08-21",
                "latest_ts": "2026-08-21 14:30:00",
                "is_final": True,
                "stale": True,
            },
            "confirmation_evidence": {
                "schema_version": 1,
                "sufficient_bars": True,
                "buy_point": "二买",
                "fresh_yang_pattern": "two_yang_one_yin",
                "ema5": 12,
                "ema10": 11,
                "close": 13,
                "macd_hist_direction": "improving",
            },
            "confirm_date": "2026-08-21",
        })

        sublevel = candidate["sublevel_30m"]
        self.assertEqual(sublevel["status"], "stale")
        for field in (
            "buy_point", "fresh_yang_pattern", "ema5", "ema10",
            "close", "macd_state",
        ):
            self.assertIsNone(sublevel[field], field)

    def test_capital_sector_and_risk_missing_fields_are_never_silently_omitted(self):
        candidate = self._candidate()
        volume = candidate["volume_and_capital"]
        market = candidate["market_and_sector"]
        risk = candidate["risk_and_next"]

        for field in (
            "turnover_rate", "volume_labels", "stock_net_flow",
            "stock_net_inflow_days", "capital_alignment_state",
            "missing_evidence",
        ):
            self.assertIn(field, volume)
        for field in (
            "sector_change_pct", "sector_up_count", "sector_total_count",
            "sector_limit_up_count", "sector_market_rank",
            "stock_relative_strength", "market_state", "stock_state",
            "missing_evidence",
        ):
            self.assertIn(field, market)
        self.assertIn("as_of", risk)
        self.assertIn("missing_evidence", risk)

    def test_current_amount_uses_only_current_final_date_aligned_daily_series(self):
        formal = _raw_candidate()
        formal.update({
            "dates": ["2026-08-26", "2026-08-27", "2026-08-28"],
            "amount": 999_000_000,
            "amounts": [120_000_000, 180_000_000, 250_000_000],
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
        })

        volume = build_recommendation_evidence_projection(
            {"picks_fusion": [formal]},
            _workspace_daily([_workspace_row()], [_raw_candidate()]),
        )["views"]["main"][0]["volume_and_capital"]

        self.assertEqual(volume.get("current_amount"), 250_000_000)
        self.assertEqual(volume.get("current_amount_text"), "2.5亿")
        self.assertEqual(volume.get("current_amount_as_of"), "2026-08-28")
        self.assertEqual(volume.get("current_amount_source"), "daily_kline.amounts")
        self.assertEqual(volume.get("current_amount_status"), "available")

    def test_current_amount_never_falls_back_to_quote_when_series_contract_is_invalid(self):
        cases = {
            "length_mismatch": {
                "dates": ["2026-08-27", "2026-08-28"],
                "amounts": [120_000_000],
            },
            "date_mismatch": {
                "dates": ["2026-08-26", "2026-08-27"],
                "amounts": [120_000_000, 180_000_000],
            },
            "not_final": {"is_final": False},
            "stale": {"stale": True},
        }
        for name, changes in cases.items():
            with self.subTest(name=name):
                formal = _raw_candidate()
                formal.update({
                    "dates": ["2026-08-27", "2026-08-28"],
                    "amount": 999_000_000,
                    "amounts": [120_000_000, 180_000_000],
                    "data_status": {
                        "daily": "verified",
                        "latest_date": "2026-08-28",
                        "source": "market_history_db",
                        "stale": False,
                        "is_final": True,
                    },
                })
                if "dates" in changes:
                    formal["dates"] = changes["dates"]
                if "amounts" in changes:
                    formal["amounts"] = changes["amounts"]
                if "is_final" in changes:
                    formal["data_status"]["is_final"] = changes["is_final"]
                if "stale" in changes:
                    formal["data_status"]["stale"] = changes["stale"]

                volume = build_recommendation_evidence_projection(
                    {"picks_fusion": [formal]},
                    _workspace_daily([_workspace_row()], [_raw_candidate()]),
                )["views"]["main"][0]["volume_and_capital"]

                self.assertIsNone(volume.get("current_amount"))
                self.assertIsNone(volume.get("current_amount_text"))
                self.assertIsNone(volume.get("current_amount_source"))
                self.assertEqual(volume.get("current_amount_status"), "missing")

    def test_distance_state_only_maps_exact_existing_formal_risk_labels(self):
        for label in ("距参考价偏高", "距参考价过远", "距参考位过远"):
            with self.subTest(label=label):
                candidate = self._candidate(
                    row_updates={
                        "current_price": 10,
                        "risk_flags": [label],
                        "formal_decision_contract": {
                            "action": "观察",
                            "reference_price": 9,
                        },
                    },
                )
                derived = candidate["display_derived"]
                self.assertEqual(derived.get("distance_state"), "偏离")
                self.assertEqual(
                    derived.get("distance_state_source"),
                    "risk_and_next.risk_labels",
                )

        candidate = self._candidate(
            row_updates={
                "current_price": 10,
                "risk_flags": ["距参考价适中"],
                "formal_decision_contract": {
                    "action": "观察",
                    "reference_price": 9,
                },
            },
        )
        self.assertIsNone(candidate["display_derived"].get("distance_state"))
        self.assertIsNone(
            candidate["display_derived"].get("distance_state_source")
        )

    def test_three_layer_states_do_not_relabel_market_or_sector_labels(self):
        candidate = self._candidate(
            raw_updates={"sector_strength_label": "资金流入TOP15"},
            daily_updates={
                "market_sentiment": {
                    "version": "v2",
                    "date": "2026-08-28",
                    "score": 62,
                    "label": "偏强",
                    "coverage": 1,
                    "insufficient": False,
                    "components": {
                        key: 62 for key in (
                            "breadth", "limit_ecology", "index",
                            "turnover", "trend",
                        )
                    },
                    "evidence": {
                        key: {"available": True} for key in (
                            "breadth", "limit_ecology", "index",
                            "turnover", "trend",
                        )
                    },
                },
            },
        )

        market = candidate["market_and_sector"]
        self.assertEqual(market["market_label"], "偏强")
        self.assertEqual(market["market_state"], "未知")
        self.assertEqual(market["stock_state"], "未知")
        self.assertIsNone(market["stock_relative_strength"])
        self.assertIn(
            market["sector_layer_state"],
            {"支持", "分歧", "风险", "未知"},
        )

    def test_verified_sector_without_direction_facts_remains_unknown(self):
        candidate = self._candidate(
            daily_updates={
                "sector_heat": {
                    "date": "2026-08-28",
                    "status": "verified_complete",
                    "source": "formal-sector",
                    "items": [{
                        "sector_name": "半导体",
                        "status": "verified_complete",
                        "source": "formal-sector",
                    }],
                },
            },
        )

        market = candidate["market_and_sector"]
        sector = market["sector_evidence"]
        self.assertEqual(sector["direction"], "unknown")
        self.assertEqual(market["sector_layer_state"], "未知")
        self.assertEqual(sector["display_completeness"], "missing")

    def test_sector_item_without_own_date_and_source_is_not_available(self):
        candidate = self._candidate(
            daily_updates={
                "sector_heat": {
                    "date": "2026-08-28",
                    "status": "verified_complete",
                    "source": "formal-sector",
                    "items": [{
                        "sector_name": "半导体",
                        "status": "verified_complete",
                        "component_coverage": 1,
                        "hierarchy_dedup_status": "checked_unique",
                        "net_flow": 1000000,
                        "change_pct": 1.2,
                    }],
                },
            },
        )

        sector = candidate["market_and_sector"]["sector_evidence"]
        self.assertEqual(sector["status"], "missing")
        self.assertEqual(sector["direction"], "unknown")

    def test_stock_relative_strength_requires_current_verified_provenance(self):
        hidden = self._candidate({
            "stock_relative_strength": "板块内前10%",
            "stock_direction_state": "支持",
        })["market_and_sector"]
        self.assertIsNone(hidden["stock_relative_strength"])
        self.assertEqual(hidden["stock_state"], "未知")

        available = self._candidate({
            "stock_relative_evidence": {
                "status": "verified_complete",
                "source": "formal-sector-ranking",
                "as_of": "2026-08-28",
                "relative_strength": "板块内前10%",
                "direction_state": "支持",
            },
        })["market_and_sector"]
        self.assertEqual(available["stock_relative_strength"], "板块内前10%")
        self.assertEqual(available["stock_state"], "支持")
        self.assertEqual(
            available["stock_relative_source"],
            "formal-sector-ranking",
        )

    def test_unverified_event_risks_are_never_published(self):
        candidate = self._candidate({
            "event_risks": ["未经核实的公告风险"],
        })

        risk = candidate["risk_and_next"]
        self.assertEqual(risk["event_risks"], [])
        self.assertIn("公告或事件风险缺少正式验证", risk["missing_evidence"])

    def test_verified_current_event_risks_are_published(self):
        candidate = self._candidate({
            "event_risk_evidence": {
                "status": "verified_complete",
                "source": "formal_daily_report",
                "as_of": "2026-08-28",
                "items": ["限售股解禁风险"],
            },
        })

        risk = candidate["risk_and_next"]
        self.assertEqual(risk["event_risks"], ["限售股解禁风险"])
        self.assertEqual(risk["event_risk_status"], "available")

    def test_conflicting_verified_event_risk_contracts_are_hidden(self):
        candidate = self._candidate({
            "event_risk_evidence": {
                "status": "verified_complete",
                "source": "formal_daily_report",
                "as_of": "2026-08-28",
                "items": ["解禁风险"],
            },
            "announcement_risk_evidence": {
                "status": "verified_complete",
                "source": "formal_daily_report",
                "as_of": "2026-08-28",
                "items": ["监管问询风险"],
            },
        })

        risk = candidate["risk_and_next"]
        self.assertEqual(risk["event_risk_status"], "conflict")
        self.assertEqual(risk["event_risks"], [])

    def test_missing_report_date_fails_closed_for_dated_evidence(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw.update({
            "data_status": {
                "daily": "verified",
                "latest_date": "2099-01-01",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
            "volume_summary": {
                "status": "verified_complete",
                "as_of": "2099-01-01",
                "volume": 100,
            },
        })
        daily = _workspace_daily([row], [raw])
        daily.pop("date")

        candidate = build_recommendation_evidence_projection(
            {},
            daily,
        )["views"]["main"][0]

        self.assertNotEqual(candidate["daily_structure"]["status"], "available")
        self.assertNotEqual(candidate["volume_and_capital"]["status"], "available")

    def test_capital_alignment_never_compares_missing_net_flow_values(self):
        candidate = self._candidate({
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
            "stock_capital_flow": {
                "status": "verified_complete",
                "source": "licensed-stock-flow",
                "as_of": "2026-08-28",
                "consecutive_inflow_days": 3,
            },
            "sector_flow_status": "verified_complete",
            "sector_flow_source": "licensed-sector-flow",
            "sector_flow_as_of": "2026-08-28",
            "sector_rank": 2,
            "sector_strength_label": "资金排名可验证",
        })

        volume = candidate["volume_and_capital"]
        self.assertEqual(volume["stock_capital_flow"]["status"], "available")
        self.assertEqual(volume["sector_capital_flow"]["status"], "available")
        self.assertEqual(
            volume["capital_alignment_state"],
            "资金方向不可判定",
        )

    def test_stock_capital_flow_rejects_conflicting_declared_dates(self):
        candidate = self._candidate({
            "stock_capital_flow": {
                "status": "verified_complete",
                "source": "licensed-stock-flow",
                "as_of": "2026-08-28",
                "date": "2026-08-29",
                "net_flow": 1200000,
            },
        })

        stock_flow = candidate["volume_and_capital"]["stock_capital_flow"]
        self.assertEqual(stock_flow["status"], "missing")
        self.assertIsNone(stock_flow["net_flow"])

    def test_pool_quality_and_buy_point_ratios_require_their_own_dates(self):
        candidate = self._candidate(
            raw_updates={
                "data_status": {
                    "daily": "verified",
                    "latest_date": "2026-08-28",
                    "source": "market_history_db",
                    "stale": False,
                    "is_final": True,
                },
                "best_buy_point": {"type": "二买", "volume_ratio": 2.0},
            },
            row_updates={
                "pool_quality": {
                    "quality_evidence_eligible": True,
                    "money20": 1230000,
                    "volume_ratio20": 1.8,
                    "liquidity_source": "daily amount",
                },
            },
        )

        volume = candidate["volume_and_capital"]
        self.assertEqual(volume["turnover"]["status"], "missing")
        self.assertIsNone(volume["volume_ratio"])

    def test_duplicate_serialized_code_is_explicitly_ambiguous(self):
        row = _workspace_row()
        old = _raw_candidate()
        old["data_status"] = {
            "daily": "verified",
            "latest_date": "2026-08-21",
            "stale": True,
            "is_final": True,
        }
        current = copy.deepcopy(old)
        current["data_status"] = {
            "daily": "verified",
            "latest_date": "2026-08-28",
            "stale": False,
            "is_final": True,
        }

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [old, current]),
        )["views"]["main"][0]

        self.assertEqual(candidate["source_identity"]["status"], "conflict")
        self.assertEqual(candidate["summary"]["status"], "conflict")
        self.assertNotEqual(candidate["daily_structure"]["status"], "available")


if __name__ == "__main__":
    unittest.main()
