import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
import tencent_equipment as equipment


def response(**changes):
    body = {'dtstatdate': '20261031',
            'itemone_json': json.dumps({'2': {'itemone': '3031', 'showrate': 8403, 'winrate': 4813},
                                       '1': {'itemone': '6676', 'showrate': 9005, 'winrate': 4788}}),
            'itemcore_json': json.dumps({'1': {'itemcore': '6676&3031&3036', 'showrate': 1725, 'winrate': 4874}}),
            'itemshoes': '3009$0.4516$0.4766', 'itemout': '1036,2003$0.3$0.49',
            'itemover_rec': '1_3009,3031,6676_0.0614_0.4705'}
    body.update(changes)
    return {'code': 0, 'data': {'_fieldValues': {'unpredictable_key': json.dumps(body)}}}


class TencentEquipmentTests(unittest.TestCase):
    identity = {'name': '戏命师', 'title': '烬'}

    def test_rates_have_two_scales_and_source_rank_is_preserved(self):
        hero = equipment.project_hero(response(), '202', self.identity)
        self.assertEqual(hero['stats_date'], '2026-10-31')
        self.assertEqual(hero['items'][0]['items'], ['6676'])
        self.assertAlmostEqual(hero['items'][0]['pick_rate'], .9005)
        self.assertAlmostEqual(hero['items'][0]['win_rate'], .4788)
        self.assertAlmostEqual(hero['boots'][0]['pick_rate'], .4516)
        self.assertEqual(hero['core'][0]['items'], ['6676', '3031', '3036'])
        self.assertEqual(hero['full'][0]['items'], ['3009', '3031', '6676'])

    def test_reject_changed_envelopes_errors_invalid_dates_and_rates(self):
        invalid = [ {'code': 1}, {'code': 0, 'data': {'_fieldValues': {}}},
                    response(dtstatdate='20260230'), response(dtstatdate=None),
                    response(itemshoes='3009$1.5$0.5'), response(itemshoes='3009$nan$0.5'),
                    response(itemshoes='3009$0.5$inf'),
                    response(itemone_json='{"1":{"itemone":"6676","showrate":true,"winrate":5000}}'),
                    response(itemcore_json='{"1":{"itemcore":"../bad","showrate":1,"winrate":1}}') ]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises((ValueError, KeyError, TypeError)):
                equipment.project_hero(body, '202', self.identity)

    def test_explicit_no_data_is_preserved_as_unavailable(self):
        body = {'code': 0, 'data': {'_fieldValues': {'new_key': ''}}}
        hero = equipment.project_hero(body, '202', self.identity)
        self.assertFalse(hero['available'])
        self.assertIsNone(hero['stats_date'])

    def test_unknown_scope_stays_unknown_and_hero_dates_stay_separate(self):
        raw = {'retrieved_at': '2026-11-01T00:00:00Z',
               'heroes': {'202': response(), '157': response(dtstatdate='20261030')}}
        champions = {'202': self.identity, '157': {'name': '疾风剑豪', 'title': '亚索'}}
        data = equipment.project(raw, champions, {'6676': {'name': '收集者'}}, lambda iid: iid == '6676')
        self.assertIsNone(data['patch'])
        self.assertIsNone(data['sample_size'])
        self.assertIsNone(data['window'])
        self.assertIsNone(data['regions'])
        self.assertEqual(data['sample_scope'], 'undisclosed')
        self.assertEqual(data['stats_date_min'], '2026-10-30')
        self.assertEqual(data['stats_date_max'], '2026-10-31')
        self.assertEqual(data['items']['6676']['icon_url'], '/assets/items/6676.png')
        self.assertIsNone(data['items']['3031']['icon_url'])
        self.assertEqual(len(data['snapshot_id']), 64)
        incomplete = copy.deepcopy(raw)
        del incomplete['heroes']['157']
        with self.assertRaises(ValueError):
            equipment.project(incomplete, champions, {}, lambda _: False)

    def test_failed_refresh_never_replaces_previous_snapshot_or_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            cache, output, static = [base / name for name in ('cache', 'output', 'static')]
            for path in (cache, output, static):
                path.mkdir()
            (static / 'champions.json').write_text(json.dumps({'202': self.identity}), encoding='utf-8')
            (static / 'items.json').write_text('{}', encoding='utf-8')
            for path in (cache, output):
                (path / 'tencent-equipment.json').write_text('previous', encoding='utf-8')
            with patch.object(equipment, 'fetch', return_value=response(dtstatdate='invalid')):
                with self.assertRaises(ValueError):
                    equipment.refresh(cache, output, static, base)
            for path in (cache, output):
                self.assertEqual((path / 'tencent-equipment.json').read_text(encoding='utf-8'), 'previous')


if __name__ == '__main__':
    unittest.main()
