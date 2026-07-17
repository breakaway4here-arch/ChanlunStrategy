"""Fail-closed ingestion of the full-market official close snapshot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .industry_metadata import _is_a_share_identity
from .market_history_store import MarketHistoryStore


_CN_TZ = timezone(timedelta(hours=8))


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _raw_quote(row: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    values = {
        "open": _number(row.get("open")),
        "high": _number(row.get("high")),
        "low": _number(row.get("low")),
        "close": _number(row.get("current_price")),
        "prev_close": _number(row.get("prev_close")),
        "volume": _number(row.get("volume")),
        "amount": _number(row.get("amount")),
    }
    if any(
        values[key] is None or values[key] <= 0
        for key in ("open", "high", "low", "close", "prev_close")
    ):
        return None
    if values["volume"] is None or values["volume"] < 0:
        return None
    if values["amount"] is None or values["amount"] < 0:
        return None
    if values["high"] < max(values["open"], values["low"], values["close"]):
        return None
    if values["low"] > min(values["open"], values["high"], values["close"]):
        return None
    return values  # type: ignore[return-value]


def _previous_final_closes(
    store: MarketHistoryStore, report_date: str
) -> Dict[Any, float]:
    rows = store.connection.execute(
        """
        SELECT i.exchange, i.code, b.close
        FROM instruments i
        JOIN bars_day b ON b.instrument_id=i.instrument_id
        WHERE i.asset_type='stock'
          AND b.is_final=1
          AND b.ts=(
              SELECT MAX(previous.ts)
              FROM bars_day previous
              WHERE previous.instrument_id=i.instrument_id
                AND previous.is_final=1
                AND previous.ts < ?
          )
        """,
        (str(report_date),),
    ).fetchall()
    return {
        (str(row["exchange"]), str(row["code"])): float(row["close"])
        for row in rows
        if float(row["close"]) > 0
    }


def ingest_market_close_snapshot(
    db_path: Any,
    report_date: str,
    fetch_all_a_stocks: Callable[..., Any],
    generated_at: Optional[datetime] = None,
    min_coverage: float = 0.90,
    force_remote: bool = False,
) -> Dict[str, Any]:
    """Fetch one full-A quote snapshot and atomically append the final qfq bar."""
    now = generated_at or datetime.now(_CN_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_CN_TZ)
    now_cn = now.astimezone(_CN_TZ)
    diagnostics = {
        "status": "not_closed",
        "report_date": str(report_date),
        "requested": 0,
        "unique": 0,
        "valid_a_rows": 0,
        "quoted_rows": 0,
        "written": 0,
        "skipped_unquoted": 0,
        "skipped_missing_factor": 0,
        "history_eligible_rows": 0,
        "coverage": 0.0,
        "remote_calls": 0,
    }
    if str(report_date) != now_cn.date().isoformat() or now_cn.hour < 15:
        return diagnostics

    path = Path(db_path)
    with MarketHistoryStore(path) as store:
        instruments = [
            row
            for row in store.list_instruments(asset_type="stock")
            if _is_a_share_identity(row)
        ]
        final_identities = {
            (str(row["exchange"]), str(row["code"]))
            for row in store.connection.execute(
                """
                SELECT i.exchange, i.code
                FROM instruments i
                JOIN bars_day b ON b.instrument_id=i.instrument_id
                WHERE i.asset_type='stock' AND b.ts=? AND b.is_final=1
                """,
                (str(report_date),),
            ).fetchall()
        }
        final_count = sum(
            (str(row["exchange"]), str(row["code"])) in final_identities
            for row in instruments
        )
        db_coverage = (
            final_count / float(len(instruments)) if instruments else 0.0
        )
        if (
            not force_remote
            and instruments
            and db_coverage >= float(min_coverage)
        ):
            diagnostics.update(
                status="complete",
                source="db",
                valid_a_rows=len(instruments),
                valid_bar_count=final_count,
                coverage=round(db_coverage, 6),
            )
            return diagnostics

    diagnostics["remote_calls"] = 1
    result = fetch_all_a_stocks(return_diagnostics=True)
    if not isinstance(result, tuple) or len(result) != 2:
        diagnostics.update(status="incomplete", reason="missing_fetch_diagnostics")
        return diagnostics
    rows, fetch_diagnostics = result
    rows = rows if isinstance(rows, list) else []
    fetch_diagnostics = (
        fetch_diagnostics if isinstance(fetch_diagnostics, Mapping) else {}
    )
    requested = int(fetch_diagnostics.get("requested") or 0)
    unique = int(fetch_diagnostics.get("unique") or len(rows))
    diagnostics.update(requested=requested, unique=unique)
    if (
        not fetch_diagnostics.get("complete")
        or requested <= 0
        or unique != requested
        or len(rows) != unique
    ):
        diagnostics.update(status="incomplete", reason="universe_not_complete")
        return diagnostics

    valid_rows = [
        row
        for row in rows
        if isinstance(row, Mapping) and _is_a_share_identity(row)
    ]
    diagnostics["valid_a_rows"] = len(valid_rows)
    if not valid_rows:
        diagnostics.update(status="incomplete", reason="no_valid_a_rows")
        return diagnostics

    with MarketHistoryStore(path) as store:
        previous_closes = _previous_final_closes(store, str(report_date))
        prepared = []
        valid_identities = {
            (str(row.get("exchange")), str(row.get("code")))
            for row in valid_rows
        }
        history_eligible = valid_identities.intersection(previous_closes)
        diagnostics["history_eligible_rows"] = len(history_eligible)
        for row in valid_rows:
            quote = _raw_quote(row)
            if quote is None:
                diagnostics["skipped_unquoted"] += 1
                continue
            diagnostics["quoted_rows"] += 1
            identity = (str(row.get("exchange")), str(row.get("code")))
            previous_close = previous_closes.get(identity)
            if previous_close is None or previous_close <= 0:
                diagnostics["skipped_missing_factor"] += 1
                continue
            factor = previous_close / quote["prev_close"]
            if factor <= 0:
                diagnostics["skipped_missing_factor"] += 1
                continue
            prepared.append(
                (
                    row,
                    {
                        "ts": str(report_date),
                        "open": quote["open"] * factor,
                        "high": quote["high"] * factor,
                        "low": quote["low"] * factor,
                        "close": quote["close"] * factor,
                        "volume": quote["volume"],
                        "amount": quote["amount"],
                        "adjustment": "qfq",
                        "is_final": True,
                        "source_batch": "official_close_snapshot:eastmoney",
                    },
                )
            )

        diagnostics["coverage"] = round(
            len(prepared) / float(len(history_eligible)), 6
            if history_eligible
            else 0.0
        )
        if diagnostics["coverage"] < float(min_coverage):
            diagnostics.update(
                status="insufficient_coverage",
                reason="valid_bar_coverage_below_floor",
            )
            return diagnostics

        changed = 0
        with store.connection:
            for row, bar in prepared:
                instrument_id = store.upsert_instrument(
                    "stock",
                    str(row.get("exchange")),
                    str(row.get("code")),
                    name=str(row.get("name") or ""),
                )
                changed += store.upsert_bars(
                    "day", instrument_id, [bar], adjustment="qfq"
                )
        diagnostics.update(
            status="complete",
            valid_bar_count=len(prepared),
            written=changed,
        )
    return diagnostics
