import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.market_history_store import MarketHistoryStore
from scripts import apply_market_history_repair as repair
from scripts.apply_market_history_repair import (
    RepairManifestError,
    inspect_or_apply,
    rollback_repair,
    stable_row_sha256,
)
from scripts.build_joint_market_history_manifest import (
    JointManifestError,
    _validate_no_conflicts,
)


def _bar(ts, close=10.0):
    return {
        "ts": ts,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1000.0,
        "amount": 10000.0,
        "volume_unit": "hands",
        "volume_raw_unit": "hands",
        "volume_source": "fixture",
        "amount_unit": "CNY",
        "amount_source": "fixture",
        "amount_available": True,
        "adjustment": "qfq",
        "is_final": True,
        "source_batch": "fixture",
    }


class ApplyMarketHistoryRepairTests(unittest.TestCase):
    def test_joint_manifest_conflict_guard_allows_identity_overlap_but_rejects_duplicate_operation(self):
        identity = {
            "asset_type": "stock",
            "exchange": "SZ",
            "code": "000001",
            "instrument_id": 1,
        }
        first = {
            "identity": identity,
            "identity_key": "stock|SZ|000001|1",
            "interval": "day",
            "ts": "2026-09-09",
        }
        second = dict(first, ts="2026-09-10")
        summary = _validate_no_conflicts(
            [
                ({"name": "price"}, [first]),
                ({"name": "tail"}, [second]),
            ]
        )
        self.assertEqual(summary["duplicate_operation_count"], 0)
        self.assertEqual(summary["identity_overlap_count"], 1)
        with self.assertRaises(JointManifestError):
            _validate_no_conflicts(
                [
                    ({"name": "price"}, [first]),
                    ({"name": "tail"}, [first]),
                ]
            )

    def _manifest(self, db_path, manifest_path, old_row, new_row):
        with MarketHistoryStore(db_path, readonly=True) as store:
            instrument = store.resolve_instrument("stock", "SZ", "301682")
        record = {
            "record_type": "bar_candidate",
            "identity": {
                "asset_type": "stock",
                "exchange": "SZ",
                "code": "301682",
                "instrument_id": instrument["instrument_id"],
            },
            "identity_key": "stock|SZ|301682|{}".format(instrument["instrument_id"]),
            "interval": "day",
            "ts": old_row["ts"],
            "expected_old_present": True,
            "expected_old_row_sha256": stable_row_sha256(old_row),
            "expected_old_row": old_row,
            "new_row": dict(new_row),
        }
        header = {
            "record_type": "manifest_header",
            "schema_version": "test",
            "base_db_sha256": hashlib.sha256(Path(db_path).read_bytes()).hexdigest(),
            "candidate_bar_count": 1,
        }
        with Path(manifest_path).open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(header, sort_keys=True) + "\n")
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()

    def test_default_dry_run_does_not_change_temp_db_and_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "candidate.sqlite"
            manifest = Path(tmp) / "candidate.jsonl"
            old = _bar("2026-08-07", 10.0)
            new = _bar("2026-08-07", 11.0)
            with MarketHistoryStore(db) as store:
                iid = store.upsert_instrument("stock", "SZ", "301682")
                store.upsert_bars("day", iid, [old], adjustment="qfq")
                old = store.query_bars("day", iid)[0]
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            new["instrument_id"] = iid
            new["ingest_run_id"] = None
            manifest_sha = self._manifest(db, manifest, old, new)
            rollback = Path(tmp) / "rollback.json"

            preview = inspect_or_apply(db, manifest, manifest_sha)
            self.assertEqual(preview["mode"], "dry_run")
            self.assertFalse(preview["applied"])
            self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())

            applied = inspect_or_apply(
                db,
                manifest,
                manifest_sha,
                apply=True,
                allow_temporary_db=True,
                rollback_path=rollback,
            )
            self.assertEqual(applied["mode"], "apply")
            self.assertEqual(applied["planned_rows"], 1)
            self.assertTrue(rollback.exists())

            rerun = inspect_or_apply(
                db,
                manifest,
                manifest_sha,
                apply=True,
                allow_temporary_db=True,
            )
            self.assertEqual(rerun["mode"], "idempotent")
            with MarketHistoryStore(db, readonly=True) as store:
                iid = store.resolve_instrument("stock", "SZ", "301682")["instrument_id"]
                rows = store.query_bars("day", iid)
            self.assertEqual(rows[0]["close"], 11.0)

            preview_rollback = rollback_repair(db, rollback)
            self.assertEqual(preview_rollback["mode"], "rollback_dry_run")
            self.assertEqual(preview_rollback["planned_rows"], 1)
            restored = rollback_repair(
                db,
                rollback,
                apply=True,
                allow_temporary_db=True,
            )
            self.assertEqual(restored["mode"], "rollback_apply")
            self.assertEqual(restored["planned_rows"], 1)
            with MarketHistoryStore(db, readonly=True) as store:
                iid = store.resolve_instrument("stock", "SZ", "301682")["instrument_id"]
                rows = store.query_bars("day", iid)
            self.assertEqual(rows[0]["close"], 10.0)
            rerestore = rollback_repair(
                db,
                rollback,
                apply=True,
                allow_temporary_db=True,
            )
            self.assertEqual(rerestore["idempotent_rows"], 1)

    def test_cas_mismatch_rolls_back_all_rows_and_apply_requires_temp_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "candidate.sqlite"
            manifest = Path(tmp) / "candidate.jsonl"
            old = _bar("2026-08-07", 10.0)
            new = _bar("2026-08-07", 11.0)
            with MarketHistoryStore(db) as store:
                iid = store.upsert_instrument("stock", "SZ", "301682")
                store.upsert_bars("day", iid, [old], adjustment="qfq")
                old = store.query_bars("day", iid)[0]
            new["instrument_id"] = iid
            new["ingest_run_id"] = None
            manifest_sha = self._manifest(db, manifest, old, new)

            with self.assertRaises(RepairManifestError):
                inspect_or_apply(db, manifest, manifest_sha, apply=True)

            # Change the row outside the manifest so the CAS must fail.
            with MarketHistoryStore(db) as store:
                store.upsert_bars("day", iid, [_bar("2026-08-07", 12.0)], adjustment="qfq")
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            with self.assertRaises(RepairManifestError):
                inspect_or_apply(
                    db,
                    manifest,
                    manifest_sha,
                    apply=True,
                    allow_temporary_db=True,
                )
            self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())

    def test_delete_legacy_contradictory_identity_is_exact_and_reversible(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.sqlite"
            manifest = Path(tmp) / "delete.jsonl"
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE instruments (
                    instrument_id INTEGER PRIMARY KEY,
                    asset_type TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(asset_type, exchange, code)
                );
                CREATE TABLE bars_day (
                    instrument_id INTEGER NOT NULL,
                    ts TEXT NOT NULL,
                    open REAL NOT NULL, high REAL NOT NULL,
                    low REAL NOT NULL, close REAL NOT NULL,
                    volume REAL NOT NULL, amount REAL NOT NULL,
                    adjustment TEXT NOT NULL, is_final INTEGER NOT NULL,
                    source_batch TEXT NOT NULL, ingest_run_id TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(instrument_id, ts)
                );
                CREATE TABLE bars_30m AS SELECT * FROM bars_day WHERE 0;
                CREATE TABLE bars_15m AS SELECT * FROM bars_day WHERE 0;
                """
            )
            connection.execute(
                "INSERT INTO instruments VALUES (1, 'stock', 'SH', '000063', '', 't')"
            )
            connection.execute(
                "INSERT INTO bars_day VALUES (1, '2026-09-11', 3515, 3516, 3514, 3515, 100, 1000, 'qfq', 1, 'bad', NULL, 'old')"
            )
            connection.commit()
            old = dict(
                zip(
                    [
                        column[1]
                        for column in connection.execute(
                            "PRAGMA table_info(bars_day)"
                        ).fetchall()
                    ],
                    connection.execute(
                        "SELECT * FROM bars_day WHERE instrument_id=1"
                    ).fetchone(),
                )
            )
            connection.close()
            record = {
                "record_type": "bar_candidate",
                "identity": {
                    "asset_type": "stock",
                    "exchange": "SH",
                    "code": "000063",
                    "instrument_id": 1,
                },
                "identity_key": "stock|SH|000063|1",
                "interval": "day",
                "ts": old["ts"],
                "repair_scope": "identity_quarantine_delete",
                "repair_action": "delete_identity_rows",
                "expected_old_present": True,
                "expected_old_row_sha256": stable_row_sha256(old),
                "expected_old_row": old,
                "new_row": None,
            }
            header = {
                "record_type": "manifest_header",
                "schema_version": "test-delete",
                "base_db_sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
                "candidate_bar_count": 1,
            }
            manifest.write_text(
                json.dumps(header, sort_keys=True) + "\n"
                + json.dumps(record, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            rollback = Path(tmp) / "delete-rollback.json"

            applied = inspect_or_apply(
                db,
                manifest,
                manifest_sha,
                apply=True,
                allow_temporary_db=True,
                rollback_path=rollback,
            )
            self.assertEqual(applied["planned_rows"], 1)
            connection = sqlite3.connect(db)
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM bars_day WHERE instrument_id=1"
                ).fetchone()
            )
            connection.close()

            restored = rollback_repair(
                db,
                rollback,
                apply=True,
                allow_temporary_db=True,
            )
            self.assertEqual(restored["planned_rows"], 1)
            connection = sqlite3.connect(db)
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM bars_day WHERE instrument_id=1"
                ).fetchone()
            )
            connection.close()


def _formal_bar(ts, close=10.0):
    return {
        "instrument_id": 1,
        "ts": ts,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1000.0,
        "amount": 10000.0,
        "volume_unit": "hands",
        "volume_raw_unit": "hands",
        "volume_source": "fixture",
        "amount_unit": "CNY",
        "amount_source": "fixture",
        "amount_available": 1,
        "adjustment": "qfq",
        "is_final": 1,
        "source_batch": "fixture",
        "ingest_run_id": None,
        "updated_at": "2026-09-12T00:00:00Z",
    }


def _create_formal_database(path, row=None):
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE instruments (
            instrument_id INTEGER PRIMARY KEY,
            asset_type TEXT NOT NULL,
            exchange TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(asset_type, exchange, code)
        );
        CREATE TABLE bars_day (
            instrument_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            amount REAL NOT NULL,
            volume_unit TEXT NOT NULL,
            volume_raw_unit TEXT NOT NULL,
            volume_source TEXT NOT NULL,
            amount_unit TEXT NOT NULL,
            amount_source TEXT NOT NULL,
            amount_available INTEGER NOT NULL,
            adjustment TEXT NOT NULL,
            is_final INTEGER NOT NULL,
            source_batch TEXT NOT NULL,
            ingest_run_id TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(instrument_id, ts)
        );
        CREATE TABLE bars_30m AS SELECT * FROM bars_day WHERE 0;
        CREATE TABLE bars_15m AS SELECT * FROM bars_day WHERE 0;
        INSERT INTO instruments VALUES (
            1, 'stock', 'SZ', '301682', '', '2026-09-12T00:00:00Z'
        );
        """
    )
    if row is not None:
        columns = ", ".join(repair.BAR_FIELDS)
        placeholders = ", ".join("?" for _ in repair.BAR_FIELDS)
        connection.execute(
            "INSERT INTO bars_day({}) VALUES ({})".format(columns, placeholders),
            tuple(row.get(field) for field in repair.BAR_FIELDS),
        )
    connection.commit()
    connection.close()


