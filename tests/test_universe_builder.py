import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import run as run_module
from chanlun.market_history_store import MarketHistoryStore
from chanlun.universe_builder import (
    UniverseConfig,
    attach_sector_context,
    build_candidate_universe,
    build_sector_groups,
    load_eligible_candidates,
)


def _candidate(index):
    return {
        "code": "{:06d}".format(index),
        "name": "股票{}".format(index),
        "low_position_retrieval_score": float(2000 - index),
        "trend_retrieval_score": float(index),
        "neutral_retrieval_score": float(1000 - abs(500 - index)),
    }


def _bar(ts, close, amount=100_000_000):
    return {
        "ts": ts,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1_000_000,
        "amount": amount,
        "adjustment": "qfq",
        "is_final": True,
        "source_batch": "fixture",
    }


class UniverseBuilderTests(unittest.TestCase):
    def test_low_trend_neutral_quotas_fill_base_without_duplicates(self):
        candidates = [_candidate(index) for index in range(20)]
        config = UniverseConfig(
            low_quota=3,
            trend_quota=3,
            neutral_quota=2,
            base_limit=8,
            overlay_limit=4,
            final_limit=12,
        )

        result = build_candidate_universe(candidates, [], config=config)

        self.assertEqual(len(result["base"]), 8)
        self.assertEqual(len({row["code"] for row in result["base"]}), 8)
        self.assertTrue(all("retrieval_score" in row for row in result["base"]))
        self.assertTrue(
            all("recommendation_score" not in row for row in result["base"])
        )
        self.assertEqual(result["diagnostics"]["base_target"], 8)

    def test_default_base_is_hard_capped_at_800(self):
        candidates = [_candidate(index) for index in range(1000)]

        result = build_candidate_universe(candidates, [])

        self.assertEqual(len(result["base"]), 800)
        self.assertEqual(len(result["final"]), 800)
        self.assertEqual(len({row["code"] for row in result["base"]}), 800)

    def test_overlay_applies_rank_quotas_caps_at_400_and_preserves_base(self):
        candidates = [_candidate(index) for index in range(1600)]
        base_result = build_candidate_universe(candidates, [])
        base_codes = {row["code"] for row in base_result["base"]}
        outside = [row["code"] for row in candidates if row["code"] not in base_codes]
        sectors = []
        for rank in range(1, 21):
            start = (rank - 1) * 40
            sectors.append(
                {
                    "sector_code": "BK{:04d}".format(rank),
                    "sector_name": "板块{}".format(rank),
                    "sector_rank": rank,
                    "codes": outside[start:start + 40],
                }
            )

        result = build_candidate_universe(candidates, sectors)

        self.assertEqual(len(result["base"]), 800)
        self.assertEqual(len(result["overlay"]), 400)
        self.assertEqual(len(result["final"]), 1200)
        self.assertTrue(base_codes.issubset({row["code"] for row in result["final"]}))
        counts = result["diagnostics"]["overlay_by_sector"]
        self.assertEqual(counts["BK0001"], 30)
        self.assertEqual(counts["BK0006"], 20)
        self.assertEqual(counts["BK0011"], 15)

    def test_parent_child_like_high_overlap_sector_is_deduplicated(self):
        candidates = [_candidate(index) for index in range(30)]
        config = UniverseConfig(
            low_quota=2,
            trend_quota=2,
            neutral_quota=0,
            base_limit=4,
            overlay_limit=10,
            final_limit=14,
            sector_top_quota=4,
            sector_mid_quota=4,
            sector_tail_quota=4,
            sector_overlap_dedupe_ratio=0.8,
        )
        sectors = [
            {
                "sector_code": "PARENT",
                "sector_rank": 1,
                "codes": ["000010", "000011", "000012", "000013", "000014"],
            },
            {
                "sector_code": "CHILD",
                "sector_rank": 2,
                "codes": ["000010", "000011", "000012", "000013"],
            },
        ]

        result = build_candidate_universe(candidates, sectors, config=config)

        self.assertIn("CHILD", result["diagnostics"]["deduped_sectors"])
        self.assertNotIn("CHILD", result["diagnostics"]["overlay_by_sector"])

    def test_sector_groups_and_context_reuse_paged_component_snapshot(self):
        sectors = [
            {"code": "BK1", "name": "机器人"},
            {"code": "BK2", "name": "人工智能"},
        ]
        stocks = [
            {
                "code": "000001",
                "sector": "机器人",
                "sector_tags": ["机器人", "人工智能"],
                "sector_rank": 1,
                "sector_flow": 100,
            }
        ]

        groups = build_sector_groups(sectors, stocks)
        enriched = attach_sector_context([_candidate(1)], stocks)

        self.assertEqual(groups[0]["codes"], ["000001"])
        self.assertEqual(groups[1]["codes"], ["000001"])
        self.assertEqual(enriched[0]["sector"], "机器人")
        self.assertEqual(enriched[0]["sector_tags"], ["机器人", "人工智能"])

    def test_as_of_stock_meta_filters_st_delisting_young_and_liquidity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                end = date(2026, 7, 1)
                for offset, code in enumerate(
                    ("600000", "600001", "600002", "600003", "600004")
                ):
                    instrument_id = store.upsert_instrument(
                        "stock", "SH", code, name=code
                    )
                    bars = [
                        _bar(
                            (end - timedelta(days=69 - index)).isoformat(),
                            10 + index * 0.01 + offset,
                            amount=10_000_000 if code == "600004" else 100_000_000,
                        )
                        for index in range(70)
                    ]
                    store.upsert_bars("day", instrument_id, bars, adjustment="qfq")
                    metadata = {
                        "name": code,
                        "is_st": code == "600001",
                        "delisting_risk": code == "600002",
                        "listed_days": 30 if code == "600003" else 500,
                    }
                    store.upsert_stock_meta(
                        instrument_id, "2026-07-01", metadata
                    )
                normal = store.resolve_instrument("stock", "SH", "600000")
                store.upsert_stock_meta(
                    normal["instrument_id"],
                    "2026-07-02",
                    {
                        "name": "600000",
                        "is_st": True,
                        "delisting_risk": False,
                        "listed_days": 501,
                    },
                )

            with MarketHistoryStore(path, readonly=True) as store:
                before = load_eligible_candidates(
                    store,
                    as_of="2026-07-01",
                    min_listed_days=60,
                    min_daily_amount=50_000_000,
                )
                after = load_eligible_candidates(
                    store,
                    as_of="2026-07-02",
                    min_listed_days=60,
                    min_daily_amount=50_000_000,
                )

        self.assertEqual([row["code"] for row in before], ["600000"])
        self.assertEqual(after, [])

    def test_required_date_rejects_stale_latest_bar_and_reports_funnel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                instrument_id = store.upsert_instrument(
                    "stock", "SH", "600000", name="浦发银行"
                )
                end = date(2026, 7, 1)
                store.upsert_bars(
                    "day",
                    instrument_id,
                    [
                        _bar(
                            (end - timedelta(days=69 - index)).isoformat(),
                            10 + index * 0.01,
                        )
                        for index in range(70)
                    ],
                    adjustment="qfq",
                )
                store.upsert_stock_meta(
                    instrument_id,
                    "2026-07-02",
                    {
                        "name": "浦发银行",
                        "is_st": False,
                        "delisting_risk": False,
                        "listed_days": 500,
                    },
                )

            with MarketHistoryStore(path, readonly=True) as store:
                candidates, diagnostics = load_eligible_candidates(
                    store,
                    as_of="2026-07-02",
                    required_date="2026-07-02",
                    min_listed_days=60,
                    min_daily_amount=50_000_000,
                    return_diagnostics=True,
                )

        self.assertEqual(candidates, [])
        self.assertEqual(diagnostics["instrument_count"], 1)
        self.assertEqual(diagnostics["excluded"]["stale_latest_bar"], 1)

    def test_run_activates_full_a_pool_only_after_coverage_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            end = date(2026, 7, 1)
            with MarketHistoryStore(path) as store:
                for offset in range(8):
                    code = "{:06d}".format(offset)
                    instrument_id = store.upsert_instrument(
                        "stock", "SZ", code, name=code
                    )
                    store.upsert_bars(
                        "day",
                        instrument_id,
                        [
                            _bar(
                                (end - timedelta(days=69 - index)).isoformat(),
                                10 + offset + index * 0.01,
                            )
                            for index in range(70)
                        ],
                        adjustment="qfq",
                    )
                    store.upsert_stock_meta(
                        instrument_id,
                        "2026-07-01",
                        {
                            "name": code,
                            "is_st": False,
                            "delisting_risk": False,
                            "listed_days": 500,
                        },
                    )
            existing = [
                {
                    "code": "000000",
                    "sector": "机器人",
                    "sector_tags": ["机器人"],
                    "sector_rank": 1,
                    "sector_flow": 100,
                }
            ]
            quality = {}
            with patch.multiple(
                run_module,
                MARKET_HISTORY_DB_PATH=str(path),
                FULL_A_MIN_ELIGIBLE_COUNT=4,
                FULL_A_LOW_QUOTA=2,
                FULL_A_TREND_QUOTA=2,
                FULL_A_NEUTRAL_QUOTA=0,
                FULL_A_BASE_LIMIT=4,
                FULL_A_OVERLAY_LIMIT=2,
                FULL_A_FINAL_LIMIT=6,
            ):
                selected = run_module._apply_full_a_universe(
                    existing,
                    [{"code": "BK1", "name": "机器人"}],
                    quality,
                    "2026-07-01",
                )

        self.assertGreaterEqual(len(selected), 4)
        self.assertEqual(quality["universe_builder"]["status"], "activated")
        self.assertEqual(
            quality["stock_pool_source"], "full_a_db+sector_overlay"
        )
        self.assertEqual(selected[0]["klines"]["source"], "market_history_db")

    def test_run_keeps_existing_pool_when_database_is_missing(self):
        existing = [{"code": "600000", "name": "浦发银行"}]
        quality = {"stock_pool_source": "sector_components"}
        with patch.object(
            run_module,
            "MARKET_HISTORY_DB_PATH",
            "/definitely/missing/market.sqlite",
        ):
            selected = run_module._apply_full_a_universe(
                existing, [], quality, "2026-07-01"
            )

        self.assertIs(selected, existing)
        self.assertEqual(quality["universe_builder"]["status"], "fallback")
        self.assertEqual(quality["stock_pool_source"], "sector_components")


if __name__ == "__main__":
    unittest.main()
