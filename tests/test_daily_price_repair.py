"""Offline rule and bounded repair checks; all database writes use private copies."""
import copy
import importlib
import importlib.util
import json
import hashlib
import fcntl
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BASE = Path('/private/tmp/chanlun-price-conflict-rules-20261020')
PILOT = Path('/private/tmp/chanlun-coverage-impl-20261020/pilot')


class PriceConflictRulesTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('chanlun.daily_price_repair'),
                             'the bounded offline repair module is required')
        return importlib.import_module('chanlun.daily_price_repair')

    def test_same_basis_and_quantity_unknown_are_separate(self):
        m = self.module()
        row = dict(ts='2026-08-07', open=6., high=6.2, low=5.9, close=6.1,
                   adjustment='qfq', is_final=1, volume_unit='hands',
                   amount_available=1, amount_unit='CNY')
        self.assertEqual(m.classify_price_conflict([row], [row])['category'], 'same_basis')
        unknown = dict(row, volume_unit='unknown', amount_available=0)
        result = m.classify_price_conflict([unknown], [row])
        self.assertEqual(result['category'], 'quantity_unverified')
        self.assertEqual(result['price_category'], 'same_basis')

    def test_rounding_needs_explicit_precision_contract(self):
        m = self.module()
        old = dict(ts='2026-08-07', open=6., high=6.2, low=5.9, close=6.1)
        new = dict(old, close=6.1004)
        self.assertEqual(m.classify_price_conflict([old], [new])['category'], 'unexplained')
        self.assertEqual(m.classify_price_conflict([old], [new],
            source_precision={'decimals': 3, 'contract': 'archived-provider-round-half-up'})[
                'price_category'], 'rounding_equivalent')

    def test_fit_and_qfq_labels_do_not_prove_anchor_or_event(self):
        m = self.module()
        old = dict(ts='2026-08-07', open=6., high=6.2, low=5.9, close=6.1)
        new = dict(old, **{k: old[k] / 1.005 for k in m.PRICE_FIELDS})
        for kwargs in ({}, {'anchor_rule': {'factor': 1.005}},
                       {'event': {'date': '2026-08-07', 'cash': .01}}):
            self.assertEqual(m.classify_price_conflict([old], [new], **kwargs)[
                'category'], 'unexplained')
        self.assertEqual(m.classify_price_conflict([old], [dict(new, ts='2026-08-08')])[
            'category'], 'unexplained')

    def test_actual_consumed_dates_and_knowledge_time(self):
        from chanlun import price_basis
        self.assertTrue(hasattr(price_basis, 'repaired_daily_basis_failure'))
        check = price_basis.repaired_daily_basis_failure
        marker = 'price_basis_repair:v1:2026-04-21:2026-10-19:20261020T070000Z:tencent:'+'a'*64
        rows = [dict(ts='2026-04-20', source='old'),
                dict(ts='2026-10-19', source=marker),
                dict(ts='2026-10-20', source='official_close_snapshot:sina')]
        self.assertEqual(check(rows, as_of='2026-10-20T15:01:00+08:00'), 'price_basis_repair_window_crossed')
        self.assertEqual(check(rows, consumed_dates=['2026-10-19'], as_of='2026-10-19T16:00:00+08:00'),
                         'price_basis_repair_not_known_as_of')
        self.assertIsNone(check(rows, consumed_dates=['2026-10-19'], as_of='2026-10-20T15:01:00+08:00'))
        self.assertIsNone(check(rows, consumed_dates=['2026-04-20'], as_of='2026-10-19T16:00:00+08:00'))
        self.assertIsNone(check(rows[1:], as_of='2026-10-21T15:01:00+08:00'))


@unittest.skipUnless((BASE / 'parent/proposed-two-stock-scope.json').exists(),
                     'approved archived pilot evidence is not on this machine')
