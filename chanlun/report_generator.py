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
            "macd_hist": _slice(p.get("macd_hist", [])),
            # 图表标注
            "chart_annotations": build_chart_annotations(p, slice_start, dates_sliced, closes_sliced),
            # 买卖点标注（超出图表范围的已过滤）
            "buy_points": [b for b in (_adjust_bp(b) for b in p.get("buy_points", [])) if b is not None],
            "reference_buy_points": [_serialize_bp(b) for b in p.get("reference_buy_points", [])],
            "blocked_buy_points": [_serialize_bp(b) for b in p.get("blocked_buy_points", [])],
            # 中枢
            "pivot_zg": p["pivots"].get("ZG") if p.get("pivots") else None,
            "pivot_zd": p["pivots"].get("ZD") if p.get("pivots") else None,
            # 30min data for dual chart
            "has_30min": bool(p.get("result_30min")),
            "dates_30min": _safe_list(p.get("result_30min", {}).dates) if p.get("result_30min") else [],
            "closes_30min": _safe_list(p.get("result_30min", {}).closes) if p.get("result_30min") else [],
            "opens_30min": _safe_list(p.get("result_30min", {}).opens) if p.get("result_30min") else [],
            "highs_30min": _safe_list(p.get("result_30min", {}).highs) if p.get("result_30min") else [],
            "lows_30min": _safe_list(p.get("result_30min", {}).lows) if p.get("result_30min") else [],
            "volumes_30min": _safe_list(p.get("result_30min", {}).volumes) if p.get("result_30min") else [],
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
    """Serialize startup watchlist items for JSON output."""
    result = []
    for w in watchlist:
        closes = w.get("closes")
        if closes is not None and len(closes) > 0:
            curr_price = float(closes[-1])
        else:
            curr_price = 0
        ref_price = w.get("close", 0)
        dist_pct = round((curr_price - ref_price) / ref_price * 100, 2) if ref_price and ref_price > 0 else None
        item = {
            "code": w.get("code", ""),
            "name": w.get("name", ""),
            "type": w.get("type", "强势启动观察"),
            "tier": w.get("tier", "watch"),
            "source_type": w.get("source_type", ""),
            "startup_reason": w.get("startup_reason", ""),
            "startup_signals": w.get("startup_signals", []),
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

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>缠论选股日报 — {date_str}</title>
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
    <div id="signalSummary"></div>
    <div id="versionDiff"></div>
    <div id="pickTable"></div>
</div>

<!-- 启动观察 -->
<div class="section" id="startupWatchSection">
    <div class="section-title">启动观察 <span style="font-size:13px;color:#ffa502;" id="startupWatchCount"></span></div>
    <div id="startupWatchContent"></div>
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
    <div class="section-title">事件驱动 Top10</div>
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

async function init() {{
    // 全局 resize：遍历所有已渲染图表
    window.addEventListener('resize', function() {{
        var charts = window._charts || {{}};
        Object.keys(charts).forEach(function(k) {{
            try {{ charts[k].resize(); }} catch(e) {{}}
        }});
    }});

    GRANTED = await resolveGranted();

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

function renderAll() {{
    renderMarketCards();
    renderMarketStructure();
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
        var idx = m[key];
        var cls = (idx.change_pct || 0) >= 0 ? 'up' : 'down';
        var sign = (idx.change_pct || 0) >= 0 ? '+' : '';
        html += '<div class="index-card">' +
            '<div class="name">' + key + '</div>' +
            '<div class="value">' + (idx.close || '-').toLocaleString() + '</div>' +
            '<div class="change ' + cls + '">' + sign + (idx.change_pct || 0).toFixed(2) + '%</div>' +
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
        html += '<div class="detail-section"><strong>关键信号：</strong>' + cs.key_signal + '</div>';
    }}
    if (cs.conclusion) {{
        html += '<div class="detail-section"><strong>结论：</strong>' + cs.conclusion + '</div>';
    }}
    if (!html) {{
        html = '<div class="detail-section">未能计算上证缠论结构</div>';
    }}
    document.getElementById('marketStructure').innerHTML = html;
}}

// ========== 板块资金 ==========
function renderSectorFlow() {{
    var sectors = (REPORT_DATA.sector_flow || []).slice(0, 10);
    var html = '';
    sectors.forEach(function(s, i) {{
        var cls = (s.flow || 0) >= 0 ? 'in' : 'out';
        html += '<div class="sector-tag">' +
            '<span class="rank">#' + (i + 1) + '</span>' +
            '<span class="sname">' + s.name + '</span>' +
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
    var html = '<table class="data-table"><thead><tr>' +
        '<th>排名</th><th>行业板块</th><th>涨跌幅</th><th>资金流向</th></tr></thead><tbody>';
    items.forEach(function(it, i) {{
        var chgCls = (it.change_pct || 0) >= 0 ? 'up' : 'down';
        var sign = (it.change_pct || 0) >= 0 ? '+' : '';
        html += '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td>' + it.name + '</td>' +
            '<td class="' + chgCls + '">' + sign + (it.change_pct || 0).toFixed(2) + '%</td>' +
            '<td style="color:#2ed573">' + (it.flow_str || '') + '</td>' +
            '</tr>';
    }});
    html += '</tbody></table>';
    document.getElementById('sectorOutflow').innerHTML = html;
}}

// ========== 事件驱动 ==========
function renderEvents() {{
    var events = REPORT_DATA.events || [];
    if (!events.length) {{
        document.getElementById('eventsSection').style.display = 'none';
        return;
    }}
    document.getElementById('eventsSection').style.display = '';
    var html = '';
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

        html += '<div class="event-item">' +
            '<span class="event-rank">' + (i + 1) + '</span>' +
            '<span style="color:' + levelColor + ';font-weight:bold;">' + (ev.display_title || ev.title || '') + '</span>';

        // AI headline
        if (imp.headline && !isFailed) {{
            html += '<div style="color:#dfe6e9;font-size:14px;margin:6px 0;">' +
                '📊 ' + imp.headline + '</div>';
        }} else if (isFailed) {{
            html += '<div style="color:#888;font-size:13px;margin:6px 0;">AI分析暂不可用</div>';
        }}

        // AI analysis points
        if (imp.analysis && imp.analysis.length && !isFailed) {{
            html += '<div style="color:#aaa;font-size:13px;line-height:1.6;margin:6px 0;">';
            imp.analysis.forEach(function(a) {{
                html += '<div style="margin-left:8px;">• ' + a + '</div>';
            }});
            html += '</div>';
        }}

        // Sector tags
        if (imp.positive_sectors && imp.positive_sectors.length || imp.negative_sectors && imp.negative_sectors.length) {{
            html += '<div class="impact-tags">';
            if (imp.positive_sectors && imp.positive_sectors.length) {{
                html += '<span class="impact-label">利好：</span>';
                imp.positive_sectors.forEach(function(s) {{
                    html += '<span class="impact-tag positive">' + s + '</span>';
                }});
            }}
            if (imp.negative_sectors && imp.negative_sectors.length) {{
                html += '<span class="impact-label">利空：</span>';
                imp.negative_sectors.forEach(function(s) {{
                    html += '<span class="impact-tag negative">' + s + '</span>';
                }});
            }}
            html += '</div>';
        }}

        // Stock recommendations
        if (imp.positive_stocks && imp.positive_stocks.length || imp.negative_stocks && imp.negative_stocks.length) {{
            html += '<div class="impact-stocks">';
            var renderStock = function(st, cls) {{
                return '<span class="impact-stock-item ' + cls + '">' +
                    '<span class="s-name">' + st.name + '</span>' +
                    '<span class="s-code">' + st.code + '</span>' +
                    (st.reason ? '<span class="s-reason">' + st.reason + '</span>' : '') +
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

        // Related tags
        if (tags.length) {{
            html += '<div class="event-stocks">📌 ' + tags.join(' / ') + '</div>';
        }}

        // Collapsed raw content
        var rawContent = ev.raw_content || ev.content || ev.brief || '';
        if (rawContent && !ev.has_redundant_content) {{
            html += '<div style="margin-top:8px;">' +
                '<a href="javascript:void(0)" onclick="var d=document.getElementById(\\'' + eventId + '\\');' +
                'd.style.display=d.style.display===\\'none\\'?\\'block\\':\\'none\\';' +
                'this.textContent=d.style.display===\\'none\\'?\\'查看原文 ▼\\':\\'收起 ▲\\'"' +
                'style="color:#74b9ff;font-size:12px;cursor:pointer;">查看原文 ▼</a>' +
                '<div id="' + eventId + '" style="display:none;color:#888;font-size:12px;line-height:1.6;margin-top:6px;' +
                'padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:6px;">' +
                rawContent + '</div></div>';
        }}

        html += '</div>';
    }});
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
    html += '<p><strong>📌 核心判断：' + fc.core_judgment + '</strong></p>';
    if (fc.volume_note) {{
        html += '<p style="color:#888;font-size:13px;">' + fc.volume_note + '</p>';
    }}
    if (fc.short_term && fc.short_term.length) {{
        html += '<span class="forecast-label">🔍 短期预判（1周内）：</span>';
        fc.short_term.forEach(function(s) {{
            html += '<p style="margin-left:12px;">' + s + '</p>';
        }});
    }}
    if (fc.mid_term) {{
        html += '<span class="forecast-label">🔍 中期预判（2-4周）：</span>';
        html += '<p style="margin-left:12px;">' + fc.mid_term + '</p>';
    }}
    if (fc.risks && fc.risks.length) {{
        html += '<div class="risk-box"><strong style="color:#ff4757;">⚠️ 风险提示</strong>';
        html += '<ul class="risk-list">';
        fc.risks.forEach(function(r) {{
            html += '<li>' + r + '</li>';
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
            '<td>' + s.code + '</td>' +
            '<td>' + s.name + '</td>' +
            '<td><span class="sell-tag">' + (sp.type || '-') + '</span></td>' +
            '<td>' + (sp.price || '-') + '</td>' +
            '<td>' + (s.sector || '-') + '</td>' +
            '<td>' + (s.trend_type || '-') + '</td>' +
            '<td style="font-size:12px;color:#aaa;">' + (sp.reason || '-') + '</td>' +
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
    var html = '';
    keys.forEach(function(sec) {{
        var list = groups[sec];
        html += '<h3 style="color:#fff;margin:18px 0 12px;font-size:15px;">📊 ' + sec + ' (' + list.length + '只)</h3>';
        html += '<div class="limit-up-list">';
        list.forEach(function(it) {{
            html += '<div class="limit-up-item">' +
                '<div class="stock-name">' + it.name + '</div>' +
                '<div class="stock-code">' + it.code + '</div>' +
                '</div>';
        }});
        html += '</div>';
    }});
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
        '<th>代码</th><th>名称</th><th>信号</th><th>信号年龄</th>' +
        '<th>参考价</th><th>现价</th><th>距参考价</th>' +
        '<th>启动原因</th><th>观察理由</th><th>次日条件</th>' +
        '</tr></thead><tbody>';
    watchlist.forEach(function(w) {{
        var conditions = (w.next_day_conditions || []).join('<br>');
        var ageLabel = w.startup_age_days !== undefined ? w.startup_age_days + '天' : '-';
        var refPrice = w.close || 0;
        var curPrice = w.current_price || 0;
        var distPct = w.distance_from_reference_pct;
        var distStr = distPct !== null && distPct !== undefined ? (distPct >= 0 ? '+' : '') + distPct.toFixed(2) + '%' : '-';
        var distColor = distPct !== null ? (distPct > 0 ? '#ff4757' : '#5effa0') : '#aaa';
        html += '<tr>' +
            '<td>' + w.code + '</td>' +
            '<td>' + w.name + '</td>' +
            '<td><span class="sell-tag">' + w.type + '</span></td>' +
            '<td style="font-size:12px;">' + ageLabel + '</td>' +
            '<td>' + (refPrice ? refPrice.toFixed(2) : '-') + '</td>' +
            '<td>' + (curPrice ? curPrice.toFixed(2) : '-') + '</td>' +
            '<td style="color:' + distColor + ';">' + distStr + '</td>' +
            '<td style="color:#ffa502;font-size:13px;">' + (w.startup_reason || '') + '</td>' +
            '<td style="color:#dfe6e9;font-size:13px;">' + (w.watch_reason || '') + '</td>' +
            '<td style="color:#aaa;font-size:12px;">' + conditions + '</td>' +
            '</tr>';
    }});
    html += '</tbody></table>';
    document.getElementById('startupWatchContent').innerHTML = html;
}}

// ========== 选股表格 ==========
function renderPickTable(ver) {{
    var picks = REPORT_DATA['picks_' + ver] || [];
    var isFusion = ver === 'fusion';

    renderSignalSummary(picks);
    renderVersionDiffSummary();

    var html = '<table class="chan-table"><thead><tr>' +
        '<th>代码</th><th>名称</th><th>信号类型</th>' +
        '<th>信号年龄</th><th>参考价</th><th>现价</th><th>距参考价</th>' +
        '<th>评分</th><th>一句话原因</th>';
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

        html += '<tr class="expandable" onclick="toggleChart(' + idx + ', \\'' + ver + '\\')">';
        html += '<td>' + p.code + '</td>';
        html += '<td>' + p.name + '</td>';
        html += '<td><span class="buy-tag ' + tagClass + '">' + (bp.type || '-') + '</span></td>';
        html += '<td style="color:' + ageColor + ';font-size:12px;">' + ageLabel + '</td>';
        html += '<td style="font-size:13px;">' + (refPrice ? refPrice.toFixed(2) : '-') + '</td>';
        html += '<td style="font-size:13px;">' + (curPrice ? curPrice.toFixed(2) : '-') + '</td>';
        html += '<td style="color:' + distColor + ';font-size:13px;">' + distStr + '</td>';
        html += '<td><span class="score-bar" style="width:' + barW + 'px;"></span>' + score.toFixed(1) + '</td>';
        html += '<td style="font-size:12px;white-space:normal;line-height:1.6;max-width:200px;">' + shortReason + '</td>';
        if (isFusion) {{
            var fa = p.fusion_admission || {{}};
            html += '<td style="font-size:12px;">' +
                (fa.passed ? '<span style="color:#5effa0;">通过</span>' : '<span style="color:#ff4757;">过滤</span>') +
                '</td>';
            html += '<td>' + (p.stop_loss ? p.stop_loss.toFixed(2) : '-') + '</td>';
        }}
        html += '</tr>';

        // —— Expand row: full detail ——
        var detail = '';
        detail += '<div class="detail-section">';

        // Basic info
        detail += '<div class="detail-group">' +
            '<div class="detail-group-title">信号详情</div>';
        if (bp.signal_date) detail += '<strong>信号发生日：</strong>' + bp.signal_date + '<br>';
        detail += '<strong>距今天数：</strong>' + ageLabel + '<br>';
        detail += '<strong>参考价：</strong>' + (refPrice ? refPrice.toFixed(2) : '-') +
            ' &nbsp; <strong>现价：</strong>' + (curPrice ? curPrice.toFixed(2) : '-') +
            ' &nbsp; <strong>距参考价：</strong><span style="color:' + distColor + ';">' + distStr + '</span><br>';
        detail += '<strong>完整原因：</strong>' + (bp.reason || bp.startup_reason || '-') + '<br>';
        if (bp.confirmed_by) detail += '<strong>30min确认：</strong>' + bp.confirmed_by +
            (bp.strength ? ' [' + bp.strength + ']' : '') + '<br>';
        if (bp.confirmations && bp.confirmations.length) detail += '<strong>确认细节：</strong>' + bp.confirmations.join('，') + '<br>';
        detail += '</div>';

        // Strong startup specifics
        if (bp.type === '强势启动候选') {{
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">强势启动详情</div>';
            if (bp.startup_date) detail += '<strong>启动日：</strong>' + bp.startup_date +
                (bp.startup_age_days !== undefined ? ' (' + bp.startup_age_days + '天前)' : '') + '<br>';
            if (bp.confirm_date) detail += '<strong>确认日：</strong>' + bp.confirm_date +
                (bp.confirm_age_days !== undefined ? ' (' + bp.confirm_age_days + '天前)' : '') + '<br>';
            if (bp.volume_ratio) detail += '<strong>放量倍数：</strong>' + bp.volume_ratio.toFixed(1) + '倍<br>';
            if (bp.change_pct) detail += '<strong>涨幅：</strong>' + bp.change_pct.toFixed(1) + '%<br>';
            if (bp.startup_signals && bp.startup_signals.length) detail += '<strong>突破类型：</strong>' + bp.startup_signals.join('，') + '<br>';
            if (bp.source_type) detail += '<strong>来源：</strong>' + bp.source_type + '<br>';
            detail += '</div>';
        }}

        // 底背驰/低吸 specifics
        if (bp.seed_type || bp.seed_reason) {{
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">原始参考信号</div>';
            if (bp.seed_type) detail += '<strong>种子类型：</strong>' + bp.seed_type + '<br>';
            if (bp.seed_reason) detail += '<strong>种子原因：</strong>' + bp.seed_reason + '<br>';
            if (bp.source_type) detail += '<strong>参考信号：</strong>' + bp.source_type + '<br>';
            detail += '</div>';
        }}

        // Risk / structure
        detail += '<div class="detail-group">' +
            '<div class="detail-group-title">结构状态</div>' +
            '<strong>走势类型：</strong>' + (p.trend_type || '-') + '<br>' +
            '<strong>日线中枢数量：</strong>' + (p.pivots ? (p.pivots.count || 0) : 0) + '<br>' +
            (p.pivot_zg && p.pivot_zd ? '<strong>中枢区间：</strong>[' + p.pivot_zd + ' — ' + p.pivot_zg + ']<br>' : '') +
            '<strong>共振等级：</strong>' + (resonance.level || '-') +
            (resonance.reason ? ' (' + resonance.reason + ')' : '') + '<br>' +
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
                 ' — ' + fa.reason + '<br>' : '') +
                (p.stop_loss_pct ? '<strong>止损：</strong>' + p.stop_loss_pct + '%<br>' : '') +
                '</div>';
        }}

        // Risk tips
        if (bp.recency_reason) {{
            var rColor = bp.is_recent ? (bp.signal_age_days >= 8 ? '#ffa502' : '#5effa0') : '#ff4757';
            detail += '<div class="detail-group">' +
                '<div class="detail-group-title">风险提示</div>' +
                '<span style="color:' + rColor + ';">' + bp.recency_reason + '</span><br>';
            if (bp.signal_age_days >= 8 && bp.is_recent) {{
                detail += '<span style="color:#ffa502;">⚠ 信号接近过期，建议优先关注更新鲜的信号</span><br>';
            }}
            detail += '</div>';
        }}

        detail += '</div>';

        html += '<tr class="chart-row" id="chartRow_' + ver + '_' + idx + '">' +
                '<td colspan="' + colspan + '" style="white-space:normal;line-height:1.6;">' +
                '<div class="chart-container" id="chart_' + ver + '_' + idx + '"></div>' +
                detail + '</td></tr>';
    }});
    html += '</tbody></table>';
    document.getElementById('pickTable').innerHTML = html;

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
    var row = document.getElementById('chartRow_' + ver + '_' + idx);
    if (!row) return;
    var isOpen = row.classList.contains('open');
    row.classList.toggle('open');
    if (!isOpen) {{
        setTimeout(function() {{ renderChart(idx, ver); }}, 100);
    }}
}}

// ========== ECharts 走势图 ==========
function renderChart(idx, ver) {{
    var domId = 'chart_' + ver + '_' + idx;
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

    function formatTooltip(params) {{
        var p = Array.isArray(params) ? params[0] : params;
        if (!p) return '';
        var name = p.name || '';
        var series = p.seriesName || '';
        var val = p.value;
        if (p.seriesType === 'candlestick' && Array.isArray(val)) {{
            return '<strong>' + series + '</strong><br>' +
                name + '<br>' +
                '开: ' + val[0] + '<br>' +
                '收: ' + val[1] + '<br>' +
                '低: ' + val[2] + '<br>' +
                '高: ' + val[3];
        }}
        return '<strong>' + series + '</strong><br>' + name + '<br>' + val;
    }}

    var option = {{
        backgroundColor: '#252545',
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        series: series,
        tooltip: {{
            trigger: 'item',
            formatter: formatTooltip,
            axisPointer: {{ type: 'cross' }}
        }}
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
