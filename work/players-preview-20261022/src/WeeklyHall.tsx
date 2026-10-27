import {useEffect,useState} from 'react';
import type {Profile} from './App';
import {Portrait,StarButton,type Visuals,type Preferences} from './experience';
import MotionCard from './MotionCard';
import RatingRules from './RatingRules';
import {loadRecap} from '../lib/recaps';
import {track} from '../lib/analytics';
import {hallRanking,hallPlace,type HallRow as Row,type HallMode} from '../lib/hall-ranking';

type Report={start_ms:number;end_ms:number;through_ms:number;complete:boolean;players:Row[]};
type Weekly={build_id:string;as_of_ms:number;reports:Report[]};
const date=(v:number)=>new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const num=(v:number)=>v.toLocaleString('zh-CN',{maximumFractionDigits:1});
const signed=(v:number)=>(v>0?'+':'')+num(v);
const Crown=()=> <svg className="podium-crown" viewBox="0 0 80 60" fill="none" aria-hidden="true"><path d="M10 17 25 28 40 7 55 28 70 17 61 47H19L10 17Z" stroke="currentColor" strokeWidth="2" fill="currentColor" fillOpacity=".12"/><path d="M21 54H59M27 39H53" stroke="currentColor" strokeWidth="2"/><circle cx="40" cy="7" r="3" fill="currentColor"/><circle cx="10" cy="17" r="2" fill="currentColor"/><circle cx="70" cy="17" r="2" fill="currentColor"/></svg>;

