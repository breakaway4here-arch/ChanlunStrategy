#!/usr/bin/env python3
"""Build one conflict-checked, frozen-base market-history repair manifest.

The R01/R05 candidate files were intentionally produced independently.  They
must not be applied in separate copies and then treated as one migration: a
later copy no longer has the frozen database hash.  This utility validates
their complete operation keys against one frozen database, adds exact CAS
deletions for the known untrusted tail/minute rows, and emits one JSONL
manifest for a single apply/rollback rehearsal.

It only reads the supplied SQLite snapshot and candidate manifests.  It never
opens a database for writing.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.apply_market_history_repair import (  # noqa: E402
    BAR_TABLES,
    STABLE_FIELDS,
    _read_manifest,
    sha256_file,
    stable_row_sha256,
)


TAIL_DATES = ("2026-09-10", "2026-09-11")
TAIL_MINUTE_INTERVAL = "30m"


class JointManifestError(RuntimeError):
    pass


def _identity_tuple(identity: Mapping[str, Any]) -> Tuple[Any, ...]:
    return tuple(
        identity.get(field)
        for field in ("asset_type", "exchange", "code", "instrument_id")
    )


def _operation_key(record: Mapping[str, Any]) -> Tuple[Any, ...]:
    identity = record.get("identity") or {}
    return (
        record.get("identity_key"),
        record.get("interval"),
        str(record.get("ts")),
    )


def _stable_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    mapping = dict(row)
    return {field: mapping.get(field) for field in STABLE_FIELDS}


def _manifest_component(path: Path, name: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    header, records = _read_manifest(path)
    return {
        "name": name,
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": len(records),
        "identity_count": len(
            {_identity_tuple(record.get("identity") or {}) for record in records}
        ),
        "schema_version": header.get("schema_version"),
        "candidate_scope": header.get("candidate_scope"),
        "base_db_sha256": header.get("base_db_sha256"),
    }, records


def _read_tail_rows(
    db_path: Path,
    price_records: Sequence[Mapping[str, Any]],
    snapshot_sha256: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    identities = {}
    for record in price_records:
        identity = dict(record.get("identity") or {})
        if (
            identity.get("asset_type") == "stock"
            and identity.get("exchange") == "SZ"
        ):
            identities[_identity_tuple(identity)] = identity
    if not identities:
        raise JointManifestError("price manifest has no stock|SZ identities")

    connection = sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for identity in identities.values():
            row = connection.execute(
                """
                SELECT instrument_id, asset_type, exchange, code
                FROM instruments
                WHERE instrument_id=?
                """,
                (int(identity["instrument_id"]),),
            ).fetchone()
            if row is None or tuple(row[field] for field in (
                "asset_type", "exchange", "code", "instrument_id"
            )) != _identity_tuple(identity):
                raise JointManifestError(
                    "price identity does not resolve exactly in frozen DB: {}".format(
                        identity
                    )
                )

        rows: List[Dict[str, Any]] = []
        tail_placeholders = ",".join("?" for _ in TAIL_DATES)
        for identity in sorted(identities.values(), key=lambda item: item["code"]):
            instrument_id = int(identity["instrument_id"])
            day_rows = connection.execute(
                """
                SELECT * FROM bars_day
                WHERE instrument_id=? AND ts IN ({})
                ORDER BY ts
                """.format(tail_placeholders),
                (instrument_id,) + TAIL_DATES,
            ).fetchall()
            for row in day_rows:
                stable = _stable_row(row)
                rows.append(
                    {
                        "expected_old_present": True,
                        "expected_old_row": stable,
                        "expected_old_row_sha256": stable_row_sha256(dict(row)),
                        "identity": dict(identity),
                        "identity_key": "stock|SZ|{}|{}".format(
                            identity["code"], identity["instrument_id"]
                        ),
                        "interval": "day",
                        "new_row": None,
                        "reason": (
                            "2026-09-10/11 tail is outside the verified price "
                            "bundle cutoff; invalidate exact cached rows until a "
                            "source-backed replacement arrives"
                        ),
                        "record_type": "bar_candidate",
                        "repair_action": "delete_identity_rows",
                        "repair_scope": "tail_invalidation",
                        "schema_version": "chanlun-r05-tail-invalidation-v1",
                        "source": {
                            "snapshot": str(db_path),
                            "snapshot_sha256": snapshot_sha256,
                            "trusted_replacement": None,
                            "verified_cutoff": "2026-09-09",
                        },
                        "ts": str(row["ts"]),
                    }
                )

            minute_rows = connection.execute(
                """
                SELECT * FROM bars_30m
                WHERE instrument_id=?
                ORDER BY ts
                """,
                (instrument_id,),
            ).fetchall()
            for row in minute_rows:
                stable = _stable_row(row)
                rows.append(
                    {
                        "expected_old_present": True,
                        "expected_old_row": stable,
                        "expected_old_row_sha256": stable_row_sha256(dict(row)),
                        "identity": dict(identity),
                        "identity_key": "stock|SZ|{}|{}".format(
                            identity["code"], identity["instrument_id"]
                        ),
                        "interval": TAIL_MINUTE_INTERVAL,
                        "new_row": None,
                        "reason": (
                            "legacy SZ minute rows are stale pre-cutoff material "
                            "without a verified replacement; invalidate exact rows "
                            "so consumers return missing/pending"
                        ),
                        "record_type": "bar_candidate",
                        "repair_action": "delete_identity_rows",
                        "repair_scope": "minute_invalidation",
                        "schema_version": "chanlun-r05-tail-invalidation-v1",
                        "source": {
                            "snapshot": str(db_path),
                            "snapshot_sha256": snapshot_sha256,
                            "trusted_replacement": None,
                            "verified_cutoff": "2026-09-09",
                        },
                        "ts": str(row["ts"]),
                    }
                )
    finally:
        connection.close()

    component = {
        "name": "tail_invalidation",
        "path": None,
        "sha256": None,
        "rows": len(rows),
        "identity_count": len(
            {_identity_tuple(record["identity"]) for record in rows}
        ),
        "schema_version": "chanlun-r05-tail-invalidation-v1",
        "candidate_scope": (
            "exact 2026-09-10/11 day rows plus all stale 30m rows for "
            "the 39 repaired SZ identities"
        ),
        "base_db_sha256": snapshot_sha256,
        "interval_counts": dict(Counter(record["interval"] for record in rows)),
    }
    return component, rows


def _validate_no_conflicts(
    components: Sequence[Tuple[Dict[str, Any], Sequence[Mapping[str, Any]]]]
) -> Dict[str, Any]:
    operation_owner: Dict[Tuple[Any, ...], str] = {}
    identity_owner: Dict[Tuple[Any, ...], str] = {}
    instrument_owner: Dict[Any, Tuple[Any, ...]] = {}
    instrument_component: Dict[Any, str] = {}
    duplicates = []
    identity_conflicts = []
    identity_overlaps = set()
    for component, records in components:
        name = str(component["name"])
        for record in records:
            key = _operation_key(record)
            previous = operation_owner.get(key)
            if previous is not None:
                duplicates.append({"key": list(key), "components": [previous, name]})
            operation_owner[key] = name
            identity = _identity_tuple(record.get("identity") or {})
            previous_identity = identity_owner.get(identity)
            if previous_identity is not None and previous_identity != name:
                identity_overlaps.add(identity)
            identity_owner[identity] = name
            instrument_id = identity[3]
            previous_instrument = instrument_owner.get(instrument_id)
            if previous_instrument is not None and previous_instrument != identity:
                identity_conflicts.append(
                    {
                        "instrument_id": instrument_id,
                        "identities": [list(previous_instrument), list(identity)],
                        "components": [instrument_component.get(instrument_id), name],
                    }
                )
            instrument_owner[instrument_id] = identity
            instrument_component[instrument_id] = name
    if duplicates or identity_conflicts:
        raise JointManifestError(
            "joint manifest conflict: duplicate_operations={} identity_conflicts={}".format(
                len(duplicates), len(identity_conflicts)
            )
        )
    return {
        "duplicate_operation_count": len(duplicates),
        "identity_conflict_count": len(identity_conflicts),
        "identity_overlap_count": len(identity_overlaps),
        "operation_count": len(operation_owner),
        "identity_count": len(identity_owner),
    }


def build_joint_manifest(
    database_path: Any,
    d4_manifest: Any,
    price_manifest: Any,
    sh_manifest: Any,
    tail_manifest_path: Any,
    joint_manifest_path: Any,
    summary_path: Any,
) -> Dict[str, Any]:
    database = Path(database_path).expanduser().resolve()
    paths = {
        "d4_volume": Path(d4_manifest).expanduser().resolve(),
        "stock_sz_price": Path(price_manifest).expanduser().resolve(),
        "stock_sh_delete": Path(sh_manifest).expanduser().resolve(),
    }
    expected_db_sha = sha256_file(database)
    loaded = []
    component_records = {}
    for name, path in paths.items():
        component, records = _manifest_component(path, name)
        if component.get("base_db_sha256") != expected_db_sha:
            raise JointManifestError(
                "{} base hash mismatch: {} != {}".format(
                    name, component.get("base_db_sha256"), expected_db_sha
                )
            )
        loaded.append((component, records))
        component_records[name] = records

    tail_component, tail_records = _read_tail_rows(
        database, component_records["stock_sz_price"], expected_db_sha
    )
    tail_path = Path(tail_manifest_path).expanduser().resolve()
    tail_path.parent.mkdir(parents=True, exist_ok=True)
    tail_header = {
        "base_db_path": str(database),
        "base_db_sha256": expected_db_sha,
        "candidate_bar_count": len(tail_records),
        "candidate_identity_count": tail_component["identity_count"],
        "candidate_scope": tail_component["candidate_scope"],
        "interval_counts": tail_component["interval_counts"],
        "record_type": "manifest_header",
        "schema_version": "chanlun-r05-tail-invalidation-v1",
        "status": "candidate_only; not_applied",
        "tail_dates": list(TAIL_DATES),
        "trusted_replacement": None,
    }
    _write_jsonl(tail_path, tail_header, tail_records)
    tail_component["path"] = str(tail_path)
    tail_component["sha256"] = sha256_file(tail_path)

    loaded_with_tail = loaded + [(tail_component, tail_records)]
    conflict_summary = _validate_no_conflicts(loaded_with_tail)
    ordered = [
        next(item for item in loaded_with_tail if item[0]["name"] == name)
        for name in ("tail_invalidation", "stock_sh_delete", "stock_sz_price", "d4_volume")
    ]
    all_records: List[Dict[str, Any]] = []
    for component, records in ordered:
        for record in records:
            copied = dict(record)
            copied["joint_component"] = component["name"]
            all_records.append(copied)

    all_identities = {
        _identity_tuple(record.get("identity") or {}) for record in all_records
    }
    joint_header = {
        "base_db_path": str(database),
        "base_db_sha256": expected_db_sha,
        "candidate_bar_count": len(all_records),
        "candidate_identity_count": len(all_identities),
        "candidate_scope": (
            "single frozen-base apply: invalidate untrusted tail/minutes, "
            "delete wrong SH stock bars, rebuild verified SZ prices, then "
            "replace source-backed daily volume"
        ),
        "components": [component for component, _ in ordered],
        "conflict_check": conflict_summary,
        "record_type": "manifest_header",
        "repair_order": [component["name"] for component, _ in ordered],
        "schema_version": "chanlun-r05-r01-joint-candidate-v1",
        "status": "candidate_only; not_applied",
        "formal_db_writes": False,
        "frozen_db_writes": False,
        "tail_policy": {
            "cutoff": "2026-09-09",
            "replacement": None,
            "consumer_status_after_apply": "missing_or_pending_until_source_backed_refill",
        },
    }
    joint_path = Path(joint_manifest_path).expanduser().resolve()
    joint_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(joint_path, joint_header, all_records)

    summary = {
        "base_db_path": str(database),
        "base_db_sha256": expected_db_sha,
        "components": [component for component, _ in ordered],
        "conflict_check": conflict_summary,
        "joint_manifest": str(joint_path),
        "joint_manifest_sha256": sha256_file(joint_path),
        "tail_manifest": str(tail_path),
        "tail_manifest_sha256": sha256_file(tail_path),
        "rows_by_component": {
            component["name"]: component["rows"] for component, _ in ordered
        },
        "rows_by_interval": dict(
            Counter(record["interval"] for record in all_records)
        ),
        "status": "candidate_only; one temp-copy rehearsal required",
        "source_expansion": False,
        "unresolved": [
            "2026-09-10/11 daily tail has no trusted replacement",
            "legacy SZ 30m rows are invalidated without replacement",
            "unknown volume scales and unavailable amount remain pending per component evidence",
            "old SZ/920xxx identities remain separately pending; this manifest does not relabel them",
        ],
    }
    Path(summary_path).expanduser().resolve().write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _write_jsonl(path: Path, header: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(header), ensure_ascii=False, sort_keys=True) + "\n")
        for record in records:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--d4-manifest", required=True)
    parser.add_argument("--price-manifest", required=True)
    parser.add_argument("--sh-manifest", required=True)
    parser.add_argument("--tail-out", required=True)
    parser.add_argument("--joint-out", required=True)
    parser.add_argument("--summary-out", required=True)
    args = parser.parse_args(argv)
    result = build_joint_manifest(
        args.db,
        args.d4_manifest,
        args.price_manifest,
        args.sh_manifest,
        args.tail_out,
        args.joint_out,
        args.summary_out,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
