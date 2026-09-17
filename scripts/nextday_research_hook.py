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
PUBLISH_TIMEOUT_SECONDS = 30
MAX_DETAIL_CHARS = 2000
STATUS_FILENAME = "last_hook_status.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    from scripts.publish_nextday_research import publish_sidecars
except Exception:
    # Research and the daily report remain successful if the optional public
    # sidecar publisher cannot be imported in this runtime checkout.
    publish_sidecars = None
try:
    from chanlun.nextday_public import project_runs
except Exception:
    project_runs = None


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


def _publisher_result(output_dir: Path) -> dict:
    if publish_sidecars is None:
        return {"status": "unavailable", "reason": "publisher_unavailable"}
    try:
        result = publish_sidecars(
            PROJECT_ROOT,
            output_dir,
            timeout_seconds=PUBLISH_TIMEOUT_SECONDS,
        )
    except Exception:
        return {"status": "unavailable", "reason": "publisher_error"}
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        return {"status": "unavailable", "reason": "publisher_unavailable"}
    return result


def _frozen_record_is_valid(output_dir: Path, report_date: Optional[str]) -> bool:
    if project_runs is None or not report_date:
        return False
    try:
        projections, errors = project_runs(output_dir, [report_date])
    except Exception:
        return False
    record = projections.get(report_date)
    return (
        not errors
        and isinstance(record, dict)
        and record.get("report_date") == report_date
        and isinstance(record.get("source_run_id"), str)
        and bool(record.get("source_run_id"))
        and isinstance(record.get("frozen_at"), str)
        and bool(record.get("frozen_at"))
    )


def _record_publisher_result(
    output_dir: Path,
    *,
    as_of: Optional[str],
    report_path: Optional[Path],
    db_path: Optional[Path],
    publish_result: dict,
    research_status: Optional[str] = None,
    research_exit_code: int = 0,
) -> None:
    publish_status = publish_result.get("status")
    if not isinstance(publish_status, str) or not publish_status:
        publish_status = "unavailable"
    reason = publish_result.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 120:
        reason = "publisher_unavailable"
    if research_status:
        reason = "research_status={};{}".format(research_status, reason)
    _record_status(
        output_dir,
        status=publish_status,
        as_of=as_of,
        report_path=report_path,
        db_path=db_path,
        exit_code=research_exit_code if research_exit_code else (
            0 if publish_status in ("published", "published_partial", "no_changes", "partial_no_changes") else 1
        ),
        timeout_seconds=PUBLISH_TIMEOUT_SECONDS,
        error_summary=reason,
    )


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
        try:
            payload = json.loads(_text(result.stdout))
        except (TypeError, ValueError):
            payload = None
        research_status = payload.get("status") if isinstance(payload, dict) else None
        if (
            result.returncode == 2
            and research_status in ("conflict", "partial_refresh")
            and _frozen_record_is_valid(output_dir, args.as_of)
        ):
            _record_publisher_result(
                output_dir,
                as_of=args.as_of,
                report_path=report_path,
                db_path=db_path,
                publish_result=_publisher_result(output_dir),
                research_status=research_status,
                research_exit_code=result.returncode,
            )
            return 0
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

    _record_publisher_result(
        output_dir,
        as_of=args.as_of,
        report_path=report_path,
        db_path=db_path,
        publish_result=_publisher_result(output_dir),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