class ArchivedRepairTests(PriceConflictRulesTests):
    def manifest(self):
        return self.module().build_manifest(
            BASE / 'parent/proposed-two-stock-scope.json',
            PILOT / 'frozen-production-windows.json',
            PILOT / 'current-source-pilot-result.json',
            BASE / 'parent/independent-close-anchors.json',
            created_at='2026-10-20T07:00:00Z')

    def database(self, manifest):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'private.sqlite'
        with sqlite3.connect(str(path)) as conn:
            conn.execute('CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, '
                         'asset_type TEXT, exchange TEXT, code TEXT, name TEXT, updated_at TEXT)')
            columns = manifest['targets'][0]['old_window'][0]
            conn.execute('CREATE TABLE bars_day (' + ','.join(
                '"{}" {}'.format(k, 'TEXT' if k in ('ts','adjustment','source_batch',
                    'ingest_run_id','updated_at','volume_unit','volume_raw_unit',
                    'volume_source','amount_unit','amount_source') else 'REAL') for k in columns)
                + ', PRIMARY KEY(instrument_id,ts))')
            for target in manifest['targets']:
                ident = target['identity']
                conn.execute('INSERT INTO instruments VALUES (?,?,?,?,?,?)',
                    tuple(ident[k] for k in ('instrument_id','asset_type','exchange','code','name','updated_at')))
                for row in target['old_window']:
                    conn.execute('INSERT INTO bars_day ('+','.join(row)+') VALUES ('+
                                 ','.join('?' for _ in row)+')', tuple(row.values()))
        return path

    def test_real_94_scope_and_unknown_quantity_preserved(self):
        m = self.module()
        manifest = self.manifest()
        self.assertEqual(sum(len(t['changes']) for t in manifest['targets']), 94)
        self.assertEqual(m.validate_manifest(manifest)['sha256'], manifest['sha256'])
        for target in manifest['targets']:
            self.assertEqual(len(target['old_window']), 120)
            self.assertEqual(target['diagnostic']['category'], 'anchor_contaminated')
            for change in target['changes']:
                if change['old']['is_final']:
                    self.assertTrue(set(change['fields']) <= set(m.PRICE_FIELDS) | {'source_batch','updated_at'})
                else:
                    self.assertEqual(change['new']['volume_unit'], 'unknown')
                    self.assertEqual(change['new']['amount_available'], 0)
                    self.assertEqual(change['new']['amount_source'], '')

    def test_manifest_tampering_missing_day_identity_and_quantity_are_rejected(self):
        m = self.module()
        manifest = self.manifest()
        for mutation in (
                lambda x: x['targets'][0]['changes'][0]['new'].update(code='600050'),
                lambda x: x['targets'][0]['old_window'].pop(),
                lambda x: x['targets'][0]['identity'].update(exchange='SZ'),
                lambda x: x['targets'][0]['changes'][1]['new'].update(volume=1),
                lambda x: x['targets'][0]['changes'][1]['new'].update(close=1),
                lambda x: x['targets'][0]['diagnostic'].update(category='event_rebase_required')):
            value = copy.deepcopy(manifest)
            mutation(value)
            value['sha256'] = m.content_sha256({k:v for k,v in value.items() if k != 'sha256'})
            with self.assertRaises(ValueError):
                m.validate_manifest(value)

    def test_dry_run_single_stock_apply_idempotence_and_old_window_cas(self):
        m = self.module()
        manifest = self.manifest()
        path = self.database(manifest)
        original = path.read_bytes()
        self.assertEqual(m.apply_manifest(path, manifest)['status'], 'dry_run')
        self.assertEqual(path.read_bytes(), original)
        first = manifest['targets'][0]['identity_key']
        result = m.apply_manifest(path, manifest, apply=True, identity_keys=[first],
            backup_dir=path.parent/'backup', lock_path=path.parent/'publish.lock', expected_sha256=manifest['sha256'])
        self.assertEqual(result['targets'][0]['status'], 'applied')
        result = m.apply_manifest(path, manifest, apply=True, identity_keys=[first],
            backup_dir=path.parent/'backup', lock_path=path.parent/'publish.lock', expected_sha256=manifest['sha256'])
        self.assertEqual(result['targets'][0]['status'], 'already_applied')
        second = manifest['targets'][1]
        with sqlite3.connect(str(path)) as conn:
            conn.execute('UPDATE bars_day SET volume=volume+1 WHERE instrument_id=? AND ts=?',
                         (second['identity']['instrument_id'], second['old_window'][0]['ts']))
        with self.assertRaisesRegex(ValueError, 'cas'):
            m.apply_manifest(path, manifest, apply=True, identity_keys=[second['identity_key']],
                backup_dir=path.parent/'backup', lock_path=path.parent/'publish.lock', expected_sha256=manifest['sha256'])

    def test_no_lock_and_outside_scope_cannot_apply(self):
        m = self.module()
        manifest = self.manifest()
        path = self.database(manifest)
        for kwargs in ({'apply': True, 'backup_dir': path.parent/'backup'},
                       {'identity_keys': ['stock|SH|600050']}):
            with self.assertRaises(ValueError):
                m.apply_manifest(path, manifest, **kwargs)

    def test_latest_tail_and_reviewed_digest_guard(self):
        m, manifest = self.module(), self.manifest()
        path = self.database(manifest)
        args = dict(apply=True, backup_dir=path.parent/'backup', lock_path=path.parent/'lock')
        with self.assertRaisesRegex(ValueError, 'reviewed_manifest'):
            m.apply_manifest(path, manifest, expected_sha256='wrong', **args)
        with sqlite3.connect(str(path)) as conn:
            row = dict(manifest['targets'][0]['old_window'][-1], ts='2026-10-20')
            conn.execute('INSERT INTO bars_day ('+','.join(row)+') VALUES ('+
                         ','.join('?' for _ in row)+')', tuple(row.values()))
        with self.assertRaisesRegex(ValueError, 'unapproved_tail'):
            m.apply_manifest(path, manifest, expected_sha256=manifest['sha256'], **args)

    def test_transaction_and_independent_readback_failure_restore_old_rows(self):
        m, manifest = self.module(), self.manifest()
        path = self.database(manifest)
        args = dict(apply=True, backup_dir=path.parent/'backup', lock_path=path.parent/'lock',
                    expected_sha256=manifest['sha256'], identity_keys=[manifest['targets'][0]['identity_key']])
        original_write = m._write_rows
        def broken_write(conn, target, rows):
            original_write(conn, target, rows)
            raise ValueError('injected_write_failure')
        with patch.object(m, '_write_rows', side_effect=broken_write):
            with self.assertRaisesRegex(ValueError, 'injected_write_failure'):
                m.apply_manifest(path, manifest, **args)
        self.assertEqual(m.apply_manifest(path, manifest)['targets'][0]['status'], 'ready')
        original_read = m._read_window
        calls = [0]
        def broken_read(conn, target):
            calls[0] += 1
            # preflight, write CAS, transactional readback, independent readback
            if calls[0] == 4:
                raise ValueError('injected_readback_failure')
            return original_read(conn, target)
        with patch.object(m, '_read_window', side_effect=broken_read):
            with self.assertRaisesRegex(ValueError, 'injected_readback_failure'):
                m.apply_manifest(path, manifest, **args)
        self.assertEqual(m.apply_manifest(path, manifest)['targets'][0]['status'], 'ready')

    def test_parent_inherited_lock_and_other_owner_lock(self):
        m, manifest = self.module(), self.manifest()
        path = self.database(manifest)
        lock = path.parent/'lock'
        descriptor = os.open(str(lock), os.O_CREAT|os.O_RDWR, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX|fcntl.LOCK_NB)
        args = dict(apply=True, backup_dir=path.parent/'backup', lock_path=lock,
                    expected_sha256=manifest['sha256'])
        with self.assertRaises(BlockingIOError):
            m.apply_manifest(path, manifest, **args)
        self.assertEqual(m.apply_manifest(path, manifest, lock_fd=descriptor, **args)['status'], 'applied')


