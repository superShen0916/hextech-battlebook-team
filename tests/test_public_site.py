"""Public export tests: only synthetic records, temporary databases, mocked HTTP."""
import copy
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import SourceError
from public_site import (build_public_snapshot, compact_public_snapshot, load_public_snapshot, push_public_snapshot,
                         watch_public_site, _NoRedirect, _exclusive_lock)
from recover import run_recovery
from store import Store
from sync import run_sync, sync_lock
from test_share_report import game


class Response(io.BytesIO):
    status = 200


class FakeSource:
    platform = 'TEST'
    account_key = 'TEST:OWNER-SECRET'
    account = {'puuid': 'OWNER-SECRET', 'gameName': 'Owner', 'tagLine': 'SECRET-TAG'}
    _token = 'PRIVATE-TOKEN'

    def __init__(self):
        def unavailable(*args, **kwargs):
            raise SourceError('synthetic_local_unavailable')
        self._local = SimpleNamespace(base='https://127.0.0.1:1', authorization='PRIVATE-AUTH',
                                      opener=SimpleNamespace(open=unavailable))

    def list_ids(self, start, count):
        return ['TEST_1', 'TEST_2'][start:start + count]

    def summary(self, mid):
        if mid == 'TEST_2':
            raise SourceError('synthetic_missing_match', 503)
        raw = {'platformId': 'TEST', 'gameId': 1, 'queueId': 2400, 'gameMode': 'KIWI',
               'gameCreation': 1000, 'gameDuration': 600, 'endOfGameResult': 'GameComplete',
               'gameVersion': '16.20.1', 'participants': []}
        for pid in range(1, 11):
            player = {'participantId': pid, 'puuid': 'OWNER-SECRET' if pid == 1 else f'PRIVATE-{pid}',
                      'teamId': 100 if pid <= 5 else 200, 'championId': pid, 'kills': 1,
                      'deaths': 1, 'assists': 1, 'win': pid <= 5, 'totalDamageDealtToChampions': 100}
            player.update({f'playerAugment{i}': 0 for i in range(1, 7)})
            raw['participants'].append(player)
        return raw

    def get(self, *args, **kwargs):
        raise SourceError('synthetic_remote_unavailable')


