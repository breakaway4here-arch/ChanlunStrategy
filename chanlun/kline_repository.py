"""DB-first K-line repository shared by ongoing jobs and frozen backtests."""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

from .market_history_store import MarketHistoryStore


_CN_TZ = timezone(timedelta(hours=8))
_INTERVAL_MINUTES = {"30m": 30, "15m": 15}


@dataclass
class KLineResult:
    kline: Optional[Dict[str, Any]]
    status: str
    source: str
    stale: bool
    fetched_remote: bool = False
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class KLineRepository:
    """Read canonical SQLite first and serialize only necessary remote writes."""

    def __init__(
        self,
        path: Any,
        remote_fetchers: Optional[Mapping[str, Callable[[str, int], Any]]] = None,
        mode: str = "ongoing",
        shadow_reader: Optional[Callable[[str, str, int], Any]] = None,
        overlap_counts: Optional[Mapping[str, int]] = None,
        adjustment: str = "qfq",
        max_workers: int = 8,
        trace_callback: Optional[Callable[[str], None]] = None,
        immutable_backtest: bool = True,
    ):
        if mode not in ("ongoing", "backtest"):
            raise ValueError("mode must be ongoing or backtest")
        self.path = Path(path)
        self.remote_fetchers = dict(remote_fetchers or {})
        self.mode = mode
        self.shadow_reader = shadow_reader
        self.overlap_counts = dict(
            overlap_counts or {"day": 2, "30m": 16, "15m": 32}
        )
        self.adjustment = str(adjustment)
        self.max_workers = max(1, int(max_workers))
        self.trace_callback = trace_callback
        self.immutable_backtest = bool(immutable_backtest)
        self._write_lock = threading.Lock()
        self._memory = {}
        if self.mode == "ongoing":
            with MarketHistoryStore(self.path):
                pass

    @staticmethod
    def _exchange(code: str) -> str:
        return "SH" if str(code).startswith(("60", "68", "900")) else "SZ"

    def _open(self, readonly: bool) -> MarketHistoryStore:
        store = MarketHistoryStore(
            self.path,
            readonly=readonly,
            immutable=readonly and self.mode == "backtest" and self.immutable_backtest,
        )
        if self.trace_callback is not None:
            store.connection.set_trace_callback(self.trace_callback)
        return store

    @staticmethod
    def _latest_date(rows: Sequence[Mapping[str, Any]]) -> str:
        return str(rows[-1]["ts"]).split(" ")[0] if rows else ""

    @staticmethod
    def _safe_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if hasattr(value, "tolist"):
            value = value.tolist()
        return list(value)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        text = str(value).strip().replace("T", " ")
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            raise ValueError("invalid kline timestamp: {}".format(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_CN_TZ)
        return parsed.astimezone(_CN_TZ)

    @classmethod
    def _normalized_timestamp(cls, interval: str, value: Any) -> str:
        parsed = cls._parse_timestamp(value)
        if interval == "day":
            return parsed.strftime("%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _strict_final(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if type(value) is int and value in (0, 1):
            return value
        raise ValueError("final flag must be bool or integer 0/1")

    @classmethod
    def _infer_final(cls, interval: str, ts: str, now: datetime) -> int:
        parsed = cls._parse_timestamp(ts)
        current = now.astimezone(_CN_TZ)
        if interval == "day":
            if parsed.date() < current.date():
                return 1
            return int(
                parsed.date() == current.date()
                and current.time() >= datetime.strptime("15:00", "%H:%M").time()
            )
        # Eastmoney/Sina minute K-line timestamps identify the bar's end,
        # unlike an exchange event stream where timestamps identify the
        # interval start.  Waiting another full interval kept the 15:00 close
        # permanently marked preview in the 15:05 official run.
        return int(parsed <= current)

    @staticmethod
    def _optional_nonnegative(values: Sequence[Any], index: int) -> float:
        if index >= len(values):
            return 0.0
        try:
            number = float(values[index])
        except (TypeError, ValueError):
            return 0.0
        return number if math.isfinite(number) and number >= 0 else 0.0

    def _prepare_remote(
        self,
        interval: str,
        code: str,
        payload: Mapping[str, Any],
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        dates = self._safe_list(payload.get("dates"))
        arrays = {
            key: self._safe_list(payload.get(key))
            for key in ("opens", "highs", "lows", "closes", "volumes")
        }
        if not dates or any(len(values) != len(dates) for values in arrays.values()):
            raise ValueError("remote kline arrays must have identical nonzero lengths")
        amounts = self._safe_list(payload.get("amounts"))
        finals_value = payload.get("finals")
        finals = self._safe_list(finals_value) if finals_value is not None else []
        if finals and len(finals) != len(dates):
            raise ValueError("remote finals length mismatch")
        current = now or datetime.now(_CN_TZ)
        provider = str(payload.get("source") or "remote")
        seen = set()
        bars = []
        for index, raw_ts in enumerate(dates):
            ts = self._normalized_timestamp(interval, raw_ts)
            if ts in seen:
                raise ValueError("duplicate remote timestamp: {}".format(ts))
            seen.add(ts)
            final = (
                self._strict_final(finals[index])
                if finals
                else self._infer_final(interval, ts, current)
            )
            bars.append(
                {
                    "ts": ts,
                    "open": arrays["opens"][index],
                    "high": arrays["highs"][index],
                    "low": arrays["lows"][index],
                    "close": arrays["closes"][index],
                    "volume": arrays["volumes"][index],
                    "amount": self._optional_nonnegative(amounts, index),
                    "adjustment": self.adjustment,
                    "is_final": final,
                    "source_batch": "ongoing:{}".format(provider),
                }
            )
        validated_bars = [
            MarketHistoryStore._validated_bar(bar, self.adjustment)
            for bar in sorted(bars, key=lambda row: row["ts"])
        ]
        return {
            "code": code,
            "exchange": self._exchange(code),
            "provider": provider,
            "bars": validated_bars,
        }

    def _load_many(
        self,
        interval: str,
        codes: Sequence[str],
        count: int,
        as_of: Optional[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        identities = [(self._exchange(code), code) for code in codes]
        with self._open(readonly=True) as store:
            instruments = store.resolve_instruments("stock", identities)
            id_to_code = {}
            instrument_ids = []
            for code in codes:
                identity = (self._exchange(code), code)
                instrument = instruments.get(identity)
                if instrument is not None:
                    instrument_id = int(instrument["instrument_id"])
                    instrument_ids.append(instrument_id)
                    id_to_code[instrument_id] = code
            rows_by_id = store.query_bars_many(
                interval,
                instrument_ids,
                as_of=as_of,
                limit=count,
            )
        result = {code: [] for code in codes}
        for instrument_id, rows in rows_by_id.items():
            result[id_to_code[instrument_id]] = rows
        return result

    @staticmethod
    def _rows_to_kline(
        rows: Sequence[Mapping[str, Any]],
        status: str,
        stale: bool,
    ) -> Optional[Dict[str, Any]]:
        if not rows:
            return None
        latest_final = bool(rows[-1]["is_final"])
        result = {
            "dates": [row["ts"] for row in rows],
            "opens": np.array([row["open"] for row in rows], dtype=float),
            "highs": np.array([row["high"] for row in rows], dtype=float),
            "lows": np.array([row["low"] for row in rows], dtype=float),
            "closes": np.array([row["close"] for row in rows], dtype=float),
            "volumes": np.array([row["volume"] for row in rows], dtype=float),
            "amounts": np.array([row["amount"] for row in rows], dtype=float),
            "source": "market_history_db",
        }
        result["_data_status"] = {
            "daily": status,
            "latest_date": str(rows[-1]["ts"]).split(" ")[0],
            "source": "market_history_db",
            "bars": len(rows),
            "stale": bool(stale),
            "is_final": latest_final,
        }
        return result

    @classmethod
    def _needs_refresh(
        cls,
        rows: Sequence[Mapping[str, Any]],
        count: int,
        required_date: Optional[str],
        force_refresh: bool,
    ) -> bool:
        if force_refresh or len(rows) < count:
            return True
        if required_date and cls._latest_date(rows) != str(required_date):
            return True
        if (
            not required_date
            and cls._latest_date(rows)
            < datetime.now(_CN_TZ).date().isoformat()
        ):
            return True
        return not bool(rows[-1]["is_final"])

    def _status(
        self,
        rows: Sequence[Mapping[str, Any]],
        count: int,
        required_date: Optional[str],
        remote_failed: bool,
    ):
        if not rows:
            return "missing", True
        latest_matches = (
            not required_date or self._latest_date(rows) == str(required_date)
        )
        enough = len(rows) >= count
        latest_final = bool(rows[-1]["is_final"])
        if self.mode == "backtest":
            return ("verified", False) if enough and latest_matches and latest_final else (
                "missing",
                True,
            )
        if enough and latest_matches and latest_final and not remote_failed:
            return "verified", False
        if latest_matches and not latest_final:
            return "preview", False
        return "stale_cache", True

    def _write_prepared(self, prepared: Sequence[Mapping[str, Any]]) -> None:
        if not prepared:
            return
        with self._write_lock:
            with self._open(readonly=False) as store:
                try:
                    store.connection.execute("BEGIN IMMEDIATE")
                    for item in prepared:
                        instrument_id = store.upsert_instrument(
                            "stock", item["exchange"], item["code"]
                        )
                        store.upsert_bars(
                            item["interval"],
                            instrument_id,
                            item["bars"],
                            adjustment=self.adjustment,
                        )
                    store.connection.commit()
                except Exception:
                    store.connection.rollback()
                    raise

    def _shadow_diagnostics(
        self, interval: str, code: str, count: int, kline: Optional[Mapping[str, Any]]
    ) -> Dict[str, Any]:
        if self.shadow_reader is None:
            return {}
        try:
            shadow = self.shadow_reader(interval, code, count)
            current_dates = list((kline or {}).get("dates", []))
            shadow_dates = list((shadow or {}).get("dates", []))
            return {
                "shadow_checked": True,
                "shadow_mismatch": current_dates != shadow_dates,
                "shadow_bars": len(shadow_dates),
            }
        except Exception as exc:
            return {
                "shadow_checked": True,
                "shadow_mismatch": True,
                "shadow_error": str(exc),
            }

    def get_many(
        self,
        interval: str,
        codes: Sequence[str],
        count: int,
        required_date: Optional[str] = None,
        as_of: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, KLineResult]:
        if interval not in ("day", "30m", "15m"):
            raise ValueError("unsupported interval: {}".format(interval))
        if int(count) <= 0:
            raise ValueError("count must be positive")
        if self.mode == "backtest" and not as_of:
            raise ValueError("backtest mode requires as_of")
        normalized = list(dict.fromkeys(str(code).strip() for code in codes))
        local = self._load_many(interval, normalized, int(count), as_of)
        remote_failed = {}
        fetched_remote = set()
        prepared = []

        refresh_codes = [
            code
            for code in normalized
            if self.mode == "ongoing"
            and self._needs_refresh(
                local[code], int(count), required_date, force_refresh
            )
        ]
        fetcher = self.remote_fetchers.get(interval)
        if refresh_codes and fetcher is None:
            remote_failed.update((code, True) for code in refresh_codes)
        elif refresh_codes:
            def _fetch(code):
                existing = local[code]
                remote_count = (
                    int(count)
                    if force_refresh or len(existing) < int(count)
                    else int(self.overlap_counts[interval])
                )
                return code, fetcher(code, remote_count)

            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(refresh_codes))
            ) as pool:
                futures = {pool.submit(_fetch, code): code for code in refresh_codes}
                for future in as_completed(futures):
                    code = futures[future]
                    try:
                        _returned_code, payload = future.result()
                        if not payload:
                            remote_failed[code] = True
                            continue
                        item = self._prepare_remote(interval, code, payload)
                        item["interval"] = interval
                        prepared.append(item)
                        fetched_remote.add(code)
                    except Exception:
                        remote_failed[code] = True
            if prepared:
                try:
                    self._write_prepared(prepared)
                except Exception:
                    for item in prepared:
                        remote_failed[item["code"]] = True
                        fetched_remote.discard(item["code"])
                else:
                    local = self._load_many(
                        interval, normalized, int(count), as_of
                    )

        results = {}
        for code in normalized:
            rows = local[code]
            status, stale = self._status(
                rows,
                int(count),
                required_date,
                remote_failed=bool(remote_failed.get(code)),
            )
            kline = self._rows_to_kline(rows, status, stale)
            diagnostics = {
                "remote_failed": bool(remote_failed.get(code)),
                "mode": self.mode,
            }
            diagnostics.update(
                self._shadow_diagnostics(interval, code, int(count), kline)
            )
            result = KLineResult(
                kline=kline,
                status=status,
                source="market_history_db" if kline else "missing",
                stale=stale,
                fetched_remote=code in fetched_remote,
                diagnostics=diagnostics,
            )
            results[code] = result
            if status == "verified" and not force_refresh:
                self._memory[
                    (interval, code, int(count), required_date, as_of, force_refresh)
                ] = result
        return results

    def get(
        self,
        interval: str,
        code: str,
        count: int,
        required_date: Optional[str] = None,
        as_of: Optional[str] = None,
        force_refresh: bool = False,
    ) -> KLineResult:
        key = (interval, str(code), int(count), required_date, as_of, force_refresh)
        if key in self._memory:
            return self._memory[key]
        return self.get_many(
            interval,
            [str(code)],
            count=int(count),
            required_date=required_date,
            as_of=as_of,
            force_refresh=force_refresh,
        )[str(code)]

    def list_instruments(self) -> List[Dict[str, Any]]:
        with self._open(readonly=True) as store:
            return store.list_instruments(asset_type="stock")
