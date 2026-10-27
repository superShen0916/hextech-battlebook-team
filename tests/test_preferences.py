"""Final-holdings counts and hero/person scopes, without live data."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from insights import build_insights
from companions import build_companions, companion_detail
from test_insights import game
from test_companions import game as companion_game


class PreferencesTests(unittest.TestCase):
    def test_deduplicates_per_match_and_excludes_trinket_slot(self):
        first = game(1, slots=[10, 10, 20, 0, 0, 0])
        first['self']['items'] = [3031, 3031, 3006, 0, 0, 0, 3340]
        second = game(2, slots=[10, 30, 40, 0, 0, 0])
        second['self']['items'] = [3031, 1001, 0, 0, 0, 0, 2052]
        result = build_insights([first, second])['preferences']
        self.assertEqual(result['augments']['top3'], [
            {'id': 10, 'uses': 2, 'games': 2, 'frequency': 1},
            {'id': 20, 'uses': 1, 'games': 2, 'frequency': .5},
            {'id': 30, 'uses': 1, 'games': 2, 'frequency': .5}])
        self.assertEqual([r['id'] for r in result['items']['top3']], [3031, 1001, 3006])
        self.assertEqual(result['items']['top3'][0]['uses'], 2)
        self.assertNotIn(3340, [r['id'] for r in result['items']['top3']])
        self.assertNotIn(2052, [r['id'] for r in result['items']['top3']])

    def test_unknown_and_zero_have_distinct_coverage_and_use_all_games_denominator(self):
        known = game(1, slots=[10, 0, 0, 0, 0, 0])
        known['self']['items'] = [3031, 0, 0, 0, 0, 0, 0]
        empty = game(2, slots=[0] * 6)
        empty['self']['items'] = [0] * 7
        missing = game(3, slots=[None] * 6)
        result = build_insights([known, empty, missing])['preferences']
        for field in ('items', 'augments'):
            self.assertEqual(result[field]['observed_games'], 2)
            self.assertEqual(result[field]['complete_games'], 2)
            self.assertEqual(result[field]['missing_slot_games'], 1)
            self.assertAlmostEqual(result[field]['top3'][0]['frequency'], 1/3)
        self.assertEqual(build_insights([empty])['preferences']['items']['top3'], [])
        self.assertEqual(build_insights([missing])['preferences']['items']['observed_games'], 0)

    def test_hero_and_eligibility_scope_are_independent(self):
        records = [game(1, champion=1, slots=[10]*6), game(2, champion=1, slots=[10]*6),
                   game(3, champion=2, slots=[20]*6), game(4, champion=2, slots=[20]*6),
                   game(5, champion=1, eligible=False, slots=[99]*6)]
        for m in records:
            m['self']['items'] = [1000 + m['self']['champion_id']] * 6 + [3340]
        before = copy.deepcopy(records)
        data = build_insights(records)
        self.assertEqual(data['preferences']['games'], 4)
        self.assertEqual([r['id'] for r in data['preferences']['augments']['top3']], [10, 20])
        for hero in data['champions']:
            expected = 10 if hero['champion_id'] == 1 else 20
            self.assertEqual(hero['preferences']['games'], 2)
            self.assertEqual(hero['preferences']['augments']['top3'][0]['id'], expected)
            self.assertEqual(hero['preferences']['items']['top3'][0]['id'], 1000 + hero['champion_id'])
        self.assertEqual(records, before)

    def test_invalid_slots_do_not_turn_into_ids_or_complete_samples(self):
        m = game(slots=[True, -1, '12', 1.5, None, 900000])
        m['self']['items'] = [None, -1, True, '3031', 2.5, 900001, 999999]
        data = build_insights([m])['preferences']
        self.assertEqual(data['augments']['top3'][0]['id'], 900000)
        self.assertEqual(data['items']['top3'][0]['id'], 900001)
        self.assertEqual(data['items']['known_slots'], 1)
        self.assertEqual(data['augments']['complete_games'], 0)
        json.dumps(data, allow_nan=False)

    def test_empty_and_short_inventory_are_missing_not_known_empty(self):
        self.assertEqual(build_insights([])['preferences']['items']['top3'], [])
        m = game(slots=[10])
        m['self']['items'] = [3031]
        data = build_insights([m])['preferences']
        self.assertEqual(data['items']['known_slots'], 1)
        self.assertEqual(data['items']['complete_games'], 0)
        self.assertEqual(data['items']['observed_games'], 1)

    def test_companion_and_hero_filter_use_companions_own_holdings(self):
        records = [companion_game(1, champion=11), companion_game(2, champion=22), companion_game(3, champion=22)]
        for i,m in enumerate(records):
            m['participants'][0]['items'] = [111] * 6 + [3340]
            m['participants'][1]['items'] = [222 if i == 0 else 333] * 6 + [3340]
        ref = build_companions(records)[0]['ref']
        detail = companion_detail(records, ref)
        self.assertEqual([r['id'] for r in detail['insights']['preferences']['items']['top3']], [333, 222])
        self.assertEqual([r['id'] for r in detail['insights']['preferences']['augments']['top3']], [300, 400])
        filtered = companion_detail(records, ref, champion=11)
        self.assertEqual(filtered['insights']['preferences']['games'], 1)
        self.assertEqual(filtered['insights']['preferences']['items']['top3'][0]['id'], 222)
        self.assertEqual(filtered['insights']['champions'][0]['preferences']['items']['top3'][0]['id'], 222)


if __name__ == '__main__':
    unittest.main()
