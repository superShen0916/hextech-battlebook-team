"""Weekly publication freezes the clock, reuses v4, and handles resets/new entrants."""
import copy
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from build_weekly import reports
from haido.rating_lp import CUTOFF, WEEK_MS, week_start_ms, week_scores, WEEK0


class WeeklyReportsTests(unittest.TestCase):
    def setUp(self):
        self.start = week_start_ms(CUTOFF)
        self.snapshot = dict(build_id='test', players=[dict(id=p, name=p) for p in ('a', 'b', 'c')])
        self.baseline = dict(pool=dict(mu=50, sigma=10), players={p: dict(base=1000.04) for p in ('a', 'b', 'c')})
        self.details = [dict(started_ms=self.start-1000-i, players=[dict(profile_id=p, performance=dict(score=50), win=True) for p in ('a', 'b')]) for i in range(5)]

    def add(self, ts, win=True):
        self.details.append(dict(started_ms=ts, players=[dict(profile_id='a', performance=dict(score=60), win=win)]))

    def test_clock_and_current_rating_agree_and_baseline_is_read_only(self):
        self.add(CUTOFF+1000)
        self.add(CUTOFF+5000, False)
        before = copy.deepcopy(self.baseline)
        report = reports(self.snapshot, self.details, self.baseline, CUTOFF+2000)['reports'][0]
        a = next(p for p in report['players'] if p['id']=='a')
        self.assertEqual(a['games'], 1)
        self.assertEqual(a['score'], round(1000.04+week_scores([(CUTOFF+1000, 60, True, 0)], 50, 10)[(self.start-WEEK0)//WEEK_MS]['score'], 1))
        self.assertEqual(report['through_ms'], CUTOFF+2000)
        self.assertEqual(self.baseline, before)
        self.assertEqual(a['rank'], 1)

    def test_monday_no_games_resets_and_closes_previous_week(self):
        self.add(CUTOFF+1000)
        data = reports(self.snapshot, self.details, self.baseline, self.start+WEEK_MS)
        self.assertEqual(len(data['reports']), 2)
        now, previous = data['reports']
        self.assertTrue(previous['complete'])
        old_a = next(p for p in previous['players'] if p['id']=='a')
        new_a = next(p for p in now['players'] if p['id']=='a')
        self.assertEqual(new_a['score'], old_a['score'])
        self.assertEqual(new_a['settled_delta'], old_a['delta'])
        self.assertEqual(previous['through_ms'], previous['end_ms'])
        self.assertFalse(now['complete'])
        self.assertTrue(all(p['delta']==0 and p['games']==0 for p in now['players']))
        self.assertTrue(all(p['rank_change']==0 for p in now['players'] if p['rank']))

    def test_unrated_and_idle_stay_visible_but_follow_active_rated_players(self):
        self.add(CUTOFF+1000, False)
        report = reports(self.snapshot, self.details, self.baseline, CUTOFF+2000)['reports'][0]
        self.assertEqual([p['id'] for p in report['players']], ['a','b','c'])
        c = report['players'][-1]
        self.assertEqual(c['tier'], 'unrated')
        self.assertIsNone(c['rank'])
        self.assertIsNone(c['rank_change'])
        self.assertEqual([p['place'] for p in report['players']], [1,2,3])


if __name__ == '__main__':
    unittest.main()
