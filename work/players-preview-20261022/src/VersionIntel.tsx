import {useEffect,useMemo,useState} from 'react';
import {rankRows,readIntel,selectPairs,type IntelIndex,type IntelOverview,type IntelDetail,type IntelHero} from '../lib/version-intel';
import {track} from '../lib/analytics';
import TencentEquipment from './TencentEquipment';
import TencentAugments from './TencentAugments';
import AugmentCards from './AugmentCards';

const n=(v:number)=>v.toLocaleString('zh-CN');
const pc=(v:number)=>(v*100).toFixed(1)+'%';
const date=(v:string)=>new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const rarity=(r:string)=>({silver:'白银',gold:'黄金',prismatic:'棱彩'}[r]||r);
const tabs=[['heroes','英雄胜率'],['augments','海克斯胜率'],['pairs','英雄 × 海克斯'],['items','装备情报']] as const;
type Tab=typeof tabs[number][0];
function HeroPortrait({hero}:{hero:IntelHero}){return <img className="intel-portrait" src={`/assets/champions/${hero.id}.png`} alt="" loading="lazy" onError={e=>{e.currentTarget.style.visibility='hidden';}}/>;}

export default function VersionIntel(){
 const[index,setIndex]=useState<IntelIndex|null>(null),[patch,setPatch]=useState(''),[data,setData]=useState<IntelOverview|null>(null);
 const[tab,setTab]=useState<Tab>(()=>(['heroes','augments','pairs','items'] as string[]).includes(new URLSearchParams(location.search).get('tab')||'')?new URLSearchParams(location.search).get('tab') as Tab:'heroes'),[query,setQuery]=useState(''),[sort,setSort]=useState('confidence'),[minimum,setMinimum]=useState(250),[page,setPage]=useState(1);
 const[pairSource,setPairSource]=useState(()=>new URLSearchParams(location.search).get('source')==='tencent'?'tencent':'aramhex'),[pairRarity,setPairRarity]=useState('all');
 const[heroId,setHeroId]=useState('157'),[detail,setDetail]=useState<IntelDetail|null>(null),[showPbe,setShowPbe]=useState(false);
 const[error,setError]=useState(''),[pairError,setPairError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const abort=new AbortController();readIntel<IntelIndex>('/api/version-intel/index.json',abort.signal).then(value=>{setIndex(value);setPatch(p=>p||value.default_patch);setError('');}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[retry]);
 useEffect(()=>{if(!patch)return;const abort=new AbortController();setData(null);setDetail(null);setError('');readIntel<IntelOverview>(`/api/version-intel/${patch}/overview.json`,abort.signal).then(value=>{if(value.patch!==patch)throw new Error('版本不匹配，请重新读取。');setData(value);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[patch,retry]);
 useEffect(()=>{
  setDetail(null);setPairError('');if(!data||tab!=='pairs'||pairSource!=='aramhex')return;
  const abort=new AbortController();readIntel<IntelDetail>(`/api/version-intel/${patch}/heroes/${heroId}.json`,abort.signal).then(value=>{
   if(value.patch!==patch||value.hero_id!==heroId||value.snapshot_at!==data.snapshot_at)throw new Error('搭配数据与当前版本快照不一致，请重试。');setDetail(value);
  }).catch(e=>{if(!abort.signal.aborted)setPairError(e.message);});return()=>abort.abort();
 },[data,patch,heroId,tab,retry,pairSource]);
 useEffect(()=>{setPage(1);},[patch,tab,query,sort,minimum,heroId,showPbe,pairRarity,pairSource]);
 const hero=data?.heroes.find(h=>h.id===heroId);
 const heroRows=useMemo(()=>rankRows((data?.heroes||[]).filter(h=>h.games>=minimum&&(h.name+h.title+h.id).includes(query.trim())),sort),[data,minimum,query,sort]);
 const augmentRows=useMemo(()=>rankRows((data?.augments||[]).filter(a=>a.games>=minimum&&(a.name+rarity(a.rarity)+a.id).includes(query.trim())),sort),[data,minimum,query,sort]);
 const pairRows=useMemo(()=>rankRows(selectPairs(detail?.pairs||[],showPbe,minimum).filter(p=>(pairRarity==='all'||data?.augment_dictionary[p.id]?.rarity===pairRarity)&&((data?.augment_dictionary[p.id]?.name||'')+p.id).includes(query.trim())),sort),[data,detail,minimum,showPbe,query,sort,pairRarity]);
 const count=tab==='heroes'?heroRows.length:tab==='augments'?augmentRows.length:pairRows.length;
 const pages=Math.max(1,Math.ceil(count/20)),offset=(Math.min(page,pages)-1)*20;
 const chooseHero=(id:string)=>{track('intel_detail',{detail:JSON.stringify({hero:id,from:tab})});setHeroId(id);setTab('pairs');setPairSource('aramhex');setQuery('');setShowPbe(false);};
 return <main className="site-shell intel-shell">
  <header className="intel-header"><a className="brand" href="/"><span className="brand-symbol">⬡</span><span>海克斯战报馆<small>HEXTECH BATTLEBOOK</small></span></a><a className="intel-back" href="/">← 返回玩家大厅</a><span className="intel-preview">版本快照</span></header>
  <section className="intel-hero"><div><p className="eyebrow">PATCH INTELLIGENCE</p><h1>英雄随机，<span>选择有据。</span></h1><p>看看这个版本谁更顺手，哪个海克斯更合拍。</p></div>{tab==='items'||(tab==='pairs'&&pairSource==='tencent')?<div className="equipment-context"><span>海克斯大乱斗</span><small>腾讯统计 · 按统计日期查看</small></div>:<label>统计补丁<select aria-label="统计补丁" value={patch} onChange={e=>{track('intel_patch',{detail:JSON.stringify({patch:e.target.value})});setPatch(e.target.value);setShowPbe(false);}}>{index?.datasets.map(d=><option key={d.patch} value={d.patch}>{d.patch}{d.patch===index.default_patch?' · 最新已收录':' · 历史快照'} · 常规规则</option>)}</select><small>按补丁分开统计 · 不跨版本混算</small></label>}</section>
   <nav className="intel-tabs" aria-label="情报分类">{tabs.map(([key,label])=><button key={key} aria-pressed={tab===key} onClick={()=>{track('intel_tab',{detail:JSON.stringify({tab:key,patch})});setTab(key);setQuery('');}}>{label}</button>)}</nav>
  {tab==='pairs'&&<nav className="intel-providers" aria-label="海克斯数据来源"><button aria-pressed={pairSource==='aramhex'} onClick={()=>setPairSource('aramhex')}>AramHex · 胜率与样本</button><button aria-pressed={pairSource==='tencent'} onClick={()=>setPairSource('tencent')}>腾讯 · 分档与使用率</button></nav>}
  {tab==='items'?<TencentEquipment/>:tab==='pairs'&&pairSource==='tencent'?<TencentAugments heroId={heroId} onHeroChange={setHeroId}/>:error?<div className="intel-message" role="alert">{error}<button className="button" onClick={()=>setRetry(r=>r+1)}>重新读取</button></div>:!data?<p className="intel-message" role="status">正在读取版本统计…</p>:<>
   <div className="intel-scope"><span className="intel-live">正式服 {data.patch} · 常规</span><span>数据截至 {date(data.snapshot_at)}</span><span>来源：<a href={data.source_url} target="_blank" rel="noreferrer">AramHex ↗</a></span></div>
   <section className="intel-metrics" aria-label="统计样本"><div><span>有效对局</span><strong>{n(data.matches.valid)}</strong><small>{data.regions.length} 个大区的已采集样本</small></div><div><span>有记录的英雄</span><strong>{data.heroes.length}</strong><small>全体样本 · 不等于全服全集</small></div><div><span>正式服海克斯</span><strong>{data.augments.length}</strong><small>{Object.keys(data.provisional_augments).length?'另有 '+Object.keys(data.provisional_augments).length+' 个仅测试服参考':'仅统计本补丁局末持有'}</small></div></section>
   <p className="intel-caution">统计窗口 {date(data.window.start)} — {date(data.window.end_exclusive)}（不含终点）。只代表这些已采集对局；胜率描述历史表现，不是下一局的获胜概率。</p>
   <>
    {tab==='pairs'&&<div className="intel-pair-picker"><label>选择英雄<select aria-label="选择搭配英雄" value={heroId} onChange={e=>setHeroId(e.target.value)}>{[...data.heroes].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')).map(h=><option key={h.id} value={h.id}>{h.name} · {h.title}</option>)}</select></label>{hero&&<div className="intel-chosen"><HeroPortrait hero={hero}/><div><b>{hero.name}</b><span>英雄基准 {pc(hero.win_rate)} · {n(hero.games)} 场</span></div></div>}{Object.keys(data.provisional_augments).length>0&&<label className="intel-check"><input type="checkbox" checked={showPbe} onChange={e=>setShowPbe(e.target.checked)}/>显示测试服参考（单独标注）</label>}</div>}
    {tab==='pairs'&&<nav className="hex-rarity-filter" aria-label="AramHex海克斯稀有度">{[["all","全部"],["silver","白银"],["gold","黄金"],["prismatic","棱彩"]].map(([key,label])=><button key={key} aria-pressed={pairRarity===key} onClick={()=>setPairRarity(key)}>{label}</button>)}</nav>}
    <div className="intel-controls"><label className="intel-search">{tab==='heroes'?'搜索英雄':'搜索海克斯'}<input aria-label="搜索情报" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder={tab==='heroes'?'英雄名字、称号或编号':'海克斯名字或编号'}/></label><label>最少样本<select aria-label="最少样本" value={minimum} onChange={e=>setMinimum(Number(e.target.value))}><option value={0}>不限 · 包含极小样本</option><option value={250}>250 场</option><option value={1000}>1,000 场</option><option value={5000}>5,000 场</option></select></label><label>排序<select aria-label="情报排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="confidence">稳健排序 · 置信下界</option><option value="win_rate">实际胜率</option><option value="games">样本场数</option></select></label></div>
    <div className="intel-list-head"><h2>{tab==='heroes'?'英雄版本表现':tab==='augments'?'海克斯整体表现':`${hero?.name||'英雄'} · 海克斯搭配`}</h2><span>{count} 项结果</span></div>
    <p className="intel-caution">{tab==='heroes'?'点英雄查看搭配。默认按胜率的 Wilson 95% 置信下界排序，让极小样本的高胜率少占前排。':tab==='augments'?'以每位玩家的局末持有为一条记录，跨英雄汇总胜场 ÷ 持有人次；不是被提供三选一时的选取胜率，未混入测试服。':'胜率为持有该海克斯的样本胜场 ÷ 持有场数；与英雄基准的差值仅供观察，不代表拿了它就能提高这么多胜率。'}</p>
    {tab==='pairs'&&pairError?<p className="intel-message" role="alert">{pairError}<button onClick={()=>setRetry(r=>r+1)}>重新读取</button></p>:tab==='pairs'&&!detail?<p className="intel-message" role="status">正在读取这个英雄的搭配…</p>:tab==='pairs'?<><AugmentCards rows={pairRows.slice(offset,offset+20)} dictionary={data.augment_dictionary} heroRate={hero?.win_rate||0}/>{count===0&&<p className="intel-message">没有符合条件的样本。可以换个关键词或降低场数门槛。</p>}</>:<div className="intel-list">
     <div className="intel-row intel-columns"><span>{tab==='heroes'?'英雄':'海克斯'}</span><span>实际胜率</span><span>样本 / 胜场</span><span>{tab==='heroes'?'详情':tab==='augments'?'覆盖英雄':'较英雄基准'}</span></div>
     {tab==='heroes'?heroRows.slice(offset,offset+20).map((h,i)=><button className="intel-row intel-hero-row" key={h.id} onClick={()=>chooseHero(h.id)}><span className="intel-identity"><small className="intel-rank">{offset+i+1}</small><HeroPortrait hero={h}/><span><b>{h.name}</b><small>{h.title}</small></span></span><strong data-label="胜率">{pc(h.win_rate)}</strong><span data-label="样本 / 胜场">{n(h.games)}<small>{n(h.wins)} 胜</small></span><span className="intel-open">看搭配 →</span></button>):augmentRows.slice(offset,offset+20).map((a,i)=><div className="intel-row" key={a.id}><span className="intel-identity"><small className="intel-rank">{offset+i+1}</small><i className={'intel-rarity '+a.rarity}>⬡</i><span><b>{a.name}</b><small>{rarity(a.rarity)} · #{a.id}</small></span></span><strong data-label="胜率">{pc(a.win_rate)}</strong><span data-label="样本 / 胜场">{n(a.games)}<small>{n(a.wins)} 胜</small></span><span data-label="覆盖英雄">{a.heroes} 位</span></div>)}
     {count===0&&<p className="intel-message">没有符合条件的样本。可以换个关键词或降低场数门槛。</p>}
    </div>}
    <div className="intel-pagination"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>上一页</button><span>{Math.min(page,pages)} / {pages}</span><button disabled={page>=pages} onClick={()=>setPage(p=>p+1)}>下一页</button></div>
    {Object.keys(data.provisional_augments).length>0&&<details className="intel-method"><summary>{Object.keys(data.provisional_augments).length} 个仅有测试服参考的新海克斯</summary><p>这些海克斯暂未在本期正式服有效持有记录中出现，不表示已停用。整体海克斯榜排除了它们；在英雄搭配中可以主动开启查看。</p><p>{Object.keys(data.provisional_augments).map(id=>data.augment_dictionary[id]?.name||id).join('、')}。</p></details>}
   </>
   <details className="intel-method"><summary>胜率到底怎么算？</summary><p>英雄胜率 = 使用该英雄的胜场 ÷ 该英雄参赛场数。海克斯胜率 = 局末持有该海克斯的胜场 ÷ 持有人次；同一玩家六个槽位去重。英雄搭配胜率只在该英雄的样本里计算。</p><p>每场比赛有10位玩家，所以“持有人次”可以大于对局数。跨英雄汇总采用胜场与人次分别求和后相除，不把各英雄的百分数简单平均。</p><p>只计正常结束、至少4分钟、10人齐全且5胜5负的标准海克斯对局。朋友个人胜率与这里的公共样本分别展示；不同版本、活动规则和测试服不混算。</p><p>稳健排序使用 Wilson 95% 置信下界，不是 Hexdata 的 HexScore。样本越少，不确定性越大；持有胜率与英雄基准差值都不证明因果。</p></details>
   <footer className="intel-footer"><p>数据来源：<a href={data.source_url} target="_blank" rel="noreferrer">AramHex / czgreat/aramhex-data</a> · {data.license}（署名、非商业）<br/>本页对公开汇总重新计算比例并分离测试服数据；没有修改个人战绩。</p><a href="https://hexdata.com.cn/" target="_blank" rel="noreferrer">参考网站：Hexdata ↗</a></footer>
  </>}
 </main>;
}
