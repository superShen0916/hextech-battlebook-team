import type {Profile,Dictionaries} from '../src/App';
import {playerVerdict} from './player-verdict';
export function shareStyle(p:Profile,dictionary:Dictionaries){
 const heroes=(p.champions||[]).slice(0,3).map(h=>dictionary.champions[String(h.champion_id)]?.name||h.champion_name||'英雄');
 const verdict=playerVerdict(p.name,p.summary||{},p.awards||{},heroes,p.champions||[],p.verdict);
 if(!verdict)return null;
 const s=p.summary||{},n=(v:number,d=0)=>v.toLocaleString('zh-CN',{maximumFractionDigits:d});
 const details=[typeof s.dpm==='number'?`每分钟 ${n(s.dpm)} 伤害`:'',typeof s.kill_participation==='number'?`参团率 ${n(s.kill_participation*100,1)}%`:'',typeof p.awards?.mvp==='number'?`${n(p.awards.mvp)} 次自评 MVP`:''].filter(Boolean);
 const punch=(s.taken||0)>=55000?'往前站的每一步，都在给队友创造空间。':(s.kill_participation||0)>=.7?'精彩不只在击杀里，也在每一次并肩里。':(s.dpm||0)>=3000?'把火力留给对手，把底气留给队友。':'把自己的那份贡献，认真留在每一张战报里。';
 return {tag:verdict.pro.tag,text:verdict.text,details,punch};
}
