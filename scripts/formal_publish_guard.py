#!/usr/bin/env python3
"""Distinguish user-dirty files from formal artifacts awaiting a safe retry."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SCHEMA_VERSION = 1
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HISTORICAL_ENTRYPOINT_RE = re.compile(
    r"docs/\d{4}-\d{2}-\d{2}/index\.html"
)


def formal_publish_targets(trade_date):
    if not DATE_RE.fullmatch(str(trade_date or "")):
        raise ValueError("trade_date must use YYYY-MM-DD")
    return (
        "docs/index.html",
        "docs/data.json",
        "docs/data/comparison-index.json",
        "docs/data/index.json",
        f"docs/data/{trade_date}.json",
        f"docs/{trade_date}/index.html",
        "docs/assets/report-v2.css",
        "docs/assets/report-v2.js",
    )


def _git(repo_root, *args):
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _head_sha(repo_root):
    completed = _git(repo_root, "rev-parse", "HEAD")
    if completed.returncode != 0:
        raise RuntimeError("cannot resolve formal runtime HEAD")
    return completed.stdout.decode("ascii").strip()


def _index_is_dirty(repo_root):
    completed = _git(repo_root, "diff", "--cached", "--quiet")
    if completed.returncode not in (0, 1):
        raise RuntimeError("cannot inspect staged formal runtime changes")
    return completed.returncode == 1


def _path_is_dirty(repo_root, relative_path):
    completed = _git(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        relative_path,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot inspect formal publish target: {relative_path}")
    return bool(completed.stdout.strip())


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report_entrypoints(repo_root):
    completed = _git(repo_root, "ls-files", "-z", "--", "docs")
    if completed.returncode != 0:
        raise RuntimeError("cannot enumerate tracked report entrypoints")
    candidates = set()
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative_path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if (
            relative_path == "docs/compare/index.html"
            or HISTORICAL_ENTRYPOINT_RE.fullmatch(relative_path)
        ):
            candidates.add(relative_path)

    docs_dir = Path(repo_root) / "docs"
    compare_path = docs_dir / "compare" / "index.html"
    if compare_path.exists():
        candidates.add("docs/compare/index.html")
    if docs_dir.is_dir():
        for child in docs_dir.iterdir():
            if DATE_RE.fullmatch(child.name) and (child / "index.html").exists():
                candidates.add(f"docs/{child.name}/index.html")
    return sorted(candidates)


def _load_journal(journal_path):
    try:
        payload = json.loads(Path(journal_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _valid_journal(payload, trade_date, head_sha):
    return bool(
        isinstance(payload, dict)
        and payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("trade_date") == trade_date
        and payload.get("head_sha") == head_sha
        and isinstance(payload.get("generated_targets"), dict)
        and isinstance(payload.get("excluded_report_entrypoints"), list)
    )


def _write_journal(journal_path, payload):
    journal_path = Path(journal_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=journal_path.name + ".",
        dir=str(journal_path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, journal_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def preflight_formal_publish(repo_root, trade_date, journal_path):
    repo_root = Path(repo_root).resolve()
    head_sha = _head_sha(repo_root)
    if _index_is_dirty(repo_root):
        raise RuntimeError("formal runtime index already contains staged changes")

    existing = _load_journal(journal_path)
    if _valid_journal(existing, trade_date, head_sha):
        generated_targets = existing["generated_targets"]
        for relative_path in formal_publish_targets(trade_date):
            if not _path_is_dirty(repo_root, relative_path):
                continue
            expected_hash = generated_targets.get(relative_path)
            target_path = repo_root / relative_path
            if (
                not expected_hash
                or not target_path.is_file()
                or _sha256(target_path) != expected_hash
            ):
                raise RuntimeError(
                    f"{relative_path} does not match generated journal"
                )
        return existing

    for relative_path in formal_publish_targets(trade_date):
        if _path_is_dirty(repo_root, relative_path):
            raise RuntimeError(
                f"preexisting user change in formal publish target: {relative_path}"
            )
    return None


def prepare_formal_publish(repo_root, trade_date, journal_path):
    repo_root = Path(repo_root).resolve()
    existing = preflight_formal_publish(repo_root, trade_date, journal_path)
    if existing is not None:
        return existing
    head_sha = _head_sha(repo_root)

    excluded = [
        relative_path
        for relative_path in _report_entrypoints(repo_root)
        if _path_is_dirty(repo_root, relative_path)
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "head_sha": head_sha,
        "generated_targets": {},
        "excluded_report_entrypoints": excluded,
    }
    _write_journal(journal_path, payload)
    return payload


def record_formal_publish_targets(repo_root, trade_date, journal_path):
    repo_root = Path(repo_root).resolve()
    head_sha = _head_sha(repo_root)
    if _index_is_dirty(repo_root):
        raise RuntimeError("cannot record generated targets with a dirty index")
    payload = _load_journal(journal_path)
    if not _valid_journal(payload, trade_date, head_sha):
        raise RuntimeError("formal publish journal is missing or stale")

    payload["generated_targets"] = {
        relative_path: _sha256(repo_root / relative_path)
        for relative_path in formal_publish_targets(trade_date)
        if (repo_root / relative_path).is_file()
    }
    _write_journal(journal_path, payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "prepare", "record"))
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--journal-path", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            payload = preflight_formal_publish(
                args.repo_root,
                args.trade_date,
                args.journal_path,
            ) or {
                "generated_targets": {},
                "excluded_report_entrypoints": [],
            }
        elif args.action == "prepare":
            payload = prepare_formal_publish(
                args.repo_root,
                args.trade_date,
                args.journal_path,
            )
        else:
            payload = record_formal_publish_targets(
                args.repo_root,
                args.trade_date,
                args.journal_path,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"正式发布来源保护失败: {exc}", file=sys.stderr)
        return 1
    print(
        "正式发布来源保护通过: "
        f"generated={len(payload['generated_targets'])}, "
        f"excluded={len(payload['excluded_report_entrypoints'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
