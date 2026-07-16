#!/usr/bin/env python3
"""
缠论选股系统 — 主入口

运行流程:
  Phase 1: 数据采集（板块→成分股→日线）
  Phase 2: 日线缠论扫描
  Phase 3: 板块热度计算
  Phase 4: 双通道筛选（纯净版 + 融合版）
  Phase 5: 30分钟精细确认
  Phase 6: 评分 + 生成 HTML 日报

用法:
  python3 run.py              # 当日运行
  python3 run.py --debug      # 调试模式（少量股票）
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
from datetime import datetime
import math
from typing import Callable

import numpy as np
import random

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DAY_LOOKBACK, HISTORY_DAYS, OUTPUT_DIR, DEBUG_OUTPUT_DIR,
    SECTOR_OUTFLOW_COUNT, EVENT_TOP_N, CLS_NEWS_COUNT,
    ENABLE_DAILY_STRUCTURE_POOL, ENABLE_30MIN_CANDIDATE_UPGRADE,
    ENABLE_SIGNAL_DISTRIBUTION_DIAGNOSTICS,
    ENABLE_FUSION_ADMISSION_POLICY,
    SIGNAL_MAX_AGE_TRADING_DAYS,
)
from chanlun.data_fetcher import (
    collect_daily_data, collect_30min_data, collect_15min_data,
    fetch_daily_kline, fetch_kline, fetch_verified_index_kline,
    MarketDataUnavailable,
    build_market_time_metadata,
    _build_code_to_name,
    fetch_sector_outflow, fetch_limit_up_pool,
)
from chanlun.chan_engine import analyze, calc_macd
from chanlun.screener_pure import screen_daily_pure, screen_30min_pure
from chanlun.screener_fusion import screen_daily_fusion, screen_30min_fusion
from chanlun.daily_structure_pool import build_daily_structure_pool
from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min
from chanlun.scorer import apply_scores
from chanlun.report_generator import generate_report, update_data_json
from chanlun.market_news import fetch_cls_news, rank_events, rank_market_impact_events, enrich_events, generate_forecast
from chanlun.fusion_admission import apply_fusion_admission
from chanlun.event_normalizer import normalize_events
from chanlun.strong_startup import build_strong_startup_pool, upgrade_strong_startup_with_30min, annotate_startup_quality
from chanlun.signal_recency import filter_recent_picks, filter_recent_watchlist
from chanlun.next_day_boom import build_next_day_boom_candidates
from chanlun.luojie_pool import prefilter_luojie_theme_candidates, build_luojie_pool
from chanlun.research_frameworks import calc_gf_dma_health


# ============================================================
# 市场指数数据
# ============================================================
MARKET_INDICES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "科创50": "000688",
    "沪深300": "000300",
    "中证500": "000905",
}
PREVIEW_OUTPUT_DIR = "docs-preview"


def _get_decision_engine():
    """Delay import for optional decision engine plugin compatibility."""
    try:
        from chanlun.decision_engine import evaluate_stock
    except ImportError:
        return None
    return evaluate_stock


def _evaluate_with_context(evaluator: Callable, item: dict, market_context: dict | None):
    if not callable(evaluator) or not isinstance(item, dict):
        return None
    try:
        return evaluator(item, market_context=market_context)
    except TypeError:
        try:
            return evaluator(item, market_context)
        except TypeError:
            return evaluator(item)
    except Exception:
        return None


def _inject_decision_engine(items, evaluator: Callable | None, market_context: dict | None = None):
    if not evaluator:
        return
    for item in items or []:
        if not isinstance(item, dict):
            continue
        decision = _evaluate_with_context(evaluator, item, market_context)
        if decision is not None:
            item["decision_engine_v1"] = decision


def _safe_number(value, default=None):
    """Convert arbitrary input to finite float when possible."""
    if value is None:
        return default
    try:
        if isinstance(value, bool):
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _as_list(value):
    """Return list-like inputs as list; otherwise return empty list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        try:
            return list(value.tolist())
        except (TypeError, ValueError):
            return []
    return []


def _clamp(value, low, high):
    if value is None:
        return low
    return max(low, min(high, value))


def _market_temperature_label(score):
    if score >= 90:
        return "过热"
    if score >= 75:
        return "热"
    if score >= 60:
        return "偏强"
    if score >= 45:
        return "平衡"
    if score >= 30:
        return "偏冷"
    return "冰点"


