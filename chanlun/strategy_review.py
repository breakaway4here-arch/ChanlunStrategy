"""Deterministic, attributable strategy scorecards from immutable ledger rows."""

import math
import os
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from .market_history_store import MarketHistoryStore
from .pool_contract import resolve_list_pool, resolve_nested_strategy_pool


HORIZONS = (1, 3, 5)
EXPECTED_ADJUSTMENT = "qfq"
BENCHMARK_CODE = "000300"
SCORECARD_SCHEMA_VERSION = 2
SCORECARD_THRESHOLDS = {
    "mature_samples": 100,
    "active_dates": 20,
    "calendar_months": 2,
}
_DEFAULT_RESEARCH_TIER = "prospective_ledger"
_LEGACY_RESEARCH_TIER = "legacy_unclassified"
_SCORECARD_ROLES = {"formal", "baseline", "research", "diagnostic"}
_SECTION_BY_ROLE = {
    "formal": "formal",
    "baseline": "baselines",
    "research": "research",
    "diagnostic": "gates",
}
_SURFACE_BY_ROLE = {
    "formal": "formal_recommendation",
    "baseline": "baseline_candidates",
    "research": "research_review",
    "diagnostic": "gate_diagnostics",
}
# The tuple is intentionally exact.  It is only used for immutable rows
# written before evaluation_role/publication_surface were frozen.
_LEGACY_ROLE_REGISTRY = {
    ("daily_fusion", "fusion-v2", "daily_fusion"): "formal",
    ("daily_fusion", "daily-fusion-close-v1", "picks_fusion"): "formal",
    ("daily_pure", "pure-v1", "daily_pure"): "baseline",
    ("daily_pure", "daily-pure-close-v1", "picks_pure"): "baseline",
    ("next_day_boom", "boom-v1", "next_day_boom"): "research",
    ("next_day_boom", "next-day-boom-close-v1", "next_day_boom"): "research",
    ("luojie_pool", "luojie-v1", "luojie_pool"): "research",
    ("luojie_pool", "luojie-close-v1", "luojie_pool"): "research",
    ("observation_gate", "gate-v1", "observation_gate"): "diagnostic",
    ("observation_gate", "observation-gate-close-v1", "observation_watchlist"): "diagnostic",
    ("h4_t3", "h4_t3_k30_tail_safe_v1", "h4_t3_pool"): "formal",
}
DEFAULT_SAMPLE_EXCLUSIONS_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "strategy_sample_exclusions.json"
)


def load_strategy_sample_exclusions(path=None):
    source = Path(path) if path else DEFAULT_SAMPLE_EXCLUSIONS_PATH
    if not source.exists():
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("invalid strategy sample exclusion registry")
    incidents = payload.get("incidents")
    if not isinstance(incidents, list):
        raise ValueError("invalid strategy sample exclusion incidents")
    return [item for item in incidents if isinstance(item, dict)]


def _sample_exclusion(entry, contribution, exclusions):
    report_date = str(entry.get("report_date") or "")
    code = str(entry.get("code") or "")
    strategy = str(contribution.get("strategy_name") or "")
    source_pool = str(contribution.get("source_pool") or "")
    for rule in exclusions or []:
        dates = {str(value) for value in rule.get("report_dates") or []}
        strategies = {str(value) for value in rule.get("strategy_names") or []}
        source_pools = {str(value) for value in rule.get("source_pools") or []}
        codes = {str(value) for value in rule.get("codes") or []}
        if dates and report_date not in dates:
            continue
        if strategies and strategy not in strategies:
            continue
        if source_pools and source_pool not in source_pools:
            continue
        if codes and code not in codes:
            continue
        return {
            "incident_id": str(rule.get("incident_id") or "unregistered"),
            "reason": str(
                rule.get("reason")
                or "strategy_input_stale_or_unverified"
            ),
        }
    return None


def _manifest_list_state(report, field_name):
    state = resolve_list_pool(report, field_name)
    return state["state"], state["count"], state["reason"]


def _manifest_pool_state(report, field_name, *, formal_h4=False):
    state = resolve_nested_strategy_pool(
        report, field_name, formal_h4=formal_h4
    )
    run_state = "unavailable" if state["state"] == "partial" else state["state"]
    return run_state, state["count"], state["reason"]


def _strategy_input_health(report, strategy_name):
    selection = report.get("selection_input_health")
    selection = selection if isinstance(selection, dict) else {}
    by_strategy = selection.get("by_strategy")
    by_strategy = by_strategy if isinstance(by_strategy, dict) else {}
    specific = by_strategy.get(strategy_name)
    if isinstance(specific, dict):
        return specific
    if strategy_name in {"daily_fusion", "h4_t3"}:
        formal = selection.get("formal")
        return formal if isinstance(formal, dict) else {}
    return {}


def _blocked_strategy_state(report, strategy_name):
    health = _strategy_input_health(report, strategy_name)
    if strategy_name in {"daily_fusion", "h4_t3"}:
        trusted = (
            health.get("formal_actions_allowed") is True
            and health.get("status") == "verified"
        )
    else:
        trusted = health.get("status") == "verified"
    if trusted:
        return None
    blocker = str(health.get("blocking_reason") or "")
    if blocker == "strategy_upstream_contract_mismatch":
        reason = "共同上游合同不匹配，策略结果仅供追溯并停止评分"
    elif strategy_name in {"daily_fusion", "h4_t3"}:
        reason = "策略输入状态缺失、过期或未核验，正式动作已封闭"
    else:
        reason = "策略输入过期或未核验，候选仅供事故复盘并停止评分"
    return "unavailable", 0, reason


def _strategy_blocking_reason(report, strategy_name):
    health = _strategy_input_health(report, strategy_name)
    return str(health.get("blocking_reason") or "")