class PublicSiteTests(unittest.TestCase):
    def test_explicitly_disabled_legacy_upload_never_reads_snapshot_or_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'public-site.json').write_text(json.dumps({'enabled': False}), encoding='utf-8')
            with patch('public_site.load_public_snapshot') as load, patch('urllib.request.build_opener') as network:
                self.assertEqual(push_public_snapshot(directory, force=True), {'status': 'disabled'})
                load.assert_not_called()
                network.assert_not_called()

    def config(self, directory, token='ONLY-UPLOAD-SECRET', url='https://example.chatgpt.site'):
        path = Path(directory) / 'public-site.json'
        path.write_text(json.dumps({'url': url, 'token': token}), encoding='utf-8')

    def test_public_whitelist_companion_scope_and_hero_views(self):
        records = [game(i) for i in range(1, 11)]
        records += [game(i, friend='TOO-SMALL', name='Small') for i in range(20, 23)]
        records[0]['participants'][1]['champion_id'] = 33
        for match in records:
            match['self']['raw'] = {'client_token': 'CLIENT-SECRET'}
            match['self']['performance']['raw'] = 'PERFORMANCE-SECRET'
        before = copy.deepcopy(records)
        static = {'champions': {'1': {'name': 'Hero', 'icon_url': '/assets/champions/1.png', 'raw': 'SECRET'}},
                  'items': {'1001': {'name': 'Boots', 'icon_url': 'https://tracking.example/x.png'}},
                  'augments': {'100': {'name': 'Hex', 'description': 'Known explanation', 'rarity': 'gold',
                                       'icon_url': '/assets/augments/100.png', 'raw': 'SECRET'}}}
        result = build_public_snapshot(records, {'game_name': 'Owner', 'puuid': 'OWNER-SECRET',
                                                 'tag_line': 'SECRET-TAG'}, static)
        self.assertEqual(result['owner'], {'name': 'Owner'})
        self.assertEqual(len(result['companions']), 1)
        friend = result['companions'][0]
        self.assertEqual(friend['id'], 'c1')
        self.assertEqual(friend['summary']['dpm'], 400)
        self.assertEqual(friend['by_champion']['33']['summary']['games'], 1)
        self.assertEqual(len(friend['recent']), 10)
        self.assertTrue(all(row['id'].startswith('m') for row in friend['recent']))
        self.assertEqual(result['static']['items']['1001']['icon_url'], '')
        self.assertEqual(set(result['reports']), {'20', '30'})
        self.assertEqual(result['overview']['companions'], 1)
        self.assertEqual(result['reports']['20']['overview']['companions'], 0)
        serialized = json.dumps(result, allow_nan=False)
        for value in ('puuid', 'tag_line', 'account_key', 'match_key', 'raw', 'OWNER-SECRET',
                      'ALLY-A', 'TEST_1', 'CLIENT-SECRET', 'PERFORMANCE-SECRET', 'SECRET-TAG'):
            self.assertNotIn(value, serialized)
        self.assertEqual(records, before)

    def test_lean_snapshot_preserves_used_data_and_limits_public_float_precision(self):
        records = [game(i) for i in range(1, 11)]
        for match in records:
            match['self']['damage_share'] = 1 / 3
            match['self']['performance'].update(dimensions={'damage': 22.333333333333},
                                                 points={'damage': 13.999999999999})
        before = copy.deepcopy(records)
        snapshot = build_public_snapshot(records)
        self.assertEqual(len(snapshot['personal']['recent']), 10)
        self.assertEqual(len(snapshot['companions'][0]['recent']), 10)
        for view in [snapshot['personal']] + snapshot['companions']:
            self.assertNotIn('comparison', view)
            self.assertNotIn('pairs', view['hextech'])
            for filtered in view['by_champion'].values():
                self.assertNotIn('champions', filtered)
                self.assertNotIn('comparison', filtered)
                self.assertNotIn('pairs', filtered['hextech'])
            self.assertTrue(view['champions'])
            for row in view['recent']:
                perf = row['player']['performance']
                self.assertNotIn('dimensions', perf)
                self.assertNotIn('points', perf)
                self.assertIn('score', perf)
                self.assertIn('items', row['player'])
                self.assertIn('augment_slots', row['player'])
        self.assertEqual(snapshot['personal']['recent'][0]['player']['damage_share'], .333333)
        self.assertEqual(records, before)
        self.assertEqual(compact_public_snapshot(snapshot), snapshot)

    def test_public_friend_roster_keeps_ten_games_but_awards_use_twenty_or_thirty(self):
        records = [game(i, friend='NINETEEN', name='Nineteen') for i in range(1, 20)]
        records += [game(i, friend='TWENTY', name='Twenty') for i in range(101, 121)]
        records += [game(i, friend='THIRTY', name='Thirty') for i in range(201, 231)]
        snapshot = build_public_snapshot(records)
        self.assertEqual(set(snapshot['reports']), {'20', '30'})
        self.assertEqual(snapshot['overview']['companions'], 3)
        self.assertEqual(len(snapshot['companions']), 3)
        self.assertEqual(snapshot['reports']['20']['overview']['companions'], 2)
        self.assertEqual(snapshot['reports']['30']['overview']['companions'], 1)
        for minimum in (20, 30):
            report = snapshot['reports'][str(minimum)]
            self.assertEqual(report['minimum_award_games'], minimum)
            self.assertTrue(all(row['samples'] >= minimum for row in report['leaderboard']))
            self.assertNotIn('Nineteen', [row['name'] for row in report['leaderboard']])
            for award in report['awards']:
                self.assertTrue(all(row['samples'] >= minimum for row in award['leaders']))

    def test_public_holdings_follow_subject_and_champion_without_private_fields(self):
        records = [game(i) for i in range(1, 11)]
        for i, match in enumerate(records):
            match['self'].update(champion_id=1 if i < 6 else 2,
                                 augment_slots=[100, 100, 200 if i < 6 else 300, 0, 0, 0],
                                 items=[10, 10, 20 if i < 6 else 30, 0, 0, 0, 999])
            match['participants'][1].update(augment_slots=[400, 0, 0, 0, 0, 0],
                                             items=[40, 0, 0, 0, 0, 0, 999])
        snapshot = build_public_snapshot(records)
        personal = snapshot['personal']
        self.assertEqual(personal['preferences']['items']['top3'][0],
                         {'id': 10, 'uses': 10, 'games': 10, 'frequency': 1})
        self.assertEqual(personal['by_champion']['1']['preferences']['games'], 6)
        self.assertEqual(personal['by_champion']['2']['preferences']['augments']['top3'][1]['id'], 300)
        hero = next(row for row in personal['champions'] if row['champion_id'] == 1)
        self.assertEqual(hero['preferences'], personal['by_champion']['1']['preferences'])
        self.assertEqual(snapshot['companions'][0]['preferences']['items']['top3'][0]['id'], 40)
        self.assertNotIn(999, [row['id'] for row in personal['preferences']['items']['top3']])
        injected = copy.deepcopy(snapshot)
        injected['personal']['preferences']['raw'] = 'PRIVATE-SOURCE'
        injected['personal']['preferences']['items']['top3'][0]['puuid'] = 'PRIVATE-ID'
        self.assertNotIn('PRIVATE', json.dumps(compact_public_snapshot(injected)))
        self.assertEqual(compact_public_snapshot(snapshot), snapshot)

    def test_selected_companion_network_uses_only_their_shared_subset(self):
        records = [game(i, friend='ALLY-A', name='Ally A') for i in range(1, 31)]
        for i, match in enumerate(records):
            if i < 20:
                match['participants'][2].update(puuid='ALLY-B', game_name='Ally B')
        records += [game(i, friend='ALLY-B', name='Ally B', win=False) for i in range(101, 111)]
        before = copy.deepcopy(records)
        snapshot = build_public_snapshot(records)
        selected = next(row for row in snapshot['companions'] if row['name'] == 'Ally A')
        others = {row['name']: row for row in selected['teammates']}
        self.assertNotIn('Ally A', others)
        self.assertEqual(others['Player 1']['id'], 'personal')
        self.assertEqual(others['Ally B']['games'], 20)
        self.assertEqual(others['Ally B']['win_rate'], 1)
        overall_b = next(row for row in snapshot['companions'] if row['name'] == 'Ally B')
        self.assertEqual(overall_b['games'], 30)
        self.assertEqual(others['Ally B']['id'], overall_b['id'])
        self.assertEqual(selected['reports']['20']['overview']['saved'], 30)
        self.assertEqual(snapshot['reports']['20']['overview']['saved'], 40)
        for report in selected['reports'].values():
            self.assertNotIn('Ally A', [p['name'] for a in report['awards'] for p in a['leaders']])
        serialized = json.dumps(snapshot)
        for secret in ('puuid', 'OWNER-SECRET', 'ALLY-A', 'ALLY-B', 'PRIVATE-TAG'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(records, before)
        self.assertEqual(compact_public_snapshot(snapshot), snapshot)

    def test_loader_is_readonly_and_does_not_rewrite_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.register(FakeSource())
            for i in range(1, 11):
                store.put(FakeSource.account_key, game(i))
            with store.connect() as db:
                before = [tuple(row) for row in db.execute('SELECT match_key,payload FROM matches ORDER BY match_key')]
            from public_site import enrich_matches as actual_enrich

            def inspect(snapshot, records):
                with snapshot.connect() as db:
                    self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                    with self.assertRaises(sqlite3.OperationalError):
                        db.execute('DELETE FROM matches')
                store.put(FakeSource.account_key, game(99))
                self.assertEqual(len(snapshot.all_matches()), 10)
                return actual_enrich(snapshot, records)

            with patch('public_site.enrich_matches', side_effect=inspect):
                snapshot = load_public_snapshot(store.path, static_directory=Path(directory) / 'absent-static')
            self.assertEqual(snapshot['overview']['saved'], 10)
            with store.connect() as db:
                after = [tuple(row) for row in db.execute('SELECT match_key,payload FROM matches WHERE match_key != ? ORDER BY match_key', ('TEST_99',))]
            self.assertEqual(after, before)

    def test_missing_configuration_is_complete_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            absent = Path(directory) / 'absent'
            with patch('public_site.load_public_snapshot') as loader:
                self.assertEqual(push_public_snapshot(absent), {'status': 'not_configured'})
            loader.assert_not_called()
            self.assertFalse(absent.exists())

    def test_success_deduplicates_but_content_and_destination_changes_push(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory)
            snapshot = {'schema_version': 1, 'updated_at': 'time1', 'generated_at': 'time1', 'owner': {'name': 'Owner'}}
            opener = SimpleNamespace(open=lambda *args, **kwargs: Response(b'{"ok":true}'))
            with patch('public_site.load_public_snapshot', return_value=snapshot), patch(
                    'public_site.urllib.request.build_opener', return_value=opener), patch.object(
                        opener, 'open', wraps=opener.open) as upload:
                first = push_public_snapshot(directory)
                self.assertEqual(first['status'], 'uploaded')
                snapshot['updated_at'] = snapshot['generated_at'] = 'time2'
                self.assertEqual(push_public_snapshot(directory)['status'], 'unchanged')
                self.assertEqual(upload.call_count, 1)
                request = upload.call_args.args[0]
                self.assertEqual(request.full_url, 'https://example.chatgpt.site/api/snapshot')
                self.assertEqual(request.get_header('Authorization'), 'Bearer ONLY-UPLOAD-SECRET')
                self.assertEqual(request.get_header('User-agent'), 'HextechBattlebook/1.0')
                self.assertEqual(request.get_header('Accept'), 'application/json')
                self.assertEqual(upload.call_args.kwargs['timeout'], 30)
                snapshot['owner']['name'] = 'Renamed'
                self.assertEqual(push_public_snapshot(directory)['status'], 'uploaded')
                self.config(directory, token='ROTATED-SECRET')
                self.assertEqual(push_public_snapshot(directory)['status'], 'uploaded')
                self.assertEqual(upload.call_count, 3)
            status = (Path(directory) / 'public-site-status.json').read_text(encoding='utf-8')
            self.assertNotIn('SECRET', status)

    def test_failed_upload_is_retryable_and_does_not_log_token_or_response(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory)
            failure = urllib.error.HTTPError('https://example.chatgpt.site/api/snapshot', 409,
                                             'ONLY-UPLOAD-SECRET', {}, io.BytesIO(b'SERVER-SECRET'))
            opener = SimpleNamespace(open=None)
            with patch('public_site.load_public_snapshot', return_value={'owner': {'name': 'Owner'}}), patch(
                    'public_site.urllib.request.build_opener', return_value=opener), patch.object(
                        opener, 'open', side_effect=[failure, Response(b'{}')]) as upload:
                self.assertEqual(push_public_snapshot(directory)['http_status'], 409)
                first_status = (Path(directory) / 'public-site-status.json').read_text(encoding='utf-8')
                self.assertNotIn('ONLY-UPLOAD-SECRET', first_status)
                self.assertNotIn('SERVER-SECRET', first_status)
                self.assertEqual(push_public_snapshot(directory)['status'], 'uploaded')
                self.assertEqual(upload.call_count, 2)

    def test_http_and_redirects_rejected_without_forwarding_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory, url='http://third-party.example')
            with patch('public_site.load_public_snapshot') as loader:
                self.assertEqual(push_public_snapshot(directory)['status'], 'failed')
                loader.assert_not_called()
        request = urllib.request.Request('https://example.chatgpt.site/api/snapshot',
                                         headers={'Authorization': 'Bearer PRIVATE'})
        with self.assertRaises(urllib.error.HTTPError):
            _NoRedirect().redirect_request(request, io.BytesIO(), 302, '', {}, 'https://other.example')

    def test_sync_with_gaps_pushes_after_completion_and_delivery_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory:
            def fail_delivery(path):
                self.assertFalse(Store(path).get('sync_status')['running'])
                raise RuntimeError('synthetic_public_site_failure')
            with patch('public_site.push_public_snapshot', side_effect=fail_delivery) as delivery:
                state = run_sync(directory, limit=2, source_factory=FakeSource)
            self.assertEqual(state['outcome'], 'completed_with_gaps')
            self.assertEqual(state['completed'], 1)
            delivery.assert_called_once_with(directory)

    def test_recovery_pushes_after_completion_and_delivery_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.register(FakeSource())
            def fail_delivery(path):
                self.assertFalse(Store(path).get('recovery_status')['running'])
                raise RuntimeError('synthetic_public_site_failure')
            with patch('recover.time.sleep'), patch('public_site.push_public_snapshot', side_effect=fail_delivery) as delivery:
                state = run_recovery(directory, timelines=False, source_factory=FakeSource)
            self.assertEqual(state['outcome'], 'completed')
            delivery.assert_called_once_with(directory)

    def test_watcher_skips_unchanged_signatures_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory)
            (Path(directory) / 'mayhem.sqlite').touch()
            with patch('public_site.push_public_snapshot', return_value={'status': 'uploaded'}) as upload, patch('public_site.time.sleep'):
                result = watch_public_site(directory, max_iterations=3, force=True)
            self.assertEqual(result['status'], 'stopped')
            upload.assert_called_once_with(Path(directory), force=True)

    def test_watcher_detects_wal_changes_and_defers_while_sync_is_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory)
            (Path(directory) / 'mayhem.sqlite').touch()
            with sync_lock(directory), patch('public_site.push_public_snapshot') as upload:
                watch_public_site(directory, max_iterations=1)
                upload.assert_not_called()
            def mutate(_):
                (Path(directory) / 'mayhem.sqlite-wal').write_bytes(b'new synthetic data')
            with patch('public_site.push_public_snapshot', return_value={'status': 'uploaded'}) as upload, patch('public_site.time.sleep', side_effect=mutate):
                watch_public_site(directory, max_iterations=2)
            self.assertEqual(upload.call_count, 2)

    def test_watcher_retries_failure_with_backoff_without_new_database_change(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory)
            (Path(directory) / 'mayhem.sqlite').touch()
            clock = [0]
            def advance(delay):
                clock[0] += delay
            with patch('public_site.time.monotonic', side_effect=lambda: clock[0]), patch(
                    'public_site.time.sleep', side_effect=advance), patch('public_site.push_public_snapshot',
                    side_effect=[{'status': 'failed'}, {'status': 'failed'}, {'status': 'uploaded'}]) as upload:
                watch_public_site(directory, max_iterations=5)
            self.assertEqual(upload.call_count, 3)
            self.assertEqual(clock[0], 100)

    def test_only_one_watcher_and_one_cross_process_push_can_hold_locks(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config(directory)
            with _exclusive_lock(Path(directory) / 'public-site-watch.lock') as acquired:
                self.assertTrue(acquired)
                self.assertEqual(watch_public_site(directory, max_iterations=1)['status'], 'already_watching')
            with _exclusive_lock(Path(directory) / 'public-site-push.lock') as acquired:
                self.assertTrue(acquired)
                with patch('public_site.load_public_snapshot') as loader:
                    self.assertEqual(push_public_snapshot(directory)['status'], 'busy')
                loader.assert_not_called()

    def test_watcher_waits_for_configuration_and_supports_bounded_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('public_site.push_public_snapshot') as upload, patch('public_site.time.sleep'):
                watch_public_site(directory, max_iterations=2)
            upload.assert_not_called()
            stopped = watch_public_site(directory, stop=lambda: True)
            self.assertEqual(stopped['iterations'], 0)


if __name__ == '__main__':
    unittest.main()
