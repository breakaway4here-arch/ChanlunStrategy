"""Small price-basis helpers shared by daily and intraday strategy gates."""

from __future__ import annotations

import math
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional
from urllib.parse import unquote

from .identity import normalize_identity


def basis_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def canonical_daily_reference(identity, rows):
    """A reference to the actual identity-scoped canonical rows, never a raw factor."""
    by_date = {}
    for row in rows:
        date = str(row['ts'])[:10]
        by_date[date] = {
            **{key: float(row[key]) for key in ('open', 'high', 'low', 'close')},
            'adjustment': str(row['adjustment']), 'is_final': bool(row['is_final']),
            'source': str(row.get('source_batch') or row.get('source') or ''),
        }
    return {'schema_version': 1, 'identity_key': normalize_identity(identity).key,
            'by_date': by_date, 'sha256': basis_sha256(by_date)}


def _repair_source_parts(source):
    prefix, version, start, end, known, provider, digest = source.split('|quantity_source=',1)[0].split(':')
    if (prefix != 'price_basis_repair' or version != 'v1' or provider not in ('tencent','sina')
            or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
        raise ValueError('invalid_repair_source')
    if provider == 'sina' and (start != '2026-04-21' or end != '2026-10-20'):
        raise ValueError('invalid_repair_source_scope')
    datetime.strptime(start, '%Y-%m-%d')
    datetime.strptime(end, '%Y-%m-%d')
    known_at = datetime.strptime(known, '%Y%m%dT%H%M%S.%fZ' if '.' in known else '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    if start > end:
        raise ValueError('invalid_repair_scope')
    return start, end, known_at


def repair_quantity_source(source):
    """Unwrap an explicit original quantity contract, never guess on corruption."""
    if not source.startswith('price_basis_repair:'):
        return source
    try:
        _repair_source_parts(source)
        return unquote(source.split('|quantity_source=',1)[1])
    except (IndexError, TypeError, ValueError):
        return ''


def repaired_daily_basis_failure(rows, *, as_of=None, consumed_dates=None):
    """Check only the consumed dates of an explicitly versioned repair.

    A 240-day reference container is not itself a 240-day consumption. Existing
    receipts for unrelated dates keep their existing verification behavior.
    """
    dates = None if consumed_dates is None else {str(d)[:10] for d in consumed_dates}
    consumed = [r for r in rows if dates is None or str(r['ts'])[:10] in dates]
    for row in consumed:
        source = str(row.get('source_batch') or row.get('source') or '')
        if not source.startswith('price_basis_repair:'):
            continue
        try:
            start, end, known_at = _repair_source_parts(source)
            if ':sina:' in source.split('|quantity_source=',1)[0] and str(row['ts'])[:10] != '2026-10-20':
                raise ValueError('invalid_repair_sina_date')
            if not start <= str(row['ts'])[:10] <= end:
                raise ValueError('invalid_repair_scope')
            if any(str(r['ts'])[:10] < start for r in consumed):
                return 'price_basis_repair_window_crossed'
            if as_of is not None and _basis_cutoff(as_of) < known_at:
                return 'price_basis_repair_not_known_as_of'
        except (TypeError, ValueError):
            return 'invalid_price_basis_repair_provenance'
    return None


def minute_price_rows(kline):
    """Stable content for both repository output and the bare-array analyzer."""
    def get(key, default=None):
        return kline.get(key, default) if isinstance(kline, Mapping) else getattr(kline, key, default)
    dates = list(get('dates', []))
    finals = get('is_final', get('finals', []))
    sources = get('source_batches', [])
    units = get('volume_units', [])
    raw_units = get('volume_raw_units', [])
    volume_sources = get('volume_sources', [])
    rows = []
    for index, date in enumerate(dates):
        rows.append({
            'ts': str(date),
            **{key: float(get(key+'s')[index]) for key in ('open', 'high', 'low', 'close', 'volume')},
            'is_final': bool(finals[index]),
            'source': str(sources[index]),
            'adjustment': str(get('adjustment', '')),
            'volume_unit': str(units[index]),
            'volume_raw_unit': str(raw_units[index]),
            'volume_source': str(volume_sources[index]),
        })
    return rows


def pending_minute_basis(reason, identity_key='', interval='30m', as_of=''):
    return {'schema_version': 1, 'status': 'pending', 'reason': reason,
            'identity_key': identity_key, 'interval': interval, 'as_of': str(as_of or '')}


def _basis_cutoff(value):
    cn = timezone(timedelta(hours=8))
    text = str(value)
    result = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if len(text) == 10:
        result = result.replace(hour=23, minute=59, second=59, microsecond=999999)
    return result.replace(tzinfo=cn) if result.tzinfo is None else result.astimezone(cn)


def verified_minute_basis(identity, interval, kline, daily_reference, receipts, as_of):
    """Bind only persisted producer receipts to the final merged/sliced window.

    Complete OHLC equality alone cannot create a receipt for a legacy cache.
    A partial first day may consume a subset of a previously proven full day.
    """
    identity_key = normalize_identity(identity).key
    as_of = str(as_of or datetime.now(timezone(timedelta(hours=8))).isoformat())
    pending = lambda reason: pending_minute_basis(reason, identity_key, interval, as_of)
    try:
        rows = minute_price_rows(kline)
        if not rows or any(not r['is_final'] or r['adjustment'] != 'qfq' or not r['source'] for r in rows):
            return pending('minute_window_unverified')
        if as_of and any(_basis_cutoff(row['ts']) > _basis_cutoff(as_of) for row in rows):
            return pending('minute_window_after_cutoff')
        if daily_reference.get('identity_key') != identity_key:
            return pending('daily_identity_mismatch')
        dates = sorted({row['ts'][:10] for row in rows})
        targets = {date: daily_reference['by_date'][date] for date in dates}
        target_rows = [dict(target, ts=date) for date, target in targets.items()]
        failure = repaired_daily_basis_failure(target_rows, as_of=as_of)
        if failure:
            return pending(failure)
        evidence, inputs = {}, []
        for date in dates:
            receipt = receipts.get(date)
            if not isinstance(receipt, Mapping):
                return pending('missing_producer_receipt:'+date)
            body = {k: v for k, v in receipt.items() if k != 'sha256'}
            if (receipt.get('schema_version') != 1 or receipt.get('identity_key') != identity_key
                    or receipt.get('interval') != interval or receipt.get('date') != date
                    or receipt.get('sha256') != basis_sha256(body)
                    or receipt.get('transform_applied') is not True
                    or receipt.get('input_adjustment') != 'unverified'
                    or receipt.get('output_adjustment') != 'qfq'):
                return pending('invalid_producer_receipt:'+date)
            mapping = receipt['evidence']
            if (not receipt.get('as_of') or _basis_cutoff(receipt['as_of']) > _basis_cutoff(as_of)
                    or _basis_cutoff(date+' 15:00:00') > _basis_cutoff(as_of)):
                return pending('receipt_or_daily_reference_after_cutoff:'+date)
            failure = repaired_daily_basis_failure([dict(targets[date], ts=date)], as_of=receipt['as_of'])
            if failure:
                return pending(failure)
            if (mapping['target_daily'] != targets[date] or not targets[date]['is_final']
                    or targets[date]['adjustment'] != 'qfq' or not targets[date]['source']):
                return pending('target_reference_changed:'+date)
            if (basis_sha256(receipt['input_rows']) != receipt['input_sha256']
                    or basis_sha256(receipt['output_rows']) != receipt['output_sha256']):
                return pending('producer_content_changed:'+date)
            proven = {row['ts']: row for row in receipt['output_rows']}
            consumed = [row for row in rows if row['ts'][:10] == date]
            if any(proven.get(row['ts']) != row for row in consumed):
                return pending('minute_content_changed:'+date)
            raw_rows = {row['ts']: row for row in receipt['input_rows']}
            inputs.extend(raw_rows[row['ts']] for row in consumed)
            evidence[date] = dict(mapping, receipt_sha256=receipt['sha256'],
                                  receipt_as_of=receipt['as_of'])
        proof = {'schema_version': 1, 'status': 'verified', 'identity_key': identity_key,
                 'interval': interval, 'as_of': as_of,
                 'window_start': rows[0]['ts'], 'window_end': rows[-1]['ts'],
                 'input_adjustment': 'unverified', 'output_adjustment': 'qfq',
                 'transform_applied': True, 'input_sha256': basis_sha256(inputs),
                 'output_sha256': basis_sha256(rows),
                 'target_reference_sha256': basis_sha256(targets),
                 'evidence_by_date': evidence}
        proof['sha256'] = basis_sha256(proof)
        return proof
    except (KeyError, IndexError, TypeError, ValueError):
        return pending('invalid_basis_receipt')


def _canonical_minute_comparable(daily_stock, min30_result, proof):
    try:
        if (proof.get('schema_version') != 1 or proof.get('status') != 'verified'
                or proof.get('interval') != '30m' or proof.get('output_adjustment') != 'qfq'
                or proof.get('transform_applied') is not True
                or proof.get('sha256') != basis_sha256({k:v for k,v in proof.items() if k != 'sha256'})):
            return False
        identity = normalize_identity(daily_stock).key
        if identity != proof['identity_key'] or str(getattr(min30_result, 'code', '')) != daily_stock['code']:
            return False
        rows = minute_price_rows(min30_result)
        if (not rows or basis_sha256(rows) != proof['output_sha256']
                or rows[0]['ts'] != proof['window_start'] or rows[-1]['ts'] != proof['window_end']):
            return False
        cutoff = _basis_cutoff(proof['as_of'])
        if any(_basis_cutoff(row['ts']) > cutoff for row in rows):
            return False
        basis = daily_stock.get('price_basis') or {}
        reference = basis['canonical_daily']
        if reference['identity_key'] != identity or reference.get('sha256') != basis_sha256(reference['by_date']):
            return False
        dates = sorted({row['ts'][:10] for row in rows})
        targets = {date: reference['by_date'][date] for date in dates}
        if repaired_daily_basis_failure([dict(target, ts=date) for date,target in targets.items()], as_of=proof['as_of']):
            return False
        if set(proof['evidence_by_date']) != set(dates) or basis_sha256(targets) != proof['target_reference_sha256']:
            return False
        actual_dates = {str(date)[:10]: index for index,date in enumerate(daily_stock['dates'])}
        for date,target in targets.items():
            item = proof['evidence_by_date'][date]
            if (target != item['target_daily'] or not item.get('receipt_as_of')
                    or _basis_cutoff(item['receipt_as_of']) > cutoff
                    or _basis_cutoff(date+' 15:00:00') > cutoff):
                return False
            if repaired_daily_basis_failure([dict(target,ts=date)], as_of=item['receipt_as_of']):
                return False
            index = actual_dates[date]
            if any(float(daily_stock[key+'s'][index]) != target[key] for key in ('open','high','low','close')):
                return False
        return True
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return False


def _positive(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def adjustment_factor(target_anchor: Any, source_anchor: Any) -> float:
    """Return the multiplicative factor that maps source prices to target basis."""

    target = _positive(target_anchor)
    source = _positive(source_anchor)
    if target is None or source is None:
        raise ValueError("price basis anchors must be finite and positive")
    factor = target / source
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("price basis factor must be finite and positive")
    return factor


def scale_price(value: Any, factor: Any) -> float:
    price = _positive(value)
    multiplier = _positive(factor)
    if price is None or multiplier is None:
        raise ValueError("price and factor must be finite and positive")
    result = price * multiplier
    if not math.isfinite(result) or result <= 0:
        raise ValueError("scaled price must be finite and positive")
    return result


def daily_intraday_factor(
    daily_stock: Mapping[str, Any],
    min30_result: Any,
) -> Optional[float]:
    """Keep canonical minute proof separate from the public raw-price factor."""
    evidence = getattr(min30_result, 'strategy_input_evidence', {})
    if isinstance(evidence, Mapping) and 'minute_to_daily' in evidence:
        proof = evidence['minute_to_daily']
        return 1.0 if isinstance(proof, Mapping) and _canonical_minute_comparable(daily_stock, min30_result, proof) else None
    if hasattr(min30_result, 'minute_to_daily'):
        proof = min30_result.minute_to_daily
        return 1.0 if isinstance(proof, Mapping) and _canonical_minute_comparable(daily_stock, min30_result, proof) else None
    if (getattr(min30_result, 'adjustment', '') in ('unverified', 'raw')
            or isinstance(evidence, Mapping) and (evidence.get('adjustment') in ('unverified', 'raw')
                or evidence.get('status') == 'price_basis_unverified')):
        return None

    basis = daily_stock.get("price_basis")
    basis = basis if isinstance(basis, Mapping) else {}
    explicit = _positive(basis.get("factor_vs_raw"))
    if explicit is not None:
        return explicit
    return None


def align_intraday_price(
    value: Any,
    daily_stock: Mapping[str, Any],
    min30_result: Any,
) -> Optional[float]:
    factor = daily_intraday_factor(daily_stock, min30_result)
    if factor is None:
        return None
    try:
        return scale_price(value, factor)
    except ValueError:
        return None
