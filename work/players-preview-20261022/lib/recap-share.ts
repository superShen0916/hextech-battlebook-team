import {summarizeGames,recapCast,recapCastGroup,type RecapGame} from './recaps';

export type RecapSelection =
 | {mode:'night';anchor:string;night:string;fridays:boolean}
 | {mode:'team';selected:string[];period:'all'|'30'|'90'};

export function readRecapShare(search:string,knownIds:string[]):{selection:RecapSelection|null;error:string}{
 const p=new URLSearchParams(search),mode=p.get('recap');
 if(!mode)return {selection:null,error:''};
 const known=new Set(knownIds),invalid=()=>({selection:null,error:'这份回顾链接的玩家或筛选条件已不可用，请重新选择。'});
 if(mode==='night'){
  const anchor=p.get('recap_player')||'',night=p.get('recap_date')||'';
  const date=/^\d{4}-\d{2}-\d{2}$/.test(night)?new Date(night+'T00:00:00Z'):null;
  if(!known.has(anchor)||!date||!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==night)return invalid();
  return {selection:{mode,anchor,night,fridays:p.get('recap_fridays')==='1'},error:''};
 }
 if(mode==='team'){
  const selected=(p.get('recap_players')||'').split(','),period=p.get('recap_period')||'all';
  if(selected.length<2||selected.length>5||new Set(selected).size!==selected.length||selected.some(id=>!known.has(id))||!['all','30','90'].includes(period))return invalid();
  return {selection:{mode,selected,period:period as 'all'|'30'|'90'},error:''};
 }
 return invalid();
}

export function recapShareUrl(base:string,selection:RecapSelection){
 const url=new URL(base),code=url.searchParams.get('sharecode');
 url.pathname='/';url.search='';url.hash='recaps';
 if(code)url.searchParams.set('sharecode',code);
 else if(url.hostname==='hextech-battlebook.app.workbuddy.host')url.searchParams.set('sharecode','7ZFAIH5YHV');
 url.searchParams.set('recap',selection.mode);
 if(selection.mode==='night'){
  url.searchParams.set('recap_player',selection.anchor);url.searchParams.set('recap_date',selection.night);
  url.searchParams.set('recap_fridays',selection.fridays?'1':'0');
 }else{
  url.searchParams.set('recap_players',selection.selected.join(','));url.searchParams.set('recap_period',selection.period);
 }
 return url.toString();
}

export function recapShareModel(games:RecapGame[],selection:RecapSelection,names:Record<string,string>){
 const ids=selection.mode==='night'?[...new Set(games.flatMap(g=>g.members.map(p=>p.profile_id)))]:selection.selected;
 const summary=summarizeGames(games,ids);
 const headline=selection.mode==='night'?selection.night+' · 当晚战报':'我们的共同回顾';
 const subtitle=selection.mode==='night'?(names[selection.anchor]||'玩家')+'的视角':selection.selected.map(id=>names[id]||'玩家').join(' × ');
 const scope=selection.mode==='night'?'北京时间18:00—次日06:00':selection.period==='all'?'全部已收录同队对局':`最近${selection.period}天 · 全部同队`;
 const cast=recapCast(games,recapCastGroup(games,selection.mode==='night'?[selection.anchor]:selection.selected));
 return {headline,subtitle,scope,summary,cast,members:[...summary.people].sort((a,b)=>b.games-a.games),
  results:[...games].sort((a,b)=>a.started_ms-b.started_ms).slice(-50),
  recent:[...games].sort((a,b)=>b.started_ms-a.started_ms).slice(0,3)};
}

