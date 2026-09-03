"""Low-cost full-A retrieval layer, separate from recommendation decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .market_history_store import MarketHistoryStore


@dataclass(frozen=True)
class UniverseConfig:
    low_quota: int = 350
    trend_quota: int = 350
    neutral_quota: int = 100
    base_limit: int = 800
    overlay_limit: int = 400
    final_limit: int = 1200
    sector_top_quota: int = 30
    sector_mid_quota: int = 20
    sector_tail_quota: int = 15
    sector_overlap_dedupe_ratio: float = 0.8


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _mean(values: Sequence[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _feature_scores(rows: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    closes = [float(row["close"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    volumes = [float(row["volume"]) for row in rows]
    amounts = [float(row["amount"]) for row in rows]
    close = closes[-1]
    window_low = min(lows[-60:])
    window_high = max(highs[-60:])
    position = (
        (close - window_low) / (window_high - window_low)
        if window_high > window_low
        else 0.5
    )
    ma5 = _mean(closes[-5:])
    ma10 = _mean(closes[-10:])
    ma20 = _mean(closes[-20:])
    previous_ma5 = _mean(closes[-6:-1])
    pullback = 1.0 - _clamp(abs(close / ma20 - 1.0) / 0.10) if ma20 else 0.0
    recent_volume = _mean(volumes[-3:])
    prior_volume = _mean(volumes[-13:-3])
    contraction = _clamp(1.5 - recent_volume / prior_volume) if prior_volume else 0.0
    volume_ratio = recent_volume / prior_volume if prior_volume else 0.0
    prior_amount = _mean(amounts[-6:-1])
    amount_ratio = amounts[-1] / prior_amount if prior_amount else 0.0
    return5 = close / closes[-6] - 1.0 if len(closes) >= 6 and closes[-6] else 0.0
    return20 = close / closes[-21] - 1.0 if len(closes) >= 21 and closes[-21] else 0.0
    breakout_reference = max(highs[-21:-1]) if len(highs) >= 21 else max(highs[:-1])
    distance_from_reference = (
        (close / breakout_reference - 1.0) * 100.0
        if breakout_reference
        else 0.0
    )
    breakout = _clamp((close / breakout_reference - 0.97) / 0.08) if breakout_reference else 0.0
    ma_structure = (
        1.0 if close >= ma5 >= ma10 >= ma20 else
        0.6 if close >= ma10 >= ma20 else
        0.2 if close >= ma20 else 0.0
    )
    momentum5 = _clamp((return5 + 0.03) / 0.12)
    momentum20 = _clamp((return20 + 0.08) / 0.30)
    volume_start = _clamp((volume_ratio - 0.8) / 1.2)
    average_amount = _mean(amounts[-5:])
    liquidity = _clamp(
        math.log1p(max(average_amount, 0.0)) / math.log1p(1_000_000_000)
    )
    low_score = 100.0 * (
        0.35 * (1.0 - _clamp(position))
        + 0.20 * pullback
        + 0.15 * contraction
        + 0.20 * max(momentum5, volume_start)
        + 0.10 * liquidity
    )
    trend_score = 100.0 * (
        0.30 * breakout
        + 0.25 * ma_structure
        + 0.20 * momentum20
        + 0.15 * volume_start
        + 0.10 * liquidity
    )
    neutral_score = 100.0 * (0.75 * liquidity + 0.25 * pullback)
    return {
        "low_position_retrieval_score": round(low_score, 6),
        "trend_retrieval_score": round(trend_score, 6),
        "neutral_retrieval_score": round(neutral_score, 6),
        "average_amount_5d": average_amount,
        "position_60d": position,
        "return_5d": return5,
        "return_20d": return20,
        "volume_ratio_3v10": volume_ratio,
        "amount_ratio_1v5": amount_ratio,
        "distance_from_reference_pct": distance_from_reference,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "close": close,
        "ema5_slope": ma5 - previous_ma5,
        "ma_gap_pct": (
            (ma5 / ma10 - 1.0) * 100.0 if ma10 else 0.0
        ),
        "ma_direction": (
            "up" if ma5 >= ma10 >= ma20 else
            "down" if ma5 <= ma10 <= ma20 else
            "mixed"
        ),
    }


def _rows_to_kline(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "dates": [row["ts"] for row in rows],
        "opens": np.array([row["open"] for row in rows], dtype=float),
        "highs": np.array([row["high"] for row in rows], dtype=float),
        "lows": np.array([row["low"] for row in rows], dtype=float),
        "closes": np.array([row["close"] for row in rows], dtype=float),
        "volumes": np.array([row["volume"] for row in rows], dtype=float),
        "amounts": np.array([row["amount"] for row in rows], dtype=float),
        "source": "market_history_db",
        "adjustment": str(rows[-1]["adjustment"]),
        "_data_status": {
            "daily": "verified",
            "latest_date": str(rows[-1]["ts"]).split(" ")[0],
            "source": "market_history_db",
            "bars": len(rows),
            "stale": False,
            "is_final": bool(rows[-1]["is_final"]),
            "adjustment": str(rows[-1]["adjustment"]),
        },
    }


def load_eligible_candidates(
    store: MarketHistoryStore,
    as_of: str,
    min_listed_days: int,
    min_daily_amount: float,
    minimum_bars: int = 60,
    lookback_bars: int = 120,
    required_date: Optional[str] = None,
    return_diagnostics: bool = False,
    audit_records: Optional[List[Dict[str, Any]]] = None,
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    """Load an as-of-safe eligible universe and compute retrieval-only features."""
    instruments = store.list_instruments(asset_type="stock")
    ids = [int(row["instrument_id"]) for row in instruments]
    metadata = store.query_stock_meta_many(ids, as_of=as_of)
    rows_by_id = store.query_bars_many(
        "day", ids, as_of=as_of, limit=lookback_bars
    )
    candidates = []
    excluded = {
        "missing_meta": 0,
        "st_or_delisting": 0,
        "listed_days": 0,
        "insufficient_bars": 0,
        "nonfinal_bars": 0,
        "stale_latest_bar": 0,
        "low_liquidity": 0,
    }
    for instrument in instruments:
        instrument_id = int(instrument["instrument_id"])
        meta = metadata.get(instrument_id)
        rows = rows_by_id.get(instrument_id, [])
        audit = {
            "code": instrument["code"],
            "name": (
                (meta or {}).get("name")
                or instrument.get("name")
                or instrument["code"]
            ),
            "exchange": instrument["exchange"],
            "asset_type": instrument["asset_type"],
            "stock_meta_asof": meta or {},
            "eligibility_passed": False,
            "eligibility_failure_reason": "",
            "data_quality": {
                "daily": "verified" if rows else "missing",
                "bars": len(rows),
                "latest_date": (
                    str(rows[-1]["ts"]).split(" ", 1)[0] if rows else ""
                ),
                "is_final": (
                    bool(rows[-1]["is_final"]) if rows else False
                ),
            },
        }
        if len(rows) >= int(minimum_bars):
            try:
                audit.update(_feature_scores(rows))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass

        def reject(reason: str) -> None:
            audit["eligibility_failure_reason"] = reason
            if audit_records is not None:
                audit_records.append(dict(audit))

        if not meta:
            excluded["missing_meta"] += 1
            reject("missing_meta")
            continue
        if meta.get("is_st") is True or meta.get("delisting_risk") is True:
            excluded["st_or_delisting"] += 1
            reject("st_or_delisting")
            continue
        try:
            listed_days = int(meta.get("listed_days"))
        except (TypeError, ValueError):
            excluded["listed_days"] += 1
            reject("listed_days")
            continue
        if listed_days < int(min_listed_days):
            excluded["listed_days"] += 1
            reject("listed_days")
            continue
        if len(rows) < int(minimum_bars):
            excluded["insufficient_bars"] += 1
            reject("insufficient_bars")
            continue
        if not all(bool(row["is_final"]) for row in rows):
            excluded["nonfinal_bars"] += 1
            reject("nonfinal_bars")
            continue
        latest_date = str(rows[-1]["ts"]).split(" ", 1)[0]
        if required_date is not None and latest_date != str(required_date):
            excluded["stale_latest_bar"] += 1
            reject("stale_latest_bar")
            continue
        average_amount = _mean([float(row["amount"]) for row in rows[-5:]])
        if average_amount < float(min_daily_amount):
            excluded["low_liquidity"] += 1
            audit["average_amount_5d"] = average_amount
            reject("low_liquidity")
            continue
        scores = _feature_scores(rows)
        kline = _rows_to_kline(rows)
        previous_close = float(rows[-2]["close"]) if len(rows) >= 2 else 0.0
        change_pct = (
            (float(rows[-1]["close"]) / previous_close - 1.0) * 100.0
            if previous_close
            else 0.0
        )
        candidate = {
            "code": instrument["code"],
            "name": meta.get("name") or instrument.get("name") or instrument["code"],
            "exchange": instrument["exchange"],
            "asset_type": instrument["asset_type"],
            "stock_meta_asof": meta,
            "industry": str(meta.get("industry") or "").strip(),
            "sector": str(meta.get("industry") or "").strip(),
            "market_cap": meta.get("market_cap"),
            "circulating_market_cap": meta.get("circulating_market_cap"),
            "float_market_cap": (
                meta.get("float_market_cap")
                if meta.get("float_market_cap") is not None
                else meta.get("circulating_market_cap")
            ),
            "klines": kline,
            "data_status": kline["_data_status"],
            "amount": average_amount,
            "amounts": np.array([row["amount"] for row in rows], dtype=float),
            "change_pct": change_pct,
        }
        candidate.update(scores)
        candidates.append(candidate)
        audit.update(candidate)
        audit["eligibility_passed"] = True
        if audit_records is not None:
            audit_records.append(audit)
    candidates = sorted(candidates, key=lambda row: row["code"])
    diagnostics = {
        "as_of": str(as_of),
        "required_date": str(required_date or ""),
        "instrument_count": len(instruments),
        "eligible_count": len(candidates),
        "excluded": excluded,
    }
    if return_diagnostics:
        return candidates, diagnostics
    return candidates


def _ranked(
    candidates: Sequence[Mapping[str, Any]], score_field: str
) -> List[Mapping[str, Any]]:
    return sorted(
        candidates,
        key=lambda row: (-float(row.get(score_field, 0.0)), str(row.get("code", ""))),
    )


def _sector_quota(rank: int, config: UniverseConfig) -> int:
    if rank <= 5:
        return config.sector_top_quota
    if rank <= 10:
        return config.sector_mid_quota
    return config.sector_tail_quota


def build_sector_groups(
    sectors: Sequence[Mapping[str, Any]],
    sector_stocks: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Build overlay memberships from the already paged sector component pool."""
    codes_by_sector: Dict[str, set] = {}
    for stock in sector_stocks:
        code = str(stock.get("code") or "")
        names = []
        primary = str(stock.get("sector") or "")
        if primary:
            names.append(primary)
        tags = stock.get("sector_tags")
        if isinstance(tags, (list, tuple)):
            names.extend(str(value) for value in tags if str(value))
        for name in names:
            codes_by_sector.setdefault(name, set()).add(code)

    groups = []
    for rank, sector in enumerate(sectors, start=1):
        name = str(sector.get("name") or sector.get("sector_name") or "")
        code = str(sector.get("code") or sector.get("sector_code") or name)
        groups.append({
            "sector_code": code,
            "sector_name": name,
            "sector_rank": int(sector.get("sector_rank") or rank),
            "canonical_sector_code": sector.get("canonical_sector_code"),
            "parent_sector_code": sector.get("parent_sector_code"),
            "dedupe_key": sector.get("dedupe_key"),
            "codes": sorted(codes_by_sector.get(name, set())),
        })
    return groups


