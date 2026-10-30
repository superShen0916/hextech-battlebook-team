import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(fs.readFileSync('lib/recaps.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const recapUrl='data:text/javascript;base64,'+Buffer.from(code).toString('base64');
const rankingSource=ts.transpileModule(fs.readFileSync('lib/hall-ranking.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {hallRanking,hallPlace}=await import('data:text/javascript;base64,'+Buffer.from(rankingSource).toString('base64'));
const board=[{id:'a',score:1200,tier:'stable',rank:3,place:1},{id:'b',score:1400,tier:'provisional',rank:1,place:2},{id:'c',score:1400,tier:'stable',rank:1,place:3},{id:'d',score:1800,tier:'unrated',rank:null,place:4}];
assert.deepEqual(hallRanking(board,'total').map(r=>r.id),['b','c','a','d']);
assert.deepEqual(hallRanking(board,'weekly').map(r=>r.id),['a','b','c','d']);
assert.deepEqual(hallRanking(board,'total').map(r=>hallPlace(r,'total')),[1,1,3,null]);
assert.deepEqual(board.map(r=>r.id),['a','b','c','d']);
console.log('PASS: independent weekly/total order, provisional score ordering, published tie ranks, unrated last, immutable input.');
const {commonGames,summarizeGames,loadRecap,clearRecapCache,recapCast,castPool}=await import(recapUrl);
const people=ids=>ids.map(profile_id=>({profile_id,kills:2,deaths:1,assists:3,damage:100,heal:0}));
const games=[{id:'one',started_ms:1,win:true,members:people(['a','b','c'])},{id:'two',started_ms:2,win:false,members:people(['a','b'])},{id:'three',started_ms:3,win:true,members:people(['c','d'])}];
assert.equal(commonGames(games,['a','b']).length,2);
assert.equal(commonGames(games,['a','c']).length,1);
assert.equal(commonGames(games,['a','d']).length,0);
assert.equal(commonGames(games,['a']).length,0);
assert.equal(commonGames(games,['a','b','c']).length,1);
const s=summarizeGames(commonGames(games,['a','b']),['a','b']);
assert.equal(s.games,2);assert.equal(s.wins,1);assert.equal(s.longest,1);assert.equal(s.people[0].kills,4);assert.equal(s.people[0].heal,0);
console.log('PASS: 2–5 player intersections, separate opponents, selected-sample totals, zero healing and streaks.');

const shareSource=ts.transpileModule(fs.readFileSync('lib/recap-share.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace("from './recaps'",`from '${recapUrl}'`);
const {readRecapShare,recapShareUrl,recapShareModel}=await import('data:text/javascript;base64,'+Buffer.from(shareSource).toString('base64'));
const known=['a','b','c','d','e'];
for(const selection of [
 {mode:'night',anchor:'a',night:'2026-10-22',fridays:false},
 {mode:'night',anchor:'a',night:'2026-10-23',fridays:true},
 {mode:'team',selected:['a','b'],period:'all'},
 {mode:'team',selected:known,period:'30'},
 {mode:'team',selected:['c','b','a'],period:'90'},
]){
 const url=new URL(recapShareUrl('https://hextech-battlebook.app.workbuddy.host/?player=a&name=A&sharecode=original',selection));
 assert.deepEqual(readRecapShare(url.search,known),{selection,error:''});
 assert.equal(url.hash,'#recaps');assert.equal(url.searchParams.get('sharecode'),'original');
 assert.equal(url.searchParams.has('player'),false);assert.equal(url.searchParams.has('name'),false);
}
assert.equal(new URL(recapShareUrl('https://hextech-battlebook.app.workbuddy.host/',{mode:'team',selected:['a','b'],period:'all'})).searchParams.get('sharecode'),'7ZFAIH5YHV');
for(const search of ['?recap=night&recap_player=a&recap_date=2026-02-30','?recap=team&recap_players=a,a','?recap=team&recap_players=a,unknown','?recap=team&recap_players=a,b&recap_period=1','?recap=wrong']){
 const result=readRecapShare(search,known);assert.equal(result.selection,null);assert.ok(result.error);
}
const shared=recapShareModel(commonGames(games,['a','b']),{mode:'team',selected:['a','b'],period:'all'},{a:'A',b:'B'});
assert.equal(shared.summary.games,2);assert.equal(shared.summary.wins,1);assert.equal(shared.subtitle,'A × B');
assert.equal(shared.members.length,2);assert.equal(shared.results[0].id,'one');assert.equal(shared.recent[0].id,'two');

const castGames=Array.from({length:5},(_,i)=>({id:'cast'+i,started_ms:i,win:i===0,members:[{profile_id:'a',performance:{score:75,award:i===0?'MVP':'ACE'}},{profile_id:'b',performance:{score:55}},{profile_id:'c',performance:{score:30}}]}));
const cast=recapCast(castGames,['a','b','c']);
assert.deepEqual(cast.roles.map(r=>r.title),['上等马','中等马','下等马 · 甲级战犯']);
assert.equal(cast.roles[0].ace,4);
assert.equal(recapCast(castGames.slice(0,2),['a','b','c']).roles.length,0);
assert.equal(recapCast(castGames.map(g=>({...g,win:true})),['a','b','c']).roles.at(-1).title,'稳住位');
assert.equal(recapCast(castGames.map(g=>({...g,win:true})),['a','b','c']).roles.at(-1).tier,'steady');
assert.equal(recapCast(castGames.map(g=>({...g,members:g.members.map(p=>({...p,performance:{score:60}}))})),['a','b','c']).roles.length,0);
assert.deepEqual(recapCast(castGames.map(g=>({...g,members:g.members.map(p=>({...p,performance:{score:p.profile_id==='c'?30:75}}))})),['a','b','c']).roles.map(r=>r.title),['上等马','上等马','下等马 · 甲级战犯']);
assert.deepEqual(castPool(castGames,['a']),['a','b','c']);
const mixed=[...castGames,{id:'solo',started_ms:99,win:false,members:[{profile_id:'a',performance:{score:0}},{profile_id:'d',performance:{score:100}}]}];
assert.deepEqual(castPool(mixed,['a']),['a','b','c']);
assert.equal(recapCast(mixed,castPool(mixed,['a'])).roles[0].games,6);
assert.equal(recapCast(mixed,castPool(mixed,['a'])).roles[0].average,62.5);
const extra=Array.from({length:6},(_,i)=>({id:'only'+i,started_ms:50+i,win:true,members:[{profile_id:'a',performance:{score:70}},{profile_id:'b',performance:{score:70}}]}));
const thin=recapCast([...castGames,...extra],['a','b','c']);
assert.equal(thin.roles.length,3);
assert.equal(thin.roles.filter(r=>r.thin).length,1);
assert.equal(thin.roles.at(-1).id,'c');
assert.equal(thin.roles.at(-1).title,'轮换位');
assert.equal(thin.roles.at(-1).tier,'thin');
assert.equal(recapCastShareSafe().cast.roles[0].title,'上等马');
function recapCastShareSafe(){return recapShareModel(castGames,{mode:'team',selected:['a','b','c'],period:'all'},{a:'A',b:'B',c:'C'});}
console.log('PASS: recap cast covers every team game of the scope, keeps own-sample averages, marks short samples as rotation instead of ranks, never roasts a winning crew, and uses the same model in the share image.');

const realFetch=globalThis.fetch;
try{
 globalThis.fetch=()=>new Promise(()=>{});
 await assert.rejects(loadRecap('/test/hung-fetch','one',{timeoutMs:15}),/超时/);
 globalThis.fetch=async()=>({ok:true,json:()=>new Promise(()=>{})});
 await assert.rejects(loadRecap('/test/hung-body','one',{timeoutMs:15}),/超时/);
 globalThis.fetch=async()=>({ok:false});
 await assert.rejects(loadRecap('/test/retry','one'),/暂时无法读取/);
 globalThis.fetch=async()=>({ok:true,json:async()=>({build_id:'wrong'})});
 await assert.rejects(loadRecap('/test/revision','one'),/战报正在更新/);
 globalThis.fetch=async()=>({ok:true,json:async()=>({build_id:'one',games:[]})});
 assert.equal((await loadRecap('/test/retry','one')).build_id,'one');
 let rejectOld;
 globalThis.fetch=()=>new Promise((_,reject)=>{rejectOld=reject;});
 const old=loadRecap('/test/force','one').catch(e=>e);
 await Promise.resolve();
 globalThis.fetch=async()=>({ok:true,json:async()=>({build_id:'one',fresh:true})});
 const fresh=await loadRecap('/test/force','one',{force:true});assert.equal(fresh.fresh,true);
 rejectOld(Error('old request failed late'));await old;
 globalThis.fetch=()=>{throw Error('healthy replacement cache was wrongly evicted');};
 assert.deepEqual(await loadRecap('/test/force','one'),fresh);
}finally{globalThis.fetch=realFetch;clearRecapCache();}
console.log('PASS: night/team share links restore exact filters, keep access code, reject invalid selections; card totals/order; timeout/body hang, failure retry and forced-cache races.');
