"""Small, local proofs of a single provider's historical qfq response.

The canonical market database is deliberately not an input to this module.
Every returned series is reconstructed from saved response bytes, never from
an asserted ``bars`` array or a matching pair of self-declared hashes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


SCHEMA_VERSION = "selection-price-evidence-v1"
_IDENTITY = re.compile(r"(SH|SZ|BJ)(\d{6})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RESPONSE_BYTES = 256 * 1024
_CN_TZ = timezone(timedelta(hours=8))


def _canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamp must have a timezone")
    return parsed.astimezone(_CN_TZ)


def _market(identity):
    match = _IDENTITY.fullmatch(identity if isinstance(identity, str) else "")
    if not match:
        raise ValueError("invalid stock identity")
    return ("1" if match.group(1) == "SH" else "0"), match.group(2)


def _number(value, *, positive):
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError("invalid historical price or volume")
    return number


def _decode_eastmoney(identity, request, raw, fetched_at):
    market, code = _market(identity)
    if not isinstance(request, dict) or (
        str(request.get("secid")) != "{}.{}".format(market, code)
        or str(request.get("klt")) != "101"
        or str(request.get("fqt")) != "1"
    ):
        raise ValueError("historical request identity or adjustment mismatch")
    if len(raw) > _MAX_RESPONSE_BYTES or not raw:
        raise ValueError("historical response size out of bounds")
    start = request.get("beg")
    end = request.get("end")
    try:
        first_allowed = datetime.strptime(start, "%Y%m%d").date() if start else None
        last_allowed = datetime.strptime(end, "%Y%m%d").date() if end else None
    except (TypeError, ValueError):
        raise ValueError("invalid historical request window")
    if first_allowed is not None and last_allowed is not None \
            and first_allowed > last_allowed:
        raise ValueError("reversed historical request window")
    captured = _timestamp(fetched_at)
    response = json.loads(raw.decode("utf-8"))
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict) or str(data.get("code")) != code \
            or str(data.get("market")) != market:
        raise ValueError("historical response identity mismatch")
    lines = data.get("klines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("historical response has no kline rows")
    last_date = None
    bars = []
    for line in lines:
        if not isinstance(line, str):
            raise ValueError("invalid historical kline row")
        parts = line.split(",")
        if len(parts) < 6:
            raise ValueError("incomplete historical kline row")
        current = date.fromisoformat(parts[0])
        if current.isoformat() != parts[0] or (last_date is not None and current <= last_date):
            raise ValueError("historical dates must be sorted and unique")
        if (first_allowed is not None and current < first_allowed) or (
                last_allowed is not None and current > last_allowed):
            raise ValueError("historical response is outside the request window")
        opening, closing, high, low = (_number(part, positive=True) for part in parts[1:5])
        volume = _number(parts[5], positive=False)
        if low > min(opening, closing) or high < max(opening, closing):
            raise ValueError("historical OHLC is inconsistent")
        is_final = current < captured.date() or (
            current == captured.date() and captured.timetz().replace(tzinfo=None) >= time(15, 0)
        )
        bars.append({
            "date": parts[0], "close": closing, "volume": volume,
            "is_final": is_final, "adjustment": "qfq",
            "instrument_id": identity,
        })
        last_date = current
    return bars


def _decode_tencent(identity, request, raw, fetched_at):
    _market(identity)
    symbol = identity[:2].lower() + identity[2:]
    if not isinstance(request, dict) or request.get("symbol") != symbol \
            or request.get("period") != "day" \
            or request.get("adjustment") != "qfq":
        raise ValueError("Tencent request identity or adjustment mismatch")
    start, end, count = (request.get(key) for key in ("start", "end", "count"))
    try:
        first_allowed = date.fromisoformat(start) if start else None
        last_allowed = date.fromisoformat(end) if end else None
        parsed_count = int(count)
    except (TypeError, ValueError):
        raise ValueError("invalid Tencent historical window")
    if parsed_count < 1 or parsed_count > 100 or (first_allowed and last_allowed
                                                 and first_allowed > last_allowed):
        raise ValueError("invalid Tencent historical window")
    expected_param = "{},day,{},{},{},qfq".format(
        symbol, start or "", end or "", parsed_count,
    )
    if request.get("param") != expected_param or len(raw) > _MAX_RESPONSE_BYTES or not raw:
        raise ValueError("Tencent parameter or response size mismatch")
    captured = _timestamp(fetched_at)
    response = json.loads(raw.decode("utf-8"))
    if not isinstance(response, dict) or str(response.get("code", 0)) != "0":
        raise ValueError("invalid Tencent historical response")
    data = response.get("data")
    stock = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(stock, dict) or not isinstance(stock.get("qfqday"), list) \
            or not stock["qfqday"]:
        raise ValueError("Tencent qfqday response is missing")
    if "symbol" in stock and stock["symbol"] != symbol:
        raise ValueError("Tencent response symbol mismatch")
    bars = []
    last_date = None
    for row in stock["qfqday"]:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError("invalid Tencent qfqday row")
        current = date.fromisoformat(row[0])
        if current.isoformat() != row[0] or (last_date and current <= last_date):
            raise ValueError("Tencent dates must be sorted and unique")
        if (first_allowed and current < first_allowed) or (
                last_allowed and current > last_allowed):
            raise ValueError("Tencent response is outside the request window")
        opening, closing, high, low = (_number(value, positive=True)
                                        for value in row[1:5])
        volume = _number(row[5], positive=False)
        if low > min(opening, closing) or high < max(opening, closing):
            raise ValueError("Tencent OHLC is inconsistent")
        is_final = current < captured.date() or (
            current == captured.date() and captured.timetz().replace(tzinfo=None) >= time(15, 0)
        )
        bars.append({
            "date": row[0], "close": closing, "volume": volume,
            "is_final": is_final, "adjustment": "qfq",
            "instrument_id": identity,
        })
        last_date = current
    return bars


def _persist_response(evidence_dir, identity, request, raw_response, captured, provider):
    digest = hashlib.sha256(raw_response).hexdigest()
    record = {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "instrument_id": identity,
        "request": request,
        "fetched_at": captured.isoformat(),
        "raw_sha256": digest,
        "raw_response": raw_response.decode("utf-8"),
    }
    folder = Path(evidence_dir) / identity
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / (digest + ".json")
    if target.is_file():
        try:
            _load_record(target, identity, None, None)
            return target
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            pass
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".evidence-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def capture_eastmoney_historical_response(evidence_dir, identity, request_params,
                                          raw_response, *, fetched_at=None):
    """Persist exact response bytes from an already completed Eastmoney request.

    This function performs no network activity. One immutable response gets one
    file under its stock identity; a later short overlap cannot erase an older
    response that covered a published start and target date.
    """
    if not isinstance(raw_response, bytes):
        raise ValueError("raw historical response must be bytes")
    if not isinstance(request_params, dict):
        raise ValueError("invalid historical request parameters")
    captured = _timestamp(fetched_at or datetime.now(_CN_TZ).isoformat())
    request = {key: str(request_params.get(key, ""))
               for key in ("secid", "klt", "fqt", "end", "lmt")}
    if request_params.get("beg") is not None:
        request["beg"] = str(request_params["beg"])
    _decode_eastmoney(identity, request, raw_response, captured.isoformat())
    return _persist_response(evidence_dir, identity, request, raw_response,
                             captured, "eastmoney")


def capture_tencent_historical_response(evidence_dir, identity, request_params,
                                        raw_response, *, fetched_at=None):
    """Persist only a Tencent qfqday payload whose request/window are verified."""
    if not isinstance(raw_response, bytes) or not isinstance(request_params, dict):
        raise ValueError("invalid Tencent historical response")
    captured = _timestamp(fetched_at or datetime.now(_CN_TZ).isoformat())
    request = {key: str(request_params.get(key, ""))
               for key in ("symbol", "period", "adjustment", "start", "end",
                           "count", "param")}
    _decode_tencent(identity, request, raw_response, captured.isoformat())
    return _persist_response(evidence_dir, identity, request, raw_response,
                             captured, "tencent")


def _load_record(path, identity, price_cutoff_at, evidence_cutoff_at):
    if path.is_symlink() or path.stat().st_size > _MAX_RESPONSE_BYTES * 2:
        raise ValueError("invalid evidence file")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION \
            or record.get("provider") not in ("eastmoney", "tencent") \
            or record.get("instrument_id") != identity:
        raise ValueError("invalid evidence record")
    raw = record.get("raw_response")
    digest = record.get("raw_sha256")
    if not isinstance(raw, str) or not isinstance(digest, str) \
            or not _SHA256.fullmatch(digest) or path.name != digest + ".json" \
            or hashlib.sha256(raw.encode("utf-8")).hexdigest() != digest:
        raise ValueError("historical raw response hash mismatch")
    provider = record["provider"]
    decode = _decode_eastmoney if provider == "eastmoney" else _decode_tencent
    bars = decode(identity, record.get("request"), raw.encode("utf-8"),
                  record.get("fetched_at"))
    if evidence_cutoff_at is not None \
            and _timestamp(record.get("fetched_at")) > evidence_cutoff_at:
        raise ValueError("response was captured after evaluation cutoff")
    if price_cutoff_at is not None \
            and bars[-1]["date"] > price_cutoff_at.date().isoformat():
        raise ValueError("response extends beyond evaluation cutoff")
    source_response = {
        "instrument_id": identity, "adjustment": "qfq",
        "provider": provider, "bars": bars,
        "raw_sha256": digest,
        "fetched_at": record["fetched_at"],
        "request": record["request"],
    }
    series = {
        "instrument_id": identity,
        "series_ref": "{}:{}:{}".format(provider, identity, digest[:24]),
        "adjustment": "qfq",
        "bars": bars,
        "source_response": source_response,
        "basis_evidence": {
            "status": "verified", "kind": "single_historical_response",
            "source_ref": "{}:{}".format(provider, digest[:24]),
            "content_sha256": _canonical_hash(bars),
            "response_sha256": _canonical_hash(source_response),
        },
    }
    return series, digest


def _cutoff_timestamp(value):
    if value is None:
        return None
    text = str(value)
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), time.max, tzinfo=_CN_TZ)
    return _timestamp(text)


def load_verified_price_series(evidence_dir, identities, *, evaluation_as_of=None,
                               evidence_as_of=None):
    """Return independently reconstructed series and a stable content fingerprint."""
    price_cutoff_at = _cutoff_timestamp(evaluation_as_of)
    evidence_cutoff_at = _cutoff_timestamp(
        evidence_as_of if evidence_as_of is not None else evaluation_as_of
    )
    root = Path(evidence_dir)
    found = {}
    accepted = []
    for identity in sorted(set(identities)):
        try:
            _market(identity)
        except ValueError:
            continue
        folder = root / identity
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                series, digest = _load_record(path, identity, price_cutoff_at,
                                              evidence_cutoff_at)
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                continue
            found.setdefault(identity, []).append(series)
            accepted.append((identity, digest,
                             series["source_response"]["fetched_at"]))
    return found, _canonical_hash(accepted) if accepted else None


def _attempt_ledger(evidence_dir):
    path = Path(evidence_dir) / "fill-attempts.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result = {}
    for identity, row in payload.items():
        if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
            continue
        if type(row) is int:
            row = {"count": row}
        if not isinstance(row, dict) or type(row.get("count")) is not int \
                or row["count"] < 0:
            continue
        last = row.get("last_report_date")
        result[identity] = {"count": row["count"],
                            "last_report_date": last if isinstance(last, str) else None}
    return result


def select_due_fill_candidate(dataset, evidence_dir, *, preferred_identity=None):
    """Choose one published, matured missing proof; rotate past failed attempts."""
    due = {}
    published = set()
    for row in dataset.get("observations") or []:
        identity = row.get("instrument_id")
        report_date = row.get("report_date")
        if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity) \
                or not isinstance(report_date, str):
            continue
        published.add(identity)
        if any(isinstance(outcome, dict)
               and outcome.get("status") == "price_basis_unverified"
               for outcome in (row.get("outcomes") or {}).values()):
            due[identity] = min(due.get(identity, report_date), report_date)
    if preferred_identity is not None and preferred_identity not in published:
        raise ValueError("requested evidence target is not a published member")
    attempts = _attempt_ledger(evidence_dir)
    if preferred_identity is not None:
        return ((preferred_identity, due[preferred_identity])
                if preferred_identity in due else None)
    if not due:
        return None
    identity = min(due, key=lambda item: (
        attempts.get(item, {}).get("count", 0), due[item], item,
    ))
    return identity, due[identity]


def record_fill_attempt(evidence_dir, identity, report_date):
    """Keep a tiny fairness counter so one failing stock does not monopolize runs."""
    _market(identity)
    folder = Path(evidence_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    counts = _attempt_ledger(folder)
    counts[identity] = {
        "count": counts.get(identity, {}).get("count", 0) + 1,
        "last_report_date": str(report_date),
    }
    target = folder / "fill-attempts.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".fill-attempts-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(counts, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
