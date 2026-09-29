import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from pathlib import Path

from chanlun import quote_sources as q
from chanlun.market_close_snapshot import ingest_market_close_snapshot
from chanlun.market_history_store import MarketHistoryStore

NOW = datetime(2026, 9, 29, 15, 5, tzinfo=timezone(timedelta(hours=8)))


def sina(symbol='sh600000', date='2026-09-29', time='15:00:00', volume='10000'):
    p = ['测试', '10', '10', '10.2', '10.3', '9.9', '10.2', '10.2', volume, '102000'] + ['0'] * 20
    return 'var hq_str_' + symbol + '="' + ','.join(p + [date, time, '00']) + '";'


def tencent(symbol='sz000001'):
    p = ['0'] * 50
    for k, v in {1:'测试', 2:symbol[2:], 3:'10.2', 4:'10', 5:'10', 6:'100', 30:'20260929150000', 33:'10.3', 34:'9.9', 35:'10.2/100/102000', 37:'10.2'}.items(): p[k] = v
    return 'v_' + symbol + '="' + '~'.join(p) + '";'


class Response:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass
    def json(self): return json.loads(self.text)


class Session:
    def __init__(self, sina_text='', tencent_text=''):
        self.calls = []
        self.sina_text, self.tencent_text = sina_text, tencent_text
    def get(self, url, **kw):
        self.calls.append((url, kw.get('params', {})))
        if 'getHQNodeStockCount' in url: return Response('"2"')
        if 'getHQNodeData' in url:
            return Response(json.dumps([{'symbol':'sh600000','code':'600000','name':'A'}, {'symbol':'sz000001','code':'000001','name':'B'}]))
        return Response(self.sina_text if 'sinajs' in url else self.tencent_text)


def down(**kwargs): return [], {'complete':False,'requested':5920,'unique':0,'error':'disconnected'}


