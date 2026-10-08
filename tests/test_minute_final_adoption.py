"""Synthetic complete-source windows through real repository and batch consumers."""
import copy
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from chanlun import data_fetcher as df
from chanlun.minute_sources import clean_minutes
from chanlun.kline_repository import KLineRepository
from chanlun.market_history_store import MarketHistoryStore

DAY='2026-09-23'


class MinuteFinalAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'market.sqlite'
        self.raw={};self.calls=[];self.reference_calls=[]
        self.scale=30

    def seed(self,scale=30,bars=80):
        self.scale=scale
        days=[];current=date.fromisoformat(DAY)
        while len(days)<(bars+240//scale-1)//(240//scale):
            if current.weekday()<5:days.append(current.isoformat())
            current-=timedelta(days=1)
        rows=[]
        for day in reversed(days):
            self.raw[day]=dict(open=10.,high=10.3,low=9.8,close=10.1,is_final=True,source='frozen_raw')
            for start in (570,780):
                for minute in range(start+scale,start+121,scale):
                    rows.append(dict(day=day+' %02d:%02d:00'%(minute//60,minute%60),
                        open='10',high='10.3',low='9.8',close='10.1',volume='10000',amount='101000'))
        self.good=clean_minutes(rows,source='sina',symbol='sz301377',scale=scale)
        self.bad=copy.deepcopy(self.good);self.bad['highs'][:]=10.4
        with MarketHistoryStore(self.path) as store:
            iid=store.upsert_instrument('stock','SZ','301377')
            store.upsert_bars('day',iid,[dict(r,ts=day,adjustment='qfq',volume=800,
                amount=808000,source_batch='frozen_target',volume_unit='hands') for day,r in self.raw.items()],adjustment='qfq')
        def raw_reader(*a):
            self.reference_calls.append(a);return copy.deepcopy(self.raw)
        self.repo=KLineRepository(self.path,remote_fetchers={str(scale)+'m':
            df._fetch_30min_for_repository if scale==30 else df._fetch_15min_for_repository},raw_daily_reader=raw_reader)

    def providers(self,items):
        def factory(*a):
            sources=[]
            for name,value in items:
                def source(*args,_name=name,_value=value,**kwargs):
                    self.calls.append(_name);return copy.deepcopy(_value)
                sources.append((name,source))
            return sources
        return factory

    def get(self,items,count=80):
        with patch.object(df,'_minute_providers',self.providers(items)), \
             patch.object(df,'_fetch_minute_for_repository',wraps=df._fetch_minute_for_repository) as fetch:
            # Existing backoff is retained in production, disabled only here.
            original=fetch._mock_wraps
            fetch.side_effect=lambda *a,**kw:original(*a,**kw,sleep_fn=lambda _:None)
            return self.repo.get(str(self.scale)+'m','301377',count,required_date=DAY,as_of=DAY+'T15:05:00+08:00')

    def test_first_basis_failure_then_next_verified_and_refs_loaded_once(self):
        self.seed()
        result=self.get([('sina',self.bad),('tencent',self.good)])
        self.assertEqual(result.status,'verified');self.assertEqual(self.calls,['sina','tencent'])
        self.assertEqual(len(self.reference_calls),1)
        evidence=df._sublevel_input_evidence('30m',result.kline,result)
        self.assertTrue(evidence['final_adopted']);self.assertEqual(evidence['rejection_reason'],'')
        self.assertEqual(evidence['attempt_evidence'][0]['reason'],'raw_daily_conflict:'+min(self.raw))
        self.assertNotIn('price_basis_failure',result.diagnostics)

    def test_first_verified_no_second_source_or_extra_reference(self):
        self.seed();result=self.get([('tencent',self.good),('sina',self.bad)])
        self.assertEqual(result.status,'verified');self.assertEqual(self.calls,['tencent'])
        self.assertEqual(len(self.reference_calls),1)
        self.calls.clear();self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
        self.assertEqual(self.calls,[])

    def test_all_final_fail_bounded_readonly_and_specific_batch_causes(self):
        import run
        for scale,bars in ((30,80),(15,220)):
            with self.subTest(scale=scale):
                self.path=Path(self.tmp.name)/('market'+str(scale)+'.sqlite');self.raw={};self.calls=[]
                self.seed(scale,bars)
                result=self.get([('sina',self.bad),('tencent',self.bad)],bars)
                self.assertEqual(len(self.calls),4);self.assertEqual(result.status,'price_basis_unverified')
                with MarketHistoryStore(self.path,readonly=True) as store:
                    self.assertEqual(store.query_bars(str(scale)+'m',1),[])
                self.calls.clear();failure={}
                batch=df.batch_fetch_30min_klines if scale==30 else df.batch_fetch_15min_klines
                original=df._fetch_minute_for_repository
                with patch.object(df,'_get_kline_repository',return_value=self.repo), \
                     patch.object(df,'_minute_providers',self.providers([('sina',self.bad),('tencent',self.bad)])), \
                     patch.object(df,'_fetch_minute_for_repository',side_effect=lambda *a,**kw:original(*a,**kw,sleep_fn=lambda _:None)):
                    rows=batch([dict(code='301377',asset_type='stock',exchange='SZ')],required_date=DAY,
                        as_of=DAY+'T15:05:00+08:00',failure_evidence=failure)
                self.assertEqual(rows,[]);self.assertEqual(len(self.calls),4)
                record=failure['stock|SZ|301377']
                self.assertTrue(record['rejection_reason'].startswith('raw_daily_conflict:'))
                health=run._build_sublevel_input_health(str(scale)+'m',[{'code':'301377'}],rows,DAY,failure)
                self.assertEqual(health['failure_evidence']['301377']['rejection_reason'],record['rejection_reason'])

    def test_attempt_cap_one_and_legacy_fetchers_cannot_bypass_validation(self):
        self.seed()
        validator=self.repo._minute_final_validator('30m',self.repo._identity('301377'),80,DAY,DAY+'T15:05:00+08:00')
        def check(p):validator(p);return p
        with patch.object(df,'_minute_providers',self.providers([('sina',self.bad),('tencent',self.good)])):
            value=df._fetch_minute_for_repository('301377',30,80,required_date=DAY,
                as_of=DAY+'T15:05:00+08:00',final_validator=check,max_attempts=1,sleep_fn=lambda _:None)
        self.assertEqual(self.calls,['sina']);self.assertFalse(value['_fetch_diagnostics']['final_adopted'])
        for custom in (lambda code,count:self.bad,
                       lambda code,count,required_date=None,as_of=None:self.bad,
                       lambda code,count,**kwargs:self.bad):
            self.repo.remote_fetchers['30m']=custom
            result=self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
            self.assertNotEqual(result.status,'verified')

    def test_ignored_callback_and_self_declared_free_qfq_never_written(self):
        self.seed()
        forged=copy.deepcopy(self.good);forged['adjustment']='qfq'
        self.repo.remote_fetchers['30m']=lambda code,count,**kwargs:forged
        result=self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
        self.assertNotEqual(result.status,'verified')
        self.assertEqual(result.diagnostics['price_basis_failure'],'already_adjusted_or_invalid_scale')
        self.repo.raw_daily_reader=None
        result=self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
        self.assertNotEqual(result.status,'verified')
        with MarketHistoryStore(self.path,readonly=True) as store:
            self.assertEqual(store.query_bars('30m',1),[])

    def test_invalid_first_windows_and_reference_failures_cannot_adopt(self):
        self.seed()
        for label, change in (
            ('identity',lambda p:p.update(symbol='sz000001')),
            ('unit',lambda p:p.update(volume_unit='unknown')),
            ('nonfinal',lambda p:p['finals'].__setitem__(0,False)),
            ('date',lambda p:p['dates'].__setitem__(-1,DAY+' 14:30:00')),
            ('closed_day',lambda p:p['dates'].__setitem__(0,p['dates'][0].replace('10:00','09:45')))):
            with self.subTest(label=label):
                bad=copy.deepcopy(self.good);change(bad)
                self.calls=[]
                result=self.get([('sina',bad),('tencent',self.good)])
                self.assertEqual(result.status,'verified')
                self.assertEqual(self.calls,['sina','tencent'])
                # Remove only this isolated test's minute cache before next input.
                with MarketHistoryStore(self.path) as store:
                    store.connection.execute('DELETE FROM bars_30m');store.connection.commit()
                self.repo._memory.clear()

    def test_no_false_legacy_typeerror_retry(self):
        self.seed();calls=[]
        def broken(code,count):
            calls.append(code);raise TypeError('internal error')
        self.repo.remote_fetchers['30m']=broken
        result=self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
        self.assertEqual(len(calls),1);self.assertNotEqual(result.status,'verified')

    def test_legacy_verified_qfq_custom_fetcher_keeps_existing_behavior(self):
        self.seed();calls=[]
        value=copy.deepcopy(self.good);value.pop('schema');value['adjustment']='qfq'
        def old(code,count):calls.append(code);return value
        self.repo.remote_fetchers['30m']=old
        result=self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
        self.assertEqual(result.status,'verified');self.assertEqual(len(calls),1)

    def test_missing_raw_reference_is_loaded_once_and_raw_remains_readable(self):
        self.seed();calls=[]
        def missing(*a):
            calls.append(a);raise ValueError('missing_raw_daily_reference')
        self.repo.raw_daily_reader=missing
        result=self.get([('sina',self.good),('tencent',self.good)])
        self.assertEqual(len(calls),1)
        self.assertEqual(result.status,'price_basis_unverified')
        self.assertEqual(len(result.kline['dates']),80)
        self.assertEqual(result.diagnostics['price_basis_failure'],'missing_raw_daily_reference')
        with MarketHistoryStore(self.path,readonly=True) as store:
            self.assertEqual(store.query_bars('30m',1),[])

    def test_empty_and_nonmapping_reference_failures_are_controlled(self):
        self.seed()
        for value in ({},None,[],{DAY:42}):
            with self.subTest(value=value):
                calls=[]
                def reader(*a):calls.append(a);return value
                self.repo.raw_daily_reader=reader
                result=self.get([('sina',self.good),('tencent',self.good)])
                self.assertEqual(len(calls),1)
                self.assertEqual(result.status,'price_basis_unverified')
                self.assertIn(result.diagnostics['price_basis_failure'],('missing_raw_daily_reference','invalid_raw_daily_reference'))

    def test_same_window_success_reaches_both_batch_consumers(self):
        import run
        for scale,bars in ((30,80),(15,220)):
            with self.subTest(scale=scale):
                self.path=Path(self.tmp.name)/('success'+str(scale)+'.sqlite');self.raw={};self.calls=[]
                self.seed(scale,bars)
                original=df._fetch_minute_for_repository;failures={}
                with patch.object(df,'_get_kline_repository',return_value=self.repo), \
                     patch.object(df,'_minute_providers',self.providers([('sina',self.bad),('tencent',self.good)])), \
                     patch.object(df,'_fetch_minute_for_repository',side_effect=lambda *a,**kw:original(*a,**kw,sleep_fn=lambda _:None)):
                    batch=df.batch_fetch_30min_klines if scale==30 else df.batch_fetch_15min_klines
                    stocks=[dict(code='301377',asset_type='stock',exchange='SZ')]
                    rows=batch(stocks,required_date=DAY,as_of=DAY+'T15:05:00+08:00',failure_evidence=failures)
                self.assertEqual(self.calls,['sina','tencent']);self.assertEqual(len(rows),1)
                self.assertTrue(rows[0]['input_evidence']['final_adopted'])
                self.assertEqual(rows[0]['input_evidence']['rejection_reason'],'')
                self.assertEqual(failures,{})
                self.assertEqual(run._build_sublevel_input_health(str(scale)+'m',stocks,rows,DAY,failures)['status'],'verified')

    def test_legacy_raw_complete_window_remains_readonly_single_call(self):
        self.seed();calls=[]
        value=copy.deepcopy(self.good);value.pop('schema');value['adjustment']='raw'
        def old(code,count):calls.append(code);return value
        self.repo.remote_fetchers['30m']=old
        result=self.repo.get('30m','301377',80,required_date=DAY,as_of=DAY+'T15:05:00+08:00')
        self.assertEqual(result.status,'price_basis_unverified')
        self.assertEqual(len(result.kline['dates']),80);self.assertEqual(len(calls),1)
        with MarketHistoryStore(self.path,readonly=True) as store:
            self.assertEqual(store.query_bars('30m',1),[])


if __name__=='__main__':unittest.main()
