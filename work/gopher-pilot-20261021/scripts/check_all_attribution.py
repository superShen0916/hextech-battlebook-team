"""Per-player attribution gap in the isolated gopher pilot database (read-only).

'listed'      = how many games the upstream returns for that player's own history list
'appears_in'  = games already stored in the pilot DB that contain this player's puuid
'attributed'  = rows written under his account_key today
'gap'         = stored games where he fights but which are not in his own list,
               i.e. records the per-account collector never wrote for him.
Gopher is included so the already-repaired number can be re-verified.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE, client_account
import sqlite3,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
PILOT=ROOT/'work/gopher-pilot-20261021'
main=sqlite3.connect('file:'+str(DATABASE)+'?mode=ro',uri=True)
pilot=sqlite3.connect('file:'+str(DATABASE)+'?mode=ro',uri=True)

own=client_account(main)['account_key']
ownp=main.execute('SELECT puuid FROM accounts WHERE account_key=?',(own,)).fetchone()[0]
maincnt={}
for puuid,payload in main.execute('SELECT puuid,payload FROM participants'):
    d=json.loads(payload);maincnt[puuid]=maincnt.get(puuid,0)+1

L=json.loads((PILOT/'teammate-id-listing.json').read_text(encoding='utf-8'))
idxmap={t['game_name']:len(t['ids']) for t in L['teammates']}
built={k:n for k,n in pilot.execute('SELECT account_key,COUNT(*) FROM account_matches GROUP BY account_key')}

appears={}
for mid,payload in pilot.execute('SELECT match_key,payload FROM matches'):
    p=json.loads(payload)
    for x in pilot.execute('SELECT puuid,payload FROM participants WHERE match_key=?',(mid,)):
        appears.setdefault(x[0],set()).add(mid)

rows=[]
for key,puuid,name in pilot.execute('SELECT account_key,puuid,game_name FROM accounts'):
    if key.endswith('test-probe'):
        continue
    rows.append((maincnt.get(puuid,0),name,idxmap.get(name,0),built.get(key,0),len(appears.get(puuid,()))))
rows.sort(reverse=True)

print('%-16s %8s %8s %8s %8s %6s'%('player','w/main','listed','attr','appears','gap'))
total=0
for wm,name,listed,got,seen in rows:
    gap=seen-got
    total+=max(gap,0)
    print('%-16s %8d %8d %8d %8d %6d'%(name,wm,listed,got,seen,gap))
print('\ntotal unattributed player records still to write: %d'%total)
