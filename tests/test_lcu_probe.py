"""Offline regression tests; no live client or remote service requests."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import lcu_probe as probe


class ProbeTests(unittest.TestCase):
    def test_reject_stale_lockfile(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / 'lockfile'
            lock.write_text('LeagueClient:999:12345:secret:https')
            with self.assertRaisesRegex(probe.ProbeError, 'credentials_unavailable'):
                probe.discover([{'Name': 'LeagueClient.exe', 'ProcessId': 1}], str(lock))

    def test_log_fallback_uses_current_pair_of_process_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / 'lockfile'
            lock.write_text('')
            (root / 'old_99_77_LeagueClientUx.log').write_text('--app-port=11111 --remoting-auth-token=old-secret')
            rows = [{'Name': 'LeagueClient.exe', 'ProcessId': 1}, {'Name': 'LeagueClientUx.exe', 'ProcessId': 2}]
            with self.assertRaises(probe.ProbeError):
                probe.discover(rows, str(lock))
            (root / 'now_1_2_LeagueClientUx.log').write_text('--app-port=12345 --remoting-auth-token=new-secret')
            self.assertEqual(probe.discover(rows, str(lock)), (12345, 'new-secret', 'current_pid_ux_startup_log'))

    def test_remote_or_sensitive_routes_rejected(self):
        client = probe.Client(12345, 'secret', {'endpoints': []})
        for route in ('https://example.com/', '//example.com/', '/entitlements/v1/token',
                      '/lol-summoner/v1/current-summoner/icon'):
            with self.subTest(route=route), self.assertRaises(probe.ProbeError):
                client.get('bad', route)
        with self.assertRaises(probe.ProbeError):
            client.get('bad_post', '/lol-summoner/v1/current-summoner', lookup_body={})

    def test_exception_does_not_leak_token_or_url(self):
        report = {'endpoints': []}
        client = probe.Client(12345, 'SENTINEL-TOKEN', report)
        with patch.object(client.opener, 'open', side_effect=urllib.error.URLError('SENTINEL-TOKEN private-url')), patch.object(probe.time, 'sleep'):
            self.assertIsNone(client.get('self', '/lol-summoner/v1/current-summoner'))
        serialized = json.dumps(report)
        self.assertNotIn('SENTINEL-TOKEN', serialized)
        self.assertNotIn('private-url', serialized)
        self.assertEqual(report['endpoints'][0]['error'], 'URLError')

    def test_zero_augment_slot_differs_from_absent_field(self):
        present = probe.augment_fields({'stats': {'playerAugment1': 0, 'playerAugment2': 1234}})
        self.assertEqual(present['stats.playerAugment1'], 0)
        self.assertNotIn('stats.playerAugment3', present)

    def simulate(self, history):
        account = {'puuid': 'PRIVATE-PUUID', 'gameName': 'PRIVATE-NAME', 'tagLine': 'PRIVATE-TAG'}
        calls = []

        class FakeClient:
            def __init__(self, *args):
                pass

            def get(self, label, path, template=None, lookup_body=None):
                calls.append((label, path))
                if label == 'current_summoner':
                    return account
                if label == 'alias_lookup_self':
                    return [account]
                if label == 'queues':
                    return []
                if label.startswith('history_') or label == 'puuid_history_self':
                    return history
                if label.startswith('game_'):
                    return {'queueId': 2400, 'participants': []}
                return None

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'report.json'
            args = types.SimpleNamespace(lockfile=None, log_dir=None, save_raw=None, queue_id=[2400],
                                         pages=3, details=2, friend_puuid=None, output=str(output))
            with patch.object(probe, 'processes', return_value=[]), patch.object(probe, 'discover', return_value=(12345, 'PRIVATE-TOKEN', 'mock')), patch.object(probe, 'Client', FakeClient), contextlib.redirect_stdout(io.StringIO()):
                code = probe.run(args)
            data = json.loads(output.read_text(encoding='utf-8'))
            for secret in ('PRIVATE-PUUID', 'PRIVATE-NAME', 'PRIVATE-TAG', 'PRIVATE-TOKEN'):
                self.assertNotIn(secret, json.dumps(data))
            return code, data, calls

    def test_history_error_is_unavailable_not_empty_or_success(self):
        code, data, _ = self.simulate(None)
        self.assertEqual(code, 4)
        self.assertEqual(data['result'], 'history_unavailable')
        self.assertIsNone(data['history_unique_games'])
        self.assertFalse(data['history_read_success'])

    def test_successful_empty_history_is_distinct(self):
        code, data, _ = self.simulate({'games': {'games': []}})
        self.assertEqual(code, 0)
        self.assertEqual(data['history_unique_games'], 0)
        self.assertTrue(data['history_read_success'])

    def test_repeated_page_detected_and_other_modes_not_sampled(self):
        code, data, calls = self.simulate({'games': {'games': [
            {'gameId': 10, 'queueId': 450}, {'gameId': 11, 'queueId': 2400}]}})
        self.assertEqual(code, 0)
        self.assertEqual(data['history_unique_games'], 2)
        self.assertIn('pagination_warning', data)
        details = [path for label, path in calls if label.startswith('game_')]
        self.assertEqual(details, ['/lol-match-history/v1/games/11'])


if __name__ == '__main__':
    unittest.main()
