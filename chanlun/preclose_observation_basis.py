"""Pre-close-only proof for an entire Eastmoney observation window."""

from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import stat

import numpy as np

from .identity import normalize_identity
from .intraday_observation_data import (
    ARRAY_KEYS, CN, PRICE_KEYS, _digest, _expected_times, _resample_30m,
    parse_eastmoney_daily, parse_eastmoney_minutes,
)
from .minute_sources import align_daily_basis
from .price_basis import basis_sha256, repaired_daily_basis_failure
from .preclose_schedule import PRE_CLOSE_CUTOFF_TIME

SCHEMA = "preclose-eastmoney-observation-30m-v1"
FALLBACK_KEY = "observation_basis_fallback"
SOURCE = "eastmoney_cutoff"
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024
_PRICES = ("open", "high", "low", "close")
_QUOTE_PRICES = ("open", "high", "low", "current_price")
_RESPONSE_MODES = (
    ("15", "0", "raw", "raw"), ("15", "1", "qfq", "qfq"),
    ("101", "0", "raw", "raw_daily"), ("101", "1", "qfq", "daily"),
)
_BAR_COLUMNS = ("dates",) + PRICE_KEYS + ("volumes",)
_QUANTITY_SOURCE_FIELDS = (
    "volume_unit", "volume_raw_unit", "volume_source", "amount_unit", "amount_source",
    "volume_units", "volume_raw_units", "volume_sources", "amount_units", "amount_sources",
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _time(value):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    _require(stamp.tzinfo is not None, "time_zone_missing")
    return stamp.astimezone(CN)


def _epoch_ns(stamp):
    return round(stamp.timestamp() * 1_000_000) * 1_000


def read_observation_capture(path, as_of):
    """Read one exact, local, regular capture without waiting on a special file."""
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= _MAX_CAPTURE_BYTES,
                 "capture_not_regular_or_too_large")
        # The observer publishes by hard link. ctime also bounds a file whose
        # old mtime was retained during a late link or rename.
        ready = max(before.st_ctime_ns, before.st_mtime_ns)
        _require(ready <= _epoch_ns(as_of), "capture_after_fact")
        content = source.read(_MAX_CAPTURE_BYTES + 1)
        after = os.fstat(source.fileno())
        _require(len(content) == before.st_size == after.st_size
                 and before.st_ctime_ns == after.st_ctime_ns
                 and before.st_mtime_ns == after.st_mtime_ns, "capture_changed_during_read")
    return json.loads(content), ready, hashlib.sha256(content).hexdigest()


def _read_pair(document, identity, cutoff, previous, fact, ready):
    result = document["result"]
    _require(document["identity"] == identity.key and document["cutoff"] == cutoff.isoformat()
             and document["sha256"] == _digest(result), "capture_identity_date_or_digest")
    pair = result.get("pair")
    _require(isinstance(pair, dict), "capture_has_no_source_pair")
    source = pair.get("source_evidence") or []
    _require(len(source) == len(_RESPONSE_MODES), "capture_missing_responses")
    known = [_time(row["fetched_at"]) for row in source]
    _require(known == sorted(known) and all(cutoff < stamp <= fact for stamp in known)
             and _epoch_ns(known[-1]) <= ready <= _epoch_ns(fact), "source_after_fact")
    parsed, hashes = {}, []
    secid = ("1" if identity.exchange == "SH" else "0") + "." + identity.code
    day = cutoff.date().isoformat()
    for row, stamp, (interval, flag, adjustment, key) in zip(source, known, _RESPONSE_MODES):
        params = row["params"]
        end = (day if interval == "15" else previous).replace("-", "")
        _require((params["secid"], params["klt"], params["fqt"], params["end"])
                 == (secid, interval, flag, end), "source_request_identity_date_or_basis")
        response = row["response"]
        digest = _digest(response)
        _require(row["response_sha256"] == digest, "response_digest_mismatch")
        hashes.append(digest)
        if interval == "15":
            parsed[key] = parse_eastmoney_minutes(
                response, identity, adjustment=adjustment, cutoff=cutoff, fetched_at=stamp)
        else:
            parsed[key] = parse_eastmoney_daily(
                response, identity, adjustment=adjustment, previous_trade_date=previous)
        _require(parsed[key] == pair[key], "reparsed_source_changed")
    raw_days, qfq_days = parsed["raw_daily"], parsed["daily"]
    _require([row["ts"] for row in raw_days] == [row["ts"] for row in qfq_days]
             and all(a[key] == b[key] for a,b in zip(raw_days, qfq_days)
                     for key in ("volume", "amount")), "source_daily_quantity_or_date_conflict")
    return parsed, known[-1], hashes


