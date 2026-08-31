#!/usr/bin/env python3
"""Network-free, read-only walk-forward replay for right-side startup.

Feature construction is strictly as-of each trade date.  Later bars are read
only by ``collect_forward_outcome`` and are never passed to the selection
functions.  The default command writes nothing; an evidence directory must be
provided explicitly before a JSON artifact is created.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
import hashlib
import json
import math
import socket
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chanlun.chan_engine import analyze
from chanlun.fusion_admission import apply_fusion_admission
from chanlun.preclose_pipeline import evaluate_preclose_main_candidates
from chanlun.report_view_model import build_workspace
from chanlun.right_side_startup import (
    apply_right_side_startup_mode,
    build_right_side_startup_state,
)
from chanlun.scorer import apply_scores
from chanlun.trend_continuation import build_trend_continuation_pool
import config


HORIZONS = ("t1", "t3", "t5")
HORIZON_DAYS = {"t1": 1, "t3": 3, "t5": 5}
SCHEMA_VERSION = "right-side-startup-replay-v1"
MIN_OOS_TRADE_DATES = 20
MIN_T3_SAMPLES_PER_LANE = 20
MAX_RAW_CONFIRMED_DAILY_P95 = 20.0
DEFAULT_TRAIN_DAYS = 4
DEFAULT_EMBARGO_DAYS = 2
DEFAULT_TEST_DAYS = 2
DEFAULT_BLOCK_COUNT = 10


def read_only_uri(path: Any) -> str:
    absolute = str(Path(path).expanduser().resolve())
    return "file:{}?mode=ro".format(quote(absolute, safe="/"))


def connect_read_only(path: Any) -> sqlite3.Connection:
    connection = sqlite3.connect(read_only_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


@contextlib.contextmanager
def network_disabled():
    """Fail closed if a replay dependency attempts an outbound connection."""

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("network disabled during right-side replay")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def build_walkforward_blocks(
    trading_dates: Sequence[str],
    *,
    train_days: int = DEFAULT_TRAIN_DAYS,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    block_count: int = DEFAULT_BLOCK_COUNT,
) -> List[Dict[str, Any]]:
    dates = sorted(dict.fromkeys(str(value) for value in trading_dates))
    required = train_days + embargo_days + test_days * block_count
    if min(train_days, test_days, block_count) <= 0 or embargo_days < 1:
        raise ValueError("walk-forward windows must be positive with embargo")
    if len(dates) < required:
        raise ValueError(
            "walk-forward requires at least {} trading dates".format(required)
        )
    dates = dates[-required:]
    blocks = []
    for index in range(block_count):
        test_start = train_days + embargo_days + index * test_days
        train_end = test_start - embargo_days
        blocks.append({
            "fold": index + 1,
            "train_dates": dates[:train_end],
            "embargo_dates": dates[train_end:test_start],
            "test_dates": dates[test_start:test_start + test_days],
        })
    return blocks


def load_daily_bars(
    connection: sqlite3.Connection,
    instrument_id: int,
    trade_date: str,
    *,
    limit: int = 180,
) -> List[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT ts, open, high, low, close, volume
        FROM bars_day
        WHERE instrument_id = ?
          AND substr(ts, 1, 10) <= ?
          AND is_final = 1
        ORDER BY ts DESC
        LIMIT ?
        """,
        (int(instrument_id), str(trade_date), int(limit)),
    ).fetchall()
    return list(reversed(rows))


def load_30m_bars(
    connection: sqlite3.Connection,
    instrument_id: int,
    trade_date: str,
    *,
    limit: int = 160,
) -> List[sqlite3.Row]:
    cutoff = str(trade_date) + " 15:00:00"
    rows = connection.execute(
        """
        SELECT ts, open, high, low, close, volume
        FROM bars_30m
        WHERE instrument_id = ?
          AND ts <= ?
          AND is_final = 1
        ORDER BY ts DESC
        LIMIT ?
        """,
        (int(instrument_id), cutoff, int(limit)),
    ).fetchall()
    return list(reversed(rows))


