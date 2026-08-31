"""RED contracts for formal recommendation evidence provenance.

These tests intentionally describe the remaining fail-closed boundaries before
the production projection is tightened:

* the applicable horizon must come from the formal decision contract; a raw
  candidate declaration cannot override a conflicting contract value;
* formal market sentiment needs an explicit complete evidence declaration,
  rather than treating a score/label/date tuple as verified by itself.
"""

import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)
from tests.test_recommendation_evidence import (
    _raw_candidate,
    _workspace_daily,
    _workspace_row,
)


class RecommendationEvidenceContractGuardTests(unittest.TestCase):

    def test_formal_horizon_is_authoritative_and_conflicts_fail_closed(self):
        row = _workspace_row()
        row["formal_decision_contract"]["intended_horizon"] = "T+5"
        raw = _raw_candidate()
        raw["intended_horizon"] = 3

        candidate = build_recommendation_evidence_projection(
            {},
            _workspace_daily([row], [raw]),
        )["views"]["main"][0]

        summary = candidate["summary"]
        self.assertIsNone(summary["applicable_horizon"])
        self.assertEqual(summary["applicable_horizon_status"], "conflict")
        self.assertEqual(
            summary["audit_reasons"]["intended_horizon"],
            "conflict",
        )

    def test_market_sentiment_requires_complete_explicit_evidence(self):
        row = _workspace_row()
        raw = _raw_candidate()
        daily = _workspace_daily([row], [raw])
        daily["market_sentiment"] = {
            "date": "2026-08-28",
            "score": 62,
            "label": "偏强",
            # Missing insufficient=false, coverage, components, evidence and
            # source must not be interpreted as a verified market result.
        }

        projection = build_recommendation_evidence_projection(
            {},
            daily,
        )
        candidate = projection["views"]["main"][0]

        sentiment = candidate["market_and_sector"]["formal_market_sentiment"]
        self.assertEqual(sentiment["status"], "missing")
        self.assertEqual(
            sentiment["reason"],
            "formal_market_sentiment_not_provided",
        )
        top_level = projection["market_sentiment"]["formal_contract"]
        self.assertEqual(top_level["status"], "missing")
        self.assertEqual(
            top_level["reason"],
            "formal_market_sentiment_not_provided",
        )

    def test_market_sentiment_rejects_component_availability_conflict(self):
        row = _workspace_row()
        raw = _raw_candidate()
        daily = _workspace_daily([row], [raw])
        components = {
            key: 62 for key in (
                "breadth", "limit_ecology", "index", "turnover", "trend"
            )
        }
        components["trend"] = None
        daily["market_sentiment"] = {
            "version": "v2",
            "date": "2026-08-28",
            "score": 62,
            "label": "偏强",
            "coverage": 1,
            "insufficient": False,
            "components": components,
            "evidence": {
                key: {"available": True}
                for key in components
            },
        }

        sentiment = build_recommendation_evidence_projection(
            {},
            daily,
        )["views"]["main"][0]["market_and_sector"][
            "formal_market_sentiment"
        ]

        self.assertEqual(sentiment["status"], "missing")

    def test_top_level_market_sentiment_contract_preserves_verified_formal_data(self):
        row = _workspace_row()
        raw = _raw_candidate()
        daily = _workspace_daily([row], [raw])
        components = {
            key: 62 for key in (
                "breadth", "limit_ecology", "index", "turnover", "trend"
            )
        }
        daily["market_sentiment"] = {
            "version": "v2",
            "date": "2026-08-28",
            "score": 62,
            "label": "偏强",
            "coverage": 1,
            "insufficient": False,
            "components": components,
            "evidence": {
                key: {"available": True}
                for key in components
            },
        }

        formal = build_recommendation_evidence_projection(
            {},
            daily,
        )["market_sentiment"]["formal_contract"]

        self.assertEqual(formal["status"], "available")
        self.assertEqual(formal["score"], 62)
        self.assertEqual(formal["label"], "偏强")
        self.assertEqual(formal["coverage"], 1)
        self.assertEqual(formal["components"], components)

    def test_market_sentiment_rejects_non_string_text_and_timestamp_dates(self):
        row = _workspace_row()
        raw_candidate = _raw_candidate()
        components = {
            key: 62 for key in (
                "breadth", "limit_ecology", "index", "turnover", "trend"
            )
        }
        base_sentiment = {
            "version": "v2",
            "date": "2026-08-28",
            "score": 62,
            "label": "偏强",
            "coverage": 1,
            "insufficient": False,
            "components": components,
            "evidence": {
                key: {"available": True}
                for key in components
            },
        }

        for field, value in (
            ("label", 2),
            ("version", 2),
            ("date", "2026-08-28T15:00:00+08:00"),
        ):
            daily = _workspace_daily([row], [raw_candidate])
            daily["market_sentiment"] = dict(base_sentiment)
            daily["market_sentiment"][field] = value
            with self.subTest(field=field):
                formal = build_recommendation_evidence_projection(
                    {}, daily
                )["market_sentiment"]["formal_contract"]
                self.assertEqual(formal["status"], "missing")
                self.assertIsNone(formal["score"])


if __name__ == "__main__":
    unittest.main()
