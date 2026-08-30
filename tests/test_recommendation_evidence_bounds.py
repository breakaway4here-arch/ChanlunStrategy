"""RED contracts for bounded recommendation-evidence payloads."""

import json
import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)
from tests.test_recommendation_evidence import (
    _raw_candidate,
    _workspace_daily,
    _workspace_row,
)


REPORT_DATE = "2026-08-28"
MAX_TEXT_ITEMS = 8
MAX_TRAILING_TARGETS = 5
MAX_CANDIDATE_BYTES = 32 * 1024
MAX_TEXT_LENGTH = 512


def _large_candidate_projection():
    """Build a hostile but otherwise valid candidate with oversized lists."""
    def labels(prefix, count=256):
        return ["{}-{:03d}".format(prefix, index) for index in range(count)]

    row = _workspace_row()
    raw = _raw_candidate()
    raw.update({
        "data_status": {
            "daily": "verified",
            "latest_date": REPORT_DATE,
            "source": "market_history_db",
            "stale": False,
            "is_final": True,
        },
        "strategy_input_evidence": {
            "interval": "30m",
            "status": "verified",
            "latest_date": REPORT_DATE,
        },
        "trailing_targets": [
            {"price": index + 1, "pct": index, "label": "target-{:03d}".format(index)}
            for index in range(256)
        ],
        "startup_signals": labels("startup"),
        "confirmations": labels("confirmation"),
        "risk_flags": labels("risk"),
        "risk_reasons": labels("risk-reason"),
        "upgrade_conditions": labels("upgrade"),
        "next_day_conditions": labels("next-day"),
        "confirmation_conditions": labels("confirm"),
        "next_confirmation": labels("next-confirm"),
        "keep_conditions": labels("keep"),
        "retest_conditions": labels("retest"),
        "cancel_conditions": labels("cancel"),
        "invalidation_conditions": labels("invalidate"),
        "decision_engine_v1": {
            "decision_code": "recommend",
            "total_score": 62,
            "structure": {"score": 10, "reasons": labels("structure")},
            "position": {"score": 15, "reasons": labels("position")},
            "sentiment": {"score": 37, "reasons": labels("sentiment")},
        },
    })
    daily = _workspace_daily([row], [raw])
    return build_recommendation_evidence_projection(
        {},
        daily,
    )["views"]["main"][0]


class RecommendationEvidenceBoundsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.candidate = _large_candidate_projection()

    def test_decision_component_reasons_are_bounded(self):
        components = self.candidate["decision_score"]["components"]
        for name, component in components.items():
            with self.subTest(component=name):
                self.assertLessEqual(
                    len(component["reasons"]),
                    MAX_TEXT_ITEMS,
                )

    def test_trailing_targets_are_bounded(self):
        targets = self.candidate["price_evidence"]["trailing_targets"]
        self.assertLessEqual(len(targets), MAX_TRAILING_TARGETS)
        self.assertEqual(
            self.candidate["price_evidence"]["trailing_targets_contract"],
            {
                "max_visible": MAX_TRAILING_TARGETS,
                "input_count": 256,
                "valid_count": 256,
                "visible_count": MAX_TRAILING_TARGETS,
                "omitted_count": 251,
                "truncated": True,
                "reason": "display_payload_limit",
            },
        )

    def test_daily_startup_signals_are_bounded(self):
        signals = self.candidate["daily_structure"]["startup_signals"]
        self.assertLessEqual(len(signals), MAX_TEXT_ITEMS)

    def test_sublevel_confirmations_are_bounded(self):
        confirmations = self.candidate["sublevel_30m"]["confirmations"]
        self.assertLessEqual(len(confirmations), MAX_TEXT_ITEMS)

    def test_risk_labels_are_bounded(self):
        labels = self.candidate["risk_and_next"]["risk_labels"]
        self.assertLessEqual(len(labels), MAX_TEXT_ITEMS)

    def test_condition_items_are_bounded(self):
        conditions = self.candidate["risk_and_next"]
        for name in (
            "next_confirmation",
            "keep_conditions",
            "retest_conditions",
            "cancel_conditions",
            "invalidation_conditions",
        ):
            with self.subTest(condition=name):
                self.assertLessEqual(
                    len(conditions[name]["items"]),
                    MAX_TEXT_ITEMS,
                )

    def test_single_candidate_json_is_smaller_than_ui_payload_budget(self):
        encoded = json.dumps(
            self.candidate,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertLess(len(encoded), MAX_CANDIDATE_BYTES)

    def test_single_oversized_text_is_truncated_with_an_explicit_contract(self):
        row = _workspace_row()
        raw = _raw_candidate()
        raw["best_buy_point"] = {
            "type": "二买",
            "summary": "X" * 100000,
            "signal_date": REPORT_DATE,
        }
        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)

        self.assertLessEqual(max(map(len, strings(candidate))), MAX_TEXT_LENGTH)
        self.assertEqual(candidate["payload_contract"]["status"], "truncated")
        self.assertGreater(
            candidate["payload_contract"]["truncated_text_count"],
            0,
        )
        encoded = json.dumps(candidate, ensure_ascii=False).encode("utf-8")
        self.assertLess(len(encoded), MAX_CANDIDATE_BYTES)


if __name__ == "__main__":
    unittest.main()
