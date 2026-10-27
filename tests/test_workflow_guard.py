import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'scripts')]
from workflow_guard import check_database_routes, collector_result, sync_exit_code
import sync_release


class WorkflowGuardTests(unittest.TestCase):
    def test_stopped_event_is_not_hidden_by_later_successful_summary(self):
        text = '\n'.join(json.dumps(row) for row in [
            {'stopped': 'rate_limited_stop_batch/429'},
            {'account': 'test', 'fetched': 2, 'coverage': {'complete': 3}}])
        status = collector_result(text, 0)
        self.assertFalse(status['ok'])
        self.assertTrue(status['stopped'])
        self.assertEqual(sync_exit_code({'steps': [{'step': 'fetch', **status}]}), 4)

    def test_gaps_and_failed_local_steps_block_success_but_skipped_history_does_not(self):
        for text, code in [('{"outcome":"finished_with_gaps"}', 4),
                           ('{"coverage":{"failed":1}}', 0), ('', 1)]:
            status = collector_result(text, code)
            self.assertFalse(status['ok'])
        good = collector_result('{"coverage":{"complete":100,"skipped":200}}', 0)
        self.assertTrue(good['ok'])
        self.assertEqual(sync_exit_code({'steps': [{'exit': 0, 'ok': True}]}), 0)
        self.assertEqual(sync_exit_code({'steps': [{'step': 'attribution', 'exit': 1}]}), 4)

    def make_layout(self, root):
        active = root / 'data/mayhem.sqlite'
        legacy = root / 'work/gopher-pilot-20261021/data/mayhem.sqlite'
        for path in (active,):
            path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.closing(sqlite3.connect(path)) as db, db:
                db.executescript('CREATE TABLE matches(match_key TEXT); CREATE TABLE accounts(account_key TEXT, puuid TEXT); CREATE TABLE settings(key TEXT,value TEXT);')
                db.execute('INSERT INTO accounts VALUES(?,?)', ('test', 'test-identity'))
                db.execute('INSERT INTO settings VALUES(?,?)', ('active_account', json.dumps('test')))
        config = root / 'data/public-profiles.json'
        (root / 'data/collection.json').write_text(json.dumps(dict(client_profile='test', primary_profile='test', default_profile='test')))
        config.write_text(json.dumps([{'id': 'test', 'expected_puuid': 'test-identity',
            'database': 'mayhem.sqlite'}]))
        return active, legacy, config

    def test_routes_refuse_wrong_database_and_missing_identity_without_creating_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active, legacy, config = self.make_layout(root)
            self.assertEqual(check_database_routes(root)['profile_databases'], 1)
            rows = json.loads(config.read_text())
            rows[0]['database'] = 'another.sqlite'
            config.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'database_mismatch'):
                check_database_routes(root)
            rows[0]['database'] = 'mayhem.sqlite'
            rows[0]['expected_puuid'] = 'wrong-identity'
            config.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'identity_missing'):
                check_database_routes(root)
            active.unlink()
            with self.assertRaises(sqlite3.OperationalError):
                check_database_routes(root)
            self.assertFalse(active.exists())

    def test_sync_detects_same_size_same_timestamp_content_changes_and_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'new-chat-2'
            dist, pub = base / 'dist', base / 'outputs/public-site-20261022b'
            for path in (dist, pub):
                (path / 'api').mkdir(parents=True)
                (path / 'api/manifest.json').write_text('{"build_id":"same"}')
                (path / 'api/snapshot.json').write_text('{}')
                (path / 'index.html').write_text('same')
            (pub / 'index.html').write_text('DIFF')
            stamp = (dist / 'index.html').stat().st_mtime_ns
            os.utime(pub / 'index.html', ns=(stamp, stamp))
            with patch.object(sync_release, 'ROOT', base), patch.object(sync_release, 'DIST', dist), patch.object(sync_release, 'PUB', pub):
                from release_files import inspect_tree
                self.assertNotEqual(inspect_tree(dist).files['index.html'], inspect_tree(pub).files['index.html'])
                with patch.object(sys, 'argv', ['sync_release', '--check']), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(SystemExit, 'SYNC_DIFF'):
                        sync_release.main()

    def test_build_refuses_busy_lock_before_subprocess_or_data_work(self):
        spec = importlib.util.spec_from_file_location('build_lock_test', ROOT / 'scripts/build_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        @contextlib.contextmanager
        def busy(_):
            yield False
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, 'ROOT', Path(tmp)), \
             patch.object(module, 'NODE', 'node'), patch('public_site._exclusive_lock', busy), \
             patch.object(sys, 'argv', ['build_release']), patch.object(module.subprocess, 'run') as run, \
             patch.object(module.subprocess, 'check_output') as output:
            with self.assertRaisesRegex(RuntimeError, 'release_already_running'):
                module.main()
            run.assert_not_called()
            output.assert_not_called()

    def test_sync_refuses_busy_lock_without_network(self):
        @contextlib.contextmanager
        def busy(_):
            yield False
        with patch('public_site._exclusive_lock', busy), patch.object(sys, 'argv', ['sync_new_matches']), \
             patch('subprocess.run') as run:
            with self.assertRaisesRegex(SystemExit, 'sync_already_running'):
                runpy.run_path(str(ROOT / 'work/gopher-pilot-20261021/scripts/sync_new_matches.py'), run_name='__main__')
            run.assert_not_called()

    def test_sync_main_writes_incomplete_report_and_exit_for_owner_or_attribution_failure(self):
        spec = importlib.util.spec_from_file_location('sync_workflow_test', ROOT / 'work/gopher-pilot-20261021/scripts/sync_new_matches.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'argv', ['sync_new_matches']):
            spec.loader.exec_module(module)
        from store import Store
        for owner_fails, attribution_fails in [(True, False), (False, True), (False, False)]:
            with self.subTest(owner_fails=owner_fails, attribution_fails=attribution_fails), tempfile.TemporaryDirectory() as tmp:
                pilot = Path(tmp)
                Store(pilot / 'data')
                (pilot / 'teammate-id-listing.json').write_text('{"gopher_puuid":"test","teammates":[]}')
                report = pilot / 'report.json'
                args = SimpleNamespace(interval=4, cap=40, threshold=100, full_backfill=False,
                    skip_listing=True, yes=True, report=str(report))
                def run(script, *unused):
                    if script == 'collect_gopher_pilot.py':
                        output = {'phase': 'stopped', 'outcome': 'incomplete'} if owner_fails else {'outcome': 'complete_available_window'}
                        return SimpleNamespace(returncode=4 if owner_fails else 0, stdout=json.dumps(output))
                    return SimpleNamespace(returncode=1 if script == 'fix_all_attribution.py' and attribution_fails else 0, stdout='')
                with patch.object(module, 'PILOT', pilot), patch.object(module, 'DATABASE', pilot / 'data/mayhem.sqlite'), patch.object(module, 'args', args), \
                     patch.object(module, 'run', run), patch.object(module, 'check_database_routes', return_value={}), \
                     contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as result:
                        module.main()
                failed = owner_fails or attribution_fails
                self.assertEqual(result.exception.code, 4 if failed else 0)
                self.assertEqual(json.loads(report.read_text())['status'], 'incomplete' if failed else 'complete')


if __name__ == '__main__':
    unittest.main()
