import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import SourceError, error_excerpt, normalize
from recover import run_recovery, validate_timeline
from store import Store
from test_mayhem import FakeSource, game


class RecoverySource(FakeSource):
    _token = 'SYNTHETIC-SECRET'
    def __init__(self):
        def local_open(request, **kwargs):
            raise urllib.error.HTTPError(request.full_url, 500, 'error', {},
                                        io.BytesIO(b'{"errorCode":"RPC_ERROR","message":"match history failed"}'))
        self._local = types.SimpleNamespace(base='https://127.0.0.1:1', authorization='SYNTHETIC-LOCAL',
                                           opener=types.SimpleNamespace(open=local_open))
    def list_ids(self, *args):
        raise AssertionError('Recovery must not replace its frozen gap list with a recent window')
    def get(self, route, retries=0, diagnostic=None):
        if diagnostic:
            diagnostic({'status': 200, 'elapsed_ms': 1, 'attempt': 1})
        if 'matchId/' in route:
            return game()
        return ['HN1_1000001']
    def refresh_token(self):
        pass


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.register(FakeSource())
    def tearDown(self):
        self.temp.cleanup()

    def test_recovery_uses_persisted_gaps_and_stores_full_raw(self):
        self.store.discover(FakeSource.account_key, ['HN1_1000001'])
        self.store.discovery_status(FakeSource.account_key, 'HN1_1000001', 'failed', 'HTTP 503')
        with patch('recover.time.sleep'):
            source = RecoverySource()
            with patch.object(source, 'get', wraps=source.get) as requests:
                result = run_recovery(self.temp.name, source_factory=lambda: source)
            self.assertTrue(all('infoType/details' not in c.args[0] and 'DETAILS' not in c.args[0]
                                for c in requests.call_args_list))
        self.assertEqual(result['recovered'], 1)
        self.assertEqual(self.store.counts(), {'complete': 1})
        with self.store.connect() as db:
            raw = json.loads(db.execute("SELECT payload FROM source_payloads WHERE kind='summary'").fetchone()[0])
            self.assertEqual(len(raw['participants']), 10)
            self.assertGreater(db.execute('SELECT count(*) FROM request_log').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM timelines').fetchone()[0], 0)

    def test_recovery_account_guard_does_not_change_active_account(self):
        source = RecoverySource()
        source.account_key = 'HN1:OTHER'
        result = run_recovery(self.temp.name, source_factory=lambda: source)
        self.assertEqual(result['last_error'], 'logged_in_account_differs_from_recovery_account')
        self.assertEqual(self.store.account()['account_key'], FakeSource.account_key)

    def test_timeline_identity_and_shape_validation(self):
        raw = {'gameId': 1000001, 'frames': [{'timestamp': 0, 'events': []}]}
        self.assertIs(validate_timeline(raw, 'HN1_1000001'), raw)
        for bad in ({'gameId': 9, 'frames': raw['frames']}, {'frames': []},
                    {'frames': [{'timestamp': 3}, {'timestamp': 2}]},
                    {'metadata': {'match_id': 'HN1_9'}, 'json': raw}):
            with self.subTest(bad=bad), self.assertRaises(SourceError):
                validate_timeline(bad, 'HN1_1000001')

    def test_timeline_events_upsert_and_transaction_rollback(self):
        self.store.put(FakeSource.account_key, normalize(game(), FakeSource.account['puuid']))
        timeline = {'frames': [{'timestamp': 0, 'events': [{'type': 'CHAMPION_KILL', 'timestamp': 12}]}]}
        for _ in range(2):
            self.store.put_timeline('HN1_1000001', 'test', validate_timeline(timeline, 'HN1_1000001'))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM timeline_events').fetchone()[0], 1)
        with self.assertRaises(AttributeError):
            self.store.put_timeline('HN1_1000001', 'bad', {'frames': [None]})
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM timeline_events').fetchone()[0], 1)

    def test_raw_preserves_extra_fields_but_scrubs_credentials(self):
        raw = game()
        raw['extra_unknown'] = {'unmapped': 7, 'Authorization': 'SYNTHETIC-SECRET'}
        for _ in range(2):
            self.store.save_payload('HN1_1000001', 'summary', 'test', raw)
        with self.store.connect() as db:
            rows = db.execute('SELECT payload FROM source_payloads').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn('SYNTHETIC-SECRET', rows[0][0])
        self.assertEqual(json.loads(rows[0][0])['extra_unknown']['unmapped'], 7)

    def test_timeline_batch_continues_after_three_failed_samples(self):
        for gid in range(1000001, 1000005):
            raw = game(gid)
            raw['gameCreation'] -= gid
            self.store.put(FakeSource.account_key, normalize(raw, FakeSource.account['puuid']))
        class PartialTimelineSource(RecoverySource):
            def get(self, route, retries=0, diagnostic=None):
                if '/infoType/details' in route and 'HN1_1000004' in route:
                    if diagnostic:
                        diagnostic({'status': 200, 'elapsed_ms': 1, 'attempt': 1})
                    return {'gameId': 1000004, 'frames': [{'timestamp': 0, 'events': []}]}
                if 'details' in route or 'DETAILS' in route:
                    if diagnostic:
                        diagnostic({'status': 503, 'elapsed_ms': 1, 'attempt': 1})
                    raise SourceError('upstream_unavailable', 503)
                return super().get(route, retries, diagnostic)
        with patch('recover.time.sleep'):
            state = run_recovery(self.temp.name, source_factory=PartialTimelineSource, timelines=True)
        self.assertEqual(state['timeline_total'], 1)
        self.assertEqual(state['timeline_route'], 'sgp_v3_details')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT match_key FROM timelines').fetchone()[0], 'HN1_1000004')

    def test_error_body_limits_and_redaction(self):
        body = json.dumps({'status': {'message': 'timeout SYNTHETIC-SECRET HN1_12345678'},
                           'accessToken': 'SYNTHETIC-SECRET'})
        text = error_excerpt(body, ['SYNTHETIC-SECRET'])
        self.assertNotIn('SYNTHETIC-SECRET', text)
        self.assertNotIn('12345678', text)
        self.assertIn('timeout', text)
        self.assertEqual(error_excerpt('<html>private</html>'), 'non_json_error_body')

    def test_timeline_retries_only_missing_records(self):
        for gid in (1000001, 1000002):
            self.store.put(FakeSource.account_key, normalize(game(gid), FakeSource.account['puuid']))
        calls = {}
        class RetryTimelineSource(RecoverySource):
            def get(self, route, retries=0, diagnostic=None):
                if '/infoType/details' in route:
                    gid = int(route.split('/matchId/HN1_')[1].split('/')[0])
                    calls[gid] = calls.get(gid, 0) + 1
                    if calls[gid] >= 3:
                        if diagnostic:
                            diagnostic({'status': 200, 'attempt': 1})
                        return {'gameId': gid, 'frames': [{'timestamp': 0, 'events': []}]}
                if 'details' in route or 'DETAILS' in route:
                    raise SourceError('upstream_unavailable', 503)
                return super().get(route, retries, diagnostic)
        with patch('recover.time.sleep'):
            state = run_recovery(self.temp.name, source_factory=RetryTimelineSource, timelines=True, timeline_rounds=5)
        self.assertEqual(state['timeline_total'], 2)
        self.assertEqual(state['timeline_remaining'], 0)
        self.assertEqual(calls, {1000001: 3, 1000002: 3})


if __name__ == '__main__':
    unittest.main()