def build_strategy_run_manifest(report_data):
    """Describe the current day's registered strategy runs, including zeros."""
    report = report_data if isinstance(report_data, dict) else {}
    report_date = str(report.get("date") or "")
    fusion_state = resolve_list_pool(report, "picks_fusion")
    fusion_published_count = sum(
        1 for item in fusion_state["candidates"]
        if isinstance(item, dict)
        and str(((item.get("decision_engine_v1") or {}).get("decision_code")) or "").strip().lower() == "recommend"
    )
    h4_payload = report.get("h4_t3_pool")
    h4_payload = h4_payload if isinstance(h4_payload, dict) else {}
    fusion_blocked_state = _blocked_strategy_state(
        report, "daily_fusion"
    )
    h4_blocked_state = _blocked_strategy_state(report, "h4_t3")
    luojie_blocked_state = _blocked_strategy_state(
        report, "luojie_pool"
    )
    specs = [
        {
            "strategy": "daily_pure",
            "name": "日线纯净策略",
            "version": "daily-pure-close-v1",
            "source_pool": "picks_pure",
            "evaluation_role": "baseline",
            "publication_surface": "baseline_candidates",
            "entry_mode": "immediate_close",
            "intended_horizon": None,
            "state": _manifest_list_state(report, "picks_pure"),
        },
        {
            "strategy": "daily_fusion",
            "name": "日线融合策略",
            "version": "daily-fusion-close-v1",
            "source_pool": "picks_fusion",
            "evaluation_role": "formal",
            "publication_surface": "formal_recommendation",
            "entry_mode": "immediate_close",
            "intended_horizon": None,
            "state": (
                fusion_blocked_state
                or _manifest_list_state(report, "picks_fusion")
            ),
            "source_candidate_count": fusion_state["count"],
            "published_count": (
                0 if fusion_blocked_state else fusion_published_count
            ),
            "blocking_reason": (
                _strategy_blocking_reason(report, "daily_fusion")
                if fusion_blocked_state else ""
            ),
        },
        {
            "strategy": "observation_gate",
            "name": "观察池门控",
            "version": "observation-gate-close-v1",
            "source_pool": "observation_watchlist",
            "evaluation_role": "diagnostic",
            "publication_surface": "gate_diagnostics",
            "entry_mode": "immediate_close",
            "intended_horizon": None,
            "state": _manifest_list_state(report, "observation_watchlist"),
        },
        {
            "strategy": "next_day_boom",
            "name": "次日大涨策略",
            "version": "next-day-boom-close-v1",
            "source_pool": "next_day_boom",
            "evaluation_role": "research",
            "publication_surface": "research_review",
            "entry_mode": "immediate_close",
            "intended_horizon": 1,
            "state": _manifest_pool_state(report, "next_day_boom"),
        },
        {
            "strategy": "luojie_pool",
            "name": "罗姐主题策略",
            "version": "luojie-close-v1",
            "source_pool": "luojie_pool",
            "evaluation_role": "research",
            "publication_surface": "research_review",
            "entry_mode": "immediate_close",
            "intended_horizon": None,
            "state": (
                luojie_blocked_state
                or _manifest_pool_state(report, "luojie_pool")
            ),
            "blocking_reason": (
                _strategy_blocking_reason(report, "luojie_pool")
                if luojie_blocked_state else ""
            ),
        },
        {
            "strategy": "h4_t3",
            "name": "H4 T+3 策略",
            "version": str(
                h4_payload.get("strategy_version")
                or "unknown"
            ),
            "source_pool": "h4_t3_pool",
            "evaluation_role": "formal",
            "publication_surface": "formal_recommendation",
            "entry_mode": "immediate_close",
            "intended_horizon": 3,
            "state": (
                h4_blocked_state
                or _manifest_pool_state(
                    report, "h4_t3_pool", formal_h4=True
                )
            ),
            "source_candidate_count": len(
                h4_payload.get("candidates") or []
            ),
            "published_count": (
                0 if h4_blocked_state
                else len(h4_payload.get("candidates") or [])
            ),
            "blocking_reason": (
                _strategy_blocking_reason(report, "h4_t3")
                if h4_blocked_state else ""
            ),
        },
    ]
    manifest = []
    for spec in specs:
        row = dict(spec)
        status, count, reason = row.pop("state")
        row.update({
            "report_date": report_date,
            "run_status": status,
            "signal_count": count,
            "source_candidate_count": (
                row.get("source_candidate_count")
                if row.get("source_candidate_count") is not None
                else count
            ),
            "published_count": (
                row.get("published_count")
                if row.get("published_count") is not None
                else (count if row.get("strategy") == "h4_t3" else None)
            ),
            "reason": reason,
        })
        manifest.append(row)
    return manifest


def persist_review_benchmark_kline(
    db_path,
    kline,
    *,
    code=BENCHMARK_CODE,
    name="沪深300",
):
    """Persist a multi-source-verified index series as canonical final bars."""
    kline = kline if isinstance(kline, dict) else {}
    dates = _plain_list(kline.get("dates"))
    arrays = {
        key: _plain_list(kline.get(key))
        for key in ("opens", "closes", "highs", "lows", "volumes")
    }
    size = len(dates)
    if not size or any(len(values) != size for values in arrays.values()):
        raise ValueError("invalid benchmark kline")
    amounts = _plain_list(kline.get("amounts"))
    if len(amounts) != size:
        amounts = [0.0] * size
    bars = []
    for index, trade_date in enumerate(dates):
        amount = _finite(amounts[index])
        bars.append({
            "ts": str(trade_date).split(" ", 1)[0],
            "open": arrays["opens"][index],
            "close": arrays["closes"][index],
            "high": arrays["highs"][index],
            "low": arrays["lows"][index],
            "volume": arrays["volumes"][index],
            "amount": amount if amount is not None and amount >= 0 else 0.0,
            "adjustment": EXPECTED_ADJUSTMENT,
            "is_final": True,
            "source_batch": "verified_index_history",
        })
    with MarketHistoryStore(db_path) as store:
        instrument_id = store.upsert_instrument(
            "index", "SH", code, name
        )
        written = store.upsert_bars("day", instrument_id, bars)
    return {
        "status": "ok",
        "code": code,
        "bars": size,
        "rows_written": written,
        "latest_date": bars[-1]["ts"],
    }


def _exchange(code):
    code = str(code or "")
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    return ""


def load_review_market_context_from_store(db_path, entries, *, as_of=None):
    """Load stocks, an authoritative market calendar and fixed benchmark."""
    resolved_path = os.fspath(db_path)
    codes = sorted({
        str(entry.get("code") or "")
        for entry in entries or []
        if isinstance(entry, dict) and _exchange(entry.get("code"))
    })
    diagnostics = {
        "status": "missing",
        "requested_codes": len(codes),
        "resolved_codes": 0,
        "missing_codes": list(codes),
        "adjustment": "",
    }
    if not codes:
        diagnostics.update(status="empty", missing_codes=[])
        return {}, [], None, diagnostics
    if not os.path.exists(resolved_path):
        diagnostics["reason"] = "market_history_db_missing"
        return {}, [], None, diagnostics
    report_dates = sorted({
        str(entry.get("report_date") or "")
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("report_date")
    })
    start = report_dates[0] if report_dates else None
    try:
        with MarketHistoryStore(resolved_path, readonly=True) as store:
            adjustment = store.get_canonical_adjustment("day") or ""
            diagnostics["adjustment"] = adjustment
            if adjustment != EXPECTED_ADJUSTMENT:
                diagnostics.update(
                    status="adjustment_mismatch",
                    reason="canonical_adjustment_mismatch",
                )
                return {}, [], None, diagnostics
            identities = [(_exchange(code), code) for code in codes]
            instruments = store.resolve_instruments("stock", identities)
            by_id = {
                int(instrument["instrument_id"]): code
                for (exchange, code), instrument in instruments.items()
            }
            rows_by_id = store.query_bars_many(
                "day",
                sorted(by_id),
                start=start,
                end=as_of,
            )
            calendar_rows = store.connection.execute(
                """
                SELECT trade_date
                FROM trade_calendar
                WHERE is_open=1 AND trade_date>=?
                  AND (? IS NULL OR trade_date<=?)
                GROUP BY trade_date
                ORDER BY trade_date
                """,
                (start or "", as_of, as_of),
            ).fetchall()
            calendar_source = "trade_calendar"
            if not calendar_rows:
                calendar_rows = store.connection.execute(
                    """
                    SELECT substr(b.ts, 1, 10) AS trade_date
                    FROM bars_day b
                    JOIN instruments i ON i.instrument_id=b.instrument_id
                    WHERE i.asset_type='stock' AND b.is_final=1
                      AND substr(b.ts, 1, 10)>=?
                      AND (? IS NULL OR substr(b.ts, 1, 10)<=?)
                    GROUP BY substr(b.ts, 1, 10)
                    ORDER BY trade_date
                    """,
                    (start or "", as_of, as_of),
                ).fetchall()
                calendar_source = "canonical_stock_market_dates"
            benchmark_instrument = store.resolve_instrument(
                "index", "SH", "000300"
            )
            benchmark_rows = []
            if benchmark_instrument:
                benchmark_rows = store.query_bars(
                    "day",
                    int(benchmark_instrument["instrument_id"]),
                    start=start,
                    end=as_of,
                )
    except (OSError, ValueError, TypeError) as exc:
        diagnostics.update(
            status="error",
            reason="{}".format(type(exc).__name__),
        )
        return {}, [], None, diagnostics

    klines = {}
    for instrument_id, rows in rows_by_id.items():
        code = by_id.get(int(instrument_id))
        if not code or not rows:
            continue
        klines[code] = {
            "dates": [str(row.get("ts") or "").split(" ", 1)[0] for row in rows],
            "opens": [row.get("open") for row in rows],
            "closes": [row.get("close") for row in rows],
            "highs": [row.get("high") for row in rows],
            "lows": [row.get("low") for row in rows],
            "volumes": [row.get("volume") for row in rows],
            "is_final": [bool(row.get("is_final")) for row in rows],
            "adjustment": adjustment,
            "source": "market_history_db",
        }
    diagnostics.update(
        status="ok" if klines else "missing",
        resolved_codes=len(klines),
        missing_codes=sorted(set(codes) - set(klines)),
        calendar_source=calendar_source,
        calendar_days=len(calendar_rows),
        benchmark_status="ok" if benchmark_rows else "missing",
        benchmark_code="000300",
    )
    trading_calendar = [str(row["trade_date"]) for row in calendar_rows]
    benchmark_kline = None
    if benchmark_rows:
        benchmark_kline = {
            "dates": [
                str(row.get("ts") or "").split(" ", 1)[0]
                for row in benchmark_rows
            ],
            "opens": [row.get("open") for row in benchmark_rows],
            "closes": [row.get("close") for row in benchmark_rows],
            "highs": [row.get("high") for row in benchmark_rows],
            "lows": [row.get("low") for row in benchmark_rows],
            "volumes": [row.get("volume") for row in benchmark_rows],
            "is_final": [bool(row.get("is_final")) for row in benchmark_rows],
            "adjustment": adjustment,
            "source": "market_history_db",
            "code": "000300",
        }
    return klines, trading_calendar, benchmark_kline, diagnostics


