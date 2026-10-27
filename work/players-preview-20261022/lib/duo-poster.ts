import type {PairStory} from './pair-story';
import {duoAchievements} from './achievements';
type PairPoster={a:string;b:string;avatarA?:string|null;avatarB?:string|null;story:PairStory};
const day=(v?:number|null)=>v?new Date(v).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'}):'待补';
const n=(v?:number|null,d=0)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:d}):'—';
export async function drawPairPoster(data:PairPoster):Promise<string>{
 const {story:s}=data,canvas=document.createElement('canvas');canvas.width=1080;canvas.height=2400;
 const c=canvas.getContext('2d');if(!c)throw Error('canvas_unavailable');
 const gradient=c.createLinearGradient(0,0,1080,2400);gradient.addColorStop(0,'#194039');gradient.addColorStop(.38,'#10272f');gradient.addColorStop(1,'#111c29');c.fillStyle=gradient;c.fillRect(0,0,1080,2400);
 const text=(value:string,x:number,y:number,size:number,color='#f2eee2',align:CanvasTextAlign='left',weight=500,max=950)=>{c.fillStyle=color;c.textAlign=align;while(size>14){c.font=`${weight} ${size}px "Microsoft YaHei","Segoe UI",sans-serif`;if(c.measureText(value).width<=max)break;size--;}c.fillText(value,x,y);};
 const line=(x:number,y:number,w:number,color='#517067')=>{c.beginPath();c.moveTo(x,y);c.lineTo(x+w,y);c.strokeStyle=color;c.lineWidth=1;c.stroke();};
 const panel=(x:number,y:number,w:number,h:number)=>{c.fillStyle='#9fc5ae09';c.fillRect(x,y,w,h);c.strokeStyle='#5d82754d';c.strokeRect(x,y,w,h);};
 const heading=(label:string,y:number,sub:string)=>{text(label,68,y,30,'#dec792','left',600);text(sub,1012,y,17,'#a4b9b0','right',400,510);line(68,y+20,944,'#51706780');};
 for(let j=0;j<5;j++){c.beginPath();for(let i=0;i<6;i++){const a=Math.PI/3*i+.52,r=280+j*55;c[i?'lineTo':'moveTo'](540+Math.cos(a)*r,440+Math.sin(a)*r);}c.closePath();c.strokeStyle='#93bfa51a';c.stroke();}
 for(let i=0;i<38;i++){c.fillStyle=i%3?'#94c5b635':'#d7bd7f70';c.fillRect(70+(i*137)%940,130+(i*89)%2080,2,2);}
 text('⬡  海克斯战报馆',68,77,25,'#e0c58d');text('THE DUO ARCHIVE / 01',1012,77,17,'#a7bdb3','right',400);line(68,108,944);
 text('我们的并肩档案',540,204,52,'#f2eee2','center',600);text('GOOD GAMES. GREAT COMPANY.',540,249,18,'#a4c1b2','center',400);
 const load=async(url?:string|null):Promise<HTMLImageElement|null>=>{if(!url?.startsWith('/assets/'))return null;return new Promise(resolve=>{const img=new Image();const timer=setTimeout(()=>resolve(null),5000);img.onload=()=>{clearTimeout(timer);resolve(img);};img.onerror=()=>{clearTimeout(timer);resolve(null);};img.src=url;});};
 const images=await Promise.all([load(data.avatarA),load(data.avatarB)]);
 for(let i=0;i<2;i++){const x=i?750:330,y=389;c.save();c.beginPath();c.arc(x,y,77,0,2*Math.PI);c.clip();if(images[i])c.drawImage(images[i]!,x-77,y-77,154,154);else{c.fillStyle='#263e41';c.fillRect(x-77,y-77,154,154);text((i?data.b:data.a).slice(0,1),x,y+19,52,'#dfc38d','center');}c.restore();c.beginPath();c.arc(x,y,84,0,2*Math.PI);c.strokeStyle='#d4ba82';c.lineWidth=2;c.stroke();text(i?data.b:data.a,x,514,32,'#f2eee2','center',500,390);}
 line(436,389,208,'#bbab7c');text('＋',540,400,30,'#d4ba82','center');
 text(n(s.games),540,691,137,'#e8ce96','center');text('场有效同队',540,744,27,'#e3e7df','center',400);
 text((s.rate===null?'—':n(s.rate*100,1)+'%')+' 同队胜率',540,809,36,'#a6d2b9','center');
 text(`${n(s.wins)} 场一起赢   /   ${n(s.losses)} 场一起扛   /   最长 ${n(s.longest)} 连胜`,540,865,24,'#c9d5c9','center');
 text(s.complete?`${day(s.oldest)} — ${day(s.newest)} · 已收录的并肩时光`:'逐局关联待补，暂不推算日期与连胜',540,914,20,'#9db6aa','center',400);
 const recent=[...s.recent].reverse();text('最近同队',68,995,22,'#d9c893');
 if(recent.length){recent.forEach((m,i)=>{const x=236+i*65;c.fillStyle=m.player.win?'#366650':'#694b52';c.fillRect(x,958,50,50);text(m.player.win?'胜':'负',x+25,992,22,'#e3e6d9','center');});text('旧 → 新',1012,992,16,'#9db6aa','right');}else text('逐局记录尚未齐备',1012,994,22,'#9db6aa','right');
 heading('并肩时，我们的样子',1093,'只看这段同队样本');
 s.people.forEach((p,i)=>{const x=68+i*486;panel(x,1130,458,308);text(p.name,x+25,1178,29,'#e3d6ad','left',600,410);text('KDA',x+25,1226,19,'#a5bab0');text('每分钟伤害',x+230,1226,19,'#a5bab0');text(n(p.kda,2),x+25,1278,38);text(n(p.dpm),x+230,1278,38);text(`自评 MVP ${n(p.mvp)}  /  ACE ${n(p.ace)}`,x+25,1325,21,'#b9cbbd');text(p.heroes[0]||'同队英雄记录待补',x+25,1372,22,'#ddc88e','left',500,410);text(p.heroes.slice(1).join(' · ')||'未齐备的指标保留为空',x+25,1411,18,'#9db6aa','left',400,410);});
 duoAchievements(s).forEach((p,i)=>{const x=68+i*324;panel(x,1455,296,42);text(p.definition.name+' '+(p.value===null?'待补':p.tier?['','I','II','III'][p.tier]:'未点亮'),x+148,1483,19,'#dfc78c','center',500,276);});
 heading('彼此战报里的荣誉',1556,'20 场指标门槛 · 保留并列');
 const honors=s.honors.slice(0,4);
 if(honors.length)honors.forEach((h,i)=>{const x=68+(i%2)*486,y=1594+Math.floor(i/2)*130;panel(x,y,458,112);text('⬡ '+h.title+(h.tied?' · 并列':''),x+20,y+35,24,'#dfc78c','left',600,420);text(h.winner,x+20,y+68,22,'#eee9d9','left',500,420);text(`来自 ${h.from} 的战报 · ${h.samples} 场样本`,x+20,y+96,15,'#a8bdb0','left',400,420);});
 else{panel(68,1594,944,210);text('暂未进入彼此的荣誉榜',540,1678,29,'#d6d8c7','center');text('一起打过的每一场，仍值得记住。',540,1735,23,'#9fb8ac','center');}
 text(s.honors.length>4?`另有 ${s.honors.length-4} 项荣誉，打开双方朋友战报查看。`:'荣誉分别来自双方各自的已收录历史，并非只在两人之间评选。',68,1877,17,'#a5b8ad');
 heading('一起打过，值得记得',1933,(s.source?.name||'玩家')+' 的对局视角');
 if(s.memories.length)s.memories.forEach(({label,match,hero},i)=>{const y=1991+i*105;text(label,68,y,24,'#d9c58e');text(`${day(match.started_ms)} · ${hero}`,68,y+35,20,'#a8bdb0');text(`${n(match.player.kills)} / ${n(match.player.deaths)} / ${n(match.player.assists)}`,1012,y,27,'#ebe7d7','right');text(n((match.player.damage||0)/10000,1)+' 万伤害',1012,y+35,20,'#a8bdb0','right');});
 else text('逐局关联尚未齐备，代表对局待补。',68,2035,24,'#a8bdb0');
 line(68,2211,944);text('有些默契，是一场一场打出来的。',540,2262,27,'#e5d3a5','center',400);
 text(`来源：${s.source?.name||'—'} 的${s.source?.history_scope==='shared'?'部分同队样本':'已收录个人历史'}；不代表完整共同历史。`,540,2310,17,'#a6b8b1','center',400,944);
 text('同队不代表预先组队。MVP / ACE 为工具自评。缺失指标不推算。',540,2343,17,'#8ca59c','center',400);
 const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(Error('png_failed')),'image/png'));return URL.createObjectURL(blob);
}
