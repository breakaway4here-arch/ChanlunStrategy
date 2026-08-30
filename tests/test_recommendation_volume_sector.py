"""Fail-closed contracts for volume, capital, market, and sector evidence."""

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


def _candidate_section(row=None, raw=None, **daily_fields):
    row = copy.deepcopy(row or _workspace_row())
    raw = copy.deepcopy(raw or _raw_candidate())
    daily = _workspace_daily([row], [raw])
    daily.update(copy.deepcopy(daily_fields))
    return build_recommendation_evidence_projection(
        {},
        daily,
    )["views"]["main"][0]


class RecommendationVolumeAndCapitalTests(unittest.TestCase):

    def test_volume_turnover_stock_flow_and_sector_flow_are_distinct(self):
        row = _workspace_row()
        row["pool_quality"] = {
            "volume20": 10.5,
            "volume_ratio20": 1.44,
            "money20": 174570073.16,
            "liquidity_source": "amounts",
            "quality_evidence_eligible": True,
            "as_of": "2026-08-28",
        }
        raw = _raw_candidate()
        raw.update({
            "dates": ["2026-08-{:02d}".format(day) for day in range(9, 29)],
            "volumes": list(range(1, 21)),
            "money20": 174570073.16,
            "sector_flow": 675301216,
            "sector_rank": 15,
            "sector_strength_label": "资金流入TOP15",
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-08-28",
                "source": "market_history_db",
                "stale": False,
                "is_final": True,
            },
            "best_buy_point": {
                "volume_ratio": 1.4,
                "as_of": "2026-08-28",
            },
            "sector_flow_status": "verified_complete",
            "sector_flow_source": "licensed-sector-flow",
            "sector_flow_as_of": "2026-08-28",
        })

        evidence = _candidate_section(row, raw)["volume_and_capital"]

        self.assertEqual(evidence["volume"]["current"], 20)
        self.assertEqual(evidence["volume"]["average_5"], 18)
        self.assertEqual(evidence["volume"]["average_20"], 10.5)
        self.assertEqual(evidence["volume"]["source"], "candidate.volumes")
        self.assertEqual(evidence["volume_ratio"], 1.4)
        self.assertEqual(
            evidence["volume_ratio_source"],
            "candidate.best_buy_point.volume_ratio",
        )
        self.assertEqual(evidence["money20"], 174570073.16)
        self.assertEqual(evidence["money20_text"], "1.75亿")
        self.assertEqual(evidence["money20_kind"], "average_turnover_amount")
        self.assertEqual(evidence["money20_source"], "amounts")
        self.assertEqual(evidence["stock_capital_flow"]["status"], "missing")
        self.assertEqual(evidence["stock_money_flow"], "个股资金证据不足")
        self.assertEqual(
            evidence["stock_capital_flow"]["reason"],
            "individual_stock_fund_source_not_provided",
        )
        self.assertEqual(evidence["sector_capital_flow"]["net_flow"], 675301216)
        self.assertEqual(evidence["sector_money_flow_text"], "6.75亿")
        self.assertEqual(evidence["sector_capital_flow"]["rank"], 15)
        self.assertNotEqual(
            evidence["sector_capital_flow"].get("net_flow"),
            evidence["stock_capital_flow"].get("net_flow"),
        )

    def test_zero_defaults_do_not_become_volume_or_capital_evidence(self):
        row = _workspace_row()
        row["pool_quality"] = {
            "volume20": 0,
            "volume_ratio20": 0,
            "money20": 0,
            "liquidity_source": "",
        }
        raw = _raw_candidate()
        raw.update({
            "volumes": [],
            "money20": 0,
            "sector_flow": 0,
            "sector_rank": 0,
            "best_buy_point": {"volume_ratio": 0},
        })

        evidence = _candidate_section(row, raw)["volume_and_capital"]

        self.assertEqual(evidence["volume"]["status"], "missing")
        self.assertIsNone(evidence["volume"]["current"])
        self.assertIsNone(evidence["volume20"])
        self.assertIsNone(evidence["volume_ratio"])
        self.assertIsNone(evidence["money20"])
        self.assertEqual(evidence["stock_capital_flow"]["status"], "missing")
        self.assertEqual(evidence["sector_capital_flow"]["status"], "missing")


class RecommendationProjectionBoundTests(unittest.TestCase):

    def test_rank_trace_is_compact_and_does_not_copy_arbitrary_arrays(self):
        row = _workspace_row()
        row["rank_trace"] = {
            "base_source": "main",
            "source_count": 1,
            "signal_score": 9.88,
            "entry_score": 16,
            "selected_reason": "主推池单源入榜",
            "large_internal_array": list(range(1000)),
            "alpha_features": {"huge": list(range(1000))},
        }

        rank = _candidate_section(row=row)["rank_evidence"]["rank_trace"]

        self.assertEqual(rank["base_source"], "main")
        self.assertEqual(rank["selected_reason"], "主推池单源入榜")
        self.assertNotIn("large_internal_array", rank)
        self.assertNotIn("alpha_features", rank)


