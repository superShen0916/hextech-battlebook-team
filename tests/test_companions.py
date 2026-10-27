"""Synthetic companion tests: no live database, account access, or network."""
import copy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from companions import build_companions, companion_detail


def game(index, *, ally=True, eligible=True, name='Companion', focus_id='FRIEND-A', champion=22):
    players = []
    for pid in range(1, 11):
        identity = 'MAIN-PRIVATE' if pid == 1 else f'OTHER-{index}-{pid}'
        if pid == 2 if ally else pid == 6:
            identity = focus_id
        focus = identity == focus_id
        players.append({
            'participant_id': pid, 'puuid': identity, 'team_id': 100 if pid <= 5 else 200,
            'champion_id': champion if focus else pid, 'champion_name': f'Hero {champion if focus else pid}',
            'game_name': name if focus else f'Player {pid}', 'tag_line': 'TEST',
            'win': pid <= 5, 'kills': 8 if focus else 1, 'deaths': 2 if focus else 1,
            'assists': 4 if focus else 1, 'damage': 800 if focus else 100,
            'taken': 900 if focus else 100, 'heal': 0,
            'augment_slots': [300, 400, 0, 0, 0, 0] if focus else [100, 200, 0, 0, 0, 0],
            'augment_complete': True, 'penta_kills': 1 if focus else 0,
        })
    return {'match_key': f'TEST_{index}', 'queue_id': 2400, 'game_mode': 'KIWI',
            'patch': '16.20.1', 'started_ms': index * 86400000, 'duration': 120,
            'stats_eligible': eligible, 'augment_complete': True,
            'participants': players, 'self': players[0]}


