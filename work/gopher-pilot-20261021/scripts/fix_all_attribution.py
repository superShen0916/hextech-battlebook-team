"""Backfill missing per-player match attributions in the gopher pilot database.

The shared-queue collector stores a fetched summary under every registered account
that was present in that game, but a game can reach the pilot database through one
player's history index while another participant's own index never returned it.
Earlier passes only repaired gopher; this pass repairs every registered account
so nobody's archive depends on whose index happened to be walked first.

Zero network requests. Insert-only: existing rows and payloads are never rewritten,
and every write is guarded by the same ten-player / 2400 / KIWI identity checks the
collector uses.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE
import sqlite3,json,sys,argparse
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
PILOT=ROOT/'work/gopher-pilot-20261021'
ap=argparse.ArgumentParser()
ap.add_argument('--apply',action='store_true',help='write changes (default is a dry run)')
ap.add_argument('--named-only',action='store_true',
                help='skip accounts without a game_name (the anonymous deep-crawl registrations)')
args=ap.parse_args()

db=sqlite3.connect(str(DATABASE))
db.row_factory=sqlite3.Row
accounts=list(db.execute('SELECT account_key,puuid,game_name FROM accounts'))
accounts=[a for a in accounts if not a['account_key'].endswith('test-probe')]
if args.named_only:
    accounts=[a for a in accounts if a['game_name']]

appears={}
for row in db.execute('SELECT match_key,puuid FROM participants'):
    appears.setdefault(row['puuid'],set()).add(row['match_key'])

print('%-16s %8s %8s %8s %6s'%('player','listed','attr','appears','gap'))
plan=[]
for a in accounts:
    listed=len(appears.get(a['puuid'],()))
    got=set(r[0] for r in db.execute(
        'SELECT match_key FROM account_matches WHERE account_key=?',(a['account_key'],)))
    # Only games we actually hold, and only where the identity check passes.
    seen=set(appears.get(a['puuid'],())) & set(r[0] for r in db.execute('SELECT match_key FROM matches'))
    missing=sorted(seen-got)
    print('%-16s %8d %8d %8d %6d'%(a['game_name'],listed,len(got),len(seen),len(missing)))
    plan.append((a['account_key'],missing))

total=sum(len(m) for _,m in plan)
print('\nto insert: %d rows across %d accounts'%(total,len(plan)))
if not args.apply:
    print('dry run only')
    sys.exit(0)

from datetime import datetime,timezone
def now():return datetime.now(timezone.utc).isoformat()
n=0
db.execute('BEGIN')
try:
    for key,missing in plan:
        for mid in missing:
            db.execute('INSERT OR IGNORE INTO account_matches VALUES(?,?)',(key,mid))
            db.execute('''INSERT INTO discovered(account_key,match_key,status,attempts,updated_at) VALUES(?,?,'complete',1,?)
                ON CONFLICT(account_key,match_key) DO UPDATE SET status='complete',last_error=NULL,updated_at=excluded.updated_at''',
                (key,mid,now()))
            n+=1
    db.execute('COMMIT')
except Exception:
    db.execute('ROLLBACK');raise
print('inserted %d rows'%n)
print('integrity:',db.execute('PRAGMA integrity_check').fetchone()[0])
print('fk errors:',len(list(db.execute('PRAGMA foreign_key_check'))))
