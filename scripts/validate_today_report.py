#!/usr/bin/env python3
"""Validate that today's published report uses trustworthy market index data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run import fetch_market_indices  # noqa: E402
from typing import Any, Mapping, Optional


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_float_list(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        raw = value
    elif hasattr(value, "tolist"):
        try:
            raw = list(value.tolist())  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            return []
    else:
        return []

    result: list[float] = []
    for item in raw:
        num = _safe_float(item)
        if num is not None:
            result.append(num)
    return result


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _resolve_change_pct(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not row:
        return None
    direct = _safe_float(row.get("change_pct"))
    if direct is not None:
        return direct
    bp = _as_mapping(row.get("best_buy_point"))
    bp_change = _safe_float(bp.get("change_pct"))
    if bp_change is not None:
        return bp_change
    closes = _to_float_list(row.get("closes"))
    if len(closes) < 2:
        return None
    prev_close = closes[-2]
    latest_close = closes[-1]
    if prev_close in (None, 0) or latest_close is None:
        return None
    return round((latest_close - prev_close) / prev_close * 100, 2)


def _resolve_current_price(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not row:
        return None
    direct = _safe_float(row.get("current_price"))
    if direct is not None:
        return direct

    bp = _as_mapping(row.get("best_buy_point"))
    direct = _safe_float(bp.get("current_price"))
    if direct is not None:
        return direct

    direct = _safe_float(row.get("close"))
    if direct is not None:
        return direct

    closes = _to_float_list(row.get("closes"))
    if closes:
        return closes[-1]
    return None


def _resolve_candidate_candidates(report: Mapping[str, Any], pool: str) -> list[Mapping[str, Any]]:
    value = report.get(pool)
    if pool == "luojie_pool":
        value = _as_mapping(value).get("candidates", [])
    elif pool == "next_day_boom":
        value = _as_mapping(value).get("candidates", [])
    if not isinstance(value, (list, tuple)):
        return []
    return [x for x in value if isinstance(x, Mapping)]


def _resolve_raw_candidate(
    report: Mapping[str, Any],
    ref: Optional[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    if not ref:
        return None
    code = str(ref.get("code", "")).strip()
    if not code:
        return None
    pool_hint = str(ref.get("pool", "")).strip()

    pool_candidates = []
    if pool_hint:
        pool_map = {
            "main": "picks_fusion",
            "highlights": "picks_fusion",
            "acceleration": "next_day_boom",
            "luojie": "luojie_pool",
            "luojie_pool": "luojie_pool",
            "confirming": "startup_watchlist",
            "baseline": "picks_pure",
            "picks_fusion": "picks_fusion",
            "picks_pure": "picks_pure",
            "startup_watchlist": "startup_watchlist",
            "next_day_boom": "next_day_boom",
        }
        pool_name = pool_map.get(pool_hint, pool_hint)
        pool_candidates = _resolve_candidate_candidates(report, pool_name)
        for row in pool_candidates:
            if str(row.get("code", "")).strip() == code:
                return _as_mapping(row)

    all_pools = [
        "picks_fusion",
        "picks_pure",
        "startup_watchlist",
        "next_day_boom",
        "luojie_pool",
    ]
    for pool_name in all_pools:
        for row in _resolve_candidate_candidates(report, pool_name):
            if str(row.get("code", "")).strip() == code:
                return _as_mapping(row)
    return None


def _is_luojie_row(row: Mapping[str, Any]) -> bool:
    sources = row.get("sources")
    if isinstance(sources, (list, tuple)):
        if any(str(source) == "luojie" for source in sources):
            return True
    ref = _as_mapping(row.get("ref"))
    return str(ref.get("pool")) == "luojie_pool" or str(ref.get("pool")) == "luojie"


def _resolve_change_pct_for_view(
    row: Mapping[str, Any],
    report: Mapping[str, Any],
) -> Optional[float]:
    direct = _resolve_change_pct(row)
    if direct is not None:
        return direct
    raw = _resolve_raw_candidate(report, _as_mapping(row.get("ref")))
    return _resolve_change_pct(raw)


def validate_report_contract(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    workspace = _as_mapping(report.get("workspace"))
    views = _as_mapping(workspace.get("views"))
    picks_fusion = _resolve_candidate_candidates(report, "picks_fusion")
    picks_pure = _resolve_candidate_candidates(report, "picks_pure")

    if picks_fusion and not _as_mapping(views).get("main"):
        errors.append("main view missing while picks_fusion is non-empty")
    if picks_pure and not _as_mapping(views).get("baseline"):
        errors.append("baseline view missing while picks_pure is non-empty")

    for view in ("highlights", "main", "baseline"):
        for row in _as_mapping(views).get(view, []) or []:
            if not isinstance(row, Mapping):
                continue
            if not row.get("code"):
                continue
            change = _resolve_change_pct_for_view(row, report)
            row_is_luojie = _is_luojie_row(_as_mapping(row))
            if change is None and not row_is_luojie:
                errors.append(f"{view} row missing displayable change_pct: code={row.get('code')}")
            if row.get("current_price") is None:
                current = _resolve_current_price(_as_mapping(row))
                if current is None:
                    raw = _resolve_raw_candidate(report, _as_mapping(row.get("ref")))
                    current = _resolve_current_price(raw)
                if current is None:
                    errors.append(f"{view} row missing displayable current_price: code={row.get('code')}")

    return errors


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: validate_today_report.py YYYY-MM-DD", file=sys.stderr)
        return 2
    report_date = argv[0]
    path = ROOT / "docs" / "data" / f"{report_date}.json"
    if not path.exists():
        print(f"missing report data: {path}", file=sys.stderr)
        return 1

    report = json.loads(path.read_text(encoding="utf-8"))
    contract_errors = validate_report_contract(report)
    live = fetch_market_indices(report_date=report_date)
    saved = report.get("market") or {}
    errors = []

    if contract_errors:
        print("report contract mismatch:", file=sys.stderr)
        for err in contract_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    for name, live_row in live.items():
        saved_row = saved.get(name) or {}
        live_pct = float(live_row.get("change_pct", 0))
        saved_pct = float(saved_row.get("change_pct", 999))
        live_close = float(live_row.get("close", 0))
        saved_close = float(saved_row.get("close", 0))
        if abs(live_pct - saved_pct) > 0.05 or abs(live_close - saved_close) > 0.05:
            errors.append(
                f"{name}: report close={saved_close} pct={saved_pct}, "
                f"live close={live_close} pct={live_pct}"
            )

    if errors:
        print("market data mismatch:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"report market data validated for {report_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
