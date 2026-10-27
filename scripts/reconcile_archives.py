"""Repair archived-player links and apply explicit exclusions, without network.

Default is read-only. --apply creates verified SQLite backups before writes.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from match_policy import apply_policy
from project_paths import DATABASE

DATABASES = [DATABASE]


def backup(path, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError(f'Refusing to overwrite backup: {target}')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('backup_integrity_failed')


def reconcile(path, apply=False):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    links = list(db.execute('''SELECT DISTINCT a.account_key,p.match_key FROM accounts a
        JOIN participants p ON p.puuid=a.puuid JOIN matches m USING(match_key)
        WHERE a.game_name!='' AND m.queue_id=2400 AND m.game_mode='KIWI'
        AND (SELECT count(*) FROM participants q WHERE q.match_key=m.match_key)=10
        AND (SELECT count(*) FROM participants q WHERE q.match_key=m.match_key AND q.puuid=a.puuid)=1
        AND NOT EXISTS (SELECT 1 FROM account_matches am WHERE am.account_key=a.account_key AND am.match_key=m.match_key)'''))
    updates = []
    for row in db.execute('SELECT match_key,payload,stats_eligible FROM matches'):
        old = json.loads(row['payload'])
        value = apply_policy(dict(old))
        if value != old or bool(row['stats_eligible']) != bool(value['stats_eligible']):
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
            updates.append((int(value['stats_eligible']), payload, hashlib.sha256(payload.encode()).hexdigest(), row['match_key']))
    db.close()
    result = {'database': str(path.relative_to(ROOT)), 'new_links': len(links), 'excluded_updates': len(updates)}
    if not apply or not (links or updates):
        return result
    label = 'pilot' if 'gopher-pilot' in str(path) else 'legacy'
    target = ROOT / 'backups' / f'{label}-before-maintenance-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.sqlite'
    backup(path, target)
    result['backup'] = str(target.relative_to(ROOT))
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        db.executemany('INSERT OR IGNORE INTO account_matches VALUES(?,?)', links)
        db.executemany('''INSERT INTO discovered(account_key,match_key,status,attempts,updated_at)
            VALUES(?,?,'complete',0,?) ON CONFLICT(account_key,match_key)
            DO UPDATE SET status='complete',last_error=NULL,updated_at=excluded.updated_at''',
            [(r['account_key'], r['match_key'], now) for r in links])
        db.executemany('UPDATE matches SET stats_eligible=?,payload=?,payload_hash=? WHERE match_key=?', updates)
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or list(db.execute('PRAGMA foreign_key_check')):
            raise RuntimeError('database_validation_failed')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    results = [reconcile(p, args.apply) for p in DATABASES]
    print(json.dumps({'applied': args.apply, 'results': results}, ensure_ascii=False, indent=2))
    if args.apply:
        (ROOT / 'backups').mkdir(parents=True, exist_ok=True)
        (ROOT / 'backups/maintenance-reconcile.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
