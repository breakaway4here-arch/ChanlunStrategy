#!/usr/bin/env python3
"""Backfill canonical market history through isolated, resumable SQLite shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chanlun import data_fetcher  # noqa: E402
from chanlun.market_history_store import MarketHistoryStore  # noqa: E402
from config import MARKET_HISTORY_DB_PATH, MIN15_LOOKBACK_BARS  # noqa: E402


DEFAULT_SHARD_COUNT = 20
DEFAULT_WORKERS = 3
DEFAULT_COUNTS = {"day": 1000, "30m": 500, "15m": MIN15_LOOKBACK_BARS}
_CN_TZ = timezone(timedelta(hours=8))


class BackfillIncomplete(RuntimeError):
    """Raised when shard evidence is insufficient for an atomic master merge."""


def _normalized_codes(codes: Iterable[Any]) -> List[str]:
    normalized = {
        str(code).strip()
        for code in codes
        if str(code).strip().isdigit() and len(str(code).strip()) == 6
    }
    return sorted(normalized)


def stable_code_shards(
    codes: Iterable[Any], shard_count: int = DEFAULT_SHARD_COUNT
) -> List[List[str]]:
    """Return deterministic `codes[i::shard_count]` partitions."""
    count = int(shard_count)
    if count <= 0:
        raise ValueError("shard_count must be positive")
    normalized = _normalized_codes(codes)
    return [normalized[index::count] for index in range(count)]


def _code_checksum(
    run_id: str,
    interval: str,
    count: int,
    shard_id: int,
    shard_count: int,
    codes: Sequence[str],
) -> str:
    payload = {
        "run_id": str(run_id),
        "interval": str(interval),
        "count": int(count),
        "shard_id": int(shard_id),
        "shard_count": int(shard_count),
        "codes": list(codes),
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _exchange_for_code(code: str) -> str:
    return "SH" if data_fetcher._is_sh(code) else "SZ"


def _listed_days(listed_date: Any, as_of: str) -> Optional[int]:
    text = str(listed_date or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        listed = datetime.strptime(text, "%Y%m%d").date()
        target = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(0, (target - listed).days)


def _safe_sequence(value: Any) -> List[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def _optional_number(values: Sequence[Any], index: int) -> float:
    if index >= len(values):
        return 0.0
    try:
        number = float(values[index])
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number >= 0 else 0.0


def _parse_timestamp(value: str) -> Optional[datetime]:
    text = str(value).strip().replace("T", " ")
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_CN_TZ)
    return parsed.astimezone(_CN_TZ)


def _is_final_bar(interval: str, ts: str, now: datetime) -> bool:
    parsed = _parse_timestamp(ts)
    if parsed is None:
        return False
    current = now.astimezone(_CN_TZ)
    if interval == "day":
        if parsed.date() < current.date():
            return True
        return parsed.date() == current.date() and current.time() >= datetime.strptime(
            "15:00", "%H:%M"
        ).time()
    minutes = 30 if interval == "30m" else 15
    return parsed + timedelta(minutes=minutes) <= current


def kline_payload_to_bars(
    payload: Mapping[str, Any],
    interval: str,
    adjustment: str,
    source_batch: str,
    ingest_run_id: str,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Convert the repository's public array shape into validated bar rows."""
    dates = _safe_sequence(payload.get("dates"))
    required = {
        "opens": _safe_sequence(payload.get("opens")),
        "highs": _safe_sequence(payload.get("highs")),
        "lows": _safe_sequence(payload.get("lows")),
        "closes": _safe_sequence(payload.get("closes")),
        "volumes": _safe_sequence(payload.get("volumes")),
    }
    if not dates:
        return []
    if any(len(values) != len(dates) for values in required.values()):
        raise ValueError("kline arrays must have identical lengths")
    amounts = _safe_sequence(payload.get("amounts"))
    current = now or datetime.now(_CN_TZ)
    bars = []
    seen_timestamps = set()
    for index, raw_ts in enumerate(dates):
        parsed = _parse_timestamp(str(raw_ts))
        if parsed is None:
            raise ValueError("invalid kline timestamp: {}".format(raw_ts))
        ts = (
            parsed.strftime("%Y-%m-%d")
            if interval == "day"
            else parsed.strftime("%Y-%m-%d %H:%M:%S")
        )
        if ts in seen_timestamps:
            raise ValueError("duplicate kline timestamp: {}".format(ts))
        seen_timestamps.add(ts)
        bars.append(
            {
                "ts": ts,
                "open": required["opens"][index],
                "high": required["highs"][index],
                "low": required["lows"][index],
                "close": required["closes"][index],
                "volume": required["volumes"][index],
                "amount": _optional_number(amounts, index),
                "adjustment": adjustment,
                "is_final": _is_final_bar(interval, ts, current),
                "source_batch": source_batch,
                "ingest_run_id": ingest_run_id,
            }
        )
    return sorted(bars, key=lambda row: row["ts"])


