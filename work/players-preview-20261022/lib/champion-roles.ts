/** 海克斯大乱斗：英雄 → 定位。用于从英雄池推断打法参照，未知英雄不参与占比。 */
export type Role = "marksman" | "mage" | "assassin" | "fighter" | "tank" | "support";

export const ROLE_LABEL: Record<Role, string> = {
  marksman: "射手",
  mage: "法师",
  assassin: "刺客",
  fighter: "战士",
  tank: "坦克",
  support: "辅助",
};

export const CHAMPION_ROLES: Record<string, Role> = {
  Ryze: "mage", Malzahar: "mage", Syndra: "mage", Yone: "fighter", MissFortune: "marksman",
  Graves: "marksman", Kayn: "assassin", Tristana: "marksman", Lucian: "marksman", Jax: "fighter",
  Yasuo: "fighter", Caitlyn: "marksman", Darius: "fighter", Brand: "mage", TahmKench: "tank",
  Lillia: "mage", Morgana: "mage", Tryndamere: "fighter", Aatrox: "fighter", Mordekaiser: "fighter",
  Ekko: "assassin", Twitch: "marksman", Jayce: "fighter", Galio: "tank", Corki: "marksman",
  Swain: "mage", Vayne: "marksman", JarvanIV: "tank", DrMundo: "tank", XinZhao: "fighter",
  TwistedFate: "mage", MasterYi: "assassin", AurelionSol: "mage", Hecarim: "fighter", Maokai: "tank",
  Nocturne: "assassin", Lux: "mage", Karthus: "mage", Ezreal: "marksman", Kassadin: "assassin",
  Varus: "marksman", Thresh: "support", Malphite: "tank", Diana: "assassin", Teemo: "marksman",
  Jhin: "marksman", Trundle: "fighter", Nasus: "fighter", Sett: "fighter", Sion: "tank",
  Garen: "fighter", Quinn: "marksman", Smolder: "marksman", Samira: "marksman", Xayah: "marksman",
  Kayle: "fighter", Heimerdinger: "mage", Zed: "assassin", Ziggs: "mage", Volibear: "fighter",
  Gangplank: "fighter", MonkeyKing: "fighter", Talon: "assassin", Kindred: "marksman", Kaisa: "marksman",
  Fizz: "assassin", Ashe: "marksman", Mel: "mage", Blitzcrank: "tank", Xerath: "mage",
  Sylas: "assassin", Sejuani: "tank", Udyr: "fighter", Ornn: "tank", Shaco: "assassin",
  Shen: "tank", Senna: "marksman", Nidalee: "assassin", Zyra: "mage", Chogath: "tank",
  Briar: "fighter", Pyke: "assassin", Zeri: "marksman", Veigar: "mage", Alistar: "tank",
  Zilean: "support", Katarina: "assassin", Draven: "marksman", Singed: "tank", Ahri: "mage",
  Qiyana: "assassin", Skarner: "fighter", Seraphine: "support", Zoe: "mage", Leona: "support",
  Velkoz: "mage", Gnar: "fighter", Hwei: "mage", Urgot: "fighter", Jinx: "marksman",
  Ambessa: "fighter", Kled: "fighter", Rumble: "fighter", LeeSin: "assassin", FiddleSticks: "mage",
  Olaf: "fighter", Amumu: "tank", Azir: "mage", Illaoi: "fighter", Aurora: "mage",
  Poppy: "tank", Sivir: "marksman", Akshan: "marksman", Renekton: "fighter", Gragas: "tank",
  Akali: "assassin", Taliyah: "mage", Viego: "assassin", Zac: "tank", Vi: "fighter",
  Orianna: "mage", Gwen: "fighter", Riven: "fighter", Kalista: "marksman", KogMaw: "marksman",
  Lulu: "support", Karma: "support", Pantheon: "fighter", Aphelios: "marksman", Viktor: "mage",
  Leblanc: "assassin", Nautilus: "tank", Khazix: "assassin", Fiora: "fighter", Neeko: "mage",
  Vladimir: "mage", Kennen: "mage", Cassiopeia: "mage", Vex: "mage", Rengar: "assassin",
  Rell: "tank", Belveth: "fighter", Braum: "support", RekSai: "fighter", Nami: "support",
  KSante: "tank", Shyvana: "fighter", Nilah: "fighter", Annie: "mage", Yorick: "fighter",
  Lissandra: "mage", Rammus: "tank", Anivia: "mage", Milio: "support", Janna: "support",
  Irelia: "fighter", Yuumi: "support", Sona: "support", Soraka: "support", Ivern: "support",
  Nunu: "tank", Elise: "assassin", Renata: "support", Camille: "fighter", Warwick: "fighter",
  Rakan: "support", Bard: "support", Taric: "support",
};

export type RoleStat = { role: Role; games: number; share: number };
export type RoleProfile = { total: number; stats: RoleStat[]; top?: RoleStat; mixed: boolean };

/** 按场次算各定位占比；未知英雄不计入分母。 */
export function roleProfile(champions: { champion_name?: string; games?: number | null }[] = []): RoleProfile {
  const counts = new Map<Role, number>();
  let total = 0;
  for (const c of champions) {
    const role = c?.champion_name ? CHAMPION_ROLES[c.champion_name] : undefined;
    if (!role) continue;
    const g = Number(c?.games) || 0;
    counts.set(role, (counts.get(role) || 0) + g);
    total += g;
  }
  const stats: RoleStat[] = [...counts.entries()]
    .map(([role, games]) => ({ role, games, share: total ? games / total : 0 }))
    .sort((a, b) => b.games - a.games);
  const top = stats[0];
  return { total, stats, top, mixed: !top || top.share < 0.35 };
}
