#!/usr/bin/env python3
"""Apply an audited market-history candidate manifest to an authorized DB.

The command is deliberately dry-run by default.  Applying requires both
``--apply`` and exactly one temporary/formal authorization.  Formal writes are
restricted to one allowlisted runtime path and require an explicit reference.
Every row is checked against the manifest's old fingerprint before one
transaction updates the database.  A mismatch rolls back the complete batch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chanlun.identity import normalize_identity


BAR_TABLES = {"day": "bars_day", "30m": "bars_30m", "15m": "bars_15m"}
STABLE_FIELDS = (
    "instrument_id", "ts", "open", "high", "low", "close", "volume",
    "amount", "adjustment", "is_final", "source_batch", "ingest_run_id",
    "updated_at",
)
BAR_FIELDS = (
    "instrument_id", "ts", "open", "high", "low", "close", "volume",
    "amount", "volume_unit", "volume_raw_unit", "volume_source", "amount_unit",
    "amount_source", "amount_available", "adjustment", "is_final", "source_batch",
    "ingest_run_id", "updated_at",
)
METADATA_COLUMNS = {
    "volume_unit": "TEXT NOT NULL DEFAULT 'unknown'",
    "volume_raw_unit": "TEXT NOT NULL DEFAULT 'unknown'",
    "volume_source": "TEXT NOT NULL DEFAULT ''",
    "amount_unit": "TEXT NOT NULL DEFAULT 'unknown'",
    "amount_source": "TEXT NOT NULL DEFAULT ''",
    "amount_available": "INTEGER NOT NULL DEFAULT 1",
}
_FORMAL_DB_PATH = Path(
    "/Users/yangfan/yf_source/ChanlunStrategy/.cache/chanlun/market_history.sqlite"
).resolve()


class RepairManifestError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: row.get(field) for field in STABLE_FIELDS}


def stable_row_sha256(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _stable_payload(row),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _semantic_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        field: row.get(field)
        for field in BAR_FIELDS
        if field != "updated_at"
    }


def _same_semantics(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _semantic_row(left) == _semantic_row(right)


def _read_manifest(path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    header = None
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RepairManifestError(
                    "invalid manifest JSON at line {}: {}".format(line_number, exc)
                )
            if header is None:
                if item.get("record_type") != "manifest_header":
                    raise RepairManifestError("manifest header is missing")
                header = item
            else:
                if item.get("record_type") != "bar_candidate":
                    raise RepairManifestError(
                        "unsupported record at line {}".format(line_number)
                    )
                records.append(item)
    if header is None:
        raise RepairManifestError("manifest is empty")
    expected_count = int(header.get("candidate_bar_count") or len(records))
    if expected_count != len(records):
        raise RepairManifestError(
            "candidate count mismatch: header={} rows={}".format(
                expected_count, len(records)
            )
        )
    return header, records


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_temp_apply_path(path: Path) -> None:
    resolved = path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    allowed_roots = [temp_root, Path("/private/tmp").resolve()]
    if not any(_is_below(resolved, root) for root in allowed_roots):
        raise RepairManifestError(
            "apply is restricted to a temporary DB below {}".format(
                ", ".join(str(root) for root in allowed_roots)
            )
        )
    text = str(resolved)
    if ".cache/chanlun" in text or "frozen-market-history" in text:
        raise RepairManifestError("formal or frozen database path is forbidden")


def _assert_not_frozen_evidence(path: Path) -> None:
    if "frozen-market-history" in str(path.resolve()).lower():
        raise RepairManifestError(
            "formal apply rejects frozen evidence paths: {}".format(path)
        )


def _assert_formal_apply_path(
    path: Path, authorized_formal_path: Optional[Any]
) -> None:
    resolved = path.resolve()
    if authorized_formal_path is None:
        raise RepairManifestError(
            "--authorized-formal-path is required with --allow-formal-db"
        )
    authorized = Path(authorized_formal_path).expanduser().resolve()
    if resolved != authorized:
        raise RepairManifestError(
            "database does not equal the authorized formal path: {} != {}".format(
                resolved, authorized
            )
        )
    if resolved != _FORMAL_DB_PATH.resolve():
        raise RepairManifestError(
            "formal database is not the allowlisted production path: {}".format(
                resolved
            )
        )


def _authorize_apply(
    database_path: Path,
    *,
    allow_temporary_db: bool,
    allow_formal_db: bool,
    authorized_formal_path: Optional[Any],
    authorization_reference: Optional[str],
    evidence_paths: Iterable[Path] = (),
) -> Tuple[str, Optional[str]]:
    if bool(allow_temporary_db) == bool(allow_formal_db):
        raise RepairManifestError(
            "apply requires exactly one of --allow-temporary-db or "
            "--allow-formal-db"
        )
    if allow_temporary_db:
        _assert_temp_apply_path(database_path)
        return "temporary", None

    _assert_formal_apply_path(database_path, authorized_formal_path)
    reference = str(authorization_reference or "").strip()
    if not reference:
        raise RepairManifestError(
            "a nonempty authorization reference (--authorization-reference) "
            "is required for formal apply"
        )
    for evidence_path in evidence_paths:
        _assert_not_frozen_evidence(evidence_path)
    return "formal", reference


def _connect(path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:{}?mode=ro".format(str(path).replace("?", "%3F"))
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_metadata_columns(connection: sqlite3.Connection, table: str) -> None:
    existing = {
        str(row[1]) for row in connection.execute("PRAGMA table_info({})".format(table))
    }
    for name, declaration in METADATA_COLUMNS.items():
        if name not in existing:
            connection.execute(
                "ALTER TABLE {} ADD COLUMN {} {}".format(
                    table, name, declaration
                )
            )


def _preflight_rollback_path(path: Path) -> None:
    """Check that a new rollback artifact can be created without overwriting one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RepairManifestError(
            "rollback artifact already exists; choose a new path: {}".format(path)
        )
    try:
        descriptor = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        os.close(descriptor)
        path.unlink()
    except OSError as exc:
        try:
            path.unlink()
        except OSError:
            pass
        raise RepairManifestError(
            "rollback artifact path is not writable: {}".format(exc)
        )


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably create an evidence file and refuse to replace old evidence."""
    encoded = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
    except OSError as exc:
        raise RepairManifestError(
            "cannot create rollback artifact: {}".format(exc)
        )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _resolve_instrument(
    connection: sqlite3.Connection,
    identity: Mapping[str, Any],
    *,
    allow_legacy_delete_identity: bool = False,
) -> sqlite3.Row:
    try:
        canonical = normalize_identity(identity)
    except (TypeError, ValueError):
        if not allow_legacy_delete_identity:
            raise
        asset_type = str(identity.get("asset_type") or "").strip().lower()
        exchange = str(identity.get("exchange") or "").strip().upper()
        code = str(identity.get("code") or "").strip()
        if (
            asset_type != "stock"
            or exchange not in ("SH", "SZ", "BJ")
            or len(code) != 6
            or any(char < "0" or char > "9" for char in code)
        ):
            raise RepairManifestError("legacy delete identity is invalid")
        canonical = type("LegacyIdentity", (), {
            "asset_type": asset_type,
            "exchange": exchange,
            "code": code,
        })()
    row = connection.execute(
        """
        SELECT instrument_id, asset_type, exchange, code
        FROM instruments WHERE asset_type=? AND exchange=? AND code=?
        """,
        (
            canonical.asset_type,
            canonical.exchange,
            canonical.code,
        ),
    ).fetchone()
    if row is None:
        raise RepairManifestError(
            "target instrument is missing: {}|{}|{}".format(
                identity.get("asset_type"),
                identity.get("exchange"),
                identity.get("code"),
            )
        )
    expected_id = int(identity.get("instrument_id") or 0)
    if expected_id and int(row["instrument_id"]) != expected_id:
        raise RepairManifestError(
            "instrument id mismatch for {}: {} != {}".format(
                identity.get("code"), row["instrument_id"], expected_id
            )
        )
    return row


def _current_row(
    connection: sqlite3.Connection, table: str, instrument_id: int, ts: str
) -> Optional[Dict[str, Any]]:
    row = connection.execute(
        "SELECT * FROM {} WHERE instrument_id=? AND ts=?".format(table),
        (instrument_id, str(ts)),
    ).fetchone()
    return dict(row) if row is not None else None


def _validate_record(record: Mapping[str, Any]) -> None:
    identity = record.get("identity") or {}
    try:
        instrument_id = int(identity.get("instrument_id") or 0)
    except (TypeError, ValueError):
        instrument_id = 0
    if instrument_id <= 0:
        raise RepairManifestError("candidate identity requires instrument_id")
    action = str(record.get("repair_action") or record.get("action") or "")
    delete_action = action in (
        "delete", "delete_identity_rows", "identity_quarantine_delete"
    )
    if delete_action:
        asset_type = str(identity.get("asset_type") or "").strip().lower()
        exchange = str(identity.get("exchange") or "").strip().upper()
        code = str(identity.get("code") or "").strip()
        if (
            asset_type != "stock"
            or exchange not in ("SH", "SZ", "BJ")
            or len(code) != 6
            or any(char < "0" or char > "9" for char in code)
        ):
            raise RepairManifestError("delete candidate identity is invalid")
        expected_identity_key = "{}|{}|{}|{}".format(
            asset_type, exchange, code, identity.get("instrument_id")
        )
        if str(record.get("identity_key") or "") != expected_identity_key:
            raise RepairManifestError("candidate identity_key disagrees with identity")
        if record.get("interval") not in BAR_TABLES:
            raise RepairManifestError("unsupported candidate interval")
        if record.get("new_row") is not None:
            raise RepairManifestError("delete candidate must not have new_row")
        if (
            not record.get("expected_old_present")
            or not record.get("expected_old_row_sha256")
        ):
            raise RepairManifestError("delete candidate requires an old-row CAS hash")
        return
    try:
        canonical = normalize_identity(identity)
    except (TypeError, ValueError) as exc:
        raise RepairManifestError("candidate identity is invalid: {}".format(exc))
    if canonical.asset_type != "stock":
        raise RepairManifestError("candidate is outside stock scope")
    expected_identity_key = "{}|{}|{}|{}".format(
        canonical.asset_type,
        canonical.exchange,
        canonical.code,
        identity.get("instrument_id"),
    )
    if str(record.get("identity_key") or "") != expected_identity_key:
        raise RepairManifestError("candidate identity_key disagrees with identity")
    if record.get("interval") not in BAR_TABLES:
        raise RepairManifestError("unsupported candidate interval")
    new_row = record.get("new_row")
    if not isinstance(new_row, Mapping):
        raise RepairManifestError("candidate new_row is missing")
    repair_scope = str(record.get("repair_scope") or "volume").strip().lower()
    if repair_scope not in ("volume", "price_only"):
        raise RepairManifestError("unsupported candidate repair_scope")
    volume_unit = str(new_row.get("volume_unit") or "")
    if repair_scope == "volume" and volume_unit != "hands":
        raise RepairManifestError("candidate volume must be canonical hands")
    if repair_scope == "price_only" and volume_unit not in ("hands", "unknown"):
        raise RepairManifestError("price-only candidate volume unit is invalid")
    raw_volume_unit = str(new_row.get("volume_raw_unit") or "unknown").strip().lower()
    if raw_volume_unit not in ("hands", "shares", "unknown"):
        raise RepairManifestError("candidate raw volume unit is invalid")
    if volume_unit == "hands" and not str(new_row.get("volume_source") or "").strip():
        raise RepairManifestError("canonical volume requires a source")
    if new_row.get("instrument_id") is not None:
        try:
            if int(new_row.get("instrument_id")) != instrument_id:
                raise RepairManifestError("candidate instrument id disagrees with identity")
        except (TypeError, ValueError):
            raise RepairManifestError("candidate instrument id is invalid")
    if new_row.get("ts") is not None and str(new_row.get("ts")) != str(record.get("ts")):
        raise RepairManifestError("candidate timestamp disagrees with manifest")
    if str(new_row.get("adjustment") or "") != "qfq":
        raise RepairManifestError("candidate adjustment must be canonical qfq")
    amount_available = new_row.get("amount_available")
    if not (
        isinstance(amount_available, bool)
        or type(amount_available) is int and amount_available in (0, 1)
    ):
        raise RepairManifestError("candidate amount_available must be bool or 0/1")
    amount_unit = str(new_row.get("amount_unit") or "unknown").strip().upper()
    if amount_unit not in ("CNY", "UNKNOWN"):
        raise RepairManifestError("candidate amount unit is invalid")
    try:
        amount = float(new_row.get("amount"))
    except (TypeError, ValueError):
        raise RepairManifestError("candidate amount must be numeric")
    if not math.isfinite(amount):
        raise RepairManifestError("candidate amount must be finite")
    if amount < 0 or (bool(amount_available) and amount <= 0):
        raise RepairManifestError("candidate amount availability/value is invalid")
    if record.get("expected_old_present") and not record.get("expected_old_row_sha256"):
        raise RepairManifestError("present old row requires a CAS hash")


def _all_records_already_applied(
    database_path: Path, records: Iterable[Mapping[str, Any]]
) -> bool:
    """Permit a rerun only when every target row already equals its candidate."""
    try:
        connection = _connect(database_path, readonly=True)
        for record in records:
            _validate_record(record)
            table = BAR_TABLES[record["interval"]]
            identity = record["identity"]
            action = str(
                record.get("repair_action") or record.get("action") or ""
            )
            instrument = _resolve_instrument(
                connection,
                identity,
                allow_legacy_delete_identity=action
                in ("delete", "delete_identity_rows", "identity_quarantine_delete"),
            )
            current = _current_row(
                connection, table, int(instrument["instrument_id"]), record["ts"]
            )
            action = str(
                record.get("repair_action") or record.get("action") or ""
            )
            if action in (
                "delete", "delete_identity_rows", "identity_quarantine_delete"
            ):
                if current is not None:
                    connection.close()
                    return False
                continue
            if current is None or not _same_semantics(current, record["new_row"]):
                connection.close()
                return False
        connection.close()
        return True
    except Exception:
        try:
            connection.close()
        except Exception:
            pass
        return False


def _upsert_candidate(
    connection: sqlite3.Connection,
    table: str,
    row: Mapping[str, Any],
    *,
    preserve_updated_at: bool = False,
) -> None:
    columns = ", ".join(BAR_FIELDS)
    placeholders = ", ".join("?" for _ in BAR_FIELDS)
    updates = ", ".join(
        "{0}=excluded.{0}".format(field)
        for field in BAR_FIELDS
        if field not in ("instrument_id", "ts")
    )
    values = dict(row)
    if not preserve_updated_at or not values.get("updated_at"):
        values["updated_at"] = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    connection.execute(
        "INSERT INTO {table}({columns}) VALUES ({placeholders}) "
        "ON CONFLICT(instrument_id, ts) DO UPDATE SET {updates}".format(
            table=table, columns=columns, placeholders=placeholders, updates=updates
        ),
        tuple(values.get(field) for field in BAR_FIELDS),
    )


def _storage_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Fill metadata defaults when rolling back a pre-R05 legacy row."""
    result = dict(row)
    result.setdefault("volume_unit", "unknown")
    result.setdefault("volume_raw_unit", "unknown")
    result.setdefault("volume_source", "")
    result.setdefault("amount_unit", "unknown")
    result.setdefault("amount_source", "")
    if "amount_available" not in result:
        try:
            result["amount_available"] = int(float(result.get("amount", 0)) > 0)
        except (TypeError, ValueError):
            result["amount_available"] = 0
    return result


