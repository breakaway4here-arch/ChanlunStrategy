"""RED contracts for freshness and bounded sector-fund evidence.

These tests intentionally exercise hostile/stale presentation inputs.  They
must fail until the evidence projection validates date alignment and bounds
the sector-flow evidence it copies into the HTML-only envelope.
"""

import copy
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


def _candidate_section(row=None, raw=None, **daily_fields):
    row = copy.deepcopy(row or _workspace_row())
    raw = copy.deepcopy(raw or _raw_candidate())
    daily = _workspace_daily([row], [raw])
    daily.update(copy.deepcopy(daily_fields))
    return build_recommendation_evidence_projection(
        {},
        daily,
    )["views"]["main"][0]


def _verified_daily_raw(*, dates):
    raw = _raw_candidate()
    raw.update({
        "dates": list(dates),
        "volumes": list(range(1, len(dates) + 1)),
        "data_status": {
            "daily": "verified",
            "latest_date": REPORT_DATE,
            "source": "market_history_db",
            "stale": False,
            "is_final": True,
        },
    })
    return raw


class RecommendationVolumeFreshnessTests(unittest.TestCase):

    def test_volume_date_mismatch_is_missing_even_when_status_claims_latest(self):
        dates = [
            "2026-08-{:02d}".format(day)
            for day in range(9, 28)
        ] + ["2026-08-27"]
        raw = _verified_daily_raw(dates=dates)

        volume = _candidate_section(raw=raw)["volume_and_capital"]["volume"]

        self.assertEqual(volume["status"], "missing")
        self.assertIsNone(volume["current"])

    def test_volume_future_date_is_missing_even_when_status_claims_final(self):
        dates = [
            "2026-08-{:02d}".format(day)
            for day in range(9, 29)
        ] + ["2026-08-29"]
        raw = _verified_daily_raw(dates=dates)

        volume = _candidate_section(raw=raw)["volume_and_capital"]["volume"]

        self.assertEqual(volume["status"], "missing")
        self.assertIsNone(volume["current"])

    def test_extreme_finite_volumes_never_create_infinity(self):
        dates = [
            "2026-08-{:02d}".format(day)
            for day in range(9, 29)
        ]
        raw = _verified_daily_raw(dates=dates)
        raw["volumes"] = [1e308] * len(dates)

        candidate = _candidate_section(raw=raw)
        volume = candidate["volume_and_capital"]["volume"]

        self.assertEqual(volume["status"], "available")
        self.assertEqual(volume["average_5"], 1e308)
        self.assertEqual(volume["average_20"], 1e308)
        json.dumps(candidate, ensure_ascii=False, allow_nan=False)

    def test_pool_quality_future_as_of_does_not_become_current_turnover(self):
        row = _workspace_row()
        row["pool_quality"] = {
            "money20": 174570073.16,
            "liquidity_source": "amounts",
            "quality_evidence_eligible": True,
            "as_of": "2026-08-29T16:00:00+08:00",
        }
        raw = _raw_candidate()
        raw["data_status"] = {
            "daily": "verified",
            "latest_date": REPORT_DATE,
            "source": "market_history_db",
            "stale": False,
            "is_final": True,
        }

        turnover = _candidate_section(row=row, raw=raw)["volume_and_capital"]["turnover"]

        self.assertEqual(turnover["status"], "missing")
        self.assertIsNone(turnover["average_20"])

    def test_stale_or_future_candidate_sector_flow_is_not_current_evidence(self):
        cases = (
            {
                "daily": "verified",
                "latest_date": "2026-08-27",
                "stale": True,
                "is_final": True,
            },
            {
                "daily": "verified",
                "latest_date": "2026-08-29",
                "stale": False,
                "is_final": True,
            },
        )
        for data_status in cases:
            with self.subTest(data_status=data_status):
                raw = _raw_candidate()
                raw.update({
                    "sector_flow": 123456,
                    "sector_rank": 1,
                    "sector_flow_status": "verified_complete",
                    "data_status": data_status,
                })

                flow = _candidate_section(raw=raw)[
                    "volume_and_capital"
                ]["sector_capital_flow"]

                self.assertEqual(flow["status"], "missing")
                self.assertIsNone(flow["net_flow"])

    def test_nonempty_invalid_evidence_dates_fail_closed(self):
        raw = _raw_candidate()
        raw.update({
            "data_status": {
                "daily": "verified",
                "latest_date": REPORT_DATE,
                "stale": False,
                "is_final": True,
            },
            "best_buy_point": {
                "volume_ratio": 1.5,
                "date": "not-a-date",
            },
            "sector_flow": 123456,
            "sector_rank": 1,
            "sector_flow_status": "verified_complete",
            "sector_flow_as_of": "garbage",
        })
        row = _workspace_row()
        row["pool_quality"] = {
            "money20": 174570073.16,
            "liquidity_source": "amounts",
            "quality_evidence_eligible": True,
            "as_of": "not-a-date",
        }

        evidence = _candidate_section(row=row, raw=raw)[
            "volume_and_capital"
        ]

        self.assertIsNone(evidence["volume_ratio"])
        self.assertEqual(evidence["turnover"]["status"], "missing")
        self.assertEqual(
            evidence["sector_capital_flow"]["status"],
            "missing",
        )

    def test_conflicting_duplicate_date_fields_fail_closed(self):
        raw = _raw_candidate()
        raw.update({
            "data_status": {
                "daily": "verified",
                "latest_date": REPORT_DATE,
                "stale": False,
                "is_final": True,
            },
            "best_buy_point": {
                "volume_ratio": 1.5,
                "as_of": "2026-08-28T15:00:00+08:00",
                "date": "2026-08-29",
            },
        })
        row = _workspace_row()
        row["pool_quality"] = {
            "money20": 174570073.16,
            "liquidity_source": "amounts",
            "quality_evidence_eligible": True,
            "as_of": "2026-08-28T15:00:00+08:00",
            "date": "2026-08-29",
        }

        evidence = _candidate_section(row=row, raw=raw)[
            "volume_and_capital"
        ]

        self.assertIsNone(evidence["volume_ratio"])
        self.assertEqual(evidence["turnover"]["status"], "missing")

    def test_sector_flow_conflicting_declared_dates_fail_closed(self):
        for conflicting_field, conflicting_value in (
            ("date", "2026-08-29"),
            ("as_of", "2026-08-29"),
            ("date", "2026-08-28garbage"),
            ("as_of", "2026-08-28garbage"),
        ):
            with self.subTest(
                field=conflicting_field,
                value=conflicting_value,
            ):
                raw = _raw_candidate()
                raw.update({
                    "data_status": {
                        "daily": "verified",
                        "latest_date": REPORT_DATE,
                        "stale": False,
                        "is_final": True,
                    },
                    "sector_flow": 123456,
                    "sector_rank": 1,
                    "sector_flow_status": "verified_complete",
                    "sector_flow_as_of": "2026-08-28T16:00:00+08:00",
                    conflicting_field: conflicting_value,
                })

                flow = _candidate_section(raw=raw)[
                    "volume_and_capital"
                ]["sector_capital_flow"]

                self.assertEqual(flow["status"], "missing")
                self.assertIsNone(flow["net_flow"])


