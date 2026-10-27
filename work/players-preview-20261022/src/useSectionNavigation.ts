import {useEffect,useState} from 'react';
import {activeSectionAt} from '../lib/section-navigation';
export const lobbySections=[['players','玩家'],['together','并肩'],['recaps','回顾'],['achievements','成就'],['moments','高光'],['lobby-recent','最近']];
export default function useSectionNavigation(){
 const[visible,setVisible]=useState(false),[active,setActive]=useState('players');
 useEffect(()=>{
  let frame=0,pending:{id:string;until:number;y:number}|null=null;
  const rows=()=>lobbySections.flatMap(([id])=>{const el=document.getElementById(id);return el?[{id,top:el.getBoundingClientRect().top}]:[];});
  const update=()=>{setVisible(window.scrollY>200);if(pending){if(Math.abs(window.scrollY-pending.y)<3||Date.now()>pending.until)pending=null;else{setActive(pending.id);return;}}setActive(activeSectionAt(rows()));};
  const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(update);};
  const move=(id:string)=>{const el=document.getElementById(id);if(!el)return;const y=Math.min(Math.max(0,window.scrollY+el.getBoundingClientRect().top-32),Math.max(0,document.documentElement.scrollHeight-window.innerHeight));pending={id,y,until:Date.now()+1800};setActive(id);window.scrollTo({top:y,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});};
  const click=(event:MouseEvent)=>{if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;const a=(event.target as Element)?.closest('a[href^="#"]');const id=a?.getAttribute('href')?.slice(1);if(!id||!lobbySections.some(([key])=>key===id))return;event.preventDefault();if(location.hash!=='#'+id)history.pushState(null,'','#'+id);move(id);};
  const hash=()=>{const id=location.hash.slice(1);if(lobbySections.some(([key])=>key===id))move(id);else schedule();};
  const interrupt=()=>{pending=null;schedule();};const key=(event:KeyboardEvent)=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key))interrupt();};
  update();document.addEventListener('click',click);window.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule);window.addEventListener('hashchange',hash);window.addEventListener('popstate',schedule);window.addEventListener('wheel',interrupt,{passive:true});window.addEventListener('touchstart',interrupt,{passive:true});window.addEventListener('keydown',key);
  return()=>{cancelAnimationFrame(frame);document.removeEventListener('click',click);window.removeEventListener('scroll',schedule);window.removeEventListener('resize',schedule);window.removeEventListener('hashchange',hash);window.removeEventListener('popstate',schedule);window.removeEventListener('wheel',interrupt);window.removeEventListener('touchstart',interrupt);window.removeEventListener('keydown',key);};
 },[]);
 return {visible,active};
}
