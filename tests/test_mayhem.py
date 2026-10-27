import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import TencentSource, SourceError, NotStandardMayhem, normalize, approved_origin
from store import Store, metrics
from sync import run_sync
from main import LocalServer


def game(gid=1000001, win=True):
    members = []
    for pid in range(1, 11):
        p = {'participantId': pid, 'puuid': 'SYNTHETIC-PUUID-' + str(pid), 'teamId': 100 if pid <= 5 else 200,
             'championId': pid, 'championName': 'Hero' + str(pid), 'riotIdGameName': 'SYNTHETIC-NAME-' + str(pid),
             'riotIdTagline': 'TAG', 'kills': pid, 'deaths': 1, 'assists': 2,
             'win': win if pid <= 5 else not win, 'totalDamageDealtToChampions': 1000,
             'totalDamageTaken': 2000, 'goldEarned': 12000}
        p.update({f'playerAugment{i}': 1000 + i if i < 5 else 0 for i in range(1, 7)})
        members.append(p)
    return {'platformId': 'HN1', 'gameId': gid, 'queueId': 2400, 'gameMode': 'KIWI', 'gameVersion': '16.20.1',
            'gameCreation': 1792500000000, 'gameDuration': 600, 'endOfGameResult': 'GameComplete', 'participants': members}


class FakeSource:
    platform = 'HN1'
    account = {'puuid': 'SYNTHETIC-PUUID-1', 'gameName': 'SYNTHETIC-NAME-1', 'tagLine': 'TAG'}
    account_key = 'HN1:SYNTHETIC-PUUID-1'
    fail = False
    fetches = 0
    def list_ids(self, start, count):
        return ['HN1_1000001'][start:start+count]
    def summary(self, mid):
        type(self).fetches += 1
        if self.fail:
            raise SourceError('upstream_unavailable', 503)
        return game()


class MayhemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = Store(self.directory)
        self.store.register(FakeSource())
        FakeSource.fail, FakeSource.fetches = False, 0

    def tearDown(self):
        self.temporary.cleanup()

    def test_other_queues_are_rejected(self):
        for qid in (450, 420, 2410, 2450, 2401):
            raw = game()
            raw['queueId'] = qid
            with self.subTest(qid=qid), self.assertRaises(NotStandardMayhem):
                normalize(raw, FakeSource.account['puuid'])

    def test_incomplete_or_other_accounts_game_is_rejected(self):
        raw = game()
        raw['participants'].pop()
        with self.assertRaisesRegex(SourceError, 'incomplete_ten_player'):
            normalize(raw, FakeSource.account['puuid'])
        with self.assertRaisesRegex(SourceError, 'self_not_in_match'):
            normalize(game(), 'unrelated-player')

    def test_missing_augment_is_not_empty_slot(self):
        raw = game()
        del raw['participants'][0]['playerAugment6']
        match = normalize(raw, FakeSource.account['puuid'])
        self.assertFalse(match['augment_complete'])
        self.assertEqual(match['participants'][0]['augment_slots'][-2:], [0, None])

    def test_idempotent_upsert_keeps_ten_players(self):
        match = normalize(game(), FakeSource.account['puuid'])
        self.store.put(FakeSource.account_key, match)
        self.store.put(FakeSource.account_key, match)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM matches').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM participants').fetchone()[0], 10)

    def test_failure_is_pending_then_resumes_without_duplicates(self):
        FakeSource.fail = True
        first = run_sync(self.directory, 20, source_factory=FakeSource)
        self.assertEqual(first['outcome'], 'completed_with_gaps')
        self.assertEqual(self.store.counts(), {'failed': 1})
        FakeSource.fail = False
        second = run_sync(self.directory, 20, source_factory=FakeSource)
        self.assertEqual(second['completed'], 1)
        self.assertEqual(self.store.counts(), {'complete': 1})
        before = FakeSource.fetches
        third = run_sync(self.directory, 20, source_factory=FakeSource)
        self.assertEqual(third['cached'], 1)
        self.assertEqual(FakeSource.fetches, before)

    def test_account_switch_does_not_mix_personal_stats(self):
        match = normalize(game(), FakeSource.account['puuid'])
        self.store.put(FakeSource.account_key, match)
        second = types.SimpleNamespace(platform='HN1', account_key='HN1:SYNTHETIC-PUUID-6',
            account={'puuid': 'SYNTHETIC-PUUID-6', 'gameName': 'Second', 'tagLine': 'T'})
        self.store.register(second)
        self.assertEqual(len(self.store.all_matches()), 0)
        self.store.put(second.account_key, normalize(game(), second.account['puuid']))
        self.assertEqual(self.store.all_matches()[0]['self']['kills'], 6)
        self.assertEqual(metrics(self.store.all_matches())['wins'], 0)

    def test_metrics_denominators_and_augment_frequency(self):
        old = game(1000002, False)
        old['gameVersion'] = '16.19.1'
        for raw in (game(), old):
            self.store.put(FakeSource.account_key, normalize(raw, FakeSource.account['puuid']))
        result = metrics(self.store.all_matches())
        self.assertEqual(result['games'], 2)
        self.assertEqual(result['win_rate'], .5)
        self.assertEqual(result['kda'], 3)
        self.assertEqual(result['dpm'], 100)
        self.assertAlmostEqual(result['kill_participation'], .2)
        self.assertAlmostEqual(result['damage_share'], .2)
        self.assertTrue(all('wins' not in a and 'win_rate' not in a for a in result['augments']))
        self.assertEqual(len(self.store.all_matches(patch='16.20')), 1)

    def test_remote_origin_boundary(self):
        self.assertEqual(approved_origin('https://hn1-k8s-sgp.lol.qq.com:21019'), 'https://hn1-k8s-sgp.lol.qq.com:21019')
        for origin in ('http://hn1.lol.qq.com', 'https://lol.qq.com.evil.test', 'https://user:password@hn1.lol.qq.com', 'https://hn1.lol.qq.com/other'):
            with self.subTest(origin=origin), self.assertRaises(SourceError):
                approved_origin(origin)

    def test_connection_error_does_not_disclose_credentials(self):
        source = TencentSource.__new__(TencentSource)
        source._token, source._expires = 'SECRET-SENTINEL', 9999999999
        source.origin, source.request_count = 'https://hn1.lol.qq.com', 0
        source._opener = types.SimpleNamespace(open=lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError('SECRET-SENTINEL private-puuid')))
        with patch('core.time.sleep'), self.assertRaises(SourceError) as caught:
            source.get('/match-history-query/example', retries=0)
        self.assertNotIn('SECRET-SENTINEL', str(caught.exception))
        self.assertNotIn('private-puuid', str(caught.exception))

    def test_detail_does_not_expose_puuid(self):
        self.store.put(FakeSource.account_key, normalize(game(), FakeSource.account['puuid']))
        detail = self.store.detail('HN1_1000001')
        self.assertNotIn('SYNTHETIC-PUUID', json.dumps(detail))
        self.assertTrue(detail['participants'][0]['is_self'])

    def test_source_failure_preserves_existing_data(self):
        self.store.put(FakeSource.account_key, normalize(game(), FakeSource.account['puuid']))
        def unavailable():
            raise SourceError('client_not_running')
        result = run_sync(self.directory, 20, source_factory=unavailable)
        self.assertFalse(result['running'])
        self.assertEqual(result['outcome'], 'source_unavailable')
        self.assertEqual(len(self.store.all_matches()), 1)

    def test_http_host_and_csrf_boundary(self):
        server = LocalServer(('127.0.0.1', 0), self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with self.assertRaises(OSError):
                LocalServer(('127.0.0.1', server.server_port), self.store)
            with urllib.request.urlopen(base + '/api/health') as response:
                self.assertTrue(json.load(response)['ok'])
            bad = urllib.request.Request(base + '/api/sync', data=b'{"limit":20}',
                    headers={'Origin': 'https://unrelated.example', 'X-Mayhem-CSRF': server.nonce})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(bad)
            self.assertEqual(caught.exception.code, 403)
            rebinding = urllib.request.Request(base + '/api/overview', headers={'Host': 'unrelated.example'})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(rebinding)
            self.assertEqual(caught.exception.code, 403)
            self.assertIsNone(server.job)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