def _write_formal_manifest(db, path, old_row, new_row, base_sha=None):
    header = {
        "record_type": "manifest_header",
        "schema_version": "test-formal-adapter",
        "base_db_sha256": base_sha or repair.sha256_file(db),
        "candidate_bar_count": 1,
    }
    record = {
        "record_type": "bar_candidate",
        "identity": {
            "asset_type": "stock",
            "exchange": "SZ",
            "code": "301682",
            "instrument_id": 1,
        },
        "identity_key": "stock|SZ|301682|1",
        "interval": "day",
        "ts": old_row["ts"],
        "expected_old_present": True,
        "expected_old_row_sha256": repair.stable_row_sha256(old_row),
        "expected_old_row": old_row,
        "new_row": new_row,
    }
    path.write_text(
        json.dumps(header, sort_keys=True) + "\n"
        + json.dumps(record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return repair.sha256_file(path)


def _replace_formal_close(db, close):
    connection = sqlite3.connect(str(db))
    connection.execute(
        "UPDATE bars_day SET open=?, high=?, low=?, close=? WHERE instrument_id=1",
        (close - 0.1, close + 0.2, close - 0.2, close),
    )
    connection.commit()
    connection.close()


def _current_formal_close(db):
    connection = sqlite3.connect(str(db))
    value = connection.execute(
        "SELECT close FROM bars_day WHERE instrument_id=1"
    ).fetchone()[0]
    connection.close()
    return value


class FormalBoundaryTests(unittest.TestCase):
    def _fixture(self, root, manifest_dir=None):
        db = root / "market_history.sqlite"
        manifest_root = manifest_dir or root
        manifest_root.mkdir(parents=True, exist_ok=True)
        manifest = manifest_root / "repair.jsonl"
        old = _formal_bar("2026-09-11", 10.0)
        new = _formal_bar("2026-09-11", 11.0)
        _create_formal_database(db, old)
        manifest_sha = _write_formal_manifest(db, manifest, old, new)
        return db, manifest, manifest_sha

    def _formal_kwargs(self, db, rollback, reference="coverage-92-review"):
        return {
            "apply": True,
            "allow_formal_db": True,
            "authorized_formal_path": db,
            "authorization_reference": reference,
            "rollback_path": rollback,
        }

    def test_default_apply_and_rollback_rejection_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            with self.assertRaisesRegex(
                repair.RepairManifestError, "allow-temporary-db"
            ):
                repair.inspect_or_apply(db, manifest, manifest_sha, apply=True)

            rollback = root / "rollback.json"
            repair.inspect_or_apply(
                db,
                manifest,
                manifest_sha,
                apply=True,
                allow_temporary_db=True,
                rollback_path=rollback,
            )
            with self.assertRaisesRegex(
                repair.RepairManifestError, "allow-temporary-db"
            ):
                repair.rollback_repair(db, rollback, apply=True)

    def test_conflicting_authorization_flags_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            with self.assertRaisesRegex(repair.RepairManifestError, "exactly one"):
                repair.inspect_or_apply(
                    db,
                    manifest,
                    manifest_sha,
                    apply=True,
                    allow_temporary_db=True,
                    allow_formal_db=True,
                    authorized_formal_path=db,
                    authorization_reference="coverage-92-review",
                    rollback_path=root / "rollback.json",
                )

    def test_formal_authorization_rejects_wrong_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            wrong = root / "other.sqlite"
            kwargs = self._formal_kwargs(db, root / "rollback.json")
            kwargs["authorized_formal_path"] = wrong
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                with self.assertRaisesRegex(
                    repair.RepairManifestError, "authorized formal path"
                ):
                    repair.inspect_or_apply(db, manifest, manifest_sha, **kwargs)

    def test_formal_authorization_requires_nonempty_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                with self.assertRaisesRegex(
                    repair.RepairManifestError, "authorization reference"
                ):
                    repair.inspect_or_apply(
                        db,
                        manifest,
                        manifest_sha,
                        **self._formal_kwargs(db, root / "rollback.json", "  ")
                    )

    def test_formal_apply_rejects_frozen_manifest_evidence_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = root / "frozen-market-history"
            db, manifest, manifest_sha = self._fixture(root, manifest_dir=frozen)
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                with self.assertRaisesRegex(
                    repair.RepairManifestError, "frozen evidence"
                ):
                    repair.inspect_or_apply(
                        db,
                        manifest,
                        manifest_sha,
                        **self._formal_kwargs(db, root / "rollback.json")
                    )

    def test_formal_validation_allows_only_exact_allowlisted_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            rollback = root / "rollback.json"
            with self.assertRaisesRegex(repair.RepairManifestError, "allowlisted"):
                repair.inspect_or_apply(
                    db,
                    manifest,
                    manifest_sha,
                    **self._formal_kwargs(db, rollback)
                )
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                result = repair.inspect_or_apply(
                    db,
                    manifest,
                    manifest_sha,
                    **self._formal_kwargs(db, rollback)
                )
            self.assertEqual(result["authorization_reference"], "coverage-92-review")
            receipt = json.loads(rollback.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["authorization_reference"], "coverage-92-review"
            )

    def test_formal_apply_preserves_base_sha_and_row_cas_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            _replace_formal_close(db, 12.0)
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                with self.assertRaisesRegex(
                    repair.RepairManifestError, "base database hash mismatch"
                ):
                    repair.inspect_or_apply(
                        db,
                        manifest,
                        manifest_sha,
                        **self._formal_kwargs(db, root / "base-rollback.json")
                    )

            old = _formal_bar("2026-09-11", 10.0)
            new = _formal_bar("2026-09-11", 11.0)
            manifest_sha = _write_formal_manifest(
                db, manifest, old, new, base_sha=repair.sha256_file(db)
            )
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                with self.assertRaisesRegex(repair.RepairManifestError, "CAS mismatch"):
                    repair.inspect_or_apply(
                        db,
                        manifest,
                        manifest_sha,
                        **self._formal_kwargs(db, root / "cas-rollback.json")
                    )

    def test_formal_rollback_requires_reference_tied_to_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            rollback = root / "rollback.json"
            with mock.patch.object(repair, "_FORMAL_DB_PATH", db.resolve()):
                repair.inspect_or_apply(
                    db,
                    manifest,
                    manifest_sha,
                    **self._formal_kwargs(db, rollback)
                )
                with self.assertRaisesRegex(repair.RepairManifestError, "exactly one"):
                    repair.rollback_repair(
                        db,
                        rollback,
                        apply=True,
                        allow_temporary_db=True,
                        allow_formal_db=True,
                        authorized_formal_path=db,
                        authorization_reference="coverage-92-review",
                    )
                frozen_dir = root / "frozen-market-history"
                frozen_dir.mkdir()
                frozen_rollback = frozen_dir / "rollback.json"
                shutil.copyfile(rollback, frozen_rollback)
                with self.assertRaisesRegex(
                    repair.RepairManifestError, "frozen evidence"
                ):
                    repair.rollback_repair(
                        db,
                        frozen_rollback,
                        apply=True,
                        allow_formal_db=True,
                        authorized_formal_path=db,
                        authorization_reference="coverage-92-review",
                    )
                with self.assertRaisesRegex(
                    repair.RepairManifestError, "authorization reference"
                ):
                    repair.rollback_repair(
                        db,
                        rollback,
                        apply=True,
                        allow_formal_db=True,
                        authorized_formal_path=db,
                        authorization_reference="different-review",
                    )
                restored = repair.rollback_repair(
                    db,
                    rollback,
                    apply=True,
                    allow_formal_db=True,
                    authorized_formal_path=db,
                    authorization_reference="coverage-92-review",
                )
            self.assertEqual(restored["authorization_reference"], "coverage-92-review")
            self.assertEqual(_current_formal_close(db), 10.0)

    def test_temporary_apply_and_rollback_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, manifest, manifest_sha = self._fixture(root)
            rollback = root / "rollback.json"
            applied = repair.inspect_or_apply(
                db,
                manifest,
                manifest_sha,
                apply=True,
                allow_temporary_db=True,
                rollback_path=rollback,
            )
            self.assertEqual(applied["mode"], "apply")
            self.assertEqual(_current_formal_close(db), 11.0)
            rerun = repair.inspect_or_apply(
                db,
                manifest,
                manifest_sha,
                apply=True,
                allow_temporary_db=True,
            )
            self.assertEqual(rerun["mode"], "idempotent")
            self.assertTrue(rollback.exists())
            restored = repair.rollback_repair(
                db, rollback, apply=True, allow_temporary_db=True
            )
            self.assertEqual(restored["mode"], "rollback_apply")
            self.assertEqual(_current_formal_close(db), 10.0)
            rerestore = repair.rollback_repair(
                db, rollback, apply=True, allow_temporary_db=True
            )
            self.assertEqual(rerestore["idempotent_rows"], 1)

    def test_cli_forwards_formal_authorization_flags(self):
        with mock.patch.object(
            repair, "inspect_or_apply", return_value={"mode": "dry_run"}
        ) as inspect, mock.patch("builtins.print"):
            repair.main(
                [
                    "--db", "/formal.sqlite",
                    "--manifest", "/repair.jsonl",
                    "--manifest-sha256", "abc",
                    "--apply",
                    "--allow-formal-db",
                    "--authorized-formal-path", "/formal.sqlite",
                    "--authorization-reference", "coverage-92-review",
                    "--rollback-out", "/rollback.json",
                ]
            )
        self.assertTrue(inspect.call_args[1]["allow_formal_db"])
        self.assertEqual(
            inspect.call_args[1]["authorized_formal_path"], "/formal.sqlite"
        )
        self.assertEqual(
            inspect.call_args[1]["authorization_reference"],
            "coverage-92-review",
        )

        with mock.patch.object(
            repair, "rollback_repair", return_value={"mode": "rollback_dry_run"}
        ) as rollback, mock.patch("builtins.print"):
            repair.main(
                [
                    "--db", "/formal.sqlite",
                    "--rollback",
                    "--rollback-file", "/rollback.json",
                    "--apply",
                    "--allow-formal-db",
                    "--authorized-formal-path", "/formal.sqlite",
                    "--authorization-reference", "coverage-92-review",
                ]
            )
        self.assertTrue(rollback.call_args[1]["allow_formal_db"])
        self.assertEqual(
            rollback.call_args[1]["authorized_formal_path"], "/formal.sqlite"
        )
        self.assertEqual(
            rollback.call_args[1]["authorization_reference"],
            "coverage-92-review",
        )


if __name__ == "__main__":
    unittest.main()