def inspect_or_apply(
    database_path: Any,
    manifest_path: Any,
    manifest_sha256: str,
    *,
    apply: bool = False,
    allow_temporary_db: bool = False,
    allow_formal_db: bool = False,
    authorized_formal_path: Optional[Any] = None,
    authorization_reference: Optional[str] = None,
    rollback_path: Optional[Any] = None,
) -> Dict[str, Any]:
    db = Path(database_path).expanduser().resolve()
    manifest = Path(manifest_path).expanduser().resolve()
    if not manifest.is_file() or not db.is_file():
        raise RepairManifestError("database and manifest must exist")
    actual_manifest_sha = sha256_file(manifest)
    if actual_manifest_sha != str(manifest_sha256):
        raise RepairManifestError(
            "manifest hash mismatch: {} != {}".format(
                actual_manifest_sha, manifest_sha256
            )
        )
    header, records = _read_manifest(manifest)
    expected_db_sha = str(header.get("base_db_sha256") or "")
    actual_db_sha = sha256_file(db)
    rollback = (
        Path(rollback_path).expanduser().resolve()
        if rollback_path is not None
        else None
    )
    authorization_mode = None
    formal_reference = None
    if apply:
        authorization_mode, formal_reference = _authorize_apply(
            db,
            allow_temporary_db=allow_temporary_db,
            allow_formal_db=allow_formal_db,
            authorized_formal_path=authorized_formal_path,
            authorization_reference=authorization_reference,
            evidence_paths=[path for path in (manifest, rollback) if path is not None],
        )
    if expected_db_sha and actual_db_sha != expected_db_sha:
        if _all_records_already_applied(db, records):
            output = {
                "database": str(db),
                "manifest": str(manifest),
                "manifest_sha256": actual_manifest_sha,
                "base_db_sha256": actual_db_sha,
                "mode": "idempotent",
                "candidate_rows": len(records),
                "planned_rows": 0,
                "idempotent_rows": len(records),
                "applied": False,
                "rollback_rows": 0,
            }
            if authorization_mode == "formal":
                output["authorization_mode"] = authorization_mode
                output["authorization_reference"] = formal_reference
            return output
        raise RepairManifestError(
            "base database hash mismatch: {} != {}".format(
                actual_db_sha, expected_db_sha
            )
        )
    if apply:
        if rollback_path is None:
            raise RepairManifestError(
                "--rollback-out is required with --apply"
            )
    if apply and rollback is not None:
        _preflight_rollback_path(rollback)
    connection = _connect(db, readonly=not apply)
    rollback_rows: List[Dict[str, Any]] = []
    planned = 0
    idempotent = 0
    try:
        if apply:
            connection.execute("BEGIN IMMEDIATE")
            for table in set(BAR_TABLES[record["interval"]] for record in records):
                _ensure_metadata_columns(connection, table)
        for record in records:
            _validate_record(record)
            identity = record["identity"]
            table = BAR_TABLES[record["interval"]]
            action = str(
                record.get("repair_action") or record.get("action") or ""
            )
            delete_action = action in (
                "delete", "delete_identity_rows", "identity_quarantine_delete"
            )
            instrument = _resolve_instrument(
                connection,
                identity,
                allow_legacy_delete_identity=delete_action,
            )
            current = _current_row(
                connection, table, int(instrument["instrument_id"]), record["ts"]
            )
            expected_hash = record.get("expected_old_row_sha256")
            if delete_action and current is None:
                idempotent += 1
                continue
            if (
                not delete_action
                and current is not None
                and _same_semantics(current, record["new_row"])
            ):
                idempotent += 1
                continue
            if expected_hash is None:
                if current is not None:
                    raise RepairManifestError(
                        "CAS expected missing but row exists: {} {}".format(
                            record["identity_key"], record["ts"]
                        )
                    )
            elif current is None or stable_row_sha256(current) != expected_hash:
                raise RepairManifestError(
                    "CAS mismatch: {} {}".format(
                        record["identity_key"], record["ts"]
                    )
                )
            rollback_rows.append(
                {
                    "identity": identity,
                    "identity_key": record["identity_key"],
                    "interval": record["interval"],
                    "repair_scope": record.get("repair_scope") or "volume",
                    "ts": record["ts"],
                    "old_row": current,
                    "old_row_sha256": stable_row_sha256(current) if current else None,
                    "new_row": (
                        dict(record["new_row"])
                        if isinstance(record.get("new_row"), Mapping)
                        else None
                    ),
                }
            )
            planned += 1
            if apply:
                if delete_action:
                    connection.execute(
                        "DELETE FROM {} WHERE instrument_id=? AND ts=?".format(table),
                        (int(instrument["instrument_id"]), str(record["ts"])),
                    )
                else:
                    new_row = dict(record["new_row"])
                    new_row["instrument_id"] = int(instrument["instrument_id"])
                    new_row["ts"] = record["ts"]
                    _upsert_candidate(connection, table, new_row)
        rollback_payload = {
            "schema_version": "market-history-repair-rollback-v2",
            "status": "ready_for_rollback",
            "manifest_sha256": actual_manifest_sha,
            "database_before_sha256": actual_db_sha,
            "candidate_rows": len(records),
            "planned_rows": planned,
            "rows": rollback_rows,
        }
        if authorization_mode == "formal":
            rollback_payload["authorization_mode"] = authorization_mode
            rollback_payload["authorization_reference"] = formal_reference
        if apply:
            # The rollback artifact is durable before the transaction commits.
            _write_json_exclusive(rollback, rollback_payload)
            connection.commit()
    except Exception:
        if apply:
            connection.rollback()
        raise
    finally:
        connection.close()
    output = {
        "database": str(db),
        "manifest": str(manifest),
        "manifest_sha256": actual_manifest_sha,
        "base_db_sha256": actual_db_sha,
        "mode": "apply" if apply else "dry_run",
        "candidate_rows": len(records),
        "planned_rows": planned,
        "idempotent_rows": idempotent,
        "applied": bool(apply),
        "rollback_rows": len(rollback_rows),
    }
    if rollback is not None and not apply:
        rollback.parent.mkdir(parents=True, exist_ok=True)
        _write_json_exclusive(rollback, rollback_payload)
        output["rollback_path"] = str(rollback)
    elif rollback is not None:
        output["rollback_path"] = str(rollback)
    if authorization_mode == "formal":
        output["authorization_mode"] = authorization_mode
        output["authorization_reference"] = formal_reference
    return output