class CompanionTests(unittest.TestCase):
    def test_automatic_threshold_counts_shared_but_metrics_only_eligible(self):
        records = [game(1), game(2), game(3, eligible=False)]
        roster = build_companions(records)
        self.assertEqual(len(roster), 1)
        person = roster[0]
        self.assertEqual(person['shared_games'], 3)
        self.assertEqual(person['eligible_games'], 2)
        self.assertEqual(person['wins'], 2)
        self.assertEqual(person['win_rate'], 1)
        self.assertEqual(build_companions(records[:2]), [])
        self.assertEqual(len(build_companions(records[:2], min_games=2)), 1)

    def test_names_do_not_merge_identities_and_rename_preserves_reference(self):
        records = [game(i, name='Same name') for i in (1, 2, 3)]
        records += [game(i, name='Same name', focus_id='FRIEND-B') for i in (4, 5, 6)]
        roster = build_companions(records)
        self.assertEqual(len(roster), 2)
        self.assertEqual(len({p['ref'] for p in roster}), 2)
        before = build_companions(records[:3])[0]['ref']
        records[2]['participants'][1]['game_name'] = 'New name'
        after = build_companions(list(reversed(records[:3])))[0]
        self.assertEqual(after['game_name'], 'New name')
        self.assertEqual(after['ref'], before)
        self.assertTrue(re.fullmatch('[0-9a-f]{24}', before))

    def test_roster_qualification_is_global_and_filters_use_companion_hero(self):
        records = [game(1, champion=11), game(2, champion=22), game(3, champion=22)]
        records[2]['patch'] = '16.21.1'
        person = build_companions(records)[0]
        detail = companion_detail(records, person['ref'], champion=22, patch='16.21')
        self.assertEqual(detail['companion']['shared_games'], 3)
        self.assertEqual(detail['shared_games'], 1)
        self.assertEqual(detail['recent'][0]['player']['champion_id'], 22)
        self.assertEqual({p['champion_id'] for p in detail['champion_options']}, {11, 22})
        self.assertEqual(detail['patch_options'], ['16.21', '16.20'])
        empty = companion_detail(records, person['ref'], champion=999)
        self.assertEqual(empty['recent'], [])
        self.assertEqual(empty['companion']['shared_games'], 3)
        self.assertIsNone(empty['insights']['summary']['kda'])

    def test_date_filter_does_not_requalify_roster(self):
        records = [game(i) for i in (1, 2, 10)]
        ref = build_companions(records)[0]['ref']
        with patch('companions._now_ms', return_value=10 * 86400000):
            detail = companion_detail(records, ref, days=1)
        self.assertEqual(detail['shared_games'], 1)
        self.assertEqual(detail['companion']['shared_games'], 3)
        self.assertEqual(detail['recent'][0]['match_key'], 'TEST_10')

    def test_enemy_appearance_and_other_modes_do_not_count(self):
        records = [game(1), game(2), game(3, ally=False)]
        self.assertEqual(build_companions(records), [])
        records += [game(4)]
        other_mode = game(5)
        other_mode['queue_id'] = 450
        records.append(other_mode)
        person = build_companions(records)[0]
        self.assertEqual(person['shared_games'], 3)
        detail = companion_detail(records, person['ref'])
        self.assertEqual([m['match_key'] for m in detail['recent']], ['TEST_4', 'TEST_2', 'TEST_1'])

    def test_companion_metrics_and_highlights_use_their_own_participant(self):
        records = [game(i) for i in (1, 2, 3)]
        person = build_companions(records)[0]
        self.assertEqual(person['summary']['kda'], 6)
        self.assertEqual(person['summary']['dpm'], 400)
        self.assertEqual(person['self_summary']['kda'], 2)
        detail = companion_detail(records, person['ref'])
        self.assertEqual(detail['insights']['highlights']['totals']['penta_kills'], 3)
        self.assertEqual(detail['insights']['hextech']['augments'][0]['id'], 300)
        self.assertEqual(detail['insights']['champions'][0]['champion_id'], 22)
        self.assertEqual(detail['recent'][0]['focus_participant_id'], 2)
        self.assertTrue(detail['recent'][0]['player']['is_focus'])
        self.assertFalse(detail['recent'][0]['player']['is_self'])
        self.assertTrue(detail['recent'][0]['participants'][0]['is_self'])

    def test_missing_and_zero_have_individual_denominators(self):
        records = [game(i) for i in (1, 2, 3)]
        records[0]['participants'][1].update(damage=0, heal=0, penta_kills=0)
        for record in records[1:]:
            record['participants'][1].update(damage=None, heal=None, penta_kills=None)
        summary = build_companions(records)[0]['summary']
        self.assertEqual(summary['dpm'], 0)
        self.assertEqual(summary['heal'], 0)
        self.assertEqual(summary['penta_kills'], 0)
        self.assertEqual(summary['samples']['dpm'], 1)
        self.assertEqual(summary['samples']['heal'], 1)
        self.assertEqual(summary['samples']['penta_kills'], 1)

    def test_account_scoped_refs_and_mixed_account_rejection(self):
        records = [game(i) for i in (1, 2, 3)]
        original = build_companions(records)[0]['ref']
        second = copy.deepcopy(records)
        for match in second:
            match['self']['puuid'] = 'SECOND-MAIN-PRIVATE'
        alternate = build_companions(second)[0]['ref']
        self.assertNotEqual(original, alternate)
        self.assertIsNone(companion_detail(second, original))
        with self.assertRaises(ValueError):
            build_companions(records + second)

    def test_duplicate_records_do_not_reach_threshold_and_input_is_unmodified(self):
        records = [game(i) for i in (1, 2)]
        self.assertEqual(build_companions(records + records), [])
        records.append(game(3))
        before = copy.deepcopy(records)
        roster = build_companions(records)
        detail = companion_detail(records, roster[0]['ref'])
        self.assertEqual(records, before)
        public = json.dumps({'companions': roster, 'detail': detail}, allow_nan=False)
        for value in ('puuid', 'MAIN-PRIVATE', 'FRIEND-A', 'OTHER-'):
            self.assertNotIn(value, public)
        self.assertIsNone(companion_detail(records, 'unknown-ref'))


if __name__ == '__main__':
    unittest.main()
