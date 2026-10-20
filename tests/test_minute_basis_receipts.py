"""Proof survives the real cache/analysis boundary; all data stays in tmp DBs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np

from chanlun import data_fetcher as df
from chanlun import minute_sources as ms
from chanlun import price_basis
from chanlun.candidate_upgrade import _passes_upgrade_risk_guard
from chanlun.kline_repository import KLineRepository
from chanlun.market_history_store import MarketHistoryStore
from chanlun.universe_builder import load_eligible_candidates

DAY = '2026-09-23'
CUTOFF = DAY + 'T15:05:00+08:00'


class MinuteBasisReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'market.sqlite'
        days=[]
        current=date.fromisoformat(DAY)
        while len(days)<60:
            if current.weekday()<5: days.append(current.isoformat())
            current-=timedelta(days=1)
        days=list(reversed(days))
        rows = [dict(day=day+' '+t+':00', open='100', high='104', low='98',
                     close='101', volume='10000', amount='1010000')
                for day in days[-10:] for t in ('10:00','10:30','11:00','11:30','13:30','14:00','14:30','15:00')]
        self.raw = {day: dict(open=100., high=104., low=98., close=101.,
                             is_final=True, source='independent_raw') for day in days}
        self.payload = ms.clean_minutes(rows, source='sina', symbol='sz301377', scale=30)
        with MarketHistoryStore(self.path) as store:
            self.iid = store.upsert_instrument('stock', 'SZ', '301377')
            store.upsert_stock_meta(self.iid, days[0], dict(name='样本', listed_days=200,
                is_st=False, delisting_risk=False))
            store.upsert_bars('day', self.iid, [dict(ts=day, open=49.8, high=51.8,
                low=48.8, close=50.3, volume=800, amount=4024000, is_final=True,
                source_batch='canonical_day', adjustment='qfq', volume_unit='hands',
                volume_source='fixture', amount_unit='CNY', amount_source='fixture') for day in days])
        self.repo = KLineRepository(self.path, remote_fetchers={'30m':lambda *a, **kw:copy.deepcopy(self.payload)},
            raw_daily_reader=lambda *a:copy.deepcopy(self.raw))

    def get(self, repo=None):
        return (repo or self.repo).get('30m', '301377', 80, required_date=DAY, as_of=CUTOFF)

    def stock(self):
        with MarketHistoryStore(self.path, readonly=True) as store:
            values = load_eligible_candidates(store, CUTOFF, 60, 0, minimum_bars=1,
                required_date=DAY)
        row = values[0]
        row.update({k: row['klines'][k] for k in ('dates','opens','highs','lows','closes','volumes')})
        return row

    def analyzed(self, result):
        import run
        evidence = df._sublevel_input_evidence('30m', result.kline, result)
        return run._analyze_30min_rows([dict(code='301377', klines=result.kline,
            input_evidence=evidence)])[0]

    def test_real_producer_analysis_risk_guard_uses_canonical_without_double_transform(self):
        result = self.get()
        stock = self.stock()
        stock['price_basis']['factor_vs_raw'] = .5
        analyzed = self.analyzed(result)
        self.assertEqual(analyzed.strategy_input_evidence['minute_to_daily']['status'], 'verified')
        self.assertAlmostEqual(price_basis.align_intraday_price(48.8, stock, analyzed), 48.8)
        self.assertTrue(_passes_upgrade_risk_guard(stock, {'price':50.3}, analyzed))
        self.assertEqual(stock['price_basis']['factor_vs_raw'], .5)
        proof = result.kline['minute_to_daily']
        self.assertTrue(proof['transform_applied'])
        self.assertAlmostEqual(proof['evidence_by_date'][DAY]['offset'], -.2)
        self.assertNotEqual(proof['input_sha256'], proof['output_sha256'])

    def test_restarted_repository_verifies_persisted_receipt_without_fetch(self):
        self.get()
        fresh = KLineRepository(self.path, remote_fetchers={'30m':lambda *a, **kw:self.fail('cache must not fetch')})
        result = self.get(fresh)
        self.assertEqual(result.kline['minute_to_daily']['status'], 'verified')
        self.assertAlmostEqual(price_basis.align_intraday_price(48.8, self.stock(), self.analyzed(result)), 48.8)

    def test_minute_or_daily_content_mutation_invalidates_proof(self):
        result = self.get()
        stock = self.stock()
        for field in ('lows', 'dates', 'volumes'):
            analyzed = self.analyzed(result)
            values = list(getattr(analyzed, field))
            values[0] = DAY+' 09:30:00' if field == 'dates' else float(values[0]) + .1
            setattr(analyzed, field, values)
            self.assertIsNone(price_basis.align_intraday_price(48.8, stock, analyzed), field)
        stock['closes'] = np.array([51.3])
        self.assertIsNone(price_basis.align_intraday_price(48.8, stock, self.analyzed(result)))

    def test_wrong_identity_interval_cutoff_or_missing_date_proof_rejected(self):
        result = self.get()
        for change in (lambda p:p.update(identity_key='index|SH|000001'),
                       lambda p:p.update(interval='15m'),
                       lambda p:p.update(as_of=DAY+'T14:45:00+08:00'),
                       lambda p:p['evidence_by_date'].clear()):
            analyzed = self.analyzed(result)
            analyzed.strategy_input_evidence=copy.deepcopy(analyzed.strategy_input_evidence)
            change(analyzed.strategy_input_evidence['minute_to_daily'])
            self.assertIsNone(price_basis.align_intraday_price(48.8, self.stock(), analyzed))

    def test_aware_utc_cutoff_equals_shanghai_and_a_true_future_is_rejected(self):
        result=self.get()
        for cutoff, allowed in ((DAY+'T07:05:00+00:00',True),
                                (DAY+'T06:45:00+00:00',False),
                                (DAY,True)):
            minute=self.analyzed(result)
            proof=minute.strategy_input_evidence['minute_to_daily']
            proof['as_of']=cutoff
            proof['sha256']=price_basis.basis_sha256({k:v for k,v in proof.items() if k!='sha256'})
            actual=price_basis.align_intraday_price(48.8,self.stock(),minute)
            self.assertEqual(actual is not None,allowed,cutoff)

    def test_two_day_receipt_cannot_certify_a_ten_day_cache_window(self):
        self.get()
        receipt_path=next(self.path.parent.glob('minute_basis_v1/*.json'))
        receipt=json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps({date:receipt[date] for date in sorted(receipt)[-2:]}))
        result=self.get(KLineRepository(self.path))
        self.assertEqual(len(result.kline['dates']),80)
        self.assertEqual(result.kline['minute_to_daily']['status'],'pending')
        self.assertTrue(result.kline['minute_to_daily']['reason'].startswith('missing_producer_receipt:'))

    def test_cache_hit_rechecks_current_window_and_daily_reference_in_same_process(self):
        first=self.get()
        self.assertEqual(first.kline['minute_to_daily']['status'],'verified')
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_30m SET volume=volume+1 WHERE ts=(SELECT MIN(ts) FROM bars_30m)')
            store.connection.commit()
        self.assertEqual(self.get().kline['minute_to_daily']['status'],'pending')

    def test_public_reference_raw_conversion_remains_independent_of_canonical_minute_comparison(self):
        from chanlun.preclose_pipeline import _public_reference_price
        stock=self.stock()
        stock['price_basis']['factor_vs_raw']=.5
        stock['reference_price']=50.3
        result=self.get()
        self.assertAlmostEqual(price_basis.align_intraday_price(48.8,stock,self.analyzed(result)),48.8)
        self.assertAlmostEqual(_public_reference_price(stock),100.6)

    def test_existing_pure_and_fusion_guards_consume_the_same_canonical_contract(self):
        from chanlun.screener_fusion import _confirm_third_buy_30min
        from chanlun.screener_pure import screen_30min_pure
        from types import SimpleNamespace
        stock=self.stock()
        stock['price_basis']['factor_vs_raw']=.5
        stock['pivots']={'ZG':50.3}
        minute=self.analyzed(self.get())
        self.assertFalse(_confirm_third_buy_30min(stock,minute))
        stock['best_buy_point']={'type':'一买','price':50.3}
        minute.divergence={'is_divergence':True,'type':'底背驰'}
        minute.fractals=[SimpleNamespace(type='bottom',price=48.8,index=79)]
        out=screen_30min_pure([stock],[minute])
        self.assertAlmostEqual(out[0]['buy_points_30min'][0]['price'],48.8)

    def test_receipt_output_cannot_be_from_another_source(self):
        self.get()
        for field,new_value in (('source_batch','ongoing:tencent'),):
            with MarketHistoryStore(self.path) as store:
                original=store.connection.execute('SELECT '+field+' FROM bars_30m LIMIT 1').fetchone()[0]
                store.connection.execute('UPDATE bars_30m SET '+field+'=?',(new_value,))
                store.connection.commit()
            self.assertEqual(self.get(KLineRepository(self.path)).kline['minute_to_daily']['status'],'pending')
            with MarketHistoryStore(self.path) as store:
                store.connection.execute('UPDATE bars_30m SET '+field+'=?',(original,))
                store.connection.commit()

    def test_full_close_receipt_is_not_verified_at_an_earlier_intraday_cutoff(self):
        self.get()
        value=KLineRepository(self.path).get('30m','301377',80,required_date=DAY,
            as_of=DAY+'T06:45:00+00:00')
        self.assertEqual(value.kline['minute_to_daily']['status'],'pending')

    def test_corrupt_or_version_changed_receipt_remains_local_pending(self):
        self.get()
        path=next(self.path.parent.glob('minute_basis_v1/*.json'))
        original=path.read_text()
        for text in ('{broken', original.replace('schema_version": 1','schema_version": 99')):
            path.write_text(text)
            value=self.get(KLineRepository(self.path))
            self.assertEqual(value.kline['minute_to_daily']['status'],'pending')
        path.write_text(original)
        self.assertEqual(self.get(KLineRepository(self.path)).kline['minute_to_daily']['status'],'verified')

    def test_postclose_receipt_cannot_certify_an_earlier_same_day_prefix(self):
        self.get()
        repository=KLineRepository(self.path,mode='backtest')
        result=repository.get('30m','301377',79,required_date=DAY,
            as_of=DAY+' 14:45:00')
        self.assertEqual(result.kline['dates'][-1],DAY+' 14:30:00')
        self.assertEqual(result.kline['minute_to_daily']['status'],'pending')
        self.assertIn('after_cutoff',result.kline['minute_to_daily']['reason'])

    def test_receipt_cutoff_handles_equivalent_aware_times_and_cross_day_consumption(self):
        self.get()
        path=next(self.path.parent.glob('minute_basis_v1/*.json'))
        receipts=json.loads(path.read_text())
        for receipt in receipts.values():
            receipt['as_of']=DAY+'T07:05:00+00:00'
            receipt['sha256']=price_basis.basis_sha256({k:v for k,v in receipt.items() if k!='sha256'})
        path.write_text(json.dumps(receipts))
        result=self.get(KLineRepository(self.path))
        self.assertEqual(result.kline['minute_to_daily']['status'],'verified')
        from chanlun.price_basis import canonical_daily_reference,verified_minute_basis
        with MarketHistoryStore(self.path,readonly=True) as store:
            reference=canonical_daily_reference('301377',store.query_bars('day',self.iid))
        for cutoff, expected in (('2026-09-24T06:45:00+00:00','verified'),
                                 (DAY+'T06:45:00+00:00','pending')):
            self.assertEqual(verified_minute_basis('301377','30m',result.kline,reference,receipts,cutoff)['status'],expected)

    def test_repository_daily_batch_retains_target_reference_on_sector_fallback_path(self):
        minute=self.analyzed(self.get())
        with patch.object(df,'_get_kline_repository',return_value=self.repo), \
             patch.object(df,'DAY_LOOKBACK',60):
            stock=df.batch_fetch_daily_klines([{'code':'301377','name':'样本',
                'raw_current_price':100.6}],required_date=DAY)[0]
        stock.update({k:stock['klines'][k] for k in ('dates','opens','highs','lows','closes','volumes')})
        self.assertAlmostEqual(stock['price_basis']['factor_vs_raw'],.5)
        self.assertAlmostEqual(price_basis.align_intraday_price(48.8,stock,minute),48.8)
        self.assertEqual(stock['price_basis']['canonical_daily']['identity_key'],'stock|SZ|301377')

    def test_changed_target_in_db_invalidates_cached_receipt(self):
        self.get()
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET close=close+0.1')
            store.connection.commit()
        result = self.get(KLineRepository(self.path))
        self.assertEqual(result.kline['minute_to_daily']['status'], 'pending')
        self.assertIsNone(price_basis.align_intraday_price(48.8, self.stock(), self.analyzed(result)))

    def test_old_qfq_cache_without_receipt_is_pending_even_when_four_prices_match(self):
        self.get()
        for path in self.path.parent.glob('minute_basis_v1/**/*.json'):
            path.unlink()
        result = self.get(KLineRepository(self.path))
        self.assertEqual(result.status, 'verified')
        self.assertEqual(result.kline['minute_to_daily']['status'], 'pending')
        self.assertIsNone(price_basis.align_intraday_price(48.8, self.stock(), self.analyzed(result)))

    def test_missing_listing_age_is_not_a_confirmed_new_listing(self):
        with MarketHistoryStore(self.path) as store:
            store.upsert_stock_meta(self.iid, DAY, {'name':'样本','is_st':False,'delisting_risk':False})
            _,diag=load_eligible_candidates(store,CUTOFF,60,0,minimum_bars=1,
                required_date=DAY,return_diagnostics=True)
        self.assertEqual(diag['excluded']['listed_days'],1)
        self.assertEqual(diag['listing_age_evidence']['unknown'],1)
        self.assertEqual(diag['listing_age_evidence']['below_minimum'],0)

    def test_real_breakdown_remains_rejected(self):
        result=self.get()
        self.assertFalse(_passes_upgrade_risk_guard(self.stock(), {'price':51.5}, self.analyzed(result)))

    def test_preclose_validator_never_promotes_unverified_sina_to_qfq(self):
        from chanlun.preclose_runtime import fetch_preclose_30m
        with patch.object(df, '_fetch_sina_minute_kline_remote', return_value=self.payload):
            got=fetch_preclose_30m([{'code':'301377'}],DAY,DAY+'T14:45:00+08:00')['301377']['klines']
        self.assertEqual(got['adjustment'], 'unverified')
        self.assertEqual(got['minute_to_daily']['status'], 'pending')

if __name__ == '__main__':
    unittest.main()

class CoverageDiagnosticTests(unittest.TestCase):
    def test_unknown_basis_is_not_counted_as_a_real_risk_or_no_confirmation(self):
        from tests.test_candidate_upgrade import make_stock, make_min30_result
        from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min
        stock=make_stock('000001',[{'type':'swing底背驰候选种子','tier':'seed','price':10}])
        minute=make_min30_result('000001')
        minute.strategy_input_evidence['minute_to_daily']={'status':'pending'}
        rows,diag=upgrade_daily_candidates_with_30min([stock],[minute])
        self.assertEqual(rows,[])
        self.assertEqual(diag['evaluation_by_code']['000001']['status'],'price_basis_unverified')
        self.assertEqual(diag['evaluation_stock_counts']['risk_rejected'],0)
        self.assertEqual(diag['evaluation_stock_counts']['valid_no_confirmation'],0)

    def test_multiple_buy_points_do_not_multiply_stock_counts(self):
        from tests.test_candidate_upgrade import make_stock, make_min30_result
        from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min
        bps=[{'type':'swing底背驰候选种子','tier':'seed','price':10}]*2
        stock=make_stock('000001',bps)
        minute=make_min30_result('000001',medium_confirm=False)
        _,diag=upgrade_daily_candidates_with_30min([stock],[minute])
        self.assertEqual(diag['evaluation_stock_counts']['valid_no_confirmation'],1)
        self.assertEqual(diag['evaluation_buy_point_counts']['valid_no_confirmation'],2)

    def test_explicit_unknown_or_malformed_contract_never_falls_back_to_legacy_factor(self):
        from tests.test_candidate_upgrade import make_stock,make_min30_result
        stock=make_stock('000001',[])
        for update in ({'adjustment':'unverified'}, {'status':'price_basis_unverified'},
                       {'minute_to_daily':None}, {'minute_to_daily':{}},
                       {'minute_to_daily':{'status':'pending'}}):
            minute=make_min30_result('000001')
            minute.strategy_input_evidence.update(update)
            self.assertIsNone(price_basis.align_intraday_price(10.,stock,minute),update)

    def test_failed_basis_fetch_is_not_flattened_into_generic_request_failure(self):
        from tests.test_candidate_upgrade import make_stock
        from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min
        stock=make_stock('000001',[{'type':'swing底背驰候选种子','tier':'seed','price':10}])
        _,diag=upgrade_daily_candidates_with_30min([stock],[],requested_codes={'000001'},
            failure_evidence={'stock|SZ|000001':{'status':'price_basis_unverified',
                'rejection_reason':'raw_daily_conflict:2026-09-23'}})
        self.assertEqual(diag['evaluation_by_code']['000001']['status'],'price_basis_unverified')

    def test_absent_requested_and_unrequested_minute_inputs_are_distinct(self):
        from tests.test_candidate_upgrade import make_stock
        from chanlun.candidate_upgrade import upgrade_daily_candidates_with_30min
        stocks=[make_stock(c,[{'type':'swing底背驰候选种子','tier':'seed','price':10}]) for c in ('000001','000002')]
        _,diag=upgrade_daily_candidates_with_30min(stocks,[],requested_codes={'000001'})
        self.assertEqual(diag['evaluation_by_code']['000001']['status'],'request_failed')
        self.assertEqual(diag['evaluation_by_code']['000002']['status'],'not_requested')