class RecommendationSectorFlowBoundsTests(unittest.TestCase):

    def test_unverified_hierarchy_dedupe_status_never_creates_support(self):
        sector_heat = {
            "schema_version": 1,
            "date": REPORT_DATE,
            "status": "verified_complete",
            "source": "verified-sector-source",
            "items": [{
                "sector_name": "半导体",
                "status": "verified_complete",
                "net_flow": 0,
                "change_pct": 0,
                "rank": 1,
                "source": "verified-sector-source",
                "as_of": "2026-08-28T16:30:00+08:00",
            }],
        }
        for dedupe_status in (
            "partial_check_only",
            "insufficient_evidence",
            "bogus",
        ):
            with self.subTest(dedupe_status=dedupe_status):
                sector = _candidate_section(
                    sector_heat=sector_heat,
                    sector_flow=[{
                        "name": "半导体",
                        "flow": 120000000,
                        "component_coverage": 1,
                        "hierarchy_dedup_status": dedupe_status,
                        "as_of": "2026-08-28T15:00:00+08:00",
                    }],
                )["market_and_sector"]["sector_evidence"]

                self.assertEqual(sector["direction"], "unknown")
                self.assertEqual(sector["supporting_evidence"], [])

    def test_sector_flow_matching_deduplicates_and_caps_supporting_signals(self):
        sector_heat = {
            "schema_version": 1,
            "date": REPORT_DATE,
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
        duplicate = {
            "name": "半导体",
            "flow": 120000000,
            "change_pct": 1.1,
            "rank": 2,
            "component_coverage": 1,
            "hierarchy_dedup_status": "checked_unique",
            "as_of": "2026-08-28T15:00:00+08:00",
        }
        sector_flow = [
            {**copy.deepcopy(duplicate), "source": "feed-a"},
            {**copy.deepcopy(duplicate), "source": "feed-b"},
            copy.deepcopy(duplicate),
            copy.deepcopy(duplicate),
        ] + [
            {
                **copy.deepcopy(duplicate),
                "flow": 130000000 + offset * 1000000,
                "rank": 3 + offset,
            }
            for offset in range(5)
        ]

        sector = _candidate_section(
            sector_heat=sector_heat,
            sector_flow=sector_flow,
        )["market_and_sector"]["sector_evidence"]
        supporting = sector["supporting_evidence"]
        identities = [
            (
                item.get("source"),
                item.get("net_flow"),
                item.get("change_pct"),
                item.get("rank"),
            )
            for item in supporting
        ]

        self.assertLessEqual(len(supporting), 3)
        self.assertEqual(len(identities), len(set(identities)))


if __name__ == "__main__":
    unittest.main()
