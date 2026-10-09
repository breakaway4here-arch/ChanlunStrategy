"""Frozen synthetic histories: bounded repair, no network or formal database."""
import copy
import hashlib
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from chanlun.kline_repository import DailyRepairBudget, KLineRepository
from chanlun.market_history_store import MarketHistoryStore
from chanlun.universe_builder import load_eligible_candidates

DAY = '2026-09-30'


def dates(count):
    day = date.fromisoformat(DAY)
    result = []
    while len(result) < count:
        if day.weekday() < 5:
            result.append(day.isoformat())
        day -= timedelta(days=1)
    return result[::-1]


def payload(code, ds):
    size = len(ds)
    return dict(asset_type='stock', exchange='SH', code=code, dates=ds,
                opens=[10.] * size, highs=[10.3] * size, lows=[9.9] * size,
                closes=[10.] * size, volumes=[100000.] * size,
                amounts=[100000000.] * size, amount_available=[True] * size,
                finals=[True] * size, source='eastmoney', adjustment='qfq',
                volume_unit='hands', volume_raw_unit='hands', volume_source='eastmoney',
                amount_unit='CNY', amount_source='eastmoney')


class DailyNonfinalRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'market.sqlite'
        self.fixtures = [(60,None),(80,None),(100,None),(119,None),(120,None),
                         (120,30),(120,10),(121,0),(120,119)]
        with MarketHistoryStore(self.path) as store:
            for index, (count, bad) in enumerate(self.fixtures):
                code = '60000' + str(index)
                iid = store.upsert_instrument('stock','SH',code,name='普通'+code)
                store.upsert_stock_meta(iid,DAY,dict(name='普通'+code,is_st=False,
                    delisting_risk=False,listed_days=1000,industry='银行'))
                bars = [dict(ts=ds,open=10,high=10.3,low=9.9,close=10,volume=100000,
                    amount=100000000,amount_available=True,volume_unit='hands',
                    volume_raw_unit='hands',volume_source='eastmoney',amount_unit='CNY',
                    amount_source='eastmoney',adjustment='qfq',is_final=j!=bad,
                    source_batch='synthetic_frozen') for j,ds in enumerate(dates(count))]
                store.upsert_bars('day',iid,bars,adjustment='qfq')
        self.repo = KLineRepository(self.path)
        self.calls = []

    def source(self, identity, count, *, request_budget):
        request_budget.take_request()
        self.calls.append((identity.code,count))
        return payload(identity.code,dates(count))

    def qualify(self, overrides=None):
        with MarketHistoryStore(self.path,readonly=True) as store:
            return load_eligible_candidates(store,as_of=DAY,required_date=DAY,
                min_listed_days=60,min_daily_amount=50000000,return_diagnostics=True,
                **({'daily_rows_override':overrides} if overrides is not None else {}))

    def rows(self):
        with MarketHistoryStore(self.path,readonly=True) as store:
            return {(r['instrument_id'],r['ts']):dict(r) for r in
                    store.connection.execute('SELECT * FROM bars_day').fetchall()}

    def test_history_gap_cannot_be_verified_or_trigger_ordinary_fanout(self):
        ordinary = []
        repo = KLineRepository(self.path,remote_fetchers={'day':lambda *a,**k:ordinary.append(a)})
        result = repo.get('day','600005',100,required_date=DAY)
        self.assertNotEqual(result.status,'verified')
        self.assertEqual(result.kline['_data_status']['nonfinal_dates'],[dates(120)[30]])
        self.assertEqual(ordinary,[])

    def test_exact_dates_repair_and_same_call_qualification(self):
        before = self.rows()
        rows, diag = self.qualify()
        self.assertEqual(len(rows),6)
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)])
        rows, diag = self.qualify()
        self.assertEqual([r['code'] for r in rows],['60000'+str(i) for i in range(9)])
        self.assertEqual(diag['excluded']['nonfinal_bars'],0)
        after = self.rows()
        changed = [key for key in before if before[key] != after[key]]
        self.assertEqual(len(changed),3)
        self.assertEqual(result['diagnostics']['repaired_count'],3)
        self.assertEqual(self.calls,[('600005',120),('600006',120),('600008',120)])

    def test_readonly_memory_override_and_prior_day_tail(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        def source(identity,count,*,request_budget):
            request_budget.take_request()
            return payload(identity.code,dates(count-1)+['2026-10-08'])
        repo = KLineRepository(self.path,mode='backtest',immutable_backtest=False)
        result = repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)],write=False,fetch_buffer=True)
        rows, diag = self.qualify(result['daily_rows_override'])
        self.assertEqual(len(rows),9)
        self.assertEqual(diag['excluded']['nonfinal_bars'],0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        self.assertTrue(all(len(rs)==120 for rs in result['daily_rows_override'].values()))

    def test_source_contract_failures_do_not_write_or_flip_final(self):
        cases = {
            'identity':lambda p:p.update(code='600999'),
            'exchange':lambda p:p.update(exchange='SZ'),
            'source':lambda p:p.update(source='sina'),
            'units':lambda p:p.update(volume_unit='contracts'),
            'amount_units':lambda p:p.update(amount_unit='USD'),
            'adjustment':lambda p:p.update(adjustment='raw'),
            'short':lambda p:p.update(dates=p['dates'][-50:]),
            'nonfinal':lambda p:p['finals'].__setitem__(30,False),
            'invalid_final':lambda p:p['finals'].__setitem__(30,'true'),
            'duplicate':lambda p:p['dates'].__setitem__(0,p['dates'][1]),
            'order':lambda p:p['dates'].reverse(),
            'ohlc':lambda p:p['highs'].__setitem__(30,1),
            'basis':lambda p:p['closes'].__setitem__(0,10.01),
            'negative_volume':lambda p:p['volumes'].__setitem__(30,-1),
            'latest_date':lambda p:p['dates'].__setitem__(-1,'2026-09-29'),
        }
        before = self.rows()
        for name, change in cases.items():
            with self.subTest(name=name):
                def bad(identity,count,*,request_budget):
                    request_budget.take_request()
                    value = payload(identity.code,dates(count))
                    change(value)
                    return value
                result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',bad)])
                self.assertEqual(result['diagnostics']['repaired_count'],0)
                self.assertEqual(self.rows(),before)

    def test_zero_budget_no_http(self):
        for kwargs in ({'seconds':0},{'max_stocks':0},{'max_requests':0},{'remaining':lambda:0}):
            with self.subTest(kwargs=list(kwargs)):
                result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)],
                    budget=DailyRepairBudget(**kwargs))
                self.assertEqual(result['diagnostics']['http_requests'],0)
                self.assertEqual(result['diagnostics']['pending_count'],3)
        self.assertEqual(self.calls,[])

    def test_request_stock_limits_and_shared_time(self):
        budget = DailyRepairBudget(max_stocks=2,max_requests=2)
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)],budget=budget)
        self.assertEqual(result['diagnostics']['http_requests'],2)
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending_count'],1)
        self.assertEqual(len(self.qualify()[0]),8)

    def test_late_response_never_adopted_or_written(self):
        now = [0.]
        budget = DailyRepairBudget(seconds=1,monotonic=lambda:now[0])
        def late(identity,count,*,request_budget):
            request_budget.take_request()
            now[0] = 2.
            return payload(identity.code,dates(count))
        before = self.rows()
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',late)],budget=budget)
        self.assertEqual(result['diagnostics']['http_requests'],1)
        self.assertEqual(result['diagnostics']['repaired_count'],0)
        self.assertEqual(result['diagnostics']['pending_count'],3)
        self.assertEqual(self.rows(),before)

    def test_stock_failure_continues_next_stock_without_retry(self):
        def mixed(identity,count,*,request_budget):
            request_budget.take_request()
            return None if identity.code=='600005' else payload(identity.code,dates(count))
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',mixed)])
        self.assertEqual(result['diagnostics']['http_requests'],3)
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['code'],'600005')

    def test_baseexception_from_real_remaining_is_not_swallowed(self):
        class Cutoff(BaseException):
            pass
        def remaining():
            raise Cutoff()
        with self.assertRaises(Cutoff):
            self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)],
                budget=DailyRepairBudget(remaining=remaining))
        self.assertEqual(self.calls,[])

    def test_readonly_loader_rechecks_before_empty_or_selection(self):
        from chanlun import preclose_runtime
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        def previous_source(identity,count,*,request_budget):
            return self.source(identity,count-1,request_budget=request_budget)
        with patch.object(preclose_runtime,'_previous_market_date',return_value=DAY):
            rows, diag = preclose_runtime.load_readonly_preclose_universe(self.path,'2026-10-08',
                repair_providers=[('eastmoney',previous_source)])
        self.assertEqual(sorted(r['code'] for r in rows),['60000'+str(i) for i in range(9)])
        self.assertEqual(diag['eligibility']['eligible_count'],9)
        self.assertEqual(diag['daily_nonfinal_repair']['repaired_count'],3)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_strict_helper_actual_http_ledger_identity_redirect_timeout(self):
        from chanlun import data_fetcher
        from unittest.mock import Mock
        ds = dates(120)
        raw = [','.join([d,'10','10','10.3','9.9','100000','100000000']) for d in ds]
        response = Mock(status_code=200)
        response.json.return_value = {'data':{'code':'600005','market':1,'klines':raw}}
        budget = DailyRepairBudget()
        with patch.object(data_fetcher.SESSION,'get',return_value=response) as get:
            result = data_fetcher._fetch_daily_kline_eastmoney_remote('600005',120,request_budget=budget)
        self.assertEqual(result['code'],'600005')
        self.assertEqual(budget.requests,1)
        self.assertEqual(get.call_args.kwargs['timeout'],3)
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        for body,status in [({'code':'600006','market':1,'klines':raw},200),
                            ({'code':'600005','market':0,'klines':raw},200),
                            ({'code':'600005','market':1,'klines':raw},302)]:
            response.status_code=status
            response.json.return_value={'data':body}
            with patch.object(data_fetcher.SESSION,'get',return_value=response):
                self.assertIsNone(data_fetcher._fetch_daily_kline_eastmoney_remote('600005',120,
                    request_budget=budget))
        self.assertEqual(budget.requests,4)

    def test_healthy_window_no_new_source_calls(self):
        self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)])
        self.calls.clear()
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)])
        self.assertEqual(self.calls,[])
        self.assertEqual(result['diagnostics']['nonfinal_stock_count'],0)

    def test_incomplete_source_fields_outside_consumer_windows_remain_unknown(self):
        def tencent(identity,count,*,request_budget):
            request_budget.take_request()
            value = payload(identity.code,dates(count))
            value.update(source='tencent',volume_unit='unknown',volume_raw_unit='unknown',
                         volume_source='tencent',amount_unit='unknown',amount_source='')
            value.pop('amounts');value.pop('amount_available')
            return value
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('tencent',tencent)])
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['code'],'600008')
        self.assertEqual(len(self.qualify()[0]),8)
        row = result['daily_rows_override'][6][30]
        self.assertEqual(row['volume_unit'],'unknown')
        self.assertFalse(row['amount_available'])

    def test_latest_bar_no_synthetic_close_time(self):
        before = self.rows()
        def source(identity,count,*,request_budget):
            value = self.source(identity,count,request_budget=request_budget)
            value.pop('finals')
            return value
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)],
            as_of=DAY+'T14:45:00+08:00')
        self.assertEqual(result['diagnostics']['repaired_count'],0)
        self.assertEqual(self.rows(),before)
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)],
            as_of=DAY+'T15:05:00+08:00')
        self.assertEqual(result['diagnostics']['repaired_count'],3)

    def test_invalid_identity_is_one_pending_stock(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute("UPDATE instruments SET exchange='SZ' WHERE code='600005'")
            store.connection.commit()
        result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)])
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['reasons'],['invalid_identity'])

    def test_actual_commit_is_success_when_clock_expires_after_commit(self):
        now = [0.]
        budget = DailyRepairBudget(seconds=1,monotonic=lambda:now[0])
        original = self.repo._write_prepared
        def commit(*args,**kwargs):
            original(*args,**kwargs)
            now[0]=2.
        with patch.object(self.repo,'_write_prepared',side_effect=commit):
            result = self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)],budget=budget)
        self.assertEqual(result['diagnostics']['repaired_count'],1)
        self.assertEqual(result['diagnostics']['pending_count'],2)
        self.assertEqual(len(self.qualify()[0]),7)

    def test_failed_bounded_repair_does_not_repeat_ordinary_fanout(self):
        ordinary = []
        self.repo.remote_fetchers['day'] = lambda *a,**k:ordinary.append(a)
        self.assertEqual(self.repo.get('day','600006',100,required_date=DAY).status,'verified')
        self.repo.repair_daily_nonfinal(DAY,providers=[],budget=DailyRepairBudget(max_requests=0))
        self.assertEqual(self.repo.get('day','600006',100,required_date=DAY).status,'repair_pending')
        results = self.repo.get_many('day',['600005','600006','600008'],100,required_date=DAY)
        self.assertEqual(ordinary,[])
        self.assertTrue(all(r.status=='repair_pending' for r in results.values()))
        self.assertEqual(results['600006'].kline['_data_status']['nonfinal_dates'],[dates(120)[10]])

    def test_formal_collect_freezes_repaired_status_for_fallback_and_shadow(self):
        from chanlun import data_fetcher
        from datetime import datetime
        import run
        from chanlun.universe_builder import UniverseConfig
        from chanlun.candidate_funnel import CandidateFunnel
        codes = ['600002','600005','600006','600007','600008']
        sector = dict(code='BK001',name='银行',flow=100000000)
        components = [dict(code=c,name='普通'+c,close=10) for c in codes]
        index = dict(dates=[DAY],closes=[10.])
        with patch.object(data_fetcher,'_get_kline_repository',return_value=self.repo), \
             patch.object(data_fetcher,'daily_nonfinal_repair_providers',return_value=[('eastmoney',self.source)]), \
             patch.object(data_fetcher,'fetch_sector_flow',return_value=[sector]), \
             patch.object(data_fetcher,'fetch_sector_stocks',return_value=(components,{'complete':True})), \
             patch.object(data_fetcher,'fetch_shanghai_index',return_value=index):
            collected = data_fetcher.collect_daily_data(required_date=DAY,
                generated_at=datetime.fromisoformat(DAY+'T15:05:00+08:00'),missing_only=True)
        stocks = collected['stocks'];quality = collected['data_quality']
        self.assertEqual(sorted(s['code'] for s in stocks),codes)
        self.assertTrue(all(len(s['klines']['dates'])==100 for s in stocks))
        self.assertEqual(quality['missing_daily_count'],0)
        self.assertEqual(quality['stale_stock_count'],0)
        self.assertTrue(quality['is_official'])
        self.assertEqual(quality['daily_nonfinal_repair']['repaired_count'],3)
        def apply(floor,config=None,mode='active',selection=None):
            q=copy.deepcopy(quality)
            funnel=CandidateFunnel('bounded-repair',DAY)
            with patch.object(run,'MARKET_HISTORY_DB_PATH',str(self.path)), \
                 patch.object(run,'ENABLE_FULL_A_UNIVERSE',True), \
                 patch.object(run,'FULL_A_MIN_ELIGIBLE_COUNT',floor), \
                 patch.object(run,'RECALL_STRATEGY_MODE',mode), \
                 patch.object(run,'hydrate_industry_metadata',return_value={}):
                if config is None:
                    result=run._apply_full_a_universe(stocks,[],q,DAY,candidate_funnel=funnel)
                else:
                    with patch.object(run,'_universe_config_for_sector_groups',return_value=(config,'base_expanded_no_overlay')), \
                         patch.object(run,'build_candidate_universe',return_value=selection):
                        result=run._apply_full_a_universe(stocks,[],q,DAY,candidate_funnel=funnel)
            self.assertEqual(funnel.summary()['stage_counts']['eligible'],9)
            return result,q
        fallback,q=apply(1000)
        self.assertEqual(q['universe_builder']['reason'],'eligible_count_below_activation_floor')
        self.assertEqual(sorted(s['code'] for s in fallback),codes)
        self.assertTrue(all(s['data_status']['daily']=='verified' and len(s['klines']['dates'])==100 for s in fallback))
        final_floor,q=apply(1,UniverseConfig(base_limit=6),selection={'final':stocks[:1],'diagnostics':{}})
        self.assertEqual(q['universe_builder']['reason'],'final_pool_below_base_limit')
        self.assertEqual(sorted(s['code'] for s in final_floor),codes)
        shadow,q=apply(1,UniverseConfig(base_limit=1),mode='shadow',selection={'final':stocks[:1],'diagnostics':{}})
        self.assertEqual(q['universe_builder']['shadow_legacy_extra_count'],4)
        self.assertEqual(sorted(s['code'] for s in shadow),codes)
        self.assertEqual(q['universe_builder']['eligibility']['eligible_count'],9)

    def test_preclose_repair_reaches_daily_and_minute_targets_without_db_write(self):
        from chanlun import preclose_runtime
        trade='2026-10-08';as_of=trade+'T14:45:00+08:00'
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        codes=['60000'+str(i) for i in range(9)]
        quotes=[dict(code=c,asset_type='stock',exchange='SH',name='普通'+c,is_st=False,
            delisting_risk=False,open=10,high=10.3,low=9.9,current_price=10,prev_close=10,
            volume=100000,amount=100000000,volume_unit='hands',volume_raw_unit='hands',
            volume_source='eastmoney',amount_unit='CNY',amount_source='eastmoney',amount_available=True,
            quote_source='eastmoney',quote_asof=as_of) for c in codes]
        targets=[]
        def loader(path,day,**kwargs):
            def previous_source(identity,count,*,request_budget):
                return self.source(identity,count-1,request_budget=request_budget)
            return preclose_runtime.load_readonly_preclose_universe(path,day,
                repair_providers=[('eastmoney',previous_source)],**kwargs)
        def minute(rows,*args):
            targets.extend(r['code'] for r in rows)
            return {}
        with patch.object(preclose_runtime,'_previous_market_date',return_value=DAY):
            result=preclose_runtime.build_scheduled_preclose_input(trade,as_of,formal_market_db=self.path,
                universe_loader=loader,quote_fetcher=lambda:(quotes,{'complete':True,'requested':9,'unique':9}),
                index_fetcher=lambda day:{name:{} for name in preclose_runtime.MARKET_INDICES},
                target_selector=lambda rows:rows,min30_fetcher=minute,turnover_loader=lambda *a:[],
                repair_budget_remaining=lambda:10)
        self.assertEqual(sorted(r['code'] for r in result['daily']),codes)
        self.assertEqual(sorted(targets),codes)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_preclose_partial_repair_does_not_reduce_healthy_splice_coverage(self):
        from chanlun import preclose_runtime
        trade='2026-10-08';as_of=trade+'T14:45:00+08:00'
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        quotes=[dict(code='60000'+str(i),asset_type='stock',exchange='SH',name='普通60000'+str(i),
            is_st=False,delisting_risk=False,open=10,high=10.3,low=9.9,current_price=10,prev_close=10,
            volume=100000,amount=100000000,volume_unit='hands',volume_raw_unit='hands',
            volume_source='eastmoney',amount_unit='CNY',amount_source='eastmoney',amount_available=True,
            quote_source='eastmoney',quote_asof=as_of) for i in range(9)]
        def failed(*a,request_budget,**k):
            request_budget.take_request();return None
        def partial(identity,count,*,request_budget):
            request_budget.take_request()
            value=payload(identity.code,dates(count-1))
            value.update(source='tencent',volume_source='tencent',volume_unit='unknown',
                         volume_raw_unit='unknown',amount_unit='unknown',amount_source='')
            value.pop('amounts');value.pop('amount_available')
            return value
        def loader(path,day,**kwargs):
            return preclose_runtime.load_readonly_preclose_universe(path,day,
                repair_providers=[('eastmoney',failed),('tencent',partial)],**kwargs)
        with patch.object(preclose_runtime,'_previous_market_date',return_value=DAY):
            result=preclose_runtime.build_scheduled_preclose_input(trade,as_of,formal_market_db=self.path,
                universe_loader=loader,quote_fetcher=lambda:(quotes,{'complete':True,'requested':9,'unique':9}),
                index_fetcher=lambda day:{name:{} for name in preclose_runtime.MARKET_INDICES},
                target_selector=lambda rows:rows,min30_fetcher=lambda *a:{},turnover_loader=lambda *a:[])
        self.assertEqual(sorted(r['code'] for r in result['daily']),['600000','600001','600002','600003','600004','600007'])
        diag=result['runtime_diagnostics']['daily_splice']
        self.assertEqual(diag['requested_count'],6)
        self.assertEqual(diag['available_count'],6)
        self.assertEqual(diag['coverage'],1.)
        self.assertEqual(result['runtime_diagnostics']['universe']['daily_nonfinal_repair']['pending_count'],3)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def concurrent_source(self, identity, count, *, request_budget, code='600005', close=10.05):
        request_budget.take_request()
        if identity.code == code:
            with MarketHistoryStore(self.path) as other:
                instrument=other.resolve_instrument('stock','SH',code)
                bad=next(r for r in other.query_bars('day',instrument['instrument_id'],as_of=DAY,limit=120)
                         if not r['is_final'])
                other.upsert_bars('day',instrument['instrument_id'],[dict(bad,is_final=True,
                    close=close,source_batch='source_new')],adjustment='qfq')
        return payload(identity.code,dates(count))

    def test_concurrent_final_writer_is_not_overwritten_or_claimed_repaired(self):
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.concurrent_source)])
        changed=self.rows()[(6,dates(120)[30])]
        self.assertEqual(changed['close'],10.05)
        self.assertEqual(changed['source_batch'],'source_new')
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending_count'],1)
        self.assertEqual(len(self.qualify()[0]),9)
        self.assertEqual(self.repo.get('day','600005',100,required_date=DAY).status,'verified')

    def test_concurrent_same_price_final_or_source_change_is_protected(self):
        def source(identity,count,*,request_budget):
            return self.concurrent_source(identity,count,request_budget=request_budget,close=10.)
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)])
        changed=self.rows()[(6,dates(120)[30])]
        self.assertEqual(changed['source_batch'],'source_new')
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['nonfinal_dates'],[])

    def test_multiple_bad_dates_conflict_rolls_back_whole_stock(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=0 WHERE instrument_id=6 AND ts=?',
                                     (dates(120)[40],))
            store.connection.commit()
        before=self.rows()[(6,dates(120)[40])]
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.concurrent_source)])
        self.assertEqual(self.rows()[(6,dates(120)[40])],before)
        self.assertEqual(self.rows()[(6,dates(120)[30])]['close'],10.05)
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['nonfinal_dates'],[dates(120)[40]])

    def test_concurrent_final_outside_analysis_window_is_not_false_pending(self):
        def source(identity,count,*,request_budget):
            return self.concurrent_source(identity,count,request_budget=request_budget,code='600006')
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)])
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['code'],'600006')
        self.assertEqual(self.rows()[(7,dates(120)[10])]['source_batch'],'source_new')
        self.assertEqual(self.repo.get('day','600006',100,required_date=DAY).status,'verified')
        self.assertEqual(len(self.qualify()[0]),9)

    def test_readonly_external_final_change_wins_over_memory_repair(self):
        readonly=KLineRepository(self.path,mode='backtest',immutable_backtest=False)
        result=readonly.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.concurrent_source)],write=False)
        self.assertNotIn(6,result['daily_rows_override'])
        self.assertEqual(self.rows()[(6,dates(120)[30])]['close'],10.05)
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        rows,diag=self.qualify(result['daily_rows_override'])
        self.assertEqual(len(rows),9)
        candidate=next(r for r in rows if r['code']=='600005')
        self.assertEqual(candidate['klines']['closes'][30],10.05)

    def test_readonly_consumer_rechecks_snapshot_before_using_override(self):
        readonly=KLineRepository(self.path,mode='backtest',immutable_backtest=False)
        result=readonly.repair_daily_nonfinal(DAY,providers=[('eastmoney',self.source)],write=False)
        # External change after source validation but before qualification.
        self.concurrent_source(readonly._identity('600005'),120,request_budget=DailyRepairBudget())
        with MarketHistoryStore(self.path,readonly=True) as store:
            rows,diag=load_eligible_candidates(store,as_of=DAY,required_date=DAY,
                min_listed_days=60,min_daily_amount=50000000,return_diagnostics=True,
                daily_rows_override=result['daily_rows_override'],daily_rows_expected=result['daily_rows_expected'])
        self.assertEqual(len(rows),9)
        candidate=next(r for r in rows if r['code']=='600005')
        self.assertEqual(candidate['klines']['closes'][30],10.05)

    def test_concurrent_source_only_change_keeps_nonfinal_pending(self):
        def source(identity,count,*,request_budget):
            request_budget.take_request()
            if identity.code=='600005':
                with MarketHistoryStore(self.path) as other:
                    old=next(r for r in other.query_bars('day',6,as_of=DAY,limit=120) if not r['is_final'])
                    other.upsert_bars('day',6,[dict(old,source_batch='source_new')],adjustment='qfq')
            return payload(identity.code,dates(count))
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)])
        self.assertEqual(self.rows()[(6,dates(120)[30])]['source_batch'],'source_new')
        self.assertFalse(self.rows()[(6,dates(120)[30])]['is_final'])
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(self.repo.get('day','600005',100,required_date=DAY).status,'repair_pending')

    def test_collect_consumes_concurrent_final_without_false_health_failure(self):
        from chanlun import data_fetcher
        from datetime import datetime
        codes=['600002','600005','600006','600007','600008']
        with patch.object(data_fetcher,'_get_kline_repository',return_value=self.repo), \
             patch.object(data_fetcher,'daily_nonfinal_repair_providers',return_value=[('eastmoney',self.concurrent_source)]), \
             patch.object(data_fetcher,'fetch_sector_flow',return_value=[dict(code='BK001',name='银行',flow=100000000)]), \
             patch.object(data_fetcher,'fetch_sector_stocks',return_value=([dict(code=c,name='普通'+c,close=10) for c in codes],{'complete':True})), \
             patch.object(data_fetcher,'fetch_shanghai_index',return_value=dict(dates=[DAY],closes=[10.])):
            result=data_fetcher.collect_daily_data(required_date=DAY,
                generated_at=datetime.fromisoformat(DAY+'T15:05:00+08:00'),missing_only=True)
        row=next(s for s in result['stocks'] if s['code']=='600005')
        self.assertEqual(row['klines']['closes'][10],10.05)
        self.assertEqual(row['data_status']['daily'],'verified')
        self.assertEqual(result['data_quality']['missing_daily_count'],0)
        self.assertEqual(result['data_quality']['stale_stock_count'],0)
        self.assertTrue(result['data_quality']['is_official'])
        self.assertEqual(result['data_quality']['daily_nonfinal_repair']['repaired_count'],2)
        self.assertEqual(self.rows()[(6,dates(120)[30])]['source_batch'],'source_new')

    def test_concurrent_healthy_basis_change_blocks_old_source_repair(self):
        def source(identity,count,*,request_budget):
            request_budget.take_request()
            if identity.code=='600005':
                with MarketHistoryStore(self.path) as other:
                    healthy=[dict(r,open=20,high=20.6,low=19.8,close=20,source_batch='source_new')
                             for r in other.query_bars('day',6,as_of=DAY,limit=120) if r['is_final']]
                    other.upsert_bars('day',6,healthy,adjustment='qfq')
            return payload(identity.code,dates(count))
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)])
        bad=self.rows()[(6,dates(120)[30])]
        self.assertFalse(bad['is_final'])
        self.assertEqual(bad['source_batch'],'synthetic_frozen')
        self.assertEqual(self.rows()[(6,dates(120)[31])]['close'],20)
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertEqual(result['diagnostics']['pending'][0]['code'],'600005')

    def test_concurrent_healthy_source_change_blocks_old_source_repair(self):
        def source(identity,count,*,request_budget):
            request_budget.take_request()
            if identity.code=='600005':
                with MarketHistoryStore(self.path) as other:
                    healthy=[dict(r,source_batch='source_new')
                             for r in other.query_bars('day',6,as_of=DAY,limit=120) if r['is_final']]
                    other.upsert_bars('day',6,healthy,adjustment='qfq')
            return payload(identity.code,dates(count))
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)])
        self.assertFalse(self.rows()[(6,dates(120)[30])]['is_final'])
        self.assertEqual(self.rows()[(6,dates(120)[31])]['source_batch'],'source_new')
        self.assertEqual(result['diagnostics']['repaired_count'],2)

    def test_concurrent_new_row_inside_reference_frame_blocks_repair(self):
        def source(identity,count,*,request_budget):
            request_budget.take_request()
            if identity.code=='600005':
                with MarketHistoryStore(self.path) as other:
                    reference=other.query_bars('day',6,as_of=DAY,limit=120)[0]
                    # Synthetic added record, not a claim about a trading day.
                    other.upsert_bars('day',6,[dict(reference,ts='2026-09-26',source_batch='source_new')],adjustment='qfq')
            return payload(identity.code,dates(count))
        result=self.repo.repair_daily_nonfinal(DAY,providers=[('eastmoney',source)])
        self.assertFalse(self.rows()[(6,dates(120)[30])]['is_final'])
        self.assertIn((6,'2026-09-26'),self.rows())
        self.assertEqual(result['diagnostics']['repaired_count'],2)
        self.assertIn('repair_local_window_changed',result['diagnostics']['pending'][0]['reasons'][0])


if __name__ == '__main__':
    unittest.main()