class PortableRepairTests(ArchivedRepairTests):
    """Explicitly synthetic prices; no market history or external files required."""
    __unittest_skip__ = False

    def setUp(self):
        m = self.module()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Only the approved calendar is shared with the real test. Prices, IDs
        # and source archives below are generated synthetic evidence.
        from datetime import date, timedelta
        dates = []
        current = date(2026,4,21)
        omitted = {'2026-05-01','2026-06-19','2026-05-04','2026-05-05',
                   '2026-10-01','2026-10-02','2026-10-05','2026-10-06','2026-10-07','2026-10-08'}
        while current <= date(2026,10,19):
            if current.weekday() < 5 and current.isoformat() not in omitted:
                dates.append(current.isoformat())
            current += timedelta(days=1)
        self.assertEqual(len(dates),120)
        scoped, frozen, pilot, approved = [], [], [], {}
        for n,(exchange, code) in enumerate((('SH','600063'),('SZ','000070'))):
            iid = 100+n
            identity = dict(instrument_id=iid, asset_type='stock', exchange=exchange,
                            code=code, name='synthetic', updated_at='2026-10-19T08:00:00Z')
            source = [dict(ts=d, open=10., close=10.1, high=10.2, low=9.9, volume=100.) for d in dates]
            old = []
            for row in source:
                factor = 10.1/10.1 if row['ts'] <= '2026-08-06' else 10.1/10.2
                r = dict(instrument_id=iid, ts=row['ts'], **{k:row[k]*factor for k in m.PRICE_FIELDS},
                         volume=90. if row['ts']=='2026-08-06' else 100., amount=1000000.,
                         adjustment='qfq', is_final=int(row['ts']!='2026-08-06'),
                         source_batch='synthetic_frozen', ingest_run_id=None,
                         updated_at='2026-10-19T08:00:00Z', volume_unit='hands', volume_raw_unit='hands',
                         volume_source='synthetic', amount_unit='CNY', amount_source='synthetic', amount_available=1)
                if row['ts']=='2026-08-06':
                    row['close']=10.2
                    row['high']=10.2
                    r.update(close=10.2, high=10.2)
                old.append(r)
            h=m.content_sha256(old)
            approved['stock|'+exchange+'|'+code]=(iid,h)
            raw_path=self.root/(code+'.json')
            raw_lines=[[r['ts'],r['open'],r['close'],r['high'],r['low'],r['volume']] for r in source]
            raw_lines=[['2026-04-20',10.,10.,10.,10.,100.]]+raw_lines+[['2026-10-20',10.,10.,10.,10.,100.]]
            raw_path.write_text(json.dumps(dict(code=0,data={exchange.lower()+code:dict(qfqday=raw_lines)})))
            pilot.append(dict(identity=identity,raw_response_file=str(raw_path),
                raw_response_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),fetched_at='2026-10-20T04:00:00Z'))
            frozen.append(dict(identity=identity,window_rows=old))
            scoped.append(dict(identity=identity,rows=[dict(date=r['ts'],old_row=r,
                proposed_price_fields={k:s[k] for k in m.PRICE_FIELDS}) for r,s in zip(old,source) if r['ts']>='2026-08-06']))
        anchors=[]
        for ds,provider in (('2026-10-14','sina'),('2026-10-16','eastmoney'),('2026-10-19','sina')):
            raw_path=self.root/(ds+'.json')
            quotes=[dict(asset_type='stock',exchange=ex,code=code,open=10.,high=10.2,low=9.9,current_price=10.1,
                         quote_asof=ds+'T15:05:00+08:00',quote_source=provider,quote_status='valid',
                         price_basis='raw' if provider=='sina' else None) for ex,code in (('SH','600063'),('SZ','000070'))]
            raw_path.write_text(json.dumps(dict(rows=quotes)))
            anchors.append(dict(path=str(raw_path),file_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),date=ds))
        values=dict(scope=dict(targets=scoped),frozen=dict(targets=frozen),pilot=dict(pending=pilot),anchors=anchors)
        self.paths={}
        hashes={}
        for key,value in values.items():
            path=self.root/(key+'.json');path.write_text(json.dumps(value));self.paths[key]=path
            hashes[key]=hashlib.sha256(path.read_bytes()).hexdigest()
        for name,value in (('INPUT_HASHES',hashes),('APPROVED',approved)):
            patcher=patch.object(m,name,value);patcher.start();self.addCleanup(patcher.stop)

    def manifest(self):
        return self.module().build_manifest(*(self.paths[k] for k in ('scope','frozen','pilot','anchors')),
                                             created_at='2026-10-20T07:00:00Z')

    def test_raw_archive_modification_fails_even_with_self_updated_manifest_digest(self):
        m, manifest = self.module(), self.manifest()
        raw = Path(manifest['targets'][0]['source_evidence']['path'])
        raw.write_text(raw.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'):
            m.validate_manifest(manifest)


class PortableRepair96Tests(PortableRepairTests):
    """Synthetic 96-row extension, with a separately approved closing quote."""
    def setUp(self):
        super().setUp()
        m = self.module()
        self.assertTrue(hasattr(m, 'build_manifest_96'), '96 approval requires a distinct builder')
        base=self.manifest()
        self.quotes=[]
        extra=[]
        approved={}
        for target in base['targets']:
            old=dict(target['old_window'][-1],ts='2026-10-20',updated_at='2026-10-20T07:06:00Z',
                     source_batch='official_close_snapshot:sina')
            quote=dict(asset_type='stock',exchange=target['identity']['exchange'],code=target['identity']['code'],
                       open=10.,high=10.2,low=9.9,current_price=10.1,prev_close=10.1,
                       quote_source='sina',price_basis='raw',quote_status='valid',
                       quote_asof='2026-10-20T15:00:00+08:00',fetched_at='2026-10-20T15:06:00+08:00')
            self.quotes.append(quote)
            old_window=target['old_window']+[old]
            digest=m.content_sha256(old_window)
            approved[target['identity_key']]=(target['identity']['instrument_id'],digest)
            extra.append(dict(identity=target['identity'],date='2026-10-20',old_row=old,
                              source_raw_quote=quote,combined_121_old_rows=old_window,
                              combined_121_old_sha256=digest))
        self.tail_quotes=self.root/'tail-quotes.json'
        self.tail_quotes.write_text(json.dumps(dict(rows=self.quotes,fetched_at='2026-10-20T15:06:01+08:00')))
        quote_digest=hashlib.sha256(self.tail_quotes.read_bytes()).hexdigest()
        self.tail_scope=self.root/'tail-scope.json'
        self.tail_scope.write_text(json.dumps(dict(targets=extra,source_cache_sha256=quote_digest,
            captured_at_utc='2026-10-20T07:07:00Z',combined_if_separately_authorized=96)))
        hashes=dict(tail_scope=hashlib.sha256(self.tail_scope.read_bytes()).hexdigest(),tail_quotes=quote_digest)
        for name,value in (('TAIL_INPUT_HASHES',hashes),('APPROVED_96',approved)):
            patcher=patch.object(m,name,value);patcher.start();self.addCleanup(patcher.stop)

    def manifest96(self):
        return self.module().build_manifest_96(*(self.paths[k] for k in ('scope','frozen','pilot','anchors')),
            tail_scope_path=self.tail_scope,tail_quotes_path=self.tail_quotes,created_at='2026-10-20T08:00:00Z')

    def test_96_is_explicit_and_extends_only_two_closed_price_rows(self):
        m,manifest=self.module(),self.manifest96()
        self.assertEqual(manifest['total_changes'],96)
        self.assertNotEqual(manifest['schema'],self.manifest()['schema'])
        self.assertEqual(m.validate_manifest(manifest),manifest)
        keys=('volume','volume_unit','volume_raw_unit','volume_source','amount','amount_available',
              'amount_unit','amount_source','is_final','ingest_run_id')
        for target in manifest['targets']:
            self.assertEqual(len(target['old_window']),121)
            self.assertEqual(len(target['changes']),48)
            last=target['changes'][-1]
            self.assertEqual(last['date'],'2026-10-20')
            self.assertIn(':sina:',last['new']['source_batch'])
            self.assertEqual({k:last['old'][k] for k in keys},{k:last['new'][k] for k in keys})
            self.assertEqual(last['new']['close'],10.1)

    def test_96_apply_old94_rejected_idempotent_and_21_tail_rejected(self):
        m,manifest=self.module(),self.manifest96()
        path=self.database(manifest)
        with self.assertRaisesRegex(ValueError,'unapproved_tail'):
            m.apply_manifest(path,self.manifest())
        args=dict(apply=True,backup_dir=path.parent/'backups',lock_path=path.parent/'lock',expected_sha256=manifest['sha256'])
        result=m.apply_manifest(path,manifest,**args)
        self.assertEqual([r['rows'] for r in result['targets']],[48,48])
        result=m.apply_manifest(path,manifest,**args)
        self.assertEqual([r['status'] for r in result['targets']],['already_applied']*2)
        with sqlite3.connect(str(path)) as conn:
            row=dict(manifest['targets'][0]['new_window'][-1],ts='2026-10-21')
            conn.execute('INSERT INTO bars_day ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        with self.assertRaisesRegex(ValueError,'unapproved_tail'):
            m.apply_manifest(path,manifest)

    def test_96_quote_contract_requires_closed_raw_identity_previous_close_and_exact_old_chain(self):
        m,manifest=self.module(),self.manifest96()
        t=manifest['targets'][0]
        args=(t['identity'],t['new_window'][-2],t['old_window'][-2],t['old_window'][-1])
        kwargs=dict(created_at=manifest['created_at'],cache_fetched_at='2026-10-20T15:06:01+08:00')
        for key,value,reason in (('prev_close',99.,'previous_close'),
                                ('quote_asof','2026-10-20T14:59:59+08:00','closed'),
                                ('quote_source','tencent','source'),
                                ('price_basis','qfq','basis'),
                                ('code','600050','identity'),
                                ('fetched_at','2026-10-20T14:59:00+08:00','timestamp')):
            quote=dict(self.quotes[0],**{key:value})
            with self.subTest(field=key),self.assertRaisesRegex(ValueError,reason):
                m._validate_tail_quote(quote,*args,**kwargs)
        old=dict(t['old_window'][-1],close=9.)
        with self.assertRaisesRegex(ValueError,'chain'):
            m._validate_tail_quote(self.quotes[0],t['identity'],t['new_window'][-2],t['old_window'][-2],old,**kwargs)

    def test_96_cas_and_failed_readback_restore_all_121_rows(self):
        m,manifest=self.module(),self.manifest96()
        path=self.database(manifest)
        original=m._read_window
        calls=[0]
        first=manifest['targets'][0]
        def fail_independent(conn,target):
            calls[0]+=1
            if calls[0]==4:raise ValueError('96_readback_injected')
            return original(conn,target)
        args=dict(apply=True,backup_dir=path.parent/'backups',lock_path=path.parent/'lock',
                  expected_sha256=manifest['sha256'],identity_keys=[first['identity_key']])
        with patch.object(m,'_read_window',side_effect=fail_independent):
            with self.assertRaisesRegex(ValueError,'96_readback_injected'):
                m.apply_manifest(path,manifest,**args)
        self.assertEqual(m.apply_manifest(path,manifest)['targets'][0]['status'],'ready')
        with sqlite3.connect(str(path)) as conn:
            conn.execute('UPDATE bars_day SET amount=amount+1 WHERE instrument_id=? AND ts=?',
                         (first['identity']['instrument_id'],'2026-10-20'))
        with self.assertRaisesRegex(ValueError,'cas_full_window_changed'):
            m.apply_manifest(path,manifest,**args)


class ConsumerRepairTests(unittest.TestCase):
    def test_price_repair_provenance_preserves_legacy_quantity_contract(self):
        from chanlun.market_history_store import _decorate_legacy_bar
        from urllib.parse import quote
        row = dict(ts='2026-08-07', volume=10000., volume_unit='unknown', volume_raw_unit='unknown',
                   volume_source='', amount=100000., amount_unit='unknown', amount_source='', amount_available=1)
        marker = 'price_basis_repair:v1:2026-04-21:2026-10-19:20261020T070000Z:tencent:'+'a'*64
        keys = ('volume','volume_unit','volume_raw_unit','volume_source','amount','amount_available','amount_unit','amount_source')
        for source in ('ongoing:sina','official_close_snapshot:eastmoney','opaque_old_batch'):
            before = _decorate_legacy_bar(dict(row,source_batch=source))
            after = _decorate_legacy_bar(dict(row,source_batch=marker+'|quantity_source='+quote(source,safe='')))
            self.assertEqual({k:before[k] for k in keys}, {k:after[k] for k in keys})
        bad = _decorate_legacy_bar(dict(row,source_batch='price_basis_repair:broken|quantity_source=eastmoney'))
        self.assertEqual(bad['volume_unit'],'unknown')
        self.assertEqual(bad['volume'],10000.)

    def test_existing_nonfinal_maintenance_reports_conflict_without_any_write(self):
        from tests.test_daily_nonfinal_repair import DailyNonfinalRepairTests, payload, dates
        from chanlun.kline_repository import DailyRepairBudget
        fixture = DailyNonfinalRepairTests('test_zero_budget_no_http')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = fixture.rows()
        def source(identity, count, *, request_budget):
            request_budget.take_request()
            result = payload(identity.code, dates(count))
            result['closes'][0] = 10.01
            return result
        result = fixture.repo.repair_daily_nonfinal('2026-09-30', providers=[('eastmoney',source)],
            budget=DailyRepairBudget(max_stocks=1,max_requests=1))
        self.assertEqual(fixture.rows(), before)
        diagnostic = result['diagnostics']['pending'][0]['price_conflicts'][0]
        self.assertEqual(diagnostic['category'], 'unexplained')
        self.assertFalse(diagnostic['write_authorized'])

    def test_quantity_only_conflict_is_not_a_price_classification(self):
        from tests.test_daily_nonfinal_repair import DailyNonfinalRepairTests, payload, dates
        from chanlun.kline_repository import DailyRepairBudget
        fixture = DailyNonfinalRepairTests('test_zero_budget_no_http')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = fixture.rows()
        def source(identity,count,*,request_budget):
            request_budget.take_request()
            result=payload(identity.code,dates(count));result['volumes'][0]=123456.
            return result
        result=fixture.repo.repair_daily_nonfinal('2026-09-30',providers=[('eastmoney',source)],
            budget=DailyRepairBudget(max_stocks=1,max_requests=1))
        self.assertEqual(fixture.rows(),before)
        self.assertNotIn('price_conflicts',result['diagnostics']['pending'][0])

    def test_actual_daily_repository_and_qualification_refuse_future_repair_version(self):
        from tests.test_daily_nonfinal_repair import DailyNonfinalRepairTests
        from chanlun.market_history_store import MarketHistoryStore
        from chanlun.universe_builder import load_eligible_candidates
        fixture=DailyNonfinalRepairTests('test_zero_budget_no_http');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        marker='price_basis_repair:v1:2026-04-21:2026-10-19:20261020T070000Z:tencent:'+'a'*64+'|quantity_source=synthetic'
        with MarketHistoryStore(fixture.path) as store:
            store.connection.execute('UPDATE bars_day SET source_batch=? WHERE instrument_id=(SELECT instrument_id FROM instruments WHERE code=?)',
                                     (marker,'600000'));store.connection.commit()
        result=fixture.repo.get('day','600000',60,required_date='2026-09-30',as_of='2026-09-30T15:30:00+08:00')
        self.assertEqual(result.status,'price_basis_unverified')
        self.assertEqual(result.kline['_data_status']['degraded_reason'],'price_basis_repair_not_known_as_of')
        with MarketHistoryStore(fixture.path,readonly=True) as store:
            values,diag=load_eligible_candidates(store,'2026-09-30',60,0,minimum_bars=60,
                required_date='2026-09-30',return_diagnostics=True)
        self.assertNotIn('600000',[r['code'] for r in values])
        self.assertEqual(diag['excluded']['price_basis_unverified'],1)

    def test_historical_producer_does_not_persist_a_receipt_for_future_repair(self):
        from tests.test_minute_basis_receipts import MinuteBasisReceiptTests
        from chanlun.market_history_store import MarketHistoryStore
        from chanlun.identity import normalize_identity
        fixture=MinuteBasisReceiptTests('test_restarted_repository_verifies_persisted_receipt_without_fetch')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        marker='price_basis_repair:v1:2026-04-21:2026-10-19:20261020T070000Z:tencent:'+'a'*64+'|quantity_source=synthetic'
        with MarketHistoryStore(fixture.path) as store:
            store.connection.execute('UPDATE bars_day SET source_batch=? WHERE instrument_id=?',(marker,fixture.iid))
            store.connection.commit()
        result=fixture.get()
        self.assertEqual(result.kline['minute_to_daily']['status'],'pending')
        self.assertEqual(fixture.repo._load_basis_receipts(normalize_identity('301377'),'30m'),{})


if __name__ == '__main__':
    unittest.main()
