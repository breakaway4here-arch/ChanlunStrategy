"""Offline real quote orchestration regressions; only source I/O is synthetic."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from chanlun import quote_sources
from chanlun.preclose_contract import build_preclose_snapshot, build_public_preclose_view
from chanlun.preclose_runtime import MARKET_INDICES
from preclose_run import run_scheduled_preclose
from tests.test_preclose_runtime import _history
from tests.test_quote_sources import Response, Session, sina

CN = timezone(timedelta(hours=8))
START = datetime(2026, 8, 28, 14, 45, tzinfo=CN)


class AcquisitionClockTests(unittest.TestCase):
    def run_chain(self, seconds, *, start=START, stamp_offset=0, fallback=False, input_write_seconds=0):
        elapsed = [0.0]
        captured = {}
        network_calls = []
        def clock():
            return start + timedelta(seconds=elapsed[0])
        def primary(params):
            elapsed[0] += seconds
            stamp = clock() + timedelta(seconds=stamp_offset)
            return {'data': {'total': 1, 'diff': [{
                'f12': '600000', 'f14': '测试', 'f26': '20000101', 'f100': '测试行业',
                'f2': 10.2, 'f3': 2, 'f5': 100, 'f6': 102000, 'f15': 10.3,
                'f16': 9.9, 'f17': 10, 'f18': 10,
                'f124': (stamp - timedelta(days=1) if fallback else stamp).timestamp(),
            }]}}
        def response(_session, url, **kwargs):
            network_calls.append(url)
            if fallback:
                elapsed[0] += 61
                return Response(sina(date=clock().date().isoformat(), time=clock().strftime('%H:%M:%S')))
            return Response('')
        def minute(targets, date, as_of):
            captured['minute_as_of'] = as_of
            return {}
        def pipeline(inputs, config, **kwargs):
            captured['inputs'], captured['config'] = inputs, config
            return build_preclose_snapshot(config.trade_date, config.as_of, config.generated_at,
                                          {}, config.source_sha)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            original_write = Path.write_text
            def write_text(path, *args, **kwargs):
                result = original_write(path, *args, **kwargs)
                if path.name == '.input.json.tmp':
                    elapsed[0] += input_write_seconds
                return result
            stack.enter_context(patch.object(Path, 'write_text', autospec=True, side_effect=write_text))
            stack.enter_context(patch('chanlun.data_fetcher._fetch_eastmoney_json', side_effect=primary))
            stack.enter_context(patch('requests.sessions.Session.get', autospec=True, side_effect=response))
            stack.enter_context(patch('chanlun.preclose_runtime.load_readonly_preclose_universe',
                return_value=([_history('600000', '测试', 8.81)], {})))
            stack.enter_context(patch('chanlun.preclose_runtime.select_preclose_30m_targets', side_effect=lambda rows: rows))
            stack.enter_context(patch('chanlun.preclose_runtime.fetch_preclose_30m', side_effect=minute))
            stack.enter_context(patch('chanlun.preclose_runtime.fetch_preclose_indices',
                return_value={key: {} for key in MARKET_INDICES}))
            stack.enter_context(patch('chanlun.preclose_runtime.load_market_turnover_history', return_value=[]))
            result = run_scheduled_preclose(root=root/'preclose', formal_market_db=root/'market_history.sqlite',
                env_file=root/'unused-env', source_sha='clock-test', now=clock,
                monotonic=lambda: elapsed[0], trading_day_check=lambda *args: True,
                pipeline_runner=pipeline, skip_publish=True, notify=False)
            day_root = root/'preclose'/start.date().isoformat()
            captured['files'] = {path.name: json.loads(path.read_text())
                for path in day_root.glob('*.json')}
            captured['network_calls'] = network_calls
        return result, captured, clock()

    def test_real_primary_chain_30_61_and_205_seconds_uses_collection_time(self):
        for seconds in (30, 61, 205):
            with self.subTest(seconds=seconds):
                result, seen, finished = self.run_chain(seconds)
                self.assertEqual(result['exit_code'], 0)
                inputs, config = seen['inputs'], seen['config']
                expected = finished.isoformat(timespec='seconds')
                self.assertEqual(inputs['as_of'], expected)
                self.assertEqual(config.as_of, expected)
                self.assertEqual(seen['files']['snapshot.json']['as_of'], expected)
                self.assertEqual(seen['minute_as_of'], expected)
                self.assertEqual(inputs['daily'][0]['as_of'], expected)
                self.assertEqual(inputs['daily'][0]['stock_meta_asof']['risk_status'], 'verified')
                self.assertEqual(inputs['daily'][0]['stock_meta_asof']['risk_as_of'], expected)
                self.assertLessEqual(config.as_of, config.generated_at)
                self.assertEqual(seen['files']['timings.json']['started_at'], START.isoformat())
                self.assertEqual(inputs['runtime_diagnostics']['quote_snapshot']['valid_quotes'], 1)
                self.assertEqual(seen['network_calls'], [])

    def test_actual_fallback_validation_clock_advances_after_primary(self):
        result, seen, finished = self.run_chain(30, fallback=True)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(seen['inputs']['as_of'], finished.isoformat())
        self.assertEqual(seen['inputs']['runtime_diagnostics']['quote_snapshot']['quote_sources'], {'sina': 1})

    def test_no_input_or_snapshot_freeze_after_acquisition_crosses_cutoff(self):
        result, seen, _ = self.run_chain(61, start=START.replace(hour=14, minute=55))
        self.assertEqual(result['exit_code'], 1)
        self.assertNotIn('inputs', seen)
        self.assertNotIn('input.json', seen['files'])
        self.assertNotIn('snapshot.json', seen['files'])
        self.assertEqual(seen['network_calls'], [])

    def test_input_write_that_crosses_cutoff_never_promotes_temporary_file(self):
        result, seen, _ = self.run_chain(30, input_write_seconds=660)
        self.assertEqual(result['exit_code'], 1)
        self.assertNotIn('input.json', seen['files'])
        self.assertNotIn('.input.json.tmp', seen['files'])
        self.assertNotIn('snapshot.json', seen['files'])

    def test_wall_clock_rewind_after_quote_snapshot_fails_before_fact_publication(self):
        for rewind in (-30, -86400):
            with self.subTest(rewind=rewind):
                result, seen, _ = self.run_chain(61, input_write_seconds=rewind)
                self.assertEqual(result['exit_code'], 1)
                self.assertNotIn('inputs', seen)

    def test_future_quote_does_not_enter_snapshot_even_within_clock_skew_allowance(self):
        result, seen, _ = self.run_chain(30, stamp_offset=1)
        self.assertEqual(result['exit_code'], 1)
        self.assertNotIn('inputs', seen)

    def test_subsecond_quote_never_exceeds_seconds_precision_snapshot_as_of(self):
        result, seen, _ = self.run_chain(30.5)
        self.assertEqual(result['exit_code'], 1)
        self.assertNotIn('inputs', seen)

    def test_same_valid_quotes_preserve_prices_risks_and_actual_target_selection(self):
        from chanlun.preclose_runtime import select_preclose_30m_targets
        _, fast, _ = self.run_chain(0)
        _, slow, _ = self.run_chain(205)
        fast_daily, slow_daily = fast['inputs']['daily'], slow['inputs']['daily']
        self.assertEqual([row['code'] for row in select_preclose_30m_targets(fast_daily)],
                         [row['code'] for row in select_preclose_30m_targets(slow_daily)])
        for left, right in zip(fast_daily, slow_daily):
            left.pop('as_of')
            right.pop('as_of')
            left['stock_meta_asof'].pop('risk_as_of')
            right['stock_meta_asof'].pop('risk_as_of')
        self.assertEqual(fast_daily, slow_daily)
        self.assertEqual(fast['inputs']['market'], slow['inputs']['market'])

    def test_local_failure_contains_reason_and_quote_counts_only_public_type_survives(self):
        result, seen, _ = self.run_chain(61, stamp_offset=-181)
        self.assertEqual(result['exit_code'], 1)
        detail = seen['files']['acquisition-failure.json']
        self.assertEqual(detail['stage'], 'input_acquisition')
        self.assertEqual(detail['error_type'], 'PrecloseInputError')
        self.assertEqual(detail['reason'], 'no_eligible_intraday_daily_rows')
        self.assertEqual(detail['quote_snapshot']['valid_quotes'], 0)
        self.assertTrue(detail['frames'])
        public = build_public_preclose_view(seen['files']['snapshot.json'], now=START + timedelta(seconds=61))
        public_json = json.dumps(public)
        self.assertNotIn('frames', public_json)
        self.assertNotIn('quote_snapshot', public_json)
        self.assertNotIn('no_eligible_intraday_daily_rows', public_json)

    def test_fixed_historical_now_is_repeatable_despite_host_time(self):
        row = next(iter(quote_sources.parse_quotes(sina(date='2026-08-28', time='14:45:00'), 'sina', START).values()))
        def source(**kwargs):
            return [row], {'complete': True, 'requested': 1, 'unique': 1}
        outputs = []
        for host_day in (START + timedelta(days=1), START + timedelta(days=30)):
            with patch('chanlun.quote_sources.datetime', wraps=datetime) as host_datetime:
                host_datetime.now.return_value = host_day
                outputs.append(quote_sources.fetch_quotes(source, session=Session(), now=START))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0][1]['valid_quotes'], 1)
        self.assertEqual(outputs[0][1]['as_of'], START.isoformat())

    def test_dynamic_clock_rechecks_old_day_stale_future_and_final_fact_bound(self):
        for stamp in (START-timedelta(days=1), START-timedelta(seconds=181),
                      START+timedelta(seconds=61), START+timedelta(seconds=1)):
            with self.subTest(stamp=stamp):
                row = next(iter(quote_sources.parse_quotes(sina(date='2026-08-28', time='14:45:00'), 'sina', START).values()))
                row['quote_asof'] = stamp.isoformat()
                rows, diagnostic = quote_sources.fetch_quotes(
                    lambda **kwargs: ([row], {'complete': True, 'requested': 1, 'unique': 1}),
                    session=Session(), clock=lambda: START)
                self.assertEqual(diagnostic['valid_quotes'], 0)
                self.assertIsNone(rows[0]['current_price'])

    def test_early_quote_is_rechecked_after_slow_remaining_batch(self):
        elapsed = [0]
        first = next(iter(quote_sources.parse_quotes(sina(date='2026-08-28', time='14:45:00'), 'sina', START).values()))
        second = dict(first, code='600001', quote_asof='2026-08-27T14:45:00+08:00')
        class SlowSession(Session):
            def get(self, url, **kwargs):
                elapsed[0] += 181
                return Response('')
        rows, diagnostic = quote_sources.fetch_quotes(
            lambda **kwargs: ([first, second], {'complete': True, 'requested': 2, 'unique': 2}),
            session=SlowSession(), clock=lambda: START+timedelta(seconds=elapsed[0]),
            monotonic=lambda: elapsed[0])
        self.assertEqual(diagnostic['valid_quotes'], 0)
        self.assertEqual(diagnostic['as_of'], '2026-08-28T14:48:01+08:00')
        self.assertTrue(all(row['current_price'] is None for row in rows))

    def test_slow_primary_does_not_restart_180_second_fallback_budget(self):
        result, seen, _ = self.run_chain(205, fallback=True)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(seen['network_calls'], [])
        self.assertEqual(seen['files']['acquisition-failure.json']['quote_snapshot']['valid_quotes'], 0)

    def test_quote_cache_cannot_be_promoted_when_serialization_exhausts_caller_budget(self):
        elapsed = [0]
        row = next(iter(quote_sources.parse_quotes(sina(date='2026-08-28', time='14:45:00'), 'sina', START).values()))
        original_dump = json.dump
        def slow_dump(*args, **kwargs):
            result = original_dump(*args, **kwargs)
            elapsed[0] = 60
            return result
        with tempfile.TemporaryDirectory() as directory, patch('chanlun.quote_sources.json.dump', side_effect=slow_dump):
            with self.assertRaises(quote_sources.QuoteAcquisitionDeadline):
                quote_sources.fetch_quotes(
                    lambda **kwargs: ([row], {'complete': True, 'requested': 1, 'unique': 1}),
                    session=Session(), clock=lambda: START+timedelta(seconds=elapsed[0]),
                    budget_remaining=lambda: 60-elapsed[0], cache_dir=directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unexpected_error_local_evidence_does_not_copy_credentials_or_paths(self):
        from preclose_run import _local_acquisition_failure
        try:
            raise RuntimeError('token=private-key path=/Users/private/account.json https://user:pass@example.com')
        except RuntimeError as exc:
            detail = _local_acquisition_failure(exc)
        self.assertEqual(detail['reason'], 'unexpected_exception')
        self.assertEqual(detail['error_type'], 'RuntimeError')
        encoded = json.dumps(detail)
        for forbidden in ('private-key', '/Users/', 'user:pass', 'account.json'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(detail['frames'][-1]['function'], 'test_unexpected_error_local_evidence_does_not_copy_credentials_or_paths')

    def test_optional_failure_evidence_write_error_preserves_failed_snapshot(self):
        import preclose_run
        original_write = preclose_run._durable_json
        def fail_extra_only(path, payload):
            if Path(path).name == 'acquisition-failure.json':
                raise OSError('synthetic diagnostic failure')
            return original_write(path, payload)
        with patch('preclose_run._durable_json', side_effect=fail_extra_only):
            result, seen, _ = self.run_chain(61, stamp_offset=-181)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(seen['files']['snapshot.json']['status'], 'failed')
        self.assertEqual(result['acquisition_evidence_error'], 'OSError')


if __name__ == '__main__':
    unittest.main()
