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

// Titles use the existing v0.5 performance score. Compare only the exact same team games.
export function recapCast(games:RecapGame[],ids:string[]){
 const common=commonGames(games,ids);
 const rows=ids.map(id=>{const samples=common.map(g=>({g,p:g.members.find(p=>p.profile_id===id)!}));
  const valid=samples.filter(r=>typeof r.p.performance?.score==='number'&&Number.isFinite(r.p.performance.score));
  return {id,games:common.length,samples:valid.length,average:valid.length?valid.reduce((sum,r)=>sum+r.p.performance!.score,0)/valid.length:null,
   wins:samples.filter(r=>r.g.win).length,mvp:samples.filter(r=>r.p.performance?.award==='MVP').length,ace:samples.filter(r=>r.p.performance?.award==='ACE').length};
 }).filter((r):r is typeof r&{average:number}=>r.average!==null&&r.samples===common.length&&common.length>=3).sort((a,b)=>b.average-a.average||a.id.localeCompare(b.id));
 if(rows.length<2)return {games:common.length,roles:[],note:'至少 2 位朋友、3 场相同同队对局且表现分完整才评梗；当前样本不足，先不急着分锅。'};
 const high=rows[0],low=rows.at(-1)!;
 if(high.average-low.average<0.1)return {games:common.length,roles:[],note:'这次大家表现接近，并肩同分，不硬分上中下。'};
 const roles=rows.map(r=>({...r,title:high.average-r.average<0.1?'上等马':r.average-low.average<0.1?(r.average<50?'下等马':'稳住位'):'中等马',
  line:high.average-r.average<0.1?'这车能开，全靠你在前面拉。':r.average-low.average<0.1?(r.average<50?'今晚的学费，兄弟们先垫了。':'有人负责起飞，也有人负责陪到最后。'):'不抢方向盘，也没跳车，主打一个陪伴。'}));
 if(common.filter(g=>!g.win).length/common.length>=0.6&&low.average<40&&high.average-low.average>=10){
  for(const last of roles.filter(r=>r.average-low.average<0.1)){last.title='下等马 · 甲级战犯';last.line='今晚的锅有点烫，下把请用操作申诉。';}
 }
 return {games:common.length,roles,note:'仅按相同同队样本的 v0.5 场均表现分玩梗，不判输赢责任；低于 50 才叫下等马，差战绩不强行甩锅。'};
}

export function recapCastGroup(games:RecapGame[],ids:string[]){
 // Anchor-only night views can include changing teammates. Choose a shared group,
 // never compare individuals with different schedules as if they played together.
 if(ids.length>=2)return ids;
 const anchor=ids[0],groups=new Map<string,{ids:string[];count:number}>();
 for(const g of games){const group=g.members.map(p=>p.profile_id).sort();if(!group.includes(anchor)||group.length<2)continue;
  const key=group.join(',');const row=groups.get(key)||{ids:group,count:0};row.count++;groups.set(key,row);}
 return [...groups.values()].sort((a,b)=>b.ids.length-a.ids.length||b.count-a.count||a.ids.join(',').localeCompare(b.ids.join(','))).find(r=>r.count>=3)?.ids||ids;
}
