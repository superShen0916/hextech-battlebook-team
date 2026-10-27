"""Post-game enrichment tests; all records live in isolated temporary stores."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import normalize
from enrichment import enrich_matches
from insights import build_insights
from main import LocalServer
from store import Store


MATCH_KEY = 'TEST_1000001'


def raw_match():
    players = []
    for pid in range(1, 11):
        player = {'participantId': pid, 'puuid': f'PRIVATE-PUUID-{pid}',
                  'teamId': 100 if pid <= 5 else 200, 'championId': pid,
                  'championName': f'Hero {pid}', 'riotIdGameName': f'Player {pid}',
                  'kills': 1, 'deaths': 1, 'assists': 1, 'win': pid <= 5,
                  'totalDamageDealtToChampions': pid * 100,
                  'doubleKills': 2 if pid == 1 else 0,
                  'tripleKills': 1 if pid == 1 else 0, 'quadraKills': 0, 'pentaKills': 0,
                  'largestMultiKill': 3 if pid == 1 else 1, 'largestKillingSpree': 4}
        player.update({f'playerAugment{slot}': 0 for slot in range(1, 7)})
        players.append(player)
    return {'platformId': 'TEST', 'gameId': 1000001, 'queueId': 2400,
            'gameMode': 'KIWI', 'gameVersion': '16.20.1', 'gameCreation': 1000,
            'gameDuration': 600, 'endOfGameResult': 'GameComplete', 'participants': players}


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.source = SimpleNamespace(platform='TEST', account_key='TEST:PRIVATE-PUUID-1',
                                      account={'puuid': 'PRIVATE-PUUID-1',
                                               'gameName': 'Player 1', 'tagLine': 'TEST'})
        self.store.register(self.source)
        self.raw = raw_match()
        old = normalize(self.raw, self.source.account['puuid'])
        # Simulate a record created before the app mapped any multikill fields.
        for player in old['participants']:
            for key in ('double_kills', 'triple_kills', 'quadra_kills', 'penta_kills',
                        'largest_multi_kill', 'largest_killing_spree'):
                player.pop(key, None)
        self.store.put(self.source.account_key, old)

    def tearDown(self):
        self.temporary.cleanup()

    def save_raw(self, raw=None):
        self.store.save_payload(MATCH_KEY, 'summary', 'synthetic-test', self.raw if raw is None else raw)

    def stored_payload(self):
        with self.store.connect() as db:
            return db.execute('SELECT payload FROM matches WHERE match_key=?', (MATCH_KEY,)).fetchone()[0]

    def test_legacy_raw_multikills_enrich_memory_and_feed_highlights_without_db_write(self):
        before = self.stored_payload()
        self.save_raw()
        records = self.store.all_matches()
        self.assertNotIn('triple_kills', records[0]['self'])
        enriched = enrich_matches(self.store, records)
        self.assertIs(enriched, records)
        self.assertEqual(enriched[0]['self']['double_kills'], 2)
        self.assertEqual(enriched[0]['self']['triple_kills'], 1)
        highlights = build_insights(enriched)['highlights']
        self.assertEqual(highlights['totals']['triple_kills'], 1)
        self.assertEqual(highlights['largest_multi_kill'], 3)
        self.assertEqual(highlights['samples']['triple_kills'], 1)
        self.assertEqual(self.stored_payload(), before)
        self.assertNotIn('triple_kills', self.store.all_matches()[0]['self'])

    def test_true_zero_and_independently_missing_fields(self):
        player = self.raw['participants'][0]
        player.update(doubleKills=0, pentaKills=None, largestMultiKill=0)
        del player['tripleKills']
        self.save_raw()
        own = enrich_matches(self.store, self.store.all_matches())[0]['self']
        self.assertEqual(own['double_kills'], 0)
        self.assertEqual(own['quadra_kills'], 0)
        self.assertEqual(own['largest_multi_kill'], 0)
        self.assertIsNone(own['triple_kills'])
        self.assertIsNone(own['penta_kills'])

    def test_raw_game_identity_mismatch_cannot_attach(self):
        invalid = copy.deepcopy(self.raw)
        invalid['gameId'] = 9999999
        self.save_raw(invalid)
        own = enrich_matches(self.store, self.store.all_matches())[0]['self']
        self.assertIsNone(own['double_kills'])
        self.assertIsNone(own['largest_multi_kill'])

    def test_raw_player_identity_mismatch_cannot_attach(self):
        invalid = copy.deepcopy(self.raw)
        invalid['participants'][0]['puuid'] = 'OTHER-PRIVATE-PUUID'
        self.save_raw(invalid)
        own = enrich_matches(self.store, self.store.all_matches())[0]['self']
        self.assertIsNone(own['double_kills'])
        self.assertIsNone(own['triple_kills'])

    def test_complete_team_damage_shares_and_ten_player_ranks(self):
        players = enrich_matches(self.store, self.store.all_matches())[0]['participants']
        self.assertAlmostEqual(players[0]['damage_share'], 100 / 1500)
        self.assertAlmostEqual(players[4]['damage_share'], 500 / 1500)
        self.assertAlmostEqual(players[5]['damage_share'], 600 / 4000)
        self.assertEqual([p['damage_rank'] for p in players], list(range(10, 0, -1)))

    def test_missing_damage_blocks_affected_team_share_and_all_player_rank(self):
        records = self.store.all_matches()
        records[0]['participants'][1]['damage'] = None
        players = enrich_matches(self.store, records)[0]['participants']
        self.assertTrue(all(p['damage_share'] is None for p in players[:5]))
        self.assertAlmostEqual(players[5]['damage_share'], 600 / 4000)
        self.assertTrue(all(p['damage_rank'] is None for p in players))

    def test_zero_team_total_is_uncomputable_but_zero_individual_is_valid(self):
        records = self.store.all_matches()
        for player in records[0]['participants'][:5]:
            player['damage'] = 0
        players = enrich_matches(self.store, records)[0]['participants']
        self.assertTrue(all(p['damage_share'] is None for p in players[:5]))
        self.assertEqual([p['damage_rank'] for p in players[:5]], [6] * 5)
        records[0]['participants'][1]['damage'] = 100
        own = enrich_matches(self.store, records)[0]['self']
        self.assertEqual(own['damage_share'], 0)

    def test_tied_damage_uses_competition_ranking(self):
        records = self.store.all_matches()
        for player, damage in zip(records[0]['participants'], [1000, 1000, 500, 100, 100, 50, 40, 30, 20, 10]):
            player['damage'] = damage
        players = enrich_matches(self.store, records)[0]['participants']
        self.assertEqual([p['damage_rank'] for p in players], [1, 1, 3, 4, 4, 6, 7, 8, 9, 10])

    def test_cached_raw_values_refresh_after_payload_update(self):
        self.save_raw()
        first = enrich_matches(self.store, self.store.all_matches())[0]['self']
        self.assertEqual(first['triple_kills'], 1)
        self.raw['participants'][0]['tripleKills'] = 7
        self.save_raw()
        second = enrich_matches(self.store, self.store.all_matches())[0]['self']
        self.assertEqual(second['triple_kills'], 7)

    def test_public_detail_has_enriched_fields_without_puuid(self):
        self.save_raw()
        server = LocalServer(('127.0.0.1', 0), self.store)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{server.server_port}/api/match/{MATCH_KEY}', timeout=5) as response:
                public = json.load(response)
            self.assertEqual(public['participants'][0]['double_kills'], 2)
            self.assertEqual(public['participants'][0]['triple_kills'], 1)
            self.assertEqual(public['participants'][0]['damage_rank'], 10)
            serialized = json.dumps(public)
            self.assertNotIn('puuid', serialized.lower())
            self.assertNotIn('PRIVATE-PUUID', serialized)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
