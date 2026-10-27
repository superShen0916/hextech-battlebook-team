"""Collect match details for a non-gopher pilot account.

The gopher collector (collect_gopher_pilot.py) is hard-wired to the gopher
identity resolved from the production database. This one generalises the same
loop to any account already registered in the pilot database (registered by
merge_teammate_ids.py from teammate-id-listing.json).

Two deliberate differences from the gopher collector:
1. It never calls store.register(), so it cannot overwrite the pilot's
   active_account while another collector is running.
2. It reuses summaries already stored in the pilot database (source_payloads)
   before spending a request, because the 6 teammates share most of their games
   with gopher. Only genuinely new match IDs hit the network.

Client and target identities are explicitly selected. All reads and writes use
the single project database configured by project_paths; no account switch.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE, DATA, client_account
import json,sys,time,sqlite3,argparse
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[3]
PILOT=ROOT/'work/gopher-pilot-20261021'
from core import TencentSource,SourceError,NotStandardMayhem,normalize,scrub,utc_now,summary_page_path,parse_summary_page
from batch_fetch import cover as cover_pages
from store import Store

def now():return datetime.now(timezone(timedelta(hours=8))).isoformat()
ap=argparse.ArgumentParser(description='Collect match details for one pilot account.')
ap.add_argument('--account-key',required=True,help='registered account_key from the local database')
ap.add_argument('--shard-index',type=int,default=0)
ap.add_argument('--shard-count',type=int,default=1)
ap.add_argument('--limit',type=int,default=0,help='stop after this many network fetches (0 = no limit)')
ap.add_argument('--interval',type=float,default=4.0)
args=ap.parse_args()

store=Store(DATA,account_key=args.account_key)
with store.connect() as db:
    row=db.execute('SELECT * FROM accounts WHERE account_key=?',(args.account_key,)).fetchone()
    if row is None:raise SystemExit('account_not_registered: '+args.account_key)
    account=dict(row)
target=account['puuid']
key=account['account_key']

main=sqlite3.connect((DATABASE).as_uri()+'?mode=ro',uri=True)
try:
    main.execute('PRAGMA query_only=ON')
    active=client_account(main)['account_key']
    own=main.execute('SELECT puuid FROM accounts WHERE account_key=?',(active,)).fetchone()[0]
finally:
    main.close()
source=TencentSource()
if source.account['puuid']!=own:raise SystemExit('active_client_account_mismatch')

state={'started_at':now(),'running':True,'account_key':key,'game_name':account['game_name'],
       'tag_line':account['tag_line'],'target_puuid':target,'database':'data/mayhem.sqlite',
       'website_modified':False,'minimum_request_interval_seconds':args.interval,
       'http_counts':{},'fetched':0,'reused':0,'shard_index':args.shard_index,'shard_count':args.shard_count}
STATUS=PILOT/('status-account-%s.json'%account['game_name'])
def update(force=False):
    state['updated_at']=now()
    with store.connect() as db:
        state['coverage']=dict(db.execute('SELECT status,count(*) FROM discovered WHERE account_key=? GROUP BY status',(key,)).fetchall())
    tmp=STATUS.with_suffix('.json.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(STATUS)

last=0.0;cooldown=0.0
FATAL_STATUS={401,403,429}
def read(path,mid=None):
    """Route every request through the audited TencentSource.opener.

    The previous version called urllib.request.urlopen directly, which inherits
    any terminal HTTP(S)_PROXY (this machine ships one that answers 502 for the
    Tencent edge) and follows 3xx redirects while carrying the local client's
    bearer token. source.get also refreshes entitlements before the request,
    so no manual token handling is needed here.
    """
    global last,cooldown
    wait=max(last+args.interval-time.monotonic(),cooldown-time.monotonic(),0)
    if wait:time.sleep(wait)
    last=time.monotonic()
    def diagnostic(record):
        status=str(record.get('status') or 'transport')
        state['http_counts'][status]=state['http_counts'].get(status,0)+1
        store.log_request(state['started_at'],mid,'account_pilot_summary',record)
    return source.get(path,retries=0,diagnostic=diagnostic,timeout=25)

def put(raw,mid,route):
    if isinstance(raw,dict):raw=raw.get('json',raw)
    match=normalize(raw,target,expected_id=mid)
    if not isinstance(match['started_ms'],(int,float)) or match['started_ms']<=0:
        raise SourceError('invalid_match_timestamp')
    store.save_payload(mid,'summary',route,raw)
    store.put(key,match)

with store.connect() as db:
    known=set(r[0] for r in db.execute('SELECT match_key FROM source_payloads WHERE kind=\'summary\''))
    # Only work that is still outstanding. 'complete' rows are already stored, and
    # re-putting them on every run is pure churn; 'skipped' rows are non-2400 games.
    todo=[r[0] for r in db.execute("SELECT match_key FROM discovered WHERE account_key=? AND status IN ('pending','failed')",(key,))]
todo.sort()
if args.shard_count>1:
    todo=[mid for i,mid in enumerate(todo) if i%args.shard_count==args.shard_index]
state['todo']=len(todo);update(True)
print(json.dumps({'account':account['game_name'],'todo':len(todo),'already_stored':len(known)},ensure_ascii=False),flush=True)

# Paged SUMMARY first: the queue usually sits inside the newest page, so a tail
# of N new matches costs one page request instead of N (app/batch_fetch.py).
# Only queued IDs are stored; the rest of the page is discarded. A page failure
# falls back to per-match, except for the statuses that stop the whole batch.
stopped=None
covered={}

def store_from_page(mid,raw):
    """One write per match; a lost write lock must cost a retry, not the run."""
    for db_attempt in range(6):
        try:
            put(raw,mid,'sgp_v1_summary_batch');return
        except sqlite3.Error as e:
            state['db_retries']=state.get('db_retries',0)+1
            state['last_db_error']=type(e).__name__+': '+str(e)[:200]
            if db_attempt==5:raise
            time.sleep(2*(db_attempt+1))

if todo:
    def fetch_page(start,count):
        return parse_summary_page(read(summary_page_path(target,start,count)))
    try:
        pages=cover_pages(todo,fetch_page)
        for mid,raw in pages['matched'].items():
            if stopped:break
            try:
                store_from_page(mid,raw);state['fetched']+=1
            except NotStandardMayhem as e:
                store.discovery_status(key,mid,'skipped',e.code)
            except SourceError as e:
                store.discovery_status(key,mid,'failed',str(e))
        covered=pages['matched']
        state['batch']={'pages':pages['pages'],'matched':len(covered),'stop':pages['stop'],'missing':len(pages['missing'])}
    except SourceError as e:
        state['batch']={'error':e.code,'status':e.status,'fallback':'per_match'}
        if e.status in FATAL_STATUS or e.code in ('login_token_unavailable','local_connection_failed','local_request_failed'):
            stopped='%s/%s'%(e.code,e.status);state['stopped_reason']=stopped
update(True)

for mid in todo:
    if mid in covered:continue
    if args.limit and state['fetched']>=args.limit:break
    try:
        with store.connect() as db:
            row=db.execute('SELECT payload FROM source_payloads WHERE match_key=? AND kind=\'summary\' ORDER BY fetched_at DESC LIMIT 1',(mid,)).fetchone()
        if row:
            try:
                put(json.loads(row['payload']),mid,'reuse_pilot');state['reused']+=1;continue
            except (SourceError,ValueError):pass
        raw=read('/match-history-query/v3/product/lol/matchId/'+mid+'/infoType/summary',mid)
        # The pilot database can be written by another collector at the same time;
        # a lost write lock must cost a retry, not the whole run.
        for attempt in range(6):
            try:
                put(raw,mid,'sgp_v3_summary');state['fetched']+=1;break
            except sqlite3.Error as e:
                state['db_retries']=state.get('db_retries',0)+1
                state['last_db_error']=type(e).__name__+': '+str(e)[:200]
                if attempt==5:raise
                time.sleep(2*(attempt+1))
    except NotStandardMayhem as e:
        store.discovery_status(key,mid,'skipped',e.code)
    except SourceError as e:
        store.discovery_status(key,mid,'failed',str(e))
        if e.status in FATAL_STATUS or e.code in ('rate_limited_stop_batch','authentication_or_permission_stop_batch',
                                                  'login_token_unavailable','local_connection_failed','local_request_failed'):
            stopped='%s/%s'%(e.code,e.status);state['stopped_reason']=stopped;break
        time.sleep(10)
    update()
if stopped:print(json.dumps({'stopped':stopped},ensure_ascii=False),flush=True)
state['running']=False;state['finished_at']=now();update(True)
with store.connect() as db:
    state['coverage']=dict(db.execute('SELECT status,count(*) FROM discovered WHERE account_key=? GROUP BY status',(key,)).fetchall())
update(True)
print(json.dumps({'account':account['game_name'],'fetched':state['fetched'],'reused':state['reused'],
    'http':state['http_counts'],'coverage':state['coverage']},ensure_ascii=False),flush=True)
sys.exit(4 if stopped or any(state['coverage'].get(k, 0) for k in ('pending', 'failed')) else 0)
