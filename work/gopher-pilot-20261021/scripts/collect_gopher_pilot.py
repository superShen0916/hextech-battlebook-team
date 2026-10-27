"""Resume the configured primary player's collection into the single project DB."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE, DATA, client_account, primary_account
import json,sys,time,sqlite3,urllib.parse,hashlib,argparse
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PILOT=ROOT/'work/gopher-pilot-20261021';PILOT.mkdir(parents=True,exist_ok=True)
from core import TencentSource,SourceError,NotStandardMayhem,MATCH_ID,normalize,scrub,utc_now
from listing import classify_window,archive_index,iso_to_ms
from store import Store

ap=argparse.ArgumentParser(description='Resumable gopher pilot collector (optionally sharded).')
ap.add_argument('--shard-index',type=int,default=0,help='this worker handles match IDs where i %% shard-count == shard-index')
ap.add_argument('--shard-count',type=int,default=1,help='total number of parallel workers; 1 keeps the original behaviour')
ap.add_argument('--status-file',default=None,help='status JSON path; defaults to status.json, or status-shardN.json when sharded')
args=ap.parse_args()
shard_index,shard_count=args.shard_index,args.shard_count
if shard_count<1 or not 0<=shard_index<shard_count:
    ap.error('--shard-index must be in [0, --shard-count) and --shard-count >= 1')
STATUS_PATH=PILOT/args.status_file if args.status_file else (PILOT/('status.json' if shard_count==1 else 'status-shard%d.json'%shard_index))

def now():return datetime.now(timezone(timedelta(hours=8))).isoformat()
store=Store(DATA)
state={'started_at':now(),'running':True,'phase':'connecting','target':'gopher#79070',
       'database':'data/mayhem.sqlite','website_modified':False,'minimum_request_interval_seconds':4,
       'timeline_requests':0,'http_counts':{},'new_remote_summaries':0,'copied_main':0,'copied_probe':0,
       'shard_index':shard_index,'shard_count':shard_count}
last_print=0
def update(force=False):
    global last_print
    state['updated_at']=now();state['coverage']=store.counts()
    state['listing']=store.get('pilot_listing',{})
    tmp=STATUS_PATH.with_suffix('.json.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(STATUS_PATH)
    if force or time.monotonic()-last_print>=25:
        print(json.dumps({k:v for k,v in state.items() if k not in ('listing',)},ensure_ascii=True),flush=True);last_print=time.monotonic()

main=sqlite3.connect((DATABASE).as_uri()+'?mode=ro',uri=True)
main.row_factory=sqlite3.Row
try:
    main.execute('PRAGMA query_only=ON')
    active=client_account(main)['account_key']
    own=main.execute('SELECT puuid FROM accounts WHERE account_key=?',(active,)).fetchone()[0]
    account=primary_account(main)
    target=account['puuid']
    source=TencentSource()
    if source.account['puuid']!=own:raise SourceError('active_client_account_mismatch')
    key=account['account_key']
    store.account_key=key
    store.set('pilot_origin',{'main_account_key':active,'main_puuid':own,'target_puuid':target,'created_at':store.get('pilot_origin',{}).get('created_at',now())})
    last_started=0;cooldown=0;consecutive=0
    def read(path,label,mid=None):
        global last_started,cooldown,consecutive
        wait=max(last_started+4-time.monotonic(),cooldown-time.monotonic(),0)
        if wait:time.sleep(wait)
        last_started=time.monotonic()
        def diagnostic(record):
            record=dict(record)
            if record.get('message'):record['message']=record['message'].replace(target,'[target]').replace(own,'[main]')
            store.log_request(state['started_at'],mid,label,record)
            status=str(record.get('status') or 'transport');state['http_counts'][status]=state['http_counts'].get(status,0)+1
        try:
            payload=source.get(path,retries=0,diagnostic=diagnostic,timeout=20)
            consecutive=0;return payload
        except SourceError as e:
            if e.status==429:raise SourceError('rate_limited_stop_batch',429) from None
            if e.status in (401,403):raise SourceError('authentication_or_permission_stop_batch',e.status) from None
            consecutive+=1
            # Failed individual summaries are left for a later pass. Keep a
            # ten-second server-error cooldown while scanning other IDs.
            pause=10;cooldown=time.monotonic()+pause
            state['cooldown_seconds']=pause
            raise
    fatal={'rate_limited_stop_batch','authentication_or_permission_stop_batch','upstream_repeatedly_unavailable',
           'login_token_unavailable','local_connection_failed','local_request_failed'}
    listing=store.get('pilot_listing',{})
    if shard_count>1 and shard_index!=0:
        # Only shard 0 lists the history index; the others wait for it so the
        # listing endpoint is not hit by every worker at once.
        waited=0
        while not store.get('pilot_listing',{}).get('complete'):
            if waited>=900:raise SourceError('listing_wait_timeout')
            time.sleep(5);waited+=5
        listing=store.get('pilot_listing',{})
    if not listing.get('complete'):
        state['phase']='listing_history';update(True)
        ids=[];seen=set();pages=[]
        for start in range(0,20000,200):
            query=urllib.parse.urlencode({'startIndex':start,'count':200,'tag':'q_2400'})
            path='/match-history-query/v1/products/lol/player/'+urllib.parse.quote(target,safe='')+'?'+query
            page=None
            for attempt in range(3):
                try:page=read(path,'pilot_history_ids');break
                except SourceError as e:
                    if e.code in fatal or attempt==2:raise
            if not isinstance(page,list) or any(not isinstance(x,str) or not MATCH_ID.fullmatch(x) for x in page):raise SourceError('unexpected_history_schema')
            if len(page)!=len(set(page)) or any(mid in seen for mid in page):raise SourceError('repeated_history_page')
            ids.extend(page);seen.update(page);store.discover(key,page)
            pages.append({'start':start,'requested':200,'returned':len(page)})
            listing={'complete':len(page)<200,'end_reason':'available_window_end' if len(page)<200 else 'listing',
                     'ids':ids,'pages':pages,'listed_at':now()}
            store.set('pilot_listing',listing);state['listed']=len(ids);update(True)
            if len(page)<200:break
        else:raise SourceError('history_listing_safety_ceiling_reached')
    ids=listing['ids'];state['listed']=len(ids)
    # A short last page only means the crawl reached the end of the window the
    # endpoint exposes (~1000 IDs, no time paging). Whether that window is the
    # player's whole history is decided by the archive, not by page lengths.
    if not isinstance(listing.get('window'),dict):
        with store.connect() as db:
            archived,started=archive_index(db,target)
        window=classify_window(ids,started,archived,listed_at_ms=iso_to_ms(listing.get('listed_at')))
        window.pop('older_archived_ids',None);window.pop('inside_window_missing_ids',None)
        listing['window']=window
        store.set('pilot_listing',listing)
    state['window']=listing['window'];state['window_status']=listing['window']['status']
    def put(raw,mid,route):
        if isinstance(raw,dict):raw=raw.get('json',raw)
        match=normalize(raw,target,expected_id=mid)
        if not isinstance(match['started_ms'],(int,float)) or match['started_ms']<=0:raise SourceError('invalid_match_timestamp')
        store.save_payload(mid,'summary',route,raw);store.put(key,match)
    state['phase']='reuse_existing_cache';update(True)
    probe_index={}
    for path in (HERE/'sgp-teammate-research').glob('*.json'):
        if path.stem.startswith('gopher-history'):continue
        try:
            raw=json.loads(path.read_text(encoding='utf-8'))
            mid=str(raw.get('platformId'))+'_'+str(raw.get('gameId'))
            if mid in ids:probe_index[mid]=raw
        except (ValueError,AttributeError):pass
    for mid in ids:
        if store.has(key,mid):continue
        row=main.execute("SELECT payload FROM source_payloads WHERE match_key=? AND kind='summary' ORDER BY fetched_at DESC LIMIT 1",(mid,)).fetchone()
        if row:
            try:put(json.loads(row['payload']),mid,'cached_main');state['copied_main']+=1;continue
            except (SourceError,ValueError):pass
        if mid in probe_index:
            try:put(probe_index[mid],mid,'cached_probe');state['copied_probe']+=1
            except SourceError:pass
    main.close();main=None
    state['phase']='capture_missing_summaries';update(True)
    for round_index in range(1,4):
        with store.connect() as db:
            statuses={row['match_key']:row['status'] for row in db.execute('SELECT match_key,status FROM discovered WHERE account_key=?',(key,))}
        missing=[mid for mid in ids if not store.has(key,mid) and statuses.get(mid)!='skipped']
        missing.sort(key=lambda mid:statuses.get(mid)=='failed')
        if shard_count>1:
            missing=[mid for i,mid in enumerate(missing) if i%shard_count==shard_index]
        if not missing:break
        state['round']=round_index;state['round_targets']=len(missing);update(True)
        if round_index>1:time.sleep(30)
        for mid in missing:
            # Sharded workers contend for the pilot database write lock. A lost
            # race must cost a retry, not the whole round, so sqlite3.Error is
            # retried here with backoff instead of escaping to the top level.
            for db_attempt in range(6):
                try:
                    raw=read('/match-history-query/v3/product/lol/matchId/'+mid+'/infoType/summary','pilot_sgp_v3_summary',mid)
                    put(raw,mid,'sgp_v3_summary');state['new_remote_summaries']+=1
                    break
                except NotStandardMayhem as e:
                    store.discovery_status(key,mid,'skipped',e.code);break
                except SourceError as e:
                    store.discovery_status(key,mid,'failed',str(e))
                    if e.code in fatal:raise
                    break
                except sqlite3.Error as e:
                    state['db_retries']=state.get('db_retries',0)+1
                    state['last_db_error']=type(e).__name__+': '+str(e)[:200]
                    if db_attempt==5:raise
                    time.sleep(2*(db_attempt+1))
            update()
    state['phase']='finished';counts=store.counts()
    state['outcome']='complete_available_window' if sum(store.has(key,mid) for mid in ids)==len(ids) else 'finished_with_gaps'
except SourceError as e:
    state.update(phase='stopped',outcome='incomplete',error=e.code,http_status=e.status)
except Exception as e:
    import traceback
    state.update(phase='stopped',outcome='incomplete',error=type(e).__name__,detail=str(e)[:500])
    traceback.print_exc()
finally:
    if main is not None:main.close()
    state['running']=False;state['finished_at']=now();update(True)

# A completed process can still have gaps; expose this to launchers.
sys.exit(0 if state.get('outcome') == 'complete_available_window' else 4)
