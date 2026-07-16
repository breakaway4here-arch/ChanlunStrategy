#!/usr/bin/env python3
"""Generate a compact Top10 snapshot payload from docs/data fixtures."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT_DIR / "docs" / "data"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.validate_today_report import (  # noqa: E402
    validate_manifest_contract,
    validate_report_contract,
)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = _safe_str(item)
        if text:
            out.append(text)
    return out


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _choose_snapshot_date(manifest: Mapping[str, Any]) -> str:
    for key in ("latest_trading_date", "latest"):
        value = _safe_str(manifest.get(key))
        if value:
            return value
    for key in ("trading_dates", "dates"):
        dates = _as_str_list(manifest.get(key))
        if dates:
            return dates[-1]
    raise ValueError("manifest missing latest/latest_trading_date/dates fields")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid JSON object in {path}")
    return payload


def _resolve_score(row: Mapping[str, Any]) -> float:
    for key in ("opportunity_score", "watch_score", "score"):
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return 0.0


def _resolve_change_pct(row: Mapping[str, Any]) -> Optional[float]:
    for value in (row.get("change_pct"), _as_mapping(row.get("best_buy_point")).get("change_pct")):
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _resolve_current_price(row: Mapping[str, Any]) -> Optional[float]:
    for value in (
        row.get("current_price"),
        row.get("close"),
        _as_mapping(row.get("best_buy_point")).get("current_price"),
        _as_mapping(row.get("best_buy_point")).get("price"),
        row.get("reference_price"),
    ):
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _build_item(row: Mapping[str, Any], rank: int, source: str) -> dict[str, Any]:
    code = _safe_str(row.get("code"))
    if not code:
        raise ValueError("candidate missing code")

    return {
        "rank": rank,
        "view_rank": row.get("view_rank"),
        "code": code,
        "name": _safe_str(row.get("name")),
        "score": _resolve_score(row),
        "action": _safe_str(row.get("action")),
        "action_reason": _safe_str(row.get("action_reason")),
        "reason": _safe_str(row.get("primary_reason")) or _safe_str(row.get("reason")),
        "source": source,
        "change_pct": _resolve_change_pct(row),
        "current_price": _resolve_current_price(row),
    }


def _collect_candidates(report: Mapping[str, Any], diagnostics: dict[str, Any]) -> tuple[list[dict[str, Any]], str, bool]:
    workspace_value = report.get("workspace")
    if not isinstance(workspace_value, Mapping):
        raise ValueError("report missing workspace.views.highlights")
    views_value = workspace_value.get("views")
    if not isinstance(views_value, Mapping) or "highlights" not in views_value:
        raise ValueError("report missing workspace.views.highlights")
    highlights_value = views_value.get("highlights")
    if not isinstance(highlights_value, (list, tuple)):
        raise ValueError("report workspace.views.highlights must be an array")

    rows: list[dict[str, Any]] = []
    for expected_rank, row in enumerate(highlights_value, start=1):
        if not isinstance(row, Mapping):
            raise ValueError("report workspace.views.highlights contains a non-object row")
        view_rank = row.get("view_rank")
        if (
            isinstance(view_rank, bool)
            or not isinstance(view_rank, int)
            or view_rank <= 0
            or view_rank != expected_rank
        ):
            raise ValueError(
                "report workspace.views.highlights view_rank must be a positive "
                f"integer matching array position: expected {expected_rank}, got {view_rank!r}"
            )
        mapped = dict(row)
        mapped["_top10_source"] = "highlights"
        rows.append(mapped)

    diagnostics["selected_source"] = "highlights"
    diagnostics["fallback_used"] = False
    diagnostics["raw_source_counts"] = {"highlights": len(rows)}
    return rows, "highlights", False


def build_snapshot_payload(
    job_id: str,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    data_dir = data_dir.expanduser().resolve()
    diagnostics: dict[str, Any] = {
        "data_dir": str(data_dir),
    }

    manifest = _load_json(data_dir / "index.json")
    diagnostics["manifest_path"] = str(data_dir / "index.json")
    manifest_errors = validate_manifest_contract(manifest)
    if manifest_errors:
        raise ValueError(
            "Top10 manifest contract invalid: " + "; ".join(manifest_errors)
        )
    snapshot_date = _choose_snapshot_date(manifest)
    diagnostics["snapshot_date"] = snapshot_date

    if (
        snapshot_date not in manifest["dates"]
        or snapshot_date not in manifest["trading_dates"]
    ):
        raise ValueError(
            "Top10 manifest contract invalid: selected date must belong to dates and trading_dates"
        )

    date_meta = manifest["date_meta"]
    selected_meta = date_meta.get(snapshot_date)
    if not isinstance(selected_meta, Mapping) or not (
        selected_meta.get("is_trading_day") is True
        and selected_meta.get("is_official") is True
    ):
        raise ValueError(
            "Top10 manifest contract invalid: selected date_meta must be trading and official"
        )

    snapshot_path = data_dir / f"{snapshot_date}.json"
    if not snapshot_path.exists():
        root_data_path = data_dir.parent / "data.json"
        snapshot_path = root_data_path if root_data_path.exists() else data_dir / "data.json"
    snapshot = _load_json(snapshot_path)
    diagnostics["snapshot_path"] = str(snapshot_path)
    report_date = _safe_str(snapshot.get("date"))
    quality_report_date = _safe_str(
        _as_mapping(snapshot.get("data_quality")).get("report_date")
    )
    if report_date != snapshot_date or quality_report_date != snapshot_date:
        raise ValueError(
            "Top10 selected snapshot_date must match report.date and "
            "data_quality.report_date"
        )
    raw_rows, selected_source, fallback_used = _collect_candidates(snapshot, diagnostics)
    report_errors = validate_report_contract(snapshot, require_official=True)
    if report_errors:
        raise ValueError(
            "Top10 report contract invalid: " + "; ".join(report_errors)
        )

    ranked_rows = raw_rows

    diagnostics["candidate_count"] = len(ranked_rows)
    diagnostics["selected_source"] = selected_source
    diagnostics["fallback_used"] = fallback_used

    items = []
    for row in ranked_rows[:10]:
        row_dict = _as_mapping(row)
        items.append(_build_item(
            row_dict,
            row_dict["view_rank"],
            _safe_str(row_dict.get("_top10_source", selected_source), selected_source),
        ))

    return {
        "job_id": job_id,
        "generated_at": _now_iso(),
        "source": "github_actions",
        "status": "done",
        "snapshot_date": snapshot_date,
        "items": items,
        "diagnostics": diagnostics,
    }


def write_payload(payload: Mapping[str, Any], output_path: Path) -> None:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate compact Top10 snapshot")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output_path = Path(args.output)

    try:
        payload = build_snapshot_payload(args.job_id, Path(args.data_dir))
        write_payload(payload, output_path)
        return 0
    except Exception as exc:  # pragma: no cover - exercised by behavior on malformed inputs
        diagnostics = {
            "data_dir": str(Path(args.data_dir).resolve()),
            "error": f"{exc}",
            "traceback": traceback.format_exc().splitlines()[:3],
            "status": "failed",
        }
        payload = {
            "job_id": args.job_id,
            "generated_at": _now_iso(),
            "source": "github_actions",
            "status": "failed",
            "snapshot_date": None,
            "items": [],
            "diagnostics": diagnostics,
        }
        write_payload(payload, output_path)
        print(f"Top10 snapshot generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
