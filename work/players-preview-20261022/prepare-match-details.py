"""Read saved JSON only. Add whitelisted ten-player details for this fixed preview snapshot."""
from pathlib import Path
from collections import defaultdict,Counter
import json,hashlib,math,sqlite3,sys,argparse
ROOT=Path(__file__).parent;PROJECT=ROOT.parent.parent
sys.path.insert(0,str(PROJECT/'app'))
from awards import annotate_awards
from project_paths import database_path
sys.path.insert(0,str(PROJECT/'scripts'))
from snapshot_io import FULL,load_full
from build_cache import digest,implementation_key
from snapshot_io import write_json
def number(v):return v if type(v) in (int,float) and math.isfinite(v) and v>=0 else None
def signature(start,duration,p,raw=False):
 keys=['championId','kills','deaths','assists','win'] if raw else ['champion_id','kills','deaths','assists','win']
 return (start,duration,*(p.get(k) for k in keys))
def prepare(source=FULL,incremental=False):
 snapshot=load_full(source);payload=Path(source).read_bytes()
 profiles=[*snapshot['players'],*[dict(c,id='shared-'+c['id']) for c in snapshot['companions'] if c['name'] not in {p['name'] for p in snapshot['players']}]]
 target_times={m.get('started_ms') for p in profiles for m in p.get('recent',[])}
 raws={};skipped=0
 for directory in [database_path(PROJECT).parent/'raw']:
  for file in directory.glob('*.json'):
   try:r=json.loads(file.read_text(encoding='utf-8'));r=r.get('json',r)
   except (OSError,ValueError):skipped+=1;continue
   if r.get('queueId')!=2400 or r.get('gameMode')!='KIWI' or r.get('gameStartTimestamp') not in target_times:continue
   participants=r.get('participants',[]);counts=Counter(x.get('teamId') for x in participants)
   if len(participants)!=10 or sorted(counts.values())!=[5,5] or len({x.get('participantId') for x in participants})!=10:continue
   key=f"{r.get('platformId')}_{r.get('gameId')}";public='m-'+hashlib.sha256(key.encode()).hexdigest()[:20]
   raws.setdefault(public,r)
 # Pilot keeps some complete summaries in SQLite instead of loose JSON. Read only the fixed snapshot's missing IDs.
 wanted={m['id'] for p in profiles for m in p.get('recent',[]) if m['id'].startswith('m-')}-raws.keys()
 dbpath=database_path(PROJECT)
 if wanted and dbpath.is_file():
  db=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=15)
  try:
   db.execute('PRAGMA query_only=ON')
   keys=[key for (key,) in db.execute("SELECT DISTINCT match_key FROM source_payloads WHERE kind='summary'") if 'm-'+hashlib.sha256(key.encode()).hexdigest()[:20] in wanted]
   for offset in range(0,len(keys),100):
    batch=keys[offset:offset+100]
    for key,raw_payload in db.execute("SELECT match_key,payload FROM source_payloads WHERE kind='summary' AND match_key IN ("+','.join('?' for _ in batch)+') ORDER BY fetched_at',batch):
     try:r=json.loads(raw_payload);r=r.get('json',r)
     except (TypeError,ValueError):continue
     if r.get('queueId')!=2400 or r.get('gameMode')!='KIWI' or r.get('gameStartTimestamp') not in target_times:continue
     participants=r.get('participants',[]);counts=Counter(x.get('teamId') for x in participants)
     if len(participants)!=10 or sorted(counts.values())!=[5,5] or len({x.get('participantId') for x in participants})!=10:continue
     if key!=f"{r.get('platformId')}_{r.get('gameId')}":continue
     public='m-'+hashlib.sha256(key.encode()).hexdigest()[:20];raws[public]=r
  finally:db.close()
 candidates=defaultdict(list)
 for mid,r in raws.items():
  for player in r['participants']:
   sig=signature(r['gameStartTimestamp'],r['gameDuration'],player,True)
   candidates[sig].append((mid,player))
 aliases={};identities=defaultdict(set);missing=0;eligibility=defaultdict(set)
 for profile in profiles:
  rows={}
  for m in profile.get('recent',[]):
   sig=signature(m.get('started_ms'),m.get('duration'),m['player'])
   matches=candidates.get(sig,[])
   if m['id'].startswith('m-'):matches=[x for x in matches if x[0]==m['id']]
   if len(matches)!=1:missing+=1;continue
   mid,player=matches[0];rows[m['id']]={'file':mid,'slot':player['participantId']}
   eligibility[mid].add(m.get('stats_eligible') is True)
   if player.get('puuid'):identities[profile['id']].add(player['puuid'])
  aliases[profile['id']]=rows
 identity_to_profile={next(iter(ids)):p for p in profiles if len(ids:=identities[p['id']])==1}
 used={row['file'] for rows in aliases.values() for row in rows.values()}
 dest=ROOT/'public/matches';dest.mkdir(exist_ok=True)
 forbidden={'puuid','summonerId','accountId','riotIdTagline','gameId','platformId','match_key'}
 cache_path=PROJECT/'work/build/cache/match-details.json'
 try:cached=json.loads(cache_path.read_text(encoding='utf-8')) if incremental else {}
 except (OSError,ValueError):cached={}
 implementation=implementation_key(PROJECT/'app')+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 names={key:{'id':p['id'],'name':p['name']} for key,p in identity_to_profile.items()}
 fresh={};bundle={};reused=0;evaluated=0;unavailable=Counter()
 for mid in sorted(used):
  r=raws[mid];team_damage={team:sum(number(x.get('totalDamageDealtToChampions')) or 0 for x in r['participants'] if x['teamId']==team) for team in {x['teamId'] for x in r['participants']}}
  assert len(eligibility[mid])==1,'inconsistent_snapshot_eligibility'
  input_key=digest([implementation,r,names,sorted(eligibility[mid])])
  output=dest/(mid+'.json');entry=cached.get(mid,{})
  cached_bytes=output.read_bytes() if entry.get('input')==input_key and output.is_file() else None
  if cached_bytes is not None and hashlib.sha256(cached_bytes).hexdigest()==entry.get('output'):
   reused+=1;fresh[mid]=entry
   bundle[mid]=json.loads(cached_bytes)
   if entry['available']:evaluated+=1
   else:unavailable[entry['reason']]+=1
   continue
  # Reuse the original pure scoring function. Do not invent a second MVP formula for the preview.
  scored={'stats_eligible':next(iter(eligibility[mid])),'queue_id':r['queueId'],'game_mode':r['gameMode'],'participants':[
   {'participant_id':x['participantId'],'team_id':x['teamId'],'win':x.get('win'),**{k:number(x.get(v)) for k,v in [('kills','kills'),('deaths','deaths'),('assists','assists'),('damage','totalDamageDealtToChampions'),('taken','totalDamageTaken'),('heal','totalHealsOnTeammates'),('cc_seconds','timeCCingOthers'),('shield_teammates','totalDamageShieldedOnTeammates')]}} for x in r['participants']]}
  annotate_awards(scored)
  if scored['performance']['available']:evaluated+=1
  else:unavailable[scored['performance']['reason']]+=1
  performances={x['participant_id']:x.get('performance') for x in scored['participants']}
  people=[]
  for raw in r['participants']:
   known=identity_to_profile.get(raw.get('puuid'));damage=number(raw.get('totalDamageDealtToChampions'))
   row={'slot':raw['participantId'],'team':raw['teamId'],'name':str((known or {}).get('name') or raw.get('riotIdGameName') or raw.get('summonerName') or '未记录昵称')[:80],
    'profile_id':known['id'] if known else None,'champion_id':number(raw.get('championId')),'win':raw.get('win') if type(raw.get('win')) is bool else None,
    **{key:number(raw.get(source)) for key,source in [('kills','kills'),('deaths','deaths'),('assists','assists'),('damage','totalDamageDealtToChampions'),('taken','totalDamageTaken'),('heal','totalHealsOnTeammates'),('shield','totalDamageShieldedOnTeammates'),('gold','goldEarned'),('penta_kills','pentaKills')]},
    'damage_share':damage/team_damage[raw['teamId']] if damage is not None and team_damage[raw['teamId']]>0 else None,
    'items':[number(raw.get('item'+str(i))) for i in range(7)],'augment_slots':[number(raw.get('playerAugment'+str(i))) for i in range(1,7)]}
   performance=performances[raw['participantId']]
   row['performance']={k:performance[k] for k in ['version','score','award','team_rank','tied']} if performance else None
   assert not forbidden&row.keys();people.append(row)
  result={'id':mid,'started_ms':r['gameStartTimestamp'],'duration':r['gameDuration'],'players':people,'performance':scored['performance']}
  write_json(output,result)
  bundle[mid]=result
  fresh[mid]={'input':input_key,'output':hashlib.sha256(output.read_bytes()).hexdigest(),'available':scored['performance']['available'],'reason':scored['performance'].get('reason')}
 if missing:raise RuntimeError(f'unmatched_player_views: {missing}; refusing to publish incomplete details')
 write_json(cache_path,fresh)
 write_json(PROJECT/'work/build/cache/details.bundle.json',{'build_id':snapshot['build_id'],'details':bundle})
 for stale in dest.glob('m-*.json'):
  if stale.stem not in used:stale.unlink()
 index={'version':2,'build_id':snapshot.get('build_id'),'snapshot_sha256':hashlib.sha256(payload).hexdigest(),'profiles':aliases,'coverage':{'matches':len(used),'player_views':sum(map(len,aliases.values())),'unmatched_views':missing}}
 (dest/'index.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 # 按玩家拆索引：全量 index 有 880KB，而打开战报只需自己那几十 KB
 index_dir=dest/'index';index_dir.mkdir(exist_ok=True)
 for stale in index_dir.glob('*.json'):stale.unlink()
 for pid,rows in aliases.items():(index_dir/(pid+'.json')).write_text(json.dumps(rows,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 (ROOT/'match-details-validation.json').write_text(json.dumps({**index['coverage'],'snapshot_sha256':index['snapshot_sha256'],'profiles':{p['name']:{'matched':len(aliases[p['id']]),'saved':len(p.get('recent',[]))} for p in profiles},'skipped_unreadable':skipped,'raw_identity_exported':False,'evaluated_matches':evaluated,'unavailable_awards':dict(unavailable)},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({**index['coverage'],'evaluated_matches':evaluated,'unavailable_awards':dict(unavailable),'reused_matches':reused,'rebuilt_matches':len(used)-reused},ensure_ascii=False))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--snapshot',type=Path,default=FULL);ap.add_argument('--incremental',action='store_true');args=ap.parse_args();prepare(args.snapshot,args.incremental)
