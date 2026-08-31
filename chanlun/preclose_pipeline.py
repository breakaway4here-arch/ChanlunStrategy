"""Isolated, deterministic three-pool orchestration for the 14:45 advisory."""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from datetime import datetime, time as wall_time

import numpy as np

from .candidate_upgrade import upgrade_daily_candidates_with_30min
from .chan_engine import analyze as analyze_chanlun
from .decision_engine import evaluate_stock as evaluate_decision_stock
from .daily_structure_pool import build_daily_structure_pool
from .fusion_admission import apply_fusion_admission
from .h4_t3_pool import build_h4_t3_pool, filter_h4_upstream_candidates
from .market_sentiment import build_market_sentiment
from .next_day_boom import build_next_day_boom_candidates
from .preclose_contract import build_preclose_snapshot
from .scorer import apply_scores
from .right_side_startup import (
    apply_right_side_startup_mode,
    resolve_right_side_startup_mode,
    select_classic_startup_inputs,
)
from .strong_startup import (
    build_strong_startup_pool,
    upgrade_strong_startup_with_30min,
)
from .trend_continuation import (
    build_trend_continuation_pool,
    normalize_trend_candidate,
    upgrade_trend_continuation_with_30min,
)


PRE_CLOSE_STRATEGY_VERSION = "preclose-1445-v2"
EXECUTED_STAGES = (
    "daily_structure",
    "target_30m_confirm",
    "market_context",
    "decision_engine",
    "main_public_view",
    "h4_t3",
    "acceleration",
)


class PrecloseDeadlineExceeded(RuntimeError):
    """Raised internally when the 14:49 output deadline has been reached."""

    def __init__(self, stage, elapsed):
        super().__init__("pre-close deadline exceeded")
        self.stage = str(stage or "")
        self.elapsed = float(elapsed)


@dataclass(frozen=True)
class PreclosePipelineComponents:
    """Injectable pure components; defaults are the production strategy modules."""

    analyze: object = analyze_chanlun
    build_daily_structure_pool: object = build_daily_structure_pool
    upgrade_daily_candidates: object = upgrade_daily_candidates_with_30min
    build_strong_startup_pool: object = build_strong_startup_pool
    upgrade_strong_startup: object = upgrade_strong_startup_with_30min
    build_right_side_startup_pool: object = build_trend_continuation_pool
    upgrade_right_side_startup: object = upgrade_trend_continuation_with_30min
    right_side_startup_mode: object = None
    apply_fusion_admission: object = apply_fusion_admission
    apply_scores: object = apply_scores
    evaluate_stock: object = evaluate_decision_stock
    build_h4_t3_pool: object = build_h4_t3_pool
    build_next_day_boom_candidates: object = build_next_day_boom_candidates
    build_market_sentiment: object = build_market_sentiment


@dataclass(frozen=True)
class PreclosePipelineConfig:
    trade_date: str
    as_of: str
    generated_at: str
    source_sha: str
    run_id: str
    deadline_seconds: float = 240.0
    monotonic: object = time.monotonic

    def __post_init__(self):
        trade_date = _canonical_date(self.trade_date)
        as_of = _parse_datetime(self.as_of)
        generated_at = _parse_datetime(self.generated_at)
        if as_of.date().isoformat() != trade_date:
            raise ValueError("as_of date mismatch")
        if generated_at.date().isoformat() != trade_date:
            raise ValueError("generated_at date mismatch")
        if float(self.deadline_seconds) <= 0 or float(self.deadline_seconds) > 240:
            raise ValueError("deadline_seconds must be in (0, 240]")
        if not callable(self.monotonic):
            raise TypeError("monotonic must be callable")
        if not str(self.source_sha or "").strip():
            raise ValueError("source_sha is required")
        if not str(self.run_id or "").strip():
            raise ValueError("run_id is required")
        object.__setattr__(self, "trade_date", trade_date)
        object.__setattr__(self, "as_of", as_of.isoformat(timespec="seconds"))
        object.__setattr__(
            self, "generated_at", generated_at.isoformat(timespec="seconds")
        )


def _canonical_date(value):
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError("invalid trade_date")
    if parsed.strftime("%Y-%m-%d") != text:
        raise ValueError("invalid trade_date")
    return text


