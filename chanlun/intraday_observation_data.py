"""Strict 14:45 inputs for the independent observation job.

No canonical writes, quote fallback, current-day final daily reference, or
guessed suspension/factor is permitted here. Provider captures stay separate
from the existing daily and pre-close acquisition paths.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
import time as elapsed_clock
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .identity import normalize_identity

CN = timezone(timedelta(hours=8))
PRICE_KEYS = ("opens", "highs", "lows", "closes")
ARRAY_KEYS = ("dates",) + PRICE_KEYS + ("volumes", "amounts", "amount_available", "finals")
MINUTE_COUNT = 656  # 40 complete past sessions plus today's closed buckets.
MINIMUM_COVERAGE = 0.90


def _dt(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return result.replace(tzinfo=CN) if result.tzinfo is None else result.astimezone(CN)


def _cutoff(value):
    result = _dt(value)
    if (result.hour, result.minute, result.second, result.microsecond) != (14, 45, 0, 0):
        raise ValueError("invalid_observation_cutoff")
    return result


def _number(value, field):
    if value is None or isinstance(value, bool):
        raise ValueError("invalid_" + field)
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_" + field) from None
    if not math.isfinite(result):
        raise ValueError("invalid_" + field)
    return result


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=_jsonable,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _freeze_capture(path, value):
    """Serialize once, then expose only a complete create-once capture.

    json.dump streams thousands of Python writes per provider response. That
    contends with all acquisition workers; dumps uses the C encoder instead.
    Keep its original bytes and never replace an existing capture.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    material = json.dumps(_jsonable(value), ensure_ascii=False, allow_nan=False).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(material)
        try:
            os.link(temporary, str(path))
        except FileExistsError:
            if path.read_bytes() != material:
                raise FileExistsError("immutable source capture already differs")
    finally:
        os.unlink(temporary)


def _reserve_request_phase(path, value, clock):
    """Durably reserve a phase once; missing results after restart are unknown.

    One fsynced cohort intent avoids a per-stock fsync bottleneck. All listed
    identities are conservatively dispatching until a complete capture exists.
    """
    from .intraday_observation_delivery import freeze_json
    path = Path(path)
    expected = dict(value, state="dispatching")
    def validate():
        saved = json.loads(path.read_text())
        if any(saved.get(key) != item for key, item in expected.items()):
            raise ValueError("capture_phase_identity_conflict")
    if path.exists():
        validate()
        return False
    try:
        freeze_json(path, dict(expected, started_at=_dt(clock()).isoformat()))
    except FileExistsError:
        validate()
        return False
    return True


