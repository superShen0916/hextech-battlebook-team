import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
import nightly
from node_runtime import resolve_node
from prune_builds import plan
from release_reuse import mirror_slot, promote


class NightlyPublicationTests(unittest.TestCase):
    def scenario(self, code, fresh, disk=None, manifest_id='new', online=True, collect_code=0,
                 last_artifact=None, last_build_id='published', upload_enabled=False, upload_error=False):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            result, state, reports, release = [base / n for n in ('result.json', 'state.json', 'reports', 'release')]
            (release / 'api').mkdir(parents=True)
            (release / 'api/manifest.json').write_text(json.dumps({'build_id': manifest_id}))
            result.write_text(json.dumps(disk if disk is not None else {'build_id': 'stale', 'release_directory_synced': True}))
            state.write_text(json.dumps({'last_published_build_id': last_build_id,
                                         'last_published_artifact_sha256': last_artifact}))
            if upload_enabled:
                (base/'config').mkdir()
                (base/'config/team.local.json').write_text(json.dumps(
                    {'repository':'owner/private','upload_after_nightly':True}))
            def run(script, extra, timeout):
                if script == nightly.COLLECT:
                    return {'exit': collect_code, 'tail': [], 'stderr': ''}
                return {'exit': code, 'tail': [], 'stderr': '', 'release_result': fresh}
            with patch.multiple(nightly, ROOT=base, STATE=state, RESULT=result, REPORTS=reports, RELEASE=release), \
                 patch.object(nightly, 'check_database_routes', return_value={}), \
                 patch.object(nightly, 'client_status', return_value={'online': online}), \
                 patch.object(nightly, 'run', side_effect=run), \
                 patch.object(nightly, 'retired_builds', return_value={'count': 0, 'mb': 0}), \
                 patch('team_data.publish', side_effect=RuntimeError('upload interrupted') if upload_error else None,
                       return_value={'ok':True,'build_id':'new','artifact_sha256':'a'*64}), \
                 patch.object(sys, 'argv', ['nightly.py']), redirect_stdout(io.StringIO()):
                exit_code = nightly.main()
            return exit_code, json.loads((reports / 'latest.json').read_text()), json.loads(state.read_text())

    def test_failed_build_cannot_publish_or_report_a_stale_success(self):
        for code in (2, 124):
            with self.subTest(code=code):
                exit_code, report, state = self.scenario(code, None)
                self.assertEqual(exit_code, 1)
                self.assertFalse(report['ok'])
                self.assertFalse(report['publish']['needed'])
                self.assertIsNone(report['publish']['current_build_id'])
                self.assertNotIn('release_directory_synced', report['build'])
                self.assertEqual(state['last_published_build_id'], 'published')

    def test_zero_exit_without_a_fresh_receipt_is_not_publishable(self):
        exit_code, report, _ = self.scenario(0, None)
        self.assertEqual(exit_code, 1)
        self.assertIn('build_result_unverified', report['reasons'])
        self.assertFalse(report['publish']['needed'])

    def test_matching_receipt_disk_result_and_release_manifest_can_publish(self):
        fresh = {'build_id': 'new', 'artifact_sha256': 'a'*64, 'release_directory_synced': True, 'frontend_reused': True}
        exit_code, report, _ = self.scenario(0, fresh, fresh)
        self.assertEqual(exit_code, 0)
        self.assertTrue(report['ok'])
        self.assertTrue(report['publish']['needed'])
        self.assertEqual(report['publish']['current_build_id'], 'new')

    def test_team_upload_failure_is_reported_without_blocking_website_publication(self):
        fresh={'build_id':'new','artifact_sha256':'a'*64,'release_directory_synced':True}
        code,report,_=self.scenario(0,fresh,fresh,upload_enabled=True,upload_error=True)
        self.assertEqual(code,0)
        self.assertTrue(report['publish']['needed'])
        self.assertFalse(report['team_data']['ok'])
        self.assertIn('team_data_upload_failed',report['reasons'])

    def test_team_upload_only_follows_successful_online_collection_and_build(self):
        fresh={'build_id':'new','artifact_sha256':'a'*64,'release_directory_synced':True}
        code,report,_=self.scenario(0,fresh,fresh,upload_enabled=True)
        self.assertEqual(code,0)
        self.assertTrue(report['team_data']['ok'])
        _,offline,_=self.scenario(0,None,online=False,upload_enabled=True)
        self.assertNotIn('team_data',offline)

    def test_mismatched_manifest_or_result_is_not_publishable(self):
        fresh = {'build_id': 'new', 'artifact_sha256': 'a'*64, 'release_directory_synced': True}
        for disk, manifest_id in ((fresh, 'wrong'), ({**fresh, 'other': True}, 'new')):
            exit_code, report, _ = self.scenario(0, fresh, disk, manifest_id)
            self.assertEqual(exit_code, 1)
            self.assertFalse(report['publish']['needed'])

    def test_failed_collection_does_not_build_or_publish(self):
        exit_code, report, _ = self.scenario(0, None, online=True, collect_code=2)
        self.assertEqual(exit_code, 1)
        self.assertFalse(report['build']['attempted'])
        self.assertFalse(report['publish']['needed'])

    def test_same_data_id_still_publishes_a_changed_frontend_artifact(self):
        fresh = {'build_id':'new','artifact_sha256':'a'*64,'release_directory_synced':True}
        code, report, _ = self.scenario(0,fresh,fresh,last_artifact='b'*64,last_build_id='new')
        self.assertEqual(code,0)
        self.assertTrue(report['publish']['needed'])
        code, report, _ = self.scenario(0,fresh,fresh,last_artifact='a'*64,last_build_id='new')
        self.assertEqual(code,0)
        self.assertFalse(report['publish']['needed'])
        # Legacy state knows only data ID; it cannot prove the frontend matches.
        code, report, _ = self.scenario(0,fresh,fresh,last_build_id='new')
        self.assertTrue(report['publish']['needed'])

    def test_success_without_a_complete_artifact_identity_is_not_publishable(self):
        fresh = {'build_id':'new','release_directory_synced':True}
        code, report, _ = self.scenario(0,fresh,fresh)
        self.assertEqual(code,1)
        self.assertFalse(report['publish']['needed'])

    def test_offline_direct_invocation_does_not_collect_build_or_publish(self):
        code, report, _ = self.scenario(0,None,online=False)
        self.assertEqual(code,0)
        self.assertFalse(report['collect']['attempted'])
        self.assertFalse(report['build']['attempted'])
        self.assertFalse(report['publish']['needed'])

    def test_run_only_parses_receipts_from_successful_processes(self):
        from types import SimpleNamespace
        for code in (0, 2):
            with patch('nightly.subprocess.run', return_value=SimpleNamespace(returncode=code,
                    stdout='RELEASE_READY {"build_id":"fresh"}\n', stderr='')):
                result = nightly.run('unused.py', [], 5)
            self.assertEqual(result['release_result'], {'build_id': 'fresh'} if code == 0 else None)


