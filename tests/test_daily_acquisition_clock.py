"""Offline daily main/quote/close integration; only provider I/O is synthetic."""
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import run
from chanlun import market_close_snapshot, quote_sources
from chanlun.market_history_store import MarketHistoryStore
from tests.test_quote_sources import Response, Session, sina

CN = timezone(timedelta(hours=8))
START = datetime(2026, 10, 15, 15, 20, 14, tzinfo=CN)
DAY = START.date().isoformat()
CODES = ('600000', '600001')


class Collected(Exception):
    pass


class DailyAcquisitionClockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'market_history.sqlite'
        with MarketHistoryStore(self.database) as store:
            for code in CODES:
                instrument = store.upsert_instrument('stock', 'SH', code, name='测试')
                store.upsert_bars('day', instrument, [{
                    'ts': '2026-10-14', 'open': 5, 'high': 5.2,
                    'low': 4.8, 'close': 5, 'volume': 100,
                    'amount': 50000, 'adjustment': 'qfq', 'is_final': True,
                }])

    def today_bars(self):
        with MarketHistoryStore(self.database, readonly=True) as store:
            return [dict(row) for row in store.connection.execute(
                'SELECT * FROM bars_day WHERE ts=? ORDER BY instrument_id', (DAY,)
            )]

    def quote_rows(self, stamp):
        text = ''.join(sina('sh' + code, date=stamp.date().isoformat(),
                            time=stamp.strftime('%H:%M:%S')) for code in CODES)
        return list(quote_sources.parse_quotes(text, 'sina', stamp).values())

    def run_main_chain(self, seconds, *, replay=False, poison_cache=False):
        elapsed = [0]
        calls, captured = [], {}
        cache = self.root / 'full_market_quotes'
        inventory = [{'asset_type': 'stock', 'exchange': 'SH', 'code': code,
                      'name': '测试'} for code in CODES]
        primary = lambda **kwargs: (inventory, {'complete': True, 'requested': 2, 'unique': 2})
        if poison_cache:
            quote_sources.fetch_quotes(primary, session=Session(), now=START, cache_dir=cache)
            self.assertEqual(json.loads((cache / ('quotes-' + DAY + '.json')).read_text())
                             ['diagnostics']['valid_quotes'], 0)

        def clock(*args, **kwargs):
            return START + timedelta(seconds=elapsed[0])

        def response(_session, url, **kwargs):
            calls.append(url)
            elapsed[0] += seconds
            stamp = clock()
            return Response(''.join(sina('sh' + code, date=DAY,
                time=stamp.strftime('%H:%M:%S')) for code in CODES))

        def collected(**kwargs):
            captured.update(kwargs)
            raise Collected()

        with ExitStack() as stack, redirect_stdout(io.StringIO()):
            host_time = stack.enter_context(patch.object(run, 'datetime', wraps=datetime))
            host_time.now.side_effect = clock
            stack.enter_context(patch.object(market_close_snapshot, 'datetime', wraps=datetime))
            market_close_snapshot.datetime.now.side_effect = clock
            stack.enter_context(patch.object(run, 'MARKET_HISTORY_DB_PATH', str(self.database)))
            stack.enter_context(patch.object(run, 'MARKET_HISTORY_CUTOVER_MODE', 'sqlite'))
            stack.enter_context(patch.object(run, 'resolve_personal_watchlist',
                return_value=({}, {'status': 'ok'})))
            stack.enter_context(patch.object(run, 'collect_daily_data', side_effect=collected))
            source = stack.enter_context(patch('chanlun.data_fetcher.fetch_all_a_stocks',
                side_effect=AssertionError('must reuse same-day inventory') if poison_cache else primary))
            stack.enter_context(patch('requests.sessions.Session.get', autospec=True, side_effect=response))
            ingest = stack.enter_context(patch.object(run, 'ingest_market_close_snapshot',
                wraps=market_close_snapshot.ingest_market_close_snapshot))
            error = None
            try:
                run.main(generated_at=START if replay else None)
            except Collected:
                pass
            except run.MarketDataUnavailable as exc:
                error = exc
            return error, captured, ingest, calls, source.call_count

    def test_live_main_keeps_post_start_quotes_and_scaled_final_bars(self):
        for seconds in (2, 75):
            with self.subTest(seconds=seconds):
                error, collected, ingest, calls, _ = self.run_main_chain(seconds)
                self.assertIsNone(error)
                self.assertEqual(collected['generated_at'], START + timedelta(seconds=seconds))
                self.assertEqual(collected['required_date'], DAY)
                self.assertEqual(len(calls), 1)
                bars = self.today_bars()
                self.assertEqual(len(bars), 2)
                self.assertTrue(all(row['is_final'] == 1 for row in bars))
                self.assertEqual([row['close'] for row in bars], [5.1, 5.1])
                self.assertEqual(ingest.call_args.kwargs['generated_at'], START)
                # The next case must exercise source acquisition again.
                with MarketHistoryStore(self.database) as store:
                    store.connection.execute('DELETE FROM bars_day WHERE ts=?', (DAY,))
                    store.connection.commit()
                for path in (self.root / 'full_market_quotes').glob('*'):
                    path.unlink()

    def test_replay_rejects_even_one_second_of_future_facts(self):
        rows = self.quote_rows(START + timedelta(seconds=1))
        result = market_close_snapshot.ingest_market_close_snapshot(
            self.database, DAY, lambda **kwargs: (rows,
                {'complete': True, 'requested': 2, 'unique': 2}), generated_at=START)
        self.assertEqual(result['status'], 'insufficient_coverage')
        self.assertEqual(self.today_bars(), [])

    def test_explicit_main_replay_freezes_quote_ceiling(self):
        error, collected, _, _, _ = self.run_main_chain(2, replay=True)
        self.assertIsNotNone(error)
        self.assertEqual(collected, {})
        self.assertEqual(self.today_bars(), [])

    def test_live_main_refills_same_day_poisoned_cache_without_refreshing_inventory(self):
        error, collected, _, calls, primary_calls = self.run_main_chain(75, poison_cache=True)
        self.assertIsNone(error)
        self.assertEqual(collected['required_date'], DAY)
        self.assertEqual(primary_calls, 0)
        self.assertEqual(calls, ['https://hq.sinajs.cn/list=sh600000,sh600001'])
        self.assertEqual(len(self.today_bars()), 2)

    def ingest_live(self, rows, *, finished=None, diagnostics=None):
        finished = finished or START + timedelta(seconds=75)
        observed = [START]
        def fetch(**kwargs):
            observed[0] = finished
            return rows, dict(complete=True, requested=2, unique=2, **(diagnostics or {}))
        with patch.object(market_close_snapshot, 'datetime', wraps=datetime) as host_time:
            host_time.now.side_effect = lambda *args, **kwargs: observed[0]
            return market_close_snapshot.ingest_market_close_snapshot(self.database, DAY, fetch)

    def test_natural_ingest_rechecks_at_collection_completion(self):
        result = self.ingest_live(self.quote_rows(START + timedelta(seconds=75)))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['written'], 2)
        self.assertEqual(result.get('acquired_at'), (START + timedelta(seconds=75)).isoformat())
        self.assertEqual(len(self.today_bars()), 2)

    def test_future_old_and_intraday_rows_never_write_partial_day(self):
        finished = START + timedelta(seconds=75)
        for stamp in (finished + timedelta(seconds=1), finished + timedelta(seconds=61),
                      START - timedelta(days=1), START.replace(hour=14, minute=59)):
            with self.subTest(stamp=stamp):
                rows = [self.quote_rows(finished)[0], self.quote_rows(stamp)[1]]
                result = self.ingest_live(rows, finished=finished)
                self.assertEqual(result['status'], 'insufficient_coverage')
                self.assertEqual(result['minimum_coverage'], 0.9)
                self.assertEqual(result['written'], 0)
                self.assertEqual(self.today_bars(), [])

    def test_future_cross_day_and_naive_fetch_diagnostics_are_rejected(self):
        finished = START + timedelta(seconds=75)
        for field in ('started_at', 'as_of', 'fetched_at'):
            for stamp in (finished + timedelta(seconds=1), START - timedelta(days=1),
                          START.replace(tzinfo=None)):
                with self.subTest(field=field, stamp=stamp):
                    result = self.ingest_live(self.quote_rows(START), finished=finished,
                                              diagnostics={field: stamp.isoformat()})
                    self.assertEqual(result['status'], 'incomplete')
                    self.assertEqual(result['reason'], 'invalid_fetch_time')
                    self.assertEqual(self.today_bars(), [])

    def test_collection_crossing_day_or_rewinding_never_writes(self):
        for finished in (START + timedelta(days=1), START - timedelta(seconds=1)):
            with self.subTest(finished=finished):
                result = self.ingest_live(self.quote_rows(START), finished=finished)
                self.assertEqual(result['status'], 'incomplete')
                self.assertEqual(result['reason'], 'invalid_collection_time')
                self.assertEqual(self.today_bars(), [])

    def test_same_day_cached_fetch_times_remain_valid(self):
        cached = START - timedelta(minutes=10)
        result = self.ingest_live(self.quote_rows(cached), diagnostics={
            'started_at': cached.isoformat(), 'as_of': cached.isoformat(),
            'fetched_at': cached.isoformat()})
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(self.today_bars()), 2)

    def test_replay_ingest_ignores_later_host_time_and_rejects_future_rows(self):
        with patch.object(market_close_snapshot, 'datetime', wraps=datetime) as host_time:
            host_time.now.return_value = START + timedelta(days=1)
            result = market_close_snapshot.ingest_market_close_snapshot(
                self.database, DAY, lambda **kwargs: (self.quote_rows(START + timedelta(seconds=75)),
                    {'complete': True, 'requested': 2, 'unique': 2}), generated_at=START)
        self.assertEqual(result['status'], 'insufficient_coverage')
        self.assertEqual(self.today_bars(), [])


if __name__ == '__main__':
    unittest.main()
