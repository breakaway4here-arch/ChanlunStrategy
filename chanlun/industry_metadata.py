"""DB-first industry metadata hydration for the canonical market history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping

from .market_history_store import MarketHistoryStore


def _has_industry(metadata: Mapping[str, Any]) -> bool:
    return bool(str((metadata or {}).get("industry") or "").strip())


def _is_a_share_identity(instrument: Mapping[str, Any]) -> bool:
    """Exclude B shares and stale rows stored under an impossible exchange."""
    exchange = str(instrument.get("exchange") or "").upper()
    code = str(instrument.get("code") or "")
    if exchange == "SH":
        return code.startswith("6")
    if exchange == "SZ":
        return code.startswith(("0", "3"))
    if exchange == "BJ":
        return code.startswith(("4", "8"))
    return False


def _remote_rows(result: Any) -> Iterable[Mapping[str, Any]]:
    """Support the fetcher's optional ``(rows, diagnostics)`` return shape."""
    if isinstance(result, tuple):
        result = result[0]
    return result if isinstance(result, list) else []


def hydrate_industry_metadata(
    db_path: Any,
    report_date: str,
    fetch_all_a_stocks: Callable[[], Any],
) -> Dict[str, Any]:
    """Ensure the DB snapshot has industry labels, fetching once only if needed."""
    path = Path(db_path)
    diagnostics = {
        "status": "complete",
        "db_path": str(path),
        "report_date": str(report_date),
        "instrument_count": 0,
        "total_instrument_count": 0,
        "ignored_non_a_instruments": 0,
        "db_complete": 0,
        "missing_before": 0,
        "missing_after": 0,
        "remote_calls": 0,
        "remote_rows": 0,
        "remote_matched": 0,
        "hydrated": 0,
        "industry_complete": False,
    }
    if not path.exists():
        diagnostics.update(status="fallback", reason="market_history_db_missing")
        return diagnostics

    with MarketHistoryStore(path) as store:
        all_instruments = store.list_instruments(asset_type="stock")
        instruments = [
            row for row in all_instruments if _is_a_share_identity(row)
        ]
        metadata = store.query_stock_meta_many(
            [row["instrument_id"] for row in instruments], as_of=report_date
        )
        by_code = {str(row["code"]): row for row in instruments}
        missing_codes = [
            code for code, instrument in by_code.items()
            if not _has_industry(metadata.get(instrument["instrument_id"], {}))
        ]
        diagnostics.update(
            instrument_count=len(instruments),
            total_instrument_count=len(all_instruments),
            ignored_non_a_instruments=len(all_instruments) - len(instruments),
            db_complete=len(instruments) - len(missing_codes),
            missing_before=len(missing_codes),
        )
        if not missing_codes:
            diagnostics["industry_complete"] = True
            return diagnostics

        diagnostics["remote_calls"] = 1
        fetched = list(_remote_rows(fetch_all_a_stocks()))
        diagnostics["remote_rows"] = len(fetched)
        remote_by_code = {
            str(row.get("code") or "").strip(): row
            for row in fetched
            if isinstance(row, Mapping) and str(row.get("code") or "").strip()
        }
        writes = []
        for code in missing_codes:
            remote = remote_by_code.get(code)
            if not remote or not _has_industry(remote):
                continue
            instrument = by_code[code]
            existing = dict(metadata.get(instrument["instrument_id"], {}))
            existing.pop("as_of", None)
            # This hydrator owns only the industry label.  The remote full-A
            # list is not authoritative for listing age, market cap or risk
            # flags, so never let its sparse fields replace canonical values.
            existing["industry"] = str(remote["industry"]).strip()
            writes.append((instrument["instrument_id"], str(report_date), existing))
            diagnostics["remote_matched"] += 1
        diagnostics["hydrated"] = store.upsert_stock_meta_many(writes)

        merged = store.query_stock_meta_many(
            [row["instrument_id"] for row in instruments], as_of=report_date
        )
        diagnostics["missing_after"] = sum(
            not _has_industry(merged.get(row["instrument_id"], {}))
            for row in instruments
        )
        diagnostics["industry_complete"] = diagnostics["missing_after"] == 0
        if not diagnostics["industry_complete"]:
            diagnostics["status"] = "partial"
    return diagnostics