def _sina_pending(original, fact):
    kline = original.get("klines", {})
    marker = kline.get("minute_to_daily", {})
    return (original.get("status") == "available" and original.get("is_final") is False
            and original.get("as_of") == fact.isoformat()
            and kline.get("source") == "sina" and kline.get("adjustment") == "unverified"
            and isinstance(marker, dict) and marker.get("schema_version") == 1
            and marker.get("status") == "pending" and marker.get("reason") == "preclose_basis_unverified")


def _canonical_rows(stock, days, fact, previous):
    basis, daily = stock["price_basis"], stock["klines"]
    _require(stock.get("is_final") is False and stock.get("bar_state") == "intraday"
             and stock.get("as_of") == fact.isoformat()
             and daily["dates"][-2:] == [previous, fact.date().isoformat()]
             and daily["finals"][-1] is False and daily["adjustment"] == "qfq",
             "nonfinal_daily_reference_mismatch")
    ref = basis.get("canonical_daily")
    _require(isinstance(ref,dict), "canonical_reference_unavailable")
    _require(basis.get("historical_known_at"), "canonical_known_time_unavailable")
    rows = ref["by_date"]
    known = _time(basis["historical_known_at"])
    _require(ref["identity_key"] == normalize_identity(stock).key
             and ref["sha256"] == basis_sha256(rows)
             and known <= fact, "canonical_provenance_mismatch")
    dates = {value: index for index, value in enumerate(daily["dates"])}
    actual = {day: rows[day] for day in days}
    _require(all(row["is_final"] is True and row["source"] and row["adjustment"] == "qfq"
                 and daily["finals"][dates[day]] is True
                 and all(daily[key+"s"][dates[day]] == row[key] for key in _PRICES)
                 for day,row in actual.items()), "canonical_content_changed")
    failure = repaired_daily_basis_failure(
        [dict(row, ts=day) for day,row in actual.items()], as_of=known.isoformat())
    _require(failure is None, failure)
    return actual


def _full_raw_window(pair, dates, cutoff, calendar_check):
    raw, qfq = pair["raw"], pair["qfq"]
    days = sorted({stamp[:10] for stamp in dates})
    requested = set(days)
    day = cutoff.date().isoformat()
    first, end = datetime.fromisoformat(days[0]), datetime.fromisoformat(day)
    for offset in range((end-first).days+1):
        value = (first+timedelta(days=offset)).date().isoformat()
        _require(calendar_check(value) is (value in requested), "minute_calendar_gap")
    expected = [stamp for value in days
                for stamp in _expected_times(value, cutoff=cutoff if value==day else None)]
    raw_indices = [i for i,stamp in enumerate(raw["dates"]) if stamp[:10] in requested]
    qfq_indices = [i for i,stamp in enumerate(qfq["dates"]) if stamp[:10] in requested]
    _require([raw["dates"][i] for i in raw_indices]
             == [qfq["dates"][i] for i in qfq_indices] == expected, "minute_window_incomplete")
    _require(all(a[:10] <= day for a in dates) and all(
        raw["finals"][a] is True and qfq["finals"][b] is True
        and raw["amount_available"][a] is True and qfq["amount_available"][b] is True
        and all(raw[key][a] == qfq[key][b] for key in ("volumes","amounts"))
        and (raw["dates"][a][:10] != day or all(raw[key][a] == qfq[key][b] for key in PRICE_KEYS))
        for a,b in zip(raw_indices,qfq_indices)), "minute_price_quantity_or_finality_conflict")
    return {key: [value[i] for i in raw_indices] if key in ARRAY_KEYS else value
            for key,value in raw.items()}


