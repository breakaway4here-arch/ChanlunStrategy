import hashlib
import json
import unittest
from unittest.mock import patch

from chanlun.policy_experiment_metrics import (
    bootstrap_mean_confidence_interval,
    list_policy_experiments,
    bottom_quality_guard_reasons,
    bottom_trend_guard_reasons,
    evaluate_recall_acceptance_gates,
    evaluate_high_return_version_selection,
    verify_oot_attestation,
    should_filter_for_policy,
    run_policy_experiment_metrics,
)


def _make_pick(
    code="000001",
    point_type="底背驰候选",
    distance=None,
    index=0,
    confirmations=None,
    market_regime=None,
    ma_bullish=None,
):
    bbp = {
        "type": point_type,
        "index": index,
    }
    if distance is not None:
        bbp["distance_from_reference_pct"] = distance
    if confirmations is not None:
        bbp["confirmations"] = confirmations
    return {
        "code": code,
        "best_buy_point": bbp,
        "market_regime": market_regime,
        "ma_bullish": ma_bullish,
        "closes": [1, 2, 3, 4, 5, 6, 7],
    }


def _make_fusion_pick(
    code="000001",
    best_type="一买",
    trend_strength=2.0,
    volatility=0.05,
    pivot=None,
    segment=None,
    signal_index=0,
    market_regime=None,
):
    return {
        "code": code,
        "best_buy_point": {
            "type": best_type,
            "trend_strength": trend_strength,
            "volatility": volatility,
            "pivot": pivot,
            "segment": segment,
            "index": signal_index,
        },
        "market_regime": market_regime,
    }


def _returns_matching_scorecard(card):
    count = card["sample_size"]
    hit_count = round(card["hit_rate_ge_5"] * count / 100.0)
    median_value = float(card["median_close_return"])
    mean_value = float(card["mean_close_return"])
    if median_value < 5.0 and 0 < hit_count < count // 2:
        low_count = count - hit_count
        lower_count = count // 2 - 1
        high_value = max(
            5.0,
            median_value + count * (mean_value - median_value) / hit_count,
        )
        median_count = low_count - lower_count
        lower_value = (
            count * mean_value
            - median_count * median_value
            - hit_count * high_value
        ) / lower_count
        return (
            [lower_value] * lower_count
            + [median_value] * median_count
            + [high_value] * hit_count
        )
    if median_value >= 5.0 and hit_count >= count // 2:
        non_hit_count = count - hit_count
        median_count = count // 2 + 1 - non_hit_count
        high_count = hit_count - median_count
        high_value = (
            count * mean_value - median_count * median_value
        ) / high_count
        return (
            [0.0] * non_hit_count
            + [median_value] * median_count
            + [high_value] * high_count
        )
    raise AssertionError("unsupported synthetic scorecard fixture")


