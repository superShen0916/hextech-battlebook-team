"""Score arithmetic, exclusions, ties, and public API integration."""
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
from awards import annotate_awards, award_summary
from core import normalize
from enrichment import enrich_matches
from main import LocalServer, overview
from store import Store
from test_enrichment import raw_match


def complete_raw(number=1000001):
    raw = raw_match()
    raw['gameId'] = number
    for p in raw['participants']:
        p.update(totalDamageTaken=1000, totalHealsOnTeammates=0,
                 timeCCingOthers=0, totalDamageShieldedOnTeammates=0)
    return raw


def record(raw=None):
    raw = complete_raw() if raw is None else raw
    m = normalize(raw, raw['participants'][0]['puuid'])
    for p, r in zip(m['participants'], raw['participants']):
        p.update(cc_seconds=r['timeCCingOthers'], shield_teammates=r['totalDamageShieldedOnTeammates'])
    m['self'] = m['participants'][0]
    return m


class AwardTests(unittest.TestCase):
    def test_independent_hand_calculation_and_separate_team_badges(self):
        m = record()
        annotate_awards(m)
        p = m['participants'][4]
        # v0.5: 250*(500/1500)*.40 damage + 100*(2/5)*.15 KP
        # + 200*(1/5)*.10 kills + 50*.10 survival
        # + (.6*(50*(2/5)/.6))*.25 utility = 53 1/3.
        self.assertAlmostEqual(p['performance']['score'], 160 / 3)
        self.assertEqual(p['performance']['award'], 'MVP')
        self.assertEqual(m['participants'][9]['performance']['award'], 'ACE')
        self.assertEqual(m['participants'][0]['performance']['team_rank'], 5)
        self.assertTrue(m['performance']['available'])

    def test_damage_caps_at_forty_percent_but_kills_need_fifty(self):
        for share, expected_damage, expected_kills in ((.20, 50, 40), (.25, 62.5, 50),
                                                      (.40, 100, 80), (.50, 100, 100),
                                                      (.60, 100, 100)):
            with self.subTest(share=share):
                m = record()
                for team_id in (100, 200):
                    team = [p for p in m['participants'] if p['team_id'] == team_id]
                    for index, p in enumerate(team):
                        value = 100 * (share if index == 0 else (1-share)/4)
                        p.update(kills=value, assists=0, damage=value)
                annotate_awards(m)
                self.assertTrue(m['performance']['available'])
                dims = m['participants'][0]['performance']['dimensions']
                self.assertAlmostEqual(dims['damage'], expected_damage)
                self.assertAlmostEqual(dims['kills'], expected_kills)

    def test_zero_control_and_protection_are_valid(self):
        m = record()
        annotate_awards(m)
        self.assertTrue(all(p['performance'] is not None for p in m['participants']))

    def test_missing_field_blocks_entire_match_and_does_not_retain_stale_awards(self):
        for key in ('damage', 'taken', 'heal', 'cc_seconds', 'shield_teammates'):
            with self.subTest(key=key):
                m = record()
                annotate_awards(m)
                m['participants'][9][key] = None
                annotate_awards(m)
                self.assertEqual(m['performance']['reason'], 'missing_or_invalid_fields')
                self.assertTrue(all(p['performance'] is None for p in m['participants']))

    def test_ineligible_match_never_awarded(self):
        m = record()
        m['stats_eligible'] = False
        annotate_awards(m)
        self.assertFalse(m['performance']['available'])
        self.assertTrue(all(p['performance'] is None for p in m['participants']))
        self.assertEqual(award_summary([m])['games'], 0)

    def test_invalid_numbers_are_not_treated_as_zero(self):
        for value in (float('nan'), float('inf'), -1, True, '20'):
            with self.subTest(value=value):
                m = record()
                m['participants'][0]['cc_seconds'] = value
                annotate_awards(m)
                self.assertFalse(m['performance']['available'])

    def test_zero_team_denominator_is_unavailable(self):
        for key in ('kills', 'damage'):
            m = record()
            for p in m['participants'][:5]:
                p[key] = 0
            annotate_awards(m)
            self.assertEqual(m['performance']['reason'], 'zero_team_denominator')

    def test_true_ties_share_badge_and_do_not_depend_on_participant_order(self):
        m = record()
        for p in m['participants']:
            p['damage'] = 100
        annotate_awards(m)
        for p in m['participants']:
            self.assertEqual(p['performance']['team_rank'], 1)
            self.assertTrue(p['performance']['tied'])
            self.assertEqual(p['performance']['award'], 'MVP' if p['win'] else 'ACE')
        before = {p['participant_id']: copy.deepcopy(p['performance']) for p in m['participants']}
        m['participants'].reverse()
        annotate_awards(m)
        self.assertEqual(before, {p['participant_id']: p['performance'] for p in m['participants']})

    def test_incomplete_or_inconsistent_teams_are_rejected(self):
        for change in ('remove', 'duplicate', 'win', 'participation', 'mode'):
            with self.subTest(change=change):
                m = record()
                if change == 'remove': m['participants'].pop()
                elif change == 'duplicate': m['participants'][1]['participant_id'] = 1
                elif change == 'win': m['participants'][0]['win'] = False
                elif change == 'participation': m['participants'][0]['assists'] = 99
                elif change == 'mode': m['queue_id'] = 450
                annotate_awards(m)
                self.assertFalse(m['performance']['available'])


class AwardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.source = SimpleNamespace(platform='TEST', account_key='TEST:PRIVATE-PUUID-5',
            account={'puuid': 'PRIVATE-PUUID-5', 'gameName': 'Owner', 'tagLine': 'TEST'})
        self.store.register(self.source)
        for index in range(3):
            raw = complete_raw(1000001 + index)
            if index == 1:
                raw['participants'][4]['championId'] = 55
                for p in raw['participants']: p['win'] = not p['win']
            key = f'TEST_{raw["gameId"]}'
            self.store.put(self.source.account_key, normalize(raw, self.source.account['puuid']))
            self.store.save_payload(key, 'summary', 'awards-synthetic', raw)
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

    def test_overview_counts_follow_current_filters_and_no_db_payload_rewrite(self):
        with self.store.connect() as db:
            before = list(db.execute('SELECT payload FROM matches ORDER BY match_key'))
            before = [r[0] for r in before]
        data = self.get('/api/overview')
        self.assertEqual(data['insights']['awards'], {'version': '0.5', 'games': 3, 'missing_games': 0, 'mvp': 2, 'ace': 1})
        filtered = self.get('/api/overview?champion=55')
        self.assertEqual(filtered['insights']['awards']['mvp'], 0)
        self.assertEqual(filtered['insights']['awards']['ace'], 1)
        self.assertNotIn('PRIVATE-PUUID', json.dumps(data))
        with self.store.connect() as db:
            after = [r[0] for r in db.execute('SELECT payload FROM matches ORDER BY match_key')]
        self.assertEqual(before, after)

    def test_match_api_exposes_performance_and_labels_without_identity(self):
        data = self.get('/api/match/TEST_1000001')
        self.assertTrue(data['performance']['available'])
        self.assertEqual(data['participants'][4]['performance']['award'], 'MVP')
        self.assertEqual(data['participants'][9]['performance']['award'], 'ACE')
        self.assertNotIn('PRIVATE-PUUID', json.dumps(data))

    def test_companion_uses_its_own_award_and_independent_summary(self):
        roster = self.get('/api/companions')['companions']
        companion = next(p for p in roster if p['game_name'] == 'Player 1')
        self.assertEqual(companion['awards'], {'version': '0.5', 'games': 3, 'missing_games': 0, 'mvp': 0, 'ace': 0})
        data = self.get('/api/companion/' + companion['ref'])
        self.assertEqual(data['insights']['awards']['mvp'], 0)
        self.assertEqual(data['insights']['awards']['ace'], 0)
        self.assertTrue(all(m['player']['performance']['team_rank'] == 5 for m in data['recent']))
        self.assertTrue(all(next(p for p in m['participants'] if p['is_self'])['performance']['award'] in ('MVP', 'ACE') for m in data['recent']))
        self.assertNotIn('PRIVATE-PUUID', json.dumps(data))


if __name__ == '__main__':
    unittest.main()
