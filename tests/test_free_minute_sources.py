import json
import math
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from chanlun import data_fetcher as df
from chanlun.kline_repository import KLineRepository
from chanlun.market_history_store import MarketHistoryStore

NOW = datetime(2026, 9, 28, 10, 10, tzinfo=timezone(timedelta(hours=8)))


class Response:
    status_code = 200
    headers = {'Content-Type': 'text/html'}

    def __init__(self, payload):
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        pass

    def close(self):
        pass


def sina_row(volume='10000', amount='100100'):
    row = dict(day='2026-09-24 15:00:00', open='10', close='10.1', high='10.2', low='9.9', volume=volume)
    if amount is not None:
        row['amount'] = amount
    return row


def tc_payload(volume='100'):
    return {'code': 0, 'data': {'sh600792': {'m30': [['202609241500', '10', '10.1', '10.2', '9.9', volume, {}, '1.2']]}}}


class FreeMinuteTests(unittest.TestCase):
    def sina(self, rows, text=None):
        with patch.object(df.SESSION, 'get', return_value=Response(text if text is not None else rows)):
            return df._fetch_sina_minute_kline_remote('600792', 30, 1, capture_failure=True)

    def tencent(self, payload=None):
        self.assertTrue(hasattr(df, '_fetch_tencent_minute_kline_remote'), 'Tencent minute adapter is not connected')
        with patch.object(df.SESSION, 'get', return_value=Response(payload or tc_payload())):
            return df._fetch_tencent_minute_kline_remote('600792', 30, 1, capture_failure=True)

    def test_same_trade_tencent_hands_sina_shares_becomes_identical_hands(self):
        a, b = self.tencent(), self.sina([sina_row()])
        self.assertEqual(a['volumes'].tolist(), [100.0])
        self.assertEqual(a['volumes'].tolist(), b['volumes'].tolist())
        self.assertEqual(a['volume_raw_unit'], 'hands')
        self.assertEqual(b['volume_raw_unit'], 'shares')
        self.assertEqual(b['volume_unit'], 'hands')
        self.assertEqual(b['raw_volumes'].tolist(), [10000.0])

    def test_fractional_hands_and_cny_survive_jsonp(self):
        text = '/*<script>normal provider comment</script>*/\nvar _DATA=(' + json.dumps([sina_row('10001', '100100.25')]) + ');'
        result = self.sina([], text)
        self.assertEqual(result['volumes'].tolist(), [100.01])
        self.assertEqual(result['amounts'].tolist(), [100100.25])
        self.assertEqual(result['amount_unit'], 'CNY')
        self.assertEqual(result['amount_source'], 'sina')

    def test_missing_amount_not_zero_and_tencent_extra_field_not_amount(self):
        for p in [self.sina([sina_row(amount=None)]), self.tencent()]:
            self.assertTrue(math.isnan(float(p['amounts'][0])))
            self.assertFalse(bool(p['amount_available'][0]))
            self.assertEqual(p['amount_unit'], 'unknown')

    def test_zero_volume_is_real_zero(self):
        result = self.sina([sina_row('0', '0')])
        self.assertEqual(result['volumes'].tolist(), [0.0])
        self.assertEqual(result['amounts'].tolist(), [0.0])

    def test_invalid_numeric_rows_are_rejected_not_dropped(self):
        for field, value in [('volume', '-1'), ('volume', 'NaN'), ('volume', True), ('high', '9'), ('amount', '-1'), ('amount', 'inf')]:
            with self.subTest(field=field, value=value):
                row = sina_row(); row[field] = value
                with self.assertRaises(df._MinuteProviderFailure):
                    self.sina([row])

    def test_duplicate_and_bad_bucket_times_rejected(self):
        for rows in [[sina_row(), sina_row()], [dict(sina_row(), day='2026-09-24 12:30:00')]]:
            with self.assertRaises(df._MinuteProviderFailure):
                self.sina(rows)

    def test_html_and_executable_wrappers_rejected(self):
        for text in ['<html>error</html>', 'var _DATA=(alert(1));', 'var _DATA=([]);evil()']:
            with self.assertRaises(df._MinuteProviderFailure):
                self.sina([], text)

    def test_source_metadata_does_not_claim_qfq(self):
        p = self.tencent()
        self.assertEqual(p['adjustment'], 'unverified')
        self.assertEqual(p['source'], 'tencent')
        self.assertIn('fetched_at', p)

    def test_amount_volume_price_cross_check_catches_100x_unit_error(self):
        with self.assertRaises(df._MinuteProviderFailure):
            self.sina([sina_row('100', '100100')])

    def test_unverified_free_data_is_not_formal_or_intraday_confirmation(self):
        evidence = {'status': 'price_basis_unverified', 'stale': False, 'is_final': True,
                    'latest_date': '2026-09-24', 'latest_ts': '2026-09-24 15:00:00', 'bars': 80}
        self.assertFalse(df._verified_sublevel_input(evidence, '2026-09-24', 40))
        self.assertFalse(df._verified_sublevel_input(evidence, None, 40))

    def test_legacy_entry_uses_free_source_without_changing_units(self):
        with patch.object(df.SESSION, 'get', return_value=Response(tc_payload())):
            result = df._fetch_30min_kline_remote('600792', count=1)
        self.assertEqual(result['source'], 'tencent')
        self.assertEqual(result['volumes'].tolist(), [100])
        self.assertEqual(result['_data_status']['daily'], 'price_basis_unverified')

    def test_invalid_tencent_schema_does_not_read_quote_as_kline(self):
        for p in [{'code':0, 'data':{'sh600792':{'qt':{'sh600792':[]}}}},
                  {'code':1, 'data':tc_payload()['data']},
                  {'code':0, 'data':{'sz600792':{'m30':[]}}}]:
            with self.assertRaises(df._MinuteProviderFailure):
                self.tencent(p)

    def test_missing_volume_and_string_inf_rejected(self):
        for volume in [None, 'inf', '', '-']:
            with self.assertRaises(df._MinuteProviderFailure):
                self.sina([sina_row(volume)])

    def test_known_valid_qfq_cache_is_not_replaced_by_unverified_free_prices(self):
        p = self.sina([sina_row()])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bars.sqlite'
            with MarketHistoryStore(path) as store:
                iid = store.upsert_instrument('stock', 'SH', '600792')
                store.upsert_bars('30m', iid, [dict(ts='2026-09-24 15:00:00', open=20., high=21., low=19., close=20.5,
                    volume=100., amount=200000., volume_unit='hands', volume_raw_unit='hands', volume_source='eastmoney',
                    amount_unit='CNY', amount_source='eastmoney', amount_available=True,
                    adjustment='qfq', is_final=True, source_batch='existing')], adjustment='qfq')
            repo = KLineRepository(path, remote_fetchers={'30m': lambda code, count: p})
            result = repo.get('30m', '600792', 1, required_date='2026-09-24', as_of=NOW.isoformat(), force_refresh=True)
            self.assertEqual(result.status, 'verified')
            self.assertFalse(result.fetched_remote, 'Unverified remote prices were not adopted')
            self.assertEqual(result.kline['closes'].tolist(), [20.5])
            self.assertEqual(result.kline['adjustment'], 'qfq')
            with MarketHistoryStore(path, readonly=True) as store:
                row = store.connection.execute('SELECT close,source_batch FROM bars_30m').fetchone()
                self.assertEqual(tuple(row), (20.5, 'existing'))

    def test_main_entry_prefers_sina_and_clips_future_bar(self):
        self.assertTrue(hasattr(df, '_fetch_tencent_minute_kline_remote'))
        raw = [dict(sina_row(),day='2026-09-28 10:00:00'),
               dict(sina_row('20000','202000'),day='2026-09-28 10:30:00')]
        with patch.object(df.SESSION, 'get', return_value=Response(raw)) as request:
            p = df._fetch_minute_for_repository('600792', 30, 1, as_of=NOW.isoformat(), max_attempts=1)
        self.assertEqual(p['dates'], ['2026-09-28 10:00:00'])
        self.assertEqual(p['volumes'].tolist(), [100])
        self.assertEqual(p['source'], 'sina')
        self.assertIn('sina', request.call_args.args[0])

    def test_bj_skips_tencent_uses_sina(self):
        with patch.object(df.SESSION, 'get', return_value=Response([sina_row()])) as request:
            p = df._fetch_minute_for_repository('920000', 30, 1, required_date='2026-09-24', as_of=NOW.isoformat(), max_attempts=1)
        self.assertIn('json_v2.php', request.call_args.args[0])
        self.assertEqual(p['volumes'].tolist(), [100])

    def test_unverified_price_basis_never_written_as_qfq(self):
        p = self.sina([sina_row()])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bars.sqlite'
            repo = KLineRepository(path, remote_fetchers={'30m': lambda code, count: p})
            result = repo.get('30m', '600792', 1, required_date='2026-09-24', as_of=NOW.isoformat())
            self.assertEqual(result.status, 'price_basis_unverified')
            self.assertIsNotNone(result.kline)
            self.assertEqual(result.kline['volumes'].tolist(), [100])
            self.assertEqual(result.kline['adjustment'], 'unverified')
            with MarketHistoryStore(path, readonly=True) as store:
                self.assertEqual(store.connection.execute('SELECT count(*) FROM bars_30m').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
