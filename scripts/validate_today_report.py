#!/usr/bin/env python3
"""Validate that today's published report uses trustworthy market index data."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run import fetch_market_indices  # noqa: E402
from typing import Any, Optional

TZ_CN = timezone(timedelta(hours=8))


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def validate_manifest_contract(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    if not isinstance(manifest, Mapping):
        return ["manifest must be a mapping"]

    for key in ("dates", "trading_dates", "latest", "latest_trading_date", "date_meta"):
        if key not in manifest:
            errors.append(f"manifest missing required key: {key}")

    if errors:
        return errors

    dates_raw = manifest.get("dates")
    trading_dates_raw = manifest.get("trading_dates")
    latest = str(manifest.get("latest", "")).strip()
    latest_trading_date = str(manifest.get("latest_trading_date", "")).strip()
    date_meta = manifest.get("date_meta")

    if not isinstance(dates_raw, (list, tuple)):
        errors.append("manifest dates must be an array")
    if not isinstance(trading_dates_raw, (list, tuple)):
        errors.append("manifest trading_dates must be an array")
    if not isinstance(date_meta, Mapping):
        errors.append("manifest date_meta must be a mapping")

    if errors:
        return errors

    dates = _as_str_list(dates_raw)
    trading_dates = _as_str_list(trading_dates_raw)
    dates = sorted(set(dates))
    trading_dates = sorted(set(trading_dates))

    if latest and latest not in dates:
        errors.append(f"manifest.latest not in manifest.dates: {latest}")

    valid_trading_dates = set()
    for date_value in trading_dates:
        if date_value not in dates:
            errors.append(f"trading_dates entry not in dates: {date_value}")
            continue
        meta = date_meta.get(date_value, {})
        if not isinstance(meta, Mapping):
            errors.append(f"date_meta[{date_value}] must be an object")
            continue
        if meta.get("is_trading_day") is False:
            errors.append(f"trading_dates contains non-trading day: {date_value}")
        else:
            valid_trading_dates.add(date_value)

    trading_dates = sorted(valid_trading_dates)

    if trading_dates:
        expected_latest_trading_date = trading_dates[-1]
        if latest_trading_date != expected_latest_trading_date:
            errors.append(
                f"manifest.latest_trading_date mismatch: expected {expected_latest_trading_date}, got {latest_trading_date}"
            )
    elif latest_trading_date:
        errors.append("manifest.latest_trading_date should be empty when no trading_dates")

    if latest_trading_date and latest_trading_date not in trading_dates:
        errors.append(f"manifest.latest_trading_date not in manifest.trading_dates: {latest_trading_date}")

    for d in dates:
        meta = date_meta.get(d)
        if not isinstance(meta, Mapping):
            errors.append(f"date_meta missing or invalid for date: {d}")

    return errors


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


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _data_status_daily(row: Any) -> str:
    return str(_as_mapping(_as_mapping(row).get("data_status")).get("daily") or "")


def _has_valid_row_data_status(row: Any) -> bool:
    return _data_status_daily(row) in {"verified", "stale_cache", "missing", "preview"}


def _iter_workspace_rows(report: Mapping[str, Any]):
    workspace = _as_mapping(report.get("workspace"))
    views = _as_mapping(workspace.get("views"))
    for view, rows in views.items():
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if isinstance(row, Mapping):
                yield str(view), row


_EXECUTABLE_WORKSPACE_ACTIONS = {"可上车", "等回踩", "慎追"}


def _decision_action_conflict(row: Mapping[str, Any]) -> Optional[str]:
    decision = _as_mapping(row.get("decision_engine_v1"))
    decision_code = str(decision.get("decision_code") or "").strip().lower()
    action = str(row.get("action") or "").strip()
    if decision_code in {"reject", "observe"} and action in _EXECUTABLE_WORKSPACE_ACTIONS:
        return decision_code
    return None


def _iter_raw_candidates(report: Mapping[str, Any]):
    for pool_name in (
        "picks_fusion",
        "picks_pure",
        "startup_watchlist",
        "observation_watchlist",
        "next_day_boom",
        "luojie_pool",
    ):
        for row in _resolve_candidate_candidates(report, pool_name):
            yield pool_name, row


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
            "observation_top5": "observation_watchlist",
            "observation_watchlist": "observation_watchlist",
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


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def validate_report_contract(
    report: Mapping[str, Any], require_official: bool = False
) -> list[str]:
    errors: list[str] = []
    workspace = _as_mapping(report.get("workspace"))
    views = _as_mapping(workspace.get("views"))
    picks_fusion = _resolve_candidate_candidates(report, "picks_fusion")
    picks_pure = _resolve_candidate_candidates(report, "picks_pure")
    dq_value = report.get("data_quality")
    data_quality: dict[str, Any] = {}
    is_data_quality_present = "data_quality" in report
    if is_data_quality_present and not isinstance(dq_value, Mapping):
        errors.append("data_quality must be a mapping")
    else:
        data_quality = _as_mapping(dq_value)

    is_official = data_quality.get("is_official") is True
    workspace_rows = list(_iter_workspace_rows(report))
    if require_official and not is_official:
        errors.append("publish requires data_quality.is_official == True")
    if is_official:
        report_date = str(report.get("date") or "").strip()
        quality_report_date = str(data_quality.get("report_date") or "").strip()
        generated_at = _parse_iso_datetime(data_quality.get("generated_at"))
        as_of = _parse_iso_datetime(data_quality.get("as_of"))
        if generated_at is None:
            errors.append("official report requires valid data_quality.generated_at")
        elif generated_at.utcoffset() is None:
            errors.append("official report data_quality.generated_at must include timezone")
        if as_of is None:
            errors.append("official report requires valid data_quality.as_of")
            as_of_cn = None
        elif as_of.utcoffset() is None:
            errors.append("official report data_quality.as_of must include timezone")
            as_of_cn = None
        else:
            as_of_cn = as_of.astimezone(TZ_CN)
        if data_quality.get("bar_state") != "closed":
            errors.append("official report requires data_quality.bar_state == 'closed'")
        if data_quality.get("sources_trusted") is not True:
            errors.append("official report requires data_quality.sources_trusted == True")
        if not report_date or quality_report_date != report_date:
            errors.append("official report requires report date consistency")
        if as_of_cn is not None and quality_report_date and as_of_cn.date().isoformat() != quality_report_date:
            errors.append("official report requires data_quality.as_of date == report_date")
        if as_of_cn is not None and (as_of_cn.hour, as_of_cn.minute) < (15, 0):
            errors.append("official report data_quality.as_of must be at or after 15:00 Asia/Shanghai")
        if data_quality.get("market_status") != "verified":
            errors.append("official report requires data_quality.market_status == 'verified'")
        if data_quality.get("fallback_used") is not False:
            errors.append("official report requires data_quality.fallback_used == False")
        if data_quality.get("stock_pool_incomplete") is not False:
            errors.append("official report requires data_quality.stock_pool_incomplete == False")
        if _coerce_int(data_quality.get("stale_stock_count"), default=-1) != 0:
            errors.append("official report requires data_quality.stale_stock_count == 0")
        if _coerce_int(data_quality.get("missing_daily_count"), default=-1) != 0:
            errors.append("official report requires data_quality.missing_daily_count == 0")

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
    for view, row in workspace_rows:
        decision_code = _decision_action_conflict(row)
        if decision_code:
            errors.append(
                f"{view} row decision/action conflict: code={row.get('code')} "
                f"decision_code={decision_code} action={row.get('action')}"
            )

    if is_official:
        for view, row in workspace_rows:
            daily_status = _data_status_daily(row)
            if not _has_valid_row_data_status(row):
                errors.append(f"{view} row missing valid data_status in official report: code={row.get('code')}")
            elif daily_status == "stale_cache":
                errors.append(f"{view} row has stale daily cache in official report: code={row.get('code')}")
            elif daily_status != "verified":
                errors.append(
                    f"{view} row has non-verified daily status in official report: "
                    f"code={row.get('code')} status={daily_status}"
                )
        for pool_name, row in _iter_raw_candidates(report):
            daily_status = _data_status_daily(row)
            if not _has_valid_row_data_status(row):
                errors.append(f"{pool_name} candidate missing valid data_status in official report: code={row.get('code')}")
            elif daily_status == "stale_cache":
                errors.append(f"{pool_name} candidate has stale daily cache in official report: code={row.get('code')}")
            elif daily_status != "verified":
                errors.append(
                    f"{pool_name} candidate has non-verified daily status in official report: "
                    f"code={row.get('code')} status={daily_status}"
                )

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
    manifest_path = ROOT / "docs" / "data" / "index.json"
    if not manifest_path.exists():
        print("missing report manifest: docs/data/index.json", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract_errors = validate_report_contract(report, require_official=True)
    manifest_contract_errors = validate_manifest_contract(manifest)
    contract_errors.extend(manifest_contract_errors)

    if contract_errors:
        print("report contract mismatch:", file=sys.stderr)
        for err in contract_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    live = fetch_market_indices(report_date=report_date)
    saved = report.get("market") or {}
    errors = []

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
