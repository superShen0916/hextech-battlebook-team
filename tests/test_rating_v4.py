"""Frozen base, calendar settlement, 4.6 per-match performance and release guards."""
import copy
import datetime
import importlib.util
import io
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
import hashlib
import zipfile
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'app')]
from haido import rating_lp as rating
from release_reuse import data_inputs, rating_week, data_outputs
from verify_release import verify_rating
from inject_haido_ratings import rating_for


def ms(text):
    return int(datetime.datetime.fromisoformat(text).timestamp() * 1000)


class RatingV4Tests(unittest.TestCase):
    def rows(self, n, wins, z=0, at=None, penta=0):
        return [(at or rating.CUTOFF, z, i < wins, penta) for i in range(n)]

    def test_beijing_monday_boundary_is_independent_of_machine_timezone(self):
        sunday = ms('2026-10-25T23:59:59.999+08:00')
        monday = ms('2026-10-26T00:00:00+08:00')
        self.assertEqual(rating.week_start_ms(sunday), rating.WEEK0)
        self.assertEqual(rating.week_start_ms(monday), monday)
        self.assertEqual(rating.week_start_ms(ms('2026-10-25T16:00:00+00:00')), monday)
        self.assertEqual(rating.CUTOFF, ms('2026-10-22T00:00:00+08:00'))
        self.assertEqual(rating_week(monday), '2026-10-26')

    def test_cutoff_is_exclusive_for_base_and_inclusive_for_week(self):
        rows = self.rows(1, 1, at=rating.CUTOFF - 1) + self.rows(1, 1)
        self.assertEqual(rating.week_scores(rows, 0, 1)[0]['n'], 1)

    def test_loss_ratio_zero_point_matches_declared_ratio(self):
        # 5.1：胜负项未加权零点48.7%。取12局内样本，避免顺序递减干扰零点。
        self.assertAlmostEqual(rating.WEEK_EDGE_LOSS / (1 + rating.WEEK_EDGE_LOSS), .4872, places=4)
        with patch.object(rating, 'WEEK_VOLUME_FULL_GAMES', 100):
            even = rating.week_terms(self.rows(39, 19, z=1), 0, 1)
        self.assertAlmostEqual(even['raw_edge'], 0, places=9)
        # 50% 胜率是正收益；45% 落回零点以下
        self.assertGreater(rating.week_terms(self.rows(12, 6, z=0), 0, 1)['win_part'], 0)
        self.assertLess(rating.week_terms(self.rows(12, 5, z=0), 0, 1)['win_part'], 0)
        below = rating.week_scores(self.rows(25, 9, z=1), 0, 1)[0]
        self.assertGreater(below['perf_part'], 0)
        self.assertLess(rating.week_scores(self.rows(20, 9, z=-1), 0, 1)[0]['score'], 0)

    def test_performance_still_differentiates_equal_win_rates(self):
        # 同等胜负、表现更好的周必须拿到明显更高的分
        strong = rating.week_scores(self.rows(20, 11, z=1), 0, 1)[0]['score']
        weak = rating.week_scores(self.rows(20, 11, z=-1), 0, 1)[0]['score']
        self.assertGreater(strong - weak, rating.WEEK_Z_POS * 20 / (20+rating.WEEK_CONF_K) * 1.5)

    def test_b_regular_components_are_uniformly_reduced_including_losses_and_nights(self):
        # 减幅相对于未舍入的B，而不是把已显示到1位的小数再次缩放。
        for n, wins in ((9, 7), (38, 18), (12, 2)):
            for at in (rating.CUTOFF, ms('2026-10-23T21:00:00+08:00')):
                rows = [(at+i, (-1, .5, 2)[i%3], i<wins, 0) for i in range(n)]
                scaled = rating.week_terms(rows, 0, 1)
                with patch.multiple(rating, WEEK_W=7.0, WEEK_Z_POS=1.2,
                                    WEEK_Z_NEG=.8):
                    unscaled = rating.week_terms(rows, 0, 1)
                for key in ('win_part', 'perf_part', 'penta_part', 'raw'):
                    self.assertAlmostEqual(scaled[key], .85*unscaled[key])
                self.assertEqual(scaled['score'], round(.85*unscaled['raw'], 1))

    def test_week_score_is_unclamped_and_confidence(self):
        # 4.5 起取消单周 ±100 封顶：大样本满胜/全负的周按公式原值给出，不再截断
        high = rating.week_scores(self.rows(100, 100, z=10), 0, 1)[0]
        low = rating.week_scores(self.rows(100, 0, z=-10), 0, 1)[0]
        self.assertIsNone(rating.WEEK_CAP)
        self.assertGreater(high['score'], 100)
        self.assertLess(low['score'], -100)
        self.assertEqual(high['score'], round(high['win_part_raw'] + high['perf_part_raw'], 1))
        self.assertEqual(low['score'], round(low['win_part_raw'] + low['perf_part_raw'], 1))
        self.assertEqual(rating.week_scores(self.rows(2, 2), 0, 1)[0]['score'], round(rating.WEEK_W * 2 * 2/(2+rating.WEEK_CONF_K), 1))

    def test_penta_bonus_counts_games_and_is_outside_decay(self):
        rows = self.rows(10, 5, at=rating.CUTOFF - 1)
        before = rating.lp_base(rows, 0, 1)[0]
        rows[0] = (*rows[0][:3], 2)
        self.assertAlmostEqual(rating.lp_base(rows, 0, 1)[0] - before, 3)

    def test_base_and_calibration_stay_fixed_on_backfill_or_new_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'base.json'
            games = {'a': self.rows(10, 5, at=rating.CUTOFF - 1)}
            first = copy.deepcopy(rating.frozen_baseline(p, games))
            games['a'] += self.rows(100, 0, z=20, at=rating.CUTOFF - 2)
            games['b'] = self.rows(30, 30, z=40, at=rating.CUTOFF - 2)
            second = rating.frozen_baseline(p, games)
            self.assertEqual(first['pool'], second['pool'])
            self.assertEqual(first['players']['a'], second['players']['a'])
            self.assertIn('b', second['players'])
            frozen_time = p.stat().st_mtime_ns
            rating.frozen_baseline(p, games)
            self.assertEqual(frozen_time, p.stat().st_mtime_ns)

    def test_invalid_baseline_is_refused_instead_of_silent_rebase(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'base.json'
            games = {'a': self.rows(5, 3, at=rating.CUTOFF - 1)}
            state = rating.frozen_baseline(p, games)
            state['spec']['cutoff_ms'] += 1
            p.write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError, 'baseline_rules_changed'):
                rating.frozen_baseline(p, games)

    def test_reviewed_full_baseline_migration_freezes_again_and_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, preview, backup = root/'base.json', root/'preview.json', root/'old.zip'
            rows = self.rows(10, 6, z=2, at=rating.CUTOFF-1)
            rating.frozen_baseline(path, {'a':rows})
            original = path.read_bytes()
            pool = dict(mu=0, sigma=1, n=10)
            base, wins = rating.lp_base(rows, 0, 1)
            approved = dict(sample_build_id='test', calibration=pool,
                unchanged_private_sha256={'data/haido-baseline-v4.json':hashlib.sha256(original).hexdigest()},
                players=[dict(id='a', history_games=10, history_wins=wins,
                    base_options={'full_refresh':base})])
            preview.write_text(json.dumps(approved))
            with zipfile.ZipFile(backup, 'w') as package:
                package.writestr('data/haido-baseline-v4.json', original)
            state = rating.rebuild_reviewed_baseline(path, {'a':rows}, pool, preview, backup, 'test')
            self.assertEqual(state['players']['a']['base'], base)
            frozen = path.read_bytes()
            rating.frozen_baseline(path, {'a':rows+self.rows(10,0,z=-2,at=rating.CUTOFF-2)})
            self.assertEqual(path.read_bytes(), frozen)
            with self.assertRaisesRegex(ValueError, 'baseline_changed_since_review'):
                rating.rebuild_reviewed_baseline(path, {'a':rows}, pool, preview, backup, 'test')
            self.assertEqual(path.read_bytes(), frozen)

    def test_reviewed_baseline_migration_refuses_changed_samples_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, preview, backup = root/'base.json', root/'preview.json', root/'old.zip'
            rows = self.rows(10, 6, z=2, at=rating.CUTOFF-1)
            rating.frozen_baseline(path, {'a':rows})
            original = path.read_bytes()
            pool = dict(mu=0, sigma=1, n=10)
            preview.write_text(json.dumps(dict(sample_build_id='test', calibration=pool,
                unchanged_private_sha256={'data/haido-baseline-v4.json':hashlib.sha256(original).hexdigest()},
                players=[dict(id='a', history_games=10, history_wins=6,
                    base_options={'full_refresh':rating.lp_base(rows,0,1)[0]+1})])))
            with zipfile.ZipFile(backup, 'w') as package:
                package.writestr('data/haido-baseline-v4.json', original)
            with self.assertRaisesRegex(ValueError, 'reviewed_baseline_sample_changed'):
                rating.rebuild_reviewed_baseline(path, {'a':rows}, pool, preview, backup, 'test')
            self.assertEqual(path.read_bytes(), original)

    def run_score(self, root, at, details, cli=False):
        snapshot = root / 'snapshot.json'
        snapshot.write_text(json.dumps({'players': [{'id': 'a', 'name': 'A'}, {'id': 'empty', 'name': 'Empty'}]}))
        matches = root / 'matches'; matches.mkdir(exist_ok=True)
        for i, row in enumerate(details):
            ts, perf, win, penta = row
            (matches / f'm-{i}.json').write_text(json.dumps({'started_ms': ts, 'players': [
                {'profile_id': 'a', 'performance': {'score': perf}, 'win': win, 'penta_kills': penta}]}))
        out = root / 'scores.json'
        from app.awards import VERSION as award_version, WEIGHTS, SHARE_CAPS
        calibration = root / 'weekly-calibration.json'
        calibration.write_text(json.dumps(dict(performance_version=award_version,
            performance_weights=WEIGHTS, performance_share_caps=SHARE_CAPS, cutoff_ms=rating.CUTOFF,
            pool=dict(mu=0, sigma=1, n=5))))
        argv = ['rating', '--snapshot', str(snapshot), '--matches', str(matches), '--out', str(out),
                '--as-of-ms', str(at), '--weekly-calibration', str(calibration)]
        if cli:
            subprocess.run([sys.executable, str(ROOT / 'haido/rating_lp.py'), *argv[1:]],
                           cwd=root, check=True, capture_output=True, text=True)
        else:
            with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()):
                rating.main()
        return json.loads(out.read_text())

    def test_direct_cli_loads_the_separate_weekly_scale_outside_project_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_score(Path(folder), rating.CUTOFF+1,
                self.rows(5, 3, at=rating.CUTOFF-1) + self.rows(5, 5), cli=True)
            self.assertGreater(next(p for p in result['players'] if p['id'] == 'a')['week_delta'], 0)

    def test_idle_new_week_resets_week_only_and_preserves_accumulated_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = self.rows(5, 3, at=rating.CUTOFF - 1) + self.rows(5, 5)
            first = self.run_score(root, rating.CUTOFF+1, rows)
            second = self.run_score(root, rating.WEEK0 + rating.WEEK_MS, rows)
            a = next(p for p in first['players'] if p['id'] == 'a')
            b = next(p for p in second['players'] if p['id'] == 'a')
            self.assertGreater(a['week_delta'], 0)
            self.assertEqual(b['week_delta'], 0)
            self.assertEqual(b['week_games'], 0)
            self.assertEqual(a['base'], b['base'])
            self.assertEqual(b['score'], a['score'])
            self.assertEqual(b['settled_delta'], a['week_delta'])
            self.assertEqual(b['lp_prev'], b['score'])
            empty = next(p for p in second['players'] if p['id'] == 'empty')
            self.assertEqual((empty['n'], empty['tier'], empty['week_delta']), (0, 'unrated', 0))

    def test_input_fingerprint_includes_rating_code_and_calendar_but_not_day_within_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['app/static', 'scripts', 'haido', 'data', 'work/players-preview-20261022/lib']:
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / 'haido/rating_lp.py').write_text('rules1')
            for name in ['prepare-match-details.py', 'prepare-achievements.mjs']:
                (root / 'work/players-preview-20261022' / name).write_text('fixture')
            with patch('release_inputs.database_signature', return_value='db'), patch('release_inputs.tree_hash', return_value='tree'):
                before = data_inputs(root, rating.CUTOFF)
                self.assertEqual(before, data_inputs(root, rating.CUTOFF + 86400000))
                self.assertNotEqual(before, data_inputs(root, rating.WEEK0 + rating.WEEK_MS))
                (root / 'haido/rating_lp.py').write_text('rules2')
                self.assertNotEqual(before, data_inputs(root, rating.CUTOFF))

    def valid_rating(self):
        conf = 2 / (2 + rating.WEEK_CONF_K)
        win_part = rating.WEEK_W * (1 - rating.WEEK_EDGE_LOSS) * conf
        perf = rating.WEEK_Z_POS * (.5 * 2) * conf
        delta = round(win_part + perf, 1)
        return rating_for({'tier': 'stable', 'haido': 1000 + delta, 'n': 100, 'base': 1000,
                           'lp_prev': 1000, 'week_games': 2, 'week_wins': 1, 'week_win_rate': .5,
                           'week_delta': delta, 'week_start_ms': rating.WEEK0,
                           'week_end_ms': rating.WEEK0 + rating.WEEK_MS,
                           'settled_delta': 0, 'settled_weeks': [],
                           'calculation': {'confidence': conf, 'avg_z': .5, 'performance_sum_z': 1,
                                           'performance_sum_pos': 1, 'performance_sum_neg': 0,
                                           'performance_sum_effective': rating.WEEK_Z_POS,
                                           'win_part': win_part, 'penta_games': 0, 'penta_count': 0, 'penta_part': 0,
                                           'weighted_wins': 1, 'weighted_losses': 1, 'volume_average': 1,
                                           'performance_part': perf, 'raw_delta': win_part + perf,
                                           'cap': rating.WEEK_CAP,
                                           'effective_edge': 1 - rating.WEEK_EDGE_LOSS,
                                           'battle_night_games': 0, 'battle_night_wins': 0,
                                           'battle_night_mult': rating.BATTLE_NIGHT_MULT}},
                          rating.VERSION)

    def test_positive_and_negative_weeks_both_survive_idle_rollover(self):
        for wins in (0, 8):
            rows = self.rows(8, wins)
            before = rating.period_score(rows, 1800, 0, 1, rating.CUTOFF+1)
            after = rating.period_score(rows, 1800, 0, 1, rating.WEEK0+rating.WEEK_MS)
            later = rating.period_score(rows, 1800, 0, 1, rating.WEEK0+4*rating.WEEK_MS)
            self.assertEqual(before['score'], after['score'])
            self.assertEqual(after['score'], later['score'])
            self.assertEqual(after['week_delta'], 0)
            self.assertEqual(after['settled_delta'], before['week_delta'])
            self.assertEqual(len(later['settled_weeks']), 1)

    def test_every_week_counted_once_without_cap(self):
        rows = self.rows(100, 100, z=10)
        rows += self.rows(100, 0, z=-10, at=rating.WEEK0+rating.WEEK_MS)
        rows += self.rows(2, 2, at=rating.WEEK0+2*rating.WEEK_MS)
        high = rating.week_terms(self.rows(100, 100, z=10), 0, 1)['score']
        low = rating.week_terms(self.rows(100, 0, z=-10), 0, 1)['score']
        result = rating.period_score(rows, 1800, 0, 1, rating.WEEK0+2*rating.WEEK_MS+1)
        self.assertEqual([w['delta'] for w in result['settled_weeks']], [high, low])
        self.assertEqual(result['settled_delta'], round(high + low, 1))
        this_week = round(rating.WEEK_W * 2 * 2/(2+rating.WEEK_CONF_K), 1)
        self.assertEqual(result['week_delta'], this_week)
        self.assertEqual(result['score'], round(1800 + high + low + this_week, 1))
        self.assertEqual(result, rating.period_score(rows,1800,0,1,rating.WEEK0+2*rating.WEEK_MS+1))

    def test_exact_week_boundary_and_future_game_exclusion(self):
        monday = rating.WEEK0+rating.WEEK_MS
        rows = self.rows(1,1,at=monday-1)+self.rows(1,1,at=monday)+self.rows(1,0,at=monday+1)
        current = rating.period_score(rows,1800,0,1,monday+1)
        self.assertEqual(current['settled_weeks'][0]['games'],1)
        self.assertEqual(current['this_week']['n'],1)
        closed = rating.period_score(rows,1800,0,1,monday,rating.WEEK0)
        self.assertEqual(closed['this_week']['n'],1)
        self.assertEqual(closed['settled_delta'],0)

    def test_match_deltas_split_week_score_without_cap(self):
        rows = self.rows(9, 5, z=.5)
        ids = [f'm-{i}' for i in range(9)]
        parts = rating.match_contributions(rows, ids, 0, 1)
        week = rating.week_scores(rows, 0, 1)[0]
        self.assertEqual(set(parts), set(ids))
        self.assertAlmostEqual(sum(parts.values()), week['score'], delta=.051)
        self.assertTrue(all(parts[f'm-{i}'] > 0 for i in range(5)))
        self.assertTrue(all(parts[f'm-{i}'] < 0 for i in range(5, 9)))
        big = rating.match_contributions(self.rows(100, 100, z=10), [f'c-{i}' for i in range(100)], 0, 1)
        self.assertAlmostEqual(sum(big.values()), rating.week_terms(self.rows(100, 100, z=10), 0, 1)['score'], delta=.051)
        self.assertGreater(sum(big.values()), 100)

    def test_match_deltas_skip_baseline_games_and_keep_performance_below_forty_percent(self):
        base = self.rows(3, 3, at=rating.CUTOFF - 1)
        week = self.rows(20, 4, z=5)
        parts = rating.match_contributions(base + week, [f'b-{i}' for i in range(3)] + [f'w-{i}' for i in range(20)], 0, 1)
        self.assertEqual(set(parts), {f'w-{i}' for i in range(20)})
        terms = rating.week_scores(week, 0, 1)[0]
        self.assertGreater(terms['perf_part'], 0)
        self.assertAlmostEqual(sum(parts.values()), terms['score'], delta=.051)

    def test_volume_decay_preserves_balance_between_win_and_performance(self):
        # 共同场次系数不会再次让表现相对于胜负被除以周场数。
        for n in (2, 9, 37, 100):
            strong = rating.week_terms(self.rows(n, n, z=1), 0, 1)
            middle = rating.week_terms(self.rows(n, n, z=0), 0, 1)
            self.assertAlmostEqual((strong['raw']-middle['raw']) / sum(strong['regular_weights']) / strong['conf'],
                                   rating.WEEK_Z_POS)

    def test_weekly_penta_adds_two_or_three_per_occurrence_outside_confidence(self):
        for at, per_penta in ((ms('2026-10-24T21:00:00+08:00'), 2),
                              (ms('2026-10-23T21:00:00+08:00'), 3)):
            for n in (1, 25):
                for count in (0, 1, 2):
                    plain = self.rows(n, 0, z=-1, at=at)
                    bonus = list(plain)
                    bonus[0] = (*bonus[0][:3], count)
                    a, b = rating.week_terms(plain, 0, 1), rating.week_terms(bonus, 0, 1)
                    self.assertEqual(b['penta_games'], int(count>0))
                    self.assertEqual(b['penta_count'], count)
                    self.assertEqual(b['penta_part'], count*per_penta)
                    self.assertAlmostEqual(b['raw']-a['raw'], count*per_penta)
                    ids = [f'm-{i}' for i in range(n)]
                    parts = rating.match_contributions(bonus, ids, 0, 1)
                    self.assertAlmostEqual(sum(parts.values()), b['score'], delta=.051)

    def test_penta_injection_and_cutoff_do_not_leak_to_other_games(self):
        from inject_haido_ratings import inject_match_deltas
        view = {'recent': [{'id': 'a'}, {'id': 'b', 'rating_penta_bonus': 99},
                           {'id': 'old', 'rating_penta_bonus': 99}]}
        inject_match_deltas(view, {'match_deltas': {'a': 5, 'b': 2},
                                'match_weights': {'a': 1.5, 'b': 1},
                                'match_penta_bonuses': {'a': 3}})
        self.assertEqual(view['recent'][0]['rating_penta_bonus'], 3)
        self.assertNotIn('rating_penta_bonus', view['recent'][1])
        self.assertNotIn('rating_penta_bonus', view['recent'][2])
        self.assertEqual(rating.match_contributions(self.rows(1, 1, penta=1, at=rating.CUTOFF-1), ['old'], 0, 1), {})

    def test_gate_rejects_missing_or_impossible_penta_bonus(self):
        for value in (None, 1, 999):
            broken = self.valid_rating()
            broken['calculation']['penta_part'] = value
            with self.subTest(value=value), self.assertRaises(AssertionError):
                verify_rating(broken, rating.WEEK0, 'forged')

    def test_weekly_signal_bounds_outliers_without_rewriting_awards_or_base(self):
        for sign in (-1, 1):
            ordinary = rating.week_terms(self.rows(10, 5, z=sign*2), 0, 1)
            outlier = rating.week_terms(self.rows(10, 5, z=sign*100), 0, 1)
            self.assertEqual(ordinary['score'], outlier['score'])
            self.assertNotEqual(rating.lp_base(self.rows(10, 5, z=sign*2), 0, 1),
                                rating.lp_base(self.rows(10, 5, z=sign*100), 0, 1))

    def test_good_loss_loses_less_and_bad_win_never_loses_points(self):
        # 胜负优先后强表现输局仍扣分，但比普通输局少扣；赢局不被负表现反扣。
        strong_loss = rating.week_terms(self.rows(10, 0, z=2), 0, 1)
        plain_loss = rating.week_terms(self.rows(10, 0, z=0), 0, 1)
        poor_win = rating.week_terms(self.rows(10, 10, z=-2), 0, 1)
        good_win = rating.week_terms(self.rows(10, 10, z=2), 0, 1)
        self.assertLess(strong_loss['score'], 0)
        self.assertGreater(strong_loss['score'], plain_loss['score'])
        self.assertEqual(poor_win['perf_part'], 0)
        self.assertGreater(poor_win['score'], 0)
        self.assertGreater(good_win['score'], poor_win['score'])

    def test_rounding_does_not_dump_large_week_residual_on_one_match(self):
        rows = self.rows(1000, 600, z=.123)
        rows = [(row[0]+i, *row[1:]) for i, row in enumerate(rows)]
        parts = rating.match_contributions(rows, [f'm-{i}' for i in range(1000)], 0, 1)
        terms = rating.week_terms(rows, 0, 1)
        self.assertAlmostEqual(sum(parts.values()), terms['score'], places=6)
        for i, (_, z, win, _) in enumerate(rows):
            exact = (rating.WEEK_W*(1 if win else -rating.WEEK_EDGE_LOSS)
                     + rating.match_performance_signal(z, win))*terms['conf']*rating.volume_multiplier(i+1)
            self.assertLess(abs(parts[f'm-{i}']-exact), .100001)

    def test_volume_curve_full_first_twelve_then_strictly_decreases(self):
        self.assertEqual([rating.volume_multiplier(i) for i in range(1,13)], [1]*12)
        curve = [rating.volume_multiplier(i) for i in range(12,1001)]
        self.assertTrue(all(a>b>0 for a,b in zip(curve,curve[1:])))
        self.assertAlmostEqual(rating.volume_multiplier(48), .5)
        with self.assertRaises(ValueError):rating.volume_multiplier(0)

    def test_volume_sequence_is_chronological_and_independent_of_input_order(self):
        rows = [(rating.CUTOFF+i, .2, i%2==0, 0) for i in range(40)]
        ids = [f'm-{i}' for i in range(40)]
        a = rating.match_contributions(rows,ids,0,1,with_details=True)
        b = rating.match_contributions(rows[::-1],ids[::-1],0,1,with_details=True)
        self.assertEqual(a,b)
        self.assertEqual(a[1]['m-0'],1)
        self.assertAlmostEqual(a[1]['m-35'], (12/36)**.5)
        self.assertEqual(a[2]['m-35'],36)
        self.assertEqual(rating.week_terms(rows,0,1)['score'],rating.week_terms(rows[::-1],0,1)['score'])

    def test_volume_resets_each_week_and_skips_frozen_history(self):
        rows = self.rows(30,30,at=rating.CUTOFF-1)
        rows += [(rating.CUTOFF+i,0,True,0) for i in range(30)]
        rows += [(rating.WEEK0+rating.WEEK_MS+i,0,True,0) for i in range(2)]
        ids = [f'm-{i}' for i in range(len(rows))]
        _, volumes, indices = rating.match_contributions(rows,ids,0,1,with_details=True)
        self.assertNotIn('m-0',volumes)
        self.assertEqual(indices['m-60'],1)
        self.assertEqual(volumes['m-60'],1)
        self.assertLess(volumes['m-59'],1)

    def test_repeated_good_games_have_sublinear_total_reward_without_hard_cap(self):
        small=rating.week_terms([(rating.CUTOFF+i,0,True,0) for i in range(40)],0,1)
        large=rating.week_terms([(rating.CUTOFF+i,0,True,0) for i in range(80)],0,1)
        self.assertGreater(large['score'],small['score'])
        self.assertLess(large['score'],small['score']*2)

    def test_gate_rejects_missing_or_out_of_bounds_performance_sum(self):
        for value in (None, float('nan'), 999):
            broken = self.valid_rating()
            broken['calculation']['performance_sum_z'] = value
            with self.subTest(value=value), self.assertRaises(AssertionError):
                verify_rating(broken, rating.WEEK0, 'forged')

    def test_battle_night_window_is_friday_2000_to_saturday_0200(self):
        night = ms('2026-10-23T20:00:00+08:00')
        self.assertEqual(rating.battle_night_weight(night), rating.BATTLE_NIGHT_MULT)
        self.assertEqual(rating.battle_night_weight(ms('2026-10-23T19:59:59+08:00')), 1.0)
        self.assertEqual(rating.battle_night_weight(ms('2026-10-24T01:59:59+08:00')), rating.BATTLE_NIGHT_MULT)
        self.assertEqual(rating.battle_night_weight(ms('2026-10-24T02:00:00+08:00')), 1.0)
        self.assertEqual(rating.battle_night_weight(ms('2026-10-22T23:00:00+08:00')), 1.0)
        self.assertEqual(rating.battle_night_weight(ms('2026-10-25T21:00:00+08:00')), 1.0)
        self.assertEqual(rating.battle_night_weight(0), 1.0)

    def test_battle_night_multiplies_both_components_and_keeps_split_additive(self):
        day = ms('2026-10-24T21:00:00+08:00')   # 周六晚，窗口外；仍在 10-19 那一周且晚于 CUTOFF
        night = ms('2026-10-23T21:00:00+08:00')
        ids = [f'm-{i}' for i in range(9)]
        plain = rating.week_scores(self.rows(9, 5, z=.5, at=day), 0, 1)[0]
        boosted = rating.week_scores(self.rows(9, 5, z=.5, at=night), 0, 1)[0]
        self.assertAlmostEqual(boosted['win_part_raw'], plain['win_part_raw'] * rating.BATTLE_NIGHT_MULT)
        self.assertAlmostEqual(boosted['perf_part_raw'], plain['perf_part_raw'] * rating.BATTLE_NIGHT_MULT)
        self.assertAlmostEqual(boosted['score'], plain['score'] * rating.BATTLE_NIGHT_MULT, delta=.11)
        self.assertEqual(boosted['battle_night_games'], 9)
        self.assertEqual(plain['battle_night_games'], 0)
        parts = rating.match_contributions(self.rows(9, 5, z=.5, at=night), ids, 0, 1)
        plain_parts = rating.match_contributions(self.rows(9, 5, z=.5, at=day), ids, 0, 1)
        self.assertAlmostEqual(sum(parts.values()), boosted['score'], delta=.051)
        self.assertAlmostEqual(sum(plain_parts.values()), plain['score'], delta=.051)
        for mid in ids:
            self.assertAlmostEqual(parts[mid], plain_parts[mid] * rating.BATTLE_NIGHT_MULT, delta=.15)

    def test_battle_night_is_counted_per_game_inside_a_mixed_week(self):
        day = self.rows(6, 3, z=.2, at=ms('2026-10-24T21:00:00+08:00'))
        night = self.rows(6, 6, z=.2, at=ms('2026-10-23T22:00:00+08:00'))
        mixed = rating.week_scores(day + night, 0, 1)[0]
        self.assertEqual(mixed['battle_night_games'], 6)
        self.assertEqual(mixed['battle_night_wins'], 6)
        self.assertGreater(mixed['edge'], mixed['raw_edge'])
        self.assertEqual(mixed['raw_edge'], round(9 - rating.WEEK_EDGE_LOSS * 3, 2))

    def test_gate_rejects_forged_battle_night_sample(self):
        valid = self.valid_rating()
        broken = copy.deepcopy(valid)
        broken['calculation']['battle_night_games'] = 5
        with self.assertRaises(AssertionError):
            verify_rating(broken, rating.WEEK0, 'forged')
        broken = copy.deepcopy(valid)
        broken['calculation'].pop('battle_night_mult')
        with self.assertRaises(AssertionError):
            verify_rating(broken, rating.WEEK0, 'forged')

    def test_gate_rejects_duplicate_or_missing_settlement_and_forged_explanation(self):
        valid = self.valid_rating()
        for change in ('bank','explanation','duplicate'):
            broken = copy.deepcopy(valid)
            if change == 'bank': broken['settled_delta'] = 5
            if change == 'explanation': broken['calculation']['win_part'] = 999
            if change == 'duplicate':
                entry = dict(start_ms=rating.WEEK0-rating.WEEK_MS,end_ms=rating.WEEK0,games=1,wins=1,delta=0)
                broken['settled_weeks'] = [entry,entry]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                verify_rating(broken,rating.WEEK0,'a')

    def test_gate_refuses_old_version_stale_week_broken_total_and_idle_delta(self):
        valid = self.valid_rating()
        verify_rating(valid, rating.WEEK0, 'a')
        for change in ['version', 'week', 'score', 'idle']:
            row = copy.deepcopy(valid)
            if change == 'version': row['version'] = 'lp-v1.1'
            if change == 'week': row['week']['start_ms'] -= rating.WEEK_MS
            if change == 'score': row['score'] += 10
            if change == 'idle': row['week'].update(games=0, wins=0, win_rate=None)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                verify_rating(row, rating.WEEK0, 'a')


if __name__ == '__main__':
    unittest.main()
