"""Offline conflict diagnostics and the explicitly approved two-stock repair.

The ordinary maintenance path never calls the writer.  This module imports no
application entry point, provider, network client, or schema initializer.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import quote

PRICE_FIELDS = ('open', 'high', 'low', 'close')
SCHEMA = 'chanlun-approved-daily-price-repair-v1'
SCHEMA_96 = 'chanlun-approved-daily-price-repair-v2-96'
WINDOW_START, WINDOW_END, BAD_DATE = '2026-04-21', '2026-10-19', '2026-08-06'
INPUT_HASHES = {
    'scope': '74f5aa556009710c12104825c980d6ff4adaf41c7e45ec7c4c6e641c71ecea49',
    'frozen': '957fa16b1169e0fef8ab37c7bc776a882ac454f759fc89354a5abdbb0397b406',
    'pilot': '80f7252565750596a19ee07b7542736ef17c1c23cc4362e0c85be688bf8c21ba',
    'anchors': '0a36b5265225f0a7e350767611e413a6d2c5b8e4ab7d2ad6cc75f43ae566cb0a',
}
APPROVED = {
    'stock|SH|600063': (3215, '76f420f8fd9d3bb2df2a9d08881d748c61187b81c0811e6e7a61abe0bb836dcd'),
    'stock|SZ|000070': (5000, '06a44b7cfb32b7e34ce8ed0f3b52b4ca77f10f854bb176b008ab23db3555aa94'),
}
TAIL_INPUT_HASHES = {
    'tail_scope': '17a64d467a5467fec278e7c64db99cf72a3733696eb72b39292dbb61987d52bd',
    'tail_quotes': '6dd0ee579efb3d42363b795f5be1d1fc15cacef6a33fc0caf486f4ccc7c15979',
}
APPROVED_96 = {
    'stock|SH|600063': (3215, '1c211e8d09015b8984f0261e16d46026334c545691c52e98376d2b8b2077b9ba'),
    'stock|SZ|000070': (5000, 'dac21bfee6c1974141dfbee71a83989393464e20aaaef44206d5199304c411d3'),
}


def content_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _identity(value):
    return '|'.join(str(value[k]) for k in ('asset_type', 'exchange', 'code'))


def _close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-8)


def _prices_equal(a, b):
    return all(_close(a[k], b[k]) for k in PRICE_FIELDS)


def _valid_prices(row):
    try:
        values = [float(row[k]) for k in PRICE_FIELDS]
        return (all(math.isfinite(v) and v > 0 for v in values)
                and float(row['low']) <= min(float(row['open']), float(row['close']))
                and float(row['high']) >= max(float(row['open']), float(row['close'])))
    except (KeyError, ValueError, TypeError):
        return False


def classify_price_conflict(old_rows, source_rows, *, source_precision=None,
                            anchor_rule=None, event=None):
    """Classify evidence without permitting writes or widening price tolerance.

    Anchor/event classifications require a separately verified evidence object;
    a fitted factor, a source label, or the common word qfq is insufficient.
    Quantity uncertainty remains separate from the price diagnosis.
    """
    old_rows, source_rows = list(old_rows), list(source_rows)
    result = {'category': 'unexplained', 'price_category': 'unexplained',
              'write_authorized': False, 'conflict_dates': [], 'reasons': []}
    if (not old_rows or len(old_rows) != len(source_rows)
            or [r.get('ts') for r in old_rows] != [r.get('ts') for r in source_rows]
            or len({r.get('ts') for r in old_rows}) != len(old_rows)
            or not all(_valid_prices(r) for r in old_rows + source_rows)):
        result['reasons'].append('identity_dates_or_prices_unverified')
        return result
    conflicts = [(a, b) for a, b in zip(old_rows, source_rows) if not _prices_equal(a, b)]
    result['conflict_dates'] = [a['ts'] for a, _ in conflicts]
    price_category = 'unexplained' if conflicts else 'same_basis'
    if conflicts and isinstance(source_precision, dict):
        decimals = source_precision.get('decimals')
        if (type(decimals) is int and 0 <= decimals <= 8
                and source_precision.get('contract')):
            quantum = Decimal(1).scaleb(-decimals)
            rounded = lambda x: Decimal(str(x)).quantize(quantum, rounding=ROUND_HALF_UP)
            if all(rounded(a[k]) == rounded(b[k]) for a, b in conflicts for k in PRICE_FIELDS):
                price_category = 'rounding_equivalent'
    if conflicts and isinstance(anchor_rule, dict):
        required = ('source_sha256', 'independent_anchor_sha256', 'old_anchor_date',
                    'missing_previous_date', 'old_anchor_close', 'source_previous_close')
        if (all(anchor_rule.get(k) for k in required)
                and anchor_rule.get('verification') == 'archived_full_window_exact_chain_v1'
                and anchor_rule.get('old_anchor_date') < anchor_rule.get('missing_previous_date')
                and all(a['ts'] > anchor_rule['missing_previous_date'] for a, _ in conflicts)):
            factor = float(anchor_rule['old_anchor_close']) / float(anchor_rule['source_previous_close'])
            if all(_close(a[k], float(b[k]) * factor) for a, b in conflicts for k in PRICE_FIELDS):
                price_category = 'anchor_contaminated'
    if conflicts and isinstance(event, dict) and event.get('verification') == 'official_event_raw_boundary_v1':
        if all(event.get(k) for k in ('official_document_sha256', 'effective_date',
                                      'raw_boundary_sha256', 'precision_contract')):
            price_category = 'event_rebase_required'
    quantity_unknown = any(r.get('volume_unit') != 'hands' or not r.get('amount_available')
                           or r.get('amount_unit') != 'CNY' for r in old_rows + source_rows)
    result.update(price_category=price_category,
                  category=('quantity_unverified' if quantity_unknown and price_category in
                            ('same_basis', 'rounding_equivalent') else price_category),
                  quantity_unverified=quantity_unknown)
    return result


class DailyPriceConflict(ValueError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason)
        self.diagnostic = diagnostic


def _read_json(path, expected_hash):
    path = Path(path).resolve()
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_hash:
        raise ValueError('evidence_source_hash_mismatch:' + str(path))
    return json.loads(raw), {'path': str(path), 'sha256': actual}


def _timestamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('evidence_timezone_missing')
    return result.astimezone(timezone(timedelta(hours=8)))


def _source_rows(pilot_target, identity, old_rows):
    raw, evidence = _read_json(pilot_target['raw_response_file'], pilot_target['raw_response_sha256'])
    symbol = identity['exchange'].lower() + identity['code']
    if raw.get('code') != 0 or symbol not in raw.get('data', {}):
        raise ValueError('source_identity_mismatch')
    lines = raw['data'][symbol].get('qfqday')
    if not isinstance(lines, list) or len(lines) != 122 or any(len(r) < 6 for r in lines):
        raise ValueError('source_window_incomplete')
    # Existing bounded provider rule: tail 121, then the one unfinished future day.
    lines = lines[-121:]
    if lines[-1][0] != '2026-10-20':
        raise ValueError('source_tail_date_mismatch')
    lines = lines[:-1]
    if [r[0] for r in lines] != [r['ts'] for r in old_rows]:
        raise ValueError('source_dates_mismatch')
    if _timestamp(pilot_target['fetched_at']).date().isoformat() != '2026-10-20':
        raise ValueError('source_collection_date_mismatch')
    result = [dict(ts=r[0], open=float(r[1]), close=float(r[2]), high=float(r[3]),
                   low=float(r[4]), volume=float(r[5]), volume_unit='unknown',
                   volume_raw_unit='unknown', volume_source='tencent', amount=0.,
                   amount_available=0, amount_unit='unknown', amount_source='',
                   adjustment='qfq', is_final=1) for r in lines]
    if not all(_valid_prices(r) and math.isfinite(r['volume']) and r['volume'] >= 0 for r in result):
        raise ValueError('source_invalid_ohlcv')
    return result, evidence


def _verify_anchors(anchor_index, identity, source_rows):
    sources, dates, evidence = set(), set(), []
    by_date = {r['ts']: r for r in source_rows}
    for entry in anchor_index:
        document, record = _read_json(entry['path'], entry['file_sha256'])
        matches = [r for r in document['rows'] if r.get('asset_type') == identity['asset_type']
                   and r.get('exchange') == identity['exchange'] and r.get('code') == identity['code']]
        if len(matches) != 1:
            raise ValueError('independent_anchor_identity_mismatch')
        quote = matches[0]
        ts = _timestamp(quote['quote_asof'])
        date = entry['date']
        if ts.date().isoformat() != date or (ts.hour, ts.minute) < (15, 0):
            raise ValueError('independent_anchor_not_closed')
        provider = quote['quote_source']
        # EastMoney clist/get returns actual f2/f15/f16/f17 quote prices.
        # This explicit endpoint field contract supplies the absent cache label;
        # a null basis from any other provider is never upgraded by coincidence.
        raw_contract = quote.get('price_basis') == 'raw' or (provider == 'eastmoney'
            and date == '2026-10-16' and quote.get('price_basis') is None)
        if not raw_contract or quote.get('quote_status') != 'valid':
            raise ValueError('independent_anchor_basis_unverified')
        prices = {k: quote['current_price'] if k == 'close' else quote[k] for k in PRICE_FIELDS}
        if date not in by_date or not _prices_equal(prices, by_date[date]):
            raise ValueError('independent_anchor_price_mismatch')
        sources.add(provider)
        dates.add(date)
        evidence.append(dict(record, date=date, provider=provider,
                             contract=('sina_raw_quote' if provider == 'sina' else 'eastmoney_clist_actual_quote')))
    if len(sources) < 2 or len(dates) < 3:
        raise ValueError('independent_anchor_coverage_missing')
    return evidence


def build_manifest(scope_path, frozen_path, pilot_path, anchors_path, *, created_at):
    """Rebuild exact proposed values from pinned archives, never fitted prices."""
    if _timestamp(created_at) < _timestamp('2026-10-20T14:44:00+08:00'):
        raise ValueError('repair_timestamp_before_approval')
    inputs, files = {}, {}
    for key, path in (('scope', scope_path), ('frozen', frozen_path),
                      ('pilot', pilot_path), ('anchors', anchors_path)):
        inputs[key], files[key] = _read_json(path, INPUT_HASHES[key])
    targets = []
    scoped = {_identity(t['identity']):t for t in inputs['scope']['targets']}
    frozen = {_identity(t['identity']):t for t in inputs['frozen']['targets']}
    pilot = {_identity(t['identity']):t for t in inputs['pilot']['pending']}
    if set(scoped) != set(APPROVED):
        raise ValueError('approved_scope_identity_mismatch')
    for key in sorted(APPROVED):
        target, scope, captured = frozen[key], scoped[key], pilot[key]
        identity = target['identity']
        old = target['window_rows']
        # Exact old columns, including final flags and quantities, are authoritative.
        iid, expected_hash = APPROVED[key]
        if (identity['instrument_id'] != iid or scope['identity'] != identity
                or len(old) != 120 or content_sha256(old) != expected_hash
                or [old[0]['ts'], old[-1]['ts']] != [WINDOW_START, WINDOW_END]
                or any(r['instrument_id'] != iid or r['adjustment'] != 'qfq' for r in old)):
            raise ValueError('approved_old_window_mismatch:' + key)
        source, source_evidence = _source_rows(captured, identity, old)
        if _timestamp(created_at) < _timestamp(captured['fetched_at']):
            raise ValueError('repair_timestamp_before_source_available')
        anchors = _verify_anchors(inputs['anchors'], identity, source)
        old_by_date, src_by_date = ({r['ts']:r for r in rows} for rows in (old, source))
        bad, previous = old_by_date[BAD_DATE], old_by_date['2026-08-05']
        if bad['is_final'] or not previous['is_final'] or not _prices_equal(bad, src_by_date[BAD_DATE]):
            raise ValueError('wrong_anchor_chain_boundary_mismatch')
        if any(not _prices_equal(r, src_by_date[r['ts']]) for r in old if r['ts'] < BAD_DATE):
            raise ValueError('wrong_anchor_chain_prefix_mismatch')
        rule = dict(verification='archived_full_window_exact_chain_v1',
                    source_sha256=source_evidence['sha256'],
                    independent_anchor_sha256=content_sha256(anchors),
                    old_anchor_date=previous['ts'], missing_previous_date=BAD_DATE,
                    old_anchor_close=previous['close'], source_previous_close=src_by_date[BAD_DATE]['close'])
        diagnostic = classify_price_conflict(old, source, anchor_rule=rule)
        if diagnostic['category'] != 'anchor_contaminated' or len(diagnostic['conflict_dates']) != 46:
            raise ValueError('wrong_anchor_chain_not_exact')
        expected_dates = [r['ts'] for r in old if r['ts'] >= BAD_DATE]
        if [r['date'] for r in scope['rows']] != expected_dates or len(expected_dates) != 47:
            raise ValueError('approved_write_dates_mismatch')
        known_at = _timestamp(created_at).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        marker = 'price_basis_repair:v1:{}:{}:{}:tencent:{}'.format(
            WINDOW_START, WINDOW_END, known_at, source_evidence['sha256'])
        new, changes = copy.deepcopy(old), []
        for row in new:
            if row['ts'] < BAD_DATE:
                continue
            original, source_row = old_by_date[row['ts']], src_by_date[row['ts']]
            scope_row = next(r for r in scope['rows'] if r['date'] == row['ts'])
            if scope_row['old_row'] != original or not _prices_equal(scope_row['proposed_price_fields'], source_row):
                raise ValueError('approved_row_mismatch')
            row.update({k:source_row[k] for k in PRICE_FIELDS})
            quantity_source = original['source_batch'] if original['is_final'] else 'tencent'
            row.update(source_batch=marker+'|quantity_source='+quote(quantity_source,safe=''), updated_at=created_at)
            if row['ts'] == BAD_DATE:
                # NOT NULL amount uses the existing unavailable serialization,
                # always accompanied by amount_available=0 and no unit/source.
                for field in ('volume','volume_unit','volume_raw_unit','volume_source',
                              'amount','amount_available','amount_unit','amount_source','is_final'):
                    row[field] = source_row[field]
            fields = sorted(k for k in row if row[k] != original[k])
            if original['is_final'] and set(fields) - set(PRICE_FIELDS) - {'source_batch','updated_at'}:
                raise ValueError('healthy_quantity_or_identity_write_forbidden')
            changes.append(dict(date=row['ts'], old=copy.deepcopy(original),
                                new=copy.deepcopy(row), fields=fields))
        targets.append(dict(identity=identity, identity_key=key, old_window=old, new_window=new,
                            old_sha256=expected_hash, new_sha256=content_sha256(new), changes=changes,
                            diagnostic=diagnostic, anchor_rule=rule,
                            source_evidence=source_evidence, independent_anchors=anchors))
    manifest = dict(schema=SCHEMA, authorization='2026-10-20-approved-two-stock-94',
                    created_at=created_at, inputs=files, targets=targets,
                    window_start=WINDOW_START, window_end=WINDOW_END, total_changes=94)
    manifest['sha256'] = content_sha256(manifest)
    return manifest


def _validate_tail_quote(quote, identity, canonical_previous, old_previous, old_tail,
                         *, created_at, cache_fetched_at):
    """Prove the closed raw quote and its actual previous-close basis bridge."""
    if any(quote.get(k) != identity[k] for k in ('asset_type','exchange','code')):
        raise ValueError('tail_quote_identity_mismatch')
    if quote.get('quote_source') != 'sina':
        raise ValueError('tail_quote_source_mismatch')
    if quote.get('price_basis') != 'raw' or quote.get('quote_status') != 'valid':
        raise ValueError('tail_quote_basis_or_status_unverified')
    stamp, fetched = _timestamp(quote['quote_asof']), _timestamp(quote['fetched_at'])
    cached, created = _timestamp(cache_fetched_at), _timestamp(created_at)
    if stamp.date().isoformat() != '2026-10-20' or (stamp.hour,stamp.minute) < (15,0):
        raise ValueError('tail_quote_not_closed')
    if (fetched.date().isoformat() != '2026-10-20' or not stamp <= fetched <= cached <= created):
        raise ValueError('tail_quote_timestamp_mismatch')
    prices = {k: quote['current_price'] if k == 'close' else quote[k] for k in PRICE_FIELDS}
    if not _valid_prices(prices):
        raise ValueError('tail_quote_invalid_prices')
    previous = float(quote['prev_close'])
    if (not math.isfinite(previous) or previous <= 0 or canonical_previous['ts'] != '2026-10-19'
            or old_previous['ts'] != '2026-10-19' or float(canonical_previous['close']) != previous):
        raise ValueError('tail_quote_previous_close_mismatch')
    if (old_tail['ts'] != '2026-10-20' or old_tail['instrument_id'] != identity['instrument_id']
            or not old_tail['is_final'] or old_tail['adjustment'] != 'qfq'):
        raise ValueError('tail_old_identity_date_or_final_mismatch')
    factor = float(old_previous['close']) / previous
    if not all(_close(old_tail[k], float(prices[k])*factor) for k in PRICE_FIELDS):
        raise ValueError('tail_old_wrong_anchor_chain_mismatch')
    return prices, dict(previous_date='2026-10-19', raw_previous_close=previous,
                        canonical_previous_close=float(canonical_previous['close']),
                        old_previous_close=float(old_previous['close']),
                        old_propagation_factor=factor, quote_asof=quote['quote_asof'],
                        fetched_at=quote['fetched_at'], source='sina', price_basis='raw')


def build_manifest_96(scope_path, frozen_path, pilot_path, anchors_path, *,
                      tail_scope_path, tail_quotes_path, created_at):
    """Explicit later approval: the original 94 rows plus two closed Sina rows.

    The original builder, schema and 10/19 guard remain unchanged. Tencent's
    unfinished 10/20 tail is never used as a source for this extension.
    """
    base = build_manifest(scope_path,frozen_path,pilot_path,anchors_path,created_at=created_at)
    extra, scope_evidence = _read_json(tail_scope_path,TAIL_INPUT_HASHES['tail_scope'])
    quotes, quote_evidence = _read_json(tail_quotes_path,TAIL_INPUT_HASHES['tail_quotes'])
    if (extra.get('combined_if_separately_authorized') != 96
            or extra.get('source_cache_sha256') != quote_evidence['sha256']
            or _timestamp(created_at) < _timestamp(extra['captured_at_utc'])):
        raise ValueError('tail_96_approval_inputs_mismatch')
    tails = {_identity(t['identity']):t for t in extra['targets']}
    if set(tails) != set(APPROVED_96) or len(extra['targets']) != 2:
        raise ValueError('tail_96_scope_identity_mismatch')
    for target in base['targets']:
        key = target['identity_key']
        tail = tails[key]
        iid, digest = APPROVED_96[key]
        old_tail = tail['old_row']
        old_window = target['old_window']+[old_tail]
        if (target['identity'] != tail['identity'] or target['identity']['instrument_id'] != iid
                or tail['date'] != '2026-10-20' or len(old_window) != 121
                or old_window != tail['combined_121_old_rows']
                or content_sha256(old_window) != digest or tail['combined_121_old_sha256'] != digest):
            raise ValueError('tail_96_old_window_mismatch')
        matches = [q for q in quotes['rows'] if all(q.get(k) == target['identity'][k]
                   for k in ('asset_type','exchange','code'))]
        if len(matches) != 1 or matches[0] != tail['source_raw_quote']:
            raise ValueError('tail_96_raw_quote_identity_or_content_mismatch')
        prices, proof = _validate_tail_quote(matches[0],target['identity'],target['new_window'][-1],
            target['old_window'][-1],old_tail,created_at=created_at,cache_fetched_at=quotes['fetched_at'])
        known_at = _timestamp(created_at).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        marker = 'price_basis_repair:v1:{}:2026-10-20:{}:sina:{}'.format(
            WINDOW_START,known_at,quote_evidence['sha256'])
        new_tail = dict(old_tail, **prices)
        new_tail.update(source_batch=marker+'|quantity_source='+quote(old_tail['source_batch'],safe=''),
                        updated_at=created_at)
        fields = sorted(k for k in new_tail if new_tail[k] != old_tail[k])
        if set(fields) - set(PRICE_FIELDS) - {'source_batch','updated_at'}:
            raise ValueError('tail_96_quantity_or_final_write_forbidden')
        target.update(old_window=old_window,old_sha256=digest,
                      new_window=target['new_window']+[new_tail],
                      window_start=WINDOW_START,window_end='2026-10-20',
                      tail_source_evidence=quote_evidence,tail_basis_evidence=proof)
        target['changes'].append(dict(date='2026-10-20',old=old_tail,new=new_tail,fields=fields))
        target['new_sha256'] = content_sha256(target['new_window'])
        target['diagnostic']['conflict_dates'].append('2026-10-20')
    base.update(schema=SCHEMA_96,authorization='2026-10-20-approved-two-stock-96',
                window_end='2026-10-20',total_changes=96)
    base['inputs'].update(tail_scope=scope_evidence,tail_quotes=quote_evidence)
    base.pop('sha256')
    base['sha256'] = content_sha256(base)
    return base


def validate_manifest(manifest):
    """Recompute from original bytes; a caller-updated manifest digest is no permit."""
    try:
        arguments = [manifest['inputs'][k]['path'] for k in ('scope','frozen','pilot','anchors')]
        if manifest.get('schema') == SCHEMA_96:
            rebuilt = build_manifest_96(*arguments,tail_scope_path=manifest['inputs']['tail_scope']['path'],
                tail_quotes_path=manifest['inputs']['tail_quotes']['path'],created_at=manifest['created_at'])
        elif manifest.get('schema') == SCHEMA:
            rebuilt = build_manifest(*arguments,created_at=manifest['created_at'])
        else:
            raise ValueError('repair_manifest_schema_not_approved')
    except (KeyError, TypeError) as exc:
        raise ValueError('repair_manifest_invalid') from exc
    if rebuilt != manifest:
        raise ValueError('repair_manifest_content_mismatch')
    return rebuilt


def _read_window(conn, target):
    iid = target['identity']['instrument_id']
    start, end = target.get('window_start',WINDOW_START), target.get('window_end',WINDOW_END)
    # Latest-tail guard intentionally refuses even unapproved new daily rows.
    tail = conn.execute('SELECT ts FROM bars_day WHERE instrument_id=? AND ts>? ORDER BY ts',
                        (iid, end)).fetchall()
    if tail:
        raise ValueError('cas_unapproved_tail:{}:{}'.format(target['identity_key'], ','.join(r[0] for r in tail)))
    conn.row_factory = sqlite3.Row
    identity = conn.execute('SELECT * FROM instruments WHERE instrument_id=?', (iid,)).fetchone()
    if identity is None or any(identity[k] != target['identity'][k] for k in ('asset_type','exchange','code')):
        raise ValueError('cas_identity_mismatch')
    return [dict(r) for r in conn.execute('SELECT * FROM bars_day WHERE instrument_id=? '
            'AND ts>=? AND ts<=? ORDER BY ts', (iid, start, end)).fetchall()]


@contextmanager
def _publish_lock(lock_path, lock_fd):
    owned = lock_fd is None
    if not lock_path:
        raise ValueError('apply_requires_explicit_publish_lock_path')
    path = Path(lock_path).resolve()
    if owned:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    else:
        descriptor = int(lock_fd)
        if (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) != (path.stat().st_dev, path.stat().st_ino):
            raise ValueError('inherited_publish_lock_path_mismatch')
    try:
        # Existing inherited descriptors share the parent's lock; never unlock it.
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        if owned:
            os.close(descriptor)


@contextmanager
def _connect(path, readonly=False):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                           uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    if readonly:
        conn.execute('PRAGMA query_only=ON')
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _write_rows(conn, target, rows):
    allowed = {r['date']: r['fields'] for r in target['changes']}
    for row in rows:
        if row['ts'] not in allowed:
            continue
        fields = allowed[row['ts']]
        if set(fields) & {'instrument_id','ts'}:
            raise ValueError('immutable_identity_write_forbidden')
        sql = 'UPDATE bars_day SET '+','.join('"{}"=?'.format(k) for k in fields)+' WHERE instrument_id=? AND ts=?'
        cursor = conn.execute(sql, tuple(row[k] for k in fields) + (row['instrument_id'],row['ts']))
        if cursor.rowcount != 1:
            raise ValueError('cas_row_disappeared')


def apply_manifest(db_path, manifest, *, apply=False, backup_dir=None,
                   identity_keys=None, lock_path=None, lock_fd=None, expected_sha256=None):
    """Dry-run by default. Apply one stock per transaction under the shared lock.

    The owner checks business idleness before invoking this offline command.
    No scheduler, listener, application initializer, or provider is started.
    """
    validate_manifest(manifest)
    keys = set(APPROVED if identity_keys is None else identity_keys)
    if not keys or not keys <= set(APPROVED):
        raise ValueError('identity_outside_approved_scope')
    selected = [t for t in manifest['targets'] if t['identity_key'] in keys]
    report = dict(status='dry_run' if not apply else 'applied', manifest_sha256=manifest['sha256'], targets=[])
    def inspect(conn, target):
        actual = _read_window(conn, target)
        if actual == target['new_window']:
            return 'already_applied'
        if actual != target['old_window']:
            raise ValueError('cas_full_window_changed:' + target['identity_key'])
        return 'ready'
    if not apply:
        with _connect(db_path, readonly=True) as conn:
            for target in selected:
                report['targets'].append(dict(identity_key=target['identity_key'], status=inspect(conn,target)))
        return report
    if not backup_dir:
        raise ValueError('apply_requires_backup_dir')
    if expected_sha256 != manifest['sha256']:
        raise ValueError('apply_requires_reviewed_manifest_sha256')
    with _publish_lock(lock_path, lock_fd):
        # Recheck all selected stocks before any mutation, including the tail.
        with _connect(db_path, readonly=True) as conn:
            for target in selected:
                inspect(conn, target)
        backup_dir = Path(backup_dir).resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        for target in selected:
            with _connect(db_path) as conn:
                conn.execute('BEGIN IMMEDIATE')
                status = inspect(conn, target)
                if status == 'already_applied':
                    conn.rollback()
                    report['targets'].append(dict(identity_key=target['identity_key'], status=status))
                    continue
                backup_path = backup_dir / ('{}-{}.json'.format(target['identity_key'].replace('|','-'), manifest['sha256']))
                backup_body = dict(manifest_sha256=manifest['sha256'], identity=target['identity'],
                                   old_window=target['old_window'], old_sha256=target['old_sha256'])
                raw = json.dumps(backup_body, sort_keys=True, indent=2, allow_nan=False).encode()
                if backup_path.exists():
                    if backup_path.read_bytes() != raw:
                        raise ValueError('backup_content_mismatch')
                else:
                    descriptor = os.open(str(backup_path), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                directory_fd = os.open(str(backup_dir), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                _write_rows(conn, target, target['new_window'])
                if _read_window(conn, target) != target['new_window']:
                    raise ValueError('transaction_readback_mismatch')
                conn.commit()
            try:
                with _connect(db_path, readonly=True) as readback:
                    if _read_window(readback, target) != target['new_window']:
                        raise ValueError('independent_readback_mismatch')
            except Exception:
                # Compensate only when every new value still matches. Never
                # overwrite a concurrent third party's changes during rollback.
                with _connect(db_path) as rollback:
                    rollback.execute('BEGIN IMMEDIATE')
                    if _read_window(rollback, target) != target['new_window']:
                        raise ValueError('readback_failed_rollback_cas_changed')
                    _write_rows(rollback, target, target['old_window'])
                    rollback.commit()
                with _connect(db_path, readonly=True) as readback:
                    if _read_window(readback,target) != target['old_window']:
                        raise ValueError('rollback_independent_readback_failed')
                raise
            report['targets'].append(dict(identity_key=target['identity_key'], status='applied',
                rows=len(target['changes']), backup_path=str(backup_path), readback_sha256=target['new_sha256']))
    return report
