import copy
import json
import io
from contextlib import redirect_stdout
import plistlib
import tempfile
import unittest
import subprocess
import sys
import signal
import time as elapsed_clock
from types import SimpleNamespace
from unittest import mock
from datetime import datetime, timedelta
from pathlib import Path

import intraday_observation_run as runner
from chanlun.intraday_observation_delivery import content_hash, SHANGHAI
from tests.test_intraday_observation_delivery import report_fixture


ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-10-13'
CUTOFF = DAY + 'T14:45:00+08:00'
NOW = datetime(2026, 10, 13, 14, 46, tzinfo=SHANGHAI)


def payload_fixture():
    return {'schema_version': 1, 'cutoff': CUTOFF, 'daily_data': {'stocks': []},
            'market_indices': {}, 'minute_data': {},
            'collection_health': {'status': 'available', 'coverage': 1.0,
                                  'expected': 100, 'acquired': 100, 'timed_out': 0}}


class ObservationRunnerTests(unittest.TestCase):
    def evaluate(self, payload, generated_at):
        report = report_fixture()
        report['intraday_observation']['input_hash'] = content_hash(payload)
        return report, payload

    def execute(self, directory, **overrides):
        kwargs = dict(batch_dir=Path(directory) / DAY, trade_date=DAY,
            formal_market_db=Path(directory) / 'formal.sqlite',
            deadline=NOW.replace(hour=14, minute=58), clock=lambda: NOW,
            acquire=lambda *a, **k: payload_fixture(), evaluate=self.evaluate)
        kwargs.update(overrides)
        return runner.compute_batch(**kwargs)

    def test_first_batch_freezes_inputs_and_result_replay_never_reacquires(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.execute(directory)
            def prohibited(*a, **k):
                raise AssertionError('must not reacquire or recompute frozen result')
            second = self.execute(directory, acquire=prohibited, evaluate=prohibited)
            self.assertEqual(first, second)
            batch = Path(directory) / DAY
            self.assertTrue((batch / 'input.json').is_file())
            self.assertTrue((batch / 'input-final.json').is_file())
            self.assertTrue((batch / 'snapshot.json').is_file())

    def test_reuses_frozen_inputs_after_interrupted_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = Path(directory) / DAY
            batch.mkdir()
            (batch / 'input.json').write_text(json.dumps(payload_fixture()))
            def prohibited(*a, **k):
                raise AssertionError('must use frozen input')
            result = self.execute(directory, acquire=prohibited)
            self.assertEqual(result['status'], 'empty')

    def test_collection_failure_missing_health_low_coverage_never_calls_pipeline(self):
        failures = [None, {'status': 'failed', 'coverage': 1, 'timed_out': 0},
                    {'status': 'partial', 'coverage': .89, 'timed_out': 0},
                    {'status': 'partial', 'coverage': .99, 'timed_out': 1},
                    {'status': 'available', 'coverage': True, 'timed_out': 0}]
        for health in failures:
            with self.subTest(health=health), tempfile.TemporaryDirectory() as directory:
                payload = payload_fixture()
                payload['collection_health'] = health
                calls = []
                result = self.execute(directory, acquire=lambda *a, **k: payload,
                                      evaluate=lambda *a, **k: calls.append(1))
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(calls, [])

    def test_real_pipeline_carries_collection_and_auxiliary_limits_into_notice(self):
        from tests.test_run_intraday_observation import payload
        from chanlun.intraday_observation_delivery import format_observation_messages
        value = payload()
        value['collection_health'] = {'status':'partial', 'coverage':.95,
            'expected':100, 'acquired':95, 'rejected':5, 'timed_out':0}
        value['optional_input_status'] = {'sector_flows':'unavailable'}
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            result = self.execute(directory, acquire=lambda *a, **k: value, evaluate=runner._evaluate)
        text = '\n'.join(format_observation_messages(result))
        self.assertEqual(result['status'], 'partial')
        self.assertIn('95/100', text)
        self.assertIn('板块资金', text)
        self.assertIn('市场情绪', text)
        self.assertEqual(result['input_hash'], content_hash(value))

    def test_data_cutoff_or_report_input_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = payload_fixture()
            payload['cutoff'] = DAY + 'T14:46:00+08:00'
            self.assertEqual(self.execute(directory, acquire=lambda *a, **k: payload)['status'], 'failed')
        with tempfile.TemporaryDirectory() as directory:
            def bad_evaluate(payload, generated_at):
                return report_fixture(), payload
            self.assertEqual(self.execute(directory, evaluate=bad_evaluate)['status'], 'failed')

    def test_exceptions_and_deadline_are_failed_not_empty_and_do_not_leak_details(self):
        with tempfile.TemporaryDirectory() as directory:
            def broken(*args, **kwargs):
                raise RuntimeError('secret=do-not-log')
            snapshot = self.execute(directory, acquire=broken)
            self.assertEqual(snapshot['status'], 'failed')
            stored = ''.join(path.read_text() for path in (Path(directory) / DAY).glob('*.json'))
            self.assertNotIn('do-not-log', stored)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.execute(directory, clock=lambda: NOW.replace(hour=15))['status'], 'failed')

    def test_schedule_guard_is_shanghai_dated_and_does_not_use_old_preclose_deadline(self):
        self.assertTrue(runner.should_start_scheduled(NOW, is_trading_day=lambda *a: True, market_db='unused'))
        self.assertTrue(runner.should_start_scheduled(NOW.replace(minute=57), is_trading_day=lambda *a: True, market_db='unused'))
        for stamp in (NOW.replace(minute=44), NOW.replace(minute=58)):
            self.assertFalse(runner.should_start_scheduled(stamp, is_trading_day=lambda *a: True, market_db='unused'))
        self.assertFalse(runner.should_start_scheduled(NOW, is_trading_day=lambda *a: False, market_db='unused'))

    def test_offline_late_historical_replay_has_bounded_budget_but_send_keeps_cutoff(self):
        late = NOW.replace(day=14, hour=16, minute=0)
        cutoff = datetime.fromisoformat(CUTOFF)
        offline = SimpleNamespace(scheduled=False, input='frozen.json', send=False)
        live_send = SimpleNamespace(scheduled=False, input='frozen.json', send=True)
        scheduled = SimpleNamespace(scheduled=True, input=None, send=True)
        self.assertEqual(runner.computation_deadline(offline, late, cutoff), late + timedelta(minutes=13))
        self.assertEqual(runner.computation_deadline(live_send, late, cutoff), cutoff.replace(minute=58))
        self.assertEqual(runner.computation_deadline(scheduled, late, cutoff), cutoff.replace(minute=58))
        with tempfile.TemporaryDirectory() as directory:
            result = self.execute(directory, clock=lambda: late,
                deadline=runner.computation_deadline(offline, late, cutoff))
            self.assertEqual(result['status'], 'empty')
            self.assertEqual(result['cutoff'], CUTOFF)

    def test_output_root_is_dedicated_and_cannot_redirect_to_formal_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            formal = base / 'market_history.sqlite'
            formal.write_bytes(b'protected')
            allowed = base / 'intraday-observation'
            self.assertEqual(runner.isolated_output_root(allowed, formal), allowed.resolve())
            for forbidden in (base, base / 'preclose', base / 'docs'):
                with self.subTest(path=forbidden), self.assertRaises(ValueError):
                    runner.isolated_output_root(forbidden, formal)
            allowed.symlink_to(base / 'preclose', target_is_directory=True)
            with self.assertRaises(ValueError):
                runner.isolated_output_root(allowed, formal)
            self.assertEqual(formal.read_bytes(), b'protected')

    def test_worker_timeout_kills_only_its_finite_child_and_freezes_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = Path(directory) / DAY
            batch.mkdir()
            args = SimpleNamespace(root=directory, formal_market_db=str(Path(directory) / 'formal.sqlite'), input=None)
            actual_popen = subprocess.Popen
            started = []
            def finite_child(_command, **kwargs):
                child = actual_popen([sys.executable, '-c', 'import time; time.sleep(5)'], **kwargs)
                started.append(child)
                return child
            with mock.patch.object(runner.subprocess, 'Popen', side_effect=finite_child), mock.patch.object(runner, '_now', return_value=NOW):
                result = runner._run_worker(args, batch, DAY, NOW + timedelta(seconds=.05))
            self.assertEqual(result['failure_code'], 'deadline_exceeded')
            self.assertIsNotNone(started[0].poll())
            self.assertTrue((batch / 'snapshot.json').is_file())

    def test_slow_delivery_has_wall_clock_limit_and_never_sends_next_part(self):
        from chanlun.intraday_observation_delivery import build_observation_snapshot
        report = report_fixture()
        report['picks_pure'] = [{'code':str(600000+i),'name':'候选样本{}'.format(i)} for i in range(180)]
        report['intraday_observation']['pool_status']['picks_pure']['status'] = 'available'
        snapshot = build_observation_snapshot(report)
        calls = []
        previous_handler = signal.getsignal(signal.SIGALRM)
        def stalled(*args, **kwargs):
            calls.append(1)
            elapsed_clock.sleep(.5)
            return {'success': True}
        with tempfile.TemporaryDirectory() as directory:
            started = elapsed_clock.monotonic()
            result = runner.deliver_before_deadline(snapshot,
                deadline=datetime.now(SHANGHAI)+timedelta(seconds=.05),
                outbox_path=Path(directory)/'outbox.json', app_token='a', uid='u', sender=stalled)
            elapsed = elapsed_clock.monotonic()-started
            self.assertLess(elapsed,.4)
            self.assertEqual(calls,[1])
            self.assertFalse(result['success'])
            self.assertEqual(json.loads((Path(directory)/'outbox.json').read_text())['parts']['0']['state'],'uncertain')
        self.assertIs(signal.getsignal(signal.SIGALRM), previous_handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))

    def test_saved_snapshot_from_other_date_cannot_be_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            self.execute(directory)
            batch = Path(directory) / DAY
            args = SimpleNamespace(root=directory, formal_market_db='unused', input=None)
            with self.assertRaises(ValueError):
                runner._run_worker(args, batch, '2026-10-14', NOW)

    def test_separate_scheduler_label_does_not_install_or_reference_existing_jobs(self):
        label = 'com.breakaway4here.chanlun-intraday-observation'
        with (ROOT / 'launchd' / (label + '.plist')).open('rb') as source:
            plist = plistlib.load(source)
        self.assertEqual(plist['Label'], label)
        self.assertFalse(plist['RunAtLoad'])
        self.assertEqual({(x['Weekday'], x['Hour'], x['Minute']) for x in plist['StartCalendarInterval']},
                         {(day, 14, 45) for day in range(1, 6)})
        script = (ROOT / 'scripts' / 'install_intraday_observation_launchd.sh').read_text()
        self.assertIn('already exists', script)
        self.assertNotIn('preclose-reconcile', script)
        self.assertNotIn('chanlun-daily', script)
        wrapper = (ROOT / 'scripts' / 'intraday_observation_run.sh').read_text()
        self.assertIn('--scheduled', wrapper)
        self.assertIn('--send', wrapper)
        self.assertNotIn('daily_run.sh', wrapper)
        self.assertNotIn('preclose_run.py', wrapper)


if __name__ == '__main__':
    unittest.main()
