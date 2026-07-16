#!/usr/bin/env python3
"""Rebuild historical candidate funnels from frozen SQLite market data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chanlun.candidate_funnel import CandidateFunnel  # noqa: E402
from chanlun.candidate_upgrade import (  # noqa: E402
    upgrade_daily_candidates_with_30min,
)
from chanlun.chan_engine import analyze  # noqa: E402
from chanlun.fusion_admission import apply_fusion_admission  # noqa: E402
from chanlun.market_history_store import MarketHistoryStore  # noqa: E402
from chanlun.strong_startup import (  # noqa: E402
    build_strong_startup_pool,
    upgrade_strong_startup_with_30min,
)
from chanlun.trend_continuation import (  # noqa: E402
    build_trend_continuation_pool,
    normalize_trend_candidate,
    upgrade_trend_continuation_with_30min,
)
from chanlun.daily_structure_pool import build_daily_structure_pool  # noqa: E402
from chanlun.universe_builder import (  # noqa: E402
    UniverseConfig,
    build_candidate_universe,
    load_eligible_candidates,
)
from config import MIN_DAILY_AMOUNT, MIN_LISTED_DAYS  # noqa: E402


def _listed_days(listed_date: Any, as_of: str) -> Optional[int]:
    text = str(listed_date or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return max(
            0,
            (
                date.fromisoformat(str(as_of)[:10])
                - date(
                    int(text[:4]),
                    int(text[4:6]),
                    int(text[6:8]),
                )
            ).days,
        )
    except ValueError:
        return None


def materialize_historical_meta_proxies(
    store: MarketHistoryStore,
    signal_dates: Sequence[str],
) -> Dict[str, Any]:
    """Fill missing T-day metadata from the latest known static snapshot.

    The proxy is explicit in metadata so audits can distinguish it from a true
    point-in-time security master snapshot.
    """
    latest = {}
    rows = store.connection.execute(
        """
        SELECT instrument_id, as_of, metadata_json
        FROM stock_meta_asof
        ORDER BY instrument_id, as_of DESC
        """
    ).fetchall()
    for raw in rows:
        instrument_id = int(raw["instrument_id"])
        if instrument_id in latest:
            continue
        latest[instrument_id] = {
            "source_as_of": str(raw["as_of"]),
            "metadata": json.loads(raw["metadata_json"]),
        }

    instrument_ids = [
        int(row["instrument_id"])
        for row in store.list_instruments(asset_type="stock")
    ]
    created = 0
    skipped_existing = 0
    missing_source = 0
    for signal_date in sorted(set(str(value) for value in signal_dates)):
        existing = {
            int(row["instrument_id"])
            for row in store.connection.execute(
                """
                SELECT instrument_id
                FROM stock_meta_asof
                WHERE as_of=?
                """,
                (signal_date,),
            ).fetchall()
        }
        for instrument_id in instrument_ids:
            if instrument_id in existing:
                skipped_existing += 1
                continue
            source = latest.get(instrument_id)
            if source is None:
                missing_source += 1
                continue
            metadata = dict(source["metadata"])
            proxy_listed_days = _listed_days(
                metadata.get("listed_date"), signal_date
            )
            if proxy_listed_days is not None:
                metadata["listed_days"] = proxy_listed_days
            metadata["_historical_proxy"] = True
            metadata["_proxy_source_as_of"] = source["source_as_of"]
            store.upsert_stock_meta(instrument_id, signal_date, metadata)
            created += 1
    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "missing_source": missing_source,
    }


def _analyze_rows(
    code: str,
    name: str,
    rows: Sequence[Mapping[str, Any]],
):
    if len(rows) < 10:
        return None
    return analyze(
        code=code,
        name=name,
        dates=[row["ts"] for row in rows],
        opens=[row["open"] for row in rows],
        highs=[row["high"] for row in rows],
        lows=[row["low"] for row in rows],
        closes=[row["close"] for row in rows],
        volumes=[row["volume"] for row in rows],
    )


def _load_30m_results(
    store: MarketHistoryStore,
    signal_date: str,
    codes: Sequence[str],
) -> List[Any]:
    instruments = {
        str(row["code"]): row
        for row in store.list_instruments(asset_type="stock")
    }
    selected = [
        instruments[code] for code in sorted(set(codes))
        if code in instruments
    ]
    rows_by_id = store.query_bars_many(
        "30m",
        [int(row["instrument_id"]) for row in selected],
        as_of="{} 23:59:59".format(signal_date),
        limit=500,
    )
    results = []
    for instrument in selected:
        rows = [
            row
            for row in rows_by_id.get(int(instrument["instrument_id"]), [])
            if bool(row.get("is_final"))
        ]
        result = _analyze_rows(
            str(instrument["code"]),
            str(instrument.get("name") or instrument["code"]),
            rows,
        )
        if result is not None:
            results.append(result)
    return results


def _normalize_startup_candidate(
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    row = dict(candidate)
    confirmations = list(row.get("confirmations") or [])
    price = float(row.get("close") or 0.0)
    buy_point = {
        "type": "强势启动候选",
        "tier": "candidate",
        "category": "A",
        "price": price,
        "strength": "强" if len(confirmations) >= 3 else "中",
        "confirmed_by": "+".join(confirmations),
        "confirmations": confirmations,
        "reason": row.get("startup_reason", ""),
    }
    row.update({
        "best_buy_point": buy_point,
        "buy_points": [dict(buy_point)],
        "signal_tier": "candidate",
    })
    return row


def replay_historical_funnel(
    store: MarketHistoryStore,
    signal_date: str,
    universe_config: Optional[UniverseConfig] = None,
    include_30m: bool = True,
) -> Dict[str, Any]:
    """Rebuild and persist one official historical funnel without networking."""
    report_date = str(signal_date)
    run_id = "historical-replay-{}-v1".format(
        report_date.replace("-", "")
    )
    funnel = CandidateFunnel(run_id, report_date, as_of=report_date)
    eligibility_audit = []
    candidates, eligibility = load_eligible_candidates(
        store,
        as_of=report_date,
        required_date=report_date,
        min_listed_days=MIN_LISTED_DAYS,
        min_daily_amount=MIN_DAILY_AMOUNT,
        return_diagnostics=True,
        audit_records=eligibility_audit,
    )
    funnel.set_stage_count("full_a", eligibility["instrument_count"])
    funnel.set_stage_count("eligible", eligibility["eligible_count"])
    funnel.register_many(eligibility_audit)
    for audit in eligibility_audit:
        if audit.get("eligibility_passed"):
            funnel.pass_stage(audit["code"], "eligible")
        else:
            funnel.fail_stage(
                audit["code"],
                "eligible",
                audit.get("eligibility_failure_reason")
                or "eligibility_not_passed",
            )

    universe = build_candidate_universe(
        candidates,
        [],
        config=universe_config or UniverseConfig(),
    )
    selected = list(universe["final"])
    selected_codes = [str(row["code"]) for row in selected]
    funnel.set_stage_count("retrieval", len(selected))
    funnel.register_many(selected)
    funnel.mark_membership(
        "retrieval",
        selected,
        failure_reason="retrieval_quota_not_selected",
        eligible_codes=candidates,
    )

    chan_results = []
    analysis_failures = []
    for candidate in selected:
        try:
            kline = candidate["klines"]
            result = analyze(
                code=candidate["code"],
                name=candidate["name"],
                dates=kline["dates"],
                opens=kline["opens"],
                highs=kline["highs"],
                lows=kline["lows"],
                closes=kline["closes"],
                volumes=kline["volumes"],
            )
        except Exception as exc:
            analysis_failures.append({
                "code": candidate.get("code"),
                "error": "{}: {}".format(type(exc).__name__, exc),
            })
            continue
        chan_results.append(result)

    sector_stocks = {
        str(candidate["code"]): {
            "sector": "",
            "sector_tags": [],
            "amount": candidate.get("amount"),
            "amounts": candidate.get("amounts"),
            "data_status": candidate.get("data_status") or {},
        }
        for candidate in selected
    }
    daily_pool, daily_diag = build_daily_structure_pool(
        chan_results, sector_stocks, mode="pure"
    )
    startup_seeds, startup_watch, startup_diag = (
        build_strong_startup_pool(chan_results, sector_stocks)
    )
    trend_seeds, trend_watch, trend_diag = (
        build_trend_continuation_pool(chan_results, sector_stocks)
    )
    for row in daily_pool:
        row.setdefault("source_channel", "low_position")
    daily_items = (
        list(daily_pool)
        + list(startup_seeds)
        + list(startup_watch)
        + list(trend_seeds)
        + list(trend_watch)
    )
    funnel.register_many(daily_items)
    funnel.mark_membership(
        "daily_channel",
        daily_items,
        failure_reason="daily_channel_not_matched",
        eligible_codes=selected_codes,
    )

    target_codes = {
        str(row["code"])
        for row in list(daily_pool) + list(startup_seeds) + list(trend_seeds)
    }
    minute30_results = (
        _load_30m_results(store, report_date, sorted(target_codes))
        if include_30m
        else []
    )
    pure_confirmed, upgrade_diag = upgrade_daily_candidates_with_30min(
        daily_pool, minute30_results, mode="pure"
    )
    startup_candidates, startup_upgrade_watch, startup_upgrade_diag = (
        upgrade_strong_startup_with_30min(
            startup_seeds, minute30_results
        )
    )
    trend_candidates, trend_upgrade_watch, trend_upgrade_diag = (
        upgrade_trend_continuation_with_30min(
            trend_seeds, minute30_results
        )
    )
    normalized_startup = [
        _normalize_startup_candidate(row) for row in startup_candidates
    ]
    normalized_trend = [
        normalize_trend_candidate(row) for row in trend_candidates
    ]
    pure_ready = (
        list(pure_confirmed) + normalized_startup + normalized_trend
    )
    observation = (
        list(startup_watch)
        + list(trend_watch)
        + list(startup_upgrade_watch)
        + list(trend_upgrade_watch)
    )
    minute30_pass = list(pure_ready) + list(observation)
    funnel.register_many(minute30_pass)
    funnel.mark_membership(
        "minute30",
        minute30_pass,
        failure_reason="minute30_not_confirmed",
        eligible_codes=sorted(target_codes),
    )

    fusion_ready, fusion_diag = apply_fusion_admission(
        list(pure_ready), None, sector_stocks
    )
    funnel.register_many(fusion_ready)
    funnel.mark_membership(
        "fusion",
        fusion_ready,
        failure_reason="fusion_admission_not_passed",
        eligible_codes=[row["code"] for row in pure_ready],
    )
    funnel.finalize(
        main_codes=pure_ready,
        observation_codes=observation,
    )

    proxy_count = sum(
        1
        for row in eligibility_audit
        if bool(
            (row.get("stock_meta_asof") or {}).get("_historical_proxy")
        )
    )
    metadata = {
        "is_official": True,
        "historical_replay": True,
        "historical_meta_proxy": proxy_count > 0,
        "historical_meta_proxy_count": proxy_count,
        "network_requests": 0,
        "sector_overlay_available": False,
        "market_index_regime_available": False,
        "include_30m": bool(include_30m),
        "analysis_failures": analysis_failures,
        "eligibility": eligibility,
        "universe": universe["diagnostics"],
        "daily": daily_diag,
        "startup": startup_diag,
        "trend": trend_diag,
        "upgrade": upgrade_diag,
        "startup_upgrade": startup_upgrade_diag,
        "trend_upgrade": trend_upgrade_diag,
        "fusion": fusion_diag,
    }
    store.save_candidate_funnel(
        funnel.run_record(metadata=metadata),
        funnel.events,
    )
    return {
        "run_id": run_id,
        "report_date": report_date,
        "summary": funnel.summary(),
        "metadata": metadata,
    }


def build_historical_funnels(
    database_path: Any,
    signal_dates: Sequence[str],
    include_30m: bool = True,
) -> Dict[str, Any]:
    dates = sorted(set(str(value) for value in signal_dates))
    with MarketHistoryStore(database_path) as store:
        proxies = materialize_historical_meta_proxies(store, dates)
        runs = [
            replay_historical_funnel(
                store, signal_date, include_30m=include_30m
            )
            for signal_date in dates
        ]
    return {
        "database_path": str(Path(database_path).expanduser().resolve()),
        "signal_dates": dates,
        "meta_proxies": proxies,
        "runs": runs,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--date", action="append", required=True)
    parser.add_argument("--without-30m", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = build_historical_funnels(
        args.db,
        args.date,
        include_30m=not args.without_30m,
    )
    payload = json.dumps(
        result, ensure_ascii=False, indent=2, sort_keys=True
    )
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
