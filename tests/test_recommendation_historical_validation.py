"""Contracts for per-candidate historical validation evidence.

Task 11 deliberately keeps this contract separate from the existing evidence
projection tests.  The current implementation still emits the generic
``evidence_not_projected`` placeholder for ``historical_validation``; these
tests describe the fail-closed identity, maturity, and simulation semantics
that the implementation must add without touching formal strategy outputs.
"""

import json
import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)


DATE = "2026-08-28"
CODE = "600001"


def _identity(
    *,
    strategy="daily_fusion",
    version="daily-fusion-close-v1",
    source_pool="picks_fusion",
    entry_mode="immediate_close",
    intended_horizon=None,
    research_tier="prospective_ledger",
):
    return {
        "strategy": strategy,
        "version": version,
        "source_pool": source_pool,
        "entry_mode": entry_mode,
        "intended_horizon": intended_horizon,
        "research_tier": research_tier,
    }


def _progress(
    *,
    status="collecting",
    mature_samples=4,
    waiting_samples=2,
    unavailable_samples=0,
    active_dates=3,
    active_months=1,
):
    return {
        "status": status,
        "mature_samples": mature_samples,
        "waiting_samples": waiting_samples,
        "unavailable_samples": unavailable_samples,
        "required_mature_samples": 100,
        "active_dates": active_dates,
        "required_active_dates": 20,
        "active_months": active_months,
        "required_calendar_months": 2,
    }


def _maturity(*, mature=4, waiting=2, unavailable=0):
    return {
        key: {
            "mature": mature,
            "waiting": waiting,
            "unavailable": unavailable,
        }
        for key in ("t1", "t3", "t5")
    }


def _scorecard(
    identity=None,
    *,
    role="formal",
    evaluation_status="collecting",
    readiness=None,
    progress=None,
    metrics=None,
):
    identity = dict(identity or _identity())
    readiness = readiness or {
        key: evaluation_status for key in ("t1", "t3", "t5")
    }
    progress = progress or {
        key: _progress(status=readiness[key])
        for key in ("t1", "t3", "t5")
    }
    metrics = metrics or {key: {} for key in ("t1", "t3", "t5")}
    return {
        "evaluation_role": role,
        **identity,
        "comparison_identity": dict(identity),
        "evaluation_status": evaluation_status,
        "evidence_tier": identity["research_tier"],
        "metrics_publishable": True,
        "metrics_blocking_reasons": [],
        "active_dates": 3,
        "active_months": 1,
        "episode_count": 6,
        "sample_size": None,
        "maturity_by_horizon": _maturity(),
        "horizon_readiness": dict(readiness),
        "comparison_progress_by_horizon": progress,
        "metrics_by_horizon": metrics,
        "representative_samples": [],
    }


def _contribution(
    identity=None,
    *,
    role="formal",
    entry_price=None,
    entry_price_status=None,
    entry_price_source=None,
):
    identity = dict(identity or _identity())
    row = {
        "strategy_name": identity["strategy"],
        "strategy_version": identity["version"],
        "source_pool": identity["source_pool"],
        "entry_mode": identity["entry_mode"],
        "intended_horizon": identity["intended_horizon"],
        "research_tier": identity["research_tier"],
        "evaluation_role": role,
        "publication_surface": "formal_recommendation",
        "evaluation_eligible": True,
        "cohort_eligible": True,
        "decision_code": "recommend",
        "user_action": "recommendation",
        "attribution_status": "verified",
    }
    if entry_price is not None:
        row["entry_price"] = entry_price
    if entry_price_status is not None:
        row["entry_price_status"] = entry_price_status
    if entry_price_source is not None:
        row["entry_price_source"] = entry_price_source
    return row


def _ledger_entry(
    contributions,
    *,
    reference_close=10.5,
    report_date=DATE,
    recommendation_id="rec:historical-validation",
):
    return {
        "schema_version": "1",
        "recommendation_id": recommendation_id,
        "report_date": report_date,
        "code": CODE,
        "name": "证据股",
        "reference_close": reference_close,
        "reference_close_source": "closes[-1]",
        "reference_close_status": "verified",
        "strategy_contributions": list(contributions),
    }


