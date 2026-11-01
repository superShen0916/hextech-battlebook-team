import copy
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
import tencent_equipment as equipment
import sync_version_intel as importer


def response(hero_id='202', **changes):
    body = {'dtstatdate': '20261031',
            'itemone_json': json.dumps({'2': {'itemone': '3031', 'showrate': 8403, 'winrate': 4813},
                                       '1': {'itemone': '6676', 'showrate': 9005, 'winrate': 4788}}),
            'itemcore_json': json.dumps({'1': {'itemcore': '6676&3031&3036', 'showrate': 1725, 'winrate': 4874}}),
            'itemshoes': '3009$0.4516$0.4766', 'itemout': '1036,2003$0.3$0.49',
            'itemover_rec': '1_3009,3031,6676_0.0614_0.4705',
            'augment_json_irank': f'255:1|{hero_id}|1007|255|0.14|S&kSilver:1|{hero_id}|1007|kSilver|0.14|A&kGold:&kPrismatic:'}
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

    def test_augment_projection_keeps_both_source_tiers_without_inventing_win_rates(self):
        raw = {'retrieved_at': '2026-11-01T00:00:00Z', 'heroes': {'202': response()}}
        gear = equipment.project(raw, {'202': self.identity}, {}, lambda _: False)
        data = equipment.project_augments(raw, gear, {'1007': {'name': '测试海克斯', 'rarity': 'gold'}}, lambda _: False)
        row = data['heroes'][0]['augments'][0]
        self.assertIsNone(data['win_rate'])
        self.assertIsNone(data['sample_size'])
        self.assertEqual(row['tier'], 'S')
        self.assertEqual(row['rarity_tier'], 'A')
        self.assertEqual(row['rarity'], 'silver')  # Source classification, not catalog override.
        self.assertEqual(row['pick_rate'], .14)
        for field in ('games', 'wins', 'win_rate'):
            self.assertNotIn(field, row)

    def test_augment_projection_rejects_missing_cross_hero_and_inconsistent_rows(self):
        values = [None, '255:1|157|1007|255|0.14|S&kSilver:&kGold:&kPrismatic:',
                  '255:1|202|1007|255|0.14|S&kSilver:1|202|1007|kSilver|0.15|A&kGold:&kPrismatic:',
                  '255:1|202|1007|255|0.14|S&kSilver:&kGold:&kPrismatic:']
        for value in values:
            raw = {'retrieved_at': '2026-11-01T00:00:00Z', 'heroes': {'202': response(augment_json_irank=value)}}
            gear = equipment.project(raw, {'202': self.identity}, {}, lambda _: False)
            with self.subTest(value=value), self.assertRaises(ValueError):
                equipment.project_augments(raw, gear, {}, lambda _: False)

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

    def test_missing_or_falsey_fields_cannot_erase_valid_groups(self):
        for key in ('itemone_json', 'itemcore_json', 'itemshoes', 'itemout', 'itemover_rec'):
            for value in (None, False, 0, [], 'missing'):
                body = response()
                source = json.loads(body['data']['_fieldValues']['unpredictable_key'])
                if value == 'missing':
                    del source[key]
                else:
                    source[key] = value
                body['data']['_fieldValues']['unpredictable_key'] = json.dumps(source)
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    equipment.project_hero(body, '202', self.identity)
        for data in (None, [], {'_fieldValues': {'a': None}}, {'_fieldValues': {'a': {}}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                equipment.project_hero({'code': 0, 'data': data}, '202', self.identity)

    def test_fetch_rejects_redirects_and_both_size_limits_and_reads_gzip(self):
        class Reply(io.BytesIO):
            def __init__(self, body, url=None, compressed=False):
                super().__init__(body)
                self.url = url or equipment.SOURCE + '?championid=202'
                self.headers = {'Content-Encoding': 'gzip'} if compressed else {}
        cases = [(Reply(b'{}', url='https://other.example/'), 'unexpected_equipment_redirect'),
                 (Reply(b'x' * 65), 'equipment_response_too_large'),
                 (Reply(gzip.compress(b'x' * 65), compressed=True), 'equipment_response_too_large')]
        for reply, error in cases:
            with self.subTest(error=error), patch.object(equipment, 'LIMIT', 64), \
                 patch('urllib.request.urlopen', return_value=reply), self.assertRaisesRegex(ValueError, error):
                equipment.fetch('202')
        with patch('urllib.request.urlopen', return_value=Reply(gzip.compress(b'{"code":0}'), compressed=True)):
            self.assertEqual(equipment.fetch('202'), {'code': 0})

    def test_transport_errors_retry_once_without_real_network_or_wait(self):
        for error in (OSError('offline'), urllib.error.URLError('offline')):
            reply = io.BytesIO(b'{"code":0}')
            reply.url, reply.headers = equipment.SOURCE + '?championid=202', {}
            with self.subTest(error=error), patch('urllib.request.urlopen', side_effect=[error, reply]) as call, \
                 patch.object(equipment.time, 'sleep') as sleep:
                self.assertEqual(equipment.fetch('202'), {'code': 0})
                self.assertEqual(call.call_count, 2)
                sleep.assert_called_once_with(1)
        with patch('urllib.request.urlopen', side_effect=OSError('offline')) as call, \
             patch.object(equipment.time, 'sleep'), self.assertRaises(OSError):
            equipment.fetch('202')
        self.assertEqual(call.call_count, 2)

    def test_fresh_equipment_entry_can_create_and_acquire_its_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            args = ['sync_version_intel.py', '--equipment-only', '--cache-dir', str(base / 'cache'),
                    '--output-dir', str(base / 'public/api/version-intel')]
            with patch.object(importer, 'ROOT', base), patch.object(sys, 'argv', args), \
                 patch.object(equipment, 'refresh', return_value={'ok': True}) as refresh, \
                 patch('sys.stdout', new=io.StringIO()):
                importer.main()
            refresh.assert_called_once()
            self.assertTrue((base / 'work/build/release.lock').is_file())

    def test_offline_cache_rebuild_never_requests_network_and_rejects_invalid_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            cache, output, static = [base / name for name in ('cache', 'output', 'static')]
            for path in (cache, output, static):
                path.mkdir()
            (static / 'champions.json').write_text(json.dumps({'202': self.identity}), encoding='utf-8')
            (static / 'items.json').write_text('{}', encoding='utf-8')
            (static / 'augments.json').write_text('{}', encoding='utf-8')
            raw = {'retrieved_at': '2026-11-01T00:00:00Z', 'heroes': {'202': response()}}
            cached = cache / 'tencent-equipment.json'
            cached.write_text(json.dumps(raw), encoding='utf-8')
            original = cached.read_bytes()
            with patch.object(equipment, 'fetch', side_effect=AssertionError('network forbidden')):
                result = equipment.refresh(cache, output, static, base, offline=True)
            self.assertTrue(result['ok'])
            self.assertEqual(cached.read_bytes(), original)
            published = (output / 'tencent-equipment.json').read_bytes()
            self.assertEqual(json.loads(published)['heroes'][0]['stats_date'], '2026-10-31')
            raw['heroes']['202'] = response(itemcore_json=None)
            cached.write_text(json.dumps(raw), encoding='utf-8')
            with patch.object(equipment, 'fetch', side_effect=AssertionError('network forbidden')), self.assertRaises(ValueError):
                equipment.refresh(cache, output, static, base, offline=True)
            self.assertEqual((output / 'tencent-equipment.json').read_bytes(), published)

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
            (static / 'augments.json').write_text('{}', encoding='utf-8')
            for path in (cache, output):
                (path / 'tencent-equipment.json').write_text('previous', encoding='utf-8')
            with patch.object(equipment, 'fetch', return_value=response(dtstatdate='invalid')):
                with self.assertRaises(ValueError):
                    equipment.refresh(cache, output, static, base)
            for path in (cache, output):
                self.assertEqual((path / 'tencent-equipment.json').read_text(encoding='utf-8'), 'previous')


if __name__ == '__main__':
    unittest.main()