def load_review_klines_from_store(db_path, entries, *, as_of=None):
    """Backward-compatible stock-bar loader used by focused callers."""
    klines, _calendar, _benchmark, diagnostics = (
        load_review_market_context_from_store(
            db_path, entries, as_of=as_of
        )
    )
    return klines, diagnostics


def _plain_list(value):
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _empty_outcome(entry, status):
    return {
        "recommendation_id": str(entry.get("recommendation_id") or ""),
        "code": str(entry.get("code") or ""),
        "name": str(entry.get("name") or ""),
        "report_date": str(entry.get("report_date") or ""),
        "status": status,
        "entry_date": "",
        "entry_price": None,
        "target_dates": {"t1": "", "t3": "", "t5": ""},
        "returns": {"t1": None, "t3": None, "t5": None},
        "mae": {"t1": None, "t3": None, "t5": None},
        "mfe": {"t1": None, "t3": None, "t5": None},
        "maturity": {
            "t1": "unavailable",
            "t3": "unavailable",
            "t5": "unavailable",
        },
        "benchmark_status": "not_requested",
        "benchmark_alignment": {
            "t1": "not_requested",
            "t3": "not_requested",
            "t5": "not_requested",
        },
        "excess_returns": {"t1": None, "t3": None, "t5": None},
    }


def _validated_kline(kline, expected_adjustment):
    if not isinstance(kline, dict):
        return None, "market_data_missing"
    adjustment = str(kline.get("adjustment") or "").strip()
    if adjustment != expected_adjustment:
        return None, "adjustment_mismatch"
    dates = [str(value).split(" ", 1)[0] for value in _plain_list(kline.get("dates"))]
    arrays = {
        key: [_finite(value) for value in _plain_list(kline.get(key))]
        for key in ("opens", "closes", "highs", "lows", "volumes")
    }
    size = len(dates)
    if not size or any(len(values) != size for values in arrays.values()):
        return None, "market_data_invalid"
    if any(
        value is None
        for key in ("opens", "closes", "highs", "lows")
        for value in arrays[key]
    ):
        return None, "market_data_invalid"
    if dates != sorted(set(dates)):
        return None, "market_data_invalid"
    finals = _plain_list(kline.get("is_final"))
    if len(finals) != size:
        return None, "market_data_invalid"
    return {
        "dates": dates,
        "opens": arrays["opens"],
        "closes": arrays["closes"],
        "highs": arrays["highs"],
        "lows": arrays["lows"],
        "volumes": arrays["volumes"],
        "is_final": [bool(value) for value in finals],
        "adjustment": adjustment,
    }, "ok"


def _entry_mode(entry, contribution=None):
    if isinstance(contribution, dict):
        return str(contribution.get("entry_mode") or "").strip() or "unknown"
    modes = {
        str(row.get("entry_mode") or "")
        for row in entry.get("strategy_contributions") or []
        if isinstance(row, dict) and (
            row.get("evaluation_eligible") is True
            or row.get("cohort_eligible") is True
        )
    }
    if len(modes) == 1:
        return next(iter(modes))
    return "unknown"


def _normalized_calendar(trading_calendar):
    dates = [
        str(value).split(" ", 1)[0]
        for value in _plain_list(trading_calendar)
        if str(value or "").strip()
    ]
    if not dates or dates != sorted(set(dates)):
        return None
    return dates


