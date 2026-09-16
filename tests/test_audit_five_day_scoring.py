import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from chanlun.chan_engine import locate_buy_sell_points
from chanlun.decision_engine import evaluate_stock
from chanlun.strong_startup import (
    _make_watch_item,
    upgrade_strong_startup_with_30min,
)
from chanlun.sublevel_confirm import build_30min_confirmation_evidence
from chanlun.trend_continuation import _confirm_30min
from scripts.audit_five_day_scoring import (
    FIXED_DATES,
    OUT_OF_SAMPLE_DATES,
    _handoff_markdown,
    build_audit,
    classify_pullback_evidence,
    classify_sector_hot_evidence,
    evaluate_candidate_variants,
)
from tests.test_buy_points import (
    make_result_confirmed_second_buy,
    make_result_unconfirmed_second_buy,
    make_result_with_pivot_leave_and_pullback,
)
from tests.test_strong_startup import _make_seed
from tests.test_trend_continuation import _min30_result, _verified_evidence


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "five_day_scoring"


class FiveDayScoringAuditTestCase(unittest.TestCase):
    def _base_stock(self):
        return {
            "code": "TEST01",
            "name": "固定输入",
            "trend_type": "无中枢",
            "confirmed_by": "30min确认",
            "confirmations": ["30min两阳夹一阴确认"],
            "sector_rank": 19,
            "sector_flow": 771806976,
            "position_data_status": "verified",
            "position_evidence_date": "2026-09-15",
            "position_absolute_percentile": 45.0,
            "position_absolute_window": 120,
        }

    def test_generic_confirmation_is_unknown_not_pullback_and_input_is_unchanged(self):
        stock = self._base_stock()
        before = copy.deepcopy(stock)

        result = classify_pullback_evidence(stock)

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["contributes"])
        self.assertIn("30min确认", result["generic_confirmation_values"])
        self.assertEqual(stock, before)
        self.assertNotIn("pullback_confirmed", stock)
        self.assertIn(
            "回踩确认", evaluate_stock(stock)["structure"]["reasons"]
        )

    def test_explicit_pullback_true_and_false_are_preserved(self):
        explicit_true = classify_pullback_evidence({"pullback_confirmed": True})
        explicit_false = classify_pullback_evidence({"pullback_confirmed": False})

        self.assertEqual(explicit_true["status"], "true")
        self.assertTrue(explicit_true["contributes"])
        self.assertEqual(explicit_false["status"], "false")
        self.assertFalse(explicit_false["contributes"])

    @staticmethod
    def _trim_result(result, bars):
        for field in ("closes", "opens", "highs", "lows", "volumes", "dates"):
            values = getattr(result, field)
            setattr(result, field, values[:bars])
        return result

    def test_real_formal_second_and_third_buy_evidence_keeps_pullback_contribution(self):
        second_result = self._trim_result(make_result_confirmed_second_buy(), 35)
        second_result.buy_points, _ = locate_buy_sell_points(second_result)
        second_evidence = build_30min_confirmation_evidence(second_result)

        third_result = self._trim_result(
            make_result_with_pivot_leave_and_pullback(), 45
        )
        third_result.buy_points, _ = locate_buy_sell_points(third_result)
        third_evidence = build_30min_confirmation_evidence(third_result)

        self.assertEqual(second_evidence["buy_point"], "二买")
        self.assertEqual(third_evidence["buy_point"], "三买")
        for evidence in (second_evidence, third_evidence):
            with self.subTest(buy_point=evidence["buy_point"]):
                result = classify_pullback_evidence(
                    {"best_buy_point": {"confirmation_evidence": evidence}}
                )
                self.assertEqual(result["status"], "true")
                self.assertTrue(result["contributes"])
                self.assertEqual(
                    result["structured_mapping"], "formal_second_or_third_buy"
                )

        seed = _make_seed(code="TEST")
        candidates, watchlist, _ = upgrade_strong_startup_with_30min(
            [seed], [second_result]
        )
        self.assertEqual(watchlist, [])
        self.assertEqual(candidates[0]["confirmation_evidence"]["buy_point"], "二买")
        transferred = {
            "best_buy_point": {
                "source_type": "日线强势启动",
                "confirmed_by": "30min确认",
                "confirmations": candidates[0]["confirmations"],
                "confirmation_evidence": candidates[0]["confirmation_evidence"],
            }
        }
        self.assertTrue(classify_pullback_evidence(transferred)["contributes"])

    def test_candidate_pending_blocked_stale_waiting_and_free_text_do_not_upgrade(self):
        candidate_result = self._trim_result(make_result_confirmed_second_buy(), 35)
        candidate_result.buy_points = [
            {"type": "二买候选", "tier": "candidate", "index": 34}
        ]
        candidate_evidence = build_30min_confirmation_evidence(candidate_result)
        candidate = classify_pullback_evidence(
            {"confirmation_evidence": candidate_evidence}
        )
        self.assertEqual(candidate_evidence["buy_point"], "二买候选")
        self.assertEqual(candidate["status"], "unknown")
        self.assertFalse(candidate["contributes"])
        self.assertEqual(candidate["structured_mapping"], "candidate_pending_review")

        pending_result = self._trim_result(make_result_unconfirmed_second_buy(), 35)
        pending_result.buy_points, _ = locate_buy_sell_points(pending_result)
        pending_evidence = build_30min_confirmation_evidence(pending_result)
        self.assertIsNone(pending_evidence["buy_point"])

        blocked_result = self._trim_result(
            make_result_with_pivot_leave_and_pullback(), 45
        )
        blocked_result.closes[-1] = 14.0
        blocked_result.buy_points, _ = locate_buy_sell_points(blocked_result)
        self.assertTrue(
            any(point["type"] == "三买已错过" for point in blocked_result.buy_points)
        )
        blocked_evidence = build_30min_confirmation_evidence(blocked_result)
        self.assertIsNone(blocked_evidence["buy_point"])

        stale_result = make_result_confirmed_second_buy()
        stale_result.buy_points, _ = locate_buy_sell_points(stale_result)
        stale_evidence = build_30min_confirmation_evidence(stale_result)
        self.assertIsNone(stale_evidence["buy_point"])

        watch = _make_watch_item(
            {
                "code": "WAIT",
                "name": "等待回踩",
                "price_limit_state": "limit_up",
            },
            "低位放量涨停",
            "涨停当日不追，等待次日回踩确认",
            ["回踩不破突破位", "30min二买/三买", "缩量回踩后再放量"],
        )
        waiting = classify_pullback_evidence(watch)
        self.assertEqual(waiting["status"], "unknown")
        self.assertFalse(waiting["contributes"])
        self.assertIn("回踩不破突破位", waiting["waiting_condition_values"])

        for text in ("30min回踩不破突破位", "30min回踩不破"):
            with self.subTest(text=text):
                free_text = classify_pullback_evidence(
                    {"best_buy_point": {"confirmations": [text]}}
                )
                self.assertEqual(free_text["status"], "unknown")
                self.assertFalse(free_text["contributes"])

    def test_trend_reference_hold_alone_is_not_pullback_but_passed_formal_buy_is(self):
        state_only = _min30_result(np.linspace(12.0, 12.8, 20))
        state_evidence = _confirm_30min(
            state_only,
            reference_price=11.0,
            expected_date="2026-07-14",
            factor_vs_raw=1.0,
        )
        self.assertTrue(state_evidence["mandatory"]["reference_hold"])
        self.assertFalse(state_evidence["structure"]["fresh_event"])
        state = classify_pullback_evidence(
            {"confirmation_evidence": state_evidence}
        )
        self.assertEqual(state["status"], "unknown")
        self.assertFalse(state["contributes"])
        self.assertEqual(
            state["structured_mapping"], "reference_hold_without_formal_buy_point"
        )

        formal = self._trim_result(make_result_confirmed_second_buy(), 35)
        formal.dates = ["2026-07-14 14:30:00"] * 35
        formal.buy_points, _ = locate_buy_sell_points(formal)
        formal.macd_hist = np.linspace(-1.0, 1.0, 35)
        formal.strategy_input_evidence = _verified_evidence("2026-07-14")
        trend_evidence = _confirm_30min(
            formal,
            reference_price=8.5,
            expected_date="2026-07-14",
            factor_vs_raw=1.0,
        )
        self.assertTrue(trend_evidence["passed"])
        self.assertIn("30min 二买", trend_evidence["structure"]["labels"])
        mapped = classify_pullback_evidence(
            {"confirmation_evidence": trend_evidence}
        )
        self.assertEqual(mapped["status"], "true")
        self.assertTrue(mapped["contributes"])

        trend_candidate = _min30_result(np.linspace(12.0, 12.8, 20))
        trend_candidate.buy_points = [
            {"type": "三买候选", "tier": "candidate", "index": 19}
        ]
        trend_candidate.macd_hist = np.linspace(-1.0, 1.0, 20)
        candidate_evidence = _confirm_30min(
            trend_candidate,
            reference_price=11.0,
            expected_date="2026-07-14",
            factor_vs_raw=1.0,
        )
        self.assertTrue(candidate_evidence["passed"])
        self.assertIn(
            "30min 三买候选", candidate_evidence["structure"]["labels"]
        )
        candidate_mapping = classify_pullback_evidence(
            {"confirmation_evidence": candidate_evidence}
        )
        self.assertEqual(candidate_mapping["status"], "unknown")
        self.assertFalse(candidate_mapping["contributes"])
        self.assertEqual(
            candidate_mapping["structured_mapping"], "candidate_pending_review"
        )

    def test_conflict_and_source_mismatch_do_not_contribute(self):
        formal_second = {
            "schema_version": 1,
            "sufficient_bars": True,
            "buy_point": "二买",
        }
        formal_third = {
            "schema_version": 1,
            "sufficient_bars": True,
            "buy_point": "三买",
        }
        conflict = classify_pullback_evidence({
            "pullback_confirmed": False,
            "best_buy_point": {"confirmation_evidence": formal_second},
        })
        mismatch = classify_pullback_evidence({
            "confirmation_evidence": formal_second,
            "best_buy_point": {
                "confirmation_evidence": formal_third,
            }
        })

        self.assertEqual(conflict["status"], "conflict")
        self.assertFalse(conflict["contributes"])
        self.assertEqual(mismatch["status"], "source_mismatch")
        self.assertFalse(mismatch["contributes"])

    def test_raw_sector_amount_is_not_strength_but_rank_and_label_are_preserved(self):
        amount_only = classify_sector_hot_evidence({"sector_flow": 999999999})
        rank_8 = classify_sector_hot_evidence({"sector_rank": 8})
        rank_9 = classify_sector_hot_evidence({"sector_rank": 9})
        label = classify_sector_hot_evidence({"sector_strength_label": "热门"})

        self.assertEqual(amount_only["status"], "unknown")
        self.assertFalse(amount_only["contributes"])
        self.assertEqual(amount_only["raw_sector_flow"], 999999999)
        self.assertTrue(rank_8["contributes"])
        self.assertEqual(rank_8["trigger"], "sector_rank_le_8")
        self.assertEqual(rank_9["status"], "false")
        self.assertFalse(rank_9["contributes"])
        self.assertTrue(label["contributes"])
        self.assertEqual(label["trigger"], "sector_strength_label")

    def test_single_factor_and_combined_variants_change_only_declared_contributions(self):
        stock = self._base_stock()

        variants = evaluate_candidate_variants(stock, {})

        self.assertEqual(variants["old"]["structure_score"], 10)
        self.assertEqual(variants["old"]["sentiment_score"], 20)
        self.assertEqual(variants["r1a"]["score_delta"], -15)
        self.assertEqual(variants["r1b"]["score_delta"], -20)
        self.assertEqual(variants["combined"]["score_delta"], -35)
        self.assertEqual(variants["r1a"]["structure_score_delta"], -15)
        self.assertEqual(variants["r1a"]["sentiment_score_delta"], 0)
        self.assertEqual(variants["r1b"]["structure_score_delta"], 0)
        self.assertEqual(variants["r1b"]["sentiment_score_delta"], -20)
        self.assertTrue(variants["r1a"]["decision_changed"])
        self.assertTrue(variants["r1b"]["decision_changed"])
        self.assertTrue(variants["combined"]["decision_changed"])
        self.assertEqual(
            variants["r1a"]["sentiment_score"],
            variants["old"]["sentiment_score"],
        )
        self.assertEqual(
            variants["r1b"]["structure_score"],
            variants["old"]["structure_score"],
        )

    def test_explicit_pullback_and_rank_positive_case_does_not_regress(self):
        stock = self._base_stock()
        stock["pullback_confirmed"] = True
        stock["sector_rank"] = 8

        variants = evaluate_candidate_variants(stock, {})

        self.assertEqual(variants["r1a"]["score_delta"], 0)
        self.assertEqual(variants["r1b"]["score_delta"], 0)
        self.assertEqual(variants["combined"]["score_delta"], 0)

    def test_fixed_window_keeps_all_saved_sources_and_oos_is_separate(self):
        audit = build_audit(
            FIXTURE_DIR,
            fixed_dates=FIXED_DATES,
            out_of_sample_dates=OUT_OF_SAMPLE_DATES,
        )

        fixed = audit["fixed_window"]
        oos = audit["out_of_sample"]
        self.assertEqual(fixed["record_count"], 4)
        self.assertEqual(fixed["unique_instrument_count"], 4)
        self.assertEqual(fixed["saved_source_row_count"], 6)
        self.assertEqual(fixed["reproducible_record_count"], 3)
        self.assertEqual(len(fixed["records"]), 4)
        self.assertEqual(
            sum(len(record["sources"]) for record in fixed["records"]), 6
        )
        self.assertEqual(oos["dates"], ["2026-09-16"])
        self.assertEqual(oos["record_count"], 1)
        self.assertEqual(oos["saved_source_row_count"], 1)
        self.assertEqual(len(audit["input_manifest"]), 6)
        self.assertTrue(
            all(item["sha256"] for item in audit["input_manifest"])
        )
        handoff = _handoff_markdown(audit)
        for variant, label in (("r1a", "R1-A"), ("r1b", "R1-B"), ("combined", "combined")):
            stats = fixed["variant_changes"][variant]
            self.assertIn(
                "| {} | {} | {} | {} |".format(
                    label,
                    stats["reproducible_rows"],
                    stats["score_changed_rows"],
                    stats["decision_changed_rows"],
                ),
                handoff,
            )
        self.assertIn("9/16 out-of-sample", handoff)
        evidence = audit["producer_evidence"]
        self.assertIn("03830dcf", evidence["historical_text_label"]["introduced_commit"])
        self.assertEqual(
            evidence["current_structured_buy_point"]["mapped_formal_types"],
            ["二买", "三买"],
        )
        self.assertFalse(
            evidence["trend_continuation"]["reference_hold_alone_maps"]
        )

    def test_cli_replays_portable_fixture_with_explicit_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            completed = subprocess.run(
                [
                    "/usr/bin/python3",
                    "scripts/audit_five_day_scoring.py",
                    "--data-dir",
                    str(FIXTURE_DIR),
                    "--output-dir",
                    str(temp_root / "scoring"),
                    "--handoff",
                    str(temp_root / "handoff.md"),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = __import__("json").loads(completed.stdout)
            self.assertEqual(payload["fixed_window"]["record_count"], 4)
            self.assertEqual(payload["fixed_window"]["saved_source_row_count"], 6)
            self.assertTrue((temp_root / "scoring" / "audit.json").is_file())
            self.assertTrue((temp_root / "handoff.md").is_file())
            self.assertTrue(
                (temp_root / "scoring-verified-producer-handoff.md").is_file()
            )


if __name__ == "__main__":
    unittest.main()
