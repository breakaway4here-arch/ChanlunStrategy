"""Read-only intraday inputs for the isolated 14:47 pre-close workflow."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote


_CN_TZ = timezone(timedelta(hours=8))
_CORE_ARRAY_KEYS = ("opens", "highs", "lows", "closes", "volumes")
_FORBIDDEN_OUTPUT_NAMES = {
    "recommendation_ledger.jsonl",
    "market_history.sqlite",
    "strategy_scorecard.json",
    "index.html",
}


def _parse_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_CN_TZ)
    return parsed.astimezone(_CN_TZ)


def _date_part(value):
    return str(value or "").strip().replace("T", " ").split(" ", 1)[0]


def _plain_list(value):
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _normalize_kline(payload):
    if not isinstance(payload, dict):
        return None
    try:
        dates = [str(value) for value in _plain_list(payload.get("dates"))]
        arrays = {
            key: _plain_list(payload.get(key))
            for key in _CORE_ARRAY_KEYS
        }
    except (TypeError, ValueError):
        return None
    if not dates or any(len(values) != len(dates) for values in arrays.values()):
        return None
    result = {"dates": dates}
    result.update({key: _json_safe(values) for key, values in arrays.items()})
    for optional in ("amounts", "finals"):
        raw = payload.get(optional)
        if raw is None:
            continue
        values = _plain_list(raw)
        if len(values) == len(dates):
            result[optional] = _json_safe(values)
    source = str(payload.get("source") or "").strip()
    if source:
        result["source"] = source
    return result


def _kline_rows(payload, default_final):
    normalized = _normalize_kline(payload)
    if not normalized:
        return []
    finals = normalized.get("finals")
    rows = []
    for index, timestamp in enumerate(normalized["dates"]):
        row = {"date": timestamp}
        for key in _CORE_ARRAY_KEYS:
            row[key] = normalized[key][index]
        if "amounts" in normalized:
            row["amounts"] = normalized["amounts"][index]
        row["final"] = (
            bool(finals[index]) if finals is not None else bool(default_final)
        )
        rows.append(row)
    return rows


def _merge_daily_klines(history, live, trade_date):
    rows = {}
    for row in _kline_rows(history, default_final=True):
        if _date_part(row["date"]) != trade_date:
            rows[row["date"]] = row
    for row in _kline_rows(live, default_final=False):
        if _date_part(row["date"]) == trade_date:
            row["final"] = False
            rows[row["date"]] = row
    ordered = [rows[key] for key in sorted(rows)]
    if not ordered:
        return None
    result = {"dates": [row["date"] for row in ordered]}
    for key in _CORE_ARRAY_KEYS:
        result[key] = [row[key] for row in ordered]
    if any("amounts" in row for row in ordered):
        result["amounts"] = [row.get("amounts") for row in ordered]
    result["finals"] = [bool(row["final"]) for row in ordered]
    result["source"] = str((live or {}).get("source") or (history or {}).get("source") or "")
    return result


def _validated_trade_date(value):
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError("invalid trade_date")
    if parsed.strftime("%Y-%m-%d") != text:
        raise ValueError("invalid trade_date")
    return text


@dataclass(frozen=True)
class PrecloseDataPaths:
    """Explicit isolated namespace plus read-only access to the formal DB."""

    root: Path
    formal_market_db: Path

    def __post_init__(self):
        root = Path(self.root).expanduser().resolve()
        formal = Path(self.formal_market_db).expanduser().resolve()
        self._validate_output_root(root, formal)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "formal_market_db", formal)

    @staticmethod
    def _validate_output_root(root, formal):
        lowered_parts = {part.lower() for part in root.parts}
        if "docs" in lowered_parts:
            raise ValueError("pre-close output root must not be under docs")
        if root == formal or root.name.lower() in _FORBIDDEN_OUTPUT_NAMES:
            raise ValueError("pre-close output root overlaps a formal output")
        if root.suffix and root.name != ".cache":
            raise ValueError("pre-close output root must be a directory")

    def input_path(self, trade_date):
        date = _validated_trade_date(trade_date)
        target = (self.root / date / "input.json").resolve()
        try:
            common = os.path.commonpath([str(self.root), str(target)])
        except ValueError:
            raise ValueError("pre-close output escaped its isolated root")
        if common != str(self.root) or target == self.formal_market_db:
            raise ValueError("pre-close output escaped its isolated root")
        return target

    def open_formal_market_db(self):
        """Open the canonical market store through SQLite's immutable write guard."""

        if not self.formal_market_db.is_file():
            raise FileNotFoundError(str(self.formal_market_db))
        uri = "file:{}?mode=ro".format(quote(str(self.formal_market_db)))
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection


