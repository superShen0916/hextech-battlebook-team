import {useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import type {Rank,RankQueue} from './App';

// 排位段位只作背景参考：它来自官方排位接口与排位攀登挑战 210004，
// 只能证明"至少达到过"，既不覆盖账号全部年代，也不参与海斗分。
const QUEUE_LABEL:{[key:string]:string}={solo:'单双排',flex:'灵活组排'};
const MISSING='暂无可靠段位记录 · 没查到不等于没打过排位';
const GAP=10;

const text=(value?:string|null)=>typeof value==='string'?value.trim():'';

export function queueParts(queue?:RankQueue|null){
  if(!queue) return null;
  const atLeast=text(queue.at_least),current=text(queue.current);
  const lp=typeof queue.lp==='number'?`${queue.lp} 胜点`:'';
  if(!atLeast&&!current) return null;
  const bound=atLeast?`历史至少 ${atLeast}`:'';
  // 下界与当前段位相同时不重复段位名，只补胜点。
  const now=current?(atLeast===current?(lp?`当前 ${lp}`:''):(lp?`当前 ${current} · ${lp}`:`当前 ${current}`)):'';
  return {bound,now};
}

export function queueLine(queue?:RankQueue|null){
  const parts=queueParts(queue);
  if(!parts) return null;
  return [parts.bound,parts.now].filter(Boolean).join(' · ');
}

/** 档案页常驻一行：句子里已经带了队列名，所以去掉重复的"历史至少"。 */
export function rankSummary(rank?:Rank|null){
  const combined=queueLine(rank?.solo);
  return combined?combined.replace('历史至少 ','至少 '):null;
}

export function rankPlainText(rank?:Rank|null){
  const rows:string[]=[];
  for(const key of ['solo','flex'] as const){
    if(key==='flex'&&!rank?.flex) continue;
    rows.push(`${QUEUE_LABEL[key]}：${queueLine(rank?.[key])??MISSING}`);
  }
  return ['海斗分只统计本站收录的海克斯大乱斗对局，不参考排位段位，也不代表真实实力。',
    ...rows,'段位取自官方排位接口与排位挑战记录，只证明「至少达到过」，不是完整生涯最高。'].join('\n');
}

type Anchor={left:number;top:number;bottom:number};

export default function RankHint({rank,className,children}:{rank?:Rank|null;className?:string;children:ReactNode}){
  const trigger=useRef<HTMLDivElement>(null);
  const tip=useRef<HTMLDivElement>(null);
  const[anchor,setAnchor]=useState<Anchor|null>(null);
  const[height,setHeight]=useState(190);
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
  // 不要挂 title：桌面端会同时弹出原生提示条，和自定义悬浮框叠在一起。
  // 读屏和触屏改用 aria-label，文案与悬浮框一致。
  return <div ref={trigger} className={className} role="group" aria-label={rankPlainText(rank)} onMouseEnter={open} onMouseLeave={close}>
    {children}
    {anchor&&style&&createPortal(<div ref={tip} className="rank-tip" role="tooltip" style={style}>
      <p className="rank-tip-title">海斗分 ≠ 排位实力</p>
      <p className="rank-tip-lede">海斗分只统计本站收录的海克斯大乱斗对局，<b>不参考排位段位</b>，也不代表真实实力。</p>
      <ul className="rank-tip-rows">{(['solo','flex'] as const).map(key=>{
        if(key==='flex'&&!rank?.flex) return null;
        const parts=queueParts(rank?.[key]);
        return <li key={key}><span>{QUEUE_LABEL[key]}</span>{parts?<strong>{parts.bound||parts.now}{parts.bound&&parts.now&&<small>{parts.now}</small>}</strong>:<em>{MISSING}</em>}</li>;
      })}</ul>
      <p className="rank-tip-note">段位取自官方排位接口与排位挑战记录，只证明「至少达到过」，不是完整生涯最高。</p>
    </div>,document.body)}
  </div>;
}
