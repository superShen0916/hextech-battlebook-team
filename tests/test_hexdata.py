"""Stable identity, missing estimates, and public projection regressions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from hexdata import load_ratings, public_rating, rating_for
from public_site import build_public_snapshot, compact_public_snapshot, _source_signature
from companions import build_companions, companion_detail
from test_share_report import game


def estimate(score=2265):
    return {'status': 'estimated', 'score': score, 'top_percent': 9.4,
            'queried_at': '2026-10-21T12:27:00+08:00', 'matches_through': None}


class HexdataTests(unittest.TestCase):
    def test_same_name_and_rename_are_resolved_by_identity(self):
        ratings = {'a': estimate(), 'b': {'status': 'pending'}}
        self.assertEqual(rating_for({'puuid': 'a', 'game_name': 'Renamed'}, ratings)['score'], 2265)
        self.assertEqual(rating_for({'puuid': 'b', 'game_name': 'Renamed'}, ratings)['status'], 'pending')
        self.assertIsNone(rating_for({'puuid': 'b'}, ratings)['score'])
        self.assertEqual(rating_for({'puuid': 'unknown'}, ratings)['status'], 'not_queried')

    def test_invalid_estimates_never_become_zero_or_a_valid_score(self):
        for patch in [{'score': True}, {'score': -1}, {'top_percent': 101}, {'top_percent': float('nan')},
                      {'queried_at': '2026-10-21'}, {'score': '2265'}]:
            row = public_rating({**estimate(), **patch})
            self.assertEqual(row['status'], 'unavailable')
            self.assertIsNone(row['score'])
        self.assertEqual(public_rating(estimate(0))['score'], 0)

    def test_private_and_untrusted_source_fields_are_dropped(self):
        row = public_rating({**estimate(), 'puuid': 'SECRET', 'game_id': 'Name#Tag',
                             'password': 'SECRET', 'source_url': 'https://untrusted.example'})
        self.assertNotIn('SECRET', json.dumps(row))
        self.assertNotIn('Name#Tag', json.dumps(row))
        self.assertEqual(row['source_url'], 'https://hexdata.com.cn/matchmaking-position')

    def test_missing_and_corrupt_local_file_do_not_break_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_ratings(d), {})
            path = Path(d) / 'hexdata-ratings.json'
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(rating_for({'puuid': 'a'}, load_ratings(d))['status'], 'unavailable')
            before = _source_signature(Path(d))
            path.write_text(json.dumps({'schema_version': 1, 'ratings': {'a': estimate()}}), encoding='utf-8')
            self.assertNotEqual(before, _source_signature(Path(d)))
            self.assertEqual(load_ratings(d)['a']['score'], 2265)

    def test_personal_friend_and_friend_roster_export_keep_scores_with_correct_people(self):
        records = [game(i) for i in range(1, 21)]
        ratings = {'OWNER-SECRET': estimate(1415), 'ALLY-A': estimate()}
        snapshot = build_public_snapshot(records, ratings=ratings)
        self.assertEqual(snapshot['projection_version'], 3)
        self.assertEqual(snapshot['personal']['rating']['score'], 1415)
        friend = snapshot['companions'][0]
        self.assertEqual(friend['rating']['score'], 2265)
        self.assertEqual(friend['teammates'][0]['rating']['score'], 1415)
        self.assertNotIn('rating', friend['by_champion']['22'])
        self.assertEqual(compact_public_snapshot(snapshot), snapshot)
        for private in ('OWNER-SECRET', 'ALLY-A', 'puuid', 'tag_line', 'PRIVATE-TAG'):
            self.assertNotIn(private, json.dumps(snapshot))

    def test_friend_hero_filter_does_not_change_account_estimate(self):
        records = [game(i) for i in range(1, 11)]
        before = copy.deepcopy(records)
        ratings = {'ALLY-A': estimate()}
        friend = build_companions(records, ratings=ratings)[0]
        detail = companion_detail(records, friend['ref'], champion=999, ratings=ratings)
        self.assertEqual(detail['eligible_games'], 0)
        self.assertEqual(detail['rating']['score'], 2265)
        self.assertEqual(records, before)


if __name__ == '__main__':
    unittest.main()
