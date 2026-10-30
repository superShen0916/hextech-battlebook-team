export type RecapPerson={profile_id:string;champion_id:number;kills:number;deaths:number;assists:number;damage:number|null;taken:number|null;heal:number|null;penta_kills:number|null;performance?:{score:number;award?:string|null}|null};
export type RecapGame={id:string;match_id:string;started_ms:number;duration:number;win:boolean;members:RecapPerson[]};
export type RecapIndex={build_id:string;team_games:number;players:string[];nights:{date:string;friday:boolean;games:number;player_games?:Record<string,number>;players:string[];started_ms:number;ended_ms:number}[]};
const cache=new Map<string,Promise<unknown>>();
export function clearRecapCache(){cache.clear();}
export function loadRecap<T>(path:string,revision='',options:{force?:boolean;timeoutMs?:number}={}):Promise<T>{
 const url=path+(revision?'?v='+encodeURIComponent(revision):'');
 if(options.force)cache.delete(url);
 if(!cache.has(url)){
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
  const timeout=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{reject(Error('回顾读取超时，请检查网络后重试'));controller.abort();},options.timeoutMs??20000);});
  const read=Promise.resolve().then(()=>fetch(url,{cache:options.force?'reload':'no-cache',signal:controller.signal})).then(async r=>{if(!r.ok)throw Error('回顾数据暂时无法读取');const d=await r.json();if(revision&&d.build_id!==revision)throw Error('战报正在更新，请刷新后重试');return d;});
  const request=Promise.race([read,timeout]).finally(()=>clearTimeout(timer)).catch(e=>{if(cache.get(url)===request)cache.delete(url);throw e;});
  cache.set(url,request);
 }
 return cache.get(url) as Promise<T>;
}
export function commonGames(games:RecapGame[],ids:string[]){
 const selected=new Set(ids);if(selected.size<2)return [];
 return games.filter(g=>[...selected].every(id=>g.members.some(p=>p.profile_id===id)));
}
export function summarizeGames(games:RecapGame[],ids:string[]){
 const chronological=[...games].sort((a,b)=>a.started_ms-b.started_ms);let run=0,longest=0;
 for(const g of chronological){run=g.win?run+1:0;longest=Math.max(longest,run);}
 const people=ids.map(id=>{const rows=games.flatMap(g=>g.members.filter(p=>p.profile_id===id));const sum=(key:'kills'|'deaths'|'assists'|'damage'|'taken'|'heal')=>{const values=rows.map(p=>p[key]).filter((v):v is number=>typeof v==='number');return values.length?values.reduce((a,b)=>a+b,0):null;};return {id,games:rows.length,kills:sum('kills'),deaths:sum('deaths'),assists:sum('assists'),damage:sum('damage'),taken:sum('taken'),heal:sum('heal'),mvp:rows.filter(p=>p.performance?.award==='MVP').length,ace:rows.filter(p=>p.performance?.award==='ACE').length};});
 return {games:games.length,wins:games.filter(g=>g.win).length,longest,people};
}

// 车队鉴定的人数门槛与「主力」比例：不足主力一半样本的人仍然上榜，只标注不参与排马。
export const CAST_MIN_GAMES=3;
const FULL_RATIO=0.5;
export type CastTier='top'|'mid'|'steady'|'bad'|'thin';
export type CastRole={id:string;games:number;samples:number;average:number;wins:number;losses:number;rate:number;mvp:number;ace:number;title:string;line:string;tier:CastTier;thin:boolean};

/**
 * 当晚视角（只给一位玩家）时，取这一晚和他在同一队打过至少 3 场的人。
 * 多人回顾时就是所选玩家本身，交集已由 commonGames 处理。
 * 这里不再挑「人数最多的固定阵容」——那样会把换过队友的场次整段丢掉。
 */
export function castPool(games:RecapGame[],ids:string[]){
 if(ids.length>=2)return ids;
 const anchor=ids[0];if(!anchor)return ids;
 const counts=new Map<string,number>();
 for(const g of games){
  if(!g.members.some(p=>p.profile_id===anchor))continue;
  for(const p of g.members)counts.set(p.profile_id,(counts.get(p.profile_id)||0)+1);
 }
 const pool=[...counts].filter(([,n])=>n>=CAST_MIN_GAMES).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([id])=>id);
 return pool.length>=2?pool:ids;
}

