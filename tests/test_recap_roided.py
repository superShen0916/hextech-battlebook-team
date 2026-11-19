"""「本周最胡」进高光回顾索引：只认已建档名册、只看本周、无候选为 null。"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
from build_recaps import match_details, night_key, recap_index, recap_rows, week_roided
from haido.rating_lp import week_start_ms

TZ = timezone(timedelta(hours=8))
# 2026-11-17 周二中午：北京时间的自然周从 11-16 周一 00:00 开始，和 haido 周分同一刀。
AS_OF = int(datetime(2026, 11, 17, 12, tzinfo=TZ).timestamp() * 1000)
START = week_start_ms(AS_OF)

ROSTER = ('a', 'b', 'c', 'd', 'e')


def player(pid, damage, team=100, win=True):
    return {'profile_id': pid, 'team': team, 'win': win, 'damage': damage,
            'champion_id': 1, 'kills': 1, 'deaths': 2, 'assists': 3}


def build(ids, matches):
    """把合成明细写进临时目录，跑一遍 build_recaps 的行、本周最胡与索引组装。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for mid, started, players in matches:
            (root / (mid + '.json')).write_text(
                json.dumps({'id': mid, 'started_ms': started, 'duration': 1200, 'players': players}),
                encoding='utf-8')
        recent = [{'id': mid, 'stats_eligible': True} for mid, _, _ in matches]
        snapshot = {'build_id': 'test', 'players': [
            {'id': pid, 'name': pid, 'recent': recent} for pid in ids]}
        details = match_details(snapshot, match_dir=root)
        rows = recap_rows(snapshot, match_dir=root, details=details)
        pick = week_roided(snapshot, details, AS_OF)
        nights = {}
        for row in rows:
            key = night_key(row['started_ms'])
            if key:
                nights.setdefault(key, []).append(row)
        return rows, pick, recap_index(snapshot, nights, rows, pick)


class RecapRoidedTests(unittest.TestCase):
    def test_index_carries_roided_list_and_only_picks_the_roster(self):
        # 路人 x 一局打了 500，占比 79%，比任何已建档玩家都高；只因为他不在名册里才不能进榜。
        team = [player('a', 100), player('b', 10), player('c', 10), player('d', 10), player('x', 500)]
        rows, picks, index = build(ROSTER, [('m1', START + 3_600_000, team)])
        self.assertTrue(rows, '已建档的 a—d 同队应产生一条回顾行')
        self.assertIsInstance(index['roided'], list)
        top = index['roided'][0]
        self.assertEqual(top['profile_id'], 'a')
        self.assertAlmostEqual(top['damage_share'], 100 / 630)
        self.assertEqual(top['match_id'], 'm1')
        self.assertEqual(top['match_key'], 'm1')
        self.assertEqual(picks, index['roided'])
        self.assertNotIn('x', [p['profile_id'] for r in rows for p in r['members']])

    def test_top_three_are_ranked_and_capped(self):
        # 四局不同占比：只取前三条，按占比从高到低；共用的 _rank_key 保证同分可比。
        games = [
            ('low', START + 1000, [player('a', 30), player('b', 30), player('c', 30), player('d', 30), player('e', 30)]),
            ('high', START + 2000, [player('a', 400), player('b', 25), player('c', 25), player('d', 25), player('e', 25)]),
            ('mid', START + 3000, [player('a', 100), player('b', 50), player('c', 50), player('d', 50), player('e', 50)]),
            ('best', START + 4000, [player('e', 700), player('a', 25), player('b', 25), player('c', 25), player('d', 25)]),
        ]
        _, picks, index = build(ROSTER, games)
        self.assertEqual([p['match_id'] for p in picks], ['best', 'high', 'mid'])
        self.assertEqual([p['match_id'] for p in index['roided']], ['best', 'high', 'mid'])
        self.assertEqual(len({p['match_id'] for p in picks}), 3, '三条必须指向三份不同战报')
        self.assertTrue(all(p['match_id'] != 'low' for p in picks))

    def test_no_candidate_is_empty_list_not_null(self):
        rows, picks, index = build(ROSTER, [])
        self.assertEqual(rows, [])
        self.assertEqual(picks, [])
        self.assertEqual(index['roided'], [])

    def test_only_the_current_natural_week_counts(self):
        # 上周日 23:59:59.999 的 90% 占比不算；本周一 00:00 的 20% 才算；截止时刻开局的也不算。
        old = [player('a', 900), player('b', 25), player('c', 25), player('d', 25), player('e', 25)]
        fresh = [player('a', 20), player('b', 20), player('c', 20), player('d', 20), player('e', 20)]
        late = [player('e', 800), player('a', 50), player('b', 50), player('c', 50), player('d', 50)]
        _, picks, index = build(ROSTER, [
            ('old', START - 1, old),
            ('fresh', START, fresh),
            ('late', AS_OF, late),  # 半开区间 [start, through) 不含截止时刻
        ])
        self.assertEqual([p['match_id'] for p in picks], ['fresh'])
        self.assertAlmostEqual(picks[0]['damage_share'], 0.2)
        self.assertEqual(index['roided'][0]['match_id'], 'fresh')

    def test_strangers_alone_never_fill_the_card(self):
        # 数据齐全但整队都不在名册：没有候选，卡片为空数组。
        outsiders = [player(pid, 100) for pid in ('x', 'y', 'z', 'w', 'v')]
        rows, picks, index = build(ROSTER, [('m9', START + 1000, outsiders)])
        self.assertEqual(rows, [])
        self.assertEqual(picks, [])
        self.assertEqual(index['roided'], [])

    def test_match_id_is_the_public_id_not_the_riot_key(self):
        # 明细里同时有 Riot 的 match_key 和 public id 时，额外补的 match_id 必须是公开 id。
        team = [player(pid, 100) for pid in ROSTER]
        detail = {'id': 'pub1', 'match_key': 'RIOT_1', 'started_ms': START + 1000, 'duration': 1200,
                  'players': team}
        snapshot = {'build_id': 'test', 'players': [
            {'id': pid, 'name': pid, 'recent': [{'id': 'pub1', 'stats_eligible': True}]} for pid in ROSTER]}
        picks = week_roided(snapshot, {'pub1': detail}, AS_OF)
        self.assertEqual(picks[0]['match_key'], 'RIOT_1')
        self.assertEqual(picks[0]['match_id'], 'pub1')


if __name__ == '__main__':
    unittest.main()
