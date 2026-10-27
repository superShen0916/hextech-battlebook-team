import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('sync_version_intel', Path(__file__).resolve().parents[1] / 'scripts/sync_version_intel.py')
intel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intel)


class VersionIntelTests(unittest.TestCase):
    def fixture(self):
        meta = {'patch': '16.21', 'mode': 'normal', 'snapshot_at': '2026-10-22T17:33:16+08:00',
                'matches': {'valid': 1}, 'regions': ['sample'], 'window': {},
                'provisional_augments': {'999': {'source': 'PBE'}}}
        heroes = {'1': {'name': 'A', 'title': 'A', 'games': 5, 'wins': 2},
                  '2': {'name': 'B', 'title': 'B', 'games': 5, 'wins': 3}}
        pairs = {'1': {'10': {'games': 1, 'wins': 1}, '999': {'games': 9, 'wins': 8}},
                 '2': {'10': {'games': 2, 'wins': 0}}}
        augments = {'10': {'name': 'live', 'rarity': 'gold'}, '999': {'name': 'test', 'rarity': 'gold'}}
        return dict(zip(intel.FILES, (meta, heroes, pairs, augments)))

    def project(self, bundle, path='patches/16.21/normal'):
        return intel.project(bundle, {'patch': '16.21', 'path': path}, 7)

    def test_weighted_counts_and_pbe_isolation(self):
        data, details = self.project(self.fixture())
        self.assertEqual(len(data['augments']), 1)
        self.assertEqual(data['augments'][0]['games'], 3)
        self.assertAlmostEqual(data['augments'][0]['win_rate'], 1 / 3)
        self.assertEqual(details['1']['pairs'][1]['source'], 'pbe')
        self.assertEqual(details['1']['pairs'][0]['source'], 'live')

    def test_reject_mixed_patch_or_transition_dataset(self):
        bundle = self.fixture()
        bundle['meta.json']['patch'] = '16.20'
        with self.assertRaises(ValueError):
            self.project(bundle)
        with self.assertRaises(ValueError):
            self.project(self.fixture(), 'patches/16.21-pbe/normal')

    def test_reject_wrong_denominator_and_inconsistent_pair(self):
        bundle = self.fixture()
        bundle['heroes.json']['1']['games'] = 6
        with self.assertRaises(ValueError):
            self.project(bundle)
        bundle = self.fixture()
        bundle['hero_augments.json']['1']['10'] = {'games': 5, 'wins': 3}
        with self.assertRaises(ValueError):
            self.project(bundle)

    def test_reject_fabricated_rate(self):
        with self.assertRaises(ValueError):
            intel.counts({'games': 10, 'wins': 5, 'win_rate': .9})


if __name__ == '__main__':
    unittest.main()
