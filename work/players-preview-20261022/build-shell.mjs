// Build the small frontend shell in memory, then atomically refresh its files.
// Public data is mirrored by Python; Vite never empties a 10,000-file directory.
import fs from 'node:fs';
import path from 'node:path';
import {build} from 'vite';
const front=process.cwd(),root=path.resolve(front,'../..');
const target=path.resolve(process.argv[2]||'');
if(target!==path.join(root,'work/build/candidate'))throw Error('unsafe shell output directory');
const result=await build({build:{outDir:target,write:false,copyPublicDir:false,emptyOutDir:false}});
const names=[];
for(const bundle of Array.isArray(result)?result:[result])for(const output of bundle.output){
 const name=output.fileName,dest=path.resolve(target,name);
 if(!dest.startsWith(target+path.sep))throw Error('unsafe shell filename');
 const content=Buffer.from(output.type==='chunk'?output.code:output.source);
 fs.mkdirSync(path.dirname(dest),{recursive:true});
 if(!fs.existsSync(dest)||!fs.readFileSync(dest).equals(content)){
  const temporary=dest+'.shell-tmp';
  fs.writeFileSync(temporary,content);fs.renameSync(temporary,dest);
 }
 names.push(name);
}
fs.writeFileSync(path.join(root,'work/build/frontend-outputs.json'),JSON.stringify(names));
console.log('SHELL_READY '+JSON.stringify(names));