def _evaluate_without_benchmark(
    entry,
    kline,
    expected_adjustment,
    *,
    contribution=None,
    trading_calendar=None,
    validate_reference=True,
):
    outcome = _empty_outcome(entry, "market_data_missing")
    normalized, status = _validated_kline(kline, expected_adjustment)
    if normalized is None:
        outcome["status"] = status
        return outcome
    calendar = _normalized_calendar(trading_calendar)
    if calendar is None:
        outcome["status"] = "calendar_missing"
        return outcome
    report_date = str(entry.get("report_date") or "")
    try:
        report_calendar_index = calendar.index(report_date)
    except ValueError:
        outcome["status"] = "recommendation_calendar_missing"
        return outcome
    date_index = {
        trade_date: index
        for index, trade_date in enumerate(normalized["dates"])
    }
    report_index = date_index.get(report_date)
    if report_index is None:
        outcome["status"] = "recommendation_date_missing"
        return outcome
    if not normalized["is_final"][report_index]:
        outcome["status"] = "recommendation_not_final"
        return outcome
    mode = _entry_mode(entry, contribution)
    if mode == "unknown":
        outcome["status"] = "entry_mode_unknown"
        return outcome
    if mode not in {"delay1_open", "immediate_close"}:
        outcome["status"] = "unsupported_entry_mode"
        return outcome
    entry_calendar_index = (
        report_calendar_index + 1
        if mode == "delay1_open"
        else report_calendar_index
    )
    if entry_calendar_index >= len(calendar):
        outcome["status"] = "right_censored"
        outcome["maturity"] = {
            "t1": "right_censored",
            "t3": "right_censored",
            "t5": "right_censored",
        }
        return outcome
    entry_date = calendar[entry_calendar_index]
    entry_index = date_index.get(entry_date)
    if entry_index is None:
        outcome["status"] = "suspended_entry"
        return outcome
    if not normalized["is_final"][entry_index]:
        outcome["status"] = "right_censored"
        return outcome
    entry_volume = normalized["volumes"][entry_index]
    if entry_volume is None or entry_volume <= 0:
        outcome["status"] = "suspended_entry"
        return outcome
    entry_price = (
        normalized["opens"][entry_index]
        if mode == "delay1_open"
        else normalized["closes"][entry_index]
    )
    if entry_price is None or entry_price <= 0:
        outcome["status"] = "market_data_invalid"
        return outcome
    if mode == "immediate_close" and validate_reference:
        reference_adjustment = str(
            entry.get("reference_adjustment") or expected_adjustment
        ).strip()
        if reference_adjustment != expected_adjustment:
            outcome["status"] = "reference_adjustment_mismatch"
            return outcome
        reference_close = _finite(entry.get("reference_close"))
        if reference_close is None or reference_close <= 0:
            outcome["status"] = "reference_close_missing"
            return outcome
        if not math.isclose(
            entry_price,
            reference_close,
            rel_tol=1e-9,
            abs_tol=1e-8,
        ):
            outcome["status"] = "reference_close_mismatch"
            return outcome
    if mode == "delay1_open":
        previous_close = normalized["closes"][report_index]
        one_price = (
            normalized["opens"][entry_index]
            == normalized["closes"][entry_index]
            == normalized["highs"][entry_index]
            == normalized["lows"][entry_index]
        )
        locked_move = (
            entry_price / previous_close - 1.0 >= 0.048
            if previous_close and previous_close > 0 else False
        )
        if one_price and locked_move:
            outcome["status"] = "limit_locked_entry"
            return outcome

    outcome["entry_date"] = entry_date
    outcome["entry_price"] = entry_price
    maturity = {}
    returns = {}
    target_dates = {}
    mae = {}
    mfe = {}
    for horizon in HORIZONS:
        key = "t{}".format(horizon)
        target_calendar_index = report_calendar_index + horizon
        if target_calendar_index >= len(calendar):
            target_dates[key] = ""
            maturity[key] = "right_censored"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        target_date = calendar[target_calendar_index]
        target_dates[key] = target_date
        endpoint = date_index.get(target_date)
        if endpoint is None:
            maturity[key] = "unavailable"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        if not normalized["is_final"][endpoint]:
            maturity[key] = "right_censored"
            returns[key] = None
            mae[key] = None
            mfe[key] = None
            continue
        if mode == "immediate_close":
            target_volume = normalized["volumes"][endpoint]
            if target_volume is None or target_volume <= 0:
                maturity[key] = "unavailable"
                returns[key] = None
                mae[key] = None
                mfe[key] = None
                continue
        maturity[key] = "mature"
        returns[key] = (
            (normalized["closes"][endpoint] - entry_price)
            / entry_price * 100.0
        )
        # The immediate-close research contract starts its excursion window
        # at D+1.  In particular, a signal-day intraday high/low can never
        # inflate MFE or MAE.  The legacy next-open contract still starts at
        # its entry day, preserving the existing output byte-for-byte.
        path_start = (
            report_calendar_index + 1
            if mode == "immediate_close"
            else entry_calendar_index
        )
        path_dates = calendar[path_start:target_calendar_index + 1]
        path_indexes = [
            date_index[trade_date]
            for trade_date in path_dates
            if trade_date in date_index
            and normalized["is_final"][date_index[trade_date]]
        ]
        complete_path = len(path_indexes) == len(path_dates)
        if mode == "immediate_close" and complete_path:
            complete_path = all(
                normalized["volumes"][index] is not None
                and normalized["volumes"][index] > 0
                for index in path_indexes
            )
        mae[key] = (
            (min(normalized["lows"][index] for index in path_indexes)
             - entry_price) / entry_price * 100.0
            if path_indexes and (mode != "immediate_close" or complete_path)
            else None
        )
        mfe[key] = (
            (max(normalized["highs"][index] for index in path_indexes)
             - entry_price) / entry_price * 100.0
            if path_indexes and (mode != "immediate_close" or complete_path)
            else None
        )
    outcome["target_dates"] = target_dates
    outcome["returns"] = returns
    outcome["mae"] = mae
    outcome["mfe"] = mfe
    outcome["maturity"] = maturity
    if maturity["t5"] == "mature":
        outcome["status"] = "evaluated"
    elif any(value == "mature" for value in maturity.values()):
        outcome["status"] = "partial"
    else:
        outcome["status"] = "right_censored"
    return outcome


def evaluate_recommendation_entry(
    entry,
    kline,
    *,
    contribution=None,
    trading_calendar=None,
    benchmark_kline=None,
    expected_adjustment=EXPECTED_ADJUSTMENT,
):
    """Evaluate one record under next-open or signal-close research rules."""
    entry = entry if isinstance(entry, dict) else {}
    outcome = _evaluate_without_benchmark(
        entry,
        kline,
        expected_adjustment,
        contribution=contribution,
        trading_calendar=trading_calendar,
    )
    if benchmark_kline is None:
        return outcome
    benchmark = _evaluate_without_benchmark(
        entry,
        benchmark_kline,
        expected_adjustment,
        contribution=contribution,
        trading_calendar=trading_calendar,
        validate_reference=False,
    )
    if (
        benchmark.get("status") not in {"evaluated", "partial"}
        or benchmark.get("entry_date") != outcome.get("entry_date")
    ):
        outcome["benchmark_status"] = "unaligned"
        outcome["benchmark_alignment"] = {
            key: "unaligned" for key in ("t1", "t3", "t5")
        }
        return outcome
    alignment = {}
    excess = {}
    for key in ("t1", "t3", "t5"):
        if outcome["returns"].get(key) is None:
            alignment[key] = "unavailable"
            excess[key] = None
        elif (
            benchmark["returns"].get(key) is not None
            and benchmark["target_dates"].get(key)
            == outcome["target_dates"].get(key)
        ):
            alignment[key] = "aligned"
            excess[key] = (
                outcome["returns"][key] - benchmark["returns"][key]
            )
        else:
            alignment[key] = "unaligned"
            excess[key] = None
    outcome["benchmark_alignment"] = alignment
    aligned_count = sum(value == "aligned" for value in alignment.values())
    outcome["benchmark_status"] = (
        "aligned" if aligned_count == len(HORIZONS)
        else ("partial" if aligned_count else "unaligned")
    )
    outcome["excess_returns"] = excess
    return outcome


