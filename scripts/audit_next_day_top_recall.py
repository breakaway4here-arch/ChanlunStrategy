#!/usr/bin/env python3
"""Read-only T/T+1 audit of strong-stock recall through every funnel gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from chanlun.candidate_funnel import FUNNEL_STAGES
from chanlun.market_history_store import MarketHistoryStore


DEFAULT_PAIRS = (
    ("2026-07-10", "2026-07-13"),
    ("2026-07-13", "2026-07-14"),
    ("2026-07-14", "2026-07-15"),
)


def _load_official_run(
    store: MarketHistoryStore,
    signal_date: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    rows = store.connection.execute(
        """
        SELECT * FROM funnel_runs
        WHERE report_date=?
        ORDER BY updated_at DESC, run_id DESC
        """,
        (str(signal_date),),
    ).fetchall()
    for raw in rows:
        row = dict(raw)
        metadata = json.loads(row["metadata_json"])
        if not bool(metadata.get("is_official")):
            continue
        if str(row["as_of"]) > str(signal_date):
            continue
        run = {
            "run_id": row["run_id"],
            "report_date": row["report_date"],
            "as_of": row["as_of"],
            "status": row["status"],
            "summary": json.loads(row["summary_json"]),
            "metadata": metadata,
        }
        return run, store.list_gate_events(row["run_id"])
    raise ValueError(
        "official funnel run not found for {}".format(signal_date)
    )


def _load_outcomes(
    store: MarketHistoryStore,
    signal_date: str,
    outcome_date: str,
) -> List[Dict[str, Any]]:
    instruments = store.list_instruments(asset_type="stock")
    ids = [int(row["instrument_id"]) for row in instruments]
    identity = {
        int(row["instrument_id"]): row for row in instruments
    }
    rows_by_id = store.query_bars_many(
        "day",
        ids,
        start=signal_date,
        end=outcome_date,
        as_of=outcome_date,
    )
    outcomes = []
    for instrument_id, rows in rows_by_id.items():
        by_date = {
            str(row["ts"]).split(" ", 1)[0]: row
            for row in rows
            if bool(row.get("is_final"))
        }
        signal_bar = by_date.get(str(signal_date))
        outcome_bar = by_date.get(str(outcome_date))
        if signal_bar is None or outcome_bar is None:
            continue
        signal_close = float(signal_bar["close"])
        outcome_close = float(outcome_bar["close"])
        if signal_close <= 0:
            continue
        instrument = identity[instrument_id]
        outcomes.append({
            "code": str(instrument["code"]),
            "name": str(instrument.get("name") or ""),
            "exchange": str(instrument["exchange"]),
            "signal_close": signal_close,
            "outcome_close": outcome_close,
            "gain_pct": (
                outcome_close / signal_close - 1.0
            ) * 100.0,
        })
    return sorted(
        outcomes,
        key=lambda row: (-float(row["gain_pct"]), str(row["code"])),
    )


def _rate(hit: int, total: int) -> float:
    return round(float(hit) / total, 6) if total else 0.0


def _failure_category(event: Mapping[str, Any]) -> str:
    gate = str(event.get("first_failure_gate") or "")
    reason = str(event.get("first_failure_reason") or "")
    if not event:
        return "漏斗记录缺失"
    if gate == "eligible":
        if reason in {"missing_meta", "insufficient_bars", "stale_latest_bar"}:
            return "基础数据不完整"
        if reason in {"st_or_delisting", "listed_days", "low_liquidity"}:
            return "基础资格未通过"
        return "基础资格未通过"
    if gate == "retrieval":
        return "召回名额未覆盖"
    if gate == "daily_channel":
        return "日线通道未匹配"
    if gate == "minute30":
        return "30分钟确认未通过"
    if gate == "fusion":
        return "融合门槛未通过"
    if gate == "display":
        return "展示或决策未通过"
    return "未归类"


def _target_metrics(
    target_rows: Sequence[Mapping[str, Any]],
    events_by_code: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    codes = [str(row["code"]) for row in target_rows]
    stages = {}
    for stage in FUNNEL_STAGES:
        hit_codes = [
            code
            for code in codes
            if stage in events_by_code.get(code, {}).get("passed_stages", [])
        ]
        stages[stage] = {
            "hit": len(hit_codes),
            "total": len(codes),
            "recall": _rate(len(hit_codes), len(codes)),
            "codes": hit_codes,
        }

    terminal = {"main": 0, "observe": 0, "reject": 0, "missing": 0}
    failures_by_gate = {}
    failures_by_reason = {}
    failures_by_category = {}
    category_codes = {}
    for code in codes:
        event = events_by_code.get(code, {})
        state = str(event.get("final_state") or "missing")
        if state not in terminal:
            state = "missing"
        terminal[state] += 1
        if state == "main":
            continue
        gate = str(event.get("first_failure_gate") or "missing")
        reason = str(
            event.get("first_failure_reason") or "funnel_record_missing"
        )
        category = _failure_category(event)
        failures_by_gate[gate] = failures_by_gate.get(gate, 0) + 1
        failures_by_reason[reason] = failures_by_reason.get(reason, 0) + 1
        failures_by_category[category] = (
            failures_by_category.get(category, 0) + 1
        )
        category_codes.setdefault(category, []).append(code)

    trend_codes = []
    overlay_codes = []
    for code in codes:
        event = events_by_code.get(code, {})
        passed = set(event.get("passed_stages") or [])
        channel = str(event.get("source_channel") or "")
        sources = set(event.get("retrieval_sources") or [])
        if (
            "daily_channel" in passed
            and (channel == "trend" or "trend" in sources)
        ):
            trend_codes.append(code)
        if (
            "retrieval" in passed
            and str(event.get("retrieval_pool") or "") == "overlay"
        ):
            overlay_codes.append(code)

    return {
        "count": len(codes),
        "codes": codes,
        "stages": stages,
        "terminal": terminal,
        "failure_breakdown": {
            "by_gate": failures_by_gate,
            "by_reason": failures_by_reason,
            "by_category": failures_by_category,
            "category_codes": category_codes,
        },
        "independent_increment": {
            "trend_hit": len(trend_codes),
            "trend_recall": _rate(len(trend_codes), len(codes)),
            "trend_codes": trend_codes,
            "overlay_hit": len(overlay_codes),
            "overlay_recall": _rate(len(overlay_codes), len(codes)),
            "overlay_codes": overlay_codes,
        },
    }


def _aggregate(pairs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    result = {}
    for target_name in ("top20", "top30", "gain_ge_9_5"):
        total = sum(int(pair["targets"][target_name]["count"]) for pair in pairs)
        stage_hits = {
            stage: sum(
                int(pair["targets"][target_name]["stages"][stage]["hit"])
                for pair in pairs
            )
            for stage in FUNNEL_STAGES
        }
        failure_breakdown = {}
        for dimension in ("by_gate", "by_reason", "by_category"):
            counts = {}
            for pair in pairs:
                values = pair["targets"][target_name][
                    "failure_breakdown"
                ][dimension]
                for key, value in values.items():
                    counts[key] = counts.get(key, 0) + int(value)
            failure_breakdown[dimension] = counts
        result[target_name] = {
            "count": total,
            "stages": {
                stage: {
                    "hit": hit,
                    "total": total,
                    "recall": _rate(hit, total),
                }
                for stage, hit in stage_hits.items()
            },
            "failure_breakdown": failure_breakdown,
            "independent_increment": {
                "trend_hit": sum(
                    int(
                        pair["targets"][target_name][
                            "independent_increment"
                        ]["trend_hit"]
                    )
                    for pair in pairs
                ),
                "overlay_hit": sum(
                    int(
                        pair["targets"][target_name][
                            "independent_increment"
                        ]["overlay_hit"]
                    )
                    for pair in pairs
                ),
            },
        }
    return result


def audit_recall_pairs(
    database_path: Any,
    pairs: Sequence[Tuple[str, str]] = DEFAULT_PAIRS,
) -> Dict[str, Any]:
    """Audit frozen official runs without invoking any remote data source."""
    pair_results = []
    with MarketHistoryStore(
        database_path, readonly=True, immutable=True
    ) as store:
        for signal_date, outcome_date in pairs:
            if str(outcome_date) <= str(signal_date):
                raise ValueError("outcome_date must be after signal_date")
            run, events = _load_official_run(store, str(signal_date))
            outcomes = _load_outcomes(
                store, str(signal_date), str(outcome_date)
            )
            events_by_code = {
                str(event.get("code")): event for event in events
            }
            target_sets = {
                "top20": outcomes[:20],
                "top30": outcomes[:30],
                "gain_ge_9_5": [
                    row
                    for row in outcomes
                    if float(row["gain_pct"]) >= 9.5
                ],
            }
            pair_results.append({
                "signal_date": str(signal_date),
                "outcome_date": str(outcome_date),
                "run": run,
                "outcome_coverage": len(outcomes),
                "outcomes": outcomes,
                "targets": {
                    name: _target_metrics(rows, events_by_code)
                    for name, rows in target_sets.items()
                },
            })
    return {
        "schema_version": 1,
        "database_path": str(Path(database_path).expanduser().resolve()),
        "official_only": True,
        "network_requests": 0,
        "pairs": pair_results,
        "aggregate": _aggregate(pair_results),
    }


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# 三日强股召回审计",
        "",
        "数据约束：仅使用 T 日 official 漏斗和 T/T+1 终态日线；网络请求 0。",
        "",
    ]
    for pair in result.get("pairs", []):
        lines.extend([
            "## {} → {}".format(
                pair["signal_date"], pair["outcome_date"]
            ),
            "",
            "| 样本 | 数量 | 召回池 | 日线通道 | 30min | 主池 | 观察 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        increments = []
        for name, label in (
            ("top20", "Top20"),
            ("top30", "Top30"),
            ("gain_ge_9_5", "涨幅≥9.5%"),
        ):
            target = pair["targets"][name]
            lines.append(
                "| {label} | {count} | {retrieval} | {daily} | "
                "{minute30} | {main} | {observe} |".format(
                    label=label,
                    count=target["count"],
                    retrieval=target["stages"]["retrieval"]["hit"],
                    daily=target["stages"]["daily_channel"]["hit"],
                    minute30=target["stages"]["minute30"]["hit"],
                    main=target["terminal"]["main"],
                    observe=target["terminal"]["observe"],
                )
            )
            increment = target["independent_increment"]
            increments.append(
                "- {} 独立增量：趋势通道 {}，板块 overlay {}。".format(
                    label,
                    increment["trend_hit"],
                    increment["overlay_hit"],
                )
            )
            categories = target["failure_breakdown"]["by_category"]
            if categories:
                increments.append(
                    "- {} 未进主池原因：{}。".format(
                        label,
                        "；".join(
                            "{} {}".format(category, count)
                            for category, count in sorted(
                                categories.items(),
                                key=lambda item: (-item[1], item[0]),
                            )
                        ),
                    )
                )
        lines.extend([""] + increments + [""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_pair(value: str) -> Tuple[str, str]:
    parts = [part.strip() for part in str(value).split(":", 1)]
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError("pair must be T:T+1")
    return parts[0], parts[1]


def main(argv: Iterable[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="审计次日强股在前一交易日候选漏斗中的召回"
    )
    parser.add_argument("--db", required=True, help="冻结行情 SQLite 路径")
    parser.add_argument(
        "--pair",
        action="append",
        type=_parse_pair,
        help="日期对 T:T+1，可重复；默认使用固定三组",
    )
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = audit_recall_pairs(args.db, args.pair or DEFAULT_PAIRS)
    json_text = json.dumps(
        result, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    markdown_text = render_markdown(result)
    if args.json_output:
        Path(args.json_output).write_text(json_text, encoding="utf-8")
    else:
        print(json_text, end="")
    if args.markdown_output:
        Path(args.markdown_output).write_text(
            markdown_text, encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
