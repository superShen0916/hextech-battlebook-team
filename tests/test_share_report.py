"""Sharing regressions using synthetic records and temporary SQLite only."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from share_report import build_share_report, load_share_report, _SnapshotStore
from store import Store


def game(index, friend='ALLY-A', name='Ally A', win=True, eligible=True):
    players = []
    for pid in range(1, 11):
        focus = pid == 2
        players.append({'participant_id': pid,
                        'puuid': 'OWNER-SECRET' if pid == 1 else friend if focus else f'OTHER-{index}-{pid}',
                        'team_id': 100 if pid <= 5 else 200, 'champion_id': 22 if focus else pid,
                        'champion_name': 'Friend hero' if focus else f'Hero {pid}',
                        'game_name': name if focus else f'Player {pid}', 'tag_line': 'PRIVATE-TAG',
                        'win': win if pid <= 5 else not win, 'kills': 1, 'deaths': 1, 'assists': 1,
                        'damage': 800 if focus else 100, 'taken': 600 if focus else 100,
                        'heal': 20 if focus else 0, 'shield_teammates': 40 if focus else 0,
                        'gold': 1000, 'augment_slots': [0] * 6, 'augment_complete': True,
                        'penta_kills': 1 if focus else 0,
                        'performance': {'version': '0.2', 'score': 99 if focus else 1,
                                        'award': 'MVP' if focus and win else None}})
    return {'match_key': f'TEST_{index}', 'queue_id': 2400, 'game_mode': 'KIWI',
            'patch': '16.20.1', 'started_ms': index * 100000, 'duration': 120,
            'stats_eligible': eligible, 'augment_complete': True, 'participants': players,
            'self': players[0], 'platform': 'TEST', 'game_id': str(index)}


def award(report, aid):
    return next(row for row in report['awards'] if row['id'] == aid)


class ShareReportTests(unittest.TestCase):
    def test_small_perfect_sample_does_not_beat_larger_good_sample(self):
        records = [game(i, friend='SMALL', name='Small') for i in range(1, 4)]
        records += [game(i + 10, friend='LARGE', name='Large', win=i < 80) for i in range(100)]
        report = build_share_report(records)
        self.assertEqual(report['leaderboard'][0]['name'], 'Large')
        self.assertEqual(award(report, 'best_partner')['leaders'][0]['name'], 'Large')
        self.assertNotIn('Small', [p['name'] for p in report['leaderboard']])
        self.assertNotIn('Small', [p['name'] for p in award(report, 'best_partner')['leaders']])
        self.assertEqual(report['overview']['companions'], 1)

    def test_leaderboard_respects_twenty_and_thirty_game_gates(self):
        records = [game(i, friend='NINETEEN', name='Nineteen') for i in range(1, 20)]
        records += [game(i + 20, friend='TWENTY', name='Twenty') for i in range(20)]
        records += [game(i + 50, friend='THIRTY', name='Thirty') for i in range(30)]
        for minimum, expected in ((20, {'Twenty', 'Thirty'}), (30, {'Thirty'})):
            report = build_share_report(records, minimum_award_games=minimum)
            self.assertEqual({p['name'] for p in report['leaderboard']}, expected)
            self.assertTrue(all(p['samples'] >= minimum for p in report['leaderboard']))
            self.assertTrue(all(p['qualified'] for p in report['leaderboard']))
            self.assertEqual(report['overview']['companions'], len(expected))

    def test_each_award_requires_its_own_twenty_known_samples(self):
        records = [game(i) for i in range(1, 21)]
        records[0]['participants'][1].update(damage=None, taken=None, heal=None, penta_kills=None)
        report = build_share_report(records)
        self.assertTrue(award(report, 'best_partner')['leaders'])
        self.assertTrue(award(report, 'most_played')['leaders'])
        for aid in ('damage_carry', 'protector', 'penta_king'):
            self.assertEqual(award(report, aid)['leaders'], [], aid)
        report30 = build_share_report(records, minimum_award_games=30)
        self.assertTrue(all(not a['leaders'] for a in report30['awards']))

    def test_nineteen_eligible_excluded_and_twentieth_eligible_qualifies(self):
        records = [game(i) for i in range(1, 20)]
        records.append(game(20, eligible=False))
        before = build_share_report(records)
        self.assertEqual(before['minimum_award_games'], 20)
        self.assertEqual(before['overview']['companions'], 0)
        self.assertEqual(before['leaderboard'], [])
        self.assertTrue(all(not item['leaders'] for item in before['awards']))
        records.append(game(21))
        after = build_share_report(records)
        self.assertEqual(after['overview']['companions'], 1)
        self.assertEqual(after['leaderboard'][0]['samples'], 20)
        self.assertEqual(after['leaderboard'][0]['shared_games'], 21)

    def test_tied_people_share_awards_and_scores_are_never_averaged(self):
        records = [game(i) for i in range(1, 21)]
        records += [game(i, friend='ALLY-B', name='Ally B') for i in range(21, 41)]
        report = build_share_report(records)
        for item in report['awards']:
            self.assertTrue(item['ties'], item['id'])
            self.assertEqual(len(item['leaders']), 2)
        self.assertEqual([r['rank'] for r in report['leaderboard']], [1, 1])
        self.assertNotIn('score', json.dumps(report))
        self.assertEqual(report['leaderboard'][0]['secondary']['award_samples'], 20)

    def test_awards_use_friend_fields_and_complete_protection_pair(self):
        records = [game(i) for i in range(1, 21)]
        report = build_share_report(records)
        self.assertAlmostEqual(award(report, 'damage_carry')['leaders'][0]['value'], 800 / 1200)
        self.assertNotIn('tank', [a['id'] for a in report['awards']])
        self.assertEqual(award(report, 'protector')['leaders'][0]['value'], 30)
        self.assertEqual(award(report, 'penta_king')['leaders'][0]['value'], 20)
        self.assertEqual(award(report, 'penta_king')['leaders'][0]['champion_id'], 22)
        for m in records:
            m['participants'][1]['shield_teammates'] = None
        self.assertEqual(award(build_share_report(records), 'protector')['leaders'], [])

    def test_true_zero_has_samples_but_does_not_create_empty_honors(self):
        records = [game(i, win=False) for i in range(1, 21)]
        for m in records:
            m['participants'][1].update(damage=0, taken=0, heal=0, shield_teammates=0, penta_kills=0)
        report = build_share_report(records)
        for aid in ('best_partner', 'damage_carry', 'protector', 'penta_king'):
            item = award(report, aid)
            self.assertEqual(item['qualified_count'], 1)
            self.assertEqual(item['leaders'], [])
        self.assertTrue(award(report, 'most_played')['leaders'])
        self.assertEqual(award(report, 'worst_partner')['leaders'][0]['value'], 0)

    def test_lowest_raw_win_rate_wins_and_real_zero_can_tie(self):
        records = [game(i, friend='LOW', name='Low', win=i <= 4) for i in range(1, 21)]
        records += [game(i + 20, friend='HIGH', name='High', win=i <= 16) for i in range(1, 21)]
        report = build_share_report(records)
        self.assertEqual(len(report['awards']), 10)
        self.assertEqual(award(report, 'worst_partner')['leaders'][0]['name'], 'Low')
        self.assertEqual(award(report, 'worst_partner')['leaders'][0]['value'], .2)
        records += [game(i + 41, friend='ZERO-A', name='Zero A', win=False) for i in range(20)]
        records += [game(i + 61, friend='ZERO-B', name='Zero B', win=False) for i in range(20)]
        losers = award(build_share_report(records), 'worst_partner')
        self.assertTrue(losers['ties'])
        self.assertEqual({p['name'] for p in losers['leaders']}, {'Zero A', 'Zero B'})
        self.assertTrue(all(p['value'] == 0 for p in losers['leaders']))

    def test_new_awards_use_independent_metric_samples_and_friend_values(self):
        records = [game(i) for i in range(1, 21)]
        for m in records:
            for p in m['participants'][:5]:
                p['kills'] = 2
            m['participants'][1].update(kills=3, assists=5)
        report = build_share_report(records)
        self.assertEqual(award(report, 'assist_master')['leaders'][0]['value'], 5)
        self.assertEqual(award(report, 'kill_harvester')['leaders'][0]['value'], 3)
        self.assertAlmostEqual(award(report, 'teamfighter')['leaders'][0]['value'], 8 / 11)
        mvp = award(report, 'mvp_star')['leaders'][0]
        self.assertEqual(mvp['value'], 1)
        self.assertEqual(mvp['samples'], 20)
        self.assertEqual(mvp['secondary']['award_version'], '0.5')
        # Missing deaths prevents KDA but must not remove known kills/assists.
        records[0]['participants'][1]['deaths'] = None
        self.assertTrue(award(build_share_report(records), 'assist_master')['leaders'])
        records[0]['participants'][1]['assists'] = None
        records[1]['participants'][1]['kills'] = None
        records[2]['participants'][1]['performance'] = None
        records[3]['participants'][1]['win'] = None
        missing = build_share_report(records)
        for aid in ('assist_master', 'kill_harvester', 'teamfighter', 'mvp_star', 'worst_partner'):
            self.assertEqual(award(missing, aid)['leaders'], [], aid)

    def test_no_positive_new_metric_does_not_grant_award_and_gate_applies(self):
        records = [game(i) for i in range(1, 31)]
        for m in records:
            m['participants'][1].update(kills=0, assists=0)
            m['participants'][1]['performance']['award'] = None
        for minimum in (20, 30):
            report = build_share_report(records, minimum_award_games=minimum)
            for aid in ('assist_master', 'kill_harvester', 'teamfighter', 'mvp_star'):
                item = award(report, aid)
                self.assertEqual(item['qualified_count'], 1)
                self.assertEqual(item['leaders'], [])
        records[-1]['participants'][1]['performance'] = None
        gated = build_share_report(records, minimum_award_games=30)
        self.assertEqual(award(gated, 'mvp_star')['qualified_count'], 0)
        self.assertEqual(gated['overview']['companions'], 1)

    def test_scope_eligibility_duplicate_boundary_privacy_and_input_purity(self):
        records = [game(i) for i in range(1, 22)]
        records[-1]['stats_eligible'] = False
        wrong_mode = game(100)
        wrong_mode['queue_id'] = 450
        enemy = game(101)
        enemy['participants'][1]['puuid'], enemy['participants'][5]['puuid'] = 'NOT-ALLY', 'ALLY-A'
        records += [wrong_mode, enemy, copy.deepcopy(records[0])]
        before = copy.deepcopy(records)
        report = build_share_report(records, {'game_name': 'Owner', 'platform': 'TEST',
                                               'puuid': 'OWNER-SECRET', 'tag_line': 'PRIVATE-TAG'})
        self.assertEqual(report['overview']['saved'], 22)
        self.assertEqual(report['overview']['eligible'], 21)
        self.assertEqual(report['overview']['companions'], 1)
        self.assertEqual(report['leaderboard'][0]['shared_games'], 21)
        self.assertEqual(report['leaderboard'][0]['games'], 20)
        serialized = json.dumps(report, allow_nan=False)
        for marker in ('puuid', 'uuid', 'OWNER-SECRET', 'ALLY-A', 'TEST_1', 'PRIVATE-TAG', 'match_key'):
            self.assertNotIn(marker, serialized)
        self.assertEqual(records, before)

    def test_empty_and_invalid_options(self):
        report = build_share_report([])
        self.assertEqual(report['overview']['saved'], 0)
        self.assertIsNone(report['overview']['win_rate'])
        self.assertTrue(all(not a['leaders'] for a in report['awards']))
        for invalid in (3, 10, 19, True, 11, 20.0):
            with self.assertRaises(ValueError):
                build_share_report([], minimum_award_games=invalid)

    def test_readonly_loader_keeps_payload_and_schema_and_uses_account_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            source = SimpleNamespace(platform='TEST', account_key='TEST:OWNER-SECRET',
                                     account={'puuid': 'OWNER-SECRET', 'gameName': 'Owner', 'tagLine': 'T'})
            store.register(source)
            for i in range(1, 11):
                store.put(source.account_key, game(i))
            # A separate account's exclusive match must not enter the snapshot.
            other = SimpleNamespace(platform='TEST', account_key='TEST:OTHER-99-3',
                                    account={'puuid': 'OTHER-99-3', 'gameName': 'Other account', 'tagLine': 'T'})
            store.register(other)
            exclusive = game(99)
            exclusive['self'] = exclusive['participants'][2]
            store.put(other.account_key, exclusive)
            store.register(source)
            with store.connect() as db:
                before = db.execute('SELECT match_key,payload FROM matches ORDER BY match_key').fetchall()
                before = [tuple(row) for row in before]
                schema = [tuple(row) for row in db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name')]
            report = load_share_report(store.path)
            self.assertEqual(report['overview']['saved'], 10)
            self.assertEqual(report['account']['game_name'], 'Owner')
            with store.connect() as db:
                self.assertEqual([tuple(row) for row in db.execute('SELECT match_key,payload FROM matches ORDER BY match_key')], before)
                self.assertEqual([tuple(row) for row in db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name')], schema)
            self.assertEqual(load_share_report(store.path, days=30)['overview']['saved'], 0)

    def test_loader_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'missing.sqlite'
            with self.assertRaises(sqlite3.OperationalError):
                load_share_report(missing)
            self.assertFalse(missing.exists())

    def test_loader_uses_query_only_and_same_snapshot_during_concurrent_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            source = SimpleNamespace(platform='TEST', account_key='TEST:OWNER-SECRET',
                                     account={'puuid': 'OWNER-SECRET', 'gameName': 'Owner', 'tagLine': 'T'})
            store.register(source)
            store.put(source.account_key, game(1))
            from share_report import enrich_matches as actual_enrich

            def inspect(snapshot, records):
                with snapshot.connect() as db:
                    self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                    with self.assertRaises(sqlite3.OperationalError):
                        db.execute("DELETE FROM matches")
                store.put(source.account_key, game(2))
                self.assertEqual(len(snapshot.all_matches()), 1)
                return actual_enrich(snapshot, records)

            with patch('share_report.enrich_matches', side_effect=inspect):
                self.assertEqual(load_share_report(store.path)['overview']['saved'], 1)
            self.assertEqual(len(store.all_matches()), 2)


if __name__ == '__main__':
    unittest.main()
