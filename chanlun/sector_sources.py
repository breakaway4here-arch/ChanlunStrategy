"""Strict, same-day parsing for Eastmoney's public sector fund relay."""

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .identity import infer_stock_exchange, normalize_identity
from .quote_sources import valid_quote


CN = timezone(timedelta(hours=8))
RELAY_URL = "https://data.eastmoney.com/dataapi/bkzj/getbkzj"
_SECTOR_CODE = re.compile(r"BK[0-9]{4}\Z")
_STOCK_CODE = re.compile(r"[0-9]{6}\Z")


class SectorSourceError(ValueError):
    """Relay payload lacks the completeness or date proof needed for ranking."""


def _rows(payload, identity_field, *, max_total=10000):
    data = payload.get("data") if isinstance(payload, dict) and payload.get("rc") == 0 else None
    if not isinstance(data, dict) or not isinstance(data.get("diff"), list):
        raise SectorSourceError("missing_relay_data")
    total = data.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0 or total > max_total:
        raise SectorSourceError("invalid_relay_total")
    rows = data["diff"]
    if len(rows) != total:
        raise SectorSourceError("incomplete_relay_rows")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SectorSourceError("invalid_relay_row")
        code = row.get("f12")
        market = row.get("f13")
        if not isinstance(code, str) or not identity_field.fullmatch(code):
            raise SectorSourceError("invalid_relay_identity")
        if isinstance(market, bool) or not isinstance(market, int):
            raise SectorSourceError("invalid_relay_market")
        key = (market, code)
        if key in indexed:
            raise SectorSourceError("duplicate_relay_identity")
        indexed[key] = row
    return indexed, total


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SectorSourceError("invalid_relay_number")
    return value


def parse_fund_relay(payloads, report_date, acquired_at):
    """Join three full relay lists by identity; reject stale or partial funds."""
    if acquired_at.tzinfo is None or acquired_at.astimezone(CN).date().isoformat() != report_date:
        raise SectorSourceError("invalid_acquisition_date")
    indexed = {}
    for field in ("f62", "f124"):
        if field not in payloads:
            raise SectorSourceError("missing_relay_field")
        indexed[field], total = _rows(payloads[field], _SECTOR_CODE, max_total=1000)
        if total == 0 or any(key[0] != 90 for key in indexed[field]):
            raise SectorSourceError("invalid_sector_set")
    keys = set(indexed["f62"])
    if keys != set(indexed["f124"]):
        raise SectorSourceError("relay_identity_mismatch")
    if "f3" in payloads:
        try:
            indexed["f3"], _ = _rows(payloads["f3"], _SECTOR_CODE, max_total=1000)
            if set(indexed["f3"]) != keys:
                indexed["f3"] = {}
        except SectorSourceError:
            indexed["f3"] = {}
    else:
        indexed["f3"] = {}
    result = []
    for key in keys:
        amount = _finite(indexed["f62"][key].get("f62"))
        pct_row = indexed["f3"].get(key, {})
        pct_raw = pct_row.get("f3")
        if (pct_row.get("f14") != indexed["f62"][key].get("f14")
                or isinstance(pct_raw, bool)
                or not isinstance(pct_raw, (int, float))
                or not math.isfinite(pct_raw)):
            pct_raw = None
        stamp_raw = _finite(indexed["f124"][key].get("f124"))
        if not isinstance(stamp_raw, int):
            raise SectorSourceError("invalid_relay_timestamp")
        try:
            stamp = datetime.fromtimestamp(stamp_raw, CN)
        except (ValueError, OverflowError, OSError) as exc:
            raise SectorSourceError("invalid_relay_timestamp") from exc
        if stamp.date().isoformat() != report_date or stamp > acquired_at.astimezone(CN) + timedelta(seconds=60):
            raise SectorSourceError("stale_or_future_sector_funds")
        name = indexed["f62"][key].get("f14")
        if not isinstance(name, str) or not name.strip():
            raise SectorSourceError("missing_sector_name")
        if indexed["f124"][key].get("f14") != name:
            raise SectorSourceError("sector_name_mismatch")
        result.append({"code": key[1], "name": name.strip(), "flow": amount,
                       "change_pct": pct_raw / 100 if pct_raw is not None else None,
                       "board_quote_as_of": stamp.isoformat(),
                       "flow_retrieved_at": acquired_at.astimezone(CN).isoformat(),
                       "fund_date_evidence": "same_day_board_quote"})
    return sorted(result, key=lambda row: (-row["flow"], row["code"]))


def verified_quote_snapshot(path, report_date, acquired_at):
    """Read an already saved full-A snapshot; never fetch or repair quotes."""
    try:
        if (acquired_at.tzinfo is None
                or acquired_at.astimezone(CN).date().isoformat() != report_date):
            raise ValueError("invalid_acquisition_date")
        payload = json.loads(Path(path).read_text())
        rows = payload["rows"]
        stamp = datetime.fromisoformat(payload["fetched_at"])
        if stamp.tzinfo is None:
            raise ValueError("naive_quote_snapshot_timestamp")
        stamp = stamp.astimezone(CN)
        diagnostics = payload.get("diagnostics")
        if (payload.get("schema_version") != 1
                or payload.get("universe_source") not in ("eastmoney", "sina_hs_a")
                or not isinstance(rows, list)
                or payload.get("requested") != len(rows)
                or not isinstance(diagnostics, dict)
                or diagnostics.get("complete") is not True
                or diagnostics.get("universe_source") != payload.get("universe_source")
                or any(diagnostics.get(field) != len(rows) for field in ("requested", "unique", "fetched"))
                or stamp.date().isoformat() != report_date
                or stamp > acquired_at.astimezone(CN) + timedelta(seconds=60)):
            raise ValueError("invalid_quote_snapshot_header")
        seen = set()
        for row in rows:
            identity = normalize_identity(row)
            if identity.asset_type != "stock" or identity.key in seen:
                raise ValueError("invalid_quote_snapshot_identity")
            seen.add(identity.key)
        return rows, "verified"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return [], "unavailable"