def attach_sector_context(
    candidates: Sequence[Mapping[str, Any]],
    sector_stocks: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach sector/live snapshot fields without replacing canonical DB bars."""
    context_by_code = {
        str(row.get("code") or ""): row
        for row in sector_stocks
        if str(row.get("code") or "")
    }
    context_fields = (
        "sector",
        "sector_tags",
        "sector_rank",
        "sector_flow",
        "sector_strength_label",
        "market_cap",
        "circulating_market_cap",
        "float_market_cap",
    )
    enriched = []
    for candidate in candidates:
        row = dict(candidate)
        context = context_by_code.get(str(row.get("code") or ""), {})
        for field in context_fields:
            context_value = context.get(field)
            if context_value not in (None, "", []):
                row[field] = context[field]
        row.setdefault("sector", "")
        row.setdefault("sector_tags", [])
        row.setdefault("sector_rank", None)
        row.setdefault("sector_flow", None)
        row.setdefault("sector_strength_label", "")
        enriched.append(row)
    return enriched


def _dedupe_sectors(
    sector_groups: Sequence[Mapping[str, Any]],
    ratio: float,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    kept = []
    deduped = []
    seen_keys = set()
    for raw in sorted(
        sector_groups,
        key=lambda row: (
            int(row.get("sector_rank") or 9999),
            str(row.get("sector_code") or ""),
        ),
    ):
        row = dict(raw)
        code = str(row.get("sector_code") or row.get("sector_name") or "")
        codes = set(str(value) for value in row.get("codes", []) if str(value))
        explicit_key = str(
            row.get("dedupe_key")
            or row.get("canonical_sector_code")
            or row.get("parent_sector_code")
            or ""
        )
        if explicit_key and explicit_key in seen_keys:
            deduped.append(code)
            continue
        duplicate = False
        for previous in kept:
            previous_codes = previous["_code_set"]
            denominator = min(len(codes), len(previous_codes))
            overlap = (
                len(codes & previous_codes) / denominator if denominator else 0.0
            )
            if overlap >= float(ratio):
                duplicate = True
                break
        if duplicate:
            deduped.append(code)
            continue
        row["_code_set"] = codes
        kept.append(row)
        if explicit_key:
            seen_keys.add(explicit_key)
    return kept, deduped


def build_candidate_universe(
    candidates: Sequence[Mapping[str, Any]],
    sector_groups: Sequence[Mapping[str, Any]],
    config: Optional[UniverseConfig] = None,
) -> Dict[str, Any]:
    config = config or UniverseConfig()
    normalized = []
    by_code = {}
    for raw in candidates:
        code = str(raw.get("code") or "")
        if not code or code in by_code:
            continue
        row = dict(raw)
        row["low_position_retrieval_score"] = float(
            row.get("low_position_retrieval_score", 0.0)
        )
        row["trend_retrieval_score"] = float(
            row.get("trend_retrieval_score", 0.0)
        )
        row["neutral_retrieval_score"] = float(
            row.get("neutral_retrieval_score", 0.0)
        )
        row["retrieval_score"] = max(
            row["low_position_retrieval_score"],
            row["trend_retrieval_score"],
        )
        row["retrieval_sources"] = []
        normalized.append(row)
        by_code[code] = row

    selected = []
    selected_codes = set()

    def add_top(rows, quota, source):
        for row in list(rows)[:int(quota)]:
            code = row["code"]
            if source not in row["retrieval_sources"]:
                row["retrieval_sources"].append(source)
            if code in selected_codes:
                continue
            selected.append(row)
            selected_codes.add(code)

    add_top(
        _ranked(normalized, "low_position_retrieval_score"),
        config.low_quota,
        "low_position",
    )
    add_top(
        _ranked(normalized, "trend_retrieval_score"),
        config.trend_quota,
        "trend",
    )
    add_top(
        _ranked(normalized, "neutral_retrieval_score"),
        config.neutral_quota,
        "neutral",
    )
    base_target = min(int(config.base_limit), len(normalized))
    if len(selected) < base_target:
        for row in sorted(
            normalized,
            key=lambda item: (-item["retrieval_score"], item["code"]),
        ):
            if len(selected) >= base_target:
                break
            if "score_fill" not in row["retrieval_sources"]:
                row["retrieval_sources"].append("score_fill")
            if row["code"] in selected_codes:
                continue
            selected.append(row)
            selected_codes.add(row["code"])
    base = [dict(row) for row in selected[:base_target]]
    for rank, row in enumerate(base, start=1):
        row["retrieval_pool"] = "base"
        row["base_rank"] = rank
    base_codes = {row["code"] for row in base}

    sectors, deduped_sectors = _dedupe_sectors(
        sector_groups, config.sector_overlap_dedupe_ratio
    )
    overlay = []
    overlay_codes = set()
    overlay_by_sector = {}
    for sector in sectors:
        if len(overlay) >= int(config.overlay_limit):
            break
        sector_code = str(
            sector.get("sector_code") or sector.get("sector_name") or ""
        )
        rank = int(sector.get("sector_rank") or 9999)
        available = [
            by_code[code]
            for code in sector["_code_set"]
            if code in by_code and code not in base_codes and code not in overlay_codes
        ]
        quota = min(
            _sector_quota(rank, config),
            int(config.overlay_limit) - len(overlay),
        )
        chosen = []
        chosen_codes = set()
        low_quota = (quota + 1) // 2
        trend_quota = quota // 2
        for rows, target in (
            (_ranked(available, "low_position_retrieval_score"), low_quota),
            (_ranked(available, "trend_retrieval_score"), trend_quota),
        ):
            added = 0
            for row in rows:
                if added >= target:
                    break
                if row["code"] in chosen_codes:
                    continue
                chosen.append(row)
                chosen_codes.add(row["code"])
                added += 1
        if len(chosen) < quota:
            for row in sorted(
                available,
                key=lambda item: (-item["retrieval_score"], item["code"]),
            ):
                if len(chosen) >= quota:
                    break
                if row["code"] in chosen_codes:
                    continue
                chosen.append(row)
                chosen_codes.add(row["code"])
        for row in chosen:
            item = dict(row)
            item["retrieval_pool"] = "overlay"
            item["overlay_sector_code"] = sector_code
            item["overlay_sector_name"] = sector.get("sector_name", "")
            item["overlay_sector_rank"] = rank
            overlay.append(item)
            overlay_codes.add(item["code"])
        if chosen:
            overlay_by_sector[sector_code] = len(chosen)

    max_final = max(len(base), int(config.final_limit))
    overlay = overlay[:max(0, max_final - len(base))]
    final = base + overlay
    return {
        "base": base,
        "overlay": overlay,
        "final": final,
        "diagnostics": {
            "eligible_count": len(normalized),
            "base_target": base_target,
            "base_count": len(base),
            "overlay_count": len(overlay),
            "final_count": len(final),
            "overlay_by_sector": overlay_by_sector,
            "deduped_sectors": deduped_sectors,
        },
    }
