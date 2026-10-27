import type {Profile,Match,Dictionaries} from '../src/App';
import {buildPairStory,type PairStory} from './pair-story';
export type Category='journey'|'heroes'|'moments'|'duo';
export type Achievement={id:string;name:string;subtitle:string;category:Category;symbol:string;thresholds:number[];unit:string;rule:string};
export const categories:Record<Category,string>={journey:'出勤积累',heroes:'英雄收藏',moments:'单局高光',duo:'搭档默契'};
export const achievements:Achievement[]=[
 {id:'games',name:'大乱斗常驻人口',subtitle:'最后一把？你上把也是这么说的',category:'journey',symbol:'Ⅰ',thresholds:[100,500,1000],unit:'场',rule:'累计已收录的有效对局。'},
 {id:'wins',name:'这把分我先上',subtitle:'赢一把，今晚的嘴又硬了一点',category:'journey',symbol:'W',thresholds:[50,200,500],unit:'胜',rule:'累计已收录有效对局的胜场。'},
 {id:'mvp',name:'这把真是我 C',subtitle:'别急着下一把，先看右上角',category:'journey',symbol:'✦',thresholds:[10,50,100],unit:'次',rule:'累计自评 MVP 次数，只计可评有效对局。'},
 {id:'ace',name:'尽力局局长',subtitle:'水晶可以炸，战绩得拿得出手',category:'journey',symbol:'◇',thresholds:[10,50,100],unit:'次',rule:'累计自评败方 ACE 次数，只计可评有效对局。'},
 {id:'heroes',name:'英雄池还是海',subtitle:'骰到谁算谁，拿谁都能整两手',category:'heroes',symbol:'⬡',thresholds:[10,30,60],unit:'位',rule:'至少打过一场有效局的不同英雄数。'},
 {id:'signature',name:'这英雄有身份证',subtitle:'又是他？这熟练度藏都藏不住',category:'heroes',symbol:'♜',thresholds:[20,50,100],unit:'场',rule:'同一个英雄的已收录有效场次最高值。'},
 {id:'penta',name:'五杀，截图！',subtitle:'先别推，等我截个图',category:'moments',symbol:'Ⅴ',thresholds:[1,5,20],unit:'次',rule:'累计有效局中已记录的五杀次数，同一局可记录多次。'},
 {id:'damage',name:'伤害面板有话说',subtitle:'不多解释，打开伤害看一眼',category:'moments',symbol:'↗',thresholds:[100000,200000,300000],unit:'伤害',rule:'单场有效局对英雄伤害最高值。'},
 {id:'assists',name:'人头你拿，助攻归我',subtitle:'你负责帅，我负责让你帅',category:'moments',symbol:'＋',thresholds:[30,50,70],unit:'助攻',rule:'单场有效局助攻最高值。'},
 {id:'taken',name:'对面技能我全吃',subtitle:'人可以倒，技能得先帮兄弟骗完',category:'moments',symbol:'▱',thresholds:[100000,200000,300000],unit:'承伤',rule:'单场有效局承受伤害最高值。'},
 {id:'duo-games',name:'怎么又是你',subtitle:'一看开黑记录，好家伙，全是你',category:'duo',symbol:'∞',thresholds:[20,100,500],unit:'场同队',rule:'两人已收录的有效同队场次，同队不代表预先组队。'},
 {id:'duo-wins',name:'咱俩有点说法',subtitle:'这波配合，建议加入保留节目',category:'duo',symbol:'Ⅱ',thresholds:[10,50,200],unit:'场同队胜利',rule:'两人已收录的有效同队胜场。'},
 {id:'duo-streak',name:'赢了就不许散',subtitle:'谁说最后一把？连胜不能断',category:'duo',symbol:'≋',thresholds:[3,5,8],unit:'连胜',rule:'按已收录有效同队对局的时间顺序计算最长连胜；关联不完整时不推算。不代表未收录对局中也连续获胜。'},
 {id:'carry-streak',name:'把把 C',subtitle:'一把 C 是手感，把把 C 是节目',category:'journey',symbol:'C',thresholds:[2,3,5],unit:'连场 MVP',rule:'已收录有效局按时间排序，连续获得自评 MVP 的最长场数；缺评分会中断，不把 ACE 计成 MVP。只描述已收录样本，不代表未收录对局也连续获奖。'},
 {id:'loss-streak',name:'下把一定',subtitle:'再开一把，这次真能赢',category:'journey',symbol:'↻',thresholds:[3,5,8],unit:'连败',rule:'已收录有效局按时间排序的最长连续失利场数；缺胜负会中断，只描述已收录样本。'},
 {id:'healing',name:'兄弟别急，我有奶',subtitle:'人头先放一放，先把兄弟血条抬满',category:'moments',symbol:'♥',thresholds:[10000,30000,60000],unit:'队友治疗',rule:'单场有效局对队友治疗量最高值；不包含自我治疗，不把队友护盾混入治疗。'}
];
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
export type AchievementProgress={definition:Achievement;value:number|null;tier:number;next:number|null;witness?:Match;detail?:string};
export function progressFor(definition:Achievement,value:number|null,witness?:Match,detail?:string):AchievementProgress{
 const tier=value===null?0:definition.thresholds.filter(t=>value>=t).length;
 return {definition,value,tier,next:definition.thresholds[tier]??null,witness,detail};
}
export function personalAchievements(p:Profile):AchievementProgress[]{
 const rows=(p.recent||[]).filter(m=>m.stats_eligible),summary=p.summary||{};
 const best=(key:'damage'|'assists'|'taken'|'heal')=>rows.filter(m=>finite(m.player[key])).sort((a,b)=>(b.player[key]||0)-(a.player[key]||0))[0];
 const streak=(carry:boolean)=>{let run=0,maximum=0,known=0,witness:Match|undefined;if(rows.some(m=>!finite(m.started_ms)))return {value:null,witness};for(const m of [...rows].sort((a,b)=>(a.started_ms||0)-(b.started_ms||0))){const available=carry?finite(m.player.performance?.score):typeof m.player.win==='boolean';if(available)known++;run=available&&(carry?m.player.performance?.award==='MVP':m.player.win===false)?run+1:0;if(run>maximum){maximum=run;witness=m;}}return {value:known?maximum:null,witness};};
 const champion=[...(p.champions||[])].filter(h=>finite(h.games)&&h.games>0).sort((a,b)=>(b.games||0)-(a.games||0))[0];
 return achievements.filter(d=>d.category!=='duo').map(d=>{
  if(d.id==='carry-streak'||d.id==='loss-streak'){const result=streak(d.id==='carry-streak');return progressFor(d,result.value,result.witness);}
  if(d.id==='healing'){const m=best('heal');return progressFor(d,m?.player.heal??null,m);}
  if(['damage','assists','taken'].includes(d.id)){const key=d.id as 'damage'|'assists'|'taken',m=best(key);return progressFor(d,m?.player[key]??null,m);}
  const values:Record<string,number|null>={games:summary.games??null,wins:summary.wins??null,mvp:p.awards?.mvp??null,ace:p.awards?.ace??null,heroes:p.champions?.filter(h=>finite(h.games)&&h.games>0).length??null,signature:champion?.games??null,penta:summary.penta_kills??null};
  const witness=d.id==='penta'?rows.find(m=>(m.player.penta_kills||0)>0):undefined;
  return progressFor(d,values[d.id]??null,witness,d.id==='signature'?champion?.champion_name:undefined);
 });
}
export function duoAchievements(s:PairStory):AchievementProgress[]{return achievements.filter(d=>d.category==='duo').map(d=>progressFor(d,d.id==='duo-games'?s.games:d.id==='duo-wins'?s.wins:s.longest));}
export type AchievementHolder={key:string;players:Profile[];progress:AchievementProgress;source?:Profile};
export function achievementHolders(profiles:Profile[],dictionary:Dictionaries){
 const result:AchievementHolder[]=[];
 for(const p of profiles)for(const progress of personalAchievements(p))result.push({key:p.id,players:[p],progress,source:p});
 for(let i=0;i<profiles.length;i++)for(let j=i+1;j<profiles.length;j++){
  const a=profiles[i],b=profiles[j];if(!a.teammates?.some(t=>t.name===b.name)&&!b.teammates?.some(t=>t.name===a.name))continue;
  const s=buildPairStory(a,b,dictionary);if(!s.row)continue;
  for(const progress of duoAchievements(s))result.push({key:[a.id,b.id].sort().join('::'),players:[a,b],progress,source:s.source});
 }
 return result;
}
