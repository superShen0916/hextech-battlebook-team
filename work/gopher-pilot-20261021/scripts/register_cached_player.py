"""Register a cached player and link the matches we already have.

One-off maintenance for the battlebook: a player who appears in stored
ten-player summaries (participants rows) but has no accounts row cannot be
resolved by app/personal_profiles.py (_read_archive raises
personal_archive_identity_mismatch). This script mirrors Store.register /
Store.put semantics for an identity we can prove from the payload itself:

- accounts: one row, game_name/tag_line taken from the participant payload
  (never guessed from a display name alone);
- account_matches + discovered('complete'): one link per stored match where
  the puuid is a participant.

It deliberately does NOT touch settings.active_account, matches, or
participants rows, and is idempotent (ON CONFLICT DO NOTHING / DO UPDATE).
Usage:
    python register_cached_player.py --puuid <puuid> [--dry-run]
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = DATABASE


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puuid', required=True)
    ap.add_argument('--db', type=Path, default=DB)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            'SELECT match_key, payload FROM participants WHERE puuid=?', (args.puuid,)).fetchall()
        if not rows:
            print('no participant rows for puuid; nothing to do', file=sys.stderr)
            return 2
        identity = None
        for row in rows:
            payload = json.loads(row['payload'])
            candidate = (payload.get('game_name'), payload.get('tag_line'))
            if all(candidate) and identity is None:
                identity = candidate
            elif identity is not None and candidate != identity:
                print('conflicting identity in payloads:', identity, candidate, file=sys.stderr)
                return 2
        if not identity or not all(identity):
            print('payload lacks game_name/tag_line; refuse to guess', file=sys.stderr)
            return 2
        game_name, tag_line = identity
        key = 'HN1:' + args.puuid

        existing = db.execute('SELECT * FROM accounts WHERE account_key=?', (key,)).fetchone()
        already = db.execute(
            'SELECT count(*) c FROM account_matches WHERE account_key=?', (key,)).fetchone()['c']
        print('identity: %s#%s  key=%s  account_row=%s  linked=%d  participant_rows=%d'
              % (game_name, tag_line, key, 'present' if existing else 'missing', already, len(rows)))
        if args.dry_run:
            return 0

        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?) ON CONFLICT(account_key) DO UPDATE SET '
                   'game_name=excluded.game_name,tag_line=excluded.tag_line,last_seen=excluded.last_seen',
                   (key, 'HN1', args.puuid, game_name, tag_line, utc_now()))
        now = utc_now()
        for row in rows:
            db.execute('INSERT OR IGNORE INTO account_matches VALUES(?,?)', (key, row['match_key']))
            db.execute('INSERT INTO discovered(account_key,match_key,status,attempts,updated_at) '
                       'VALUES(?,?,\'complete\',1,?) ON CONFLICT(account_key,match_key) DO UPDATE SET '
                       'status=\'complete\',last_error=NULL,updated_at=excluded.updated_at',
                       (key, row['match_key'], now))
        db.commit()
        after = db.execute('SELECT count(*) c FROM account_matches WHERE account_key=?', (key,)).fetchone()['c']
        print('linked account_matches now:', after)
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
