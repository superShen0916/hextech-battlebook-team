import {useEffect,useMemo,useState} from 'react';
import {rankEquipment,readIntel,type EquipmentGroup,type EquipmentSnapshot} from '../lib/version-intel';

const groups:[EquipmentGroup,string][]=[['items','单件装备'],['core','核心组合'],['boots','鞋子'],['starting','出门装'],['full','完整出装']];
const percent=(value:number)=>(value*100).toFixed(2)+'%';

export default function TencentEquipment(){
 const [data,setData]=useState<EquipmentSnapshot|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const [heroId,setHeroId]=useState('202'),[query,setQuery]=useState(''),[group,setGroup]=useState<EquipmentGroup>('items'),[sort,setSort]=useState('pick_rate');
 useEffect(()=>{
  const abort=new AbortController();setError('');setData(null);
  readIntel<EquipmentSnapshot>('/api/version-intel/tencent-equipment.json',abort.signal).then(value=>{
   if(value.schema_version!==1||value.source!=='Tencent'||value.mode!=='KIWI'||value.queue_id!==2400||value.patch!==null||value.sample_size!==null||!value.heroes?.length)throw new Error('腾讯出装数据格式不匹配，请稍后重试。');
   setData(value);
  }).catch(e=>{if(!abort.signal.aborted)setError(e.message);});
  return()=>abort.abort();
 },[retry]);
 const heroes=useMemo(()=>[...(data?.heroes||[])].filter(h=>(h.name+h.title+h.id).includes(query.trim())).sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')),[data,query]);
 const hero=heroes.find(h=>h.id===heroId)||heroes[0];
 const rows=useMemo(()=>rankEquipment(hero?.[group]||[],sort),[hero,group,sort]);
 if(error)return <section className="intel-message" role="alert">腾讯出装暂时无法读取：{error}<button onClick={()=>setRetry(r=>r+1)}>重新读取出装</button></section>;
 if(!data)return <p className="intel-message" role="status">正在读取腾讯海克斯出装统计…</p>;
 const age=hero?.stats_date?Math.floor((Date.now()-Date.parse(hero.stats_date+'T00:00:00+08:00'))/86400000):null;
 return <section className="intel-items equipment-panel" aria-label="腾讯海克斯出装统计">
  <div className="equipment-heading"><div><p className="eyebrow">HEXTECH EQUIPMENT</p><h2>给英雄，找一套顺手出装。</h2><p>海克斯大乱斗 · 腾讯装备使用率与胜率</p></div><span className="equipment-source">腾讯统计</span></div>
  <div className="equipment-meta"><span>统计日期 <b data-testid="equipment-date">{hero?.stats_date||'暂无'}</b></span><span>{data.heroes.filter(h=>h.available).length} 位英雄有数据</span><span>样本范围未公开</span>{age!==null&&age>3&&<span className="equipment-stale">这份统计距今 {age} 天</span>}</div>
  <p className="equipment-scope">腾讯未提供补丁号、统计时间区间及样本场数；本栏按来源日期展示，不随上方其他榜单的补丁切换。大区、段位及活动规则覆盖范围未公开。</p>
  <div className="equipment-controls"><label>找英雄<input type="search" aria-label="搜索出装英雄" placeholder="名字、称号或编号" value={query} onChange={e=>setQuery(e.target.value)}/></label><label>选择英雄<select aria-label="选择出装英雄" value={hero?.id||''} onChange={e=>setHeroId(e.target.value)}>{heroes.length?heroes.map(h=><option key={h.id} value={h.id}>{h.name} · {h.title}{h.available?'':' · 暂无统计'}</option>):<option value="">没有匹配的英雄</option>}</select></label><label>排列方式<select aria-label="出装排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="pick_rate">使用率优先</option><option value="win_rate">胜率优先</option></select></label></div>
  {hero&&<div className="equipment-champion"><img src={'/assets/champions/'+hero.id+'.png'} alt=""/><div><h3>{hero.name}<small>{hero.title}</small></h3><p>统计日期 {hero.stats_date||'未提供'} · <a href={data.source_url+'?championid='+hero.id} target="_blank" rel="noreferrer">腾讯原始数据 ↗</a></p></div></div>}
  <nav className="equipment-groups" aria-label="出装分类">{groups.map(([key,label])=><button key={key} aria-pressed={group===key} onClick={()=>setGroup(key)}>{label}<span>{hero?.[key].length||0}</span></button>)}</nav>
  <div className="equipment-table" aria-label={groups.find(([key])=>key===group)?.[1]}>
   <div className="equipment-row equipment-columns"><span>装备{group==='core'||group==='full'?'组合':''}</span><span>使用率</span><span>胜率</span></div>
   {rows.map((row,i)=><div className="equipment-row" key={row.items.join('-')}><div className="equipment-build"><span className="equipment-rank">{i+1}</span><div className="equipment-pieces">{row.items.map((id,j)=>{const item=data.items[id];return <span className="equipment-piece" key={id+'-'+j}>{item?.icon_url?<img src={item.icon_url} alt="" loading="lazy"/>:<span className="equipment-placeholder" aria-hidden="true">⬡</span>}<span>{item?.name||'装备 #'+id}</span></span>;})}</div></div><span data-label="使用率" className="equipment-pick">{percent(row.pick_rate)}</span><strong data-label="胜率">{percent(row.win_rate)}</strong></div>)}
   {!rows.length&&<p className="intel-message">{hero?'这个英雄暂时没有该类出装统计。':'没有匹配的英雄，试试其他名字。'}</p>}
  </div>
  <details className="intel-method equipment-method"><summary>如何理解这些出装数据？</summary><p>使用率与胜率沿用腾讯接口返回值。接口未说明统计分母、是否只计局末持有及具体出装顺序，所以核心组合中的排列不代表购买顺序；同一对局可以出现多件装备，单件使用率不需要相加为100%。</p><p>样本场数未公开，因此不计算置信区间或稳健排名。装备胜率会受英雄打法、经济和成型时间影响，不代表换上这件装备就能提高相同幅度的胜率。</p></details>
  <footer className="intel-footer"><p>数据来源：<a href={data.source_url+'?championid='+(hero?.id||'202')} target="_blank" rel="noreferrer">腾讯 mlol.qt.qq.com ↗</a><br/>最近获取 {new Date(data.retrieved_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})} · 统计日期范围 {data.stats_date_min} — {data.stats_date_max}</p><a href="https://hexdata.com.cn/items" target="_blank" rel="noreferrer">更多装备参考：Hexdata ↗</a></footer>
 </section>;
}
