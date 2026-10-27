"""Friend analysis is limited to actual shared matches in this account."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import normalize
from main import LocalServer
from store import Store
from test_mayhem import FakeSource, game


class CompanionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.register(FakeSource())
        for index in range(3):
            self.store.put(FakeSource.account_key, normalize(game(1000001 + index), FakeSource.account['puuid']))
        self.server = LocalServer(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return json.load(response)

    def companion(self):
        return next(p for p in self.get('/api/companions')['companions'] if p['game_name'] == 'SYNTHETIC-NAME-2')

    def test_automatic_roster_and_friend_metrics_use_the_friend(self):
        roster = self.get('/api/companions')
        self.assertEqual(roster['minimum_shared_games'], 3)
        self.assertEqual(len(roster['companions']), 4)
        self.assertNotIn('SYNTHETIC-PUUID', json.dumps(roster))
        player = self.companion()
        self.assertEqual(player['shared_games'], 3)
        self.assertEqual(player['summary']['kda'], 4)
        detail = self.get('/api/companion/' + player['ref'])
        self.assertEqual(detail['insights']['summary']['kda'], 4)
        self.assertEqual(detail['recent'][0]['player']['kills'], 2)
        self.assertEqual(detail['recent'][0]['focus_participant_id'], 2)
        self.assertNotIn('SYNTHETIC-PUUID', json.dumps(detail))

    def test_friend_filters_are_independent_and_do_not_remove_qualification(self):
        ref = self.companion()['ref']
        friend_hero = self.get('/api/companion/' + ref + '?champion=2')
        self.assertEqual(friend_hero['shared_games'], 3)
        empty = self.get('/api/companion/' + ref + '?champion=1')
        self.assertEqual(empty['shared_games'], 0)
        self.assertEqual(empty['companion']['shared_games'], 3)
        self.assertEqual(len(self.get('/api/companions')['companions']), 4)

    def test_detail_marks_friend_focus_without_changing_original_self(self):
        ref = self.companion()['ref']
        detail = self.get('/api/match/HN1_1000001?companion=' + ref)
        own = next(p for p in detail['participants'] if p['participant_id'] == 1)
        friend = next(p for p in detail['participants'] if p['participant_id'] == 2)
        self.assertTrue(own['is_self'])
        self.assertFalse(own['is_focus'])
        self.assertFalse(friend['is_self'])
        self.assertTrue(friend['is_focus'])
        self.assertEqual(detail['focus']['participant_id'], 2)
        self.assertNotIn('SYNTHETIC-PUUID', json.dumps(detail))

    def test_unknown_reference_and_malformed_filters_are_rejected(self):
        for path, expected in [('/api/companion/' + 'f' * 24, 404),
                               ('/api/companion/not-a-ref', 400),
                               ('/api/companion/' + self.companion()['ref'] + '?days=1', 400),
                               ('/api/match/HN1_1000001?companion=' + 'f' * 24, 404)]:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, expected)

    def test_account_switch_cannot_use_the_previous_accounts_reference(self):
        ref = self.companion()['ref']
        second = types.SimpleNamespace(platform='HN1', account_key='HN1:SYNTHETIC-PUUID-6',
            account={'puuid': 'SYNTHETIC-PUUID-6', 'gameName': 'Second', 'tagLine': 'TEST'})
        self.store.register(second)
        for index in range(3):
            self.store.put(second.account_key, normalize(game(1000001 + index), second.account['puuid']))
        self.assertNotIn(ref, [p['ref'] for p in self.get('/api/companions')['companions']])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get('/api/companion/' + ref)
        self.assertEqual(error.exception.code, 404)

    def test_static_asset_path_cannot_escape_the_icons_directory(self):
        root = Path(self.temp.name) / 'public'
        icon = root / 'static/icons/champions/1.png'
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b'\x89PNG\r\n\x1a\nSYNTHETIC-ICON')
        (root / 'private.txt').write_text('PRIVATE-SENTINEL', encoding='utf-8')
        with patch('main.APP', root):
            with urllib.request.urlopen(self.base + '/assets/champions/1.png') as response:
                self.assertEqual(response.headers['Content-Type'], 'image/png')
                self.assertTrue(response.read().startswith(b'\x89PNG'))
            for path in ('/assets/../private.txt', '/assets/champions/%2e%2e/%2e%2e/private.txt',
                         '/assets/champions/1.png%00', '/assets/champions/1.svg'):
                with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(self.base + path)
                self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
