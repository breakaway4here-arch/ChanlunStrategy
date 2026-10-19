"""Offline recovery of the frozen legacy preclose delivery, never real notices."""
import copy
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from chanlun.preclose_notify import (NotificationOutbox, publish_preclose_and_notify,
    publish_preclose_snapshot, send_wxpusher_message, send_reconciliation_notifications)
from preclose_run import PrecloseExecutionDeadline, _deadline_alarm


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self.payload = status, payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


def accepted_payload(uid='fixture', code=1000):
    return {'success': True, 'code': 1000, 'data': [
        {'uid': uid, 'topicId': None, 'messageContentId': 123,
         'code': code, 'status': 'fixture accepted' if code == 1000 else 'fixture rejected'}]}


class DeliveryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {'trade_date': '2026-10-16', 'snapshot_id': 'preclose:2026-10-16:fixture',
                         'content_hash': 'a' * 64, 'status': 'empty', 'pools': {}}
        self.calls = []
        self.addCleanup(patch.stopall)
        patch('time.sleep').start()

    def matching(self):
        return Response(payload=self.snapshot)

    def publish(self, put, get, **kwargs):
        return publish_preclose_snapshot(self.snapshot, api_base='https://fixture.invalid',
            write_token='fixture', put=put, get=get, **kwargs)

    def test_lost_put_response_is_read_back_without_another_write(self):
        def put(*args, **kwargs):
            self.calls.append('put')
            raise requests.exceptions.SSLError('response lost')
        def get(*args, **kwargs):
            self.calls.append('get')
            return self.matching()
        result = self.publish(put, get)
        self.assertTrue(result['success'])
        self.assertEqual(self.calls, ['put', 'get'])

    def test_accepted_write_with_unparseable_response_still_requires_exact_get(self):
        class UnparseableResponse(Response):
            def json(self): raise ValueError('response body truncated')
        def put(*args, **kwargs): self.calls.append('put'); return UnparseableResponse()
        def get(*args, **kwargs): self.calls.append('get'); return self.matching()
        result=self.publish(put,get)
        self.assertTrue(result['success'])
        self.assertEqual(self.calls,['put','get'])

    def test_unknown_write_with_404_retries_identical_frozen_snapshot(self):
        puts, gets = [], []
        def put(*args, **kwargs):
            puts.append(copy.deepcopy(kwargs['json']))
            if len(puts) == 1:
                raise requests.Timeout('no response')
            return Response(payload={'revision': 1})
        def get(*args, **kwargs):
            gets.append(True)
            return Response(404) if len(gets) == 1 else self.matching()
        result = self.publish(put, get)
        self.assertTrue(result['success'])
        self.assertEqual(puts, [self.snapshot, self.snapshot])

    def test_readback_network_failure_retries_get_without_repeating_put(self):
        def put(*args, **kwargs):
            self.calls.append('put'); return Response(payload={'revision': 2})
        def get(*args, **kwargs):
            self.calls.append('get')
            if self.calls.count('get') == 1:
                raise requests.ConnectionError('SSL disconnected')
            return self.matching()
        result = self.publish(put, get)
        self.assertTrue(result['success'])
        self.assertEqual(self.calls, ['put', 'get', 'get'])

    def test_unreadable_unknown_result_never_rewrites_or_notifies(self):
        def put(*args, **kwargs):
            self.calls.append('put'); raise requests.Timeout('lost')
        def get(*args, **kwargs):
            self.calls.append('get'); raise requests.ConnectionError('unreachable')
        result = self.publish(put, get)
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, ['put', 'get', 'get', 'get'])

    def test_retryable_service_error_and_429_are_bounded(self):
        for status in (429, 503):
            calls = []
            def put(*args, **kwargs):
                calls.append('put'); return Response(status)
            def get(*args, **kwargs):
                calls.append('get'); return Response(404)
            result = self.publish(put, get)
            self.assertFalse(result['success'])
            self.assertEqual(calls, ['put', 'get'] * 3)

    def test_429_retry_after_is_observed_only_with_remaining_delivery_budget(self):
        for budget, expected_puts in [(10, 2), (1, 1)]:
            calls = []
            def put(*args, **kwargs):
                calls.append('put')
                return Response(429, headers={'Retry-After': '2'}) if len(calls) == 1 else Response()
            with patch('time.sleep') as sleep:
                result = self.publish(put, lambda *a, **k: Response(404) if len(calls) == 1 else self.matching(),
                                      budget_remaining=lambda: budget)
            self.assertEqual(len(calls), expected_puts)
            self.assertEqual(result['success'], budget == 10)
            if budget == 10: sleep.assert_called_once_with(2)
            else: sleep.assert_not_called()

    def test_authorization_and_conflict_are_not_retried(self):
        for status in (400, 401, 403, 409, 412):
            calls = []
            def put(*args, **kwargs):
                calls.append('put'); return Response(status)
            result = self.publish(put, lambda *a, **k: calls.append('get'))
            self.assertFalse(result['success'])
            self.assertEqual(calls, ['put'])

    def test_wrong_identity_hash_or_date_never_unlocks_notifications(self):
        for field in ('snapshot_id', 'content_hash', 'trade_date'):
            wrong = dict(self.snapshot, **{field: 'wrong'})
            posts = []
            with tempfile.TemporaryDirectory() as directory:
                result = publish_preclose_and_notify(self.snapshot, api_base='https://fixture.invalid',
                    write_token='fixture', wxpusher_app_token='fixture', wxpusher_uid='fixture',
                    outbox=NotificationOutbox(Path(directory)/'outbox.jsonl'),
                    put=lambda *a, **k: Response(), get=lambda *a, **k: Response(payload=wrong),
                    post=lambda *a, **k: posts.append(True))
            self.assertFalse(result['publish']['success'])
            self.assertEqual(result['publish']['error'], 'readback_mismatch')
            self.assertEqual(posts, [])

    def test_exhausted_total_budget_stops_before_any_network_or_late_retry(self):
        result = self.publish(lambda *a, **k: self.calls.append('put'),
            lambda *a, **k: self.calls.append('get'), budget_remaining=lambda: 0)
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, [])
        remaining = [0.1]
        def put(*args, **kwargs):
            self.assertLessEqual(kwargs['timeout'], 0.1)
            self.calls.append('put'); remaining[0] = 0
            raise requests.Timeout('deadline')
        result = self.publish(put, lambda *a, **k: self.calls.append('get'),
                              budget_remaining=lambda: remaining[0])
        self.assertFalse(result['success'])
        self.assertEqual(self.calls, ['put'])

    def test_resume_notifies_only_channel_not_already_provider_accepted(self):
        posts = []
        with tempfile.TemporaryDirectory() as directory:
            outbox = NotificationOutbox(Path(directory)/'outbox.jsonl')
            def run():
                return publish_preclose_and_notify(self.snapshot, api_base='https://fixture.invalid',
                    write_token='fixture', wxpusher_app_token='fixture', wxpusher_uid='fixture',
                    wecom_webhook='https://fixture.invalid/wecom', outbox=outbox,
                    put=lambda *a, **k: Response(), get=lambda *a, **k: self.matching(), post=post)
            def post(url, **kwargs):
                posts.append(url)
                if 'wxpusher' in url: return Response(payload=accepted_payload())
                return Response(payload={'errcode': 1 if posts.count(url) == 1 else 0})
            first, second = run(), run()
        self.assertEqual(len(posts), 3)
        self.assertEqual(first['notifications']['wxpusher'].get('delivery_status'), 'provider_accepted')
        self.assertEqual(second['notifications']['wxpusher']['status'], 'already_sent')
        self.assertTrue(second['notifications']['wecom']['success'])

    def test_unknown_provider_result_is_not_blindly_sent_again(self):
        posts = []
        with tempfile.TemporaryDirectory() as directory:
            outbox = NotificationOutbox(Path(directory)/'outbox.jsonl')
            def post(*args, **kwargs):
                posts.append(True)
                raise requests.Timeout('response may be lost after acceptance')
            def run():
                return publish_preclose_and_notify(self.snapshot, api_base='https://fixture.invalid',
                    write_token='fixture', wxpusher_app_token='fixture', wxpusher_uid='fixture',
                    outbox=outbox, put=lambda *a, **k: Response(),
                    get=lambda *a, **k: self.matching(), post=post)
            first, second = run(), run()
            self.assertEqual(len([row for row in outbox._rows() if row.get('dispatch_state') != 'dispatching']), 1)
        self.assertEqual(posts, [True])
        for result in (first, second):
            delivery=result['notifications']['wxpusher']
            self.assertFalse(delivery['success'])
            self.assertEqual(delivery.get('delivery_status'), 'provider_result_unknown')
            self.assertEqual(delivery.get('error'), 'Timeout')

    def test_legacy_unknown_provider_row_remains_protected_without_new_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            outbox = NotificationOutbox(Path(directory)/'outbox.jsonl')
            outbox.record(content_hash=self.snapshot['content_hash'], channel='wxpusher',
                          success=False, response={'success': False, 'provider': 'wxpusher', 'error': 'SSLError'})
            posts=[]
            result=publish_preclose_and_notify(self.snapshot, api_base='https://fixture.invalid',
                write_token='fixture', wxpusher_app_token='fixture', wxpusher_uid='fixture', outbox=outbox,
                put=lambda *a, **k: Response(), get=lambda *a, **k: self.matching(),
                post=lambda *a, **k: posts.append(True))
        self.assertFalse(result['notifications']['wxpusher']['success'])
        self.assertEqual(posts, [])

    def test_unparseable_provider_response_is_unknown_and_never_blindly_resent(self):
        class UnparseableResponse(Response):
            def json(self): raise ValueError('response body truncated')
        with tempfile.TemporaryDirectory() as directory:
            outbox = NotificationOutbox(Path(directory)/'outbox.jsonl')
            posts=[]
            def post(*args, **kwargs): posts.append(True); return UnparseableResponse()
            for _ in range(2):
                result=publish_preclose_and_notify(self.snapshot, api_base='https://fixture.invalid',
                    write_token='fixture', wxpusher_app_token='fixture', wxpusher_uid='fixture', outbox=outbox,
                    put=lambda *a, **k: Response(), get=lambda *a, **k: self.matching(),post=post)
                self.assertEqual(result['notifications']['wxpusher'].get('delivery_status'),'provider_result_unknown')
            self.assertEqual(posts,[True])