def _reason_summary(contribution):
    snapshot = contribution.get("reason_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    decision = snapshot.get("decision_engine_v1")
    decision = decision if isinstance(decision, dict) else {}
    best_buy = snapshot.get("best_buy_point")
    best_buy = best_buy if isinstance(best_buy, dict) else {}
    parts = [
        str(decision.get("decision") or "").strip(),
        str(best_buy.get("type") or "").strip(),
        str(best_buy.get("reason") or "").strip(),
    ]
    return " · ".join(part for part in parts if part) or "推荐理由未知"


def _representative_samples(samples, *, contracted):
    if not samples:
        return []
    if not contracted:
        return sorted(
            samples,
            key=lambda row: (
                str(row.get("rec_date") or ""),
                str(row.get("recommendation_id") or ""),
            ),
            reverse=True,
        )[:3]
    ordered = sorted(samples, key=lambda row: (
        row.get("return_pct") is None,
        row.get("return_pct") if row.get("return_pct") is not None else 0,
        row.get("recommendation_id"),
    ))
    indexes = [0, len(ordered) // 2, len(ordered) - 1]
    selected = []
    seen = set()
    for index in indexes:
        row = ordered[index]
        key = row.get("recommendation_id")
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected[:3]


def _episode_rows(rows, trading_calendar):
    calendar = _normalized_calendar(trading_calendar) or []
    date_index = {value: index for index, value in enumerate(calendar)}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["entry"]["code"]].append(row)
    episodes = []
    for code in sorted(grouped):
        ordered = sorted(
            grouped[code],
            key=lambda row: (
                row["entry"]["report_date"],
                row["contribution"].get("contribution_id") or "",
            ),
        )
        previous_index = None
        previous_date = None
        for row in ordered:
            current_date = row["entry"]["report_date"]
            if current_date == previous_date:
                continue
            current_index = date_index.get(current_date)
            if (
                previous_index is not None
                and current_index is not None
                and current_index == previous_index + 1
            ):
                previous_index = current_index
                previous_date = current_date
                continue
            episodes.append(row)
            previous_index = current_index
            previous_date = current_date
    return episodes


def _normalized_horizon(value):
    if isinstance(value, bool):
        return None
    try:
        horizon = int(value)
    except (TypeError, ValueError):
        return None
    return horizon if horizon in HORIZONS else None


def _research_tier(contribution, *, legacy=False):
    value = str((contribution or {}).get("research_tier") or "").strip()
    if value:
        return value
    return _LEGACY_RESEARCH_TIER if legacy else _DEFAULT_RESEARCH_TIER


def _legacy_role_for(contribution):
    strategy = str(contribution.get("strategy_name") or "unknown")
    version = str(contribution.get("strategy_version") or "unknown")
    source_pool = str(contribution.get("source_pool") or "")
    return _LEGACY_ROLE_REGISTRY.get((strategy, version, source_pool))


def _classify_scorecard_contribution(contribution):
    """Return a frozen role view or a fail-closed classification reason."""
    if not isinstance(contribution, dict):
        return None
    role_field_present = "evaluation_role" in contribution
    requested_role = str(contribution.get("evaluation_role") or "").strip().lower()
    legacy_role = _legacy_role_for(contribution)
    if role_field_present and requested_role not in _SCORECARD_ROLES:
        return {"failure_reason": "evaluation_role_invalid"}
    if role_field_present and legacy_role and requested_role != legacy_role:
        return {"failure_reason": "evaluation_role_conflict"}
    if role_field_present:
        role = requested_role
        classification_status = "explicit"
    else:
        role = legacy_role
        if role not in _SCORECARD_ROLES:
            return {"failure_reason": "legacy_identity_unknown"}
        classification_status = "legacy_corrected"

    surface = str(contribution.get("publication_surface") or "").strip().lower()
    if surface != _SURFACE_BY_ROLE[role]:
        surface = _SURFACE_BY_ROLE[role]
    if role == "diagnostic":
        evaluation_eligible = False
        eligibility_reason = "diagnostic_only"
    elif classification_status == "legacy_corrected":
        evaluation_eligible = role in {"formal", "baseline", "research"}
        eligibility_reason = "legacy_{}".format(role)
    elif isinstance(contribution.get("evaluation_eligible"), bool):
        evaluation_eligible = contribution["evaluation_eligible"]
        eligibility_reason = str(
            contribution.get("eligibility_reason")
            or ("eligible" if evaluation_eligible else "ineligible")
        )
    else:
        # A role is explicit but an older writer omitted the bool.  Formal
        # still requires its immutable cohort gate; baseline/research rows
        # represent their own selected signals; diagnostics never evaluate.
        evaluation_eligible = (
            bool(contribution.get("cohort_eligible"))
            if role == "formal"
            else role in {"baseline", "research"}
        )
        eligibility_reason = (
            "formal_recommendation"
            if evaluation_eligible and role == "formal"
            else ("{}_candidate".format(role) if evaluation_eligible else "ineligible")
        )
    if role == "formal":
        # A baseline/research flag must never promote a contribution into the
        # formal recommendation denominator.
        evaluation_eligible = bool(
            evaluation_eligible and contribution.get("cohort_eligible") is True
        )
        if not evaluation_eligible and eligibility_reason == "eligible":
            eligibility_reason = "formal_cohort_ineligible"
    return {
        "evaluation_role": role,
        "publication_surface": surface,
        "evaluation_eligible": bool(evaluation_eligible),
        "eligibility_reason": eligibility_reason,
        "classification_status": classification_status,
    }


def _empty_horizon_metrics():
    return {
        "n": 0,
        "date_start": None,
        "date_end": None,
        "mean": None,
        "median": None,
        "excess_mean": None,
        "excess_n": 0,
        "win_rate": None,
        "win_rate_n": 0,
        "hit_rate_ge_5": None,
        "hit_rate_ge_5_n": 0,
        "period_high": None,
        "period_high_n": 0,
        "period_low": None,
        "period_low_n": 0,
        # Explicit aliases keep the serialized contract self-describing for
        # older consumers that used MAE/MFE terminology.
        "mean_return": None,
        "median_return": None,
        "mean_excess_return": None,
        "mean_mfe": None,
        "mean_mae": None,
        "max_drawdown": None,
        "mfe_n": 0,
        "mae_n": 0,
    }


def _horizon_metrics(outcomes, key, *, publishable=True):
    if not publishable:
        return _empty_horizon_metrics()
    returns = [
        _finite(outcome.get("returns", {}).get(key))
        for outcome in outcomes
    ]
    returns = [value for value in returns if value is not None]
    excess = [
        _finite(outcome.get("excess_returns", {}).get(key))
        for outcome in outcomes
    ]
    excess = [value for value in excess if value is not None]
    highs = [
        _finite(outcome.get("mfe", {}).get(key))
        for outcome in outcomes
    ]
    highs = [value for value in highs if value is not None]
    lows = [
        _finite(outcome.get("mae", {}).get(key))
        for outcome in outcomes
    ]
    lows = [value for value in lows if value is not None]
    mature_dates = sorted({
        str(outcome.get("report_date") or "")
        for outcome in outcomes
        if _finite(outcome.get("returns", {}).get(key)) is not None
        and outcome.get("report_date")
    })
    metrics = _empty_horizon_metrics()
    metrics.update({
        "n": len(returns),
        "date_start": mature_dates[0] if mature_dates else None,
        "date_end": mature_dates[-1] if mature_dates else None,
        "mean": mean(returns) if returns else None,
        "median": median(returns) if returns else None,
        "excess_mean": mean(excess) if excess else None,
        "excess_n": len(excess),
        "win_rate": (
            sum(value > 0 for value in returns) / len(returns) * 100.0
            if returns else None
        ),
        "win_rate_n": len(returns),
        "hit_rate_ge_5": (
            sum(value >= 5.0 for value in returns) / len(returns) * 100.0
            if returns else None
        ),
        "hit_rate_ge_5_n": len(returns),
        "period_high": mean(highs) if highs else None,
        "period_high_n": len(highs),
        "period_low": mean(lows) if lows else None,
        "period_low_n": len(lows),
        "mean_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None,
        "mean_excess_return": mean(excess) if excess else None,
        "mean_mfe": mean(highs) if highs else None,
        "mean_mae": mean(lows) if lows else None,
        # Worst observed adverse excursion across the mature cohort.  This is
        # deliberately distinct from mean MAE and does not invent a portfolio
        # equity curve for overlapping recommendations.
        "max_drawdown": min(lows) if lows else None,
        "mfe_n": len(highs),
        "mae_n": len(lows),
    })
    return metrics


def _comparison_progress(*, maturity, active_dates, active_months, status):
    return {
        "status": status,
        "mature_samples": int((maturity or {}).get("mature") or 0),
        "waiting_samples": int((maturity or {}).get("waiting") or 0),
        "unavailable_samples": int((maturity or {}).get("unavailable") or 0),
        "required_mature_samples": SCORECARD_THRESHOLDS["mature_samples"],
        "active_dates": int(active_dates or 0),
        "required_active_dates": SCORECARD_THRESHOLDS["active_dates"],
        "active_months": int(active_months or 0),
        "required_calendar_months": SCORECARD_THRESHOLDS["calendar_months"],
    }


def _maturity_by_horizon(outcomes):
    result = {}
    for horizon in HORIZONS:
        key = "t{}".format(horizon)
        counts = {"mature": 0, "waiting": 0, "unavailable": 0}
        for outcome in outcomes:
            state = outcome.get("maturity", {}).get(key)
            if state == "mature":
                counts["mature"] += 1
            elif state in {"right_censored", "waiting"}:
                counts["waiting"] += 1
            else:
                counts["unavailable"] += 1
        result[key] = counts
    return result


def _horizon_readiness(
    *,
    maturity,
    key,
    metrics_publishable,
    metrics_blocking_reasons,
    active_dates,
    active_months,
):
    """Return the readiness state for one horizon, never another horizon."""
    if metrics_blocking_reasons or not metrics_publishable:
        return "data_unavailable"
    state = maturity.get(key) or {}
    mature = int(state.get("mature") or 0)
    waiting = int(state.get("waiting") or 0)
    if mature == 0 and waiting > 0:
        return "waiting_for_maturity"
    if mature == 0:
        return "data_unavailable"
    if (
        mature >= SCORECARD_THRESHOLDS["mature_samples"]
        and active_dates >= SCORECARD_THRESHOLDS["active_dates"]
        and active_months >= SCORECARD_THRESHOLDS["calendar_months"]
    ):
        return "ready_for_manual_comparison"
    return "collecting"


def _card_evaluation_status(
    *,
    role,
    signal_count,
    eligible_signal_count,
    maturity,
    metrics_publishable,
    metrics_blocking_reasons,
    active_dates,
    active_months,
    intended_horizon=None,
):
    if signal_count == 0:
        return "no_signals"
    if eligible_signal_count == 0:
        incident_blockers = {
            "strategy_input_stale_or_unverified",
            "strategy_upstream_contract_mismatch",
        }
        if incident_blockers & set(metrics_blocking_reasons or []):
            return "data_unavailable"
        return (
            "no_formal_recommendations"
            if role == "formal"
            else "contract_missing"
        )
    if metrics_blocking_reasons:
        return "data_unavailable"
    if not metrics_publishable:
        return "data_unavailable"
    # A card without a declared primary horizon cannot claim a single
    # overall readiness state.  Its per-horizon map is the authoritative
    # result; keep the card itself in the accumulating state.
    if intended_horizon is None:
        return "collecting"
    return _horizon_readiness(
        maturity=maturity,
        key="t{}".format(intended_horizon),
        metrics_publishable=metrics_publishable,
        metrics_blocking_reasons=metrics_blocking_reasons,
        active_dates=active_dates,
        active_months=active_months,
    )


def _card_representative_samples(rows, outcomes, *, primary_horizon):
    samples = []
    for row, outcome in zip(rows, outcomes):
        returns = dict(outcome.get("returns") or {})
        primary_key = "t{}".format(primary_horizon) if primary_horizon else None
        primary_return = returns.get(primary_key) if primary_key else None
        if primary_return is None and not any(value is not None for value in returns.values()):
            continue
        samples.append({
            "recommendation_id": row["entry"].get("recommendation_id"),
            "rec_date": row["entry"].get("report_date"),
            "code": row["entry"].get("code"),
            "name": row["entry"].get("name"),
            "strategy": row["card_strategy"],
            "strategy_version": row["card_version"],
            "source_pool": row["card_source_pool"],
            "return_pct": primary_return,
            "returns": returns,
            "excess_returns": dict(outcome.get("excess_returns") or {}),
            "outcome_label": (
                "T+{} {:+.2f}%".format(primary_horizon, primary_return)
                if primary_return is not None
                else "逐周期结果"
            ),
            "reason_summary": _reason_summary(row["contribution"]),
            "entry_date": outcome.get("entry_date"),
            "entry_price": outcome.get("entry_price"),
        })
    return _representative_samples(
        samples,
        contracted=primary_horizon is not None,
    )


def build_strategy_scorecards(
    entries,
    kline_by_code,
    *,
    trading_calendar=None,
    benchmark_kline=None,
    expected_adjustment=EXPECTED_ADJUSTMENT,
    run_manifest=None,
    sample_exclusions=None,
):
    """Build schema-v2 scorecards with explicit role and horizon semantics."""
    entries = [entry for entry in entries or [] if isinstance(entry, dict)]
    cards = {}
    classification_failures = []
    exclusions = (
        load_strategy_sample_exclusions()
        if sample_exclusions is None else list(sample_exclusions)
    )

    def empty_card(
        *, role, strategy, version, source_pool, entry_mode,
        intended_horizon, research_tier, publication_surface,
    ):
        return {
            "evaluation_role": role,
            "publication_surface": publication_surface,
            "strategy": strategy,
            "version": version,
            "source_pool": source_pool,
            "entry_mode": entry_mode,
            "intended_horizon": intended_horizon,
            "research_tier": research_tier,
            "display_names": Counter(),
            "attribution_statuses": Counter(),
            "classification_statuses": Counter(),
            "gate_outcomes": Counter(),
            "publication_outcomes": Counter(),
            "all_rows": [],
            "eligible_rows": [],
            "sample_exclusions": Counter(),
            "latest_run_status": "",
            "latest_run_reason": "",
            "latest_run_blocking_reason": "",
            "latest_signal_count": None,
            "latest_source_candidate_count": None,
            "latest_published_count": None,
            "latest_report_date": "",
        }

    for item in run_manifest or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("evaluation_role") or "").strip()
        if role not in _SCORECARD_ROLES:
            continue
        strategy = str(item.get("strategy") or "unknown").strip() or "unknown"
        version = str(item.get("version") or "unknown").strip() or "unknown"
        source_pool = str(item.get("source_pool") or "unknown").strip() or "unknown"
        entry_mode = str(item.get("entry_mode") or "unknown").strip() or "unknown"
        intended_horizon = _normalized_horizon(item.get("intended_horizon"))
        research_tier = _research_tier(item)
        key = (
            role, strategy, version, source_pool, entry_mode,
            intended_horizon, research_tier,
        )
        card = cards.setdefault(key, empty_card(
            role=role,
            strategy=strategy,
            version=version,
            source_pool=source_pool,
            entry_mode=entry_mode,
            intended_horizon=intended_horizon,
            research_tier=research_tier,
            publication_surface=_SURFACE_BY_ROLE[role],
        ))
        card["display_names"][str(item.get("name") or strategy)] += 1
        card["latest_run_status"] = str(
            item.get("run_status") or "unavailable"
        )
        card["latest_run_reason"] = str(item.get("reason") or "")
        card["latest_run_blocking_reason"] = str(
            item.get("blocking_reason") or ""
        )
        card["latest_signal_count"] = int(item.get("signal_count") or 0)
        card["latest_source_candidate_count"] = int(
            item.get("source_candidate_count") or 0
        )
        published_count = item.get("published_count")
        card["latest_published_count"] = (
            int(published_count) if published_count is not None else None
        )
        card["latest_report_date"] = str(item.get("report_date") or "")

    for entry in entries:
        for contribution in entry.get("strategy_contributions") or []:
            if not isinstance(contribution, dict):
                continue
            classification = _classify_scorecard_contribution(contribution)
            strategy = str(contribution.get("strategy_name") or "unknown")
            version = str(contribution.get("strategy_version") or "unknown")
            source_pool = str(contribution.get("source_pool") or "unknown")
            if not classification or classification.get("failure_reason"):
                classification_failures.append({
                    "strategy": strategy,
                    "version": version,
                    "source_pool": source_pool,
                    "reason": (
                        classification.get("failure_reason")
                        if classification else "legacy_identity_unknown"
                    ),
                    "recommendation_id": entry.get("recommendation_id"),
                })
                continue
            role = classification["evaluation_role"]
            entry_mode = str(
                contribution.get("entry_mode") or "unknown"
            ).strip() or "unknown"
            intended_horizon = _normalized_horizon(
                contribution.get("intended_horizon")
            )
            research_tier = _research_tier(
                contribution,
                legacy=classification["classification_status"] == "legacy_corrected",
            )
            key = (
                role,
                strategy,
                version,
                source_pool,
                entry_mode,
                intended_horizon,
                research_tier,
            )
            card = cards.setdefault(key, empty_card(
                role=role,
                strategy=strategy,
                version=version,
                source_pool=source_pool,
                entry_mode=entry_mode,
                intended_horizon=intended_horizon,
                research_tier=research_tier,
                publication_surface=classification["publication_surface"],
            ))
            card["display_names"][
                str(contribution.get("display_name") or strategy)
            ] += 1
            card["attribution_statuses"][
                str(contribution.get("attribution_status") or "legacy_unknown")
            ] += 1
            card["classification_statuses"][
                classification["classification_status"]
            ] += 1
            card["gate_outcomes"][
                str(contribution.get("decision_code") or "unknown")
            ] += 1
            card["publication_outcomes"][
                str(contribution.get("user_action") or "unknown")
            ] += 1
            row = {
                "entry": entry,
                "contribution": contribution,
                "card_strategy": strategy,
                "card_version": version,
                "card_source_pool": source_pool,
                "classification": classification,
            }
            card["all_rows"].append(row)
            exclusion = (
                _sample_exclusion(entry, contribution, exclusions)
                if classification["evaluation_eligible"] else None
            )
            if exclusion:
                card["sample_exclusions"][
                    (exclusion["incident_id"], exclusion["reason"])
                ] += 1
            elif classification["evaluation_eligible"]:
                card["eligible_rows"].append(row)

    sections = {"formal": [], "baselines": [], "research": [], "gates": []}
    for key in sorted(
        cards,
        key=lambda value: (
            value[0], value[1], value[2], value[3], value[4],
            -1 if value[5] is None else value[5], value[6],
        ),
    ):
        card = cards[key]
        role = card["evaluation_role"]
        display_name = sorted(
            card["display_names"],
            key=lambda value: (-card["display_names"][value], value),
        )[0]
        classification_statuses = dict(card["classification_statuses"])
        classification_status = (
            next(iter(classification_statuses))
            if len(classification_statuses) == 1
            else ("mixed" if classification_statuses else "run_manifest")
        )
        evidence_tier = (
            "prospective_ledger"
            if set(classification_statuses) == {"explicit"}
            else (
                "legacy_inferred"
                if set(classification_statuses) == {"legacy_corrected"}
                else ("mixed_identity" if classification_statuses else "run_manifest")
            )
        )
        ledger_dates = sorted({
            str(row["entry"].get("report_date") or "")
            for row in card["all_rows"]
            if row["entry"].get("report_date")
        })
        evaluation_contract_signal_count = sum(
            1 for row in card["all_rows"]
            if row["classification"].get("evaluation_eligible") is True
        )
        base = {
            "evaluation_role": role,
            "publication_surface": card["publication_surface"],
            "strategy": card["strategy"],
            "name": display_name,
            "version": card["version"],
            "source_pool": card["source_pool"],
            "entry_mode": card["entry_mode"],
            "intended_horizon": card["intended_horizon"],
            "research_tier": card["research_tier"],
            "comparison_identity": {
                "strategy": card["strategy"],
                "version": card["version"],
                "source_pool": card["source_pool"],
                "entry_mode": card["entry_mode"],
                "intended_horizon": card["intended_horizon"],
                "research_tier": card["research_tier"],
            },
            "classification_status": classification_status,
            "classification_status_counts": classification_statuses,
            "signal_count": len(card["all_rows"]),
            "evaluation_contract_signal_count": (
                evaluation_contract_signal_count
            ),
            "non_evaluation_signal_count": (
                len(card["all_rows"]) - evaluation_contract_signal_count
            ),
            "eligible_signal_count": len(card["eligible_rows"]),
            "excluded_signal_count": sum(card["sample_exclusions"].values()),
            "ledger_active_dates": len(ledger_dates),
            "ledger_date_start": ledger_dates[0] if ledger_dates else "",
            "ledger_date_end": ledger_dates[-1] if ledger_dates else "",
            "sample_exclusions": [
                {
                    "incident_id": incident_id,
                    "reason": reason,
                    "count": count,
                }
                for (incident_id, reason), count
                in sorted(card["sample_exclusions"].items())
            ],
            "gate_outcomes": dict(card["gate_outcomes"]),
            "publication_outcomes": dict(card["publication_outcomes"]),
            "attribution_status_counts": dict(card["attribution_statuses"]),
            "attribution_status": (
                next(iter(card["attribution_statuses"]))
                if len(card["attribution_statuses"]) == 1
                else ("mixed" if card["attribution_statuses"] else "run_manifest")
            ),
            "evidence_tier": evidence_tier,
            "latest_run_status": card["latest_run_status"] or "unrecorded",
            "latest_run_reason": card["latest_run_reason"],
            "latest_run_blocking_reason": card[
                "latest_run_blocking_reason"
            ],
            "latest_signal_count": card["latest_signal_count"],
            "latest_source_candidate_count": card[
                "latest_source_candidate_count"
            ],
            "latest_published_count": card["latest_published_count"],
            "latest_report_date": card["latest_report_date"],
        }
        if role == "diagnostic":
            # Gate diagnostics are intentionally not passed through the return
            # evaluator.  The absence of return keys is part of their contract.
            if card["all_rows"]:
                gate_status = "running"
            elif card["latest_run_status"] == "disabled":
                gate_status = "disabled"
            elif card["latest_run_status"] == "unavailable":
                gate_status = "data_unavailable"
            else:
                gate_status = "normal_empty"
            base.update({
                "evaluation_status": gate_status,
                "gate_status": gate_status,
                "evaluation_statuses": {},
            })
            sections["gates"].append(base)
            continue

        eligible_rows = _episode_rows(card["eligible_rows"], trading_calendar)
        outcomes = []
        status_counts = Counter()
        for row in eligible_rows:
            entry = row["entry"]
            outcome = evaluate_recommendation_entry(
                entry,
                (kline_by_code or {}).get(str(entry.get("code") or "")),
                contribution=row["contribution"],
                trading_calendar=trading_calendar,
                benchmark_kline=benchmark_kline,
                expected_adjustment=expected_adjustment,
            )
            outcomes.append(outcome)
            status_counts[outcome.get("status") or "unknown"] += 1

        maturity = _maturity_by_horizon(outcomes)
        reference_missing = sum(
            1
            for row in card["eligible_rows"]
            if card["entry_mode"] == "immediate_close"
            and (_finite(row["entry"].get("reference_close")) or 0) <= 0
        )
        metrics_blocking_reasons = []
        if not card["all_rows"]:
            metrics_blocking_reasons.append("no_signals")
        elif not card["eligible_rows"]:
            incident_reasons = sorted({
                reason for (_incident_id, reason) in card["sample_exclusions"]
            })
            metrics_blocking_reasons.extend(
                incident_reasons or ["no_eligible_signals"]
            )
        if role == "research" and reference_missing:
            metrics_blocking_reasons.append("reference_close_missing")
        if not metrics_blocking_reasons and outcomes and not any(
            maturity[key_name]["mature"] or maturity[key_name]["waiting"]
            for key_name in ("t1", "t3", "t5")
        ):
            metrics_blocking_reasons.append("market_data_unavailable")
        metrics_publishable = not metrics_blocking_reasons
        raw_metrics = {
            key_name: _horizon_metrics(
                outcomes,
                key_name,
                publishable=metrics_publishable,
            )
            for key_name in ("t1", "t3", "t5")
        }
        active_dates = len({
            str(row["entry"].get("report_date") or "")
            for row in card["eligible_rows"]
            if row["entry"].get("report_date")
        })
        active_months = len({
            str(row["entry"].get("report_date") or "")[:7]
            for row in card["eligible_rows"]
            if row["entry"].get("report_date")
        })
        mature_dates_by_horizon = {
            key_name: sorted({
                str(outcome.get("report_date") or "")
                for outcome in outcomes
                if outcome.get("maturity", {}).get(key_name) == "mature"
                and outcome.get("report_date")
            })
            for key_name in ("t1", "t3", "t5")
        }
        mature_active_dates = {
            key_name: len(values)
            for key_name, values in mature_dates_by_horizon.items()
        }
        mature_active_months = {
            key_name: len({value[:7] for value in values})
            for key_name, values in mature_dates_by_horizon.items()
        }
        primary_horizon = card["intended_horizon"]
        primary_key = "t{}".format(primary_horizon) if primary_horizon else None
        evaluation_status = _card_evaluation_status(
            role=role,
            signal_count=len(card["all_rows"]),
            eligible_signal_count=len(card["eligible_rows"]),
            maturity=maturity,
            metrics_publishable=metrics_publishable,
            metrics_blocking_reasons=metrics_blocking_reasons,
            active_dates=(
                mature_active_dates.get(primary_key, 0)
                if primary_key else active_dates
            ),
            active_months=(
                mature_active_months.get(primary_key, 0)
                if primary_key else active_months
            ),
            intended_horizon=card["intended_horizon"],
        )
        if not card["all_rows"]:
            if card["latest_run_status"] == "disabled":
                evaluation_status = "disabled"
            elif card["latest_run_status"] == "unavailable":
                evaluation_status = "data_unavailable"
                metrics_blocking_reasons = [
                    card["latest_run_blocking_reason"]
                    or "strategy_input_stale_or_unverified"
                ]
                metrics_publishable = False
                raw_metrics = {
                    key_name: _horizon_metrics(
                        outcomes,
                        key_name,
                        publishable=False,
                    )
                    for key_name in ("t1", "t3", "t5")
                }
        horizon_readiness = {
            key_name: _horizon_readiness(
                maturity=maturity,
                key=key_name,
                metrics_publishable=metrics_publishable,
                metrics_blocking_reasons=metrics_blocking_reasons,
                active_dates=mature_active_dates[key_name],
                active_months=mature_active_months[key_name],
            )
            for key_name in ("t1", "t3", "t5")
        }
        comparison_progress = {
            key_name: _comparison_progress(
                maturity=maturity[key_name],
                active_dates=mature_active_dates[key_name],
                active_months=mature_active_months[key_name],
                status=horizon_readiness[key_name],
            )
            for key_name in ("t1", "t3", "t5")
        }
        # The public scorecard deliberately withholds every return conclusion
        # until the exact comparison cohort passes all three maturity gates.
        # Maturity counts remain available through comparison_progress.
        metrics = {
            key_name: (
                raw_metrics[key_name]
                if horizon_readiness[key_name] == "ready_for_manual_comparison"
                else {}
            )
            for key_name in ("t1", "t3", "t5")
        }
        returns = {
            key_name: metrics[key_name].get("mean")
            for key_name in metrics
        }
        median_returns = {
            key_name: metrics[key_name].get("median")
            for key_name in metrics
        }
        excess_values = {
            key_name: [
                _finite(outcome.get("excess_returns", {}).get(key_name))
                for outcome in outcomes
                if _finite(outcome.get("excess_returns", {}).get(key_name)) is not None
            ]
            if horizon_readiness[key_name] == "ready_for_manual_comparison"
            else []
            for key_name in ("t1", "t3", "t5")
        }
        excess_returns = {
            key_name: metrics[key_name].get("excess_mean")
            for key_name in excess_values
        }
        win_rates = {
            key_name: metrics[key_name].get("win_rate") for key_name in metrics
        }
        excursions = {
            "mae": {
                key_name: metrics[key_name].get("mean_mae")
                for key_name in metrics
            },
            "mfe": {
                key_name: metrics[key_name].get("mean_mfe")
                for key_name in metrics
            },
        }
        evaluable_episode_count = (
            sum(
                any(value is not None for value in outcome.get("returns", {}).values())
                for outcome in outcomes
            )
            if metrics_publishable else 0
        )
        base.update({
            "active_dates": active_dates,
            "active_months": active_months,
            "episode_count": len(eligible_rows),
            "evaluable_episode_count": evaluable_episode_count,
            "sample_size": (
                raw_metrics[primary_key]["n"] if primary_key else None
            ),
            "matured_by_horizon": {
                key_name: raw_metrics[key_name]["n"]
                for key_name in raw_metrics
            },
            "maturity_by_horizon": maturity,
            "horizon_readiness": horizon_readiness,
            "comparison_progress_by_horizon": comparison_progress,
            "comparison_metrics_publishable_by_horizon": {
                key_name: (
                    horizon_readiness[key_name]
                    == "ready_for_manual_comparison"
                )
                for key_name in horizon_readiness
            },
            "metrics_by_horizon": metrics,
            "metrics_publishable": metrics_publishable,
            "metrics_blocking_reasons": metrics_blocking_reasons,
            "evaluation_status": evaluation_status,
            "evaluation_statuses": dict(status_counts),
            "evidence_tier": evidence_tier,
            "overall_verdict": None,
            # Compatibility fields for the pre-v2 reader.  New renderers use
            # metrics_by_horizon and never infer a primary horizon from them.
            "returns": returns,
            "median_returns": median_returns,
            "excess_returns": excess_returns,
            "median_excess_returns": {
                key_name: (
                    median(excess_values[key_name]) if excess_values[key_name] else None
                )
                for key_name in excess_values
            },
            "excursions": excursions,
            "win_rates": win_rates,
            "win_rate": win_rates[primary_key] if primary_key else None,
            "representative_samples": (
                _card_representative_samples(
                    eligible_rows,
                    outcomes,
                    primary_horizon=primary_horizon,
                )
                if (
                    primary_key
                    and horizon_readiness[primary_key]
                    == "ready_for_manual_comparison"
                ) else []
            ),
        })
        sections[_SECTION_BY_ROLE[role]].append(base)

    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "thresholds": dict(SCORECARD_THRESHOLDS),
        "formal": sections["formal"],
        "baselines": sections["baselines"],
        "research": sections["research"],
        "gates": sections["gates"],
        "classification_failures": classification_failures,
    }