export default function WeeklyHall({buildId,profiles,visuals,preferences,save,onChoose,search,onlyStars,mode='weekly'}:{buildId?:string;profiles:Profile[];visuals:Visuals;preferences:Preferences;save:(p:Preferences)=>void;onChoose:(id:string)=>void;search:string;onlyStars:boolean;mode?:HallMode}){
 const[data,setData]=useState<Weekly|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0),[week,setWeek]=useState(0),[message,setMessage]=useState('');
 useEffect(()=>{let alive=true;setError('');loadRecap<Weekly>('/api/weekly.json',buildId,{force:retry>0}).then(d=>{if(alive)setData(d);}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[buildId,retry]);
 useEffect(()=>setMessage(''),[mode]);
 const report=data?.reports[week],map=new Map(profiles.map(p=>[p.id,p])),total=mode==='total';
 const ranked=hallRanking(report?.players||[],mode);
 const matches=(r:Row)=>r.name.toLowerCase().includes(search.trim().toLowerCase())&&(!onlyStars||preferences.stars.some(p=>p.id===r.id&&p.name===r.name));
 const podium=ranked.filter(r=>r.tier!=='unrated'&&(total?r.rank!==null:r.games>0&&r.delta>0)).slice(0,3);
 const rest=ranked.filter(r=>!podium.some(p=>p.id===r.id));
 const movement=(r:Row)=>r.rank_change===null?(r.rank?'新入榜':'未定级'):r.rank_change>0?`↑ ${r.rank_change} 名`:r.rank_change<0?`↓ ${-r.rank_change} 名`:'排名持平';
 const weekText=(r:Row)=>r.games?`本周 ${signed(r.delta)} 分`:'本周未打 · +0 分';
 // 榜单浏览打点：谁在什么时候翻到了哪一档（周榜/总分榜）和哪一周；3 秒内同组合只记一次，避免切来切去刷表
 useEffect(()=>{const r=data?.reports[week];if(!r)return;track('weekly_hall_view',{detail:JSON.stringify({mode,week,label:date(r.start_ms).slice(0,5),complete:Boolean(r.complete),players:r.players.length})},3000);},[data,week,mode]);
 const copy=async()=>{if(!report)return;const text=`${date(report.start_ms).slice(0,5)} ${total?'海斗总分榜':'海斗周报'}${report.complete?' · 已结算':' · 进行中'}\n截至 ${date(report.through_ms)}\n`+ranked.filter(r=>total||r.games>0).map(r=>`${hallPlace(r,mode)??'未定级'}. ${r.name} ${total?num(r.score)+' 总分 · 本周 ':''}${signed(r.delta)} 分 · ${r.wins}胜${r.games-r.wins}负 · ${movement(r)}`).join('\n')+'\n周分每周重置，历周涨跌保留；总分排名与本周开始时的累计总分排名比较。\n'+location.href.split('#')[0]+'#players';track('weekly_copy',{detail:JSON.stringify({mode,week,mutuals:ranked.length})});try{await navigator.clipboard.writeText(text);setMessage(total?'海斗总分榜已复制。':'周报已复制，发群里看看这周谁在偷偷 C。');}catch{setMessage(text);}};
 if(error)return <div className="recap-status" role="alert">{error}<button onClick={()=>setRetry(r=>r+1)}>重试榜单</button></div>;
 if(!report)return <p className="recap-status" role="status">正在揭晓{total?'海斗总分榜':'每周之星'}…</p>;
 return <div className="weekly-hall hall-arena" data-board={mode}>
  <div className="weekly-heading"><div><p className="section-kicker">{total?'THE HALL OF FAME / 海斗总分榜':'THE WEEKLY ASCENT / 海斗周报'}</p><h2>{total?'海斗殿堂':'本周之星'}<span>{total?'每一场，都是实力的注脚。':'这周，谁在偷偷 C？'}</span></h2><p>{date(report.start_ms)} — {date(report.end_ms)} · 北京时间<br/>统计截至 {date(report.through_ms)} · {report.complete?'历史周已结算':'随网站数据更新'}</p></div><div className="weekly-tools"><label>翻阅周报<select aria-label="选择海斗周报" value={week} onChange={e=>{const next=Number(e.target.value);track('weekly_week',{detail:JSON.stringify({mode,week:next,label:date(data!.reports[next]?.start_ms||0).slice(0,5)})});setWeek(next);setMessage('');}}>{data!.reports.map((r,i)=><option key={r.start_ms} value={i}>{date(r.start_ms).slice(0,5)} 开始 · {r.complete?'已结算':'进行中'}</option>)}</select></label><button className="ghost" onClick={copy}>{total?'复制总分榜':'复制本周周报'} ↗</button></div></div>
  <div className="hall-intro"><span className="hall-live-dot"/><p>{total?'按累计海斗总分排名 · 历周涨跌保留，同分并列':'只看这周的上升势头 · 周一重置，截至本次数据更新'}</p><RatingRules/></div>
  <div className="podium-arena"><div className="stage-rig" aria-hidden="true"><i className="stage-beam beam-left"/><i className="stage-beam beam-center"/><i className="stage-beam beam-right"/><div className="stage-floor"/></div><div className="arena-orbit" aria-hidden="true"/><div className="arena-caption" aria-hidden="true">{total?'THE HAIDO THRONE':'RISE ABOVE THE REST'}<span>VICTORY LEAVES A SIGNATURE</span></div>
   <div className="weekly-podium">{podium.map((r,i)=>{const p=map.get(r.id),place=hallPlace(r,mode),tied=total&&ranked.filter(row=>row.rank===place).length>1;return p&&matches(r)?<div className={'podium-slot slot-'+(i+1)} key={r.id}>
    <MotionCard className={'weekly-star star-'+(i+1)} aria-label={`${total?'海斗总分':'本周涨分'}第${place}名 ${r.name}`}>
     <div className="star-splash" aria-hidden="true" style={{backgroundImage:visuals[r.id]?.splash_url?`url("${visuals[r.id].splash_url}")`:undefined}}/><div className="card-prism" aria-hidden="true"/><div className="rank-frame" aria-hidden="true"/><div className="star-watermark" aria-hidden="true">{String(place).padStart(2,'0')}</div>
     <div className="podium-card-head"><span className="star-place">{i===0?(total?'HAIDO LEADER':'WEEKLY STAR'):i===1?'SILVER HONORS':'BRONZE HONORS'}</span><span className="podium-rank">{tied?'并列 ':''}NO. {String(place).padStart(2,'0')}</span></div>
     {i===0&&<Crown/>}<button className="star-open" onClick={()=>{track('weekly_open',{detail:JSON.stringify({mode,place,from:'podium'})});onChoose(r.id);}}><Portrait profile={p} visual={visuals[r.id]} large/><h3>{r.name}</h3><strong className="star-value">{total?num(r.score):signed(r.delta)}<small>{total?'海斗分':'本周涨分'}</small></strong>
      <span className={'podium-week '+(r.delta<0?'negative':'')}>{total?weekText(r):`海斗总分 ${num(r.score)}`}<span>{movement(r)}</span></span>
      <p>{r.games} 场 · {r.wins} 胜 {r.games-r.wins} 负{r.games?` · ${num(r.wins/r.games*100)}%`:''}</p><small>{r.tier==='provisional'?'暂定样本 · ':''}翻开完整档案 <span>↗</span></small></button>
     <div className="podium-card-footer"><span>{i===0?'THE SPOTLIGHT IS YOURS':i===1?'CLOSE TO THE CROWN':'EARNED, NEVER GIVEN'}</span><StarButton profile={p} preferences={preferences} save={save}/></div>
    </MotionCard><div className="podium-plinth" aria-hidden="true"><b>{['I','II','III'][i]}</b><span>{total?'HAIDO RANK':'WEEKLY RANK'}</span></div></div>:null;})}</div>
  </div>
  {podium.length<3&&<p className="weekly-rule">{total?'已定级玩家不足三位，等待下一位挑战者。':podium.length?`本周已有 ${podium.length} 位正向涨分玩家，其余星位等待下一场高光。`:'本周暂未产生正向涨分之星。未打、掉分和未定级玩家仍在下方展示。'}</p>}
  <div className="weekly-list-head"><h3>{total?'海斗总分榜':'本周涨分榜'} · {podium.length===3?'第 4 名起':'其余玩家'}</h3><span>{total?'总分排位 / 本周涨跌，一眼看全':'本周向前走了多少，都记在这里'}</span></div>
  <div className="weekly-list">{rest.filter(matches).map(r=>{const p=map.get(r.id);return p?<article className="weekly-row" key={r.id}><span className="weekly-place">{hallPlace(r,mode)===null?'—':String(hallPlace(r,mode)).padStart(2,'0')}</span><button className="weekly-player" onClick={()=>{track('weekly_open',{detail:JSON.stringify({mode,place:hallPlace(r,mode),from:'list'})});onChoose(r.id);}}><Portrait profile={p} visual={visuals[r.id]}/><span><b>{r.name}</b><small>{r.games?`${r.games} 场 · ${r.wins} 胜 ${r.games-r.wins} 负`:'本周未打'}{r.tier==='unrated'?' · 未定级':r.tier==='provisional'?' · 暂定':''}</small></span></button><div className={'weekly-delta '+(!total&&r.delta<0?'negative':'')}><strong>{r.tier==='unrated'?'—':total?num(r.score):signed(r.delta)}</strong><small>{total?'海斗总分':'本周涨分'}</small></div><div className={'weekly-total '+(total&&r.delta<0?'negative':'')}><b>{r.tier==='unrated'?'—':total?signed(r.delta)+' 分':num(r.score)}</b><small>{total?'本周涨跌':'海斗总分'} · {movement(r)}</small></div><StarButton profile={p} preferences={preferences} save={save}/></article>:null;})}</div>
  {!ranked.some(matches)&&<p className="empty-state">没有符合筛选的玩家。排名沿用全榜，不因搜索重新编号。</p>}
  {message&&<p className="weekly-message" role="status">{message}</p>}
 </div>;
}
