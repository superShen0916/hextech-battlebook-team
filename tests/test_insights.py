"""Synthetic, offline tests; never reads the live SQLite database."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from insights import build_insights


def game(index=1, win=True, eligible=True, slots=None, damage=100, champion=1):
    players = [{'puuid': f'player-{i}', 'participant_id': i + 1,
                'team_id': 100 if i < 5 else 200, 'champion_id': champion if i == 0 else i + 1,
                'champion_name': f'Hero {champion}' if i == 0 else f'Hero {i + 1}',
                'game_name': 'Me' if i == 0 else f'Player {i}', 'tag_line': 'TEST',
                'win': win if i < 5 else not win, 'kills': 2, 'deaths': 1, 'assists': 3,
                'damage': damage if i == 0 else 100,
                'augment_slots': [10, 20, 0, 0, 0, 0] if slots is None else slots}
               for i in range(10)]
    return {'match_key': f'TEST_{index}', 'started_ms': index * 1000,
            'duration': 60, 'stats_eligible': eligible, 'participants': players,
            'self': players[0]}


class InsightsTest(unittest.TestCase):
    def test_eligible_only_pure_and_json_serializable(self):
        records = [game(), game(2, eligible=False, champion=2)]
        before = copy.deepcopy(records)
        result = build_insights(records)
        self.assertEqual(result['hextech']['games'], 1)
        self.assertEqual(len(result['champions']), 1)
        self.assertEqual(records, before)
        json.dumps(result, allow_nan=False)

    def test_metric_denominators_and_zero_are_not_missing(self):
        zero = game(1, damage=0)
        missing = game(2, damage=None)
        unknown_team = game(3, damage=200)
        unknown_team['participants'][1]['damage'] = None
        zero_kills = game(4)
        for player in zero_kills['participants']:
            player['kills'] = 0
        row = build_insights([zero, missing, unknown_team, zero_kills])['champions'][0]
        self.assertEqual(row['samples'], {'wins': 4, 'kda': 4, 'dpm': 3,
                                         'damage_share': 2, 'kill_participation': 3,
                                         'taken': 0, 'taken_per_minute': 0,
                                         'heal': 0, 'heal_per_minute': 0,
                                         'double_kills': 0, 'triple_kills': 0,
                                         'quadra_kills': 0, 'penta_kills': 0,
                                         'largest_multi_kill': 0, 'largest_killing_spree': 0})
        self.assertEqual(row['dpm'], 100)
        self.assertAlmostEqual(row['damage_share'], .1)
        self.assertEqual(row['games'], 4)
        self.assertEqual(row['kda'], 4.5)

    def test_no_zero_denominator_substitution(self):
        record = game(damage=0)
        for player in record['participants']:
            player.update(kills=0, deaths=0, damage=0)
        row = build_insights([record])['champions'][0]
        self.assertIsNone(row['kda'])
        self.assertIsNone(row['damage_share'])
        self.assertIsNone(row['kill_participation'])
        self.assertEqual(row['dpm'], 0)

    def test_hextech_known_empty_missing_and_deduplication(self):
        records = [game(1, slots=[10, 10, 20, 0, None, None]),
                   game(2, slots=[10, 20, 0, 0, 0, 0]),
                   game(3, slots=[None] * 6), game(4, slots=[0] * 6)]
        data = build_insights(records)['hextech']
        self.assertEqual(data['known_slots'], 16)
        self.assertEqual(data['expected_slots'], 24)
        self.assertEqual(data['complete_games'], 2)
        self.assertEqual(data['observed_games'], 3)
        self.assertEqual(data['missing_slot_games'], 2)
        self.assertEqual(data['augments'], [{'id': 10, 'uses': 2, 'games': 4, 'frequency': .5},
                                            {'id': 20, 'uses': 2, 'games': 4, 'frequency': .5}])
        self.assertEqual(data['pairs'], [{'ids': [10, 20], 'uses': 2, 'games': 4, 'frequency': .5}])

    def test_short_slots_are_missing_not_empty(self):
        data = build_insights([game(slots=[10, 0])])['hextech']
        self.assertEqual(data['known_slots'], 2)
        self.assertEqual(data['complete_games'], 0)

    def test_equal_adjacent_windows_sorted_after_eligibility(self):
        records = [game(i, win=i > 3) for i in (3, 1, 6, 2, 5, 4)]
        records += [game(7, eligible=False)]
        data = build_insights(records, window=20)['comparison']
        self.assertEqual(data['window'], 3)
        self.assertEqual(data['recent']['games'], data['previous']['games'])
        self.assertEqual(data['recent']['oldest_ms'], 4000)
        self.assertEqual(data['previous']['newest_ms'], 3000)
        self.assertEqual(data['delta']['win_rate'], 1)

    def test_window_limit_and_unknown_dates(self):
        records = [game(i) for i in range(1, 7)]
        records[0]['started_ms'] = None
        result = build_insights(records, window=2)['comparison']
        self.assertEqual(result['window'], 2)
        self.assertEqual(result['excluded_undated_games'], 1)
        self.assertEqual(result['previous']['oldest_ms'], 3000)
        self.assertEqual(build_insights([game()])['comparison']['window'], 0)
        self.assertIsNone(build_insights([])['comparison']['delta']['win_rate'])
        for invalid in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                build_insights([], invalid)

    def test_teammates_identified_by_identity_not_name(self):
        records = [game(1, win=False), game(2)]
        records[1]['participants'][1]['game_name'] = 'Renamed'
        records[1]['participants'][2]['game_name'] = 'Renamed'
        result = build_insights(records)['teammates']
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]['game_name'], 'Renamed')
        self.assertEqual(result[0]['games'], 2)
        self.assertEqual(result[0]['wins'], 1)
        self.assertEqual(result[0]['win_rate'], .5)
        self.assertNotIn('puuid', json.dumps(result))
        self.assertNotIn('player-1', json.dumps(result))
        self.assertEqual(len({row['player_ref'] for row in result}), 4)

    def test_missing_team_stat_does_not_produce_partial_team_ratio(self):
        record = game()
        record['participants'][1]['kills'] = None
        record['participants'].pop(4)
        row = build_insights([record])['champions'][0]
        self.assertEqual(row['samples']['kill_participation'], 0)
        self.assertEqual(row['samples']['damage_share'], 0)

    def test_tank_and_teammate_heal_metrics_have_individual_samples(self):
        first, second, missing = game(1), game(2), game(3)
        first['self'].update(taken=0, heal=0)
        second['self'].update(taken=600, heal=120)
        second['duration'] = 120
        missing['self'].update(taken=None, heal=None)
        excluded = game(4, eligible=False)
        excluded['self'].update(taken=9000, heal=9000)
        data = build_insights([first, second, missing, excluded])
        for row in (data['summary'], data['champions'][0]):
            self.assertEqual(row['taken'], 300)
            self.assertEqual(row['taken_per_minute'], 150)
            self.assertEqual(row['heal'], 60)
            self.assertEqual(row['heal_per_minute'], 30)
            for key in ('taken', 'taken_per_minute', 'heal', 'heal_per_minute'):
                self.assertEqual(row['samples'][key], 2)
        self.assertEqual(data['summary']['games'], 3)

    def test_raw_tank_heal_metrics_survive_missing_duration(self):
        record = game()
        record['self'].update(taken=120, heal=0)
        record['duration'] = None
        summary = build_insights([record])['summary']
        self.assertEqual(summary['taken'], 120)
        self.assertEqual(summary['heal'], 0)
        self.assertEqual(summary['samples']['taken'], 1)
        self.assertEqual(summary['samples']['heal'], 1)
        self.assertIsNone(summary['taken_per_minute'])
        self.assertIsNone(summary['heal_per_minute'])
        self.assertEqual(summary['samples']['taken_per_minute'], 0)
        self.assertEqual(summary['samples']['heal_per_minute'], 0)

    def test_highlights_totals_maximums_and_real_samples(self):
        first, second, missing, excluded = game(1), game(2), game(3), game(4, eligible=False)
        first['self'].update(double_kills=2, triple_kills=1, quadra_kills=0, penta_kills=0,
                             largest_multi_kill=3, largest_killing_spree=8)
        second['self'].update(double_kills=3, triple_kills=0, quadra_kills=1, penta_kills=1,
                              largest_multi_kill=5, largest_killing_spree=6)
        excluded['self'].update(double_kills=99, triple_kills=99, quadra_kills=99, penta_kills=99,
                                largest_multi_kill=99, largest_killing_spree=99)
        data = build_insights([first, second, missing, excluded])
        highlights = data['highlights']
        self.assertEqual(highlights['games'], 3)
        self.assertEqual(highlights['totals'], {'double_kills': 5, 'triple_kills': 1,
                                               'quadra_kills': 1, 'penta_kills': 1})
        self.assertEqual(highlights['games_with'], {'double_kills': 2, 'triple_kills': 1,
                                                   'quadra_kills': 1, 'penta_kills': 1})
        self.assertTrue(all(sample == 2 for sample in highlights['samples'].values()))
        self.assertEqual(highlights['largest_multi_kill'], 5)
        self.assertEqual(highlights['largest_killing_spree'], 8)
        for key, total in highlights['totals'].items():
            self.assertEqual(data['summary'][key], total)
            self.assertEqual(data['summary']['samples'][key], 2)
        self.assertEqual(data['champions'][0]['penta_kills'], 1)
        self.assertEqual(data['comparison']['recent']['penta_kills'], None)

    def test_highlights_zero_and_missing_remain_distinct(self):
        zero, missing = game(1), game(2)
        zero['self'].update(double_kills=0, triple_kills=0, quadra_kills=0, penta_kills=0,
                            largest_multi_kill=0, largest_killing_spree=0)
        only_missing = build_insights([missing])['highlights']
        for key, value in only_missing['totals'].items():
            self.assertIsNone(value)
            self.assertIsNone(only_missing['games_with'][key])
            self.assertEqual(only_missing['samples'][key], 0)
        self.assertIsNone(only_missing['largest_multi_kill'])
        data = build_insights([zero, missing])['highlights']
        for key, value in data['totals'].items():
            self.assertEqual(value, 0)
            self.assertEqual(data['games_with'][key], 0)
            self.assertEqual(data['samples'][key], 1)
        self.assertEqual(data['largest_multi_kill'], 0)
        self.assertEqual(data['largest_killing_spree'], 0)


if __name__ == '__main__':
    unittest.main()
