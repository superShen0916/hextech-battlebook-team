import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const payload=fs.readFileSync('../../work/build/snapshot.full.json'),d=JSON.parse(payload),index=JSON.parse(fs.readFileSync('public/matches/index.json','utf8'));
assert.equal(index.build_id,d.build_id);
const profiles=[...d.players,...d.companions.filter(c=>!d.players.some(p=>p.name===c.name)).map(c=>({...c,id:'shared-'+c.id}))];
const details=new Map();let views=0;
for(const p of profiles)for(const m of p.recent){const ref=index.profiles[p.id][m.id];assert.ok(ref,p.id+': missing view');assert.match(ref.file,/^m-[0-9a-f]{20}$/);let detail=details.get(ref.file);if(!detail){detail=JSON.parse(fs.readFileSync('public/matches/'+ref.file+'.json','utf8'));details.set(ref.file,detail);}assert.equal(detail.started_ms,m.started_ms);assert.equal(detail.duration,m.duration);assert.equal(detail.id,ref.file);const player=detail.players.find(x=>x.slot===ref.slot);for(const field of ['champion_id','kills','deaths','assists','win'])assert.equal(player[field]??null,m.player[field]??null,p.id+': '+field);if(m.id.startsWith('m-'))assert.equal(ref.file,m.id);const expected=m.player.performance,actual=player.performance;if(expected){assert.ok(actual);for(const k of ['award','team_rank','tied'])assert.equal(actual[k],expected[k]??(k==='tied'?false:null));assert.ok(Math.abs(actual.score-expected.score)<0.00001);}else assert.equal(actual,null);views++;}
const allowed=new Set(['slot','team','name','profile_id','champion_id','win','kills','deaths','assists','damage','taken','heal','shield','gold','penta_kills','damage_share','items','augment_slots','performance']);
for(const detail of details.values()){assert.equal(detail.players.length,10);assert.equal(new Set(detail.players.map(p=>p.slot)).size,10);const teams=Map.groupBy(detail.players,p=>p.team);assert.equal(teams.size,2);for(const team of teams.values()){assert.equal(team.length,5);assert.ok(team.every(p=>p.win===team[0].win));const shares=team.map(p=>p.damage_share);if(shares.every(x=>x!==null))assert.ok(Math.abs(shares.reduce((a,b)=>a+b,0)-1)<1e-8);}if(detail.performance.available){for(const team of teams.values()){const winners=team.filter(p=>p.performance.award);assert.ok(winners.length>0);assert.ok(winners.every(p=>p.performance.team_rank===1&&p.performance.award===(p.win?'MVP':'ACE')));}}else assert.ok(detail.players.every(p=>p.performance===null));for(const p of detail.players){if(p.performance)assert.deepEqual(Object.keys(p.performance).sort(),['version','score','award','team_rank','tied'].sort());assert.ok(Object.keys(p).every(k=>allowed.has(k)));assert.equal(p.items.length,7);assert.equal(p.augment_slots.length,6);if(p.profile_id)assert.ok(profiles.some(x=>x.id===p.profile_id));}}
assert.equal(details.size,index.coverage.matches);assert.equal(views,index.coverage.player_views);assert.equal(index.coverage.unmatched_views,0);
console.log(`PASS: ${views} complete perspective mappings, ${details.size} ten-player matches, source identity/score consistency and whitelist only.`);
const bundlePath='../../work/build/cache/details.bundle.json';
if(fs.existsSync(bundlePath)){
 const bundle=JSON.parse(fs.readFileSync(bundlePath,'utf8'));
 assert.equal(bundle.build_id,d.build_id,'private detail bundle must belong to this complete snapshot');
 assert.equal(Object.keys(bundle.details).length,details.size);
 for(const [id,detail] of details)assert.deepEqual(bundle.details[id],detail,'private bundle differs from published ten-player file: '+id);
 console.log('PASS: LP/recap I/O bundle equals every real ten-player file; no skipped detail checks.');
}