class RemotePrecloseMarketFetcher:
    """Remote-only adapter; it never constructs the formal K-line repository."""

    def __init__(self):
        self._daily = {}

    def fetch_daily_history(self, code, count):
        from . import data_fetcher

        payload = data_fetcher._fetch_daily_for_repository(code, count)
        self._daily[str(code)] = payload
        return payload

    def fetch_intraday_daily(self, code, as_of):
        del as_of
        if str(code) in self._daily:
            return self._daily[str(code)]
        from . import data_fetcher

        return data_fetcher._fetch_daily_for_repository(code, 120)

    def fetch_30m(self, code, count, as_of):
        del as_of
        from . import data_fetcher

        return data_fetcher._fetch_30min_kline_remote(code, count=count)


def build_intraday_daily_snapshot(
    universe,
    *,
    fetcher,
    trade_date,
    as_of,
    history_count=120
):
    """Fetch historical daily evidence and splice the current non-final bar."""

    date = _validated_trade_date(trade_date)
    as_of_text = _parse_datetime(as_of).isoformat(timespec="seconds")
    rows = []
    for raw_stock in universe or []:
        stock = dict(raw_stock or {})
        code = str(stock.get("code") or "").strip()
        history = fetcher.fetch_daily_history(code, int(history_count))
        intraday = fetcher.fetch_intraday_daily(code, as_of_text)
        normalized_live = _normalize_kline(intraday)
        latest_date = (
            _date_part(normalized_live["dates"][-1]) if normalized_live else ""
        )
        merged = _merge_daily_klines(history, intraday, date)
        available = latest_date == date and merged is not None
        row = dict(stock)
        row.update({
            "status": "available" if available else "unavailable",
            "bar_state": "intraday",
            "is_final": False,
            "as_of": as_of_text,
            "latest_date": latest_date,
        })
        if available:
            row["klines"] = merged
        else:
            row["reason_code"] = (
                "current_trade_date_missing" if normalized_live else "daily_data_missing"
            )
        rows.append(row)
    return rows


def fetch_target_30m_snapshots(
    targets,
    *,
    fetcher,
    trade_date,
    as_of,
    count=80
):
    """Fetch 30-minute evidence only after the daily target set is known."""

    date = _validated_trade_date(trade_date)
    as_of_dt = _parse_datetime(as_of)
    as_of_text = as_of_dt.isoformat(timespec="seconds")
    output = {}
    for target in targets or []:
        code = str((target or {}).get("code") or "").strip()
        payload = _normalize_kline(fetcher.fetch_30m(code, int(count), as_of_text))
        latest_ts = payload["dates"][-1] if payload else ""
        latest_date = _date_part(latest_ts)
        if not payload or latest_date != date:
            output[code] = {
                "status": "unavailable",
                "reason_code": (
                    "current_trade_date_missing" if payload else "data_missing"
                ),
                "latest_date": latest_date,
                "bar_state": "intraday",
                "is_final": False,
                "as_of": as_of_text,
            }
            continue
        finals = payload.get("finals")
        if finals is None:
            finals = []
            for raw_timestamp in payload["dates"]:
                try:
                    finals.append(_parse_datetime(raw_timestamp) <= as_of_dt)
                except ValueError:
                    finals.append(False)
            payload["finals"] = finals
        output[code] = {
            "status": "available",
            "latest_date": latest_date,
            "latest_ts": latest_ts,
            "bar_state": "intraday",
            "is_final": False,
            "as_of": as_of_text,
            "klines": payload,
        }
    return output


def build_preclose_market_inputs(
    universe,
    *,
    fetcher,
    select_daily_targets,
    trade_date,
    as_of,
    history_count=120,
    min30_count=80
):
    """Build daily inputs first, then fetch 30m only for selected codes."""

    daily = build_intraday_daily_snapshot(
        universe,
        fetcher=fetcher,
        trade_date=trade_date,
        as_of=as_of,
        history_count=history_count,
    )
    selectable = [row for row in daily if row.get("status") == "available"]
    selected = list(select_daily_targets(selectable) or [])
    selected_codes = {
        str(item.get("code") if isinstance(item, dict) else item).strip()
        for item in selected
    }
    targets = [row for row in selectable if row.get("code") in selected_codes]
    min30 = fetch_target_30m_snapshots(
        targets,
        fetcher=fetcher,
        trade_date=trade_date,
        as_of=as_of,
        count=min30_count,
    )
    return {
        "schema_version": "preclose-input-v1",
        "mode": "preclose_advisory",
        "trade_date": _validated_trade_date(trade_date),
        "as_of": _parse_datetime(as_of).isoformat(timespec="seconds"),
        "bar_state": "intraday",
        "is_final": False,
        "daily": daily,
        "target_codes": [row["code"] for row in targets],
        "min30": min30,
    }


def write_preclose_input_snapshot(paths, snapshot):
    """Atomically write one JSON input under ``<root>/<date>/input.json``."""

    if not isinstance(paths, PrecloseDataPaths):
        raise TypeError("paths must be PrecloseDataPaths")
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a mapping")
    target = paths.input_path(snapshot.get("trade_date"))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".input.json.tmp")
    encoded = json.dumps(
        _json_safe(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(str(temporary), str(target))
    return target
