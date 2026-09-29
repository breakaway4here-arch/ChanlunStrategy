import copy
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from chanlun import kaipanla as k

NOW=datetime(2026,9,29,10,0,tzinfo=timezone(timedelta(hours=8)))


class KaipanlaTests(unittest.TestCase):
    def test_theme_uses_response_date_and_is_never_formal(self):
        stock=['600000','浦发银行']+['']*15+['题材原因 <script>bad</script>']
        result=k.parse_themes({'errcode':'0','date':'2026-09-28','Day':['2026-09-29'],
            'list':[{'ZSCode':'801000','ZSName':'测试题材','StockList':[stock]}]},'2026-09-29')
        self.assertEqual(result['data_date'],'2026-09-28')
        self.assertEqual(result['status'],'previous_day')
        self.assertFalse(result['affects_formal'])
        self.assertEqual(result['groups'][0]['stocks'][0]['code'],'600000')

    def test_theme_bad_inputs_are_optional_empty(self):
        for raw in [{}, {'errcode':1016,'errmsg':'未登录'}, {'errcode':'0','date':'bad','list':[]}]:
            self.assertEqual(k.parse_themes(raw,'2026-09-29')['status'],'unavailable')

    def test_kline_qfq_hands_and_intraday_bar_exclusion(self):
        raw={'StockID':'600000','errcode':'0','x':['20260928','20260929'],
             'y':[[10,11,12,9],[11,11.2,11.3,10.9]],'vol':[100,20],'bal':[110000,22300]}
        result=k.parse_daily(raw,'600000',now=NOW)
        self.assertEqual(result['dates'],['2026-09-28'])
        self.assertEqual(result['adjustment'],'qfq')
        self.assertEqual(result['closes'].tolist(),[11])
        self.assertEqual(result['volume_unit'],'hands')
        self.assertEqual(result['source'],'kaipanla')
        self.assertIsNone(k.parse_daily(raw,'000001',now=NOW))

    def test_malformed_daily_rejected_not_relabelled(self):
        raw={'StockID':'600000','errcode':'0','x':['20260928'],'y':[[10,11,9,12]],'vol':[100],'bal':[110000]}
        self.assertIsNone(k.parse_daily(raw,'600000',now=NOW))

    def test_cached_intraday_bar_not_promoted_to_final_after_close(self):
        raw={'StockID':'600000','errcode':'0','x':['20260929'],'y':[[10,11,12,9]],'vol':[100],'bal':[110000],
             'Time':int(NOW.timestamp())}
        self.assertIsNone(k.parse_daily(raw,'600000',now=NOW.replace(hour=15,minute=5)))

    def test_success_and_failure_requests_are_cached_without_retry(self):
        for success in (True,False):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as tmp, \
                 patch.object(k,'_cooldown_until',0),patch.object(k.time,'sleep'), \
                 patch.object(k.requests,'Session') as session:
                response=Mock()
                response.json.return_value={'errcode':'0','list':[]} if success else {'errcode':'1016'}
                post=session.return_value.__enter__.return_value.post
                post.return_value=response
                one=k._request('https://example.test',{'a':'read'},cache_dir=Path(tmp),now=NOW)
                two=k._request('https://example.test',{'a':'read'},cache_dir=Path(tmp),now=NOW)
                self.assertEqual(one,two);post.assert_called_once()

    def test_display_escapes_provider_text_and_hides_failure(self):
        from chanlun.report_generator import _render_kaipanla_context
        self.assertEqual(_render_kaipanla_context({}), '')
        self.assertEqual(_render_kaipanla_context({'status':'unavailable','groups':[{}]}), '')
        html=_render_kaipanla_context({'status':'previous_day','data_date':'2026-09-28',
            'groups':[{'name':'<script>x</script>','stocks':[{'code':'600000','name':'A','reason':'<img src=x onerror=bad>'}]}]})
        self.assertIn('2026-09-28',html);self.assertIn('往期资料',html)
        self.assertNotIn('<script>',html);self.assertNotIn('<img',html)
        self.assertIn('不参与正式评分或 L1 排序',html)

    def test_normal_sources_do_not_request_new_source(self):
        from chanlun import data_fetcher as f
        good={'dates':['2026-09-28'],'opens':[10],'highs':[12],'lows':[9],'closes':[11],'volumes':[100]}
        with patch.object(f,'_fetch_daily_kline_remote',return_value=good), \
             patch.object(f,'_fetch_daily_kline_eastmoney_remote',return_value=None), \
             patch.object(f,'_fetch_daily_kline_sina_daily_remote',return_value=None), \
             patch.object(k,'fetch_daily') as fallback:
            self.assertIsNotNone(f._fetch_daily_for_repository('600000',1,required_date='2026-09-28'))
            fallback.assert_not_called()

    def test_all_existing_sources_failed_uses_last_backup(self):
        from chanlun import data_fetcher as f
        good={'dates':['2026-09-28'],'opens':[10],'highs':[12],'lows':[9],'closes':[11],'volumes':[100],
              'source':'kaipanla','volume_unit':'hands','adjustment':'qfq'}
        with patch.object(f,'_fetch_daily_kline_remote',return_value=None), \
             patch.object(f,'_fetch_daily_kline_eastmoney_remote',return_value=None), \
             patch.object(f,'_fetch_daily_kline_sina_daily_remote',return_value=None), \
             patch.object(k,'fetch_daily',return_value=good) as fallback:
            result=f._fetch_daily_for_repository('600000',1,required_date='2026-09-28')
            self.assertIsNotNone(result)
            self.assertEqual(result['source'],'kaipanla'); fallback.assert_called_once()

    def test_optional_themes_do_not_change_formal_projection(self):
        from chanlun.report_generator import build_formal_output_projection,build_full_daily_projection
        report={'date':'2026-09-29','picks_pure':[],'picks_fusion':[]}
        original=build_formal_output_projection(report)
        report['kaipanla_context']={'status':'available','data_date':'2026-09-29','groups':[],'affects_formal':False}
        after=build_formal_output_projection(report)
        # The protected public envelope gains this field; all pre-existing
        # facts, strategy rows, workspace membership and ordering stay identical.
        for surface in ('daily','aggregate'):
            self.assertEqual(after[surface].pop('kaipanla_context'),report['kaipanla_context'])
            original[surface].pop('kaipanla_context',None)
        self.assertEqual(after,original)
        self.assertEqual(build_full_daily_projection(report)['kaipanla_context'],report['kaipanla_context'])

    def test_generated_shell_contains_optional_card_but_failure_does_not_block(self):
        import json
        from chanlun.report_generator import _build_report_v2_html
        context={'status':'previous_day','data_date':'2026-09-28','groups':[{'name':'题材','stocks':[{'code':'600000','name':'样例','reason':'原因'}]}]}
        html=_build_report_v2_html('2026-09-29',json.dumps({'inlineReportData':{'kaipanla_context':context}}))
        self.assertIn('id="kaipanla-context"',html)
        self.assertIn('往期资料',html)
        self.assertIn('<div id="app"></div>',html)
        bad=_build_report_v2_html('2026-09-29',json.dumps({'inlineReportData':{'kaipanla_context':{'status':'unavailable'}}}))
        self.assertNotIn('id="kaipanla-context"',bad)
        self.assertIn('<div id="app"></div>',bad)

    def test_theme_exceptions_return_optional_unavailable(self):
        with patch.object(k,'_request',side_effect=OSError('cache unavailable')):
            self.assertEqual(k.fetch_themes('2026-09-29')['status'],'unavailable')