def _read_rollback(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RepairManifestError("invalid rollback artifact: {}".format(exc))
    if not isinstance(payload, dict):
        raise RepairManifestError("rollback artifact must be an object")
    if payload.get("schema_version") != "market-history-repair-rollback-v2":
        raise RepairManifestError("unsupported rollback artifact version")
    if not payload.get("manifest_sha256"):
        raise RepairManifestError("rollback artifact has no manifest hash")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RepairManifestError("rollback artifact rows must be a list")
    return payload


def _validate_rollback_item(item: Mapping[str, Any]) -> None:
    if not isinstance(item, Mapping):
        raise RepairManifestError("rollback row must be an object")
    identity = item.get("identity") or {}
    new_row = item.get("new_row")
    synthetic = {
        "identity": identity,
        "identity_key": item.get("identity_key"),
        "interval": item.get("interval"),
        "ts": item.get("ts"),
        "repair_action": "delete" if new_row is None else "replace",
        "repair_scope": item.get("repair_scope") or "volume",
        "expected_old_present": True,
        "expected_old_row_sha256": item.get("old_row_sha256") or "rollback",
        "new_row": new_row,
    }
    _validate_record(synthetic)


def rollback_repair(
    database_path: Any,
    rollback_path: Any,
    *,
    apply: bool = False,
    allow_temporary_db: bool = False,
    allow_formal_db: bool = False,
    authorized_formal_path: Optional[Any] = None,
    authorization_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore rows with a reverse CAS; dry-run is the default."""
    db = Path(database_path).expanduser().resolve()
    rollback_file = Path(rollback_path).expanduser().resolve()
    if not db.is_file() or not rollback_file.is_file():
        raise RepairManifestError("database and rollback artifact must exist")
    authorization_mode = None
    formal_reference = None
    if apply:
        authorization_mode, formal_reference = _authorize_apply(
            db,
            allow_temporary_db=allow_temporary_db,
            allow_formal_db=allow_formal_db,
            authorized_formal_path=authorized_formal_path,
            authorization_reference=authorization_reference,
            evidence_paths=(rollback_file,),
        )
    payload = _read_rollback(rollback_file)
    if authorization_mode == "formal":
        receipt_reference = str(
            payload.get("authorization_reference") or ""
        ).strip()
        if not receipt_reference or receipt_reference != formal_reference:
            raise RepairManifestError(
                "formal rollback authorization reference does not match receipt"
            )
    records = list(payload.get("rows") or [])
    connection = _connect(db, readonly=not apply)
    planned = 0
    idempotent = 0
    try:
        if apply:
            connection.execute("BEGIN IMMEDIATE")
            for table in set(BAR_TABLES[item.get("interval")] for item in records):
                _ensure_metadata_columns(connection, table)
        for item in records:
            _validate_rollback_item(item)
            table = BAR_TABLES[item["interval"]]
            instrument = _resolve_instrument(
                connection,
                item["identity"],
                allow_legacy_delete_identity=item.get("new_row") is None,
            )
            current = _current_row(
                connection,
                table,
                int(instrument["instrument_id"]),
                item["ts"],
            )
            old_row = item.get("old_row")
            if old_row is not None and not isinstance(old_row, Mapping):
                raise RepairManifestError("rollback old_row must be an object or null")
            old_storage = _storage_row(old_row) if old_row is not None else None
            if old_storage is not None:
                if int(old_storage.get("instrument_id") or 0) != int(instrument["instrument_id"]):
                    raise RepairManifestError("rollback old_row instrument mismatch")
                if str(old_storage.get("ts") or "") != str(item["ts"]):
                    raise RepairManifestError("rollback old_row timestamp mismatch")
            new_row = item.get("new_row")
            if old_storage is None and current is None:
                idempotent += 1
                continue
            if (
                old_storage is not None
                and current is not None
                and _same_semantics(current, old_storage)
            ):
                idempotent += 1
                continue
            if new_row is None:
                if current is not None:
                    raise RepairManifestError(
                        "reverse CAS mismatch: {} {}".format(
                            item["identity_key"], item["ts"]
                        )
                    )
            elif current is None or not _same_semantics(current, new_row):
                raise RepairManifestError(
                    "reverse CAS mismatch: {} {}".format(
                        item["identity_key"], item["ts"]
                    )
                )
            planned += 1
            if apply:
                if old_storage is None:
                    connection.execute(
                        "DELETE FROM {} WHERE instrument_id=? AND ts=?".format(table),
                        (int(instrument["instrument_id"]), str(item["ts"])),
                    )
                else:
                    _upsert_candidate(
                        connection,
                        table,
                        old_storage,
                        preserve_updated_at=True,
                    )
        if apply:
            connection.commit()
    except Exception:
        if apply:
            connection.rollback()
        raise
    finally:
        connection.close()
    output = {
        "database": str(db),
        "rollback": str(rollback_file),
        "manifest_sha256": payload["manifest_sha256"],
        "mode": "rollback_apply" if apply else "rollback_dry_run",
        "candidate_rows": len(records),
        "planned_rows": planned,
        "idempotent_rows": idempotent,
        "applied": bool(apply),
    }
    if authorization_mode == "formal":
        output["authorization_mode"] = authorization_mode
        output["authorization_reference"] = formal_reference
    return output


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--rollback-file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-temporary-db", action="store_true")
    parser.add_argument("--allow-formal-db", action="store_true")
    parser.add_argument("--authorized-formal-path")
    parser.add_argument("--authorization-reference")
    parser.add_argument("--rollback-out")
    args = parser.parse_args(argv)
    if args.rollback:
        if not args.rollback_file:
            parser.error("--rollback-file is required with --rollback")
        result = rollback_repair(
            args.db,
            args.rollback_file,
            apply=args.apply,
            allow_temporary_db=args.allow_temporary_db,
            allow_formal_db=args.allow_formal_db,
            authorized_formal_path=args.authorized_formal_path,
            authorization_reference=args.authorization_reference,
        )
    else:
        if not args.manifest or not args.manifest_sha256:
            parser.error("--manifest and --manifest-sha256 are required")
        result = inspect_or_apply(
            args.db,
            args.manifest,
            args.manifest_sha256,
            apply=args.apply,
            allow_temporary_db=args.allow_temporary_db,
            allow_formal_db=args.allow_formal_db,
            authorized_formal_path=args.authorized_formal_path,
            authorization_reference=args.authorization_reference,
            rollback_path=args.rollback_out,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
