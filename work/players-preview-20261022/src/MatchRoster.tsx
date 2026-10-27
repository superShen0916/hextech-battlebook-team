import {useEffect,useState} from 'react';
import type {Profile,Match,Dictionaries} from './App';
import {Portrait,type Visuals} from './experience';
type Person=Match['player']&{slot:number;team:number;name:string;profile_id:string|null;shield?:number|null;items:(number|null)[]};
type Detail={id:string;started_ms:number;duration:number;players:Person[];performance?:{version:string;available:boolean;reason:string|null}};
type MatchIndex={profiles:Record<string,Record<string,{file:string;slot:number}>>};
type ProfileIndex=Record<string,{file:string;slot:number}>;
// 按玩家缓存：全量 index 有 880KB，取自己那份通常只有几十 KB
const indexCache=new Map<string,Promise<ProfileIndex>>();
async function loadIndex(id:string,revision=''):Promise<ProfileIndex>{
 const key=id+revision,cached=indexCache.get(key);if(cached)return cached;
 const task=(async()=>{
  const own=await fetch(`/matches/index/${encodeURIComponent(id)}.json`,{cache:'no-store'});
  if(own.ok)return await own.json() as ProfileIndex;
  const all=await fetch('/matches/index.json',{cache:'no-store'});
  if(!all.ok)throw Error('missing_index');
  const data=await all.json() as MatchIndex;
  return data.profiles[id]||{};
 })().catch(e=>{indexCache.delete(key);throw e;});
 indexCache.set(key,task);return task;
}
const n=(v?:number|null,d=0)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:d}):'—';
const damage=(v?:number|null)=>typeof v==='number'?v>=10000?n(v/10000,1)+'万':n(v):'—';
export default function MatchRoster({profile,match,profiles,visuals,dictionary,onHex,onChoose}:{profile:Profile;match:Match;profiles:Profile[];visuals:Visuals;dictionary:Dictionaries;onHex:(id:number)=>void;onChoose:(id:string)=>void}){
 const[data,setData]=useState<{detail:Detail;slot:number}|null>(null),[state,setState]=useState('loading'),[retry,setRetry]=useState(0);
 useEffect(()=>{let current=true;const abort=new AbortController();setData(null);setState('loading');
  const load=async()=>{try{
   const index=await loadIndex(profile.id,profile.detail_url),entry=index[match.id];
   if(!entry){if(current)setState('missing');return;}
   if(!/^m-[a-f0-9]{20}$/.test(entry.file))throw Error('invalid_reference');
   const response=await fetch('/matches/'+entry.file+'.json',{cache:'no-store',signal:abort.signal});if(!response.ok)throw Error('read_failed');const detail=await response.json() as Detail;
   const player=detail.players?.find(p=>p.slot===entry.slot),teams=new Map<number,number>();for(const p of detail.players||[])teams.set(p.team,(teams.get(p.team)||0)+1);
   if(detail.id!==entry.file||detail.started_ms!==match.started_ms||detail.duration!==match.duration||detail.players.length!==10||new Set(detail.players.map(p=>p.slot)).size!==10||teams.size!==2||[...teams.values()].some(v=>v!==5)||!player||(['champion_id','kills','deaths','assists','win'] as const).some(k=>(player[k]??null)!==(match.player[k]??null)))throw Error('match_mismatch');
   if(current){setData({detail,slot:entry.slot});setState('ready');}
  }catch(e){if(current&&!abort.signal.aborted)setState('error');}};load();return()=>{current=false;abort.abort();};
 },[profile.id,match.id,match.started_ms,retry]);
 const self=data?.detail.players.find(p=>p.slot===data.slot),teams=data?[...new Set(data.detail.players.map(p=>p.team))].sort((a,b)=>Number(b===self?.team)-Number(a===self?.team)):[];
 return <section className="match-roster" aria-label="完整十人赛后战报"><div className="roster-heading"><div><p className="section-kicker">WHO WAS IN THIS GAME</p><h3>这把谁在 C，面板说了算</h3><p>两队阵容 · 每位玩家的赛后数据、装备与海克斯</p></div><span>自评 MVP / ACE · v0.5</span></div>
  {state==='loading'&&<p role="status" className="roster-loading">正在翻这一把的十人战报…</p>}
  {state==='missing'&&<p className="roster-loading">这一把的十人明细还没归档，先保留上面的个人记录。</p>}
  {state==='error'&&<div className="roster-loading" role="status">暂时没能读取同场明细。<button onClick={()=>{indexCache.delete(profile.id);setRetry(retry+1);}}>重新读取</button></div>}
  {data&&<><div className="roster-awards-summary" aria-label="本局MVP与ACE">{data.detail.performance?.available?['MVP','ACE'].map(award=>{const winners=data.detail.players.filter(p=>p.performance?.award===award);return <div className={'roster-award-summary '+award.toLowerCase()} key={award}><b>自评 {award}{winners.length>1?' · 并列':''}</b><span>{winners.map(p=>p.name).join(' / ')}</span></div>;}):<p className="roster-awards-unavailable">{data.detail.performance?.reason==='ineligible_match'?'该局重开或未正常结束，不评 MVP / ACE。':'该局关键评分数据不足，暂不评 MVP / ACE。'}</p>}</div><div className="roster-teams">{teams.map(team=>{const rows=data.detail.players.filter(p=>p.team===team).sort((a,b)=>Number(b.slot===data.slot)-Number(a.slot===data.slot)||a.slot-b.slot),win=rows[0]?.win;return <section className={'roster-team '+(win?'team-won':'team-lost')} key={team}><header><h4>{team===self?.team?'与 '+profile.name+' 同队':'对面那一队'}</h4><span>{win===true?'胜利':win===false?'失利':'结果待补'}</span></header>{rows.map(p=>{const known=profiles.find(x=>x.id===p.profile_id),hero=dictionary.champions[String(p.champion_id)],augments=[...new Set(p.augment_slots?.filter((id):id is number=>typeof id==='number'&&id>0)||[])];return <article key={p.slot} className={'roster-person'+(p.slot===data.slot?' selected-person':'')}>
   <div className="roster-person-heading"><div className="roster-player-identity">{hero?.icon_url?<img className="roster-champion-icon" src={hero.icon_url} alt={hero.name||p.champion_name||'英雄'} loading="lazy"/>:known?<Portrait profile={known} visual={visuals[known.id]}/>:<span className="roster-fallback">?</span>}<div>{known?<button className="roster-player-link" onClick={()=>onChoose(known.id)}>{p.name} ↗</button>:<strong>{p.name}</strong>}<small>{hero?.name||p.champion_name||'英雄待补'}{p.slot===data.slot?' · 当前查看':''}</small>{p.performance?.award&&<span className={'roster-award-badge '+p.performance.award.toLowerCase()} title={`自评 v${data.detail.performance?.version||'0.2'} · 表现分 ${n(p.performance.score,1)} · 队内第 ${n(p.performance.team_rank)}${p.performance.tied?' · 并列':''}`}>自评 {p.performance.award}{p.performance.tied?' · 并列':''}</span>}</div></div><b className="roster-kda">{n(p.kills)} / {n(p.deaths)} / {n(p.assists)}<small>K / D / A</small></b></div>
   <div className="roster-main-stats"><span>伤害 <b>{damage(p.damage)}</b></span><span>团队占比 <b>{typeof p.damage_share==='number'?n(p.damage_share*100,1)+'%':'—'}</b></span><span>承伤 <b>{damage(p.taken)}</b></span></div>
   <div className="roster-augments" aria-label={p.name+'的局末海克斯'}>{augments.length?augments.map(id=><button key={id} onClick={()=>onHex(id)}>{dictionary.augments[String(id)]?.icon_url&&<img src={dictionary.augments[String(id)].icon_url} alt="" loading="lazy"/>}<span>{dictionary.augments[String(id)]?.name||'海克斯 #'+id}</span></button>):<span className="muted">这位的海克斯记录待补。</span>}</div>
   <details className="roster-equipment"><summary>装备与更多数据 <span>⌄</span></summary><div className="roster-extra-stats">{p.performance&&<span>自评表现分 <b>{n(p.performance.score,1)} · 队内第 {n(p.performance.team_rank)}</b></span>}<span>治疗队友 <b>{damage(p.heal)}</b></span><span>队友护盾 <b>{damage(p.shield)}</b></span><span>金币 <b>{n(p.gold)}</b></span></div><div className="roster-items">{p.items.filter((id):id is number=>typeof id==='number'&&id>0).map((id,i)=><span key={id+'-'+i} title={dictionary.items[String(id)]?.name||'装备 #'+id}>{dictionary.items[String(id)]?.icon_url&&<img src={dictionary.items[String(id)].icon_url} alt="" loading="lazy"/>}<span>{dictionary.items[String(id)]?.name||'装备 #'+id}</span></span>)}</div></details>
  </article>;})}</section>;})}</div></>}
  <p className="roster-note">MVP / ACE 为工具自评 v0.5：胜方队内最高分为 MVP，败方为 ACE，精确同分并列。可以回看赛后面板，不能播放游戏录像。海克斯为局末持有，不表示选取顺序或实战触发次数。已建档朋友的名字可进入个人页。</p>
 </section>;
}
