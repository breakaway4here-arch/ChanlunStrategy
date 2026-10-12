#!/usr/bin/env python3
"""Stage one verified optional selection-performance publication triplet."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
DATASET_ID_RE = re.compile(r"[0-9a-f]{64}\Z")


def _git(repo_root, *args):
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def _read_verified_json(repo_root, relative_path, hashes):
    expected = hashes.get(relative_path)
    path = repo_root / relative_path
    if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
            or path.is_symlink() or not path.is_file()):
        return None
    try:
        encoded = path.read_bytes()
        if hashlib.sha256(encoded).hexdigest() != expected:
            return None
        value = json.loads(encoded)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _consistent_publication(repo_root, trade_date, hashes):
    report = _read_verified_json(
        repo_root, f"docs/data/{trade_date}.json", hashes,
    )
    archive_path = f"docs/{trade_date}/index.html"
    archive = repo_root / archive_path
    if (report is None or archive.is_symlink() or not archive.is_file()
            or not isinstance(hashes.get(archive_path), str)
            or hashlib.sha256(archive.read_bytes()).hexdigest() != hashes[archive_path]):
        return False
    quality = report.get("data_quality")
    quality = quality if isinstance(quality, dict) else {}
    evaluation_as_of = quality.get("as_of")
    if (report.get("date") != trade_date or quality.get("is_official") is not True
            or quality.get("bar_state") != "closed"
            or not isinstance(evaluation_as_of, str)):
        return False
    try:
        cutoff = datetime.fromisoformat(evaluation_as_of.replace("Z", "+00:00"))
    except ValueError:
        return False
    if (cutoff.tzinfo is None
            or cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            != trade_date):
        return False

    derived_dir = "docs/data/selection-performance"
    dated_path = f"{derived_dir}/{trade_date}.json"
    index_path = f"{derived_dir}/index.json"
    status_path = f"{derived_dir}/status.json"
    dated = _read_verified_json(repo_root, dated_path, hashes)
    index = _read_verified_json(repo_root, index_path, hashes)
    status = _read_verified_json(repo_root, status_path, hashes)
    if dated is None or index is None or status is None:
        return False
    dataset_id = dated.get("dataset_id")
    if (dated.get("schema_version") != "selection-performance-v1"
            or dated.get("report_as_of") != trade_date
            or dated.get("evaluation_as_of") != evaluation_as_of
            or not isinstance(dataset_id, str)
            or not DATASET_ID_RE.fullmatch(dataset_id)
            or index.get("schema_version") != "selection-performance-index-v1"):
        return False
    datasets = index.get("datasets")
    entry = datasets.get(trade_date) if isinstance(datasets, dict) else None
    dates = index.get("dates")
    if (not isinstance(entry, dict) or not isinstance(dates, list)
            or trade_date not in dates
            or entry.get("dataset_id") != dataset_id
            or entry.get("evaluation_as_of") != evaluation_as_of
            or status.get("status") != "ready"
            or status.get("attempted_report_as_of") != trade_date
            or status.get("last_success") != entry):
        return False
    return True


def _discard_verified_invalid_group(repo_root, trade_date, journal_path, hashes):
    """Keep a private receipt, then undo only this run's unchanged derived output."""
    paths = [
        f"docs/data/selection-performance/{trade_date}.json",
        "docs/data/selection-performance/index.json",
        "docs/data/selection-performance/status.json",
    ]
    dirty = []
    for relative_path in paths:
        status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all",
                      "--", relative_path)
        staged = _git(repo_root, "diff", "--cached", "--quiet", "--", relative_path)
        if status.returncode != 0 or staged.returncode not in (0, 1):
            raise RuntimeError("cannot inspect optional derived file")
        if staged.returncode == 1:
            raise RuntimeError("optional derived file was already staged")
        if not status.stdout.strip():
            continue
        path = repo_root / relative_path
        expected = hashes.get(relative_path)
        if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise RuntimeError("optional derived file differs from generated journal")
        tracked = _git(repo_root, "ls-files", "--error-unmatch", "--", relative_path)
        if tracked.returncode not in (0, 1):
            raise RuntimeError("cannot identify optional derived file")
        dirty.append((relative_path, tracked.returncode == 0))
    if not dirty:
        return

    receipt_dir = Path(journal_path).parent / "selection-performance-stage-skips"
    if receipt_dir.is_symlink():
        raise RuntimeError("optional derived receipt directory is a symlink")
    receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(receipt_dir, 0o700)
    backups = {}
    created_backups = []
    temporary = None
    receipt_published = False
    try:
        for relative_path, _ in dirty:
            source = repo_root / relative_path
            encoded = source.read_bytes()
            if hashlib.sha256(encoded).hexdigest() != hashes[relative_path]:
                raise RuntimeError("optional derived file changed before backup")
            descriptor, name = tempfile.mkstemp(
                prefix=trade_date + "-", suffix=".bak", dir=receipt_dir)
            backup = Path(name)
            created_backups.append(backup)
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if (backup.read_bytes() != encoded
                    or hashlib.sha256(backup.read_bytes()).hexdigest()
                    != hashes[relative_path]):
                raise RuntimeError("optional derived backup verification failed")
            backups[relative_path] = backup.name
        for relative_path, _ in dirty:
            source = repo_root / relative_path
            if (source.is_symlink() or not source.is_file()
                    or hashlib.sha256(source.read_bytes()).hexdigest()
                    != hashes[relative_path]):
                raise RuntimeError("optional derived file changed before receipt")
        descriptor, temporary = tempfile.mkstemp(
            prefix="." + trade_date + "-", suffix=".tmp", dir=receipt_dir)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump({
                "schema_version": 1,
                "trade_date": trade_date,
                "reason": "invalid_or_incomplete_optional_derived",
                "generated_sha256": {
                    relative_path: hashes[relative_path]
                    for relative_path, _ in dirty
                },
                "backups": backups,
            }, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        receipt = receipt_dir / (trade_date + "-" + uuid.uuid4().hex + ".json")
        os.link(temporary, receipt)
        receipt_published = True
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
        if not receipt_published:
            for backup in created_backups:
                backup.unlink(missing_ok=True)

    for relative_path, tracked in dirty:
        path = repo_root / relative_path
        if (not path.is_file() or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != hashes[relative_path]):
            raise RuntimeError("optional derived file changed before cleanup")
        if tracked:
            restored = _git(repo_root, "restore", "--worktree", "--", relative_path)
            if restored.returncode != 0:
                raise RuntimeError("cannot restore previous optional derived file")
        else:
            path.unlink()


def stage_selection_performance(repo_root, trade_date, journal_path):
    """Return True only when all three current files are staged together."""
    repo_root = Path(repo_root).resolve()
    if not DATE_RE.fullmatch(str(trade_date or "")):
        raise ValueError("trade_date must use YYYY-MM-DD")
    head = _git(repo_root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise RuntimeError("cannot resolve publication HEAD")
    try:
        journal = json.loads(Path(journal_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if (not isinstance(journal, dict) or journal.get("schema_version") != 1
            or journal.get("head_sha") != head.stdout.decode("ascii").strip()
            or journal.get("trade_date") != trade_date
            or not isinstance(journal.get("generated_targets"), dict)):
        return False
    hashes = journal["generated_targets"]
    if not _consistent_publication(repo_root, trade_date, hashes):
        _discard_verified_invalid_group(repo_root, trade_date, journal_path, hashes)
        return False

    paths = [
        f"docs/data/selection-performance/{trade_date}.json",
        "docs/data/selection-performance/index.json",
        "docs/data/selection-performance/status.json",
    ]
    staged = _git(repo_root, "add", "--", *paths)
    if staged.returncode != 0:
        raise RuntimeError("cannot stage selection-performance files")
    for relative_path in paths:
        indexed = _git(repo_root, "show", ":" + relative_path)
        if (indexed.returncode != 0 or hashlib.sha256(indexed.stdout).hexdigest()
                != hashes[relative_path]):
            _git(repo_root, "restore", "--staged", "--", *paths)
            raise RuntimeError("staged selection-performance bytes differ from journal")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--journal-path", required=True)
    args = parser.parse_args(argv)
    try:
        staged = stage_selection_performance(
            args.repo_root, args.trade_date, args.journal_path,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print("选股表现暂存失败: {}".format(exc), file=sys.stderr)
        return 1
    print("选股表现已暂存" if staged else "选股表现未形成有效当期证据，保留原线上结果")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