def _workspace_row():
    return {
        "code": CODE,
        "name": "证据股",
        "sector": "工业",
        "view_rank": 1,
        "opportunity_score": 88,
        "ref": {"pool": "picks_fusion", "code": CODE},
        "formal_decision_contract": {
            "action": "观察",
            "action_reason": "等待确认",
        },
    }


def _raw_candidate():
    return {
        "code": CODE,
        "name": "证据股",
        "current_price": 99.0,
        "closes": [98.0, 99.0],
        "decision_engine_v1": {
            "decision_code": "recommend",
            "total_score": 62,
        },
    }


def _daily_data(*, scorecards, ledger, row=None, raw=None):
    return {
        "date": DATE,
        "workspace": {
            "view_order": ["main"],
            "views": {"main": [row or _workspace_row()]},
        },
        "picks_fusion": [raw or _raw_candidate()],
        "recommendation_ledger": list(ledger),
        "strategy_scorecards": scorecards,
    }


def _project(*, scorecards, ledger, row=None, raw=None):
    return build_recommendation_evidence_projection(
        {"date": DATE},
        _daily_data(
            scorecards=scorecards,
            ledger=ledger,
            row=row,
            raw=raw,
        ),
    )["views"]["main"][0]["historical_validation"]


def _scorecards(*rows):
    return {
        "schema_version": 2,
        "thresholds": {
            "mature_samples": 100,
            "active_dates": 20,
            "calendar_months": 2,
        },
        "formal": list(rows),
        "baselines": [],
        "research": [],
        "gates": [],
        "classification_failures": [],
    }


