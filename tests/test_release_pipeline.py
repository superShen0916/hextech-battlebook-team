import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from split_snapshot import split
from build_recaps import night_key, recap_rows
from match_policy import apply_policy


class ReleaseTests(unittest.TestCase):
    def test_repeated_split_keeps_complete_history_and_rejects_summary_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = {'id': 'alice', 'name': 'Alice', 'coverage': {'saved': 250},
                 'recent': [{'id': str(i)} for i in range(250)],
                 'champions': [{'champion_id': i} for i in range(60)], 'by_champion': {'1': {}}, 'reports': {'20': {'awards': []}}}
            source = root / 'full.json'
            source.write_text(json.dumps({'snapshot_kind': 'full', 'build_id': 'one', 'players': [p]}), encoding='utf-8')
            split(source, root / 'api')
            before = {f.name: f.read_bytes() for f in (root / 'api/profiles').glob('*.json')}
            split(source, root / 'api')
            self.assertEqual(before, {f.name: f.read_bytes() for f in (root / 'api/profiles').glob('*.json')})
            complete = json.loads((root / 'api/profiles/alice.json').read_text(encoding='utf-8'))
            self.assertEqual(len(complete['recent']), 250)
            self.assertEqual(len(complete['champions']), 60)
            self.assertIn('reports', complete)
            with self.assertRaises(ValueError):
                split(root / 'api/snapshot', root / 'api')
            self.assertEqual(before, {f.name: f.read_bytes() for f in (root / 'api/profiles').glob('*.json')})

    def test_friday_night_crosses_midnight_but_ends_at_six(self):
        tz = timezone(timedelta(hours=8))
        ms = lambda s: datetime.fromisoformat(s).replace(tzinfo=tz).timestamp() * 1000
        self.assertEqual(night_key(ms('2026-10-23T22:00:00')), '2026-10-23')
        self.assertEqual(night_key(ms('2026-10-24T02:30:00')), '2026-10-23')
        self.assertIsNone(night_key(ms('2026-10-24T06:00:00')))
        self.assertIsNone(night_key(ms('2026-10-23T17:59:59')))

    def test_opponents_are_never_combined_and_ineligible_matches_are_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            detail = {'started_ms': 1000, 'duration': 600, 'players': [
                {'profile_id': pid, 'team': team, 'win': team == 100}
                for pid, team in [('a', 100), ('b', 100), ('c', 200), ('d', 200)]]}
            (root / 'm-good.json').write_text(json.dumps(detail), encoding='utf-8')
            snapshot = {'players': [{'id': pid, 'recent': [{'id': 'm-good', 'stats_eligible': True}, {'id': 'm-excluded', 'stats_eligible': False}]} for pid in 'abcd']}
            rows = recap_rows(snapshot, root)
            self.assertEqual(len(rows), 2)
            self.assertEqual({tuple(p['profile_id'] for p in r['members']) for r in rows}, {('a', 'b'), ('c', 'd')})

    def test_explicit_exclusion_changes_statistics_without_discarding_source(self):
        match = {'match_key': 'TEST_123', 'stats_eligible': True, 'participants': [{'name': 'example'}]}
        mid = 'm-' + hashlib.sha256(b'TEST_123').hexdigest()[:20]
        apply_policy(match, {mid: 'user decision'})
        self.assertFalse(match['stats_eligible'])
        self.assertEqual(match['participants'], [{'name': 'example'}])


if __name__ == '__main__':
    unittest.main()
