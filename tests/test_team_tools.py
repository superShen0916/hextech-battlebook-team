"""Safety and end-to-end data installation tests for team distribution."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'app')]
import team_data
import team_source
from node_runtime import resolve_node


def make_bundle(base):
    payloads = {name:b'{}' for name in team_data.REQUIRED}
    database = base/'sample.sqlite'
    with closing(sqlite3.connect(database)) as db:
        db.executescript('CREATE TABLE matches(id INTEGER); INSERT INTO matches VALUES(1);'
                         'CREATE TABLE accounts(puuid TEXT); INSERT INTO accounts VALUES("sample");')
    payloads['data/mayhem.sqlite'] = database.read_bytes()
    payloads['data/public-profiles.json'] = b'[{"id":"one","database":"mayhem.sqlite","expected_puuid":"sample"}]'
    payloads['data/collection.json'] = b'{"client_profile":"one","primary_profile":"one","default_profile":"one"}'
    info = {'format':1,'database_matches':1,'build_id':'sample','files':
            {k:hashlib.sha256(v).hexdigest() for k,v in payloads.items()}}
    archive = base/'bundle.zip'
    with zipfile.ZipFile(archive,'w') as output:
        output.writestr('bundle.json',json.dumps(info))
        for name, content in payloads.items():
            output.writestr(name,content)
    return archive


class TeamBundleTests(unittest.TestCase):
    def test_install_real_sqlite_and_block_implicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); archive=make_bundle(base); checkout=base/'checkout';checkout.mkdir()
            result=team_data.install(archive,checkout)
            self.assertTrue(result['ok'])
            with closing(sqlite3.connect(checkout/'data/mayhem.sqlite')) as db:
                self.assertEqual(db.execute('select count(*) from matches').fetchone()[0],1)
            with self.assertRaisesRegex(RuntimeError,'existing_data'):
                team_data.install(archive,checkout)
            self.assertTrue(team_data.install(archive,checkout,True)['ok'])

    def test_invalid_hash_and_traversal_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); archive=make_bundle(base)
            with zipfile.ZipFile(archive) as source:
                values={name:source.read(name) for name in source.namelist()}
            for extra in ('../outside','data/../../outside',team_data.FRONT+'/public/../../outside','C:/outside'):
                info=json.loads(values['bundle.json']);info['files'][extra]=hashlib.sha256(b'x').hexdigest()
                bad=base/'bad.zip'
                with zipfile.ZipFile(bad,'w') as output:
                    for name,content in values.items():output.writestr(name,json.dumps(info) if name=='bundle.json' else content)
                    output.writestr(extra,b'x')
                with self.assertRaisesRegex(ValueError,'unsafe_bundle_member'):
                    team_data.verify_archive(bad)
            info=json.loads(values['bundle.json']);info['files']['data/collection.json']='0'*64
            with zipfile.ZipFile(base/'bad.zip','w') as output:
                for name,content in values.items():output.writestr(name,json.dumps(info) if name=='bundle.json' else content)
            with self.assertRaisesRegex(ValueError,'bundle_hash_mismatch'):
                team_data.verify_archive(base/'bad.zip')

    def test_refuses_publisher_and_open_database(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);archive=make_bundle(base);checkout=base/'checkout';checkout.mkdir()
            marker=checkout/'.wbapp_test.genie';marker.write_text('binding')
            with self.assertRaisesRegex(RuntimeError,'refuse_install_on_publisher'):
                team_data.install(archive,checkout)
            marker.unlink();(checkout/'data').mkdir();(checkout/'data/mayhem.sqlite-wal').write_bytes(b'pending')
            with self.assertRaisesRegex(RuntimeError,'sidecars'):
                team_data.install(archive,checkout)

    def test_public_game_data_is_allowed_only_for_canonical_repository(self):
        with patch('team_data.gh', return_value=json.dumps({
                'nameWithOwner': team_data.REPOSITORY, 'isPrivate': False})):
            team_data.check_repository(team_data.REPOSITORY.lower())
        with patch('team_data.gh', return_value='{"nameWithOwner":"owner/public","isPrivate":false}'):
            with self.assertRaisesRegex(ValueError, 'public_data_repository_not_authorized'):
                team_data.check_repository('owner/public')
            # A renamed repository can redirect: check the resolved destination too.
            with self.assertRaisesRegex(ValueError, 'public_data_repository_not_authorized'):
                team_data.check_repository(team_data.REPOSITORY)
        with patch('team_data.gh', return_value='{"nameWithOwner":"owner/private","isPrivate":true}'):
            team_data.check_repository('owner/private')
        with patch('team_data.gh') as github:
            with self.assertRaisesRegex(ValueError, 'invalid_repository'):
                team_data.check_repository('owner/public --bad-argument')
            github.assert_not_called()

    def test_failed_install_restores_overwritten_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);archive=make_bundle(base);checkout=base/'checkout';checkout.mkdir()
            (checkout/'data').mkdir();old=checkout/'data/collection.json';old.write_text('old')
            real_replace=os.replace
            def fail(src,dst):
                if str(dst).endswith('snapshot.full.json'):raise OSError('disk failure')
                return real_replace(src,dst)
            with patch('team_data.os.replace',side_effect=fail),self.assertRaises(OSError):
                team_data.install(archive,checkout)
            self.assertEqual(old.read_text(),'old')
            self.assertFalse((checkout/'data/mayhem.sqlite').exists())

    def test_sqlite_backup_includes_wal_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            with closing(sqlite3.connect(base/'live.sqlite')) as db:
                db.execute('pragma journal_mode=wal');db.executescript('create table matches(id);insert into matches values(1);')
                self.assertEqual(team_data.database_backup(base/'live.sqlite',base/'copy.sqlite'),1)


class SourceAndRuntimeTests(unittest.TestCase):
    def test_export_includes_license_without_generating_owner_diaries(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'project'; source.mkdir()
            (source/'LICENSE').write_text('sample license', encoding='utf-8')
            (source/'STATUS.md').write_text('owner runtime status', encoding='utf-8')
            (source/'docs/history').mkdir(parents=True)
            (source/'docs/history/CHANGELOG.md').write_text('local operations', encoding='utf-8')
            inventory = b'LICENSE\0STATUS.md\0docs/history/CHANGELOG.md\0'
            with patch('team_source.subprocess.check_output', return_value=inventory):
                result = team_source.export(source, base/'export/source')
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertEqual(archive.read('LICENSE'), b'sample license')
                self.assertIn('AGENTS.md', archive.namelist())
                self.assertNotIn('STATUS.md', archive.namelist())
                self.assertNotIn('docs/history/CHANGELOG.md', archive.namelist())

    def test_first_build_creates_missing_backup_report_directory(self):
        import reconcile_archives
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            with patch.multiple(reconcile_archives,ROOT=base,DATABASES=[]), \
                 patch.object(sys,'argv',['reconcile_archives','--apply']), \
                 patch('builtins.print'):
                reconcile_archives.main()
            self.assertEqual(json.loads((base/'backups/maintenance-reconcile.json').read_text()),[])

    def test_source_never_carries_local_history_identity_or_generated_scores(self):
        for name in ('STATUS.md','docs/HISTORY.md','docs/history/CHANGELOG.md','data/public-profiles.json',
                     'haido/haido_scores_lp.json','.git/config','work/players-preview-20261022/_archive/old.py'):
            self.assertFalse(team_source.selected(name),name)
        self.assertTrue(team_source.selected('app/awards.py'))
        self.assertTrue(team_source.selected('docs/TEAM-GUIDE.md'))
        self.assertTrue(team_source.selected('LICENSE'))

    def test_node_location_is_portable_but_version_is_still_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);(base/'config').mkdir();fake=base/'node.exe';fake.write_bytes(b'node')
            (base/'config/runtime.json').write_text('{"node_version":"22.23.3","node_executable":"node"}')
            (base/'config/runtime.local.json').write_text(json.dumps({'node_executable':str(fake),'node_version':'1'}))
            with patch.dict(os.environ,{'BATTLEBOOK_NODE':''}),patch('node_runtime.subprocess.check_output',return_value='v22.23.3'):
                self.assertEqual(resolve_node(base)[0],str(fake))
            with patch.dict(os.environ,{'BATTLEBOOK_NODE':''}),patch('node_runtime.subprocess.check_output',return_value='v22.1.0'):
                with self.assertRaisesRegex(RuntimeError,'version_mismatch'):resolve_node(base)


if __name__=='__main__':
    unittest.main()