def build_market_temperature(
    market_indices=None,
    sector_flow=None,
    sector_outflow=None,
    limit_up_pool=None,
    sell_signals=None,
    diagnostics=None,
    data_quality=None,
    sh_volumes=None,
    prev_limit_up_count=None,
    limit_down_count=None,
    hot_risk_flags=None,
    advance_count=None,
    decline_count=None,
    flat_count=None,
    prev_turnover=None,
    turnover=None,
    turnover_ma5=None,
):
    """Build back-end market temperature with frontend-compatible structure."""
    if isinstance(market_indices, dict):
        market_items = list(market_indices.values())
    else:
        market_items = _as_list(market_indices)

    valid_items = [
        item for item in market_items
        if isinstance(item, dict) and _safe_number(item.get("change_pct"), None) is not None
    ]

    # Breadth inputs
    advance_count = _safe_number(advance_count, None)
    decline_count = _safe_number(decline_count, None)
    flat_count = _safe_number(flat_count, None)

    # Limits
    limit_up_count = len(_as_list(limit_up_pool))
    prev_limit_up_count = _safe_number(prev_limit_up_count, None)
    limit_down_count = _safe_number(limit_down_count, 0)

    # Volume inputs
    volume_series = [n for n in _as_list(sh_volumes) if _safe_number(n, None) is not None]
    if turnover is None and len(volume_series) >= 1:
        turnover = _safe_number(volume_series[-1], None)
    if prev_turnover is None and len(volume_series) >= 2:
        prev_turnover = _safe_number(volume_series[-2], None)
    if turnover_ma5 is None and len(volume_series) >= 5:
        turnover_ma5 = sum(_safe_number(v, 0) for v in volume_series[-5:]) / 5

    turnover = _safe_number(turnover, None)
    prev_turnover = _safe_number(prev_turnover, None)
    turnover_ma5 = _safe_number(turnover_ma5, None)

    # Risk flags
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    data_quality = data_quality if isinstance(data_quality, dict) else {}
    hot_risk_flags = _as_list(hot_risk_flags)

    sector_in = _as_list(sector_flow)
    sector_out = _as_list(sector_outflow)
    sell_signals = _as_list(sell_signals)

    avg_index_change = 0
    if valid_items:
        avg_index_change = sum(_safe_number(item.get("change_pct"), 0) for item in valid_items) / len(valid_items)
    index_score = _clamp(50 + avg_index_change * 18, 0, 100) if valid_items else 50

    breadth_score = 50
    if advance_count is not None and decline_count is not None:
        denom = advance_count + decline_count + (flat_count if flat_count is not None else 0)
        if denom > 0:
            breadth_score = _clamp((advance_count / denom) * 100, 0, 100)
    elif valid_items:
        up_count = len([item for item in valid_items if _safe_number(item.get("change_pct"), 0) > 0])
        breadth_score = _clamp((up_count / len(valid_items)) * 100, 0, 100)

    limit_score = _clamp(50 + limit_up_count * 2, 0, 90)
    if prev_limit_up_count is not None:
        limit_score = _clamp(
            limit_score + _clamp((limit_up_count - prev_limit_up_count) * 0.8, -10, 10),
            0,
            90,
        )

    volume_score = 55
    if turnover is not None and turnover_ma5 not in (None, 0):
        volume_ratio = turnover / turnover_ma5
        volume_score = _clamp(50 + (volume_ratio - 1) * 80, 20, 90)
    elif turnover is not None and prev_turnover not in (None, 0):
        volume_ratio = turnover / prev_turnover
        volume_score = _clamp(50 + (volume_ratio - 1) * 80, 20, 90)

    sector_score = 50
    if not sector_in and not sector_out:
        sector_score = 50
    else:
        by_value = None
        in_count = 0
        out_count = 0
        net_sector_flow = 0
        for item in sector_in:
            if not isinstance(item, dict):
                continue
            item_flow = _safe_number(item.get("flow"), _safe_number(item.get("net_flow"), _safe_number(item.get("amount"), None)))
            if item_flow is not None:
                by_value = 0
                if item_flow > 0:
                    in_count += 1
                net_sector_flow += item_flow

        for item in sector_out:
            if not isinstance(item, dict):
                continue
            item_flow = _safe_number(item.get("flow"), _safe_number(item.get("net_flow"), _safe_number(item.get("amount"), None)))
            if item_flow is not None:
                by_value = 0
                if item_flow < 0:
                    out_count += 1
                net_sector_flow += item_flow

        if by_value is not None:
            if by_value == 0:
                sector_score = _clamp(50 + in_count * 4 - out_count * 3, 20, 85)
            else:
                sector_score = _clamp(50 + net_sector_flow / 10, 20, 85)

    risk_penalty = 0
    risk_penalty += min(15, len(sell_signals) * 1.5)
    for item in hot_risk_flags:
        if isinstance(item, str) and "涨幅过热" in item:
            risk_penalty += 1
    risk_penalty += limit_down_count * 1.2 if limit_down_count else 0
    risk_penalty += 10 if data_quality.get("is_official") is False else 0
    risk_penalty += 10 if diagnostics.get("error") else 0
    risk_penalty = min(30, risk_penalty)

    raw_score = (
        breadth_score * 0.30
        + index_score * 0.20
        + limit_score * 0.20
        + volume_score * 0.15
        + sector_score * 0.10
        - risk_penalty * 0.05
    )
    score = round(_clamp(raw_score, 0, 100))

    return {
        "score": int(score),
        "label": _market_temperature_label(int(score)),
        "components": {
            "breadth_score": round(breadth_score),
            "index_score": round(index_score),
            "limit_score": round(limit_score),
            "volume_score": round(volume_score),
            "sector_score": round(sector_score),
            "risk_penalty": round(risk_penalty),
        },
    }


def fetch_market_indices(report_date=None, index_codes=None):
    """拉取主要市场指数行情"""
    index_codes = index_codes or MARKET_INDICES
    indices = {}
    for name, code in index_codes.items():
        kline = fetch_verified_index_kline(code, count=3, required_date=report_date)
        prev = float(kline["closes"][-2])
        curr = float(kline["closes"][-1])
        chg_pct = (curr - prev) / prev * 100 if prev > 0 else 0
        indices[name] = {
            "close": round(curr, 2),
            "change_pct": round(float(chg_pct), 2),
            "date": str(kline["dates"][-1]).split(" ")[0],
            "source": kline.get("source", ""),
        }
    return indices


def build_unverified_market_indices(report_date=None, reason="", index_codes=None):
    """Build explicit unverified market placeholders for preview-only reports."""
    index_codes = index_codes or MARKET_INDICES
    return {
        name: {
            "close": None,
            "change_pct": None,
            "date": report_date or "",
            "source": "",
            "status": "unverified",
            "reason": reason,
        }
        for name in index_codes
    }


def analyze_shanghai_chanlun(sh_kline):
    """对上证指数进行缠论分析，提取结构信息"""
    if sh_kline is None or len(sh_kline.get("closes", [])) < 10:
        return {"daily_pivot": None, "trend_type": "数据不足", "key_signal": "", "conclusion": ""}

    result = analyze(
        code="000001", name="上证指数",
        dates=sh_kline["dates"],
        opens=sh_kline["opens"],
        highs=sh_kline["highs"],
        lows=sh_kline["lows"],
        closes=sh_kline["closes"],
        volumes=sh_kline["volumes"],
    )

    if result is None:
        return {"daily_pivot": None, "trend_type": "分析失败", "key_signal": "", "conclusion": ""}

    pivot_info = None
    if result.pivots:
        last = result.pivots[-1]
        pivot_info = {"ZD": last.ZD, "ZG": last.ZG, "count": len(result.pivots)}

    # 生成关键信号和结论
    key_signal = ""
    conclusion = ""

    if result.divergence and result.divergence.get("is_divergence"):
        div_type = result.divergence["type"]
        area_ratio = result.divergence.get("area_ratio", 1.0)
        key_signal = f"{div_type}信号出现，力度比={area_ratio:.2%}"
        if "底背驰" in div_type:
            conclusion = "下跌力度衰竭，关注反弹机会。"
        elif "顶背驰" in div_type:
            conclusion = "上涨力度衰竭，注意回调风险。"
    else:
        key_signal = "未出现明显背驰信号"

    if result.trend_type == "盘整":
        if pivot_info:
            conclusion += f" 当前处于{pivot_info['ZG']}-{pivot_info['ZD']}区间盘整，等待方向选择。"
    elif result.trend_type == "上涨趋势":
        conclusion += " 处于上涨趋势中，持股为主。"
    elif result.trend_type == "下跌趋势":
        conclusion += " 处于下跌趋势中，观望为主。"

    if not conclusion:
        conclusion = result.trend_type

    return {
        "daily_pivot": pivot_info,
        "trend_type": result.trend_type,
        "key_signal": key_signal,
        "conclusion": conclusion.strip(),
    }


def _downgrade_to_formal_only(pool):
    """When 30min data is unavailable, keep only stocks with formal buy points."""
    from chanlun.signal_policy import is_formal_buy
    result = []
    for stock in pool:
        formal_bps = [bp for bp in stock.get("buy_points", []) if is_formal_buy(bp)]
        if not formal_bps:
            continue
        s = dict(stock)
        s["buy_points"] = formal_bps
        s["best_buy_point"] = formal_bps[0]
        s["resonance"] = {"level": "弱", "reason": "30分钟数据缺失，未做次级别确认"}
        result.append(s)
    return result


