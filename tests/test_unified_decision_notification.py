import copy
import unittest
import tempfile
from pathlib import Path
from chanlun.decision_workbench import build_decision_workbench
from chanlun.preclose_notify import format_reconciliation_message, _reconciliation_signature_hash
from chanlun.preclose_notify import format_preclose_message
from chanlun.preclose_notify import NotificationOutbox, send_reconciliation_notifications
from tests.test_unified_workbench_contract import inputs


class UnifiedDecisionNotification(unittest.TestCase):
    def test_failed_preclose_is_not_reported_as_normal_empty(self):
        self.assertNotEqual(format_preclose_message({'status': 'failed', 'pools': {}}),
                            format_preclose_message({'status': 'empty', 'pools': {}}))

    def test_legacy_success_suppresses_upgrade_but_not_later_condition_correction(self):
        class Response:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {'success': True, 'code': 1000}
        calls = []
        p = build_decision_workbench(*inputs())
        rec = {'trade_date': '2026-09-07', 'status': 'unchanged', 'formal_content_hash': 'f' * 64, 'pools': {}}
        with tempfile.TemporaryDirectory() as td:
            outbox = NotificationOutbox(Path(td) / 'outbox.jsonl')
            outbox.record(content_hash='f' * 64, channel='wxpusher', success=True, response={},
                          idempotency_key='2026-09-07:' + 'f' * 64)
            def send(projection):
                return send_reconciliation_notifications(rec, outbox=outbox, wxpusher_app_token='test',
                    wxpusher_uid='test', post=lambda *a, **kw: (calls.append(kw) or Response()), decision_projection=projection)
            self.assertEqual(send(p)['wxpusher']['status'], 'already_sent')
            changed = copy.deepcopy(p); changed['items'][0]['invalidation'] = ['跌破8元']
            send(changed)
            send(changed)
            self.assertEqual(len(calls), 1)
            self.assertIn('更正', calls[0]['json']['content'])

    def test_notification_uses_same_projection_reason_and_conditions(self):
        r, w, e = inputs()
        p = build_decision_workbench(r, w, e)
        message = format_reconciliation_message({'trade_date': r['date'], 'status': 'unchanged'}, decision_projection=p)
        self.assertIn(p['summary']['title'], message)
        self.assertIn('结构确认', message)
        self.assertEqual(message.count('600001'), 1)
        self.assertIn('下一确认', message)
        self.assertIn('/2026-09-07/', message)

    def test_semantic_dedupe_tracks_condition_changes_not_explanation_edits(self):
        p = build_decision_workbench(*inputs())
        rec = {'trade_date': '2026-09-07', 'status': 'unchanged', 'pools': {}}
        a = _reconciliation_signature_hash(rec, decision_projection=p)
        q = copy.deepcopy(p); q['items'][0]['primary_reason'] = '同一理由的文案润色'
        self.assertEqual(a, _reconciliation_signature_hash(rec, decision_projection=q))
        q['items'][0]['invalidation'] = ['跌破8元']
        self.assertNotEqual(a, _reconciliation_signature_hash(rec, decision_projection=q))

    def test_other_date_projection_is_not_used_in_notification(self):
        p = build_decision_workbench(*inputs())
        message = format_reconciliation_message({'trade_date': '2026-09-08', 'status': 'unchanged'}, decision_projection=p)
        self.assertNotIn('600001', message)

    def test_rank_only_changes_do_not_resend_same_business_facts(self):
        p = build_decision_workbench(*inputs())
        other = copy.deepcopy(p['items'][0]); other.update(code='600002', instrument_id='SH600002')
        p['items'].append(other)
        rec = {'trade_date': p['report_date'], 'status': 'unchanged', 'pools': {}}
        before = _reconciliation_signature_hash(rec, decision_projection=p)
        p['items'].reverse()
        self.assertEqual(before, _reconciliation_signature_hash(rec, decision_projection=p))

    def test_independent_strategy_price_correction_is_not_suppressed(self):
        r, w, e = inputs()
        w['views']['h4_t3'] = copy.deepcopy(w['views']['main'])
        e['views']['h4_t3'] = copy.deepcopy(e['views']['main'])
        p = build_decision_workbench(r, w, e)
        rec = {'trade_date': r['date'], 'status': 'unchanged', 'pools': {}}
        before = _reconciliation_signature_hash(rec, decision_projection=p)
        w['views']['h4_t3'][0]['formal_decision_contract']['reference_price'] = 11
        q = build_decision_workbench(r, w, e)
        self.assertNotEqual(before, _reconciliation_signature_hash(rec, decision_projection=q))
        message = format_reconciliation_message(rec, decision_projection=q)
        self.assertIn('H4', message)
        self.assertIn('11.00', message)

    def test_preclose_deduplicates_across_pools_and_caps_whole_message(self):
        rows = [{'code': '60000' + str(i), 'name': '候选' + str(i), 'reference_price': 10 + i} for i in range(1, 5)]
        message = format_preclose_message({'status': 'available', 'trade_date': '2026-09-07',
                                          'pools': {'main': rows, 'h4_t3': rows, 'acceleration': rows}})
        self.assertEqual(message.count('600001'), 1)
        self.assertNotIn('600004', message)
        self.assertIn('14:57', message)
        self.assertIn('完整执行条件', message)
