#!/usr/bin/env python3
"""Generate sanitized mock input for the LLM research material builder.

This is a demo input generator. It mimics an upstream market/candidate snapshot
without exposing real stock codes, names, watchlists, or production data-source
logic. The output schema is compatible with scripts/llm_research_material_builder.py.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date
from pathlib import Path
from typing import Any


SECTOR_THEMES = [
    "semiconductor_cycle",
    "robotics_supply_chain",
    "ai_application",
    "consumer_electronics",
    "innovative_drug_repair",
    "new_energy_rebound",
    "industrial_software",
    "low_altitude_economy",
    "brokerage_beta",
    "military_equipment",
]


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _generate_market(rng: random.Random, run_date: str) -> dict[str, Any]:
    up_count = rng.randint(2100, 3600)
    down_count = rng.randint(1200, 2800)
    index_change = _round(rng.uniform(-0.4, 1.2), 2)
    if index_change >= 0.8 and up_count > down_count:
        risk_preference = "balanced_offense"
    elif index_change <= -0.5 or down_count > up_count:
        risk_preference = "defensive_confirmation_first"
    else:
        risk_preference = "balanced_wait_for_confirmation"

    return {
        "date": run_date,
        "index_name": "BROAD_INDEX",
        "index_change_pct": index_change,
        "up_count": up_count,
        "down_count": down_count,
        "risk_preference": risk_preference,
        "notes": [
            "sanitized_demo_market_snapshot",
            "not_production_data",
        ],
    }


def _generate_sectors(rng: random.Random, sector_count: int) -> list[dict[str, Any]]:
    sectors: list[dict[str, Any]] = []
    for idx in range(1, sector_count + 1):
        theme = SECTOR_THEMES[(idx - 1) % len(SECTOR_THEMES)]
        sectors.append(
            {
                "name": f"SECTOR_{idx:02d}",
                "rank": idx,
                "change_pct": _round(max(0.1, 3.2 - idx * 0.18 + rng.uniform(-0.25, 0.25)), 2),
                "flow": int(max(120_000_000, 5_800_000_000 - idx * 360_000_000 + rng.randint(-80_000_000, 80_000_000))),
                "reason": theme,
            }
        )
    return sectors


def _make_price_path(rng: random.Random, base_price: float, days: int, style_bias: float) -> tuple[list[float], list[float], list[float]]:
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    price = base_price
    for day_index in range(days):
        drift = style_bias + rng.uniform(-0.018, 0.028)
        if day_index == days - 1:
            drift += rng.uniform(0.005, 0.025)
        price = max(2.0, price * (1.0 + drift))
        high = price * (1.0 + rng.uniform(0.005, 0.025))
        low = price * (1.0 - rng.uniform(0.005, 0.025))
        closes.append(_round(price))
        highs.append(_round(max(high, price)))
        lows.append(_round(min(low, price)))
    return closes, highs, lows


def _make_volume_path(rng: random.Random, days: int, sector_rank: int, stock_rank: int) -> tuple[list[int], list[int]]:
    base_volume = max(80, 360 - sector_rank * 8 - stock_rank * 2 + rng.randint(-20, 30))
    volumes: list[int] = []
    amounts: list[int] = []
    for day_index in range(days):
        multiplier = 1.0 + day_index * rng.uniform(0.04, 0.12)
        volume = int(max(30, base_volume * multiplier + rng.randint(-18, 24)))
        avg_price = rng.uniform(8.0, 38.0)
        amount = int(volume * avg_price * 10_000)
        volumes.append(volume)
        amounts.append(amount)
    return volumes, amounts


def _structure_note(sector_rank: int, stock_rank: int) -> str:
    if sector_rank <= 3 and stock_rank <= 5:
        return "low_position_recovery_with_sector_strength"
    if stock_rank <= 8:
        return "short_term_ma_reclaim_wait_confirmation"
    if stock_rank <= 15:
        return "range_repair_watch_confirmation"
    return "theme_related_watch_only"


def _news_risk(stock_rank: int) -> str:
    if stock_rank % 17 == 0:
        return "recent_gain_hot_watch_chasing_risk"
    if stock_rank % 19 == 0:
        return "liquidity_needs_review"
    return ""


def _generate_candidates(
    rng: random.Random,
    sectors: list[dict[str, Any]],
    stocks_per_sector: int,
    kline_days: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    global_index = 1
    for sector in sectors:
        sector_rank = int(sector["rank"])
        for stock_rank in range(1, stocks_per_sector + 1):
            base_price = rng.uniform(6.0, 42.0)
            style_bias = max(-0.006, 0.016 - sector_rank * 0.001 - stock_rank * 0.0003)
            closes, highs, lows = _make_price_path(rng, base_price, kline_days, style_bias)
            volumes, amounts = _make_volume_path(rng, kline_days, sector_rank, stock_rank)
            fund_flow = int(max(-50_000_000, 180_000_000 - sector_rank * 9_000_000 - stock_rank * 2_300_000 + rng.randint(-18_000_000, 30_000_000)))
            main_inflow = int(fund_flow * rng.uniform(0.22, 0.55)) if fund_flow > 0 else int(fund_flow * rng.uniform(0.1, 0.35))

            candidates.append(
                {
                    "code": f"MASKED_{global_index:03d}",
                    "name": f"CANDIDATE_{global_index:03d}",
                    "sector": sector["name"],
                    "closes": closes,
                    "highs": highs,
                    "lows": lows,
                    "volumes": volumes,
                    "amounts": amounts,
                    "fund_flow": fund_flow,
                    "main_inflow": main_inflow,
                    "structure_note": _structure_note(sector_rank, stock_rank),
                    "news_risk": _news_risk(stock_rank),
                    "source_tags": [
                        "mock_sector_top_pool",
                        "mock_recent_kline",
                        "sanitized_candidate",
                    ],
                }
            )
            global_index += 1
    return candidates


def build_mock_input(
    *,
    sector_count: int,
    stocks_per_sector: int,
    kline_days: int,
    seed: int,
    run_date: str,
) -> dict[str, Any]:
    rng = random.Random(seed)
    sectors = _generate_sectors(rng, sector_count)
    return {
        "metadata": {
            "kind": "sanitized_mock_input",
            "schema_version": "llm_material_input.v1",
            "sector_count": sector_count,
            "stocks_per_sector": stocks_per_sector,
            "kline_days": kline_days,
            "seed": seed,
            "disclaimer": "Synthetic data for workflow demonstration only. Not a stock pick.",
        },
        "market": _generate_market(rng, run_date),
        "sectors": sectors,
        "candidates": _generate_candidates(rng, sectors, stocks_per_sector, kline_days),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate sanitized mock input for LLM stock research material.")
    parser.add_argument("--output", type=Path, help="write JSON to this file; stdout when omitted")
    parser.add_argument("--sector-count", type=int, default=10, help="number of mock top sectors")
    parser.add_argument("--stocks-per-sector", type=int, default=20, help="number of mock candidates per sector")
    parser.add_argument("--kline-days", type=int, default=5, help="number of recent daily K-line bars")
    parser.add_argument("--seed", type=int, default=20260706, help="deterministic random seed")
    parser.add_argument("--date", default=date.today().isoformat(), help="snapshot date")
    args = parser.parse_args()

    if args.sector_count <= 0:
        raise SystemExit("--sector-count must be positive")
    if args.stocks_per_sector <= 0:
        raise SystemExit("--stocks-per-sector must be positive")
    if args.kline_days < 2:
        raise SystemExit("--kline-days must be at least 2")

    payload = build_mock_input(
        sector_count=args.sector_count,
        stocks_per_sector=args.stocks_per_sector,
        kline_days=args.kline_days,
        seed=args.seed,
        run_date=args.date,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
