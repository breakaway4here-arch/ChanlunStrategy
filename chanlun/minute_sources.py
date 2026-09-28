"""Strict, source-specific free minute schemas. No network or database writes."""

import json
import math
import re
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

CN = timezone(timedelta(hours=8))


def decode_response(text):
    """Parse data only; never execute a provider's JavaScript wrapper."""
    text = text.lstrip('\ufeff \t\r\n')
    text = re.sub(r'^(?:/\*.*?\*/\s*)+', '', text, flags=re.S)
    if text.startswith('<'):
        raise ValueError('html_error_page')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.fullmatch(r'var\s+_DATA\s*=\s*\((.*)\);?\s*', text, re.S)
        if not match:
            raise ValueError('unsupported_json_wrapper') from None
        return json.loads(match.group(1))


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('invalid_numeric_value')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('nonfinite_value')
    return value


def clean_minutes(data, *, source, symbol, scale, now=None):
    """Unit contracts are explicit by source, never inferred from magnitude."""
    if source not in ('tencent', 'sina') or int(scale) not in (15, 30):
        raise ValueError('unsupported_minute_schema')
    current = now or datetime.now(CN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=CN)
    if source == 'tencent':
        if not isinstance(data, dict) or data.get('code') != 0:
            raise ValueError('provider_error')
        rows = (data.get('data', {}).get(symbol) or {}).get('m' + str(scale))
    else:
        rows = data
    if not isinstance(rows, list) or not rows:
        raise ValueError('empty_response')
    dates, prices, volumes, amounts, finals = [], [], [], [], []
    previous = None
    for row in rows:
        if source == 'tencent':
            if not isinstance(row, list) or len(row) < 6:
                raise ValueError('invalid_row')
            ts = datetime.strptime(row[0], '%Y%m%d%H%M').replace(tzinfo=CN)
            o, c, h, l, v = map(_number, row[1:6])
            amount = math.nan  # Later columns are not a documented amount field.
        else:
            if not isinstance(row, dict):
                raise ValueError('invalid_row')
            ts = datetime.strptime(row['day'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CN)
            o, c, h, l, v = [_number(row[k]) for k in ('open', 'close', 'high', 'low', 'volume')]
            amount = math.nan if row.get('amount') in (None, '', '-') else _number(row['amount'])
        minute = ts.hour * 60 + ts.minute
        in_session = (570 < minute <= 690) or (780 < minute <= 900)
        origin = 570 if minute <= 690 else 780
        if ts.weekday() >= 5 or ts.second or not in_session or (minute - origin) % int(scale):
            raise ValueError('invalid_bucket_timestamp')
        if previous is not None and ts <= previous:
            raise ValueError('timestamps_not_strictly_increasing')
        previous = ts
        if not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0 or amount < 0:
            raise ValueError('invalid_ohlcva')
        if math.isfinite(amount):
            # Sina's explicit shares/CNY contract permits an independent unit check.
            # Do not repair a suspect value by guessing another conversion factor.
            shares = v * 100 if source == 'tencent' else v
            if shares == 0:
                if amount != 0:
                    raise ValueError('amount_volume_conflict')
            elif not l * 0.99 - 0.01 <= amount / shares <= h * 1.01 + 0.01:
                raise ValueError('amount_volume_price_conflict')
        dates.append(ts.strftime('%Y-%m-%d %H:%M:%S'))
        prices.append((o, h, l, c)); volumes.append(v); amounts.append(amount)
        finals.append(ts < current)  # At the exact boundary wait for the next observation.
    raw = np.asarray(volumes, dtype=float)
    amount_array = np.asarray(amounts, dtype=float)
    available = np.isfinite(amount_array)
    raw_unit = 'hands' if source == 'tencent' else 'shares'
    return {
        'dates': dates,
        **{key: np.asarray([p[i] for p in prices]) for i, key in enumerate(('opens', 'highs', 'lows', 'closes'))},
        'raw_volumes': raw,
        'volumes': raw.copy() if raw_unit == 'hands' else raw / 100.0,
        'volume_unit': 'hands', 'volume_raw_unit': raw_unit, 'volume_source': source,
        'amounts': amount_array, 'amount_available': available,
        'amount_unit': 'CNY' if available.any() else 'unknown',
        'amount_source': source if available.any() else '',
        'source': source, 'adjustment': 'unverified', 'finals': finals,
        'fetched_at': current.isoformat(), 'data_time': dates[-1],
        'schema': 'free_minute_v1', 'symbol': symbol,
    }


def closed_window(payload, *, count, cutoff):
    """Select one complete source window; no cache/source splicing or relabeling."""
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=CN)
    keep = [i for i, ts in enumerate(payload['dates'])
            if datetime.fromisoformat(ts).replace(tzinfo=CN) <= cutoff
            and payload['finals'][i]][-int(count):]
    result = dict(payload)
    for key in ('dates', 'opens', 'highs', 'lows', 'closes', 'volumes', 'raw_volumes',
                'amounts', 'amount_available', 'finals'):
        values = payload[key]
        result[key] = values[keep] if isinstance(values, np.ndarray) else [values[i] for i in keep]
    result['data_time'] = result['dates'][-1] if keep else ''
    result['excluded_rows'] = len(payload['dates']) - len(keep)
    return result