def _expected_times(day, scale=15, cutoff=None):
    times = []
    for start in (570, 780):
        for minute in range(start + scale, start + 121, scale):
            stamp = "{} {:02}:{:02}:00".format(day, minute // 60, minute % 60)
            if cutoff is None or _dt(stamp) <= cutoff:
                times.append(stamp)
    return times


def parse_eastmoney_minutes(response, identity, *, adjustment, cutoff, fetched_at):
    """Parse the known Eastmoney schema and discard later buckets first."""
    identity = normalize_identity(identity)
    cutoff = _cutoff(cutoff)
    observed = _dt(fetched_at)
    if observed <= cutoff or observed.date() != cutoff.date():
        raise ValueError("cutoff_not_observed")
    if adjustment not in ("raw", "qfq"):
        raise ValueError("invalid_adjustment")
    data = response.get("data") if isinstance(response, dict) else None
    market = "1" if identity.exchange == "SH" else "0"
    if not isinstance(data, dict) or str(data.get("code")) != identity.code or str(data.get("market")) != market:
        raise ValueError("minute_identity_mismatch")
    lines = data.get("klines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("empty_minute_response")
    output = {key: [] for key in ARRAY_KEYS}
    previous = None
    expected_by_day = {}
    for line in lines:
        fields = str(line).split(",")
        try:
            stamp = _dt(fields[0])
        except (TypeError, ValueError):
            raise ValueError("invalid_minute_timestamp") from None
        if previous is not None and stamp <= previous:
            raise ValueError("duplicate_or_unsorted_minute")
        previous = stamp
        if stamp > cutoff:
            continue
        text = stamp.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        day = stamp.date().isoformat()
        if day not in expected_by_day:
            expected_by_day[day] = set(_expected_times(day))
        if text not in expected_by_day[day] or stamp.second or stamp.microsecond:
            raise ValueError("invalid_minute_bucket")
        if len(fields) < 7:
            raise ValueError("missing_minute_amount")
        o, c, h, l, v, a = [_number(x, name) for x, name in zip(fields[1:7],
            ("open", "close", "high", "low", "volume", "amount"))]
        if not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0 or a < 0:
            raise ValueError("invalid_minute_ohlcva")
        if (v == 0) != (a == 0):
            raise ValueError("amount_volume_conflict")
        if adjustment == "raw" and identity.asset_type == "stock" and v > 0:
            average = a / (v * 100)
            if not l * .99 - .01 <= average <= h * 1.01 + .01:
                raise ValueError("amount_volume_price_conflict")
        for key, value in zip(ARRAY_KEYS, (text, o, h, l, c, v, a, True, True)):
            output[key].append(value)
    if not output["dates"]:
        raise ValueError("empty_cutoff_window")
    output.update(source="eastmoney_cutoff", adjustment=adjustment,
        identity_key=identity.key, code=identity.code, exchange=identity.exchange,
        asset_type=identity.asset_type, interval="15m", fetched_at=observed.isoformat(),
        as_of=cutoff.isoformat(), volume_unit="hands" if identity.asset_type == "stock" else "unknown",
        volume_raw_unit="hands" if identity.asset_type == "stock" else "unknown",
        volume_source="eastmoney", amount_unit="CNY", amount_source="eastmoney",
        schema="eastmoney_cutoff_15m_v1", source_response_sha256=_digest(response))
    return output


def parse_eastmoney_daily(response, identity, *, adjustment, previous_trade_date):
    identity = normalize_identity(identity)
    data = response.get("data") if isinstance(response, dict) else None
    market = "1" if identity.exchange == "SH" else "0"
    if not isinstance(data, dict) or str(data.get("code")) != identity.code or str(data.get("market")) != market:
        raise ValueError("daily_identity_mismatch")
    rows = []
    previous = ""
    for line in data.get("klines") or []:
        fields = str(line).split(",")
        if len(fields) < 7:
            raise ValueError("missing_daily_amount")
        date = datetime.strptime(fields[0], "%Y-%m-%d").date().isoformat()
        if date > previous_trade_date:
            raise ValueError("daily_after_reference")
        if date <= previous:
            raise ValueError("duplicate_or_unsorted_daily")
        previous = date
        o, c, h, l, v, a = [_number(x, name) for x, name in zip(fields[1:7],
            ("open", "close", "high", "low", "volume", "amount"))]
        if not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0 or a < 0:
            raise ValueError("invalid_daily_ohlcva")
        if (v == 0) != (a == 0):
            raise ValueError("daily_amount_volume_conflict")
        if adjustment == "raw" and identity.asset_type == "stock" and v > 0:
            if not l * .99 - .01 <= a / (v * 100) <= h * 1.01 + .01:
                raise ValueError("daily_amount_volume_price_conflict")
        rows.append(dict(ts=date, open=o, high=h, low=l, close=c, volume=v, amount=a,
            is_final=True, adjustment=adjustment, amount_available=True,
            volume_unit="hands" if identity.asset_type == "stock" else "unknown",
            volume_raw_unit="hands" if identity.asset_type == "stock" else "unknown",
            volume_source="eastmoney", amount_unit="CNY", amount_source="eastmoney",
            source_batch="eastmoney_observation_daily:" + adjustment))
    if not rows or rows[-1]["ts"] != previous_trade_date:
        raise ValueError("stale_daily_reference")
    return rows


class SourceRateLimited(RuntimeError):
    pass


class SourceDispatchUncertain(RuntimeError):
    pass


def fetch_eastmoney_cutoff_pair(identity, *, cutoff, previous_trade_date, deadline,
        session=None, count=MINUTE_COUNT, timeout=5.0, clock=None, stop_event=None):
    """Four logical requests and at most one transient retry per identity."""
    import requests
    identity = normalize_identity(identity)
    cutoff = _cutoff(cutoff)
    clock = clock or (lambda: datetime.now(CN))
    deadline = _dt(deadline)
    current = _dt(clock())
    if current.date() != cutoff.date():
        raise ValueError("live_capture_date_mismatch")
    if current <= cutoff:
        raise ValueError("cutoff_not_observed")
    owned = session is None
    if owned:
        session = requests.Session()
        # The existing eastmoney transport is direct. Do not inherit a desktop
        # proxy which would change this independently audited provider path.
        session.trust_env = False
    pair = {"source_evidence": []}
    retry_used, request_count = False, 0
    request_failures = []
    try:
        for interval, adjustment in (("15", "raw"), ("15", "qfq"), ("101", "raw"), ("101", "qfq")):
            remaining = (deadline - _dt(clock())).total_seconds()
            if remaining <= 0 or (stop_event is not None and stop_event.is_set()):
                raise TimeoutError("observation_acquisition_deadline")
            params = {"secid": ("1" if identity.exchange == "SH" else "0") + "." + identity.code,
                "ut": "7eea3edcaed734bea9cbfc24409ed989", "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": interval, "fqt": "0" if adjustment == "raw" else "1",
                "end": (previous_trade_date if interval == "101" else cutoff.date().isoformat()).replace("-", ""),
                "lmt": str(120 if interval == "101" else max(MINUTE_COUNT, int(count)))}
            attempts = 0
            while True:
                remaining = (deadline - _dt(clock())).total_seconds()
                if remaining <= 0 or (stop_event is not None and stop_event.is_set()):
                    raise TimeoutError("observation_acquisition_deadline")
                attempts += 1
                request_count += 1
                try:
                    response = session.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                        params=params, timeout=min(float(timeout), 5.0, remaining), allow_redirects=False)
                    break
                except (requests.ConnectionError, requests.Timeout) as exc:
                    request_failures.append(dict(interval=interval, adjustment=adjustment,
                        attempt=attempts, error_type=type(exc).__name__,
                        observed_at=_dt(clock()).isoformat()))
                    if isinstance(exc, requests.exceptions.SSLError) or retry_used:
                        raise
                    retry_used = True
                    remaining = (deadline - _dt(clock())).total_seconds()
                    if remaining <= 0:
                        raise TimeoutError("observation_acquisition_deadline") from exc
                    elapsed_clock.sleep(min(.05, remaining))
            try:
                if response.status_code in (429, 456):
                    if stop_event is not None:
                        stop_event.set()
                    raise SourceRateLimited("eastmoney_rate_limited")
                if not 200 <= response.status_code < 300:
                    raise ValueError("eastmoney_http_{}".format(response.status_code))
                decoded = response.json()
            finally:
                response.close()
            fetched_at = _dt(clock())
            if fetched_at > deadline:
                raise TimeoutError("observation_acquisition_deadline")
            if interval == "15":
                pair[adjustment] = parse_eastmoney_minutes(decoded, identity, adjustment=adjustment,
                    cutoff=cutoff, fetched_at=fetched_at)
            else:
                pair["raw_daily" if adjustment == "raw" else "daily"] = parse_eastmoney_daily(
                    decoded, identity, adjustment=adjustment, previous_trade_date=previous_trade_date)
            pair["source_evidence"].append(dict(params=params, fetched_at=fetched_at.isoformat(),
                response_sha256=_digest(decoded), response=decoded, attempts=attempts))
        raw_rows, qfq_rows = pair["raw_daily"], pair["daily"]
        if [r["ts"] for r in raw_rows] != [r["ts"] for r in qfq_rows]:
            raise ValueError("daily_pair_dates_conflict")
        if any(not math.isclose(a[k], b[k], rel_tol=1e-8, abs_tol=.01)
               for a,b in zip(raw_rows,qfq_rows) for k in ("volume", "amount")):
            raise ValueError("daily_pair_quantity_conflict")
        if request_failures:
            pair["request_failures"] = request_failures
        pair["request_count"] = request_count
        return pair
    except Exception as exc:
        exc.observation_request_evidence = dict(request_count=request_count,
            failures=request_failures, interval=interval, adjustment=adjustment,
            final_error_type=type(exc).__name__,
            retryable_transport_failure=(
                isinstance(exc, (requests.ConnectionError, requests.Timeout))
                and not isinstance(exc, requests.exceptions.SSLError)
                and _dt(clock()) < deadline),
        )
        raise
    finally:
        if owned:
            session.close()


def validate_daily_history(rows, *, previous_trade_date, calendar_check, minimum_bars=60, require_quantity=True):
    if len(rows) < minimum_bars:
        raise ValueError("insufficient_daily_history")
    dates = [str(row["ts"])[:10] for row in rows]
    if dates != sorted(set(dates)):
        raise ValueError("duplicate_or_unsorted_daily")
    if dates[-1] != previous_trade_date:
        raise ValueError("history_not_previous")
    expected = []
    current = datetime.fromisoformat(dates[0]).date()
    finish = datetime.fromisoformat(previous_trade_date).date()
    while current <= finish:
        status = calendar_check(current.isoformat())
        if status is None:
            raise ValueError("calendar_unavailable")
        if status:
            expected.append(current.isoformat())
        current += timedelta(days=1)
    if dates != expected:
        raise ValueError("daily_gap_pending")
    for row in rows:
        if row.get("is_final") not in (True, 1):
            raise ValueError("daily_nonfinal_pending")
        if row.get("adjustment") != "qfq" or not row.get("source_batch"):
            raise ValueError("daily_basis_unverified")
        o, h, l, c = [_number(row.get(k), "daily_price") for k in ("open", "high", "low", "close")]
        if not 0 < l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("invalid_daily_ohlc")
        if row.get("volume") is not None and row.get("amount") is not None:
            volume = _number(row["volume"], "daily_volume")
            amount = _number(row["amount"], "daily_amount")
            if (volume == 0) != (amount == 0):
                raise ValueError("daily_amount_volume_conflict")
        if require_quantity:
            if (row.get("volume_unit") != "hands" or not row.get("volume_source")
                or row.get("amount_unit") != "CNY" or not row.get("amount_source")
                or row.get("amount_available") not in (True, 1)):
                raise ValueError("daily_quantity_unavailable")
            if _number(row.get("volume"), "daily_volume") < 0 or _number(row.get("amount"), "daily_amount") <= 0:
                raise ValueError("invalid_daily_quantity")


def _slice(payload, indices):
    output = {key: copy.deepcopy(value) for key,value in payload.items() if key not in ARRAY_KEYS}
    for key in ARRAY_KEYS:
        output[key] = [payload[key][i] for i in indices]
    return output


def _aggregate(payload, indices):
    return dict(open=payload["opens"][indices[0]], high=max(payload["highs"][i] for i in indices),
        low=min(payload["lows"][i] for i in indices), close=payload["closes"][indices[-1]],
        volume=sum(payload["volumes"][i] for i in indices), amount=sum(payload["amounts"][i] for i in indices))


def _verify_pair(pair, identity, rows, cutoff, previous_trade_date, calendar_check):
    raw, qfq = pair["raw"], copy.deepcopy(pair["qfq"])
    day = cutoff.date().isoformat()
    for name, payload in (("raw", raw), ("qfq", qfq)):
        if (payload.get("identity_key") != identity.key or payload.get("adjustment") != name
            or payload.get("schema") != "eastmoney_cutoff_15m_v1" or payload.get("as_of") != cutoff.isoformat()):
            raise ValueError("pair_identity_or_basis_mismatch")
        size = len(payload.get("dates", []))
        if any(len(payload.get(k, [])) != size for k in ARRAY_KEYS):
            raise ValueError("pair_array_length_mismatch")
        if any(_dt(ts) > cutoff for ts in payload["dates"]) or not all(x is True for x in payload["finals"]):
            raise ValueError("pair_unclosed_or_future")
    if raw["dates"] != qfq["dates"]:
        raise ValueError("pair_timestamp_conflict")
    for key in ("volumes", "amounts"):
        if any(not math.isclose(a, b, rel_tol=1e-8, abs_tol=.01) for a, b in zip(raw[key], qfq[key])):
            raise ValueError("pair_quantity_conflict")
    groups = {}
    for i, stamp in enumerate(qfq["dates"]):
        groups.setdefault(stamp[:10], []).append(i)
    if [qfq["dates"][i] for i in groups.get(day, [])] != _expected_times(day, cutoff=cutoff):
        raise ValueError("incomplete_cutoff_day")
    if previous_trade_date not in groups:
        raise ValueError("missing_previous_minute_day")
    # The request's leading partial session can be discarded, never an internal hole.
    first = min(groups)
    if first != day and [qfq["dates"][i] for i in groups[first]] != _expected_times(first):
        del groups[first]
    history = {str(row["ts"])[:10]: row for row in rows}
    raw_history = {str(row["ts"])[:10]: row for row in pair.get("raw_daily", [])}
    if raw_history:
        prior_raw, prior_qfq = raw_history.get(previous_trade_date), history.get(previous_trade_date)
        if not prior_raw or not prior_qfq or any(abs(prior_raw[k] - prior_qfq[k]) > .011
                for k in ("open", "high", "low", "close")):
            # A same-day corporate action needs an independently evidenced new
            # anchor. Never carry yesterday's factor through it speculatively.
            raise ValueError("current_day_basis_unverified")
    first = min(groups)
    required_days = [d for d in history if first <= d <= previous_trade_date] + [day]
    if sorted(groups) != sorted(required_days):
        raise ValueError("minute_day_gap")
    for date, indices in groups.items():
        if calendar_check(date) is not True:
            raise ValueError("minute_calendar_conflict")
        expected = _expected_times(date, cutoff=cutoff if date == day else None)
        if [qfq["dates"][i] for i in indices] != expected:
            raise ValueError("incomplete_minute_day:" + date)
        # One provider's named qfq is insufficient. Every complete historical
        # session must independently match the frozen canonical daily scale.
        if date != day:
            if raw_history:
                raw_day = raw_history.get(date)
                aggregate = _aggregate(raw, indices)
                if not raw_day or any(abs(aggregate[k] - float(raw_day[k])) > .011
                        for k in ("open", "high", "low", "close")):
                    raise ValueError("historical_raw_conflict:" + date)
                x = [raw_day[k] for k in ("open", "high", "low", "close")]
                y = [history[date][k] for k in ("open", "high", "low", "close")]
                scale, offset = _affine(x, y)
                for key in PRICE_KEYS:
                    for i in indices:
                        qfq[key][i] = raw[key][i] * scale + offset
            aggregate = _aggregate(qfq, indices)
            if any(abs(aggregate[k] - float(history[date][k])) > .011 for k in ("open", "high", "low", "close")):
                raise ValueError("historical_basis_conflict:" + date)
        elif any(abs(raw[k][i] - qfq[k][i]) > .011 for k in PRICE_KEYS for i in indices):
            raise ValueError("current_day_basis_unverified")
        x = [raw[k][i] for k in PRICE_KEYS for i in indices]
        y = [qfq[k][i] for k in PRICE_KEYS for i in indices]
        if max(abs(a-b) for a,b in zip(x,y)) > .011:
            low, high = min(range(len(x)), key=x.__getitem__), max(range(len(x)), key=x.__getitem__)
            if x[high] - x[low] <= .011:
                raise ValueError("indeterminate_pair_basis")
            scale = (y[high] - y[low]) / (x[high] - x[low])
            offset = y[low] - scale * x[low]
            if scale <= 0 or max(abs(scale*a+offset-b) for a,b in zip(x,y)) > .011:
                raise ValueError("non_affine_pair_basis")
    keep = [i for date in sorted(groups) for i in groups[date]]
    return _slice(qfq, keep), _aggregate(qfq, groups[day]), _aggregate(raw, groups[day])


def _affine(x, y):
    if max(abs(a-b) for a,b in zip(x,y)) <= .011:
        return 1.0, 0.0
    low, high = min(range(len(x)), key=x.__getitem__), max(range(len(x)), key=x.__getitem__)
    if x[high] - x[low] <= .011:
        raise ValueError("indeterminate_pair_basis")
    scale = (y[high] - y[low]) / (x[high] - x[low])
    offset = y[low] - scale * x[low]
    if scale <= 0 or max(abs(scale*a+offset-b) for a,b in zip(x,y)) > .011:
        raise ValueError("non_affine_pair_basis")
    return scale, offset


def _resample_30m(minutes):
    output = {key: [] for key in ARRAY_KEYS}
    by_stamp = {stamp: i for i, stamp in enumerate(minutes["dates"])}
    for day in sorted({d[:10] for d in by_stamp}):
        for stamp in _expected_times(day, 30):
            earlier = (_dt(stamp) - timedelta(minutes=15)).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            if stamp not in by_stamp or earlier not in by_stamp:
                continue
            bar = _aggregate(minutes, [by_stamp[earlier], by_stamp[stamp]])
            for key, value in zip(ARRAY_KEYS, (stamp, bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"], bar["amount"], True, True)):
                output[key].append(value)
    output.update({k: copy.deepcopy(v) for k,v in minutes.items() if k not in ARRAY_KEYS})
    output["interval"] = "30m"
    return output


def build_cutoff_stock(candidate, history_rows, pair, *, cutoff, previous_trade_date, calendar_check, minimum_bars=60):
    from .universe_builder import _rows_to_kline, _feature_scores
    identity = normalize_identity(candidate)
    cutoff = _cutoff(cutoff)
    validate_daily_history(history_rows, previous_trade_date=previous_trade_date,
        calendar_check=calendar_check, minimum_bars=minimum_bars, require_quantity=identity.asset_type == "stock")
    minutes, today, raw_today = _verify_pair(pair, identity, history_rows, cutoff, previous_trade_date, calendar_check)
    if len(minutes["dates"]) < 220:
        raise ValueError("insufficient_cutoff_minute_history")
    today.update(ts=cutoff.date().isoformat(), is_final=False, adjustment="qfq",
        volume_unit=minutes["volume_unit"], volume_raw_unit=minutes["volume_raw_unit"],
        volume_source="eastmoney", amount_unit="CNY", amount_source="eastmoney",
        amount_available=True, source_batch="eastmoney_cutoff_15m_v1")
    combined = [dict(row) for row in history_rows] + [today]
    daily = _jsonable(_rows_to_kline(combined[-120:]))
    daily.update(finals=[bool(row["is_final"]) for row in combined[-120:]],
        as_of=cutoff.isoformat(), source="formal_history+eastmoney_cutoff_15m", bar_state="intraday")
    daily["_data_status"].update(daily="verified", is_final=False, as_of=cutoff.isoformat())
    # Legacy upgrade code calls this field factor_vs_raw. Both arrays supplied
    # here are already independently proven to be the SAME qfq scale.
    history_hash, pair_hash = _digest(history_rows), _digest(pair)
    basis = dict(adjustment="qfq", factor_vs_raw=1.0, minute_to_daily_factor=1.0,
        basis_status="verified_same_qfq_window", reference_date=previous_trade_date,
        adjusted_current_price=today["close"], raw_current_price=raw_today["close"],
        historical_daily_sha256=history_hash, minute_pair_sha256=pair_hash)
    minutes.update(price_basis=copy.deepcopy(basis))
    min30 = _resample_30m(minutes)
    minutes = _slice(minutes, list(range(max(0, len(minutes["dates"]) - 220), len(minutes["dates"]))))
    min30 = _slice(min30, list(range(max(0, len(min30["dates"]) - 80), len(min30["dates"]))))
    output = copy.deepcopy(candidate)
    output.update(identity_key=identity.key, code=identity.code, exchange=identity.exchange,
        asset_type=identity.asset_type, klines=daily, data_status=daily["_data_status"],
        as_of=cutoff.isoformat(), is_final=False, bar_state="intraday", status="available",
        latest_date=today["ts"], price_basis=basis, close=today["close"],
        change_pct=(today["close"] / float(history_rows[-1]["close"]) - 1) * 100,
        amount=today["amount"], amount_available=True, amount_unit="CNY", amount_source="eastmoney",
        volume=today["volume"], volume_unit=minutes["volume_unit"], volume_source="eastmoney",
        cutoff_minutes={"15m": minutes, "30m": min30},
        cutoff_evidence={"cutoff": cutoff.isoformat(), "today_buckets": 15,
            "previous_trade_date": previous_trade_date, "current_daily_final_used": False,
            "history_sha256": history_hash, "pair_sha256": pair_hash})
    if identity.asset_type == "stock":
        output.update(_feature_scores(combined[-120:]))
    return _jsonable(output)


INDEX_NAMES = {"上证指数": "000001", "深证成指": "399001", "创业板指": "399006",
    "科创50": "000688", "沪深300": "000300", "中证500": "000905"}


def _calendar_reader(store):
    from .preclose_schedule import _SSE_2026_CLOSED
    entries = {}
    for row in store.connection.execute("SELECT exchange,trade_date,is_open FROM trade_calendar WHERE exchange IN ('SH','SZ')"):
        entries.setdefault(row["trade_date"], {})[row["exchange"]] = row["is_open"]

    def check(day):
        date = datetime.fromisoformat(day).date()
        flags = entries.get(day)
        if flags:
            if set(flags) != {"SH", "SZ"} or len(set(flags.values())) != 1 or flags["SH"] not in (0, 1):
                return None
            return bool(flags["SH"]) if date.weekday() < 5 else False
        if date.weekday() >= 5:
            return False
        if date.year != 2026:
            return None
        return day not in _SSE_2026_CLOSED
    return check


def _load_cohort(store, cutoff):
    from config import MIN_LISTED_DAYS
    instruments = store.list_instruments(asset_type="stock")
    metadata = store.query_stock_meta_many([int(row["instrument_id"]) for row in instruments], as_of=cutoff)
    candidates, excluded = [], []
    for instrument in instruments:
        reason = ""
        try:
            identity = normalize_identity(instrument)
        except (ValueError, TypeError):
            excluded.append(dict(code=str(instrument.get("code", "")), reason="invalid_identity"))
            continue
        meta = metadata.get(int(instrument["instrument_id"]))
        if not meta:
            reason = "missing_metadata"
        elif meta.get("risk_status") == "conflict":
            reason = "risk_evidence_conflict"
        elif (meta.get("is_st") is True or meta.get("delisting_risk") is True
              or "ST" in str(meta.get("name", "")).upper() or "退" in str(meta.get("name", ""))):
            reason = "st_or_delisting"
        else:
            try:
                if int(meta.get("listed_days")) < MIN_LISTED_DAYS:
                    reason = "listed_days"
            except (TypeError, ValueError):
                reason = "listing_metadata_unavailable"
        if reason:
            excluded.append(dict(code=identity.code, identity_key=identity.key, reason=reason))
            continue
        candidates.append(dict(code=identity.code, exchange=identity.exchange, asset_type="stock",
            identity_key=identity.key, name=meta.get("name") or identity.code,
            stock_meta_asof=copy.deepcopy(meta), industry=meta.get("industry") or "",
            sector=meta.get("industry") or "", market_cap=meta.get("market_cap"),
            circulating_market_cap=meta.get("circulating_market_cap"),
            float_market_cap=meta.get("float_market_cap", meta.get("circulating_market_cap"))))
    return sorted(candidates, key=lambda row: row["identity_key"]), dict(
        instrument_count=len(instruments), eligible_metadata_count=len(candidates), excluded=excluded,
        rule="canonical stocks with historical listing/risk metadata; no prior-day liquidity or retrieval filter",
        historic_daily_source="independent bounded raw/qfq snapshots ending previous trading day")


def _minute_row(stock, interval, cutoff):
    minutes = stock["cutoff_minutes"][interval]
    return dict(code=stock["code"], name=stock["name"], asset_type="stock", exchange=stock["exchange"],
        identity_key=stock["identity_key"], price_basis=copy.deepcopy(stock["price_basis"]),
        klines=minutes, input_evidence=dict(interval=interval, status="verified", stale=False,
            is_final=True, latest_date=cutoff[:10], latest_ts=minutes["dates"][-1], as_of=cutoff,
            bars=len(minutes["dates"]), source="eastmoney_cutoff", adjustment="qfq"))


def acquire_observation_payload(formal_market_db, trade_date, *, deadline, snapshot_dir=None,
        max_workers=20, pair_fetcher=None, clock=None, timings=None):
    """Read-only full metadata cohort, then bounded cutoff acquisition/retrieval.

    The caller owns the date lock and immutable final payload. Individual source
    captures here are create-once, including failures, so interrupted retries
    cannot silently replace one stock's batch with a newer provider response.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Event, local
    from .market_history_store import MarketHistoryStore
    from .market_close_snapshot import _previous_trade_date
    from .universe_builder import build_candidate_universe, UniverseConfig
    from config import (MIN_DAILY_AMOUNT, FULL_A_FINAL_LIMIT, FULL_A_NO_OVERLAY_LOW_QUOTA,
        FULL_A_NO_OVERLAY_TREND_QUOTA, FULL_A_NO_OVERLAY_NEUTRAL_QUOTA)
    started = elapsed_clock.monotonic()
    cutoff = _cutoff(str(trade_date) + "T14:45:00+08:00")
    clock = clock or (lambda: datetime.now(CN))
    if _dt(clock()).date() != cutoff.date():
        raise ValueError("live_capture_date_mismatch")
    if _dt(clock()) <= cutoff:
        raise ValueError("cutoff_not_observed")
    deadline = _dt(deadline)
    with MarketHistoryStore(formal_market_db, readonly=True) as store:
        calendar_check = _calendar_reader(store)
        if calendar_check(trade_date) is not True:
            raise ValueError("observation_calendar_unavailable_or_closed")
        previous = _previous_trade_date(trade_date, store)
        if not previous:
            raise ValueError("previous_trade_date_unavailable")
        candidates, cohort = _load_cohort(store, cutoff.isoformat())
    index_candidates = [dict(code=code, exchange="SZ" if code.startswith("399") else "SH",
        asset_type="index", name=name) for name,code in INDEX_NAMES.items()]
    source_dir = Path(snapshot_dir) if snapshot_dir is not None else None
    if source_dir is not None:
        source_dir.mkdir(parents=True, exist_ok=True)
    thread_state, sessions = local(), []
    def fetch_default(identity, **kwargs):
        session = getattr(thread_state, "session", None)
        if session is None:
            import requests
            session = requests.Session()
            session.trust_env = False
            thread_state.session = session
            sessions.append(session)
        return fetch_eastmoney_cutoff_pair(identity, session=session, **kwargs)
    fetcher = pair_fetcher or fetch_default
    stop = Event()
    # A fresh process must retain an earlier rate-limit decision before it
    # sends anything. Only capture files are scanned, never request intents.
    if pair_fetcher is None and source_dir is not None:
        for directory in (source_dir, source_dir / "recovery-1"):
            for path in directory.glob("*.json"):
                try:
                    saved = json.loads(path.read_text())
                    result = saved.get("result") or {}
                    if (result.get("reason") == "eastmoney_rate_limited"
                            and saved.get("cutoff") == cutoff.isoformat()
                            and saved.get("sha256") == _digest(result)):
                        stop.set()
                except (OSError, ValueError, TypeError, AttributeError):
                    # The ordinary per-identity reader rejects corrupt input;
                    # it never becomes an eligible transport recovery.
                    continue
    phase_reserved_here = {"primary": True, "recovery-1": False}
    if pair_fetcher is None and source_dir is not None:
        primary_budget = dict(cutoff=cutoff.isoformat(), previous_trade_date=previous,
            cohort_sha256=_digest(candidates), maximum_requests_per_identity=5,
            identities=sorted(normalize_identity(row).key for row in index_candidates + candidates))
        phase_reserved_here["primary"] = (not stop.is_set() and _reserve_request_phase(
            source_dir / "_requests" / "primary.json", primary_budget, clock))

    def source_details(result):
        evidence = result.get("request_evidence") or {}
        count = evidence.get("request_count") if result.get("reason") else result["pair"].get("request_count")
        return dict(request_count=count if type(count) is int and count >= 0 else None,
            retryable_transport_failure=(result.get("reason") is not None
                and evidence.get("retryable_transport_failure") is True))

    def acquire(candidate, recovery=False):
        identity = normalize_identity(candidate)
        name = identity.asset_type + "-" + identity.exchange + identity.code + ".json"
        directory = source_dir / "recovery-1" if recovery and source_dir else source_dir
        path = directory / name if directory else None
        if path is not None and path.exists():
            record = json.loads(path.read_text())
            if record.get("cutoff") != cutoff.isoformat() or record.get("identity") != identity.key:
                raise ValueError("capture_identity_conflict")
            if record.get("sha256") != _digest(record.get("result")):
                raise ValueError("capture_hash_conflict")
            result = record["result"]
            if result.get("reason"):
                if result["reason"] == "eastmoney_rate_limited":
                    stop.set()
                return candidate, None, result["reason"], source_details(result)
            pair = result["pair"]
        else:
            try:
                if stop.is_set() or _dt(clock()) >= deadline:
                    raise TimeoutError("observation_acquisition_deadline")
                if pair_fetcher is None and source_dir is not None:
                    if not phase_reserved_here["recovery-1" if recovery else "primary"]:
                        raise SourceDispatchUncertain(
                            "recovery_dispatch_uncertain" if recovery else "capture_dispatch_uncertain")
                pair = fetcher(identity, cutoff=cutoff.isoformat(), previous_trade_date=previous,
                    deadline=deadline, clock=clock, stop_event=stop)
                result = {"pair": pair}
            except Exception as exc:
                if isinstance(exc, SourceRateLimited):
                    stop.set()
                result = {"reason": str(exc)[:160] or type(exc).__name__}
                if getattr(exc, "observation_request_evidence", None):
                    result["request_evidence"] = exc.observation_request_evidence
                pair = None
            if path is not None:
                record = dict(cutoff=cutoff.isoformat(), identity=identity.key,
                    sha256=_digest(result), result=result)
                _freeze_capture(path, record)
            if pair is None:
                return candidate, None, result["reason"], source_details(result)
        try:
            history = pair.get("daily")
            if not history or not pair.get("raw_daily"):
                raise ValueError("missing_independent_daily_reference")
            row = build_cutoff_stock(candidate, history, pair, cutoff=cutoff.isoformat(),
                previous_trade_date=previous, calendar_check=calendar_check)
            return candidate, row, "", source_details(result)
        except (ValueError, TypeError, KeyError) as exc:
            details = source_details(result)
            details["retryable_transport_failure"] = False
            return candidate, None, str(exc)[:160] or type(exc).__name__, details

    stocks, indices, failure_map = [], {}, {}
    recovery_candidates, first_details, recovery_details = [], {}, {}
    recovery_diagnostics = None
    def identity_key(candidate):
        return (candidate["asset_type"], candidate["exchange"], candidate["code"])
    def consume(futures, *, recovery=False):
        for future in as_completed(futures):
            candidate = futures[future]
            key = identity_key(candidate)
            try:
                _, row, reason, details = future.result()
            except Exception as exc:
                row, reason, details = None, str(exc)[:160] or type(exc).__name__, {}
            (recovery_details if recovery else first_details)[key] = details
            if row is None:
                failure_map[key] = dict(code=candidate["code"], asset_type=candidate["asset_type"], reason=reason)
                if not recovery and details.get("retryable_transport_failure") is True:
                    recovery_candidates.append(candidate)
            else:
                failure_map.pop(key, None)
                if candidate["asset_type"] == "index":
                    indices[candidate["name"]] = row
                else:
                    stocks.append(row)
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(20, int(max_workers)))) as executor:
            futures = {executor.submit(acquire, row): row for row in index_candidates + candidates}
            consume(futures)
            # Foundation gaps cannot be repaired by asking the quote provider
            # again. Recovery has its own finite namespace and no third wave.
            missing_foundation = sum(row["reason"] not in ("st_or_delisting", "listed_days")
                for row in cohort["excluded"])
            foundation_ready = bool(candidates) and len(candidates) / (len(candidates) + missing_foundation) >= MINIMUM_COVERAGE
            provider_incomplete = (not candidates or len(stocks) / len(candidates) < MINIMUM_COVERAGE
                or "上证指数" not in indices)
            recovery_budget_path = source_dir / "_requests" / "recovery-1.json" if source_dir else None
            existing_recovery = recovery_budget_path is not None and recovery_budget_path.exists()
            fresh_recovery_allowed = (not stop.is_set() and
                (deadline - _dt(clock())).total_seconds() >= 60)
            if (pair_fetcher is None and source_dir is not None and recovery_candidates
                    and foundation_ready and provider_incomplete
                    and (existing_recovery or fresh_recovery_allowed)):
                recovery_candidates.sort(key=identity_key)
                budget = dict(cutoff=cutoff.isoformat(), previous_trade_date=previous,
                    cohort_sha256=_digest(candidates), maximum_requests_per_identity=10,
                    identities=[normalize_identity(row).key for row in recovery_candidates])
                phase_reserved_here["recovery-1"] = _reserve_request_phase(recovery_budget_path, budget, clock)
                recovery_diagnostics = dict(attempted=False, target_count=len(recovery_candidates),
                    recovered=0, maximum_rounds=1, cooldown_seconds=2.0)
                needs_dispatch = phase_reserved_here["recovery-1"]
                if needs_dispatch:
                    elapsed_clock.sleep(2.0)
                if not needs_dispatch or (not stop.is_set() and _dt(clock()) < deadline):
                    recovery_diagnostics["attempted"] = True
                    futures = {executor.submit(acquire, row, True): row for row in recovery_candidates}
                    consume(futures, recovery=True)
                    recovery_diagnostics["recovered"] = sum(identity_key(row) not in failure_map for row in recovery_candidates)
                else:
                    recovery_diagnostics["status"] = "deadline_exceeded"
    finally:
        # Each session belongs to one finite worker. No global sessions or
        # refresh threads survive a completed or failed acquisition.
        cleanup_error = None
        for session in sessions:
            try:
                session.close()
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            raise RuntimeError("observation_transport_cleanup_failed") from cleanup_error
    collection_finished = elapsed_clock.monotonic()
    failures = list(failure_map.values())
    stocks.sort(key=lambda row: row["identity_key"])
    failures.sort(key=lambda row: (row["asset_type"], row["code"]))
    stock_failures = [r for r in failures if r["asset_type"] == "stock"]
    expected, acquired = len(candidates), len(stocks)
    coverage = acquired / expected if expected else 0.0
    timed_out = sum("deadline" in r["reason"] for r in stock_failures)
    low_liquidity = [row["code"] for row in stocks if row["average_amount_5d"] < MIN_DAILY_AMOUNT]
    eligible = [row for row in stocks if row["average_amount_5d"] >= MIN_DAILY_AMOUNT]
    retrieval = build_candidate_universe(eligible, [], config=UniverseConfig(
        low_quota=FULL_A_NO_OVERLAY_LOW_QUOTA, trend_quota=FULL_A_NO_OVERLAY_TREND_QUOTA,
        neutral_quota=FULL_A_NO_OVERLAY_NEUTRAL_QUOTA, base_limit=FULL_A_FINAL_LIMIT,
        overlay_limit=0, final_limit=FULL_A_FINAL_LIMIT))
    selected = list(retrieval["final"])
    minute_data = {interval: {row["code"]: _minute_row(row, interval, cutoff.isoformat())
        for row in selected} for interval in ("15m", "30m")}
    for row in selected:
        row.pop("cutoff_minutes", None)
    # Every original instrument is accounted for. Only confirmed business
    # exclusions leave the acquisition denominator; unknown identity/metadata
    # remains a separate, visible foundation gap.
    business_excluded = [r for r in cohort["excluded"] if r["reason"] in
        ("st_or_delisting", "listed_days")]
    foundation_missing = [r for r in cohort["excluded"] if r["reason"] not in
        ("st_or_delisting", "listed_days")]
    def reason_counts(records):
        counts = {}
        for record in records:
            reason = record["reason"]
            counts[reason] = counts.get(reason, 0) + 1
        return counts
    foundation_coverage = expected / (expected + len(foundation_missing)) if expected else 0.0
    failed = (coverage < MINIMUM_COVERAGE or foundation_coverage < MINIMUM_COVERAGE
        or timed_out > 0 or stop.is_set() or "上证指数" not in indices or _dt(clock()) >= deadline)
    health = dict(status="failed" if failed else "partial" if failures or foundation_missing else "available",
        expected=expected, acquired=acquired, rejected=len(stock_failures), timed_out=timed_out,
        instrument_count=cohort["instrument_count"], qualified_cohort=expected,
        business_excluded=len(business_excluded), business_excluded_reasons=reason_counts(business_excluded),
        foundation_missing=len(foundation_missing), foundation_missing_reasons=reason_counts(foundation_missing),
        foundation_missing_records=foundation_missing,
        coverage=coverage, minimum_coverage=MINIMUM_COVERAGE, foundation_coverage=foundation_coverage,
        source_rate_limited=stop.is_set(), failures=failures,
        history_gap_policy="source repair in independent snapshot; unresolved stays unavailable",
        source_requests_per_identity_max=5 if pair_fetcher is None else 4)
    if recovery_diagnostics is not None:
        def request_totals(records):
            counts = [row.get("request_count") for row in records.values()]
            return dict(known_attempts=sum(x for x in counts if x is not None),
                unknown_identities=sum(x is None for x in counts))
        recovery_diagnostics.update(first_wave_requests=request_totals(first_details),
            recovery_requests=request_totals(recovery_details))
        health["source_recovery"] = recovery_diagnostics
        health["source_requests_per_identity_max"] = 10
    market_indices = {}
    for name in INDEX_NAMES:
        row = indices.get(name)
        market_indices[name] = (dict(close=row["klines"]["closes"][-1], change_pct=row["change_pct"],
            date=trade_date, as_of=cutoff.isoformat(), source="eastmoney_cutoff", status="available")
            if row else dict(close=None, change_pct=None, date=trade_date, as_of=cutoff.isoformat(),
                source="", status="unavailable", reason="cutoff_index_input_unavailable"))
    quality = dict(observation=health, cohort=cohort, retrieval=retrieval.get("diagnostics", {}),
        previous_trade_date=previous, low_liquidity_at_cutoff=low_liquidity,
        legacy_codes=[row["code"] for row in selected],
        legacy_membership="frozen observation retrieval; no post-close or personal-watchlist injection",
        sector_status="unavailable", reason="strict cutoff does not borrow later sector flows")
    payload = _jsonable(dict(schema_version=1, cutoff=cutoff.isoformat(), collection_health=health,
        daily_data=dict(stocks=selected, sectors=[], sh_index=indices.get("上证指数", {}).get("klines"),
            data_quality=quality, sector_component_evidence={}, legacy_codes=[r["code"] for r in selected]),
        market_indices=market_indices, minute_data=minute_data,
        optional_input_status={"sector_flows": "unavailable", "news": "unavailable",
            "limit_up_pool": "unavailable", "market_sentiment": "unavailable"}))
    if timings is not None:
        timings.update(collection_wall_seconds=collection_finished - started,
            post_collection_aggregation_seconds=elapsed_clock.monotonic() - collection_finished)
    return payload
