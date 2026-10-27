"""Timeline presentation regression tests using a temporary synthetic database."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import normalize
from review import timeline_review
from store import Store


MATCH_KEY = 'TEST_1000001'


def source(pid=1):
    return SimpleNamespace(platform='TEST', account_key=f'TEST:PRIVATE-PUUID-{pid}',
                           account={'puuid': f'PRIVATE-PUUID-{pid}',
                                    'gameName': f'Player {pid}', 'tagLine': 'TEST'})


def match():
    players = []
    for pid in range(1, 11):
        player = {'participantId': pid, 'puuid': f'PRIVATE-PUUID-{pid}',
                  'teamId': 100 if pid <= 5 else 200,
                  'championId': pid, 'championName': f'Hero {pid}',
                  'riotIdGameName': f'Player {pid}', 'riotIdTagline': 'PRIVATE-TAG',
                  'kills': 1, 'deaths': 1, 'assists': 1, 'win': pid <= 5,
                  'totalDamageDealtToChampions': 100,
                  'unknownPrivateField': 'RAW-MATCH-SECRET'}
        player.update({f'playerAugment{slot}': 0 for slot in range(1, 7)})
        players.append(player)
    return {'platformId': 'TEST', 'gameId': 1000001, 'queueId': 2400,
            'gameMode': 'KIWI', 'gameVersion': '16.20.1', 'gameCreation': 1000,
            'gameDuration': 600, 'endOfGameResult': 'GameComplete', 'participants': players}


def frame(timestamp=0, team100=100, team200=100, events=None):
    return {'timestamp': timestamp, 'unknownFrameField': 'RAW-FRAME-SECRET',
            'participantFrames': {
                str(pid): {'participantId': pid, 'totalGold': team100 if pid <= 5 else team200,
                           'currentGold': 0, 'level': 0, 'xp': 0, 'minionsKilled': 0,
                           'damageStats': {'totalDamageDoneToChampions': 0,
                                           'totalDamageTaken': 0},
                           'unknownProgressField': 'RAW-PROGRESS-SECRET'}
                for pid in range(1, 11)},
            'events': events or []}


class TimelineReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.current_source = source()
        self.store.register(self.current_source)
        self.store.put(self.current_source.account_key,
                       normalize(match(), self.current_source.account['puuid']))

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, frames):
        self.store.put_timeline(MATCH_KEY, 'synthetic-test', {'frames': frames,
                                                           'unknownRoot': 'RAW-ROOT-SECRET'})

    def test_account_isolation_even_if_timeline_exists(self):
        self.save([frame()])
        self.store.register(source(6))
        self.assertIsNone(timeline_review(self.store, MATCH_KEY))
        self.assertIsNone(timeline_review(self.store, 'TEST_9999999'))
        self.store.set('active_account', None)
        self.assertIsNone(timeline_review(self.store, MATCH_KEY))

    def test_missing_timeline_is_distinct_from_collected_without_events(self):
        missing = timeline_review(self.store, MATCH_KEY)
        self.assertIs(missing['available'], False)
        self.assertEqual(missing['reason'], 'timeline_not_collected')
        self.assertEqual(missing['frames'], [])
        self.assertEqual(missing['event_count'], 0)
        self.save([frame()])
        collected = timeline_review(self.store, MATCH_KEY)
        self.assertIs(collected['available'], True)
        self.assertNotIn('reason', collected)
        self.assertEqual(len(collected['frames']), 1)
        self.assertEqual(collected['events'], [])

    def test_team200_gold_diff_uses_self_team_perspective(self):
        second = source(6)
        self.store.register(second)
        self.store.put(second.account_key, normalize(match(), second.account['puuid']))
        self.save([frame(60000, team100=100, team200=200),
                   frame(120000, team100=300, team200=200)])
        result = timeline_review(self.store, MATCH_KEY)
        self.assertEqual(result['self_id'], 6)
        self.assertEqual(result['self_team_id'], 200)
        self.assertEqual([f['gold_diff'] for f in result['frames']], [500, -500])

    def test_one_missing_team_gold_is_not_treated_as_zero(self):
        incomplete = frame()
        del incomplete['participantFrames']['5']['totalGold']
        explicit_missing = frame(60000)
        explicit_missing['participantFrames']['6']['totalGold'] = None
        self.save([incomplete, explicit_missing])
        first, second = timeline_review(self.store, MATCH_KEY)['frames']
        self.assertIsNone(first['team_100_gold'])
        self.assertEqual(first['team_200_gold'], 500)
        self.assertIsNone(first['gold_diff'])
        self.assertEqual(second['team_100_gold'], 500)
        self.assertIsNone(second['team_200_gold'])
        self.assertIsNone(second['gold_diff'])

    def test_real_zero_frame_metrics_are_valid(self):
        self.save([frame(team100=0, team200=0)])
        result = timeline_review(self.store, MATCH_KEY)['frames'][0]
        for key in ('timestamp_ms', 'gold', 'current_gold', 'level', 'xp', 'minions',
                    'damage', 'taken', 'team_100_gold', 'team_200_gold', 'gold_diff'):
            self.assertEqual(result[key], 0, key)

    def test_missing_self_metrics_stay_none(self):
        missing = frame()
        missing['participantFrames']['1'] = {}
        self.save([missing])
        result = timeline_review(self.store, MATCH_KEY)['frames'][0]
        for key in ('gold', 'current_gold', 'level', 'xp', 'minions', 'damage', 'taken'):
            self.assertIsNone(result[key], key)

    def test_events_and_frames_sort_and_mark_self_involvement(self):
        self.save([
            frame(120000, events=[{'type': 'CHAMPION_KILL', 'timestamp': 110000,
                                   'killerId': 2, 'victimId': 6,
                                   'assistingParticipantIds': [1, 999, '2', None]},
                                  {'type': 'LEVEL_UP', 'timestamp': 100000,
                                   'participantId': 2, 'level': 4}]),
            frame(0, events=[{'type': 'ITEM_PURCHASED', 'timestamp': 0,
                              'participantId': 1, 'itemId': 1001}]),
        ])
        result = timeline_review(self.store, MATCH_KEY)
        self.assertEqual([f['timestamp_ms'] for f in result['frames']], [0, 120000])
        self.assertEqual([e['timestamp_ms'] for e in result['events']], [0, 100000, 110000])
        self.assertEqual([e['self_related'] for e in result['events']], [True, False, True])
        self.assertEqual(result['events'][2]['assistingParticipantIds'], [1])
        self.assertEqual(result['event_count'], 3)

    def test_unknown_fields_identities_and_unknown_events_are_not_exposed(self):
        self.save([frame(events=[
            {'type': 'CHAMPION_KILL', 'timestamp': 4, 'killerId': 1, 'victimId': 6,
             'puuid': 'EVENT-PRIVATE-PUUID', 'unknownEventField': 'RAW-EVENT-SECRET'},
            {'type': 'UNVERIFIED_AUGMENT_PICK', 'timestamp': 1, 'rawChoiceOrder': [1, 2]},
        ])])
        result = timeline_review(self.store, MATCH_KEY)
        text = json.dumps(result, allow_nan=False)
        for marker in ('PUUID', 'PRIVATE-TAG', 'RAW-', 'unknown', 'rawChoiceOrder',
                       'UNVERIFIED_AUGMENT_PICK'):
            self.assertNotIn(marker, text)
        self.assertEqual(result['event_count'], 1)
        self.assertEqual(set(result['participants'][0]),
                         {'participant_id', 'team_id', 'champion_id', 'champion_name', 'game_name'})

    def test_invalid_numbers_are_missing_and_invalid_events_are_skipped(self):
        invalid = frame(events=[{'type': 'CHAMPION_KILL', 'timestamp': -1},
                                {'type': 'GAME_END', 'timestamp': None}])
        invalid['participantFrames']['1'].update(totalGold=-1, currentGold=True, xp='0')
        self.save([invalid, {'timestamp': -10, 'events': []}])
        result = timeline_review(self.store, MATCH_KEY)
        self.assertEqual(len(result['frames']), 1)
        for key in ('gold', 'current_gold', 'xp', 'team_100_gold', 'gold_diff'):
            self.assertIsNone(result['frames'][0][key], key)
        self.assertEqual(result['event_count'], 0)


if __name__ == '__main__':
    unittest.main()