def _quote_binding(stock, fact, cutoff):
    info = stock["price_basis"].get("intraday_quote")
    _require(isinstance(info,dict), "original_intraday_quote_unavailable")
    quote, known = info["raw"], _time(info["known_at"])
    event = _time(quote["quote_asof"])
    _require(normalize_identity(quote) == normalize_identity(stock)
             and quote["quote_source"] == "eastmoney" and quote["quote_status"] == "valid"
             and cutoff <= event <= known <= fact, "quote_identity_source_or_time_conflict")
    _require(quote["volume_unit"] == "hands" and quote["amount_unit"] == "CNY"
             and quote["amount_available"] is True and quote["volume_source"] == "eastmoney"
             and quote["amount_source"] == "eastmoney", "quote_quantity_contract")
    return quote, event, known


def _previous_scale(target, raw):
    factor = target["close"] / raw["close"]
    _require(math.isfinite(factor) and factor > 0 and all(
        abs(target[key]-factor*raw[key]) <= 1e-12 for key in _PRICES
    ), "independent_previous_scale_conflict")
    return factor


def _current_scale(stock, quote, raw_prior, raw_today, previous_scale):
    daily = stock["klines"]
    _require(quote["prev_close"] == raw_prior["close"] > 0
             and stock["price_basis"]["raw_previous_close"] == quote["prev_close"]
             and stock["price_basis"]["raw_current_price"] == quote["current_price"] > 0,
             "actual_raw_anchors_conflict")
    scale = daily["closes"][-1] / quote["current_price"]
    # Both actual splice and independent past OHLC must prove the same pure
    # scale. The stored previous-close factor is not used as a witness.
    _require(math.isfinite(scale) and scale > 0
             and abs(scale - previous_scale) <= 1e-12
             and all(abs(daily[key][-1]-scale*quote[raw_key]) <= 1e-12
                     for key,raw_key in zip(PRICE_KEYS,_QUOTE_PRICES)),
             "current_scale_not_independently_anchored")
    _require(raw_today["opens"][0] == quote["open"]
             and max(raw_today["highs"]) <= quote["high"]
             and min(raw_today["lows"]) >= quote["low"]
             and sum(raw_today["volumes"]) <= quote["volume"] == daily["volumes"][-1]
             and sum(raw_today["amounts"]) <= quote["amount"] == daily["amounts"][-1],
             "current_partial_quote_conflict")
    return scale


def _kline_digest(kline):
    return basis_sha256({key:kline.get(key) for key in ARRAY_KEYS + _QUANTITY_SOURCE_FIELDS
                         + ("identity_key","source","adjustment","as_of","fetched_at","interval")})


def _daily_fingerprint(stock):
    kline = stock["klines"]
    material = {key:kline[key] for key in ARRAY_KEYS}
    amounts = list(material["amounts"])
    available = material["amount_available"]
    _require(len(amounts) == len(available), "daily_amount_contract_mismatch")
    for index, amount in enumerate(amounts):
        if amount is None or (isinstance(amount, float) and math.isnan(amount)):
            _require(available[index] is False, "daily_amount_contract_mismatch")
            amounts[index] = None
    # The live reader uses NaN for an explicitly missing amount, while the
    # immutable input serializes that same value as null. Bind both to the
    # missing-value marker without changing prices, volume, or availability.
    material["amounts"] = amounts
    return basis_sha256(material)


