import {useEffect,useRef,useState} from 'react';
// 组件内有同名状态 track（曲目 id），打点函数改名为 trackEvent 避免遮蔽
import {track as trackEvent} from '../lib/analytics';

const skins=[['hextech','海克斯鎏金','#d8b778'],['freljord','极地极光','#7de1e0'],['void','虚空星云','#c3a4ff'],['zaun','祖安霓虹','#a4ed7d']] as const;
const tracks=[['sessions-vi','Sessions: Vi · 松弛 Lo-fi'],['sessions-diana','Sessions: Diana · 月下氛围']] as const;
type Widget={bind:(event:string,fn:()=>void)=>void;setVolume:(n:number)=>void;play:()=>void;pause:()=>void;getCurrentSound:(fn:(s:{title?:string;user?:{username?:string}})=>void)=>void};
type SoundCloud={Widget:((frame:HTMLIFrameElement)=>Widget)&{Events:{READY:string;PLAY:string;PAUSE:string;ERROR:string;FINISH:string}}};
let sdk:Promise<SoundCloud>|undefined;
function soundCloud(){
 if(!sdk)sdk=new Promise<SoundCloud>((resolve,reject)=>{const ready=()=>(window as Window&{SC?:SoundCloud}).SC;
  if(ready()){resolve(ready()!);return;}const s=document.createElement('script');s.src='https://w.soundcloud.com/player/api.js';s.async=true;
  const timer=setTimeout(()=>{s.remove();reject(Error('timeout'));},15000);
  s.onload=()=>{clearTimeout(timer);ready()?resolve(ready()!):reject(Error('sdk'));};s.onerror=()=>{clearTimeout(timer);s.remove();reject(Error('network'));};document.head.append(s);
 }).catch(e=>{sdk=undefined;throw e;});return sdk;
}
export default function Atmosphere(){
 const[open,setOpen]=useState(false),[skin,setSkin]=useState(()=>{try{const s=localStorage.getItem('battlebook-skin');return skins.some(([id])=>id===s)?s!:'hextech';}catch{return 'hextech';}});
 const[volume,setVolume]=useState(()=>{try{const v=Number(localStorage.getItem('battlebook-volume')??18);return Number.isFinite(v)?Math.min(35,Math.max(0,v)):18;}catch{return 18;}});
 const[enabled,setEnabled]=useState(false),[track,setTrack]=useState('sessions-vi'),[attempt,setAttempt]=useState(0),[playing,setPlaying]=useState(false),[status,setStatus]=useState('默认静音，点一下才开始。'),[credit,setCredit]=useState('');
 const frame=useRef<HTMLIFrameElement>(null),widget=useRef<Widget|null>(null),volumeRef=useRef(volume);volumeRef.current=volume;
 useEffect(()=>{document.documentElement.dataset.skin=skin;try{localStorage.setItem('battlebook-skin',skin);}catch{}},[skin]);
 useEffect(()=>{widget.current?.setVolume(volume);try{localStorage.setItem('battlebook-volume',String(volume));}catch{}},[volume]);
 useEffect(()=>{if(!enabled)return;let alive=true;setStatus('正在连接 Riot Sessions…');setPlaying(false);setCredit('');
  const timer=setTimeout(()=>{if(alive)setStatus('音乐服务连接较慢，可重试或打开官方专辑。');},18000);
  soundCloud().then(sc=>{if(!alive||!frame.current)return;const w=sc.Widget(frame.current);widget.current=w;
   w.bind(sc.Widget.Events.READY,()=>{if(!alive)return;clearTimeout(timer);w.setVolume(volumeRef.current);w.play();setStatus('已连接；若无声音，点播放器里的播放键。');});
   w.bind(sc.Widget.Events.PLAY,()=>{if(alive){setPlaying(true);setStatus('轻轻听，慢慢翻战报。');w.getCurrentSound(s=>{if(alive)setCredit([s.title,s.user?.username].filter(Boolean).join(' / '));});}});
   w.bind(sc.Widget.Events.PAUSE,()=>{if(alive)setPlaying(false);});
   w.bind(sc.Widget.Events.ERROR,()=>{if(alive){setPlaying(false);setStatus('音乐暂时无法连接，可重试或打开官方专辑。');}});
  }).catch(()=>{if(alive)setStatus('音乐暂时无法连接，可重试或打开官方专辑。');});
  const hide=()=>{if(document.hidden){widget.current?.pause();setPlaying(false);setStatus('离开页面已暂停，回来后点播放继续。');}};document.addEventListener('visibilitychange',hide);
  // Removing/replacing the iframe stops playback. The widget cannot post to a detached frame.
  return()=>{alive=false;clearTimeout(timer);widget.current=null;document.removeEventListener('visibilitychange',hide);};
 },[enabled,track,attempt]);
 return <aside className="atmosphere"><button className="atmosphere-toggle" aria-expanded={open} aria-controls="atmosphere-panel" onClick={()=>setOpen(!open)}>{playing?'♫':'✧'} 皮肤 / BGM {open?'×':''}</button>
  <section id="atmosphere-panel" className="atmosphere-panel" hidden={!open} aria-label="皮肤与背景音乐"><header><h2>给今晚换个氛围</h2><button className="ghost" aria-label="关闭氛围设置" onClick={()=>setOpen(false)}>×</button></header>
   <div className="skin-options" role="group" aria-label="全站皮肤">{skins.map(([id,name,color])=><button key={id} aria-pressed={skin===id} onClick={()=>{trackEvent('skin_pick',{detail:JSON.stringify({skin:id})});setSkin(id);}}><i style={{background:color}}/>{name}</button>)}</div>
   <p>皮肤与音量只记在你的浏览器。音乐每次打开网站均默认关闭。</p>
   <label>背景音乐<select aria-label="选择背景音乐" value={track} onChange={e=>{trackEvent('bgm_toggle',{detail:JSON.stringify({action:'switch',track:e.target.value})});setTrack(e.target.value)}}>{tracks.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
   <div className="music-actions"><button className="ghost" onClick={()=>{const action=!enabled?'start':playing?'pause':'resume';trackEvent('bgm_toggle',{detail:JSON.stringify({action})});if(!enabled){setEnabled(true);return;}if(playing)widget.current?.pause();else widget.current?.play();}}>{!enabled?'开启音乐':playing?'暂停音乐':'继续播放'}</button><button className="ghost" disabled={!enabled} onClick={()=>{trackEvent('bgm_toggle',{detail:JSON.stringify({action:'stop'})});setEnabled(false);setPlaying(false);setStatus('音乐已关闭。');setCredit('');}}>关闭音乐</button>{enabled&&<button className="ghost" onClick={()=>{trackEvent('bgm_toggle',{detail:JSON.stringify({action:'retry'})});setAttempt(a=>a+1);}}>重试连接</button>}</div>
   <label className="music-volume">音量 {volume}%<input aria-label="背景音乐音量" type="range" min="0" max="35" value={volume} onChange={e=>setVolume(Number(e.target.value))}/></label>
   <p role="status">{status}</p>
   {enabled&&<iframe ref={frame} key={track+attempt} title="Riot Sessions 背景音乐播放器" width="100%" height="140" allow="autoplay" src={'https://w.soundcloud.com/player/?url='+encodeURIComponent('https://soundcloud.com/leagueoflegends/sets/'+track)+'&auto_play=false&hide_related=true&show_comments=false&show_user=true&show_reposts=false&visual=false'}/>}
   {credit&&<p>{credit}</p>}<a href={'https://soundcloud.com/leagueoflegends/sets/'+track} target="_blank" rel="noreferrer">官方专辑 ↗</a><small> · Courtesy of Riot Games · <a href="https://www.leagueoflegends.com/en-us/event/sessions/" target="_blank" rel="noreferrer">Sessions / 音乐来源</a></small>
  </section>
 </aside>;
}