class ProviderDispatchGuards(unittest.TestCase):
    def setUp(self):
        self.snapshot={'trade_date': '2026-10-19', 'snapshot_id': 'preclose:2026-10-19:guard',
                       'content_hash': 'd' * 64, 'status': 'empty', 'pools': {}}
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.outbox=NotificationOutbox(Path(self.temp.name)/'outbox.jsonl')

    def run_delivery(self, post):
        return publish_preclose_and_notify(self.snapshot,api_base='https://fixture.invalid',
            write_token='fixture',wxpusher_app_token='fixture',wxpusher_uid='fixture',outbox=self.outbox,
            put=lambda *a, **k: Response(),get=lambda *a, **k: Response(payload=self.snapshot),post=post)

    def test_chunked_put_and_get_recover_with_real_requests_exception(self):
        for fail_at in ('put','get'):
            calls=[]
            def put(*a,**k):
                calls.append('put')
                if fail_at=='put': raise requests.exceptions.ChunkedEncodingError('response incomplete')
                return Response()
            def get(*a,**k):
                calls.append('get')
                if fail_at=='get' and calls.count('get')==1:
                    raise requests.exceptions.ChunkedEncodingError('read incomplete')
                return Response(payload=self.snapshot)
            with patch('time.sleep'):
                result=publish_preclose_snapshot(self.snapshot,api_base='https://fixture.invalid',
                    write_token='fixture',put=put,get=get)
            self.assertTrue(result['success'])
            self.assertEqual(calls,['put','get'] if fail_at=='put' else ['put','get','get'])

    def test_transport_error_carrying_auth_or_conflict_response_cannot_unlock_get(self):
        for status in (401,403,409,412):
            calls=[]
            def put(*a,**k):
                calls.append('put')
                raise requests.exceptions.ChunkedEncodingError('error response truncated',response=Response(status))
            def get(*a,**k): calls.append('get'); return Response(payload=self.snapshot)
            result=publish_preclose_snapshot(self.snapshot,api_base='https://fixture.invalid',
                write_token='fixture',put=put,get=get)
            self.assertFalse(result['success'])
            self.assertEqual(calls,['put'])

    def test_deadline_and_keyboard_interrupt_escape_but_leave_durable_unknown(self):
        for interruption in (PrecloseExecutionDeadline('delivery'),KeyboardInterrupt(),SystemExit(143)):
            with self.subTest(interruption=type(interruption).__name__):
                self.outbox=NotificationOutbox(Path(self.temp.name)/(type(interruption).__name__+'.jsonl'))
                posts=[]; observed=[]
                def post(*a,**k):
                    posts.append(True); observed.extend(self.outbox._rows()); raise interruption
                with self.assertRaises(type(interruption)): self.run_delivery(post)
                self.assertTrue(observed,'dispatch marker must be durable before POST')
                self.assertEqual(observed[-1].get('dispatch_state'),'dispatching')
                second=self.run_delivery(lambda *a,**k: (posts.append(True) or Response(payload=accepted_payload())))
                self.assertEqual(posts,[True])
                self.assertFalse(second['notifications']['wxpusher']['success'])
                self.assertEqual(second['notifications']['wxpusher'].get('delivery_status'),'provider_result_unknown')

    def test_actual_alarm_during_post_leaves_unknown_and_does_not_resend(self):
        posts=[]
        def post(*a,**k): posts.append(True); time.sleep(0.1); return Response(payload=accepted_payload())
        with self.assertRaises(PrecloseExecutionDeadline):
            with _deadline_alarm(0.01,'delivery'): self.run_delivery(post)
        result=self.run_delivery(post)
        self.assertEqual(posts,[True])
        self.assertFalse(result['notifications']['wxpusher']['success'])

    def test_success_and_explicit_rejection_close_matching_dispatch_attempt(self):
        posts=[]
        def post(*a,**k):
            posts.append(True)
            return Response(payload=accepted_payload(code=1001 if len(posts)==1 else 1000))
        first,second,third=self.run_delivery(post),self.run_delivery(post),self.run_delivery(post)
        self.assertFalse(first['notifications']['wxpusher']['success'])
        self.assertEqual(first['notifications']['wxpusher'].get('target_business_code'),1001)
        self.assertEqual(first['notifications']['wxpusher'].get('delivery_status'),'provider_rejected')
        self.assertTrue(second['notifications']['wxpusher']['success'])
        self.assertEqual(third['notifications']['wxpusher']['status'],'already_sent')
        self.assertEqual(posts,[True,True])
        rows=self.outbox._rows()
        self.assertEqual([row.get('dispatch_state') for row in rows],['dispatching','final']*2)
        self.assertEqual(rows[0].get('dispatch_id'),rows[1].get('dispatch_id'))
        self.assertEqual(rows[2].get('dispatch_id'),rows[3].get('dispatch_id'))
        self.assertNotEqual(rows[0].get('dispatch_id'),rows[2].get('dispatch_id'))

    def test_missing_duplicate_or_malformed_target_is_unknown_and_not_resent(self):
        payloads=[{'success':True,'code':1000},accepted_payload(uid='other'),
            dict(accepted_payload(),data=[]),dict(accepted_payload(),data={}),
            dict(accepted_payload(),data=[None]),
            dict(accepted_payload(),data=accepted_payload()['data']+accepted_payload(code=1001)['data']),
            dict(accepted_payload(),data=[{'uid':'fixture','code':'1000'}]),
            dict(accepted_payload(),success=False)]
        for index,payload in enumerate(payloads):
            with self.subTest(payload=payload):
                self.outbox=NotificationOutbox(Path(self.temp.name)/(str(index)+'.jsonl'))
                posts=[]
                def post(*a,**k): posts.append(True); return Response(payload=payload)
                for _ in range(2):
                    delivery=self.run_delivery(post)['notifications']['wxpusher']
                    self.assertFalse(delivery['success'])
                    self.assertEqual(delivery.get('delivery_status'),'provider_result_unknown')
                self.assertEqual(posts,[True])

    def test_latest_uid_schema_without_legacy_ids_is_accepted_and_keeps_optional_ids(self):
        for legacy_ids in ({},{'messageId':99,'sendRecordId':88}):
            payload=accepted_payload();payload['data'][0].update(legacy_ids)
            result=send_wxpusher_message('fixture',app_token='fixture',uid='fixture',
                post=lambda *a,**k: Response(payload=payload))
            self.assertTrue(result['success'])
            self.assertTrue(result.get('provider_accepted'))
            self.assertEqual(result.get('target_business_code'),1000)
            self.assertEqual(result.get('message_content_ids'),[123])
            if legacy_ids:
                self.assertEqual(result.get('message_ids'),[99])
                self.assertEqual(result.get('send_record_ids'),[88])

    def test_other_recipient_rejection_does_not_reject_our_accepted_target(self):
        payload=accepted_payload()
        payload['data'].insert(0,dict(accepted_payload(uid='other',code=1001)['data'][0],
                                      messageId=999,messageContentId=999))
        result=send_wxpusher_message('fixture',app_token='fixture',uid='fixture',
            post=lambda *a,**k: Response(payload=payload))
        self.assertTrue(result['success'])
        self.assertEqual(result.get('target_business_code'),1000)
        self.assertEqual(result.get('message_content_ids'),[123])
        self.assertNotIn('message_ids',result)

    def test_explicit_http_rejection_closes_dispatch_and_allows_later_attempt(self):
        posts=[]
        def post(*a,**k):
            posts.append(True)
            return Response(401) if len(posts)==1 else Response(payload=accepted_payload())
        first,second=self.run_delivery(post),self.run_delivery(post)
        self.assertFalse(first['notifications']['wxpusher']['success'])
        self.assertEqual(first['notifications']['wxpusher'].get('delivery_status'),'provider_rejected')
        self.assertTrue(second['notifications']['wxpusher']['success'])
        self.assertEqual(posts,[True,True])

    def test_outbox_write_failure_prevents_post_and_final_write_failure_preserves_unknown(self):
        posts=[]
        def post(*a,**k): posts.append(True); return Response(payload=accepted_payload())
        with patch.object(self.outbox,'record',side_effect=OSError('disk write failed')):
            with self.assertRaises(OSError): self.run_delivery(post)
        self.assertEqual(posts,[])
        original=self.outbox.record
        calls=[]
        def record(**kwargs):
            calls.append(True)
            if len(calls)==2: raise OSError('final fsync failed')
            return original(**kwargs)
        with patch.object(self.outbox,'record',side_effect=record):
            with self.assertRaises(OSError): self.run_delivery(post)
        result=self.run_delivery(post)
        self.assertEqual(posts,[True])
        self.assertFalse(result['notifications']['wxpusher']['success'])

    def test_deadline_exhausted_by_dispatch_fsync_never_starts_post(self):
        remaining=[10]
        original=self.outbox.record
        def record(**kwargs):
            result=original(**kwargs)
            if kwargs.get('dispatch_state')=='dispatching': remaining[0]=0
            return result
        posts=[]
        with patch.object(self.outbox,'record',side_effect=record):
            result=publish_preclose_and_notify(self.snapshot,api_base='https://fixture.invalid',
                write_token='fixture',wxpusher_app_token='fixture',wxpusher_uid='fixture',outbox=self.outbox,
                put=lambda *a,**k: Response(),get=lambda *a,**k: Response(payload=self.snapshot),
                post=lambda *a,**k: (posts.append(True) or Response(payload=accepted_payload())),
                budget_remaining=lambda: remaining[0])
        self.assertEqual(posts,[])
        self.assertFalse(result['notifications']['wxpusher']['success'])

    def test_reconciliation_uses_same_dispatch_guard_and_preserves_event_identity(self):
        reconciliation={'trade_date':'2026-10-19','status':'changed','formal_content_hash':'f'*64,'pools':{}}
        posts=[]
        def post(*a,**k):
            posts.append(True)
            if len(posts)==1: raise PrecloseExecutionDeadline('delivery')
            return Response(payload=accepted_payload())
        def run():
            return send_reconciliation_notifications(reconciliation,outbox=self.outbox,
                wxpusher_app_token='fixture',wxpusher_uid='fixture',post=post)
        with self.assertRaises(PrecloseExecutionDeadline): run()
        result=run()
        self.assertEqual(posts,[True])
        self.assertFalse(result['wxpusher']['success'])
        row=self.outbox._rows()[0]
        self.assertEqual(row.get('phase'),'reconciliation')
        self.assertEqual(row.get('event_type'),'changed')
        self.assertTrue(row.get('idempotency_key').startswith('2026-10-19:reconciliation:changed:'))

    def test_partial_dispatch_write_is_completed_before_only_post(self):
        real_write=os.write
        writes=[];posts=[];observed=[]
        def short_write(fd,data):
            writes.append(len(data))
            return real_write(fd,data[:len(data)//2]) if len(writes)==1 else real_write(fd,data)
        def post(*a,**k):
            posts.append(True);observed.extend(self.outbox._rows())
            if len(posts)==1: raise PrecloseExecutionDeadline('delivery')
            return Response(payload=accepted_payload())
        with patch('chanlun.preclose_notify.os.write',side_effect=short_write):
            with self.assertRaises(PrecloseExecutionDeadline): self.run_delivery(post)
        result=self.run_delivery(post)
        self.assertEqual(posts,[True])
        self.assertEqual(len(writes),2)
        self.assertEqual(writes[1],writes[0]-writes[0]//2)
        self.assertEqual(observed[-1]['dispatch_state'],'dispatching')
        self.assertFalse(result['notifications']['wxpusher']['success'])

    def test_zero_or_negative_dispatch_write_fails_before_post_or_fsync(self):
        for index,count in enumerate((0,-1)):
            self.outbox=NotificationOutbox(Path(self.temp.name)/('no-progress-'+str(index)+'.jsonl'))
            posts=[]
            with patch('chanlun.preclose_notify.os.write',return_value=count), patch('chanlun.preclose_notify.os.fsync') as fsync:
                with self.assertRaises(OSError):
                    self.run_delivery(lambda *a,**k: (posts.append(True) or Response(payload=accepted_payload())))
            fsync.assert_not_called()
            self.assertEqual(posts,[])

    def test_partial_then_failed_dispatch_write_does_not_hide_next_intent(self):
        real_write=os.write
        writes=[];posts=[]
        def fail_after_partial(fd,data):
            writes.append(len(data))
            if len(writes)==1: return real_write(fd,data[:len(data)//2])
            raise OSError('disk write interrupted')
        def post(*a,**k): posts.append(True); return Response(payload=accepted_payload())
        with patch('chanlun.preclose_notify.os.write',side_effect=fail_after_partial), patch('chanlun.preclose_notify.os.fsync') as fsync:
            with self.assertRaises(OSError): self.run_delivery(post)
        fsync.assert_not_called()
        self.assertEqual(posts,[])
        damaged_tail=self.outbox.path.read_bytes()
        self.assertTrue(damaged_tail)
        self.assertFalse(damaged_tail.endswith(b'\n'))
        def interrupted_post(*a,**k):
            posts.append(True)
            if len(posts)==1: raise PrecloseExecutionDeadline('delivery')
            return Response(payload=accepted_payload())
        with self.assertRaises(PrecloseExecutionDeadline): self.run_delivery(interrupted_post)
        self.assertTrue(self.outbox.path.read_bytes().startswith(damaged_tail+b'\n'))
        self.assertEqual(self.outbox._rows()[-1]['dispatch_state'],'dispatching')
        result=self.run_delivery(interrupted_post)
        self.assertEqual(posts,[True])
        self.assertFalse(result['notifications']['wxpusher']['success'])

    def test_partial_unicode_record_cannot_break_next_complete_jsonl_row(self):
        real_write=os.write
        writes=[]
        def fail_after_partial(fd,data):
            writes.append(bytes(data))
            if len(writes)==1:
                raw=bytes(data)
                cut=next((i+1 for i,value in enumerate(raw) if value>=128),len(raw)//2)
                return real_write(fd,raw[:cut])
            raise OSError('partial unicode record')
        with patch('chanlun.preclose_notify.os.write',side_effect=fail_after_partial):
            with self.assertRaises(OSError):
                self.outbox.record(content_hash='first',channel='fixture',success=False,response={'reason':'中文🙂'})
        self.assertTrue(writes[0].isascii(),'JSONL transport must stay decodable after any byte-prefix write')
        tail=self.outbox.path.read_bytes()
        self.outbox.record(content_hash='second',channel='fixture',success=True,response={'reason':'中文🙂'})
        self.assertTrue(self.outbox.path.read_bytes().startswith(tail+b'\n'))
        self.assertEqual(self.outbox._rows()[-1]['content_hash'],'second')
        self.assertEqual(self.outbox._rows()[-1]['response']['reason'],'中文🙂')
