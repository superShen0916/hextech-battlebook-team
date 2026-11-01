import type {IntelPair} from '../lib/version-intel';

type Entry={name:string;rarity:string;icon_url?:string|null};
const rarityName=(value:string)=>({silver:'白银',gold:'黄金',prismatic:'棱彩'}[value]||value);
export default function AugmentCards({rows,dictionary,heroRate}:{rows:IntelPair[];dictionary:Record<string,Entry>;heroRate:number}){
 return <div className="hex-card-grid" aria-label="英雄海克斯胜率">{rows.map(row=>{
  const hex=dictionary[row.id],delta=(row.win_rate-heroRate)*100;
  return <article className={'hex-stat-card '+(hex?.rarity||'')+(row.source==='pbe'?' intel-pbe':'')} key={row.id} data-augment-id={row.id}>
   <header>{hex?.icon_url?<img src={hex.icon_url} alt="" loading="lazy"/>:<span className="hex-card-symbol" aria-hidden="true">⬡</span>}<div><span className="hex-card-rarity">{rarityName(hex?.rarity||'')} · #{row.id}</span><h3>{hex?.name||row.id}</h3></div></header>
   <div className="hex-card-stats"><div><span>持有胜率</span><strong>{(row.win_rate*100).toFixed(1)}%</strong></div><div><span>较英雄基准</span><b className={delta>=0?'intel-positive':'intel-negative'}>{row.source==='pbe'?'不跨服比较':`${delta>=0?'+':''}${delta.toFixed(1)} 个百分点`}</b></div></div>
   <footer><span>{row.games.toLocaleString('zh-CN')} 场 · {row.wins.toLocaleString('zh-CN')} 胜</span><span>{row.source==='pbe'?'测试服参考':row.low_sample?'来源标记低样本':'正式服样本'}</span></footer>
  </article>;
 })}</div>;
}
