"""「本周最胡」口径测试：周窗口、有效局、队伍边界、并列与缺失字段。"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from weekly_award import most_roided, top_roided

WEEK = 7 * 24 * 60 * 60 * 1000
# 北京时间 2026-11-16 周一 00:00，与 haido/rating_lp.py 的周切分同一时刻。
START = int(datetime(2026, 11, 16, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)
END = START + WEEK


def team(prefix, damages, team_id=100, win=True, **extra):
    return [dict(profile_id=f'{prefix}{i}', name=f'{prefix}{i}', team_id=team_id, win=win,
                 damage=damage, kills=i, deaths=1, assists=2, champion_name='黑默丁格', **extra)
            for i, damage in enumerate(damages)]


def match(key, started, players, **extra):
    return dict(id=key, match_key=key, started_ms=started, players=players, **extra)


class MostRoidedTests(unittest.TestCase):
    def test_only_eligible_matches_count(self):
        eligible = match('m1', START + 1000, team('a', [100, 100, 100, 100, 100]))
        skipped = match('m2', START + 2000, team('b', [500, 10, 10, 10, 10]), stats_eligible=False)
        winner = most_roided([eligible, skipped], START, END)
        self.assertEqual(winner['match_key'], 'm1')
        self.assertEqual(winner['profile_id'], 'a0')

    def test_teams_are_scored_separately(self):
        # 100 队内最高占比 80/300；200 队内最高占比 90/250，跨队合并会算错。
        players = team('a', [80, 60, 60, 50, 50], team_id=100) + team('b', [90, 50, 50, 30, 30], team_id=200)
        winner = most_roided([match('m1', START + 1000, players)], START, END)
        self.assertEqual(winner['profile_id'], 'b0')
        self.assertAlmostEqual(winner['damage_share'], 90 / 250)

    def test_tie_breaks_follow_share_damage_time_then_profile_id(self):
        same_share = team('a', [50, 50, 50, 50, 50]) + team('b', [10, 10, 10, 10, 10], team_id=200)
        early = match('early', START + 1000, same_share)
        late = match('late', START + 9000, same_share)
        # 占比与伤害都相同：后开局的赢。
        self.assertEqual(most_roided([early, late], START, END)['started_ms'], START + 9000)
        # 时间也相同：同占比、同伤害下 profile_id 字符串升序，'a0' 在 'a1' 等之前。
        self.assertEqual(most_roided([early], START, END)['profile_id'], 'a0')
        # 占比相同但伤害绝对值更高者优先。
        bigger = team('c', [100, 100, 100, 100, 100])
        self.assertEqual(most_roided([early, match('bigger', START + 1000, bigger)], START, END)['damage'], 100)

    def test_incomplete_team_damage_is_skipped(self):
        broken = team('a', [100, 100, 100, 100, None])
        short = team('b', [100, 100, 100, 100], team_id=200)
        zeroed = team('z', [0, 0, 0, 0, 0], team_id=400)
        only = team('c', [70, 20, 20, 20, 20], team_id=300)
        winner = most_roided([match('m1', START + 1000, broken + short + zeroed + only)], START, END)
        self.assertEqual(winner['profile_id'], 'c0')

    def test_missing_items_and_augments_do_not_raise(self):
        players = team('a', [10, 10, 10, 10, 10])
        winner = most_roided([match('m1', START + 1000, players)], START, END)
        self.assertNotIn('items', winner)
        self.assertNotIn('augments', winner)
        # 缺失字段一律省略，不补 0；有值的字段照常输出。
        self.assertTrue(winner['win'])
        self.assertEqual((winner['kills'], winner['deaths'], winner['assists']), (0, 1, 2))
        self.assertNotIn('champion_id', winner)

    def test_raw_riot_slots_and_normalized_lists(self):
        raw = dict(profile_id='a0', name='a0', team_id=100, damage=10)
        raw.update({f'item{i}': 3031 for i in range(2)})
        raw.update({f'item{i}': 0 for i in range(2, 7)})
        raw.update({f'playerAugment{i}': 0 for i in range(1, 7)})
        raw['playerAugment2'] = 7
        raw_match = match('raw', START + 1000, [raw] + team('a', [10, 10, 10, 10, 10])[1:])
        self.assertEqual(most_roided([raw_match], START, END)['items'],
                         [3031, 3031, None, None, None, None, None])
        self.assertEqual(most_roided([raw_match], START, END)['augments'],
                         [None, 7, None, None, None, None])
        normalized = dict(profile_id='b0', name='b0', team_id=100, damage=10,
                          items=[3031, None, 3006], augments=[11, 12])
        normalized_match = match('norm', START + 1000, [normalized] + team('b', [10, 10, 10, 10, 10])[1:])
        winner = most_roided([normalized_match], START, END)
        self.assertEqual(winner['items'], [3031, None, 3006, None, None, None, None])
        self.assertEqual(winner['augments'], [11, 12, None, None, None, None])

    def test_monday_midnight_belongs_to_the_new_week(self):
        players = team('a', [10, 10, 10, 10, 10])
        sunday = match('sun', END - 1, players)
        monday = match('mon', END, players)
        self.assertEqual(most_roided([sunday, monday], START, END)['match_key'], 'sun')
        self.assertIsNone(most_roided([monday], START, END))
        self.assertEqual(most_roided([monday], END, END + WEEK)['match_key'], 'mon')


class TopRoidedTests(unittest.TestCase):
    def test_top_three_uses_the_same_rank_key_and_is_capped(self):
        games = [
            match('low', START + 1000, team('a', [30, 30, 30, 30, 30])),          # 0.20
            match('high', START + 2000, team('b', [400, 25, 25, 25, 25])),       # 0.80
            match('mid', START + 3000, team('c', [100, 50, 50, 50, 50])),        # 0.33
            match('best', START + 4000, team('d', [700, 25, 25, 25, 25])),       # 0.88
        ]
        ranked = top_roided(games, START, END)
        self.assertEqual([row['match_key'] for row in ranked], ['best', 'high', 'mid'])
        self.assertEqual([round(row['damage_share'], 4) for row in ranked], [0.875, 0.8, round(1 / 3, 4)])
        # 兼容包装：第一条与 most_roided 完全一致。
        self.assertEqual(most_roided(games, START, END), ranked[0])
        self.assertEqual(top_roided(games, START, END, limit=2),
                         [row for row in ranked if row['match_key'] in ('best', 'high')])
        # limit 大于候选数时返回全部候选，顺序与截断前一致。
        full = top_roided(games, START, END, limit=10)
        self.assertEqual([row['match_key'] for row in full], ['best', 'high', 'mid', 'low'])
        self.assertEqual(full[:3], ranked)

    def test_top_three_keeps_week_window_and_roster_filter(self):
        early = match('early', START - 1, team('a', [900, 10, 10, 10, 10]))
        inside = match('inside', START, team('b', [300, 10, 10, 10, 10]))
        remake = match('remake', START + 500, team('c', [900, 10, 10, 10, 10]), stats_eligible=False)
        ranked = top_roided([early, inside, remake], START, END, allowed_ids={'b0'})
        self.assertEqual([row['match_key'] for row in ranked], ['inside'])
        self.assertEqual(ranked[0]['profile_id'], 'b0')

    def test_empty_input_and_invalid_limit(self):
        self.assertEqual(top_roided([], START, END), [])
        self.assertEqual(top_roided([], START, END, limit=1), [])
        for bad in (0, -1, True, 3.0, None, '3'):
            with self.assertRaises(ValueError):
                top_roided([], START, END, limit=bad)

    def test_one_game_fills_only_one_slot(self):
        # 同一局两队各有高占比玩家，但这局只能占一个名额，卡片不会重复指向同一份战报。
        both = (team('a', [400, 25, 25, 25, 25])
                + team('b', [300, 20, 20, 20, 20], team_id=200))
        ranked = top_roided([match('m1', START + 1000, both),
                             match('m2', START + 2000, team('c', [50, 50, 50, 50, 50]))], START, END)
        self.assertEqual([row['match_key'] for row in ranked], ['m1', 'm2'])
        self.assertEqual(ranked[0]['profile_id'], 'a0')
        self.assertEqual(len({row['match_key'] for row in ranked}), len(ranked))


if __name__ == '__main__':
    unittest.main()
