import {useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import type {Rank,RankQueue} from './App';

// 只展示「当前赛季段位」：来自官方排位接口，是本季实时的段位与胜点。
// 早期那套「历史至少达到过某段位」的下界统计口径不可靠，已从界面撤掉；
// 保留这段提示的真正目的是说清一件事：海斗分不参考段位，也不代表真实实力。
const QUEUE_LABEL:{[key:string]:string}={solo:'单双排',flex:'灵活组排'};
const QUEUES=['solo','flex'] as const;
const MISSING='本季暂无段位记录';
const MISSING_BOTH='本季两个队列都没有段位读数 · 没查到不等于没打过排位';
const GAP=10;

const text=(value?:string|null)=>typeof value==='string'?value.trim():'';

/** 当前赛季段位：只认官方排位接口返回的 current，没有就是没有，不拿别的字段凑。 */
export function queueParts(queue?:RankQueue|null){
  const tier=text(queue?.current);
  if(!tier) return null;
  const lp=typeof queue?.lp==='number'?`${queue.lp} 胜点`:'';
  return {tier,lp};
}

export function queueLine(queue?:RankQueue|null){
  const parts=queueParts(queue);
  if(!parts) return null;
  return parts.lp?`${parts.tier} · ${parts.lp}`:parts.tier;
}

/** 档案页常驻一行：优先单双排，本季没打单双排就退到灵活组排，两个都没有返回 null。 */
export function rankSummary(rank?:Rank|null){
  const solo=queueLine(rank?.solo);
  if(solo) return solo;
  const flex=queueLine(rank?.flex);
  return flex?`灵活组排 ${flex}`:null;
}

export function rankPlainText(rank?:Rank|null){
  // 两个队列都没读数时不再逐队列重复两遍「暂无」，合成一句，避免看起来像缺数据。
  const anyQueue=QUEUES.some(key=>queueParts(rank?.[key]));
  const rows=anyQueue?QUEUES.map(key=>`${QUEUE_LABEL[key]}：${queueLine(rank?.[key])??MISSING}`):[MISSING_BOTH];
  return ['海斗分只统计本站收录的海克斯大乱斗对局，不参考排位段位，也不代表真实实力。',
    '当前赛季排位：',...rows].join('\n');
}

type Anchor={left:number;top:number;bottom:number};

export default function RankHint({rank,className,children}:{rank?:Rank|null;className?:string;children:ReactNode}){
  const trigger=useRef<HTMLDivElement>(null);
  const tip=useRef<HTMLDivElement>(null);
  const[anchor,setAnchor]=useState<Anchor|null>(null);
  const[height,setHeight]=useState(170);
  const close=()=>setAnchor(null);
  // 先按估算高度摆位，挂载后按真实高度纠偏，避免小屏把最后一句话裁掉。
  useLayoutEffect(()=>{
    if(anchor&&tip.current){const measured=tip.current.offsetHeight;if(measured&&Math.abs(measured-height)>1)setHeight(measured);}
  },[anchor,height]);
  useEffect(()=>{
    if(!anchor) return;
    // 滚动或点别处就收起，避免悬浮框跟卡片错位后一直挂着。
    const dismiss=(event:Event)=>{if(trigger.current&&!trigger.current.contains(event.target as Node))close();};
    window.addEventListener('scroll',close,{passive:true});
    window.addEventListener('resize',close);
    document.addEventListener('pointerdown',dismiss);
    return()=>{window.removeEventListener('scroll',close);window.removeEventListener('resize',close);document.removeEventListener('pointerdown',dismiss);};
  },[anchor]);
  const open=()=>{
    // 触屏没有 hover：点一下会直接进档案，有常驻段位行；这里不弹悬浮框。
    if(typeof window==='undefined'||!window.matchMedia('(hover: hover)').matches) return;
    const host=(trigger.current?.closest('.player-tile') as HTMLElement|null)||trigger.current;
    const rect=host?.getBoundingClientRect();
    if(!rect) return;
    setAnchor({left:rect.left,top:rect.top,bottom:rect.bottom});
  };
  const style=anchor?(()=>{
    const width=Math.min(292,window.innerWidth-24);
    const left=Math.max(12,Math.min(anchor.left,window.innerWidth-width-12));
    const below=window.innerHeight-anchor.bottom-GAP,above=anchor.top-GAP;
    // 优先放到卡片下方；下方放不下且上方更宽裕时才上移，尽量不盖住正在看的卡片。
    return below>=height||above<height?{left,top:anchor.bottom+GAP}:{left,bottom:window.innerHeight-anchor.top+GAP};
  })():null;
  const checked=text(rank?.checked_at);
  // 不要挂 title：桌面端会同时弹出原生提示条，和自定义悬浮框叠在一起。
  // 读屏和触屏改用 aria-label，文案与悬浮框一致。
  return <div ref={trigger} className={className} role="group" aria-label={rankPlainText(rank)} onMouseEnter={open} onMouseLeave={close}>
    {children}
    {anchor&&style&&createPortal(<div ref={tip} className="rank-tip" role="tooltip" style={style}>
      <p className="rank-tip-title">海斗分 ≠ 排位实力</p>
      <p className="rank-tip-lede">海斗分只统计本站收录的海克斯大乱斗对局，<b>与排位段位无关</b>，也不代表真实实力。</p>
      <ul className="rank-tip-rows">{QUEUES.some(key=>queueParts(rank?.[key]))?QUEUES.map(key=>{
        const parts=queueParts(rank?.[key]);
        return <li key={key}><span>{QUEUE_LABEL[key]}</span>{parts?<strong>{parts.tier}{parts.lp&&<small>{parts.lp}</small>}</strong>:<em>{MISSING}</em>}</li>;
      }):<li><span>当前赛季</span><em>{MISSING_BOTH}</em></li>}</ul>
      <p className="rank-tip-note">{checked?`段位为当前赛季排位接口读数（${checked}），赛季结算或补分会变；只作背景参考，不进海斗分。`:'段位为当前赛季排位接口读数，只作背景参考，不进海斗分。'}</p>
    </div>,document.body)}
  </div>;
}
