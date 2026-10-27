"""排位下界：只投影白名单字段，缺失不臆造，注入不碰其它字段。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_ranked_bounds import build
from inject_ranked_bounds import inject, load_bounds, public_queue, public_rank


def report_player(puuid, name, solo=None, flex=None):
    return {'name': name, 'puuid': puuid, 'ranked_checked_at': '2026-10-28T02:36:18+08:00',
            'queues': {'RANKED_SOLO_5x5': solo or {}, 'RANKED_FLEX_SR': flex or {}}}


class BuildBoundTests(unittest.TestCase):
    def test_only_site_players_and_lower_bounds_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'report.json'
            source.write_text(json.dumps({'players': [
                report_player('A', '甲', {'current': {'display': '翡翠 IV'}, 'current_lp': 66,
                                          'known_achieved_lower_bound': {'display': '翡翠 IV', 'tier': 'EMERALD',
                                                                        'source': 'ranked.highest'}}),
                report_player('B', '乙'),
                report_player('C', '丙'),
            ]}), encoding='utf-8')
            profiles = directory / 'public-profiles.json'
            profiles.write_text(json.dumps([{'id': 'a', 'expected_puuid': 'A'},
                                            {'id': 'b', 'expected_puuid': 'B'}]), encoding='utf-8')
            target = directory / 'bounds.json'
            result = build(source, profiles, target, checked_at='2026-10-28T03:00:00+08:00')
            self.assertEqual((result['players'], result['solo_lower_bound']), (2, 1))
            self.assertEqual(result['not_on_site'], ['丙'])
            data = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(sorted(data['players']), ['a', 'b'])
            self.assertEqual(data['players']['a']['solo']['lower_bound'], '翡翠 IV')
            self.assertIsNone(data['players']['b']['solo']['lower_bound'])
            self.assertNotIn('puuid', target.read_text(encoding='utf-8'))

    def test_unchanged_input_keeps_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'report.json'
            source.write_text(json.dumps({'players': [report_player('A', '甲')]}), encoding='utf-8')
            profiles = directory / 'public-profiles.json'
            profiles.write_text(json.dumps([{'id': 'a', 'expected_puuid': 'A'}]), encoding='utf-8')
            target = directory / 'bounds.json'
            build(source, profiles, target, checked_at='2026-10-28T03:00:00+08:00')
            first = target.stat().st_mtime_ns
            build(source, profiles, target, checked_at='2026-10-28T03:00:00+08:00')
            self.assertEqual(target.stat().st_mtime_ns, first)


class PublicProjectionTests(unittest.TestCase):
    def test_empty_queue_is_dropped_and_unknown_values_become_null(self):
        # 输入是 build_ranked_bounds 归一化后的结构：段位已经是显示字符串。
        self.assertIsNone(public_queue({'current': None, 'lower_bound': None}))
        self.assertIsNone(public_rank({'checked_at': '2026-10-28', 'solo': {}, 'flex': {}}))
        self.assertEqual(public_queue({'current': '白银 II', 'current_lp': 5,
                                       'lower_bound': '白银 II', 'lower_bound_tier': 'SILVER',
                                       'lower_bound_source': 'ranked.current'}),
                         {'current': '白银 II', 'lp': 5, 'at_least': '白银 II', 'tier': 'SILVER',
                          'basis': 'ranked.current'})

    def test_out_of_contract_values_are_rejected(self):
        queue = public_queue({'current': 'x' * 40, 'current_lp': 4000,
                              'known_achieved_lower_bound': {'display': '翡翠', 'tier': 'MYTHIC'}})
        self.assertEqual(len(queue['current']), 24)
        self.assertIsNone(queue['lp'])
        self.assertIsNone(queue['tier'])
        self.assertIsNone(public_rank({'checked_at': 'yesterday', 'solo': queue})['checked_at'])


class InjectTests(unittest.TestCase):
    def test_missing_bounds_file_is_skipped_not_fatal(self):
        # 团队仓库和 CI 拿到的源码里没有这份调研产物：缺文件要能继续构建。
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_bounds(Path(directory) / 'absent.json'), {})
            snapshot = Path(directory) / 'snapshot.full.json'
            snapshot.write_text(json.dumps({'players': [{'id': 'a', 'rating': {'score': 1},
                                                         'rank': {'stale': True}}]}), encoding='utf-8')
            self.assertEqual(inject(snapshot, load_bounds(Path(directory) / 'absent.json')),
                             {'injected': 0, 'players': 1, 'without_rank': ['a']})
            self.assertNotIn('rank', json.loads(snapshot.read_text(encoding='utf-8'))['players'][0])

    def test_injects_only_rank_and_clears_stale_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'snapshot.full.json'
            snapshot.write_text(json.dumps({'players': [
                {'id': 'a', 'name': '甲', 'rating': {'score': 1}, 'rank': {'stale': True}},
                {'id': 'b', 'name': '乙', 'rating': {'score': 2}},
            ]}), encoding='utf-8')
            players = {'a': {'checked_at': '2026-10-28', 'solo': {'current': '钻石 III', 'current_lp': 24,
                                                                  'lower_bound': '钻石 III',
                                                                  'lower_bound_tier': 'DIAMOND',
                                                                  'lower_bound_source': 'ranked.current'}},
                       'b': {'checked_at': '2026-10-28', 'solo': {}, 'flex': {}}}
            result = inject(snapshot, players)
            self.assertEqual((result['injected'], result['without_rank']), (1, ['b']))
            data = json.loads(snapshot.read_text(encoding='utf-8'))
            self.assertEqual(data['players'][0]['rank']['solo']['at_least'], '钻石 III')
            self.assertEqual(data['players'][0]['rating'], {'score': 1})
            self.assertNotIn('rank', data['players'][1])


if __name__ == '__main__':
    unittest.main()
