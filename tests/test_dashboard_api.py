"""API integration against temporary synthetic match data only."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import normalize
from main import LocalServer, overview
from store import Store
from test_mayhem import FakeSource, game


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.register(FakeSource())
        for index in range(2):
            raw = game(1000001 + index)
            raw['participants'][0]['championId'] = index + 1
            self.store.put(FakeSource.account_key, normalize(raw, FakeSource.account['puuid']))

    def tearDown(self):
        self.temp.cleanup()

    def test_filters_keep_champion_choices_and_recalculate_insights(self):
        data = overview(self.store, champion=2)
        self.assertEqual(data['games'], 1)
        self.assertEqual(data['insights']['summary']['games'], 1)
        self.assertEqual(data['insights']['champions'][0]['champion_id'], 2)
        self.assertEqual({p['champion_id'] for p in data['champion_options']}, {1, 2})
        self.assertFalse(data['recent'][0]['timeline_available'])
        self.assertEqual(data['filtered_timeline_coverage'], 0)
        self.assertNotIn('SYNTHETIC-PUUID', json.dumps(data))

    def test_timeline_route_missing_data_is_distinct_from_missing_match(self):
        server = LocalServer(('127.0.0.1', 0), self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base + '/api/timeline/HN1_1000001') as response:
                data = json.load(response)
            self.assertFalse(data['available'])
            self.assertEqual(data['reason'], 'timeline_not_collected')
            for key, expected in [('HN1_999999', 404), ('bad-key', 400)]:
                with self.subTest(key=key), self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(base + '/api/timeline/' + key)
                self.assertEqual(caught.exception.code, expected)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
