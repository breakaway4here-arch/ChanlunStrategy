#!/usr/bin/env python3
"""Build a deterministic, synthetic report for browser acceptance.

The fixture deliberately contains no production report, account, token, or
holding data.  It uses the same decision-workbench projection builder as the
application and adds small hand-written K-line arrays so the browser test can
exercise the real chart lifecycle.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chanlun.decision_workbench import build_decision_workbench


DAY = "2026-09-11"
BASIS = {"adjustment": "qfq", "factor_vs_raw": 1.0}


def _series(seed: int, *, volume: str = "full") -> dict:
    """Return a small synthetic daily chart with explicit quantity metadata."""

    dates = [f"2026-08-{day:02d}" for day in range(1, 29)] + [
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
        DAY,
    ]
    base = 10.0 + seed / 10.0
    closes = [round(base + index * 0.04 + ((index + seed) % 5) * 0.03, 3)
              for index in range(len(dates))]
    opens = [round(value - 0.08, 3) for value in closes]
    highs = [round(value + 0.16, 3) for value in closes]
    lows = [round(value - 0.16, 3) for value in opens]
    volumes = [1000 + seed * 10 + index * 3 for index in range(len(dates))]
    if volume == "partial":
        volumes = [None if index < len(volumes) - 18 else value
                   for index, value in enumerate(volumes)]
    if volume == "missing":
        volumes = []
    if volume == "misaligned":
        volumes = volumes[-18:]
    metadata = {
        "volume_units": ["hands" if value is not None else None for value in volumes],
        "volume_raw_units": ["shares" if value is not None else None for value in volumes],
        "volume_sources": ["synthetic-fixture" if value is not None else None for value in volumes],
        "volume_unit": "hands",
        "volume_raw_unit": "shares",
        "volume_source": "synthetic-fixture",
    }
    if volume == "partial":
        metadata["volume_status"] = "partial"
        metadata["volume_reason"] = "合成样本只提供末段成交量"
    elif volume == "missing":
        metadata["volume_status"] = "missing"
        metadata["volume_reason"] = "合成样本未提供成交量"
    elif volume == "misaligned":
        metadata["volume_status"] = "conflict"
        metadata["volume_reason"] = "合成错位负例：成交量数组短于K线窗口"
    return {
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
        **metadata,
        "chart_annotations": {
            "markLines": [{
                "name": "synthetic-reference",
                "yAxis": closes[-1] - 0.2,
                "lineStyle": {"color": "rgba(116,185,255,0.5)", "type": "dotted"},
            }],
            "markPoints": [{
                "name": "合成测试信号",
                "coord": [DAY, closes[-1]],
                "symbol": "pin",
                "symbolSize": 18,
            }],
            "labels": ["合成测试样本"],
        },
        "buy_points": [{"type": "合成测试买点", "price": closes[-1]}],
    }


def _market_sentiment() -> dict:
    components = {"breadth": 66, "limit_ecology": 70, "index": 61,
                  "turnover": 72, "trend": 74}
    evidence = {
        "breadth": {"available": True, "advance_count": 2200,
                     "decline_count": 1800, "flat_count": 800,
                     "advance_ratio": 0.46},
        "limit_ecology": {"available": True, "limit_up_count": 52,
                           "limit_down_count": 4},
        "index": {"available": True, "valid_count": 6,
                   "average_change_pct": 0.62},
        "turnover": {"available": True, "ratio_to_ma5": 1.08,
                      "ratio_to_ma20": 1.02},
        "trend": {"available": True, "above_ma20_ratio": 0.58},
    }
    return {
        "date": DAY, "score": 68, "label": "偏强", "coverage": 1,
        "version": "synthetic-market-v1", "insufficient": False,
        "components": components, "evidence": evidence,
    }


def _candidate(
    code: str,
    name: str,
    view: str,
    rank: int,
    *,
    sector: str = "芯片",
    action: str | None = "可上车",
    invalidation: float | None = 9.0,
    status: str = "verified",
    latest_date: str = DAY,
    stale: bool = False,
    final: bool = True,
    volume: str = "full",
    chart: bool = True,
    timeframe: str = "30m",
) -> tuple[dict, dict]:
    semantics = "formal" if view in {"main", "h4_t3"} else "watch_only"
    row = {
        "code": code,
        "name": name,
        "sector": sector,
        "view_rank": rank,
        "action_semantics": semantics,
        "price_basis": copy.deepcopy(BASIS),
        "decision_engine_v1": {"total_score": 62 if action == "可上车" else 38},
        "ref": {"pool": "picks_fusion" if view == "main" else (
            "h4_t3_pool" if view == "h4_t3" else "startup_watchlist"),
                "code": code},
        "data_status": {
            "daily": status, "latest_date": latest_date, "stale": stale,
            "is_final": final, "source": "synthetic-fixture",
        },
        "risk_flags": ["合成测试样本"],
    }
    if chart:
        row.update(_series(rank, volume=volume))
    if semantics == "formal":
        row["formal_decision_contract"] = {
            "action": action,
            "action_reason": "合成结构确认",
            "reference_price": 10.0,
            "invalidation_price": invalidation,
            "intended_horizon": 3,
            "requires_30m": True,
        }

    evidence_status = "available"
    if status in {"stale", "conflict"}:
        evidence_status = status
    evidence = {
        "code": code,
        "summary": {"status": evidence_status, "as_of": DAY,
                    "name": name, "sector": sector,
                    "summary": "合成浏览器验收样本"},
        "daily_structure": {
            "status": evidence_status, "as_of": DAY, "is_final": final,
            "summary": "合成日线结构证据",
        },
        "sublevel_30m": {
            "status": "available", "as_of": DAY, "is_final": True,
            "summary": f"{timeframe}合成确认依据", "timeframe": timeframe,
            "interval": timeframe, "bars": 30,
        },
        "price_evidence": {
            "status": "available", "as_of": DAY,
            "current_price": 11.0, "reference_price": 10.0,
            "invalidation_price": invalidation,
        },
        "volume_and_capital": {
            "status": "partial" if volume == "partial" else (
                "missing" if volume == "missing" else "available"),
            "as_of": DAY, "summary": "合成成交量证据",
        },
        "market_and_sector": {
            "status": "available", "as_of": DAY,
            "summary": "合成市场与板块证据",
        },
        "risk_and_next": {
            "status": "available", "as_of": DAY,
            "next_confirmation": ["合成确认条件"],
            "cancel_conditions": ["跌破合成失效位"],
        },
        "historical_validation": {
            "status": "partial", "as_of": DAY,
            "summary": "测试样本不用于收益结论",
        },
    }
    if view not in {"main", "h4_t3"}:
        row.pop("decision_engine_v1", None)
        row.pop("price_basis", None)
        row.pop("formal_decision_contract", None)
        row["primary_reason"] = "合成研究观察样本"
        evidence["sublevel_30m"]["status"] = "partial"
    if status == "conflict":
        evidence["daily_structure"]["status"] = "conflict"
        evidence["daily_structure"]["summary"] = "合成结构证据冲突"
    if status == "stale":
        evidence["summary"]["status"] = "stale"
        evidence["daily_structure"]["status"] = "stale"
        evidence["daily_structure"]["stale"] = True
    if status == "missing":
        evidence["daily_structure"] = {"status": "missing", "as_of": DAY}
    return row, evidence


def build() -> dict:
    report = {
        "date": DAY,
        "data_quality": {
            "as_of": DAY + "T15:05:00+08:00", "is_official": True,
            "bar_state": "closed", "market_status": "verified",
        },
        "selection_input_health": {
            "schema_version": 2, "status": "verified",
            "formal": {"status": "verified", "formal_actions_allowed": True,
                       "all_formal_actions_allowed": True,
                       "blocked_strategies": []},
        },
        "price_basis": copy.deepcopy(BASIS),
        "strategy_version": "ui-browser-fixture-v1",
        "market_sentiment": _market_sentiment(),
        "market": {
            "上证指数": {"close": 3100.0, "change_pct": 0.62, "date": DAY,
                       "source": "synthetic-fixture"},
            "创业板指": {"close": 2200.0, "change_pct": 1.08, "date": DAY,
                       "source": "synthetic-fixture"},
        },
        "sector_flow": [{"name": "芯片", "net_flow": 1000000,
                          "source": "synthetic-fixture"}],
        "sector_outflow": [{"name": "银行", "net_flow": -300000,
                             "source": "synthetic-fixture"}],
        "decision_brief": {"status": "rules_only", "theses": [{
            "theme": "合成主线", "direction": "观察", "stage": "观察",
            "risk_reasons": [],
        }]},
    }

    views: dict[str, list[dict]] = {"main": [], "h4_t3": [], "confirming": []}
    evidence_views: dict[str, list[dict]] = {"main": [], "h4_t3": [], "confirming": []}
    raw_pools: dict[str, list[dict]] = {"picks_fusion": [], "picks_pure": [],
                                        "h4_t3_pool": [], "startup_watchlist": []}

    def add(view: str, code: str, name: str, rank: int, **kwargs) -> None:
        row, evidence = _candidate(code, name, view, rank, **kwargs)
        views[view].append(row)
        evidence_views[view].append(evidence)
        raw_pools[{"main": "picks_fusion", "h4_t3": "h4_t3_pool",
                   "confirming": "startup_watchlist"}[view]].append(row)

    add("main", "600001", "完整正式样本", 1)
    add("main", "600002", "正式缺价样本", 2, invalidation=None)
    add("main", "600003", "正式分歧样本", 3)
    add("h4_t3", "600003", "正式分歧样本", 1, action="不推荐")
    add("confirming", "600004", "研究不覆盖样本", 1)
    add("main", "600005", "过期冲突样本", 4, status="stale",
        latest_date="2026-08-28", stale=True)
    add("main", "600006", "无日线样本", 5, status="missing", chart=False)
    add("main", "600007", "部分量能样本", 6, volume="partial")
    add("main", "600008", "超过四十字的合成长名称浏览器验收样本用于断言窄屏不会横向溢出", 7)
    add("main", "600009", "普通正式样本", 8)
    add("main", "600010", "十五分钟错配样本", 8, timeframe="15m")

    # Keep the full decision list at 25 unique instruments so the acceptance
    # checks can prove that paging only changes visible rows, not comparison.
    for index in range(11, 26):
        add("confirming", f"6000{index:02d}", f"研究样本{index}", index - 8,
            sector="芯片" if index % 2 else "银行", chart=index == 11)

    negative_raw = {"code": "999001", "name": "错位成交量负例", **_series(99, volume="misaligned")}
    raw_pools["picks_pure"] = [negative_raw]
    report.update(raw_pools)
    report["workspace"] = {
        "default_view": "main",
        "views": views,
        "view_meta": {
            "main": {"role": "formal", "action_semantics": "formal",
                      "availability": {"state": "available"}},
            "h4_t3": {"role": "formal", "action_semantics": "formal",
                      "availability": {"state": "available"}},
            "confirming": {"role": "research", "action_semantics": "watch_only",
                           "availability": {"state": "available"}},
        },
    }
    evidence = {"report_date": DAY, "schema_version": 1,
                "views": evidence_views}
    projection = build_decision_workbench(
        report, report["workspace"], evidence,
        snapshot_id="ui-browser-fixture-v1",
    )
    expected = {
        item["code"]: {"page_status": item["page_status"],
                       "formal_action": item.get("formal_action"),
                       "is_executable": item["is_executable"]}
        for item in projection["items"]
    }
    return {
        "report": report,
        "workbench": projection,
        "recommendation_evidence": evidence,
        "expected": expected,
        "cases": {
            "formal_complete": "600001",
            "formal_missing_price": "600002",
            "formal_strategy_disagreement": "600003",
            "research_only": "600004",
            "expired_conflict": "600005",
            "no_daily": "600006",
            "partial_volume": "600007",
            "long_name": "600008",
            "timeframe_mismatch": "600010",
            "paging_total": 25,
            "fixture_only": True,
        },
        "negatives": {
            "misaligned_volume": negative_raw,
        },
    }


def main() -> int:
    payload = build()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