def build_observation_fallback(stock, original, document, *, ready_at_ns, as_of,
                               previous, calendar_check, clock=None, capture_file_sha256=None):
    """Prove and map one whole replacement. The original remains independent."""
    fact = _time(as_of)
    day = fact.date().isoformat()
    cutoff = fact.replace(hour=14, minute=45, second=0,microsecond=0)
    identity = normalize_identity(stock)
    _require(identity.asset_type == "stock" and identity.exchange in ("SH","SZ")
             and _sina_pending(original,fact), "original_not_pending_sina")
    source = original["klines"]
    dates = source["dates"]
    _require(len(dates) >= 40 and len(set(dates)) == len(dates)
             and source["finals"] == [True] * len(dates)
             and dates == sorted(dates) and dates[-1][:10] == day
             and isinstance(ready_at_ns,int) and ready_at_ns <= _epoch_ns(fact),
             "original_hours_window_or_capture_time")
    pair, known, hashes = _read_pair(document,identity,cutoff,previous,fact,ready_at_ns)
    raw = _full_raw_window(pair,dates,cutoff,calendar_check)
    prior_days = sorted({stamp[:10] for stamp in dates if stamp[:10] < day})
    _require(prior_days and prior_days[-1] == previous, "minute_missing_true_previous_session")
    target = _canonical_rows(stock,prior_days,fact,previous)
    independent = {record["ts"]:dict(record, source=record["source_batch"])
                   for record in pair["raw_daily"]}
    size = sum(stamp[:10] < day for stamp in raw["dates"])
    historical = {key:np.asarray(raw[key][:size]) for key in PRICE_KEYS}
    historical.update(dates=raw["dates"][:size], finals=raw["finals"][:size], volume_unit="hands",
                      schema="archived_minute_v1", adjustment="unverified")
    mapped_history = align_daily_basis(historical,independent,target,scale=15)
    previous_scale = _previous_scale(target[previous],independent[previous])
    quote, event, quote_known = _quote_binding(stock,fact,cutoff)
    today = {key:raw[key][size:] for key in PRICE_KEYS+("volumes","amounts")}
    scale = _current_scale(stock,quote,independent[previous],today,previous_scale)
    mapped = dict(raw, adjustment="qfq")
    for key in PRICE_KEYS:
        mapped[key] = mapped_history[key].tolist() + [value*scale for value in today[key]]
    kline = _resample_30m(mapped)
    _require(kline["dates"] == dates and len(kline["dates"]) == original.get("bars"),
             "whole_original_30m_window_mismatch")
    produced = _time(clock() if clock is not None else datetime.now(CN))
    _require(produced >= fact and produced.date() == fact.date()
             and produced.time() < PRE_CLOSE_CUTOFF_TIME, "proof_outside_run_window")
    proof = {
        "schema":SCHEMA, "identity":identity.key, "as_of":fact.isoformat(), "previous":previous,
        "produced_at":produced.isoformat(),
        "file_ready_at_ns":ready_at_ns, "responses_known_at":known.isoformat(),
        "capture_sha256":document["sha256"], "capture_file_sha256":capture_file_sha256 or _digest(document),
        "response_sha256":hashes, "quote_event_at":event.isoformat(),
        "quote_known_at":quote_known.isoformat(), "quote_sha256":basis_sha256(quote),
        "canonical_sha256":basis_sha256(target), "daily_sha256":_daily_fingerprint(stock),
        "original_sha256":_kline_digest(source), "replacement_sha256":_kline_digest(kline),
        "current_scale":scale, "previous_raw":{key:independent[previous][key] for key in _PRICES},
    }
    proof["sha256"] = basis_sha256(proof)
    kline["minute_to_daily"] = proof
    return {"klines":kline,"proof":proof}