def collect_forward_outcome(
    connection: sqlite3.Connection,
    instrument_id: int,
    trade_date: str,
) -> Dict[str, Any]:
    rows = connection.execute(
        """
        SELECT substr(ts, 1, 10) AS trade_date, close, low
        FROM bars_day
        WHERE instrument_id = ?
          AND substr(ts, 1, 10) >= ?
          AND is_final = 1
        ORDER BY ts
        LIMIT 6
        """,
        (int(instrument_id), str(trade_date)),
    ).fetchall()
    empty = {
        "returns_pct": {key: None for key in HORIZONS},
        "drawdowns_pct": {key: None for key in HORIZONS},
        "outcome_max_date": None,
    }
    if not rows or str(rows[0]["trade_date"]) != str(trade_date):
        return empty
    base = float(rows[0]["close"])
    if not math.isfinite(base) or base <= 0:
        return empty

    returns: Dict[str, Optional[float]] = {}
    drawdowns: Dict[str, Optional[float]] = {}
    for horizon in HORIZONS:
        days = HORIZON_DAYS[horizon]
        if len(rows) <= days:
            returns[horizon] = None
            drawdowns[horizon] = None
            continue
        returns[horizon] = round(
            (float(rows[days]["close"]) / base - 1.0) * 100.0, 6
        )
        path_lows = [float(row["low"]) for row in rows[1:days + 1]]
        drawdowns[horizon] = round(
            min(0.0, (min(path_lows) / base - 1.0) * 100.0), 6
        )
    return {
        "returns_pct": returns,
        "drawdowns_pct": drawdowns,
        "outcome_max_date": str(rows[min(5, len(rows) - 1)]["trade_date"]),
    }


