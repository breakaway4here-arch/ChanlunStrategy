import copy
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chanlun.nextday_research import adapt_report
from tests.test_nextday_research import _candidate, _limit_row, _report, _snapshot


class IdentityRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'market.sqlite'
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE instruments (asset_type TEXT, exchange TEXT, code TEXT, name TEXT)')
            conn.execute("INSERT INTO instruments VALUES ('stock','SH','600609','金杯汽车')")
        self.report = _report([_candidate(identity_key='')], _snapshot([_limit_row('600609', '金杯汽车')]))

    def run_report(self):
        return adapt_report(self.report, db_path=self.db)

    def test_empty_identity_is_recovered_without_mutating_input_or_database(self):
        original = copy.deepcopy(self.report)
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = self.run_report()
        self.assertEqual(result['l1']['status'], 'evaluated')
        self.assertEqual([x['instrument_id'] for x in result['l1']['selected']], ['SH600609'])
        self.assertEqual(result['l1']['selected'][0]['source_evidence'][0]['identity_recovery'],
                         {'source': 'market_history.instruments', 'identity_key': 'stock|SH|600609'})
        self.assertEqual(self.report, original)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), digest)

    def test_missing_or_ambiguous_registry_identity_remains_blocked(self):
        for sql in ("DELETE FROM instruments", "INSERT INTO instruments VALUES ('stock','SZ','600609','wrong')"):
            with self.subTest(sql=sql):
                with sqlite3.connect(self.db) as conn:
                    conn.execute('DELETE FROM instruments')
                    conn.execute("INSERT INTO instruments VALUES ('stock','SH','600609','金杯汽车')")
                    conn.execute(sql)
                self.assertEqual(self.run_report()['l1']['status'], 'not_evaluated')

    def test_nonempty_conflict_is_never_replaced(self):
        self.report['picks_pure'][0]['identity_key'] = 'stock|SZ|000001'
        self.assertEqual(self.run_report()['l1']['status'], 'not_evaluated')

    def test_other_identity_conflict_survives_recovery(self):
        self.report['picks_pure'][0]['stock_identity'] = 'stock|SZ|000001'
        self.assertEqual(self.run_report()['l1']['status'], 'not_evaluated')

    def test_unavailable_database_does_not_get_created(self):
        self.db = Path(self.tmp.name) / 'missing.sqlite'
        self.assertEqual(self.run_report()['l1']['status'], 'not_evaluated')
        self.assertFalse(self.db.exists())

    def test_valid_identity_needs_no_database(self):
        self.report['picks_pure'][0]['identity_key'] = 'stock|SH|600609'
        self.db = Path(self.tmp.name) / 'missing.sqlite'
        self.assertEqual(self.run_report()['l1']['status'], 'evaluated')

    def test_null_and_whitespace_are_missing_not_conflicting(self):
        for value in (None, '  '):
            with self.subTest(value=value):
                self.report['picks_pure'][0]['identity_key'] = value
                self.assertEqual(self.run_report()['l1']['status'], 'evaluated')
