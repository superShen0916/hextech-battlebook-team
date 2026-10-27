export type Counts = {games:number;wins:number;win_rate:number};
export type IntelHero = Counts & {id:string;name:string;title:string};
export type IntelAugment = Counts & {id:string;name:string;rarity:string;heroes:number};
export type IntelPair = Counts & {id:string;source:'live'|'pbe';low_sample:boolean};
export type IntelIndex = {default_patch:string;datasets:{patch:string;snapshot_at:string;matches:number;heroes:number;augments:number;pbe_augments:number}[]};
export type IntelOverview = {patch:string;snapshot_at:string;license:string;source_url:string;regions:string[];window:{start:string;end_exclusive:string};matches:{valid:number;excluded:number};heroes:IntelHero[];augments:IntelAugment[];augment_dictionary:Record<string,{name:string;rarity:string}>;provisional_augments:Record<string,{games:number;wins:number;win_rate:number;source:string}>};
export type IntelDetail = {patch:string;hero_id:string;snapshot_at:string;pairs:IntelPair[]};

// Ranking confidence, never displayed as a forecast of the next game's outcome.
export function wilson(row:Counts){
 if(row.games<=0)return 0;
 const z=1.959963984540054,n=row.games,p=row.wins/n;
 return (p+z*z/(2*n)-z*Math.sqrt((p*(1-p)+z*z/(4*n))/n))/(1+z*z/n);
}
export function rankRows<T extends Counts & {id:string}>(rows:T[],sort:string){
 const metric=(r:T)=>sort==='games'?r.games:sort==='win_rate'?r.win_rate:wilson(r);
 return [...rows].sort((a,b)=>metric(b)-metric(a)||b.games-a.games||a.id.localeCompare(b.id));
}
export function selectPairs(rows:IntelPair[],showPbe:boolean,minimum:number){
 return rows.filter(row=>(showPbe||row.source==='live')&&row.games>=minimum);
}
export async function readIntel<T>(url:string,signal?:AbortSignal):Promise<T>{
 const response=await fetch(url,{signal,cache:'no-cache'});
 if(!response.ok)throw new Error(`数据读取失败（${response.status}），请稍后重试。`);
 return response.json() as Promise<T>;
}
