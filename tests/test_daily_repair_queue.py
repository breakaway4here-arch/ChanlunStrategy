"""Synthetic persistent repair scheduling; all fixtures live in temporary storage."""
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chanlun.kline_repository import DailyRepairBudget, KLineRepository
from chanlun.market_history_store import MarketHistoryStore
from tests.test_daily_nonfinal_repair import DAY, dates, payload


class DailyRepairQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'market.sqlite'
        with MarketHistoryStore(self.path) as store:
            for index in range(12):
                code = str(600000 + index)
                iid = store.upsert_instrument('stock', 'SH', code)
                store.upsert_bars('day', iid, [dict(ts=ds, open=10, high=10.3,
                    low=9.9, close=10, volume=100000, amount=100000000,
                    amount_available=True, volume_unit='hands', volume_raw_unit='hands',
                    volume_source='eastmoney', amount_unit='CNY', amount_source='eastmoney',
                    is_final=j != 30, source_batch='synthetic')
                    for j, ds in enumerate(dates(120))], adjustment='qfq')
        self.repo = KLineRepository(self.path)
        self.calls = []
        self.net = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.net.start()
        self.addCleanup(self.net.stop)

    def unavailable(self, identity, count, *, request_budget):
        request_budget.take_request()
        self.calls.append(identity.code)
        return None

    def test_first_eight_fail_next_round_reaches_ninth_after_restart(self):
        first = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls, [str(600000+i) for i in range(8)])
        self.repo = KLineRepository(self.path)
        second = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls[8:], [str(600008+i) for i in range(4)])
        self.assertEqual(first['diagnostics']['pending_count'], 12)
        self.assertEqual(second['diagnostics']['pending_count'], 12)
        self.assertEqual(second['diagnostics']['cooldown_count'], 8)

    def test_invalid_identities_do_not_consume_stock_attempt_budget(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute("UPDATE instruments SET exchange='BJ' WHERE code<'600008'")
            store.connection.commit()
        result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls, [str(600008+i) for i in range(4)])
        self.assertEqual(result['diagnostics']['invalid_identity_count'], 8)

    def test_only_selected_targets_load_full_rows(self):
        original = MarketHistoryStore.query_bars_many
        loaded = []
        def track(store, interval, ids, **kwargs):
            loaded.extend(ids)
            return original(store, interval, ids, **kwargs)
        with patch.object(MarketHistoryStore, 'query_bars_many', track):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertLessEqual(len(set(loaded)), 8)
        self.assertTrue(result['diagnostics']['discovery_complete'])
        self.assertEqual(result['diagnostics']['nonfinal_stock_count'], 12)

    def test_reused_budget_does_not_reset_stock_limit(self):
        budget = DailyRepairBudget(max_stocks=2)
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)], budget=budget)
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)], budget=budget)
        self.assertEqual(len(self.calls), 2)

    def test_slow_discovery_no_request_and_complete_pending_preserved(self):
        now = [0.]
        original = MarketHistoryStore.discover_daily_nonfinal
        def slow(store, *args, **kwargs):
            result = original(store, *args, **kwargs)
            now[0] = 21.
            return result
        with patch.object(MarketHistoryStore, 'discover_daily_nonfinal', slow):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                budget=DailyRepairBudget(monotonic=lambda: now[0]))
        self.assertEqual(self.calls, [])
        self.assertEqual(result['diagnostics']['pending_count'], 12)
        self.assertTrue(all('repair_budget_exhausted' in row['reasons']
            for row in result['diagnostics']['pending']))
        self.assertGreaterEqual(result['diagnostics']['phase_seconds']['discovery'], 21)

    def test_health_tail_update_does_not_reset_cooldown(self):
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        with MarketHistoryStore(self.path) as store:
            store.connection.execute("UPDATE bars_day SET updated_at='changed-health' WHERE is_final=1")
            store.connection.commit()
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(len(self.calls), 12)

    def test_crash_intent_is_unknown_after_restart_and_not_resent(self):
        class Crash(BaseException):
            pass
        def crash(identity, count, *, request_budget):
            request_budget.take_request()
            self.calls.append(identity.code)
            raise Crash()
        with self.assertRaises(Crash):
            self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', crash)])
        result = KLineRepository(self.path).repair_daily_nonfinal(DAY,
            providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls.count('600000'), 1)
        pending = next(d for d in result['diagnostics']['pending'] if d['code']=='600000')
        self.assertIn('repair_attempt_unknown', pending['reasons'])

    def test_readonly_creates_no_queue_files(self):
        before = set(Path(self.tmp.name).iterdir())
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)], write=False)
        self.assertEqual(set(Path(self.tmp.name).iterdir()), before)

    def test_locked_queue_makes_no_requests(self):
        import fcntl
        lock_path = Path(str(self.path) + '.daily-repair.lock')
        with lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls, [])
        self.assertEqual(result['diagnostics']['pending_count'], 12)
        self.assertEqual(result['diagnostics']['queue_error'], 'repair_queue_locked')

    def test_corrupt_queue_stops_without_requests_or_erasing_pending(self):
        Path(str(self.path)+'.daily-repair.json').write_text('{broken')
        result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls, [])
        self.assertEqual(result['diagnostics']['pending_count'], 12)
        self.assertEqual(result['diagnostics']['queue_error'], 'repair_queue_state_invalid')


    def test_persist_failure_prevents_dispatch_and_preserves_pending(self):
        from chanlun.daily_repair_queue import DailyRepairQueue, RepairQueueError
        original = DailyRepairQueue.save
        calls = []
        def failing_intent(queue):
            calls.append(1)
            if len(calls) == 2:
                raise RepairQueueError('repair_queue_persist_failed')
            return original(queue)
        with patch.object(DailyRepairQueue, 'save', failing_intent):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls, [])
        self.assertEqual(result['diagnostics']['pending_count'], 12)
        self.assertEqual(result['diagnostics']['queue_error'], 'repair_queue_persist_failed')

    def test_bad_row_evidence_change_unblocks_cooldown(self):
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        with MarketHistoryStore(self.path) as store:
            store.connection.execute("UPDATE bars_day SET updated_at='explicit-new-bad-evidence' "
                "WHERE instrument_id=1 AND is_final=0")
            store.connection.commit()
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls.count('600000'), 2)
        self.assertEqual(self.calls.count('600001'), 1)

    def test_expired_cooldown_rotates_to_least_recent_failure(self):
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        with patch('chanlun.kline_repository.time.time', return_value=9999999999.):
            self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)])
        self.assertEqual(self.calls[12:20], [str(600000+i) for i in range(8)])

    def test_sql_progress_interrupt_exposes_unknown_denominator(self):
        import time
        original = MarketHistoryStore.list_instruments
        def slow(store, *args, **kwargs):
            store.connection.execute('WITH RECURSIVE many(x) AS (SELECT 1 UNION ALL '
                'SELECT x+1 FROM many WHERE x<10000000) SELECT sum(x) FROM many').fetchone()
            return original(store, *args, **kwargs)
        started = time.monotonic()
        with patch.object(MarketHistoryStore, 'list_instruments', slow):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                budget=DailyRepairBudget(seconds=.02))
        self.assertLess(time.monotonic()-started, .5)
        self.assertEqual(self.calls, [])
        self.assertFalse(result['diagnostics']['discovery_complete'])
        self.assertIsNone(result['diagnostics']['nonfinal_stock_count'])
        self.assertIsNone(result['diagnostics']['pending_count'])
        self.assertEqual(result['diagnostics']['discovery_reason'], 'daily_repair_deadline')
        json.dumps(result)

    def test_provider_conflict_and_cas_conflict_remain_distinct(self):
        def conflict(identity, count, *, request_budget):
            request_budget.take_request()
            value = payload(identity.code, dates(count))
            if identity.code == '600000':
                value['closes'][31] = 10.1
            elif identity.code == '600001':
                with MarketHistoryStore(self.path) as store:
                    store.connection.execute("UPDATE bars_day SET source_batch='concurrent' "
                        "WHERE instrument_id=2 AND is_final=1")
                    store.connection.commit()
            return value
        result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', conflict)])
        pending = {d['code']: d for d in result['diagnostics']['pending']}
        self.assertIn('repair_healthy_overlap_conflict', pending['600000']['reasons'][0])
        self.assertIn('repair_local_row_changed', pending['600001']['reasons'][0])
        self.assertEqual(result['diagnostics']['repaired_count'], 6)

    def test_two_provider_attempts_share_sixteen_request_limit(self):
        result = self.repo.repair_daily_nonfinal(DAY,
            providers=[('eastmoney', self.unavailable), ('tencent', self.unavailable)])
        self.assertEqual(result['diagnostics']['http_requests'], 16)
        self.assertEqual(result['diagnostics']['stock_attempts'], 8)
        self.assertEqual(len(self.calls), 16)

    def test_queue_reentry_is_nonblocking_and_does_not_dispatch(self):
        nested = []
        def reenter(identity, count, *, request_budget):
            request_budget.take_request()
            nested.append(KLineRepository(self.path).repair_daily_nonfinal(DAY,
                providers=[('eastmoney', self.unavailable)]))
            return None
        result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', reenter)],
            budget=DailyRepairBudget(max_stocks=1))
        self.assertEqual(self.calls, [])
        self.assertEqual(nested[0]['diagnostics']['queue_error'], 'repair_queue_locked')
        self.assertEqual(nested[0]['diagnostics']['pending_count'], 12)
        self.assertEqual(result['diagnostics']['http_requests'], 1)

    def test_writable_store_initialization_cannot_escape_shared_sql_deadline(self):
        import time
        original = MarketHistoryStore._initialize_schema
        def slow(store):
            store.connection.execute('WITH RECURSIVE many(x) AS (SELECT 1 UNION ALL '
                'SELECT x+1 FROM many WHERE x<10000000) SELECT sum(x) FROM many').fetchone()
            return original(store)
        def available(identity, count, *, request_budget):
            request_budget.take_request()
            return payload(identity.code, dates(count))
        started = time.monotonic()
        with patch.object(MarketHistoryStore, '_initialize_schema', slow):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', available)],
                budget=DailyRepairBudget(seconds=.04))
        self.assertLess(time.monotonic()-started, .5)
        self.assertEqual(result['diagnostics']['repaired_count'], 0)

    def test_bad_version_changed_between_discovery_and_full_read_is_not_dispatched(self):
        original = MarketHistoryStore.query_bars_many
        def changed(store, interval, ids, **kwargs):
            with MarketHistoryStore(self.path) as other:
                other.connection.execute("UPDATE bars_day SET updated_at='new-bad-version' "
                    "WHERE instrument_id=? AND is_final=0", (ids[0],))
                other.connection.commit()
            return original(store, interval, ids, **kwargs)
        with patch.object(MarketHistoryStore, 'query_bars_many', changed):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                budget=DailyRepairBudget(max_stocks=1))
        self.assertEqual(self.calls, [])
        self.assertIn('repair_discovery_changed', result['diagnostics']['pending'][0]['reasons'])

    def test_incomplete_discovery_keeps_existing_in_memory_pending(self):
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(max_requests=0))
        known = dict(self.repo._daily_repair_pending)
        self.assertEqual(len(known), 12)
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(seconds=0))
        self.assertEqual(self.repo._daily_repair_pending, known)


    def test_unknown_repair_denominator_does_not_replace_eligibility_coverage(self):
        from chanlun.decision_workbench import _coverage
        from tests.test_selection_coverage_summary import recorded_report
        report = recorded_report()
        result = self.repo.repair_daily_nonfinal(DAY, providers=[],
            budget=DailyRepairBudget(seconds=0))
        report['data_quality']['daily_nonfinal_repair'] = result['diagnostics']
        coverage = _coverage(report)
        self.assertEqual(coverage['eligibility']['excluded']['nonfinal_bars'], 4)
        self.assertEqual(coverage['eligibility']['eligible_count'], 60)
        self.assertIsNone(report['data_quality']['daily_nonfinal_repair']['pending_count'])
        json.dumps(coverage)

    def test_deadline_after_intent_before_dispatch_preserves_unknown_without_save(self):
        from chanlun.daily_repair_queue import DailyRepairQueue
        original = DailyRepairQueue.save
        now = [0.]
        saves = []
        def advance_after_intent(queue):
            original(queue)
            saves.append(1)
            if len(saves) == 2:
                now[0] = 21.
        with patch.object(DailyRepairQueue, 'save', advance_after_intent):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                budget=DailyRepairBudget(monotonic=lambda:now[0]))
        self.assertEqual(self.calls, [])
        state = json.loads(Path(str(self.path)+'.daily-repair.json').read_text())
        self.assertEqual(state['entries']['stock|SH|600000']['status'], 'inflight')
        self.assertEqual(len(saves), 2)
        self.assertEqual(result['diagnostics']['http_requests'], 0)


    def test_response_exactly_at_deadline_preserves_intent_without_finish_save(self):
        from chanlun.daily_repair_queue import DailyRepairQueue
        original = DailyRepairQueue.save
        now = [0.]
        saves = []
        def track(queue):
            saves.append(now[0])
            return original(queue)
        def expired(identity, count, *, request_budget):
            request_budget.take_request()
            self.calls.append(identity.code)
            now[0] = 20.
            return None
        with patch.object(DailyRepairQueue, 'save', track):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', expired)],
                budget=DailyRepairBudget(monotonic=lambda:now[0]))
        self.assertEqual(saves, [0., 0.])
        state = json.loads(Path(str(self.path)+'.daily-repair.json').read_text())
        self.assertEqual(state['entries']['stock|SH|600000']['status'], 'inflight')
        self.assertEqual(result['diagnostics']['http_requests'], 1)
        self.assertEqual(result['diagnostics']['repaired_count'], 0)

    def test_slow_finish_serialization_does_not_start_fsync_after_deadline(self):
        import os
        original_dump, original_fsync = json.dump, os.fsync
        now = [0.]
        dumps, syncs = [], []
        def slow_dump(*args, **kwargs):
            result = original_dump(*args, **kwargs)
            dumps.append(1)
            if len(dumps) == 3:
                now[0] = 20.
            return result
        def track_sync(fd):
            syncs.append(now[0])
            return original_fsync(fd)
        with patch('chanlun.daily_repair_queue.json.dump', slow_dump), \
             patch('chanlun.daily_repair_queue.os.fsync', track_sync):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                budget=DailyRepairBudget(monotonic=lambda:now[0]))
        self.assertEqual(syncs, [0., 0., 0., 0.])
        state = json.loads(Path(str(self.path)+'.daily-repair.json').read_text())
        self.assertEqual(state['entries']['stock|SH|600000']['status'], 'inflight')
        self.assertEqual(result['diagnostics']['http_requests'], 1)
        self.assertEqual(list(self.path.parent.glob('*.daily-repair.json.*')), [])

    def test_deadline_during_reconcile_closes_queue_without_fsync_or_dispatch(self):
        from chanlun.daily_repair_queue import DailyRepairQueue
        import os
        original_dump, original_exit = json.dump, DailyRepairQueue.__exit__
        now, exits = [0.], []
        def slow_dump(*args, **kwargs):
            result = original_dump(*args, **kwargs)
            now[0] = 20.
            return result
        def close(queue, *args):
            exits.append(True)
            return original_exit(queue, *args)
        with patch('chanlun.daily_repair_queue.json.dump', slow_dump), \
             patch('chanlun.daily_repair_queue.os.fsync') as sync, \
             patch.object(DailyRepairQueue, '__exit__', close):
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                budget=DailyRepairBudget(monotonic=lambda:now[0]))
        self.assertEqual(exits, [True])
        sync.assert_not_called()
        self.assertEqual(self.calls, [])
        self.assertEqual(result['diagnostics']['pending_count'], 12)

    def test_write_lock_acquire_uses_shared_remaining_deadline(self):
        import threading
        import time
        def available(identity, count, *, request_budget):
            request_budget.take_request()
            return payload(identity.code, dates(count))
        self.repo._write_lock.acquire()
        release = threading.Timer(.25, self.repo._write_lock.release)
        release.start()
        try:
            started = time.monotonic()
            result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', available)],
                budget=DailyRepairBudget(seconds=.04, max_stocks=1))
            elapsed = time.monotonic()-started
        finally:
            release.join(timeout=1)
        self.assertFalse(release.is_alive())
        self.assertLess(elapsed, .15)
        self.assertEqual(result['diagnostics']['repaired_count'], 0)

    def test_complete_final_window_resolves_old_pending_after_incomplete_discovery(self):
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(max_requests=0))
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=1 WHERE instrument_id=1 AND is_final=0')
            store.connection.commit()
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(seconds=0))
        self.assertEqual(self.repo.get('day', '600000', 120, required_date=DAY).status, 'verified')
        self.assertNotIn(self.repo._identity('600000'), self.repo._daily_repair_pending)

    def test_short_window_hiding_known_bad_day_keeps_pending_until_covered(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=1 WHERE instrument_id=1')
            store.connection.execute('UPDATE bars_day SET is_final=0 WHERE instrument_id=1 AND ts=?',
                (dates(120)[10],))
            store.connection.commit()
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(max_requests=0))
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=1 WHERE instrument_id=1 AND is_final=0')
            store.connection.commit()
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(seconds=0))
        self.assertEqual(self.repo.get('day', '600000', 100, required_date=DAY).status, 'repair_pending')
        self.assertEqual(self.repo.get('day', '600000', 120, required_date=DAY).status, 'verified')
        # Confirming the full old bad-day set also invalidates the shorter old result.
        self.assertEqual(self.repo.get('day', '600000', 100, required_date=DAY).status, 'verified')

    def test_final_flag_with_invalid_ohlc_does_not_clear_old_pending(self):
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(max_requests=0))
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=1,close=100 '
                'WHERE instrument_id=1 AND is_final=0')
            store.connection.commit()
        self.repo.repair_daily_nonfinal(DAY, providers=[], budget=DailyRepairBudget(seconds=0))
        self.assertEqual(self.repo.get('day', '600000', 120, required_date=DAY).status, 'repair_pending')

    def test_actual_bad_content_changes_release_unknown_without_timestamp_change(self):
        class Crash(BaseException):
            pass
        def crash(identity, count, *, request_budget):
            request_budget.take_request()
            self.calls.append(identity.code)
            raise Crash()
        with self.assertRaises(Crash):
            self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', crash)],
                budget=DailyRepairBudget(max_stocks=1))
        changes = [('close',10.1), ('volume',200000), ('amount',200000000),
                   ('volume_unit','unknown'), ('source_batch','new-evidence')]
        with MarketHistoryStore(self.path, readonly=True) as store:
            stamp = store.connection.execute('SELECT updated_at FROM bars_day WHERE instrument_id=1 '
                'AND is_final=0').fetchone()[0]
        for index, (field, value) in enumerate(changes, start=2):
            with self.subTest(field=field):
                with MarketHistoryStore(self.path) as store:
                    store.connection.execute('UPDATE bars_day SET '+field+'=? '
                        'WHERE instrument_id=1 AND is_final=0', (value,))
                    store.connection.commit()
                    self.assertEqual(store.connection.execute('SELECT updated_at FROM bars_day '
                        'WHERE instrument_id=1 AND is_final=0').fetchone()[0], stamp)
                self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', self.unavailable)],
                    budget=DailyRepairBudget(max_stocks=1))
                self.assertEqual(self.calls.count('600000'), index)

    def test_nonfinite_bad_content_can_be_fingerprinted_and_repaired(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET close=? WHERE instrument_id=1 AND is_final=0',
                (float('inf'),))
            store.connection.commit()
        def available(identity, count, *, request_budget):
            request_budget.take_request()
            return payload(identity.code, dates(count))
        result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', available)],
            budget=DailyRepairBudget(max_stocks=1))
        self.assertEqual(result['diagnostics']['repaired_count'], 1)
        self.assertEqual(self.repo.get('day', '600000', 120, required_date=DAY).status, 'verified')

    def test_nonfinite_source_is_still_rejected_after_bad_row_fingerprint(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET close=? WHERE instrument_id=1 AND is_final=0',
                (float('inf'),))
            store.connection.commit()
        def invalid(identity, count, *, request_budget):
            request_budget.take_request()
            value = payload(identity.code, dates(count))
            value['closes'][30] = float('inf')
            return value
        result = self.repo.repair_daily_nonfinal(DAY, providers=[('eastmoney', invalid)],
            budget=DailyRepairBudget(max_stocks=1))
        self.assertEqual(result['diagnostics']['repaired_count'], 0)
        # The old K-line stays readable, with unusable proof explicitly pending.
        bad = self.repo.get('day', '600000', 120, required_date=DAY)
        self.assertNotIn('canonical_daily', bad.kline)
        self.assertEqual(bad.diagnostics['canonical_daily_reference']['status'], 'pending')
        from chanlun.price_basis import canonical_daily_reference
        with MarketHistoryStore(self.path, readonly=True) as store:
            invalid_rows = store.query_bars('day', 1, as_of=DAY, limit=120)
        # The strict proof helper itself still rejects this invalid input.
        with self.assertRaises(ValueError):
            canonical_daily_reference('600000', invalid_rows)
        with MarketHistoryStore(self.path, readonly=True) as store:
            self.assertEqual(store.connection.execute('SELECT is_final FROM bars_day '
                'WHERE instrument_id=1 AND ts=?', (dates(120)[30],)).fetchone()[0], 0)

    def test_daily_reference_failure_isolated_from_healthy_same_batch(self):
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=1')
            store.connection.execute('UPDATE bars_day SET high=? WHERE instrument_id=1 AND ts=?',
                (float('inf'), dates(120)[30]))
            store.connection.commit()
        results = self.repo.get_many('day', ['600000','600001'], 120, required_date=DAY)
        self.assertEqual(set(results), {'600000','600001'})
        healthy, bad = results['600001'], results['600000']
        self.assertEqual(healthy.status, 'verified')
        self.assertEqual(healthy.kline['canonical_daily']['identity_key'], 'stock|SH|600001')
        self.assertEqual(len(bad.kline['dates']), 120)
        self.assertNotIn('canonical_daily', bad.kline)
        self.assertEqual(bad.diagnostics['canonical_daily_reference'],
            {'status':'pending', 'reason':'invalid_daily_reference'})

    def test_minute_daily_reference_failure_isolated_for_both_intervals(self):
        from chanlun.price_basis import align_intraday_price
        from tests.test_candidate_upgrade import make_stock, make_min30_result
        with MarketHistoryStore(self.path) as store:
            store.connection.execute('UPDATE bars_day SET is_final=1')
            store.connection.execute('UPDATE bars_day SET high=? WHERE instrument_id=1 AND ts=?',
                (float('inf'), DAY))
            store.connection.commit()
            for interval in ('30m','15m'):
                for iid in (1,2):
                    store.upsert_bars(interval, iid, [dict(ts=DAY+' 15:00:00',open=10,
                        high=10.3,low=9.9,close=10,volume=100000,amount=100000000,
                        amount_available=True,volume_unit='hands',volume_raw_unit='hands',
                        volume_source='eastmoney',amount_unit='CNY',amount_source='eastmoney',
                        is_final=True,source_batch='synthetic')], adjustment='qfq')
        for interval in ('30m','15m'):
            with self.subTest(interval=interval):
                results = self.repo.get_many(interval, ['600000','600001'], 1,
                    required_date=DAY, as_of=DAY+'T15:05:00+08:00')
                self.assertEqual(set(results), {'600000','600001'})
                self.assertEqual(results['600001'].status, 'verified')
                self.assertNotEqual(results['600001'].kline['minute_to_daily']['reason'],
                    'invalid_daily_reference')
                proof = results['600000'].kline['minute_to_daily']
                self.assertEqual(proof['status'], 'pending')
                self.assertEqual(proof['reason'], 'invalid_daily_reference')
                self.assertEqual(results['600000'].diagnostics['minute_to_daily'], proof)
                stock, minute = make_stock('000001',[]), make_min30_result('000001')
                minute.strategy_input_evidence['minute_to_daily'] = proof
                self.assertIsNone(align_intraday_price(10., stock, minute))
