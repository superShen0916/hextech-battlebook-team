"""Workflow selection and stale/failed publication protection, without real data/network."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
import workflow
import release_inputs
from check_state import publication_check


class ScopeTests(unittest.TestCase):
    def test_frontend_and_documentation_do_not_force_full_data_rebuild(self):
        plan = workflow.make_plan([workflow.FRONT_REL + 'src/Lobby.tsx', 'README.md'])
        self.assertEqual(plan['scope'], 'frontend')
        self.assertEqual(plan['build_mode'], '--data-only')
        self.assertFalse(plan['python_tests'])

    def test_data_rules_and_unknown_runtime_changes_select_wider_gates(self):
        self.assertEqual(workflow.make_plan(['data/stat-exclusions.json'])['scope'], 'data')
        for filename in ('haido/rating_lp.py', 'scripts/build_release.py', 'mystery.bin',
                         workflow.FRONT_REL + 'prepare-match-details.py', 'tests/browser/smoke.mjs'):
            with self.subTest(filename=filename):
                self.assertTrue(workflow.make_plan([filename])['python_tests'])

    def test_narrow_scope_cannot_hide_detected_backend_change(self):
        with self.assertRaisesRegex(ValueError, 'scope_too_narrow'):
            workflow.make_plan(['app/awards.py'], 'frontend')

    def test_explicit_file_cannot_escape_project_or_pass_another_drive(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'file_outside_project'):
                workflow.normalize_file('../outside', Path(folder))

    def test_docs_do_not_run_browser_or_build(self):
        plan = workflow.make_plan(['docs/PUBLIC-SITE.md'])
        self.assertEqual(plan['checks'], ['check_state'])
        self.assertIsNone(plan['build_mode'])


class ReceiptTests(unittest.TestCase):
    def receipt(self):
        return {'ok': True, 'ready': True, 'scope': 'pipeline',
                'source_sha256': 'source', 'dist_sha256': 'same', 'release_sha256': 'same'}

    def test_valid_receipt_can_be_rechecked_without_rebuilding(self):
        receipt = self.receipt()
        self.assertIs(workflow.checked_receipt(receipt, 'source', 'same', 'same'), receipt)

    def test_source_and_artifact_tampering_invalidate_receipt_even_with_same_build_id(self):
        for source, dist, release in (('changed', 'same', 'same'), ('source','changed','same'),
                                      ('source','same','changed')):
            with self.subTest(values=(source,dist,release)), self.assertRaises(RuntimeError):
                workflow.checked_receipt(self.receipt(), source, dist, release)

    def test_failed_or_incomplete_attempt_cannot_reuse_old_ready(self):
        for change in ({'ok':False}, {'ready':False}, {'scope':'frontend'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                workflow.checked_receipt({**self.receipt(), **change}, 'source','same','same','pipeline')

    def test_baseline_content_change_invalidates_source_even_if_database_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); (base / 'data').mkdir(); (base / 'haido').mkdir()
            (base / 'haido/rating_lp.py').write_text('rating')
            for name in ('haido-baseline-v4.json','public-profiles.json','collection.json','stat-exclusions.json'):
                (base / 'data' / name).write_text('{}')
            with patch.object(workflow,'ROOT',base), patch('release_inputs.tree_hash',return_value='tree'), \
                 patch('release_inputs.frontend_inputs',return_value='front'):
                before = workflow.source_identity('v22', 'same-database')
                (base / 'data/haido-baseline-v4.json').write_text('[]')
                self.assertNotEqual(before, workflow.source_identity('v22', 'same-database'))

    def test_failed_stage_and_timeout_cannot_be_marked_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for result in (3, subprocess.TimeoutExpired([], 1)):
                child = MagicMock()
                if isinstance(result, Exception):
                    child.wait.side_effect = result
                else:
                    child.wait.return_value = result
                with patch('workflow.subprocess.Popen') as popen, patch('workflow.stop_process_tree') as stop, \
                     contextlib.redirect_stdout(io.StringIO()):
                    popen.return_value.__enter__.return_value = child
                    with self.assertRaises(RuntimeError):
                        workflow.run_step(['unused'], out, out, 'failing', [], timeout=1)
                    self.assertEqual(stop.called, isinstance(result, Exception))

    def test_online_resource_set_covers_lazy_frontend_chunks_and_full_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            data = {
                'index.html':'<script src="/assets/main.js"></script>', 'intel.html':'', 'share/index.html':'',
                'assets/main.js':'main', 'assets/lazy.js':'lazy',
                'api/snapshot.json':json.dumps({'players':[{'detail_url':'/api/full.json','summary':{'games':42}}],
                                                'achievements_url':'/api/hall.json'}),
                'api/full.json':json.dumps({'recent':[{'id':'m-abc'}]}),
                'api/recaps/index.json':json.dumps({'nights':[{'date':'2026-10-24'}]}),
            }
            for name, value in data.items():
                file = base / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text(value)
            paths = workflow.online_paths(base)
            self.assertIn('assets/lazy.js', paths)
            self.assertIn('api/full.json', paths)
            self.assertIn('matches/m-abc.json', paths)
            self.assertIn('api/recaps/nights/2026-10-24.json', paths)

    def test_real_timed_out_child_is_terminated(self):
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs); children.append(child); return child
        with tempfile.TemporaryDirectory() as folder, patch('workflow.subprocess.Popen',side_effect=spawn), \
             contextlib.redirect_stdout(io.StringIO()):
            started = time.perf_counter()
            with self.assertRaisesRegex(RuntimeError,'step_timeout'):
                workflow.run_step([sys.executable,'-c','import time; time.sleep(30)'], Path(folder),
                                  Path(folder),'timeout',[],timeout=.2)
            self.assertIsNotNone(children[0].poll())
            self.assertLess(time.perf_counter()-started, 10)


class PublicationPhaseTests(unittest.TestCase):
    def test_pending_may_have_a_different_or_identical_data_build_id(self):
        for online in ('new','old'):
            self.assertTrue(publication_check('已同步未托管', 'new', online)['ok'])

    def test_claimed_published_must_match_and_unknown_phase_is_rejected(self):
        self.assertFalse(publication_check('已托管上线', 'new','old')['ok'])
        self.assertTrue(publication_check('已托管上线', 'new','new')['ok'])
        self.assertFalse(publication_check('构建完成', 'new','new')['ok'])


class PreparationFailureTests(unittest.TestCase):
    def scenario(self, fail_browser=False, lock_available=True, change_code=False):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); build = base / 'build'; build.mkdir()
            (base / 'data').mkdir(); (base / 'data/mayhem.sqlite').touch()
            receipt = build / 'receipt.json'
            receipt.write_text(json.dumps({'ok':True,'ready':True,'run_id':'old'}))
            (build / 'release-result.json').write_text(json.dumps({'build_id':'new'}))
            (build / 'data-state.json').write_text(json.dumps({'inputs':'data'}))
            log = base / 'build.log'; log.write_text('RELEASE_READY {"build_id":"new"}\n')
            steps = []
            def step(command, cwd, output, name, stages, env=None, timeout=1800):
                steps.append(name)
                if fail_browser and name == 'browser':
                    raise RuntimeError('simulated_browser_failure')
                return log
            @contextlib.contextmanager
            def lock(_path):
                yield lock_available
            with patch.multiple(workflow, ROOT=base, BUILD=build, RECEIPT=receipt,
                                FRONT=base/'front', RELEASE=base/'release'), \
                 patch('workflow.resolve_node', return_value=('node','v22')), \
                 patch('workflow.node_environment', return_value={}), \
                 patch('workflow._exclusive_lock', side_effect=lock), \
                 patch('workflow.source_identity', return_value='source'), \
                 patch('workflow.code_identity', side_effect=(['code','changed'] if change_code else None), return_value='code'), \
                 patch('workflow.data_inputs', return_value='data'), \
                 patch('workflow.frontend_inputs', return_value='front'), \
                 patch('workflow.can_reuse_frontend', return_value=True), \
                 patch('workflow.tree_hash', return_value='same'), \
                 patch('workflow.inspect_tree', return_value=MagicMock(digest='same')), \
                 patch('workflow.synchronize_release', side_effect=lambda _tree: steps.append('sync') or {'artifact_sha256':'same'}), \
                 patch('workflow.run_step', side_effect=step), \
                 patch.object(sys, 'argv', ['workflow','prepare','--files','scripts/workflow.py']), \
                 contextlib.redirect_stdout(io.StringIO()):
                code = workflow.main()
            return code, steps, json.loads(receipt.read_text())

    def test_browser_failure_does_not_sync_or_reuse_old_success(self):
        code, steps, receipt = self.scenario(fail_browser=True)
        self.assertEqual(code, 1)
        self.assertNotIn('sync', steps)
        self.assertFalse(receipt['ready'])
        self.assertFalse(receipt['ok'])
        self.assertNotEqual(receipt['run_id'], 'old')

    def test_sync_happens_only_after_browser_and_produces_bound_receipt(self):
        code, steps, receipt = self.scenario()
        self.assertEqual(code, 0)
        self.assertLess(steps.index('browser'), steps.index('sync'))
        self.assertTrue(receipt['ready'])
        self.assertEqual(receipt['source_sha256'], 'source')

    def test_lock_conflict_does_not_destroy_the_other_runs_receipt(self):
        code, steps, receipt = self.scenario(lock_available=False)
        self.assertEqual(code, 1)
        self.assertEqual(steps, [])
        self.assertEqual(receipt['run_id'], 'old')

    def test_code_changed_while_tests_or_build_were_running_is_not_published(self):
        code, steps, receipt = self.scenario(change_code=True)
        self.assertEqual(code, 1)
        self.assertNotIn('sync', steps)
        self.assertIn('code_changed_during_tests_or_build',receipt['error'])


if __name__ == '__main__':
    unittest.main()
