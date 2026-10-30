import {summarizeGames,recapCast,castPool,type RecapGame} from './recaps';

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
 const cast=recapCast(games,castPool(games,selection.mode==='night'?[selection.anchor]:selection.selected));
 return {headline,subtitle,scope,summary,cast,members:[...summary.people].sort((a,b)=>b.games-a.games),
  results:[...games].sort((a,b)=>a.started_ms-b.started_ms).slice(-50),
  recent:[...games].sort((a,b)=>b.started_ms-a.started_ms).slice(0,3)};
}

const GOLD='#ecd49c',GOLD_DIM='#c7ac69',TEXT='#f1f5ef',MUTED='#a3b8ae',LINE='#5d82744d';
const WIN='#2f7d6b',LOSS='#8a4f63';
const TIER:{[key:string]:string}={top:'#f0d9a4',mid:'#8db4c6',steady:'#9fd0b6',bad:'#e2a2b4',thin:'#8b9aa6'};
const PAD=64,WIDTH=1080;
const CONTENT=WIDTH-PAD*2;

export function renderRecapShare(games:RecapGame[],selection:RecapSelection,names:Record<string,string>){
 const model=recapShareModel(games,selection,names);
 const members=model.members.slice(0,8),recent=model.recent,roles=model.cast.roles.slice(0,10);
 const s=model.summary,rate=s.games?s.wins/s.games:0;
 const tall=document.createElement('canvas');tall.width=WIDTH;tall.height=7200;
 const c=tall.getContext('2d');if(!c)throw Error('当前浏览器暂不支持生成分享图');

 const T=(value:string,x:number,y:number,size:number,color=TEXT,o:{align?:CanvasTextAlign;max?:number;weight?:number}={})=>{
  c.font=`${o.weight??500} ${size}px "Microsoft YaHei","PingFang SC",sans-serif`;
  c.fillStyle=color;c.textAlign=o.align??'left';
  const max=o.max??CONTENT;let out=value;
  if(c.measureText(out).width>max){while(out.length>1&&c.measureText(out+'…').width>max)out=out.slice(0,-1);out+='…';}
  c.fillText(out,x,y);return c.measureText(out).width;
 };
 const width=(value:string,size:number,weight=500)=>{c.font=`${weight} ${size}px "Microsoft YaHei","PingFang SC",sans-serif`;return c.measureText(value).width;};
 const wrap=(value:string,x:number,y:number,size:number,color:string,max:number,lh:number)=>{
  c.font=`500 ${size}px "Microsoft YaHei","PingFang SC",sans-serif`;c.fillStyle=color;c.textAlign='left';
  let line='',row=0;
  for(const ch of value){
   const next=line+ch;
   if(c.measureText(next).width>max&&line){c.fillText(line,x,y+row*lh);row++;line=ch;}
   else line=next;
  }
  if(line){c.fillText(line,x,y+row*lh);row++;}
  return Math.max(row,1);
 };

 const panel=(x:number,y:number,w:number,h:number,r=16,fill='#ffffff09',stroke=LINE)=>{c.beginPath();c.roundRect(x,y,w,h,r);c.fillStyle=fill;c.fill();c.strokeStyle=stroke;c.lineWidth=1;c.stroke();};
 const rule=(y:number,color=LINE)=>{c.beginPath();c.moveTo(PAD,y);c.lineTo(PAD+CONTENT,y);c.strokeStyle=color;c.lineWidth=1;c.stroke();};

 // 背景：深青到墨蓝，加柔和光斑、六边形水印与细颗粒，避免纯色板的廉价感。
 const bg=c.createLinearGradient(0,0,WIDTH*0.35,tall.height);
 bg.addColorStop(0,'#183c3f');bg.addColorStop(.42,'#10262f');bg.addColorStop(1,'#0a1622');
 c.fillStyle=bg;c.fillRect(0,0,WIDTH,tall.height);
 const glow=c.createRadialGradient(560,300,60,560,300,860);
 glow.addColorStop(0,'#9dc9ad1f');glow.addColorStop(1,'#00000000');
 c.fillStyle=glow;c.fillRect(0,0,WIDTH,1200);
 for(let j=0;j<5;j++){c.beginPath();for(let i=0;i<6;i++){const a=Math.PI/3*i+.52,r=300+j*60;c[i?'lineTo':'moveTo'](540+Math.cos(a)*r,420+Math.sin(a)*r);}c.closePath();c.strokeStyle='#93bfa514';c.stroke();}
 for(let i=0;i<46;i++){c.fillStyle=i%3?'#94c5b62e':'#d7bd7f5c';c.fillRect(70+(i*151)%950,120+(i*97)%3000,2,2);}

 let y=0;
 // 品牌头
 T('⬡  海克斯战报馆',PAD,78,24,GOLD,{weight:600});
 T('THE RECAP ARCHIVE',PAD+CONTENT,78,16,MUTED,{align:'right',max:360});
 rule(104,'#5d827466');

 // 标题区
 T(model.headline,PAD,182,52,GOLD,{weight:600,max:CONTENT});
 T(model.subtitle,PAD,232,26,TEXT,{max:CONTENT});
 T(model.scope,PAD,268,18,MUTED);

 // 主面板：左边场次大字，右边胜率环形
 panel(PAD,300,CONTENT,250,18,'#ffffff0a','#5d82744d');
 T('一起打过',PAD+40,352,18,MUTED);
 const bigW=T(String(s.games),PAD+40,452,94,GOLD,{weight:600,max:520});
 T('场',PAD+40+bigW+14,452,26,MUTED,{max:120});
 const chip=(x:number,label:string,color:string)=>{c.font='600 22px "Microsoft YaHei","PingFang SC",sans-serif';const w=c.measureText(label).width+40;
  c.beginPath();c.roundRect(x,474,w,42,21);c.fillStyle=color+'1f';c.fill();c.strokeStyle=color+'55';c.lineWidth=1;c.stroke();
  T(label,x+w/2,502,22,color,{align:'center',max:w-20});return w;};
 const w1=chip(PAD+40,`${s.wins} 胜 ${s.games-s.wins} 负`,'#9fd0b6');
 chip(PAD+40+w1+14,`最长 ${s.longest} 连胜`,GOLD_DIM);
 const cx=880,cy=425,r=86;
 c.lineWidth=14;c.lineCap='round';
 c.beginPath();c.arc(cx,cy,r,0,Math.PI*2);c.strokeStyle='#ffffff12';c.stroke();
 if(rate>0){const arc=c.createLinearGradient(cx-r,cy-r,cx+r,cy+r);arc.addColorStop(0,'#f0d9a4');arc.addColorStop(1,'#9fd0b6');
  c.beginPath();c.arc(cx,cy,r,-Math.PI/2,-Math.PI/2+Math.PI*2*Math.min(rate,1));c.strokeStyle=arc;c.stroke();}
 c.lineCap='butt';
 T(`${(rate*100).toFixed(1)}%`,cx,cy+8,38,TEXT,{align:'center',max:r*1.7,weight:600});
 T('胜率',cx,cy+38,16,MUTED,{align:'center',max:r*1.4});
 y=584;

 // 战果时间线
 T('每一格，都是一起扛过的一把',PAD,y,26,GOLD,{weight:600,max:700});
 T('旧 → 新',PAD+CONTENT,y,16,MUTED,{align:'right',max:200});
 y+=26;
 const perRow=23,cell=32,gap=8;
 model.results.forEach((g,i)=>{
  const x=PAD+(i%perRow)*(cell+gap),top=y+Math.floor(i/perRow)*(cell+gap);
  c.beginPath();c.roundRect(x,top,cell,cell,7);c.fillStyle=g.win?WIN:LOSS;c.fill();
  c.strokeStyle=g.win?'#7fc9a866':'#d99bb066';c.lineWidth=1;c.stroke();
  T(g.win?'胜':'负',x+cell/2,top+22,15,'#e8efe6',{align:'center',max:cell-6});
 });
 y+=Math.max(1,Math.ceil(model.results.length/perRow))*(cell+gap)+18;
 T(`共 ${model.results.length} 场${model.results.length===50?'（最近 50 场）':''}`,PAD,y,17,MUTED);
 T('绿＝胜 / 红＝负',PAD+CONTENT,y,17,MUTED,{align:'right',max:300});
 y+=52;

 // 车队鉴定
 T(selection.mode==='night'?'今晚的车队鉴定':'这份回顾的车队鉴定',PAD,y,30,GOLD,{weight:600,max:700});
 T(roles.length?`同队 ${model.cast.games} 场 · ${roles.length} 人上车`:`同队 ${model.cast.games} 场`,PAD+CONTENT,y,17,MUTED,{align:'right',max:420});
 y+=22;rule(y);y+=26;
 if(roles.length){
  roles.forEach((role,i)=>{
   const top=y,h=156,tone=TIER[role.tier]||TIER.mid;
   panel(PAD,top,CONTENT,h,16,'#ffffff09','#5d82744d');
   c.beginPath();c.roundRect(PAD+1,top+14,4,h-28,2);c.fillStyle=tone;c.fill();
   T(role.thin?'替补':`#${i+1}`,PAD+28,top+46,role.thin?18:24,tone,{weight:600,max:60});
   const title=role.title,tn=width(title,18,600)+30;
   c.beginPath();c.roundRect(PAD+CONTENT-tn,top+24,tn,34,17);c.fillStyle=tone+'22';c.fill();c.strokeStyle=tone+'66';c.lineWidth=1;c.stroke();
   T(title,PAD+CONTENT-tn/2,top+47,18,tone,{align:'center',max:tn-18});
   T(names[role.id]||'玩家',PAD+86,top+48,32,TEXT,{weight:600,max:CONTENT-86-tn-60});
   const scoreW=T(role.average.toFixed(1),PAD+86,top+104,42,GOLD,{weight:600,max:180});
   T('场均表现分',PAD+86+scoreW+12,top+104,17,MUTED,{max:200});
   T(`${role.games} 场 · ${role.wins} 胜 ${role.losses} 负 · 胜率 ${(role.rate*100).toFixed(0)}%`,PAD+CONTENT,top+104,17,MUTED,{align:'right',max:340});
   T(role.line,PAD+86,top+138,19,'#cfe0d4',{max:CONTENT-120});
   y+=h+14;
  });
  y-=14;
  y+=30;const noteLines=wrap(model.cast.note,PAD,y,16,MUTED,CONTENT,24);y+=(noteLines-1)*24+64;
 }else{
  y+=wrap(model.cast.note||'这次样本不足，先不急着分锅。',PAD,y,20,MUTED,CONTENT,28)+30;
 }

 // 成员名单
 T('这份战报里，有这些熟悉的名字',PAD,y,26,GOLD,{weight:600,max:700});
 T(members.length<model.members.length?`共 ${model.members.length} 人 · 仅展示前 8 位`:`共 ${members.length} 人`,PAD+CONTENT,y,16,MUTED,{align:'right',max:340});
 y+=22;rule(y);y+=18;
 members.forEach((p,i)=>{
  const col=i%2,x=PAD+col*488,top=y+Math.floor(i/2)*104;
  panel(x,top,464,96,14,'#ffffff08','#5d827440');
  T(names[p.id]||'玩家',x+22,top+34,23,TEXT,{weight:600,max:240});
  T(`${p.games} 场`,x+442,top+34,16,MUTED,{align:'right',max:110});
  T(`KDA ${p.kills??'—'} / ${p.deaths??'—'} / ${p.assists??'—'}`,x+22,top+64,16,MUTED,{max:250});
  T(`伤害 ${p.damage===null?'—':Math.round(p.damage/10000*10)/10+' 万'}`,x+442,top+64,16,MUTED,{align:'right',max:180});
  T(`${p.mvp} MVP / ${p.ace} ACE`,x+22,top+86,15,GOLD_DIM,{max:250});
 });
 y+=Math.ceil(members.length/2)*104+34;

 // 最近几场
 const when=(ts:number)=>new Date(ts).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
 T('最近一起打过的几场',PAD,y,26,GOLD,{weight:600,max:700});
 y+=22;rule(y);y+=18;
 recent.forEach((g,i)=>{
  const top=y+i*92;
  panel(PAD,top,CONTENT,82,14,'#ffffff08','#5d827440');
  c.beginPath();c.roundRect(PAD+20,top+25,62,32,9);c.fillStyle=g.win?'#7fc9a826':'#d99bb026';c.fill();
  c.strokeStyle=g.win?'#7fc9a866':'#d99bb066';c.lineWidth=1;c.stroke();
  T(g.win?'胜利':'一起扛',PAD+51,top+47,17,g.win?'#9fdcbd':'#e5b2c3',{align:'center',max:56});
  T(`${when(g.started_ms)} · ${Math.round(g.duration/60)} 分钟`,PAD+104,top+36,21,TEXT,{max:420});
  T(g.members.map(p=>names[p.profile_id]||'玩家').join(' · '),PAD+104,top+64,17,MUTED,{max:CONTENT-140});
 });
 y+=Math.max(1,recent.length)*92+10;

 // 页脚
 rule(y+16,'#5d827466');
 T('一起打过的每一场，都值得记住。',WIDTH/2,y+84,27,GOLD,{align:'center',max:CONTENT,weight:600});
 T('同队样本来自已收录有效战绩，不代表完整共同历史，也不据此断言真实预组队。',WIDTH/2,y+126,16,MUTED,{align:'center',max:CONTENT});
 T(`MVP / ACE 为工具自评 · ${selection.mode==='night'?'当晚为北京时间 18:00 至次日 06:00':'多人回顾取全部同队交集'} · 分享链接可打开完整回顾`,WIDTH/2,y+156,16,MUTED,{align:'center',max:CONTENT});
 const height=Math.min(tall.height,Math.ceil(y+196));

 const canvas=document.createElement('canvas');canvas.width=WIDTH;canvas.height=height;
 const ctx=canvas.getContext('2d');if(!ctx)throw Error('当前浏览器暂不支持生成分享图');
 ctx.drawImage(tall,0,0,WIDTH,height,0,0,WIDTH,height);
 ctx.strokeStyle='#c7ac6940';ctx.lineWidth=2;ctx.strokeRect(30,30,WIDTH-60,height-60);
 ctx.strokeStyle='#c7ac6920';ctx.lineWidth=1;ctx.strokeRect(40,40,WIDTH-80,height-80);
 return {image:canvas.toDataURL('image/png'),width:WIDTH,height,model};
}