class TestRecommendationHistoricalValidation(unittest.TestCase):
    def test_historical_validation_keeps_exact_strategy_contract_identity(self):
        exact = _identity(research_tier="prospective_ledger")
        wrong_tier = _identity(research_tier="historical_replay")
        exact_metrics = {
            key: {}
            for key in ("t1", "t3", "t5")
        }
        exact_metrics["t3"] = {
            "n": 100,
            "date_start": "2026-01-05",
            "date_end": "2026-08-28",
            "mean": 1.5,
            "median": 1.0,
            "win_rate": 66.7,
            "excess_mean": 0.2,
            "mean_mfe": 4.0,
            "mean_mae": -2.0,
            "max_drawdown": -4.0,
        }
        exact_progress = {
            key: _progress(
                status="ready_for_manual_comparison",
                mature_samples=100,
                waiting_samples=0,
                active_dates=20,
                active_months=2,
            )
            for key in ("t1", "t3", "t5")
        }
        exact_readiness = {
            key: "ready_for_manual_comparison"
            for key in ("t1", "t3", "t5")
        }
        wrong_metrics = {
            key: {"mean": 999.0, "win_rate": 100.0}
            for key in ("t1", "t3", "t5")
        }
        ledger = [_ledger_entry([_contribution(exact)])]
        validation = _project(
            scorecards=_scorecards(
                _scorecard(
                    exact,
                    readiness=exact_readiness,
                    progress=exact_progress,
                    evaluation_status="ready_for_manual_comparison",
                    metrics=exact_metrics,
                ),
                _scorecard(
                    wrong_tier,
                    readiness=exact_readiness,
                    progress=exact_progress,
                    evaluation_status="ready_for_manual_comparison",
                    metrics=wrong_metrics,
                ),
            ),
            ledger=ledger,
        )

        self.assertEqual(validation["comparison_identity"], exact)
        self.assertEqual(
            validation["metrics_by_horizon"]["t3"]["mean"],
            1.5,
        )
        self.assertNotIn("999.0", json.dumps(validation, ensure_ascii=False))

    def test_ready_progress_without_complete_dated_metrics_stays_collecting(self):
        identity = _identity(intended_horizon=3)
        readiness = {
            key: "ready_for_manual_comparison"
            for key in ("t1", "t3", "t5")
        }
        progress = {
            key: _progress(
                status="ready_for_manual_comparison",
                mature_samples=100,
                waiting_samples=0,
                active_dates=20,
                active_months=2,
            )
            for key in ("t1", "t3", "t5")
        }
        incomplete_metrics = {
            key: {"n": 100, "mean": 1.5}
            for key in ("t1", "t3", "t5")
        }
        validation = _project(
            scorecards=_scorecards(_scorecard(
                identity,
                evaluation_status="ready_for_manual_comparison",
                readiness=readiness,
                progress=progress,
                metrics=incomplete_metrics,
            )),
            ledger=[_ledger_entry([_contribution(identity)])],
        )

        self.assertEqual(validation["status"], "collecting")
        self.assertEqual(validation["metrics_by_horizon"]["t3"], {})

    def test_duplicate_role_identity_is_ambiguous_and_fails_closed(self):
        identity = _identity()
        ledger = [_ledger_entry([_contribution(identity)])]
        validation = _project(
            scorecards=_scorecards(
                _scorecard(identity, role="formal"),
                _scorecard(identity, role="baseline"),
            ),
            ledger=ledger,
        )

        self.assertEqual(validation["status"], "ambiguous")
        self.assertEqual(
            validation["metrics_by_horizon"],
            {"t1": {}, "t3": {}, "t5": {}},
        )

    def test_unique_nonformal_scorecard_never_represents_formal_candidate(self):
        identity = _identity()
        scorecards = _scorecards()
        scorecards["research"] = [_scorecard(identity, role="research")]

        validation = _project(
            scorecards=scorecards,
            ledger=[_ledger_entry([_contribution(identity)])],
        )

        self.assertEqual(validation["status"], "missing")
        self.assertEqual(
            validation["reason"],
            "same_contract_scorecard_role_not_formal",
        )
        self.assertEqual(
            validation["metrics_by_horizon"],
            {"t1": {}, "t3": {}, "t5": {}},
        )

    def test_formal_role_row_outside_formal_section_fails_closed(self):
        identity = _identity()
        for section in ("baselines", "research", "gates"):
            with self.subTest(section=section):
                scorecards = _scorecards()
                scorecards[section] = [
                    _scorecard(identity, role="formal")
                ]

                validation = _project(
                    scorecards=scorecards,
                    ledger=[_ledger_entry([_contribution(identity)])],
                )

                self.assertEqual(validation["status"], "missing")
                self.assertEqual(
                    validation["reason"],
                    "same_contract_scorecard_section_not_formal",
                )
                self.assertEqual(
                    validation["metrics_by_horizon"],
                    {"t1": {}, "t3": {}, "t5": {}},
                )

    def test_immature_scorecard_shows_progress_without_win_rate_claim(self):
        identity = _identity()
        progress = {
            "t1": _progress(mature_samples=4, waiting_samples=0),
            "t3": _progress(mature_samples=4, waiting_samples=2),
            "t5": _progress(mature_samples=0, waiting_samples=6),
        }
        malicious_metrics = {
            key: {
                "n": 4,
                "mean": 999.0,
                "median": 999.0,
                "win_rate": 100.0,
                "excess_mean": 999.0,
                "mean_mfe": 999.0,
                "mean_mae": -999.0,
                "max_drawdown": -999.0,
            }
            for key in ("t1", "t3", "t5")
        }
        validation = _project(
            scorecards=_scorecards(
                _scorecard(
                    identity,
                    progress=progress,
                    metrics=malicious_metrics,
                ),
            ),
            ledger=[_ledger_entry([_contribution(identity)])],
        )

        self.assertEqual(validation["status"], "collecting")
        self.assertEqual(
            validation["progress_by_horizon"]["t3"]["mature_samples"],
            4,
        )
        self.assertEqual(
            validation["progress_by_horizon"]["t3"]["waiting_samples"],
            2,
        )
        self.assertEqual(
            validation["progress_by_horizon"]["t3"]["active_dates"],
            3,
        )
        self.assertEqual(
            validation["progress_by_horizon"]["t3"]["active_months"],
            1,
        )
        self.assertEqual(
            validation["metrics_by_horizon"],
            {"t1": {}, "t3": {}, "t5": {}},
        )
        self.assertNotIn("win_rate", validation["metrics_by_horizon"]["t3"])
        self.assertNotIn("999.0", json.dumps(validation, ensure_ascii=False))

    def test_daily_fusion_does_not_default_to_t3(self):
        identity = _identity(intended_horizon=None)
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[_ledger_entry([_contribution(identity)])],
        )

        self.assertIsNone(validation["comparison_identity"]["intended_horizon"])
        self.assertIsNone(validation["declared_horizon"])
        self.assertIn("未声明", validation["summary"])
        self.assertIsNot(validation.get("primary_horizon"), 3)

    def test_missing_entry_mode_never_creates_simulated_entry_price(self):
        identity = _identity(entry_mode="unknown")
        contribution = _contribution(identity)
        ledger = [
            _ledger_entry([contribution], reference_close=10.5),
            _ledger_entry(
                [contribution],
                reference_close=9.5,
                report_date="2026-08-20",
                recommendation_id="rec:historical-entry-mode-unknown",
            ),
        ]
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=ledger,
            row=_workspace_row(),
        )

        tracking = validation["simulation_tracking"]
        self.assertEqual(tracking["status"], "entry_mode_unknown")
        self.assertIsNone(tracking.get("entry_price"))
        self.assertIsNone(tracking.get("entry_price_source"))
        self.assertNotIn("99.0", json.dumps(tracking, ensure_ascii=False))

    def test_same_contract_tracking_uses_ledger_identity_only(self):
        exact = _identity()
        near_match = _identity(source_pool="picks_pure")
        current_contribution = _contribution(exact)
        exact_contribution = _contribution(
            exact,
            entry_price=10.5,
            entry_price_status="verified",
            entry_price_source="ledger.exact.entry_price",
        )
        exact_contribution["publication_status"] = "published"
        wrong_contribution = _contribution(
            near_match,
            role="baseline",
            entry_price=99.0,
            entry_price_status="verified",
            entry_price_source="ledger.wrong.entry_price",
        )
        validation = _project(
            scorecards=_scorecards(_scorecard(exact)),
            ledger=[
                _ledger_entry([current_contribution]),
                _ledger_entry(
                    [exact_contribution],
                    report_date="2026-08-20",
                    recommendation_id="rec:historical-exact",
                ),
                _ledger_entry(
                    [wrong_contribution],
                    report_date="2026-08-27",
                    recommendation_id="rec:historical-wrong-contract",
                ),
            ],
        )

        tracking = validation["simulation_tracking"]
        self.assertEqual(tracking["status"], "available")
        self.assertEqual(tracking["signal_date"], "2026-08-20")
        self.assertEqual(tracking["entry_mode"], "immediate_close")
        self.assertEqual(tracking["intended_horizon"], None)
        self.assertEqual(tracking["publication_status"], "published")
        self.assertEqual(tracking["decision_code"], "recommend")
        self.assertEqual(tracking["entry_price"], 10.5)
        self.assertIn("ledger", tracking["entry_price_source"])
        self.assertNotEqual(tracking["entry_price"], 99.0)

    def test_current_report_record_is_not_historical_tracking(self):
        identity = _identity(intended_horizon=3)
        current = _contribution(
            identity,
            entry_price=10.5,
            entry_price_status="verified",
            entry_price_source="ledger.current.entry_price",
        )
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[_ledger_entry([current], reference_close=10.5)],
        )

        tracking = validation["simulation_tracking"]
        self.assertEqual(tracking["status"], "missing")
        self.assertEqual(
            tracking["label"],
            "暂无同合同历史跟踪记录",
        )
        self.assertIsNone(tracking.get("signal_date"))
        self.assertIsNone(tracking.get("entry_price"))
        self.assertIsNone(tracking.get("tracking_status"))
        self.assertIsNone(tracking.get("target_triggered"))
        self.assertIsNone(tracking.get("invalidation_triggered"))

    def test_simulation_copy_never_says_real_holding_or_real_trade(self):
        identity = _identity()
        contribution = _contribution(
            identity,
            entry_price=10.5,
            entry_price_status="verified",
            entry_price_source="ledger.reference_close",
        )
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[
                _ledger_entry([_contribution(identity)]),
                _ledger_entry(
                    [contribution],
                    report_date="2026-08-20",
                    recommendation_id="rec:historical-copy",
                ),
            ],
        )
        encoded = json.dumps(validation, ensure_ascii=False)

        self.assertIn("策略模拟跟踪", encoded)
        self.assertNotIn("真实持仓", encoded)
        self.assertNotIn("真实交易", encoded)

    def test_other_date_ledger_row_never_becomes_same_contract_tracking(self):
        identity = _identity()
        entry = _ledger_entry([_contribution(identity)])
        entry["report_date"] = "2026-08-27"
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[entry],
        )

        self.assertEqual(validation["status"], "missing")
        self.assertEqual(validation["simulation_tracking"]["status"], "missing")

    def test_ineligible_or_unverified_contribution_never_anchors_contract(self):
        identity = _identity()
        invalid_contract_fields = (
            ("evaluation_eligible", False),
            ("cohort_eligible", False),
            ("attribution_status", "unverified"),
            ("decision_code", "observe"),
            ("user_action", "observation"),
            ("publication_surface", "research_only"),
            ("evaluation_role", "research"),
        )
        for field, value in invalid_contract_fields:
            with self.subTest(field=field):
                contribution = _contribution(identity)
                contribution[field] = value
                validation = _project(
                    scorecards=_scorecards(_scorecard(identity)),
                    ledger=[_ledger_entry([contribution])],
                )

                self.assertEqual(validation["status"], "missing")
                self.assertIsNone(validation["comparison_identity"])
                self.assertEqual(
                    validation["simulation_tracking"]["status"],
                    "missing",
                )

    def test_valid_entry_mode_without_explicit_verified_price_never_falls_back(self):
        identity = _identity()
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[
                _ledger_entry([_contribution(identity)], reference_close=10.5),
                _ledger_entry(
                    [_contribution(identity)],
                    reference_close=9.5,
                    report_date="2026-08-20",
                    recommendation_id="rec:historical-no-entry-price",
                ),
            ],
            raw=_raw_candidate(),
        )

        tracking = validation["simulation_tracking"]
        self.assertEqual(tracking["status"], "entry_price_missing")
        self.assertIsNone(tracking["entry_price"])
        self.assertIsNone(tracking["entry_price_source"])
        self.assertNotIn("99.0", json.dumps(tracking, ensure_ascii=False))
        self.assertNotIn("10.5", json.dumps(tracking, ensure_ascii=False))

    def test_advertised_ready_below_fixed_gate_never_publishes_metrics(self):
        identity = _identity(intended_horizon=3)
        readiness = {
            key: "ready_for_manual_comparison"
            for key in ("t1", "t3", "t5")
        }
        progress = {
            key: _progress(
                status="ready_for_manual_comparison",
                mature_samples=99,
                active_dates=20,
                active_months=2,
            )
            for key in ("t1", "t3", "t5")
        }
        metrics = {
            key: {"n": 99, "mean": 999.0, "win_rate": 100.0}
            for key in ("t1", "t3", "t5")
        }
        validation = _project(
            scorecards=_scorecards(_scorecard(
                identity,
                evaluation_status="ready_for_manual_comparison",
                readiness=readiness,
                progress=progress,
                metrics=metrics,
            )),
            ledger=[_ledger_entry([_contribution(identity)])],
        )

        self.assertEqual(validation["status"], "collecting")
        self.assertEqual(
            validation["metrics_by_horizon"],
            {"t1": {}, "t3": {}, "t5": {}},
        )
        self.assertNotIn("999.0", json.dumps(validation, ensure_ascii=False))

    def test_missing_research_tier_uses_explicit_formal_identity(self):
        identity = _identity(research_tier="prospective_ledger")
        contribution = _contribution(identity)
        contribution.pop("research_tier")
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[_ledger_entry([contribution])],
        )

        self.assertEqual(
            validation["comparison_identity"]["research_tier"],
            "prospective_ledger",
        )

    def test_missing_evaluation_role_never_anchors_formal_contract(self):
        identity = _identity(research_tier="legacy_unclassified")
        contribution = _contribution(identity)
        contribution.pop("evaluation_role")
        contribution.pop("research_tier")
        validation = _project(
            scorecards=_scorecards(_scorecard(identity)),
            ledger=[_ledger_entry([contribution])],
        )

        self.assertEqual(validation["status"], "missing")
        self.assertIsNone(validation["comparison_identity"])
        self.assertEqual(
            validation["simulation_tracking"]["status"],
            "missing",
        )


if __name__ == "__main__":
    unittest.main()
