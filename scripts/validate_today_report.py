#!/usr/bin/env python3
"""Validate that today's published report uses trustworthy market index data."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run import fetch_market_indices  # noqa: E402
from chanlun.pool_contract import (  # noqa: E402
    resolve_list_pool,
    resolve_nested_strategy_pool,
)
from chanlun.strategy_review import (  # noqa: E402
    load_strategy_sample_exclusions,
)
from typing import Any, Optional

TZ_CN = timezone(timedelta(hours=8))
COMPARISON_VIEWS = {
    "main", "h4_t3", "highlights", "observation_top5", "acceleration",
    "luojie", "confirming", "growth_quality", "baseline",
}


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


def validate_comparison_contract(
    index: Mapping[str, Any], report_date: str = ""
) -> list[str]:
    """Validate the static 26-report-day comparison index."""
    errors: list[str] = []
    if not isinstance(index, Mapping):
        return ["comparison index must be a mapping"]
    if index.get("version") != 1:
        errors.append("comparison index version must be 1")
    dates = _as_str_list(index.get("dates"))
    if not dates:
        errors.append("comparison index dates must be non-empty")
        return errors
    if dates != sorted(set(dates)):
        errors.append("comparison index dates must be sorted and unique")
    if len(dates) > 26:
        errors.append("comparison index exceeds 26 report days")
    latest = str(index.get("latest_date") or "").strip()
    if latest != dates[-1]:
        errors.append("comparison index latest_date mismatch")
    if report_date and latest != report_date:
        errors.append(
            f"comparison index latest_date must equal report date: {report_date}"
        )
    reports = index.get("reports")
    if not isinstance(reports, Mapping):
        return errors + ["comparison index reports must be a mapping"]
    for date_value in dates:
        snapshot = reports.get(date_value)
        if not isinstance(snapshot, Mapping):
            errors.append(f"comparison report missing: {date_value}")
            continue
        views = snapshot.get("views")
        prices = snapshot.get("prices")
        benchmark = snapshot.get("benchmark")
        quality = snapshot.get("quality")
        if not isinstance(quality, Mapping):
            errors.append(f"comparison quality invalid: {date_value}")
        else:
            if not isinstance(quality.get("is_official"), bool):
                errors.append(f"comparison quality official flag invalid: {date_value}")
            if quality.get("is_trading_day") is not True:
                errors.append(f"comparison quality trading flag invalid: {date_value}")
            if quality.get("status") not in {"official", "quality_warning"}:
                errors.append(f"comparison quality status invalid: {date_value}")
        if not isinstance(views, Mapping) or not COMPARISON_VIEWS.issubset(views):
            errors.append(f"comparison views incomplete: {date_value}")
            continue
        if not isinstance(prices, Mapping):
            errors.append(f"comparison prices invalid: {date_value}")
            continue
        if not isinstance(benchmark, Mapping) or str(benchmark.get("code")) != "000300":
            errors.append(f"comparison benchmark invalid: {date_value}")
        for view in COMPARISON_VIEWS:
            rows = views.get(view)
            if not isinstance(rows, list):
                errors.append(f"comparison view must be an array: {date_value}/{view}")
                continue
            for row in rows:
                code = str(_as_mapping(row).get("code") or "").strip()
                if not code or code not in prices:
                    errors.append(
                        f"comparison row missing indexed price: {date_value}/{view}/{code or '--'}"
                    )
    return errors


def validate_comparison_formal_alignment(
    report: Mapping[str, Any],
    index: Mapping[str, Any],
    report_date: str,
) -> list[str]:
    errors: list[str] = []
    workspace_views = _as_mapping(
        _as_mapping(report.get("workspace")).get("views")
    )
    comparison_views = _as_mapping(
        _as_mapping(
            _as_mapping(index.get("reports")).get(report_date)
        ).get("views")
    )
    for view_name in ("main", "h4_t3"):
        daily_codes = [
            str(_as_mapping(row).get("code") or "")
            for row in workspace_views.get(view_name) or []
        ]
        comparison_codes = [
            str(_as_mapping(row).get("code") or "")
            for row in comparison_views.get(view_name) or []
        ]
        if daily_codes != comparison_codes:
            errors.append(
                "comparison formal view mismatch: {}".format(view_name)
            )
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
    action = str(
        row.get("page_action")
        or row.get("effective_action")
        or row.get("action")
        or ""
    ).strip()
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


def _is_registered_fail_closed_incident_correction(
    report: Mapping[str, Any], selection_health: Mapping[str, Any]
) -> bool:
    """Allow an official market snapshot to publish with formal actions shut.

    This is intentionally narrower than a generic missing-input exemption: the
    report date and incident ids must exist in the versioned registry, at least
    one incident must affect the formal fusion strategy, and every executable
    workspace surface must already be empty.
    """
    report_date = str(report.get("date") or "").strip()
    if not report_date:
        return False
    try:
        rules = [
            rule for rule in load_strategy_sample_exclusions()
            if report_date in {
                str(value) for value in rule.get("report_dates") or []
            }
        ]
    except (OSError, ValueError, TypeError):
        return False
    registered_ids = {
        str(rule.get("incident_id") or "").strip()
        for rule in rules
        if str(rule.get("incident_id") or "").strip()
    }
    supplied_ids = set(_as_str_list(selection_health.get("incident_ids")))
    if (
        not supplied_ids
        or not supplied_ids.issubset(registered_ids)
    ):
        return False

    workspace = _as_mapping(report.get("workspace"))
    views = _as_mapping(workspace.get("views"))
    view_meta = _as_mapping(workspace.get("view_meta"))
    by_strategy = _as_mapping(selection_health.get("by_strategy"))
    if by_strategy:
        affected = False
        for strategy_name, view_name in (
            ("daily_fusion", "main"),
            ("h4_t3", "h4_t3"),
        ):
            health = _as_mapping(by_strategy.get(strategy_name))
            if (
                health.get("formal_actions_allowed") is True
                and str(health.get("status") or "") == "verified"
            ):
                continue
            strategy_rules = [
                rule for rule in rules
                if str(rule.get("incident_id") or "") in supplied_ids
                and strategy_name in {
                    str(value)
                    for value in rule.get("strategy_names") or []
                }
            ]
            if not strategy_rules:
                return False
            registered_reasons = {
                str(rule.get("reason") or "") for rule in strategy_rules
            }
            if str(health.get("blocking_reason") or "") not in registered_reasons:
                return False
            registered_codes = {
                str(code)
                for rule in strategy_rules
                for code in rule.get("codes") or []
            }
            if registered_codes and not registered_codes.issubset(
                set(_as_str_list(health.get("invalid_codes")))
            ):
                return False
            if views.get(view_name) not in (None, [], ()):
                return False
            availability = _as_mapping(
                _as_mapping(view_meta.get(view_name)).get("availability")
            )
            if view_name in view_meta and str(
                availability.get("state") or ""
            ) != "unavailable":
                return False
            affected = True
        if not affected:
            return False
    else:
        # Schema-v1 compatibility for already-published incident corrections.
        formal = _as_mapping(selection_health.get("formal"))
        registered_formal_ids = {
            str(rule.get("incident_id") or "").strip()
            for rule in rules
            if "daily_fusion" in {
                str(value) for value in rule.get("strategy_names") or []
            }
        }
        if (
            not supplied_ids.intersection(registered_formal_ids)
            or str(selection_health.get("status") or "") != "unavailable"
            or formal.get("formal_actions_allowed") is not False
            or str(formal.get("status") or "") != "unavailable"
            or str(formal.get("blocking_reason") or "")
            != "strategy_input_stale_or_unverified"
            or _coerce_int(formal.get("invalid_count"), default=0) <= 0
            or not _as_str_list(formal.get("invalid_codes"))
            or views.get("main") not in ([], ())
        ):
            return False
    for _view, row in _iter_workspace_rows(report):
        page_action = str(
            row.get("page_action") or row.get("effective_action") or ""
        ).strip()
        if page_action in _EXECUTABLE_WORKSPACE_ACTIONS:
            return False
    return True


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
    incident_correction = False
    if require_official and not is_official:
        errors.append("publish requires data_quality.is_official == True")
    if require_official or is_official:
        selection_health = report.get("selection_input_health")
        if not isinstance(selection_health, Mapping):
            errors.append(
                "official report requires selection_input_health mapping"
            )
        else:
            formal_health = _as_mapping(selection_health.get("formal"))
            incident_correction = (
                _is_registered_fail_closed_incident_correction(
                    report, selection_health
                )
            )
            if (
                formal_health.get("formal_actions_allowed") is not True
                or str(formal_health.get("status") or "") != "verified"
            ) and not incident_correction:
                errors.append(
                    "official report formal strategy input is not verified"
                )
        for pool_name in (
            "picks_fusion", "picks_pure", "startup_watchlist",
            "observation_watchlist",
        ):
            if pool_name not in report:
                continue
            state = resolve_list_pool(report, pool_name)
            if state["state"] == "unavailable":
                errors.append(
                    f"{pool_name} pool contract invalid: {state['reason']}"
                )
        for pool_name, formal_h4 in (
            ("next_day_boom", False),
            ("luojie_pool", False),
            ("h4_t3_pool", True),
        ):
            if pool_name not in report:
                continue
            state = resolve_nested_strategy_pool(
                report, pool_name, formal_h4=formal_h4
            )
            if state["state"] in {"unavailable", "partial"}:
                errors.append(
                    f"{pool_name} pool contract invalid: {state['reason']}"
                )
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

    recommend_rows = [
        row
        for row in picks_fusion
        if str(
            _as_mapping(_as_mapping(row).get("decision_engine_v1")).get(
                "decision_code"
            )
            or ""
        ).strip().lower()
        == "recommend"
    ]
    if (
        recommend_rows
        and not _as_mapping(views).get("main")
        and not incident_correction
    ):
        errors.append("main view missing while recommend decisions exist")
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


def validate_runtime_cutover(report: Mapping[str, Any]) -> list[str]:
    """Validate operational cutover metadata before an official push."""
    errors: list[str] = []
    data_quality = _as_mapping(report.get("data_quality"))
    runtime = _as_mapping(data_quality.get("runtime_policy"))
    diagnostics = _as_mapping(report.get("diagnostics"))
    funnel = _as_mapping(diagnostics.get("candidate_funnel"))
    shadow = _as_mapping(diagnostics.get("recall_shadow"))
    market_mode = str(
        runtime.get("market_history_cutover_mode") or ""
    )
    strategy_mode = str(runtime.get("recall_strategy_mode") or "")
    if market_mode != "sqlite":
        errors.append(
            "publish requires market_history_cutover_mode == sqlite"
        )
    if strategy_mode not in {"legacy", "shadow", "active"}:
        errors.append("publish requires a valid recall_strategy_mode")
    if runtime.get("decision_semantics") != "v2_missing_position_is_observe":
        errors.append("publish requires decision semantics v2")
    if funnel.get("persist_status") != "saved":
        errors.append("publish requires saved candidate funnel")
    if strategy_mode == "shadow":
        if shadow.get("mode") != "shadow":
            errors.append("shadow publish requires recall comparison")
        if shadow.get("new_strategy_controls_publish") is not False:
            errors.append("shadow mode cannot let new strategy control publish")
    if strategy_mode == "active":
        if shadow.get("mode") != "active":
            errors.append("active publish requires recall diagnostics")
        if shadow.get("new_strategy_controls_publish") is not True:
            errors.append(
                "active mode requires new strategy to control publish"
            )
    return errors


def needs_sublevel_retry(report: Mapping[str, Any]) -> bool:
    """Return whether a second close run can still fill research-only inputs."""
    selection = _as_mapping(report.get("selection_input_health"))
    formal = _as_mapping(selection.get("formal"))
    if formal.get("all_formal_actions_allowed", formal.get("formal_actions_allowed")) is not True:
        return False
    return any(
        str(_as_mapping(value).get("status") or "") in {
            "partial", "unavailable",
        }
        for value in _as_mapping(selection.get("sublevels")).values()
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate one generated official report"
    )
    parser.add_argument("--needs-sublevel-retry", action="store_true")
    parser.add_argument(
        "--docs-dir", default=str(ROOT / "docs")
    )
    parser.add_argument("report_date")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    retry_check = args.needs_sublevel_retry
    report_date = args.report_date
    docs_dir = Path(args.docs_dir).resolve()
    path = docs_dir / "data" / f"{report_date}.json"
    if not path.exists():
        print(f"missing report data: {path}", file=sys.stderr)
        return 1

    report = json.loads(path.read_text(encoding="utf-8"))
    if retry_check:
        if needs_sublevel_retry(report):
            print(f"sublevel retry needed for {report_date}")
            return 0
        print(f"sublevel retry not needed for {report_date}")
        return 1
    manifest_path = docs_dir / "data" / "index.json"
    if not manifest_path.exists():
        print("missing report manifest: docs/data/index.json", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract_errors = validate_report_contract(report, require_official=True)
    contract_errors.extend(validate_runtime_cutover(report))
    manifest_contract_errors = validate_manifest_contract(manifest)
    contract_errors.extend(manifest_contract_errors)

    comparison_path = docs_dir / "data" / "comparison-index.json"
    comparison_page = docs_dir / "compare" / "index.html"
    if not comparison_path.exists():
        contract_errors.append("missing comparison index: docs/data/comparison-index.json")
    else:
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        contract_errors.extend(
            validate_comparison_contract(comparison, report_date=report_date)
        )
        contract_errors.extend(
            validate_comparison_formal_alignment(
                report, comparison, report_date
            )
        )
    if not comparison_page.exists():
        contract_errors.append("missing comparison page: docs/compare/index.html")
    else:
        comparison_html = comparison_page.read_text(encoding="utf-8")
        if "__CHANLUN_TOP10_API_BASE__" in comparison_html:
            contract_errors.append("comparison page quote API was not configured")
        if 'id="comparisonApp"' not in comparison_html:
            contract_errors.append("comparison page mount is missing")

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
