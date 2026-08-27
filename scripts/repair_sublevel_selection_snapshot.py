#!/usr/bin/env python3
"""Publish a review-only reconstruction for the 2026-08-26 minute-data incident.

The original pools, workspace, health contract, ledger, scorecards, shadow
contract and comparison index are immutable.  The verified reconstruction is
stored in a separate top-level overlay and is never treated as a recommendation
that existed at the original publication time.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.chan_engine import analyze  # noqa: E402
from chanlun.kline_repository import KLineRepository  # noqa: E402
from chanlun.market_history_store import MarketHistoryStore  # noqa: E402
from chanlun.report_generator import (  # noqa: E402
    _build_report_v2_html,
    _escape_inline_json,
    _report_asset_version,
    copy_report_assets,
)
from chanlun.shadow_evaluation import production_digest  # noqa: E402
from chanlun.strong_startup import (  # noqa: E402
    upgrade_strong_startup_with_30min,
)
from scripts import enable_shadow_evaluation_snapshot as atomic  # noqa: E402


SUPPORTED_REPORT_DATE = "2026-08-26"
SUPPORTED_CODE = "300697"
_CN_TZ = timezone(timedelta(hours=8))
_OVERLAY_KEY = "historical_reconstruction"


def _deepcopy_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _validate_source_report(report, report_date):
    if str(report_date) != SUPPORTED_REPORT_DATE:
        raise ValueError("unsupported repair date: {}".format(report_date))
    if not isinstance(report, dict):
        raise ValueError("source report must be a mapping")
    if _OVERLAY_KEY in report:
        raise ValueError("historical reconstruction already exists")
    payload_date = str(report.get("date") or "")
    if payload_date and payload_date != str(report_date):
        raise ValueError("source report date mismatch")
    quality = report.get("data_quality")
    if not isinstance(quality, dict):
        raise ValueError("source report data_quality is missing")
    if not (
        str(quality.get("report_date") or "") == str(report_date)
        and quality.get("is_official") is True
        and quality.get("bar_state") == "closed"
        and quality.get("market_status") == "verified"
    ):
        raise ValueError("repair requires an official closed report")


def _parse_acquired_at(value, report_date):
    text = str(value or datetime.now(_CN_TZ).isoformat()).replace(
        "Z", "+00:00"
    )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("acquired_at must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("acquired_at must include a timezone")
    parsed = parsed.astimezone(_CN_TZ)
    if parsed.date().isoformat() <= str(report_date):
        raise ValueError("acquired_at must be after the report date")
    return parsed.isoformat()


def _candidate_by_code(rows, code):
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("code") or "") == str(code):
            return row
    return None


def _protected_projection(report):
    projected = _deepcopy_json(report)
    projected.pop(_OVERLAY_KEY, None)
    return projected


def _protected_digest(report):
    return production_digest(_protected_projection(report))


def _assert_original_snapshot_unchanged(before, after, plane):
    if _protected_projection(before) != _protected_projection(after):
        raise RuntimeError(
            "historical reconstruction mutated original {} plane".format(
                plane
            )
        )


def _verified_30m_result(market_db_path, report_date, code):
    repository = KLineRepository(
        market_db_path,
        mode="backtest",
        immutable_backtest=False,
    )
    expected_latest = "{} 15:00:00".format(report_date)
    result = repository.get(
        "30m",
        code,
        count=80,
        required_date=report_date,
        as_of=expected_latest,
    )
    status = (result.kline or {}).get("_data_status") or {}
    dates = list((result.kline or {}).get("dates") or [])
    if not (
        result.status == "verified"
        and result.stale is False
        and len(dates) >= 80
        and str(dates[-1]) == expected_latest
        and status.get("is_final") is True
    ):
        raise ValueError(
            "verified 30m input is unavailable for {} {}".format(
                report_date, code
            )
        )
    evidence = {
        "interval": "30m",
        "status": "verified",
        "latest_date": report_date,
        "latest_ts": str(dates[-1]),
        "source": "market_history_db",
        "bars": len(dates),
        "stale": False,
        "is_final": True,
        "as_of": expected_latest,
    }
    return result, evidence


def _source_batches(market_db_path, report_date, code):
    with MarketHistoryStore(
        market_db_path, readonly=True, immutable=False
    ) as store:
        instrument = store.resolve_instrument("stock", "SZ", code)
        if instrument is None:
            return []
        rows = store.query_bars(
            "30m",
            int(instrument["instrument_id"]),
            as_of="{} 15:00:00".format(report_date),
            limit=80,
        )
    return sorted({
        str(row.get("source_batch") or "")
        for row in rows
        if str(row.get("source_batch") or "")
    })


def _startup_seed(row):
    best = row.get("best_buy_point")
    best = best if isinstance(best, dict) else {}
    return {
        "code": str(row.get("code") or ""),
        "name": str(row.get("name") or ""),
        "sector": str(row.get("sector") or ""),
        "type": "强势启动候选",
        "tier": "candidate",
        "category": str(row.get("category") or "A"),
        "quality_tier": str(row.get("quality_tier") or ""),
        "source_channel": "low_position",
        "view": "main",
        "source_type": "日线强势启动",
        "startup_reason": str(
            best.get("startup_reason") or best.get("reason") or ""
        ),
        "startup_signals": list(best.get("startup_signals") or []),
        "startup_index": best.get("startup_index"),
        "startup_date": str(best.get("startup_date") or ""),
        "startup_age_days": best.get("startup_age_days", 0),
        "change_pct": row.get("change_pct", best.get("change_pct", 0)),
        "volume_ratio": best.get("volume_ratio", 0),
        "close": float((row.get("closes") or [0])[-1]),
        "pivot_info": dict(row.get("pivots") or {}),
        "closes": np.asarray(row.get("closes") or [], dtype=float),
        "opens": np.asarray(row.get("opens") or [], dtype=float),
        "highs": np.asarray(row.get("highs") or [], dtype=float),
        "lows": np.asarray(row.get("lows") or [], dtype=float),
        "volumes": np.asarray(row.get("volumes") or [], dtype=float),
        "dates": list(row.get("dates") or []),
        "buy_points": list(row.get("reference_buy_points") or []),
        "result_30min": None,
    }


def _overlay_candidate(source, upgraded, evidence):
    confirmations = list(upgraded.get("confirmations") or [])
    source_best = source.get("best_buy_point")
    source_best = source_best if isinstance(source_best, dict) else {}
    closes = list(source.get("closes") or [])
    reference_close = closes[-1] if closes else source.get("reference_price")
    return {
        "code": SUPPORTED_CODE,
        "name": str(source.get("name") or SUPPORTED_CODE),
        "sector": str(source.get("sector") or ""),
        "review_identity": "历史重建·仅复盘",
        "page_action": "仅复盘",
        "is_formal_recommendation": False,
        "scorecard_eligible": False,
        "source_pool": "picks_fusion",
        "reference_close": reference_close,
        "reference_close_source": "original_report_closes[-1]",
        "startup_date": str(
            upgraded.get("startup_date")
            or source_best.get("startup_date")
            or ""
        ),
        "startup_reason": str(
            upgraded.get("startup_reason")
            or source_best.get("startup_reason")
            or source_best.get("reason")
            or ""
        ),
        "confirmations": confirmations,
        "confirmed_by": "+".join(confirmations),
        "confirm_date": str(upgraded.get("confirm_date") or ""),
        "confirm_index": upgraded.get("confirm_index"),
        "strategy_input_evidence": copy.deepcopy(evidence),
        "review_reason": (
            "使用报告日 15:00 已收盘分钟线事后重建；不视为当日已发布"
            "推荐，也不计入策略记分牌。"
        ),
    }


def _original_publication_summary(report):
    workspace = report.get("workspace") or {}
    raw_main_count = len(
        ((workspace.get("views") or {}).get("main") or [])
    )
    selection = report.get("selection_input_health") or {}
    daily_fusion = (
        (selection.get("by_strategy") or {}).get("daily_fusion") or {}
    )
    formal_allowed = bool(
        daily_fusion.get("status") == "verified"
        and daily_fusion.get("formal_actions_allowed") is True
    )
    return {
        "formal_snapshot_unchanged": True,
        "main_count": raw_main_count if formal_allowed else 0,
        "raw_main_candidate_count": raw_main_count,
        "affected_candidate_count": int(
            _candidate_by_code(
                report.get("picks_fusion"), SUPPORTED_CODE
            ) is not None
        ),
        "formal_actions_allowed": formal_allowed,
    }


def rebuild_sublevel_selection_report(
    report,
    *,
    report_date,
    market_db_path,
    acquired_at=None,
):
    _validate_source_report(report, report_date)
    acquired_at = _parse_acquired_at(acquired_at, report_date)
    before_digest = _protected_digest(report)
    source = _candidate_by_code(report.get("picks_fusion"), SUPPORTED_CODE)
    if source is None:
        source = _candidate_by_code(report.get("picks_pure"), SUPPORTED_CODE)
    if source is None:
        raise ValueError("registered repair candidate is missing")

    repository_result, evidence = _verified_30m_result(
        market_db_path, report_date, SUPPORTED_CODE
    )
    kline = repository_result.kline
    analysis = analyze(
        code=SUPPORTED_CODE,
        name=str(source.get("name") or SUPPORTED_CODE),
        dates=kline["dates"],
        opens=kline["opens"],
        highs=kline["highs"],
        lows=kline["lows"],
        closes=kline["closes"],
        volumes=kline["volumes"],
    )
    setattr(analysis, "strategy_input_evidence", copy.deepcopy(evidence))
    upgraded, _watchlist, _diagnostics = upgrade_strong_startup_with_30min(
        [_startup_seed(source)], [analysis]
    )

    candidates = (
        [_overlay_candidate(source, upgraded[0], evidence)]
        if upgraded else []
    )
    rebuilt = _deepcopy_json(report)
    rebuilt[_OVERLAY_KEY] = {
        "schema_version": 2,
        "status": "verified_reconstruction",
        "report_date": report_date,
        "acquired_at": acquired_at,
        "outcome": (
            "reconstructed_candidate" if candidates else "no_confirmation"
        ),
        "codes": [SUPPORTED_CODE],
        "candidates": candidates,
        "input": copy.deepcopy(evidence),
        "source_batches": _source_batches(
            market_db_path, report_date, SUPPORTED_CODE
        ),
        "original_publication": _original_publication_summary(report),
        "published_after_fact": True,
        "scorecard_eligible": False,
        "recommendation_ledger_mutated": False,
        "comparison_mutated": False,
        "canonical_original_sha256": before_digest,
    }
    _assert_original_snapshot_unchanged(report, rebuilt, "daily")
    if _protected_digest(rebuilt) != before_digest:
        raise RuntimeError("historical reconstruction changed formal digest")
    return rebuilt


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _attach_overlay(report, report_date, overlay):
    _validate_source_report(report, report_date)
    rebuilt = _deepcopy_json(report)
    rebuilt[_OVERLAY_KEY] = copy.deepcopy(overlay)
    return rebuilt


def _rebuild_staged_artifacts(
    staged_docs,
    report_date,
    rebuilt_planes,
    original_aggregate,
    original_bootstraps,
):
    _write_json(
        staged_docs / "data" / "{}.json".format(report_date),
        rebuilt_planes["daily"],
    )
    aggregate = copy.deepcopy(original_aggregate)
    aggregate["reports"][report_date] = rebuilt_planes["aggregate"]
    _write_json(staged_docs / "data.json", aggregate)
    copy_report_assets(os.fspath(staged_docs))
    asset_version = _report_asset_version()
    for name, relative, prefix in (
        ("inline", "index.html", ""),
        ("archive", "{}/index.html".format(report_date), "../"),
    ):
        envelope = copy.deepcopy(original_bootstraps[name])
        envelope["inlineReportData"] = rebuilt_planes[name]
        html = _build_report_v2_html(
            report_date,
            _escape_inline_json(envelope),
            asset_prefix=prefix,
            asset_version=asset_version,
        )
        with open(staged_docs / relative, "w", encoding="utf-8") as handle:
            handle.write(html)


def _validate_staged_docs(
    staged_docs,
    report_date,
    original_planes,
    expected_overlay,
    original_manifest,
    original_comparison,
):
    staged_planes = atomic._load_public_planes(staged_docs, report_date)
    for name, payload in staged_planes.items():
        _assert_original_snapshot_unchanged(
            original_planes[name], payload, name
        )
        if payload.get(_OVERLAY_KEY) != expected_overlay:
            raise RuntimeError(
                "staged reconstruction differs in {}".format(name)
            )
    if atomic._read_json(staged_docs / "data" / "index.json") != original_manifest:
        raise RuntimeError("report manifest changed during reconstruction")
    comparison_path = staged_docs / "data" / "comparison-index.json"
    if comparison_path.is_file() and atomic._read_json(
        comparison_path
    ) != original_comparison:
        raise RuntimeError("comparison index changed during reconstruction")

    source_assets = ROOT_DIR / "chanlun" / "report_assets"
    for relative in ("report-v2.js", "report-v2.css"):
        staged = staged_docs / "assets" / relative
        source = source_assets / relative
        if atomic._sha256_file(staged) != atomic._sha256_file(source):
            raise RuntimeError(
                "asset whitelist mismatch: {}".format(relative)
            )
    js = (staged_docs / "assets" / "report-v2.js").read_text(
        encoding="utf-8"
    )
    if "function renderHistoricalReconstruction" not in js:
        raise RuntimeError("historical reconstruction renderer is missing")
    return staged_planes


def publish_sublevel_selection_snapshot(
    *, docs_dir, report_date, market_db_path, acquired_at=None
):
    if str(report_date) != SUPPORTED_REPORT_DATE:
        raise ValueError("unsupported repair date: {}".format(report_date))
    docs_dir = Path(docs_dir).resolve()
    market_db_path = Path(market_db_path).resolve()
    with atomic._exclusive_docs_publish_lock(docs_dir):
        atomic._recover_incomplete_transaction(docs_dir)
        atomic._cleanup_stale_publication_artifacts(docs_dir, report_date)
        initial_hashes = atomic._public_target_hashes(docs_dir, report_date)
        original_planes = atomic._load_public_planes(docs_dir, report_date)
        rebuilt_daily = rebuild_sublevel_selection_report(
            original_planes["daily"],
            report_date=report_date,
            market_db_path=market_db_path,
            acquired_at=acquired_at,
        )
        expected = rebuilt_daily[_OVERLAY_KEY]
        rebuilt_planes = {"daily": rebuilt_daily}
        for name in ("aggregate", "inline", "archive"):
            rebuilt_planes[name] = _attach_overlay(
                original_planes[name], report_date, expected
            )

        original_aggregate = atomic._read_json(docs_dir / "data.json")
        original_bootstraps = {
            "inline": atomic._read_bootstrap_envelope(
                docs_dir / "index.html"
            ),
            "archive": atomic._read_bootstrap_envelope(
                docs_dir / report_date / "index.html"
            ),
        }
        original_manifest = atomic._read_json(
            docs_dir / "data" / "index.json"
        )
        comparison_path = docs_dir / "data" / "comparison-index.json"
        original_comparison = (
            atomic._read_json(comparison_path)
            if comparison_path.is_file() else None
        )
        transaction_id = uuid.uuid4().hex
        stage_root = atomic._create_controlled_stage_root(
            docs_dir, transaction_id
        )
        try:
            staged_docs = stage_root / "docs"
            shutil.copytree(docs_dir, staged_docs)
            _rebuild_staged_artifacts(
                staged_docs,
                report_date,
                rebuilt_planes,
                original_aggregate,
                original_bootstraps,
            )
            _validate_staged_docs(
                staged_docs,
                report_date,
                original_planes,
                expected,
                original_manifest,
                original_comparison,
            )
            updated_files = atomic._atomic_replace_targets(
                staged_docs,
                docs_dir,
                report_date,
                expected_original_hashes=initial_hashes,
                transaction_id=transaction_id,
            )
        finally:
            if stage_root.exists():
                atomic._remove_controlled_stage_root(
                    stage_root, docs_dir, assume_owned=True
                )
    return {
        "status": "repaired",
        "report_date": report_date,
        _OVERLAY_KEY: expected,
        "updated_files": updated_files,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--docs-dir", default=os.fspath(ROOT_DIR / "docs"))
    parser.add_argument(
        "--market-db-path",
        default=os.fspath(
            ROOT_DIR / ".cache" / "chanlun" / "market_history.sqlite"
        ),
    )
    parser.add_argument("--acquired-at")
    args = parser.parse_args(argv)
    result = publish_sublevel_selection_snapshot(
        docs_dir=args.docs_dir,
        report_date=args.report_date,
        market_db_path=args.market_db_path,
        acquired_at=args.acquired_at,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
