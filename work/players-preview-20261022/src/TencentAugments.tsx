import {useEffect,useMemo,useState} from 'react';
import {rankTencentAugments,readIntel,type TencentAugmentSnapshot} from '../lib/version-intel';

const rarities=[['all','全部'],['silver','白银'],['gold','黄金'],['prismatic','棱彩']] as const;
const rarityName=(value:string)=>({silver:'白银',gold:'黄金',prismatic:'棱彩'}[value]||value);
export default function TencentAugments({heroId,onHeroChange}:{heroId:string;onHeroChange:(id:string)=>void}){
 const [data,setData]=useState<TencentAugmentSnapshot|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const [query,setQuery]=useState(''),[rarity,setRarity]=useState('all'),[tier,setTier]=useState('all'),[sort,setSort]=useState('tier');
 useEffect(()=>{const abort=new AbortController();setError('');
  readIntel<TencentAugmentSnapshot>('/api/version-intel/tencent-augments.json',abort.signal).then(value=>{
   if(value.schema_version!==1||value.source!=='Tencent'||value.mode!=='KIWI'||value.win_rate!==null||value.sample_size!==null||!value.heroes?.length)throw new Error('腾讯海克斯数据格式不匹配。');
   setData(value);
  }).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();
 },[retry]);
 const hero=data?.heroes.find(h=>h.id===heroId)||data?.heroes[0];
 const rows=useMemo(()=>rankTencentAugments((hero?.augments||[]).filter(row=>(rarity==='all'||row.rarity===rarity)&&(tier==='all'||(rarity==='all'?row.tier:row.rarity_tier)===tier)&&((data?.dictionary[row.id]?.name||'')+row.id).includes(query.trim())),sort,rarity!=='all'),[hero,data,rarity,tier,query,sort]);
 if(error)return <section className="intel-message" role="alert">腾讯海克斯暂时无法读取：{error}<button onClick={()=>setRetry(r=>r+1)}>重新读取海克斯</button></section>;
 if(!data)return <p className="intel-message" role="status">正在读取腾讯海克斯分档…</p>;
 return <section className="tencent-hex-panel" aria-label="腾讯英雄海克斯参考">
  <div className="equipment-heading"><div><p className="eyebrow">AUGMENT REFERENCE</p><h2>海克斯怎么搭，换个来源看看。</h2><p>腾讯接口分档 · 使用率</p></div><span className="equipment-source">腾讯统计</span></div>
  <p className="equipment-scope">本来源只提供使用率和 S/A/B/C 分档，没有海克斯胜率或样本场数；分档标准、统计窗口及覆盖范围未公开。需要胜率与样本时，可切回 AramHex。</p>
  <div className="equipment-controls tencent-hex-controls"><label>选择英雄<select aria-label="选择腾讯海克斯英雄" value={hero?.id||''} onChange={e=>onHeroChange(e.target.value)}>{[...data.heroes].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')).map(h=><option key={h.id} value={h.id}>{h.name} · {h.title}</option>)}</select></label><label>分档<select aria-label="腾讯海克斯分档" value={tier} onChange={e=>setTier(e.target.value)}><option value="all">全部分档</option>{['S','A','B','C'].map(value=><option key={value} value={value}>{value} 档</option>)}</select></label><label>排列方式<select aria-label="腾讯海克斯排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="tier">分档优先</option><option value="pick_rate">使用率优先</option></select></label></div>
  {hero&&<div className="equipment-champion"><img src={'/assets/champions/'+hero.id+'.png'} alt=""/><div><h3>{hero.name}<small>{hero.title}</small></h3><p>统计日期 <b data-testid="tencent-augment-date">{hero.stats_date||'未提供'}</b> · {hero.augments.length} 个海克斯 · 来源：腾讯</p></div></div>}
  <div className="hex-filter-row"><nav className="hex-rarity-filter" aria-label="腾讯海克斯稀有度">{rarities.map(([key,label])=><button key={key} aria-pressed={rarity===key} onClick={()=>setRarity(key)}>{label}<span>{(hero?.augments||[]).filter(row=>key==='all'||row.rarity===key).length}</span></button>)}</nav><label className="hex-search">搜索海克斯<input type="search" aria-label="搜索腾讯海克斯" value={query} onChange={e=>setQuery(e.target.value)} placeholder="海克斯名字或编号"/></label></div>
  <div className="hex-results-count">{rows.length} 项结果 · 分档沿用腾讯接口，不代表获胜概率</div>
  <div className="hex-card-grid" aria-label="腾讯海克斯卡片">{rows.map(row=>{const hex=data.dictionary[row.id],grade=rarity==='all'?row.tier:row.rarity_tier;return <article className={'hex-stat-card '+row.rarity} key={row.id} data-augment-id={row.id}>
   <header>{hex?.icon_url?<img src={hex.icon_url} alt="" loading="lazy"/>:<span className="hex-card-symbol" aria-hidden="true">⬡</span>}<div><span className="hex-card-rarity">{rarityName(row.rarity)} · #{row.id}</span><h3>{hex?.name||'海克斯 #'+row.id}</h3></div><span className={'hex-source-tier tier-'+grade} aria-label={'腾讯分档 '+grade}>{grade}</span></header>
   <div className="hex-card-stats"><div><span>使用率</span><strong>{(row.pick_rate*100).toFixed(2)}%</strong></div><div><span>{rarity==='all'?'综合分档':'同稀有度分档'}</span><b>{grade} 档</b></div></div>
   {hex?.description&&<details className="hex-effect"><summary>查看海克斯效果</summary><p>{hex.description}</p><small>字典说明 {hex.description_patch||'版本未标注'} · 动态数值以游戏内为准</small></details>}
  </article>;})}</div>
  {!rows.length&&<p className="intel-message">没有符合条件的海克斯，试试清除筛选。</p>}
  <footer className="intel-footer"><p>数据来源：<a href={data.source_url+'?championid='+(hero?.id||'157')} target="_blank" rel="noreferrer">腾讯 mlol.qt.qq.com ↗</a><br/>统计日期范围 {data.stats_date_min} — {data.stats_date_max} · 名称与效果来自本地海克斯字典</p><span>腾讯使用率与 AramHex 持有胜率分别展示</span></footer>
 </section>;
}
