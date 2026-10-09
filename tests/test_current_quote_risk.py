"""Synthetic offline producer/store/eligibility regressions for current quote risk."""
import hashlib
import copy
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import run as run_module
from chanlun.preclose_pipeline import PreclosePipelineConfig, run_preclose_pipeline

from chanlun.market_history_store import MarketHistoryStore
from chanlun.market_close_snapshot import ingest_market_close_snapshot
from chanlun.universe_builder import load_eligible_candidates
from chanlun.industry_metadata import hydrate_industry_metadata
from chanlun.preclose_runtime import _append_intraday_quote_with_reason, build_scheduled_preclose_input, MARKET_INDICES
from chanlun.data_fetcher import is_st_stock

DAY='2026-09-30'
PREVIOUS='2026-09-29'
CN=timezone(timedelta(hours=8))


def bar(ts):
    return dict(ts=ts,open=10,high=10.3,low=9.9,close=10,volume=100000,amount=100000000,
        volume_unit='hands',volume_raw_unit='hands',volume_source='fixture',amount_unit='CNY',
        amount_source='fixture',amount_available=True,adjustment='qfq',is_final=True,source_batch='fixture')


def quote(code, name=None, **changes):
    value=dict(code=code,exchange='SH',asset_type='stock',name=name or '普通'+code,
        is_st=False,delisting_risk=False,current_price=10,open=10,high=10.3,low=9.9,prev_close=10,
        volume=100000,amount=100000000,volume_unit='hands',volume_raw_unit='hands',volume_source='sina',
        amount_unit='CNY',amount_source='sina',amount_available=True,quote_source='sina',
        quote_asof=DAY+'T15:00:00+08:00')
    value.update(changes)
    return value


def indices():
    """Synthetic values in the actual fetch_preclose_indices output contract."""
    return {name:dict(code=code,date=DAY,source='tencent+tencent_plain_verified',
                     close=101.0,change_pct=1.0,closes=[100.0,101.0])
            for name,code in MARKET_INDICES.items()}


class CurrentQuoteRiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'market.sqlite'
        dates=[]; current=date.fromisoformat(PREVIOUS)
        while len(dates)<120:
            if current.weekday()<5: dates.append(current.isoformat())
            current-=timedelta(days=1)
        with MarketHistoryStore(self.path) as store:
            for code in ('600000','600001'):
                iid=store.upsert_instrument('stock','SH',code,name='普通'+code)
                store.upsert_stock_meta(iid,'2026-09-28',dict(name='普通'+code,is_st=False,
                    delisting_risk=False,listed_days=1000,market_cap=1234,industry='银行'))
                store.upsert_bars('day',iid,[bar(value) for value in reversed(dates)],adjustment='qfq')

    def tearDown(self): self.tmp.cleanup()

    def eligible(self, as_of=DAY):
        with MarketHistoryStore(self.path,readonly=True) as store:
            return load_eligible_candidates(store,as_of=as_of,required_date=as_of,
                min_listed_days=60,min_daily_amount=50000000,return_diagnostics=True)

    def ingest(self, rows):
        return ingest_market_close_snapshot(self.path,DAY,
            lambda **kw:(rows,{'complete':True,'requested':len(rows),'unique':len(rows)}),
            generated_at=datetime.fromisoformat(DAY+'T15:05:00+08:00'))

    def meta(self, code='600000', as_of=DAY):
        with MarketHistoryStore(self.path,readonly=True) as store:
            iid=store.resolve_instrument('stock','SH',code)['instrument_id']
            return store.query_stock_meta(iid,as_of)

    def test_real_close_to_eligibility_uses_today_st_and_keeps_healthy_stock(self):
        before,_=self.eligible(PREVIOUS)
        result=self.ingest([quote('600000','ST测试',is_st=True),quote('600001')])
        rows,diag=self.eligible()
        self.assertEqual([row['code'] for row in before],['600000','600001'])
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['written'],2)
        self.assertEqual(result['coverage'],1)
        self.assertEqual([row['code'] for row in rows],['600001'])
        self.assertEqual(diag['excluded']['st_or_delisting'],1)
        meta=self.meta()
        self.assertEqual(meta['name'],'ST测试')
        self.assertTrue(is_st_stock(meta['name']))
        self.assertIs(meta['is_st'],True)
        self.assertEqual(meta['listed_days'],1000)
        self.assertEqual(meta['market_cap'],1234)
        self.assertEqual(meta['industry'],'银行')
        self.assertEqual(meta['risk_source'],'sina')
        self.assertEqual(meta['risk_as_of'],DAY+'T15:00:00+08:00')
        self.assertEqual(meta['risk_status'],'verified')

    def test_industry_hydration_does_not_make_old_risk_current(self):
        with MarketHistoryStore(self.path) as store:
            iid=store.resolve_instrument('stock','SH','600000')['instrument_id']
            store.upsert_stock_meta(iid,'2026-09-28',dict(name='普通600000',is_st=False,
                delisting_risk=False,listed_days=1000,industry=''))
        result=hydrate_industry_metadata(self.path,DAY,lambda:[{'code':'600000','name':'ST新名','is_st':True,'industry':'银行'}])
        meta=self.meta()
        self.assertEqual(result['hydrated'],1)
        self.assertEqual(meta['as_of'],DAY)
        self.assertEqual(meta.get('risk_as_of'),'2026-09-28')
        self.assertEqual(meta['name'],'普通600000')
        self.assertIs(meta['is_st'],False)

    def test_preclose_unknown_is_not_false_and_explicit_delisting_is_excluded(self):
        candidate=self.eligible(PREVIOUS)[0][0]
        current=quote('600000',quote_asof=DAY+'T14:45:00+08:00')
        current.pop('is_st')
        value,reason=_append_intraday_quote_with_reason(candidate,current,DAY,DAY+'T14:45:00+08:00')
        self.assertEqual(reason,'')
        self.assertIsNone(value['is_st'])
        self.assertEqual(value['stock_meta_asof']['risk_status'],'unknown')
        current=quote('600000',delisting_risk=True,quote_asof=DAY+'T14:45:00+08:00')
        value,reason=_append_intraday_quote_with_reason(candidate,current,DAY,DAY+'T14:45:00+08:00')
        self.assertIsNone(value)
        self.assertEqual(reason,'st_or_delisting')

    def test_close_explicit_delisting_with_normal_name_is_still_excluded(self):
        result=self.ingest([quote('600000',delisting_risk=True),quote('600001')])
        rows,diag=self.eligible()
        self.assertEqual(result['coverage'],1)
        self.assertEqual([row['code'] for row in rows],['600001'])
        self.assertEqual(diag['excluded']['st_or_delisting'],1)

    def test_missing_flag_keeps_unknown_and_existing_eligibility(self):
        current=quote('600000');current.pop('is_st')
        self.ingest([current,quote('600001')])
        rows,diag=self.eligible()
        self.assertEqual([row['code'] for row in rows],['600000','600001'])
        self.assertIsNone(self.meta()['is_st'])
        self.assertEqual(self.meta()['risk_status'],'unknown')
        self.assertEqual(diag['risk_unknown_count'],1)

    def seed_positive(self, field):
        with MarketHistoryStore(self.path) as store:
            iid=store.resolve_instrument('stock','SH','600000')['instrument_id']
            with store.connection:
                store.connection.execute('DELETE FROM stock_meta_asof WHERE instrument_id=? AND as_of>=?',(iid,DAY))
            store.upsert_stock_meta(iid,'2026-09-28',dict(name='ST既有' if field=='is_st' else '普通600000',
                is_st=field=='is_st',delisting_risk=field=='delisting_risk',
                listed_days=1000,industry='银行',risk_status='verified',risk_source='sina',
                risk_as_of='2026-09-28T15:00:00+08:00'))

    def test_missing_current_flag_does_not_release_existing_positive(self):
        for field in ('is_st','delisting_risk'):
            with self.subTest(field=field):
                self.seed_positive(field)
                current=quote('600000');current.pop(field)
                self.ingest([current,quote('600001')])
                rows,diag=self.eligible()
                self.assertEqual([row['code'] for row in rows],['600001'])
                meta=self.meta()
                self.assertIsNone(meta[field])
                self.assertEqual(meta['risk_status'],'conflict')
                previous=meta['risk_conflicts'][0]
                self.assertEqual(previous['field'],field)
                self.assertEqual(previous['reason'],'previous_positive_not_cleared')
                self.assertEqual(previous['previous_as_of'],'2026-09-28T15:00:00+08:00')
                self.assertEqual(previous['previous_source'],'sina')
                self.assertEqual(diag['excluded']['risk_evidence_conflict'],1)
                self.ingest([current,quote('600001')])
                self.assertEqual([row['code'] for row in self.eligible()[0]],['600001'])

    def test_verified_false_can_release_corresponding_previous_positive(self):
        for field in ('is_st','delisting_risk'):
            with self.subTest(field=field):
                self.seed_positive(field)
                self.ingest([quote('600000'),quote('600001')])
                rows,_=self.eligible()
                self.assertEqual([row['code'] for row in rows],['600000','600001'])
                self.assertIs(self.meta()[field],False)
                self.assertEqual(self.meta()['risk_status'],'verified')
                self.assertFalse(self.meta().get('risk_conflicts'))
                historical,_=self.eligible(PREVIOUS)
                self.assertEqual([row['code'] for row in historical],['600001'])

    def test_same_day_positive_overwrite_keeps_captured_evidence_until_verified_false(self):
        for field in ('is_st','delisting_risk'):
            with self.subTest(field=field):
                self.seed_positive(field)
                self.ingest([quote('600000',**{field:True}),quote('600001')])
                current=quote('600000');current.pop(field)
                self.ingest([current,quote('600001')])
                self.assertEqual([row['code'] for row in self.eligible()[0]],['600001'])
                evidence=self.meta()['risk_conflicts'][0]
                self.assertEqual(evidence['previous_meta_as_of'],DAY)
                self.assertIs(evidence['previous_value'],True)
                self.ingest([current,quote('600001')])
                self.assertEqual([row['code'] for row in self.eligible()[0]],['600001'])
                self.ingest([quote('600000'),quote('600001')])
                self.assertEqual([row['code'] for row in self.eligible()[0]],['600000','600001'])

    def test_pending_positive_reads_the_same_historical_record_not_a_declared_claim(self):
        for change in ('future','wrong_identity','false_history','missing_history'):
            evidence=dict(field='is_st',reason='previous_positive_not_cleared',
                previous_meta_as_of='2026-09-28',previous_as_of='2026-09-28T15:00:00+08:00',
                previous_source='sina',previous_identity_key='stock|SH|600000')
            if change=='future': evidence.update(previous_meta_as_of='2026-10-09',previous_as_of='2026-10-09T15:00:00+08:00')
            elif change=='wrong_identity': evidence['previous_identity_key']='stock|SH|600001'
            elif change=='missing_history': evidence['previous_meta_as_of']='2026-09-27'
            with self.subTest(change=change), MarketHistoryStore(self.path) as store:
                iid=store.resolve_instrument('stock','SH','600000')['instrument_id']
                store.upsert_stock_meta(iid,DAY,dict(name='普通600000',is_st=None,delisting_risk=False,
                    listed_days=1000,industry='银行',risk_status='conflict',risk_source='sina',
                    risk_as_of=DAY+'T15:00:00+08:00',risk_conflict_reason='previous_positive_not_cleared',
                    risk_conflicts=[evidence]))
            with self.subTest(change=change):
                metadata=self.meta()
                self.assertEqual(metadata['risk_status'],'unknown')
                self.assertEqual(metadata['risk_conflicts'],[])

    def test_preclose_does_not_use_future_or_wrong_identity_previous_positive(self):
        candidate=self.eligible(PREVIOUS)[0][0]
        current=quote('600000',quote_asof=DAY+'T14:45:00+08:00');current.pop('is_st')
        for prior in (dict(as_of='2026-10-09',risk_as_of='2026-10-09T15:00:00+08:00',
                           is_st=True,delisting_risk=False,risk_source='sina',risk_status='verified'),
                      dict(as_of='2026-09-28',risk_as_of='2026-09-28T15:00:00+08:00',
                           code='600001',exchange='SH',asset_type='stock',is_st=True,
                           delisting_risk=False,risk_source='sina',risk_status='verified')):
            with self.subTest(prior=prior):
                value,reason=_append_intraday_quote_with_reason(dict(candidate,stock_meta_asof=prior),
                    current,DAY,DAY+'T14:45:00+08:00')
                self.assertEqual(reason,'')
                self.assertIsNone(value['is_st'])
                self.assertEqual(value['stock_meta_asof']['risk_status'],'unknown')

    def test_quote_flag_name_type_or_source_conflict_does_not_release(self):
        cases=[quote('600000','ST测试',is_st=False),
            quote('600000',is_st='false'),quote('600000',is_st=0),
            quote('600000',delisting_risk='true'),
            quote('600000',risk_source='tencent'),
            quote('600000',risk_as_of='2026-09-29T15:00:00+08:00')]
        for current in cases:
            with self.subTest(current=current):
                # Rechecked same-day quotes use the existing identity/coverage gate.
                self.ingest([current,quote('600001')])
                rows,diag=self.eligible()
                self.assertEqual([row['code'] for row in rows],['600001'])
                self.assertEqual(diag['excluded']['risk_evidence_conflict'],1)
                self.assertEqual(self.meta()['risk_status'],'conflict')

    def test_future_metadata_and_future_instrument_name_do_not_rewrite_history(self):
        self.ingest([quote('600000'),quote('600001')])
        with MarketHistoryStore(self.path) as store:
            iid=store.upsert_instrument('stock','SH','600000',name='ST未来名')
            store.upsert_stock_meta(iid,'2026-10-09',dict(name='ST未来名',is_st=True,
                delisting_risk=False,listed_days=1000,industry='银行'))
        rows,diag=self.eligible()
        self.assertEqual([row['code'] for row in rows],['600000','600001'])
        self.assertEqual(rows[0]['name'],'普通600000')
        self.assertEqual(diag['excluded']['st_or_delisting'],0)

    def test_historical_missing_name_does_not_borrow_future_registry_name(self):
        with MarketHistoryStore(self.path) as store:
            iid=store.upsert_instrument('stock','SH','600000',name='ST未来名')
            store.upsert_stock_meta(iid,'2026-09-28',dict(is_st=False,
                delisting_risk=False,listed_days=1000,industry='银行'))
        rows,_=self.eligible(PREVIOUS)
        self.assertEqual(rows[0]['name'],'600000')
        self.assertFalse(is_st_stock(rows[0]['name']))

    def test_declared_verified_nonbool_risk_is_not_self_authenticating(self):
        with MarketHistoryStore(self.path) as store:
            iid=store.resolve_instrument('stock','SH','600000')['instrument_id']
            store.upsert_stock_meta(iid,'2026-09-28',dict(name='普通600000',is_st='false',
                delisting_risk=False,risk_status='verified',risk_source='sina',risk_as_of='2026-09-28',
                listed_days=1000,industry='银行'))
        rows,diag=self.eligible(PREVIOUS)
        self.assertEqual([row['code'] for row in rows],['600001'])
        self.assertEqual(diag['excluded']['risk_evidence_conflict'],1)
        self.assertEqual(self.meta(as_of=PREVIOUS)['risk_status'],'conflict')

    def test_future_risk_embedded_in_old_metadata_does_not_supply_historical_name_or_flags(self):
        with MarketHistoryStore(self.path) as store:
            iid=store.resolve_instrument('stock','SH','600000')['instrument_id']
            store.upsert_stock_meta(iid,'2026-09-28',dict(name='ST未来风险',is_st=True,
                delisting_risk=False,risk_status='verified',risk_source='sina',risk_as_of='2026-10-09T15:00:00+08:00',
                listed_days=1000,industry='银行'))
        rows,diag=self.eligible(PREVIOUS)
        self.assertEqual([row['code'] for row in rows],['600000','600001'])
        self.assertEqual(rows[0]['name'],'600000')
        self.assertIsNone(rows[0]['stock_meta_asof']['is_st'])
        self.assertEqual(rows[0]['stock_meta_asof']['risk_status'],'unknown')

    def test_preclose_quote_provenance_does_not_borrow_stale_or_future_risk(self):
        candidate=self.eligible(PREVIOUS)[0][0]
        for changes in ({'quote_asof':'2026-09-29T14:45:00+08:00'},
                        {'quote_asof':DAY+'T14:45:30+08:00'},
                        {'quote_source':'unsupported'}, {'quote_status':'unavailable'}):
            with self.subTest(changes=changes):
                current=quote('600000','ST未核验名',is_st=True,**changes)
                value,reason=_append_intraday_quote_with_reason(candidate,current,DAY,DAY+'T14:45:00+08:00')
                self.assertEqual(reason,'')
                self.assertIsNone(value['is_st'])
                self.assertEqual(value['name'],'普通600000')
                self.assertEqual(value['stock_meta_asof']['risk_status'],'unknown')

    def test_preclose_wrong_identity_is_data_failure_not_business_risk(self):
        candidate=self.eligible(PREVIOUS)[0][0]
        value,reason=_append_intraday_quote_with_reason(candidate,
            quote('600001',quote_asof=DAY+'T14:45:00+08:00'),DAY,DAY+'T14:45:00+08:00')
        self.assertIsNone(value)
        self.assertEqual(reason,'quote_identity_mismatch')

    def test_preclose_mixed_risk_keeps_healthy_targets_and_full_quote_coverage(self):
        before_hash=hashlib.sha256(self.path.read_bytes()).hexdigest()
        universe,diag=self.eligible(PREVIOUS)
        quotes=[quote('600000','ST测试',is_st=True,quote_asof=DAY+'T14:45:00+08:00'),
                quote('600001',quote_asof=DAY+'T14:45:00+08:00')]
        targets=[]
        def select(rows):
            targets.extend(row['code'] for row in rows)
            return rows
        result=build_scheduled_preclose_input(DAY,DAY+'T14:45:00+08:00',formal_market_db=self.path,
            universe_loader=lambda *args:(universe,{'eligibility':diag}),
            quote_fetcher=lambda:(quotes,{'complete':True,'requested':2,'unique':2}),
            target_selector=select,min30_fetcher=lambda *args:{},
            index_fetcher=lambda *args:indices(),
            turnover_loader=lambda *args:[])
        self.assertEqual([row['code'] for row in result['daily']],['600001'])
        self.assertEqual(targets,['600001'])
        self.assertEqual(result['target_codes'],['600001'])
        self.assertEqual(len(result['market']['stock_bars']),2)
        splice=result['runtime_diagnostics']['daily_splice']
        self.assertEqual(splice['requested_count'],2)
        self.assertEqual(splice['available_count'],2)
        self.assertEqual(splice['business_available_count'],1)
        self.assertEqual(splice['risk_excluded_count'],1)
        self.assertEqual(splice['quote_eligible_count'],1)
        self.assertEqual(splice['coverage'],1)
        self.assertEqual(splice['excluded_by_reason'],{'st_or_delisting':1})
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before_hash)

    def test_main_fallback_final_floor_and_shadow_do_not_restore_verified_delisting(self):
        self.ingest([quote('600000',delisting_risk=True),quote('600001')])
        original=[{'code':code,'name':'普通'+code,'exchange':'SH','asset_type':'stock','sector':'银行'}
                  for code in ('600000','600001')]
        for floor,base,mode in ((1000,1,'active'),(0,2,'active'),(0,1,'shadow')):
            with self.subTest(floor=floor,base=base,mode=mode), patch.multiple(run_module,
                MARKET_HISTORY_DB_PATH=str(self.path),ENABLE_FULL_A_UNIVERSE=True,
                FULL_A_MIN_ELIGIBLE_COUNT=floor,RECALL_STRATEGY_MODE=mode,
                FULL_A_LOW_QUOTA=base,FULL_A_TREND_QUOTA=0,FULL_A_NEUTRAL_QUOTA=0,
                FULL_A_BASE_LIMIT=base,FULL_A_OVERLAY_LIMIT=1,FULL_A_FINAL_LIMIT=base+1):
                quality={}
                selected=run_module._apply_full_a_universe(original,[{'name':'银行','code':'BK1'}],quality,DAY)
                self.assertEqual([row['code'] for row in selected],['600001'])
                self.assertEqual(quality['universe_builder']['risk_filtered_existing_codes'],['600000'])

    def test_all_preclose_rows_explicitly_risky_produce_health_empty_with_evidence(self):
        universe,diag=self.eligible(PREVIOUS)
        quotes=[quote(code,delisting_risk=True,quote_asof=DAY+'T14:45:00+08:00')
                for code in ('600000','600001')]
        result=build_scheduled_preclose_input(DAY,DAY+'T14:45:00+08:00',formal_market_db=self.path,
            universe_loader=lambda *args:(universe,{'eligibility':diag}),
            quote_fetcher=lambda:(quotes,{'complete':True,'requested':2,'unique':2}),
            target_selector=lambda rows:rows,min30_fetcher=lambda *args:{},
            index_fetcher=lambda *args:indices(),
            turnover_loader=lambda *args:[])
        config=PreclosePipelineConfig(trade_date=DAY,as_of=DAY+'T14:45:00+08:00',
            generated_at=DAY+'T14:45:01+08:00',source_sha='fixture',run_id='all-risk',deadline_seconds=60)
        snapshot=run_preclose_pipeline(result,config=config)
        self.assertEqual(snapshot['status'],'empty')
        self.assertEqual(snapshot['pools'],{'main':[],'h4_t3':[],'acceleration':[]})
        for change in ('missing_proof','duplicate_code','conflicting_source','unverified_quote','wrong_count','missing_market'):
            bad=copy.deepcopy(result)
            splice=bad['runtime_diagnostics']['daily_splice']
            if change=='missing_proof': splice.pop('risk_exclusions')
            elif change=='duplicate_code': splice['risk_exclusions'][1]=copy.deepcopy(splice['risk_exclusions'][0])
            elif change=='conflicting_source': splice['risk_exclusions'][0]['quote']['risk_source']='tencent'
            elif change=='unverified_quote': splice['risk_exclusions'][0]['quote']['quote_asof']='2026-09-29T14:45:00+08:00'
            elif change=='wrong_count': splice['available_count']=0
            else: bad['market']['stock_bars']=[]
            with self.subTest(change=change):
                self.assertNotEqual(run_preclose_pipeline(bad,config=config)['status'],'empty')

    def test_risk_does_not_mask_invalid_history_adjustment_or_quantity(self):
        candidate=self.eligible(PREVIOUS)[0][0]
        risky=quote('600000',delisting_risk=True,quote_asof=DAY+'T14:45:00+08:00')
        cases=[]
        invalid=copy.deepcopy(candidate);invalid['klines']['opens']=[];cases.append((invalid,'invalid_history'))
        invalid=copy.deepcopy(candidate);invalid['klines']['closes'][-1]=0;cases.append((invalid,'invalid_adjustment_factor'))
        invalid=copy.deepcopy(candidate);invalid['klines']['adjustment']='raw';cases.append((invalid,'risk_history_unverified'))
        invalid=copy.deepcopy(candidate);invalid['klines']['volume_units']=['unknown']*120;cases.append((invalid,'risk_history_unverified'))
        for invalid,reason in cases:
            with self.subTest(reason=reason):
                row,actual=_append_intraday_quote_with_reason(invalid,risky,DAY,DAY+'T14:45:00+08:00')
                self.assertIsNone(row)
                self.assertEqual(actual,reason)

    def test_all_conflicting_risk_is_not_healthy_business_empty(self):
        universe,diag=self.eligible(PREVIOUS)
        quotes=[quote(code,risk_source='tencent',quote_asof=DAY+'T14:45:00+08:00')
                for code in ('600000','600001')]
        with self.assertRaisesRegex(RuntimeError,'no eligible intraday daily rows'):
            build_scheduled_preclose_input(DAY,DAY+'T14:45:00+08:00',formal_market_db=self.path,
                universe_loader=lambda *args:(universe,{'eligibility':diag}),
                quote_fetcher=lambda:(quotes,{'complete':True,'requested':2,'unique':2}),
                target_selector=lambda rows:rows,min30_fetcher=lambda *args:{},
                index_fetcher=lambda *args:indices(),
                turnover_loader=lambda *args:[])

    def risk_empty_input(self, index_values=None):
        universe,diag=self.eligible(PREVIOUS)
        quotes=[quote(code,delisting_risk=True,quote_asof=DAY+'T14:45:00+08:00')
                for code in ('600000','600001')]
        result=build_scheduled_preclose_input(DAY,DAY+'T14:45:00+08:00',formal_market_db=self.path,
            universe_loader=lambda *args:(universe,{'eligibility':diag}),
            quote_fetcher=lambda:(quotes,{'complete':True,'requested':2,'unique':2}),
            target_selector=lambda rows:rows,min30_fetcher=lambda *args:{},
            index_fetcher=lambda *args:indices() if index_values is None else index_values,
            turnover_loader=lambda *args:[])
        config=PreclosePipelineConfig(trade_date=DAY,as_of=DAY+'T14:45:00+08:00',
            generated_at=DAY+'T14:45:01+08:00',source_sha='fixture',run_id='risk-contract',deadline_seconds=60)
        return result,config

    def test_risk_empty_requires_the_actual_index_producer_contract(self):
        for change in ('empty_items','wrong_date','wrong_code','wrong_source','missing_closes','bad_close','bad_change'):
            values=indices()
            if change=='empty_items': values={name:{} for name in MARKET_INDICES}
            elif change=='wrong_date': values['上证指数']['date']=PREVIOUS
            elif change=='wrong_code': values['上证指数']['code']='399001'
            elif change=='wrong_source': values['上证指数']['source']='unverified'
            elif change=='missing_closes': values['上证指数']['closes']=[]
            elif change=='bad_close': values['上证指数']['close']=0
            else: values['上证指数']['change_pct']=20
            with self.subTest(change=change):
                payload,config=self.risk_empty_input(values)
                self.assertNotEqual(run_preclose_pipeline(payload,config=config)['status'],'empty')
        payload,config=self.risk_empty_input()
        payload['market']['market_indices']={'wrong'+str(index):row for index,row in enumerate(indices().values())}
        self.assertNotEqual(run_preclose_pipeline(payload,config=config)['status'],'empty')

    def test_risk_empty_requires_stock_bars_matching_the_specific_valid_quotes(self):
        for field,value in (('close',0),('close',11),('prev_close',0),('prev_close',11),
                            ('name','另一个名称'),('is_st',True),('is_st','false')):
            with self.subTest(field=field,value=value):
                payload,config=self.risk_empty_input()
                payload['market']['stock_bars'][0][field]=value
                self.assertNotEqual(run_preclose_pipeline(payload,config=config)['status'],'empty')
