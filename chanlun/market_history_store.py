"""SQLite-backed canonical market history storage.

The store deliberately keeps market identity, adjustment policy and finality in
the database contract so ongoing jobs and backtests cannot silently reinterpret
the same primary key.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote


BAR_TABLES = {
    "day": "bars_day",
    "30m": "bars_30m",
    "15m": "bars_15m",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(value: Optional[Mapping[str, Any]]) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=False, sort_keys=True)


def _row_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


class MarketHistoryStore:
    """Read/write facade for the unified market history SQLite database."""

    def __init__(self, path: Any, readonly: bool = False, immutable: bool = False):
        self.path = Path(path).expanduser().resolve()
        self.readonly = bool(readonly)
        self.immutable = bool(immutable)
        if self.immutable and not self.readonly:
            raise ValueError("immutable mode requires readonly=True")

        if self.readonly:
            uri = "file:{}?mode=ro{}".format(
                quote(str(self.path), safe="/"),
                "&immutable=1" if self.immutable else "",
            )
            self.connection = sqlite3.connect(uri, uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if not self.readonly:
            self._initialize_schema()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self) -> None:
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None

    def _require_writable(self) -> None:
        if self.readonly:
            raise PermissionError("market history store is readonly")

    def _write_scope(self):
        if self.connection.in_transaction:
            return nullcontext(self.connection)
        return self.connection

    def _initialize_schema(self) -> None:
        bar_schema = """
            instrument_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            amount REAL NOT NULL,
            adjustment TEXT NOT NULL,
            is_final INTEGER NOT NULL DEFAULT 0 CHECK (is_final IN (0, 1)),
            source_batch TEXT NOT NULL DEFAULT '',
            ingest_run_id TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (instrument_id, ts),
            FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
        """
        with self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_type TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE (asset_type, exchange, code)
                );

                CREATE TABLE IF NOT EXISTS stock_meta_asof (
                    instrument_id INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, as_of),
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS trade_calendar (
                    exchange TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    is_open INTEGER NOT NULL CHECK (is_open IN (0, 1)),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (exchange, trade_date)
                );

                CREATE TABLE IF NOT EXISTS ingest_runs (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    rows_written INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS shard_manifests (
                    run_id TEXT NOT NULL,
                    shard_id INTEGER NOT NULL,
                    shard_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    checksum TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, shard_id)
                );

                CREATE TABLE IF NOT EXISTS bar_table_settings (
                    table_name TEXT PRIMARY KEY,
                    adjustment TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            for table in BAR_TABLES.values():
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS {} ({})".format(table, bar_schema)
                )
                self.connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_{}_ts_instrument "
                    "ON {} (ts, instrument_id)".format(table, table)
                )

    @staticmethod
    def _table(interval: str) -> str:
        try:
            return BAR_TABLES[str(interval)]
        except KeyError:
            raise ValueError("unsupported bar interval: {}".format(interval))

    def upsert_instrument(
        self,
        asset_type: str,
        exchange: str,
        code: str,
        name: str = "",
    ) -> int:
        self._require_writable()
        identity = tuple(str(value).strip() for value in (asset_type, exchange, code))
        if not all(identity):
            raise ValueError("asset_type, exchange and code are required")
        now = _utc_now()
        with self._write_scope():
            self.connection.execute(
                """
                INSERT INTO instruments(asset_type, exchange, code, name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(asset_type, exchange, code) DO UPDATE SET
                    name=CASE WHEN excluded.name <> '' THEN excluded.name ELSE instruments.name END,
                    updated_at=excluded.updated_at
                """,
                identity + (str(name or ""), now),
            )
        row = self.resolve_instrument(*identity)
        return int(row["instrument_id"])

    def resolve_instrument(
        self, asset_type: str, exchange: str, code: str
    ) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            """
            SELECT instrument_id, asset_type, exchange, code, name, updated_at
            FROM instruments WHERE asset_type=? AND exchange=? AND code=?
            """,
            (str(asset_type).strip(), str(exchange).strip(), str(code).strip()),
        ).fetchone()
        return _row_dict(row)

    def upsert_stock_meta(
        self, instrument_id: int, as_of: str, metadata: Mapping[str, Any]
    ) -> None:
        self._require_writable()
        if not str(as_of).strip():
            raise ValueError("as_of is required")
        with self._write_scope():
            self.connection.execute(
                """
                INSERT INTO stock_meta_asof(instrument_id, as_of, metadata_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(instrument_id, as_of) DO UPDATE SET
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (instrument_id, str(as_of), _json_dumps(metadata), _utc_now()),
            )

    def query_stock_meta(
        self, instrument_id: int, as_of: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        sql = "SELECT as_of, metadata_json FROM stock_meta_asof WHERE instrument_id=?"
        params = [instrument_id]
        if as_of is not None:
            sql += " AND as_of<=?"
            params.append(str(as_of))
        sql += " ORDER BY as_of DESC LIMIT 1"
        row = self.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        payload = json.loads(row["metadata_json"])
        payload["as_of"] = row["as_of"]
        return payload

    def upsert_trade_calendar(self, exchange: str, trade_date: str, is_open: bool) -> None:
        self._require_writable()
        with self._write_scope():
            self.connection.execute(
                """
                INSERT INTO trade_calendar(exchange, trade_date, is_open, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(exchange, trade_date) DO UPDATE SET
                    is_open=excluded.is_open, updated_at=excluded.updated_at
                """,
                (str(exchange), str(trade_date), int(bool(is_open)), _utc_now()),
            )

    def is_trading_day(self, exchange: str, trade_date: str) -> Optional[bool]:
        row = self.connection.execute(
            "SELECT is_open FROM trade_calendar WHERE exchange=? AND trade_date=?",
            (str(exchange), str(trade_date)),
        ).fetchone()
        return None if row is None else bool(row["is_open"])

    @staticmethod
    def _finite_number(value: Any, field: str, positive: bool = False) -> float:
        if isinstance(value, bool):
            raise ValueError("{} must be numeric".format(field))
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("{} must be numeric".format(field))
        if not math.isfinite(number):
            raise ValueError("{} must be finite".format(field))
        if positive and number <= 0:
            raise ValueError("{} must be > 0".format(field))
        return number

    @classmethod
    def _validated_bar(
        cls, bar: Mapping[str, Any], default_adjustment: Optional[str]
    ) -> Dict[str, Any]:
        ts = str(bar.get("ts") or "").strip()
        if not ts:
            raise ValueError("bar ts is required")
        values = {
            field: cls._finite_number(bar.get(field), field, positive=True)
            for field in ("open", "high", "low", "close")
        }
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("bar high violates OHLC bounds")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("bar low violates OHLC bounds")
        volume = cls._finite_number(bar.get("volume", 0), "volume")
        amount = cls._finite_number(bar.get("amount", 0), "amount")
        if volume < 0 or amount < 0:
            raise ValueError("volume and amount must be non-negative")
        adjustment = str(bar.get("adjustment") or default_adjustment or "").strip()
        if not adjustment:
            raise ValueError("bar adjustment is required")
        return {
            "ts": ts,
            "open": values["open"],
            "high": values["high"],
            "low": values["low"],
            "close": values["close"],
            "volume": volume,
            "amount": amount,
            "adjustment": adjustment,
            "is_final": int(bool(bar.get("is_final", False))),
            "source_batch": str(bar.get("source_batch") or ""),
            "ingest_run_id": bar.get("ingest_run_id"),
        }

    def get_canonical_adjustment(self, interval: str) -> Optional[str]:
        table = self._table(interval)
        row = self.connection.execute(
            "SELECT adjustment FROM bar_table_settings WHERE table_name=?", (table,)
        ).fetchone()
        return None if row is None else str(row["adjustment"])

    def upsert_bars(
        self,
        interval: str,
        instrument_id: int,
        bars: Iterable[Mapping[str, Any]],
        adjustment: Optional[str] = None,
        ingest_run_id: Optional[str] = None,
    ) -> int:
        self._require_writable()
        table = self._table(interval)
        materialized = [self._validated_bar(bar, adjustment) for bar in bars]
        if not materialized:
            return 0
        adjustments = {bar["adjustment"] for bar in materialized}
        if len(adjustments) != 1:
            raise ValueError("a bar batch must use one canonical adjustment")
        batch_adjustment = next(iter(adjustments))
        canonical = self.get_canonical_adjustment(interval)
        if canonical is not None and canonical != batch_adjustment:
            raise ValueError(
                "adjustment mismatch for {}: expected {}, got {}".format(
                    table, canonical, batch_adjustment
                )
            )

        now = _utc_now()
        sql = """
            INSERT INTO {table}(
                instrument_id, ts, open, high, low, close, volume, amount,
                adjustment, is_final, source_batch, ingest_run_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_id, ts) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                adjustment=excluded.adjustment, is_final=excluded.is_final,
                source_batch=excluded.source_batch,
                ingest_run_id=excluded.ingest_run_id, updated_at=excluded.updated_at
            WHERE {table}.is_final = 0 OR excluded.is_final = 1
        """.format(table=table)
        with self._write_scope():
            if canonical is None:
                self.connection.execute(
                    """
                    INSERT INTO bar_table_settings(table_name, adjustment, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(table_name) DO NOTHING
                    """,
                    (table, batch_adjustment, now),
                )
                canonical = self.get_canonical_adjustment(interval)
                if canonical != batch_adjustment:
                    raise ValueError("adjustment mismatch for {}".format(table))
            for bar in materialized:
                self.connection.execute(
                    sql,
                    (
                        instrument_id, bar["ts"], bar["open"], bar["high"],
                        bar["low"], bar["close"], bar["volume"], bar["amount"],
                        bar["adjustment"], bar["is_final"], bar["source_batch"],
                        ingest_run_id or bar["ingest_run_id"], now,
                    ),
                )
        return len(materialized)

    def query_bars(
        self,
        interval: str,
        instrument_id: int,
        start: Optional[str] = None,
        end: Optional[str] = None,
        as_of: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        table = self._table(interval)
        clauses = ["instrument_id=?"]
        params = [instrument_id]
        if start is not None:
            clauses.append("ts>=?")
            params.append(str(start))
        upper = min(str(end), str(as_of)) if end is not None and as_of is not None else end or as_of
        if upper is not None:
            clauses.append("ts<=?")
            params.append(str(upper))
        sql = "SELECT * FROM {} WHERE {} ORDER BY ts".format(table, " AND ".join(clauses))
        if limit is not None:
            if int(limit) <= 0:
                return []
            sql = "SELECT * FROM ({}) ORDER BY ts DESC LIMIT ?".format(sql)
            params.append(int(limit))
            rows = self.connection.execute(sql, params).fetchall()
            return [dict(row) for row in reversed(rows)]
        return [dict(row) for row in self.connection.execute(sql, params).fetchall()]

    def query_bars_many(
        self,
        interval: str,
        instrument_ids: Sequence[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
        as_of: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[int, List[Dict[str, Any]]]:
        return {
            int(instrument_id): self.query_bars(
                interval, int(instrument_id), start=start, end=end, as_of=as_of, limit=limit
            )
            for instrument_id in instrument_ids
        }

    def query_cross_section(
        self,
        interval: str,
        ts: str,
        instrument_ids: Optional[Sequence[int]] = None,
        as_of: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        table = self._table(interval)
        target = str(ts)
        if as_of is not None and target > str(as_of):
            return []
        clauses = ["ts=?"]
        params = [target]
        if instrument_ids is not None:
            ids = [int(value) for value in instrument_ids]
            if not ids:
                return []
            clauses.append("instrument_id IN ({})".format(",".join("?" for _ in ids)))
            params.extend(ids)
        sql = "SELECT * FROM {} WHERE {} ORDER BY instrument_id".format(
            table, " AND ".join(clauses)
        )
        return [dict(row) for row in self.connection.execute(sql, params).fetchall()]

    def start_ingest_run(
        self,
        run_id: str,
        mode: str,
        started_at: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._require_writable()
        with self._write_scope():
            self.connection.execute(
                """
                INSERT INTO ingest_runs(run_id, mode, status, started_at, metadata_json)
                VALUES (?, ?, 'running', ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    mode=excluded.mode, metadata_json=excluded.metadata_json
                """,
                (str(run_id), str(mode), started_at or _utc_now(), _json_dumps(metadata)),
            )

    def finish_ingest_run(
        self,
        run_id: str,
        status: str,
        finished_at: Optional[str] = None,
        rows_written: int = 0,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._require_writable()
        with self._write_scope():
            cursor = self.connection.execute(
                """
                UPDATE ingest_runs SET status=?, finished_at=?, rows_written=?,
                    metadata_json=CASE WHEN ? IS NULL THEN metadata_json ELSE ? END
                WHERE run_id=?
                """,
                (
                    str(status), finished_at or _utc_now(), int(rows_written),
                    None if metadata is None else 1, _json_dumps(metadata), str(run_id),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("unknown ingest run: {}".format(run_id))

    def get_ingest_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return _row_dict(self.connection.execute(
            "SELECT * FROM ingest_runs WHERE run_id=?", (str(run_id),)
        ).fetchone())

    def upsert_shard_manifest(
        self,
        run_id: str,
        shard_id: int,
        shard_count: int,
        status: str,
        row_count: int = 0,
        checksum: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._require_writable()
        with self._write_scope():
            self.connection.execute(
                """
                INSERT INTO shard_manifests(
                    run_id, shard_id, shard_count, status, row_count, checksum,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, shard_id) DO UPDATE SET
                    shard_count=excluded.shard_count, status=excluded.status,
                    row_count=excluded.row_count, checksum=excluded.checksum,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                (
                    str(run_id), int(shard_id), int(shard_count), str(status),
                    int(row_count), str(checksum), _json_dumps(metadata), _utc_now(),
                ),
            )

    def list_shard_manifests(self, run_id: str) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM shard_manifests WHERE run_id=? ORDER BY shard_id", (str(run_id),)
        ).fetchall()
        return [dict(row) for row in rows]

    def merge_staging_database(self, staging_path: Any) -> Dict[str, int]:
        """Idempotently merge a staging database using logical instrument identity."""
        self._require_writable()
        source = MarketHistoryStore(staging_path, readonly=True, immutable=True)
        counts = {"instruments": 0, "bars": 0, "ingest_runs": 0, "manifests": 0}
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            id_map = {}
            instruments = source.connection.execute(
                "SELECT * FROM instruments ORDER BY instrument_id"
            ).fetchall()
            for row in instruments:
                target_id = self.upsert_instrument(
                    row["asset_type"], row["exchange"], row["code"], row["name"]
                )
                id_map[int(row["instrument_id"])] = target_id
                counts["instruments"] += 1

            for row in source.connection.execute("SELECT * FROM stock_meta_asof"):
                self.upsert_stock_meta(
                    id_map[int(row["instrument_id"])], row["as_of"], json.loads(row["metadata_json"])
                )
            for row in source.connection.execute("SELECT * FROM trade_calendar"):
                self.upsert_trade_calendar(row["exchange"], row["trade_date"], bool(row["is_open"]))

            for interval, table in BAR_TABLES.items():
                for row in source.connection.execute(
                    "SELECT * FROM {} ORDER BY instrument_id, ts".format(table)
                ):
                    payload = dict(row)
                    payload.pop("instrument_id", None)
                    payload.pop("updated_at", None)
                    self.upsert_bars(
                        interval,
                        id_map[int(row["instrument_id"])],
                        [payload],
                        adjustment=row["adjustment"],
                        ingest_run_id=row["ingest_run_id"],
                    )
                    counts["bars"] += 1

            for row in source.connection.execute("SELECT * FROM ingest_runs"):
                self.start_ingest_run(
                    row["run_id"], row["mode"], row["started_at"], json.loads(row["metadata_json"])
                )
                if row["status"] != "running" or row["finished_at"]:
                    self.finish_ingest_run(
                        row["run_id"], row["status"], row["finished_at"], row["rows_written"],
                        json.loads(row["metadata_json"]),
                    )
                counts["ingest_runs"] += 1
            for row in source.connection.execute("SELECT * FROM shard_manifests"):
                self.upsert_shard_manifest(
                    row["run_id"], row["shard_id"], row["shard_count"], row["status"],
                    row["row_count"], row["checksum"], json.loads(row["metadata_json"]),
                )
                counts["manifests"] += 1
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            source.close()
        return counts
