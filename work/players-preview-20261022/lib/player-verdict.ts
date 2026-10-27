import { ROLE_LABEL, roleProfile, type Role } from "./champion-roles";
import { CHAMPION_CN } from "./champion-names";

type NumberValue = number | null | undefined;
type Summary = { games?: NumberValue; win_rate?: NumberValue; kda?: NumberValue; dpm?: NumberValue; taken?: NumberValue; heal?: NumberValue; damage_share?: NumberValue; kill_participation?: NumberValue };
type Awards = { games?: NumberValue; mvp?: NumberValue; ace?: NumberValue };
export type Verdict = { text: string; punch: string; pro: { pro: string; tag: string; text: string } };
type Seed = { punch?: string; pro?: { pro?: string; tag?: string } };
type Champion = { champion_name?: string; games?: number | null };

const numeric = (value: NumberValue): value is number => typeof value === "number" && Number.isFinite(value);
const n = (value: number, digits = 0) => value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
const num = (value: NumberValue) => (numeric(value) ? value : 0);

/** 打法参照：选手与风格的对应。人选综合英雄池定位与数据画像得出。 */
const CURATED_PRO: Record<string, { pro: string; tag: string }> = {
  间客丿: { pro: "Faker", tag: "全能常青" },
  gopher: { pro: "Doinb", tag: "功能型核心" },
  好人还遇好人救: { pro: "Meiko", tag: "保护型辅助" },
  碰不到你的灵魂: { pro: "Rookie", tag: "全能补位" },
  LliMaozi: { pro: "Uzi", tag: "极致输出" },
  十一月的萧邦: { pro: "Chovy", tag: "稳定输出" },
  柿子蒸螃蟹: { pro: "TheShy", tag: "上单花活" },
  我要写cpp: { pro: "Ming", tag: "开团辅助" },
  雨下喝酒: { pro: "369", tag: "前排模板" },
  小无敌520: { pro: "Knight", tag: "刺客本能" },
  淹死的鱼oO丶: { pro: "Xiaohu", tag: "万金油" },
  上路的老爹: { pro: "Zeus", tag: "全能上单" },
  破碎浮云帝: { pro: "ShowMaker", tag: "远程法师" },
  快给我看看: { pro: "Keria", tag: "多面手" },
  我和我的三个儿: { pro: "Rookie", tag: "全能补位" },
  LookOutTheBush: { pro: "Kanavi", tag: "野区怪物" },
  VivaLaVida01: { pro: "Keria", tag: "多面手" },
};

/** 每位选手的一句话风格，用来把数据和人选对上。 */
const PRO_STYLE: Record<string, string> = {
  Uzi: "以 AD 核心的极致输出著称",
  Ruler: "沉得住气、把伤害稳定交出来的 AD",
  JackeyLove: "自己找机会的激进派输出",
  Deft: "愿意为队伍把脏活接下的老将 AD",
  Chovy: "每一刀都算过的稳健派",
  ShowMaker: "站在两个屏幕外要人命的远程法师",
  Rookie: "不挑英雄、哪缺补哪的全能中单",
  Doinb: "输出和承伤一手抓的功能型核心",
  Knight: "切后排不需要理由的刺客手感",
  Tarzan: "抓机会下手极快的野区猎手",
  TheShy: "把射手和花活带上路的那个性子",
  Zeus: "上路的稳定与全能",
  Bin: "敢一打多的上路对拼",
  "369": "顶在最前面还带输出的前排",
  Meiko: "把保护和开团都揽下来的辅助",
  Ming: "钩子一出手就是开团信号的辅助",
  Keria: "什么位置都能上的多面手",
  Xiaohu: "哪都能打、局面从不缺他",
  Kanavi: "能吃不亏、打完还能站着的野区打法",
  Faker: "什么位置都拿得起、常年一线的全能",
};

const styleOf = (pro: string) => PRO_STYLE[pro] || "风格鲜明的一线选手";