def parse_component_relay(payload, sector_code, quotes, report_date, acquired_at,
                          *, quote_evidence_status="verified"):
    """Keep every member identity while admitting only valid A-share quotes."""
    if (acquired_at.tzinfo is None
            or acquired_at.astimezone(CN).date().isoformat() != report_date):
        raise SectorSourceError("invalid_acquisition_date")
    if not _SECTOR_CODE.fullmatch(str(sector_code)):
        raise SectorSourceError("invalid_sector_code")
    indexed, total = _rows(payload, _STOCK_CODE)
    if len({code for _, code in indexed}) != total:
        raise SectorSourceError("duplicate_constituent_code")
    if any(market not in (0, 1) for market, _ in indexed):
        raise SectorSourceError("invalid_constituent_market")
    quotes_by_key = {}
    if quote_evidence_status == "verified":
        for quote in quotes:
            try:
                identity = normalize_identity(quote)
                if (identity.asset_type == "stock" and quote.get("quote_status") == "valid"
                        and quote.get("price_basis") == "raw"
                        and valid_quote(quote, acquired_at.astimezone(CN))):
                    quotes_by_key[identity.key] = quote
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
    stocks = []
    raw_codes = set()
    usable_codes = set()
    for (market, code), item in indexed.items():
        raw_codes.add(code)
        exchange = infer_stock_exchange(code)
        # The relay includes valid non-A constituents (for example B shares).
        # They count toward raw completeness but never enter the A-share pool.
        if not exchange:
            continue
        if (exchange == "SH" and market != 1) or (exchange in ("SZ", "BJ") and market != 0):
            raise SectorSourceError("constituent_market_mismatch")
        identity = normalize_identity({"asset_type": "stock", "exchange": exchange, "code": code})
        quote = quotes_by_key.get(identity.key)
        if quote is not None:
            usable_codes.add(code)
        name = item.get("f14")
        stocks.append({"code": code, "asset_type": "stock", "exchange": exchange,
                       "name": name.strip() if isinstance(name, str) and name.strip() else code,
                       "close": quote.get("current_price") if quote else None,
                       "change_pct": quote.get("change_pct") if quote else None,
                       "market_cap": None, "circulating_market_cap": None,
                       "float_market_cap": None})
    component_codes = sorted(stock["code"] for stock in stocks)
    diag = {"sector_code": sector_code, "source": "eastmoney_relay", "page_size": total,
            "requested": total, "fetched": total, "raw_valid_unique": len(indexed),
            "raw_component_codes": sorted(raw_codes), "filtered_unique": len(stocks),
            "unique": len(stocks), "component_codes": component_codes,
            "quote_usable_codes": sorted(usable_codes), "quote_usable_count": len(usable_codes),
            "quote_missing_codes": sorted(set(component_codes) - usable_codes),
            "quote_evidence_date": report_date, "quote_evidence_status": quote_evidence_status,
            "pages": 1, "complete": True, "error": ""}
    return sorted(stocks, key=lambda row: row["code"]), diag


class SectorRelaySession:
    """One collection's bounded fallback state; never shared across report dates."""

    def __init__(self, report_date, fetch_json, quote_cache_path, clock):
        self.report_date = report_date
        self.fetch_json = fetch_json
        self.quote_cache_path = quote_cache_path
        self.clock = clock
        self.clist_failed = False
        self._fund_rows = None
        self._fund_error = None
        self.used_relay_funds = False
        self._quotes = None
        self._quote_status = None

    def funds(self):
        if self._fund_error is not None:
            raise self._fund_error
        if self._fund_rows is None:
            try:
                payloads = {field: self.fetch_json(field, "m:90+t:2")
                            for field in ("f62", "f124")}
                try:
                    payloads["f3"] = self.fetch_json("f3", "m:90+t:2")
                except Exception:
                    # Price change is auxiliary; money and same-day board
                    # quote evidence are the two required full lists.
                    pass
                self._fund_rows = parse_fund_relay(payloads, self.report_date, self.clock())
                self.used_relay_funds = True
            except Exception as exc:
                self._fund_error = exc
                raise
        return self._fund_rows

    def members(self, sector_code):
        if self._quotes is None:
            self._quotes, self._quote_status = verified_quote_snapshot(
                self.quote_cache_path, self.report_date, self.clock())
        payload = self.fetch_json("f62", "b:" + sector_code)
        return parse_component_relay(payload, sector_code, self._quotes,
                                     self.report_date, self.clock(),
                                     quote_evidence_status=self._quote_status)