export function renderRecapShare(games:RecapGame[],selection:RecapSelection,names:Record<string,string>){
 const model=recapShareModel(games,selection,names),members=model.members.slice(0,8),recent=model.recent;
 const castHeight=180+model.cast.roles.length*120;
 const canvas=document.createElement('canvas');canvas.width=1080;canvas.height=1100+members.length*100+recent.length*100+castHeight;
 const c=canvas.getContext('2d');if(!c)throw Error('当前浏览器暂不支持生成分享图');
 const W=canvas.width,H=canvas.height,gold='#ecd098',white='#edf3f7',muted='#a4b8c8';
 const bg=c.createLinearGradient(0,0,W,H);bg.addColorStop(0,'#0b1925');bg.addColorStop(.5,'#1b3547');bg.addColorStop(1,'#0a1723');c.fillStyle=bg;c.fillRect(0,0,W,H);
 const text=(s:string,x:number,y:number,size=24,color=white,maxWidth=950)=>{
  c.font=`500 ${size}px "Microsoft YaHei", "PingFang SC", sans-serif`;c.fillStyle=color;
  while(c.measureText(s).width>maxWidth&&s.length>1)s=s.slice(0,-2)+'…';c.fillText(s,x,y);
 };
 const box=(x:number,y:number,w:number,h:number)=>{c.fillStyle='#091b2b99';c.strokeStyle='#486170';c.lineWidth=1;c.beginPath();c.roundRect(x,y,w,h,14);c.fill();c.stroke();};
 c.strokeStyle='#c7ac6944';c.lineWidth=2;c.strokeRect(32,32,W-64,H-64);
 text('⬡ 海克斯战报馆  /  一起打过的故事',64,85,26,gold);
 text(model.headline,64,164,48,gold);text(model.subtitle,64,220,28,white);text(model.scope,64,257,20,muted);
 box(64,288,952,155);
 const stats=[['一起打过',`${model.summary.games} 场`],['共同胜负',`${model.summary.wins} 胜 ${model.summary.games-model.summary.wins} 负`],['胜率',model.summary.games?(100*model.summary.wins/model.summary.games).toFixed(1)+'%':'—'],['最长连胜',`${model.summary.longest} 场`]];
 stats.forEach(([label,value],i)=>{const x=88+i*238;text(label,x,331,20,muted,215);text(value,x,391,38,i===2?gold:white,215);});
 text('每一格，都是一起扛过的一把',64,497,26,gold);
 model.results.forEach((g,i)=>{const x=64+(i%25)*38,y=523+Math.floor(i/25)*39;c.fillStyle=g.win?'#3a8075':'#895269';c.fillRect(x,y,30,30);});
 text(`${model.results.length===50?'最近50场':'所选范围'} · 从旧到新   绿＝胜 / 红＝负`,64,626,20,muted);
 text('今晚的车队鉴定 / 同队 '+model.cast.games+' 场',64,685,28,gold);
 model.cast.roles.forEach((p,i)=>{const y=714+i*120;box(64,y,952,106);text(p.title+' / '+(names[p.id]||'玩家'),84,y+34,26,gold,890);text(p.line,84,y+65,22,white,890);text(`${p.average.toFixed(1)} 场均表现分 · ${p.wins}胜${p.games-p.wins}负 · ${p.mvp} MVP / ${p.ace} ACE`,84,y+92,19,muted,890);});
 text(model.cast.roles.length?'按 v0.5 场均表现玩梗，不判输赢责任。':model.cast.note,64,750+model.cast.roles.length*120,20,muted,950);
 text('这份战报里，有这些熟悉的名字',64,685+castHeight,28,gold);
 members.forEach((p,i)=>{const y=710+castHeight+i*100;box(64,y,952,86);text(names[p.id]||'玩家',84,y+34,26,white,410);
  text(`${p.games} 场 · ${p.kills??'—'} / ${p.deaths??'—'} / ${p.assists??'—'}`,84,y+66,20,muted,530);
  text(`${p.mvp} MVP  /  ${p.ace} ACE`,650,y+49,24,gold,340);
 });
 const recentY=770+castHeight+members.length*100;text('最近一起打过的几场',64,recentY,28,gold);
 const when=(ts:number)=>new Date(ts).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
 recent.forEach((g,i)=>{const y=recentY+28+i*100;box(64,y,952,87);text(g.win?'胜利':'一起扛',84,y+37,25,g.win?'#a0dfc8':'#e2b6c7',160);
  text(`${when(g.started_ms)} · ${Math.round(g.duration/60)} 分钟`,260,y+36,23,white,730);
  text(g.members.map(p=>names[p.profile_id]||'玩家').join(' / '),84,y+69,19,muted,910);
 });
 text('一起打过的每一场，都值得记住。',64,H-157,28,gold);
 text('仅依据已收录有效同队战绩，不据此断言真实预组队。',64,H-112,20,muted);
 text(`MVP / ACE 为工具自评 · ${model.members.length>8?'成员仅展示前8位 · ':''}分享链接可打开完整回顾`,64,H-77,19,muted);
 return {image:canvas.toDataURL('image/png'),width:W,height:H,model};
}
