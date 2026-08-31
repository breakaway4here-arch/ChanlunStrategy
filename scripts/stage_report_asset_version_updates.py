#!/usr/bin/env python3
"""Stage query-only report shell updates without capturing user HTML edits."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chanlun.report_generator import (
    _report_asset_version,
    replace_report_asset_versions,
)  # noqa: E402


DATE_DIR_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HISTORICAL_ENTRYPOINT_RE = re.compile(
    r"docs/\d{4}-\d{2}-\d{2}/index\.html"
)
NORMALIZED_ASSET_VERSION = "000000000000"


def iter_report_entrypoints(docs_dir):
    docs_dir = Path(docs_dir)
    compare_path = docs_dir / "compare" / "index.html"
    if compare_path.is_file():
        yield compare_path
    if not docs_dir.is_dir():
        return
    for child in sorted(docs_dir.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or not DATE_DIR_RE.fullmatch(child.name):
            continue
        index_path = child / "index.html"
        if index_path.is_file():
            yield index_path


def _head_bytes(repo_root, relative_path):
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{relative_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def _deleted_historical_entrypoints(repo_root):
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--deleted",
            "-z",
            "--",
            "docs",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    deleted = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative_path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if HISTORICAL_ENTRYPOINT_RE.fullmatch(relative_path):
            deleted.append(relative_path)
    return sorted(deleted)


def _asset_query_only_change(before, after, current_version):
    if before == after:
        return False
    if replace_report_asset_versions(after, current_version) != after:
        return False
    return replace_report_asset_versions(
        before,
        NORMALIZED_ASSET_VERSION,
    ) == replace_report_asset_versions(after, NORMALIZED_ASSET_VERSION)


def stage_report_asset_version_updates(
    repo_root,
    docs_dir,
    excluded_paths=None,
    stage_generated_deletions=False,
):
    repo_root = Path(repo_root).resolve()
    docs_dir = Path(docs_dir)
    if not docs_dir.is_absolute():
        docs_dir = repo_root / docs_dir
    docs_dir = docs_dir.resolve()
    try:
        docs_dir.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("docs_dir must be inside repo_root") from exc

    stageable = []
    skipped = []
    excluded_paths = set(excluded_paths or ())
    current_version = _report_asset_version()
    for entrypoint in iter_report_entrypoints(docs_dir):
        relative_path = entrypoint.relative_to(repo_root).as_posix()
        if relative_path in excluded_paths:
            skipped.append(relative_path)
            continue
        before_bytes = _head_bytes(repo_root, relative_path)
        if before_bytes is None:
            continue
        try:
            before = before_bytes.decode("utf-8")
            after = entrypoint.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append(relative_path)
            continue
        if before == after:
            continue
        if not _asset_query_only_change(before, after, current_version):
            skipped.append(relative_path)
            continue
        stageable.append(relative_path)

    if stage_generated_deletions:
        for relative_path in _deleted_historical_entrypoints(repo_root):
            if relative_path in excluded_paths:
                skipped.append(relative_path)
                continue
            stageable.append(relative_path)

    if stageable:
        subprocess.run(
            ["git", "-C", str(repo_root), "add", "--", *stageable],
            check=True,
        )
    return stageable, skipped


def _journal_exclusions(journal_path, repo_root):
    try:
        payload = json.loads(Path(journal_path).read_text(encoding="utf-8"))
        excluded = payload["excluded_report_entrypoints"]
        journal_head = payload["head_sha"]
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("formal publish journal exclusions are unavailable") from exc
    if not isinstance(excluded, list) or not all(
        isinstance(path, str) for path in excluded
    ):
        raise ValueError("formal publish journal exclusions are invalid")
    completed = subprocess.run(
        ["git", "-C", str(Path(repo_root).resolve()), "rev-parse", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("formal publish journal HEAD cannot be verified")
    current_head = completed.stdout.decode("ascii", errors="ignore").strip()
    if not isinstance(journal_head, str) or journal_head != current_head:
        raise ValueError("formal publish journal HEAD mismatch")
    return excluded


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--journal-path")
    args = parser.parse_args(argv)

    try:
        excluded = (
            _journal_exclusions(args.journal_path, args.repo_root)
            if args.journal_path
            else ()
        )
        staged, skipped = stage_report_asset_version_updates(
            args.repo_root,
            args.docs_dir,
            excluded_paths=excluded,
            stage_generated_deletions=bool(args.journal_path),
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"历史入口资源版本暂存失败: {exc}", file=sys.stderr)
        return 1
    for path in skipped:
        print(f"跳过含用户正文改动的历史入口: {path}")
    print(f"历史入口资源版本安全暂存: {len(staged)}，保留用户改动: {len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
