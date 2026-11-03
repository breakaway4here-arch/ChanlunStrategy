"""One-shot 09:40 personal alert. No --send means no credentials or POST.

Offline inputs can never send. --scheduled also obeys the real wall clock and
never starts a delayed catch-up collection. All outputs are separate previews.
"""
import argparse
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import sys
import tempfile

from chanlun.opening_limitup import SHANGHAI
from chanlun.opening_limitup_delivery import deliver
from chanlun.opening_limitup_sources import collect_opening_evidence
from chanlun.preclose_schedule import is_trading_day


def _preview_directory(value):
    path = Path(value).expanduser().resolve()
    if path.name != "opening-limitup-preview" or any(p in ("docs", "data", "db", "research", "outbox") for p in path.parts):
        raise ValueError("preview_must_be_independent")
    return path


def _write_preview_text(path, text):
    fd, temp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv=None, *, collector=None, stdout=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="explicit offline/dry-run date; never bypasses real send clock")
    parser.add_argument("--input", type=Path, help="canonical offline evidence JSON (never sendable)")
    parser.add_argument("--send", action="store_true", help="explicit personal WxPusher attempt, actual same-day09:40–09:41 only")
    parser.add_argument("--scheduled", action="store_true", help="skip outside actual09:40–09:41; does not imply --send")
    parser.add_argument("--state-dir", type=Path, help="independent private directory named opening-limitup")
    parser.add_argument("--output-dir", help="optional preview directory named opening-limitup-preview")
    parser.add_argument("--market-db", default=str(Path(__file__).resolve().parent / ".cache/chanlun/market_history.sqlite"), help="existing calendar DB, opened read-only")
    args = parser.parse_args(argv)
    out = stdout or sys.stdout
    def emit(body, code=0):
        print(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2), file=out)
        return code
    try:
        preview = _preview_directory(args.output_dir) if args.output_dir else None
    except (ValueError, TypeError):
        return emit({"delivery_status": "blocked_preview_directory"}, 2)
    now = datetime.now(SHANGHAI)
    day = args.date or now.date().isoformat()
    try:
        if date.fromisoformat(day).isoformat() != day: raise ValueError("bad_date")
    except ValueError:
        return emit({"delivery_status": "invalid_date"}, 2)
    if args.send and args.input:
        return emit({"delivery_status": "blocked_offline_input"}, 2)
    window = now.date().isoformat() == day and time(9, 40) <= now.time().replace(tzinfo=None) < time(9, 41)
    if (args.send or args.scheduled) and (not window or not is_trading_day(day, args.market_db)):
        return emit({"delivery_status": "blocked_time_or_calendar", "trade_date": day}, 2 if args.send else 0)
    if not args.input and not is_trading_day(day, args.market_db):
        return emit({"delivery_status": "skipped_closed_or_unsupported_calendar", "trade_date": day}, 0)
    try:
        if args.input:
            evidence = json.loads(args.input.read_text(encoding="utf-8"))
            if args.date and evidence.get("trade_date") != day:
                raise ValueError("input_date_mismatch")
        else:
            budget = 45.0
            if args.send or args.scheduled:
                budget = max(0, min(budget, (now.replace(hour=9, minute=40, second=45, microsecond=0) - now).total_seconds()))
            if budget <= 0:
                evidence = {"trade_date": day, "issues": ["collection_deadline_passed"]}
            else:
                evidence = (collector or collect_opening_evidence)(day, args.market_db, budget_seconds=budget)
        response = deliver(evidence, send=args.send, state_root=args.state_dir, market_db=args.market_db, offline=bool(args.input))
    except Exception as exc:
        evidence = {"trade_date": day, "issues": ["collection_or_input_unavailable:" + type(exc).__name__]}
        response = deliver(evidence, send=args.send, state_root=args.state_dir, market_db=args.market_db, offline=bool(args.input))
    response["offline_replay"] = bool(args.input)
    response["preview_only"] = not args.send
    if preview:
        preview.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_preview_text(preview / "evidence.json", json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        _write_preview_text(preview / "result.json", json.dumps(response, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        _write_preview_text(preview / "message.txt", response["message"] + "\n")
    return emit(response, 2 if args.send and str(response["delivery_status"]).startswith("blocked_") else 0)


if __name__ == "__main__":
    raise SystemExit(main())
