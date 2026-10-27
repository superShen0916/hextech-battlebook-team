// Compute the complete hall once, rather than fetching 26 player archives.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import ts from 'typescript';
const dir=path.resolve('../../work/build/rules');fs.mkdirSync(dir,{recursive:true});
fs.mkdirSync('public/share',{recursive:true});
for(const name of ['player-verdict','pair-story','achievements','share-style','champion-roles','champion-names']){
 const source=fs.readFileSync(`lib/${name}.ts`,'utf8');
 const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"](.\/[\w-]+)['"]/g,"from '$1.js'");
 fs.writeFileSync('public/share/'+name+'.js',code);
}
for(const name of ['pair-story','achievements']){
 const source=fs.readFileSync(`lib/${name}.ts`,'utf8');
 const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from '(\.\/[\w-]+)'/g,"from '$1.mjs'");
 fs.writeFileSync(path.join(dir,name+'.mjs'),code);
}
const {achievementHolders}=await import('file:///'+path.join(dir,'achievements.mjs').replaceAll('\\','/'));
const data=JSON.parse(fs.readFileSync('../../work/build/snapshot.full.json','utf8'));
const profiles=data.players.map(p=>({...p,history_scope:'personal'}));
const brief=p=>({id:p.id,name:p.name,history_scope:p.history_scope});
const holders=achievementHolders(profiles,data.static).map(h=>({...h,players:h.players.map(brief),source:h.source?brief(h.source):undefined}));
const payload=JSON.stringify({build_id:data.build_id,holders});
const hash=crypto.createHash('sha256').update(payload).digest('hex').slice(0,16);
const file=`achievements.${hash}.json`;fs.mkdirSync('public/api/hall',{recursive:true});fs.writeFileSync('public/api/hall/'+file,payload);
for(const stale of fs.readdirSync('public/api/hall'))if(stale!==file)fs.unlinkSync('public/api/hall/'+stale);
data.achievements_url='/api/hall/'+file;fs.writeFileSync('../../work/build/snapshot.full.json',JSON.stringify(data));
console.log(JSON.stringify({holders:holders.length,bytes:Buffer.byteLength(payload)}));
