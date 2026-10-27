"""Bind saved query results to local stable identities, without network access."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from hexdata import public_rating


def import_ratings(database, result_path, pending_path=None):
    database = Path(database).resolve()
    results = json.loads(Path(result_path).read_text(encoding='utf-8'))
    pending = json.loads(Path(pending_path).read_text(encoding='utf-8')) if pending_path else {'players': []}
    year = datetime.fromisoformat(results['query_date']).year
    def timestamp(value):
        return datetime.strptime(f'{year}/{value}', '%Y/%m/%d %H:%M').isoformat() + '+08:00' if value else None
    identities = defaultdict(set)
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        key = json.loads(db.execute("SELECT value FROM settings WHERE key='active_account'").fetchone()[0])
        for payload, in db.execute('SELECT m.payload FROM matches m JOIN account_matches a USING(match_key) WHERE a.account_key=?', (key,)):
            for player in json.loads(payload)['participants']:
                gid = player.get('game_name', '') + '#' + player.get('tag_line', '')
                if player.get('puuid'):
                    identities[gid].add(player['puuid'])
    finally:
        db.close()
    target = database.parent / 'hexdata-ratings.json'
    data = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'schema_version': 1, 'ratings': {}}
    seen = set()
    for row in results['players'] + pending['players']:
        gid = row['game_id']
        candidates = identities.get(gid, set())
        if len(candidates) != 1:
            raise ValueError(f'Identity missing or ambiguous: {gid}')
        identity = next(iter(candidates))
        if identity in seen:
            raise ValueError(f'Duplicate identity: {gid}')
        seen.add(identity)
        rated = 'estimated_score' in row
        estimate = public_rating({'status': 'estimated' if rated else 'pending',
                                  'score': row.get('estimated_score'), 'top_percent': row.get('region_top_percent'),
                                  'queried_at': timestamp(row.get('queried_at')),
                                  'matches_through': timestamp(row.get('matches_counted_through'))})
        if rated and estimate['status'] != 'estimated':
            raise ValueError(f'Invalid estimate: {gid}')
        # A later pending-list import must not erase a previously saved score.
        if rated or data['ratings'].get(identity, {}).get('status') != 'estimated':
            data['ratings'][identity] = estimate
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)
    return {'estimated': sum(r['status'] == 'estimated' for r in data['ratings'].values()),
            'pending': sum(r['status'] == 'pending' for r in data['ratings'].values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/mayhem.sqlite')
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--pending', type=Path)
    args = parser.parse_args()
    print(json.dumps(import_ratings(args.database, args.results, args.pending)))