class RecommendationMarketAndSectorTests(unittest.TestCase):

    def _formal_sentiment(self):
        return {
            "version": "v2",
            "date": "2026-08-28",
            "score": 62,
            "label": "偏强",
            "coverage": 1,
            "insufficient": False,
            "components": {
                "breadth": 53.55,
                "limit_ecology": 86.62,
                "index": 37.12,
                "turnover": 52.29,
                "trend": 60.45,
            },
            "evidence": {
                key: {"available": True}
                for key in (
                    "breadth",
                    "limit_ecology",
                    "index",
                    "turnover",
                    "trend",
                )
            },
        }

    def test_formal_market_sentiment_is_copied_without_psy12_override(self):
        evidence = _candidate_section(
            market_sentiment=self._formal_sentiment(),
            psy12={"status": "available", "score": 100},
            psy12_shadow={
                "status": "available",
                "shadow_score_with_psy12": 100,
                "shadow_label": "极强",
            },
        )["market_and_sector"]

        formal = evidence["formal_market_sentiment"]
        self.assertEqual(formal["score"], 62)
        self.assertEqual(formal["label"], "偏强")
        self.assertEqual(formal["components"]["breadth"], 53.55)
        self.assertEqual(formal["source"], "daily.market_sentiment")
        self.assertEqual(evidence["market_sentiment_score"], 62)
        self.assertEqual(evidence["market_label"], "偏强")
        self.assertNotIn("psy12", str(formal).lower())
        self.assertNotEqual(formal["score"], 100)

    def test_missing_formal_sentiment_does_not_fall_back_to_shadow(self):
        evidence = _candidate_section(
            psy12={"status": "available", "score": 100},
            psy12_shadow={
                "status": "available",
                "shadow_score_with_psy12": 100,
            },
        )["market_and_sector"]

        self.assertEqual(evidence["formal_market_sentiment"]["status"], "missing")
        self.assertIsNone(evidence["market_sentiment_score"])
        self.assertIsNone(evidence["market_label"])

    def test_invalid_formal_sentiment_score_fails_closed(self):
        formal = self._formal_sentiment()
        formal["score"] = 999

        evidence = _candidate_section(
            market_sentiment=formal,
            psy12={"status": "available", "score": 50},
        )["market_and_sector"]

        self.assertEqual(evidence["formal_market_sentiment"]["status"], "missing")
        self.assertIsNone(evidence["market_sentiment_score"])

    def test_formal_sentiment_projection_whitelists_scalar_components(self):
        formal = self._formal_sentiment()
        formal["components"]["large_internal_array"] = list(range(1000))
        formal["evidence"]["large_internal_array"] = {
            "available": True,
            "values": list(range(1000)),
        }

        evidence = _candidate_section(
            market_sentiment=formal,
        )["market_and_sector"]["formal_market_sentiment"]

        self.assertNotIn("large_internal_array", evidence["components"])
        self.assertNotIn("large_internal_array", evidence["evidence"])

    def test_partial_sector_evidence_stays_unknown_not_fund_support(self):
        row = _workspace_row()
        daily_sector = {
            "schema_version": 1,
            "date": "2026-08-28",
            "status": "verified_partial",
            "source": "verified-sector-source",
            "items": [{
                "sector_name": "半导体",
                "status": "verified_partial",
                "net_flow": 900000000,
                "change_pct": 3.2,
                "rank": 1,
                "component_coverage": 1,
                "hierarchy_dedup_status": "checked_unique",
                "source": "verified-sector-source",
                "as_of": "2026-08-28T16:30:00+08:00",
            }],
        }

        evidence = _candidate_section(
            row=row,
            market_sentiment=self._formal_sentiment(),
            sector_heat=daily_sector,
        )["market_and_sector"]

        sector = evidence["sector_evidence"]
        self.assertEqual(sector["status"], "partial")
        self.assertEqual(sector["direction"], "unknown")
        self.assertIsNone(evidence["sector_support"])
        self.assertNotIn("资金流入支持", evidence["summary"])
        self.assertEqual(sector["net_flow"], 900000000)

    def test_complete_item_under_partial_heat_stays_unknown(self):
        sector_heat = {
            "schema_version": 1,
            "date": "2026-08-28",
            "as_of": "2026-08-28T16:30:00+08:00",
            "status": "verified_partial",
            "source": "verified-sector-source",
            "items": [{
                "sector_name": "半导体",
                "status": "verified_complete",
                "net_flow": 900000000,
                "change_pct": 3.2,
                "rank": 1,
                "component_coverage": 1,
                "hierarchy_dedup_status": "checked_unique",
                "source": "verified-sector-source",
                "as_of": "2026-08-28T16:30:00+08:00",
            }],
        }

        evidence = _candidate_section(
            market_sentiment=self._formal_sentiment(),
            sector_heat=sector_heat,
        )["market_and_sector"]

        self.assertEqual(evidence["sector_evidence"]["status"], "partial")
        self.assertEqual(evidence["sector_evidence"]["direction"], "unknown")
        self.assertIsNone(evidence["sector_support"])

    def test_future_sector_heat_or_item_fails_closed(self):
        base = {
            "schema_version": 1,
            "date": "2026-08-28",
            "as_of": "2026-08-28T16:30:00+08:00",
            "status": "verified_complete",
            "source": "verified-sector-source",
            "items": [{
                "sector_name": "半导体",
                "status": "verified_complete",
                "net_flow": 900000000,
                "change_pct": 3.2,
                "rank": 1,
                "source": "verified-sector-source",
                "as_of": "2026-08-28T16:30:00+08:00",
            }],
        }
        cases = []
        future_heat = copy.deepcopy(base)
        future_heat["date"] = "2026-08-29"
        cases.append(future_heat)
        conflicting_heat = copy.deepcopy(base)
        conflicting_heat["as_of"] = "2026-08-29T09:30:00+08:00"
        cases.append(conflicting_heat)
        future_item = copy.deepcopy(base)
        future_item["items"][0]["as_of"] = "2026-08-29T09:30:00+08:00"
        cases.append(future_item)
        conflicting_item = copy.deepcopy(base)
        conflicting_item["items"][0]["date"] = "2026-08-29"
        cases.append(conflicting_item)

        for sector_heat in cases:
            with self.subTest(sector_heat=sector_heat):
                evidence = _candidate_section(
                    market_sentiment=self._formal_sentiment(),
                    sector_heat=sector_heat,
                )["market_and_sector"]
                self.assertEqual(evidence["sector_evidence"]["status"], "missing")
                self.assertEqual(evidence["sector_evidence"]["direction"], "unknown")
                self.assertIsNone(evidence["sector_support"])

    def test_future_sector_outflow_does_not_create_disagreement(self):
        sector_heat = {
            "schema_version": 1,
            "date": "2026-08-28",
            "as_of": "2026-08-28T16:30:00+08:00",
            "status": "verified_complete",
            "source": "verified-sector-source",
            "items": [{
                "sector_name": "半导体",
                "status": "verified_complete",
                "net_flow": 900000000,
                "change_pct": 3.2,
                "rank": 1,
                "component_coverage": 1,
                "hierarchy_dedup_status": "checked_unique",
                "source": "verified-sector-source",
                "as_of": "2026-08-28T16:30:00+08:00",
            }],
        }
        future_outflow = [{
            "name": "半导体",
            "flow": -200000000,
            "change_pct": -0.5,
            "component_coverage": 1,
            "hierarchy_dedup_status": "checked_unique",
            "as_of": "2026-08-29T09:30:00+08:00",
        }]

        evidence = _candidate_section(
            market_sentiment=self._formal_sentiment(),
            sector_heat=sector_heat,
            sector_outflow=future_outflow,
        )["market_and_sector"]

        self.assertEqual(evidence["sector_evidence"]["direction"], "support")
        self.assertEqual(evidence["sector_evidence"]["opposing_evidence"], [])

    def test_positive_and_negative_sector_evidence_merge_to_disagreement(self):
        row = _workspace_row()
        sector_heat = {
            "schema_version": 1,
            "date": "2026-08-28",
            "status": "verified_complete",
            "source": "verified-sector-source",
            "items": [{
                "sector_name": "半导体",
                "status": "verified_complete",
                "net_flow": 900000000,
                "change_pct": 3.2,
                "rank": 1,
                "component_coverage": 1,
                "hierarchy_dedup_status": "checked_unique",
                "source": "verified-sector-source",
                "as_of": "2026-08-28T16:30:00+08:00",
            }],
        }
        sector_outflow = [{
            "name": "半导体",
            "flow": -200000000,
            "change_pct": -0.5,
            "component_coverage": 1,
            "hierarchy_dedup_status": "checked_unique",
            "as_of": "2026-08-28T16:30:00+08:00",
        }]

        evidence = _candidate_section(
            row=row,
            market_sentiment=self._formal_sentiment(),
            sector_heat=sector_heat,
            sector_outflow=sector_outflow,
        )["market_and_sector"]

        sector = evidence["sector_evidence"]
        self.assertEqual(sector["status"], "available")
        self.assertEqual(sector["direction"], "disagreement")
        self.assertEqual(evidence["sector_state"], "分歧")
        self.assertIsNone(evidence["sector_support"])
        self.assertIsNone(evidence["sector_risk"])
        self.assertTrue(sector["supporting_evidence"])
        self.assertTrue(sector["opposing_evidence"])


if __name__ == "__main__":
    unittest.main()
