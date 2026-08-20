"""
HTML 日报生成器 — v2 策略工作台壳子 + 外部静态资源

输出结构:
- docs/index.html (最新，含 bootstrap + 外部 CSS/JS)
- docs/YYYY-MM-DD/index.html (按日期归档)
- docs/data.json (历史5天聚合数据)
"""

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from datetime import datetime, timedelta

import numpy as np

from chanlun.chan_engine import calc_macd
from chanlun.report_comparison import write_comparison_index
from chanlun.report_view_model import build_workspace

from config import (
    OUTPUT_DIR, HISTORY_DAYS,
    MARKET_HISTORY_DB_PATH,
    ENABLE_WEAK_ACCESS_CONTROL,
    FULL_ACCESS_KEY, FULL_ACCESS_KEY_SALT,
)

# ------------------------------------------------------------
# JSON 序列化辅助
# ------------------------------------------------------------
class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


CHART_MAX_BARS = 50  # 图表展示默认K线根数（动态窗口会扩展）
CHART_MIN_BARS = 50
CHART_MAX_EXTENDED = 120
REPORT_V2_ASSETS = ("report-v2.css", "report-v2.js")
DEFAULT_TOP10_API_BASE = "https://top10-worker.breakaway4here.workers.dev"


def build_chart_window(pick):
    """Calculate the slice window so key points (reference/seed/confirm/best_buy) are visible.

    Returns (slice_start, slice_end) indices into the original arrays.
    """
    dates = _safe_list(pick.get("dates", []))
    n = len(dates)
    if n == 0:
        return 0, 0

    # Collect key indices that must be visible
    key_indices = set()

    bp = pick.get("best_buy_point", {})
    bp_idx = bp.get("index")
    if bp_idx is not None and isinstance(bp_idx, int) and 0 <= bp_idx < n:
        key_indices.add(bp_idx)

    # reference buy points
    for ref in pick.get("reference_buy_points", []) or []:
        ri = ref.get("index")
        if ri is not None and isinstance(ri, int) and 0 <= ri < n:
            key_indices.add(ri)

    # Always include latest bar
    key_indices.add(n - 1)

    if not key_indices:
        return max(0, n - CHART_MAX_BARS), n

    min_key = min(key_indices)
    max_key = max(key_indices)

    # Window must cover min_key to max_key, plus padding
    padding = 5
    win_start = max(0, min_key - padding)
    win_end = min(n, max_key + padding + 1)

    # Ensure minimum window size
    if win_end - win_start < CHART_MIN_BARS:
        extra = CHART_MIN_BARS - (win_end - win_start)
        win_start = max(0, win_start - extra // 2)
        win_end = min(n, win_end + extra - extra // 2)

    # Cap at max extended
    if win_end - win_start > CHART_MAX_EXTENDED:
        win_start = win_end - CHART_MAX_EXTENDED

    return win_start, win_end


def build_chart_annotations(pick, slice_start, dates_sliced, closes_sliced):
    """Build annotation data for chart JS rendering.

    Returns a dict with markLines and markPoints for ECharts.
    """
    annotations = {"markLines": [], "markPoints": [], "labels": []}

    bp = pick.get("best_buy_point", {})
    bp_idx_orig = bp.get("index")
    bp_price = bp.get("price")
    bp_type = bp.get("type", "")

    # Pivot ZD/ZG
    pivots = pick.get("pivots", {})
    zg = pivots.get("ZG")
    zd = pivots.get("ZD")
    if zg is not None and zd is not None and dates_sliced:
        annotations["markLines"].append({
            "name": "ZG",
            "yAxis": float(zg),
            "lineStyle": {"color": "rgba(255,165,0,0.4)", "type": "dashed"},
            "label": {"formatter": f"ZG {zg}", "color": "#ffa502", "fontSize": 10},
        })
        annotations["markLines"].append({
            "name": "ZD",
            "yAxis": float(zd),
            "lineStyle": {"color": "rgba(255,165,0,0.4)", "type": "dashed"},
            "label": {"formatter": f"ZD {zd}", "color": "#ffa502", "fontSize": 10},
        })

    # Reference price (signal price)
    source_price = bp.get("source_price") or bp_price
    if source_price and dates_sliced:
        annotations["markLines"].append({
            "name": "source",
            "yAxis": float(source_price),
            "lineStyle": {"color": "rgba(116,185,255,0.5)", "type": "dotted"},
            "label": {"formatter": f"参考 {source_price}", "color": "#74b9ff", "fontSize": 10},
        })

    # Current price line
    if closes_sliced and dates_sliced:
        curr_price = float(closes_sliced[-1])
        annotations["markLines"].append({
            "name": "current",
            "yAxis": curr_price,
            "lineStyle": {"color": "rgba(0,255,136,0.5)", "type": "dotted"},
            "label": {"formatter": f"现价 {curr_price}", "color": "#00ff88", "fontSize": 10},
        })

    # Best buy point marker
    if bp_idx_orig is not None and isinstance(bp_idx_orig, int):
        adj_idx = bp_idx_orig - slice_start
        if 0 <= adj_idx < len(dates_sliced) and bp_price:
            is_near_expiry = bp.get("signal_age_days") is not None and bp.get("signal_age_days", 0) >= 8
            marker_label = bp_type + (" ⚠接近过期" if is_near_expiry else "")
            marker_color = "#ffa502" if is_near_expiry else "#ff4757"
            annotations["markPoints"].append({
                "name": bp_type,
                "coord": [dates_sliced[adj_idx], float(bp_price)],
                "symbol": "pin",
                "symbolSize": 36 if is_near_expiry else 30,
                "itemStyle": {"color": marker_color},
                "label": {"formatter": marker_label, "color": marker_color, "fontSize": 10},
            })

    # Strong startup: start day and confirm day markers
    startup_idx = bp.get("startup_index")
    startup_date = bp.get("startup_date", "")
    if startup_idx is not None and isinstance(startup_idx, int) and dates_sliced:
        adj_startup = startup_idx - slice_start
        if 0 <= adj_startup < len(dates_sliced):
            annotations["markPoints"].append({
                "name": "startup",
                "coord": [dates_sliced[adj_startup], float(closes_sliced[adj_startup]) if closes_sliced else 0],
                "symbol": "triangle",
                "symbolSize": 20,
                "itemStyle": {"color": "#00ff88"},
                "label": {"formatter": "启动日", "color": "#00ff88", "fontSize": 10},
            })

    confirm_idx = bp.get("confirm_index")
    confirm_date = bp.get("confirm_date", "")
    if confirm_idx is not None and isinstance(confirm_idx, int):
        # confirm index is on 30min chart, show as label on daily chart when available
        if confirm_date:
            annotations["labels"].append(f"确认日: {confirm_date}")

    # Seed reason label
    seed_reason = bp.get("seed_reason", "")
    if seed_reason and dates_sliced:
        annotations["labels"].append(seed_reason)

    # Near expiry warning label
    signal_age = bp.get("signal_age_days")
    if signal_age is not None and signal_age >= 8 and dates_sliced:
        annotations["labels"].append(f"信号接近过期（{signal_age}天）")

    return annotations


def build_startup_watch_chart_annotations(watch_item, slice_start, dates_sliced, closes_sliced):
    """Build chart annotations for a startup watchlist item.

    Only daily K-line (no 30min). Annotations:
    - 启动日 markPoint (triangle, orange)
    - 参考价 markLine (blue dotted)
    - 现价 markLine (green dotted)
    - 接近过期 label (startup_age_days >= 8)
    """
    annotations = {"markLines": [], "markPoints": [], "labels": []}

    # 启动日 markPoint
    startup_idx = watch_item.get("startup_index")
    if startup_idx is not None and isinstance(startup_idx, int) and dates_sliced:
        adj_startup = startup_idx - slice_start
        if 0 <= adj_startup < len(dates_sliced):
            startup_price = float(closes_sliced[adj_startup]) if closes_sliced else 0
            annotations["markPoints"].append({
                "name": "startup",
                "coord": [dates_sliced[adj_startup], startup_price],
                "symbol": "triangle",
                "symbolSize": 20,
                "itemStyle": {"color": "#ffa502"},
                "label": {"formatter": "启动日", "color": "#ffa502", "fontSize": 10},
            })

    # 参考价 markLine
    ref_price = watch_item.get("close")
    if ref_price and dates_sliced:
        annotations["markLines"].append({
            "name": "source",
            "yAxis": float(ref_price),
            "lineStyle": {"color": "rgba(116,185,255,0.5)", "type": "dotted"},
            "label": {"formatter": f"参考 {float(ref_price):.2f}", "color": "#74b9ff", "fontSize": 10},
        })

    # 现价 markLine
    if closes_sliced and dates_sliced and len(closes_sliced) > 0:
        curr_price = float(closes_sliced[-1])
        annotations["markLines"].append({
            "name": "current",
            "yAxis": curr_price,
            "lineStyle": {"color": "rgba(0,255,136,0.5)", "type": "dotted"},
            "label": {"formatter": f"现价 {curr_price:.2f}", "color": "#00ff88", "fontSize": 10},
        })

    # 接近过期 label
    age_days = watch_item.get("startup_age_days")
    if age_days is not None and age_days >= 8:
        annotations["labels"].append(f"信号接近过期（{age_days}天）")

    return annotations


def _serialize_macd(pick, _slice, closes_sliced):
    """Get MACD histogram, with fallback recomputation if data is all-zero."""
    raw = _slice(pick.get("macd_hist", []))
    if raw and any(abs(v) > 1e-9 for v in raw if v is not None):
        return raw
    full_closes = _safe_list(pick.get("closes", []))
    if len(full_closes) > 10:
        try:
            _, _, hist = calc_macd(full_closes)
            full_hist = _safe_list(hist)
            # Use the same chart window _slice so lengths match other arrays
            fallback = _slice(full_hist)
            if fallback:
                return fallback
        except Exception:
            pass
    return raw if raw else [0.0] * len(closes_sliced)


def _serialize_signal_context_for_report(context):
    """Keep classifier context JSON-safe for report output."""
    if not isinstance(context, Mapping):
        return {}

    result = {}
    for key in (
        "trend_strength",
        "volatility",
        "trend_type",
        "market_env",
        "type",
        "signal_type",
    ):
        if key in context:
            result[key] = context.get(key)

    if "pivot" in context:
        result["has_pivot"] = context.get("pivot") is not None
    if "segment" in context:
        result["has_segment"] = context.get("segment") is not None
    return result


def _sanitize_buy_point_for_report(bp):
    if not bp:
        return {}
    item = dict(bp)
    if "context" in item:
        item["context"] = _serialize_signal_context_for_report(item.get("context"))
    return item


def _serialize_picks(picks):
    """将 picks 列表转为 JSON-safe 格式，使用动态图表窗口"""
    result = []
    for p in picks:
        raw_dates = _safe_list(p.get("dates", []))
        n_orig = len(raw_dates)
        slice_start, slice_end = build_chart_window(p)
        index_offset = slice_start

        def _slice(arr):
            lst = _safe_list(arr)
            if slice_start >= len(lst):
                return []
            return lst[slice_start:slice_end]

        def _adjust_bp(bp):
            if not bp or not bp.get("type"):
                return None
            d = _sanitize_buy_point_for_report(bp)
            orig_idx = d.get("index", 0)
            if slice_start <= orig_idx < slice_end:
                d["index"] = orig_idx - index_offset
                return d
            return None

        def _adjust_bp_keep(bp):
            if not bp or not bp.get("type"):
                return {}
            d = _sanitize_buy_point_for_report(bp)
            orig_idx = d.get("index", 0)
            if slice_start <= orig_idx < slice_end:
                d["index"] = orig_idx - index_offset
            else:
                d["index"] = None
            return d

        dates_sliced = _slice(raw_dates)
        closes_sliced = _slice(p.get("closes", []))

        # Compute reference / current price
        bp = p.get("best_buy_point", {})
        ref_price = bp.get("price", 0) if bp else 0
        closes_arr = p.get("closes")
        if closes_arr is not None and len(closes_arr) > 0:
            curr_price = float(closes_arr[-1])
        else:
            curr_price = 0
        dist_pct = round((curr_price - ref_price) / ref_price * 100, 2) if ref_price and ref_price > 0 else None
        change_pct = _compute_pick_change_pct(p, bp)

        # Attach computed fields to bp for serialization
        bp_enhanced = dict(bp) if bp else {}
        bp_enhanced.setdefault("reference_price", ref_price)
        bp_enhanced.setdefault("current_price", curr_price)
        bp_enhanced.setdefault("distance_from_reference_pct", dist_pct)

        item = {
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "signal_tier": p.get("signal_tier", ""),
            "source_channel": p.get("source_channel", ""),
            "tier": p.get("tier", ""),
            "category": p.get("category", ""),
            "quality_tier": p.get("quality_tier", ""),
            "view": p.get("view", "main"),
            "reference_type": p.get("reference_type", ""),
            "change_pct": change_pct,
            "best_buy_point": _adjust_bp_keep(bp_enhanced),
            "buy_points_30min": [b for b in (_adjust_bp(b) for b in p.get("buy_points_30min", [])) if b is not None],
            "pivots": p.get("pivots", {}),
            "trend_type": p.get("trend_type", ""),
            "sector_tags": p.get("sector_tags", []),
            "sector_rank": p.get("sector_rank"),
            "sector_flow": p.get("sector_flow"),
            "sector_strength_label": p.get("sector_strength_label", ""),
            "market_cap": p.get("market_cap"),
            "circulating_market_cap": p.get("circulating_market_cap"),
            "float_market_cap": p.get("float_market_cap"),
            "money20": p.get("money20"),
            "industry": p.get("industry", ""),
            "data_status": p.get("data_status", {}),
            "gf_dma_health": p.get("gf_dma_health", {}),
            "score": p.get("score", 0),
            "decision_engine_v1": p.get("decision_engine_v1"),
            "position_distance_pct": p.get("position_distance_pct"),
            "position_reference_price": p.get("position_reference_price"),
            "position_reference_type": p.get("position_reference_type", ""),
            "position_data_status": p.get("position_data_status", ""),
            "position_evidence_date": p.get("position_evidence_date", ""),
            "position_absolute_percentile": p.get("position_absolute_percentile"),
            "position_absolute_window": p.get("position_absolute_window", 0),
            "sector": p.get("sector", ""),
            "resonance": p.get("resonance", {}),
            "ma_bullish": p.get("ma_bullish", False),
            "stop_loss": p.get("stop_loss"),
            "stop_loss_pct": p.get("stop_loss_pct"),
            "trailing_targets": p.get("trailing_targets", []),
            "is_active": p.get("is_active", False),
            "market_trend": p.get("market_trend", ""),
            "version": p.get("version", ""),
            "market_regime": p.get("market_regime", ""),
            "fusion_admission": p.get("fusion_admission", {}),
            # 图表数据（动态窗口）
            "dates": dates_sliced,
            "closes": closes_sliced,
            "opens": _slice(p.get("opens", [])),
            "highs": _slice(p.get("highs", [])),
            "lows": _slice(p.get("lows", [])),
            "volumes": _slice(p.get("volumes", [])),
            "macd_hist": _serialize_macd(p, _slice, closes_sliced),
            # 图表标注
            "chart_annotations": build_chart_annotations(p, slice_start, dates_sliced, closes_sliced),
            # 买卖点标注（超出图表范围的已过滤）
            "buy_points": [b for b in (_adjust_bp(b) for b in p.get("buy_points", [])) if b is not None],
            "reference_buy_points": [_serialize_bp(b) for b in p.get("reference_buy_points", [])],
            "blocked_buy_points": [_serialize_bp(b) for b in p.get("blocked_buy_points", [])],
            # 中枢
            "pivot_zg": p["pivots"].get("ZG") if p.get("pivots") else None,
            "pivot_zd": p["pivots"].get("ZD") if p.get("pivots") else None,
        }
        result.append(item)
    return result


def _serialize_sell_signals(sell_list):
    """将卖出信号列表转为 JSON-safe 格式"""
    result = []
    for s in sell_list:
        result.append({
            "code": s.get("code", ""),
            "name": s.get("name", ""),
            "sell_points": [_serialize_bp(b) for b in s.get("sell_points", [])],
            "trend_type": s.get("trend_type", ""),
            "divergence": {
                "is_divergence": s.get("divergence", {}).get("is_divergence", False),
                "type": s.get("divergence", {}).get("type", ""),
                "area_ratio": s.get("divergence", {}).get("area_ratio", 1.0),
            } if s.get("divergence") else {},
            "sector": s.get("sector", ""),
        })
    return result


def _serialize_startup_watchlist(watchlist):
    """Serialize startup watchlist items for JSON output, including chart data."""
    result = []
    for w in watchlist:
        closes_arr = _safe_list(w.get("closes", []))
        raw_dates = _safe_list(w.get("dates", []))

        # 计算现价
        if closes_arr and len(closes_arr) > 0:
            curr_price = float(closes_arr[-1])
        else:
            curr_price = 0
        ref_price = w.get("reference_price") or w.get("close", 0)
        dist_pct = round((curr_price - ref_price) / ref_price * 100, 2) if ref_price and ref_price > 0 else None

        # 图表窗口切片（最近50根K线）
        n_orig = len(raw_dates)
        slice_start = max(0, n_orig - CHART_MAX_BARS)
        slice_end = n_orig

        def _slice(arr):
            lst = _safe_list(arr)
            if slice_start >= len(lst):
                return []
            return lst[slice_start:slice_end]

        dates_sliced = _slice(raw_dates)
        closes_sliced = _slice(closes_arr)
        opens_sliced = _slice(w.get("opens", []))
        highs_sliced = _slice(w.get("highs", []))
        lows_sliced = _slice(w.get("lows", []))
        volumes_sliced = _slice(w.get("volumes", []))

        # MACD histogram
        macd_hist_sliced = _slice(w.get("macd_hist", []))
        if not macd_hist_sliced and len(closes_sliced) > 10:
            try:
                _, _, hist = calc_macd(closes_sliced)
                macd_hist_sliced = _safe_list(hist)
            except Exception:
                macd_hist_sliced = [0.0] * len(closes_sliced)

        # Build annotations
        chart_annotations = build_startup_watch_chart_annotations(
            w, slice_start, dates_sliced, closes_sliced
        )

        item = {
            "code": w.get("code", ""),
            "name": w.get("name", ""),
            "sector": w.get("sector", ""),
            "sector_tags": w.get("sector_tags", []),
            "sector_rank": w.get("sector_rank"),
            "sector_flow": w.get("sector_flow"),
            "sector_strength_label": w.get("sector_strength_label", ""),
            "data_status": w.get("data_status", {}),
            "type": w.get("type", "强势启动观察"),
            "tier": w.get("tier", "watch"),
            "category": w.get("category", "C"),
            "quality_tier": w.get("quality_tier", ""),
            "source_channel": w.get("source_channel", "low_position"),
            "view": w.get("view", "observation"),
            "source_type": w.get("source_type", ""),
            "reference_type": w.get("reference_type", ""),
            "reference_price": ref_price,
            "startup_reason": w.get("startup_reason", ""),
            "startup_signals": w.get("startup_signals", []),
            "daily_startup_grade": w.get("daily_startup_grade", ""),
            "daily_startup_label": w.get("daily_startup_label", ""),
            "daily_startup_warning": w.get("daily_startup_warning", ""),
            "sublevel_confirm_grade": w.get("sublevel_confirm_grade", ""),
            "sublevel_confirm_label": w.get("sublevel_confirm_label", ""),
            "sublevel_confirm_reason": w.get("sublevel_confirm_reason", ""),
            "confirmed_by": w.get("confirmed_by", ""),
            "confirmations": w.get("confirmations", []),
            "startup_index": w.get("startup_index"),
            "startup_date": w.get("startup_date", ""),
            "startup_age_days": w.get("startup_age_days"),
            "change_pct": w.get("change_pct", 0),
            "volume_ratio": w.get("volume_ratio", 0),
            "decision_engine_v1": w.get("decision_engine_v1"),
            "close": ref_price,
            "current_price": curr_price,
            "distance_from_reference_pct": dist_pct,
            "avoid_chase": w.get("avoid_chase", True),
            "watch_reason": w.get("watch_reason", ""),
            "reason_code": w.get("reason_code", ""),
            "failure_gate": w.get("failure_gate", ""),
            "actual_value": w.get("actual_value"),
            "upgrade_conditions": w.get("upgrade_conditions", []),
            "next_day_conditions": w.get("next_day_conditions", []),
            "cancel_conditions": w.get("cancel_conditions", []),
            "is_recent": w.get("is_recent", True),
            "recency_reason": w.get("recency_reason", ""),
            # 图表数据
            "dates": dates_sliced,
            "closes": closes_sliced,
            "opens": opens_sliced,
            "highs": highs_sliced,
            "lows": lows_sliced,
            "volumes": volumes_sliced,
            "macd_hist": macd_hist_sliced,
            "chart_annotations": chart_annotations,
        }
        result.append(item)
    return result


def _build_candidate_series_payload(candidate):
    """Build chart/annotation payload for acceleration and luojie candidates."""
    dates = _safe_list(candidate.get("dates", []))
    closes = _safe_list(candidate.get("closes", []))
    pair_len = min(len(dates), len(closes))

    if pair_len <= 0:
        return {
            "dates": dates,
            "closes": closes,
            "chart_annotations": {"markLines": [], "markPoints": [], "labels": []},
        }

    aligned_dates = dates[-pair_len:]
    aligned_closes = closes[-pair_len:]
    slice_start = max(0, pair_len - CHART_MAX_BARS)
    chart_dates = aligned_dates[slice_start:]
    chart_closes = aligned_closes[slice_start:]

    ref_price = candidate.get("reference_price")
    if ref_price is None:
        ref_price = candidate.get("close")
    if ref_price is None:
        ref_price = candidate.get("life_line")

    chart_item = dict(candidate)
    if ref_price is not None:
        chart_item["close"] = ref_price

    chart_annotations = build_startup_watch_chart_annotations(
        chart_item,
        slice_start,
        chart_dates,
        chart_closes,
    )
    return {
        "dates": dates,
        "closes": closes,
        "chart_annotations": chart_annotations,
    }


def _serialize_next_day_boom(data):
    """Serialize next-day boom selector output."""
    data = data or {}
    candidates = []
    for c in data.get("candidates", []) or []:
        timeseries = _build_candidate_series_payload(c)
        closes = timeseries["closes"]
        change_pct = c.get("change_pct")
        if change_pct is None:
            change_pct = _compute_pick_change_pct(c)  # fallback from closes
            if change_pct is None:
                change_pct = 0
        current_price = c.get("current_price")
        if current_price is None:
            current_price = closes[-1] if closes else c.get("close")
        if current_price is None:
            current_price = 0

        candidates.append({
            "rank": c.get("rank"),
            "code": c.get("code", ""),
            "name": c.get("name", ""),
            "sector": c.get("sector", ""),
            "sector_tags": c.get("sector_tags", []),
            "sector_rank": c.get("sector_rank"),
            "sector_flow": c.get("sector_flow"),
            "sector_strength_label": c.get("sector_strength_label", ""),
            "data_status": c.get("data_status", {}),
            "source_pool": c.get("source_pool", ""),
            "source_type": c.get("source_type", ""),
            "boom_score": c.get("boom_score", 0),
            "boom_reason": c.get("boom_reason", ""),
            "decision_engine_v1": c.get("decision_engine_v1"),
            "change_pct": change_pct,
            "current_price": current_price,
            "volume_ratio": c.get("volume_ratio", 0),
            "market_change_pct": c.get("market_change_pct", data.get("market_change_pct", 0)),
            "ma_bullish": c.get("ma_bullish", False),
            "startup_reason": c.get("startup_reason", ""),
            "confirmed_by": c.get("confirmed_by", ""),
            "confirmations": c.get("confirmations", []),
            "reference_price": c.get("reference_price"),
            "dates": timeseries["dates"],
            "closes": closes,
            "chart_annotations": timeseries["chart_annotations"],
        })
    return {
        "mode": data.get("mode", "disabled"),
        "reason": data.get("reason", ""),
        "market_change_pct": data.get("market_change_pct", 0),
        "enable_threshold_pct": data.get("enable_threshold_pct", 1.0),
        "top_n": data.get("top_n", len(candidates)),
        "source_counts": data.get("source_counts", {}),
        "candidates": candidates,
    }


def _serialize_luojie_pool(data):
    """Serialize LuoJie pool output."""
    data = data or {}
    candidates = []
    for c in data.get("candidates", []) or []:
        timeseries = _build_candidate_series_payload(c)
        closes = timeseries["closes"]
        change_pct = c.get("change_pct")
        if change_pct is None:
            change_pct = _compute_pick_change_pct(c)  # fallback from closes
            if change_pct is None:
                change_pct = 0
        current_price = c.get("current_price")
        if current_price is None:
            current_price = closes[-1] if closes else c.get("close")
        if current_price is None:
            current_price = 0
        distance_life_pct = c.get("distance_life_pct")
        if distance_life_pct is None:
            life_line = c.get("life_line")
            if life_line:
                distance_life_pct = round((current_price - life_line) / life_line * 100, 2)

        candidates.append({
            "rank": c.get("rank"),
            "code": c.get("code", ""),
            "name": c.get("name", ""),
            "sector": c.get("sector", ""),
            "sector_tags": c.get("sector_tags", []),
            "sector_rank": c.get("sector_rank"),
            "sector_flow": c.get("sector_flow"),
            "sector_strength_label": c.get("sector_strength_label", ""),
            "data_status": c.get("data_status", {}),
            "theme_labels": c.get("theme_labels", []),
            "tier": c.get("tier", ""),
            "score": c.get("score", 0),
            "decision_engine_v1": c.get("decision_engine_v1"),
            "close": c.get("close", 0),
            "life_line": c.get("life_line", 0),
            "ma13": c.get("ma13", 0),
            "ma77": c.get("ma77", 0),
            "distance_life_pct": distance_life_pct,
            "distance_ma77_pct": c.get("distance_ma77_pct", 0),
            "macd_status": c.get("macd_status", ""),
            "macd_above_zero": c.get("macd_above_zero", False),
            "buy_point_type": c.get("buy_point_type", "-"),
            "pivot_status": c.get("pivot_status", ""),
            "risk_line": c.get("risk_line", 0),
            "reduce_line": c.get("reduce_line", 0),
            "change_pct": change_pct,
            "current_price": current_price,
            "reason": c.get("reason", ""),
            "dates": timeseries["dates"],
            "closes": closes,
            "chart_annotations": timeseries["chart_annotations"],
        })
    return {
        "mode": data.get("mode", "disabled"),
        "reason": data.get("reason", ""),
        "params": data.get("params", {}),
        "diagnostics": data.get("diagnostics", {}),
        "candidates": candidates,
    }


def _serialize_h4_t3_pool(data):
    """Serialize the production-attested H4 T+3 pool."""
    data = data or {}
    raw_candidates = data.get("candidates", []) or []
    candidates = _serialize_picks(raw_candidates)
    for raw, item in zip(raw_candidates, candidates):
        predictions = raw.get("h4_predictions")
        item["h4_predictions"] = (
            dict(predictions) if isinstance(predictions, Mapping) else {}
        )
        item["reason"] = raw.get("reason", "H4 T+3 全部门槛通过")
    return {
        "status": data.get("status", "error"),
        "production_attested": data.get("production_attested") is True,
        "mode": data.get("mode", "production"),
        "horizon": data.get("horizon", "T+3"),
        "strategy": data.get("strategy", "H4"),
        "strategy_version": data.get("strategy_version", ""),
        "model_date": data.get("model_date"),
        "daily_cap": data.get("daily_cap"),
        "no_backfill": data.get("no_backfill") is True,
        "score_policy": data.get("score_policy", ""),
        "reason": data.get("reason", ""),
        "policy": data.get("policy", {}),
        "diagnostics": data.get("diagnostics", {}),
        "candidates": candidates,
    }


def _serialize_picks_light(picks):
    """轻量版序列化，不含图表数组（用于 data.json 聚合）"""
    result = []
    for p in picks:
        bp = p.get("best_buy_point", {})
        item = {
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "signal_tier": p.get("signal_tier", ""),
            "source_channel": p.get("source_channel", ""),
            "tier": p.get("tier", ""),
            "category": p.get("category", ""),
            "quality_tier": p.get("quality_tier", ""),
            "view": p.get("view", "main"),
            "reference_type": p.get("reference_type", ""),
            "change_pct": _compute_pick_change_pct(p, bp),
            "best_buy_point": _serialize_bp(bp),
            "gf_dma_health": p.get("gf_dma_health", {}),
            "buy_points_30min": [_serialize_bp(b) for b in p.get("buy_points_30min", [])],
            "pivots": p.get("pivots", {}),
            "trend_type": p.get("trend_type", ""),
            "score": p.get("score", 0),
            "market_cap": p.get("market_cap"),
            "circulating_market_cap": p.get("circulating_market_cap"),
            "float_market_cap": p.get("float_market_cap"),
            "money20": p.get("money20"),
            "industry": p.get("industry", ""),
            "decision_engine_v1": p.get("decision_engine_v1"),
            "position_distance_pct": p.get("position_distance_pct"),
            "position_reference_price": p.get("position_reference_price"),
            "position_reference_type": p.get("position_reference_type", ""),
            "position_data_status": p.get("position_data_status", ""),
            "position_evidence_date": p.get("position_evidence_date", ""),
            "position_absolute_percentile": p.get("position_absolute_percentile"),
            "position_absolute_window": p.get("position_absolute_window", 0),
            "sector": p.get("sector", ""),
            "resonance": p.get("resonance", {}),
            "ma_bullish": p.get("ma_bullish", False),
            "stop_loss": p.get("stop_loss"),
            "stop_loss_pct": p.get("stop_loss_pct"),
            "trailing_targets": p.get("trailing_targets", []),
            "is_active": p.get("is_active", False),
            "market_trend": p.get("market_trend", ""),
            "version": p.get("version", ""),
            "market_regime": p.get("market_regime", ""),
            "fusion_admission": p.get("fusion_admission", {}),
            "buy_points": [_serialize_bp(b) for b in p.get("buy_points", [])],
            "reference_buy_points": [_serialize_bp(b) for b in p.get("reference_buy_points", [])],
            "blocked_buy_points": [_serialize_bp(b) for b in p.get("blocked_buy_points", [])],
            "pivot_zg": p["pivots"].get("ZG") if p.get("pivots") else None,
            "pivot_zd": p["pivots"].get("ZD") if p.get("pivots") else None,
        }
        result.append(item)
    return result


def _compute_pick_change_pct(pick, best_buy_point=None):
    for value in (
        pick.get("change_pct"),
        (best_buy_point or {}).get("change_pct"),
    ):
        if value is not None:
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                pass

    closes = _safe_list(pick.get("closes", []))
    if len(closes) < 2:
        return None
    try:
        prev_close = float(closes[-2])
        latest_close = float(closes[-1])
    except (TypeError, ValueError):
        return None
    if prev_close == 0:
        return None
    return round((latest_close - prev_close) / prev_close * 100, 2)


def _serialize_bp(bp):
    if not bp:
        return {}
    return {
        "type": bp.get("type", ""),
        "tier": bp.get("tier", ""),
        "index": bp.get("index", 0),
        "price": bp.get("price", 0),
        "date": str(bp.get("date", "")),
        "reason": bp.get("reason", ""),
        "strength": bp.get("strength", ""),
        "source_type": bp.get("source_type", ""),
        "confirmed_by": bp.get("confirmed_by", ""),
        "confirmations": bp.get("confirmations", []),
        "seed_type": bp.get("seed_type", ""),
        "seed_reason": bp.get("seed_reason", ""),
        "signal_age_days": bp.get("signal_age_days"),
        "is_recent": bp.get("is_recent", True),
        "recency_reason": bp.get("recency_reason", ""),
        "signal_date": bp.get("signal_date", ""),
        "startup_index": bp.get("startup_index"),
        "startup_date": bp.get("startup_date", ""),
        "startup_age_days": bp.get("startup_age_days"),
        "confirm_index": bp.get("confirm_index"),
        "confirm_date": bp.get("confirm_date", ""),
        "confirm_age_days": bp.get("confirm_age_days"),
        "reference_price": bp.get("reference_price"),
        "current_price": bp.get("current_price"),
        "distance_from_reference_pct": bp.get("distance_from_reference_pct"),
        "startup_reason": bp.get("startup_reason", ""),
        "startup_signals": bp.get("startup_signals", []),
        "change_pct": bp.get("change_pct"),
        "volume_ratio": bp.get("volume_ratio"),
    }


def _safe_list(arr):
    """安全转换 numpy array 到 list，处理 NaN 和日期字符串"""
    if arr is None:
        return []
    if isinstance(arr, np.ndarray):
        arr = arr.tolist()
    result = []
    for x in arr:
        if x is None:
            result.append(None)
        elif isinstance(x, str):
            result.append(x)
        elif isinstance(x, (int, float, np.floating, np.integer)):
            val = float(x)
            result.append(None if np.isnan(val) else val)
        else:
            result.append(str(x))
    return result


def _score_sort_value(item):
    value = item.get("opportunity_score")
    if isinstance(value, (int, float, np.floating, np.integer)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _copy_workspace_score_fields(raw_item, workspace_item):
    for key in ("opportunity_score", "watch_score", "view_rank", "rank_trace"):
        if key in workspace_item:
            raw_item[key] = workspace_item[key]
    if "decision_engine_v1" in workspace_item:
        raw_item["decision_engine_v1"] = workspace_item["decision_engine_v1"]
    if "rank" in raw_item and workspace_item.get("view_rank") is not None:
        raw_item["rank"] = workspace_item["view_rank"]


def _backfill_workspace_scores_for_items(items, workspace_items):
    by_code = {
        str(item.get("code", "")): item
        for item in workspace_items or []
        if item.get("code")
    }
    for raw_item in items or []:
        workspace_item = by_code.get(str(raw_item.get("code", "")))
        if workspace_item:
            _copy_workspace_score_fields(raw_item, workspace_item)
    items.sort(key=lambda item: (-_score_sort_value(item), str(item.get("code", ""))))
    for index, raw_item in enumerate(items, start=1):
        if "rank" in raw_item:
            raw_item["rank"] = index


def _backfill_workspace_scores(daily_data):
    workspace = daily_data.get("workspace") or {}
    views = workspace.get("views") or {}

    _backfill_workspace_scores_for_items(daily_data.get("picks_fusion", []), views.get("main", []))
    _backfill_workspace_scores_for_items(daily_data.get("picks_pure", []), views.get("baseline", []))
    _backfill_workspace_scores_for_items(daily_data.get("startup_watchlist", []), views.get("confirming", []))
    _backfill_workspace_scores_for_items(
        daily_data.get("observation_watchlist", []),
        views.get("observation_top5", []),
    )

    next_day_boom = daily_data.get("next_day_boom") or {}
    if isinstance(next_day_boom, dict):
        _backfill_workspace_scores_for_items(next_day_boom.get("candidates", []), views.get("acceleration", []))

    luojie_pool = daily_data.get("luojie_pool") or {}
    if isinstance(luojie_pool, dict):
        _backfill_workspace_scores_for_items(luojie_pool.get("candidates", []), views.get("luojie", []))

    h4_t3_pool = daily_data.get("h4_t3_pool") or {}
    if isinstance(h4_t3_pool, dict):
        _backfill_workspace_scores_for_items(h4_t3_pool.get("candidates", []), views.get("h4_t3", []))


def _escape_inline_json(data):
    """Serialize JSON used in HTML script with `<`, `>`, `&` escaped for safety."""
    return (
        json.dumps(data, ensure_ascii=False, cls=NpEncoder)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _copy_if_changed(src_path, dst_path):
    """Copy a file only when content changes."""
    with open(src_path, "rb") as f:
        src_bytes = f.read()

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    if os.path.exists(dst_path):
        try:
            with open(dst_path, "rb") as f:
                if f.read() == src_bytes:
                    return False
        except OSError:
            # Any failure to read target file means we should rewrite it.
            pass

    with open(dst_path, "wb") as f:
        f.write(src_bytes)
    return True


def _report_asset_source_dir():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root_dir, "chanlun", "report_assets")


def _report_asset_version():
    digest = hashlib.sha256()
    source_dir = _report_asset_source_dir()
    for asset in REPORT_V2_ASSETS:
        digest.update(asset.encode("utf-8"))
        digest.update(b"\0")
        with open(os.path.join(source_dir, asset), "rb") as f:
            digest.update(f.read())
    return digest.hexdigest()[:12]


def copy_report_assets(output_dir):
    """Copy shared v2 assets to output_dir/assets with stable-content semantics."""
    source_dir = _report_asset_source_dir()
    target_dir = os.path.join(output_dir, "assets")

    copied = 0
    for asset in REPORT_V2_ASSETS:
        source_path = os.path.join(source_dir, asset)
        target_path = os.path.join(target_dir, asset)
        changed = _copy_if_changed(source_path, target_path)
        if changed:
            copied += 1

    return copied


def write_comparison_page(output_dir, top10_api_base, asset_version=None):
    """Render the standalone comparison page with the same quote API config."""
    source_path = os.path.join(_report_asset_source_dir(), "comparison.html")
    with open(source_path, "r", encoding="utf-8") as handle:
        template = handle.read()

    api_base_json = _escape_inline_json(
        str(top10_api_base or "").strip().rstrip("/")
    )
    html = template.replace('"__CHANLUN_TOP10_API_BASE__"', api_base_json)
    if "__CHANLUN_TOP10_API_BASE__" in html:
        raise ValueError("comparison bootstrap placeholder was not replaced")
    if asset_version:
        html = html.replace(
            "../assets/report-v2.css\"",
            f"../assets/report-v2.css?v={asset_version}\"",
        ).replace(
            "../assets/report-v2.js\"",
            f"../assets/report-v2.js?v={asset_version}\"",
        )

    target_path = os.path.join(output_dir, "compare", "index.html")
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    encoded = html.encode("utf-8")
    if os.path.exists(target_path):
        with open(target_path, "rb") as handle:
            if handle.read() == encoded:
                return target_path
    with open(target_path, "wb") as handle:
        handle.write(encoded)
    return target_path


def _build_report_v2_html(date_str, bootstrap_json, asset_prefix="", asset_version=None):
    """Build the lightweight v2 HTML shell."""
    asset_query = f"?v={asset_version}" if asset_version else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>缠论选股日报 — {date_str}</title>
<link rel="icon" type="image/svg+xml" href='data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="%230b0f14"/><path d="M7 22h18M7 16h12M7 10h18" stroke="%2300e676" stroke-width="2.4" stroke-linecap="round"/></svg>'>
<script src="https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js"></script>
<link rel="stylesheet" href="{asset_prefix}assets/report-v2.css{asset_query}">
</head>
<body>
<div id="app"></div>

<script>
(function() {{
  var path = (window.location.pathname || '').replace(/\/+$/, '');
  var dataBasePrefix = /\/\d{{4}}-\d{{2}}-\d{{2}}$/.test(path) ? '../' : '';
  window.CHANLUN_BOOTSTRAP = {bootstrap_json};
  window.CHANLUN_BOOTSTRAP.dataBasePrefix = dataBasePrefix;
  window.CHANLUN_BOOTSTRAP.isFileProtocol = (window.location.protocol === 'file:');
}})();
</script>
<script src="{asset_prefix}assets/report-v2.js{asset_query}" defer></script>
</body>
</html>"""


# ============================================================
# 历史推荐回看（最近 N 个交易日，仅高质量类型）
# ============================================================
RECENT_REVIEW_DAYS = 5
RECENT_REVIEW_WHITELIST_PURE = {"二买", "三买", "二买候选", "三买候选"}
RECENT_REVIEW_WHITELIST_FUSION = {"二买", "三买", "二买候选", "三买候选", "强势启动候选"}


def build_recent_reviews(date_str, output_dir):
    """生成最近 N 个交易日的推荐回看数据。

    口径：
    - 5 个交易日，从 docs/data/index.json 读交易日列表（不含当天 date_str）
    - 类型白名单：pure 二买/三买/二买候选/三买候选；fusion 多收一个强势启动候选
    - 每个 (code) 仅保留最早一次推荐
    - 推荐价 = best_buy_point.price；当前价 = 最新交易日收盘
    - 是否触止损 = 推荐次日起最低价 ≤ stop_loss

    Returns: list[dict]，按推荐日升序
    """
    data_dir = os.path.join(output_dir, "data")
    index_path = os.path.join(data_dir, "index.json")
    if not os.path.exists(index_path):
        return []

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    all_dates = sorted(manifest.get("trading_dates") or manifest.get("dates", []))
    past_dates = [d for d in all_dates if d < date_str][-RECENT_REVIEW_DAYS:]
    if not past_dates:
        return []

    seen_codes = set()
    rows = []
    for d in past_dates:
        snap_path = os.path.join(data_dir, f"{d}.json")
        if not os.path.exists(snap_path):
            continue
        try:
            with open(snap_path, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        for ver_key, whitelist in (
            ("picks_pure", RECENT_REVIEW_WHITELIST_PURE),
            ("picks_fusion", RECENT_REVIEW_WHITELIST_FUSION),
        ):
            for pick in (snap.get(ver_key) or []):
                code = pick.get("code", "")
                if not code or code in seen_codes:
                    continue
                bbp = pick.get("best_buy_point") or {}
                bp_type = bbp.get("type", "")
                if bp_type not in whitelist:
                    continue
                ref_price = bbp.get("price")
                if not ref_price:
                    continue
                seen_codes.add(code)
                rows.append({
                    "rec_date": d,
                    "code": code,
                    "name": pick.get("name", ""),
                    "type": bp_type,
                    "version": "fusion" if ver_key == "picks_fusion" else "pure",
                    "ref_price": float(ref_price),
                    "stop_loss": pick.get("stop_loss"),
                })

    if not rows:
        return []

    # 拉每只票从推荐日到当前的 K 线，算涨跌 / 是否触止损
    from chanlun.data_fetcher import fetch_daily_kline

    enriched = []
    for row in rows:
        kline = fetch_daily_kline(row["code"], count=30)
        dates_value = kline.get("dates") if kline else None
        closes_value = kline.get("closes") if kline else None
        lows_value = kline.get("lows") if kline else None
        dates_raw = list(dates_value) if dates_value is not None else []
        closes_raw = list(closes_value) if closes_value is not None else []
        lows_raw = list(lows_value) if lows_value is not None else []
        if not dates_raw or not closes_raw:
            enriched.append({**row, "current_price": None, "change_pct": None,
                             "stop_triggered": None, "lookback_days": 0,
                             "trigger_date": None, "current_date": "", "data_status": "missing"})
            continue
        dates = [str(d).split()[0] for d in dates_raw]
        rec = row["rec_date"]
        closes = [float(x) for x in closes_raw]
        latest_close = closes[-1]
        change_pct = round((latest_close - row["ref_price"]) / row["ref_price"] * 100, 2)
        current_date = dates[-1] if dates else ""
        data_status = "verified" if current_date == date_str else "stale_cache"

        if rec in dates:
            start_idx = dates.index(rec) + 1
        else:
            start_idx = next((i for i, d in enumerate(dates) if d > rec), len(dates))
        forward_lows = [float(x) for x in lows_raw[start_idx:]]
        forward_dates = dates[start_idx:]

        stop = row.get("stop_loss")
        stop_triggered = False
        trigger_date = None
        if stop and forward_lows:
            for fl, fd in zip(forward_lows, forward_dates):
                if fl <= float(stop):
                    stop_triggered = True
                    trigger_date = fd
                    break

        enriched.append({
            **row,
            "current_price": round(latest_close, 2),
            "change_pct": change_pct,
            "stop_triggered": stop_triggered,
            "trigger_date": trigger_date,
            "lookback_days": len(forward_dates),
            "current_date": current_date,
            "data_status": data_status,
        })

    enriched.sort(key=lambda r: (r["rec_date"], r["code"]))
    return enriched


# ============================================================
# HTML 页面生成
# ============================================================
def _generate_report_v2(report_data, output_dir=None, comparison_db_path=None):
    """Generate report with the v2 shell and external assets."""
    date_str = report_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    access_key_hash = ""
    if ENABLE_WEAK_ACCESS_CONTROL and FULL_ACCESS_KEY:
        access_key_hash = hashlib.sha256(
            (FULL_ACCESS_KEY + FULL_ACCESS_KEY_SALT).encode()
        ).hexdigest()

    daily_data = {
        "date": date_str,
        "market": report_data.get("market", {}),
        "chanlun_structure": report_data.get("chanlun_structure", {}),
        "picks_pure": _serialize_picks(report_data.get("picks_pure", [])),
        "picks_fusion": _serialize_picks(report_data.get("picks_fusion", [])),
        "sector_flow": report_data.get("sector_flow", []),
        "sector_outflow": report_data.get("sector_outflow", []),
        "limit_up_pool": report_data.get("limit_up_pool", []),
        "limit_up_snapshot": report_data.get("limit_up_snapshot", {}),
        "market_sentiment": report_data.get("market_sentiment", {}),
        "market_sentiment_history": report_data.get(
            "market_sentiment_history", []
        ),
        "market_temperature": report_data.get("market_temperature", {}),
        "events": report_data.get("events", []),
        "forecast": report_data.get("forecast", {}),
        "sell_signals": _serialize_sell_signals(report_data.get("sell_signals", [])),
        "diagnostics": report_data.get("diagnostics", {}),
        "data_quality": report_data.get("data_quality", {}),
        "startup_watchlist": _serialize_startup_watchlist(report_data.get("startup_watchlist", [])),
        "observation_watchlist": _serialize_startup_watchlist(
            report_data.get("observation_watchlist", [])
        ),
        "next_day_boom": _serialize_next_day_boom(report_data.get("next_day_boom", {})),
        "luojie_pool": _serialize_luojie_pool(report_data.get("luojie_pool", {})),
        "h4_t3_pool": _serialize_h4_t3_pool(report_data.get("h4_t3_pool", {})),
        "recent_reviews": build_recent_reviews(
            date_str,
            output_dir or os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), OUTPUT_DIR
            )
        ),
    }
    daily_data["workspace"] = build_workspace(daily_data)
    _backfill_workspace_scores(daily_data)

    bootstrap = {
        "pageDate": date_str,
        "inlineReportData": daily_data,
        "top10ApiBase": os.environ.get("CHANLUN_TOP10_API_BASE", DEFAULT_TOP10_API_BASE).strip().rstrip("/"),
        "accessControlEnabled": bool(ENABLE_WEAK_ACCESS_CONTROL and FULL_ACCESS_KEY),
        "accessKeyHash": access_key_hash,
        "accessKeySalt": FULL_ACCESS_KEY_SALT if ENABLE_WEAK_ACCESS_CONTROL else "",
    }
    bootstrap_data_json = _escape_inline_json(bootstrap)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_output_dir = os.path.realpath(os.path.abspath(os.path.join(base_dir, OUTPUT_DIR)))
    if output_dir is None:
        output_dir = default_output_dir
    else:
        output_dir = os.path.realpath(os.path.abspath(output_dir))
    is_default_output = output_dir == default_output_dir

    date_dir = os.path.join(output_dir, date_str)
    os.makedirs(date_dir, exist_ok=True)
    data_dir = os.path.join(output_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    write_daily_data_json(daily_data, data_dir)
    dq = daily_data.get("data_quality", {})
    write_data_manifest(
        date_str,
        data_dir,
        is_trading_day=dq.get("is_trading_day", True),
        is_official=dq.get("is_official", True),
    )
    if comparison_db_path is None:
        comparison_db_path = MARKET_HISTORY_DB_PATH if is_default_output else ""
    write_comparison_index(data_dir, comparison_db_path)
    copy_report_assets(output_dir)
    asset_version = _report_asset_version()
    write_comparison_page(
        output_dir,
        bootstrap.get("top10ApiBase", ""),
        asset_version=asset_version,
    )

    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(_build_report_v2_html(
            date_str,
            bootstrap_data_json,
            asset_prefix="",
            asset_version=asset_version,
        ))

    archive_path = os.path.join(date_dir, "index.html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(_build_report_v2_html(
            date_str,
            bootstrap_data_json,
            asset_prefix="../",
            asset_version=asset_version,
        ))

    print(f"  日报已生成: {index_path}")
    print(f"  数据已写入: {data_dir}")
    print(f"  归档至: {archive_path}")
    return index_path


def generate_report(report_data, output_dir=None, comparison_db_path=None):
    """Backward-compatible entrypoint for report generation."""
    return _generate_report_v2(
        report_data,
        output_dir,
        comparison_db_path=comparison_db_path,
    )


# ============================================================
# per-day JSON + manifest
# ============================================================
def write_daily_data_json(daily_data, data_dir):
    """将当日全量数据写入 docs/data/{date}.json"""
    date_str = daily_data["date"]
    path = os.path.join(data_dir, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(daily_data, f, ensure_ascii=False, cls=NpEncoder, indent=2)


def write_data_manifest(date_str, data_dir, is_trading_day=True, is_official=True):
    """维护 docs/data/index.json — 日期列表 + 交易日列表 + 最新日期"""

    def _to_date_list(value):
        if not isinstance(value, (list, tuple)):
            return []
        out = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out

    manifest_path = os.path.join(data_dir, "index.json")
    existing = {
        "dates": [],
        "trading_dates": [],
        "latest": date_str,
        "latest_trading_date": "",
        "date_meta": {},
    }
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    dates = sorted(set(_to_date_list(existing.get("dates", [])) + [date_str]))
    trading_dates = _to_date_list(existing.get("trading_dates"))
    date_meta = existing.get("date_meta", {})
    if not isinstance(date_meta, dict):
        date_meta = {}

    if not trading_dates:
        trading_dates = list(dates)

    def _is_trading_meta_day(date_value):
        meta = date_meta.get(date_value)
        if not isinstance(meta, Mapping):
            return True
        return meta.get("is_trading_day", True) is not False

    trading_dates = sorted(set(
        d for d in trading_dates
        if d in dates and _is_trading_meta_day(d)
    ))

    if is_trading_day:
        trading_dates = sorted(set(trading_dates + [date_str]))
    else:
        trading_dates = [d for d in trading_dates if d != date_str]

    existing["dates"] = dates
    existing["trading_dates"] = trading_dates
    existing["latest"] = date_str
    existing["latest_trading_date"] = (
        date_str if is_trading_day else (sorted(trading_dates)[-1] if trading_dates else "")
    )

    date_meta[date_str] = {
        "is_trading_day": bool(is_trading_day),
        "is_official": bool(is_official),
    }
    existing["date_meta"] = date_meta

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


# ============================================================
# data.json 聚合
# ============================================================
def update_data_json(report_data, output_dir=None):
    """
    将当日报告数据合并到 data.json。
    同时清理超过 HISTORY_DAYS 的旧数据。
    """
    if output_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, OUTPUT_DIR)

    json_path = os.path.join(output_dir, "data.json")

    # 读取现有
    existing = {"dates": [], "reports": {}}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    date_str = report_data["date"]

    # 写入当日（picks 去掉图表数组，data.json 只存轻量索引）
    day_entry = {
        "market": report_data.get("market", {}),
        "chanlun_structure": report_data.get("chanlun_structure", {}),
        "picks_pure": _serialize_picks_light(report_data.get("picks_pure", [])),
        "picks_fusion": _serialize_picks_light(report_data.get("picks_fusion", [])),
        "sector_flow": report_data.get("sector_flow", []),
        "sector_outflow": report_data.get("sector_outflow", []),
        "limit_up_pool": report_data.get("limit_up_pool", []),
        "limit_up_snapshot": report_data.get("limit_up_snapshot", {}),
        "market_sentiment": report_data.get("market_sentiment", {}),
        "market_sentiment_history": report_data.get(
            "market_sentiment_history", []
        ),
        "market_temperature": report_data.get("market_temperature", {}),
        "events": report_data.get("events", []),
        "forecast": report_data.get("forecast", {}),
        "sell_signals": _serialize_sell_signals(report_data.get("sell_signals", [])),
        "diagnostics": report_data.get("diagnostics", {}),
        "data_quality": report_data.get("data_quality", {}),
        "next_day_boom": _serialize_next_day_boom(report_data.get("next_day_boom", {})),
        "luojie_pool": _serialize_luojie_pool(report_data.get("luojie_pool", {})),
    }
    day_entry["workspace"] = build_workspace(day_entry)
    _backfill_workspace_scores(day_entry)
    day_entry.pop("workspace", None)
    existing["reports"][date_str] = day_entry

    # 更新日期列表
    if date_str not in existing["dates"]:
        existing["dates"].append(date_str)
    existing["dates"].sort()

    # 只保留最近 HISTORY_DAYS
    if len(existing["dates"]) > HISTORY_DAYS:
        cutoff = len(existing["dates"]) - HISTORY_DAYS
        old_dates = existing["dates"][:cutoff]
        existing["dates"] = existing["dates"][cutoff:]
        for d in old_dates:
            existing["reports"].pop(d, None)
            # 删除归档目录
            old_dir = os.path.join(output_dir, d)
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir, ignore_errors=True)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, cls=NpEncoder, indent=2)

    print(f"  data.json 已更新，当前保留 {len(existing['dates'])} 天: {existing['dates']}")
    return json_path
