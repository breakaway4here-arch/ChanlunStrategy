#!/usr/bin/env python3
"""Project frozen research sidecars and optionally publish only their JSON files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = PROJECT_ROOT / "research" / "nextday-strength-v0" / "runs"
PUBLIC_DIR_REL = Path("docs") / "research" / "nextday"
GIT_TIMEOUT_SECONDS = 10
PUSH_TIMEOUT_SECONDS = 15
PUBLISH_TIMEOUT_SECONDS = 30
CLEANUP_RESERVE_SECONDS = 3

try:
    from chanlun.nextday_public import (
        PublicProjectionError,
        project_runs,
        serialize_public_json,
        write_public_sidecars,
    )
except ImportError:  # Support direct execution when the repo root is not on sys.path.
    sys.path.insert(0, str(PROJECT_ROOT))
    from chanlun.nextday_public import (
        PublicProjectionError,
        project_runs,
        serialize_public_json,
        write_public_sidecars,
    )


class GitCommandError(RuntimeError):
    """A bounded git operation failed without safe publication."""


def _git(
    repo_root: Path,
    *args: str,
    timeout: int = GIT_TIMEOUT_SECONDS,
    deadline: Optional[float] = None,
) -> subprocess.CompletedProcess:
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GitCommandError("git operation unavailable")
        timeout = min(timeout, max(0.1, remaining))
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root)] + list(args),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise GitCommandError("git operation unavailable")


def _git_ok(
    repo_root: Path,
    *args: str,
    timeout: int = GIT_TIMEOUT_SECONDS,
    deadline: Optional[float] = None,
) -> subprocess.CompletedProcess:
    result = _git(repo_root, *args, timeout=timeout, deadline=deadline)
    if result.returncode != 0:
        raise GitCommandError("git operation unavailable")
    return result


def _index_paths(repo_root: Path, deadline: Optional[float] = None) -> List[str]:
    result = _git_ok(repo_root, "diff", "--cached", "--name-only", "-z", deadline=deadline)
    return [path for path in result.stdout.split("\x00") if path]


def _relative_sidecar_paths(
    repo_root: Path, output_dir: Path, projections: Mapping[str, Mapping[str, Any]]
) -> List[str]:
    result = []
    for report_date in sorted(projections):
        path = output_dir / (report_date + ".json")
        try:
            relative = path.relative_to(repo_root)
        except ValueError:
            raise GitCommandError("public output path unavailable")
        result.append(relative.as_posix())
    return result


def _snapshot_files(paths: Sequence[Path]) -> Dict[Path, Tuple[Optional[bytes], Optional[int]]]:
    snapshots = {}
    for path in paths:
        if path.is_symlink():
            raise GitCommandError("public output path unavailable")
        if path.is_file():
            snapshots[path] = (path.read_bytes(), path.stat().st_mode & 0o777)
        elif path.exists():
            raise GitCommandError("public output path unavailable")
        else:
            snapshots[path] = (None, None)
    return snapshots


def _restore_files(
    snapshots: Mapping[Path, Tuple[Optional[bytes], Optional[int]]],
    output_dir: Path,
) -> None:
    for path, (old_bytes, old_mode) in snapshots.items():
        try:
            if old_bytes is None:
                if path.exists() and path.is_file() and not path.is_symlink():
                    path.unlink()
            elif path.exists() and path.is_file() and not path.is_symlink() and path.read_bytes() != old_bytes:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=str(path.parent), prefix=".nextday-restore.", suffix=".tmp", delete=False
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write(old_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                if old_mode is not None:
                    temporary.chmod(old_mode)
                os.replace(str(temporary), str(path))
        except OSError:
            continue

    # Remove only newly-created empty directories from this sidecar write.
    cursor = output_dir
    while cursor.exists() and cursor.name == "nextday":
        try:
            cursor.rmdir()
        except OSError:
            break
        cursor = cursor.parent
        if cursor.name != "research":
            break
    if cursor.name == "research":
        try:
            cursor.rmdir()
        except OSError:
            pass


def _unstage_paths(repo_root: Path, paths: Sequence[str]) -> None:
    if paths:
        result = _git(repo_root, "restore", "--staged", "--", *paths, timeout=1)
        if result.returncode == 0:
            return
        # Fallback is still path-limited and never resets other index entries.
        fallback = _git(repo_root, "reset", "-q", "HEAD", "--", *paths, timeout=1)
        if fallback.returncode != 0:
            raise GitCommandError("could not unstage owned sidecar paths")


def _preflight(
    repo_root: Path,
    output_dir: Path,
    relative_paths: Sequence[str],
    deadline: Optional[float] = None,
) -> Optional[str]:
    try:
        branch = _git_ok(repo_root, "branch", "--show-current", deadline=deadline).stdout.strip()
        if branch != "main":
            return "not_main_branch"
        if _index_paths(repo_root, deadline):
            return "index_not_empty"
        _git_ok(repo_root, "fetch", "origin", "main", timeout=GIT_TIMEOUT_SECONDS, deadline=deadline)
        ancestor = _git(repo_root, "merge-base", "--is-ancestor", "origin/main", "HEAD", deadline=deadline)
        if ancestor.returncode != 0:
            return "remote_ahead"
        if _index_paths(repo_root, deadline):
            return "index_not_empty"
        dirty = _git_ok(
            repo_root,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *relative_paths,
            deadline=deadline,
        ).stdout
        if dirty:
            return "sidecar_path_dirty"
        return None
    except GitCommandError:
        return "preflight_unavailable"


def _clean_precommit_failure(
    repo_root: Path,
    paths: Sequence[str],
    snapshots: Mapping[Path, Tuple[Optional[bytes], Optional[int]]],
    output_dir: Path,
    cleanup_deadline: Optional[float] = None,
) -> bool:
    try:
        _unstage_paths(repo_root, paths)
    except GitCommandError:
        _restore_files(snapshots, output_dir)
        return False
    _restore_files(snapshots, output_dir)
    try:
        staged = _index_paths(repo_root, cleanup_deadline)
    except GitCommandError:
        return False
    return not any(path in staged for path in paths)


def _result(status: str, *, dates: Sequence[str] = (), unavailable_dates: Sequence[str] = (), reason: str = "") -> Dict[str, Any]:
    return {
        "status": status,
        "dates": list(dates),
        "unavailable_dates": list(unavailable_dates),
        "reason": reason,
    }


def project_only(
    runs_dir: Path,
    output_dir: Path,
    report_dates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    projections, errors = project_runs(runs_dir, report_dates)
    write_public_sidecars(projections, output_dir)
    status = "projected" if not errors else "projected_partial"
    return _result(
        status,
        dates=sorted(projections),
        unavailable_dates=[item["report_date"] for item in errors],
        reason="source_unavailable" if errors else "",
    )


def publish_sidecars(
    repo_root: Path,
    runs_dir: Path,
    report_dates: Optional[Sequence[str]] = None,
    output_dir: Optional[Path] = None,
    timeout_seconds: int = PUBLISH_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Publish allowlisted JSON sidecars after a fail-closed main-branch preflight."""
    repo_root = Path(repo_root).resolve()
    expected_output = repo_root / PUBLIC_DIR_REL
    output_dir = Path(output_dir or expected_output).resolve()
    try:
        relative_output = output_dir.relative_to(repo_root)
    except ValueError:
        return _result("pending", reason="public_output_path_unavailable")
    if relative_output != PUBLIC_DIR_REL:
        return _result("pending", reason="public_output_path_unavailable")

    publication_deadline = time.monotonic() + max(1, timeout_seconds)
    cleanup_deadline = publication_deadline + CLEANUP_RESERVE_SECONDS
    try:
        projections, errors = project_runs(runs_dir, report_dates)
    except PublicProjectionError:
        return _result("unavailable", reason="source_unavailable")
    unavailable_dates = [item["report_date"] for item in errors]
    if not projections:
        return _result("unavailable", unavailable_dates=unavailable_dates, reason="source_unavailable")

    relative_paths = _relative_sidecar_paths(repo_root, output_dir, projections)
    preflight = _preflight(repo_root, output_dir, relative_paths, publication_deadline)
    if preflight is not None:
        return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason=preflight)

    target_paths = [output_dir / (report_date + ".json") for report_date in sorted(projections)]
    try:
        snapshots = _snapshot_files(target_paths)
    except (OSError, GitCommandError):
        return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="sidecar_path_unavailable")

    # Recheck the index immediately before writing; the daily caller already
    # owns the publication lock, so this publisher deliberately takes no lock.
    try:
        if _index_paths(repo_root, publication_deadline):
            return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="index_not_empty")
    except GitCommandError:
        return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="preflight_unavailable")

    try:
        changed_paths = write_public_sidecars(projections, output_dir)
    except Exception:
        _restore_files(snapshots, output_dir)
        return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="sidecar_write_failed")
    if not changed_paths:
        status = "partial_no_changes" if unavailable_dates else "no_changes"
        return _result(status, dates=sorted(projections), unavailable_dates=unavailable_dates, reason="source_unavailable" if unavailable_dates else "")

    changed_relative = [path.relative_to(repo_root).as_posix() for path in changed_paths]
    head_before = None
    try:
        _git_ok(repo_root, "add", "-f", "--", *changed_relative, deadline=publication_deadline)
        staged_paths = _index_paths(repo_root, publication_deadline)
        if sorted(staged_paths) != sorted(changed_relative):
            cleaned = _clean_precommit_failure(repo_root, changed_relative, snapshots, output_dir, cleanup_deadline)
            return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="staged_paths_mismatch" if cleaned else "cleanup_incomplete")
        head_before = _git_ok(repo_root, "rev-parse", "HEAD", deadline=publication_deadline).stdout.strip()
        title_date = max(path.stem for path in changed_paths)
        commit = _git(repo_root, "commit", "-m", "chore: 更新次日研究展示数据 {}".format(title_date), timeout=GIT_TIMEOUT_SECONDS, deadline=publication_deadline)
        current_head = _git_ok(repo_root, "rev-parse", "HEAD", deadline=cleanup_deadline).stdout.strip()
        committed = current_head != head_before
        if commit.returncode != 0 and not committed:
            cleaned = _clean_precommit_failure(repo_root, changed_relative, snapshots, output_dir, cleanup_deadline)
            return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="commit_failed" if cleaned else "cleanup_incomplete")
        if not committed:
            cleaned = _clean_precommit_failure(repo_root, changed_relative, snapshots, output_dir, cleanup_deadline)
            return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="commit_failed" if cleaned else "cleanup_incomplete")
    except GitCommandError:
        committed = False
        if head_before is not None:
            try:
                committed = _git_ok(repo_root, "rev-parse", "HEAD", deadline=cleanup_deadline).stdout.strip() != head_before
            except Exception:
                # An uncertain commit must not be undone; retain it for the
                # next ordinary pending-commit push and surface the state.
                committed = True
        if not committed:
            cleaned = _clean_precommit_failure(repo_root, changed_relative, snapshots, output_dir, cleanup_deadline)
            return _result("pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="commit_failed" if cleaned else "cleanup_incomplete")

    if time.monotonic() >= publication_deadline:
        return _result("committed_pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="push_pending")
    try:
        push = _git(repo_root, "push", "origin", "HEAD:main", timeout=PUSH_TIMEOUT_SECONDS, deadline=publication_deadline)
    except GitCommandError:
        push = None
    if push is None or push.returncode != 0:
        return _result("committed_pending", dates=sorted(projections), unavailable_dates=unavailable_dates, reason="push_pending")
    status = "published_partial" if unavailable_dates else "published"
    return _result(status, dates=sorted(projections), unavailable_dates=unavailable_dates, reason="source_unavailable" if unavailable_dates else "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(PROJECT_ROOT))
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument("--output-dir", help="public JSON directory; publish mode requires docs/research/nextday")
    parser.add_argument("--report-date", action="append", help="project one date; repeat to select several")
    parser.add_argument("--no-publish", action="store_true", help="write the offline projection without using git")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    runs_dir = Path(args.runs_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else repo_root / PUBLIC_DIR_REL
    if args.no_publish:
        try:
            result = project_only(runs_dir, output_dir, args.report_date)
        except PublicProjectionError:
            result = _result("unavailable", reason="source_unavailable")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result["status"] == "unavailable":
            return 1
        if args.report_date and not result["dates"]:
            return 1
        return 0

    result = publish_sidecars(repo_root, runs_dir, args.report_date, output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] in ("published", "published_partial", "no_changes", "partial_no_changes"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
