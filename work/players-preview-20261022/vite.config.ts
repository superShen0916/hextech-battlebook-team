import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
// The standalone share page reuses the same typed rules and verdicts as the React pages.
const shareLibrary={name:'local-share-library',buildStart(){
 for(const name of ['player-verdict','pair-story','achievements','share-style','champion-roles','champion-names']){
  const source=fs.readFileSync(path.resolve('lib',name+'.ts'),'utf8');
  const result=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"](\.\/[\w-]+)['"]/g,"from '$1.js'");
  fs.writeFileSync(path.resolve('public/share',name+'.js'),result);
 }
}};
// 静态托管不认无扩展名的 /api/snapshot（返回 403），构建时再出一份 .json 副本。
const snapshotJsonCopy={name:'snapshot-json-copy',writeBundle(options:any){
 const out=path.resolve(String(options.dir||'dist'),'api');
 const source=path.resolve('public/api/snapshot');
 if(!fs.existsSync(source))return;
 fs.mkdirSync(out,{recursive:true});
 fs.copyFileSync(source,path.join(out,'snapshot.json'));
}};
export default defineConfig({plugins:[react(),shareLibrary,snapshotJsonCopy],build:{outDir:'dist',emptyOutDir:true,rollupOptions:{input:{main:path.resolve('index.html'),intel:path.resolve('intel.html')}}}});
