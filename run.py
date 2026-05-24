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

import os
import sys
import json
import time
import argparse
from datetime import datetime

import numpy as np
import random

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DAY_LOOKBACK, HISTORY_DAYS, OUTPUT_DIR, DEBUG_OUTPUT_DIR,
    SECTOR_OUTFLOW_COUNT, EVENT_TOP_N,
)
from chanlun.data_fetcher import (
    collect_daily_data, collect_30min_data,
    fetch_daily_kline, fetch_kline,
    _build_code_to_name,
    fetch_sector_outflow, fetch_limit_up_pool,
)
from chanlun.chan_engine import analyze
from chanlun.screener_pure import screen_daily_pure, screen_30min_pure
from chanlun.screener_fusion import screen_daily_fusion, screen_30min_fusion
from chanlun.scorer import apply_scores
from chanlun.report_generator import generate_report, update_data_json
from chanlun.market_news import fetch_cls_news, rank_events, enrich_events, generate_forecast


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


def fetch_market_indices():
    """拉取主要市场指数行情"""
    indices = {}
    for name, code in MARKET_INDICES.items():
        kline = fetch_kline(code, klt="101", count=3)
        if kline and len(kline["closes"]) >= 2:
            prev = kline["closes"][-2]
            curr = kline["closes"][-1]
            chg_pct = (curr - prev) / prev * 100 if prev > 0 else 0
            indices[name] = {
                "close": round(float(curr), 2),
                "change_pct": round(float(chg_pct), 2),
            }
        else:
            indices[name] = {"close": 0, "change_pct": 0}
    return indices


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


# ============================================================
# 主流程
# ============================================================
def main(debug=False):
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"缠论选股系统启动 — {today} 14:35")
    print(f"调试模式: {debug}")

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
            # 从第一个板块的成分股中随机抽 DEBUG_SAMPLE_SIZE 只
            sample_sector = sectors[0]
            all_stocks = fetch_sector_stocks(sample_sector["code"])
            sample_size = min(10, len(all_stocks))
            test_stocks = random.sample(all_stocks, sample_size) if len(all_stocks) > sample_size else all_stocks
            print(f"[DEBUG] 从板块「{sample_sector['name']}」{len(all_stocks)}只成分股中随机抽取{len(test_stocks)}只")
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
        daily_data = {
            "sectors": sectors,
            "sh_index": sh_kline,
            "stocks": stocks_with_kline,
        }
    else:
        daily_data = collect_daily_data()

    sectors = daily_data["sectors"]
    sh_kline = daily_data["sh_index"]
    stocks_with_kline = daily_data["stocks"]

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
        sector_stocks[stock["code"]] = {"sector": sec, "change_pct": chg}
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
    # Phase 4: 双通道日线筛选
    # ================================================================
    print("=" * 60)
    print("Phase 4: 双通道日线筛选")
    print("=" * 60)

    # 纯净版
    print("[纯净版]")
    pure_pool = screen_daily_pure(chan_results, sector_stocks, sectors)
    print(f"  日线初筛: {len(pure_pool)} 只进入目标池")

    # 融合版（需要上证数据用于趋势判断）
    print("[融合版]")
    sh_closes = sh_kline["closes"] if sh_kline else None
    sh_volumes = sh_kline["volumes"] if sh_kline else None
    fusion_pool = screen_daily_fusion(chan_results, sh_closes, sector_stocks)
    print(f"  日线初筛: {len(fusion_pool)} 只进入目标池")

    # ================================================================
    # Phase 5: 30分钟精细确认
    # ================================================================
    print("=" * 60)
    print("Phase 5: 30分钟精细确认")
    print("=" * 60)

    # 收集两个目标池的股票代码（取并集）
    pure_codes = {s["code"] for s in pure_pool}
    fusion_codes = {s["code"] for s in fusion_pool}
    all_target_codes = pure_codes | fusion_codes
    all_targets = [{"code": c, "name": ""} for c in all_target_codes]

    # 拉取30分钟K线
    min30_data_list = collect_30min_data(all_targets)

    # 30分钟数据不可用时（如周末），跳过精细确认，直接用日线结果
    if not min30_data_list:
        print("  30分钟数据获取失败，跳过精细确认，直接用日线结果")
        pure_confirmed = pure_pool
        fusion_confirmed = fusion_pool
    else:
        min30_map = {d["code"]: d for d in min30_data_list}

        # 对30分钟数据做缠论分析
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

        # 纯净版30分钟确认
        print("[纯净版 30min确认]")
        pure_confirmed = screen_30min_pure(pure_pool, chan_results_30min)
        print(f"  区间套确认: {len(pure_confirmed)} 只")

        # 融合版30分钟确认
        print("[融合版 30min确认]")
        fusion_confirmed = screen_30min_fusion(fusion_pool, chan_results_30min)
        print(f"  区间套确认: {len(fusion_confirmed)} 只")

    # ================================================================
    # Phase 6: 评分 + 生成报告
    # ================================================================
    print("=" * 60)
    print("Phase 6: 评分 + 生成报告")
    print("=" * 60)

    # 板块排名映射（用于融合版评分）
    sector_rank_map = sectors  # 已按资金流入排序

    # 评分
    pure_scored = apply_scores(pure_confirmed, version="pure")
    fusion_scored = apply_scores(fusion_confirmed, version="fusion", sector_rank_map=sector_rank_map)

    # 自适应评分过滤：>75分全保留，不足20只从剩余按分补齐
    def adaptive_filter(scored, top_n=20, hard_threshold=75):
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        above = [s for s in scored if s.get("score", 0) > hard_threshold]
        below = [s for s in scored if s.get("score", 0) <= hard_threshold]
        if len(above) >= top_n:
            return above
        return above + below[:top_n - len(above)]

    pure_scored = adaptive_filter(pure_scored)
    fusion_scored = adaptive_filter(fusion_scored)

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
    market_indices = fetch_market_indices()

    # 上证缠论结构
    print("  分析上证缠论结构 ...")
    sh_chanlun = analyze_shanghai_chanlun(sh_kline)

    # 热点事件（LLM 分析在前，供时局推演引用）
    events = enrich_events(rank_events(fetch_cls_news(), sectors))

    # 构建报告数据
    report_data = {
        "date": today,
        "market": market_indices,
        "chanlun_structure": sh_chanlun,
        "picks_pure": pure_scored,
        "picks_fusion": fusion_scored,
        "sector_flow": sectors,
        # 新增模块
        "sector_outflow": fetch_sector_outflow(SECTOR_OUTFLOW_COUNT),
        "limit_up_pool": fetch_limit_up_pool(today.replace("-", "")),
        "events": events,
        "forecast": generate_forecast(market_indices, sh_chanlun, sectors, sh_volumes, events),
        "sell_signals": sell_signals,
    }

    # 生成 HTML（debug 模式输出到独立目录，隔离上线数据）
    output_dir_name = DEBUG_OUTPUT_DIR if debug else OUTPUT_DIR
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
    args = parser.parse_args()
    main(debug=args.debug)
