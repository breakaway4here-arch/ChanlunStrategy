#!/usr/bin/env python3
"""Run next-day research as a bounded, non-blocking post-publish task."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 60
MAX_DETAIL_CHARS = 2000
STATUS_FILENAME = "last_hook_status.json"


def resolve_output_dir(output_dir: Optional[str]) -> Path:
    """Resolve an explicit path, the environment override, or the shared runs root."""

    selected = output_dir or os.environ.get("CHANLUN_NEXTDAY_RESEARCH_DIR")
    if selected:
        return Path(selected).expanduser().resolve()

    shared_cache = (PROJECT_ROOT / ".cache" / "chanlun").resolve(strict=True)
    if shared_cache.name != "chanlun" or shared_cache.parent.name != ".cache":
        raise OSError("shared Chanlun cache path does not resolve to .cache/chanlun")
    canonical_root = shared_cache.parent.parent
    return canonical_root / "research" / "nextday-strength-v0" / "runs"


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _log_status(
    status: str,
    *,
    as_of: Optional[str],
    exit_code: Optional[int] = None,
    detail: str = "",
) -> None:
    parts = ["[optional-nextday-research]", "status=" + status]
    if as_of:
        parts.append("as_of=" + as_of)
    if exit_code is not None:
        parts.append("exit_code=" + str(exit_code))
    print(" ".join(parts), file=sys.stderr)
    if detail:
        print(
            "[optional-nextday-research] detail=" + detail[-MAX_DETAIL_CHARS:],
            file=sys.stderr,
        )


def _write_status_file(
    output_dir: Path,
    *,
    status: str,
    as_of: Optional[str],
    report_path: Optional[Path],
    db_path: Optional[Path],
    exit_code: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
    error_summary: str = "",
) -> None:
    payload = {
        "schema_version": 1,
        "status": status,
        "as_of": as_of,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report": str(report_path) if report_path is not None else None,
        "db": str(db_path) if db_path is not None else None,
        "exit_code": exit_code,
        "timeout_seconds": timeout_seconds,
        "error_summary": error_summary[-MAX_DETAIL_CHARS:] or None,
    }
    temporary_path = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(output_dir),
            prefix=".last_hook_status.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(output_dir / STATUS_FILENAME))
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        raise


def _record_status(
    output_dir: Path,
    *,
    status: str,
    as_of: Optional[str],
    report_path: Optional[Path],
    db_path: Optional[Path],
    exit_code: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
    error_summary: str = "",
) -> None:
    _log_status(status, as_of=as_of, exit_code=exit_code, detail=error_summary)
    try:
        _write_status_file(
            output_dir,
            status=status,
            as_of=as_of,
            report_path=report_path,
            db_path=db_path,
            exit_code=exit_code,
            timeout_seconds=timeout_seconds,
            error_summary=error_summary,
        )
    except Exception as exc:
        _log_status(
            "status_write_failed",
            as_of=as_of,
            detail="{}: {}".format(type(exc).__name__, exc),
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="published report JSON path")
    parser.add_argument("--output-dir", help="research runs directory")
    parser.add_argument("--db", required=True, help="canonical market history SQLite path")
    parser.add_argument("--as-of", help="explicit completed report date, YYYY-MM-DD")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code != 0:
            _log_status("unavailable", as_of=None, detail="invalid hook arguments")
        return 0

    output_dir = None
    report_path = None
    db_path = None
    try:
        report_path = Path(args.report).expanduser().resolve()
        db_path = Path(args.db).expanduser().resolve()
        output_dir = resolve_output_dir(args.output_dir)
        cli_path = (PROJECT_ROOT / "scripts" / "nextday_research.py").resolve()
        command = [
            sys.executable,
            str(cli_path),
            "--report",
            str(report_path),
            "--output-dir",
            str(output_dir),
            "--db",
            str(db_path),
        ]
        if args.as_of:
            command.extend(["--as-of", args.as_of])
        result = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        detail = "\n".join(part for part in (_text(exc.stdout), _text(exc.stderr)) if part)
        detail = "timeout_seconds={}\n{}".format(TIMEOUT_SECONDS, detail)
        if output_dir is None:
            _log_status("timeout", as_of=args.as_of, detail=detail)
        else:
            _record_status(
                output_dir,
                status="timeout",
                as_of=args.as_of,
                report_path=report_path,
                db_path=db_path,
                timeout_seconds=TIMEOUT_SECONDS,
                error_summary=detail,
            )
        return 0
    except Exception as exc:
        detail = "{}: {}".format(type(exc).__name__, exc)
        if output_dir is None:
            _log_status("unavailable", as_of=args.as_of, detail=detail)
        else:
            _record_status(
                output_dir,
                status="unavailable",
                as_of=args.as_of,
                report_path=report_path,
                db_path=db_path,
                error_summary=detail,
            )
        return 0

    if result.returncode != 0:
        detail = "\n".join(
            part for part in (_text(result.stdout), _text(result.stderr)) if part
        )
        _record_status(
            output_dir,
            status="failed",
            as_of=args.as_of,
            report_path=report_path,
            db_path=db_path,
            exit_code=result.returncode,
            error_summary=detail,
        )
        return 0

    _record_status(
        output_dir,
        status="completed",
        as_of=args.as_of,
        report_path=report_path,
        db_path=db_path,
        exit_code=0,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
