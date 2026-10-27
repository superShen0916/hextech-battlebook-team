import {useEffect,useRef,type ComponentPropsWithoutRef} from 'react';

/** Paint once per animation frame; touch and reduced-motion readers keep a static card. */
export default function MotionCard({className='',children,...props}:ComponentPropsWithoutRef<'article'>){
 const frame=useRef(0);
 useEffect(()=>()=>cancelAnimationFrame(frame.current),[]);
 const reset=(el:HTMLElement)=>{cancelAnimationFrame(frame.current);delete el.dataset.motion;
  for(const key of ['--tilt-x','--tilt-y','--pointer-x','--pointer-y'])el.style.removeProperty(key);};
 return <article {...props} className={'motion-card '+className} onPointerMove={event=>{
  if(event.pointerType!=='mouse'||!matchMedia('(hover: hover) and (pointer: fine)').matches||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const el=event.currentTarget,rect=el.getBoundingClientRect();
  const x=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height));
  cancelAnimationFrame(frame.current);frame.current=requestAnimationFrame(()=>{
   el.style.setProperty('--tilt-x',`${(0.5-y)*9}deg`);el.style.setProperty('--tilt-y',`${(x-0.5)*11}deg`);
   el.style.setProperty('--pointer-x',`${x*100}%`);el.style.setProperty('--pointer-y',`${y*100}%`);el.dataset.motion='active';
  });
 }} onPointerLeave={event=>reset(event.currentTarget)} onPointerCancel={event=>reset(event.currentTarget)}>{children}</article>;
}