def _attach_gf_dma_health(picks):
    for stock in picks:
        stock["gf_dma_health"] = calc_gf_dma_health(stock)
    return picks


def _serialize_amount_list(amounts):
    if amounts is None:
        return None
    serial = []
    for item in _as_list(amounts):
        try:
            if isinstance(item, str):
                item = item.replace(",", "")
            value = float(item)
        except (TypeError, ValueError):
            serial.append(None)
            continue
        if not math.isfinite(value):
            serial.append(None)
        else:
            serial.append(float(value))
    if not serial:
        return None
    return serial


def _money20_from_amounts(values):
    if not values:
        return None
    tail = _serialize_amount_list(values)
    if not tail:
        return None
    tail = tail[-20:]
    valid = [v for v in tail if v is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)


def _money20_from_volume_price_proxy(closes, volumes):
    close_arr = _as_list(closes)
    vol_arr = _as_list(volumes)
    if not close_arr or not vol_arr:
        return None
    n = min(len(close_arr), len(vol_arr))
    if n <= 0:
        return None
    close_tail = close_arr[-20:][-n:]
    vol_tail = vol_arr[-20:][-n:]
    values = []
    for c, v in zip(close_tail, vol_tail):
        try:
            if isinstance(c, str):
                c = c.replace(",", "")
            if isinstance(v, str):
                v = v.replace(",", "")
            cv = float(c) * float(v) * 100
        except (TypeError, ValueError):
            continue
        if math.isfinite(cv):
            values.append(cv)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _attach_liquidity(row):
    if not isinstance(row, dict):
        return row

    amounts = row.get("amounts")
    if amounts is None:
        kline = row.get("klines")
        if isinstance(kline, dict):
            amounts = kline.get("amounts")

    serialized_amounts = _serialize_amount_list(amounts)
    money20 = _money20_from_amounts(serialized_amounts)
    source = "missing"

    if money20 is None:
        closes = row.get("closes")
        if closes is None:
            kline = row.get("klines")
            if isinstance(kline, dict):
                closes = kline.get("closes")
        volumes = row.get("volumes")
        if volumes is None:
            kline = row.get("klines")
            if isinstance(kline, dict):
                volumes = kline.get("volumes")

        money20_proxy = _money20_from_volume_price_proxy(closes, volumes)
        if money20_proxy is not None:
            money20 = money20_proxy
            source = "volume_price_proxy"

    if money20 is not None and source == "missing":
        source = "amounts"

    row["money20"] = money20
    row["amounts"] = serialized_amounts
    row["market_cap"] = _safe_number(row.get("market_cap"), None)
    circulating_market_cap = _safe_number(row.get("circulating_market_cap"), None)
    float_market_cap = _safe_number(row.get("float_market_cap"), None)
    if circulating_market_cap is None:
        circulating_market_cap = float_market_cap
    if float_market_cap is None:
        float_market_cap = circulating_market_cap
    row["circulating_market_cap"] = circulating_market_cap
    row["float_market_cap"] = float_market_cap
    row["liquidity_source"] = source
    return row


