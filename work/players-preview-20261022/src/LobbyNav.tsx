import {useState} from 'react';
import {lobbySections} from './useSectionNavigation';
export default function LobbyNav({active,visible}:{active:string;visible:boolean}){
 const[open,setOpen]=useState(false);
 return <aside className={'lobby-side-dock'+(visible?' shown':'')+(open?' expanded':'')} aria-hidden={!visible} inert={!visible}>
  <button className="side-dock-toggle" aria-label={open?'收起大厅分区导航':'展开大厅分区导航'} aria-expanded={open} aria-controls="lobby-side-links" onClick={()=>setOpen(!open)}><span>{lobbySections.find(([id])=>id===active)?.[1]||'玩家'}</span><b aria-hidden="true">{open?'›':'‹'}</b></button>
  <nav className="lobby-floating-nav" id="lobby-side-links" aria-label="大厅浮动导航">{lobbySections.map(([id,name])=><a key={id} href={'#'+id} className={active===id?'active':''} aria-current={active===id?'location':undefined} onClick={()=>setOpen(false)}>{name}</a>)}<button aria-label="大厅回到顶部" onClick={()=>{setOpen(false);window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}}>顶部 ↑</button></nav>
 </aside>;
}
