#!/usr/bin/env python3
"""Repair missing turnover amounts with an explicitly audited proxy policy."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chanlun.market_history_store import MarketHistoryStore  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repair_missing_amounts(
    database_path: Any,
    run_id: str,
    intervals: Sequence[str] = ("day", "30m", "15m"),
) -> Dict[str, Any]:
    selected = list(dict.fromkeys(str(value) for value in intervals))
    per_interval = {}
    with MarketHistoryStore(database_path) as store:
        store.start_ingest_run(
            run_id,
            "repair_amount_proxy",
            metadata={
                "amount_policy": "volume_close_100_proxy",
                "intervals": selected,
            },
        )
        try:
            with store.connection:
                for interval in selected:
                    table = MarketHistoryStore._table(interval)
                    cursor = store.connection.execute(
                        """
                        UPDATE {table}
                        SET amount=volume * close * 100.0,
                            updated_at=?
                        WHERE amount<=0 AND volume>=0 AND close>0
                        """.format(table=table),
                        (_utc_now(),),
                    )
                    per_interval[interval] = int(cursor.rowcount)
        except Exception as exc:
            store.finish_ingest_run(
                run_id,
                "failed",
                rows_written=0,
                metadata={
                    "amount_policy": "volume_close_100_proxy",
                    "intervals": selected,
                    "error": "{}: {}".format(type(exc).__name__, exc),
                },
            )
            raise
        rows_repaired = sum(per_interval.values())
        store.finish_ingest_run(
            run_id,
            "complete",
            rows_written=rows_repaired,
            metadata={
                "amount_policy": "volume_close_100_proxy",
                "intervals": selected,
                "per_interval": per_interval,
            },
        )
    return {
        "run_id": str(run_id),
        "rows_repaired": rows_repaired,
        "per_interval": per_interval,
        "amount_policy": "volume_close_100_proxy",
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--interval",
        action="append",
        choices=("day", "30m", "15m"),
    )
    args = parser.parse_args(argv)
    result = repair_missing_amounts(
        args.db,
        args.run_id,
        intervals=args.interval or ("day", "30m", "15m"),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
