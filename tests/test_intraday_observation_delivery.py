import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from chanlun import intraday_observation_delivery as delivery


CUTOFF = "2026-10-13T14:45:00+08:00"
INPUT_HASH = "a" * 64


def report_fixture():
    keys = [key for key, _label, _path in delivery.POOL_SPECS]
    return {
        "date": "2026-10-13", "is_official": False, "bar_state": "intraday",
        "intraday_observation": {
            "schema_version": 1, "enabled": True, "mode": "intraday_1445",
            "cutoff": CUTOFF, "input_hash": INPUT_HASH,
            "formal_actions_allowed": False,
            "collection_health": {"status": "available", "coverage": 1.0,
                "expected": 100, "acquired": 100, "rejected": 0, "timed_out": 0},
            "pool_status": {key: {"status": "empty"} for key in keys},
        },
        "picks_pure": [], "picks_fusion": [], "startup_watchlist": [],
        "observation_watchlist": [], "next_day_boom": {"candidates": []},
        "luojie_pool": {"candidates": []}, "h4_t3_pool": {"candidates": []},
        "right_side_startup": {"candidates": [], "watchlist": []},
        "holding_risks": [{"name": "private holding", "cost": 99}],
    }


class ObservationDeliveryTests(unittest.TestCase):
    def snapshot(self, report=None):
        return delivery.build_observation_snapshot(report or report_fixture())

    def test_all_pools_source_order_and_observation_identity(self):
        report = report_fixture()
        report["picks_pure"] = [{"code": "600002", "name": "第二只", "price": 12},
                                {"code": "600001", "name": "第一只", "price": 11}]
        report["intraday_observation"]["pool_status"]["picks_pure"] = {"status": "available"}
        snapshot = self.snapshot(report)
        text = "\n".join(delivery.format_observation_messages(snapshot))
        self.assertEqual([row['code'] for row in snapshot['pools']['picks_pure']['rows']],
                         ['600002', '600001'])
        self.assertIn('候选2只', text)
        self.assertIn('依据不足', text)
        self.assertEqual(set(snapshot["pools"]), {key for key, _, _ in delivery.POOL_SPECS})
        self.assertIn("14:45", text)
        self.assertIn("观察", text)
        self.assertIn("2026-10-13", text)
        self.assertNotIn("private holding", text)
        self.assertNotIn("截点价", text)
        self.assertNotIn("price", json.dumps(snapshot))
        self.assertFalse(snapshot["formal_actions_allowed"])

    def test_refuses_formal_wrong_cutoff_wrong_hash_or_missing_contract(self):
        for path, value in [(('is_official',), True), (('bar_state',), 'closed'),
                            (('date',), '2026-10-12'),
                            (('intraday_observation', 'cutoff'), '2026-10-13T14:46:00+08:00'),
                            (('intraday_observation', 'input_hash'), 'bad'),
                            (('intraday_observation', 'formal_actions_allowed'), True)]:
            report = report_fixture()
            target = report
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.snapshot(report)
        report = report_fixture()
        del report['intraday_observation']
        with self.assertRaises(ValueError):
            self.snapshot(report)

    def test_missing_pool_or_health_is_unavailable_not_empty(self):
        for missing in ('pool', 'status'):
            report = report_fixture()
            if missing == 'pool':
                del report['picks_pure']
            else:
                del report['intraday_observation']['pool_status']['picks_pure']
            snapshot = self.snapshot(report)
            self.assertEqual(snapshot['pools']['picks_pure']['status'], 'unavailable')
            self.assertEqual(snapshot['status'], 'partial')
            self.assertIn('暂不可用', '\n'.join(delivery.format_observation_messages(snapshot)))

    def test_explicit_failed_health_suppresses_untrusted_rows(self):
        report = report_fixture()
        report['picks_pure'] = [{'code': '600001', 'name': '不可信票'}]
        report['intraday_observation']['pool_status']['picks_pure'] = {'status': 'unavailable'}
        snapshot = self.snapshot(report)
        self.assertEqual(snapshot['pools']['picks_pure']['rows'], [])
        self.assertNotIn('不可信票', '\n'.join(delivery.format_observation_messages(snapshot)))

    def test_empty_health_with_rows_is_rejected_as_conflicting_data(self):
        report = report_fixture()
        report['picks_pure'] = [{'code': '600001', 'name': '不一致'}]
        self.assertEqual(self.snapshot(report)['pools']['picks_pure']['status'], 'unavailable')

    def test_partial_pool_exposes_coverage_without_claiming_no_candidates(self):
        report = report_fixture()
        report['intraday_observation']['pool_status']['picks_pure'] = {
            'status': 'partial', 'verified_count': 8, 'requested_count': 10,
        }
        snapshot = self.snapshot(report)
        text = '\n'.join(delivery.format_observation_messages(snapshot))
        self.assertIn('覆盖不完整', text)
        self.assertIn('8/10', text)
        self.assertEqual(snapshot['status'], 'partial')

    def test_partial_collection_and_auxiliary_limits_are_visible_for_empty_pools(self):
        report = report_fixture()
        report['intraday_observation']['collection_health'].update(
            status='partial', coverage=.95, acquired=95, rejected=5)
        report['intraday_observation']['missing_auxiliary_inputs'] = ['sector_flows', 'market_sentiment', 'events']
        snapshot = self.snapshot(report)
        text = '\n'.join(delivery.format_observation_messages(snapshot))
        self.assertEqual(snapshot['status'], 'partial')
        self.assertIn('95/100', text)
        self.assertIn('板块资金', text)
        self.assertIn('市场情绪', text)
        self.assertNotIn('events', text)
        self.assertNotIn('LLM', text)

    def test_missing_or_inconsistent_collection_contract_is_rejected(self):
        for health in ({}, {'status':'available','coverage':.95,'expected':100,'acquired':80,'timed_out':0},
                       {'status':'failed','coverage':1.0,'expected':100,'acquired':100,'timed_out':0}):
            report = report_fixture()
            report['intraday_observation']['collection_health'] = health
            with self.subTest(health=health), self.assertRaises(ValueError):
                self.snapshot(report)

    def test_foundation_exclusion_is_visible_without_warning_on_business_exclusion(self):
        report = report_fixture()
        report['intraday_observation']['collection_health'].update(status='partial',
            expected=9, acquired=9, coverage=1., foundation_missing=1,
            foundation_coverage=.9, instrument_count=15, business_excluded=5)
        snapshot = self.snapshot(report)
        text = '\n'.join(delivery.format_observation_messages(snapshot))
        self.assertEqual(snapshot['status'],'partial')
        self.assertIn('另有1只基础数据不足未参与',text)
        self.assertIn('9/9',text)
        self.assertNotIn('5只',text)

    def test_invalid_row_cannot_silently_become_empty(self):
        report = report_fixture()
        report['picks_pure'] = [{'code': 'wrong', 'name': '坏数据'}]
        report['intraday_observation']['pool_status']['picks_pure'] = {'status': 'available'}
        self.assertEqual(self.snapshot(report)['pools']['picks_pure']['status'], 'unavailable')

    def test_single_unknown_digest_preserves_every_member_in_private_snapshot(self):
        report = report_fixture()
        report['picks_pure'] = [{'code': str(600000 + i), 'name': '观察样本{}'.format(i)} for i in range(100)]
        report['intraday_observation']['pool_status']['picks_pure'] = {'status': 'available'}
        snapshot = self.snapshot(report)
        messages = delivery.format_observation_messages(snapshot, max_chars=500)
        self.assertEqual(len(messages), 1)
        self.assertTrue(all(len(message) <= 500 for message in messages))
        self.assertIn('候选100只', messages[0])
        self.assertIn('依据不足', messages[0])
        for i in range(100):
            self.assertEqual(snapshot['pools']['picks_pure']['rows'][i]['code'], str(600000 + i))
            self.assertNotIn(str(600000 + i), messages[0])
        self.assertTrue(all('14:45' in message and '观察' in message for message in messages))

    def test_failed_run_message_never_looks_like_empty_pool(self):
        snapshot = delivery.build_failure_snapshot('2026-10-13', cutoff=CUTOFF,
            failure_code='input_unavailable', input_hash=INPUT_HASH)
        text = '\n'.join(delivery.format_observation_messages(snapshot))
        self.assertIn('失败', text)
        self.assertNotIn('未选出', text)
        self.assertEqual(snapshot['pools'], {})

    def test_freeze_is_idempotent_and_refuses_same_day_changed_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '2026-10-13' / 'snapshot.json'
            snapshot = self.snapshot()
            delivery.freeze_observation_snapshot(path, snapshot)
            delivery.freeze_observation_snapshot(path, copy.deepcopy(snapshot))
            before = path.read_bytes()
            changed = report_fixture()
            changed['intraday_observation']['input_hash'] = 'b' * 64
            with self.assertRaises(FileExistsError):
                delivery.freeze_observation_snapshot(path, self.snapshot(changed))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_successful_delivery_deduplicates_and_records_only_safe_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def sender(message, **kwargs):
                calls.append((message, kwargs))
                return {'success': True, 'provider': 'wxpusher', 'http_status': 200,
                        'message_ids': [42], 'secret': 'must-not-persist'}
            kwargs = dict(outbox_path=Path(directory) / 'outbox.json', app_token='secret-token', uid='secret-uid', sender=sender)
            first = delivery.deliver_observation(self.snapshot(), **kwargs)
            second = delivery.deliver_observation(self.snapshot(), **kwargs)
            self.assertEqual(first['status'], 'sent')
            self.assertEqual(second['status'], 'already_sent')
            self.assertEqual(len(calls), 1)
            stored = kwargs['outbox_path'].read_text()
            self.assertNotIn('secret', stored)
            self.assertIn('42', stored)

    def test_failed_or_interrupted_send_never_automatically_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def sender(*args, **kwargs):
                calls.append(1)
                raise RuntimeError('request outcome unknown')
            kwargs = dict(outbox_path=Path(directory) / 'outbox.json', app_token='a', uid='u', sender=sender)
            first = delivery.deliver_observation(self.snapshot(), **kwargs)
            second = delivery.deliver_observation(self.snapshot(), **kwargs)
            self.assertEqual(first['status'], 'delivery_uncertain')
            self.assertEqual(second['status'], 'delivery_uncertain')
            self.assertEqual(len(calls), 1)

    def test_outbox_refuses_changed_batch_and_invalid_snapshot_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            kwargs = dict(outbox_path=Path(directory) / 'outbox.json', app_token='a', uid='u', sender=lambda *a, **k: {'success': True})
            snapshot = self.snapshot()
            delivery.deliver_observation(snapshot, **kwargs)
            snapshot['content_hash'] = 'b' * 64
            with self.assertRaises(ValueError):
                delivery.deliver_observation(snapshot, **kwargs)
            report = report_fixture()
            report['intraday_observation']['input_hash'] = 'b' * 64
            with self.assertRaises(ValueError):
                delivery.deliver_observation(self.snapshot(report), **kwargs)

    def test_outbox_preserves_provider_acceptance_without_claiming_user_receipt(self):
        evidence = {"success": True, "provider": "wxpusher", "http_status": 200,
            "business_code": 1000, "target_business_code": 1000,
            "provider_accepted": True, "delivery_status": "provider_accepted",
            "message_ids": [42], "message_content_ids": [43], "send_record_ids": [44]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outbox.json"
            result = delivery.deliver_observation(self.snapshot(), outbox_path=path,
                app_token="private-token", uid="private-uid", sender=lambda *a, **k: dict(evidence))
            saved = json.loads(path.read_text())
            self.assertEqual(result["status"], "sent")
            self.assertEqual(saved["parts"]["0"]["response"], evidence)
            self.assertNotIn("private-", path.read_text())
            self.assertNotIn("user_received", saved["parts"]["0"]["response"])


if __name__ == '__main__':
    unittest.main()