def _parse_datetime(value):
    text = str(value or "").strip().replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _as_list(value):
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def _finite(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _stage_clock(config, diagnostics, started_at, stage, operation):
    elapsed = float(config.monotonic()) - started_at
    if elapsed >= float(config.deadline_seconds):
        raise PrecloseDeadlineExceeded(stage, elapsed)
    stage_started = float(config.monotonic())
    try:
        return operation()
    finally:
        stage_finished = float(config.monotonic())
        diagnostics["executed_stages"].append(stage)
        diagnostics["stage_seconds"][stage] = round(
            max(0.0, stage_finished - stage_started), 6
        )
        elapsed = stage_finished - started_at
        if elapsed >= float(config.deadline_seconds):
            diagnostics["deadline_stage"] = stage
            diagnostics["elapsed_seconds"] = round(elapsed, 6)
            raise PrecloseDeadlineExceeded(stage, elapsed)


def _analyze_kline(component, code, name, kline):
    return component(
        code=code,
        name=name,
        dates=kline["dates"],
        opens=np.asarray(kline["opens"], dtype=float),
        highs=np.asarray(kline["highs"], dtype=float),
        lows=np.asarray(kline["lows"], dtype=float),
        closes=np.asarray(kline["closes"], dtype=float),
        volumes=np.asarray(kline["volumes"], dtype=float),
    )


def _analyze_daily_inputs(market_inputs, components):
    results = []
    failures = []
    rows_by_code = {}
    for row in market_inputs.get("daily") or []:
        if not isinstance(row, dict) or row.get("status") != "available":
            continue
        code = str(row.get("code") or "").strip()
        kline = row.get("klines")
        if not code or not isinstance(kline, dict):
            continue
        rows_by_code[code] = row
        try:
            result = _analyze_kline(
                components.analyze, code, str(row.get("name") or ""), kline
            )
        except Exception as exc:
            failures.append({"code": code, "error": type(exc).__name__})
            continue
        if result is not None:
            results.append(result)
    return results, rows_by_code, failures


def _analyze_30m_inputs(market_inputs, rows_by_code, components):
    results = []
    unavailable = []
    requested = [str(code) for code in (market_inputs.get("target_codes") or [])]
    by_code = market_inputs.get("min30")
    by_code = by_code if isinstance(by_code, dict) else {}
    for code in requested:
        evidence = by_code.get(code)
        evidence = evidence if isinstance(evidence, dict) else {}
        if evidence.get("status") != "available" or not isinstance(
            evidence.get("klines"), dict
        ):
            unavailable.append(code)
            continue
        row = rows_by_code.get(code, {})
        try:
            result = _analyze_kline(
                components.analyze,
                code,
                str(row.get("name") or ""),
                evidence["klines"],
            )
        except Exception:
            unavailable.append(code)
            continue
        if result is None:
            unavailable.append(code)
            continue
        setattr(result, "strategy_input_evidence", {
            "interval": "30m",
            "status": "intraday_available",
            "latest_date": str(evidence.get("latest_date") or ""),
            "latest_ts": str(evidence.get("latest_ts") or ""),
            "stale": False,
            "is_final": False,
            "bar_state": "intraday",
            "as_of": str(evidence.get("as_of") or market_inputs.get("as_of") or ""),
        })
        results.append(result)
    return results, unavailable


def _sector_stocks(rows_by_code):
    output = {}
    for code, source in rows_by_code.items():
        output[code] = {
            key: copy.deepcopy(source.get(key))
            for key in (
                "sector",
                "sector_tags",
                "sector_rank",
                "sector_flow",
                "sector_strength_label",
                "market_cap",
                "circulating_market_cap",
                "float_market_cap",
                "amount",
                "amounts",
            )
            if source.get(key) is not None
        }
    return output


def _merge_sector_metadata(candidates, sector_stocks):
    output = []
    for raw in candidates or []:
        item = dict(raw)
        context = sector_stocks.get(str(item.get("code") or ""), {})
        for key, value in context.items():
            if item.get(key) in (None, "", []):
                item[key] = copy.deepcopy(value)
        output.append(item)
    return output


def _normalize_startup_candidate(candidate):
    item = dict(candidate or {})
    confirmations = list(item.get("confirmations") or [])
    price = _finite(item.get("close"), 0.0)
    best = {
        "type": "强势启动候选",
        "tier": "candidate",
        "category": "A",
        "index": int(item.get("startup_index") or 0),
        "price": price,
        "reason": str(item.get("startup_reason") or ""),
        "strength": "中",
        "source_type": "日线强势启动",
        "confirmed_by": "30min确认",
        "confirmations": confirmations,
        "confirmation_evidence": copy.deepcopy(
            item.get("confirmation_evidence") or {}
        ),
        "change_pct": item.get("change_pct"),
        "volume_ratio": item.get("volume_ratio"),
    }
    item["buy_points"] = [best]
    item["best_buy_point"] = best
    item["resonance"] = {"level": "中", "reason": "30min确认"}
    item["source_channel"] = "low_position"
    item["view"] = "main"
    return item


def _dedupe_candidates(candidates):
    output = []
    seen = set()
    for item in candidates or []:
        code = str((item or {}).get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        output.append(item)
    return output


def _build_daily_state(daily_results, sector_stocks, components):
    pure_pool, daily_diagnostics = components.build_daily_structure_pool(
        daily_results, sector_stocks, mode="pure"
    )
    classic_input_state = select_classic_startup_inputs(
        daily_results, pure_pool
    )
    startup_seeds, startup_watchlist, startup_diagnostics = (
        components.build_strong_startup_pool(
            classic_input_state["rows"], sector_stocks
        )
    )
    right_mode = resolve_right_side_startup_mode(
        components.right_side_startup_mode
    )
    if right_mode == "off":
        right_seeds, right_watchlist = [], []
        right_diagnostics = {"enabled": False, "mode": "off", "scanned": 0}
    else:
        right_seeds, right_watchlist, right_diagnostics = (
            components.build_right_side_startup_pool(
                daily_results, sector_stocks
            )
        )
        right_diagnostics = dict(right_diagnostics or {})
        right_diagnostics["mode"] = right_mode
        right_diagnostics["independent_input_count"] = len(
            daily_results or []
        )
    startup_diagnostics = dict(startup_diagnostics or {})
    startup_diagnostics["common_upstream"] = classic_input_state[
        "diagnostics"
    ]
    return {
        "pure_pool": _merge_sector_metadata(pure_pool, sector_stocks),
        "startup_seeds": _merge_sector_metadata(startup_seeds, sector_stocks),
        "startup_watchlist": _merge_sector_metadata(
            startup_watchlist, sector_stocks
        ),
        "right_seeds": _merge_sector_metadata(right_seeds, sector_stocks),
        "right_watchlist": _merge_sector_metadata(
            right_watchlist, sector_stocks
        ),
        "right_mode": right_mode,
        "diagnostics": {
            "daily_structure": daily_diagnostics,
            "strong_startup": startup_diagnostics,
            "right_side_daily": right_diagnostics,
        },
    }


def _finish_main_state(daily_state, min30_results, sector_stocks, sh_closes, components):
    pure_confirmed, upgrade_diagnostics = components.upgrade_daily_candidates(
        copy.deepcopy(daily_state["pure_pool"]), min30_results, mode="pure"
    )
    startup_candidates, startup_waiting, startup_upgrade_diagnostics = (
        components.upgrade_strong_startup(
            copy.deepcopy(daily_state["startup_seeds"]), min30_results
        )
    )
    normalized_startup = [
        _normalize_startup_candidate(item) for item in startup_candidates
    ]
    right_candidates, right_waiting, right_upgrade_diagnostics = (
        components.upgrade_right_side_startup(
            copy.deepcopy(daily_state["right_seeds"]), min30_results
        )
    )
    normalized_right = [
        normalize_trend_candidate(item) for item in right_candidates
    ]
    pure_ready = _dedupe_candidates(
        _merge_sector_metadata(
            list(pure_confirmed) + normalized_startup, sector_stocks
        )
    )
    fusion_ready, fusion_diagnostics = components.apply_fusion_admission(
        copy.deepcopy(pure_ready), sh_closes, sector_stocks
    )
    pure_scored = components.apply_scores(
        copy.deepcopy(pure_ready), version="pure"
    )
    fusion_scored = components.apply_scores(
        copy.deepcopy(fusion_ready),
        version="fusion",
        sector_rank_map=[
            {"name": value.get("sector")}
            for value in sector_stocks.values()
            if value.get("sector")
        ],
    )
    existing_fusion_codes = {
        str(item.get("code") or "") for item in fusion_scored
    }
    right_ready = [
        item for item in _dedupe_candidates(_merge_sector_metadata(
            normalized_right, sector_stocks
        ))
        if str(item.get("code") or "") not in existing_fusion_codes
    ]
    right_fusion_scored = []
    right_pure_scored = []
    right_fusion_diagnostics = {"input_count": 0, "output_count": 0}
    if right_ready:
        right_fusion_ready, right_fusion_diagnostics = (
            components.apply_fusion_admission(
                copy.deepcopy(right_ready), sh_closes, sector_stocks
            )
        )
        right_pure_scored = components.apply_scores(
            copy.deepcopy(right_ready), version="pure"
        )
        right_fusion_scored = components.apply_scores(
            copy.deepcopy(right_fusion_ready),
            version="fusion",
            sector_rank_map=[
                {"name": value.get("sector")}
                for value in sector_stocks.values()
                if value.get("sector")
            ],
        )
    right_mode_state = apply_right_side_startup_mode(
        right_fusion_scored,
        existing_candidates=fusion_scored,
        mode=daily_state["right_mode"],
    )
    published_right_fusion = list(right_mode_state["published"])
    published_codes = {
        str(item.get("code") or "") for item in published_right_fusion
    }
    published_right_pure = [
        item for item in right_pure_scored
        if str(item.get("code") or "") in published_codes
    ]
    right_diagnostics = {
        **dict(right_mode_state["diagnostics"]),
        "mode": daily_state["right_mode"],
        "published_codes": [
            str(item.get("code") or "") for item in published_right_fusion
        ],
        "upgrade": right_upgrade_diagnostics,
        "fusion_admission": right_fusion_diagnostics,
        "waiting_count": len(right_waiting),
        "daily_watch_count": len(daily_state["right_watchlist"]),
    }
    return {
        "picks_pure": _merge_sector_metadata(
            list(pure_scored) + published_right_pure, sector_stocks
        ),
        "picks_fusion": _merge_sector_metadata(
            list(fusion_scored) + published_right_fusion, sector_stocks
        ),
        "startup_watchlist": _dedupe_candidates(
            _merge_sector_metadata(
                list(daily_state["startup_watchlist"]) + list(startup_waiting),
                sector_stocks,
            )
        ),
        "diagnostics": {
            **dict(daily_state.get("diagnostics") or {}),
            "candidate_upgrade": upgrade_diagnostics,
            "startup_upgrade": startup_upgrade_diagnostics,
            "fusion_admission": fusion_diagnostics,
            "right_side_startup": right_diagnostics,
        },
    }


def build_preclose_main_pool(
    daily_results,
    min30_results,
    *,
    sector_stocks,
    sh_closes,
    components=None
):
    """Reuse the daily pool, 30m upgrade, fusion admission and unified scores."""

    components = components or PreclosePipelineComponents()
    daily_state = _build_daily_state(
        daily_results, sector_stocks or {}, components
    )
    return _finish_main_state(
        daily_state,
        min30_results,
        sector_stocks or {},
        sh_closes,
        components,
    )


def _derive_stock_bars(market_inputs):
    bars = []
    for row in market_inputs.get("daily") or []:
        if not isinstance(row, dict) or row.get("status") != "available":
            continue
        kline = row.get("klines")
        kline = kline if isinstance(kline, dict) else {}
        closes = _as_list(kline.get("closes"))
        if len(closes) < 2:
            continue
        bars.append({
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
            "prev_close": closes[-2],
            "close": closes[-1],
            "is_st": bool(row.get("is_st")),
            "listing_trade_days": row.get("listing_trade_days"),
        })
    return bars


def _derive_trend(market_inputs):
    eligible = above = 0
    for row in market_inputs.get("daily") or []:
        kline = row.get("klines") if isinstance(row, dict) else None
        closes = _as_list((kline or {}).get("closes")) if isinstance(kline, dict) else []
        values = [_finite(value) for value in closes[-20:]]
        if len(values) != 20 or any(value is None for value in values):
            continue
        eligible += 1
        above += values[-1] >= sum(values) / len(values)
    return {"above_ma20_ratio": above / float(eligible) if eligible else None}


def _derive_turnover(market_inputs):
    total = 0.0
    available = False
    for row in market_inputs.get("daily") or []:
        kline = row.get("klines") if isinstance(row, dict) else None
        amounts = _as_list((kline or {}).get("amounts")) if isinstance(kline, dict) else []
        value = _finite(amounts[-1] if amounts else row.get("amount"))
        if value is not None and value >= 0:
            total += value
            available = True
    return total if available else None


def build_preclose_market_context(market_inputs, *, components=None):
    """Build current deterministic sentiment without history-store or PSY12 paths."""

    components = components or PreclosePipelineComponents()
    market = market_inputs.get("market")
    market = market if isinstance(market, dict) else {}
    stock_bars = market.get("stock_bars")
    stock_bars = list(stock_bars) if isinstance(stock_bars, list) else _derive_stock_bars(market_inputs)
    market_indices = market.get("market_indices")
    market_indices = market_indices if isinstance(market_indices, dict) else {}
    index_bars = market.get("index_bars")
    if not isinstance(index_bars, (list, tuple, dict)):
        index_bars = list(market_indices.values())
    turnover = _finite(market.get("turnover"), _derive_turnover(market_inputs))
    trend = market.get("trend")
    trend = trend if isinstance(trend, dict) else _derive_trend(market_inputs)
    sentiment = components.build_market_sentiment(
        date=str(market_inputs.get("trade_date") or ""),
        stock_bars=stock_bars,
        index_bars=index_bars,
        turnover=turnover,
        turnover_ma5=market.get("turnover_ma5"),
        turnover_ma20=market.get("turnover_ma20"),
        trend=trend,
        prior_history=[],
        limit_counts=market.get("limit_counts"),
    )
    sectors = list(market.get("sectors") or [])
    evidence = sentiment.get("evidence") if isinstance(sentiment, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        "date": str(market_inputs.get("trade_date") or ""),
        "as_of": str(market_inputs.get("as_of") or ""),
        "bar_state": "intraday",
        "is_final": False,
        "market_indices": market_indices,
        "sectors": sectors,
        "market_sentiment": sentiment,
        "market_data_status": "verified" if sentiment.get("score") is not None else "partial",
        "data_quality": {
            "bar_state": "intraday",
            "is_final": False,
            "stock_bar_count": len(stock_bars),
            "index_count": len(index_bars) if not isinstance(index_bars, dict) else len(index_bars),
        },
        "deterministic_evidence": {
            "breadth": evidence.get("breadth"),
            "limit_ecology": evidence.get("limit_ecology"),
            "index": evidence.get("index"),
            "turnover": evidence.get("turnover"),
            "trend": evidence.get("trend"),
            "sectors": sectors,
        },
        "psy12_used": False,
    }


def _attach_intraday_position_evidence(candidate, trade_date):
    item = dict(candidate or {})
    closes = [_finite(value) for value in _as_list(item.get("closes"))[-120:]]
    current = closes[-1] if closes else _finite(item.get("close"))
    item.update({
        "position_data_status": "unavailable",
        "position_absolute_percentile": None,
        "position_absolute_window": len(closes),
        "position_evidence_date": str(trade_date),
        "position_bar_state": "intraday",
        "position_is_final": False,
    })
    if (
        len(closes) == 120
        and current is not None
        and current > 0
        and all(value is not None and value > 0 for value in closes)
    ):
        less = sum(value < current for value in closes)
        equal = sum(value == current for value in closes)
        item["position_absolute_percentile"] = round(
            (less + equal * 0.5) / len(closes) * 100.0, 4
        )
        item["position_data_status"] = "verified"
    best = item.get("best_buy_point")
    best = best if isinstance(best, dict) else {}
    reference = _finite(
        item.get("reference_price"),
        _finite(best.get("reference_price"), _finite(best.get("price"), current)),
    )
    if reference is not None and reference > 0:
        item["reference_price"] = reference
        item["position_reference_price"] = reference
        item["position_reference_type"] = "preclose_intraday_buy_point"
        if current is not None:
            item["position_distance_pct"] = round(
                (current / reference - 1.0) * 100.0, 4
            )
    item.setdefault("source_channel", "low_position")
    item.setdefault("view", "main")
    return item


def evaluate_preclose_main_candidates(
    candidates,
    *,
    market_context,
    trade_date,
    evaluator=None
):
    """Attach intraday position evidence and apply decision_engine_v1 fail-closed."""

    evaluator = evaluator or evaluate_decision_stock
    evaluated = []
    for raw in candidates or []:
        item = _attach_intraday_position_evidence(raw, trade_date)
        try:
            decision = evaluator(item, market_context=market_context)
        except TypeError:
            decision = evaluator(item, market_context)
        except Exception:
            decision = {"decision_code": "observe", "decision": "观察"}
        item["decision_engine_v1"] = dict(decision or {})
        evaluated.append(item)
    main = [
        item for item in evaluated
        if (item.get("decision_engine_v1") or {}).get("decision_code") == "recommend"
    ]
    return {"evaluated": evaluated, "main": main}


def build_preclose_h4_pool(picks_pure, trade_date, *, components=None):
    components = components or PreclosePipelineComponents()
    h4_upstream, source_diagnostics = filter_h4_upstream_candidates(
        picks_pure
    )
    result = components.build_h4_t3_pool(
        h4_upstream, trade_date, upstream_pool="picks_pure"
    )
    result = dict(result or {})
    result.setdefault("diagnostics", {})["right_side_source_filter"] = (
        source_diagnostics
    )
    return result


def build_preclose_acceleration_pool(
    main_pool,
    startup_watchlist,
    market_indices,
    *,
    components=None
):
    components = components or PreclosePipelineComponents()
    result = components.build_next_day_boom_candidates(
        picks_fusion=list(main_pool or []),
        startup_watchlist=list(startup_watchlist or []),
        market=market_indices or {},
    )
    result = dict(result or {})
    result["action_semantics"] = "research_observation"
    return result


def _reference_price(candidate):
    source = candidate if isinstance(candidate, dict) else {}
    best = source.get("best_buy_point")
    best = best if isinstance(best, dict) else {}
    closes = _as_list(source.get("closes"))
    for value in (
        source.get("reference_price"),
        best.get("reference_price"),
        best.get("price"),
        source.get("close"),
        closes[-1] if closes else None,
    ):
        price = _finite(value)
        if price is not None and price > 0:
            return price
    return None


def _public_pool(candidates):
    output = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        price = _reference_price(item)
        if not str(item.get("code") or "").strip() or not str(
            item.get("name") or ""
        ).strip() or price is None:
            continue
        output.append({
            "code": str(item["code"]),
            "name": str(item["name"]),
            "reference_price": price,
        })
    return output


def _pool_evidence(pool_name, candidates, as_of):
    output = []
    for rank, item in enumerate(candidates or [], start=1):
        best = item.get("best_buy_point") if isinstance(item, dict) else {}
        best = best if isinstance(best, dict) else {}
        output.append({
            "code": str(item.get("code") or ""),
            "pool": pool_name,
            "rank": rank,
            "reference_price": _reference_price(item),
            "signal_type": str(
                best.get("type") or item.get("source_type") or item.get("type") or ""
            ),
            "evidence_as_of": str(as_of),
        })
    return output


def _shanghai_closes(market_inputs):
    market = market_inputs.get("market")
    market = market if isinstance(market, dict) else {}
    indices = market.get("market_indices")
    indices = indices if isinstance(indices, dict) else {}
    shanghai = indices.get("上证指数")
    shanghai = shanghai if isinstance(shanghai, dict) else {}
    return _as_list(shanghai.get("closes"))


def run_preclose_pipeline(market_inputs, *, config, components=None):
    """Run only daily/30m/main/H4/acceleration and freeze one advisory snapshot."""

    if not isinstance(config, PreclosePipelineConfig):
        raise TypeError("config must be PreclosePipelineConfig")
    if not isinstance(market_inputs, dict):
        raise TypeError("market_inputs must be a mapping")
    if str(market_inputs.get("trade_date") or "") != config.trade_date:
        raise ValueError("market input trade_date mismatch")
    components = components or PreclosePipelineComponents()
    diagnostics = {
        "strategy_version": PRE_CLOSE_STRATEGY_VERSION,
        "executed_stages": [],
        "stage_seconds": {},
        "market_input": {
            "bar_state": market_inputs.get("bar_state"),
            "is_final": market_inputs.get("is_final"),
            "as_of": market_inputs.get("as_of"),
        },
    }
    started_at = float(config.monotonic())

    try:
        as_of_dt = _parse_datetime(config.as_of)
        if as_of_dt.time().replace(tzinfo=None) >= wall_time(14, 49):
            raise PrecloseDeadlineExceeded("startup", 240.0)

        def daily_operation():
            daily_results, rows_by_code, failures = _analyze_daily_inputs(
                market_inputs, components
            )
            sector_context = _sector_stocks(rows_by_code)
            state = _build_daily_state(
                daily_results, sector_context, components
            )
            state.update({
                "daily_results": daily_results,
                "rows_by_code": rows_by_code,
                "sector_stocks": sector_context,
            })
            diagnostics["daily_analysis"] = {
                "available_count": len(daily_results),
                "failed": failures,
            }
            return state

        daily_state = _stage_clock(
            config, diagnostics, started_at, "daily_structure", daily_operation
        )

        def min30_operation():
            min30_results, unavailable = _analyze_30m_inputs(
                market_inputs, daily_state["rows_by_code"], components
            )
            diagnostics["min30"] = {
                "available_count": len(min30_results),
                "unavailable_codes": unavailable,
                "is_final": False,
            }
            return _finish_main_state(
                daily_state,
                min30_results,
                daily_state["sector_stocks"],
                _shanghai_closes(market_inputs),
                components,
            )

        main_state = _stage_clock(
            config,
            diagnostics,
            started_at,
            "target_30m_confirm",
            min30_operation,
        )
        diagnostics["pool_build"] = main_state.get("diagnostics") or {}

        market_context = _stage_clock(
            config,
            diagnostics,
            started_at,
            "market_context",
            lambda: build_preclose_market_context(
                market_inputs, components=components
            ),
        )
        decision_state = _stage_clock(
            config,
            diagnostics,
            started_at,
            "decision_engine",
            lambda: evaluate_preclose_main_candidates(
                main_state["picks_fusion"],
                market_context=market_context,
                trade_date=config.trade_date,
                evaluator=components.evaluate_stock,
            ),
        )
        main_public = _stage_clock(
            config,
            diagnostics,
            started_at,
            "main_public_view",
            lambda: list(decision_state["main"]),
        )
        h4 = _stage_clock(
            config,
            diagnostics,
            started_at,
            "h4_t3",
            lambda: build_preclose_h4_pool(
                main_state["picks_pure"],
                config.trade_date,
                components=components,
            ),
        )
        acceleration = _stage_clock(
            config,
            diagnostics,
            started_at,
            "acceleration",
            lambda: build_preclose_acceleration_pool(
                main_public,
                main_state["startup_watchlist"],
                market_context.get("market_indices") or {},
                components=components,
            ),
        )
        internal_pools = {
            "main": main_public,
            "h4_t3": list(h4.get("candidates") or []),
            "acceleration": list(acceleration.get("candidates") or []),
        }
        diagnostics["pool_evidence"] = {
            name: _pool_evidence(name, candidates, config.as_of)
            for name, candidates in internal_pools.items()
        }
        diagnostics["pool_counts"] = {
            name: len(candidates) for name, candidates in internal_pools.items()
        }
        diagnostics["psy12_used"] = False
        diagnostics["elapsed_seconds"] = round(
            max(0.0, float(config.monotonic()) - started_at), 6
        )
        pools = {
            name: _public_pool(candidates)
            for name, candidates in internal_pools.items()
        }
        return build_preclose_snapshot(
            trade_date=config.trade_date,
            as_of=config.as_of,
            generated_at=config.generated_at,
            pools=pools,
            source_sha=config.source_sha,
            diagnostics=diagnostics,
            run_id=config.run_id,
        )
    except PrecloseDeadlineExceeded as exc:
        diagnostics["deadline_stage"] = exc.stage
        diagnostics["elapsed_seconds"] = round(exc.elapsed, 6)
        return build_preclose_snapshot(
            trade_date=config.trade_date,
            as_of=config.as_of,
            generated_at=config.generated_at,
            pools={"main": [], "h4_t3": [], "acceleration": []},
            source_sha=config.source_sha,
            status="deadline_exceeded",
            diagnostics=diagnostics,
            run_id=config.run_id,
        )
    except Exception as exc:
        diagnostics["failure"] = {
            "type": type(exc).__name__,
            "stage": diagnostics["executed_stages"][-1]
            if diagnostics["executed_stages"] else "startup",
        }
        return build_preclose_snapshot(
            trade_date=config.trade_date,
            as_of=config.as_of,
            generated_at=config.generated_at,
            pools={"main": [], "h4_t3": [], "acceleration": []},
            source_sha=config.source_sha,
            status="failed",
            diagnostics=diagnostics,
            run_id=config.run_id,
        )
