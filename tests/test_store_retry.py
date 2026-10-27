import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from store import Store  # noqa: E402


class DiscoveryStatusRetryTest(unittest.TestCase):
    """Collectors retry put(); the shared status write must survive the same locks."""

    def make_store(self):
        directory = tempfile.mkdtemp()
        store = Store(Path(directory))
        with store.connect() as db:
            db.execute("INSERT INTO accounts VALUES('HN1:P','HN1','P','NAME','TAG','now')")
            db.execute("INSERT INTO discovered(account_key,match_key,status,attempts,updated_at)"
                       " VALUES('HN1:P','HN1_1','pending',0,'now')")
        return store

    def flaky(self, store, failures, message='database is locked'):
        state = {'calls': 0}
        real = store.connect

        def connect():
            state['calls'] += 1
            if state['calls'] <= failures:
                raise sqlite3.OperationalError(message)
            return real()
        store.connect = connect
        return state

    def test_lock_conflict_is_retried_until_it_succeeds(self):
        store = self.make_store()
        state = self.flaky(store, failures=2)
        with patch('store.time.sleep'):
            store.discovery_status('HN1:P', 'HN1_1', 'failed', 'upstream_unavailable')
        self.assertEqual(state['calls'], 3)
        with store.connect() as db:
            row = db.execute("SELECT status,attempts,last_error FROM discovered").fetchone()
        self.assertEqual(tuple(row), ('failed', 1, 'upstream_unavailable'))

    def test_busy_is_also_treated_as_contention(self):
        store = self.make_store()
        state = self.flaky(store, failures=1, message='database is busy')
        with patch('store.time.sleep'):
            store.discovery_status('HN1:P', 'HN1_1', 'failed', 'x')
        self.assertEqual(state['calls'], 2)

    def test_other_sqlite_errors_fail_immediately(self):
        store = self.make_store()
        state = self.flaky(store, failures=99, message='attempt to write a readonly database')
        with patch('store.time.sleep') as sleeper:
            with self.assertRaises(sqlite3.OperationalError):
                store.discovery_status('HN1:P', 'HN1_1', 'failed', 'x')
        self.assertEqual(state['calls'], 1)
        self.assertEqual(sleeper.call_count, 0)

    def test_persistent_lock_conflict_still_raises(self):
        store = self.make_store()
        state = self.flaky(store, failures=99)
        with patch('store.time.sleep'):
            with self.assertRaises(sqlite3.OperationalError):
                store.discovery_status('HN1:P', 'HN1_1', 'failed', 'x')
        self.assertEqual(state['calls'], 6)


if __name__ == '__main__':
    unittest.main()
