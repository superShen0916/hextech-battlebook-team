"""Personal archives must include independent games without contaminating owners."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from personal_profiles import attach_personal_profiles
from public_site import build_public_snapshot, _source_signature
from store import Store
from test_share_report import game


class PersonalProfileTests(unittest.TestCase):
    def setup_archive(self, directory):
        owner = [game(i) for i in range(1, 13)]
        independent = game(50)
        independent['participants'][0]['puuid'] = 'UNRELATED-SECRET'
        target = [copy.deepcopy(m) for m in owner[:10]] + [independent]
        for m in target:
            m['self'] = m['participants'][1]
        store = Store(Path(directory) / 'friend')
        store.register(SimpleNamespace(platform='TEST', account_key='TEST:ALLY-A',
                                      account={'puuid': 'ALLY-A', 'gameName': 'Ally A', 'tagLine': 'PRIVATE-TAG'}))
        for m in target:
            store.put('TEST:ALLY-A', m)
        store.discover('TEST:ALLY-A', ['TEST_999'])
        config = [{'id': 'friend', 'database': 'friend/mayhem.sqlite', 'expected_puuid': 'ALLY-A'}]
        (Path(directory) / 'public-profiles.json').write_text(json.dumps(config), encoding='utf-8')
        return owner, store

    def test_independent_games_union_cached_history_and_relation_ids_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, _ = self.setup_archive(directory)
            before = copy.deepcopy(owner)
            result = attach_personal_profiles(build_public_snapshot(owner), directory, owner)
            self.assertEqual(result['projection_version'], 4)
            friend = result['players'][0]
            self.assertEqual(friend['coverage']['saved'], 13)  # 12 cached + 1 independent; overlaps once
            self.assertEqual(friend['summary']['games'], 13)
            self.assertEqual(friend['coverage']['missing'], 1)
            self.assertEqual(len(result['personal']['recent']), 12)
            self.assertTrue(all(m['player']['champion_id'] == 22 for m in friend['recent']))
            teammate = next(p for p in friend['teammates'] if p['name'] == 'Player 1')
            self.assertEqual(len(teammate['match_ids']), 12)
            ids = {m['id'] for m in friend['recent']}
            self.assertTrue(set(teammate['match_ids']) < ids)
            serialized = json.dumps(result)
            for secret in ('ALLY-A', 'OWNER-SECRET', 'UNRELATED-SECRET', 'PRIVATE-TAG', 'puuid', 'match_key', 'account_key'):
                self.assertNotIn(secret, serialized)
            again = attach_personal_profiles(build_public_snapshot(owner), directory, list(reversed(owner)))
            self.assertEqual({m['id'] for m in again['players'][0]['recent']}, ids)
            self.assertEqual(owner, before)

    def test_wrong_identity_or_missing_archive_stops_instead_of_publishing_another_account(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, _ = self.setup_archive(directory)
            path = Path(directory) / 'public-profiles.json'
            data = json.loads(path.read_text())
            data[0]['expected_puuid'] = 'OTHER-ACCOUNT'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
                attach_personal_profiles(build_public_snapshot(owner), directory, owner)

    def test_watch_signature_includes_independent_archive_and_optional_config(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, store = self.setup_archive(directory)
            before = _source_signature(Path(directory))
            m = game(60); m['self'] = m['participants'][1]
            store.put('TEST:ALLY-A', m)
            self.assertNotEqual(before, _source_signature(Path(directory)))


if __name__ == '__main__':
    unittest.main()
