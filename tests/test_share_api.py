"""Share endpoints read synthetic local data and never trigger collection."""
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import normalize
from main import LocalServer, main
from store import Store
from test_mayhem import FakeSource, game


class ShareApiTests(unittest.TestCase):
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

    def test_report_reads_saved_data_without_match_identity_or_writes(self):
        with self.store.connect() as db:
            before = [tuple(r) for r in db.execute('SELECT match_key,payload,payload_hash FROM matches ORDER BY match_key')]
        with urllib.request.urlopen(self.base + '/api/share-report') as response:
            report = json.load(response)
        self.assertEqual(report['overview']['saved'], 3)
        self.assertEqual(report['overview']['companions'], 0)
        self.assertEqual(report['minimum_award_games'], 20)
        self.assertEqual(report['leaderboard'], [])
        self.assertTrue(all(not award['leaders'] for award in report['awards']))
        text = json.dumps(report, allow_nan=False)
        self.assertNotIn('SYNTHETIC-PUUID', text)
        self.assertNotIn('HN1_1000001', text)
        self.assertIsNone(self.server.job)
        with self.store.connect() as db:
            after = [tuple(r) for r in db.execute('SELECT match_key,payload,payload_hash FROM matches ORDER BY match_key')]
        self.assertEqual(before, after)

    def test_only_supported_periods_and_sample_gates_are_accepted(self):
        for query in ('minimum=9', 'minimum=10', 'minimum=19', 'minimum=1000', 'minimum=oops', 'days=7', 'days=-1'):
            with self.subTest(query=query), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + '/api/share-report?' + query)
            self.assertEqual(error.exception.code, 400)
        with urllib.request.urlopen(self.base + '/api/share-report?minimum=20&days=30') as response:
            report = json.load(response)
        self.assertEqual(report['filters']['days'], 30)
        self.assertEqual(report['minimum_award_games'], 20)
        with urllib.request.urlopen(self.base + '/api/share-report?minimum=30') as response:
            self.assertEqual(json.load(response)['minimum_award_games'], 30)

    def test_share_page_and_health_advertise_the_new_capability(self):
        with urllib.request.urlopen(self.base + '/share') as response:
            self.assertIn('text/html', response.headers['Content-Type'])
            self.assertIn('sharePreview', response.read().decode('utf-8'))
        with urllib.request.urlopen(self.base + '/api/health') as response:
            self.assertEqual(json.load(response)['sharing_version'], 3)

    def test_default_twenty_game_boundary_does_not_change_regular_companions(self):
        with urllib.request.urlopen(self.base + '/api/companions') as response:
            self.assertEqual(len(json.load(response)['companions']), 4)
        for index in range(3, 19):
            self.store.put(FakeSource.account_key, normalize(game(1000001 + index), FakeSource.account['puuid']))
        with urllib.request.urlopen(self.base + '/api/share-report') as response:
            before = json.load(response)
        self.assertEqual(before['overview']['saved'], 19)
        self.assertEqual(before['overview']['companions'], 0)
        self.assertEqual(before['leaderboard'], [])
        self.store.put(FakeSource.account_key, normalize(game(1000020), FakeSource.account['puuid']))
        with urllib.request.urlopen(self.base + '/api/share-report') as response:
            after = json.load(response)
        self.assertEqual(after['overview']['saved'], 20)
        self.assertEqual(after['overview']['companions'], 4)
        self.assertTrue(after['leaderboard'])
        self.assertTrue(all(row['samples'] == 20 for row in after['leaderboard']))
        with urllib.request.urlopen(self.base + '/api/share-report?minimum=30') as response:
            self.assertEqual(json.load(response)['leaderboard'], [])

    def test_launcher_rejects_old_sharing_version_without_reusing_it(self):
        arguments = ['main.py', '--data-dir', self.temp.name, 'serve', '--port', '8765', '--open']
        old = {'ok': True, 'mode': 'standard_mayhem_only', 'dashboard_version': 3, 'sharing_version': 2}
        opener = SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(json.dumps(old).encode()))
        with patch('sys.argv', arguments), patch('main.LocalServer', side_effect=OSError), patch(
                'main.urllib.request.build_opener', return_value=opener), patch('main.webbrowser.open') as opened, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 2)
        opened.assert_not_called()

    def test_share_launcher_opens_the_share_page_on_an_existing_compatible_server(self):
        arguments = ['main.py', '--data-dir', self.temp.name, 'serve', '--port',
                     str(self.server.server_port), '--open', '--page', '/share']
        with patch('sys.argv', arguments), patch('main.webbrowser.open') as opened, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        opened.assert_called_once_with(self.base + '/share')


if __name__ == '__main__':
    unittest.main()
