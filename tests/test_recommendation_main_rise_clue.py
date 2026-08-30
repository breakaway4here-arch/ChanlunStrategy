"""RED contracts for the read-only main-rise clue evidence surface.

The clue is a translation of signals that already exist in the daily
candidate payload.  It is not a second strategy and must not become a formal
action.  These tests intentionally describe the evidence contract before the
projection is implemented.
"""

import copy
import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)
from tests.test_recommendation_evidence import (
    _raw_candidate,
    _workspace_row,
)


REPORT_DATE = "2026-08-28"


def _daily_with_candidate(row, raw, view="main", pool="picks_fusion"):
    """Build the smallest workspace/daily payload for one evidence row."""
    return {
        "date": REPORT_DATE,
        "workspace": {
            "view_order": [view],
            "views": {view: [row]},
        },
        pool: [raw],
    }


def _candidate(
    *,
    bp=None,
    view="main",
    pool="picks_fusion",
    row_updates=None,
    raw_updates=None,
):
    row = copy.deepcopy(_workspace_row())
    row["ref"] = {"pool": pool, "code": row["code"]}
    row["view"] = view
    row_updates = row_updates or {}
    row.update(copy.deepcopy(row_updates))

    raw = copy.deepcopy(_raw_candidate(row["code"]))
    raw["data_status"] = {
        "daily": "verified",
        "latest_date": REPORT_DATE,
        "source": "market_history_db",
        "stale": False,
        "is_final": True,
    }
    if bp is not None:
        raw["best_buy_point"] = copy.deepcopy(bp)
    raw["view"] = view
    raw_updates = raw_updates or {}
    raw.update(copy.deepcopy(raw_updates))

    projection = build_recommendation_evidence_projection(
        {},
        _daily_with_candidate(row, raw, view=view, pool=pool),
    )
    return projection["views"][view][0]


def _evidence_text(items):
    """Allow evidence entries to be strings or structured dicts."""
    return " ".join(str(item) for item in (items or []))


def _main_rise_clue(test_case, candidate):
    """Turn an unimplemented section into a normal RED assertion."""
    clue = candidate.get("main_rise_clue")
    test_case.assertIsInstance(
        clue,
        dict,
        "main_rise_clue projection is not implemented",
    )
    return clue