class BoundedBuildTests(unittest.TestCase):
    def test_many_promotions_keep_only_two_fixed_inactive_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            dist, candidate, previous = [base / name for name in ('dist', 'candidate', 'dist-previous')]
            dist.mkdir(); (dist / 'index.html').write_text('0')
            with patch('release_reuse.shutil.rmtree', side_effect=AssertionError('no whole-tree deletion')):
                for index in range(1, 12):
                    candidate.mkdir(exist_ok=True)
                    (candidate / 'index.html').write_text(str(index))
                    promote(candidate, dist, previous, base)
                    self.assertEqual((dist / 'index.html').read_text(), str(index))
                    self.assertEqual((previous / 'index.html').read_text(), str(index - 1))
                    self.assertFalse(list(base.glob('dist-retired-*')))
                    self.assertLessEqual(len(list(base.iterdir())), 3)

    def test_mirror_detaches_shared_old_files_and_removes_obsolete_shards(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            active, slot, public = [base / n for n in ('active', 'candidate', 'public')]
            for directory in (active, slot, public):
                directory.mkdir()
            (active / 'data.json').write_text('old')
            os.link(active / 'data.json', slot / 'data.json')
            (slot / 'obsolete.json').write_text('remove me')
            (public / 'data.json').write_text('new')
            mirror_slot(slot, {'data.json': public / 'data.json'})
            self.assertEqual((active / 'data.json').read_text(), 'old')
            self.assertEqual((slot / 'data.json').read_text(), 'new')
            self.assertFalse((slot / 'obsolete.json').exists())

    def test_failed_rotation_restores_both_working_and_previous_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            dist, candidate, previous = [base / n for n in ('dist', 'candidate', 'dist-previous')]
            for directory, value in ((dist, 'working'), (candidate, 'new'), (previous, 'older')):
                directory.mkdir(); (directory / 'index.html').write_text(value)
            replace = os.replace
            def failing(source, destination):
                if Path(source) == candidate:
                    raise OSError('simulated failure')
                replace(source, destination)
            with patch('release_reuse.os.replace', side_effect=failing), self.assertRaises(OSError):
                promote(candidate, dist, previous, base)
            self.assertEqual((dist / 'index.html').read_text(), 'working')
            self.assertEqual((previous / 'index.html').read_text(), 'older')

    def test_cleanup_plan_never_selects_active_or_fixed_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name in ('candidate', 'dist-previous', 'rotation-previous', 'keep', 'candidate-' + 'a'*32,
                         'dist-retired-20261024-202806-639581'):
                (base / name).mkdir(); (base / name / 'index.html').write_text('generated')
            self.assertEqual({Path(r['path']).name for r in plan(base)},
                             {'candidate-' + 'a'*32, 'dist-retired-20261024-202806-639581'})

    def test_cleanup_plan_refuses_private_data_in_legacy_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / ('candidate-' + 'a'*32)
            directory.mkdir(); (directory / 'unexpected.sqlite').write_text('private')
            with self.assertRaisesRegex(RuntimeError, 'unexpected_private_file'):
                plan(Path(folder))

    def test_pinned_runtime_is_independent_of_path_and_rejects_version_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); (base / 'config').mkdir()
            node = base / 'node.exe'; node.write_bytes(b'placeholder')
            (base / 'config/runtime.json').write_text(json.dumps({'node_executable': str(node), 'node_version': '22.23.3'}))
            for path in ('other-assistant-runtime', ''):
                with patch.dict(os.environ, {'PATH': path}), patch('node_runtime.subprocess.check_output', return_value='v22.23.3\n'):
                    self.assertEqual(resolve_node(base), (str(node), 'v22.23.3'))
            with patch('node_runtime.subprocess.check_output', return_value='v22.22.2\n'), self.assertRaisesRegex(RuntimeError, 'version_mismatch'):
                resolve_node(base)