class QuoteSourceTests(unittest.TestCase):
    def test_sina_shares_and_tencent_hands_are_equal(self):
        a=q.parse_quotes(sina(), 'sina', NOW)['sh600000']
        b=q.parse_quotes(tencent('sh600000'), 'tencent', NOW)['sh600000']
        self.assertEqual(a['volume'], b['volume'])
        self.assertEqual(a['amount'], b['amount'])
        self.assertEqual(a['volume_raw_unit'], 'shares')
        self.assertEqual(b['volume_raw_unit'], 'hands')

    def test_tencent_star_market_volume_is_shares_not_hands(self):
        text=tencent('sh688041').replace('~100~','~10000~').replace('/100/','/10000/')
        parsed=q.parse_quotes(text,'tencent',NOW)
        self.assertIn('sh688041',parsed)
        self.assertEqual(parsed['sh688041']['volume'],100)
        self.assertEqual(parsed['sh688041']['volume_raw_unit'],'shares')

    def test_reject_stale_future_intraday_nonfinite_and_wrong_identity(self):
        for text in [sina(date='2026-09-28'), sina(time='15:10:00'), sina(time='14:59:00'), sina(volume='nan'), sina('sh000001'), '<html>error</html>']:
            with self.subTest(text=text[:55]): self.assertEqual(q.parse_quotes(text,'sina',NOW), {})

    def test_missing_only_falls_through_to_tencent(self):
        session=Session(sina(), tencent())
        rows, d=q.fetch_quotes(down, session=session, now=NOW)
        self.assertTrue(d['complete'])
        self.assertEqual(d['requested'],2)
        self.assertEqual(d['valid_quotes'],2)
        self.assertEqual({r['quote_source'] for r in rows},{'sina','tencent'})
        calls=[url for url,params in session.calls if 'gtimg' in url]
        self.assertEqual(calls,['https://qt.gtimg.cn/q=sz000001'])

    def test_same_close_cache_reuses_success_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Session(sina()+sina('sz000001'))
            one=q.fetch_quotes(down,session=session,now=NOW,cache_dir=Path(tmp))
            session.calls.clear()
            two=q.fetch_quotes(lambda **kw:self.fail('successful close cache must be reused'),session=session,now=NOW,cache_dir=Path(tmp))
            self.assertEqual(one[0],two[0]); self.assertEqual(session.calls,[])

    def test_unquoted_members_not_removed_from_denominator(self):
        rows,d=q.fetch_quotes(down,session=Session(sina()),now=NOW)
        self.assertTrue(d['complete'])
        self.assertEqual(d['unique'],2)
        self.assertEqual(d['valid_quotes'],1)
        self.assertEqual(len(d['missing_quote_symbols']),1)
        self.assertIsNone(next(r for r in rows if r['code']=='000001').get('current_price'))

    def test_complete_eastmoney_does_not_call_backups(self):
        rows=list(q.parse_quotes(sina(),'sina',NOW).values())
        rows[0].update(quote_source='eastmoney',volume_source='eastmoney',amount_source='eastmoney',volume_raw_unit='hands')
        session=Session()
        out,d=q.fetch_quotes(lambda **kw:(rows,{'complete':True,'requested':1,'unique':1}),session=session,now=NOW)
        self.assertEqual({k:out[0][k] for k in rows[0]},rows[0]); self.assertEqual(session.calls,[])

    def test_universe_duplicate_page_is_not_complete(self):
        class BadSession(Session):
            def get(self,url,**kw):
                if 'getHQNodeStockCount' in url:return Response('"4"')
                return super().get(url,**kw)
        _,d=q.fetch_quotes(down,session=BadSession(),now=NOW,batch_size=2)
        self.assertFalse(d['complete'])

    def test_empty_page_retries_only_that_page(self):
        class EmptyOnce(Session):
            def __init__(self): super().__init__(sina()+sina('sz000001')); self.pages=0
            def get(self,url,**kw):
                if 'getHQNodeData' in url:
                    self.pages+=1
                    if self.pages==1:return Response('[]')
                return super().get(url,**kw)
        session=EmptyOnce()
        with patch('chanlun.quote_sources.time.sleep') as sleep:
            _,d=q.fetch_quotes(down,session=session,now=NOW)
        self.assertTrue(d['complete']);self.assertEqual(session.pages,2)
        sleep.assert_called_once_with(2)

    def test_partial_cache_only_requests_missing_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            q.fetch_quotes(down,session=Session(sina()),now=NOW,cache_dir=Path(tmp))
            session=Session(sina('sz000001'))
            rows,d=q.fetch_quotes(lambda **kw:self.fail('cached verified inventory'),session=session,now=NOW,cache_dir=Path(tmp))
            self.assertEqual(d['valid_quotes'],2)
            self.assertEqual([url for url,_ in session.calls],['https://hq.sinajs.cn/list=sz000001'])

    def test_yesterday_cache_not_used_and_extra_response_identity_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'quotes-2026-09-29.json'
            cache.write_text(json.dumps({'fetched_at':'2026-09-28T15:05:00+08:00','requested':1,
                                         'rows':list(q.parse_quotes(sina(),'sina',NOW).values()),'universe_source':'sina_hs_a'}))
            rows,d=q.fetch_quotes(down,session=Session(sina()+sina('sz000001')+sina('sh600001')),now=NOW,cache_dir=Path(tmp))
            self.assertEqual(len(rows),2);self.assertEqual(d['valid_quotes'],2)

    def test_wrong_volume_scale_and_naive_timestamp_rejected(self):
        row=q.parse_quotes(sina(),'sina',NOW)['sh600000']
        row['volume']*=100
        self.assertFalse(q.valid_quote(row,NOW))
        row['volume']/=100;row['quote_asof']='2026-09-29T15:00:00'
        self.assertFalse(q.valid_quote(row,NOW))

    def test_stale_eastmoney_quote_replaced_without_overwriting_valid_one(self):
        rows=list(q.parse_quotes(sina()+sina('sz000001'),'sina',NOW).values())
        for row in rows:row['quote_source']='eastmoney'
        rows[1]['quote_asof']='2026-09-28T15:00:00+08:00'
        session=Session(sina('sz000001'))
        out,d=q.fetch_quotes(lambda **kw:(rows,{'complete':True,'requested':2,'unique':2}),session=session,now=NOW)
        self.assertEqual(d['quote_sources'],{'eastmoney':1,'sina':1})
        self.assertEqual([url for url,_ in session.calls],['https://hq.sinajs.cn/list=sz000001'])

    def test_dead_first_backup_yields_budget_to_second_source(self):
        rows=[{'code':'60000'+str(n),'exchange':'SH','asset_type':'stock'} for n in range(5)]
        session=Session('', ''.join(tencent('sh'+r['code']) for r in rows))
        _,d=q.fetch_quotes(lambda **kw:(rows,{'complete':True,'requested':5,'unique':5}),session=session,now=NOW,batch_size=1)
        self.assertEqual(d['valid_quotes'],5)
        self.assertEqual(sum('sinajs' in url for url,_ in session.calls),2)

    def test_close_ingestion_preserves_fallback_source_and_rejects_intraday(self):
        for timestamp in ('15:00:00','14:59:00'):
            with self.subTest(timestamp=timestamp), tempfile.TemporaryDirectory() as tmp:
                db=Path(tmp)/'history.sqlite'
                with MarketHistoryStore(db) as store:
                    ident=store.upsert_instrument('stock','SH','600000',name='测试')
                    store.upsert_bars('day',ident,[{'ts':'2026-09-28','open':5,'high':5,'low':5,'close':5,
                                                  'volume':100,'amount':50000,'is_final':True,'adjustment':'qfq'}])
                row=q.parse_quotes(sina(),'sina',NOW)['sh600000']
                row['quote_asof']='2026-09-29T'+timestamp+'+08:00'
                result=ingest_market_close_snapshot(db,'2026-09-29',
                    lambda **kw:([row],{'complete':True,'requested':1,'unique':1}),generated_at=NOW)
                with MarketHistoryStore(db,readonly=True) as store:
                    bars=store.connection.execute("SELECT source_batch, volume_source, volume_raw_unit, volume,close FROM bars_day WHERE ts='2026-09-29'").fetchall()
                if timestamp=='15:00:00':
                    self.assertEqual(result['written'],1)
                    self.assertEqual(tuple(bars[0]),('official_close_snapshot:sina','sina','shares',100,5.1))
                else:
                    self.assertEqual(result['written'],0);self.assertEqual(bars,[])
