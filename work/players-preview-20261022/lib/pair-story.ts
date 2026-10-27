import type {Profile,Match,Dictionaries} from '../src/App';

const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const sum=(rows:Match[],key:'kills'|'deaths'|'assists')=>rows.every(m=>finite(m.player[key]))?rows.reduce((s,m)=>s+(m.player[key] as number),0):null;
export function comparePlayerGames(a:Profile,b:Profile){
 const av=a.summary?.games,bv=b.summary?.games;
 return (finite(bv)?bv:-1)-(finite(av)?av:-1)||a.name.localeCompare(b.name,'zh-CN',{numeric:true,sensitivity:'base'});
}
export type DuoPerson={name:string;kda:number|null;dpm:number|null;mvp:number|null;ace:number|null;heroes:string[];samples:number|null};
export type DuoHonor={title:string;winner:string;from:string;samples:number;tied:boolean};
export function buildPairStory(a:Profile,b:Profile,dictionary:Dictionaries){
 const choices=[{source:a,row:a.teammates?.find(t=>t.name===b.name)},{source:b,row:b.teammates?.find(t=>t.name===a.name)}]
  .filter(c=>c.row).sort((x,y)=>Number(x.source.history_scope==='shared')-Number(y.source.history_scope==='shared')||(y.row?.games||0)-(x.row?.games||0)||x.source.id.localeCompare(y.source.id));
 const source=choices[0]?.source,row=choices[0]?.row;
 const games=row?.summary?.games??row?.games??null,wins=row?.summary?.wins??row?.wins??null,rate=row?.summary?.win_rate??row?.win_rate??null;
 // Only the source relation's own public IDs identify the same sample. Never intersect legacy IDs across profiles.
 const ids=new Set(row?.match_ids||[]);
 const matches=(source?.recent||[]).filter(m=>ids.has(m.id)&&m.stats_eligible).sort((x,y)=>(y.started_ms||0)-(x.started_ms||0));
 const complete=finite(games)&&games>0&&matches.length===games;
 const heroName=(h:{champion_id?:number;champion_name?:string})=>dictionary.champions[String(h.champion_id)]?.name||h.champion_name||'英雄待补';
 const counts=new Map<number,{champion_id:number;champion_name?:string;games:number}>();
 for(const m of matches){const id=m.player.champion_id;if(id===undefined)continue;const h=counts.get(id)||{champion_id:id,champion_name:m.player.champion_name,games:0};h.games++;counts.set(id,h);}
 const kills=sum(matches,'kills'),deaths=sum(matches,'deaths'),assists=sum(matches,'assists');
 const damageRows=matches.filter(m=>finite(m.player.damage)&&finite(m.duration)&&m.duration>0);
 const own:DuoPerson={name:source?.name||a.name,kda:complete&&kills!==null&&deaths!==null&&assists!==null?(kills+assists)/Math.max(1,deaths):null,
  dpm:complete&&damageRows.length===matches.length?damageRows.reduce((s,m)=>s+(m.player.damage as number)/(m.duration as number)*60,0)/matches.length:null,
  mvp:complete&&matches.every(m=>m.player.performance)?matches.filter(m=>m.player.performance?.award==='MVP').length:null,
  ace:complete&&matches.every(m=>m.player.performance)?matches.filter(m=>m.player.performance?.award==='ACE').length:null,
  heroes:complete?[...counts.values()].sort((x,y)=>y.games-x.games||x.champion_id-y.champion_id).slice(0,3).map(h=>`${heroName(h)} ${h.games}场`):[],samples:complete?matches.length:null};
 const other:DuoPerson={name:row?.name||b.name,kda:row?.summary?.kda??null,dpm:row?.summary?.dpm??null,mvp:row?.awards?.mvp??null,ace:row?.awards?.ace??null,
  heroes:(row?.champions||[]).slice(0,3).map(h=>`${heroName(h)} ${h.games??'—'}场`),samples:finite(games)?games:null};
 const people=[a.name===source?.name?own:other,b.name===source?.name?own:other];
 const honors:DuoHonor[]=[];
 for(const [from,to] of [[a,b],[b,a]])for(const award of from.reports?.['20']?.awards||[]){
  const leader=award.leaders?.find(l=>l.name===to.name&&finite(l.samples)&&l.samples>=20);
  if(leader)honors.push({title:award.title,winner:to.name,from:from.name,samples:leader.samples as number,tied:(award.leaders?.length||0)>1});
 }
 const recent=complete?matches.slice(0,10):[];
 let streak=0,longest=0;for(const m of [...matches].reverse()){streak=m.player.win?streak+1:0;longest=Math.max(streak,longest);}
 const validDates=matches.map(m=>m.started_ms).filter(finite);
 const bestWin=matches.filter(m=>m.player.win&&finite(m.player.damage)).sort((x,y)=>(y.player.damage||0)-(x.player.damage||0))[0];
 const earliest=matches.at(-1),memories: {label:string;match:Match;hero:string}[]=[];
 if(complete&&bestWin)memories.push({label:'一起赢下的高光',match:bestWin,hero:heroName(bestWin.player)});
 if(complete&&earliest&&earliest.id!==bestWin?.id)memories.push({label:'已收录的最早并肩',match:earliest,hero:heroName(earliest.player)});
 return {source,row,games,wins,rate,losses:finite(games)&&finite(wins)?games-wins:null,people,honors,recent,complete,
  longest:complete?longest:null,oldest:complete&&validDates.length?Math.min(...validDates):null,newest:complete&&validDates.length?Math.max(...validDates):null,memories};
}
export type PairStory=ReturnType<typeof buildPairStory>;
