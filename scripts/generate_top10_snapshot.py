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


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


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


def _resolve_action(row: Mapping[str, Any]) -> str:
    for value in (
        row.get("action"),
        _safe_str(_as_mapping(row.get("decision_engine_v1")).get("decision")),
        row.get("type"),
        _safe_str(_as_mapping(row.get("best_buy_point")).get("confirmed_by")),
    ):
        text = _safe_str(value)
        if text:
            return text
    return ""


def _resolve_reason(row: Mapping[str, Any]) -> str:
    for value in (
        row.get("action_reason"),
        _safe_str(_as_mapping(row.get("best_buy_point")).get("reason")),
        row.get("sublevel_confirm_reason"),
        row.get("watch_reason"),
    ):
        text = _safe_str(value)
        if text:
            return text
    return "Top10 candidate"


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
        "code": code,
        "name": _safe_str(row.get("name")),
        "score": _resolve_score(row),
        "action": _resolve_action(row),
        "reason": _resolve_reason(row),
        "source": source,
        "change_pct": _resolve_change_pct(row),
        "current_price": _resolve_current_price(row),
    }


def _collect_candidates(report: Mapping[str, Any], diagnostics: dict[str, Any]) -> tuple[list[dict[str, Any]], str, bool]:
    workspace = _as_mapping(report.get("workspace"))
    views = _as_mapping(workspace.get("views"))
    highlights = _as_list(views.get("highlights"))
    if highlights:
        rows: list[dict[str, Any]] = []
        for row in highlights:
            if isinstance(row, Mapping):
                mapped = _as_mapping(row)
                mapped["_top10_source"] = "highlights"
                rows.append(mapped)
        source_rows = [
            (row, "highlights", _resolve_score(row)) for row in rows if _safe_str(row.get("code"))
        ]
        diagnostics["selected_source"] = "highlights"
        diagnostics["fallback_used"] = False
        diagnostics["raw_source_counts"] = {"highlights": len(source_rows)}
        return [row for row, _, _ in sorted(source_rows, key=lambda item: item[2], reverse=True)], "highlights", False

    source_map = [
        ("picks_fusion", "picks_fusion"),
        ("picks_pure", "picks_pure"),
        ("startup_watchlist", "startup_watchlist"),
    ]
    source_rows: list[tuple[dict[str, Any], str, float]] = []
    diagnostics["raw_source_counts"] = {}
    for source, source_name in source_map:
        rows = _as_list(report.get(source))
        typed_rows = []
        for row in rows:
            mapped = _as_mapping(row)
            if not _safe_str(mapped.get("code")):
                continue
            mapped["_top10_source"] = source_name
            typed_rows.append(mapped)
        diagnostics["raw_source_counts"][source] = len(typed_rows)
        for row in typed_rows:
            source_rows.append((row, source_name, _resolve_score(row)))

    diagnostics["fallback_used"] = True
    diagnostics["selected_source"] = "fallback"

    sorted_rows = sorted(source_rows, key=lambda item: (item[2], item[0].get("view_rank", 0)), reverse=True)
    return [row for row, _, _ in sorted_rows], "fallback", True


def _dedupe_by_code(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _safe_str(row.get("code"))
        if not code:
            continue
        if code not in seen or _resolve_score(row) > _resolve_score(seen[code]):
            seen[code] = dict(row)
    return list(seen.values())


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
    snapshot_date = _choose_snapshot_date(manifest)
    diagnostics["snapshot_date"] = snapshot_date

    snapshot_path = data_dir / f"{snapshot_date}.json"
    if not snapshot_path.exists():
        root_data_path = data_dir.parent / "data.json"
        snapshot_path = root_data_path if root_data_path.exists() else data_dir / "data.json"
    snapshot = _load_json(snapshot_path)
    diagnostics["snapshot_path"] = str(snapshot_path)

    raw_rows, selected_source, fallback_used = _collect_candidates(snapshot, diagnostics)
    rows = _dedupe_by_code(raw_rows)
    ranked_rows = rows
    if selected_source == "highlights":
        ranked_rows = rows[:]
    else:
        ranked_rows = sorted(rows, key=lambda row: (_resolve_score(row), _safe_str(row.get("name")), _safe_str(row.get("code"))), reverse=True)

    diagnostics["candidate_count"] = len(ranked_rows)
    diagnostics["selected_source"] = selected_source
    diagnostics["fallback_used"] = fallback_used

    items = []
    for index, row in enumerate(ranked_rows[:10], start=1):
        row_dict = _as_mapping(row)
        items.append(_build_item(row_dict, index, _safe_str(row_dict.get("_top10_source", selected_source), selected_source)))

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
