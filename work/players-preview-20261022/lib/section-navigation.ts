export function activeSectionAt(rows:{id:string;top:number}[],line=64){
 let active=rows[0]?.id||'';for(const row of rows)if(row.top<=line)active=row.id;return active;
}
