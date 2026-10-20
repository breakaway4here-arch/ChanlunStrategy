"""DB-first K-line repository shared by ongoing jobs and frozen backtests."""

from __future__ import annotations

import math
import json
import os
import tempfile
import copy
import inspect
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

from .market_history_store import MarketHistoryStore
from .daily_repair_queue import DailyRepairQueue, RepairQueueError
from .daily_price_repair import DailyPriceConflict, classify_price_conflict
from .identity import InstrumentIdentity, normalize_identity
from .minute_sources import align_daily_basis
from .price_basis import (basis_sha256, canonical_daily_reference,
                          minute_price_rows, pending_minute_basis, verified_minute_basis,
                          repaired_daily_basis_failure)


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
        self.started = float(monotonic())
        self.deadline = self.started + min(20., max(0., float(seconds)))
        self.external_remaining = remaining
        self.requests = 0
        self.stocks = 0
        self.phase_seconds = {}

    def remaining(self):
        left = self.deadline - float(self.monotonic())
        if self.external_remaining is not None:
            left = min(left, float(self.external_remaining()))
        return max(0., left)

    def ensure(self):
        if self.remaining() <= 0:
            raise ValueError('daily_repair_deadline')

    @contextmanager
    def phase(self, name):
        started = float(self.monotonic())
        try:
            yield
        finally:
            self.phase_seconds[name] = self.phase_seconds.get(name, 0.) + max(
                0., float(self.monotonic()) - started)

    def take_stock(self):
        self.ensure()
        if self.stocks >= self.max_stocks:
            raise ValueError('daily_repair_stock_limit')
        self.stocks += 1

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

    def _open(self, readonly: bool, execution_budget=None) -> MarketHistoryStore:
        store = MarketHistoryStore(
            self.path,
            readonly=readonly,
            immutable=readonly and self.mode == "backtest" and self.immutable_backtest,
            execution_budget=execution_budget,
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
            "source_batches": [str(row.get('source_batch') or '') for row in rows],
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

    def _basis_receipt_path(self, identity, interval):
        return self.path.parent / 'minute_basis_v1' / (
            self.path.name + '.' + identity.key.replace('|', '-') + '.' + interval + '.json')

    def _load_basis_receipts(self, identity, interval):
        try:
            with self._basis_receipt_path(identity, interval).open() as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_basis_receipts(self, identity, interval, receipts):
        """A bounded sidecar at the existing DB cache boundary; no bar migration."""
        if self.mode != 'ongoing' or not receipts:
            return
        path = self._basis_receipt_path(identity, interval)
        with self._write_lock:
            current = self._load_basis_receipts(identity, interval)
            current.update(receipts)
            current = {date: current[date] for date in sorted(current)[-240:]}
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
                    temporary = handle.name
                    json.dump(current, handle, sort_keys=True, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

    def _producer_basis_receipts(self, interval, identity, source, aligned, as_of):
        evidence = aligned.get('price_basis_evidence')
        if not isinstance(evidence, Mapping) or source.get('adjustment') != 'unverified':
            return {}
        inputs = minute_price_rows(self._rows_to_kline(
            self._prepare_remote(interval, identity, source)['bars'], 'verified', False))
        outputs = minute_price_rows(self._rows_to_kline(
            self._prepare_remote(interval, identity, aligned)['bars'], 'verified', False))
        receipts = {}
        for date, mapping in evidence.items():
            receipt_as_of = str(as_of or datetime.now(_CN_TZ).isoformat())
            if repaired_daily_basis_failure([dict(mapping['target_daily'], ts=date)], as_of=receipt_as_of):
                continue
            raw_rows = [row for row in inputs if row['ts'][:10] == date]
            mapped_rows = [row for row in outputs if row['ts'][:10] == date]
            receipt = {'schema_version': 1, 'identity_key': identity.key, 'interval': interval,
                       'date': date, 'as_of': receipt_as_of, 'input_adjustment': 'unverified',
                       'output_adjustment': 'qfq', 'transform_applied': True,
                       'input_rows': raw_rows, 'output_rows': mapped_rows,
                       'input_sha256': basis_sha256(raw_rows), 'output_sha256': basis_sha256(mapped_rows),
                       'evidence': dict(mapping)}
            receipt['sha256'] = basis_sha256(receipt)
            receipts[date] = receipt
        return receipts

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

    @contextmanager
    def _write_guard(self, budget):
        if budget is None:
            self._write_lock.acquire()
        else:
            budget.ensure()
            if not self._write_lock.acquire(timeout=budget.remaining()):
                raise ValueError('daily_repair_deadline')
        try:
            if budget is not None:
                budget.ensure()
            yield
        finally:
            self._write_lock.release()

    def _write_prepared(self, prepared: Sequence[Mapping[str, Any]], budget=None) -> None:
        if not prepared:
            return
        with self._write_guard(budget):
            with self._open(readonly=False, execution_budget=budget) as store, (
                    store.repair_execution(budget) if budget is not None else nullcontext()):
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
        """Discover all latest-120 gaps and fairly maintain at most eight identities.

        Wide rows are loaded only for this call's targets. A durable source intent
        precedes every formal request; readonly preclose never opens the sidecar.
        """
        budget = budget or DailyRepairBudget()
        evidence_as_of = as_of or datetime.now(_CN_TZ).isoformat()
        if write and self.mode != 'ongoing':
            raise ValueError('read-only repository cannot write repairs')
        with budget.phase('discovery'):
            with self._open(readonly=True) as store:
                discovery = store.discover_daily_nonfinal(required_date, budget)
        gaps = discovery['gaps']
        overrides, expected_overrides, repaired = {}, {}, []
        details, targets = [], []
        for gap in gaps:
            instrument = gap['instrument']
            bad_dates = [r['ts'] for r in gap['bad_rows']]
            detail = dict(code=instrument['code'], exchange=instrument['exchange'],
                nonfinal_dates=bad_dates, reasons=[])
            details.append(detail)
            try:
                identity = self._identity(instrument)
            except (TypeError, ValueError):
                detail['reasons'].append('invalid_identity')
                continue
            # Only the bad rows and whether today's close is available form the
            # input version. A healthy daily tail cannot reset every old failure.
            # This is a maintenance version, not a price-basis proof. Invalid
            # legacy values still need a stable version so one bad stock can be
            # repaired or rejected by the existing validators without aborting discovery.
            version_rows = [{key: ({'nonfinite_float':repr(value)}
                if isinstance(value, float) and not math.isfinite(value) else value)
                for key, value in row.items()} for row in gap['bad_rows']]
            signature = basis_sha256(dict(identity=identity.key, bad_rows=version_rows,
                required_close_available=bool(self._infer_final('day', str(required_date),
                    self._parse_timestamp(evidence_as_of)))))
            targets.append(dict(gap=gap, detail=detail, identity=identity,
                key=identity.key, signature=signature, nonfinal_dates=bad_dates))
        queue_error = ''
        cooldown_count, unknown_count = 0, 0
        attempted_ids = []
        queue_context = (DailyRepairQueue(self.path, budget=budget) if write and discovery['complete']
            and budget.remaining() > 0 and budget.stocks < budget.max_stocks
            and budget.requests < budget.max_requests else nullcontext(None))
        try:
            with budget.phase('queue'):
                queue = queue_context.__enter__()
            try:
                with budget.phase('queue'):
                    if queue is not None:
                        queue.reconcile(targets)
                now = time.time()
                if queue is not None:
                    targets.sort(key=lambda t: queue.state['entries'][t['key']]['sequence'])
                for target in targets:
                    gap, detail, identity = target['gap'], target['detail'], target['identity']
                    if not discovery['complete']:
                        detail['reasons'].append('repair_discovery_incomplete')
                        continue
                    if queue_error:
                        detail['reasons'].append(queue_error)
                        continue
                    entry = queue.state['entries'][target['key']] if queue is not None else None
                    if entry is not None and entry['status'] == 'inflight':
                        detail['reasons'].append('repair_attempt_unknown')
                        unknown_count += 1
                        continue
                    if entry is not None and float(entry['next_attempt']) > now:
                        detail['reasons'].extend(['repair_cooldown'] + list(entry.get('reasons') or []))
                        detail['next_attempt_at'] = entry['next_attempt']
                        cooldown_count += 1
                        continue
                    if (budget.stocks >= budget.max_stocks or budget.remaining() <= 0
                            or budget.requests >= budget.max_requests):
                        detail['reasons'].append('repair_budget_exhausted')
                        continue
                    if gap['count'] < 60 or gap['latest_date'] != str(required_date):
                        detail['reasons'].append('local_qualification_window_incomplete')
                        continue
                    budget.take_stock()
                    iid = int(gap['instrument']['instrument_id'])
                    attempted_ids.append(iid)
                    try:
                        with budget.phase('read'):
                            with self._open(readonly=True) as store, store.repair_execution(budget):
                                rows = store.query_bars_many('day', [iid],
                                    as_of=required_date, limit=120)[iid]
                        budget.ensure()
                    except Exception as exc:
                        detail['reasons'].append(str(exc))
                        continue
                    # Recheck discovery against the exact snapshot used as CAS input.
                    bad_dates = [r['ts'] for r in rows if not bool(r['is_final'])]
                    bad_versions = [dict(r) for r in rows if not bool(r['is_final'])]
                    if bad_versions != gap['bad_rows']:
                        detail['reasons'].append('repair_discovery_changed')
                        continue
                    adopted = False
                    sent = False
                    intent_saved = False
                    if not providers:
                        detail['reasons'].append('repair_provider_unavailable')
                    for source, fetcher in list(providers)[:2]:
                        if budget.remaining() <= 0 or budget.requests >= budget.max_requests:
                            detail['reasons'].append('repair_budget_exhausted')
                            break
                        try:
                            if queue is not None:
                                with budget.phase('queue'):
                                    budget.ensure()
                                    queue.intent(target['key'], source, time.time())
                                    intent_saved = True
                            budget.ensure()
                            sent = True
                            with budget.phase('request'):
                                payload = fetcher(identity, len(rows) + int(bool(fetch_buffer)),
                                    request_budget=budget)
                            budget.ensure()
                            with budget.phase('validation'):
                                item = self._prepare_daily_repair(identity, rows, payload, source,
                                    required_date, evidence_as_of, require_full_quantity)
                                replacements = {bar['ts']:bar for bar in item['bars'] if bar['ts'] in bad_dates}
                                if set(replacements) != set(bad_dates):
                                    raise ValueError('repair_dates_not_covered')
                            budget.ensure()
                            with budget.phase('write' if write else 'readonly_check'):
                                if write:
                                    self._write_prepared([dict(item, bars=list(replacements.values()),
                                        repair_expected_rows=rows)], budget=budget)
                                    self._memory.clear()
                                else:
                                    with self._open(readonly=True) as store, store.repair_execution(budget):
                                        self._check_repair_rows(store, iid, rows, require_nonfinal=False)
                                    budget.ensure()
                            merged = [dict(r, **replacements[r['ts']]) if r['ts'] in replacements else dict(r)
                                      for r in rows]
                            overrides[iid] = merged
                            expected_overrides[iid] = rows
                            repaired.append(dict(detail, source=source))
                            detail['_repaired'] = True
                            adopted = True
                            break
                        except RepairQueueError as exc:
                            queue_error = str(exc)
                            detail['reasons'].append(queue_error)
                            break
                        except _RepairRowsChanged as exc:
                            detail['reasons'].append('{}:{}'.format(source, str(exc)))
                            break
                        except Exception as exc:
                            detail['reasons'].append('{}:{}'.format(source, str(exc)))
                            if isinstance(exc, DailyPriceConflict):
                                detail.setdefault('price_conflicts', []).append(dict(exc.diagnostic, source=source))
                    if (queue is not None and (sent or intent_saved) and not queue_error
                            and budget.remaining() > 0):
                        try:
                            with budget.phase('queue'):
                                # At the deadline the durable intent stays unknown;
                                # do not start receipt persistence outside the budget.
                                queue.finish(target['key'], adopted, detail['reasons'], time.time())
                        except RepairQueueError as exc:
                            queue_error = str(exc)
                            if not adopted:
                                detail['reasons'].append(queue_error)
            finally:
                queue_context.__exit__(None, None, None)
        except RepairQueueError as exc:
            queue_error = str(exc)
            for detail in details:
                if not detail['reasons']:
                    detail['reasons'].append(queue_error)
        pending = [detail for detail in details if not detail.pop('_repaired', False)]
        # Only attempted identities can have changed during this call. Re-read
        # their lightweight gaps; never reload all pending OHLCV windows.
        if attempted_ids and budget.remaining() > 0:
            with budget.phase('recheck'):
                with self._open(readonly=True) as store:
                    latest = store.discover_daily_nonfinal(required_date, budget, attempted_ids)
            if latest['complete']:
                by_identity = {(g['instrument']['exchange'], g['instrument']['code']):
                    [r['ts'] for r in g['bad_rows']] for g in latest['gaps']}
                attempted_keys = {(t['identity'].exchange, t['identity'].code) for t in targets
                    if int(t['gap']['instrument']['instrument_id']) in attempted_ids}
                for detail in pending:
                    key = (detail['exchange'], detail['code'])
                    if key in attempted_keys:
                        actual_dates = by_identity.get(key, [])
                        if actual_dates != detail['nonfinal_dates']:
                            detail['initial_nonfinal_dates'] = detail['nonfinal_dates']
                            detail['nonfinal_dates'] = actual_dates
        if write:
            self._memory.clear()
            if discovery['complete']:
                self._daily_repair_pending = {}
            for detail in pending:
                if not detail['nonfinal_dates']:
                    continue
                try:
                    identity = InstrumentIdentity('stock', detail['exchange'], detail['code'])
                except ValueError:
                    continue
                self._daily_repair_pending[identity] = (str(required_date), detail['nonfinal_dates'])
        complete = discovery['complete']
        return dict(daily_rows_override=overrides, daily_rows_expected=expected_overrides,
            diagnostics=dict(nonfinal_stock_count=len(gaps) if complete else None,
                discovered_nonfinal_stock_count=len(gaps), discovery_complete=complete,
                discovery_reason=discovery['reason'], discovery_scanned_count=discovery['scanned'],
                valid_identity_count=len(targets) if complete else None,
                invalid_identity_count=len(gaps)-len(targets) if complete else None,
                discovered_valid_identity_count=len(targets),
                discovered_invalid_identity_count=len(gaps)-len(targets),
                repaired_count=len(repaired), repaired=repaired,
                pending_count=len(pending) if complete else None, pending=pending,
                known_pending_count=len(pending), queue_error=queue_error,
                cooldown_count=cooldown_count, unknown_attempt_count=unknown_count,
                stock_attempts=budget.stocks, http_requests=budget.requests,
                phase_seconds=dict(budget.phase_seconds),
                elapsed_seconds=max(0., float(budget.monotonic())-budget.started)))

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
                    if key in ('open','high','low','close'):
                        raise DailyPriceConflict('repair_healthy_overlap_conflict',
                            classify_price_conflict(healthy, [remote[r['ts']] for r in healthy]))
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
        final_validator=None,
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
            ("final_validator", final_validator),
        ):
            if name == 'final_validator' and value is None:
                continue
            if accepts_kwargs or name in parameters:
                context[name] = value
        return context

    def _minute_final_validator(self, interval, identity, count, required_date, as_of):
        references = {}

        def validate(payload):
            aligned = payload
            if payload.get('schema') == 'free_minute_v1':
                if payload.get('adjustment') != 'unverified':
                    raise ValueError('already_adjusted_or_invalid_scale')
                if payload.get('symbol') != identity.exchange.lower() + identity.code:
                    raise ValueError('minute_identity_mismatch')
                if payload.get('volume_unit') != 'hands':
                    raise ValueError('minute_volume_unit_unverified')
                if self.raw_daily_reader is not None and required_date:
                    if not references.get('loaded'):
                        references['loaded'] = True
                        try:
                            rows = self._load_many('day', [identity], 240, as_of)[identity]
                            target = {str(row['ts'])[:10]: {
                                **{k: row[k] for k in ('open', 'high', 'low', 'close', 'adjustment')},
                                'is_final': bool(row['is_final']), 'source': row.get('source_batch') or '',
                            } for row in rows}
                            raw = copy.deepcopy(self.raw_daily_reader(identity, required_date))
                            if not isinstance(raw, Mapping) or not raw:
                                raise ValueError('missing_raw_daily_reference')
                            if any(not isinstance(v, Mapping) for v in raw.values()):
                                raise ValueError('invalid_raw_daily_reference')
                            references['raw'] = MappingProxyType({k: MappingProxyType(dict(v)) for k,v in raw.items()})
                            references['target'] = MappingProxyType({k: MappingProxyType(v) for k,v in target.items()})
                        except Exception as exc:
                            reason = str(exc)
                            references['failure'] = reason if reason in ('missing_raw_daily_reference',
                                'invalid_raw_daily_reference') else 'raw_daily_reference_unavailable'
                    if references.get('failure'):
                        raise ValueError(references['failure'])
                    if not set(d[:10] for d in payload['dates']).issubset(references['target']):
                        raise ValueError('missing_canonical_daily_reference')
                    aligned = align_daily_basis(payload,
                        {k:dict(v) for k,v in references['raw'].items()},
                        {k:dict(v) for k,v in references['target'].items()}, scale=int(interval[:-1]))
            item = self._prepare_remote(interval, identity, aligned)
            item['interval'] = interval
            self._validate_prepared_remote(item, count=count, required_date=required_date, as_of=as_of)
            if any(not bar['is_final'] for bar in item['bars']):
                raise ValueError('minute_nonfinal_bar')
            if any(bar['adjustment'] != self.adjustment for bar in item['bars']):
                raise ValueError('price_basis_unverified')
            return aligned, item
        return validate

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
        producer_receipts = {}
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
                validator = self._minute_final_validator(interval, identity, remote_count, required_date, as_of) if interval in ('30m','15m') else None
                def check_source(payload):
                    validator(payload)
                    return payload
                context = self._fetcher_context_kwargs(
                    fetcher, required_date, as_of, check_source if validator else None)
                return identity, remote_count, fetcher(
                    fetch_values[identity], remote_count, **context
                ), validator

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
                        _returned_identity, remote_count, payload, validator = future.result()
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
                        if validator is not None:
                            try:
                                original_payload = payload
                                payload, _checked = validator(payload)
                                if payload.get('price_basis_evidence'):
                                    remote_diagnostics.setdefault(identity, {})['price_basis_evidence'] = payload['price_basis_evidence']
                                    producer_receipts[identity] = self._producer_basis_receipts(
                                        interval, identity, original_payload, payload, as_of)
                            except (ValueError, TypeError, KeyError) as exc:
                                reason = str(exc)
                                remote_diagnostics.setdefault(identity, {})['price_basis_failure'] = (
                                    reason if re.fullmatch(r'[a-z_]+(?::\d{4}-\d{2}-\d{2})?', reason)
                                    else 'final_validation_rejected')
                                safe_readonly = (payload.get('schema') == 'free_minute_v1'
                                    and payload.get('adjustment') == 'unverified'
                                    and reason.startswith(('raw_daily_conflict:', 'missing_canonical_daily_reference',
                                        'missing_final_daily_reference:', 'unverified_daily_reference:',
                                        'missing_raw_daily_reference', 'invalid_raw_daily_reference', 'raw_daily_reference_unavailable',
                                        'incomplete_day:', 'non_affine_daily_reference:', 'indeterminate_flat_day:',
                                        'invalid_basis_mapping:', 'price_basis_unverified')))
                                if (reason == 'price_basis_unverified'
                                        and payload.get('schema') != 'free_minute_v1'
                                        and payload.get('adjustment') in ('raw', 'unverified')
                                        and payload.get('volume_unit') in ('hands', 'unknown')
                                        and payload.get('symbol') in (None, identity.exchange.lower()+identity.code)):
                                    safe_readonly = True
                                if not safe_readonly:
                                    raise
                                readonly = self._prepare_remote(interval, identity, payload)
                                readonly['interval'] = interval
                                self._validate_prepared_remote(readonly, count=remote_count,
                                                               required_date=required_date, as_of=as_of)
                                if not all(bar['is_final'] for bar in readonly['bars']):
                                    raise ValueError('minute_nonfinal_bar')
                                read_only_remote[identity] = (readonly, payload)
                                continue
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
                            remote_diagnostics.setdefault(identity, {}).update({
                                "fetch_failure": dict(diagnostics),
                            })
                        else:
                            remote_diagnostics.setdefault(identity, {}).update({
                                "fetch_failure": {
                                    "reason": remote_diagnostics.get(identity, {}).get('price_basis_failure') or "remote_fetch_exception",
                                    "exception_type": type(exc).__name__,
                                    "final_adopted": False,
                                }
                            })
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
                    for identity in fetched_remote:
                        try:
                            self._save_basis_receipts(identity, interval, producer_receipts.get(identity, {}))
                        except (OSError, ValueError):
                            remote_diagnostics.setdefault(identity, {})['price_basis_receipt_failure'] = 'receipt_write_failed'
                    local = self._load_many(
                        interval, identities, int(count), as_of
                    )

        minute_daily_rows = (self._load_many('day', identities, 240, as_of)
                             if interval in ('30m', '15m') else {})
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
            if (interval == 'day' and pending_repair and pending_repair[0] == str(required_date)
                    and status == 'verified' and pending_repair[1]):
                covered = {row['ts']:row for row in rows}
                resolved = True
                for bad_date in pending_repair[1]:
                    row = covered.get(bad_date)
                    if not row or not bool(row['is_final']) or row['adjustment'] != self.adjustment:
                        resolved = False
                        break
                    try:
                        MarketHistoryStore._validated_bar(row, self.adjustment)
                    except (TypeError, ValueError):
                        resolved = False
                        break
                if resolved:
                    self._daily_repair_pending.pop(identity, None)
                    pending_repair = None
                    for cached in list(self._memory):
                        if cached[0] == 'day' and cached[1] == identity.key:
                            del self._memory[cached]
            if interval == 'day' and pending_repair and pending_repair[0] == str(required_date):
                status, stale = 'repair_pending', True
            basis_failure = repaired_daily_basis_failure(rows, as_of=as_of) if interval == 'day' else None
            if basis_failure:
                status, stale = 'price_basis_unverified', False
            kline = self._rows_to_kline(rows, status, stale)
            if kline and basis_failure:
                kline['_data_status']['degraded_reason'] = basis_failure
            reference_failure = False
            if kline is not None and interval == 'day':
                try:
                    kline['canonical_daily'] = canonical_daily_reference(identity, rows)
                except (TypeError, ValueError, KeyError, OverflowError):
                    # Reference evidence is optional; a bad identity's reference
                    # cannot discard the existing K-line or healthy batch members.
                    reference_failure = True
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
            if reference_failure:
                diagnostics['canonical_daily_reference'] = dict(
                    status='pending', reason='invalid_daily_reference')
            if kline is not None and interval in ('30m', '15m'):
                daily_rows = minute_daily_rows[identity]
                try:
                    reference = canonical_daily_reference(identity, daily_rows)
                except (TypeError, ValueError, KeyError, OverflowError):
                    proof = pending_minute_basis('invalid_daily_reference', identity.key, interval, as_of)
                else:
                    proof = verified_minute_basis(identity, interval, kline, reference,
                        self._load_basis_receipts(identity, interval), as_of)
                kline['minute_to_daily'] = proof
                diagnostics['minute_to_daily'] = proof
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
        if interval == 'day' and key in self._memory:
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