def align_daily_basis(payload, raw_daily, target_daily, *, scale, tolerance=0.011):
    """Map each complete day only after independent OHLC and affine checks.

    References must be identity-scoped by the caller, final, provenance-bearing
    daily bars. No single-close scaling, guessed split factors, or extrema repair.
    """
    if payload.get('schema') not in ('free_minute_v1', 'archived_minute_v1') or payload.get('volume_unit') != 'hands':
        raise ValueError('unsupported_basis_input')
    if payload.get('adjustment') != 'unverified' or int(scale) not in (15, 30):
        raise ValueError('already_adjusted_or_invalid_scale')
    result = dict(payload)
    keys = ('opens', 'highs', 'lows', 'closes')
    for key in keys:
        result[key] = np.array(payload[key], dtype=float, copy=True)
    days = defaultdict(list)
    for i, date in enumerate(payload['dates']):
        days[date[:10]].append(i)
    evidence = {}
    expected = {minute for start in (570, 780)
                for minute in range(start + int(scale), start + 121, int(scale))}
    for date, indices in days.items():
        times = [datetime.fromisoformat(payload['dates'][i]) for i in indices]
        if (len(indices) != len(expected)
                or {t.hour * 60 + t.minute for t in times} != expected
                or not all(payload['finals'][i] for i in indices)):
            raise ValueError('incomplete_day:' + date)
        raw, target = raw_daily.get(date), target_daily.get(date)
        if not raw or not target or raw.get('is_final') is not True or target.get('is_final') is not True:
            raise ValueError('missing_final_daily_reference:' + date)
        if not raw.get('source') or not target.get('source') or target.get('adjustment') != 'qfq':
            raise ValueError('unverified_daily_reference:' + date)
        fields = ('open', 'high', 'low', 'close')
        x = np.array([_number(raw[k]) for k in fields])
        y = np.array([_number(target[k]) for k in fields])
        for values in (x, y):
            if not 0 < values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]:
                raise ValueError('invalid_daily_ohlc:' + date)
        aggregate = np.array([payload['opens'][indices[0]], max(payload['highs'][indices]),
                              min(payload['lows'][indices]), payload['closes'][indices[-1]]])
        if np.max(np.abs(aggregate - x)) > tolerance:
            raise ValueError('raw_daily_conflict:' + date)
        if np.max(np.abs(x - y)) <= tolerance:
            a, b = 1.0, 0.0
        else:
            if x[1] - x[2] <= tolerance:
                raise ValueError('indeterminate_flat_day:' + date)
            a = (y[1] - y[2]) / (x[1] - x[2])
            b = y[2] - a * x[2]
            if not math.isfinite(a) or not math.isfinite(b) or a <= 0:
                raise ValueError('invalid_basis_mapping:' + date)
            if np.max(np.abs(a * x + b - y)) > tolerance:
                raise ValueError('non_affine_daily_reference:' + date)
        for key in keys:
            mapped = a * payload[key][indices] + b
            if not np.all(np.isfinite(mapped)) or np.min(mapped) <= 0:
                raise ValueError('invalid_mapped_price:' + date)
            result[key][indices] = mapped
        reference = json.dumps({'raw': raw, 'target': target}, sort_keys=True, allow_nan=False)
        evidence[date] = {'scale': float(a), 'offset': float(b),
                          'raw_daily': dict(raw), 'target_daily': dict(target),
                          'raw_daily_source': raw['source'], 'target_daily_source': target['source'],
                          'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
                          'raw_daily_max_error': float(np.max(np.abs(aggregate - x))),
                          'mapping_max_error': float(np.max(np.abs(a * x + b - y)))}
    if not days:
        raise ValueError('empty_basis_window')
    result['adjustment'] = 'qfq'
    result['price_basis_evidence'] = evidence
    return result
