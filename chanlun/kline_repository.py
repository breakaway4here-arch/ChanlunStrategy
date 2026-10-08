"""DB-first K-line repository shared by ongoing jobs and frozen backtests."""

from __future__ import annotations

import math
import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

from .market_history_store import MarketHistoryStore
from .identity import InstrumentIdentity, normalize_identity
from .minute_sources import align_daily_basis


_CN_TZ = timezone(timedelta(hours=8))
_INTERVAL_MINUTES = {"30m": 30, "15m": 15}


class _RepairRowsChanged(ValueError):
    pass


class DailyRepairBudget:
    """One request ledger and monotonic deadline shared by the entire repair."""

    def __init__(self, max_stocks=8, max_requests=16, seconds=20,
                 remaining=None, monotonic=time.monotonic):
        self.max_stocks = min(8, max(0, int(max_stocks)))
        self.max_requests = min(16, max(0, int(max_requests)))
        self.monotonic = monotonic
        self.deadline = float(monotonic()) + min(20., max(0., float(seconds)))
        self.external_remaining = remaining
        self.requests = 0

    def remaining(self):
        left = self.deadline - float(self.monotonic())
        if self.external_remaining is not None:
            left = min(left, float(self.external_remaining()))
        return max(0., left)

    def ensure(self):
        if self.remaining() <= 0:
            raise ValueError('daily_repair_deadline')

    def take_request(self):
        remaining = self.remaining()
        if remaining <= 0:
            raise ValueError('daily_repair_deadline')
        if self.requests >= self.max_requests:
            raise ValueError('daily_repair_request_limit')
        self.requests += 1
        return min(3., remaining)


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
        remote_fetchers: Optional[Mapping[str, Callable[[Any, int], Any]]] = None,
        mode: str = "ongoing",
        shadow_reader: Optional[Callable[[str, str, int], Any]] = None,
        overlap_counts: Optional[Mapping[str, int]] = None,
        adjustment: str = "qfq",
        max_workers: int = 8,
        trace_callback: Optional[Callable[[str], None]] = None,
        immutable_backtest: bool = True,
        raw_daily_reader: Optional[Callable[..., Any]] = None,
    ):
        if mode not in ("ongoing", "backtest"):
            raise ValueError("mode must be ongoing or backtest")
        self.path = Path(path)
        self.remote_fetchers = dict(remote_fetchers or {})
        self.raw_daily_reader = raw_daily_reader
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
        self._daily_repair_pending = {}
        if self.mode == "ongoing":
            with MarketHistoryStore(self.path):
                pass

    @staticmethod
    def _identity(value: Any) -> InstrumentIdentity:
        return normalize_identity(value)

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
    def _expected_latest_ts(
        interval: str,
        required_date: Optional[str],
    ) -> Optional[str]:
        if interval not in _INTERVAL_MINUTES or not required_date:
            return None
        return "{} 15:00:00".format(required_date)

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

    @staticmethod
    def _optional_amount(
        values: Sequence[Any], index: int, available: Optional[Sequence[Any]] = None
    ) -> tuple:
        if available is not None and index < len(available):
            marker = available[index]
            if marker not in (True, 1):
                return 0.0, False
        if index >= len(values):
            return 0.0, False
        try:
            number = float(values[index])
        except (TypeError, ValueError):
            return 0.0, False
        if not math.isfinite(number) or number <= 0:
            return 0.0, False
        return number, True

    def _prepare_remote(
        self,
        interval: str,
        identity: InstrumentIdentity,
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
        volume_unit = str(payload.get("volume_unit") or "unknown").strip().lower()
        volume_raw_unit = str(
            payload.get("volume_raw_unit") or volume_unit or "unknown"
        ).strip().lower()
        volume_source = str(payload.get("volume_source") or provider).strip()
        amount_unit = str(payload.get("amount_unit") or "unknown").strip().upper()
        amount_source = str(payload.get("amount_source") or "").strip()
        raw_amount_available = payload.get("amount_available")
        amount_available = None
        if raw_amount_available is not None:
            amount_available = self._safe_list(raw_amount_available)
            if len(amount_available) != len(dates):
                raise ValueError("remote amount_available length mismatch")
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
            amount, has_amount = self._optional_amount(
                amounts, index, amount_available
            )
            bars.append(
                {
                    "ts": ts,
                    "open": arrays["opens"][index],
                    "high": arrays["highs"][index],
                    "low": arrays["lows"][index],
                    "close": arrays["closes"][index],
                    "volume": arrays["volumes"][index],
                    "amount": amount,
                    "amount_available": has_amount,
                    "volume_unit": volume_unit,
                    "volume_raw_unit": volume_raw_unit,
                    "volume_source": volume_source,
                    "amount_unit": amount_unit if has_amount else "unknown",
                    "amount_source": amount_source if has_amount else "",
                    "adjustment": str(payload.get("adjustment") or self.adjustment),
                    "is_final": final,
                    "source_batch": "ongoing:{}".format(provider),
                }
            )
        validated_bars = [
            MarketHistoryStore._validated_bar(bar, self.adjustment)
            for bar in sorted(bars, key=lambda row: row["ts"])
        ]
        return {
            "asset_type": identity.asset_type,
            "code": identity.code,
            "exchange": identity.exchange,
            "provider": provider,
            "bars": validated_bars,
        }

    def _load_many(
        self,
        interval: str,
        identities: Sequence[InstrumentIdentity],
        count: int,
        as_of: Optional[str],
    ) -> Dict[InstrumentIdentity, List[Dict[str, Any]]]:
        with self._open(readonly=True) as store:
            instruments = {}
            by_asset = {}
            for identity in identities:
                by_asset.setdefault(identity.asset_type, []).append(
                    (identity.exchange, identity.code)
                )
            for asset_type, pairs in by_asset.items():
                for (exchange, code), payload in store.resolve_instruments(
                    asset_type, pairs
                ).items():
                    instruments[(asset_type, exchange, code)] = payload
            instrument_ids = []
            id_to_identity = {}
            for identity in identities:
                instrument = instruments.get(
                    (identity.asset_type, identity.exchange, identity.code)
                )
                if instrument is not None:
                    instrument_id = int(instrument["instrument_id"])
                    instrument_ids.append(instrument_id)
                    id_to_identity[instrument_id] = identity
            rows_by_id = store.query_bars_many(
                interval,
                instrument_ids,
                as_of=as_of,
                limit=count,
            )
        result = {identity: [] for identity in identities}
        for instrument_id, rows in rows_by_id.items():
            result[id_to_identity[instrument_id]] = rows
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
        volume_units = [str(row.get("volume_unit") or "unknown") for row in rows]
        volume_raw_units = [
            str(row.get("volume_raw_unit") or "unknown") for row in rows
        ]
        volume_sources = [str(row.get("volume_source") or "") for row in rows]
        amount_units = [str(row.get("amount_unit") or "unknown") for row in rows]
        amount_sources = [str(row.get("amount_source") or "") for row in rows]

        def _summary(values):
            return values[-1] if values and len(set(values)) == 1 else "mixed"

        result = {
            "dates": [row["ts"] for row in rows],
            "opens": np.array([row["open"] for row in rows], dtype=float),
            "highs": np.array([row["high"] for row in rows], dtype=float),
            "lows": np.array([row["low"] for row in rows], dtype=float),
            "closes": np.array([row["close"] for row in rows], dtype=float),
            "is_final": [bool(row["is_final"]) for row in rows],
            "volumes": np.array([row["volume"] for row in rows], dtype=float),
            "amounts": np.array(
                [
                    row["amount"]
                    if bool(row.get("amount_available", False))
                    and float(row["amount"]) > 0
                    else np.nan
                    for row in rows
                ],
                dtype=float,
            ),
            "amount_available": np.array(
                [
                    bool(row.get("amount_available", False))
                    and float(row["amount"]) > 0
                    for row in rows
                ],
                dtype=bool,
            ),
            "volume_units": volume_units,
            "volume_raw_units": volume_raw_units,
            "volume_sources": volume_sources,
            "amount_units": amount_units,
            "amount_sources": amount_sources,
            "volume_unit": _summary(volume_units),
            "volume_raw_unit": _summary(volume_raw_units),
            "volume_source": _summary(volume_sources),
            "amount_unit": _summary(amount_units),
            "amount_source": _summary(amount_sources),
            "source": "market_history_db",
            "adjustment": str(rows[-1]["adjustment"]),
        }
        result["_data_status"] = {
            "daily": status,
            "latest_date": str(rows[-1]["ts"]).split(" ")[0],
            "source": "market_history_db",
            "bars": len(rows),
            "stale": bool(stale),
            "is_final": latest_final,
            "adjustment": str(rows[-1]["adjustment"]),
            "nonfinal_dates": [str(row['ts']) for row in rows if not bool(row['is_final'])],
        }
        return result

    @classmethod
    def _needs_refresh(
        cls,
        interval: str,
        rows: Sequence[Mapping[str, Any]],
        count: int,
        required_date: Optional[str],
        force_refresh: bool,
    ) -> bool:
        if force_refresh or len(rows) < count:
            return True
        if required_date and cls._latest_date(rows) != str(required_date):
            return True
        expected_latest_ts = cls._expected_latest_ts(
            interval, required_date
        )
        if expected_latest_ts and str(rows[-1]["ts"]) != expected_latest_ts:
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
        interval: str,
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
        expected_latest_ts = self._expected_latest_ts(
            interval, required_date
        )
        close_complete = (
            not expected_latest_ts
            or str(rows[-1]["ts"]) == expected_latest_ts
        )
        enough = len(rows) >= count
        latest_final = bool(rows[-1]["is_final"])
        if interval == 'day' and latest_final and any(not bool(row['is_final']) for row in rows):
            return 'repair_pending', True
        if self.mode == "backtest":
            return ("verified", False) if (
                enough and latest_matches and close_complete and latest_final
            ) else (
                "missing",
                True,
            )
        if (
            enough
            and latest_matches
            and close_complete
            and latest_final
            and not remote_failed
        ):
            return "verified", False
        if latest_matches and close_complete and not latest_final:
            return "preview", False
        return "stale_cache", True

    def _write_prepared(self, prepared: Sequence[Mapping[str, Any]], budget=None) -> None:
        if not prepared:
            return
        with self._write_lock:
            with self._open(readonly=False) as store:
                try:
                    if budget is not None:
                        budget.ensure()
                    store.connection.execute("BEGIN IMMEDIATE")
                    for item in prepared:
                        if budget is not None:
                            budget.ensure()
                        instrument_id = store.upsert_instrument(
                            item["asset_type"],
                            item["exchange"],
                            item["code"],
                        )
                        if 'repair_expected_rows' in item:
                            self._check_repair_rows(store, instrument_id, item['repair_expected_rows'])
                        store.upsert_bars(
                            item["interval"],
                            instrument_id,
                            item["bars"],
                            adjustment=self.adjustment,
                        )
                    if budget is not None:
                        budget.ensure()
                    store.connection.commit()
                except Exception:
                    store.connection.rollback()
                    raise

    @staticmethod
    def _check_repair_rows(store, instrument_id, expected, require_nonfinal=True):
        expected = list(expected)
        current = {r['ts']:r for r in store.query_bars('day', instrument_id,
            start=min(r['ts'] for r in expected), end=max(r['ts'] for r in expected))}
        if len(current) != len(expected):
            raise _RepairRowsChanged('repair_local_window_changed')
        for old in expected:
            row = current.get(old['ts'])
            if row != dict(old) or (require_nonfinal and not bool(old['is_final'])
                                   and row and bool(row['is_final'])):
                raise _RepairRowsChanged('repair_local_row_changed:{}'.format(old['ts']))

    def repair_daily_nonfinal(self, required_date, *, providers, write=True,
                              budget=None, fetch_buffer=False, as_of=None,
                              require_full_quantity=False):
        """Replace only concrete nonfinal dates in the existing <=120 qualification window.

        The ordinary missing-only fetcher is deliberately not used here. Read-only
        callers receive overrides, never a writable connection to their database.
        """
        budget = budget or DailyRepairBudget()
        evidence_as_of = as_of or datetime.now(_CN_TZ).isoformat()
        if write and self.mode != 'ongoing':
            raise ValueError('read-only repository cannot write repairs')
        with self._open(readonly=True) as store:
            instruments = store.list_instruments(asset_type='stock')
            rows_by_id = store.query_bars_many('day', [int(i['instrument_id']) for i in instruments],
                                               as_of=required_date, limit=120)
        gaps = [(i, rows_by_id[int(i['instrument_id'])]) for i in instruments
                if any(not bool(r['is_final']) for r in rows_by_id[int(i['instrument_id'])])]
        overrides, expected_overrides, repaired, pending = {}, {}, [], []
        for index, (instrument, rows) in enumerate(gaps):
            bad_dates = [r['ts'] for r in rows if not bool(r['is_final'])]
            try:
                identity = self._identity(instrument)
            except (TypeError, ValueError):
                pending.append(dict(code=instrument['code'], exchange=instrument['exchange'],
                                    nonfinal_dates=bad_dates, reasons=['invalid_identity']))
                continue
            detail = dict(code=identity.code, exchange=identity.exchange,
                          nonfinal_dates=bad_dates, reasons=[])
            if index >= budget.max_stocks or budget.remaining() <= 0 or budget.requests >= budget.max_requests:
                detail['reasons'].append('repair_budget_exhausted')
                pending.append(detail)
                continue
            if len(rows) < 60 or self._latest_date(rows) != str(required_date):
                detail['reasons'].append('local_qualification_window_incomplete')
                pending.append(detail)
                continue
            adopted = False
            for source, fetcher in list(providers)[:2]:
                if budget.remaining() <= 0 or budget.requests >= budget.max_requests:
                    detail['reasons'].append('repair_budget_exhausted')
                    break
                try:
                    payload = fetcher(identity, len(rows) + int(bool(fetch_buffer)), request_budget=budget)
                    budget.ensure()
                    item = self._prepare_daily_repair(identity, rows, payload, source, required_date,
                                                      evidence_as_of, require_full_quantity)
                    replacements = {bar['ts']:bar for bar in item['bars'] if bar['ts'] in bad_dates}
                    if set(replacements) != set(bad_dates):
                        raise ValueError('repair_dates_not_covered')
                    budget.ensure()
                    if write:
                        self._write_prepared([dict(item, bars=list(replacements.values()),
                            repair_expected_rows=rows)], budget=budget)
                        self._memory.clear()
                    else:
                        with self._open(readonly=True) as store:
                            self._check_repair_rows(store, int(instrument['instrument_id']), rows,
                                                    require_nonfinal=False)
                        budget.ensure()
                    merged = [dict(r, **replacements[r['ts']]) if r['ts'] in replacements else dict(r) for r in rows]
                    overrides[int(instrument['instrument_id'])] = merged
                    expected_overrides[int(instrument['instrument_id'])] = rows
                    repaired.append(dict(detail, source=source))
                    adopted = True
                    break
                except _RepairRowsChanged as exc:
                    detail['reasons'].append('{}:{}'.format(source, str(exc)))
                    break
                except Exception as exc:
                    detail['reasons'].append('{}:{}'.format(source, str(exc)))
            if not adopted:
                pending.append(detail)
        if write:
            self._memory.clear()
            self._daily_repair_pending = {}
        # A different writer may already have resolved a gap. The failed
        # attempt remains auditable, while current final rows stay usable.
        instrument_ids = {(i['exchange'], i['code']): int(i['instrument_id']) for i in instruments}
        with self._open(readonly=True) as store:
            current_rows = store.query_bars_many('day',
                [instrument_ids[(d['exchange'], d['code'])] for d in pending],
                as_of=required_date, limit=120)
        for detail in pending:
            actual_dates = [r['ts'] for r in current_rows[instrument_ids[(detail['exchange'], detail['code'])]]
                            if not bool(r['is_final'])]
            if actual_dates != detail['nonfinal_dates']:
                detail['initial_nonfinal_dates'] = detail['nonfinal_dates']
                detail['nonfinal_dates'] = actual_dates
        if write:
            for detail in pending:
                if not detail['nonfinal_dates']:
                    continue
                try:
                    identity = InstrumentIdentity('stock', detail['exchange'], detail['code'])
                except ValueError:
                    continue
                self._daily_repair_pending[identity] = (str(required_date), detail['nonfinal_dates'])
        return dict(daily_rows_override=overrides, daily_rows_expected=expected_overrides, diagnostics=dict(
            nonfinal_stock_count=len(gaps), repaired_count=len(repaired), repaired=repaired,
            pending_count=len(pending), pending=pending, http_requests=budget.requests))

    def _prepare_daily_repair(self, identity, rows, payload, source, required_date, as_of,
                              require_full_quantity=False):
        if not isinstance(payload, Mapping):
            raise ValueError('repair_source_unavailable')
        if source not in ('eastmoney', 'tencent') or payload.get('source') != source:
            raise ValueError('repair_source_mismatch')
        if not all(payload.get(k) == getattr(identity, k) for k in ('asset_type','exchange','code')):
            raise ValueError('repair_identity_mismatch')
        dates = self._safe_list(payload.get('dates'))
        normalized = [self._normalized_timestamp('day', d) for d in dates]
        if any(a >= b for a,b in zip(normalized, normalized[1:])):
            raise ValueError('repair_dates_not_increasing')
        arrays = ('opens','highs','lows','closes','volumes','amounts','amount_available','finals')
        for key in arrays:
            if key in payload and len(self._safe_list(payload[key])) != len(dates):
                raise ValueError('repair_array_length_mismatch')
        # A prior-close request can return today's trailing bar. Slice every
        # parallel array together, before validating the previous-date window.
        keep = [i for i,d in enumerate(normalized) if d <= str(required_date)]
        if len(dates) - len(keep) > 1:
            raise ValueError('repair_unexpected_future_tail')
        trimmed = dict(payload, dates=[dates[i] for i in keep])
        for key in arrays:
            if key in payload:
                values = self._safe_list(payload[key])
                trimmed[key] = [values[i] for i in keep]
        if trimmed.get('adjustment') != self.adjustment:
            raise ValueError('repair_adjustment_mismatch')
        if trimmed.get('volume_unit') not in ('hands', 'unknown') or trimmed.get('volume_raw_unit') not in ('hands','shares','unknown'):
            raise ValueError('repair_volume_unit_unverified')
        if trimmed.get('volume_source') != source:
            raise ValueError('repair_volume_source_mismatch')
        if trimmed.get('amount_unit') not in ('CNY', 'unknown'):
            raise ValueError('repair_amount_unit_mismatch')
        if 'amounts' in trimmed and trimmed.get('amount_source') != source:
            raise ValueError('repair_amount_source_mismatch')
        item = self._prepare_remote('day', identity, trimmed,
                                    now=self._parse_timestamp(as_of))
        item['interval'] = 'day'
        self._validate_prepared_remote(item, count=len(rows), required_date=required_date,
                                       as_of=as_of)
        if any(not self._infer_final('day', bar['ts'], self._parse_timestamp(as_of)) for bar in item['bars']):
            raise ValueError('repair_bar_not_closed_as_of')
        remote = {bar['ts']:bar for bar in item['bars']}
        if not all(bool(r['is_final']) for r in item['bars']):
            raise ValueError('repair_nonfinal_source')
        if any(r['ts'] not in remote for r in rows):
            raise ValueError('repair_dates_not_covered')
        healthy = [r for r in rows if bool(r['is_final'])]
        if len(healthy) < 2:
            raise ValueError('repair_healthy_overlap_missing')
        for original in healthy:
            replacement = remote[original['ts']]
            if original['adjustment'] != self.adjustment:
                raise ValueError('repair_local_basis_unverified')
            if require_full_quantity and (original.get('volume_unit') != 'hands'
                    or not original.get('amount_available') or original.get('amount_unit') != 'CNY'
                    or not original.get('volume_source') or not original.get('amount_source')):
                raise ValueError('repair_local_quantity_incomplete')
            keys = ('open','high','low','close')
            if original.get('volume_unit') == replacement['volume_unit'] == 'hands':
                keys += ('volume',)
            for key in keys:
                if not math.isclose(float(original[key]), float(replacement[key]), rel_tol=1e-6, abs_tol=1e-8):
                    raise ValueError('repair_healthy_overlap_conflict')
            if original.get('amount_available') and replacement['amount_available']:
                if original.get('amount_unit') != replacement['amount_unit'] or not math.isclose(
                        float(original['amount']), float(replacement['amount']), rel_tol=1e-6, abs_tol=1e-8):
                    raise ValueError('repair_healthy_amount_conflict')
        for index, original in enumerate(rows):
            if bool(original['is_final']):
                continue
            replacement = remote[original['ts']]
            # Match the existing qualification consumers (13 volume / 5 amount).
            if (require_full_quantity or index >= len(rows)-13) and replacement['volume_unit'] != 'hands':
                raise ValueError('repair_volume_evidence_missing')
            if (require_full_quantity or index >= len(rows)-5) and (not replacement['amount_available'] or replacement['amount_unit'] != 'CNY' or replacement['amount_source'] != source):
                raise ValueError('repair_amount_evidence_missing')
        return item

    @staticmethod
    def _fetcher_context_kwargs(
        fetcher: Callable[..., Any],
        required_date: Optional[str],
        as_of: Optional[str],
    ) -> Dict[str, Any]:
        signature_target = getattr(fetcher, "side_effect", None)
        if not callable(signature_target):
            signature_target = fetcher
        try:
            parameters = inspect.signature(signature_target).parameters
        except (TypeError, ValueError):
            return {}
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        context = {}
        for name, value in (
            ("required_date", required_date),
            ("as_of", as_of),
        ):
            if accepts_kwargs or name in parameters:
                context[name] = value
        return context

    @classmethod
    def _validate_prepared_remote(
        cls,
        item: Mapping[str, Any],
        *,
        count: int,
        required_date: Optional[str],
        as_of: Optional[str],
    ) -> None:
        bars = list(item.get("bars") or [])
        if len(bars) < int(count):
            raise ValueError("remote kline has insufficient bars")
        latest = bars[-1]
        if required_date and (
            str(latest.get("ts") or "").split(" ", 1)[0]
            != str(required_date)
        ):
            raise ValueError("remote kline latest date mismatch")
        expected_latest_ts = cls._expected_latest_ts(
            str(item.get("interval") or ""), required_date
        )
        if (
            expected_latest_ts
            and str(latest.get("ts") or "") != expected_latest_ts
        ):
            raise ValueError("remote kline latest close bar is incomplete")
        if not bool(latest.get("is_final")):
            raise ValueError("remote kline latest bar is not final")
        if as_of:
            latest_time = cls._parse_timestamp(latest.get("ts"))
            cutoff = cls._parse_timestamp(as_of)
            if latest_time > cutoff:
                raise ValueError("remote kline latest bar exceeds as_of")

    def _shadow_diagnostics(
        self,
        interval: str,
        identity: InstrumentIdentity,
        count: int,
        kline: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if self.shadow_reader is None:
            return {}
        try:
            shadow = self.shadow_reader(interval, identity, count)
            shadow = shadow if isinstance(shadow, Mapping) else {}
            shadow_comparable = shadow.get("_shadow_comparable")
            if shadow_comparable is False:
                return {
                    "shadow_checked": True,
                    "shadow_comparable": False,
                    "shadow_mismatch": None,
                    "shadow_reason": str(
                        shadow.get("_shadow_reason") or "not_comparable"
                    ),
                    "shadow_identity": shadow.get("_shadow_identity"),
                    "shadow_expected_identity": shadow.get(
                        "_shadow_expected_identity", identity.key
                    ),
                }
            shadow_identity = shadow.get("_shadow_identity")
            if shadow_identity is not None and str(shadow_identity) != identity.key:
                return {
                    "shadow_checked": True,
                    "shadow_comparable": False,
                    "shadow_mismatch": None,
                    "shadow_reason": "identity_mismatch",
                    "shadow_identity": shadow_identity,
                    "shadow_expected_identity": identity.key,
                }
            current_dates = list((kline or {}).get("dates", []))
            shadow_dates = list(shadow.get("dates", []))
            current_closes = list((kline or {}).get("closes", []))
            shadow_closes = list(shadow.get("closes", []))
            price_max_abs_diff = None
            if len(current_closes) == len(shadow_closes) and current_closes:
                try:
                    price_max_abs_diff = max(
                        abs(float(left) - float(right))
                        for left, right in zip(current_closes, shadow_closes)
                    )
                except (TypeError, ValueError):
                    price_max_abs_diff = None
            price_comparable = (
                price_max_abs_diff is not None
                and price_max_abs_diff <= 1e-8
            )
            return {
                "shadow_checked": True,
                "shadow_comparable": True,
                "shadow_mismatch": (
                    current_dates != shadow_dates or not price_comparable
                ),
                "shadow_bars": len(shadow_dates),
                "shadow_price_max_abs_diff": price_max_abs_diff,
                "shadow_price_comparable": price_comparable,
                "shadow_identity": shadow.get("_shadow_identity", identity.key),
            }
        except Exception as exc:
            return {
                "shadow_checked": True,
                "shadow_comparable": False,
                "shadow_mismatch": True,
                "shadow_error": str(exc),
            }

    def get_many(
        self,
        interval: str,
        codes: Sequence[Any],
        count: int,
        required_date: Optional[str] = None,
        as_of: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[Any, KLineResult]:
        if interval not in ("day", "30m", "15m"):
            raise ValueError("unsupported interval: {}".format(interval))
        if int(count) <= 0:
            raise ValueError("count must be positive")
        if self.mode == "backtest" and not as_of:
            raise ValueError("backtest mode requires as_of")
        requested = []
        seen = set()
        for value in codes:
            identity = self._identity(value)
            if identity in seen:
                continue
            seen.add(identity)
            requested.append(
                (identity, value if isinstance(value, str) else identity)
            )
        identities = [identity for identity, _key in requested]
        result_keys = {identity: key for identity, key in requested}
        fetch_values = {identity: key for identity, key in requested}
        local = self._load_many(interval, identities, int(count), as_of)
        remote_failed = {}
        remote_diagnostics = {}
        fetched_remote = set()
        prepared = []
        read_only_remote = {}

        refresh_identities = [
            identity
            for identity in identities
            if self.mode == "ongoing"
            and not (self._daily_repair_pending.get(identity, ('',))[0] == str(required_date)
                     and interval == 'day' and not force_refresh)
            and self._needs_refresh(
                interval,
                local[identity],
                int(count),
                required_date,
                force_refresh,
            )
        ]
        fetcher = self.remote_fetchers.get(interval)
        if refresh_identities and fetcher is None:
            remote_failed.update((identity, True) for identity in refresh_identities)
        elif refresh_identities:
            def _fetch(identity):
                existing = local[identity]
                remote_count = (
                    int(count)
                    if getattr(fetcher, 'requires_full_window', False) is True or force_refresh or len(existing) < int(count)
                    else int(self.overlap_counts[interval])
                )
                context = self._fetcher_context_kwargs(
                    fetcher, required_date, as_of
                )
                return identity, remote_count, fetcher(
                    fetch_values[identity], remote_count, **context
                )

            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(refresh_identities))
            ) as pool:
                futures = {
                    pool.submit(_fetch, identity): identity
                    for identity in refresh_identities
                }
                for future in as_completed(futures):
                    identity = futures[future]
                    try:
                        _returned_identity, remote_count, payload = future.result()
                        if not payload:
                            remote_failed[identity] = True
                            remote_diagnostics[identity] = {
                                "fetch_failure": {
                                    "reason": "remote_empty_response",
                                    "final_adopted": False,
                                }
                            }
                            continue
                        if isinstance(payload, Mapping):
                            diagnostics = payload.get("_fetch_diagnostics")
                            if isinstance(diagnostics, Mapping):
                                remote_diagnostics[identity] = dict(diagnostics)
                        if (payload.get('schema') == 'free_minute_v1'
                                and self.raw_daily_reader is not None
                                and required_date and interval in ('30m', '15m')):
                            try:
                                references = self._load_many('day', [identity], 240, as_of)[identity]
                                target_daily = {str(row['ts'])[:10]: {
                                    **{k: row[k] for k in ('open', 'high', 'low', 'close', 'adjustment')},
                                    'is_final': bool(row['is_final']),
                                    'source': row.get('source_batch') or '',
                                } for row in references}
                                if not set(d[:10] for d in payload['dates']).issubset(target_daily):
                                    raise ValueError('missing_canonical_daily_reference')
                                raw_daily = self.raw_daily_reader(identity, required_date)
                                payload = align_daily_basis(payload, raw_daily, target_daily,
                                                            scale=int(interval[:-1]))
                                remote_diagnostics.setdefault(identity, {})['price_basis_evidence'] = payload['price_basis_evidence']
                            except (ValueError, TypeError, KeyError) as exc:
                                remote_diagnostics.setdefault(identity, {})['price_basis_failure'] = str(exc)
                        item = self._prepare_remote(interval, identity, payload)
                        item["interval"] = interval
                        self._validate_prepared_remote(
                            item,
                            count=remote_count,
                            required_date=required_date,
                            as_of=as_of,
                        )
                        if any(bar['adjustment'] != self.adjustment for bar in item['bars']):
                            # Never relabel or splice a new source into the canonical price basis.
                            read_only_remote[identity] = (item, payload)
                        else:
                            prepared.append(item)
                            fetched_remote.add(identity)
                    except Exception as exc:
                        remote_failed[identity] = True
                        diagnostics = getattr(exc, "diagnostics", None)
                        if isinstance(diagnostics, Mapping):
                            remote_diagnostics[identity] = {
                                "fetch_failure": dict(diagnostics),
                            }
                        else:
                            remote_diagnostics[identity] = {
                                "fetch_failure": {
                                    "reason": "remote_fetch_exception",
                                    "exception_type": type(exc).__name__,
                                    "final_adopted": False,
                                }
                            }
            if prepared:
                try:
                    self._write_prepared(prepared)
                except Exception:
                    for item in prepared:
                        identity = InstrumentIdentity(
                            item["asset_type"],
                            item["exchange"],
                            item["code"],
                        )
                        remote_failed[identity] = True
                        fetched_remote.discard(identity)
                else:
                    local = self._load_many(
                        interval, identities, int(count), as_of
                    )

        results = {}
        for identity in identities:
            result_key = result_keys[identity]
            rows = local[identity]
            status, stale = self._status(
                interval,
                rows,
                int(count),
                required_date,
                remote_failed=bool(remote_failed.get(identity)),
            )
            pending_repair = self._daily_repair_pending.get(identity)
            if interval == 'day' and pending_repair and pending_repair[0] == str(required_date):
                status, stale = 'repair_pending', True
            kline = self._rows_to_kline(rows, status, stale)
            if kline and interval == 'day' and pending_repair and pending_repair[0] == str(required_date):
                kline['_data_status']['nonfinal_dates'] = list(pending_repair[1])
            result_source = "market_history_db" if kline else "missing"
            if identity in read_only_remote and status != 'verified':
                item, payload = read_only_remote[identity]
                fetched_remote.add(identity)
                status, stale = 'price_basis_unverified', False
                kline = self._rows_to_kline(item['bars'][-int(count):], status, stale)
                result_source = str(payload.get('source') or 'remote')
                kline['source'] = result_source
                kline['_data_status']['source'] = result_source
                for key in ('fetched_at', 'data_time', 'schema', 'raw_volumes', 'amounts', 'amount_available', 'amount_unit', 'amount_source'):
                    if key in payload:
                        kline[key] = payload[key][-int(count):] if key in ('raw_volumes', 'amounts', 'amount_available') else payload[key]
                kline['_data_status']['degraded_reason'] = 'price_basis_unverified'
            diagnostics = {
                "remote_failed": bool(remote_failed.get(identity)),
                "mode": self.mode,
            }
            diagnostics.update(remote_diagnostics.get(identity, {}))
            diagnostics.update(
                self._shadow_diagnostics(interval, identity, int(count), kline)
            )
            result = KLineResult(
                kline=kline,
                status=status,
                source=result_source,
                stale=stale,
                fetched_remote=identity in fetched_remote,
                diagnostics=diagnostics,
            )
            results[result_key] = result
            if status == "verified" and not force_refresh:
                self._memory[
                    (
                        interval,
                        identity.key,
                        int(count),
                        required_date,
                        as_of,
                        force_refresh,
                    )
                ] = result
        return results

    def get(
        self,
        interval: str,
        code: Any,
        count: int,
        required_date: Optional[str] = None,
        as_of: Optional[str] = None,
        force_refresh: bool = False,
    ) -> KLineResult:
        identity = self._identity(code)
        result_key = code if isinstance(code, str) else identity
        key = (
            interval,
            identity.key,
            int(count),
            required_date,
            as_of,
            force_refresh,
        )
        if key in self._memory:
            return self._memory[key]
        return self.get_many(
            interval,
            [code],
            count=int(count),
            required_date=required_date,
            as_of=as_of,
            force_refresh=force_refresh,
        )[result_key]

    def list_instruments(self) -> List[Dict[str, Any]]:
        with self._open(readonly=True) as store:
            return store.list_instruments(asset_type="stock")
