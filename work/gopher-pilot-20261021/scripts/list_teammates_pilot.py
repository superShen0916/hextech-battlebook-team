"""Enumerate other players' 2400-queue match-ID lists for the gopher pilot.

Scope: the listing endpoint (/match-history-query/v1/products/lol/player/{puuid}
?startIndex&count&tag=q_2400) is healthy while the per-match detail endpoint is
currently returning 503. This script spends the cheap calls first: it builds the
match-ID universe for gopher's closest teammates so that detail fetching can be
batched later, and reports how many match IDs are new relative to what the pilot
already holds.

Deliberately conservative:
- read-only on the single project database
- writes only a JSON report (no SQLite writes, so it cannot race the collector)
- 4 s minimum spacing, stops at the first 429 rather than retrying
- default scope is the top 6 teammates by games played alongside gopher
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE, client_account, primary_account
import json,sys,sqlite3,time,argparse
from pathlib import Path
from datetime import datetime,timezone,timedelta
import urllib.request,urllib.error
ROOT=Path(__file__).resolve().parents[3]
PILOT=ROOT/'work/gopher-pilot-20261021'
from core import TencentSource,MATCH_ID,SourceError
from listing import classify_window, archive_index
from collection_scope import excluded_puuids

def now():return datetime.now(timezone(timedelta(hours=8))).isoformat()

ap=argparse.ArgumentParser()
ap.add_argument('--top',type=int,default=6)
ap.add_argument('--page',type=int,default=200)
ap.add_argument('--ceiling',type=int,default=20000)
ap.add_argument('--interval',type=float,default=4.0)
ap.add_argument('--registered-only',action='store_true',
                help='list every named account registered in the pilot DB instead of the top-N by appearances')
ap.add_argument('--out',default=str(PILOT/'teammate-id-listing.json'))
args=ap.parse_args()

main=sqlite3.connect((DATABASE).as_uri()+'?mode=ro',uri=True)
main.row_factory=sqlite3.Row
try:
    main.execute('PRAGMA query_only=ON')
    active=client_account(main)['account_key']
    own=main.execute('SELECT puuid FROM accounts WHERE account_key=?',(active,)).fetchone()[0]
finally:
    main.close()

pilot=sqlite3.connect((DATABASE).as_uri()+'?mode=ro',uri=True)
pilot.row_factory=sqlite3.Row
try:
    gopher=primary_account(pilot)['puuid'];counts={};names={}
    for row in pilot.execute('SELECT puuid,payload FROM participants'):
        d=json.loads(row['payload'])
        counts[d['puuid']]=counts.get(d['puuid'],0)+1
        names[d['puuid']]=(d.get('game_name'),d.get('tag_line'))
    known=set(r[0] for r in pilot.execute('SELECT match_key FROM matches'))
    known_discovered=set(r[0] for r in pilot.execute('SELECT match_key FROM discovered'))
    registered={r['puuid'] for r in pilot.execute(
        "SELECT puuid FROM accounts WHERE game_name!='' AND account_key NOT LIKE '%test-probe'")}
    # data/collection-exclusions.json: names we track in the archive but no longer
    # fetch for (2026-10-27, six accounts kept only as historical data).
    registered-=excluded_puuids()
finally:
    pilot.close()
if gopher is None:raise SystemExit('gopher_identity_not_found')

if args.registered_only:
    # Incremental sync scope: everyone we actually track by name, including the
    # client's own account (excluded from the top-N mode because it is "own").
    candidates=sorted(((n,p) for p,n in counts.items() if p in registered and p!=gopher),key=lambda x:-x[0])
else:
    candidates=sorted(((n,p) for p,n in counts.items() if p!=gopher and p!=own),key=lambda x:-x[0])[:args.top]
source=TencentSource()
if source.account['puuid']!=own:raise SystemExit('active_client_account_mismatch')

def list_player(puuid):
    ids=[];seen=set();pages=[];statuses={}
    for start in range(0,args.ceiling,args.page):
        if time.monotonic()-last[0]<args.interval:time.sleep(args.interval-(time.monotonic()-last[0]))
        last[0]=time.monotonic()
        if time.time()>=source._expires-45:source.refresh_token()
        path='/match-history-query/v1/products/lol/player/'+puuid+'?startIndex=%d&count=%d&tag=q_2400'%(start,args.page)
        # Route through TencentSource like every other call: its opener disables the
        # terminal proxy (which answers 502 here) and never follows redirects with the
        # local client token attached.
        def record_status(rec):
            statuses[str(rec.get('status') or 'transport')]=statuses.get(str(rec.get('status') or 'transport'),0)+1
        try:
            page=source.get(path,retries=0,diagnostic=record_status,timeout=30)
        except SourceError as e:
            if e.status==429:return ids,pages,statuses,'rate_limited_stop'
            if e.status in (500,502,503,504):
                time.sleep(10);continue
            return ids,pages,statuses,'http_%s'%(e.status or e.code)
        except Exception as e:
            statuses[type(e).__name__]=statuses.get(type(e).__name__,0)+1
            time.sleep(10);continue
        if not isinstance(page,list) or any(not isinstance(x,str) or not MATCH_ID.fullmatch(x) for x in page):
            return ids,pages,statuses,'unexpected_schema'
        ids.extend(page);seen.update(page)
        pages.append({'start':start,'requested':args.page,'returned':len(page)})
        if len(page)<args.page:break
    return ids,pages,statuses,'available_window_end' if pages and pages[-1]['returned']<args.page else 'ceiling'

last=[0.0]
# Second read-only handle: the archive decides whether a listing is the player's
# whole history or only the most recent window the endpoint exposes.
archive=sqlite3.connect((DATABASE).as_uri()+'?mode=ro',uri=True)
report={'started_at':now(),'production_database_written':False,'pilot_database_written':False,
        'scope':{'top':args.top,'page':args.page,'ceiling':args.ceiling,'interval':args.interval},
        'gopher_puuid':gopher,'known_match_keys':len(known),'teammates':[]}
allnew=set()
for n,puuid in candidates:
    ids,pages,statuses,reason=list_player(puuid)
    new=[m for m in ids if m not in known]
    allnew.update(new)
    archived,started=archive_index(archive,puuid)
    window=classify_window(ids,started,archived,listed_at_ms=time.time()*1000)
    window.pop('older_archived_ids',None);window.pop('inside_window_missing_ids',None)
    report['teammates'].append({'puuid':puuid,'game_name':names[puuid][0],'tag_line':names[puuid][1],
        'games_with_gopher':n,'listed':len(ids),'ids':ids,'new_vs_pilot_matches':len(new),'pages':pages,
        'http_counts':statuses,'end_reason':reason,'window':window})
    print(json.dumps({'game_name':names[puuid][0],'listed':len(ids),'new':len(new),'end':reason,
        'window':window['status'],'older_archived':window['archived_beyond_window'],
        'missing_inside':window['archived_missing_inside_window'],'http':statuses},ensure_ascii=False),flush=True)
    if reason=='rate_limited_stop':break
archive.close()
report['unique_new_match_ids']=len(allnew)
report['new_match_ids']=sorted(allnew)
report['finished_at']=now()
Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('report',args.out,'unique_new_match_ids',len(allnew))
