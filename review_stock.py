#!/usr/bin/env python3
"""缠论鉴股 - 临时鉴股

Analyze one or more stocks on-demand, without requiring holdings config.
Generates a stand-alone HTML report.

Usage:
    python3 review_stock.py --stocks 600519,宁德时代,新易盛
    python3 review_stock.py --stocks 600519 --no-llm
    python3 review_stock.py --stocks 600519 --refresh-cache
"""
import argparse
import os
import sys
import numpy as np

from chanlun.chan_engine import analyze
from chanlun.data_fetcher import fetch_daily_kline, fetch_30min_kline, set_force_refresh_cache
from chanlun.stock_review.importer import resolve_names
from chanlun.stock_review.chanlun_diagnosis import build_diagnosis
from chanlun.stock_review.rule_action import generate_rule_action
from chanlun.stock_review.fundamentals import fetch_fundamentals
from chanlun.stock_review.news import fetch_news, analyze_news_sentiment
from chanlun.stock_review.llm_review import run_llm_review
from chanlun.stock_review.report_generator import write_report
from chanlun.stock_review.models import Holding


OUTPUT_DIR_DEFAULT = "docs/stock-review/ad-hoc"


def parse_stocks_arg(arg):
    """Parse comma-separated stock list string.

    Returns list of stock identifiers (codes or names).
    """
    if not arg:
        return []
    return [s.strip() for s in arg.split(",") if s.strip()]


def resolve_stock_names(stock_ids):
    """Resolve a list of stock codes/names to Holding objects.

    Returns list of Holding objects (with code filled where possible).
    """
    holdings = []
    for sid in stock_ids:
        # Check if it looks like a pure numeric code
        if sid.isdigit() and len(sid) == 6:
            h = Holding(account="临时鉴股", code=sid, name="", source="adhoc")
        else:
            h = Holding(account="临时鉴股", code="", name=sid, source="adhoc")
        holdings.append(h)

    resolved, unresolved, _ = resolve_names(holdings)
    if unresolved:
        print(f"[WARN] {len(unresolved)} 只股票无法解析: "
              f"{', '.join(h.name for h in unresolved)}")

    return resolved


def main(stocks=None, use_llm=True, output_dir=None, date_str=None, refresh_cache=False):
    """Main entry point for ad-hoc stock review.

    Args:
        stocks: list of stock codes or names
        use_llm: whether to run LLM review
        output_dir: output directory for HTML report
        date_str: date string
        refresh_cache: force refresh K-line cache
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR_DEFAULT

    if refresh_cache:
        set_force_refresh_cache(True)

    if not stocks:
        print("[ERROR] 请指定股票: --stocks 600519,宁德时代")
        return

    print("=" * 60)
    print("缠论鉴股 - 临时鉴股")
    print(f"股票: {', '.join(stocks)}")
    print("=" * 60)

    # 1. Resolve names
    print("[1/4] 解析股票名称...")
    holdings = resolve_stock_names(stocks)
    print(f"  共解析 {len(holdings)} 只股票")

    # 2. K-line + chanlun
    print("[2/4] 获取K线并运行缠论分析...")
    results = []
    for i, h in enumerate(holdings):
        code = h.code
        name = h.name or code
        print(f"  [{i+1}/{len(holdings)}] {name}({code}) ...", end=" ")

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

    # 3. Rule actions + fundamentals + news + LLM
    print("[3/4] 生成诊断...")
    review_results = []
    for i, (h, diag) in enumerate(results):
        code = h.code
        name = h.name or code
        print(f"  [{i+1}/{len(results)}] {name}({code}) ...", end=" ")

        rule_action = generate_rule_action(
            diag["daily"], diag["min30"],
            {"code": code, "name": name}
        )

        fundamentals = fetch_fundamentals(code, name)
        news_items = fetch_news(code, name)
        news_analysis = analyze_news_sentiment(news_items)

        facts = {
            "holding": {"code": code, "name": name, "source": "adhoc"},
            "daily_structure": diag["daily"],
            "min30_structure": diag["min30"],
            "fundamentals_raw": fundamentals,
            "news_raw": news_items,
            "review_date": date_str,
            "rule_action": rule_action,
        }
        llm_review = run_llm_review(facts, use_llm=use_llm)

        review_results.append({
            "holding": {
                "account": "临时鉴股",
                "code": code,
                "name": name,
                "source": "adhoc",
                "quantity": None,
                "cost_price": None,
                "market_price": None,
                "market_value": None,
                "pnl": None,
                "pnl_pct": None,
                "note": "",
            },
            "price_snapshot": {"close": diag["daily"].get("close")},
            "chanlun_daily": diag["daily"],
            "chanlun_30min": diag["min30"],
            "fundamentals": fundamentals,
            "news": news_analysis,
            "news_raw": news_items,
            "rule_action": rule_action,
            "llm_review": llm_review,
            "risks": [],
        })
        print("OK")

    # 4. Generate report
    print("[4/4] 生成报告...")
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_dir)
    html_path = write_report(review_results, report_dir, date_str=date_str, is_ad_hoc=True)
    print(f"  报告已生成: {html_path}")
    print("=" * 60)
    print("完成!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="缠论鉴股 - 临时鉴股")
    parser.add_argument("--stocks", type=str, required=True,
                        help="股票代码或名称，逗号分隔，如 600519,宁德时代")
    parser.add_argument("--no-llm", action="store_true", help="跳过LLM复核")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--refresh-cache", action="store_true", help="强制刷新K线缓存")
    parser.add_argument("--output", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    stocks = parse_stocks_arg(args.stocks)
    main(
        stocks=stocks,
        use_llm=not args.no_llm,
        output_dir=args.output,
        date_str=args.date,
        refresh_cache=args.refresh_cache,
    )
