import importlib.util
import json
from pathlib import Path
import struct
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_assets', ROOT / 'scripts' / 'update_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class AssetTests(unittest.TestCase):
    def test_description_removes_markup_scripts_and_live_counters(self):
        value = '<scaleAD>获得@Power*100@%攻击力</scaleAD><br>已造成伤害：@f2@<script>alert(1)</script>'
        description, unresolved = assets.render_description(value, {'Power': 0.2})
        self.assertEqual(description, '获得20%攻击力')
        self.assertEqual(unresolved, [])

    def test_unknown_values_are_explicit_not_guessed(self):
        description, unresolved = assets.render_description('用@SpellName@命中@Unknown@次', {})
        self.assertIn('对应技能', description)
        self.assertIn('〔动态值〕', description)
        self.assertNotIn('@', description)
        self.assertEqual(unresolved, ['Unknown'])

    def test_png_crc_and_trailing_data_are_rejected(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00\xff')) + chunk(b'IEND', b'')
        self.assertTrue(assets.valid_png(png))
        self.assertFalse(assets.valid_png(png + b'<script>'))
        self.assertFalse(assets.valid_png(png[:-1] + b'X'))
        self.assertFalse(assets.valid_png(b'<svg onload="alert(1)"></svg>'))

    def test_bundled_assets_have_safe_paths_and_verified_images(self):
        for category in ('champions', 'items', 'augments'):
            dictionary = json.loads((ROOT / 'app' / 'static' / (category + '.json')).read_text(encoding='utf-8'))
            for identifier, entry in dictionary.items():
                with self.subTest(category=category, identifier=identifier):
                    self.assertIsInstance(entry.get('name'), str)
                    # Historical-only assets keep their original pinned patch.
                    manifest = json.loads((ROOT / 'app/static/assets.json').read_text(encoding='utf-8'))
                    self.assertRegex(entry['asset_patch'], r'^\d+\.\d+$')
                    self.assertLessEqual(tuple(map(int, entry['asset_patch'].split('.'))), tuple(map(int, manifest['patch'].split('.'))))
                    url = entry.get('icon_url')
                    if url:
                        self.assertEqual(url, f'/assets/{category}/{identifier}.png')
                        self.assertTrue(assets.valid_png((ROOT / 'app' / 'static' / 'icons' / category / (identifier + '.png')).read_bytes()))
                    if category == 'augments':
                        self.assertNotRegex(entry.get('description', ''), r'<[^>]+>|@[^@]+@|%i:')

    def test_missing_or_other_mode_effects_stay_empty(self):
        dictionary = json.loads((ROOT / 'app' / 'static' / 'augments.json').read_text(encoding='utf-8'))
        for identifier in ('2140', '2143'):
            self.assertEqual(dictionary[identifier]['description'], '')
        for identifier in ('1310', '1379'):
            self.assertTrue(dictionary[identifier]['description'])
            self.assertEqual(dictionary[identifier]['description_source'], 'https://game.gtimg.cn/images/lol/act/img/js/kiwi/kiwi_augments.json')
        # Same-name Arena Goliath has different values; the KIWI value is 35%.
        self.assertIn('35%', dictionary['1041']['description'])
        self.assertIn('15%', dictionary['1041']['description'])
        self.assertIn('攻击特效（On-Hit）', dictionary['1029']['description'])
        self.assertNotIn('已触发次数', dictionary['1029']['description'])


if __name__ == '__main__':
    unittest.main()
