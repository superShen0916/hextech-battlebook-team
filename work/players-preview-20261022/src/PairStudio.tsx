import {useEffect,useRef,useState} from 'react';
import type {Profile,Match,Dictionaries} from './App';
import {Portrait,isRef,type Visuals,type Preferences} from './experience';
import {DuoBadges} from './Achievements';
import {buildPairStory} from '../lib/pair-story';
import {loadProfile} from '../lib/profile-loader';
import {drawPairPoster} from '../lib/duo-poster';
import {track} from '../lib/analytics';
const n=(v?:number|null,d=0)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:d}):'—';
const pc=(v?:number|null)=>typeof v==='number'?n(v*100,1)+'%':'—';
const day=(v?:number|null)=>v?new Date(v).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'}):'—';
const share=(p:Profile)=>p.history_scope==='shared'?`/share/?subject=${encodeURIComponent(p.source_id||'')}&name=${encodeURIComponent(p.name)}`:`/share/?player=${encodeURIComponent(p.id)}`;

export function PairStudio({profiles,visuals,preferences,dictionary,onChoose,onMatch,initialId}:{profiles:Profile[];visuals:Visuals;preferences:Preferences;dictionary:Dictionaries;onChoose:(id:string)=>void;onMatch:(id:string,match:Match)=>void;initialId?:string}){
 const box=useRef<HTMLElement>(null),[enabled,setEnabled]=useState(false);
 useEffect(()=>{const observer=new IntersectionObserver(rows=>{if(rows.some(r=>r.isIntersecting)){setEnabled(true);observer.disconnect();}},{rootMargin:'200px'});if(box.current)observer.observe(box.current);return()=>observer.disconnect();},[]);
 const find=(key:string,nameKey:string)=>{const q=new URLSearchParams(location.search);return profiles.find(p=>p.id===q.get(key)&&p.name===q.get(nameKey));};
 const initialA=find('a','an')||profiles.find(p=>p.id===initialId)||profiles.find(p=>isRef(p,preferences.self))||profiles[0];
 const initialB=find('b','bn')||profiles.find(p=>p.name===initialA?.teammates?.find(t=>profiles.some(p=>p.id!==initialA.id&&p.name===t.name))?.name)||profiles.find(p=>p.id!==initialA?.id);
 const[aId,setA]=useState(initialA?.id||''),[bId,setB]=useState(initialB?.id||'');
 const[poster,setPoster]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');const generation=useRef(0);
 const a=profiles.find(p=>p.id===aId),b=profiles.find(p=>p.id===bId);
 // 大厅摘要只带最近 200 场，而并肩统计要全量逐局；选中两人后按需补拉完整档案
 const[fullA,setFullA]=useState<Profile|null>(null),[fullB,setFullB]=useState<Profile|null>(null);
 useEffect(()=>{let alive=true;if(!enabled)return;if(!a?.has_detail){setFullA(null);return;}
  setFullA(null);
  loadProfile(a)
   .then(d=>{if(alive&&d)setFullA({...a,...d});}).catch(()=>{});
  return()=>{alive=false;};
 },[a?.id,a?.detail_url,enabled]);
 useEffect(()=>{let alive=true;if(!enabled)return;if(!b?.has_detail){setFullB(null);return;}
  setFullB(null);
  loadProfile(b)
   .then(d=>{if(alive&&d)setFullB({...b,...d});}).catch(()=>{});
  return()=>{alive=false;};
 },[b?.id,b?.detail_url,enabled]);
 useEffect(()=>{generation.current++;setPoster('');setMessage('');},[aId,bId]);
 useEffect(()=>()=>{if(poster)URL.revokeObjectURL(poster);},[poster]);
 if(!a||!b)return null;
 const story=buildPairStory(fullA||a,fullB||b,dictionary),{source,row,games,wins,rate,losses}=story,same=aId===bId;
 const select=(side:'a'|'b',id:string)=>{track('pair_select',{detail:JSON.stringify({side,has_games:Boolean(id)})},300);if(side==='a'){setA(id);if(id===bId)setB(aId);}else{setB(id);if(id===aId)setA(bId);}};
 const makePoster=async()=>{if(!row||same||!source)return;const run=++generation.current;setBusy(true);setMessage('正在绘制双人纪念卡…');track('pair_poster',{detail:JSON.stringify({games,wins})});try{
  const url=await drawPairPoster({a:a.name,b:b.name,avatarA:visuals[a.id]?.avatar_url,avatarB:visuals[b.id]?.avatar_url,story});
  if(run===generation.current){setPoster(url);setMessage('纪念卡已生成 · 1080 × 2400 PNG');}else URL.revokeObjectURL(url);
 }catch{setMessage('这次未能生成，请重试。');}finally{setBusy(false);}};
 const copyLink=async()=>{const url=new URL(location.origin+location.pathname);url.search=new URLSearchParams({a:a.id,an:a.name,b:b.id,bn:b.name}).toString();url.hash='together';track('pair_link',{detail:JSON.stringify({games})});try{await navigator.clipboard.writeText(url.toString());setMessage('双人战报链接已复制；本地预览链接仅本机可用。');}catch{setMessage('暂时无法复制链接，可先保存纪念卡。');}};
 return <section className="pair-studio" id="together" ref={box}>
  <div className="lobby-section-head"><div><p className="section-kicker">BETTER TOGETHER</p><h2>我们的并肩档案</h2></div><span className="section-context">嘴上互相嫌弃，排队从没少你</span></div>
  <div className="pair-layout"><div className="pair-selection">
   <label>一位玩家<select aria-label="双人战报第一位玩家" value={aId} onChange={e=>select('a',e.target.value)} disabled={busy}>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><span className="pair-cross" aria-hidden="true">×</span>
   <label>另一位玩家<select aria-label="双人战报第二位玩家" value={bId} onChange={e=>select('b',e.target.value)} disabled={busy}>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
   <p className="pair-selection-note">顺风一起笑，逆风一起扛。<br/>选俩名字，看看咱这固定节目。</p>
   <div className="pair-share-links"><a href={share(a)}>看 {a.name} 的朋友荣誉 ↗</a><a href={share(b)}>看 {b.name} 的朋友荣誉 ↗</a></div>
  </div><div className="pair-ticket" aria-live="polite">
   <div className="ticket-top"><span>THE DUO ARCHIVE</span><span>并肩存档 / ⬡</span></div>
   <div className="pair-identities"><button onClick={()=>onChoose(a.id)}><Portrait profile={a} visual={visuals[a.id]} large/><strong>{a.name}</strong></button><span className="pair-thread" aria-hidden="true">＋</span><button onClick={()=>onChoose(b.id)}><Portrait profile={b} visual={visuals[b.id]} large/><strong>{b.name}</strong></button></div>
   {row&&!same?<>
    <div className="pair-numbers"><div><strong>{n(games)}</strong><span>场有效同队</span></div><div><strong>{pc(rate)}</strong><span>同队胜率</span></div></div>
    <div className="duo-scoreline"><span>{n(wins)} 场一起赢</span><i>/</i><span>{n(losses)} 场一起扛</span>{story.longest!==null&&<><i>/</i><span>最长 {story.longest} 连胜</span></>}</div>
    {story.complete&&<p className="duo-date">已收录的并肩时光 · {day(story.oldest)} — {day(story.newest)}</p>}
    {!!story.recent.length&&<div className="duo-recent"><span>最近 {story.recent.length} 场同队 <b>{story.recent.filter(m=>m.player.win).length}胜</b></span><div aria-label="最近同队对局，从旧到新">{[...story.recent].reverse().map(m=><button className={m.player.win?'won':'lost'} key={m.id} onClick={()=>source&&onMatch(source.id,m)} title={day(m.started_ms)+' · 点击看战报'}>{m.player.win?'胜':'负'}</button>)}</div><small>旧 → 新 · 点击回看</small></div>}
    <div className="duo-section-heading"><h3>并肩时，我们的样子</h3><span>只看这段同队样本</span></div>
    <div className="duo-people">{story.people.map(p=><article key={p.name}><h4>{p.name}</h4><div className="duo-person-stats"><span>KDA<b>{n(p.kda,2)}</b></span><span>每分钟伤害<b>{n(p.dpm)}</b></span><span>自评 MVP / ACE<b>{n(p.mvp)} / {n(p.ace)}</b></span></div><p>{p.heroes.length?p.heroes.join(' · '):'同队英雄记录待补'}</p>{p.samples===null&&<small>逐局样本尚未齐备，缺项暂不推算。</small>}</article>)}</div>
    <div className="duo-section-heading"><h3>彼此战报里的荣誉</h3><span>原有 20 场门槛 · 保留并列</span></div>
    {story.honors.length?<div className="duo-honors">{story.honors.slice(0,6).map(h=><article key={h.from+h.title}><span>⬡ {h.title}{h.tied?' · 并列':''}</span><strong>{h.winner}</strong><small>来自 {h.from} 的战报 · {n(h.samples)} 场指标样本</small></article>)}</div>:<p className="duo-empty-honors">暂未进入彼此的荣誉榜，已经一起打过的每一场仍值得记住。</p>}
    {story.honors.length>6&&<p className="duo-extra">另有 {story.honors.length-6} 项荣誉，可在双方朋友战报里查看。</p>}
    {!!story.memories.length&&<><div className="duo-section-heading"><h3>一起打过，值得记得</h3><span>{source?.name} 的对局视角</span></div><div className="duo-memories">{story.memories.map(({label,match,hero})=><button key={match.id} onClick={()=>source&&onMatch(source.id,match)}><span>{label}<small>{day(match.started_ms)} · {hero}</small></span><b>{n(match.player.kills)} / {n(match.player.deaths)} / {n(match.player.assists)}<small>{n((match.player.damage||0)/10000,1)} 万伤害 · 回看 ↗</small></b></button>)}</div></>}
    <DuoBadges story={story} profile={a}/>
    <p className="pair-quote">有些默契，是一场一场打出来的。</p>
    <p className="pair-scope">来自 {source?.name} 的{source?.history_scope==='shared'?'部分同队样本':'已收录个人历史'}，不代表完整共同历史。同队不代表预先组队。荣誉分别来自双方各自的已收录战报；MVP / ACE 为工具自评。{!story.complete?'逐局关联尚未齐备，时间、近期战况和代表对局暂不推算。':''}</p>
   </>:<div className="pair-no-data"><strong>{same?'挑选两位不同的玩家':'还没有可用的同队统计'}</strong><p>暂时没有记录不代表没有一起玩过，等更多战报归档后再来看看。</p></div>}
   <div className="pair-actions"><button className="button" disabled={!row||same||busy} onClick={makePoster}>{busy?'绘制中…':'生成双人纪念卡 ↗'}</button><button className="ghost" onClick={copyLink}>复制这对搭档的链接</button></div><p className="pair-status" role="status">{message}</p>
  </div></div>
  {poster&&<div className="pair-poster-preview"><img src={poster} alt={`${a.name} 与 ${b.name} 的双人纪念卡`}/><div><h3>把一起打过的故事，存成一张纪念卡。</h3><p>共同胜负、双方表现、搭档荣誉和代表对局。<br/>原图 1080 × 2400 像素。</p><a className="button" href={poster} download={`${a.name}与${b.name}_双人战报.png`}>保存纪念卡 PNG ↓</a></div></div>}
 </section>;
}
