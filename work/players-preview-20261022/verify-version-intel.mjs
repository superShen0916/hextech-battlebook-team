import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(fs.readFileSync('lib/version-intel.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {rankRows,selectPairs,rankEquipment,rankTencentAugments}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
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
const options=[{items:['1'],pick_rate:.7,win_rate:.4},{items:['2'],pick_rate:.2,win_rate:.6}];
assert.equal(rankEquipment(options,'win_rate')[0].items[0],'2');
assert.equal(rankEquipment(options,'pick_rate')[0].items[0],'1');
assert.equal(options[0].items[0],'1');
const equipmentFile='public/api/version-intel/tencent-equipment.json';
let equipmentHeroes=0;
if(fs.existsSync(equipmentFile)){
 const equipment=JSON.parse(fs.readFileSync(equipmentFile,'utf8'));
 assert.equal(equipment.mode,'KIWI');assert.equal(equipment.queue_id,2400);
 assert.equal(equipment.patch,null);assert.equal(equipment.sample_size,null);assert.equal(equipment.sample_scope,'undisclosed');
 assert.match(equipment.snapshot_id,/^[a-f0-9]{64}$/);
 for(const hero of equipment.heroes){
  equipmentHeroes++;if(hero.available)assert.match(hero.stats_date,/^\d{4}-\d{2}-\d{2}$/);
  for(const group of ['items','core','boots','starting','full'])for(const row of hero[group]){
   assert.ok(row.pick_rate>=0&&row.pick_rate<=1&&row.win_rate>=0&&row.win_rate<=1);
   for(const item of row.items){assert.ok(equipment.items[item]);if(equipment.items[item].icon_url)assert.ok(fs.existsSync('public'+equipment.items[item].icon_url));}
  }
 }
}
const referenceFile='public/api/version-intel/tencent-augments.json';let tencentPairs=0;
if(fs.existsSync(referenceFile)){
 const reference=JSON.parse(fs.readFileSync(referenceFile,'utf8'));
 assert.equal(reference.win_rate,null);assert.equal(reference.sample_size,null);assert.equal(reference.mode,'KIWI');
 for(const hero of reference.heroes)for(const row of hero.augments){
  tencentPairs++;assert.ok(row.pick_rate>=0&&row.pick_rate<=1);assert.ok(['S','A','B','C'].includes(row.tier));assert.ok(['S','A','B','C'].includes(row.rarity_tier));
  assert.ok(['silver','gold','prismatic'].includes(row.rarity));assert.ok(reference.dictionary[row.id]);
  assert.equal('win_rate' in row,false);assert.equal('games' in row,false);
  const icon=reference.dictionary[row.id].icon_url;if(icon)assert.ok(fs.existsSync('public'+icon));
 }
}
const grades=[{id:'a',source_rank:1,tier:'S',rarity_tier:'B',rarity_rank:2,pick_rate:.1},{id:'b',source_rank:2,tier:'A',rarity_tier:'S',rarity_rank:1,pick_rate:.3}];
assert.equal(rankTencentAugments(grades,'tier')[0].id,'a');assert.equal(rankTencentAugments(grades,'tier',true)[0].id,'b');assert.equal(rankTencentAugments(grades,'pick_rate')[0].id,'b');assert.equal(grades[0].id,'a');
console.log(JSON.stringify({ok:true,patches:index.datasets.map(d=>d.patch),verifiedPairs:pairs,equipmentHeroes,tencentPairs,checks:['weighted-global-rates','no-PBE-contamination','hero-denominators','snapshot-consistency','small-sample-ranking','equipment-source-rates-and-unknown-scope','Tencent-tiers-are-not-win-rates','rarity-specific-tiers-kept-separate']}));
