import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, closing
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'scripts')]
from build_cache import ProjectionCache
from release_reuse import (assemble_data_release, can_reuse_frontend, database_signature,
                           frontend_inputs, promote, tree_hash, is_dataset)
from detail_bundle import load_bundle


class IncrementalReleaseTests(unittest.TestCase):
    def test_lp_bulk_input_matches_original_file_path_exactly_and_rejects_stale_build(self):
        spec = importlib.util.spec_from_file_location('lp_incremental_test', ROOT / 'haido/rating_lp.py')
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); matches = root / 'matches'; matches.mkdir()
            data = {'build_id': 'one', 'players': [{'id': 'a', 'name': 'A'}, {'id': 'b', 'name': 'B'}]}
            snapshot = root / 'full.json'; snapshot.write_text(json.dumps(data))
            details = {}
            for i in range(7):
                detail = {'id': 'm-' + str(i), 'started_ms': i * 1000, 'players': [
                    {'profile_id': 'a' if j == 0 else 'b' if j == 1 else None,
                     'performance': {'score': 30 + i * 4 + j} if i < 6 else None,
                     'win': (i + j) % 2 == 0} for j in range(10)]}
                details[detail['id']] = detail
                (matches / (detail['id'] + '.json')).write_text(json.dumps(detail))
            bundle = root / 'bundle.json'; bundle.write_text(json.dumps({'build_id': 'one', 'details': details}))
            self.assertEqual(load_bundle(bundle, 'one'), details)
            with self.assertRaises(ValueError):
                load_bundle(bundle, 'stale')
            def run(output, extra):
                argv = ['lp', '--matches', str(matches), '--snapshot', str(snapshot), '--out', str(output), '--as-of-ms', str(mod.CUTOFF+1), *extra]
                with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()):
                    mod.main()
                return json.loads(output.read_text())
            self.assertEqual(run(root / 'original.json', []), run(root / 'bulk.json', ['--bundle', str(bundle)]))

    def test_projection_cache_reuses_unchanged_players_but_invalidates_games_policy_and_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ProjectionCache(tmp, 'v1')
            calls = []
            def get(name, games):
                return cache.get_or_compute(name, games, lambda: calls.append(name) or {'games': games})
            a = [{'id': 'one', 'eligible': True}]
            self.assertEqual(get('alice', a), get('alice', a))
            get('bob', a)
            get('alice', a + [{'id': 'two', 'eligible': True}])
            get('bob', a)
            get('alice', [{'id': 'one', 'eligible': False}])
            self.assertEqual(calls, ['alice', 'bob', 'alice', 'alice'])
            cache.implementation = 'v2'
            get('bob', a)
            self.assertEqual(calls[-1], 'bob')
            path = Path(tmp) / (hashlib.sha256(b'bob').hexdigest() + '.json')
            entry = json.loads(path.read_text()); entry['value']['games'] = []
            path.write_text(json.dumps(entry))
            get('bob', a)
            self.assertEqual(calls.count('bob'), 3)

    def test_data_changes_do_not_invalidate_frontend_but_source_dependencies_and_shell_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            front = Path(tmp)
            for folder in ('src', 'lib', 'public/api', 'public/share', 'dist/api'):
                (front / folder).mkdir(parents=True)
            (front / 'src/App.tsx').write_text('render')
            (front / 'package-lock.json').write_text('lock1')
            (front / 'public/share/index.html').write_text('share')
            (front / 'dist/index.html').write_text('bundle1')
            key = frontend_inputs(front, 'v22')
            receipt = {'inputs': key, 'shell': tree_hash(front / 'dist', lambda p: not is_dataset(p))}
            (front / 'public/api/snapshot.json').write_text('new data')
            (front / 'dist/api/manifest.json').write_text('new data')
            self.assertEqual(key, frontend_inputs(front, 'v22'))
            self.assertTrue(can_reuse_frontend(receipt, key, front / 'dist'))
            (front / 'src/App.tsx').write_text('new render')
            self.assertNotEqual(key, frontend_inputs(front, 'v22'))
            (front / 'src/App.tsx').write_text('render')
            (front / 'package-lock.json').write_text('lock2')
            self.assertNotEqual(key, frontend_inputs(front, 'v22'))
            self.assertNotEqual(key, frontend_inputs(front, 'v23'))
            (front / 'dist/index.html').write_text('tampered')
            self.assertFalse(can_reuse_frontend(receipt, key, front / 'dist'))

    def test_sqlite_wal_updates_invalidate_even_when_main_file_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'source.sqlite'
            with closing(sqlite3.connect(p)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE matches(match_key,payload_hash,stats_eligible,queue_id,game_mode,started_ms)')
                db.execute("INSERT INTO matches VALUES('one','h1',1,2400,'KIWI',1)")
                db.commit(); db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                before_file = p.read_bytes(); before = database_signature(p)
                db.execute("UPDATE matches SET payload_hash='corrected',stats_eligible=0"); db.commit()
                self.assertEqual(before_file, p.read_bytes())
                self.assertNotEqual(before, database_signature(p))

    def test_candidate_reuses_shell_and_unchanged_details_without_mutating_previous_or_linking_public(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); dist, public, candidate = [base / p for p in ('dist', 'public', 'candidate')]
            for path, value in [('dist/index.html', 'shell'), ('dist/matches/same.json', 'same'),
                                ('dist/api/old.json', 'obsolete'), ('dist/api/value.json', 'old'),
                                ('public/api/value.json', 'new')]:
                p = base / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
            # Plant an unchanged detail. Reuse must follow bytes, independently
            # of timestamp metadata inherited from a previous release.
            (base / 'public/matches').mkdir(parents=True, exist_ok=True)
            shutil.copy2(base / 'dist/matches/same.json', base / 'public/matches/same.json')
            result = assemble_data_release(dist, public, candidate)
            # A fresh candidate physically copies both files. Reuse counters now
            # describe actual candidate writes, not resemblance to active dist.
            self.assertEqual(result, {'reused_data_files': 0, 'copied_data_files': 2})
            self.assertEqual(assemble_data_release(dist, public, candidate),
                             {'reused_data_files': 2, 'copied_data_files': 0})
            self.assertFalse((candidate / 'api/old.json').exists())
            self.assertEqual((dist / 'api/value.json').read_text(), 'old')
            (public / 'api/value.json').write_text('future collection')
            (public / 'matches/same.json').write_text('future correction')
            self.assertEqual((candidate / 'api/value.json').read_text(), 'new')
            self.assertEqual((candidate / 'matches/same.json').read_text(), 'same')
            self.assertEqual((candidate / 'index.html').read_text(), 'shell')

    def test_equal_size_and_timestamp_cannot_hide_changed_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist, public, candidate = [root / p for p in ('dist', 'public', 'candidate')]
            for p in (dist / 'api', public / 'api', public / 'matches'):
                p.mkdir(parents=True)
            old, new = dist / 'api/a.json', public / 'api/a.json'
            old.write_text('old'); new.write_text('new')
            os.utime(new, ns=(old.stat().st_atime_ns, old.stat().st_mtime_ns))
            result = assemble_data_release(dist, public, candidate)
            self.assertEqual(result['copied_data_files'], 1)
            self.assertEqual((candidate / 'api/a.json').read_text(), 'new')

    def test_failed_promotion_restores_previous_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp); dist, candidate, previous = [build / p for p in ('dist', 'candidate', 'dist-previous')]
            dist.mkdir(); candidate.mkdir(); (dist / 'index.html').write_text('working')
            real_replace = os.replace
            def failing(source, target):
                if Path(source) == candidate:
                    raise OSError('simulated failure')
                real_replace(source, target)
            with patch('release_reuse.os.replace', side_effect=failing), self.assertRaises(OSError):
                promote(candidate, dist, previous, build)
            self.assertEqual((dist / 'index.html').read_text(), 'working')
            with self.assertRaises(RuntimeError):
                promote(candidate, dist, build.parent / 'outside', build)

    def test_unchanged_ten_player_detail_is_reused_but_raw_eligibility_or_corruption_rebuilds(self):
        spec = importlib.util.spec_from_file_location('detail_incremental_test', ROOT / 'work/players-preview-20261022/prepare-match-details.py')
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); front = root / 'front'; (front / 'public').mkdir(parents=True)
            raw_dir = root / 'data/raw'; raw_dir.mkdir(parents=True)
            raw = {'platformId': 'TEST', 'gameId': 1, 'gameStartTimestamp': 1000000, 'gameDuration': 600,
                   'queueId': 2400, 'gameMode': 'KIWI', 'participants': [
                       {'participantId': i, 'puuid': 'p' + str(i), 'teamId': 100 if i <= 5 else 200,
                        'championId': i, 'kills': 2, 'deaths': 1, 'assists': 3, 'win': i <= 5,
                        'totalDamageDealtToChampions': 1000 * i} for i in range(1, 11)]}
            raw_path = raw_dir / 'one.json'; raw_path.write_text(json.dumps(raw))
            mid = 'm-' + hashlib.sha256(b'TEST_1').hexdigest()[:20]
            p = {'id': 'alice', 'name': 'Alice', 'coverage': {'saved': 1}, 'by_champion': {}, 'reports': {},
                 'recent': [{'id': mid, 'started_ms': 1000000, 'duration': 600, 'stats_eligible': True,
                             'player': {'champion_id': 1, 'kills': 2, 'deaths': 1, 'assists': 3, 'win': True}}]}
            full = root / 'full.json'
            data = {'snapshot_kind': 'full', 'build_id': 'one', 'players': [p], 'companions': []}
            def run():
                full.write_text(json.dumps(data)); stream = io.StringIO()
                with patch.object(mod, 'PROJECT', root), patch.object(mod, 'ROOT', front), redirect_stdout(stream):
                    mod.prepare(full, incremental=True)
                return json.loads(stream.getvalue().splitlines()[-1])
            self.assertEqual(run()['rebuilt_matches'], 1)
            expected = (front / 'public/matches' / (mid + '.json')).read_bytes()
            self.assertEqual(run()['reused_matches'], 1)
            self.assertEqual(expected, (front / 'public/matches' / (mid + '.json')).read_bytes())
            raw['participants'][0]['totalDamageDealtToChampions'] = 9999
            raw_path.write_text(json.dumps(raw))
            self.assertEqual(run()['rebuilt_matches'], 1)
            p['recent'][0]['stats_eligible'] = False
            self.assertEqual(run()['rebuilt_matches'], 1)
            detail_path = front / 'public/matches' / (mid + '.json')
            self.assertIsNone(json.loads(detail_path.read_text())['players'][0]['performance'])
            detail_path.write_text('{}')
            self.assertEqual(run()['rebuilt_matches'], 1)


if __name__ == '__main__':
    unittest.main()
