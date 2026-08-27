"""Fail-closed trading-day guard for the independent pre-close jobs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote


# Shanghai Stock Exchange 2026 domestic-market closures. Weekends are handled
# separately. Source: https://www.sse.com.cn/disclosure/dealinstruc/closed/
_SSE_2026_CLOSED_RANGES = (
    ("2026-01-01", "2026-01-03"),
    ("2026-02-15", "2026-02-23"),
    ("2026-04-04", "2026-04-06"),
    ("2026-05-01", "2026-05-05"),
    ("2026-06-19", "2026-06-21"),
    ("2026-09-25", "2026-09-27"),
    ("2026-10-01", "2026-10-07"),
)


def _dates_in_ranges(ranges):
    values = set()
    for start, end in ranges:
        current = datetime.strptime(start, "%Y-%m-%d").date()
        finish = datetime.strptime(end, "%Y-%m-%d").date()
        while current <= finish:
            values.add(current.isoformat())
            current += timedelta(days=1)
    return values


_SSE_2026_CLOSED = _dates_in_ranges(_SSE_2026_CLOSED_RANGES)


def _canonical_date(value):
    text = str(value or "").strip()
    parsed = datetime.strptime(text, "%Y-%m-%d").date()
    if parsed.isoformat() != text:
        raise ValueError("invalid trade date")
    return parsed


def _calendar_override(trade_date, market_db):
    path = Path(market_db).expanduser().resolve()
    if not path.is_file():
        return None
    uri = "file:{}?mode=ro".format(quote(str(path)))
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute(
                "SELECT is_open FROM trade_calendar "
                "WHERE trade_date=? AND exchange IN ('SH', 'SZ')",
                (str(trade_date),),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    flags = [bool(row[0]) for row in rows]
    return all(flags)


def is_trading_day(trade_date, market_db):
    """Return true only for an explicitly supported weekday/open calendar row."""

    parsed = _canonical_date(trade_date)
    if parsed.weekday() >= 5:
        return False
    override = _calendar_override(parsed.isoformat(), market_db)
    if override is not None:
        return override
    if parsed.year == 2026:
        return parsed.isoformat() not in _SSE_2026_CLOSED
    # Unknown calendar years fail closed until the local calendar is populated
    # or the reviewed annual exchange closure list is updated.
    return False
