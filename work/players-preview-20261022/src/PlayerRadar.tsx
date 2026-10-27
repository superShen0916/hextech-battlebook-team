import {useId,useState} from 'react';
import type {Profile} from './App';
import './player-radar.css';

const axes = [
  {key:'dpm', sample:'dpm', label:'输出', unit:'每分钟对英雄伤害'},
  {key:'taken', sample:'taken', label:'承伤', unit:'场均承受伤害'},
  {key:'heal', sample:'heal', label:'治疗', unit:'场均对队友治疗'},
  {key:'kill_participation', sample:'kill_participation', label:'参团', unit:'平均参团率'},
  {key:'kda', sample:'kda', label:'KDA', unit:'总击杀助攻 ÷ 总死亡'},
  {key:'win_rate', sample:'wins', label:'胜率', unit:'有效对局胜率'},
] as const;
const finite = (v:unknown):v is number => typeof v === 'number' && Number.isFinite(v);
const format = (value:unknown, key:string) => !finite(value) ? '—' :
  ['win_rate','kill_participation'].includes(key) ? (value*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%' :
  value.toLocaleString('zh-CN',{maximumFractionDigits:key==='kda'?2:0});
function point(index:number, radius:number) {
  const angle = index*Math.PI/3-Math.PI/2;
  return [180+Math.cos(angle)*radius,155+Math.sin(angle)*radius];
}
const polygon = (radius:number) => axes.map((_,i)=>point(i,radius).join(',')).join(' ');

function measurements(profile:Profile,peers:Profile[]) {
  return axes.map(axis=>{
    const value = profile.summary?.[axis.key];
    const samples = profile.summary?.samples?.[axis.sample];
    const pool = peers.filter(p=>finite(p.summary?.[axis.key]) && (p.summary?.samples?.[axis.sample]??0)>=5)
      .map(p=>p.summary![axis.key] as number);
    const eligible = finite(value) && finite(samples) && samples>=5 && pool.length>=2;
    const rank = eligible ? 100*(pool.filter(v=>v<value).length+(pool.filter(v=>v===value).length-1)/2)/(pool.length-1) : null;
    return {...axis,value,samples,pool:pool.length,rank};
  });
}

export default function PlayerRadar({profile, profiles}:{profile:Profile;profiles:Profile[]}) {
  const titleId = useId(), selectId = useId();
  const [selection,setSelection] = useState({owner:profile.id,id:''});
  const shared = profile.history_scope === 'shared';
  const peers = profiles.filter(p=>(p.history_scope==='shared')===shared);
  const comparison = peers.find(p=>p.id!==profile.id && selection.owner===profile.id && p.id===selection.id);
  const data = measurements(profile,peers), other = comparison ? measurements(comparison,peers) : null;
  const complete = data.every(d=>d.rank!==null);
  const otherComplete = other?.every(d=>d.rank!==null);
  const candidates = peers.filter(p=>p.id!==profile.id);
  return <section className="panel player-radar" aria-labelledby={titleId}>
    <div className="panel-heading"><div><p className="section-kicker">PLAYER SIGNATURE</p><h2 id={titleId}>六维表现 · {profile.name}</h2></div><span>全部英雄 · {format(profile.summary?.games,'games')} 场有效对局</span></div>
    <div className="radar-compare-toolbar"><label htmlFor={selectId}>对比玩家<select id={selectId} aria-label="选择雷达图对比玩家" value={comparison?.id||''} disabled={!candidates.length} onChange={e=>setSelection({owner:profile.id,id:e.target.value})}><option value="">{candidates.length?'选择另一位玩家':'暂无同类玩家可对比'}</option>{candidates.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>{comparison&&<button className="ghost" onClick={()=>setSelection({owner:profile.id,id:''})}>取消对比</button>}<span>{shared?'同队样本之间比较':'个人历史之间比较'}</span></div>
    <div className="player-radar-body">
      <figure className="player-radar-figure">
        <svg viewBox="0 0 360 310" role="img" aria-label={`${profile.name}${comparison?`与${comparison.name}的对比`:'的六维'}雷达图，绿色实线为当前玩家，金色虚线为对比玩家，灰色虚线为中位参考。${complete&&(!other||otherComplete)?'':'部分维度样本不足，仅显示可比较的点。'}`}>
          {[.25,.5,.75,1].map(r=><polygon key={r} points={polygon(106*r)} className={r===.5?'radar-median':'radar-grid'}/>)}
          {axes.map((a,i)=><line key={a.key} x1="180" y1="155" x2={point(i,106)[0]} y2={point(i,106)[1]} className="radar-grid"/>)}
          {complete&&<polygon className="radar-shape" points={data.map((d,i)=>point(i,106*d.rank!/100).join(',')).join(' ')}/>}
          {otherComplete&&other&&<polygon className="radar-shape radar-shape-compare" points={other.map((d,i)=>point(i,106*d.rank!/100).join(',')).join(' ')}/>}
          {data.map((d,i)=>{const p=point(i,134);return <g key={d.key}>
            {d.rank!==null&&<circle className="radar-dot" cx={point(i,106*d.rank/100)[0]} cy={point(i,106*d.rank/100)[1]} r="3.5"/>}
            {other?.[i].rank!=null&&<circle className="radar-dot radar-dot-compare" cx={point(i,106*other[i].rank!/100)[0]} cy={point(i,106*other[i].rank!/100)[1]} r="3.5"/>}
            <text x={p[0]} y={p[1]} textAnchor="middle" dominantBaseline="middle">{d.label}</text>
          </g>;})}
        </svg>
        <figcaption><span className="radar-legend-item"><i className="radar-legend-solid"/>{comparison?profile.name:'本站相对位置'}</span>{comparison&&<span className="radar-legend-item"><i className="radar-legend-compare"/>{comparison.name}</span>}<span className="radar-legend-item"><i className="radar-legend-dash"/>中位参考</span></figcaption>
        {comparison&&(!complete||!otherComplete)&&<p className="radar-incomplete" role="status">部分维度不足5场或缺失，仅显示已知数据和可比较的点。</p>}
      </figure>
      <dl className={'radar-values'+(comparison?' radar-values-comparing':'')}>{data.map((d,i)=><div key={d.key} data-radar-axis={d.key}>
        <dt>{d.label}<small>{d.unit}</small></dt><dd className={comparison?'radar-pair':undefined}><div data-radar-player={profile.id}>{comparison&&<span className="radar-value-player">{profile.name}</span>}<strong>{format(d.value,d.key)}</strong><small>{format(d.samples,'samples')} 场样本 · {d.rank===null?'暂不比较':`相对位置 ${Math.round(d.rank)} / 100 · ${d.pool} 人`}</small></div>{comparison&&other&&<div className="radar-other-value" data-radar-player={comparison.id}><span className="radar-value-player">{comparison.name}</span><strong>{format(other[i].value,d.key)}</strong><small>{format(other[i].samples,'samples')} 场样本 · {other[i].rank===null?'暂不比较':`相对位置 ${Math.round(other[i].rank!)} / 100 · ${other[i].pool} 人`}</small></div>}</dd>
      </div>)}</dl>
    </div>
    <p className="panel-note radar-scope">按账号全部已收录有效历史展示，不随英雄或对局筛选变化。{shared?'仅与本站同队样本档案比较。':'仅与本站个人档案比较。'}双方使用同一组玩家、同一套相对位置尺度，各项样本量分别显示。每项至少 5 场、至少 2 人才比较；缺失不按 0 计。越靠外表示该项数值越高，承伤、治疗受英雄和打法影响，不代表综合实力。</p>
    <details className="radar-method"><summary>怎么看这张图？</summary><p>六个方向分别按本站同类档案的数值排序，再换算为 0—100 的相对位置；并列取平均位置，全员相同时为 50，虚线是 50 中位参考。各项有效样本可能不同，少量场次容易波动；本站样本也不代表全服水平。雷达图不参与海斗分或 MVP / ACE 计算。</p></details>
  </section>;
}
