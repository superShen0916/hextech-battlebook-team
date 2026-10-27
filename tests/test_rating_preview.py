"""Frozen calibration and historical/current-week boundary checks."""
import json
from pathlib import Path
import sys
import unittest
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'scripts')]
from haido.rating_lp import CUTOFF, WEEK_MS, lp_base, period_score
from haido.rating_lp import week_start_ms
from haido.rating_lp import load_weekly_calibration
from app.awards import VERSION, WEIGHTS, SHARE_CAPS


class RatingPreviewTests(unittest.TestCase):
    def test_separate_weekly_scale_is_read_only_and_rejects_stale_weights(self):
        state = dict(performance_version=VERSION, performance_weights=WEIGHTS,
                     performance_share_caps=SHARE_CAPS,
                     cutoff_ms=CUTOFF, pool=dict(mu=47.4, sigma=8.9, n=100))
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'weekly.json'
            p.write_text(json.dumps(state), encoding='utf-8')
            before = p.read_bytes()
            self.assertEqual(load_weekly_calibration(p), state)
            self.assertEqual(p.read_bytes(), before)
            state['performance_weights'] = dict(WEIGHTS, participation=.25)
            p.write_text(json.dumps(state), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'weekly_calibration_rules_changed'):
                load_weekly_calibration(p)

    def test_calibration_rejects_stale_share_caps_even_with_same_weights(self):
        for caps in (None, dict(damage=.5, kills=.5), dict(damage=.4, kills=.4)):
            with self.subTest(caps=caps), tempfile.TemporaryDirectory() as folder:
                p = Path(folder) / 'weekly.json'
                p.write_text(json.dumps(dict(performance_version=VERSION, performance_weights=WEIGHTS,
                    performance_share_caps=caps, cutoff_ms=CUTOFF,
                    pool=dict(mu=51, sigma=10, n=100))), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'weekly_calibration_rules_changed'):
                    load_weekly_calibration(p)

    def test_invalid_weekly_scale_cannot_silently_fall_back_to_the_old_scale(self):
        for pool in (dict(mu=47, sigma=0, n=100), dict(mu=float('nan'), sigma=8, n=100),
                     dict(mu=47, sigma=8, n=0)):
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder) / 'weekly.json'
                p.write_text(json.dumps(dict(performance_version=VERSION, performance_weights=WEIGHTS,
                                            performance_share_caps=SHARE_CAPS,
                                            cutoff_ms=CUTOFF, pool=pool)), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'invalid_weekly_calibration'):
                    load_weekly_calibration(p)

    def test_cutoff_games_and_future_games_never_reenter_the_week(self):
        start = week_start_ms(CUTOFF) + WEEK_MS
        historical = [(CUTOFF-1, 45, True, 0)]
        base = lp_base(historical, 50, 10)[0]
        rows = historical + [(CUTOFF, 55, True, 0), (start+2, 65, False, 0)]
        period = period_score(rows, base, 50, 10, start+1)
        self.assertEqual(period['base'], round(base,1))
        self.assertEqual(period['settled_weeks'][0]['games'], 1)
        self.assertEqual(period['week_delta'], 0)
        self.assertEqual(period['score'], round(base+period['settled_delta'],1))


if __name__ == '__main__':
    unittest.main()