# ============================================================
# 主流程
# ============================================================
def main(debug=False, preview=False, generated_at=None):
    generated_at = generated_at or datetime.now().astimezone()
    today = generated_at.strftime("%Y-%m-%d")
    time_metadata = build_market_time_metadata(today, generated_at=generated_at)
    print(f"缠论选股系统启动 — {today} 14:35")
    print(f"调试模式: {debug}")
    print(f"预览模式: {preview}")

    # ================================================================
    # Phase 1: 数据采集
    # ================================================================
    if debug:
        # 调试模式：拉取真实板块成分股，随机抽取少量股票
        print("[DEBUG] 使用简化数据（随机采样）")
        from chanlun.data_fetcher import fetch_sector_flow, fetch_sector_stocks
        sectors = fetch_sector_flow(3)
        sh_kline = fetch_daily_kline("000001")
        if sectors:
            # 从第一个有成分股的板块中随机抽取
            test_stocks = []
            for sector in sectors:
                all_stocks = fetch_sector_stocks(sector["code"])
                if all_stocks:
                    sample_size = min(10, len(all_stocks))
                    test_stocks = random.sample(all_stocks, sample_size) if len(all_stocks) > sample_size else all_stocks
                    print(f"[DEBUG] 从板块「{sector['name']}」{len(all_stocks)}只成分股中随机抽取{len(test_stocks)}只")
                    break
            if not test_stocks:
                test_stocks = [{"code": c, "name": c} for c in ["600519", "000858", "300750", "002594", "601012"]]
                print("[DEBUG] 所有板块均无成分股，使用固定列表")
        else:
            # fallback：板块拉取失败时用固定列表
            test_stocks = [{"code": c, "name": c} for c in ["600519", "000858", "300750", "002594", "601012"]]
            sectors = [{"code": "BK0477", "name": "汽车零部件", "change_pct": 1.5, "flow": 1e8, "flow_str": "1.0亿"}]
        stocks_with_kline = []
        name_map = _build_code_to_name()
        for st in test_stocks:
            code = st["code"]
            kline = fetch_daily_kline(code)
            if kline:
                name = name_map.get(code, st.get("name", code))
                stocks_with_kline.append({"code": code, "name": name, "klines": kline})
        data_quality = {
            "report_date": today,
            **time_metadata,
            "is_trading_day": bool(sh_kline),
            "is_official": False,
            "sources_trusted": False,
            "market_status": "verified" if sh_kline else "unverified",
            "stock_pool_source": "manual_debug",
            "sector_source": "eastmoney" if sectors else "empty",
            "stale_stock_count": 0,
            "missing_daily_count": 0,
            "missing_30min_count": 0,
            "fallback_used": False,
            "warnings": ["debug mode"],
        }
        daily_data = {
            "sectors": sectors,
            "sh_index": sh_kline,
            "stocks": stocks_with_kline,
            "data_quality": data_quality,
        }
    else:
        daily_data = collect_daily_data(
            required_date=today,
            allow_missing_index=preview,
            generated_at=generated_at,
        )

    data_quality = daily_data.get("data_quality", {})
    sectors = daily_data["sectors"]
    sh_kline = daily_data["sh_index"]
    index_error = daily_data.get("index_error", "")
    stocks_with_kline = daily_data["stocks"]
    sh_closes = sh_kline["closes"] if sh_kline else None
    sh_volumes = sh_kline["volumes"] if sh_kline else None

    if not stocks_with_kline:
        print("[ERROR] 没有获取到有效的股票日线数据，退出。")
        return

    # ================================================================
    # Phase 2: 日线缠论扫描
    # ================================================================
    print("=" * 60)
    print(f"Phase 2: 日线缠论扫描（{len(stocks_with_kline)} 只）")
    print("=" * 60)
    t0 = time.time()

    chan_results = []
    for i, stock in enumerate(stocks_with_kline):
        kline = stock["klines"]
        result = analyze(
            code=stock["code"],
            name=stock["name"],
            dates=kline["dates"],
            opens=kline["opens"],
            highs=kline["highs"],
            lows=kline["lows"],
            closes=kline["closes"],
            volumes=kline["volumes"],
        )
        chan_results.append(result)
        if (i + 1) % 50 == 0:
            print(f"  已分析 {i + 1}/{len(stocks_with_kline)} ...")

    elapsed = time.time() - t0
    bp_count = sum(1 for r in chan_results if r and r.buy_points)
    sp_count = sum(1 for r in chan_results if r and r.sell_points)
    print(f"  完成 {len(chan_results)} 只，{bp_count} 只有买点信号，{sp_count} 只有卖出信号，耗时 {elapsed:.1f}s")

    # ================================================================
    # Phase 3: 板块热度
    # ================================================================
    print("=" * 60)
    print("Phase 3: 板块热度计算")
    print("=" * 60)
    # 构建 code→sector 映射（sector 信息已在 batch_fetch 中保留）
    sector_stocks = {}
    for stock in stocks_with_kline:
        sec = stock.get("sector", "")
        chg = stock.get("change_pct", 0)
        stock_sector_tags = stock.get("sector_tags")
        if not isinstance(stock_sector_tags, list):
            stock_sector_tags = []
        sector_stocks[stock["code"]] = {
            "sector": sec,
            "change_pct": chg,
            "sector_tags": list(stock_sector_tags),
            "sector_rank": stock.get("sector_rank"),
            "sector_flow": stock.get("sector_flow"),
            "sector_strength_label": stock.get("sector_strength_label", ""),
            "data_status": stock.get("data_status") if isinstance(stock.get("data_status"), dict) else {},
            "market_cap": stock.get("market_cap"),
            "circulating_market_cap": stock.get("circulating_market_cap"),
            "float_market_cap": stock.get("float_market_cap"),
            "amount": stock.get("amount"),
            "amounts": stock.get("amounts"),
        }
    print(f"  板块映射: {len(sector_stocks)} 只")

    # 收集卖出信号（一卖/顶背驰 → 风险提示）
    sell_signals = []
    for r in chan_results:
        if r and r.sell_points:
            sec_info = sector_stocks.get(r.code, {})
            sell_signals.append({
                "code": r.code,
                "name": r.name,
                "sell_points": r.sell_points,
                "trend_type": r.trend_type,
                "divergence": r.divergence,
                "sector": sec_info.get("sector", ""),
            })
    if sell_signals:
        print(f"  卖出信号: {len(sell_signals)} 只（一卖/顶背驰风险提示）")

    # ================================================================
    # Phase 4: Daily structure pool (new: includes upgradeable references)
    # ================================================================
    print("=" * 60)
    print("Phase 4: Daily structure pool")
    print("=" * 60)

    if ENABLE_DAILY_STRUCTURE_POOL:
        print("[纯净版结构池]")
        pure_pool, pure_diag = build_daily_structure_pool(chan_results, sector_stocks, mode="pure")
        print(f"  base_pass={pure_diag['base_pass']}, with_signal={pure_diag['with_buy_points']}, "
              f"formal={pure_diag['formal_count']}, upgradeable={pure_diag['upgradeable_count']}, "
              f"seeds={pure_diag.get('swing_seed_count', 0)}, "
              f"reference_only={pure_diag['reference_only_count']}, pool={len(pure_pool)}")

        if ENABLE_FUSION_ADMISSION_POLICY:
            # Fusion derives from the pure structure pool; admission runs after 30min upgrade
            print("[融合版] 共用纯净版结构池，将在30min升级后应用独立admission策略")
            fusion_diag = pure_diag.copy()
        else:
            print("[融合版结构池]")
            fusion_pool, fusion_diag = build_daily_structure_pool(chan_results, sector_stocks, mode="fusion")
            print(f"  base_pass={fusion_diag['base_pass']}, with_signal={fusion_diag['with_buy_points']}, "
                  f"formal={fusion_diag['formal_count']}, upgradeable={fusion_diag['upgradeable_count']}, "
                  f"seeds={fusion_diag.get('swing_seed_count', 0)}, "
                  f"reference_only={fusion_diag['reference_only_count']}, pool={len(fusion_pool)}")
    else:
        # Rollback: old behavior
        print("[纯净版]")
        pure_pool = screen_daily_pure(chan_results, sector_stocks, sectors)
        print(f"  日线初筛: {len(pure_pool)} 只进入目标池")

        print("[融合版]")
        sh_closes = sh_kline["closes"] if sh_kline else None
        fusion_pool = screen_daily_fusion(chan_results, sh_closes, sector_stocks)
        print(f"  日线初筛: {len(fusion_pool)} 只进入目标池")
        pure_diag = {}
        fusion_diag = {}

    # ================================================================
    # Phase 4.5: Strong startup scan (independent of structure pool)
    # ================================================================
    print("=" * 60)
    print("Phase 4.5: Strong startup scan")
    print("=" * 60)

    def _attach_sector_metadata(row):
        """Attach sector metadata from sector_stocks without overwriting explicit row values."""
        if not isinstance(row, dict):
            return {}

        code = row.get("code")
        sector_meta = sector_stocks.get(code, {}) if code else {}
        merged = dict(row)

        if merged.get("sector") is None or "sector" not in merged or merged["sector"] == "":
            merged["sector"] = sector_meta.get("sector", merged.get("sector", ""))

        if (
            "sector_tags" not in merged
            or not isinstance(merged.get("sector_tags"), list)
            or not merged.get("sector_tags")
        ):
            merged["sector_tags"] = list(sector_meta.get("sector_tags", []))

        if "sector_rank" not in merged or merged.get("sector_rank") is None:
            merged["sector_rank"] = sector_meta.get("sector_rank")

        if "sector_flow" not in merged or merged.get("sector_flow") is None:
            merged["sector_flow"] = sector_meta.get("sector_flow")

        if "market_cap" not in merged or merged.get("market_cap") is None:
            merged["market_cap"] = sector_meta.get("market_cap")

        if "circulating_market_cap" not in merged or merged.get("circulating_market_cap") is None:
            merged["circulating_market_cap"] = sector_meta.get("circulating_market_cap")

        if "float_market_cap" not in merged or merged.get("float_market_cap") is None:
            merged["float_market_cap"] = sector_meta.get("float_market_cap")

        if "amount" not in merged or merged.get("amount") is None:
            merged["amount"] = sector_meta.get("amount")

        if not merged.get("sector_strength_label"):
            merged["sector_strength_label"] = sector_meta.get("sector_strength_label", "")

        if not isinstance(merged.get("data_status"), dict) or not merged.get("data_status"):
            merged["data_status"] = sector_meta.get("data_status", {})

        return merged

    startup_seeds, startup_watchlist, startup_diag = build_strong_startup_pool(
        chan_results, sector_stocks)
    startup_seeds = [_attach_sector_metadata(s) for s in startup_seeds]
    startup_seeds = [_attach_liquidity(s) for s in startup_seeds]
    startup_watchlist = [_attach_sector_metadata(w) for w in startup_watchlist]
    startup_watchlist = [_attach_liquidity(w) for w in startup_watchlist]

    print(f"  扫描: {startup_diag.get('scanned', 0)} 只, "
          f"启动种子: {startup_diag.get('daily_startup_seed', 0)}, "
          f"涨停观察: {startup_diag.get('watch_due_to_limit_up', 0)}")
    print(f"  过滤: 基础={startup_diag.get('dropped_base_filter', 0)}, "
          f"高位={startup_diag.get('dropped_high_position', 0)}, "
          f"无量={startup_diag.get('dropped_no_volume', 0)}, "
          f"无突破={startup_diag.get('dropped_no_breakout', 0)}")

    # ================================================================
    # Phase 4.6: 罗姐池（国家队硬方向 + 15min生命线）
    # ================================================================
    print("=" * 60)
    print("Phase 4.6: 罗姐池")
    print("=" * 60)

    luojie_theme_stocks = prefilter_luojie_theme_candidates(stocks_with_kline)
    print(f"  国家队硬方向主题预筛: {len(luojie_theme_stocks)} 只")
    min15_data_list = collect_15min_data(luojie_theme_stocks)
    chan_results_15min = []
    if min15_data_list:
        seed_map = {s["code"]: s for s in luojie_theme_stocks}
        print(f"  15分钟数据获取: {len(min15_data_list)} 只, 缠论分析 ...")
        for d in min15_data_list:
            kline = d["klines"]
            seed = seed_map.get(d["code"], {})
            result = analyze(
                code=d["code"], name=seed.get("name", d.get("name", "")),
                dates=kline["dates"], opens=kline["opens"],
                highs=kline["highs"], lows=kline["lows"],
                closes=kline["closes"], volumes=kline["volumes"],
            )
            chan_results_15min.append(result)
    luojie_pool = build_luojie_pool(luojie_theme_stocks, chan_results_15min)
    print(f"  罗姐池: 主题={luojie_pool.get('diagnostics', {}).get('theme_candidates', 0)} "
          f"15min={luojie_pool.get('diagnostics', {}).get('with_15min', 0)} "
          f"入池={len(luojie_pool.get('candidates', []))}")
    luojie_pool["candidates"] = [
        _attach_liquidity(_attach_sector_metadata(c))
        for c in luojie_pool.get("candidates", [])
    ]

    # ================================================================
    # Phase 5: 30min fetch + analysis + candidate upgrade
    # ================================================================
    print("=" * 60)
    print("Phase 5: 30min fetch + candidate upgrade")
    print("=" * 60)

    startup_candidates = []
    startup_upgrade_diag = {}
    startup_additional_watchlist = []

    if ENABLE_30MIN_CANDIDATE_UPGRADE:
        # Collect codes from structure pool(s) + non-limit-up startup seeds
        if ENABLE_FUSION_ADMISSION_POLICY:
            all_target_codes = {s["code"] for s in pure_pool}
        else:
            pure_codes = {s["code"] for s in pure_pool}
            fusion_codes = {s["code"] for s in fusion_pool}
            all_target_codes = pure_codes | fusion_codes

        # Add startup seed codes (only non-limit-up, which need 30min confirmation)
        startup_seed_codes = {s["code"] for s in startup_seeds}
        all_target_codes |= startup_seed_codes
        all_targets = [{"code": c, "name": ""} for c in all_target_codes]

        print(f"  结构池并集: {len(all_target_codes)} 只 "
              f"(含启动种子: {len(startup_seed_codes)}), 拉取30分钟数据 ...")
        min30_data_list = collect_30min_data(all_targets)

        if not min30_data_list:
            print("  30分钟数据获取失败，跳过精细确认，直接用日线结构池结果")
            # Without 30min, keep formal buys only, drop upgradeable-only stocks
            pure_confirmed = _downgrade_to_formal_only(pure_pool)
            # All startup seeds → watch (no 30min data to confirm)
            if startup_seeds:
                for s in startup_seeds:
                    startup_watchlist.append(_attach_liquidity(_attach_sector_metadata({
                        "code": s["code"], "name": s["name"],
                        "type": "强势启动观察", "tier": "watch",
                        "source_type": "日线强势启动",
                        "startup_reason": s.get("startup_reason", ""),
                        "startup_signals": s.get("startup_signals", []),
                        "change_pct": s.get("change_pct", 0),
                        "volume_ratio": s.get("volume_ratio", 0),
                        "close": s.get("close", 0),
                        "avoid_chase": True,
                        "watch_reason": "缺少30分钟数据，等待次日确认",
                        "next_day_conditions": ["回踩不破突破位", "30min出现二买/三买确认"],
                    })))
            startup_upgrade_diag = {"startup_candidate": 0,
                                     "watch_due_to_no_30min_confirm": len(startup_seeds)}
            upgrade_diag_pure = {"requested_30min": 0, "fetched_30min": 0, "formal_kept": len(pure_confirmed),
                                 "candidate_upgraded": 0, "dropped_no_confirm": 0, "dropped_no_30min": len(pure_pool) - len(pure_confirmed)}
            if ENABLE_FUSION_ADMISSION_POLICY:
                fusion_confirmed, fusion_admission_diag = apply_fusion_admission(
                    pure_confirmed, sh_closes, sector_stocks)
                upgrade_diag_fusion = {"requested_30min": 0, "fetched_30min": 0,
                                       "formal_kept": len(pure_confirmed),
                                       "candidate_upgraded": 0, "dropped_no_confirm": 0,
                                       "dropped_no_30min": len(pure_pool) - len(pure_confirmed)}
            else:
                fusion_confirmed = _downgrade_to_formal_only(fusion_pool if not ENABLE_FUSION_ADMISSION_POLICY else pure_pool)
                upgrade_diag_fusion = {"requested_30min": 0, "fetched_30min": 0, "formal_kept": len(fusion_confirmed),
                                       "candidate_upgraded": 0, "dropped_no_confirm": 0, "dropped_no_30min": len(pure_pool) - len(fusion_confirmed)}
                fusion_admission_diag = {}
        else:
            print(f"  30分钟数据获取: {len(min30_data_list)} 只, 缠论分析 ...")
            chan_results_30min = []
            for d in min30_data_list:
                kline = d["klines"]
                result = analyze(
                    code=d["code"], name=d.get("name", ""),
                    dates=kline["dates"], opens=kline["opens"],
                    highs=kline["highs"], lows=kline["lows"],
                    closes=kline["closes"], volumes=kline["volumes"],
                )
                chan_results_30min.append(result)

            print(f"  30分钟分析完成: {sum(1 for r in chan_results_30min if r is not None)} 只有效")

            print("[纯净版候选升级]")
            pure_confirmed, upgrade_diag_pure = upgrade_daily_candidates_with_30min(
                pure_pool, chan_results_30min, mode="pure")
            print(f"  formal_kept={upgrade_diag_pure['formal_kept']}, "
                  f"candidate_upgraded={upgrade_diag_pure['candidate_upgraded']}, "
                  f"dropped_no_confirm={upgrade_diag_pure['dropped_no_confirm']}, "
                  f"dropped_no_30min={upgrade_diag_pure['dropped_no_30min']}, "
                  f"dropped_risk_guard={upgrade_diag_pure.get('dropped_risk_guard', 0)}, "
                  f"dropped_diverge_far={upgrade_diag_pure.get('dropped_diverge_far', 0)}")

            # —— 强势启动 30min 升级 ——
            if startup_seeds:
                print("[强势启动30min升级]")
                startup_candidates, startup_additional_watchlist, startup_upgrade_diag = \
                    upgrade_strong_startup_with_30min(startup_seeds, chan_results_30min)
                print(f"  candidate={startup_upgrade_diag['startup_candidate']}, "
                      f"watch_no_confirm={startup_upgrade_diag['watch_due_to_no_30min_confirm']}, "
                      f"dropped_no_30min_data={startup_upgrade_diag.get('dropped_no_30min_confirm', 0)}")
                startup_additional_watchlist = [_attach_liquidity(_attach_sector_metadata(item))
                                            for item in startup_additional_watchlist]
                startup_watchlist = startup_watchlist + startup_additional_watchlist
                # Normalize startup candidates to match regular pick structure
                if startup_candidates:
                    normalized = []
                    for sc in startup_candidates:
                        pick = {
                            "code": sc["code"],
                            "name": sc["name"],
                            "signal_tier": "candidate",
                            "best_buy_point": {
                                "type": sc.get("type", "强势启动候选"),
                                "tier": "candidate",
                                "index": len(sc.get("closes", [])) - 1,
                                "price": sc.get("close", 0),
                                "reason": sc.get("startup_reason", ""),
                                "strength": sc.get("startup_strength", "中"),
                                "source_type": sc.get("source_type", "日线强势启动"),
                                "confirmed_by": "30min确认",
                                "confirmations": sc.get("confirmations", []),
                                "startup_reason": sc.get("startup_reason", ""),
                                "startup_signals": sc.get("startup_signals", []),
                                "startup_index": sc.get("startup_index"),
                                "startup_date": sc.get("startup_date", ""),
                                "startup_age_days": sc.get("startup_age_days", 0),
                                "confirm_index": sc.get("confirm_index"),
                                "confirm_date": sc.get("confirm_date", ""),
                                "confirm_age_days": sc.get("confirm_age_days"),
                                "change_pct": sc.get("change_pct", 0),
                                "volume_ratio": sc.get("volume_ratio", 0),
                            },
                            "buy_points_30min": [],
                            "pivots": sc.get("pivot_info", {}),
                            "trend_type": "",
                            "score": 0,
                            "resonance": {},
                            "ma_bullish": False,
                            "fusion_admission": {},
                            "market_regime": "",
                            "dates": sc.get("dates", sc.get("closes", [])),
                            "closes": sc.get("closes", []),
                            "opens": sc.get("opens", []),
                            "highs": sc.get("highs", []),
                            "lows": sc.get("lows", []),
                            "volumes": sc.get("volumes", []),
                            "macd_hist": calc_macd(sc.get("closes", []))[2],
                            "buy_points": [{
                                "type": sc.get("type", "强势启动候选"),
                                "tier": "candidate",
                                "index": len(sc.get("closes", [])) - 1,
                                "price": sc.get("close", 0),
                                "reason": sc.get("startup_reason", ""),
                                "strength": sc.get("startup_strength", "中"),
                                "source_type": sc.get("source_type", "日线强势启动"),
                                "confirmed_by": "30min确认",
                                "confirmations": sc.get("confirmations", []),
                            }],
                            "reference_buy_points": sc.get("buy_points", []),
                            "blocked_buy_points": [],
                            "result_30min": sc.get("result_30min"),
                            "startup_reason": sc.get("startup_reason", ""),
                            "startup_signals": sc.get("startup_signals", []),
                            "change_pct": sc.get("change_pct", 0),
                            "volume_ratio": sc.get("volume_ratio", 0),
                        }
                        pick = _attach_sector_metadata(pick)
                        # Annotate startup quality labels on best_buy_point
                        pick["best_buy_point"] = annotate_startup_quality(pick["best_buy_point"])
                        pick = _attach_liquidity(pick)
                        normalized.append(pick)
                    pure_confirmed = pure_confirmed + normalized
                    print(f"  合并启动候选 {len(startup_candidates)} 只到纯净版主推荐")
            else:
                startup_upgrade_diag = {}

            if ENABLE_FUSION_ADMISSION_POLICY:
                # Fusion: apply admission policy on top of pure confirmed picks
                print("[融合版admission]")
                import copy
                fusion_ready = copy.deepcopy(pure_confirmed)
                fusion_confirmed, fusion_admission_diag = apply_fusion_admission(
                    fusion_ready, sh_closes, sector_stocks)
                print(f"  input={fusion_admission_diag['input_count']}, "
                      f"regime={fusion_admission_diag['market_regime']}, "
                      f"kept_formal={fusion_admission_diag['kept_formal']}, "
                      f"kept_candidate={fusion_admission_diag['kept_candidate']}, "
                      f"dropped_ma={fusion_admission_diag['dropped_by_ma']}, "
                      f"dropped_regime={fusion_admission_diag['dropped_by_market_regime']}, "
                      f"dropped_gate={fusion_admission_diag['dropped_by_signal_gate']}, "
                      f"output={fusion_admission_diag['output_count']}")
                upgrade_diag_fusion = {
                    "requested_30min": upgrade_diag_pure.get("requested_30min", 0),
                    "fetched_30min": upgrade_diag_pure.get("fetched_30min", 0),
                    "formal_kept": fusion_admission_diag.get("kept_formal", 0),
                    "candidate_upgraded": fusion_admission_diag.get("kept_candidate", 0),
                    "dropped_no_confirm": upgrade_diag_pure.get("dropped_no_confirm", 0),
                    "dropped_no_30min": upgrade_diag_pure.get("dropped_no_30min", 0),
                    "dropped_risk_guard": upgrade_diag_pure.get("dropped_risk_guard", 0),
                }
            else:
                print("[融合版候选升级]")
                fusion_confirmed, upgrade_diag_fusion = upgrade_daily_candidates_with_30min(
                    fusion_pool, chan_results_30min, mode="fusion")
                print(f"  formal_kept={upgrade_diag_fusion['formal_kept']}, "
                      f"candidate_upgraded={upgrade_diag_fusion['candidate_upgraded']}, "
                      f"dropped_no_confirm={upgrade_diag_fusion['dropped_no_confirm']}, "
                      f"dropped_no_30min={upgrade_diag_fusion['dropped_no_30min']}, "
                      f"dropped_risk_guard={upgrade_diag_fusion.get('dropped_risk_guard', 0)}, "
                      f"dropped_diverge_far={upgrade_diag_fusion.get('dropped_diverge_far', 0)}")
                fusion_admission_diag = {}
    else:
        # Rollback: old 30min confirmation flow
        pure_codes = {s["code"] for s in pure_pool}
        fusion_codes = {s["code"] for s in fusion_pool}
        all_target_codes = pure_codes | fusion_codes
        all_targets = [{"code": c, "name": ""} for c in all_target_codes]
        min30_data_list = collect_30min_data(all_targets)

        if not min30_data_list:
            print("  30分钟数据获取失败，跳过精细确认，直接用日线结果")
            pure_confirmed = pure_pool
            fusion_confirmed = fusion_pool
        else:
            min30_map = {d["code"]: d for d in min30_data_list}
            print("  30分钟缠论分析 ...")
            chan_results_30min = []
            for d in min30_data_list:
                kline = d["klines"]
                result = analyze(
                    code=d["code"], name=d.get("name", ""),
                    dates=kline["dates"], opens=kline["opens"],
                    highs=kline["highs"], lows=kline["lows"],
                    closes=kline["closes"], volumes=kline["volumes"],
                )
                chan_results_30min.append(result)
            print("[纯净版 30min确认]")
            pure_confirmed = screen_30min_pure(pure_pool, chan_results_30min)
            print(f"  区间套确认: {len(pure_confirmed)} 只")
            print("[融合版 30min确认]")
            fusion_confirmed = screen_30min_fusion(fusion_pool, chan_results_30min)
            print(f"  区间套确认: {len(fusion_confirmed)} 只")
            upgrade_diag_pure = {}
            upgrade_diag_fusion = {}
            fusion_admission_diag = {}

    # ================================================================
    # Phase 6: Score + generate report
    # ================================================================
    print("=" * 60)
    print("Phase 6: Signal recency filter + Score + generate report")
    print("=" * 60)

    # Signal recency filter (before scoring, per spec)
    pure_confirmed, recency_pure_diag = filter_recent_picks(pure_confirmed, SIGNAL_MAX_AGE_TRADING_DAYS)
    fusion_confirmed, recency_fusion_diag = filter_recent_picks(fusion_confirmed, SIGNAL_MAX_AGE_TRADING_DAYS)
    startup_watchlist, recency_watch_diag = filter_recent_watchlist(startup_watchlist, SIGNAL_MAX_AGE_TRADING_DAYS)
    startup_watchlist = [_attach_liquidity(_attach_sector_metadata(item)) for item in startup_watchlist]
    print(f"  时效过滤: pure {recency_pure_diag['input']}→{recency_pure_diag['kept']} "
          f"(过期{recency_pure_diag['dropped_expired']}), "
          f"fusion {recency_fusion_diag['input']}→{recency_fusion_diag['kept']} "
          f"(过期{recency_fusion_diag['dropped_expired']}), "
          f"watch {recency_watch_diag['input']}→{recency_watch_diag['kept']} "
          f"(过期{recency_watch_diag['dropped_expired']})")

    # Score
    pure_scored = apply_scores(pure_confirmed, version="pure")
    fusion_scored = apply_scores(fusion_confirmed, version="fusion", sector_rank_map=sectors)
    pure_scored = [_attach_sector_metadata(p) for p in pure_scored]
    fusion_scored = [_attach_sector_metadata(p) for p in fusion_scored]
    pure_scored = [_attach_liquidity(p) for p in pure_scored]
    fusion_scored = [_attach_liquidity(p) for p in fusion_scored]
    pure_scored = _attach_gf_dma_health(pure_scored)
    fusion_scored = _attach_gf_dma_health(fusion_scored)

    print(f"  纯净版最终推荐: {len(pure_scored)} 只")
    if pure_scored:
        for p in pure_scored[:5]:
            bp = p["best_buy_point"]
            print(f"    {p['code']} {p['name']}: {bp['type']} @ {bp['price']} 评分={p['score']}")

    print(f"  融合版最终推荐: {len(fusion_scored)} 只")
    if fusion_scored:
        for p in fusion_scored[:5]:
            bp = p["best_buy_point"]
            print(f"    {p['code']} {p['name']}: {bp['type']} @ {bp['price']} 评分={p['score']} 止损={p.get('stop_loss', '-')}")

    # 市场指数
    print("  获取市场指数 ...")
    market_data_status = "verified"
    try:
        market_indices = fetch_market_indices(report_date=today)
    except MarketDataUnavailable as e:
        if not preview:
            raise
        market_data_status = "unverified"
        index_error = str(e)
        print(f"  [PREVIEW] 市场指数未校验，生成预览报告: {index_error}")
        market_indices = build_unverified_market_indices(
            report_date=today,
            reason=index_error,
        )

    # 次日大涨候选（独立于原选股池，不改变 pure/fusion 结果）
    next_day_boom = build_next_day_boom_candidates(
        picks_fusion=fusion_scored,
        startup_watchlist=startup_watchlist,
        market=market_indices,
    )
    print(f"  次日大涨模式: {next_day_boom.get('mode')} "
          f"候选={len(next_day_boom.get('candidates', []))} "
          f"原因={next_day_boom.get('reason', '')}")
    next_day_source_map = {}
    for item in list(fusion_scored) + list(startup_watchlist):
        if isinstance(item, dict) and item.get("code"):
            next_day_source_map[item["code"]] = item
    next_day_candidates = []
    for candidate in next_day_boom.get("candidates", []):
        merged = dict(candidate)
        source = next_day_source_map.get(candidate.get("code"), {})
        if isinstance(source, dict):
            source_for_merge = {
                k: source.get(k)
                for k in ("market_cap", "circulating_market_cap", "float_market_cap", "amounts", "amount", "closes", "volumes")
            }
            merged.update(source_for_merge)
        merged = _attach_sector_metadata(merged)
        merged = _attach_liquidity(merged)
        next_day_candidates.append(merged)
    next_day_boom["candidates"] = next_day_candidates

    # 上证缠论结构
    print("  分析上证缠论结构 ...")
    sh_chanlun = analyze_shanghai_chanlun(sh_kline)

    # 涨停池提前获取，供事件影响力评分复用
    limit_up_pool_data = fetch_limit_up_pool(today.replace("-", ""))

    # 热点事件 — 影响力评分排序后再 LLM 增强
    raw_events = fetch_cls_news(CLS_NEWS_COUNT)
    ranked_events = rank_market_impact_events(raw_events, sector_flow=sectors, limit_up_pool=limit_up_pool_data, top_n=EVENT_TOP_N)
    events = normalize_events(enrich_events(ranked_events))

    # 决策引擎评分（可选字段）
    decision_engine = _get_decision_engine()
    if decision_engine:
        market_context = {
            "market_indices": market_indices,
            "sectors": sectors,
            "date": today,
            "data_quality": data_quality,
            "market_data_status": market_data_status,
        }
        _inject_decision_engine(pure_scored, decision_engine, market_context)
        _inject_decision_engine(fusion_scored, decision_engine, market_context)
        _inject_decision_engine(startup_watchlist, decision_engine, market_context)
        _inject_decision_engine(next_day_boom.get("candidates", []), decision_engine, market_context)
        _inject_decision_engine(luojie_pool.get("candidates", []), decision_engine, market_context)

    # 构建报告数据
    daily_scan_diag = {
        "total": len(chan_results),
        "base_pass": pure_diag.get("base_pass", len(chan_results)),
        "with_buy_points": pure_diag.get("with_buy_points", 0),
        "formal_count": pure_diag.get("formal_count", 0),
        "upgradeable_count": pure_diag.get("upgradeable_count", 0),
        "swing_seed_count": pure_diag.get("swing_seed_count", 0),
        "reference_only_count": pure_diag.get("reference_only_count", 0),
        "blocked_only_count": pure_diag.get("blocked_only_count", 0),
    }
    if ENABLE_SIGNAL_DISTRIBUTION_DIAGNOSTICS:
        daily_scan_diag["buy_point_type_counts"] = pure_diag.get("buy_point_type_counts", {})
        daily_scan_diag["structure_pool_reasons"] = pure_diag.get("structure_pool_reasons", {})
        daily_scan_diag["excluded_reference_type_counts"] = pure_diag.get("excluded_reference_type_counts", {})

    # Signal distribution
    signal_distribution = {}
    for p in pure_scored:
        bp = p.get("best_buy_point", {})
        t = bp.get("type", "其他")
        signal_distribution[t] = signal_distribution.get(t, 0) + 1

    # Event analysis status counts
    event_status_counts = {"ok": 0, "failed": 0, "skipped": 0}
    for ev in events:
        imp = ev.get("impact", {})
        status = imp.get("status", "skipped")
        event_status_counts[status] = event_status_counts.get(status, 0) + 1

    preview_note = ""
    if preview:
        preview_note = "预览模式输出，仅用于查看候选，不作为正式日报。"
        if market_data_status != "verified":
            preview_note = "指数未完成多源校验，仅用于查看候选，不作为正式日报。"

    # Chart annotation coverage
    picks_with_annotations = sum(
        1 for p in pure_scored
        if p.get("best_buy_point", {}).get("index") is not None
    )

    from chanlun.kline_cache import get_cache_stats
    diagnostics = {
        "daily_scan": daily_scan_diag,
        "sublevel_upgrade_pure": upgrade_diag_pure if ENABLE_30MIN_CANDIDATE_UPGRADE else {},
        "sublevel_upgrade_fusion": upgrade_diag_fusion if ENABLE_30MIN_CANDIDATE_UPGRADE else {},
        "kline_cache": get_cache_stats(),
        "fusion_admission": fusion_admission_diag if ENABLE_FUSION_ADMISSION_POLICY else {},
        "signal_distribution": signal_distribution,
        "event_analysis_status_counts": event_status_counts,
        "chart_annotation_coverage": {
            "total_picks": len(pure_scored),
            "with_annotations": picks_with_annotations,
        },
        "data_quality": data_quality,
        "strong_startup": {
            "daily_scan": startup_diag,
            "upgrade": startup_upgrade_diag,
            "startup_candidates": len(startup_candidates),
            "startup_watchlist": len(startup_watchlist),
        },
        "luojie_pool": luojie_pool.get("diagnostics", {}),
        "signal_recency": {
            "max_age_trading_days": SIGNAL_MAX_AGE_TRADING_DAYS,
            "pure_input": recency_pure_diag["input"],
            "pure_kept": recency_pure_diag["kept"],
            "pure_dropped_expired": recency_pure_diag["dropped_expired"],
            "fusion_input": recency_fusion_diag["input"],
            "fusion_kept": recency_fusion_diag["kept"],
            "fusion_dropped_expired": recency_fusion_diag["dropped_expired"],
            "watch_input": recency_watch_diag["input"],
            "watch_kept": recency_watch_diag["kept"],
            "watch_dropped_expired": recency_watch_diag["dropped_expired"],
            "dropped_details": (
                recency_pure_diag.get("dropped_details", []) +
                recency_fusion_diag.get("dropped_details", []) +
                recency_watch_diag.get("dropped_details", [])
            ),
        },
        "preview": {
            "enabled": bool(preview),
            "market_data_status": market_data_status,
            "market_data_error": index_error,
            "note": preview_note,
        },
    }
    sector_outflow = fetch_sector_outflow(SECTOR_OUTFLOW_COUNT)
    market_temperature = build_market_temperature(
        market_indices=market_indices,
        sector_flow=sectors,
        sector_outflow=sector_outflow,
        limit_up_pool=limit_up_pool_data,
        sell_signals=sell_signals,
        diagnostics=diagnostics,
        data_quality=data_quality,
        sh_volumes=sh_volumes,
    )
    report_data = {
        "date": today,
        "market": market_indices,
        "chanlun_structure": sh_chanlun,
        "picks_pure": pure_scored,
        "picks_fusion": fusion_scored,
        "sector_flow": sectors,
        # 新增模块
        "sector_outflow": sector_outflow,
        "limit_up_pool": limit_up_pool_data,
        "market_temperature": market_temperature,
        "events": events,
        "forecast": generate_forecast(market_indices, sh_chanlun, sectors, sh_volumes, events),
        "sell_signals": sell_signals,
        "data_quality": data_quality,
        "diagnostics": diagnostics,
        "startup_watchlist": startup_watchlist,
        "next_day_boom": next_day_boom,
        "luojie_pool": luojie_pool,
    }

    # 生成 HTML（debug/preview 模式输出到独立目录，隔离上线数据）
    output_dir_name = DEBUG_OUTPUT_DIR if debug else (PREVIEW_OUTPUT_DIR if preview else OUTPUT_DIR)
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_dir_name)
    generate_report(report_data, output_dir)
    update_data_json(report_data, output_dir)

    print()
    print("=" * 60)
    print(f"完成! 纯净版 {len(pure_scored)} 只, 融合版 {len(fusion_scored)} 只")
    print(f"输出: {output_dir}/index.html")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="缠论选股系统")
    parser.add_argument("--debug", action="store_true", help="调试模式，仅用少量股票")
    parser.add_argument("--preview", action="store_true", help="预览模式：指数校验失败时输出本地预览，不作为正式日报")
    parser.add_argument("--refresh-cache", action="store_true", help="强制刷新K线缓存")
    args = parser.parse_args()
    from chanlun.data_fetcher import set_force_refresh_cache
    if args.refresh_cache:
        set_force_refresh_cache(True)
        print("[CACHE] 强制刷新K线缓存")
    main(debug=args.debug, preview=args.preview)
