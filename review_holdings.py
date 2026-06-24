#!/usr/bin/env python3
"""缠论鉴股 - 自动持仓日报

Reads holdings from accounts config, runs chanlun analysis on each holding,
generates an HTML report.

Usage:
    python3 review_holdings.py
    python3 review_holdings.py --no-llm
    python3 review_holdings.py --date 2026-05-26
    python3 review_holdings.py --refresh-cache
"""
import argparse
import os
import sys
import numpy as np

from chanlun.chan_engine import analyze
from chanlun.data_fetcher import fetch_daily_kline, fetch_30min_kline, set_force_refresh_cache
from chanlun.stock_review.importer import load_accounts, resolve_names
from chanlun.stock_review.chanlun_diagnosis import build_diagnosis
from chanlun.stock_review.rule_action import generate_rule_action
from chanlun.stock_review.fundamentals import fetch_fundamentals
from chanlun.stock_review.news import fetch_news, analyze_news_sentiment
from chanlun.stock_review.llm_review import run_llm_review
from chanlun.stock_review.report_generator import write_report
from chanlun.stock_review.models import StockReviewResult, Holding


OUTPUT_DIR_DEFAULT = "docs/stock-review"


def main(use_llm=True, output_dir=None, date_str=None, refresh_cache=False):
    """Main entry point for holdings review."""
    if output_dir is None:
        output_dir = OUTPUT_DIR_DEFAULT

    if refresh_cache:
        set_force_refresh_cache(True)

    print("=" * 60)
    print("缠论鉴股 - 持仓日报")
    print("=" * 60)

    # 1. Load holdings
    print("[1/5] 加载持仓数据...")
    config_path = "holdings/accounts.yaml"
    holdings = load_accounts(config_path)

    if not holdings:
        print("[WARN] 未找到持仓配置，请先创建 holdings/accounts.yaml")
        print("  可复制 holdings/accounts.example.yaml 并修改")
        return

    # Resolve names to codes
    resolved, unresolved, _ = resolve_names(holdings)
    if unresolved:
        print(f"[WARN] {len(unresolved)} 只股票无法解析代码: "
              f"{', '.join(h.name for h in unresolved)}")

    print(f"  共加载 {len(resolved)} 只持仓股票")

    # 2. Fetch K-line data and run chanlun analysis
    print("[2/5] 获取K线数据并运行缠论分析...")
    results = []
    for i, h in enumerate(resolved):
        code = h.code
        name = h.name
        print(f"  [{i+1}/{len(resolved)}] {name}({code}) ...", end=" ")

        try:
            daily_klines = fetch_daily_kline(code)
            min30_klines = fetch_30min_kline(code)

            daily_result = None
            min30_result = None

            if daily_klines and len(daily_klines.get("closes", [])) >= 30:
                daily_result = analyze(
                    code, name,
                    daily_klines["dates"], daily_klines["opens"],
                    daily_klines["highs"], daily_klines["lows"],
                    daily_klines["closes"], daily_klines["volumes"],
                )

            if min30_klines and len(min30_klines.get("closes", [])) >= 40:
                min30_result = analyze(
                    code, name,
                    min30_klines["dates"], min30_klines["opens"],
                    min30_klines["highs"], min30_klines["lows"],
                    min30_klines["closes"], min30_klines["volumes"],
                )

            diag = build_diagnosis(code, name, daily_result, min30_result)
            print("OK")
        except Exception as e:
            print(f"FAILED: {e}")
            diag = build_diagnosis(code, name, None, None)

        results.append((h, diag))

    # 3. Rule actions + fundamentals + news
    print("[3/5] 生成规则动作、基本面和消息面...")
    review_results = []
    for i, (h, diag) in enumerate(results):
        code = h.code
        name = h.name
        print(f"  [{i+1}/{len(results)}] {name}({code}) ...", end=" ")

        rule_action = generate_rule_action(
            diag["daily"], diag["min30"],
            {"code": code, "name": name,
             "cost_price": h.cost_price, "quantity": h.quantity}
        )

        fundamentals = fetch_fundamentals(code, name)
        news_items = fetch_news(code, name)
        news_analysis = analyze_news_sentiment(news_items)

        price_snapshot = {
            "close": diag["daily"].get("close"),
            "date": diag["daily"].get("close_date", ""),
        }

        review_results.append({
            "holding": {
                "account": h.account,
                "code": code,
                "name": name,
                "source": h.source,
                "quantity": h.quantity,
                "cost_price": h.cost_price,
                "market_price": h.market_price,
                "market_value": h.market_value,
                "pnl": h.pnl,
                "pnl_pct": h.pnl_pct,
                "note": h.note,
            },
            "price_snapshot": price_snapshot,
            "chanlun_daily": diag["daily"],
            "chanlun_30min": diag["min30"],
            "fundamentals": fundamentals,
            "news": news_analysis,
            "news_raw": news_items,
            "rule_action": rule_action,
            "llm_review": {},
            "risks": [],
        })
        print("OK")

    # 4. LLM review
    print("[4/5] LLM复核...")
    for i, r in enumerate(review_results):
        facts = {
            "holding": r["holding"],
            "daily_structure": r["chanlun_daily"],
            "min30_structure": r["chanlun_30min"],
            "fundamentals_raw": r["fundamentals"],
            "news_raw": r.get("news_raw", []),
            "review_date": date_str,
            "rule_action": r["rule_action"],
        }
        r["llm_review"] = run_llm_review(facts, use_llm=use_llm)
        if use_llm:
            fa_rating = r["llm_review"].get("fundamental_analysis", {}).get("rating", "?")
            action = r["llm_review"].get("integrated_decision", {}).get("action", "?")
            print(f"  [{i+1}/{len(review_results)}] {r['holding']['name']}: 基本面{fa_rating} → {action}")
    if not use_llm:
        print("  已跳过 (--no-llm，使用本地规则分析)")

    # 5. Generate report
    print("[5/5] 生成报告...")
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_dir)
    html_path = write_report(review_results, report_dir, date_str=date_str, is_ad_hoc=False)
    print(f"  报告已生成: {html_path}")
    print("=" * 60)
    print("完成!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="缠论鉴股 - 持仓日报")
    parser.add_argument("--no-llm", action="store_true", help="跳过LLM复核")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--refresh-cache", action="store_true", help="强制刷新K线缓存")
    parser.add_argument("--output", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    main(
        use_llm=not args.no_llm,
        output_dir=args.output,
        date_str=args.date,
        refresh_cache=args.refresh_cache,
    )