def verified_fallback_kline(stock, original, replacement, as_of, generated_at=None):
    """Fail closed on any changed provenance or final normalized array."""
    try:
        fact = _time(as_of)
        cutoff = fact.replace(hour=14, minute=45, second=0,microsecond=0)
        proof, kline = replacement["proof"], replacement["klines"]
        dates = kline["dates"]
        produced = _time(proof["produced_at"])
        if (proof["schema"] != SCHEMA or proof["as_of"] != fact.isoformat()
                or kline.get("minute_to_daily") != proof
                or produced < fact or produced.date() != fact.date() or produced.time() >= PRE_CLOSE_CUTOFF_TIME
                or (generated_at is not None and produced.replace(microsecond=0) > _time(generated_at))
                or proof["sha256"] != basis_sha256({k:v for k,v in proof.items() if k!="sha256"})
                or proof["identity"] != normalize_identity(stock).key
                or proof["identity"] != kline["identity_key"]
                or _epoch_ns(_time(proof["responses_known_at"])) > proof["file_ready_at_ns"]
                or proof["file_ready_at_ns"] > _epoch_ns(fact)
                or not _sina_pending(original,fact)
                or kline["source"] != SOURCE or kline["adjustment"] != "qfq"
                or len(dates) != original["bars"] or dates != original["klines"]["dates"]
                or proof["replacement_sha256"] != _kline_digest(kline)
                or proof["original_sha256"] != _kline_digest(original["klines"])
                or proof["daily_sha256"] != _daily_fingerprint(stock)):
            return None
        day = fact.date().isoformat()
        past = sorted({ts[:10] for ts in dates if ts[:10] < day})
        if not past or past[-1] != proof["previous"]:
            return None
        target = _canonical_rows(stock,past,fact,proof["previous"])
        quote,event,known = _quote_binding(stock,fact,cutoff)
        return kline if (
            proof["canonical_sha256"] == basis_sha256(target)
            and proof["quote_sha256"] == basis_sha256(quote)
            and proof["quote_event_at"] == event.isoformat()
            and proof["quote_known_at"] == known.isoformat()
            and len(proof["response_sha256"]) == len(_RESPONSE_MODES)
            and all(kline["finals"])
        ) else None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None


def analyzer_window_matches(value, kline):
    """Compare the price/volume arrays actually consumed by the analyzer."""
    return all(list(getattr(value,key,())) == kline[key] for key in _BAR_COLUMNS)


def comparison_daily_matches(daily, source):
    kline = source["klines"]
    return (normalize_identity(daily) == normalize_identity(source)
            and all(list(daily[key]) == kline[key] for key in ("dates",) + PRICE_KEYS))


def apply_observation_fallback(min30, targets, *, capture_dir, as_of, previous,
                               calendar_check, budget_remaining=None, clock=None):
    fact = _time(as_of)
    counts, exchanges, by_code = Counter(), {}, {}
    root = Path(capture_dir)
    for stock in targets:
        code = str(stock.get("code") or "")
        exchange = str(stock.get("exchange") or "unknown")
        reason = "verified"
        try:
            _require(budget_remaining is None or budget_remaining() > 0,"budget_exhausted")
            identity = normalize_identity(stock)
            original = min30.get(identity.code,{})
            _require(identity.exchange in ("SH","SZ") and _sina_pending(original,fact),
                     "original_not_pending_sina")
            path = root / ("stock-" + identity.exchange + identity.code + ".json")
            capture, ready, digest = read_observation_capture(path,fact)
            proposed = build_observation_fallback(stock,original,capture, ready_at_ns=ready,
                        capture_file_sha256=digest, as_of=fact, previous=previous,
                        calendar_check=calendar_check, clock=clock)
            _require(budget_remaining is None or budget_remaining() > 0,"budget_exhausted")
            original[FALLBACK_KEY] = proposed
        except FileNotFoundError:
            reason = "capture_missing"
        except OSError:
            reason = "capture_unreadable"
        except (TypeError, KeyError, IndexError, AttributeError):
            reason = "evidence_incomplete"
        except ValueError as exc:
            reason = str(exc).split(":")[0]
        counts[reason] += 1
        exchanges.setdefault(exchange,Counter())[reason] += 1
        by_code[code] = reason
    return {"target_count":len(targets),"reasons":dict(counts),
            "by_exchange":{key:dict(value) for key,value in exchanges.items()},
            "by_code":by_code}