// Titles use the existing v0.5 performance score, computed over each person's own team games.
export function recapCast(games:RecapGame[],ids:string[]){
 const scored=ids.map(id=>{
  const samples=games.map(g=>({g,p:g.members.find(p=>p.profile_id===id)})).filter((r):r is {g:RecapGame;p:RecapPerson}=>Boolean(r.p));
  const valid=samples.filter(r=>typeof r.p.performance?.score==='number'&&Number.isFinite(r.p.performance.score));
  const average=valid.length?valid.reduce((sum,r)=>sum+r.p.performance!.score,0)/valid.length:null;
  const wins=samples.filter(r=>r.g.win).length;
  return {id,games:samples.length,samples:valid.length,average,wins,losses:samples.length-wins,
   rate:samples.length?wins/samples.length:0,
   mvp:samples.filter(r=>r.p.performance?.award==='MVP').length,
   ace:samples.filter(r=>r.p.performance?.award==='ACE').length};
 }).filter((r):r is typeof r&{average:number}=>r.average!==null&&r.samples===r.games&&r.games>=CAST_MIN_GAMES)
  .sort((a,b)=>b.average-a.average||a.id.localeCompare(b.id));
 const base={games:games.length,roles:[] as CastRole[]};
 if(scored.length<2)return {...base,note:'至少 2 位朋友、3 场相同同队对局且表现分完整才评梗；当前样本不足，先不急着分锅。'};
 const most=Math.max(...scored.map(r=>r.games));
 // 样本不足主力一半的人照样上榜，但排在最后、只做备注，不占名次。
 const ordered=[...scored].sort((a,b)=>(a.games<most*FULL_RATIO?1:0)-(b.games<most*FULL_RATIO?1:0)||b.average-a.average||a.id.localeCompare(b.id));
 const ranked=ordered.filter(r=>r.games>=most*FULL_RATIO);
 if(ranked.length<2)return {...base,note:'这一晚主力样本凑不齐两个人，先把名字列出来，不排马。'};
 const high=ranked[0],low=ranked.at(-1)!;
 if(high.average-low.average<0.1)return {...base,note:'这次大家表现接近，并肩同分，不硬分上中下。'};
 const roles:CastRole[]=ordered.map(r=>{
  const common={...r,thin:r.games<most*FULL_RATIO};
  if(common.thin)return {...common,title:'轮换位',tier:'thin' as CastTier,line:`这趟只赶上 ${r.games} 场，样本太薄，先不发马牌。`};
  if(high.average-r.average<0.1){
   const line=r.mvp>=2?`${r.mvp} 个 MVP 摆在这，方向盘就是你的。`:'这车能开，全靠你在前面拉。';
   return {...common,title:'上等马',tier:'top' as CastTier,line};
  }
  if(r.average-low.average<0.1){
   if(r.average>=50)return {...common,title:'稳住位',tier:'steady' as CastTier,line:'有人负责起飞，也有人负责陪到最后。'};
   if(r.rate>0.5)return {...common,title:'稳住位',tier:'steady' as CastTier,line:'分不炸，但该赢的都赢了，稳住也是本事。'};
   return {...common,title:'下等马',tier:'bad' as CastTier,line:'今晚的学费，兄弟们先垫了。'};
  }
  return {...common,title:'中等马',tier:'mid' as CastTier,line:'不抢方向盘，也没跳车，主打一个陪伴。'};
 });
 const losses=games.filter(g=>!g.win).length;
 if(games.length&&losses/games.length>=0.6&&low.average<40&&high.average-low.average>=10){
  for(const role of roles)if(role.tier==='bad'&&role.rate<=0.5){role.title='下等马 · 甲级战犯';role.line='今晚的锅有点烫，下把请用操作申诉。';}
 }
 return {...base,roles,note:'只看同一队的样本，各人按自己打过的场次算场均；打不满主力一半的只列名字、不参与排马。胜率过半不叫下等马，差战绩也不强行甩锅。'};
}
