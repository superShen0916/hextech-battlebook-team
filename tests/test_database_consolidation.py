import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'scripts'), str(ROOT / 'tests')]
from consolidate_database import consolidate, retire_timelines
from project_paths import profile_account
from store import Store
from test_share_report import game
from workflow_guard import check_database_routes


class ConsolidationTests(unittest.TestCase):
    def fixture(self, root):
        main = Store(root / 'data')
        # Use another temporary directory first: the live retired path is guarded.
        source = Store(root / 'pool')
        owner = SimpleNamespace(platform='TEST', account_key='TEST:OWNER',
            account={'puuid': 'OWNER-A', 'gameName': 'Owner', 'tagLine': 'TEST'})
        ally = SimpleNamespace(platform='TEST', account_key='TEST:ALLY',
            account={'puuid': 'ALLY-A', 'gameName': 'Ally', 'tagLine': 'TEST'})
        main.register(owner); source.register(owner); source.register(ally)
        main.put('TEST:OWNER', game(1)); main.put('TEST:OWNER', game(3))
        main.put_timeline('TEST_3', 'test', {'frames': [{'timestamp': 1, 'events': [{'timestamp': 1, 'type': 'TEST'}]}]})
        source.put('TEST:OWNER', game(1)); source.put('TEST:OWNER', game(2))
        with main.connect() as db:
            db.execute('INSERT INTO settings VALUES(?,?)', ('legacy-only-setting', 'true'))
        source_path = root / 'work/gopher-pilot-20261021/data/mayhem.sqlite'
        source_path.parent.mkdir(parents=True)
        source.path.replace(source_path)
        profiles = [{'id': 'personal', 'expected_puuid': 'OWNER-A', 'database': '../work/gopher-pilot-20261021/data/mayhem.sqlite'},
                    {'id': 'gopher', 'expected_puuid': 'ALLY-A', 'database': '../work/gopher-pilot-20261021/data/mayhem.sqlite'}]
        (root / 'data/public-profiles.json').write_text(json.dumps(profiles))
        (root / 'data/collection.json').write_text('{"client_profile":"personal","primary_profile":"gopher","default_profile":"personal"}')
        (root / 'data/haido-baseline-v4.json').write_text('frozen-test-baseline')
        (root / 'data/public-site.json').write_text('{"token":"synthetic-old-uploader"}')
        return source_path

    def test_preview_is_read_only_and_apply_leaves_one_db_keeps_settings_identity_and_restore_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            old = self.fixture(root)
            before = (root / 'data/mayhem.sqlite').read_bytes()
            self.assertEqual(consolidate(root)['status'], 'preview')
            self.assertEqual(before, (root / 'data/mayhem.sqlite').read_bytes())
            report = consolidate(root, apply=True)
            self.assertEqual(report['status'], 'single_database')
            self.assertFalse(old.exists())
            self.assertEqual(check_database_routes(root)['active_matches'], 3)
            self.assertEqual(report['after']['timeline_events'], 1)
            self.assertEqual(report['added_from_legacy']['matches'], 1)
            self.assertFalse((root / 'data/public-site.json').exists())
            self.assertTrue((root / report['backup'] / 'retired-public-site.json').exists())
            self.assertEqual((root / 'data/haido-baseline-v4.json').read_text(), 'frozen-test-baseline')
            with contextlib.closing(sqlite3.connect(root / 'data/mayhem.sqlite')) as db:
                self.assertEqual(json.loads(db.execute("SELECT value FROM settings WHERE key='active_account'").fetchone()[0]), 'TEST:OWNER')
                self.assertEqual(profile_account(db, 'gopher', root / 'data')['puuid'], 'ALLY-A')
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='legacy-only-setting'").fetchone()[0], 'true')
            self.assertEqual(consolidate(root, apply=True)['status'], 'already_single_database')

    def test_registration_without_activation_and_pinned_store_do_not_change_client_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            def account(key):
                return SimpleNamespace(platform='TEST', account_key=key,
                    account={'puuid': key, 'gameName': key, 'tagLine': 'TEST'})
            store.register(account('client'))
            store.register(account('target'), activate=False)
            self.assertEqual(store.account()['puuid'], 'client')
            self.assertEqual(Store(tmp, account_key='target').account()['puuid'], 'target')
            self.assertEqual(store.get('active_account'), 'client')

    def test_duplicate_operational_database_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, 'duplicate_database'):
                check_database_routes(root)

    def test_failed_pool_retirement_rolls_back_root_and_keeps_both_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            pool = self.fixture(root)
            before_profiles = (root / 'data/public-profiles.json').read_bytes()
            original_replace = Path.replace
            def fail_pool(path, target):
                if path == pool:
                    raise OSError('synthetic locked source')
                return original_replace(path, target)
            with patch.object(Path, 'replace', fail_pool), self.assertRaisesRegex(OSError, 'locked source'):
                consolidate(root, apply=True)
            self.assertTrue(pool.is_file())
            self.assertEqual((root / 'data/public-profiles.json').read_bytes(), before_profiles)
            with contextlib.closing(sqlite3.connect(root / 'data/mayhem.sqlite')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM matches').fetchone()[0], 2)

    def test_frame_retirement_keeps_every_match_timestamp_and_frozen_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.fixture(root)
            consolidate(root, apply=True)
            before = retire_timelines(root)
            self.assertEqual(before['remove']['timeline_events'], 1)
            report = retire_timelines(root, apply=True)
            self.assertEqual(report['status'], 'timelines_retired')
            self.assertEqual(report['matches'], 3)
            with contextlib.closing(sqlite3.connect(root / 'data/mayhem.sqlite')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM timeline_events').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM timelines').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT started_ms FROM matches WHERE match_key=?', ('TEST_3',)).fetchone()[0], 300000)
            self.assertEqual((root / 'data/haido-baseline-v4.json').read_text(), 'frozen-test-baseline')

    def test_export_pins_owner_even_when_active_account_is_another_player(self):
        from public_site import load_public_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            owner = SimpleNamespace(platform='TEST', account_key='TEST:OWNER',
                account={'puuid': 'OWNER-SECRET', 'gameName': 'Owner', 'tagLine': 'TEST'})
            ally = SimpleNamespace(platform='TEST', account_key='TEST:ALLY',
                account={'puuid': 'ALLY-A', 'gameName': 'Ally', 'tagLine': 'TEST'})
            store.register(owner); store.register(ally)
            store.put(owner.account_key, game(1)); store.put(ally.account_key, game(1))
            snapshot = load_public_snapshot(store.path, static_directory=Path(tmp) / 'absent', owner_puuid='OWNER-SECRET')
            self.assertEqual(snapshot['owner']['name'], 'Owner')
            self.assertEqual(store.get('active_account'), ally.account_key)


if __name__ == '__main__':
    unittest.main()
