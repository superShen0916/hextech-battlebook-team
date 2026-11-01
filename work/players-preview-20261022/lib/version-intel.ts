export type Counts = {games:number;wins:number;win_rate:number};
export type IntelHero = Counts & {id:string;name:string;title:string};
export type IntelAugment = Counts & {id:string;name:string;rarity:string;heroes:number};
export type IntelPair = Counts & {id:string;source:'live'|'pbe';low_sample:boolean};
export type IntelIndex = {default_patch:string;datasets:{patch:string;snapshot_at:string;matches:number;heroes:number;augments:number;pbe_augments:number}[]};
export type IntelOverview = {patch:string;snapshot_at:string;license:string;source_url:string;regions:string[];window:{start:string;end_exclusive:string};matches:{valid:number;excluded:number};heroes:IntelHero[];augments:IntelAugment[];augment_dictionary:Record<string,{name:string;rarity:string;icon_url?:string|null}>;provisional_augments:Record<string,{games:number;wins:number;win_rate:number;source:string}>};
export type IntelDetail = {patch:string;hero_id:string;snapshot_at:string;pairs:IntelPair[]};

export type EquipmentOption = {items:string[];pick_rate:number;win_rate:number};
export type EquipmentGroup = 'items'|'core'|'boots'|'starting'|'full';
export type EquipmentHero = {id:string;name:string;title:string;stats_date:string|null;available:boolean} & Record<EquipmentGroup,EquipmentOption[]>;
export type EquipmentSnapshot = {schema_version:1;source:'Tencent';source_url:string;mode:'KIWI';queue_id:2400;patch:null;sample_size:null;sample_scope:'undisclosed';retrieved_at:string;stats_date_min:string;stats_date_max:string;snapshot_id:string;heroes:EquipmentHero[];items:Record<string,{name:string;icon_url:string|null}>};

export function rankEquipment(rows:EquipmentOption[],sort:string){
 return [...rows].sort((a,b)=>(sort==='win_rate'?b.win_rate-a.win_rate:b.pick_rate-a.pick_rate)||b.pick_rate-a.pick_rate||a.items.join(',').localeCompare(b.items.join(',')));
}

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

export type TencentAugment = {id:string;source_rank:number;pick_rate:number;tier:'S'|'A'|'B'|'C';rarity_tier:'S'|'A'|'B'|'C';rarity_rank:number;rarity:'silver'|'gold'|'prismatic'};
export type TencentAugmentSnapshot = {schema_version:1;source:'Tencent';source_url:string;mode:'KIWI';queue_id:2400;patch:null;win_rate:null;sample_size:null;sample_scope:'undisclosed';stats_date_min:string;stats_date_max:string;retrieved_at:string;snapshot_id:string;heroes:{id:string;name:string;title:string;stats_date:string|null;augments:TencentAugment[]}[];dictionary:Record<string,{name:string;icon_url:string|null;description:string;description_patch:string|null}>};
export function rankTencentAugments(rows:TencentAugment[],sort:string,withinRarity=false){
 const order={S:0,A:1,B:2,C:3};
 const tier=(row:TencentAugment)=>withinRarity?row.rarity_tier:row.tier;
 const rank=(row:TencentAugment)=>withinRarity?row.rarity_rank:row.source_rank;
 return [...rows].sort((a,b)=>(sort==='pick_rate'?b.pick_rate-a.pick_rate:order[tier(a)]-order[tier(b)])||rank(a)-rank(b)||a.id.localeCompare(b.id));
}
