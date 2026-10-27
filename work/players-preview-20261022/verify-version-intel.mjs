import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(fs.readFileSync('lib/version-intel.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {rankRows,selectPairs}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
assert.equal(rankRows([{id:'tiny',games:1,wins:1,win_rate:1},{id:'observed',games:100,wins:60,win_rate:.6}],'confidence')[0].id,'observed');
assert.equal(selectPairs([{id:'a',games:100,wins:50,win_rate:.5,source:'pbe'},{id:'b',games:100,wins:50,win_rate:.5,source:'live'}],false,0).length,1);
const read=file=>JSON.parse(fs.readFileSync('public/api/version-intel/'+file,'utf8'));
const index=read('index.json');let pairs=0;
for(const entry of index.datasets){
 const overview=read(entry.patch+'/overview.json'),totals=new Map();
 assert.equal(overview.heroes.reduce((sum,h)=>sum+h.games,0),overview.matches.valid*10);
 assert.equal(overview.heroes.reduce((sum,h)=>sum+h.wins,0),overview.matches.valid*5);
 for(const hero of overview.heroes){
  const detail=read(entry.patch+'/heroes/'+hero.id+'.json');
  assert.equal(detail.patch,entry.patch);assert.equal(detail.hero_id,hero.id);assert.equal(detail.snapshot_at,overview.snapshot_at);
  for(const pair of detail.pairs){
   pairs++;assert.ok(pair.wins<=pair.games);assert.equal(pair.win_rate,pair.wins/pair.games);
   if(pair.source==='pbe'){assert.ok(pair.id in overview.provisional_augments);continue;}
   assert.ok(!(pair.id in overview.provisional_augments));
   const sum=totals.get(pair.id)||{games:0,wins:0,heroes:0};sum.games+=pair.games;sum.wins+=pair.wins;sum.heroes++;totals.set(pair.id,sum);
  }
 }
 assert.equal(overview.augments.length,totals.size);
 for(const row of overview.augments){
  assert.ok(!(row.id in overview.provisional_augments));const total=totals.get(row.id);
  assert.equal(row.games,total.games);assert.equal(row.wins,total.wins);assert.equal(row.heroes,total.heroes);assert.equal(row.win_rate,row.wins/row.games);
 }
}
console.log(JSON.stringify({ok:true,patches:index.datasets.map(d=>d.patch),verifiedPairs:pairs,checks:['weighted-global-rates','no-PBE-contamination','hero-denominators','snapshot-consistency','small-sample-ranking']}));