def _nearest_rank(values: Sequence[float], percentile: float) -> Optional[float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, int(math.ceil(float(percentile) * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 6)


def _outcome_metrics(events: Sequence[Mapping[str, Any]], horizon: str) -> Dict[str, Any]:
    returns = []
    drawdowns = []
    missing = 0
    for event in events:
        value = (event.get("returns_pct") or {}).get(horizon)
        drawdown = (event.get("drawdowns_pct") or {}).get(horizon)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            missing += 1
            continue
        returns.append(float(value))
        if isinstance(drawdown, (int, float)) and math.isfinite(drawdown):
            drawdowns.append(float(drawdown))
    evaluable = len(returns)
    tail = sum(value <= -5.0 for value in drawdowns)
    return {
        "evaluable": evaluable,
        "missing": missing,
        "wins": sum(value > 0 for value in returns),
        "win_rate_pct": _round(
            100.0 * sum(value > 0 for value in returns) / evaluable
            if evaluable else None
        ),
        "mean_return_pct": _round(statistics.mean(returns) if returns else None),
        "median_return_pct": _round(statistics.median(returns) if returns else None),
        "p10_return_pct": _round(_nearest_rank(returns, 0.10)),
        "worst_return_pct": _round(min(returns) if returns else None),
        "max_drawdown_pct": _round(min(drawdowns) if drawdowns else None),
        "tail_le_minus_5_count": tail,
        "tail_le_minus_5_rate_pct": _round(
            100.0 * tail / len(drawdowns) if drawdowns else None
        ),
    }


def summarize_lane(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    materialized = [dict(event) for event in events]
    daily = Counter(str(event.get("trade_date") or "") for event in materialized)
    daily.pop("", None)
    daily_counts = {day: daily[day] for day in sorted(daily)}
    counts = list(daily_counts.values())
    return {
        "event_count": len(materialized),
        "trade_date_count": len(daily_counts),
        "daily_counts": daily_counts,
        "daily_count_mean": _round(statistics.mean(counts) if counts else None),
        "daily_count_p95": _round(_nearest_rank(counts, 0.95)),
        "outcomes": {
            horizon: _outcome_metrics(materialized, horizon)
            for horizon in HORIZONS
        },
    }


def build_activation_gate(
    right_side: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    shadow_diagnostics: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    right_t3 = (right_side.get("outcomes") or {}).get("t3") or {}
    baseline_t3 = (baseline.get("outcomes") or {}).get("t3") or {}
    right_median = right_t3.get("median_return_pct")
    baseline_median = baseline_t3.get("median_return_pct")
    right_tail = right_t3.get("tail_le_minus_5_rate_pct")
    baseline_tail = baseline_t3.get("tail_le_minus_5_rate_pct")
    comparable = all(
        isinstance(value, (int, float))
        for value in (right_median, baseline_median, right_tail, baseline_tail)
    )
    median_non_inferior = bool(
        comparable and float(right_median) >= float(baseline_median)
    )
    tail_delta = (
        round(float(right_tail) - float(baseline_tail), 6)
        if comparable else None
    )
    tail_within_limit = bool(comparable and tail_delta <= 2.0)
    public_daily_p95 = right_side.get("daily_count_p95")
    public_count_controlled = bool(
        public_daily_p95 is None or float(public_daily_p95) <= 3.0
    )
    raw_daily_counts = {
        str(row.get("trade_date") or ""): int(row.get("confirmed_count") or 0)
        for row in shadow_diagnostics
        if isinstance(row, Mapping) and row.get("trade_date")
    }
    raw_count_p95 = _round(
        _nearest_rank(list(raw_daily_counts.values()), 0.95)
    )
    raw_count_controlled = bool(
        raw_count_p95 is not None
        and float(raw_count_p95) <= MAX_RAW_CONFIRMED_DAILY_P95
    )
    oos_trade_dates = len(raw_daily_counts)
    enough_dates = oos_trade_dates >= MIN_OOS_TRADE_DATES
    right_samples = int(right_t3.get("evaluable") or 0)
    baseline_samples = int(baseline_t3.get("evaluable") or 0)
    enough_samples = (
        right_samples >= MIN_T3_SAMPLES_PER_LANE
        and baseline_samples >= MIN_T3_SAMPLES_PER_LANE
    )
    passed = bool(
        comparable
        and median_non_inferior
        and tail_within_limit
        and enough_dates
        and enough_samples
        and public_count_controlled
        and raw_count_controlled
    )
    reasons = []
    if not comparable:
        reasons.append("insufficient_comparable_t3_samples")
    if comparable and not median_non_inferior:
        reasons.append("t3_median_below_formal_baseline")
    if comparable and not tail_within_limit:
        reasons.append("t3_tail_delta_above_2pp")
    if not enough_dates:
        reasons.append("insufficient_oos_trade_dates")
    if not enough_samples:
        reasons.append("insufficient_t3_samples")
    if raw_count_p95 is None:
        reasons.append("missing_raw_candidate_volume_evidence")
    elif not raw_count_controlled:
        reasons.append("raw_candidate_volume_uncontrolled")
    if not public_count_controlled:
        reasons.append("public_top3_invariant_failed")
    return {
        "passed": passed,
        "promotion_eligible": False,
        "requires_real_shadow_day": True,
        "requires_new_authorization": True,
        "t3_median_non_inferior": median_non_inferior,
        "t3_tail_delta_pct_points": tail_delta,
        "t3_tail_delta_limit_pct_points": 2.0,
        "oos_trade_dates": oos_trade_dates,
        "minimum_oos_trade_dates": MIN_OOS_TRADE_DATES,
        "right_side_t3_samples": right_samples,
        "baseline_t3_samples": baseline_samples,
        "minimum_t3_samples_per_lane": MIN_T3_SAMPLES_PER_LANE,
        "raw_confirmed_daily_count_p95": raw_count_p95,
        "raw_confirmed_daily_count_p95_limit": MAX_RAW_CONFIRMED_DAILY_P95,
        "raw_candidate_volume_controlled": raw_count_controlled,
        "public_daily_count_p95_at_most_3": public_count_controlled,
        "public_daily_limit": 3,
        "reasons": reasons + ["replay_never_auto_promotes"],
    }


def build_replay_report(
    right_side_events: Sequence[Mapping[str, Any]],
    baseline_events: Sequence[Mapping[str, Any]],
    *,
    blocks: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    shadow_diagnostics: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    right_summary = summarize_lane(right_side_events)
    baseline_summary = summarize_lane(baseline_events)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": dict(source),
        "walkforward": {
            "block_count": len(blocks),
            "blocks": [dict(block) for block in blocks],
            "feature_future_data_used": False,
        },
        "lanes": {
            "right_side": right_summary,
            "formal_main_baseline": baseline_summary,
        },
        "activation_gate": build_activation_gate(
            right_summary,
            baseline_summary,
            shadow_diagnostics=shadow_diagnostics,
        ),
        "shadow_diagnostics": [dict(row) for row in shadow_diagnostics],
        "samples": {
            "right_side": [dict(event) for event in right_side_events],
            "formal_main_baseline": [dict(event) for event in baseline_events],
        },
    }


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _instrument_rows(
    connection: sqlite3.Connection, codes: Iterable[str]
) -> Dict[str, sqlite3.Row]:
    output: Dict[str, sqlite3.Row] = {}
    ordered = sorted(set(str(code).zfill(6) for code in codes if code))
    for offset in range(0, len(ordered), 400):
        chunk = ordered[offset:offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            "SELECT instrument_id, code, name FROM instruments "
            "WHERE asset_type='stock' AND code IN ({})".format(placeholders),
            chunk,
        ).fetchall()
        for row in rows:
            output[str(row["code"]).zfill(6)] = row
    return output


def _analyze_rows(code: str, name: str, rows: Sequence[sqlite3.Row]) -> Any:
    if not rows:
        return None
    return analyze(
        code,
        name or code,
        [row["ts"] for row in rows],
        [row["open"] for row in rows],
        [row["high"] for row in rows],
        [row["low"] for row in rows],
        [row["close"] for row in rows],
        [row["volume"] for row in rows],
    )


def _passes_daily_necessary_prefilter(rows: Sequence[sqlite3.Row]) -> bool:
    """Cheap necessary conditions; never replaces the strategy builder."""

    if len(rows) < 60:
        return False
    closes = [float(row["close"]) for row in rows]
    volumes = [float(row["volume"]) for row in rows]
    close = closes[-1]
    ma5 = statistics.mean(closes[-5:])
    ma10 = statistics.mean(closes[-10:])
    previous_volume = statistics.mean(volumes[-6:-1])
    if previous_volume <= 0:
        return False
    volume_ratio = volumes[-1] / previous_volume
    average_amount = statistics.mean(
        volumes[index] * closes[index] * 100.0
        for index in range(len(rows) - 5, len(rows))
    )
    return bool(
        close >= ma5 >= ma10
        and volume_ratio
        >= float(config.TREND_CONTINUATION_CONDITIONAL_VOLUME_RATIO)
        and average_amount >= float(config.MIN_DAILY_AMOUNT)
    )


def _report_path(report_dir: Path, trade_date: str) -> Path:
    direct = report_dir / (trade_date + ".json")
    if direct.exists():
        return direct
    nested = report_dir / trade_date / "data.json"
    if nested.exists():
        return nested
    raise FileNotFoundError("formal report missing for {}".format(trade_date))


def _load_report(report_dir: Path, trade_date: str) -> Dict[str, Any]:
    return json.loads(_report_path(report_dir, trade_date).read_text(encoding="utf-8"))


def _decision_market_context(
    report: Mapping[str, Any], trade_date: str
) -> Dict[str, Any]:
    sentiment = report.get("market_sentiment")
    return {
        "date": trade_date,
        "market_indices": report.get("market") or {},
        "sectors": report.get("sector_flow") or [],
        "market_sentiment": sentiment if isinstance(sentiment, Mapping) else {},
        "market_data_status": "verified" if isinstance(sentiment, Mapping) else "partial",
        "data_quality": report.get("data_quality") or {},
    }


def _shanghai_closes(
    connection: sqlite3.Connection, trade_date: str
) -> List[float]:
    row = connection.execute(
        """
        SELECT instrument_id FROM instruments
        WHERE asset_type='index' AND code='000001'
        ORDER BY CASE WHEN exchange='SH' THEN 0 ELSE 1 END
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return []
    return [
        float(bar["close"])
        for bar in load_daily_bars(
            connection, int(row["instrument_id"]), trade_date, limit=120
        )
    ]


def select_replay_right_side_public(
    candidates: Sequence[Mapping[str, Any]],
    *,
    report: Mapping[str, Any],
    trade_date: str,
    shanghai_closes: Sequence[float],
    evaluator: Any = None,
) -> Dict[str, Any]:
    """Reuse the formal fusion, scoring, Top3 and decision publication gates."""

    fusion_ready, fusion_diagnostics = apply_fusion_admission(
        copy.deepcopy(list(candidates or [])),
        list(shanghai_closes or []),
        {},
    )
    scored = apply_scores(fusion_ready, version="fusion", sector_rank_map=[])
    mode_state = apply_right_side_startup_mode(scored, mode="active")
    decision_state = evaluate_preclose_main_candidates(
        mode_state["published"],
        market_context=_decision_market_context(report, trade_date),
        trade_date=trade_date,
        evaluator=evaluator,
    )
    return {
        "main": list(decision_state["main"]),
        "diagnostics": {
            "confirmed_count": len(candidates or []),
            "fusion": fusion_diagnostics,
            "top3": mode_state["diagnostics"],
            "decision_evaluated_count": len(decision_state["evaluated"]),
            "public_main_count": len(decision_state["main"]),
        },
    }


def _retrieval_codes(
    connection: sqlite3.Connection,
    trade_date: str,
    report: Mapping[str, Any],
) -> List[str]:
    del report
    if not _table_exists(connection, "gate_events"):
        raise RuntimeError(
            "gate_events full retrieval universe is required for unbiased replay"
        )
    rows = connection.execute(
        "SELECT DISTINCT code FROM gate_events WHERE report_date=? ORDER BY code",
        (trade_date,),
    ).fetchall()
    codes = [str(row["code"]).zfill(6) for row in rows if row["code"]]
    if not codes:
        raise RuntimeError(
            "gate_events full retrieval universe is required for {}".format(
                trade_date
            )
        )
    return codes


def evaluate_right_side_date(
    connection: sqlite3.Connection,
    report_dir: Path,
    trade_date: str,
) -> Dict[str, Any]:
    report = _load_report(report_dir, trade_date)
    codes = _retrieval_codes(connection, trade_date, report)
    instruments = _instrument_rows(connection, codes)
    daily_results = []
    for code in codes:
        instrument = instruments.get(code)
        if instrument is None:
            continue
        daily_rows = load_daily_bars(
            connection, int(instrument["instrument_id"]), trade_date
        )
        if not daily_rows or str(daily_rows[-1]["ts"])[:10] != trade_date:
            continue
        if not _passes_daily_necessary_prefilter(daily_rows):
            continue
        daily_result = _analyze_rows(code, str(instrument["name"] or code), daily_rows)
        if daily_result is not None:
            daily_results.append(daily_result)

    seeds, _, _ = build_trend_continuation_pool(daily_results)
    seed_codes = {str(row.get("code") or "") for row in seeds}
    minute30_results = []
    for code in sorted(seed_codes):
        instrument = instruments.get(code)
        if instrument is None:
            continue
        minute_rows = load_30m_bars(
            connection, int(instrument["instrument_id"]), trade_date
        )
        if not minute_rows or str(minute_rows[-1]["ts"])[:10] != trade_date:
            continue
        minute_result = _analyze_rows(
            code, str(instrument["name"] or code), minute_rows
        )
        if minute_result is not None:
            minute_result.strategy_input_evidence = {
                "interval": "30m",
                "status": "verified",
                "latest_date": trade_date,
                "latest_ts": str(minute_rows[-1]["ts"]),
                "source": "market_history_db_replay",
                "bars": len(minute_rows),
                "stale": False,
                "is_final": True,
                "bar_state": "closed",
            }
            minute30_results.append(minute_result)

    state = build_right_side_startup_state(
        daily_results, minute30_results, mode="shadow"
    )
    public_state = select_replay_right_side_public(
        state.get("candidates") or [],
        report=report,
        trade_date=trade_date,
        shanghai_closes=_shanghai_closes(connection, trade_date),
    )
    return {
        "main": [dict(row) for row in public_state["main"]],
        "shadow_diagnostics": {
            "trade_date": trade_date,
            "retrieval_count": len(codes),
            "daily_prefilter_count": len(daily_results),
            "daily_seed_count": int(
                (state.get("diagnostics") or {}).get("daily_seed_count") or 0
            ),
            "min30_requested": int(
                (state.get("diagnostics") or {}).get("min30_requested") or 0
            ),
            "min30_verified": int(
                (state.get("diagnostics") or {}).get("min30_verified") or 0
            ),
            "confirmed_count": len(state.get("candidates") or []),
            "confirmed_codes": [
                str(row.get("code") or "")
                for row in state.get("candidates") or []
            ],
            "watch_count": len(state.get("watchlist") or []),
            "public_main_count": len(public_state["main"]),
            "public_main_codes": [
                str(row.get("code") or "") for row in public_state["main"]
            ],
            "publication": public_state["diagnostics"],
        },
    }


def load_formal_main_codes(report_dir: Path, trade_date: str) -> List[str]:
    workspace = build_workspace(_load_report(report_dir, trade_date))
    return [
        str(row.get("code") or "").zfill(6)
        for row in (workspace.get("views") or {}).get("main", [])
        if row.get("code")
    ]


def _attach_outcomes(
    connection: sqlite3.Connection,
    trade_date: str,
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    instruments = _instrument_rows(
        connection, [str(row.get("code") or "") for row in rows]
    )
    output = []
    seen = set()
    for raw in rows:
        code = str(raw.get("code") or "").zfill(6)
        if not code or code in seen or code not in instruments:
            continue
        seen.add(code)
        instrument = instruments[code]
        event = {"trade_date": trade_date, "code": code}
        if raw.get("name"):
            event["name"] = str(raw["name"])
        event.update(collect_forward_outcome(
            connection, int(instrument["instrument_id"]), trade_date
        ))
        output.append(event)
    return output


def _report_dates(report_dir: Path, as_of: str) -> List[str]:
    return sorted(
        path.stem
        for path in report_dir.glob("20??-??-??.json")
        if path.stem <= as_of
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_replay(
    market_db: Any,
    report_dir: Any,
    as_of: str,
    *,
    train_days: int = DEFAULT_TRAIN_DAYS,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    block_count: int = DEFAULT_BLOCK_COUNT,
) -> Dict[str, Any]:
    database = Path(market_db).expanduser().resolve()
    reports = Path(report_dir).expanduser().resolve()
    dates = _report_dates(reports, as_of)
    blocks = build_walkforward_blocks(
        dates,
        train_days=train_days,
        embargo_days=embargo_days,
        test_days=test_days,
        block_count=block_count,
    )
    test_dates = sorted({
        day for block in blocks for day in block["test_dates"]
    })
    right_side_events = []
    baseline_events = []
    shadow_diagnostics = []
    with network_disabled():
        connection = connect_read_only(database)
        try:
            for trade_date in test_dates:
                right_state = evaluate_right_side_date(
                    connection, reports, trade_date
                )
                baseline_codes = load_formal_main_codes(reports, trade_date)
                right_side_events.extend(_attach_outcomes(
                    connection, trade_date, right_state["main"]
                ))
                shadow_diagnostics.append(right_state["shadow_diagnostics"])
                baseline_events.extend(_attach_outcomes(
                    connection,
                    trade_date,
                    [{"code": code} for code in baseline_codes],
                ))
        finally:
            connection.close()
    return build_replay_report(
        right_side_events,
        baseline_events,
        blocks=blocks,
        source={
            "as_of": as_of,
            "market_db": str(database),
            "market_db_sha256": _sha256(database),
            "database_uri_mode": "ro",
            "database_read_only": True,
            "network": "disabled",
            "feature_cutoff": "trade_date 15:00:00",
            "formal_baseline": "build_workspace(formal_report).views.main",
            "right_side_builder": "build_right_side_startup_state",
        },
        shadow_diagnostics=shadow_diagnostics,
    )


def _aggregate_projection(report: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": report.get("schema_version"),
        "source": report.get("source"),
        "walkforward": report.get("walkforward"),
        "lanes": report.get("lanes"),
        "activation_gate": report.get("activation_gate"),
        "shadow_summary": {
            "dates": len(report.get("shadow_diagnostics") or []),
            "confirmed": sum(
                int(row.get("confirmed_count") or 0)
                for row in report.get("shadow_diagnostics") or []
            ),
            "public_main": sum(
                int(row.get("public_main_count") or 0)
                for row in report.get("shadow_diagnostics") or []
            ),
            "min30_verified": sum(
                int(row.get("min30_verified") or 0)
                for row in report.get("shadow_diagnostics") or []
            ),
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-db", required=True)
    parser.add_argument("--reports", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--embargo-days", type=int, default=DEFAULT_EMBARGO_DAYS)
    parser.add_argument("--test-days", type=int, default=DEFAULT_TEST_DAYS)
    parser.add_argument("--block-count", type=int, default=DEFAULT_BLOCK_COUNT)
    parser.add_argument(
        "--evidence-dir",
        help="Explicit output directory; omitted means no filesystem writes",
    )
    args = parser.parse_args(argv)
    report = run_replay(
        args.market_db,
        args.reports,
        args.as_of,
        train_days=args.train_days,
        embargo_days=args.embargo_days,
        test_days=args.test_days,
        block_count=args.block_count,
    )
    if args.evidence_dir:
        output_dir = Path(args.evidence_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "right-side-startup-replay.json"
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(str(output))
    else:
        print(json.dumps(
            _aggregate_projection(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
