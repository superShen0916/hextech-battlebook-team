type PairPoster={a:string;b:string;avatarA?:string|null;avatarB?:string|null;games:number|null;wins:number|null;rate:number|null;source:string;partial:boolean;oldest?:number|null;newest?:number|null};
const labelDate=(v?:number|null)=>v?new Date(v).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'}):'—';
const number=(v:number|null,d=0)=>v===null?'—':v.toLocaleString('zh-CN',{maximumFractionDigits:d});
export async function drawPairPoster(data:PairPoster):Promise<string>{
 const canvas=document.createElement('canvas');canvas.width=1080;canvas.height=1350;const c=canvas.getContext('2d');if(!c)throw Error('canvas_unavailable');
 const gradient=c.createLinearGradient(0,0,1080,1350);gradient.addColorStop(0,'#163a36');gradient.addColorStop(.52,'#101f2a');gradient.addColorStop(1,'#111b23');c.fillStyle=gradient;c.fillRect(0,0,1080,1350);
 const text=(value:string,x:number,y:number,size:number,color='#f2eee2',align:CanvasTextAlign='left',weight=500,max=950)=>{c.fillStyle=color;c.textAlign=align;while(size>14){c.font=`${weight} ${size}px "Microsoft YaHei","Segoe UI",sans-serif`;if(c.measureText(value).width<=max)break;size--;}c.fillText(value,x,y);};
 const line=(x:number,y:number,w:number,color='#517067')=>{c.beginPath();c.moveTo(x,y);c.lineTo(x+w,y);c.strokeStyle=color;c.lineWidth=1;c.stroke();};
 const hex=(x:number,y:number,r:number,rotation=0)=>{c.beginPath();for(let i=0;i<6;i++){const angle=Math.PI/3*i+rotation;c[i?'lineTo':'moveTo'](x+Math.cos(angle)*r,y+Math.sin(angle)*r);}c.closePath();c.stroke();};
 c.strokeStyle='#7ea99b25';c.lineWidth=1;hex(540,510,365,.52);hex(540,510,412,.52);c.strokeStyle='#c8ad7540';hex(540,510,289,.52);
 const glow=c.createRadialGradient(540,530,10,540,530,540);glow.addColorStop(0,'#5bba8c20');glow.addColorStop(1,'#5bba8c00');c.fillStyle=glow;c.fillRect(0,140,1080,900);
 for(let i=0;i<28;i++){const x=80+(i*137)%920,y=170+(i*89)%880;c.fillStyle=i%3===0?'#d7bd7f80':'#94c5b640';c.fillRect(x,y,i%3===0?3:2,i%3===0?3:2);}
 text('⬡  海克斯战报馆',68,82,26,'#e0c58d');text('THE DUO ARCHIVE',1012,82,17,'#a7bdb3','right',400);line(68,112,944);
 text('我们的并肩档案',540,208,50,'#f2eee2','center');text('GOOD GAMES. GREAT COMPANY.',540,250,17,'#9eb9ad','center',400);
 const load=async(url?:string|null):Promise<HTMLImageElement|null>=>{if(!url?.startsWith('/assets/'))return null;return await new Promise(resolve=>{const img=new Image();const timer=setTimeout(()=>resolve(null),5000);img.onload=()=>{clearTimeout(timer);resolve(img);};img.onerror=()=>{clearTimeout(timer);resolve(null);};img.src=url;});};
 const images=await Promise.all([load(data.avatarA),load(data.avatarB)]);
 for(let i=0;i<2;i++){const x=i?730:350,y=440;c.save();c.beginPath();c.arc(x,y,91,0,2*Math.PI);c.clip();if(images[i])c.drawImage(images[i]!,x-91,y-91,182,182);else{c.fillStyle='#263e41';c.fillRect(x-91,y-91,182,182);text((i?data.b:data.a).slice(0,1),x,y+20,56,'#dfc38d','center');}c.restore();c.beginPath();c.arc(x,y,99,0,2*Math.PI);c.strokeStyle='#d4ba82';c.lineWidth=2;c.stroke();text(i?data.b:data.a,x,588,31,'#f2eee2','center',500,390);}
 line(461,440,158,'#bbab7c');text('＋',540,450,28,'#d4ba82','center');
 text(number(data.games),540,803,170,'#e8ce96','center');text('场有效同队',540,862,29,'#e3e7df','center',400);
 const rate=data.rate===null?'—':number(data.rate*100,1)+'%';text(`${rate} 同队胜率  ·  ${number(data.wins)} 场胜利`,540,942,27,'#a6c9ba','center');
 line(220,995,640,'#587268');text('有些默契，是一场一场打出来的。',540,1068,30,'#e9dfc8','center',400);
 text('来源档案：'+labelDate(data.oldest)+' — '+labelDate(data.newest),540,1145,20,'#a6b8b1','center',400);text(`来自 ${data.source} 的${data.partial?'部分同队样本':'已收录个人历史'}，不代表完整生涯。`,540,1190,18,'#a6b8b1','center',400,920);text('同队不代表预先组队；仅对现有记录作纪念。',540,1225,17,'#8ca59c','center',400);
 text('把每一场并肩，留在这里。',540,1300,18,'#dac596','center',400);
 const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(Error('png_failed')),'image/png'));return URL.createObjectURL(blob);
}
