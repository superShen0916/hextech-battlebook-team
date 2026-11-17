import type {Profile,Dictionaries} from './App';
import {Portrait,type Visual} from './experience';
import type {RecapRoided} from '../lib/recaps';

const date=(v:number)=>new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const num=(v:number)=>v.toLocaleString('zh-CN',{maximumFractionDigits:1});

/** 本周最胡：已建档名册里单局伤害占本队五人合计最高的一把；缺的字段省略，不补零。 */
export default function RoidedCard({row,profile,visual,dictionary,onOpen}:{row:RecapRoided;profile?:Profile;visual?:Visual;dictionary:Dictionaries;onOpen:()=>void}){
 const hero=dictionary.champions[String(row.champion_id)]?.name||row.champion_name;
 const share=typeof row.damage_share==='number'&&Number.isFinite(row.damage_share)?(row.damage_share*100).toFixed(1)+'%':null;
 const kda=typeof row.kills==='number'&&typeof row.deaths==='number'&&typeof row.assists==='number'?`${row.kills} / ${row.deaths} / ${row.assists}`:null;
 const slots=(kind:'items'|'augments',values?:(number|null)[])=>(values||[]).filter(id=>typeof id==='number'&&id>0).map((id,i)=>{const entry=dictionary[kind][String(id)],url=entry?.icon_url?.startsWith('/assets/')?entry.icon_url:null;return <span className={'roided-slot roided-'+kind} key={kind+'-'+i+'-'+id} title={entry?.name||undefined}>{url?<img src={url} alt="" loading="lazy"/>:<i aria-hidden="true">⬡</i>}</span>;});
 const gear=slots('items',row.items),hexes=slots('augments',row.augments);
 return <section className="roided-panel" data-result={row.win===true?'won':row.win===false?'lost':undefined} aria-label="本周最胡">
  <div className="roided-heading"><p className="section-kicker">MOST DAMAGE SHARE / 本周最胡</p><span className="roided-badge">本自然周 · 北京时间周一至今</span></div>
  <button className="roided-card" onClick={onOpen} aria-label={`打开 ${row.name||row.profile_id} 的玩家档案`}>
   {profile&&<Portrait profile={profile} visual={visual} large/>}
   <div className="roided-body">
    <div className="roided-title"><h3>{row.name||profile?.name||row.profile_id}</h3>{hero&&<span className="roided-hero">{hero}</span>}{typeof row.win==='boolean'&&<span className={'roided-result '+(row.win?'won':'lost')}>{row.win?'胜':'负'}</span>}</div>
    <div className="roided-metrics">{share&&<div className="roided-share"><strong>{share}</strong><small>本队伤害占比</small></div>}{typeof row.damage==='number'&&<div><strong>{num(row.damage)}</strong><small>本局伤害</small></div>}{kda&&<div><strong>{kda}</strong><small>K / D / A</small></div>}</div>
   </div>
   {(!!gear.length||!!hexes.length)&&<div className="roided-build">{!!gear.length&&<div className="roided-slot-row">{gear}</div>}{!!hexes.length&&<div className="roided-slot-row">{hexes}</div>}</div>}
  </button>
  <p className="roided-foot">本周 = 北京时间周一 00:00 起，与你上面选的日期/范围无关；只比已建档名册里本队五人伤害齐全的单局{typeof row.started_ms==='number'?` · ${date(row.started_ms)}`:''}。战绩玩梗，不是官方奖项。</p>
 </section>;
}
