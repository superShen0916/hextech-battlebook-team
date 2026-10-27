"""Release boundaries: content integrity, cache dependencies and publication identity."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
import release_files
import release_inputs
import nightly


class ContentInventoryTests(unittest.TestCase):
    def trees(self, base):
        source, target = base/'source', base/'target'
        source.mkdir(); target.mkdir()
        (source/'value.json').write_text('new')
        (target/'value.json').write_text('old')
        return source, target

    def test_same_size_and_mtime_do_not_hide_changes_and_source_is_read_once(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = self.trees(Path(folder))
            stamp = (source/'value.json').stat().st_mtime_ns
            os.utime(target/'value.json', ns=(stamp,stamp))
            real_hash = release_files.file_hash
            with patch('release_files.file_hash', wraps=real_hash) as hashed:
                inventory = release_files.inspect_tree(source)
                result = release_files.sync_tree(inventory,target)
            self.assertEqual(sum(Path(call.args[0]) == source/'value.json' for call in hashed.call_args_list),1)
            self.assertEqual(result['copied'],1)
            self.assertEqual(result['artifact_sha256'],inventory.digest)
            self.assertEqual((target/'value.json').read_text(),'new')

    def test_new_commands_reread_content_and_repair_later_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=self.trees(Path(folder))
            release_files.sync_tree(release_files.inspect_tree(source),target)
            self.assertEqual(release_files.sync_tree(release_files.inspect_tree(source),target)['copied'],0)
            stamp=(target/'value.json').stat().st_mtime_ns
            (target/'value.json').write_text('bad'); os.utime(target/'value.json',ns=(stamp,stamp))
            self.assertEqual(release_files.sync_tree(release_files.inspect_tree(source),target)['copied'],1)

    def test_source_changed_after_inventory_cannot_produce_successful_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=self.trees(Path(folder))
            inventory=release_files.inspect_tree(source)
            (source/'value.json').write_text('bad')
            with self.assertRaisesRegex(RuntimeError,'synced_content_mismatch'):
                release_files.sync_tree(inventory,target)

    def test_bad_copy_is_detected_by_complete_destination_check(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=self.trees(Path(folder))
            def broken_copy(_source, destination):
                Path(destination).write_text('bad')
            with patch('release_files.shutil.copy2',side_effect=broken_copy), \
                 self.assertRaisesRegex(RuntimeError,'synced_content_mismatch'):
                release_files.sync_tree(release_files.inspect_tree(source),target)

    def test_atomic_copy_detaches_legacy_hardlinks_and_removes_only_obsolete_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); source,target=self.trees(base)
            rollback=base/'keep.txt'; os.link(target/'value.json',rollback)
            (target/'obsolete.json').write_text('remove')
            result=release_files.sync_tree(release_files.inspect_tree(source),target)
            self.assertEqual(rollback.read_text(),'old')
            self.assertEqual((target/'value.json').read_text(),'new')
            self.assertEqual(result['removed'],1)

    def test_failed_replace_keeps_old_file_and_cleans_own_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=self.trees(Path(folder))
            with patch('release_files.os.replace',side_effect=OSError('busy')), self.assertRaises(OSError):
                release_files.sync_tree(release_files.inspect_tree(source),target)
            self.assertEqual((target/'value.json').read_text(),'old')
            self.assertEqual([p.name for p in target.iterdir()],['value.json'])

    def test_overlap_and_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); source,target=self.trees(base)
            with self.assertRaisesRegex(RuntimeError,'overlapping'):
                release_files.sync_tree(release_files.inspect_tree(source),source/'nested')
            with self.assertRaises(ValueError):
                release_files.FileTree(source,{'../outside':'a'*64})


class InputBoundaryTests(unittest.TestCase):
    def fixture(self,root):
        front=root/'work/players-preview-20261022'
        for name in ('app/static','scripts','haido','data/raw','tests/browser','config'):
            (root/name).mkdir(parents=True)
        for name in ('src','lib','public/share'):
            (front/name).mkdir(parents=True)
        for name in ('prepare-match-details.py','prepare-achievements.mjs','package.json'):
            (front/name).write_text('{}')
        (front/'src/view.css').write_text('one')
        (root/'haido/rating_lp.py').write_text('rating')
        for name in ('haido-baseline-v4.json','public-profiles.json','collection.json','stat-exclusions.json'):
            (root/'data'/name).write_text('{}')
        for name in release_inputs.DATA_SCRIPTS:
            (root/'scripts'/name).write_text('algorithm')
        return front

    def test_maintenance_edits_invalidate_validation_but_reuse_data(self):
        with tempfile.TemporaryDirectory() as folder, patch('release_inputs.database_signature',return_value='database'):
            root=Path(folder); front=self.fixture(root)
            (root/'scripts/workflow.py').write_text('before')
            data=release_inputs.data_inputs(root)
            validation=release_inputs.validation_inputs(root,front,'v22')
            (root/'scripts/workflow.py').write_text('after')
            self.assertEqual(data,release_inputs.data_inputs(root))
            self.assertNotEqual(validation,release_inputs.validation_inputs(root,front,'v22'))

    def test_css_does_not_rebuild_data_but_data_algorithm_changes_do(self):
        with tempfile.TemporaryDirectory() as folder, patch('release_inputs.database_signature',return_value='database'):
            root=Path(folder); front=self.fixture(root)
            before=release_inputs.data_inputs(root)
            (front/'src/view.css').write_text('two')
            self.assertEqual(before,release_inputs.data_inputs(root))
            (root/'scripts/build_recaps.py').write_text('changed algorithm')
            self.assertNotEqual(before,release_inputs.data_inputs(root))

    def test_generated_share_javascript_is_frontend_output_not_a_concurrent_source_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); front=self.fixture(root)
            code=release_inputs.validation_code_inputs(root,front,'v22')
            shell=release_inputs.frontend_inputs(front,'v22')
            (front/'public/share/achievements.js').write_text('generated output')
            self.assertEqual(code,release_inputs.validation_code_inputs(root,front,'v22'))
            self.assertNotEqual(shell,release_inputs.frontend_inputs(front,'v22'))


class PublishedIdentityTests(unittest.TestCase):
    def test_mark_records_actual_artifact_and_rejects_mismatched_report(self):
        for expected in ('a'*64,'b'*64,None):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                base=Path(folder); state=base/'state.json'; result=base/'result.json'
                state.write_text(json.dumps({'last_published_build_id':'old'}))
                data={'build_id':'data-id','release_directory_synced':True}
                if expected is not None:
                    data['artifact_sha256']=expected
                result.write_text(json.dumps(data))
                @contextlib.contextmanager
                def lock(_):
                    yield True
                with patch.multiple(nightly,ROOT=base,STATE=state,RESULT=result), \
                     patch('nightly._exclusive_lock',side_effect=lock), \
                     patch('nightly.check_release',return_value={'build_id':'data-id','artifact_sha256':'a'*64}), \
                     patch.object(sys,'argv',['nightly','--mark-published']), contextlib.redirect_stdout(io.StringIO()):
                    code=nightly.main()
                marked=json.loads(state.read_text())
                self.assertEqual(code,0 if expected in ('a'*64,None) else 1)
                if code==0:
                    self.assertEqual(marked['last_published_artifact_sha256'],'a'*64)
                else:
                    self.assertEqual(marked,{'last_published_build_id':'old'})
