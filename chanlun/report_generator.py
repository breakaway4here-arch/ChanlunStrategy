"""
HTML 日报生成器 — 深色主题，双版本切换，ECharts 走势图

输出结构:
- docs/index.html (最新，含 JSON 数据 + 前端 JS)
- docs/YYYY-MM-DD/index.html (按日期归档)
- docs/data.json (历史5天聚合数据)
"""

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta

import numpy as np

from chanlun.chan_engine import calc_macd

from config import (
    OUTPUT_DIR, HISTORY_DAYS,
    ENABLE_WEAK_ACCESS_CONTROL, PUBLIC_DATES,
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
            d = dict(bp)
            orig_idx = d.get("index", 0)
            if slice_start <= orig_idx < slice_end:
                d["index"] = orig_idx - index_offset
                return d
            return None

        def _adjust_bp_keep(bp):
            if not bp or not bp.get("type"):
                return {}
            d = dict(bp)
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

        # Attach computed fields to bp for serialization
        bp_enhanced = dict(bp) if bp else {}
        bp_enhanced.setdefault("reference_price", ref_price)
        bp_enhanced.setdefault("current_price", curr_price)
        bp_enhanced.setdefault("distance_from_reference_pct", dist_pct)

        item = {
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "signal_tier": p.get("signal_tier", ""),
            "best_buy_point": _adjust_bp_keep(bp_enhanced),
            "buy_points_30min": [b for b in (_adjust_bp(b) for b in p.get("buy_points_30min", [])) if b is not None],
            "pivots": p.get("pivots", {}),
            "trend_type": p.get("trend_type", ""),
            "score": p.get("score", 0),
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
        ref_price = w.get("close", 0)
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
            "type": w.get("type", "强势启动观察"),
            "tier": w.get("tier", "watch"),
            "source_type": w.get("source_type", ""),
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
            "close": ref_price,
            "current_price": curr_price,
            "distance_from_reference_pct": dist_pct,
            "avoid_chase": w.get("avoid_chase", True),
            "watch_reason": w.get("watch_reason", ""),
            "next_day_conditions": w.get("next_day_conditions", []),
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


def _serialize_picks_light(picks):
    """轻量版序列化，不含图表数组（用于 data.json 聚合）"""
    result = []
    for p in picks:
        item = {
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "signal_tier": p.get("signal_tier", ""),
            "best_buy_point": _serialize_bp(p.get("best_buy_point", {})),
            "buy_points_30min": [_serialize_bp(b) for b in p.get("buy_points_30min", [])],
            "pivots": p.get("pivots", {}),
            "trend_type": p.get("trend_type", ""),
            "score": p.get("score", 0),
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


# ============================================================
# HTML 页面生成
# ============================================================
def generate_report(report_data, output_dir=None):
    """
    生成完整的 HTML 日报。

    report_data: {
        "date": "2026-05-23",
        "market": {"上证": {...}, "深证": {...}, ...},
        "chanlun_structure": {...},
        "picks_pure": [...],
        "picks_fusion": [...],
        "sector_flow": [...],
    }
    """
    date_str = report_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    # 计算访问控制 hash（前端不直接暴露明文 key）
    access_key_hash = ""
    if ENABLE_WEAK_ACCESS_CONTROL and FULL_ACCESS_KEY:
        access_key_hash = hashlib.sha256(
            (FULL_ACCESS_KEY + FULL_ACCESS_KEY_SALT).encode()
        ).hexdigest()

    # 全量数据（序列化后写入 per-day JSON，HTML 通过 fetch 加载）
    daily_data = {
        "date": date_str,
        "market": report_data.get("market", {}),
        "chanlun_structure": report_data.get("chanlun_structure", {}),
        "picks_pure": _serialize_picks(report_data.get("picks_pure", [])),
        "picks_fusion": _serialize_picks(report_data.get("picks_fusion", [])),
        "sector_flow": report_data.get("sector_flow", []),
        "sector_outflow": report_data.get("sector_outflow", []),
        "limit_up_pool": report_data.get("limit_up_pool", []),
        "events": report_data.get("events", []),
        "forecast": report_data.get("forecast", {}),
        "sell_signals": _serialize_sell_signals(report_data.get("sell_signals", [])),
        "diagnostics": report_data.get("diagnostics", {}),
        "startup_watchlist": _serialize_startup_watchlist(report_data.get("startup_watchlist", [])),
    }
    bootstrap_data_json = (
        json.dumps(daily_data, ensure_ascii=False, cls=NpEncoder, indent=2)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>缠论选股日报 — {date_str}</title>
<link rel="icon" type="image/svg+xml" href='data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="%230b0f14"/><path d="M7 22h18M7 16h12M7 10h18" stroke="%2300e676" stroke-width="2.4" stroke-linecap="round"/></svg>'>
<script src="https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Microsoft YaHei", sans-serif;
    background: #1a1a2e; min-height: 100vh; padding: 20px; color: #e0e0e0;
}}
.container {{ max-width: 1200px; margin: 0 auto; }}

/* 头部 */
.header {{ background: #252545; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
.header h1 {{ color: #fff; font-size: 26px; margin-bottom: 6px; }}
.header .subtitle {{ color: #888; font-size: 14px; }}

.market-summary {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px; margin-top: 18px;
}}
.index-card {{
    background: rgba(255,255,255,0.05); border-radius: 10px;
    padding: 14px; text-align: center;
}}
.index-card .name {{ font-size: 12px; color: #888; margin-bottom: 4px; }}
.index-card .value {{ font-size: 20px; font-weight: bold; color: #fff; }}
.index-card .change {{ font-size: 13px; margin-top: 4px; }}
.up {{ color: #ff4757; }}
.down {{ color: #2ed573; }}

/* 通用区块 */
.section {{ background: #252545; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
.section-title {{
    color: #fff; font-size: 18px; margin-bottom: 18px;
    padding-bottom: 10px; border-bottom: 2px solid rgba(255,255,255,0.1);
    display: flex; align-items: center; gap: 8px;
}}

/* 版本切换 */
.version-toggle {{
    display: flex; gap: 0; margin-bottom: 20px; border-radius: 8px; overflow: hidden;
}}
.version-btn {{
    flex: 1; padding: 14px 20px; border: 2px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.03); color: #999;
    font-size: 16px; font-weight: bold; cursor: pointer; text-align: center;
    transition: all 0.25s;
}}
.version-btn:first-child {{ border-radius: 8px 0 0 8px; }}
.version-btn:last-child {{ border-radius: 0 8px 8px 0; }}
.version-btn.active {{
    background: linear-gradient(135deg, rgba(255,71,87,0.3), rgba(255,71,87,0.1));
    border-color: rgba(255,71,87,0.6); color: #fff;
}}
.version-btn .badge {{
    display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px;
    margin-left: 6px; background: rgba(255,255,255,0.1);
}}

/* 表格 */
.chan-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.chan-table th {{
    background: rgba(255,255,255,0.06); padding: 10px 8px; text-align: left;
    color: #aaa; font-weight: 600; white-space: nowrap;
}}
.chan-table td {{ padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); }}
.chan-table tr:hover {{ background: rgba(255,255,255,0.03); }}
.chan-table tr.expandable {{ cursor: pointer; }}

.buy-tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 12px; font-weight: bold;
}}
.buy-tag.b1 {{ background: rgba(255,71,87,0.2); color: #ff6b7a; }}
.buy-tag.b2 {{ background: rgba(255,165,0,0.2); color: #ffb347; }}
.buy-tag.b3 {{ background: rgba(46,213,115,0.2); color: #5effa0; }}
.buy-tag.b2l {{ background: rgba(0,191,255,0.2); color: #5ebdff; }}
.buy-tag.candidate {{ background: rgba(255,165,0,0.15); color: #ffb347; border: 1px dashed rgba(255,165,0,0.4); }}
.sell-tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 12px; font-weight: bold;
    background: rgba(46,213,115,0.2); color: #5effa0;
}}

.score-bar {{
    display: inline-block; height: 6px; border-radius: 3px;
    background: linear-gradient(90deg, #ff4757, #ffa502, #2ed573);
    vertical-align: middle; margin-right: 6px;
}}

.pivot-cell {{ font-size: 12px; color: #aaa; }}
.active-dot {{ display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #ff4757; margin-right: 4px; }}

/* 图表区 */
.chart-row {{ display: none; }}
.chart-row.open {{ display: table-row; }}
.chart-container {{ height: 420px; padding: 10px 0; }}

/* 板块标签 */
.sector-tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
.sector-tag {{
    background: rgba(255,71,87,0.12); border: 1px solid rgba(255,71,87,0.3);
    border-radius: 16px; padding: 6px 14px; font-size: 13px;
    display: flex; align-items: center; gap: 6px;
}}
.sector-tag .rank {{ color: #ffd700; font-weight: bold; }}
.sector-tag .sname {{ color: #fff; }}
.sector-tag .sflow {{ font-size: 12px; }}
.sector-tag .sflow.in {{ color: #ff4757; }}
.sector-tag .sflow.out {{ color: #2ed573; }}

/* 历史切换 */
.history-tabs {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
.history-tab {{
    padding: 6px 16px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.15);
    background: transparent; color: #888; cursor: pointer; font-size: 13px;
    transition: all 0.2s;
}}
.history-tab.active {{ background: rgba(255,71,87,0.2); border-color: rgba(255,71,87,0.5); color: #fff; }}

.detail-section {{ margin-top: 12px; color: #aaa; font-size: 13px; line-height: 1.8; }}
.detail-section strong {{ color: #ddd; }}

.footer {{ text-align: center; color: #555; font-size: 12px; padding: 30px 0; }}

/* 数据表格（资金流入/流出共用） */
.data-table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
.data-table th {{
    background: rgba(255,255,255,0.05); padding: 10px 8px; text-align: left;
    color: #888; font-weight: 500; white-space: nowrap;
}}
.data-table td {{ padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
.data-table tr:hover {{ background: rgba(255,255,255,0.02); }}
.data-table .code {{ color: #74b9ff; font-weight: bold; }}

/* 事件驱动 */
.event-item {{
    background: rgba(255,255,255,0.03); border-radius: 10px; padding: 16px;
    margin-bottom: 10px; border-left: 3px solid #ffa502;
}}
.event-rank {{
    display: inline-block; background: #ffa502; color: #1a1a2e;
    padding: 2px 10px; border-radius: 12px; font-size: 12px;
    font-weight: bold; margin-right: 8px;
}}
.event-title {{ color: #fff; font-size: 14px; margin: 6px 0; }}
.event-desc {{ color: #888; font-size: 13px; line-height: 1.6; }}
.event-stocks {{ color: #74b9ff; font-size: 12px; margin-top: 6px; }}
.impact-summary {{ color: #dfe6e9; font-size: 13px; margin-top: 8px; padding: 8px 12px;
    background: rgba(255,255,255,0.05); border-radius: 6px; }}
.impact-tags {{ margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
.impact-tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
.impact-tag.positive {{ background: rgba(0,184,148,0.2); color: #00b894; border: 1px solid rgba(0,184,148,0.3); }}
.impact-tag.negative {{ background: rgba(255,71,87,0.2); color: #ff4757; border: 1px solid rgba(255,71,87,0.3); }}
.impact-label {{ font-size: 12px; color: #888; margin-right: 4px; }}
.impact-stocks {{ margin-top: 4px; font-size: 12px; }}
.impact-stock-item {{ display: inline-block; margin-right: 12px; margin-bottom: 4px; }}
.impact-stock-item .s-name {{ color: #74b9ff; font-weight: bold; }}
.impact-stock-item .s-code {{ color: #636e72; margin-left: 4px; }}
.impact-stock-item .s-reason {{ color: #888; margin-left: 4px; }}

/* 时局推演 */
.forecast-box {{
    background: linear-gradient(135deg, rgba(9,132,227,0.1) 0%, rgba(9,132,227,0.03) 100%);
    border-radius: 12px; padding: 20px; border-left: 4px solid #0984e3;
}}
.forecast-text {{ color: #e0e0e0; font-size: 14px; line-height: 1.8; }}
.forecast-label {{ font-weight: bold; color: #ddd; margin-top: 12px; display: block; }}

/* 涨停板 */
.limit-up-list {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px; margin-bottom: 20px;
}}
.limit-up-item {{
    background: rgba(255,71,87,0.1); border-radius: 8px; padding: 12px;
    text-align: center; border: 1px solid rgba(255,71,87,0.2);
}}
.limit-up-item .stock-name {{ color: #ff4757; font-weight: bold; font-size: 14px; }}
.limit-up-item .stock-code {{ color: #888; font-size: 11px; margin-top: 3px; }}

/* 风险提示 */
.risk-box {{
    background: linear-gradient(135deg, rgba(255,71,87,0.1) 0%, rgba(255,71,87,0.03) 100%);
    border-radius: 12px; padding: 20px; border: 1px solid rgba(255,71,87,0.2);
    margin-top: 16px;
}}
.risk-list {{ list-style: none; color: #e0e0e0; font-size: 13px; }}
.risk-list li {{ padding: 4px 0; padding-left: 20px; position: relative; line-height: 1.6; }}
.risk-list li::before {{ content: "!"; position: absolute; left: 0; color: #ff4757; font-weight: bold; }}

/* 信号摘要 */
.signal-summary {{
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;
    padding: 14px 18px; background: rgba(255,255,255,0.03); border-radius: 10px;
}}
.signal-summary-item {{
    display: flex; flex-direction: column; align-items: center;
    padding: 6px 14px; border-right: 1px solid rgba(255,255,255,0.08);
}}
.signal-summary-item:last-child {{ border-right: none; }}
.signal-summary-item .ss-count {{ font-size: 22px; font-weight: bold; color: #fff; }}
.signal-summary-item .ss-label {{ font-size: 11px; color: #888; margin-top: 2px; }}

.version-diff {{
    padding: 12px 18px; margin-bottom: 16px; border-radius: 8px;
    font-size: 13px; line-height: 1.6;
}}
.version-diff.identical {{ background: rgba(46,213,115,0.08); border: 1px solid rgba(46,213,115,0.2); color: #5effa0; }}
.version-diff.different {{ background: rgba(255,165,0,0.08); border: 1px solid rgba(255,165,0,0.2); color: #ffb347; }}

.detail-group {{
    margin-bottom: 10px; padding: 10px 14px;
    background: rgba(255,255,255,0.02); border-radius: 8px;
}}
.detail-group-title {{
    font-size: 12px; color: #74b9ff; font-weight: bold; margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: 1px;
}}

/* ── Industrial refresh ── */
body {{
    font-family: "SFMono-Regular", "SF Mono", "Menlo", "Monaco", Consolas, "Liberation Mono", monospace;
    background:
        radial-gradient(circle at top left, rgba(0, 230, 118, 0.08), transparent 26%),
        radial-gradient(circle at top right, rgba(255, 183, 3, 0.08), transparent 22%),
        linear-gradient(180deg, #080b10 0%, #0b0f14 100%);
    color: #e5edf5;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    font-variant-numeric: tabular-nums;
}}

.container {{
    max-width: 1360px;
}}

.header,
.section,
.version-toggle,
.summary-card,
.index-card,
.event-item,
.forecast-box,
.risk-box,
.limit-up-item,
.detail-group,
.version-diff,
.signal-summary {{
    border: 1px solid #202833;
    background: #0f141b;
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.28);
}}

.header {{
    position: relative;
    overflow: hidden;
    border-radius: 20px;
    padding: 24px 24px 22px;
    margin-bottom: 18px;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 42%),
        #0f141b;
}}

.header h1 {{
    color: #f8fbff;
    font-size: 30px;
    letter-spacing: 0.02em;
    margin-bottom: 6px;
}}

.header .subtitle {{
    color: #90a0b5;
    font-size: 12px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}}

.market-summary {{
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
}}

.summary-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 14px;
    margin-bottom: 16px;
}}

.summary-card {{
    position: relative;
    overflow: hidden;
    min-height: 118px;
    padding: 16px 18px 18px;
    border-radius: 18px;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent 68%),
        #11161d;
    border: 1px solid #202833;
}}

.summary-card::after {{
    content: "";
    position: absolute;
    inset: auto 16px 0 16px;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.14), transparent);
}}

.summary-card.primary {{
    background:
        linear-gradient(135deg, rgba(116, 185, 255, 0.12), rgba(255, 255, 255, 0.03) 65%),
        #11161d;
}}

.summary-card.accent {{
    background:
        linear-gradient(135deg, rgba(0, 230, 118, 0.12), rgba(255, 255, 255, 0.03) 65%),
        #11161d;
}}

.summary-card.warn {{
    background:
        linear-gradient(135deg, rgba(255, 183, 3, 0.12), rgba(255, 255, 255, 0.03) 65%),
        #11161d;
}}

.summary-card.risk {{
    background:
        linear-gradient(135deg, rgba(255, 71, 87, 0.14), rgba(255, 255, 255, 0.03) 65%),
        #11161d;
}}

.summary-kicker {{
    display: flex;
    align-items: center;
    gap: 8px;
    color: #9cabbd;
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-bottom: 10px;
}}

.summary-value {{
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    line-height: 1.1;
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
}}

.summary-note {{
    margin-top: 10px;
    color: #90a0b5;
    font-size: 12px;
    line-height: 1.6;
}}

.summary-note strong {{
    color: #f8fbff;
}}

.num-condensed {{
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
}}

.table-shell {{
    border: 1px solid #202833;
    border-radius: 18px;
    overflow: hidden;
    background: #0d1218;
}}

.table-meta {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid #202833;
    background: #11161d;
    color: #90a0b5;
    font-size: 12px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}}

.table-note {{
    color: #6f8095;
    font-size: 11px;
    letter-spacing: normal;
    text-transform: none;
}}

.primary-cell {{
    color: #f8fbff;
    font-weight: 700;
}}

.secondary-cell {{
    margin-top: 3px;
    color: #90a0b5;
    font-size: 11px;
    line-height: 1.4;
}}

.metric-stack {{
    display: flex;
    flex-direction: column;
    gap: 2px;
}}

.metric-main {{
    color: #f8fbff;
    font-weight: 700;
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
}}

.metric-sub {{
    color: #90a0b5;
    font-size: 11px;
}}

.decision-chip {{
    display: inline-flex;
    align-items: center;
    min-width: 52px;
    justify-content: center;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid #202833;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}

.decision-chip.pass {{
    color: #6cf0a9;
    border-color: rgba(0, 230, 118, 0.28);
    background: rgba(0, 230, 118, 0.08);
}}

.decision-chip.block {{
    color: #ff7b8a;
    border-color: rgba(255, 71, 87, 0.28);
    background: rgba(255, 71, 87, 0.08);
}}

.stop-loss-value {{
    color: #f8fbff;
    font-weight: 700;
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
}}

.outflow-flow {{
    color: #6cf0a9;
    font-weight: 700;
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
}}

.event-stack {{
    display: grid;
    gap: 12px;
}}

.event-item {{
    display: grid;
    gap: 10px;
}}

.event-head {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
}}

.event-titleline {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
}}

.event-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-end;
}}

.event-pill {{
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 999px;
    border: 1px solid #202833;
    background: rgba(255, 255, 255, 0.03);
    color: #b7c4d4;
    font-size: 11px;
    font-weight: 700;
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.03em;
}}

.event-pill.score {{
    border-color: rgba(255, 183, 3, 0.25);
}}

.event-pill.trade-strong {{
    border-color: rgba(255, 71, 87, 0.28);
    color: #ff9aa5;
}}

.event-pill.trade-mid {{
    border-color: rgba(255, 183, 3, 0.28);
    color: #ffcb66;
}}

.event-pill.trade-weak {{
    color: #9cabbd;
}}

.event-headline {{
    color: #dde6ef;
    font-size: 14px;
    line-height: 1.6;
}}

.event-analysis {{
    display: grid;
    gap: 4px;
    color: #a9b6c6;
    font-size: 13px;
    line-height: 1.6;
    padding-left: 10px;
}}

.event-analysis-row {{
    position: relative;
    padding-left: 10px;
}}

.event-analysis-row::before {{
    content: "";
    position: absolute;
    left: 0;
    top: 10px;
    width: 4px;
    height: 4px;
    border-radius: 999px;
    background: #00e676;
}}

.event-body {{
    display: grid;
    gap: 8px;
}}

.event-tags-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
}}

.raw-toggle {{
    display: inline-flex;
    align-items: center;
    color: #74b9ff;
    font-size: 12px;
    cursor: pointer;
}}

.raw-panel {{
    display: none;
    color: #90a0b5;
    font-size: 12px;
    line-height: 1.6;
    margin-top: 6px;
    padding: 10px 12px;
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    border: 1px solid #202833;
}}

.module-list {{
    display: grid;
    gap: 14px;
}}

.limit-sector {{
    border: 1px solid #202833;
    border-radius: 16px;
    padding: 14px;
    background: #11161d;
}}

.limit-sector-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
}}

.limit-sector-title {{
    color: #f8fbff;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.06em;
}}

.limit-sector-count {{
    color: #ffcb66;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}

.index-card {{
    position: relative;
    min-height: 98px;
    padding: 14px 16px 16px;
    border-radius: 16px;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent 58%),
        #11161d;
}}

.index-card::before {{
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    border-radius: 16px 0 0 16px;
    background: linear-gradient(180deg, #00e676, #74b9ff);
}}

.index-card .name {{
    color: #9cabbd;
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-bottom: 8px;
}}

.index-card .value {{
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "DIN Condensed", "Helvetica Neue Condensed", "Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Nimbus Sans Narrow", sans-serif;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
}}

.index-card .change {{
    margin-top: 6px;
    font-size: 13px;
    font-weight: 600;
}}

.section {{
    border-radius: 20px;
    padding: 22px;
    margin-bottom: 18px;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 38%),
        #0f141b;
}}

.section-title {{
    display: flex;
    align-items: center;
    gap: 10px;
    color: #f8fbff;
    font-size: 14px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding-left: 12px;
    border-left: 3px solid #00e676;
}}

.version-toggle {{
    padding: 6px;
    border-radius: 16px;
    background: #0f141b;
    border-color: #202833;
}}

.version-btn {{
    border-radius: 12px;
    border-color: transparent;
    color: #8ea0b5;
    font-weight: 700;
    letter-spacing: 0.03em;
    background: transparent;
}}

.version-btn.active {{
    background: linear-gradient(135deg, rgba(0, 230, 118, 0.18), rgba(116, 185, 255, 0.08));
    border-color: rgba(0, 230, 118, 0.45);
    color: #f8fbff;
}}

.version-btn .badge {{
    background: rgba(255, 255, 255, 0.08);
    color: #cbd5e1;
}}

.chan-table th,
.data-table th {{
    background: #11161d;
    color: #94a3b8;
    border-bottom: 1px solid #202833;
}}

.chan-table td,
.data-table td {{
    border-bottom: 1px solid #1d2430;
}}

.chan-table tr:hover,
.data-table tr:hover {{
    background: rgba(255, 255, 255, 0.03);
}}

.buy-tag.b1 {{
    background: rgba(255, 71, 87, 0.18);
    color: #ff7b8a;
}}

.buy-tag.b2 {{
    background: rgba(255, 183, 3, 0.18);
    color: #ffcb66;
}}

.buy-tag.b3 {{
    background: rgba(0, 230, 118, 0.18);
    color: #6cf0a9;
}}

.buy-tag.b2l {{
    background: rgba(116, 185, 255, 0.18);
    color: #9fd0ff;
}}

.buy-tag.candidate {{
    border: 1px dashed rgba(255, 183, 3, 0.45);
    background: rgba(255, 183, 3, 0.08);
    color: #ffcb66;
}}

.sell-tag {{
    background: rgba(0, 230, 118, 0.16);
    color: #6cf0a9;
}}

.score-bar {{
    background: linear-gradient(90deg, #ff4757 0%, #ffb703 52%, #00e676 100%);
}}

.pivot-cell,
.detail-section,
.impact-label,
.event-desc,
.forecast-text,
.risk-list,
.signal-summary-item .ss-label,
.impact-stock-item .s-reason,
.impact-stock-item .s-code,
.limit-up-item .stock-code {{
    color: #94a3b8;
}}

.sector-tag {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid #202833;
}}

.sector-tag .sname,
.event-title,
.signal-summary-item .ss-count,
.limit-up-item .stock-name {{
    color: #f8fbff;
}}

.history-tab {{
    border-color: #202833;
    color: #90a0b5;
    background: #11161d;
}}

.history-tab.active {{
    border-color: rgba(0, 230, 118, 0.45);
    background: rgba(0, 230, 118, 0.12);
    color: #f8fbff;
}}

.event-item {{
    border-left: 3px solid #00e676;
    border-radius: 16px;
    padding: 16px 16px 14px;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.025), transparent 48%),
        #11161d;
}}

.event-rank {{
    background: #00e676;
    color: #081018;
}}

.impact-summary {{
    color: #dde6ef;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid #202833;
}}

.impact-tag.positive {{
    background: rgba(0, 230, 118, 0.14);
    color: #6cf0a9;
    border-color: rgba(0, 230, 118, 0.3);
}}

.impact-tag.negative {{
    background: rgba(255, 71, 87, 0.14);
    color: #ff7b8a;
    border-color: rgba(255, 71, 87, 0.3);
}}

.forecast-box {{
    border-radius: 18px;
    padding: 20px;
    border-left: 3px solid #74b9ff;
}}

.risk-box {{
    border-radius: 18px;
    padding: 20px;
    border-color: rgba(255, 71, 87, 0.22);
    background:
        linear-gradient(180deg, rgba(255, 71, 87, 0.08), transparent 52%),
        #11161d;
}}

.signal-summary {{
    border-radius: 18px;
    padding: 16px 18px;
    background: #11161d;
    gap: 10px;
}}

.signal-summary-item {{
    min-width: 120px;
    padding: 4px 12px 4px 0;
    border-right: 1px solid #202833;
}}

.signal-summary-item:last-child {{
    border-right: none;
}}

.version-diff.identical {{
    background: rgba(0, 230, 118, 0.08);
    border-color: rgba(0, 230, 118, 0.24);
    color: #78f0ad;
}}

.version-diff.different {{
    background: rgba(255, 183, 3, 0.08);
    border-color: rgba(255, 183, 3, 0.24);
    color: #ffcb66;
}}

.detail-group {{
    border-radius: 14px;
    padding: 12px 14px;
    background: #11161d;
}}

.detail-group-title {{
    color: #74b9ff;
    letter-spacing: 0.14em;
}}

.footer {{
    color: #718096;
    font-size: 12px;
}}

.summary-strip {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 16px;
}}

.summary-meter {{
    border: 1px solid #202833;
    border-radius: 18px;
    padding: 14px 16px;
    background: #11161d;
    min-height: 108px;
}}

.summary-meter .summary-kicker {{
    margin-bottom: 8px;
}}

.summary-meter .summary-value {{
    font-size: 28px;
}}

.summary-meter .summary-note {{
    margin-top: 8px;
}}

.table-control {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 12px;
    margin: 4px 0 12px;
    padding: 12px 14px;
    border: 1px solid #202833;
    border-radius: 16px;
    background: #11161d;
}}

.table-control-left {{
    display: flex;
    flex-direction: column;
    gap: 6px;
}}

.table-control-title {{
    color: #f8fbff;
    font-size: 14px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 700;
}}

.table-control-sub {{
    color: #90a0b5;
    font-size: 12px;
    line-height: 1.5;
}}

.table-control-right {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
}}

.filter-chip {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 12px;
    border: 1px solid #202833;
    border-radius: 999px;
    background: #0f141b;
    color: #9cabbd;
    font-size: 12px;
    white-space: nowrap;
}}

.filter-chip strong {{
    color: #f8fbff;
    font-variant-numeric: tabular-nums;
}}

.table-shell {{
    overflow-x: auto;
}}

.chan-table {{
    min-width: 1120px;
}}

.pick-collapse {{
    margin-top: 12px;
    display: flex;
    justify-content: center;
}}

.pick-collapse-btn {{
    border: 1px solid #202833;
    background: #11161d;
    color: #f8fbff;
    border-radius: 999px;
    padding: 8px 14px;
    font-size: 12px;
    cursor: pointer;
}}

.pick-collapse-btn:hover {{
    border-color: #00e676;
}}

.pick-row-hidden {{
    display: none;
}}

.pick-cards {{
    display: none;
    gap: 10px;
}}

.pick-card {{
    border: 1px solid #202833;
    border-radius: 14px;
    background: #11161d;
    padding: 12px 12px 10px;
    cursor: pointer;
}}

.pick-card-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 10px;
}}

.pick-card-title {{
    color: #f8fbff;
    font-weight: 700;
    font-size: 14px;
}}

.pick-card-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px 10px;
}}

.pick-row-label {{
    color: #90a0b5;
    font-size: 11px;
}}

.pick-row-value {{
    color: #f8fbff;
    font-size: 12px;
    line-height: 1.45;
    word-break: break-word;
}}

.pick-card-detail {{
    display: none;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #202833;
}}

.pick-card.open .pick-card-detail {{
    display: block;
}}

.pick-card-detail .detail-section {{
    margin-top: 0;
}}

@media (max-width: 980px) {{
    .summary-strip {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .table-control {{
        flex-direction: column;
        align-items: stretch;
    }}
    .table-control-right {{
        justify-content: flex-start;
    }}
}}

@media (max-width: 720px) {{
    body {{
        padding: 12px;
    }}
    .container {{
        max-width: 100%;
    }}
    .summary-strip {{
        grid-template-columns: 1fr;
    }}
    .market-summary {{
        grid-template-columns: 1fr 1fr;
    }}
    .version-toggle {{
        flex-direction: column;
    }}
    .version-btn:first-child,
    .version-btn:last-child {{
        border-radius: 12px;
    }}
    .table-control-right {{
        gap: 6px;
    }}
    .filter-chip {{
        padding: 6px 10px;
    }}
    #pickTable {{
        display: none;
    }}
    .pick-cards {{
        display: grid;
    }}
    .chan-table {{
        min-width: 0;
        width: 100%;
    }}
    .chan-table thead {{
        display: none;
    }}
    .chan-table tbody,
    .chan-table tr,
    .chan-table td {{
        display: block;
        width: 100%;
    }}
    .chan-table tr.expandable {{
        margin-bottom: 10px;
        border: 1px solid #202833;
        border-radius: 14px;
        overflow: hidden;
        background: #11161d;
    }}
    .chan-table td {{
        border-bottom: 1px solid #1d2430;
        padding: 8px 10px;
    }}
    .chan-table td:last-child {{
        border-bottom: 0;
    }}
    .chart-row.open {{
        display: block;
    }}
    .chart-row.open td {{
        display: block;
        width: 100%;
    }}
    .chart-container {{
        height: 300px;
    }}
}}

::-webkit-scrollbar {{
    width: 10px;
    height: 10px;
}}

::-webkit-scrollbar-track {{
    background: #090b0f;
}}

::-webkit-scrollbar-thumb {{
    background: #202833;
    border-radius: 999px;
}}

::-webkit-scrollbar-thumb:hover {{
    background: #2b3542;
}}
</style>
</head>
<body>
<div class="container">

<!-- 头部 -->
<div class="header">
    <h1>缠论选股日报</h1>
    <div class="subtitle">{date_str} · 盘中 14:35 运行 · 基于缠中说禅108课理论</div>
    <div class="market-summary" id="marketCards"></div>
</div>

<!-- 版本切换 -->
<div class="version-toggle">
    <button class="version-btn" id="btnPure" onclick="switchVersion('pure')">
        缠论纯净版 <span class="badge">理论基准</span>
    </button>
    <button class="version-btn active" id="btnFusion" onclick="switchVersion('fusion')">
        融合版 <span class="badge">实战推荐</span>
    </button>
</div>

<!-- 大盘缠论结构 -->
<div class="section">
    <div class="section-title">上证指数 · 缠论结构分析</div>
    <div id="marketStructure"></div>
</div>

<!-- 选股结果 -->
<div class="section">
    <div class="section-title">缠论选股结果 <span style="font-size:13px;color:#888;" id="pickCount"></span></div>
    <div id="selectionSummaryCards"></div>
    <div id="signalSummary"></div>
    <div id="versionDiff"></div>
    <div id="startupWatchSection">
        <div class="section-title">启动观察 <span style="font-size:13px;color:#ffa502;" id="startupWatchCount"></span></div>
        <div id="startupWatchContent"></div>
    </div>
    <div class="table-control">
        <div class="table-control-left">
            <div class="table-control-title">选股主表</div>
            <div class="table-control-sub">默认保留可执行字段，展开后再看完整原因、结构和图表。</div>
        </div>
        <div class="table-control-right" id="tableControls"></div>
    </div>
    <div id="pickTable"></div>
    <div id="pickCards"></div>
</div>

<!-- 板块资金 -->
<div class="section">
    <div class="section-title">板块资金流向 TOP10</div>
    <div class="sector-tags" id="sectorFlow"></div>
</div>

<!-- 资金流出 -->
<div class="section" id="outflowSection">
    <div class="section-title">资金流出 TOP5</div>
    <div id="sectorOutflow"></div>
</div>

<!-- 事件驱动 -->
<div class="section" id="eventsSection">
    <div class="section-title">A股影响力事件 Top10</div>
    <div style="color:#888;font-size:12px;margin:-4px 0 12px 0;">按事件重要性、主题映射、资金流、涨停验证综合排序；不是最新新闻列表。</div>
    <div id="eventsList"></div>
</div>

<!-- 时局推演 -->
<div class="section" id="forecastSection">
    <div class="section-title">时局推演</div>
    <div id="forecastContent"></div>
</div>

<!-- 涨停板 -->
<div class="section" id="limitUpSection">
    <div class="section-title">今日涨停板</div>
    <div id="limitUpContent"></div>
</div>

<!-- 卖出信号 -->
<div class="section" id="sellSection">
    <div class="section-title">卖出信号（一卖 / 顶背驰风险提示） <span style="font-size:13px;color:#888;" id="sellCount"></span></div>
    <div id="sellTable"></div>
</div>

<!-- 历史回顾 -->
<div class="section" id="historySection" style="display:none;">
    <div class="section-title">历史回顾</div>
    <div class="history-tabs" id="historyTabs"></div>
    <div id="historyContent"></div>
</div>

<!-- 风险提示 -->
<div class="footer">
    风险提示：本报告基于缠论技术分析自动生成，仅供学习参考，不构成投资建议。<br>
    股市有风险，投资需谨慎。历史信号不代表未来收益。
</div>

</div>

<script>
// ========== 弱保护访问控制（hash 校验，非安全鉴权） ==========
var ACCESS_CONTROL_ENABLED = {str(ENABLE_WEAK_ACCESS_CONTROL).lower()};
var ACCESS_PUBLIC_DATES = {json.dumps(PUBLIC_DATES)};
var ACCESS_KEY_SALT = "{FULL_ACCESS_KEY_SALT}";
var ACCESS_KEY_HASH = "{access_key_hash}";
var GRANTED = false;

async function sha256Hex(text) {{
    var encoder = new TextEncoder();
    var data = encoder.encode(text);
    var hashBuffer = await crypto.subtle.digest('SHA-256', data);
    var hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(function(b) {{ return b.toString(16).padStart(2, '0'); }}).join('');
}}

async function resolveGranted() {{
    if (!ACCESS_CONTROL_ENABLED) return true;
    var params = new URLSearchParams(window.location.search);
    var key = params.get('key') || '';
    if (!key) return false;
    try {{
        var hash = await sha256Hex(key + ACCESS_KEY_SALT);
        return hash === ACCESS_KEY_HASH;
    }} catch(e) {{
        return false;
    }}
}}

function getAllowedDates(allDates, granted, publicDates) {{
    if (granted) return allDates.slice();
    return allDates.filter(function(d) {{ return publicDates.indexOf(d) !== -1; }});
}}

function resolveInitialDate(pageDate, allowedDates) {{
    if (allowedDates.indexOf(pageDate) !== -1) return pageDate;
    if (allowedDates.length > 0) return allowedDates[0];
    return null;
}}

function filterHistoryData(historyData, allowedDates) {{
    var filtered = {{ dates: [], reports: {{}} }};
    (historyData.dates || []).forEach(function(d) {{
        if (allowedDates.indexOf(d) !== -1) {{
            filtered.dates.push(d);
            if (historyData.reports && historyData.reports[d]) {{
                filtered.reports[d] = historyData.reports[d];
            }}
        }}
    }});
    return filtered;
}}

// ========== 数据加载 ==========
var PAGE_DATE = "{date_str}";
var REPORT_DATA = null;
var CURRENT_VERSION = 'fusion';
var HISTORY_DATA = {{}};
var PICK_TABLE_COLLAPSED = true;
var PICK_TABLE_LIMIT = 20;
var INLINE_REPORT_DATA = {bootstrap_data_json};

async function init() {{
    // 全局 resize：遍历所有已渲染图表
    window.addEventListener('resize', function() {{
        var charts = window._charts || {{}};
        Object.keys(charts).forEach(function(k) {{
            try {{ charts[k].resize(); }} catch(e) {{}}
        }});
    }});

    GRANTED = await resolveGranted();

    if (window.location.protocol === 'file:') {{
        REPORT_DATA = INLINE_REPORT_DATA;
        HISTORY_DATA = {{
            dates: [PAGE_DATE],
            reports: (function() {{
                var day = INLINE_REPORT_DATA;
                var reports = {{}};
                reports[PAGE_DATE] = {{
                    market: day.market || {{}},
                    chanlun_structure: day.chanlun_structure || {{}},
                    picks_pure: day.picks_pure || [],
                    picks_fusion: day.picks_fusion || [],
                    sector_flow: day.sector_flow || [],
                    sector_outflow: day.sector_outflow || [],
                    limit_up_pool: day.limit_up_pool || [],
                    events: day.events || [],
                    forecast: day.forecast || {{}},
                    sell_signals: day.sell_signals || [],
                    diagnostics: day.diagnostics || {{}},
                    startup_watchlist: day.startup_watchlist || [],
                }};
                return reports;
            }})()
        }};
        renderAll();
        renderHistoryTabs();
        return;
    }}

    try {{
        // 加载 data.json 获取所有可用日期
        var manifestResp = await fetch('data.json');
        if (!manifestResp.ok) throw new Error('Failed to load data.json');
        var manifest = await manifestResp.json();
        var allDates = manifest.dates || [];
        var allowedDates = getAllowedDates(allDates, GRANTED, ACCESS_PUBLIC_DATES);
        var resolvedDate = resolveInitialDate(PAGE_DATE, allowedDates);

        if (!resolvedDate) {{
            renderNoPublicData();
            return;
        }}

        // 加载实际日期的数据
        var dataResp = await fetch('data/' + resolvedDate + '.json');
        if (!dataResp.ok) throw new Error('Failed to load data for ' + resolvedDate);
        REPORT_DATA = await dataResp.json();
        REPORT_DATA.date = resolvedDate;

        // 过滤历史数据
        HISTORY_DATA = filterHistoryData(manifest, allowedDates);

        renderAll();
        renderHistoryTabs();

        // 静默限制：未授权用户仅看到 PUBLIC_DATES 中的日期，无提示
    }} catch(e) {{
        console.error(e);
        // 最终 fallback：尝试直接加载 PAGE_DATE
        try {{
            var dataResp = await fetch('data/' + PAGE_DATE + '.json');
            if (dataResp.ok) {{
                REPORT_DATA = await dataResp.json();
                renderAll();
            }}
        }} catch(e2) {{
            console.error(e2);
        }}
    }}
}}

function escapeHtml(value) {{
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}}

function renderAll() {{
    renderMarketCards();
    renderMarketStructure();
    renderSelectionSummaryCards();
    renderSectorFlow();
    renderSectorOutflow();
    renderEvents();
    renderForecast();
    renderSellSignals();
    renderLimitUp();
    renderStartupWatchlist();
    switchVersion('fusion');
}}

// ========== 版本切换 ==========
function switchVersion(ver) {{
    CURRENT_VERSION = ver;
    document.getElementById('btnPure').classList.toggle('active', ver === 'pure');
    document.getElementById('btnFusion').classList.toggle('active', ver === 'fusion');
    document.getElementById('pickCount').textContent =
        '(' + (REPORT_DATA['picks_' + ver] || []).length + ' 只)';
    renderPickTable(ver);
    window.location.hash = ver;
}}

// ========== 市场指数卡片 ==========
function renderMarketCards() {{
    var m = REPORT_DATA.market || {{}};
    var html = '';
    for (var key in m) {{
        var idx = m[key] || {{}};
        var pct = idx.change_pct || 0;
        var cls = pct >= 0 ? 'up' : 'down';
        var sign = pct >= 0 ? '+' : '';
        var closeNum = Number(idx.close);
        var closeText = Number.isFinite(closeNum) ? closeNum.toLocaleString() : '-';
        html += '<div class="index-card">' +
            '<div class="name">' + escapeHtml(key) + '</div>' +
            '<div class="value">' + closeText + '</div>' +
            '<div class="change ' + cls + '">' + sign + pct.toFixed(2) + '%</div>' +
            '</div>';
    }}
    document.getElementById('marketCards').innerHTML = html;
}}

// ========== 大盘缠论结构 ==========
function renderMarketStructure() {{
    var cs = REPORT_DATA.chanlun_structure || {{}};
    var html = '';
    if (cs.daily_pivot) {{
        html += '<div class="detail-section">' +
            '<strong>日线中枢区间：</strong>' +
            '[' + (cs.daily_pivot.ZD || '-') + ' — ' + (cs.daily_pivot.ZG || '-') + '] ｜ ' +
            '<strong>走势类型：</strong>' + (cs.trend_type || '-') +
            '</div>';
    }}
    if (cs.key_signal) {{
        html += '<div class="detail-section"><strong>关键信号：</strong>' + escapeHtml(cs.key_signal) + '</div>';
    }}
    if (cs.conclusion) {{
        html += '<div class="detail-section"><strong>结论：</strong>' + escapeHtml(cs.conclusion) + '</div>';
    }}
    if (!html) {{
        html = '<div class="detail-section">未能计算上证缠论结构</div>';
    }}
    document.getElementById('marketStructure').innerHTML = html;
}}

// ========== 选股摘要卡片 ==========
function renderSelectionSummaryCards() {{
    var fusionPicks = REPORT_DATA.picks_fusion || [];
    var purePicks = REPORT_DATA.picks_pure || [];
    var diag = REPORT_DATA.diagnostics || {{}};
    var fa = diag.fusion_admission || {{}};

    // Count strong startup candidates
    var startupCount = 0;
    var gradeB = 0, gradeC = 0, pullbackCount = 0;
    fusionPicks.forEach(function(p) {{
        var bp = p.best_buy_point || {{}};
        if (bp.type === '强势启动候选') {{
            startupCount++;
            var dg = bp.daily_startup_grade || '';
            var sg = bp.sublevel_confirm_grade || '';
            if (dg === 'pullback') pullbackCount++;
            if (sg === 'B') gradeB++;
            if (sg === 'C') gradeC++;
        }}
    }});

    var regime = fa.market_regime || 'unknown';
    var regimeText = regime === 'strong' ? '强市' : (regime === 'weak' ? '弱市' : '-');
    var regimeClass = regime === 'strong' ? 'risk' : (regime === 'weak' ? 'accent' : '');
    var regimeTone = regime === 'strong' ? '#ff7b8a' : (regime === 'weak' ? '#74b9ff' : '#9cabbd');

    var html = '<div class="summary-strip">';

    html += '<div class="summary-card summary-meter primary">' +
        '<div class="summary-kicker">今日推荐</div>' +
        '<div class="summary-value"><span style="color:#ffcb66">fusion ' + fusionPicks.length + '</span>' +
        ' <span style="color:#6f8095;font-size:16px;">/</span> ' +
        '<span style="color:#74b9ff">pure ' + purePicks.length + '</span></div>' +
        '<div class="summary-note">当前版本输出的候选总数，反映日内可观察的选股密度。</div>' +
        '</div>';

    html += '<div class="summary-card summary-meter accent">' +
        '<div class="summary-kicker">主信号</div>' +
        '<div class="summary-value">强势启动 <span style="color:#00e676">' + startupCount + '</span> 只</div>' +
        '<div class="summary-note">优先关注具备日线与分时共振的启动型候选。</div>' +
        '</div>';

    html += '<div class="summary-card summary-meter ' + regimeClass + '">' +
        '<div class="summary-kicker">市场状态</div>' +
        '<div class="summary-value">大盘<span style="color:' + regimeTone + '"> ' + escapeHtml(regimeText) + '</span></div>' +
        '<div class="summary-note">' +
            (fa.dropped_by_ma !== undefined ? 'MA过滤 <strong>' + fa.dropped_by_ma + '</strong> 只。' : '暂未识别到明显 MA 过滤压力。') +
        '</div>' +
        '</div>';

    html += '<div class="summary-card summary-meter warn">' +
        '<div class="summary-kicker">风险提示</div>';
    var riskParts = [];
    if (gradeB > 0) riskParts.push('B级确认 <strong style="color:#ffcb66">' + gradeB + '</strong> 只');
    if (gradeC > 0) riskParts.push('C级确认 <strong style="color:#9cabbd">' + gradeC + '</strong> 只');
    if (pullbackCount > 0) riskParts.push('回踩型 <strong style="color:#74b9ff">' + pullbackCount + '</strong> 只');
    html += '<div class="summary-value" style="font-size:18px;">' +
        (riskParts.length ? riskParts.join('，') : '暂无显著风险项') +
        '</div>' +
        '<div class="summary-note">这里不是“坏消息提醒”，而是告诉你哪些候选更容易在盘中失真。</div>' +
        '</div>';

    html += '</div>';
    document.getElementById('selectionSummaryCards').innerHTML = html;
}}

function renderTableControls(picks, ver) {{
    var total = picks.length;
    var startup = 0;
    var divergence = 0;
    var confirmed = 0;
    var passed = 0;
    picks.forEach(function(p) {{
        var bp = p.best_buy_point || {{}};
        var type = bp.type || '';
        if (type === '强势启动候选') startup++;
        if (type.indexOf('背驰') !== -1) divergence++;
        if (bp.confirmed_by) confirmed++;
        if (ver === 'fusion' && p.fusion_admission && p.fusion_admission.passed) passed++;
    }});
    var chips = [
        '<span class="filter-chip">总数 <strong>' + total + '</strong></span>',
        '<span class="filter-chip">强势启动 <strong>' + startup + '</strong></span>',
        '<span class="filter-chip">底背驰 <strong>' + divergence + '</strong></span>',
        '<span class="filter-chip">30min确认 <strong>' + confirmed + '</strong></span>'
    ];
    if (ver === 'fusion') {{
        chips.push('<span class="filter-chip">通过 <strong>' + passed + '</strong></span>');
    }}
    chips.push('<span class="filter-chip">手机 <strong>卡片</strong></span>');
    document.getElementById('tableControls').innerHTML = chips.join('');
}}

function togglePickTable() {{
    PICK_TABLE_COLLAPSED = !PICK_TABLE_COLLAPSED;
    renderPickTable(CURRENT_VERSION);
}}

// ========== 板块资金 ==========
function renderSectorFlow() {{
    var sectors = (REPORT_DATA.sector_flow || []).slice(0, 10);
    var html = '';
    sectors.forEach(function(s, i) {{
        var cls = (s.flow || 0) >= 0 ? 'in' : 'out';
        html += '<div class="sector-tag">' +
            '<span class="rank">#' + (i + 1) + '</span>' +
            '<span class="sname">' + escapeHtml(s.name) + '</span>' +
            '<span class="sflow ' + cls + '">' + (s.flow_str || '') + '</span>' +
            '</div>';
    }});
    document.getElementById('sectorFlow').innerHTML = html || '<div style="color:#888">暂无数据</div>';
}}

// ========== 资金流出 ==========
function renderSectorOutflow() {{
    var items = REPORT_DATA.sector_outflow || [];
    if (!items.length) {{
        document.getElementById('outflowSection').style.display = 'none';
        return;
    }}
    document.getElementById('outflowSection').style.display = '';
    var html = '<div class="table-shell">' +
        '<div class="table-meta"><span>净流出靠前板块</span><span class="table-note">按资金外流强度排序，优先看承压行业</span></div>' +
        '<table class="data-table"><thead><tr>' +
        '<th>排名</th><th>行业板块</th><th>涨跌幅</th><th>资金流向</th></tr></thead><tbody>';
    items.forEach(function(it, i) {{
        var chgCls = (it.change_pct || 0) >= 0 ? 'up' : 'down';
        var sign = (it.change_pct || 0) >= 0 ? '+' : '';
        html += '<tr>' +
            '<td><span class="event-rank">' + (i + 1) + '</span></td>' +
            '<td><div class="primary-cell">' + escapeHtml(it.name) + '</div></td>' +
            '<td class="num-condensed ' + chgCls + '">' + sign + (it.change_pct || 0).toFixed(2) + '%</td>' +
            '<td class="outflow-flow num-condensed">' + escapeHtml(it.flow_str || '-') + '</td>' +
            '</tr>';
    }});
    html += '</tbody></table></div>';
    document.getElementById('sectorOutflow').innerHTML = html;
}}

// ========== A股影响力事件 ==========
function renderEvents() {{
    var events = REPORT_DATA.events || [];
    if (!events.length) {{
        document.getElementById('eventsSection').style.display = '';
        document.getElementById('eventsList').innerHTML =
            '<div style="padding:14px 16px;border:1px solid #202833;border-radius:14px;background:#11161d;color:#90a0b5;font-size:13px;">暂无事件数据</div>';
        return;
    }}
    document.getElementById('eventsSection').style.display = '';
    var html = '<div class="event-stack">';
    events.forEach(function(ev, i) {{
        var stocks = ev.stock_list || [];
        var plates = ev.plate_list || [];
        var tags = [];
        stocks.forEach(function(s) {{ tags.push(s.name || s); }});
        plates.forEach(function(p) {{ tags.push(p.name || p); }});
        var levelColor = ev.level >= 3 ? '#ff4757' : (ev.level >= 2 ? '#ffa502' : '#888');
        var imp = ev.impact || {{}};
        var isFailed = imp.status === 'failed';
        var eventId = 'ev_' + i;

        // 影响力评分
        var impactScore = ev.impact_score;
        var impactLevel = ev.impact_level || '';
        var impactReason = ev.impact_reason || '';
        var matchedSectors = ev.matched_hot_sectors || [];
        var marketValidation = ev.market_validation || '';
        var affectedThemes = ev.affected_themes || [];
        var tradability = ev.tradability || '';

        var levelColorMap = {{'重大': '#ff4757', '较强': '#ffa502', '一般': '#ffd43b', '微弱': '#888'}};
        var levelBgMap = {{'重大': 'rgba(255,71,87,0.2)', '较强': 'rgba(255,165,2,0.2)',
                          '一般': 'rgba(255,212,59,0.15)', '微弱': 'rgba(136,136,136,0.1)'}};
        var lc = levelColorMap[impactLevel] || '#888';
        var lbg = levelBgMap[impactLevel] || 'rgba(136,136,136,0.1)';

        var tradabilityColor = tradability === '强' ? '#ff4757' : (tradability === '中' ? '#ffa502' : '#888');

        var borderColor = lc;

        html += '<div class="event-item" style="border-left-color:' + borderColor + ';">' +
            '<div class="event-head">' +
            '<div class="event-titleline">' +
            '<span class="event-rank">' + (i + 1) + '</span>';

        if (impactScore !== undefined) {{
            html += '<span class="event-pill score" style="background:' + lbg + ';color:' + lc + ';border-color:' + lc + '33;">' +
                impactScore + '分·' + escapeHtml(impactLevel) + '</span>';
        }}

        if (tradability) {{
            var tradeCls = tradability === '强' ? 'trade-strong' : (tradability === '中' ? 'trade-mid' : 'trade-weak');
            html += '<span class="event-pill ' + tradeCls + '" style="color:' + tradabilityColor + ';">可交易性 ' + escapeHtml(tradability) + '</span>';
        }}

        html += '<span class="primary-cell" style="color:' + levelColor + ';">' + escapeHtml(ev.display_title || ev.title || '') + '</span>';

        var catName = ev.event_category_name || '';
        if (catName) {{
            html += '<span class="event-pill">' + escapeHtml(catName) + '</span>';
        }}
        html += '</div><div class="event-meta">';
        if (impactReason) {{
            html += '<span class="table-note">评分逻辑已生成</span>';
        }}
        if (marketValidation) {{
            html += '<span class="table-note">盘面已验证</span>';
        }}
        html += '</div></div><div class="event-body">';

        if (impactReason) {{
            html += '<div class="secondary-cell">评分依据：' + escapeHtml(impactReason) + '</div>';
        }}

        var downgradeReasons = ev.downgrade_reasons || [];
        if (downgradeReasons.length) {{
            html += '<div class="secondary-cell" style="color:#ffcb66;">降权原因：' + downgradeReasons.map(function(r) {{ return escapeHtml(r); }}).join('；') + '</div>';
        }}

        if (matchedSectors && matchedSectors.length) {{
            html += '<div class="event-tags-row">' +
                matchedSectors.map(function(s) {{
                    return '<span class="event-pill score">热点 ' + escapeHtml(s) + '</span>';
                }}).join('') +
                '</div>';
        }}

        if (marketValidation) {{
            var valColor = marketValidation.includes('涨停') ? '#ff4757' : '#888';
            html += '<div class="secondary-cell" style="color:' + valColor + ';">盘面验证：' + escapeHtml(marketValidation) + '</div>';
        }}

        if (imp.headline && !isFailed) {{
            html += '<div class="event-headline">' + escapeHtml(imp.headline) + '</div>';
        }} else if (isFailed) {{
            html += '<div class="secondary-cell">AI分析暂不可用</div>';
        }}

        if (imp.analysis && imp.analysis.length && !isFailed) {{
            html += '<div class="event-analysis">';
            imp.analysis.forEach(function(a) {{
                html += '<div class="event-analysis-row">' + escapeHtml(a) + '</div>';
            }});
            html += '</div>';
        }}

        if (affectedThemes && affectedThemes.length &&
            (!imp.positive_sectors || !imp.positive_sectors.length) &&
            (!imp.negative_sectors || !imp.negative_sectors.length)) {{
            html += '<div class="event-tags-row">';
            html += '<span class="impact-label">主题：</span>';
            affectedThemes.forEach(function(t) {{
                html += '<span class="impact-tag positive">' + escapeHtml(t) + '</span>';
            }});
            html += '</div>';
        }}

        if (imp.positive_sectors && imp.positive_sectors.length || imp.negative_sectors && imp.negative_sectors.length) {{
            html += '<div class="event-tags-row">';
            if (imp.positive_sectors && imp.positive_sectors.length) {{
                html += '<span class="impact-label">利好：</span>';
                imp.positive_sectors.forEach(function(s) {{
                    html += '<span class="impact-tag positive">' + escapeHtml(s) + '</span>';
                }});
            }}
            if (imp.negative_sectors && imp.negative_sectors.length) {{
                html += '<span class="impact-label">利空：</span>';
                imp.negative_sectors.forEach(function(s) {{
                    html += '<span class="impact-tag negative">' + escapeHtml(s) + '</span>';
                }});
            }}
            html += '</div>';
        }}

        if (imp.positive_stocks && imp.positive_stocks.length || imp.negative_stocks && imp.negative_stocks.length) {{
            html += '<div class="impact-stocks">';
            var renderStock = function(st, cls) {{
                return '<span class="impact-stock-item ' + cls + '">' +
                    '<span class="s-name">' + escapeHtml(st.name) + '</span>' +
                    '<span class="s-code">' + escapeHtml(st.code) + '</span>' +
                    (st.reason ? '<span class="s-reason">' + escapeHtml(st.reason) + '</span>' : '') +
                    '</span>';
            }};
            if (imp.positive_stocks && imp.positive_stocks.length) {{
                html += '<span class="impact-label">📈 关注：</span>';
                imp.positive_stocks.forEach(function(s) {{ html += renderStock(s, 'positive'); }});
            }}
            if (imp.negative_stocks && imp.negative_stocks.length) {{
                html += '<span class="impact-label">📉 回避：</span>';
                imp.negative_stocks.forEach(function(s) {{ html += renderStock(s, 'negative'); }});
            }}
            html += '</div>';
        }}

        if (tags.length) {{
            html += '<div class="event-stocks">关联标的 / 板块：' + escapeHtml(tags.join(' / ')) + '</div>';
        }}

        var rawContent = ev.raw_content || ev.content || ev.brief || '';
        if (rawContent && !ev.has_redundant_content) {{
            html += '<div style="margin-top:8px;">' +
                '<a href="javascript:void(0)" onclick="var d=document.getElementById(\\'' + eventId + '\\');' +
                'd.style.display=d.style.display===\\'none\\'?\\'block\\':\\'none\\';' +
                'this.textContent=d.style.display===\\'none\\'?\\'查看原文 ▼\\':\\'收起 ▲\\'"' +
                'class="raw-toggle">查看原文 ▼</a>' +
                '<div id="' + eventId + '" class="raw-panel">' +
                escapeHtml(rawContent) + '</div></div>';
        }}

        html += '</div></div>';
    }});
    html += '</div>';
    document.getElementById('eventsList').innerHTML = html;
}}

// ========== 时局推演 ==========
function renderForecast() {{
    var fc = REPORT_DATA.forecast || {{}};
    if (!fc.core_judgment) {{
        document.getElementById('forecastSection').style.display = 'none';
        return;
    }}
    document.getElementById('forecastSection').style.display = '';
    var html = '<div class="forecast-box"><div class="forecast-text">';
    html += '<p><strong>📌 核心判断：' + escapeHtml(fc.core_judgment) + '</strong></p>';
    if (fc.volume_note) {{
        html += '<p style="color:#888;font-size:13px;">' + escapeHtml(fc.volume_note) + '</p>';
    }}
    if (fc.short_term && fc.short_term.length) {{
        html += '<span class="forecast-label">🔍 短期预判（1周内）：</span>';
        fc.short_term.forEach(function(s) {{
            html += '<p style="margin-left:12px;">' + escapeHtml(s) + '</p>';
        }});
    }}
    if (fc.mid_term) {{
        html += '<span class="forecast-label">🔍 中期预判（2-4周）：</span>';
        html += '<p style="margin-left:12px;">' + escapeHtml(fc.mid_term) + '</p>';
    }}
    if (fc.risks && fc.risks.length) {{
        html += '<div class="risk-box"><strong style="color:#ff4757;">⚠️ 风险提示</strong>';
        html += '<ul class="risk-list">';
        fc.risks.forEach(function(r) {{
            html += '<li>' + escapeHtml(r) + '</li>';
        }});
        html += '</ul></div>';
    }}
    html += '</div></div>';
    document.getElementById('forecastContent').innerHTML = html;
}}

// ========== 卖出信号 ==========
function renderSellSignals() {{
    var signals = REPORT_DATA.sell_signals || [];
    document.getElementById('sellCount').textContent = '(' + signals.length + ' 只)';
    if (!signals.length) {{
        document.getElementById('sellSection').style.display = 'none';
        return;
    }}
    document.getElementById('sellSection').style.display = '';
    var html = '<table class="chan-table"><thead><tr>' +
        '<th>代码</th><th>名称</th><th>卖出信号</th><th>价格</th><th>板块</th><th>走势类型</th><th>理由</th>' +
        '</tr></thead><tbody>';
    signals.forEach(function(s) {{
        var sp = (s.sell_points || [])[0] || {{}};
        html += '<tr>' +
            '<td>' + escapeHtml(s.code) + '</td>' +
            '<td>' + escapeHtml(s.name) + '</td>' +
            '<td><span class="sell-tag">' + escapeHtml(sp.type || '-') + '</span></td>' +
            '<td>' + (sp.price || '-') + '</td>' +
            '<td>' + escapeHtml(s.sector || '-') + '</td>' +
            '<td>' + escapeHtml(s.trend_type || '-') + '</td>' +
            '<td style="font-size:12px;color:#aaa;">' + escapeHtml(sp.reason || '-') + '</td>' +
            '</tr>';
    }});
    html += '</tbody></table>';
    document.getElementById('sellTable').innerHTML = html;
}}

// ========== 涨停板 ==========
function renderLimitUp() {{
    var pool = REPORT_DATA.limit_up_pool || [];
    if (!pool.length) {{
        document.getElementById('limitUpSection').style.display = 'none';
        return;
    }}
    document.getElementById('limitUpSection').style.display = '';
    // 按行业分组
    var groups = {{}};
    pool.forEach(function(it) {{
        var sec = it.sector || '其他';
        if (!groups[sec]) groups[sec] = [];
        groups[sec].push(it);
    }});
    // 按每组数量排序
    var keys = Object.keys(groups).sort(function(a, b) {{
        return groups[b].length - groups[a].length;
    }});
    var html = '<div class="module-list">';
    keys.forEach(function(sec) {{
        var list = groups[sec];
        html += '<div class="limit-sector"><div class="limit-sector-header">' +
            '<div class="limit-sector-title">' + escapeHtml(sec) + '</div>' +
            '<div class="limit-sector-count">' + list.length + ' 只涨停</div>' +
            '</div><div class="limit-up-list">';
        list.forEach(function(it) {{
            html += '<div class="limit-up-item">' +
                '<div class="stock-name">' + escapeHtml(it.name) + '</div>' +
                '<div class="stock-code">' + escapeHtml(it.code) + '</div>' +
                '</div>';
        }});
        html += '</div></div>';
    }});
    html += '</div>';
    document.getElementById('limitUpContent').innerHTML = html;
}}

// ========== 启动观察 ==========
function renderStartupWatchlist() {{
    var watchlist = REPORT_DATA.startup_watchlist || [];
    if (!watchlist.length) {{
        document.getElementById('startupWatchSection').style.display = 'none';
        return;
    }}
    document.getElementById('startupWatchSection').style.display = '';
    document.getElementById('startupWatchCount').textContent = '(' + watchlist.length + ' 只)';

    var html = '<table class="chan-table"><thead><tr>' +
        '<th>代码</th><th>名称</th><th>板块</th><th>信号</th><th>启动形态</th><th>30min确认</th><th>信号年龄</th>' +
        '<th>参考价</th><th>现价</th><th>距参考价</th>' +
        '<th>启动原因</th><th>观察理由</th><th>次日条件</th>' +
        '</tr></thead><tbody>';
    watchlist.forEach(function(w, idx) {{
        var conditions = (w.next_day_conditions || []).join('<br>');
        var ageLabel = w.startup_age_days !== undefined ? w.startup_age_days + '天' : '-';
        var refPrice = w.close || 0;
        var curPrice = w.current_price || 0;
        var distPct = w.distance_from_reference_pct;
        var distStr = distPct !== null && distPct !== undefined ? (distPct >= 0 ? '+' : '') + distPct.toFixed(2) + '%' : '-';
        var distColor = distPct !== null ? (distPct > 0 ? '#ff4757' : '#5effa0') : '#aaa';
        var startupGrade = w.daily_startup_grade || '';
        var startupLabel = w.daily_startup_label || (startupGrade === 'strong' ? '强启动' : (startupGrade === 'weak' ? '弱启动确认' : (startupGrade === 'pullback' ? '回踩型启动观察' : (w.startup_signals && w.startup_signals.length ? '启动观察' : '-'))));
        var confirmLabel = w.sublevel_confirm_label || (w.confirmed_by ? w.confirmed_by : '等待确认');
        html += '<tr class="expandable" onclick="toggleStartupWatchChart(' + idx + ')">' +
            '<td>' + escapeHtml(w.code) + '</td>' +
            '<td>' + escapeHtml(w.name) + '</td>' +
            '<td><div class="secondary-cell" style="margin-top:0;">' + escapeHtml(w.sector || '-') + '</div></td>' +
            '<td><span class="sell-tag">' + escapeHtml(w.type) + '</span></td>' +
            '<td><span class="buy-tag candidate">' + escapeHtml(startupLabel) + '</span></td>' +
            '<td><span class="decision-chip pass">' + escapeHtml(confirmLabel) + '</span></td>' +
            '<td class="num-condensed" style="font-size:12px;">' + ageLabel + '</td>' +
            '<td class="num-condensed">' + (refPrice ? refPrice.toFixed(2) : '-') + '</td>' +
            '<td class="num-condensed">' + (curPrice ? curPrice.toFixed(2) : '-') + '</td>' +
            '<td class="num-condensed" style="color:' + distColor + ';">' + distStr + '</td>' +
            '<td style="color:#ffa502;font-size:13px;">' + escapeHtml(w.startup_reason || '') + '</td>' +
            '<td style="color:#dfe6e9;font-size:13px;">' + escapeHtml(w.watch_reason || '') + '</td>' +
            '<td style="color:#aaa;font-size:12px;">' + escapeHtml(conditions) + '</td>' +
            '</tr>';

        // 展开行：图表 + 详情
        var detail = '';
        detail += '<div class="detail-section"><div class="detail-group"><div class="detail-group-title">启动观察详情</div>';
        if (w.startup_date) detail += '<strong>启动日：</strong>' + escapeHtml(w.startup_date) +
            (w.startup_age_days !== undefined ? ' (' + w.startup_age_days + '天前)' : '') + '<br>';
        detail += '<strong>板块：</strong>' + escapeHtml(w.sector || '-') + '<br>';
        detail += '<strong>启动形态：</strong>' + escapeHtml(startupLabel) + '<br>';
        detail += '<strong>30min确认：</strong>' + escapeHtml(confirmLabel) + '<br>';
        if (w.source_type) detail += '<strong>来源：</strong>' + escapeHtml(w.source_type) + '<br>';
        if (w.change_pct) detail += '<strong>涨幅：</strong>' + w.change_pct + '%<br>';
        if (w.volume_ratio) detail += '<strong>放量倍数：</strong>' + w.volume_ratio.toFixed(2) + '倍<br>';
        if (w.startup_signals && w.startup_signals.length) detail += '<strong>突破类型：</strong>' + escapeHtml(w.startup_signals.join('，')) + '<br>';
        detail += '<strong>完整启动原因：</strong>' + escapeHtml(w.startup_reason || '-') + '<br>';
        detail += '<strong>完整观察理由：</strong>' + escapeHtml(w.watch_reason || '-') + '<br>';
        detail += '<strong>次日确认条件：</strong>' + escapeHtml((w.next_day_conditions || []).join('；') || '-') + '<br>';
        detail += '<strong>参考价：</strong>' + (refPrice ? refPrice.toFixed(2) : '-') +
            ' &nbsp; <strong>现价：</strong>' + (curPrice ? curPrice.toFixed(2) : '-') +
            ' &nbsp; <strong>距参考价：</strong><span style="color:' + distColor + ';">' + distStr + '</span><br>';
        detail += '<strong>信号年龄：</strong>' + ageLabel + ' &nbsp; <strong>时效：</strong>' + escapeHtml(w.recency_reason || '-') + '<br>';
        detail += '</div></div>';

        html += '<tr class="chart-row" id="chartRow_sw_' + idx + '">' +
            '<td colspan="13" style="white-space:normal;line-height:1.6;">' +
            '<div class="chart-container" id="chart_sw_' + idx + '"></div>' +
            detail + '</td></tr>';
    }});
    html += '</tbody></table>';
    document.getElementById('startupWatchContent').innerHTML = html;
}}

// ========== 选股表格 ==========
function renderPickTable(ver) {{
    var picks = REPORT_DATA['picks_' + ver] || [];
    var isFusion = ver === 'fusion';
    var visibleLimit = PICK_TABLE_COLLAPSED ? PICK_TABLE_LIMIT : picks.length;

    renderSignalSummary(picks);
    renderVersionDiffSummary();
    renderTableControls(picks, ver);

    var cardHtml = '<div class="pick-cards">';

    var html = '<div class="table-shell"><div class="table-meta"><span>选股主表</span>' +
        '<span class="table-note">主表只保留筛选决策字段，完整原因与结构状态请展开查看</span></div>' +
        '<table class="chan-table"><thead><tr>' +
        '<th>代码</th><th>名称</th><th>板块</th><th>信号类型</th>' +
        '<th>启动形态</th><th>30min确认</th>' +
        '<th>信号年龄</th><th>距参考价</th>' +
        '<th>评分</th>';
    if (isFusion) {{
        html += '<th>融合版</th><th>止损</th>';
    }}
    html += '</tr></thead><tbody>';

    var colspan = isFusion ? 11 : 9;

    if (picks.length === 0) {{
        var diag = REPORT_DATA.diagnostics || {{}};
        var ds = diag.daily_scan || {{}};
        var up = diag['sublevel_upgrade_' + ver] || {{}};
        var fa = diag.fusion_admission || {{}};
        var sr = diag.signal_recency || {{}};
        var summary = '日线信号 ' + (ds.with_buy_points || 0) + ' 个' +
            '，30min确认通过 ' + (up.candidate_upgraded || 0) + ' 个' +
            '，风险保护剔除 ' + (up.dropped_risk_guard || 0) + ' 个。' +
            '时效过滤: ' + (sr.pure_kept || 0) + '只保留，' + (sr.pure_dropped_expired || 0) + '只过期丢弃。';
        if (isFusion && fa.market_regime) {{
            summary += ' 融合版大盘' + (fa.market_regime === 'strong' ? '强市' : '弱市') +
                '，MA过滤 ' + (fa.dropped_by_ma || 0) + ' 只' +
                '，弱市门槛过滤 ' + (fa.dropped_by_market_regime || 0) + ' 只。';
        }}
        html += '<tr><td colspan="' + colspan + '" style="text-align:center;color:#888;padding:20px;">' +
                '今日暂无符合条件的选股结果</td></tr>' +
                '<tr><td colspan="' + colspan + '" style="text-align:center;color:#666;font-size:12px;padding:8px 20px 20px;">' +
                summary + '</td></tr>';
    }}

    picks.forEach(function(p, idx) {{
        var isHidden = idx >= visibleLimit;
        var bp = p.best_buy_point || {{}};
        var tagClass = {{'一买':'b1','二买':'b2','三买':'b3','类二买':'b2l','强势启动候选':'b3'}}[bp.type] || '';
        if (!tagClass && bp.tier === 'candidate') {{ tagClass = 'candidate'; }}
        if (!tagClass) {{ tagClass = 'candidate'; }}
        var resonance = p.resonance || {{}};
        var score = p.score || 0;
        var barW = Math.max(4, score * 0.6);

        // Signal age
        var ageDays = bp.signal_age_days;
        var ageLabel = ageDays !== null && ageDays !== undefined ? ageDays + '天' : '-';
        var ageColor = ageDays !== null && ageDays >= 8 ? '#ffa502' : (ageDays !== null && ageDays >= 5 ? '#ffb347' : '#aaa');

        // Reference / current price
        var refPrice = bp.reference_price || bp.price || 0;
        var curPrice = bp.current_price;
        if (curPrice === undefined || curPrice === null) {{
            var closes = p.closes || [];
            curPrice = closes.length ? closes[closes.length - 1] : 0;
        }}
        var distPct = bp.distance_from_reference_pct;
        if (distPct === undefined || distPct === null) {{
            distPct = refPrice && curPrice ? ((curPrice - refPrice) / refPrice * 100) : null;
            if (distPct !== null) distPct = Math.round(distPct * 100) / 100;
        }}
        var distStr = distPct !== null && distPct !== undefined ? (distPct >= 0 ? '+' : '') + distPct.toFixed(2) + '%' : '-';
        var distColor = distPct !== null ? (distPct > 0 ? '#ff4757' : (distPct < 0 ? '#5effa0' : '#aaa')) : '#aaa';

        // One-line reason
        var shortReason = bp.startup_reason || bp.reason || '-';
        if (shortReason.length > 40) shortReason = shortReason.substring(0, 40) + '...';

        // Startup form label
        var isStartup = bp.type === '强势启动候选';
        var startupGrade = bp.daily_startup_grade || '';
        var startupLabel = bp.daily_startup_label || (startupGrade === 'strong' ? '强启动' : (startupGrade === 'weak' ? '弱启动确认' : (startupGrade === 'pullback' ? '回踩型启动观察' : '-')));
        var startupColor = startupGrade === 'strong' ? '#ff4757' : (startupGrade === 'weak' ? '#ffa502' : (startupGrade === 'pullback' ? '#74b9ff' : '#888'));
        var startupDisplay = isStartup ? startupLabel : '-';
        var startupStyle = isStartup ? ' style="color:' + startupColor + ';font-weight:bold;font-size:12px;"' : ' style="color:#666;font-size:12px;"';

        // 30min confirm grade
        var confirmGrade = bp.sublevel_confirm_grade || '';
        var confirmLabel = bp.sublevel_confirm_label || '';
        var confirmColor = confirmGrade === 'S' ? '#ff4757' : (confirmGrade === 'A' ? '#ffa502' : (confirmGrade === 'B' ? '#ffd43b' : '#888'));
        var confirmDisplay = isStartup ? (confirmLabel || '-') : '-';
        var confirmStyle = isStartup ? ' style="color:' + confirmColor + ';font-weight:bold;font-size:12px;"' : ' style="color:#666;font-size:12px;"';

        var hiddenClass = isHidden ? ' pick-row-hidden pickTableMore' : '';
        html += '<tr class="expandable pickTableCollapsed' + hiddenClass + '" onclick="toggleChart(' + idx + ', \\'' + ver + '\\')">';
        html += '<td><div class="primary-cell">' + escapeHtml(p.code) + '</div></td>';
        html += '<td><div class="primary-cell">' + escapeHtml(p.name) + '</div>' +
            '<div class="secondary-cell">参考 ' + (refPrice ? refPrice.toFixed(2) : '-') +
            ' · 现价 ' + (curPrice ? curPrice.toFixed(2) : '-') + '</div></td>';
        html += '<td><div class="secondary-cell" style="margin-top:0;">' + escapeHtml(p.sector || '-') + '</div></td>';
        html += '<td><span class="buy-tag ' + tagClass + '">' + escapeHtml(bp.type || '-') + '</span></td>';
        html += '<td' + startupStyle + '>' + escapeHtml(startupDisplay) + '</td>';
        html += '<td' + confirmStyle + '>' + escapeHtml(confirmDisplay) + '</td>';
        html += '<td class="num-condensed" style="color:' + ageColor + ';font-size:12px;">' + ageLabel + '</td>';
        html += '<td><div class="metric-stack"><span class="metric-main" style="color:' + distColor + ';">' + distStr + '</span>' +
            '<span class="metric-sub">' + escapeHtml(shortReason) + '</span></div></td>';
        html += '<td><div class="metric-stack"><span class="num-condensed"><span class="score-bar" style="width:' + barW + 'px;"></span>' + score.toFixed(1) + '</span>' +
            '<span class="metric-sub">' + escapeHtml(resonance.level || '未标注共振') + '</span></div></td>';
        if (isFusion) {{
            var fa = p.fusion_admission || {{}};
            html += '<td>' +
                (fa.passed ? '<span class="decision-chip pass">通过</span>' : '<span class="decision-chip block">过滤</span>') +
                '</td>';
            html += '<td><span class="stop-loss-value num-condensed">' + (p.stop_loss ? p.stop_loss.toFixed(2) : '-') + '</span></td>';
        }}
        html += '</tr>';

        // —— Expand row: full detail ——
        var detail = '';
        detail += '<div class="detail-section">';

        // Basic info
        detail += '<div class="detail-group">' +
            '<div class="detail-group-title">信号详情</div>';
        if (bp.signal_date) detail += '<strong>信号发生日：</strong>' + escapeHtml(bp.signal_date) + '<br>';
        detail += '<strong>距今天数：</strong>' + ageLabel + '<br>';
        detail += '<strong>参考价：</strong>' + (refPrice ? refPrice.toFixed(2) : '-') +
            ' &nbsp; <strong>现价：</strong>' + (curPrice ? curPrice.toFixed(2) : '-') +
            ' &nbsp; <strong>距参考价：</strong><span style="color:' + distColor + ';">' + distStr + '</span><br>';
        detail += '<strong>完整原因：</strong>' + escapeHtml(bp.reason || bp.startup_reason || '-') + '<br>';
        if (bp.confirmed_by) detail += '<strong>30min确认：</strong>' + escapeHtml(bp.confirmed_by) +
            (bp.strength ? ' [' + bp.strength + ']' : '') + '<br>';
        if (bp.confirmations && bp.confirmations.length) detail += '<strong>确认细节：</strong>' + escapeHtml(bp.confirmations.join('，')) + '<br>';
        detail += '</div>';

        // Strong startup specifics
        if (bp.type === '强势启动候选') {{
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">强势启动详情</div>';
            if (bp.startup_date) detail += '<strong>启动日：</strong>' + escapeHtml(bp.startup_date) +
                (bp.startup_age_days !== undefined ? ' (' + bp.startup_age_days + '天前)' : '') + '<br>';
            if (bp.confirm_date) detail += '<strong>确认日：</strong>' + escapeHtml(bp.confirm_date) +
                (bp.confirm_age_days !== undefined ? ' (' + bp.confirm_age_days + '天前)' : '') + '<br>';
            if (bp.volume_ratio) detail += '<strong>放量倍数：</strong>' + bp.volume_ratio.toFixed(1) + '倍<br>';
            if (bp.change_pct) detail += '<strong>涨幅：</strong>' + bp.change_pct.toFixed(1) + '%<br>';
            if (bp.startup_signals && bp.startup_signals.length) detail += '<strong>突破类型：</strong>' + escapeHtml(bp.startup_signals.join('，')) + '<br>';

            // Startup form grade
            detail += '<div style="margin-top:6px;padding:6px 10px;background:rgba(255,255,255,0.03);border-radius:4px;">';
            detail += '<strong>日线启动形态：</strong><span style="color:' + startupColor + ';font-weight:bold;">' + escapeHtml(startupLabel) + '</span>';
            if (bp.daily_startup_warning) detail += '<br><span style="color:#ffa502;font-size:12px;">⚠ ' + escapeHtml(bp.daily_startup_warning) + '</span>';
            detail += '</div>';

            // 30min confirm grade
            detail += '<div style="margin-top:4px;padding:6px 10px;background:rgba(255,255,255,0.03);border-radius:4px;">';
            detail += '<strong>30min确认等级：</strong><span style="color:' + confirmColor + ';font-weight:bold;">' + escapeHtml(confirmLabel) + '</span>';
            if (bp.sublevel_confirm_reason) detail += '<br><span style="color:#aaa;font-size:12px;">' + escapeHtml(bp.sublevel_confirm_reason) + '</span>';
            detail += '</div>';

            if (bp.source_type) detail += '<strong>来源：</strong>' + escapeHtml(bp.source_type) + '<br>';
            detail += '</div>';
        }}

        // 底背驰/低吸 specifics
        if (bp.seed_type || bp.seed_reason) {{
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">原始参考信号</div>';
            if (bp.seed_type) detail += '<strong>种子类型：</strong>' + escapeHtml(bp.seed_type) + '<br>';
            if (bp.seed_reason) detail += '<strong>种子原因：</strong>' + escapeHtml(bp.seed_reason) + '<br>';
            if (bp.source_type) detail += '<strong>参考信号：</strong>' + escapeHtml(bp.source_type) + '<br>';
            detail += '</div>';
        }}

        // Risk / structure
        detail += '<div class="detail-group">' +
            '<div class="detail-group-title">结构状态</div>' +
            '<strong>走势类型：</strong>' + escapeHtml(p.trend_type || '-') + '<br>' +
            '<strong>日线中枢数量：</strong>' + (p.pivots ? (p.pivots.count || 0) : 0) + '<br>' +
            (p.pivot_zg && p.pivot_zd ? '<strong>中枢区间：</strong>[' + p.pivot_zd + ' — ' + p.pivot_zg + ']<br>' : '') +
            '<strong>共振等级：</strong>' + (resonance.level || '-') +
            (resonance.reason ? ' (' + escapeHtml(resonance.reason) + ')' : '') + '<br>' +
            '</div>';

        // Fusion admission detail
        if (isFusion || p.fusion_admission) {{
            var fa = p.fusion_admission || {{}};
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">融合版约束</div>' +
                '<strong>大盘状态：</strong>' + (p.market_regime === 'strong' ? '强市' : (p.market_regime === 'weak' ? '弱市' : (p.market_trend || '-'))) + '<br>' +
                '<strong>MA多头：</strong>' + (p.ma_bullish ? '是 (MA5>MA10>MA20)' : '否') + '<br>' +
                (fa.reason ? '<strong>融合版结果：</strong>' +
                 (fa.passed ? '<span style="color:#5effa0;">保留</span>' : '<span style="color:#ff4757;">过滤</span>') +
                 ' — ' + escapeHtml(fa.reason) + '<br>' : '') +
                (p.stop_loss_pct ? '<strong>止损：</strong>' + p.stop_loss_pct + '%<br>' : '') +
                '</div>';
        }}

        // Risk tips
        if (bp.recency_reason) {{
            var rColor = bp.is_recent ? (bp.signal_age_days >= 8 ? '#ffa502' : '#5effa0') : '#ff4757';
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">风险提示</div>' +
                '<span style="color:' + rColor + ';">' + escapeHtml(bp.recency_reason) + '</span><br>';
            if (bp.signal_age_days >= 8 && bp.is_recent) {{
                detail += '<span style="color:#ffa502;">⚠ 信号接近过期，建议优先关注更新鲜的信号</span><br>';
            }}
            detail += '</div>';
        }}

        detail += '</div>';

        html += '<tr class="chart-row' + hiddenClass + '" id="chartRow_' + ver + '_' + idx + '">' +
                '<td colspan="' + colspan + '" style="white-space:normal;line-height:1.6;">' +
                '<div class="chart-container" id="chart_' + ver + '_' + idx + '"></div>' +
                detail + '</td></tr>';

        if (!isHidden) {{
            cardHtml += '<div class="pick-card" id="pickCard_' + ver + '_' + idx + '" onclick="toggleChart(' + idx + ', \\'' + ver + '\\')">' +
                '<div class="pick-card-head">' +
                '<div><div class="pick-card-title">' + escapeHtml(p.name) + '</div>' +
                '<div class="secondary-cell">' + escapeHtml(p.code) + ' · ' + escapeHtml(p.sector || '-') + ' · 参考 ' + (refPrice ? refPrice.toFixed(2) : '-') + ' · 现价 ' + (curPrice ? curPrice.toFixed(2) : '-') + '</div></div>' +
                '<span class="buy-tag ' + tagClass + '">' + escapeHtml(bp.type || '-') + '</span>' +
                '</div>' +
                '<div class="pick-card-grid">' +
                '<div><div class="pick-row-label">距参考价</div><div class="pick-row-value" style="color:' + distColor + ';">' + distStr + '</div></div>' +
                '<div><div class="pick-row-label">评分</div><div class="pick-row-value">' + score.toFixed(1) + ' · ' + escapeHtml(resonance.level || '未标注') + '</div></div>' +
                '<div><div class="pick-row-label">信号年龄</div><div class="pick-row-value" style="color:' + ageColor + ';">' + ageLabel + '</div></div>' +
                '<div><div class="pick-row-label">30min确认</div><div class="pick-row-value" style="color:' + confirmColor + ';">' + escapeHtml(confirmDisplay) + '</div></div>' +
                '<div style="grid-column:1/-1;"><div class="pick-row-label">原因</div><div class="pick-row-value">' + escapeHtml(shortReason) + '</div></div>' +
                '</div>' +
                '<div class="pick-card-detail" id="pickCardDetail_' + ver + '_' + idx + '" onclick="event.stopPropagation()">' +
                '<div class="chart-container" id="chart_card_' + ver + '_' + idx + '"></div>' +
                detail +
                '</div></div>';
        }}
    }});
    html += '</tbody></table></div>';
    if (picks.length > PICK_TABLE_LIMIT) {{
        var remaining = picks.length - PICK_TABLE_LIMIT;
        var label = PICK_TABLE_COLLAPSED ? ('展开其余 ' + remaining + ' 只') : '收起到前 20 只';
        html += '<div class="pick-collapse"><button id="pickTableToggle" class="pick-collapse-btn" type="button" onclick="togglePickTable()">' + label + '</button></div>';
        cardHtml += '<div class="pick-collapse"><button class="pick-collapse-btn" type="button" onclick="togglePickTable()">' + label + '</button></div>';
    }}
    cardHtml += '</div>';
    document.getElementById('pickTable').innerHTML = html;
    document.getElementById('pickCards').innerHTML = cardHtml;

    window._charts = window._charts || {{}};
}}

// ========== 信号摘要条 ==========
function renderSignalSummary(picks) {{
    var counts = {{}};
    picks.forEach(function(p) {{
        var bp = p.best_buy_point || {{}};
        var t = bp.type || '其他';
        counts[t] = (counts[t] || 0) + 1;
    }});
    var total = picks.length;
    var html = '<div class="signal-summary">';
    html += '<div class="signal-summary-item"><span class="ss-count">' + total + '</span><span class="ss-label">总数</span></div>';
    var order = ['一买','二买','三买','强势启动候选','底背驰候选','二买候选','三买候选','中枢低吸候选','盘整低吸候选'];
    order.forEach(function(t) {{
        if (counts[t]) {{
            html += '<div class="signal-summary-item"><span class="ss-count">' + counts[t] + '</span><span class="ss-label">' + t + '</span></div>';
        }}
    }});
    // Any types not in order
    Object.keys(counts).forEach(function(t) {{
        if (order.indexOf(t) === -1) {{
            html += '<div class="signal-summary-item"><span class="ss-count">' + counts[t] + '</span><span class="ss-label">' + t + '</span></div>';
        }}
    }});
    html += '</div>';
    document.getElementById('signalSummary').innerHTML = html;
}}

// ========== 版本差异说明 ==========
function renderVersionDiffSummary() {{
    var diag = REPORT_DATA.diagnostics || {{}};
    var fa = diag.fusion_admission || {{}};
    var pureCount = (REPORT_DATA.picks_pure || []).length;
    var fusionCount = (REPORT_DATA.picks_fusion || []).length;
    var html = '';
    if (fa.pure_fusion_identical) {{
        html = '<div class="version-diff identical">' +
            '本次 pure / fusion 选股集合相同（' + pureCount + ' 只），差异主要体现在融合版 admission 通过情况与排序。' +
            (fa.identical_reason ? ' (' + fa.identical_reason + ')' : '') +
            '</div>';
    }} else if (fa.input_count !== undefined && fa.output_count !== undefined && fa.input_count !== fa.output_count) {{
        var diff = fa.input_count - fa.output_count;
        html = '<div class="version-diff different">' +
            'fusion 相比 pure 额外过滤 ' + diff + ' 只（' + fa.input_count + ' → ' + fa.output_count + '），' +
            '主要原因：MA不多头 ' + (fa.dropped_by_ma || 0) + ' 只 / ' +
            '弱市门槛 ' + (fa.dropped_by_market_regime || 0) + ' 只 / ' +
            '信号门槛 ' + (fa.dropped_by_signal_gate || 0) + ' 只。' +
            ' 大盘状态：' + (fa.market_regime === 'strong' ? '强市' : '弱市') + '。' +
            '</div>';
    }} else if (pureCount !== fusionCount) {{
        html = '<div class="version-diff different">' +
            'pure 推荐 ' + pureCount + ' 只，fusion 推荐 ' + fusionCount + ' 只。' +
            '</div>';
    }}
    document.getElementById('versionDiff').innerHTML = html;
}}

// ========== 图表展开/收起 ==========
function toggleChart(idx, ver) {{
    var card = document.getElementById('pickCard_' + ver + '_' + idx);
    var cardDetail = document.getElementById('pickCardDetail_' + ver + '_' + idx);
    var table = document.getElementById('pickTable');
    var tableVisible = !!table && window.getComputedStyle(table).display !== 'none';
    if (!tableVisible && card && cardDetail) {{
        var isCardOpen = card.classList.contains('open');
        if (isCardOpen) {{
            card.classList.remove('open');
            return;
        }}
        document.querySelectorAll('.pick-card.open').forEach(function(openCard) {{
            if (openCard !== card) openCard.classList.remove('open');
        }});
        card.classList.add('open');
        setTimeout(function() {{ renderChart(idx, ver, 'chart_card_' + ver + '_' + idx); }}, 100);
        return;
    }}

    var row = document.getElementById('chartRow_' + ver + '_' + idx);
    if (!row) return;
    var isOpen = row.classList.contains('open');
    row.classList.toggle('open');
    if (!isOpen) {{
        setTimeout(function() {{ renderChart(idx, ver); }}, 100);
    }}
}}

// ========== 启动观察图表展开/收起 ==========
function toggleStartupWatchChart(idx) {{
    var row = document.getElementById('chartRow_sw_' + idx);
    if (!row) return;
    var isOpen = row.classList.contains('open');
    row.classList.toggle('open');
    if (!isOpen) {{
        setTimeout(function() {{ renderStartupWatchChart(idx); }}, 100);
    }}
}}

function renderStartupWatchChart(idx) {{
    var domId = 'chart_sw_' + idx;
    var dom = document.getElementById(domId);
    if (!dom || dom.clientWidth === 0) return;

    var watchlist = REPORT_DATA.startup_watchlist || [];
    var item = watchlist[idx];
    if (!item) return;

    // 销毁旧图表
    if (window._charts && window._charts[domId]) {{
        window._charts[domId].dispose();
    }}

    var chart = echarts.init(dom);
    window._charts = window._charts || {{}};
    window._charts[domId] = chart;

    var dates = item.dates || [];
    var closes = item.closes || [];
    var macdHist = item.macd_hist || [];
    var ann = item.chart_annotations || {{}};

    // 启动日标注
    var buyMarks = [];
    if (ann.markPoints && ann.markPoints.length) {{
        ann.markPoints.forEach(function(mp) {{
            buyMarks.push({{
                coord: mp.coord,
                symbol: mp.symbol || 'triangle',
                symbolSize: mp.symbolSize || 20,
                itemStyle: mp.itemStyle || {{ color: '#ffa502' }},
                label: mp.label || {{ show: true }}
            }});
        }});
    }}

    // markLines
    var markLines = [];
    if (ann.markLines && ann.markLines.length) {{
        markLines = ann.markLines;
    }}

    var hasMarkLines = markLines.length > 0;

    // 2-grid: 日线K线 + MACD（无30min子图）
    var grids = [
        {{ left: 60, right: 20, top: 20, height: '55%' }},
        {{ left: 60, right: 20, top: '68%', height: '25%' }}
    ];
    var xAxes = [
        {{ type: 'category', data: dates, gridIndex: 0, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ color: '#888', fontSize: 10, rotate: 30 }} }},
        {{ type: 'category', data: dates, gridIndex: 1, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ show: false }} }}
    ];
    var yAxes = [
        {{ type: 'value', gridIndex: 0, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ color: '#888', fontSize: 10 }}, splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.06)' }} }} }},
        {{ type: 'value', gridIndex: 1, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ color: '#888', fontSize: 10 }}, splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.06)' }} }} }}
    ];
    var series = [
        {{
            type: 'candlestick', name: '日线K线',
            data: (item.highs || []).map(function(h, i) {{
                return [item.opens ? item.opens[i] : closes[i], closes[i],
                        item.lows ? item.lows[i] : closes[i], h];
            }}),
            xAxisIndex: 0, yAxisIndex: 0,
            itemStyle: {{ color: '#ff4757', color0: '#2ed573', borderColor: '#ff4757', borderColor0: '#2ed573' }},
            markPoint: {{ data: buyMarks }},
            markLine: hasMarkLines ? {{ silent: true, symbol: 'none', data: markLines }} : undefined
        }},
        {{
            type: 'bar', name: '日线MACD',
            data: macdHist.map(function(v) {{ return v || 0; }}),
            xAxisIndex: 1, yAxisIndex: 1,
            itemStyle: {{ color: function(params) {{ return (params.value || 0) >= 0 ? 'rgba(255,71,87,0.7)' : 'rgba(46,213,115,0.7)'; }} }}
        }}
    ];

    var option = {{
        backgroundColor: '#252545',
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        series: series,
        tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }}
    }};
    chart.setOption(option);
}}

// ========== ECharts 走势图 ==========
function renderChart(idx, ver, domId) {{
    domId = domId || ('chart_' + ver + '_' + idx);
    var dom = document.getElementById(domId);
    if (!dom || dom.clientWidth === 0) return;

    var picks = REPORT_DATA['picks_' + ver] || [];
    var pick = picks[idx];
    if (!pick) return;

    // 销毁旧图表
    if (window._charts && window._charts[domId]) {{
        window._charts[domId].dispose();
    }}

    var chartHeight = 420;

    var chart = echarts.init(dom);
    window._charts = window._charts || {{}};
    window._charts[domId] = chart;

    var dates = pick.dates || [];
    var closes = pick.closes || [];
    var macdHist = pick.macd_hist || [];
    var ann = pick.chart_annotations || {{}};

    // 准备买卖点标注
    var buyMarks = [];
    (pick.buy_points || []).forEach(function(bp) {{
        if (bp.index !== undefined && bp.index < dates.length) {{
            buyMarks.push({{
                coord: [dates[bp.index], bp.price],
                value: bp.type,
                symbol: 'triangle',
                symbolSize: 14,
                itemStyle: {{ color: '#ff4757' }},
                label: {{ show: true, position: 'bottom', color: '#ff4757', fontSize: 11, formatter: bp.type }}
            }});
        }}
    }});

    // Add annotation markPoints
    if (ann.markPoints && ann.markPoints.length) {{
        ann.markPoints.forEach(function(mp) {{
            buyMarks.push({{
                coord: mp.coord,
                symbol: mp.symbol || 'pin',
                symbolSize: mp.symbolSize || 30,
                itemStyle: mp.itemStyle || {{ color: '#ff4757' }},
                label: mp.label || {{ show: true }}
            }});
        }});
    }}

    // 中枢区间
    var markAreas = [];
    if (pick.pivot_zg && pick.pivot_zd) {{
        var n = dates.length;
        var startIdx = Math.max(0, n - 30);
        markAreas.push([{{
            xAxis: dates[startIdx],
            yAxis: pick.pivot_zd,
            itemStyle: {{ color: 'rgba(255,165,0,0.08)' }}
        }}, {{
            xAxis: dates[n - 1],
            yAxis: pick.pivot_zg
        }}]);
    }}

    // Annotation markLines
    var markLines = [];
    if (ann.markLines && ann.markLines.length) {{
        markLines = ann.markLines;
    }}

    var hasMarkLines = markLines.length > 0;

    var grids, xAxes, yAxes, series;

    grids = [
        {{ left: 60, right: 20, top: 20, height: '55%' }},
        {{ left: 60, right: 20, top: '68%', height: '25%' }}
    ];
    xAxes = [
        {{ type: 'category', data: dates, gridIndex: 0, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ color: '#888', fontSize: 10, rotate: 30 }} }},
        {{ type: 'category', data: dates, gridIndex: 1, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ show: false }} }}
    ];
    yAxes = [
        {{ type: 'value', gridIndex: 0, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ color: '#888', fontSize: 10 }}, splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.06)' }} }} }},
        {{ type: 'value', gridIndex: 1, axisLine: {{ lineStyle: {{ color: '#444' }} }}, axisLabel: {{ color: '#888', fontSize: 10 }}, splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.06)' }} }} }}
    ];
    series = [
        {{
            type: 'candlestick', name: '日线K线',
            data: (pick.highs || []).map(function(h, i) {{
                return [pick.opens ? pick.opens[i] : closes[i], closes[i],
                        pick.lows ? pick.lows[i] : closes[i], h];
            }}),
            xAxisIndex: 0, yAxisIndex: 0,
            itemStyle: {{ color: '#ff4757', color0: '#2ed573', borderColor: '#ff4757', borderColor0: '#2ed573' }},
            markPoint: {{ data: buyMarks }},
            markArea: {{ silent: true, data: markAreas }},
            markLine: hasMarkLines ? {{ silent: true, symbol: 'none', data: markLines }} : undefined
        }},
        {{
            type: 'bar', name: '日线MACD',
            data: macdHist.map(function(v) {{ return v || 0; }}),
            xAxisIndex: 1, yAxisIndex: 1,
            itemStyle: {{ color: function(params) {{ return (params.value || 0) >= 0 ? 'rgba(255,71,87,0.7)' : 'rgba(46,213,115,0.7)'; }} }}
        }}
    ];

    var option = {{
        backgroundColor: '#252545',
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        series: series,
        tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }}
    }};
    chart.setOption(option);
}}

// ========== 历史数据 ==========
function renderHistoryTabs() {{
    var dates = HISTORY_DATA.dates || [];
    if (dates.length <= 1) return;
    document.getElementById('historySection').style.display = 'block';

    var html = '';
    dates.forEach(function(d) {{
        var active = d === REPORT_DATA.date ? ' active' : '';
        html += '<button class="history-tab' + active + '" onclick="showHistory(\\'' + d + '\\')">' + d + '</button>';
    }});
    document.getElementById('historyTabs').innerHTML = html;
}}

function showHistory(dateStr) {{
    // 未授权时只允许访问 PUBLIC_DATES 中的日期
    if (!GRANTED && ACCESS_PUBLIC_DATES.indexOf(dateStr) === -1) return;

    var reports = HISTORY_DATA.reports || {{}};
    var report = reports[dateStr];
    if (!report) return;
    REPORT_DATA = {{
        date: dateStr,
        market: report.market || {{}},
        chanlun_structure: report.chanlun_structure || {{}},
        picks_pure: report.picks_pure || [],
        picks_fusion: report.picks_fusion || [],
        sector_flow: report.sector_flow || [],
        sector_outflow: report.sector_outflow || [],
        limit_up_pool: report.limit_up_pool || [],
        events: report.events || [],
        forecast: report.forecast || {{}},
        sell_signals: report.sell_signals || [],
    }};
    renderMarketCards();
    renderMarketStructure();
    renderSectorFlow();
    renderSectorOutflow();
    renderEvents();
    renderForecast();
    renderSellSignals();
    renderLimitUp();
    switchVersion(CURRENT_VERSION);
    var tabs = document.querySelectorAll('.history-tab');
    tabs.forEach(function(t) {{
        t.classList.toggle('active', t.textContent.trim() === dateStr);
    }});
}}

// ========== 受限提示（仅 PUBLIC_DATES=[] 时显示） ==========
function renderNoPublicData() {{
    document.getElementById('historySection').style.display = 'none';
    document.getElementById('historyContent').innerHTML =
        '<div style="text-align:center;padding:60px 20px;color:#888;">' +
        '<p style="font-size:18px;margin-bottom:12px;">暂无日报数据</p>' +
        '</div>';
}}

function loadHistory() {{
    if (window.location.protocol === 'file:') return;
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'data.json', true);
    xhr.onload = function() {{
        if (xhr.status === 200) {{
            try {{
                HISTORY_DATA = JSON.parse(xhr.responseText);
                renderHistoryTabs();
            }} catch(e) {{}}
        }}
    }};
    xhr.send();
}}

// ========== 启动 ==========
window.onload = init;
window.onhashchange = function() {{
    var h = window.location.hash.replace('#', '');
    if (h === 'pure' || h === 'fusion') switchVersion(h);
}};
</script>

</body>
</html>"""

    # 写文件
    if output_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(base_dir, OUTPUT_DIR)

    date_dir = os.path.join(output_dir, date_str)
    os.makedirs(date_dir, exist_ok=True)
    data_dir = os.path.join(output_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    # per-day JSON（含完整图表数据）
    write_daily_data_json(daily_data, data_dir)

    # manifest
    write_data_manifest(date_str, data_dir)

    # index.html → 最新
    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 归档目录
    archive_path = os.path.join(date_dir, "index.html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  日报已生成: {index_path}")
    print(f"  数据已写入: {data_dir}")
    print(f"  归档至: {archive_path}")
    return index_path


# ============================================================
# per-day JSON + manifest
# ============================================================
def write_daily_data_json(daily_data, data_dir):
    """将当日全量数据写入 docs/data/{date}.json"""
    date_str = daily_data["date"]
    path = os.path.join(data_dir, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(daily_data, f, ensure_ascii=False, cls=NpEncoder, indent=2)


def write_data_manifest(date_str, data_dir):
    """维护 docs/data/index.json — 日期列表 + 最新日期"""
    manifest_path = os.path.join(data_dir, "index.json")
    existing = {"dates": [], "latest": date_str}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass
    if date_str not in existing.get("dates", []):
        existing.setdefault("dates", []).append(date_str)
        existing["dates"].sort()
    existing["latest"] = date_str
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
        "events": report_data.get("events", []),
        "forecast": report_data.get("forecast", {}),
        "sell_signals": _serialize_sell_signals(report_data.get("sell_signals", [])),
        "diagnostics": report_data.get("diagnostics", {}),
    }
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
