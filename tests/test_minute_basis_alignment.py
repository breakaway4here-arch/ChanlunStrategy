import copy
import unittest
import tempfile
from pathlib import Path
import numpy as np
from chanlun import minute_sources as ms
from chanlun import data_fetcher as df
from chanlun.kline_repository import KLineRepository
from chanlun.market_history_store import MarketHistoryStore


def fixture(offset=-1, factor=1):
    times=['10:00','10:30','11:00','11:30','13:30','14:00','14:30','15:00']
    rows=[{'day':'2026-09-23 '+t+':00','open':'100','high':'104','low':'98','close':'101','volume':'10000','amount':'1010000'} for t in times]
    p=ms.clean_minutes(rows,source='sina',symbol='sz301377',scale=30)
    raw={'2026-09-23':{'open':100,'high':104,'low':98,'close':101,'is_final':True,'source':'tencent_raw'}}
    target={'2026-09-23':{**{k:raw['2026-09-23'][k]*factor+offset for k in ['open','high','low','close']},'is_final':True,'adjustment':'qfq','source':'canonical_day'}}
    return p,raw,target


class AlignmentTests(unittest.TestCase):
    def align(self,p,raw,target):
        self.assertTrue(hasattr(ms,'align_daily_basis'),'Missing verified per-day price mapping')
        return ms.align_daily_basis(p,raw,target,scale=30)

    def test_sina_is_first_stock_source(self):
        self.assertEqual(df._minute_providers(df._normalize_identity('600792'),80)[0][0],'sina')

    def test_cash_dividend_offset_verified_against_all_four_daily_prices(self):
        p,raw,target=fixture();original=copy.deepcopy(p)
        result=self.align(p,raw,target)
        self.assertEqual(result['adjustment'],'qfq')
        np.testing.assert_allclose(result['opens'],99)
        np.testing.assert_allclose(result['lows'],97)
        np.testing.assert_array_equal(p['opens'],original['opens'])
        np.testing.assert_array_equal(result['volumes'],p['volumes'])
        np.testing.assert_array_equal(result['amounts'],p['amounts'])
        self.assertIn('2026-09-23',result['price_basis_evidence'])

    def test_split_and_dividend_affine_mapping(self):
        p,raw,target=fixture(offset=-.2,factor=.5)
        np.testing.assert_allclose(self.align(p,raw,target)['highs'],51.8)

    def test_archived_source_keeps_provenance_while_matching_canonical_basis(self):
        p,raw,target=fixture()
        p.update(schema='archived_minute_v1',source='tdx',provider_adjustment='qfq')
        out=self.align(p,raw,target)
        self.assertEqual(out['source'],'tdx')
        self.assertEqual(out['provider_adjustment'],'qfq')
        self.assertEqual(out['adjustment'],'qfq')

    def test_each_day_has_its_own_mapping(self):
        p,raw,target=fixture()
        p2,raw2,target2=fixture(offset=0)
        p['dates']+= [d.replace('23','24') for d in p2['dates']]
        p['finals']+=p2['finals']
        for k in ('opens','highs','lows','closes','volumes','raw_volumes','amounts','amount_available'):
            p[k]=np.concatenate([p[k],p2[k]])
        raw['2026-09-24']=raw2['2026-09-23'];target['2026-09-24']=target2['2026-09-23']
        out=self.align(p,raw,target)
        np.testing.assert_allclose(out['opens'],[99]*8+[100]*8)

    def test_missed_intraday_extreme_rejected_before_fitting(self):
        p,raw,target=fixture();p['lows'][:]=99
        with self.assertRaisesRegex(ValueError,'raw_daily_conflict'):
            self.align(p,raw,target)

    def test_non_affine_target_rejected(self):
        p,raw,target=fixture();target['2026-09-23']['open']+=.5
        with self.assertRaisesRegex(ValueError,'non_affine'):
            self.align(p,raw,target)

    def test_missing_or_nonfinal_target_rejected(self):
        for kind in ['missing','nonfinal']:
            p,raw,target=fixture()
            if kind=='missing':target={}
            else:target['2026-09-23']['is_final']=False
            with self.assertRaises(ValueError):self.align(p,raw,target)

    def test_incomplete_day_and_unknown_units_rejected(self):
        p,raw,target=fixture();p['volume_unit']='unknown'
        with self.assertRaises(ValueError):self.align(p,raw,target)
        p,raw,target=fixture();p['dates'][0]='2026-09-23 09:30:00'
        with self.assertRaises(ValueError):self.align(p,raw,target)

    def test_flat_day_nonidentity_mapping_is_not_invented(self):
        p,raw,target=fixture()
        for k in ('opens','highs','lows','closes'):p[k][:]=100
        for k in ('open','high','low','close'):raw['2026-09-23'][k]=100;target['2026-09-23'][k]=99
        with self.assertRaises(ValueError):self.align(p,raw,target)

    def test_repository_can_verify_against_its_own_final_daily_basis(self):
        import inspect
        self.assertIn('raw_daily_reader',inspect.signature(KLineRepository).parameters)
        p,raw,target=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db.sqlite'
            with MarketHistoryStore(path) as store:
                iid=store.upsert_instrument('stock','SZ','301377')
                day=target['2026-09-23']
                store.upsert_bars('day',iid,[dict(day,ts='2026-09-23',volume=800,
                    amount=8080000,source_batch='test_daily',volume_unit='hands')],adjustment='qfq')
            repo=KLineRepository(path,remote_fetchers={'30m':lambda *a,**kw:p},
                                raw_daily_reader=lambda *a,**kw:raw)
            result=repo.get('30m','301377',8,required_date='2026-09-23',as_of='2026-09-23T15:05:00+08:00')
            self.assertEqual(result.status,'verified')
            np.testing.assert_allclose(result.kline['opens'],99)
            np.testing.assert_allclose(result.kline['volumes'],100)
            self.assertIn('price_basis_evidence',result.diagnostics)

    def test_unverified_rounded_window_metadata_is_sliced_with_prices(self):
        p,raw,target=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            repo=KLineRepository(Path(tmp)/'db.sqlite',remote_fetchers={'30m':lambda *a,**kw:p})
            out=repo.get('30m','301377',7,required_date='2026-09-23',as_of='2026-09-23T15:05:00+08:00').kline
            for key in ['dates','opens','amounts','amount_available','raw_volumes']:
                self.assertEqual(len(out[key]),7,key)


if __name__=='__main__':unittest.main()