class RecommendationMainRiseClueTests(unittest.TestCase):

    def test_strong_startup_maps_to_startup_confirmation_clue(self):
        candidate = _candidate(
            bp={
                "type": "强势启动候选",
                "source_type": "日线强势启动",
                "daily_startup_grade": "strong",
                "daily_startup_label": "强启动",
                "startup_reason": "低位放量并站上MA5/MA10",
                "startup_signals": ["close_above_ma5", "break_20d_high"],
                "signal_date": REPORT_DATE,
                "signal_age_days": 0,
            },
        )

        clue = _main_rise_clue(self, candidate)

        self.assertEqual(clue["status"], "available")
        self.assertEqual(clue["clue_type"], "startup_confirmation")
        self.assertEqual(clue["label"], "启动确认线索")
        self.assertTrue(clue["supporting_evidence"])
        self.assertIn("强势启动候选", _evidence_text(clue["supporting_evidence"]))
        self.assertEqual(clue["opposing_evidence"], [])

    def test_trend_continuation_maps_to_trend_continuation_clue(self):
        candidate = _candidate(
            bp={
                "type": "趋势延续候选",
                "source_type": "日线趋势延续",
                "reason": "20日平台突破；MA5/MA10保持",
                "confirmations": ["30min突破位不破", "30min EMA5维持"],
                "signal_date": REPORT_DATE,
                "signal_age_days": 0,
            },
            raw_updates={
                "source_channel": "trend_continuation",
            },
        )

        clue = _main_rise_clue(self, candidate)

        self.assertEqual(clue["status"], "available")
        self.assertEqual(clue["clue_type"], "trend_continuation")
        self.assertEqual(clue["label"], "趋势延续线索")
        self.assertIn("趋势延续候选", _evidence_text(clue["supporting_evidence"]))
        self.assertIn("日线趋势延续", _evidence_text(clue["supporting_evidence"]))

    def test_missing_or_stale_30m_cannot_leak_confirmation_into_main_rise_support(self):
        cases = (
            ("missing", {}),
            (
                "stale",
                {
                    "strategy_input_evidence": {
                        "interval": "30m",
                        "status": "stale",
                        "latest_date": "2026-08-21",
                        "latest_ts": "2026-08-21 15:00:00",
                        "stale": True,
                        "is_final": True,
                    },
                },
            ),
        )
        for expected_status, input_updates in cases:
            with self.subTest(expected_status=expected_status):
                raw_updates = {"source_channel": "trend_continuation"}
                raw_updates.update(input_updates)
                candidate = _candidate(
                    bp={
                        "type": "趋势延续候选",
                        "source_type": "日线趋势延续",
                        "reason": "20日平台突破",
                        "confirmations": [
                            "30min突破位不破",
                            "30min EMA5维持",
                            "30分钟缩量回踩",
                        ],
                        "signal_date": REPORT_DATE,
                        "signal_age_days": 0,
                    },
                    raw_updates=raw_updates,
                )

                self.assertEqual(
                    candidate["sublevel_30m"]["status"],
                    expected_status,
                )
                supporting = _evidence_text(
                    candidate["main_rise_clue"]["supporting_evidence"]
                )
                self.assertIn("趋势延续候选", supporting)
                for forbidden in ("30min", "30m", "30分钟", "EMA"):
                    self.assertNotIn(
                        forbidden.lower(),
                        supporting.lower(),
                        "缺失或陈旧的30分钟证据泄漏进主升浪支持项: " + supporting,
                    )

    def test_stale_daily_evidence_cannot_publish_a_main_rise_clue(self):
        candidate = _candidate(
            bp={
                "type": "趋势延续候选",
                "source_type": "日线趋势延续",
                "reason": "旧日线突破",
                "signal_date": "2026-08-21",
                "signal_age_days": 5,
            },
            raw_updates={
                "data_status": {
                    "daily": "verified",
                    "latest_date": "2026-08-21",
                    "source": "market_history_db",
                    "stale": True,
                    "is_final": True,
                },
            },
        )

        daily = candidate["daily_structure"]
        clue = candidate["main_rise_clue"]
        self.assertEqual(daily["status"], "stale")
        self.assertEqual(clue["status"], "missing")
        self.assertEqual(clue["supporting_evidence"], [])
        self.assertTrue(any("日线证据陈旧" in item for item in clue["evidence_guards"]))

    def test_missing_30m_filters_identity_fields_before_building_clue(self):
        candidate = _candidate(
            bp={
                "type": "候选",
                "source_type": "30min趋势延续",
                "reason": "日线突破",
                "signal_date": REPORT_DATE,
            },
            raw_updates={"source_channel": "30min_confirmation"},
        )

        clue = candidate["main_rise_clue"]
        supporting = _evidence_text(clue["supporting_evidence"])
        self.assertEqual(candidate["sublevel_30m"]["status"], "missing")
        self.assertEqual(clue["status"], "missing")
        self.assertEqual(clue["clue_type"], "none")
        self.assertNotIn("30min", supporting.lower())

    def test_acceleration_pool_maps_to_acceleration_clue(self):
        candidate = _candidate(
            bp={
                "type": "强势启动候选",
                "source_type": "日线强势启动",
                "reason": "融合强势启动",
                "signal_date": REPORT_DATE,
                "signal_age_days": 0,
            },
            view="acceleration",
            pool="next_day_boom",
            row_updates={
                "sources": ["acceleration"],
                "source_labels": ["加速"],
            },
            raw_updates={
                "source_pool": "fusion",
                "source_type": "强势启动候选",
                "boom_score": 78,
                "boom_reason": "融合强势启动；量比甜区1.3-1.6",
                "next_day_reason": "量比甜区",
            },
        )

        clue = _main_rise_clue(self, candidate)

        self.assertEqual(clue["status"], "available")
        self.assertEqual(clue["clue_type"], "acceleration")
        self.assertEqual(clue["label"], "加速线索")
        supporting = _evidence_text(clue["supporting_evidence"])
        self.assertTrue(
            "加速" in supporting
            or "next_day_boom" in supporting
            or "boom" in supporting,
        )

    def test_distance_and_heat_are_opposing_evidence_not_support(self):
        candidate = _candidate(
            bp={
                "type": "强势启动候选",
                "source_type": "日线强势启动",
                "startup_reason": "放量突破",
                "signal_date": REPORT_DATE,
            },
            row_updates={
                "risk_flags": ["距参考价过远", "涨幅过热"],
                "distance_from_reference_pct": 8.6,
            },
            raw_updates={
                "change_pct": 9.8,
                "distance_from_reference_pct": 8.6,
                "risk_flags": ["距参考价过远", "涨幅过热"],
            },
        )

        clue = _main_rise_clue(self, candidate)
        supporting = _evidence_text(clue["supporting_evidence"])
        opposing = _evidence_text(clue["opposing_evidence"])

        self.assertIn("强势启动候选", supporting)
        self.assertTrue(opposing)
        self.assertIn("加速过热风险", opposing)
        self.assertIn("距参考价过远", opposing)
        self.assertIn("涨幅过热", opposing)
        self.assertNotIn("加速过热风险", supporting)

    def test_structure_break_invalidates_clue_but_preserves_both_evidence_sides(self):
        candidate = _candidate(
            bp={
                "type": "趋势延续候选",
                "source_type": "日线趋势延续",
                "reason": "平台突破后延续",
                "signal_date": REPORT_DATE,
            },
            row_updates={
                "risk_flags": ["结构破坏"],
            },
            raw_updates={
                "gf_dma_health": {
                    "label": "结构破坏",
                    "trend_stage": "broken",
                    "alignment": "broken",
                },
                "failure_gate": "trend_structure",
                "reason_code": "structure_break",
            },
        )

        clue = _main_rise_clue(self, candidate)
        supporting = _evidence_text(clue["supporting_evidence"])
        opposing = _evidence_text(clue["opposing_evidence"])

        self.assertEqual(clue["status"], "invalidated")
        self.assertEqual(clue["clue_type"], "invalidated")
        self.assertEqual(clue["label"], "主升线索失效")
        self.assertIn("趋势延续候选", supporting)
        self.assertIn("结构破坏", opposing)

    def test_no_existing_signal_renders_empty_clue_without_action(self):
        candidate = _candidate(
            row_updates={
                "risk_flags": [],
                "primary_reason": "仅有评分，不代表主升信号",
            },
            raw_updates={
                "decision_engine_v1": {
                    "decision_code": "observe",
                    "total_score": 72,
                    "sentiment": {"reasons": ["主升周期"]},
                },
            },
        )

        clue = _main_rise_clue(self, candidate)

        self.assertEqual(clue["status"], "missing")
        self.assertEqual(clue["clue_type"], "none")
        self.assertEqual(clue["label"], "尚未形成主升浪线索")
        self.assertEqual(clue["supporting_evidence"], [])
        self.assertEqual(clue["opposing_evidence"], [])
        self.assertEqual(clue["reason"], "main_rise_clue_not_provided")

    def test_main_rise_clue_never_overrides_formal_action(self):
        candidate = _candidate(
            bp={
                "type": "强势启动候选",
                "source_type": "日线强势启动",
                "startup_reason": "放量突破",
                "signal_date": REPORT_DATE,
            },
            row_updates={
                "action": "可上车",
                "effective_action": "可上车",
                "formal_decision_contract": {
                    "action": "观察",
                    "action_reason": "正式动作由合同决定",
                },
            },
            raw_updates={
                "formal_decision_contract": {"action": "可上车"},
                "strategy_action": "可上车",
                "effective_action": "可上车",
            },
        )

        self.assertEqual(candidate["summary"]["formal_action"], "观察")
        clue = _main_rise_clue(self, candidate)
        self.assertNotEqual(clue.get("action"), "可上车")
        self.assertNotEqual(clue.get("effective_action"), "可上车")


if __name__ == "__main__":
    unittest.main()
