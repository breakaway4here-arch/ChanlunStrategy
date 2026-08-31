"""Production read-only input acquisition for the scheduled 14:45 run."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import quote as url_quote

import numpy as np

from config import (
    FULL_A_FINAL_LIMIT,
    FULL_A_NO_OVERLAY_LOW_QUOTA,
    FULL_A_NO_OVERLAY_NEUTRAL_QUOTA,
    FULL_A_NO_OVERLAY_TREND_QUOTA,
    MIN_DAILY_AMOUNT,
    MIN_LISTED_DAYS,
)

from .market_history_store import MarketHistoryStore
from .preclose_data import fetch_target_30m_snapshots
from .preclose_pipeline import PreclosePipelineComponents
from .right_side_startup import (
    resolve_right_side_startup_mode,
    select_classic_startup_inputs,
)
from .universe_builder import (
    UniverseConfig,
    build_candidate_universe,
    load_eligible_candidates,
)


MARKET_INDICES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "科创50": "000688",
    "沪深300": "000300",
    "中证500": "000905",
}
_ARRAY_KEYS = ("dates", "opens", "highs", "lows", "closes", "volumes")


def _as_list(value):
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _readonly_connection(path):
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    connection = sqlite3.connect(
        "file:{}?mode=ro".format(url_quote(str(resolved))),
        uri=True,
    )
    connection.execute("PRAGMA query_only = ON")
    return connection


def _previous_market_date(formal_market_db, trade_date):
    with _readonly_connection(formal_market_db) as connection:
        row = connection.execute(
            "SELECT substr(b.ts, 1, 10) AS trade_date "
            "FROM bars_day b JOIN instruments i "
            "ON i.instrument_id=b.instrument_id "
            "WHERE i.asset_type='stock' AND b.is_final=1 "
            "AND substr(b.ts, 1, 10) < ? "
            "GROUP BY substr(b.ts, 1, 10) "
            "HAVING COUNT(DISTINCT b.instrument_id) >= 1000 "
            "ORDER BY trade_date DESC LIMIT 1",
            (str(trade_date),),
        ).fetchone()
    if not row:
        raise RuntimeError("previous full-market date unavailable")
    return str(row[0])


def load_readonly_preclose_universe(formal_market_db, trade_date):
    """Select the current no-overlay retrieval universe from prior final bars."""

    previous_date = _previous_market_date(formal_market_db, trade_date)
    with MarketHistoryStore(formal_market_db, readonly=True) as store:
        candidates, eligibility = load_eligible_candidates(
            store,
            as_of=previous_date,
            required_date=previous_date,
            min_listed_days=MIN_LISTED_DAYS,
            min_daily_amount=MIN_DAILY_AMOUNT,
            return_diagnostics=True,
        )
    config = UniverseConfig(
        low_quota=FULL_A_NO_OVERLAY_LOW_QUOTA,
        trend_quota=FULL_A_NO_OVERLAY_TREND_QUOTA,
        neutral_quota=FULL_A_NO_OVERLAY_NEUTRAL_QUOTA,
        base_limit=FULL_A_FINAL_LIMIT,
        overlay_limit=0,
        final_limit=FULL_A_FINAL_LIMIT,
    )
    retrieval = build_candidate_universe(candidates, [], config=config)
    selected = list(retrieval.get("final") or [])
    if not selected:
        raise RuntimeError("pre-close retrieval universe unavailable")
    return selected, {
        "previous_market_date": previous_date,
        "eligibility": eligibility,
        "retrieval": retrieval.get("diagnostics") or {},
        "selected_count": len(selected),
        "source": "formal_market_history_readonly",
    }


def _valid_quote(quote):
    values = {
        key: _finite(quote.get(key))
        for key in (
            "open", "high", "low", "current_price", "prev_close",
            "volume", "amount",
        )
    }
    if any(
        values[key] is None or values[key] <= 0
        for key in ("open", "high", "low", "current_price", "prev_close")
    ):
        return None
    if values["volume"] is None or values["volume"] < 0:
        return None
    if values["amount"] is None or values["amount"] < 0:
        return None
    if values["high"] < max(
        values["open"], values["low"], values["current_price"]
    ):
        return None
    if values["low"] > min(
        values["open"], values["high"], values["current_price"]
    ):
        return None
    return values


def _append_intraday_quote(candidate, quote, trade_date, as_of):
    values = _valid_quote(quote)
    if not values:
        return None
    source_kline = candidate.get("klines")
    source_kline = source_kline if isinstance(source_kline, dict) else {}
    arrays = {key: _as_list(source_kline.get(key)) for key in _ARRAY_KEYS}
    if not arrays["dates"] or any(
        len(arrays[key]) != len(arrays["dates"])
        for key in _ARRAY_KEYS[1:]
    ):
        return None
    last_date = str(arrays["dates"][-1]).split(" ", 1)[0]
    if last_date >= str(trade_date):
        return None
    last_close = _finite(arrays["closes"][-1])
    if last_close is None or abs(last_close - values["prev_close"]) > max(
        0.05, abs(last_close) * 0.01
    ):
        return None
    amounts = _as_list(source_kline.get("amounts"))
    if len(amounts) != len(arrays["dates"]):
        amounts = [None] * len(arrays["dates"])
    arrays["dates"].append(str(trade_date))
    arrays["opens"].append(values["open"])
    arrays["highs"].append(values["high"])
    arrays["lows"].append(values["low"])
    arrays["closes"].append(values["current_price"])
    arrays["volumes"].append(values["volume"])
    amounts.append(values["amount"])
    output_kline = {key: values_list[-120:] for key, values_list in arrays.items()}
    output_kline["amounts"] = amounts[-120:]
    output_kline["finals"] = [True] * (len(output_kline["dates"]) - 1) + [False]
    output_kline["source"] = "formal_history+eastmoney_intraday"

    row = dict(candidate)
    row.update({
        "name": str(quote.get("name") or candidate.get("name") or ""),
        "sector": str(quote.get("industry") or candidate.get("sector") or ""),
        "is_st": bool(quote.get("is_st")),
        "listed_date": str(quote.get("listed_date") or ""),
        "change_pct": _finite(quote.get("change_pct")),
        "amount": values["amount"],
        "status": "available",
        "bar_state": "intraday",
        "is_final": False,
        "as_of": str(as_of),
        "latest_date": str(trade_date),
        "klines": output_kline,
    })
    return row


def _sector_context(quotes):
    aggregates = defaultdict(lambda: {"changes": [], "amount": 0.0})
    for row in quotes:
        name = str(row.get("industry") or "").strip()
        change = _finite(row.get("change_pct"))
        amount = _finite(row.get("amount"))
        if not name:
            continue
        if change is not None:
            aggregates[name]["changes"].append(change)
        if amount is not None and amount >= 0:
            aggregates[name]["amount"] += amount
    ranked = []
    for name, value in aggregates.items():
        changes = value["changes"]
        if not changes:
            continue
        ranked.append({
            "name": name,
            "change_pct": round(sum(changes) / len(changes), 4),
            "amount": round(value["amount"], 2),
        })
    ranked.sort(key=lambda item: (-item["change_pct"], -item["amount"], item["name"]))
    for rank, row in enumerate(ranked, start=1):
        row["sector_rank"] = rank
        row["sector_strength_label"] = "盘中涨幅TOP{}".format(rank)
    return ranked


def select_preclose_30m_targets(rows, components=None):
    """Reuse daily pool and startup seed rules before any 30-minute request."""

    components = components or PreclosePipelineComponents()
    analyses = []
    sector_stocks = {}
    for row in rows or []:
        kline = row.get("klines") if isinstance(row, dict) else None
        if not isinstance(kline, dict):
            continue
        try:
            analysis = components.analyze(
                code=str(row.get("code") or ""),
                name=str(row.get("name") or ""),
                dates=kline["dates"],
                opens=np.asarray(kline["opens"], dtype=float),
                highs=np.asarray(kline["highs"], dtype=float),
                lows=np.asarray(kline["lows"], dtype=float),
                closes=np.asarray(kline["closes"], dtype=float),
                volumes=np.asarray(kline["volumes"], dtype=float),
            )
        except Exception:
            continue
        if analysis is not None:
            analyses.append(analysis)
            sector_stocks[str(row.get("code") or "")] = {
                key: row.get(key)
                for key in (
                    "sector", "sector_rank", "sector_strength_label", "amount",
                )
            }
    pure_pool, _diagnostics = components.build_daily_structure_pool(
        analyses, sector_stocks, mode="pure"
    )
    classic_input_state = select_classic_startup_inputs(
        analyses, pure_pool
    )
    startup_seeds, _watchlist, _startup_diagnostics = (
        components.build_strong_startup_pool(
            classic_input_state["rows"], sector_stocks
        )
    )
    right_seeds = []
    if resolve_right_side_startup_mode(
        components.right_side_startup_mode
    ) != "off":
        right_seeds, _right_watchlist, _right_diagnostics = (
            components.build_right_side_startup_pool(
                analyses, sector_stocks
            )
        )
    codes = []
    seen = set()
    for item in (
        list(pure_pool or [])
        + list(startup_seeds or [])
        + list(right_seeds or [])
    ):
        code = str((item or {}).get("code") or "")
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    by_code = {str(row.get("code") or ""): row for row in rows or []}
    return [by_code[code] for code in codes if code in by_code]


class _Prefetched30m:
    def __init__(self, values):
        self.values = dict(values)

    def fetch_30m(self, code, count, as_of):
        del count, as_of
        return self.values.get(str(code))


def fetch_preclose_30m(targets, trade_date, as_of, max_workers=20):
    """Fetch only already-selected targets from the remote-only 30m adapter."""

    from .data_fetcher import (
        _fetch_eastmoney_minute_kline_remote,
        _fetch_sina_minute_kline_remote,
    )

    def fetch_remote(code):
        return (
            _fetch_sina_minute_kline_remote(code, scale=30, count=80)
            or _fetch_eastmoney_minute_kline_remote(
                code, scale=30, count=80
            )
        )

    targets = list(targets or [])
    values = {}
    if targets:
        workers = max(1, min(int(max_workers), len(targets)))
        executor = ThreadPoolExecutor(max_workers=workers)
        futures = {
            executor.submit(
                fetch_remote,
                str(row.get("code") or ""),
            ): str(row.get("code") or "")
            for row in targets
        }
        try:
            for future in as_completed(futures):
                code = futures[future]
                try:
                    values[code] = future.result()
                except Exception:
                    values[code] = None
        except BaseException:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False)
            raise
        else:
            executor.shutdown(wait=True)
    return fetch_target_30m_snapshots(
        targets,
        fetcher=_Prefetched30m(values),
        trade_date=trade_date,
        as_of=as_of,
        count=80,
    )


def fetch_preclose_indices(trade_date, max_workers=6):
    """Fetch current index evidence from two independent remote-only sources."""

    from .data_fetcher import (
        _fetch_daily_kline_remote,
        _fetch_daily_kline_tencent_plain_remote,
    )

    sources = {
        "tencent": _fetch_daily_kline_remote,
        "tencent_plain": _fetch_daily_kline_tencent_plain_remote,
    }
    fetched = defaultdict(dict)
    executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
    futures = {}
    for name, code in MARKET_INDICES.items():
        count = 60 if name == "上证指数" else 3
        for source, fetcher in sources.items():
            future = executor.submit(fetcher, code, count)
            futures[future] = (name, code, source)
    try:
        for future in as_completed(futures):
            name, code, source = futures[future]
            fetched[name][source] = future.result()
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False)
        raise
    else:
        executor.shutdown(wait=True)

    output = {}
    for name, code in MARKET_INDICES.items():
        candidates = []
        for source in sources:
            kline = fetched[name].get(source)
            kline = kline if isinstance(kline, dict) else {}
            dates = _as_list(kline.get("dates"))
            closes = [_finite(value) for value in _as_list(kline.get("closes"))]
            latest_date = str(dates[-1]).split(" ", 1)[0] if dates else ""
            if (
                latest_date != str(trade_date)
                or len(closes) < 2
                or closes[-2] in (None, 0)
                or closes[-1] is None
            ):
                raise RuntimeError(
                    "index evidence unavailable: {}/{}".format(name, source)
                )
            candidates.append((source, kline, closes))
        changes = [
            (closes[-1] / closes[-2] - 1) * 100
            for _source, _kline, closes in candidates
        ]
        if max(changes) - min(changes) > 0.3:
            raise RuntimeError("index source conflict: {}".format(name))
        source, kline, closes = candidates[0]
        output[name] = {
            "code": code,
            "close": round(closes[-1], 4),
            "change_pct": round(changes[0], 4),
            "date": str(_as_list(kline.get("dates"))[-1]).split(" ", 1)[0],
            "source": source + "+tencent_plain_verified",
            "closes": closes,
        }
    return {name: output[name] for name in MARKET_INDICES}


def load_market_turnover_history(formal_market_db, trade_date):
    with _readonly_connection(formal_market_db) as connection:
        rows = connection.execute(
            "SELECT substr(b.ts, 1, 10) AS trade_date, SUM(b.amount) AS total "
            "FROM bars_day b JOIN instruments i "
            "ON i.instrument_id=b.instrument_id "
            "WHERE i.asset_type='stock' AND b.is_final=1 "
            "AND substr(b.ts, 1, 10) < ? "
            "GROUP BY substr(b.ts, 1, 10) "
            "HAVING COUNT(DISTINCT b.instrument_id) >= 1000 "
            "ORDER BY trade_date DESC LIMIT 20",
            (str(trade_date),),
        ).fetchall()
    return [float(row[1]) for row in reversed(rows) if row[1] is not None]


def _average_tail(values, count):
    selected = [_finite(value) for value in list(values or [])[-int(count):]]
    selected = [value for value in selected if value is not None]
    return sum(selected) / len(selected) if selected else None


def build_scheduled_preclose_input(
    trade_date,
    as_of,
    *,
    formal_market_db,
    universe_loader=None,
    quote_fetcher=None,
    index_fetcher=None,
    target_selector=None,
    min30_fetcher=None,
    turnover_loader=None,
):
    """Build one complete input using only batch quotes and read-only history."""

    parsed = datetime.strptime(str(trade_date), "%Y-%m-%d")
    if parsed.strftime("%Y-%m-%d") != str(trade_date):
        raise ValueError("invalid trade_date")
    universe_loader = universe_loader or load_readonly_preclose_universe
    if quote_fetcher is None:
        from .data_fetcher import fetch_all_a_stocks
        quote_fetcher = lambda: fetch_all_a_stocks(return_diagnostics=True)
    index_fetcher = index_fetcher or fetch_preclose_indices
    target_selector = target_selector or select_preclose_30m_targets
    min30_fetcher = min30_fetcher or fetch_preclose_30m
    turnover_loader = turnover_loader or load_market_turnover_history

    universe, universe_diagnostics = universe_loader(
        formal_market_db, str(trade_date)
    )
    quotes, quote_diagnostics = quote_fetcher()
    quotes = list(quotes or [])
    quote_diagnostics = (
        quote_diagnostics if isinstance(quote_diagnostics, dict) else {}
    )
    requested = int(quote_diagnostics.get("requested") or 0)
    unique = int(quote_diagnostics.get("unique") or len(quotes))
    if (
        quote_diagnostics.get("complete") is not True
        or requested <= 0
        or unique != requested
        or len(quotes) != unique
    ):
        raise RuntimeError("full-market intraday quote snapshot incomplete")
    quotes_by_code = {
        str(row.get("code") or ""): row
        for row in quotes
        if isinstance(row, dict) and str(row.get("code") or "")
    }
    sectors = _sector_context(quotes)
    sector_by_name = {row["name"]: row for row in sectors}
    daily = []
    for candidate in universe or []:
        code = str((candidate or {}).get("code") or "")
        quote = quotes_by_code.get(code)
        if not quote:
            continue
        row = _append_intraday_quote(
            candidate, quote, str(trade_date), str(as_of)
        )
        if not row:
            continue
        context = sector_by_name.get(str(row.get("sector") or ""), {})
        for key in ("sector_rank", "sector_strength_label"):
            if context.get(key) is not None:
                row[key] = context[key]
        daily.append(row)
    if not daily:
        raise RuntimeError("no eligible intraday daily rows")

    targets = list(target_selector(daily) or [])
    target_codes = [str(row.get("code") or "") for row in targets]
    min30 = min30_fetcher(targets, str(trade_date), str(as_of))
    indices = index_fetcher(str(trade_date))
    if set(indices) != set(MARKET_INDICES):
        raise RuntimeError("market index evidence incomplete")
    stock_bars = []
    current_turnover = 0.0
    for quote in quotes:
        values = _valid_quote(quote)
        if not values:
            continue
        stock_bars.append({
            "code": str(quote.get("code") or ""),
            "name": str(quote.get("name") or ""),
            "prev_close": values["prev_close"],
            "close": values["current_price"],
            "is_st": bool(quote.get("is_st")),
        })
        current_turnover += values["amount"]
    turnover_history = turnover_loader(formal_market_db, str(trade_date))
    input_payload = {
        "schema_version": "preclose-input-v1",
        "mode": "preclose_advisory",
        "trade_date": str(trade_date),
        "as_of": str(as_of),
        "bar_state": "intraday",
        "is_final": False,
        "daily": daily,
        "target_codes": target_codes,
        "min30": min30,
        "market": {
            "stock_bars": stock_bars,
            "market_indices": indices,
            "index_bars": list(indices.values()),
            "turnover": current_turnover,
            "turnover_ma5": _average_tail(turnover_history, 5),
            "turnover_ma20": _average_tail(turnover_history, 20),
            "sectors": sectors[:20],
        },
        "runtime_diagnostics": {
            "universe": universe_diagnostics,
            "quote_snapshot": quote_diagnostics,
            "daily_count": len(daily),
            "target_30m_count": len(target_codes),
            "full_market_bar_count": len(stock_bars),
            "forbidden_dependencies": {
                "news": False,
                "llm": False,
                "iwencai": False,
                "min15": False,
                "report_generation": False,
                "git_publish": False,
            },
        },
    }
    return input_payload
