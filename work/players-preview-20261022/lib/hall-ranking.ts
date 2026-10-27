export type HallRow={id:string;name:string;games:number;wins:number;delta:number;base:number;score:number;tier:string;rank:number|null;start_rank:number|null;rank_change:number|null;place:number};
export type HallMode='weekly'|'total';

/** Use published competition ranks, including ties; provisional players remain score-ordered. */
export function hallRanking(rows:HallRow[],mode:HallMode){
 return [...rows].sort(mode==='weekly'?(a,b)=>a.place-b.place:(a,b)=>
  Number(a.rank===null)-Number(b.rank===null)||b.score-a.score||a.id.localeCompare(b.id));
}
export const hallPlace=(row:HallRow,mode:HallMode)=>mode==='total'?row.rank:row.place;