/** 主定位 + 数据画像 → 选手联想。 */
function pickPro(role: Role | undefined, mixed: boolean, s: Summary): { pro: string; tag: string } {
  const share = num(s.damage_share), dpm = num(s.dpm), kda = num(s.kda),
    taken = num(s.taken), heal = num(s.heal), join = num(s.kill_participation);
  if (!mixed && role === "marksman") {
    if (share >= 0.23 || dpm >= 2800) return { pro: "Uzi", tag: "极致输出" };
    if (kda >= 3.8) return { pro: "Ruler", tag: "沉着 AD" };
    if (join >= 0.7) return { pro: "JackeyLove", tag: "激进输出" };
    return { pro: "Deft", tag: "团队老将" };
  }
  if (!mixed && role === "mage") {
    if (taken >= 55000) return { pro: "Doinb", tag: "功能型核心" };
    if (kda >= 3.8) return { pro: "Chovy", tag: "稳定输出" };
    if (share >= 0.21 || dpm >= 2600) return { pro: "ShowMaker", tag: "远程法师" };
    return { pro: "Rookie", tag: "全能补位" };
  }
  if (!mixed && role === "assassin") {
    if (kda >= 3.5) return { pro: "Knight", tag: "刺客本能" };
    if (join >= 0.68) return { pro: "Tarzan", tag: "野区猎手" };
    return { pro: "Knight", tag: "刺客本能" };
  }
  if (!mixed && role === "fighter") {
    if (taken >= 55000) return { pro: "369", tag: "前排模板" };
    if (dpm >= 2500) return { pro: "TheShy", tag: "上单花活" };
    if (kda >= 3.6) return { pro: "Zeus", tag: "全能上单" };
    return { pro: "Bin", tag: "上路硬拼" };
  }
  if (!mixed && role === "tank") {
    if (heal >= 500) return { pro: "Keria", tag: "多面手" };
    return { pro: "369", tag: "前排模板" };
  }
  if (!mixed && role === "support") {
    if (heal >= 600) return { pro: "Meiko", tag: "保护型辅助" };
    if (join >= 0.68) return { pro: "Ming", tag: "开团辅助" };
    return { pro: "Keria", tag: "多面手" };
  }
  if (heal >= 600) return { pro: "Keria", tag: "多面手" };
  if (taken >= 55000) return { pro: "369", tag: "前排模板" };
  if (share >= 0.23 || dpm >= 2800) return { pro: "Uzi", tag: "极致输出" };
  if (kda >= 3.8) return { pro: "Chovy", tag: "稳定输出" };
  if (join >= 0.68) return { pro: "Ming", tag: "开团辅助" };
  return { pro: "Faker", tag: "全能常青" };
}

/** 打法参照的依据：先说英雄池定位占比，再说支撑这个联想的数字。 */
function proText(pro: string, tag: string, s: Summary, top: { role: Role; share: number } | undefined, mixed: boolean, pool: string): string {
  const share = num(s.damage_share), dpm = num(s.dpm), kda = num(s.kda),
    taken = num(s.taken), heal = num(s.heal), join = num(s.kill_participation);
  const facts: string[] = [];
  if (numeric(s.damage_share)) facts.push(`团队伤害占比 ${n(share * 100, 1)}%`);
  if (numeric(s.dpm)) facts.push(`每分钟 ${n(dpm)} 伤害`);
  if (numeric(s.kda)) facts.push(`KDA ${n(kda, 2)}`);
  if (numeric(s.taken) && taken >= 40000) facts.push(`场均承伤 ${n(taken / 10000, 1)} 万`);
  if (numeric(s.heal) && heal >= 300) facts.push(`场均治疗 ${n(heal)}`);
  if (numeric(s.kill_participation)) facts.push(`参团率 ${n(join * 100, 1)}%`);
  const evidence = facts.slice(0, 3).join("、");
  const rolePart = !mixed && top
    ? `英雄池里${ROLE_LABEL[top.role]}占 ${n(top.share * 100)}%`
    : "英雄池铺得开、没有单一主定位";
  return `${pool}${rolePart}，${evidence}——和 ${pro} 那种「${styleOf(pro)}」的路子对得上。`;
}

/** Keep the reference site's personality; rebuild every numeric claim from this view. */
export function playerVerdict(
  name: string,
  summary: Summary,
  awards: Awards = {},
  heroes: string[] = [],
  champions: Champion[] = [],
  seed?: Seed,
): Verdict | null {
  if (!numeric(summary.games) || summary.games < 1) return null;
  const profile = roleProfile(champions);
  const base = CURATED_PRO[name] || pickPro(profile.top?.role, profile.mixed, summary);
  const lead = seed?.punch ? "" : `每场都交出自己的那份贡献。`;
  const sentences = [
    lead,
    `${n(summary.games)} 场有效样本${numeric(summary.win_rate) ? `，${n(summary.win_rate * 100, 1)}% 胜率` : ""}。`,
  ].filter(Boolean);
  const output = [
    numeric(summary.dpm) ? `每分钟 ${n(summary.dpm)} 伤害` : "",
    numeric(summary.damage_share) ? `团队伤害占比 ${n(summary.damage_share * 100, 1)}%` : "",
    numeric(summary.taken) ? `场均承伤 ${n(summary.taken / 10000, 1)} 万` : "",
  ].filter(Boolean);
  if (output.length) sentences.push(output.join("、") + "。");
  if (numeric(awards.games) && awards.games > 0)
    sentences.push(
      [numeric(awards.mvp) ? `${n(awards.mvp)} 次自评 MVP` : "", numeric(awards.ace) ? `${n(awards.ace)} 次败方 ACE` : ""]
        .filter(Boolean)
        .join("、") + "，亮点留在每一张战报里。",
    );
  const pro = seed?.pro?.pro || base.pro;
  const tag = seed?.pro?.tag || base.tag;
  const poolNames = heroes.map((h) => CHAMPION_CN[h] || h).filter(Boolean);
  const pool = poolNames.length ? `常用 ${poolNames.slice(0, 3).join("、")}；` : "";
  return {
    text: sentences.join(""),
    punch: seed?.punch || "精彩不只在最后一次击杀里。",
    pro: { pro, tag, text: proText(pro, tag, summary, profile.top, profile.mixed, pool) },
  };
}