class PolicyExperimentMetricsTests(unittest.TestCase):
    _TEST_CODE_SHA = "a" * 40

    @staticmethod
    def _high_return_card(
        version,
        *,
        mean_return,
        median_return,
        hit5,
        samples=120,
        active_dates=24,
        active_months=2,
        source_pool="picks_fusion",
        truth_verified=True,
    ):
        return {
            "source_pool": source_pool,
            "version": version,
            "entry_mode": "immediate_close",
            "intended_horizon": 3,
            "sample_size": samples,
            "active_dates": active_dates,
            "active_months": active_months,
            "mean_close_return": mean_return,
            "median_close_return": median_return,
            "hit_rate_ge_5": hit5,
            "mean_mfe": 20.0,
            "research_evidence": {
                "truth_verified": truth_verified,
                "leakage_free": True,
                "maturity_verified": True,
                "oot_locked": True,
            },
        }

    @classmethod
    def _verified_oot_attestation(cls, card, cutoff="2026-08-20"):
        card["oot_cutoff"] = cutoff
        contract = {
            "source_pool": card["source_pool"],
            "strategy_version": card["version"],
            "intended_horizon": card["intended_horizon"],
            "entry_mode": card["entry_mode"],
            "cutoff": cutoff,
            "code_sha": cls._TEST_CODE_SHA,
        }
        active_dates = []
        for index in range(card["active_dates"]):
            month = "07" if index < (card["active_dates"] + 1) // 2 else "08"
            day = index + 1 if month == "07" else index + 1 - (
                (card["active_dates"] + 1) // 2
            )
            active_dates.append("2026-{}-{:02d}".format(month, day))
        samples = []
        close_returns = _returns_matching_scorecard(card)
        for index in range(card["sample_size"]):
            report_date = active_dates[index % len(active_dates)]
            samples.append({
                "report_date": report_date,
                "target_date": cutoff,
                "feature_as_of": report_date,
                "maturity_status": "mature",
                "close_return": close_returns[index],
                "source_record_hash": hashlib.sha256(
                    "{}:{}".format(card["version"], index).encode("utf-8")
                ).hexdigest(),
            })
        artifact = json.dumps({
            "schema_version": 1,
            "contract": contract,
            "samples": samples,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
        attestation = dict(contract)
        attestation["data_hash"] = hashlib.sha256(artifact).hexdigest()
        return verify_oot_attestation(
            card,
            attestation,
            artifact,
            current_code_sha=cls._TEST_CODE_SHA,
        )

    def test_high_return_selection_blocks_outliers_and_enforces_oot_gates(self):
        baseline = self._high_return_card(
            "baseline-v1", mean_return=2.0, median_return=2.0, hit5=40.0
        )
        healthy = self._high_return_card(
            "healthy-v2", mean_return=3.0, median_return=2.2, hit5=45.0
        )
        high_mean_low_mfe = self._high_return_card(
            "high-mean-v2",
            mean_return=3.5,
            median_return=2.3,
            hit5=55.0 / 120.0 * 100.0,
        )
        high_mean_low_mfe.update({
            "mean_mfe": 1.0,
            "loss_rate_le_minus_5": 30.0,
            "worst_close_return": -20.0,
        })
        outlier = self._high_return_card(
            "outlier-v2", mean_return=4.0, median_return=1.0, hit5=30.0
        )
        shadow = self._high_return_card(
            "shadow-v2",
            mean_return=6.0,
            median_return=5.0,
            hit5=60.0,
            samples=50,
            active_dates=12,
        )
        unverified = self._high_return_card(
            "unverified-v2",
            mean_return=8.0,
            median_return=7.0,
            hit5=70.0,
            truth_verified=False,
        )

        attestations = [
            self._verified_oot_attestation(card)
            for card in (
                baseline, outlier, shadow, healthy, high_mean_low_mfe
            )
        ]
        result = evaluate_high_return_version_selection(
            baseline,
            [outlier, shadow, unverified, healthy, high_mean_low_mfe],
            oot_attestations=attestations,
        )
        by_version = {
            item["version"]: item for item in result["candidates"]
        }

        self.assertIsNone(result["selected_version"])
        self.assertFalse(by_version["healthy-v2"]["promotion_eligible"])
        self.assertEqual(
            by_version["healthy-v2"]["comparison_status"],
            "baseline_not_production",
        )
        self.assertFalse(by_version["high-mean-v2"]["promotion_eligible"])
        self.assertIn(
            "trusted_oot_provenance_unavailable",
            by_version["high-mean-v2"]["hard_gate_reasons"],
        )
        self.assertTrue(by_version["outlier-v2"]["outlier_driven"])
        self.assertFalse(by_version["outlier-v2"]["promotion_eligible"])
        self.assertEqual(by_version["shadow-v2"]["research_tier"], "shadow")
        self.assertFalse(by_version["shadow-v2"]["promotion_eligible"])
        self.assertEqual(
            by_version["unverified-v2"]["research_tier"],
            "hard_gate_failed",
        )
        self.assertFalse(by_version["unverified-v2"]["promotion_eligible"])
        self.assertEqual(result["ranking_metric"], "mean_close_return")
        self.assertEqual(result["pareto_frontier"], [])
        self.assertFalse(result["production_top_k_cap"])

    def test_high_return_selection_requires_same_pool_horizon_and_entry_mode(self):
        baseline = self._high_return_card(
            "baseline-v1", mean_return=2.0, median_return=2.0, hit5=40.0
        )
        other_pool = self._high_return_card(
            "other-v2",
            mean_return=9.0,
            median_return=8.0,
            hit5=80.0,
            source_pool="trend_continuation",
        )

        result = evaluate_high_return_version_selection(
            baseline,
            [other_pool],
            oot_attestations=[
                self._verified_oot_attestation(baseline),
                self._verified_oot_attestation(other_pool),
            ],
        )

        self.assertIsNone(result["selected_version"])
        self.assertEqual(
            result["candidates"][0]["comparison_status"],
            "slice_mismatch",
        )

    def test_high_return_selection_does_not_trust_caller_boolean_flags(self):
        baseline = self._high_return_card(
            "baseline-v1", mean_return=2.0, median_return=2.0, hit5=40.0
        )
        candidate = self._high_return_card(
            "candidate-v2", mean_return=3.0, median_return=2.2, hit5=45.0
        )

        result = evaluate_high_return_version_selection(
            baseline, [candidate]
        )

        self.assertIsNone(result["selected_version"])
        self.assertEqual(result["baseline_research_tier"], "hard_gate_failed")
        self.assertIn(
            "oot_attestation_verified",
            result["baseline_hard_gate_reasons"],
        )

    def test_oot_attestation_rejects_tampered_data_and_contract_mismatch(self):
        card = self._high_return_card(
            "candidate-v2", mean_return=3.0, median_return=2.2, hit5=45.0
        )
        card["oot_cutoff"] = "2026-08-20"
        contract = {
            "source_pool": card["source_pool"],
            "strategy_version": card["version"],
            "intended_horizon": card["intended_horizon"],
            "entry_mode": card["entry_mode"],
            "cutoff": card["oot_cutoff"],
            "code_sha": self._TEST_CODE_SHA,
        }
        artifact = json.dumps({
            "schema_version": 1,
            "contract": contract,
            "samples": [{"report_date": "2026-07-01", "code": "000001"}],
        }, sort_keys=True).encode("utf-8")
        attestation = dict(contract)
        attestation["data_hash"] = hashlib.sha256(artifact).hexdigest()

        with self.assertRaisesRegex(ValueError, "data_hash"):
            verify_oot_attestation(
                card,
                attestation,
                artifact + b" ",
                current_code_sha=self._TEST_CODE_SHA,
            )

        mismatched = dict(attestation)
        mismatched["strategy_version"] = "other-v3"
        with self.assertRaisesRegex(ValueError, "strategy_version"):
            verify_oot_attestation(
                card,
                mismatched,
                artifact,
                current_code_sha=self._TEST_CODE_SHA,
            )

    def test_oot_attestation_requires_sample_gates_from_hashed_artifact(self):
        card = self._high_return_card(
            "candidate-v2", mean_return=3.0, median_return=2.2, hit5=45.0
        )
        card["oot_cutoff"] = "2026-08-20"
        contract = {
            "source_pool": card["source_pool"],
            "strategy_version": card["version"],
            "intended_horizon": card["intended_horizon"],
            "entry_mode": card["entry_mode"],
            "cutoff": card["oot_cutoff"],
            "code_sha": self._TEST_CODE_SHA,
        }
        artifact = json.dumps({
            "schema_version": 1,
            "contract": contract,
            "samples": [{"report_date": "2026-07-01"}],
        }, sort_keys=True).encode("utf-8")
        attestation = dict(contract)
        attestation["data_hash"] = hashlib.sha256(artifact).hexdigest()

        with self.assertRaisesRegex(ValueError, "sample_size"):
            verify_oot_attestation(
                card,
                attestation,
                artifact,
                current_code_sha=self._TEST_CODE_SHA,
            )

    def test_oot_attestation_requires_row_provenance_and_time_boundaries(self):
        card = self._high_return_card(
            "candidate-v2",
            mean_return=3.0,
            median_return=2.2,
            hit5=45.0,
            samples=1,
            active_dates=1,
            active_months=1,
        )
        card["oot_cutoff"] = "2026-08-20"
        contract = {
            "source_pool": card["source_pool"],
            "strategy_version": card["version"],
            "intended_horizon": card["intended_horizon"],
            "entry_mode": card["entry_mode"],
            "cutoff": card["oot_cutoff"],
            "code_sha": self._TEST_CODE_SHA,
        }
        artifact = json.dumps({
            "schema_version": 1,
            "contract": contract,
            "samples": [{
                "report_date": "2026-07-01",
                "target_date": "2026-07-06",
                "feature_as_of": "2026-07-01",
                "maturity_status": "mature",
            }],
        }, sort_keys=True).encode("utf-8")
        attestation = dict(contract)
        attestation["data_hash"] = hashlib.sha256(artifact).hexdigest()

        with self.assertRaisesRegex(ValueError, "source_record_hash"):
            verify_oot_attestation(
                card,
                attestation,
                artifact,
                current_code_sha=self._TEST_CODE_SHA,
            )

    def test_oot_attestation_rejects_forged_high_return_scorecard(self):
        card = self._high_return_card(
            "forged-v2",
            mean_return=99.0,
            median_return=99.0,
            hit5=100.0,
            samples=3,
            active_dates=3,
            active_months=2,
        )
        card["oot_cutoff"] = "2026-08-20"
        contract = {
            "source_pool": card["source_pool"],
            "strategy_version": card["version"],
            "intended_horizon": card["intended_horizon"],
            "entry_mode": card["entry_mode"],
            "cutoff": card["oot_cutoff"],
            "code_sha": self._TEST_CODE_SHA,
        }
        samples = []
        for index, (report_date, close_return) in enumerate((
            ("2026-07-01", 1.0),
            ("2026-07-02", 2.0),
            ("2026-08-01", 3.0),
        )):
            samples.append({
                "report_date": report_date,
                "target_date": "2026-08-20",
                "feature_as_of": report_date,
                "maturity_status": "mature",
                "close_return": close_return,
                "source_record_hash": hashlib.sha256(
                    "forged:{}".format(index).encode("utf-8")
                ).hexdigest(),
            })
        artifact = json.dumps({
            "schema_version": 1,
            "contract": contract,
            "samples": samples,
        }, sort_keys=True).encode("utf-8")
        attestation = dict(contract)
        attestation["data_hash"] = hashlib.sha256(artifact).hexdigest()

        with self.assertRaisesRegex(ValueError, "mean_close_return"):
            verify_oot_attestation(
                card,
                attestation,
                artifact,
                current_code_sha=self._TEST_CODE_SHA,
            )

    def test_high_return_selection_uses_attested_metrics_after_verification(self):
        baseline = self._high_return_card(
            "baseline-v1", mean_return=2.0, median_return=2.0, hit5=40.0
        )
        candidate = self._high_return_card(
            "candidate-v2", mean_return=3.0, median_return=2.2, hit5=45.0
        )
        baseline_attestation = self._verified_oot_attestation(baseline)
        candidate_attestation = self._verified_oot_attestation(candidate)
        candidate["mean_close_return"] = 99.0

        result = evaluate_high_return_version_selection(
            baseline,
            [candidate],
            oot_attestations=[
                baseline_attestation, candidate_attestation,
            ],
        )

        self.assertIsNone(result["selected_version"])
        self.assertAlmostEqual(
            result["candidates"][0]["mean_close_return"], 3.0
        )
        self.assertIn(
            "trusted_oot_provenance_unavailable",
            result["candidates"][0]["hard_gate_reasons"],
        )

    def test_self_hashed_artifact_without_trusted_provenance_stays_shadow(self):
        baseline = self._high_return_card(
            "baseline-v1", mean_return=2.0, median_return=2.0, hit5=40.0
        )
        forged = self._high_return_card(
            "forged-v2",
            mean_return=99.0,
            median_return=99.0,
            hit5=100.0,
        )
        result = evaluate_high_return_version_selection(
            baseline,
            [forged],
            oot_attestations=[
                self._verified_oot_attestation(baseline),
                self._verified_oot_attestation(forged),
            ],
        )

        self.assertIsNone(result["selected_version"])
        self.assertFalse(result["candidates"][0]["promotion_eligible"])
        self.assertEqual(result["candidates"][0]["research_tier"], "shadow")
        self.assertIn(
            "trusted_oot_provenance_unavailable",
            result["candidates"][0]["hard_gate_reasons"],
        )
    def test_list_policy_experiments(self):
        names = set(list_policy_experiments())
        self.assertEqual(
            names,
            {
                "delay1_v1",
                "delay1_v1_cooldown3",
                "delay1_v1_cooldown5",
                "delay1_v1_bottom_quality_guard",
                "delay1_v1_cooldown3_bottom_quality",
                "delay1_v1_bottom_missing_key_guard",
                "delay1_v1_bottom_missing_distance_guard",
                "delay1_v1_bottom_invalid_distance_guard",
                "delay1_v1_bottom_distance_gt6_guard",
                "delay1_v1_bottom_missing_shape_guard",
                "delay1_v1_bottom_quality_market_strong_guard",
                "delay1_v1_bottom_quality_market_known_guard",
                "delay1_v1_bottom_quality_market_known_guard_entry_signal_close",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open",
                "delay1_v1_bottom_quality_market_known_guard_entry_confirm_close",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3",
                "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative",
                "delay1_v1_bottom_quality_market_or_ma_guard",
                "fusion_strict",
                "fusion_strict_startup_rescue_v1",
                "fusion_mid",
                "fusion_loose",
            },
        )

    def test_execution_variant_policy_has_same_filters_as_known_market_guard(self):
        base_policy = "delay1_v1_bottom_quality_market_known_guard"
        variant_policies = (
            "delay1_v1_bottom_quality_market_known_guard_entry_signal_close",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open",
            "delay1_v1_bottom_quality_market_known_guard_entry_confirm_close",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3",
            "delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative",
        )
        picks = (
            _make_pick(
                point_type="底背驰候选",
                distance=1.8,
                confirmations=["关键位不破", "30min底分型", "止跌结构"],
                market_regime="strong",
            ),
            _make_pick(
                point_type="底背驰候选",
                distance=7.0,
                confirmations=["关键位不破", "30min底分型", "止跌结构"],
                market_regime="strong",
            ),
            _make_pick(
                point_type="底背驰候选",
                distance=None,
                confirmations=["关键位不破", "30min底分型", "止跌结构"],
                market_regime="strong",
            ),
            _make_pick(
                point_type="底背驰候选",
                distance=1.8,
                confirmations=[],
                market_regime="weak",
                ma_bullish=True,
            ),
        )

        for variant in variant_policies:
            for pick in picks:
                base_filtered, base_reason = should_filter_for_policy(base_policy, pick, {})
                variant_filtered, variant_reason = should_filter_for_policy(variant, pick, {})
                self.assertEqual(base_filtered, variant_filtered)
                self.assertEqual(base_reason, variant_reason)

    def test_bottom_quality_guard_reasons(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), [])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["missing_key_protection"])

        pick = _make_pick(
            point_type="底背驰候选",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["missing_distance"])

        pick = _make_pick(
            point_type="底背驰候选",
            distance="invalid",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["invalid_distance"])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=7.1,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_quality_guard_reasons(pick), ["distance_gt_6"])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["关键位不破"],
        )
        self.assertEqual(
            bottom_quality_guard_reasons(pick),
            ["missing_bottom_shape_or_stop_drop"],
        )

        pick = _make_pick(
            point_type="底背驰候选",
            distance="invalid",
            confirmations=["止跌结构"],
        )
        self.assertEqual(
            bottom_quality_guard_reasons(pick),
            ["missing_key_protection", "invalid_distance"],
        )

        pick = {"best_buy_point": {"type": "强势启动候选"}}
        self.assertEqual(bottom_quality_guard_reasons(pick), [])

    def test_bottom_trend_guard_reasons(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="strong",
            ma_bullish=False,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_trend_guard_reasons(pick), [])

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=False,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(
            bottom_trend_guard_reasons(pick),
            ["market_not_strong", "market_not_strong_no_ma"],
        )

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=True,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_trend_guard_reasons(pick), ["market_not_strong"])

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="",
            ma_bullish=True,
            distance=1.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        self.assertEqual(bottom_trend_guard_reasons(pick), ["market_unknown", "market_not_strong"])

        pick = {"best_buy_point": {"type": "强势启动候选"}, "market_regime": None}
        self.assertEqual(bottom_trend_guard_reasons(pick), [])

    def test_bottom_trend_guard_filters(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="strong",
            ma_bullish=False,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_strong_guard",
            pick,
            {},
        )
        self.assertFalse(filtered)
        self.assertEqual(reason, "")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=True,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_strong_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_not_strong")

    def test_bottom_trend_guard_order_quality_before_trend(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=False,
            distance="invalid",
            confirmations=["30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_quality_guard")

    def test_bottom_trend_known_and_or_ma_policies(self):
        pick = _make_pick(
            point_type="底背驰候选",
            market_regime=None,
            ma_bullish=True,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_known_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_unknown")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=False,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_not_strong_no_ma")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="",
            ma_bullish=False,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_market_not_strong_no_ma")

        pick = _make_pick(
            point_type="底背驰候选",
            market_regime="weak",
            ma_bullish=True,
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy(
            "delay1_v1_bottom_quality_market_or_ma_guard",
            pick,
            {},
        )
        self.assertFalse(filtered)
        self.assertEqual(reason, "")

    def test_bottom_quality_guard_filters_missing_key_reference_distance_or_confirmations(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["30min底分型"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_quality_guard")

        pick = _make_pick(
            point_type="底背驰候选",
            confirmations=["关键位不破", "30min底分型"],
        )
        self.assertTrue(should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})[0])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=7.0,
            confirmations=["关键位不破", "止跌结构"],
        )
        self.assertTrue(should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})[0])

        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["关键位不破"],
        )
        self.assertTrue(should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})[0])

    def test_bottom_quality_guard_keeps_valid_bottom_and_non_bottom(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=1.8,
            confirmations=["关键位不破", "30min底分型", "其他"],
        )
        filtered, _reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertFalse(filtered)

        pick = _make_pick(
            point_type="底背驰候选",
            distance=5.9,
            confirmations=["关键位不破", "止跌结构"],
        )
        filtered, _reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertFalse(filtered)

        pick = _make_pick(point_type="强势启动候选")
        filtered, _reason = should_filter_for_policy("delay1_v1_bottom_quality_guard", pick, {})
        self.assertFalse(filtered)

    def test_bottom_quality_single_reason_policies(self):
        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_key_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_missing_key_protection")

        pick = _make_pick(
            point_type="底背驰候选",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_distance_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_missing_distance")

        pick = _make_pick(
            point_type="底背驰候选",
            distance="abc",
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_invalid_distance_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_invalid_distance")

        pick = _make_pick(
            point_type="底背驰候选",
            distance=7.5,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_distance_gt6_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_distance_gt_6")

        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["关键位不破"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_shape_guard", pick, {})
        self.assertTrue(filtered)
        self.assertEqual(reason, "bottom_missing_shape_or_stop_drop")

        pick = _make_pick(
            point_type="底背驰候选",
            distance=2.0,
            confirmations=["关键位不破", "30min底分型", "止跌结构"],
        )
        filtered, reason = should_filter_for_policy("delay1_v1_bottom_missing_shape_guard", pick, {})
        self.assertFalse(filtered)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_cooldown_policy(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-05", "picks_fusion", _make_pick()),
                ("2026-01-04", "picks_fusion", _make_pick()),
                ("2026-01-04", "picks_pure", _make_pick(index=1)),
                ("2026-01-06", "picks_pure", _make_pick()),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }
        payload = run_policy_experiment_metrics(["delay1_v1_cooldown3"])
        self.assertEqual(len(payload["policies"]), 1)
        result = payload["policies"][0]
        self.assertEqual(result["coverage"]["picks_seen"], 4)
        self.assertGreater(result["coverage"]["baseline_evaluated"], 0)
        # first sorted by (snap_date, version, code): 01-04 picks_fusion -> 01-04 picks_pure -> 01-05 -> 01-06
        # cooldown window=3 => keep only the first 01-04 sample.
        self.assertEqual(result["coverage"]["policy_evaluated"], 1)
        self.assertEqual(result["coverage"]["policy_filtered_by_reason"].get("cooldown"), 3)

    @patch("chanlun.historical_experiment_metrics.fetch_daily_kline")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_multiple_policies_share_kline_fetch_across_codes(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-05", "picks_fusion", _make_pick(code="000001")),
                ("2026-01-06", "picks_fusion", _make_pick(code="000001")),
                ("2026-01-07", "picks_pure", _make_pick(code="000002")),
            ],
        )
        fetch_mock.return_value = {
            "dates": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
            ],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(
            ["delay1_v1", "delay1_v1_bottom_quality_guard"],
        )
        self.assertEqual(len(payload["policies"]), 2)
        self.assertEqual(fetch_mock.call_count, 2)
        policy_names = [item["policy"] for item in payload["policies"]]
        self.assertEqual(policy_names, ["delay1_v1", "delay1_v1_bottom_quality_guard"])
        for item in payload["policies"]:
            self.assertEqual(item["coverage"]["baseline_evaluated"], 3)
            self.assertEqual(item["coverage"]["baseline_filtered"], 0)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_summary_reports_shared_cache_counters(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-07", "picks_pure", _make_pick(code="000002")),
                ("2026-01-05", "picks_fusion", _make_pick(code="000001")),
                ("2026-01-06", "picks_fusion", _make_pick(code="000001")),
            ],
        )
        fetch_mock.side_effect = lambda code, *_args, **_kwargs: {
            "000001": {
                "dates": [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                ],
                "opens": [1, 1, 1, 1, 1, 1, 1],
                "highs": [1, 1, 1, 1, 1, 1, 1],
                "lows": [1, 1, 1, 1, 1, 1, 1],
                "closes": [1, 1, 1, 1, 1, 1, 1],
            },
            "000002": {
                "dates": [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                ],
                "opens": [1, 1, 1, 1, 1, 1, 1],
                "highs": [1, 1, 1, 1, 1, 1, 1],
                "lows": [1, 1, 1, 1, 1, 1, 1],
                "closes": [1, 1, 1, 1, 1, 1, 1],
            },
        }.get(code)
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        execution = payload.get("execution") or {}
        self.assertTrue(execution["shared_baseline"])
        self.assertEqual(execution["snapshot_rows"], 3)
        self.assertEqual(execution["unique_codes"], 2)
        self.assertEqual(execution["fetch_attempts"], 2)
        self.assertEqual(execution["cache_hits"], 1)
        self.assertEqual(execution["baseline_rows"], 3)
        self.assertEqual(execution["kline_missing"], 0)
        self.assertEqual(execution["kline_invalid"], 0)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._normalize_kline")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_summary_reports_missing_and_invalid_kline_rows(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        normalize_mock,
        fetch_mock,
    ):
        invalid_kline = object()
        valid_kline = {
            "dates": ["2026-01-01", "2026-01-02"],
            "opens": [1, 1],
            "highs": [1, 1],
            "lows": [1, 1],
            "closes": [1, 1],
        }

        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-05", "picks_pure", _make_pick(code="000001")),
                ("2026-01-06", "picks_pure", _make_pick(code="000002")),
                ("2026-01-07", "picks_pure", _make_pick(code="000003")),
            ],
        )
        fetch_mock.side_effect = lambda code, *_args, **_kwargs: {
            "000001": None,
            "000002": invalid_kline,
            "000003": valid_kline,
        }.get(code)
        normalize_mock.side_effect = lambda kline: {} if kline is invalid_kline else {
            "dates": ["x"],
            "opens": [1.0],
            "highs": [1.0],
            "lows": [1.0],
            "closes": [1.0],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        execution = payload.get("execution") or {}
        self.assertTrue(execution["shared_baseline"])
        self.assertEqual(execution["snapshot_rows"], 3)
        self.assertEqual(execution["unique_codes"], 3)
        self.assertEqual(execution["fetch_attempts"], 3)
        self.assertEqual(execution["cache_hits"], 0)
        self.assertEqual(execution["kline_missing"], 1)
        self.assertEqual(execution["kline_invalid"], 1)
        self.assertEqual(execution["baseline_rows"], 1)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_multiple_policies_keep_cooldown_state_independent(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-01", "picks_fusion", _make_pick()),
                ("2026-01-02", "picks_fusion", _make_pick()),
                ("2026-01-03", "picks_fusion", _make_pick()),
            ],
        )
        fetch_mock.return_value = {
            "dates": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
            ],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(
            ["delay1_v1", "delay1_v1_cooldown3"],
        )
        policy_map = {item["policy"]: item for item in payload["policies"]}
        self.assertEqual(policy_map["delay1_v1"]["coverage"]["policy_evaluated"], 3)
        self.assertEqual(policy_map["delay1_v1_cooldown3"]["coverage"]["policy_evaluated"], 1)

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_run_policy_experiment_metrics_returns_baseline_and_policy(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-02", "picks_pure", {"code": "000001", "best_buy_point": {"type": "强势启动候选", "index": 0}, "closes": [1, 2, 3]}),
                ("2026-01-01", "picks_fusion", {"code": "000002", "best_buy_point": {"type": "强势启动候选", "index": 0}, "closes": [1, 2, 3]}),
            ]
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        self.assertIn("policies", payload)
        self.assertEqual(len(payload["policies"]), 1)
        result = payload["policies"][0]
        self.assertEqual(result["policy"], "delay1_v1")
        self.assertIn("baseline_summary", result)
        self.assertIn("policy_summary", result)
        self.assertIn("delta", result)
        self.assertEqual(result["delta"]["t3_mean_delta"], 0.0)
        self.assertEqual(payload["requested_policies"], ["delay1_v1"])

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_variant_re_evaluates_with_explicit_entry_mode(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }

        observed_entry_modes = []

        def evaluate_side_effect(_normalized_kline, _snap_date, entry_mode):
            observed_entry_modes.append(entry_mode)
            if entry_mode == "delay1_close":
                return {
                    "t1_close_pct": 1.0,
                    "t3_close_pct": 1.0,
                    "max_up_3d": 0.5,
                    "max_dd_3d": -0.2,
                }
            if entry_mode == "delay1_open":
                return {
                    "t1_close_pct": 2.0,
                    "t3_close_pct": 2.0,
                    "max_up_3d": 1.5,
                    "max_dd_3d": -0.1,
                }
            return {
                "t1_close_pct": 3.0,
                "t3_close_pct": 3.0,
                "max_up_3d": 2.0,
                "max_dd_3d": -0.05,
            }

        evaluate_mock.side_effect = evaluate_side_effect
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_next_open"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 0)
        self.assertEqual(coverage["policy_evaluated"], 1)
        self.assertEqual(coverage["policy_filtered"], 0)
        self.assertEqual(result["policy_summary"]["n"], 1)
        self.assertEqual(result["policy_summary"]["t3_mean"], 2.0)
        self.assertEqual(result["execution_model"]["entry_label"], "entry_next_open")
        self.assertEqual(result["execution_model"]["entry_mode"], "delay1_open")
        self.assertEqual(result["execution_model"]["exit_model"], "exit_t3")
        self.assertIn("delay1_close", observed_entry_modes)
        self.assertIn("delay1_open", observed_entry_modes)

    @patch("chanlun.policy_experiment_metrics.evaluate_exit_returns")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_exit_variant_calls_exit_evaluator(
        self,
        iter_snapshot_mock,
        fetch_mock,
        evaluate_pick_mock,
        evaluate_exit_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_exit_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 2.0,
            "max_up_3d": 1.5,
            "max_dd_3d": -0.2,
            "exit_model": "exit_stop_loss_5pct",
            "exit_reason": "t3_close",
            "exit_return_pct": 2.0,
            "exit_day_index": 3,
        }
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 0)
        self.assertEqual(coverage["policy_evaluated"], 1)
        self.assertEqual(result["execution_model"]["entry_label"], "entry_next_open")
        self.assertEqual(result["execution_model"]["entry_mode"], "delay1_open")
        self.assertEqual(result["execution_model"]["exit_model"], "exit_stop_loss_5pct")
        evaluate_exit_mock.assert_called_once()
        evaluate_exit_mock.assert_called_with(
            fetch_mock.return_value,
            "2026-01-02",
            "delay1_open",
            "exit_stop_loss_5pct",
        )

    @patch("chanlun.policy_experiment_metrics.evaluate_exit_returns")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_exit_variant_not_evaluable_counted(self, iter_snapshot_mock, fetch_mock, evaluate_pick_mock, evaluate_exit_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_exit_mock.return_value = None
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 1)
        self.assertEqual(coverage["policy_evaluated"], 0)
        self.assertIsNone(result["policy_summary"])
        evaluate_exit_mock.assert_called_once()
        evaluate_exit_mock.assert_called_with(
            fetch_mock.return_value,
            "2026-01-02",
            "delay1_open",
            "exit_take_profit_8pct_or_t3",
        )

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_execution_variant_records_policy_not_evaluable(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }

        def evaluate_side_effect(_normalized_kline, _snap_date, entry_mode):
            if entry_mode == "immediate_close":
                return None
            return {
                "t1_close_pct": 1.0,
                "t3_close_pct": 1.0,
                "max_up_3d": 0.5,
                "max_dd_3d": -0.2,
            }

        evaluate_mock.side_effect = evaluate_side_effect
        payload = run_policy_experiment_metrics(
            ["delay1_v1_bottom_quality_market_known_guard_entry_signal_close"],
        )
        result = payload["policies"][0]
        coverage = result["coverage"]
        self.assertEqual(coverage["policy_not_evaluable"], 1)
        self.assertEqual(coverage["policy_evaluated"], 0)
        self.assertEqual(result["policy_summary"], None)
        self.assertEqual(
            result["breakdown"]["market_regime"]["strong"]["accepted"],
            1,
        )

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_bottom_quality_guard_reports_detailed_reason_breakdown(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-02", "picks_pure", _make_pick(distance=None, confirmations=["止跌结构"])),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1_bottom_quality_guard"])
        self.assertEqual(len(payload["policies"]), 1)
        result = payload["policies"][0]
        self.assertEqual(result["coverage"]["policy_filtered"], 1)
        self.assertEqual(result["coverage"]["policy_filtered_by_reason"]["bottom_quality_guard"], 1)
        self.assertEqual(
            result["coverage"]["policy_filtered_detail_by_reason"]["bottom_missing_key_protection"],
            1,
        )
        self.assertEqual(
            result["coverage"]["policy_filtered_detail_by_reason"]["bottom_missing_distance"],
            1,
        )
        self.assertNotIn(
            "bottom_missing_key_protection",
            result["coverage"]["policy_filtered_by_reason"],
        )

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_run_policy_experiment_metrics_includes_breakdown(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-01",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="strong",
                    ),
                ),
                (
                    "2026-01-02",
                    "picks_pure",
                    _make_pick(
                        point_type="底背驰候选",
                        distance=1.8,
                        confirmations=["关键位不破", "30min底分型", "止跌结构"],
                        market_regime="",
                    ),
                ),
                (
                    "2026-01-03",
                    "picks_pure",
                    _make_pick(
                        point_type="强势启动候选",
                        confirmations=[],
                        market_regime="strong",
                    ),
                ),
            ],
        )
        fetch_mock.side_effect = lambda code, *_args, **_kwargs: {
            "000001": {
                "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
                "opens": [1, 1, 1, 1, 1],
                "highs": [1, 1, 1, 1, 1],
                "lows": [1, 1, 1, 1, 1],
                "closes": [1, 1, 1, 1, 1],
            }
        }.get(code)
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1_bottom_quality_market_known_guard"])
        result = payload["policies"][0]
        breakdown = result["breakdown"]
        self.assertEqual(breakdown["market_regime"]["strong"]["accepted"], 2)
        self.assertEqual(breakdown["market_regime"]["unknown"]["filtered"], 1)
        self.assertEqual(
            breakdown["market_regime"]["unknown"]["filter_reasons"]["bottom_market_unknown"],
            1,
        )
        self.assertEqual(
            breakdown["best_buy_point_type"]["底背驰候选"]["total"],
            2,
        )
        self.assertEqual(
            breakdown["best_buy_point_type"]["强势启动候选"]["accepted"],
            1,
        )
        confirmation_bucket_key = next(
            key
            for key in breakdown["confirmations"].keys()
            if "关键位不破" in key and "30min底分型" in key
        )
        self.assertEqual(
            breakdown["confirmations"][confirmation_bucket_key]["filtered"],
            1,
        )
        self.assertEqual(breakdown["confirmations"]["none"]["accepted"], 1)

    def test_run_policy_experiment_metrics_rejects_unknown_policy(self):
        with self.assertRaisesRegex(ValueError, "unsupported policies"):
            run_policy_experiment_metrics(["delay1_v1_not_exists"])

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_run_policy_experiment_metrics_fusion_threshold_scan(
        self,
        iter_snapshot_mock,
        evaluate_mock,
        fetch_mock,
    ):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                ("2026-01-01", "picks_fusion", _make_fusion_pick(best_type="强势启动候选", trend_strength=2.0, volatility=0.05, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=0, code="000001")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=1.6, volatility=0.08, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=1, code="000002")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(best_type="强势启动候选", trend_strength=1.0, volatility=0.08, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=2, code="000003", market_regime="weak")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=1.0, volatility=0.11, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=3, code="000004")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(trend_strength=1.0, volatility=0.11, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=4, code="000005")),
                ("2026-01-01", "picks_fusion", _make_fusion_pick(best_type="强势启动候选", trend_strength=1.0, volatility=0.08, pivot={"ZG": 12, "ZD": 10}, segment={"high": 12, "low": 10}, signal_index=5, code="000006", market_regime="strong")),
                ("2026-01-01", "picks_pure", _make_fusion_pick(code="000007")),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
            "opens": [1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1],
        }
        evaluate_mock.side_effect = [
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 2.0,
                "max_up_3d": 0.5,
                "max_dd_3d": -5.0,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 2.5,
                "max_up_3d": 1.0,
                "max_dd_3d": -4.8,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": -0.5,
                "max_up_3d": -0.5,
                "max_dd_3d": -4.7,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": -1.0,
                "max_up_3d": -1.0,
                "max_dd_3d": -5.5,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 0.5,
                "max_up_3d": 0.5,
                "max_dd_3d": -6.0,
            },
            {
                "t1_close_pct": 1.0,
                "t3_close_pct": 0.7,
                "max_up_3d": 0.5,
                "max_dd_3d": -5.2,
            },
        ]

        payload = run_policy_experiment_metrics(
            [
                "fusion_strict",
                "fusion_strict_startup_rescue_v1",
                "fusion_mid",
                "fusion_loose",
            ],
        )
        self.assertEqual(payload["policies"], [])
        scan = payload.get("fusion_threshold_scan")
        self.assertIsNotNone(scan)
        self.assertIn("profiles", scan)
        self.assertEqual(len(scan["profiles"]), 4)

        strict_profile = next(item for item in scan["profiles"] if item["candidate"] == "fusion_strict")
        rescue_profile = next(
            item for item in scan["profiles"]
            if item["candidate"] == "fusion_strict_startup_rescue_v1"
        )
        mid_profile = next(item for item in scan["profiles"] if item["candidate"] == "fusion_mid")
        loose_profile = next(item for item in scan["profiles"] if item["candidate"] == "fusion_loose")

        self.assertEqual(strict_profile["samples_before"], 6)
        self.assertEqual(strict_profile["samples_after"], 1)
        self.assertEqual(strict_profile["rejected_samples"], 5)
        self.assertEqual(
            strict_profile["reject_reason_distribution"]["trend_strength_below_min"],
            5,
        )
        self.assertEqual(
            strict_profile["reject_reason_distribution"]["volatility_above_max"],
            2,
        )
        self.assertEqual(rescue_profile["samples_after"], 2)
        self.assertEqual(rescue_profile["reject_reason_distribution"]["strong_market_rescue_guard"], 1)
        self.assertEqual(
            rescue_profile["reject_reason_distribution"]["trend_strength_below_min"],
            4,
        )
        self.assertEqual(
            rescue_profile["quality_tier_distribution"],
            {"A": 1, "A-": 1},
        )
        self.assertEqual(
            rescue_profile["expected_horizon_distribution"],
            {"T+1": 1, "T+3": 1},
        )
        self.assertEqual(
            rescue_profile["recommendation_score_bucket_distribution"],
            {"low": 1, "medium": 1},
        )
        self.assertEqual(
            rescue_profile["recommendation_score_summary"]["count"],
            2,
        )
        self.assertEqual(
            rescue_profile["recommendation_score_summary"]["min"],
            57.0,
        )
        self.assertEqual(
            rescue_profile["recommendation_score_summary"]["max"],
            78.0,
        )
        self.assertEqual(
            rescue_profile["recommendation_score_summary"]["mean"],
            67.5,
        )
        self.assertEqual(
            rescue_profile["recommendation_reason_tag_distribution"],
            {
                "标准A类": 1,
                "T+3": 1,
                "启动修复": 1,
                "T+1": 1,
                "需确认": 1,
            },
        )
        rescue_audit = rescue_profile["failure_sample_audit"]
        self.assertEqual(rescue_audit["samples"], 2)
        self.assertEqual(rescue_audit["failed_samples"], 1)
        self.assertEqual(rescue_audit["failure_rate_pct"], 50.0)
        self.assertEqual(rescue_audit["bucket_distribution"]["quality_tier:A-"], 1)
        self.assertEqual(rescue_audit["bucket_distribution"]["expected_horizon:T+1"], 1)
        self.assertEqual(
            rescue_audit["bucket_distribution"]["signal_type:强势启动候选"],
            1,
        )
        self.assertEqual(rescue_audit["bucket_distribution"]["market_env:weak"], 1)
        candidate_conditions = {
            item["condition"]: item
            for item in rescue_audit["candidate_conditions"]
        }
        self.assertEqual(
            candidate_conditions["quality_tier=A-"]["failed_samples"],
            1,
        )
        self.assertEqual(
            candidate_conditions["quality_tier=A-"]["failure_rate_pct"],
            100.0,
        )
        self.assertEqual(
            candidate_conditions["expected_horizon=T+1"]["failed_samples"],
            1,
        )
        self.assertEqual(
            candidate_conditions["expected_horizon=T+1"]["failure_rate_pct"],
            100.0,
        )
        self.assertNotIn("signal_type=强势启动候选", candidate_conditions)
        self.assertEqual(mid_profile["samples_after"], 2)
        self.assertEqual(mid_profile["rejected_samples"], 4)
        self.assertEqual(mid_profile["variant"], "fusion_mid_trend")
        self.assertEqual(
            mid_profile["reject_reason_distribution"]["trend_strength_below_min"],
            4,
        )
        self.assertEqual(loose_profile["samples_after"], 4)
        self.assertEqual(payload["baseline_reference"], "picks_fusion")

        selected = scan["selected"]
        self.assertEqual(selected["candidate"], "fusion_strict_startup_rescue_v1")
        self.assertEqual(selected["accepted"], False)
        self.assertEqual(
            set(scan["rejected"]),
            {"fusion_strict", "fusion_mid", "fusion_loose"},
        )

        self.assertEqual(scan["baseline_metrics"]["samples"], 6)
        self.assertEqual(scan["baseline_metrics"]["t3_mean_before"], 0.7)
        self.assertEqual(scan["baseline_metrics"]["t3_win_rate_before"], 66.7)
        self.assertEqual(scan["baseline_metrics"]["drawdown_mean_before"], -5.2)
        self.assertEqual(scan["execution"]["baseline_rows"], 6)
        self.assertEqual(scan["snapshot_rows"], 6)

        pareto = scan["pareto_frontier"]
        self.assertEqual(set(pareto), {"fusion_mid", "fusion_loose"})

    @patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
    @patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
    @patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
    def test_baseline_excludes_delay1_v1_filtered_samples(self, iter_snapshot_mock, evaluate_mock, fetch_mock):
        iter_snapshot_mock.side_effect = lambda: iter(
            [
                (
                    "2026-01-01",
                    "picks_pure",
                    {
                        "code": "000001",
                        "best_buy_point": {"type": "底背驰候选", "index": 2},
                        "closes": [1, 2, 3],
                    },
                ),
                (
                    "2026-01-02",
                    "picks_pure",
                    {
                        "code": "000002",
                        "best_buy_point": {"type": "强势启动候选", "index": 0},
                        "closes": [1, 2, 3],
                    },
                ),
            ],
        )
        fetch_mock.return_value = {
            "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
            "opens": [1, 1, 1, 1, 1, 1, 1],
            "highs": [1, 1, 1, 1, 1, 1, 1],
            "lows": [1, 1, 1, 1, 1, 1, 1],
            "closes": [1, 1, 1, 1, 1, 1, 1],
        }
        evaluate_mock.return_value = {
            "t1_close_pct": 1.0,
            "t3_close_pct": 1.0,
            "max_up_3d": 0.5,
            "max_dd_3d": -0.2,
        }

        payload = run_policy_experiment_metrics(["delay1_v1"])
        result = payload["policies"][0]
        self.assertEqual(result["coverage"]["baseline_filtered"], 1)
        self.assertEqual(result["coverage"]["baseline_evaluated"], 1)
        self.assertEqual(result["coverage"]["policy_evaluated"], 1)
        self.assertEqual(result["baseline_summary"]["n"], 1)
        self.assertEqual(result["policy_summary"]["n"], 1)

    def test_bootstrap_mean_confidence_interval_is_deterministic(self):
        first = bootstrap_mean_confidence_interval(
            [1.0, 2.0, 3.0, 4.0],
            iterations=300,
            seed=9,
        )
        second = bootstrap_mean_confidence_interval(
            [1.0, 2.0, 3.0, 4.0],
            iterations=300,
            seed=9,
        )
        self.assertEqual(first, second)
        self.assertLess(first["lower"], first["mean"])
        self.assertGreater(first["upper"], first["mean"])

    def test_recall_acceptance_gates_cover_attention_tail_and_stability(self):
        result = evaluate_recall_acceptance_gates(
            baseline_returns=[1.0, 2.0, -1.0, 3.0],
            candidate_returns=[1.5, 2.5, -0.5, 3.5],
            baseline_drawdowns=[-1.0, -2.0, -6.0, -1.0],
            candidate_drawdowns=[-1.0, -2.0, -5.0, -1.0],
            observation_counts=[2, 3, 4, 5, 3],
            selected_thresholds=[1.3, 1.4, 1.4, 1.3, 1.4],
            ordered_thresholds=[1.2, 1.3, 1.4, 1.5],
            bootstrap_iterations=300,
            seed=5,
        )
        self.assertEqual(5, result["threshold_stability"]["stable_folds"])
        self.assertLessEqual(result["attention_p95"], 5)
        self.assertLessEqual(result["tail_risk_delta_pp"], 2)
        self.assertTrue(result["accepted"])


if __name__ == "__main__":
    unittest.main()
