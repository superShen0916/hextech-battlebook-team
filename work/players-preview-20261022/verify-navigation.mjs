import fs from 'node:fs';
import ts from 'typescript';
import assert from 'node:assert/strict';
const js=ts.transpileModule(fs.readFileSync('lib/section-navigation.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {activeSectionAt}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
assert.equal(activeSectionAt([{id:'players',top:-3000},{id:'together',top:32},{id:'achievements',top:1500}]),'together');
assert.equal(activeSectionAt([{id:'players',top:-3000},{id:'together',top:-1400},{id:'achievements',top:32}]),'achievements');
assert.equal(activeSectionAt([{id:'players',top:300},{id:'together',top:3000}]),'players');
console.log('PASS: shared navigation section geometry at the explicit 32px scroll destination.');