def _existing_manifest(
    store: MarketHistoryStore, run_id: str, shard_id: int
) -> Optional[Dict[str, Any]]:
    for manifest in store.list_shard_manifests(run_id):
        if int(manifest["shard_id"]) == int(shard_id):
            return manifest
    return None


def run_shard(
    run_id: str,
    shard_id: int,
    shard_count: int,
    interval: str,
    codes: Sequence[str],
    staging_path: Any,
    fetcher: Callable[[str, int], Optional[Mapping[str, Any]]],
    count: Optional[int] = None,
    adjustment: str = "qfq",
    now: Optional[datetime] = None,
    stock_metadata: Optional[Mapping[str, Mapping[str, Any]]] = None,
    meta_as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Run or resume one deterministic shard in its own staging database."""
    if interval not in DEFAULT_COUNTS:
        raise ValueError("unsupported interval: {}".format(interval))
    expected_count = int(count or DEFAULT_COUNTS[interval])
    normalized = _normalized_codes(codes)
    checksum = _code_checksum(
        run_id, interval, expected_count, shard_id, shard_count, normalized
    )
    source_batch = "{}:{}".format(run_id, shard_id)
    failures = []
    insufficient = []
    success_count = 0
    changed_rows = 0
    metadata_by_code = dict(stock_metadata or {})
    metadata_date = meta_as_of or (now or datetime.now(_CN_TZ)).astimezone(
        _CN_TZ
    ).date().isoformat()

    with MarketHistoryStore(staging_path) as store:
        previous = _existing_manifest(store, run_id, shard_id)
        if previous is not None:
            previous_checksum = previous.get("checksum") or previous["metadata"].get(
                "code_checksum"
            )
            if previous_checksum and previous_checksum != checksum:
                raise BackfillIncomplete(
                    "shard {} input checksum changed".format(shard_id)
                )
            if previous["status"] == "complete":
                metadata = dict(previous["metadata"])
                metadata.update(
                    {
                        "status": "complete",
                        "row_count": int(previous["row_count"]),
                    }
                )
                return metadata

        for code in normalized:
            try:
                payload = fetcher(code, expected_count)
                if not payload:
                    raise RuntimeError("remote_unavailable")
                bars = kline_payload_to_bars(
                    payload,
                    interval=interval,
                    adjustment=adjustment,
                    source_batch=source_batch,
                    ingest_run_id=run_id,
                    now=now,
                )
                if not bars:
                    raise RuntimeError("empty_history")
                stock_meta = dict(metadata_by_code.get(code) or {})
                instrument_id = store.upsert_instrument(
                    "stock",
                    _exchange_for_code(code),
                    code,
                    name=str(stock_meta.get("name") or ""),
                )
                if stock_meta:
                    if "listed_days" not in stock_meta:
                        stock_meta["listed_days"] = _listed_days(
                            stock_meta.get("listed_date"), metadata_date
                        )
                    store.upsert_stock_meta(
                        instrument_id, metadata_date, stock_meta
                    )
                changed_rows += store.upsert_bars(
                    interval,
                    instrument_id,
                    bars,
                    adjustment=adjustment,
                    ingest_run_id=run_id,
                )
                if len(bars) < expected_count:
                    insufficient.append(
                        {
                            "code": code,
                            "bars": len(bars),
                            "required": expected_count,
                            "reason": "insufficient_history",
                        }
                    )
                else:
                    success_count += 1
            except Exception as exc:
                failures.append(
                    {
                        "code": code,
                        "reason": type(exc).__name__,
                        "message": str(exc),
                    }
                )

        status = "failed" if failures else "complete"
        table = MarketHistoryStore._table(interval)
        total_rows = int(
            store.connection.execute(
                "SELECT COUNT(*) FROM {}".format(table)
            ).fetchone()[0]
        )
        metadata = {
            "status": status,
            "interval": interval,
            "requested_count": expected_count,
            "code_count": len(normalized),
            "processed_count": len(normalized),
            "success_count": success_count,
            "insufficient_count": len(insufficient),
            "failure_count": len(failures),
            "changed_rows": changed_rows,
            "insufficient": insufficient,
            "failures": failures,
            "code_checksum": checksum,
        }
        store.upsert_shard_manifest(
            run_id,
            shard_id,
            shard_count,
            status,
            row_count=total_rows,
            checksum=checksum,
            metadata=metadata,
        )
        return metadata


def validate_complete_manifests(
    staging_paths: Sequence[Any], run_id: str, expected_shards: int
) -> List[Dict[str, Any]]:
    manifests = {}
    for path in staging_paths:
        with MarketHistoryStore(path, readonly=True, immutable=True) as store:
            rows = store.list_shard_manifests(run_id)
        for row in rows:
            shard_id = int(row["shard_id"])
            if shard_id in manifests:
                raise BackfillIncomplete("duplicate shard manifest: {}".format(shard_id))
            manifests[shard_id] = row
    expected_ids = set(range(int(expected_shards)))
    if set(manifests) != expected_ids:
        raise BackfillIncomplete(
            "manifest shards mismatch: expected {}, got {}".format(
                sorted(expected_ids), sorted(manifests)
            )
        )
    for shard_id, row in manifests.items():
        if int(row["shard_count"]) != int(expected_shards):
            raise BackfillIncomplete(
                "shard {} reports shard_count {}".format(
                    shard_id, row["shard_count"]
                )
            )
        if row["status"] != "complete":
            raise BackfillIncomplete(
                "shard {} is not complete: {}".format(shard_id, row["status"])
            )
        if not str(row.get("checksum") or "").strip():
            raise BackfillIncomplete("shard {} missing checksum".format(shard_id))
    return [manifests[index] for index in sorted(manifests)]


def merge_completed_run(
    target_path: Any,
    staging_paths: Sequence[Any],
    run_id: str,
    expected_shards: int,
) -> Dict[str, int]:
    """Validate evidence, atomically merge all shards, and close the master run."""
    validate_complete_manifests(staging_paths, run_id, expected_shards)
    with MarketHistoryStore(target_path) as store:
        store.start_ingest_run(
            run_id,
            "backfill",
            metadata={"expected_shards": int(expected_shards)},
        )
        try:
            result = store.merge_staging_databases(staging_paths)
        except Exception as exc:
            store.finish_ingest_run(
                run_id,
                "failed",
                rows_written=0,
                metadata={
                    "expected_shards": int(expected_shards),
                    "error": str(exc),
                },
            )
            raise
        store.finish_ingest_run(
            run_id,
            "complete",
            rows_written=int(result["bars"]),
            metadata={
                "expected_shards": int(expected_shards),
                "merged_shards": len(staging_paths),
            },
        )
        return result


def _remote_fetcher(interval: str):
    if interval == "day":
        sources = (
            data_fetcher._fetch_daily_kline_remote,
            data_fetcher._fetch_daily_kline_eastmoney_remote,
            data_fetcher._fetch_daily_kline_sina_daily_remote,
        )
        return lambda code, count: _retry_fetch(
            code, count, sources
        )
    if interval == "30m":
        return lambda code, count: _retry_fetch(
            code,
            count,
            (
                lambda current, size: (
                    data_fetcher._fetch_eastmoney_minute_kline_remote(
                        current, 30, size
                    )
                ),
            ),
        )
    if interval == "15m":
        return lambda code, count: _retry_fetch(
            code,
            count,
            (
                lambda current, size: (
                    data_fetcher._fetch_eastmoney_minute_kline_remote(
                        current, 15, size
                    )
                ),
            ),
        )
    raise ValueError("unsupported interval: {}".format(interval))


def _retry_fetch(
    code: str,
    count: int,
    fetchers: Sequence[Callable[[str, int], Optional[Mapping[str, Any]]]],
    attempts: int = 3,
    base_delay: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Optional[Mapping[str, Any]]:
    """Try providers sequentially, then retry the provider chain with backoff."""
    total_attempts = max(1, int(attempts))
    for attempt in range(total_attempts):
        for fetcher in fetchers:
            try:
                payload = fetcher(code, count)
            except Exception:
                payload = None
            if payload:
                return payload
        if attempt + 1 < total_attempts:
            sleep_fn(float(base_delay) * (2 ** attempt))
    return None


def _read_codes(path: Optional[str], inline: Optional[str]) -> List[str]:
    values = []
    if path:
        text = Path(path).read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = [line.strip() for line in text.splitlines()]
        if isinstance(payload, dict):
            payload = payload.get("codes", [])
        for item in payload or []:
            values.append(item.get("code") if isinstance(item, dict) else item)
    if inline:
        values.extend(inline.split(","))
    return _normalized_codes(values)


def run_backfill(
    target_path: Any,
    staging_dir: Any,
    run_id: str,
    interval: str,
    codes: Sequence[str],
    shard_count: int = DEFAULT_SHARD_COUNT,
    workers: int = DEFAULT_WORKERS,
    count: Optional[int] = None,
    stock_metadata: Optional[Mapping[str, Mapping[str, Any]]] = None,
    meta_as_of: Optional[str] = None,
) -> Dict[str, Any]:
    shards = stable_code_shards(codes, shard_count)
    root = Path(staging_dir)
    root.mkdir(parents=True, exist_ok=True)
    fetcher = _remote_fetcher(interval)
    paths = build_staging_paths(root, run_id, interval, shard_count)
    results = [None] * shard_count
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), shard_count))) as pool:
        futures = {
            pool.submit(
                run_shard,
                run_id,
                index,
                shard_count,
                interval,
                shards[index],
                paths[index],
                fetcher=fetcher,
                count=count,
                stock_metadata=stock_metadata,
                meta_as_of=meta_as_of,
            ): index
            for index in range(shard_count)
        }
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    failed = [
        index for index, result in enumerate(results)
        if not result or result.get("status") != "complete"
    ]
    if failed:
        raise BackfillIncomplete("failed shards: {}".format(failed))
    merged = merge_completed_run(target_path, paths, run_id, shard_count)
    return {"shards": results, "merge": merged, "staging_paths": paths}


def build_staging_paths(
    staging_dir: Any, run_id: str, interval: str, shard_count: int
) -> List[Path]:
    root = Path(staging_dir)
    return [
        root / "{}.{}.shard-{:02d}.sqlite".format(run_id, interval, index)
        for index in range(int(shard_count))
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", choices=sorted(DEFAULT_COUNTS), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db", default=MARKET_HISTORY_DB_PATH)
    parser.add_argument("--staging-dir", default=".cache/chanlun/backfill")
    parser.add_argument("--codes-file")
    parser.add_argument("--codes")
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--shard-id",
        type=int,
        help="run one logical shard only; use --merge-only after all shards finish",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="validate and atomically merge existing staging databases",
    )
    parser.add_argument("--count", type=int)
    args = parser.parse_args(argv)

    if args.merge_only and args.shard_id is not None:
        parser.error("--merge-only and --shard-id are mutually exclusive")
    paths = build_staging_paths(
        args.staging_dir, args.run_id, args.interval, args.shards
    )
    if args.merge_only:
        merged = merge_completed_run(
            args.db, paths, args.run_id, args.shards
        )
        print(json.dumps({"run_id": args.run_id, "merge": merged}, sort_keys=True))
        return 0

    codes = _read_codes(args.codes_file, args.codes)
    stock_metadata = {}
    if not codes:
        if args.interval == "15m":
            parser.error("15m backfill requires --codes or --codes-file")
        stocks, diagnostics = data_fetcher.fetch_all_a_stocks(
            return_diagnostics=True
        )
        if not diagnostics["complete"]:
            raise BackfillIncomplete(
                "full A-share universe incomplete: {}".format(diagnostics)
            )
        codes = [row["code"] for row in stocks]
        stock_metadata = {row["code"]: row for row in stocks}
    if args.shard_id is not None:
        if args.shard_id < 0 or args.shard_id >= args.shards:
            parser.error("--shard-id must be in [0, shards)")
        shards = stable_code_shards(codes, args.shards)
        Path(args.staging_dir).mkdir(parents=True, exist_ok=True)
        result = run_shard(
            args.run_id,
            args.shard_id,
            args.shards,
            args.interval,
            shards[args.shard_id],
            paths[args.shard_id],
            fetcher=_remote_fetcher(args.interval),
            count=args.count,
            stock_metadata=stock_metadata,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "complete" else 2
    result = run_backfill(
        args.db,
        args.staging_dir,
        args.run_id,
        args.interval,
        codes,
        shard_count=args.shards,
        workers=args.workers,
        count=args.count,
        stock_metadata=stock_metadata,
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "interval": args.interval,
                "codes": len(codes),
                "bars_written": result["merge"]["bars"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
