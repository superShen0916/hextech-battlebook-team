"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { playerVerdict } from "../lib/player-verdict";
import { track, trackSession, trackSubject } from "../lib/analytics";
import Lobby from "./Lobby";
import RatingRules,{RatingRulesContext,type RatingRuleData} from "./RatingRules";
import {loadProfile} from "../lib/profile-loader";
import MatchRoster from "./MatchRoster";
import PlayerRadar from "./PlayerRadar";
import {PersonalBadges} from "./Achievements";
import {Portrait,VisitorMenu,StarButton,ThemePicker,FormReview,HeroCards,themeFor,visualStyle,usePreferences,type Visuals} from "./experience";

type Value = number | null | undefined;
type DictionaryEntry = { name?: string; icon_url?: string; description?: string; rarity?: string };
export type Dictionaries = { champions: Record<string, DictionaryEntry>; augments: Record<string, DictionaryEntry>; items: Record<string, DictionaryEntry> };
type Summary = { games?: Value; wins?: Value; win_rate?: Value; kda?: Value; dpm?: Value; damage_share?: Value; kill_participation?: Value; taken?: Value; heal?: Value; triple_kills?: Value; quadra_kills?: Value; penta_kills?: Value; largest_killing_spree?: Value; samples?: Record<string, Value>; totals?: { kills?: Value; deaths?: Value; assists?: Value } };
type Holding = { id: number; uses?: Value; games?: Value; frequency?: Value };
type HoldingGroup = { games?: Value; observed_games?: Value; complete_games?: Value; missing_slot_games?: Value; top3?: Holding[] };
type Preferences = { games?: Value; augments?: HoldingGroup; items?: HoldingGroup };
export type Champion = Summary & { champion_id: number; champion_name?: string; preferences?: Preferences };
type Player = { champion_id?: number; champion_name?: string; win?: boolean; kills?: Value; deaths?: Value; assists?: Value; damage?: Value; damage_share?: Value; damage_rank?: Value; taken?: Value; heal?: Value; gold?: Value; items?: number[]; augment_slots?: (number | null)[]; double_kills?: Value; triple_kills?: Value; quadra_kills?: Value; penta_kills?: Value; performance?: { award?: string; score?: Value; team_rank?: Value; tied?: boolean } };
export type Match = { id: string; started_ms?: Value; patch?: string; duration?: Value; stats_eligible?: boolean; rating_delta?: Value; rating_mult?: Value; rating_penta_bonus?: Value; rating_volume_mult?: Value; rating_week_index?: Value; player: Player };
type Hextech = { games?: Value; complete_games?: Value; observed_games?: Value; augments?: { id: number; uses: number; frequency?: Value }[] };
type Highlights = { totals?: Record<string, Value>; samples?: Record<string, Value>; largest_killing_spree?: Value };
type Evaluations = { version?: string; games?: Value; missing_games?: Value; mvp?: Value; ace?: Value };
export type Rating = { status: "estimated" | "pending" | "not_queried" | "unavailable" | "unrated"; score: number | null; top_percent?: number | null; ci?: number | null; tier?: string | null; n?: number | null; carry?: number | null; avg_p?: number | null; queried_at?: string | null; matches_through?: string | null; source?: string; source_url?: string; version?: string; base?: Value; settled_delta?: number; settled_weeks?: {start_ms:number;end_ms:number;games:number;wins:number;delta:number;battle_night_games?:number;penta_games?:number;penta_part?:number}[]; calculation?: {confidence:number;avg_z:number|null;win_part:number;performance_part:number;raw_delta:number;cap:number|null;penta_games?:number;penta_part?:number;volume_average?:number;zero_win_rate?:number;effective_edge?:number;battle_night_games?:number;battle_night_wins?:number;battle_night_mult?:number;calibration:{mean:number;sigma:number}}; week?: { games?: Value; wins?: Value; win_rate?: Value; delta?: Value; prev_score?: Value; start_ms?: Value; end_ms?: Value } };
type View = { verdict?: { text?: string; punch?: string; pro?: { pro?: string; tag?: string; text?: string } }; rating?: Rating; preferences?: Preferences; summary?: Summary; champions?: Champion[]; hextech?: Hextech; highlights?: Highlights; awards?: Evaluations; recent?: Match[]; by_champion?: Record<string, View> };
type Companion = View & { match_ids?: string[]; reports?: Record<string, Report>; teammates?: Companion[]; id: string; name: string; shared_games?: Value; games?: Value; wins?: Value; win_rate?: Value };
type Leader = { name: string; champion_id?: number; champion_name?: string; games?: Value; shared_games?: Value; wins?: Value; win_rate?: Value; value?: Value; samples?: Value; rank?: Value; secondary?: { kda?: Value; damage_share?: Value; dpm?: Value; mvp?: Value; ace?: Value; award_samples?: Value; result_games?: Value } };
type Award = { id: string; title: string; metric_label?: string; leaders?: Leader[]; ties?: boolean };
type Report = { awards?: Award[]; minimum_award_games?: number; leaderboard?: Leader[] };
export type Profile = View & { history_scope?: "personal" | "shared"; source_id?: string; id: string; name: string; reports?: Record<string, Report>; teammates?: Companion[]; has_detail?: boolean; detail_url?: string; coverage: { saved: number; eligible: number; excluded: number; missing: number | null; available_listed?: Value; available_saved?: Value; time_range: { oldest_ms?: Value; newest_ms?: Value } } };
export type Snapshot = { rating_rules?:RatingRuleData; build_id?: string; achievements_url?: string; players?: Profile[]; default_player?: string; updated_at?: string; generated_at?: string; owner?: { name?: string }; personal?: View; companions?: Companion[]; reports?: Record<string, Report>; static?: Partial<Dictionaries>; overview?: { saved?: Value; eligible?: Value; wins?: Value; win_rate?: Value; companions?: Value; time_range?: { oldest_ms?: Value; newest_ms?: Value } } };

/** 静态托管会把无扩展名的 /api/snapshot 判成 403，所以优先取带 .json 的副本。 */
async function fetchSnapshot(): Promise<Response> {
  const candidates = ["/api/snapshot.json", "/api/snapshot"];
  let last: Response | undefined;
  for (const url of candidates) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.ok) return response;
      last = response;
    } catch { /* 试下一个候选 */ }
  }
  throw (last ?? Error("read_failed"));
}

function getProfiles(data?: Snapshot): Profile[] {
  const personal: Profile[] = (data?.players || []).map(p => ({...p,history_scope:"personal"}));
  const shared: Profile[] = (data?.companions || []).filter(c => !personal.some(p => p.name === c.name)).map(c => {
    const dates = (c.recent || []).map(m => m.started_ms).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    const saved = c.recent?.length || 0, eligible = c.summary?.games || 0;
    return {...c,id:`shared-${c.id}`,source_id:c.id,history_scope:"shared",coverage:{saved,eligible,excluded:Math.max(0,saved-eligible),missing:null,time_range:{oldest_ms:Math.min(...dates),newest_ms:Math.max(...dates)}}};
  });
  return [...personal,...shared].sort((a,b) => a.name.localeCompare(b.name,"zh-CN",{numeric:true,sensitivity:"base"}));
}

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const fmt = (value: Value, decimals = 0) => isNumber(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: decimals }) : "—";
const pct = (value: Value) => isNumber(value) ? `${fmt(value * 100, 1)}%` : "—";
const compact = (value: Value) => isNumber(value) ? value >= 10000 ? `${fmt(value / 10000, 1)}万` : fmt(value) : "—";
const date = (value?: Value | string, full = false) => value && Number.isFinite(new Date(value).getTime()) ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", ...(full ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) }) : "—";
const awardNames: [string, string, string][] = [["best_partner", "最佳拍档", "兼顾胜率与样本"], ["worst_partner", "最佳损友", "原始同队胜率最低"], ["damage_carry", "输出大腿", "平均团队伤害占比"], ["most_played", "最铁搭档", "有效同队场次"], ["teamfighter", "团战发动机", "平均参团率"], ["assist_master", "助攻大师", "场均助攻"], ["protector", "救命恩人", "每分钟治疗与护盾"], ["penta_king", "五杀之王", "已记录五杀次数"], ["mvp_star", "MVP之星", "自评 MVP 率 · v0.5"], ["kill_harvester", "人头收割机", "场均击杀"]];
const emptyDictionary: Dictionaries = { champions: {}, augments: {}, items: {} };
const evaluation = (player: Player) => String(player.performance?.award || "").toUpperCase();
const heroName = (player: { champion_id?: number; champion_name?: string }, dictionary: Dictionaries) => dictionary.champions[String(player.champion_id)]?.name || player.champion_name || (player.champion_id ? `英雄 #${player.champion_id}` : "未知英雄");
const hexName = (id: number, dictionary: Dictionaries) => dictionary.augments[String(id)]?.name || `海克斯 #${id}`;

function RatingWeek({ rating }: { rating?: Rating }) {
  if (rating?.source !== "haido-self" || !rating.version?.startsWith("4.") || !rating.week) return null;
  const week = rating.week;
  const label = week.games === 0 ? "本周未打" : `本周 ${isNumber(week.delta) && week.delta > 0 ? "+" : ""}${fmt(week.delta, 1)} 分 · ${fmt(week.games)} 场`;
  return <small className={'rating-week'+(isNumber(week.delta)&&week.delta<0?' is-negative':week.games===0?' is-idle':'')} title={`计分周：${date(week.start_ms)} 至 ${date(isNumber(week.end_ms) ? week.end_ms - 1 : undefined)}（北京时间）；页面构建后更新`}><span>基准 {fmt(rating.base, 1)}</span> · <span>历周 {(rating.settled_delta||0)>0?' +':''}{fmt(rating.settled_delta,1)}</span> · <span>{label}</span></small>;
}

function RatingDisplay({ rating }: { rating?: Rating; compact?: boolean }) {
  if (rating?.source === "haido-self") {
    const tier = rating.tier, score = rating.score, ci = rating.ci;
    if (tier === "unrated" || !isNumber(score))
      return <div className="rating-inline" title="自建海斗分 · 有效场次不足 5 场，暂不定级"><strong>—</strong><span>未定级</span></div>;
    if (tier === "provisional")
      return <div className="rating-inline" title={`自建海斗分 v${rating.version || "1.0"} · 暂定（${fmt(rating.n)} 场计入）`}><strong>{fmt(score)}</strong><span>暂定 ±{fmt(ci)}</span></div>;
    return <div className="rating-inline" title={`自建海斗分 v${rating.version || "1.0"} · 稳定（${fmt(rating.n)} 场计入，基准 ${fmt(rating.base,1)}，本周 ${fmt(rating.week?.delta,1)}）`}><strong>{fmt(score)}</strong><span>稳定</span></div>;
  }
  const rated = rating?.status === "estimated" && isNumber(rating.score);
  return <div className="rating-inline" title={rated ? `Hexdata 估算 · 查询于 ${date(rating.queried_at || undefined)}` : "暂无评分，不代表 0 分"}><strong>{rated ? fmt(rating.score) : "—"}</strong>{rated && <span>前 {fmt(rating.top_percent,1)}%</span>}</div>;
}

function Asset({ entry, name, large = false, quiet = false }: { entry?: DictionaryEntry; name: string; large?: boolean; quiet?: boolean }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [entry?.icon_url]);
  const valid = entry?.icon_url?.startsWith("/assets/");
  return <span className={`asset ${large ? "asset-large" : ""}`} aria-hidden="true">{!failed && valid ? <img src={entry?.icon_url} alt="" loading="lazy" onError={() => setFailed(true)} /> : quiet ? null : <span>{name.slice(0, 2)}</span>}</span>;
}
function Hero({ player, dictionary, large = false }: { player: { champion_id?: number; champion_name?: string }; dictionary: Dictionaries; large?: boolean }) {
  const name = heroName(player, dictionary);
  return <span className="hero-label"><Asset entry={dictionary.champions[String(player.champion_id)]} name={name} large={large} /><span>{name}</span></span>;
}
function Multikills({ player }: { player: Player }) {
  return <span className="multikills">{([["penta_kills", "五杀"], ["quadra_kills", "四杀"], ["triple_kills", "三杀"], ["double_kills", "双杀"]] as const).map(([key, label]) => isNumber(player[key]) && player[key]! > 0 ? <span className={`tag ${key === "penta_kills" ? "prismatic" : "gold"}`} key={key}>{label}{player[key]! > 1 ? ` ×${player[key]}` : ""}</span> : null)}</span>;
}
function AwardValue({ id, leader }: { id: string; leader?: Leader }) {
  if (!leader) return <>样本不足</>;
  if (["best_partner", "worst_partner"].includes(id)) return <>{pct(leader.win_rate)}</>;
  if (["damage_carry", "teamfighter", "mvp_star"].includes(id)) return <>{pct(leader.value)}</>;
  if (id === "most_played") return <>{fmt(leader.value ?? leader.games)}<small> 场</small></>;
  if (id === "penta_king") return <>{fmt(leader.value)}<small> 次</small></>;
  return <>{fmt(leader.value, 1)}<small>{id === "protector" ? " /分" : " /局"}</small></>;
}

function Holdings({ group, kind, dictionary, onHex }: { group?: HoldingGroup; kind: "augments" | "items"; dictionary: Dictionaries; onHex: (id: number) => void }) {
  if (!group) return <span className="muted">等待战报更新</span>;
  if (!group.top3?.length) return <span className="muted">暂无已观测持有记录</span>;
  return <ol className="holding-list">{group.top3.map((row, index) => {
    const entry = dictionary[kind][String(row.id)], name = entry?.name || `${kind === "augments" ? "海克斯" : "装备"} #${row.id}`;
    const content = <><span className="holding-rank">{index + 1}</span><Asset quiet={kind === "augments"} entry={entry} name={name} /><span className="holding-name">{name}</span><small>{fmt(row.uses)} 场 · {pct(row.frequency)}</small></>;
    return <li key={row.id}>{kind === "augments" ? <button className="holding-entry" onClick={() => onHex(row.id)} aria-label={`查看${name}说明`}>{content}</button> : <div className="holding-entry">{content}</div>}</li>;
  })}</ol>;
}

function QuickNav({ shareHref }: { shareHref: string }) {
  const jump = (id: string) => track("nav_jump", { detail: JSON.stringify({ from: "quick-nav", to: id }) });
  const links: [string, string][] = [["overview", "总览"], ["preferences", "装备"], ["honors", "荣誉"], ["matches", "对局"]];
  const [visible, setVisible] = useState(false);
  const [active, setActive] = useState("overview");
  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 520);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    const targets = links.map(([id]) => document.getElementById(id)).filter((node): node is HTMLElement => Boolean(node));
    const ids = new Set(links.map(([id]) => id));
    const observer = new IntersectionObserver(entries => {
      const hit = entries.filter(entry => entry.isIntersecting && ids.has(entry.target.id)).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (hit) setActive(hit.target.id);
    }, { rootMargin: "-35% 0px -55% 0px", threshold: [0, 0.2, 0.5, 1] });
    targets.forEach(node => observer.observe(node));
    return () => { window.removeEventListener("scroll", onScroll); observer.disconnect(); };
  }, []);
  return <nav className={`quick-nav ${visible ? "shown" : ""}`} aria-label="分区快捷导航">{links.map(([id, label]) => <a key={id} href={`#${id}`} onClick={() => jump(id)} className={active === id ? "active" : ""} aria-current={active === id ? "true" : undefined}>{label}</a>)}<a className="quick-share" href={shareHref} onClick={() => track("share_click", { detail: JSON.stringify({ from: "quick-nav" }) })} aria-label="生成这张战报的分享图">分享 ↗</a><button type="button" className="quick-top" aria-label="回到顶部" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>顶部 ↑</button></nav>;
}

export default function Home() {
  const [lobby,setLobby]=useState(true);
  const [visitor,saveVisitor]=usePreferences();
  const [visuals,setVisuals]=useState<Visuals>({});
  const [heroLayout,setHeroLayout]=useState<"cards"|"table">("cards");
  useEffect(()=>{fetch("/visuals.json",{cache:"no-store"}).then(r=>r.ok?r.json():{}).then(setVisuals).catch(()=>{});},[]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [subjectId, setSubjectId] = useState("personal");
  const [relationId, setRelationId] = useState("");
  const selectedSubject = useRef<{ id: string; name: string | null }>({ id: "personal", name: null });
  const [allHeroes, setAllHeroes] = useState(false);
  const [championId, setChampionId] = useState("0");
  const [minimum, setMinimum] = useState("20");
  const [isMobile, setIsMobile] = useState(false);
  const [companionQuery, setCompanionQuery] = useState("");
  const [companionSort, setCompanionSort] = useState("games");
  const [companionOrder, setCompanionOrder] = useState("desc");
  const [dailyHint, setDailyHint] = useState("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState("all");
  const [awardFilter, setAwardFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [hexQuery, setHexQuery] = useState("");
  const [allHexes, setAllHexes] = useState(false);
  const [selectedHex, setSelectedHex] = useState<number | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null);
  // 主快照只带摘要；完整历史（逐场明细、英雄分项、搭档）按需拉到 details 里
  const [details, setDetails] = useState<Record<string, Profile>>({});
  const revision=useRef("");
  const [detailLoading, setDetailLoading] = useState(false);
  async function refresh(initial = false) {
    if (initial) setLoading(true);
    try { if(!initial&&revision.current){const check=await fetch("/api/manifest.json",{cache:"no-cache"}).then(r=>r.ok?r.json():null).catch(()=>null);if(check?.build_id===revision.current)return;} const response = await fetchSnapshot(); const data = await response.json() as Snapshot;
      const params = new URLSearchParams(window.location.search);
      if(initial)setLobby(!params.has("player")&&!params.has("subject"));
      const requested = initial ? params.get("player") : selectedSubject.current.id;
      const name = initial ? params.get("name") : selectedSubject.current.name;
      const all = getProfiles(data);
      const exact = all.find(p => p.id === requested && (!name || p.name === name));
      const renamed = name ? all.filter(p => p.name === name) : [];
      const profile = exact || (renamed.length === 1 ? renamed[0] : undefined) || all.find(p => p.id === data.default_player) || all[0];
      if (profile) { selectedSubject.current = { id: profile.id, name: profile.name }; setSubjectId(profile.id); }
      if(data.build_id!==revision.current){revision.current=data.build_id||"";setDetails({});} setSnapshot(data); setError(""); }
    catch { setError("暂时无法更新战报，请稍后重试。"); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    const viewport = window.matchMedia("(max-width: 700px)");
    const updateViewport = () => setIsMobile(viewport.matches);
    updateViewport();
    viewport.addEventListener("change", updateViewport);
    return () => viewport.removeEventListener("change", updateViewport);
  }, []);
  useEffect(() => { refresh(true); const timer = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 60000); return () => clearInterval(timer); }, []);
  // 访问统计：只写不读，失败静默，不影响页面
  const trackedView = useRef(false);
  useEffect(() => {
    if (trackedView.current) return;
    trackedView.current = true;
    track("page_view", { detail: JSON.stringify({ entry: "home" }) });
    return trackSession();
  }, []);
  useEffect(()=>{const back=()=>{setChampionId("0");setRelationId("");setQuery("");setResult("all");setAwardFilter("all");setSelectedMatch(null);setSelectedHex(null);refresh(true);};window.addEventListener("popstate",back);return()=>window.removeEventListener("popstate",back);},[]);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { if (selectedHex !== null) setSelectedHex(null); else setSelectedMatch(null); } }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [selectedHex]);
  useEffect(() => {
    if (!selectedMatch && selectedHex === null) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const dialog = document.querySelector(selectedHex !== null ? ".hex-modal" : ".match-modal");
      const controls = dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, select, [tabindex="0"]');
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", trap);
    return () => { document.body.style.overflow = overflow; window.removeEventListener("keydown", trap); previous?.focus(); };
  }, [selectedMatch, selectedHex]);
  const dictionary = { ...emptyDictionary, ...snapshot?.static } as Dictionaries;
  const profiles = getProfiles(snapshot || undefined);
  const subject = details[subjectId] || profiles.find(p => p.id === subjectId) || profiles[0];
  useEffect(() => {
    if (lobby || !snapshot || !subjectId || details[subjectId]) return;
    const base = getProfiles(snapshot).find(p => p.id === subjectId);
    if (!base?.has_detail) return;
    let alive = true;
    setDetailLoading(true);
    loadProfile(base)
      .then(detail => { if (alive) setDetails(previous => ({ ...previous, [subjectId]: { ...base, ...detail, history_scope: detail.history_scope || base.history_scope, coverage: detail.coverage || base.coverage } })); })
      .catch(() => {})
      .finally(() => { if (alive) setDetailLoading(false); });
    return () => { alive = false; };
  }, [snapshot, subjectId, details, lobby]);
  const subjectName = subject?.name || snapshot?.owner?.name || "玩家";
  useEffect(()=>{document.title=lobby?"海克斯战报馆 · 玩家大厅":`${subjectName} · 海克斯战绩档案`;},[lobby,subjectName]);
  useEffect(()=>{if(!loading&&snapshot&&window.location.hash){let id="";try{id=decodeURIComponent(window.location.hash.slice(1));}catch{return;}requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({behavior:"instant"}));}},[loading,lobby]);
  const focused = championId !== "0" ? subject?.by_champion?.[championId] : subject;
  const summary = focused?.summary || {};
  const championRows = focused?.champions || (championId !== "0" ? (subject?.champions || []).filter(hero => String(hero.champion_id) === championId) : []);
  const visibleChampionRows = allHeroes ? championRows : championRows.slice(0, 12);
  useEffect(() => { setAllHeroes(false); setAllHexes(false); }, [subjectId, championId]);
  useEffect(() => setAllHexes(false), [hexQuery]);
  const teammateRows = subject?.teammates || [];
  const relation = teammateRows.find(p => p.id === relationId);
  const allRecent = (subject?.recent || []).filter(match => championId === "0" || String(match.player.champion_id) === championId);
  const recent = allRecent;
  const matchRecent = relation ? recent.filter(m => relation.match_ids?.includes(m.id)) : recent;
  const highlights = focused?.highlights;
  const selfAwards = focused?.awards;
  const candidateReport = subject?.reports?.[minimum];
  const report = ["20", "30"].includes(minimum) && candidateReport?.minimum_award_games === Number(minimum) ? candidateReport : undefined;
  const globalRange = subject?.coverage.time_range;
  const shareHref = subject?.history_scope === "shared" ? `/share/?subject=${encodeURIComponent(subject.source_id || "")}&name=${encodeURIComponent(subjectName)}` : `/share/?player=${encodeURIComponent(subjectId)}`;
  const verdict = playerVerdict(subjectName,subject?.summary || {},subject?.awards || {},(subject?.champions || []).slice(0,3).map(h => heroName(h,dictionary)),subject?.champions || [],subject?.verdict);
  const hexes = (focused?.hextech?.augments || []).filter(a => hexName(a.id,dictionary).includes(hexQuery.trim()));
  const shownMatches = useMemo(() => matchRecent.filter(match => {
    const p = match.player;
    const text = [heroName(p, dictionary), match.patch, date(match.started_ms), ...(p.augment_slots || []).filter((id): id is number => isNumber(id) && id > 0).map(id => hexName(id, dictionary))].join(" ").toLowerCase();
    return (result === "all" || Boolean(p.win) === (result === "win")) && (awardFilter === "all" || (awardFilter === "either" ? ["MVP", "ACE"].includes(evaluation(p)) : evaluation(p) === awardFilter)) && text.includes(query.trim().toLowerCase());
  }), [subject, relationId, championId, query, result, awardFilter, snapshot]);
  const pageSize = isMobile ? 10 : 20;
  const pages = Math.max(1, Math.ceil(shownMatches.length / pageSize));
  useEffect(() => setPage(1), [subjectId, relationId, championId, query, result, awardFilter, pageSize]);
  useEffect(() => { if (page > pages) setPage(pages); }, [page, pages]);
  const friendRows = [...teammateRows].filter(c => isNumber(c.games) && c.games >= 10 && c.name.toLowerCase().includes(companionQuery.trim().toLowerCase())).sort((a, b) => {
    const score = (c: Companion): Value => {
      if (companionSort === "rating") return c.rating?.status === "estimated" ? c.rating.score : null;
      if (["mvp", "ace", "mvp_rate"].includes(companionSort)) {
        if (!isNumber(c.awards?.games) || c.awards.games <= 0) return null;
        return companionSort === "mvp_rate" ? isNumber(c.awards.mvp) ? c.awards.mvp / c.awards.games : null : c.awards[companionSort as "mvp" | "ace"];
      }
      return companionSort === "games" ? c.games : companionSort === "win_rate" ? c.summary?.win_rate ?? c.win_rate : c.summary?.[companionSort as "damage_share" | "kda" | "dpm"];
    };
    const left = score(a), right = score(b);
    if (!isNumber(left) || !isNumber(right)) return isNumber(left) ? -1 : isNumber(right) ? 1 : (b.games || 0) - (a.games || 0) || a.id.localeCompare(b.id);
    return (companionOrder === "asc" ? left - right : right - left) || (b.games || 0) - (a.games || 0) || a.id.localeCompare(b.id);
  });
  const days = new Map<string, { games: number; wins: number }>();
  for (const m of [...recent].reverse()) if (m.stats_eligible && isNumber(m.started_ms)) { const key = date(m.started_ms); const current = days.get(key) || { games: 0, wins: 0 }; current.games++; current.wins += Number(Boolean(m.player.win)); days.set(key, current); }
  useEffect(() => setDailyHint(""), [subjectId, championId]);
  const daily = [...days].slice(-20), maxDay = Math.max(1, ...daily.map(([, d]) => d.games));
  function toggleHero(id: number) { setChampionId(current => current === String(id) ? "0" : String(id)); }
  function chooseSubject(id: string) {
    const profile = profiles.find(p => p.id === id); if (!profile) return;
    trackSubject(id, profile.name);
    selectedSubject.current = { id, name: profile.name }; setSubjectId(id); setChampionId("0"); setRelationId(""); setQuery(""); setResult("all"); setAwardFilter("all"); setHexQuery(""); setSelectedMatch(null); setSelectedHex(null); setPage(1);
    setLobby(false);try{localStorage.setItem("battlebook-last-player",id);}catch{}
    setCompanionQuery("");setDailyHint("");
    const url = new URL(window.location.href); url.searchParams.set("player", id); url.searchParams.delete("subject"); if(profile.history_scope === "shared") url.searchParams.set("name",profile.name); else url.searchParams.delete("name");url.hash=""; window.history.pushState(null, "", url);window.scrollTo({top:0,behavior:"instant"});
  }
  function openLobby(){setLobby(true);setSelectedMatch(null);setSelectedHex(null);const url=new URL(window.location.href);url.search="";url.hash="";window.history.pushState(null,"",url);window.scrollTo({top:0,behavior:"instant"});}

  const statCards: [string, string, string, Value][] = [["有效对局", fmt(summary.games), "排除重开及未正常结束", summary.games], ["胜率", pct(summary.win_rate), `${fmt(summary.wins)} 胜 / ${fmt(isNumber(summary.games) && isNumber(summary.wins) ? summary.games - summary.wins : null)} 负`, summary.samples?.wins], ["KDA", fmt(summary.kda, 2), "总击杀助攻 ÷ 总死亡", summary.samples?.kda], ["每分钟伤害", fmt(summary.dpm), "仅对英雄造成的伤害", summary.samples?.dpm], ["团队伤害占比", pct(summary.damage_share), "逐局团队伤害占比平均", summary.samples?.damage_share], ["参团率", pct(summary.kill_participation), "逐局有效参团率平均", summary.samples?.kill_participation]];

  if (loading && !snapshot) return <main className="load-screen"><span className="hex-mark">⬡</span><h1>正在读取海克斯战报</h1><p>从已保存对局，找回每一次并肩作战。</p></main>;
  if (!snapshot) return <main className="load-screen"><span className="hex-mark">⬡</span><h1>战报暂时无法读取</h1><p>{error || "暂无已发布的战绩数据。"}</p><button onClick={() => refresh(true)}>重新读取</button></main>;
  if(lobby)return <RatingRulesContext.Provider value={snapshot.rating_rules||null}><Lobby snapshot={snapshot} profiles={profiles} dictionary={dictionary} visuals={visuals} preferences={visitor} save={saveVisitor} onChoose={chooseSubject} onMatch={(id,match)=>{chooseSubject(id);setSelectedMatch(match);}}/></RatingRulesContext.Provider>;

  return <RatingRulesContext.Provider value={snapshot.rating_rules||null}><main className="site-shell unified-site experience-v2" style={subject?visualStyle(subject,visitor):undefined} data-theme={subject?themeFor(subject,visitor).key:undefined} aria-busy={detailLoading||undefined}>
    {detailLoading&&<div className="detail-loading" role="status"><span className="hex-mark spin">⬡</span><div><strong>正在加载 {subjectName} 的完整战绩</strong><small>逐场明细、英雄分项与搭档数据按需读取，通常不到一秒。</small></div></div>}
    <header className="club-header profile-global-header"><button className="club-brand brand-button" onClick={openLobby}><span className="club-logo">⬡</span><span>海克斯战报馆<small>HEXTECH BATTLEBOOK</small></span></button><nav aria-label="页面导航"><button className="back-lobby" onClick={openLobby}>← 玩家大厅</button><a href="#preferences">装备 / 海克斯</a><a href="#honors">搭档荣誉</a><a href="#heroes">英雄</a><a href="#matches">对局</a><a href="/intel.html">版本情报 ↗</a></nav><div className="header-personal"><VisitorMenu profiles={profiles} preferences={visitor} save={saveVisitor} onChoose={chooseSubject}/><span className="preview-label">本地预览</span></div></header>
    <section className="player-cover signature-cover" id="overview"><div className="cover-art" aria-hidden="true" style={{backgroundImage:visuals[subjectId]?.splash_url?`url("${visuals[subjectId].splash_url}")`:undefined}}/><span className="cover-edition" aria-hidden="true">{subject?themeFor(subject,visitor).tag:"PLAYER ARCHIVE"}<br/>EVERY PLAYER HAS A STORY.</span><div className="cover-main"><div className="cover-avatar"><Portrait profile={{name:subjectName}} visual={visuals[subjectId]} large/><span>⬡</span></div><div className="cover-name"><p className="eyebrow">PLAYER ARCHIVE / 标准海克斯大乱斗</p><h1>{subjectName}</h1><p>{verdict?.pro.tag || "每一局都有自己的精彩"}<span> · {subject?.history_scope === "shared" ? "同队样本" : "个人历史"}</span></p></div></div><div className="cover-actions"><label>切换玩家<select aria-label="切换玩家" value={subjectId} onChange={e=>chooseSubject(e.target.value)}>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><a className="button share-button" href={shareHref} onClick={() => track("share_click", { detail: JSON.stringify({ from: "cover" }) })}>分享朋友荣誉战报 ↗</a></div></section>
    <div className="profile-personalization"><span className="avatar-caption">游戏头像 · 最近战报 {date(visuals[subjectId]?.avatar_observed_ms)}</span><div>{subject&&<StarButton profile={subject} preferences={visitor} save={saveVisitor}/>} {subject&&<ThemePicker profile={subject} preferences={visitor} save={saveVisitor}/>}</div></div>
    <div className="archive-meta profile-coverage"><span><b>{fmt(subject?.coverage.saved)}</b> 场已收录</span><span className="account-rating">海斗分 <strong>{subject?.rating?.source === "haido-self" ? (subject.rating.tier === "unrated" || !isNumber(subject.rating.score) ? "—" : fmt(subject.rating.score,1)) : (subject?.rating?.status === "estimated" ? fmt(subject.rating.score,1) : "—")}</strong>{subject?.rating?.source === "haido-self" ? (subject.rating.tier === "provisional" ? <small>暂定 ±{fmt(subject.rating.ci)}</small> : subject.rating.tier === "stable" ? <small>稳定 · {fmt(subject.rating.n)} 场</small> : <small>未定级</small>) : subject?.rating?.status === "estimated" ? <small>本区前 {fmt(subject.rating.top_percent,1)}%</small> : null}<RatingWeek rating={subject?.rating} /><RatingRules rating={subject?.rating} name={subject?.name}/></span><details className="coverage-details"><summary>数据范围</summary><div><p>已收录战绩范围：{date(globalRange?.oldest_ms)} — {date(globalRange?.newest_ms)}。</p><p>只统计已收录的标准海克斯历史，不代表完整生涯；{fmt(subject?.coverage.excluded)} 场重开或未正常结束不计表现。</p>{subject?.history_scope === "shared"&&<p>此玩家当前仅收录与 {snapshot.owner?.name} 同队的记录，尚未接入独立个人历史。</p>}{(subject?.coverage.missing || 0) > 0 && <p>当前已发现的历史还有 {fmt(subject?.coverage.missing)} 场待补明细。</p>}{subject?.rating?.source === "haido-self" ? <p>海斗分为本站自建算法 v{subject.rating.version || "4.3"}：总分由冻结历史基准、已结束各周累计涨跌及本周分组成。每周一零点只重置周榜，历周涨跌保留，本周未打保持累计总分。{typeof subject.rating.calculation?.cap === "number" ? `单周上限±${subject.rating.calculation.cap}` : "单周分数不设上下限"}，胜负项零点在 {subject.rating.calculation?.zero_win_rate ?? 45.9}% 胜率，胜率过半才算净加分；发挥好会多拿、发挥一般的赢局也只加不扣；对局记录里每局的加减分是同一周分的摊分；详细分项、公式与周账本可点“海斗分规则”查看。</p> : <p>海斗分查询于 {date(subject?.rating?.queried_at || undefined)}{subject?.rating?.matches_through ? "，计入截至 " + date(subject.rating.matches_through) : ""}，来自 Hexdata 估算，有更新延迟。</p>}</div></details><button className="text-button" onClick={() => { track("refresh_click", { detail: JSON.stringify({ subject: subjectId }) }); refresh(); }}>刷新数据 ↻</button></div>
    <p className="profile-data-note" aria-label="战绩数据状态"><span>战绩截至 {date(globalRange?.newest_ms)}</span><span>数据更新于 {date(snapshot.updated_at || snapshot.generated_at)}</span><span>{subject?.history_scope === "shared" ? "仅同队样本 · 个人历史待接入" : typeof subject?.coverage.missing === "number" && Number.isFinite(subject.coverage.missing) && subject.coverage.missing > 0 ? `尚缺 ${fmt(subject.coverage.missing)} 场明细` : subject?.coverage.missing === 0 ? "已发现对局暂无缺口" : "缺口待核实"}</span></p>
    {subject?.history_scope === "shared" && <p className="notice scope-banner">当前展示 {subjectName} 的部分同队记录，尚未接入其独立个人历史。以下指标、评语和荣誉仅代表这些已收录样本。</p>}
    {error && <div className="notice" role="status">{error} 当前仍展示上次读取的数据。</div>}
    {subject&&<PersonalBadges profile={subject}/>}
    <div className="personal-toolbar"><label>英雄<select id="hero-filter" value={championId} onChange={event => { track("hero_filter", { detail: JSON.stringify({ hero: event.target.value }) }); setChampionId(event.target.value); }}><option value="0">全部英雄</option>{(subject?.champions || []).map(h => <option key={h.champion_id} value={h.champion_id}>{heroName(h, dictionary)}</option>)}</select></label>{championId !== "0" ? <button id="clear-hero-filter" className="ghost" onClick={() => { track("hero_filter", { detail: JSON.stringify({ hero: "0", cleared: true }) }); setChampionId("0"); }}>清除英雄筛选 ×</button> : <span>个人表现</span>}</div>
    {verdict && <figure className="subject-verdict"><p className="verdict-kicker">队内评语 · {subject?.history_scope === "shared" ? "已保存同队样本" : "已收录个人历史"}</p><p className="verdict-text">{verdict.text}</p><figcaption className="verdict-punch">「{verdict.punch.replace(/。$/,"")}」</figcaption><div className="verdict-pro"><p className="pro-head"><span className="pro-kicker">打法参照</span><strong>{verdict.pro.pro}</strong><span className="pro-tag">{verdict.pro.tag}</span></p><p className="pro-text">{verdict.pro.text}</p><small className="pro-note">风格联想，不代表职业水平比较；评语按账号全部已收录样本生成。</small></div></figure>}
    <section className="stats-grid" aria-label="个人表现指标">{statCards.map(([label,value,note,samples]) => <article className="stat-card" key={label} title={`${note} · ${fmt(samples)} 场有效样本`}><span>{label}</span><strong className={label === "胜率" ? "gold-text" : ""}>{value}</strong><small>{note}</small><span className="sample-count">{fmt(samples)} 场有效样本</span></article>)}</section>
    {subject&&<PlayerRadar profile={subject} profiles={profiles}/>}
    <div className="highlight-strip"><span title={`${fmt(selfAwards?.games)} 场可评 · 自评 v0.5`}><b>{fmt(selfAwards?.mvp)}</b> MVP</span><span title={`${fmt(selfAwards?.games)} 场可评 · 自评 v0.5`}><b>{fmt(selfAwards?.ace)}</b> 败方 ACE</span>{([["penta_kills","五杀"],["quadra_kills","四杀"],["triple_kills","三杀"]] as const).map(([key,label]) => <span key={key} title={`${fmt(highlights?.samples?.[key] ?? summary.samples?.[key])} 场有字段`}><b>{fmt(highlights?.totals?.[key] ?? summary[key])}</b> {label}</span>)}</div>
    <section id="preferences" className="panel holdings-panel" aria-label="海克斯与装备"><div className="panel-heading"><div><p className="section-kicker">FINAL HOLDINGS</p><h2>{championId === "0" ? "常用" : `${heroName({champion_id:Number(championId)},dictionary)} · 常用`}海克斯与装备</h2></div><span>当前分析范围 · {fmt(focused?.preferences?.games)} 场有效对局</span></div><div className="holdings-grid">{(["augments", "items"] as const).map(kind => <div key={kind}><h3>局末{kind === "augments" ? "海克斯" : "装备"} Top 3</h3><Holdings group={focused?.preferences?.[kind]} kind={kind} dictionary={dictionary} onHex={setSelectedHex} /><p className="holding-coverage">{fmt(focused?.preferences?.[kind]?.observed_games)} 场有记录 · {fmt(focused?.preferences?.[kind]?.complete_games)} 场字段齐全</p></div>)}</div><p className="panel-note">每局同一项只计一次，占比以当前有效对局为分母；装备不含饰品位。</p></section>
    <section className="overview-grid"><article className="panel trajectory"><div className="panel-heading"><div><h2>最近 20 局 · 手感回顾</h2></div><span>和之前的自己比一比</span></div><FormReview matches={recent} dictionary={dictionary} onMatch={(m) => { const hero = heroName(m.player, dictionary); track("match_open", { detail: JSON.stringify({ from: "form-review", hero }) }); setSelectedMatch(m); }}/>
      <div className="daily-chart" aria-label="每日有效对局胜负">{daily.map(([key, d]) => { const label = `${key} · ${d.games} 场 / ${d.wins} 胜 / ${d.games - d.wins} 负`; return <button type="button" className="daily-column" key={key} aria-label={label} onMouseEnter={() => setDailyHint(label)} onFocus={() => setDailyHint(label)} onClick={() => { setDailyHint(label); track("chart_tap", { detail: JSON.stringify({ day: key, games: d.games }) }); }}><span className="daily-win" style={{ height: `${d.wins / maxDay * 85}px` }} /><span className="daily-loss" style={{ height: `${(d.games - d.wins) / maxDay * 85}px` }} /></button>; })}</div><div className="chart-meta"><span>{daily[0]?.[0] || "暂无有效对局"}</span><span><i className="swatch win" />胜利 <i className="swatch loss" />失利</span><span>{daily.at(-1)?.[0] || ""}</span></div><p className="daily-hint" aria-live="polite">{dailyHint || "点击日期柱，查看当天胜负场数。"}</p></article><article className="panel favorite-heroes"><div className="panel-heading"><div><p className="section-kicker">FAVORITE CHAMPIONS</p><h2>常玩英雄</h2></div><span>点击按英雄分析</span></div>{(subject?.champions || []).slice(0, 4).map(h => <button className="favorite-row" key={h.champion_id} aria-pressed={championId === String(h.champion_id)} onClick={() => toggleHero(h.champion_id)}><Hero player={h} dictionary={dictionary} /><span><b>{fmt(h.games)} 场</b><small>{pct(h.win_rate)} 胜率</small></span><span className="hero-track"><i style={{ width: `${Math.min(100, (h.games || 0) / Math.max(1, subject?.champions?.[0]?.games || 1) * 100)}%` }} /></span></button>)}{!subject?.champions?.length && <p className="muted">暂无英雄样本。</p>}</article></section>
    <section className="panel subject-panel" id="heroes"><div className="panel-heading"><h2>英雄表现</h2><span>{championId === "0" ? "常玩英雄优先 · 点击英雄筛选个人表现" : heroName({champion_id:Number(championId)},dictionary)}</span></div><div className="hero-view-switch" role="group" aria-label="英雄展示方式"><button aria-pressed={heroLayout==="cards"} onClick={()=>setHeroLayout("cards")}>英雄收藏卡</button><button aria-pressed={heroLayout==="table"} onClick={()=>setHeroLayout("table")}>完整数据表</button></div><div className="hero-card-view" hidden={heroLayout!=="cards"}><HeroCards heroes={visibleChampionRows} dictionary={dictionary} onHero={toggleHero} selected={championId} renderHoldings={(h,kind)=><Holdings group={h.preferences?.[kind]} kind={kind} dictionary={dictionary} onHex={setSelectedHex}/>}/>{!championRows.length&&<p className="empty-state">暂无符合条件的英雄表现。</p>}{championRows.length>12&&<div className="pagination"><span>显示 {visibleChampionRows.length} / {championRows.length} 位英雄</span><button className="ghost" onClick={()=>{track("hero_expand",{detail:JSON.stringify({expanded:!allHeroes,count:championRows.length})});setAllHeroes(v=>!v);}}>{allHeroes?"收起英雄卡片":"展开全部英雄卡片"}</button></div>}</div><div hidden={heroLayout!=="table"}><div className="table-scroll hero-table-scroll" role="region" aria-label="英雄表现表，可左右滑动查看完整指标" tabIndex={0}><p className="mobile-scroll-hint" aria-hidden="true">↔ 左右滑动查看完整指标</p><table className="hero-stat-table"><thead><tr><th>英雄</th><th>场次</th><th>胜率</th><th>KDA</th><th>每分钟伤害</th><th>伤害占比</th><th>参团率</th><th>海克斯 Top 3</th><th>装备 Top 3</th></tr></thead><tbody>{visibleChampionRows.map(h => <tr key={h.champion_id}><td><button className="hero-link" aria-pressed={championId === String(h.champion_id)} onClick={() => toggleHero(h.champion_id)}><Hero player={h} dictionary={dictionary} /></button></td><td>{fmt(h.games)}</td><td className="gold-text">{pct(h.win_rate)}</td><td>{fmt(h.kda,2)}</td><td>{fmt(h.dpm)}</td><td>{pct(h.damage_share)}</td><td>{pct(h.kill_participation)}</td>{(["augments","items"] as const).map(kind => <td className="holding-cell" key={kind}><Holdings group={h.preferences?.[kind]} kind={kind} dictionary={dictionary} onHex={setSelectedHex} /></td>)}</tr>)}</tbody></table>{!championRows.length && <div className="empty-state">暂无符合条件的英雄表现。</div>}{championRows.length > 12 && <div className="pagination"><span>显示 {visibleChampionRows.length} / {championRows.length} 位英雄</span><button id="toggle-all-heroes" className="ghost" aria-expanded={allHeroes} onClick={() => setAllHeroes(v => !v)}>{allHeroes ? "收起英雄列表" : "展开全部英雄"}</button></div>}</div>
      </div><section className="hex-review" id="hextech"><div className="panel-heading"><h2>海克斯回顾</h2><span>局末持有频次 · 点击看说明</span></div><div className="hex-toolbar"><p>{fmt(focused?.hextech?.complete_games)} / {fmt(focused?.hextech?.games)} 场槽位字段齐全</p><input aria-label="搜索海克斯" value={hexQuery} onChange={event => setHexQuery(event.target.value)} placeholder="搜索海克斯名称" /></div><div className="hex-grid">{(allHexes ? hexes : hexes.slice(0,12)).map(a => <button className={`hex-card ${dictionary.augments[String(a.id)]?.rarity || ""}`} key={a.id} onClick={() => { track("hex_open", { detail: JSON.stringify({ from: "hex-grid", id: a.id, name: hexName(a.id, dictionary) }) }); setSelectedHex(a.id); }}><span className="hero-label"><Asset quiet entry={dictionary.augments[String(a.id)]} name={hexName(a.id,dictionary)} /><strong>{hexName(a.id,dictionary)}</strong></span><span><b>{fmt(a.uses)}</b> 场 · {pct(a.frequency)}</span></button>)}</div><p className="panel-note">局末持有，不代表选取顺序或海克斯独立伤害。</p>{hexes.length > 12 && <div className="pagination"><span>{allHexes ? hexes.length : 12} / {hexes.length} 枚海克斯</span><button className="ghost" onClick={() => { track("hex_open", { detail: JSON.stringify({ scope: "expand", expanded: !allHexes }) }); setAllHexes(v => !v); }}>{allHexes ? "收起海克斯" : "展开全部海克斯"}</button></div>}{!hexes.length && <p className="empty-state">没有符合条件的海克斯记录。</p>}</section>
    </section>
    <section className="honors-section" id="honors"><div className="section-heading"><div><h2>这局，有你真好。<span>一起打过的搭档荣誉</span></h2></div><label>荣誉门槛<select id="award-minimum" value={minimum} onChange={event => { const v = event.target.value === "30" ? "30" : "20"; track("hero_filter", { detail: JSON.stringify({ award_minimum: v }) }); setMinimum(v); }}><option value="20">至少 20 场</option><option value="30">至少 30 场</option></select></label><a className="text-button together-share" href={`${shareHref}&scope=shared`} onClick={() => track("share_click", { detail: JSON.stringify({ from: "honors", scope: "shared" }) })}>分享搭档战报 ↗</a></div><p className="scope-note">按当前玩家全部已收录历史评选，每项至少 {minimum} 场有效样本；不随英雄或对局筛选变化。</p>{!report && <p className="notice" role="status">当前快照尚无 {minimum} 场门槛的称号数据，等待战报更新后展示。</p>}<div className="honors-grid">{awardNames.map(([id, title, label], index) => { const award = report?.awards?.find(a => a.id === id), leaders = (award?.leaders || []).filter(leader => isNumber(leader.samples) && leader.samples >= Number(minimum)), leader = leaders[0]; return <article className={`honor-card ${id === "best_partner" ? "featured" : ""}`} key={id}><div className="honor-top"><span>{String(index + 1).padStart(2, "0")}</span><h3>{title}</h3><span className="honor-symbol">⬡</span></div><p>{label}</p><div className="honor-value"><AwardValue id={id} leader={leader} /></div>{leader ? <><div className="honor-winner"><Asset entry={dictionary.champions[String(leader.champion_id)]} name={heroName(leader, dictionary)} /><strong>{leaders.map(p => p.name).join(" / ")}</strong>{leaders.length > 1 && <span className="tag gold">并列 {leaders.length} 位</span>}</div><small>{["best_partner", "worst_partner"].includes(id) ? `${fmt(leader.wins)} 胜 / ${fmt(leader.secondary?.result_games ?? leader.games)} 场结果样本` : `${fmt(leader.samples)} 场该指标有效样本`}</small></> : <div className="honor-empty">暂无达标记录，等待下一场开黑。</div>}</article>; })}</div></section>
    <section className="panel companions-section" id="companions"><div className="panel-heading"><div><h2>常玩搭档 <span className="inline-count">{teammateRows.length}</span></h2></div><span>至少 10 场有效同队 · 点名字看玩家档案</span></div><div className="table-toolbar"><input id="companion-search" type="search" aria-label="搜索队友姓名" value={companionQuery} onChange={event => setCompanionQuery(event.target.value)} placeholder="搜索队友名字" /><label className="inline-label">排序<select id="companion-sort" value={companionSort} onChange={event => { track("companion_sort", { detail: JSON.stringify({ sort: event.target.value }) }); setCompanionSort(event.target.value); }}><option value="games">共同场数</option><option value="rating">海斗分（自建）</option><option value="win_rate">同队胜率</option><option value="mvp">自评 MVP 次数</option><option value="ace">败方 ACE 次数</option><option value="mvp_rate">自评 MVP 率</option><option value="dpm">每分钟伤害</option><option value="damage_share">搭档伤害占比</option><option value="kda">队友 KDA</option></select></label><label className="inline-label">顺序<select id="companion-order" value={companionOrder} onChange={event => setCompanionOrder(event.target.value)}><option value="desc">从高到低</option><option value="asc">从低到高</option></select></label><span className="muted">搭档指标仅计与当前玩家同队的记录，同队不代表预先组队。</span></div><div className="table-scroll"><table className="card-table companion-card-table" role="table" aria-label="常玩队友榜"><thead role="rowgroup"><tr role="row"><th scope="col" id="friend-name">队友</th><th scope="col" id="friend-games">与分析对象有效同队局</th><th scope="col" id="friend-winrate">同队胜率</th><th scope="col" id="friend-rating">海斗分</th><th scope="col" id="friend-kda">队友 KDA</th><th scope="col" id="friend-damage">队友伤害占比</th><th scope="col" id="friend-mvp">队友自评 MVP / ACE</th><th scope="col" id="friend-heroes">常用英雄</th></tr></thead><tbody role="rowgroup">{friendRows.map(c => <tr role="row" key={c.id} className={relationId === c.id ? "selected-row" : ""}><td role="cell" headers="friend-name" data-label="队友"><div className="friend-actions"><button className="friend-link" data-companion-id={c.id} disabled={!profiles.some(p=>p.name===c.name)} onClick={()=>{const target=profiles.find(p=>p.name===c.name);if(target)chooseSubject(target.id);}}>{c.name}<span>{profiles.some(p=>p.name===c.name)?"玩家档案 ↗":"档案待接入"}</span></button>{Boolean(c.match_ids?.length)&&<button className="shared-match-link" onClick={()=>{setRelationId(c.id);document.getElementById("matches")?.scrollIntoView({behavior:"smooth"});}}>看同队局 →</button>}</div></td><td role="cell" headers="friend-games" data-label="与分析对象有效同队局">{fmt(c.games)}<small className="cell-sub">已保存同队 {fmt(c.shared_games)} 场</small></td><td role="cell" headers="friend-winrate" data-label="同队胜率" className="green-text">{pct(c.summary?.win_rate ?? c.win_rate)}</td><td role="cell" headers="friend-rating" data-label="海斗分（自建）"><RatingDisplay rating={c.rating} compact /></td><td role="cell" headers="friend-kda" data-label="队友 KDA">{fmt(c.summary?.kda, 2)}</td><td role="cell" headers="friend-damage" data-label="队友伤害占比">{pct(c.summary?.damage_share)}</td><td role="cell" headers="friend-mvp" data-label="队友自评 MVP / ACE">MVP {fmt(c.awards?.mvp)} 次 / ACE {fmt(c.awards?.ace)} 次<small className="cell-sub">{fmt(c.awards?.games)} 场可评 · v0.5</small></td><td role="cell" headers="friend-heroes" data-label="常用英雄"><span className="hero-group">{(c.champions || []).slice(0, 3).map(h => <span className="companion-hero" key={h.champion_id}><Asset entry={dictionary.champions[String(h.champion_id)]} name={heroName(h, dictionary)} /><span className="companion-hero-name">{heroName(h, dictionary)}</span></span>)}</span></td></tr>)}</tbody></table>{!friendRows.length && <div className="empty-state">{companionQuery ? "没有找到这位队友，试着换个名字。" : "当前分析对象暂无达到 10 场有效同队局的队友。"}</div>}</div></section>
    <section className="panel matches-section" id="matches"><div className="panel-heading"><div><h2>{relation ? `与 ${relation.name} 同队的对局` : "对局记录"}</h2></div><span>{shownMatches.length} 场 · 点击查看战报</span></div><div className="table-toolbar">{subject?.history_scope !== "shared" && <label className="match-relation">同队筛选<select id="relation-filter" value={relationId} onChange={event => setRelationId(event.target.value)}><option value="">全部对局</option>{teammateRows.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}{relation && <button className="ghost" onClick={() => setRelationId("")}>清除同队筛选 ×</button>}<input id="match-search" type="search" aria-label="搜索对局" placeholder="搜索英雄、海克斯、日期" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && query.trim()) track("match_search", { detail: JSON.stringify({ query: query.trim(), hits: shownMatches.length }) }, 800); }} /><select id="result-filter" aria-label="筛选胜负" value={result} onChange={event => { track("match_filter", { detail: JSON.stringify({ result: event.target.value }) }); setResult(event.target.value); }}><option value="all">全部胜负</option><option value="win">仅胜利</option><option value="loss">仅失利</option></select><select id="mvp-filter" aria-label="筛选自评奖项" value={awardFilter} onChange={event => { track("match_filter", { detail: JSON.stringify({ award: event.target.value }) }); setAwardFilter(event.target.value); }}><option value="all">全部自评奖项</option><option value="MVP">自评 MVP</option><option value="ACE">自评 ACE</option><option value="either">MVP 或 ACE</option></select></div><div className="table-scroll"><table className="card-table match-card-table" role="table" aria-label="对局记录"><thead role="rowgroup"><tr role="row"><th scope="col" id="match-result">结果 / 时间</th><th scope="col" id="match-hero">英雄 / 亮点</th><th scope="col" id="match-kda">K / D / A</th><th scope="col" id="match-damage">伤害 / 团队占比</th><th scope="col" id="match-hex">局末海克斯</th><th scope="col" id="match-action">战报</th></tr></thead><tbody role="rowgroup">{shownMatches.slice((page - 1) * pageSize, page * pageSize).map(m => <tr role="row" key={m.id}><td role="cell" headers="match-result" data-label="结果 / 时间"><span className={`result-tag ${m.player.win ? "win" : "loss"}`}>{m.player.win ? "胜利" : "失利"}</span><small className="cell-sub">{date(m.started_ms, true)}</small>{isNumber(m.rating_delta) && <small className={`cell-sub match-delta ${m.rating_delta >= 0 ? "up" : "down"}`} title="该局为所在自然周海斗分贡献的分值；同一周各局相加等于该周周分">{m.rating_delta > 0 ? "+" : ""}{fmt(m.rating_delta, 1)} 海斗分{isNumber(m.rating_mult) && m.rating_mult > 1 && <span className="night-flag" title="战斗之夜（周五 20:00—周六 02:00）对局，权重 ×1.5">战斗之夜 ×{m.rating_mult}</span>}{isNumber(m.rating_penta_bonus) && m.rating_penta_bonus > 0 && <span className="night-flag penta-flag" title="已计入该局海斗分；按该局所属计分规则计算，战斗之夜乘1.5">五杀奖励 +{fmt(m.rating_penta_bonus,2)}</span>}{isNumber(m.rating_volume_mult) && m.rating_volume_mult < 1 && <span className="volume-flag" title="周内前 12 局权重为 1，之后按 sqrt(12/局号) 逐局递减；赢局收益与输局扣分同比缩小">第{fmt(m.rating_week_index,0)}局 ×{fmt(m.rating_volume_mult,2)}</span>}</small>}</td><td role="cell" headers="match-hero" data-label="英雄 / 亮点"><Hero player={m.player} dictionary={dictionary} /><span className="match-badges">{evaluation(m.player) && <span className="tag gold" title="本工具自评 v0.5">{evaluation(m.player)} · 自评</span>}<Multikills player={m.player} /></span></td><td role="cell" headers="match-kda" data-label="K / D / A">{fmt(m.player.kills)} / {fmt(m.player.deaths)} / {fmt(m.player.assists)}<small className="cell-sub">{m.patch?.split(".").slice(0, 2).join(".") || "—"} 版本{!m.stats_eligible ? " · 不计统计" : ""}</small></td><td role="cell" headers="match-damage" data-label="伤害 / 团队占比">{compact(m.player.damage)}<small className="cell-sub">{pct(m.player.damage_share)} 团队伤害{isNumber(m.player.damage_rank) ? ` · 全场第 ${m.player.damage_rank}` : ""}</small></td><td role="cell" headers="match-hex" data-label="局末海克斯"><div className="match-hexes">{[...new Set((m.player.augment_slots || []).filter((id): id is number => isNumber(id) && id > 0))].map(id => <button key={id} className={`hex-chip ${dictionary.augments[String(id)]?.rarity || ""}`} onClick={() => { track("hex_open", { detail: JSON.stringify({ from: "match-row", id }) }); setSelectedHex(id); }} title={dictionary.augments[String(id)]?.description || "查看海克斯说明"}><Asset quiet entry={dictionary.augments[String(id)]} name={hexName(id, dictionary)} /><span>{hexName(id, dictionary)}</span></button>)}{!m.player.augment_slots?.some(id => isNumber(id) && id > 0) && <span className="muted">暂无已观测记录</span>}</div></td><td role="cell" headers="match-action" data-label="战报"><button className="detail-button" aria-label={`查看 ${heroName(m.player, dictionary)} 单局战报`} onClick={() => { track("match_open", { detail: JSON.stringify({ from: "table", hero: heroName(m.player, dictionary), eligible: Boolean(m.stats_eligible) }) }); setSelectedMatch(m); }}>战报 ↗</button></td></tr>)}</tbody></table>{!shownMatches.length && <div className="empty-state">没有符合条件的对局，试着清除筛选。</div>}</div><div className="pagination"><button className="ghost" disabled={page === 1} onClick={() => setPage(p => p - 1)}>上一页</button><span>第 {page} / {pages} 页 · 每页 {pageSize} 场</span><button className="ghost" disabled={page === pages} onClick={() => setPage(p => p + 1)}>下一页</button></div><p className="panel-note match-delta-note">「海斗分」是该局为所在自然周周分贡献的分值：胜负项按胜/负取正负，表现项按单局表现累加（发挥好加得更多，赢局即使躺平也不扣分）；周内前12局保持原场次权重，之后按平方根曲线逐局递减，赢局收益和输局扣分同比缩小。同一周各局相加等于该周周分。标有<i className="night-inline">战斗之夜</i>的对局落在周五 20:00—周六 02:00，该局权重 ×1.5。有五杀的计分对局另加1.2分，战斗之夜加1.8分（已包含在该局海斗分内），同局多次五杀只奖励一局。10-22 之前的对局已计入冻结历史基准，不单独计分。</p></section>
    <QuickNav shareHref={shareHref} />
    <footer className="site-footer"><button className="ghost" onClick={openLobby}>← 返回玩家大厅</button><strong>海克斯战报馆</strong><p>MVP / ACE 为本工具自评 v0.5 · 海斗分为本站自建算法 · 英雄及游戏资产属于其权利人</p><a href="/assets/SOURCE-NOTICES.txt" target="_blank" rel="noreferrer">资源来源 ↗</a></footer>
    {selectedMatch && <div className="modal-backdrop" role="presentation" onClick={() => setSelectedMatch(null)}><section className="modal match-modal" role="dialog" aria-modal="true" aria-labelledby="match-modal-title" onClick={event => event.stopPropagation()}><header><div><p className="section-kicker">POST-GAME REPORT</p><h2 id="match-modal-title">{`${subjectName}的赛后战报`}</h2><p>{date(selectedMatch.started_ms, true)} · {isNumber(selectedMatch.duration) ? `${Math.floor(selectedMatch.duration / 60)} 分钟` : "—"} · {selectedMatch.patch || "—"}</p></div><button className="close-button" aria-label="关闭单局战报" autoFocus onClick={() => setSelectedMatch(null)}>×</button></header><div className="match-identity"><Hero player={selectedMatch.player} dictionary={dictionary} large /><span className={`result-tag ${selectedMatch.player.win ? "win" : "loss"}`}>{selectedMatch.player.win ? "胜利" : "失利"}</span>{evaluation(selectedMatch.player) && <span className="tag gold">{evaluation(selectedMatch.player)} · 自评 v0.5</span>}<Multikills player={selectedMatch.player} /></div><div className="detail-stats">{[["K / D / A", `${fmt(selectedMatch.player.kills)} / ${fmt(selectedMatch.player.deaths)} / ${fmt(selectedMatch.player.assists)}`], ["对英雄伤害", compact(selectedMatch.player.damage)], ["团队伤害占比", pct(selectedMatch.player.damage_share)], ["全场伤害排名", isNumber(selectedMatch.player.damage_rank) ? `第 ${selectedMatch.player.damage_rank}` : "—"], ["承受伤害", compact(selectedMatch.player.taken)], ["对队友治疗", compact(selectedMatch.player.heal)]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><h3>局末海克斯</h3><div className="detail-hexes">{[...new Set((selectedMatch.player.augment_slots || []).filter((id): id is number => isNumber(id) && id > 0))].map(id => <button className="hex-chip" key={id} onClick={() => { track("hex_open", { detail: JSON.stringify({ from: "match-modal", id }) }); setSelectedHex(id); }}><Asset quiet entry={dictionary.augments[String(id)]} name={hexName(id, dictionary)} />{hexName(id, dictionary)}</button>)}</div><h3>局末装备</h3><div className="equipment">{(selectedMatch.player.items || []).filter(id => id > 0).map((id, index) => <span className="equipment-item" key={`${id}-${index}`}><Asset entry={dictionary.items[String(id)]} name={dictionary.items[String(id)]?.name || `装备 #${id}`} /><span>{dictionary.items[String(id)]?.name || `装备 #${id}`}</span></span>)}{!selectedMatch.player.items?.some(id => id > 0) && <span className="muted">暂无装备记录。</span>}</div><p className="panel-note">{!selectedMatch.stats_eligible ? "该局不计入表现统计。" : ""}以上为当前分析对象的赛后记录；海克斯为局末持有，不表示选取顺序。</p>{subject&&<MatchRoster key={subject.id+selectedMatch.id} profile={subject} match={selectedMatch} profiles={profiles} visuals={visuals} dictionary={dictionary} onHex={setSelectedHex} onChoose={id=>{setSelectedMatch(null);chooseSubject(id);}}/>}</section></div>}
    {selectedHex !== null && <div className="modal-backdrop hex-backdrop" role="presentation" onClick={() => setSelectedHex(null)}><section className="modal hex-modal" role="dialog" aria-modal="true" aria-labelledby="hex-modal-title" onClick={event => event.stopPropagation()}><header><div className="hero-label"><Asset quiet entry={dictionary.augments[String(selectedHex)]} name={hexName(selectedHex, dictionary)} large /><div><p className="section-kicker">海克斯字典</p><h2 id="hex-modal-title">{hexName(selectedHex, dictionary)}</h2></div></div><button className="close-button" autoFocus aria-label="关闭海克斯说明" onClick={() => setSelectedHex(null)}>×</button></header><p className="hex-description">{dictionary.augments[String(selectedHex)]?.description || "当前字典尚未收录这枚海克斯的说明。"}</p><p className="panel-note">字典说明不代表本局实测伤害或触发次数；动态数值以游戏内说明为准。</p><button className="button" onClick={() => { track("hex_open", { detail: JSON.stringify({ from: "hex-modal", action: "jump-matches", id: selectedHex, name: hexName(selectedHex, dictionary) }) }); setQuery(hexName(selectedHex, dictionary)); setResult("all"); setAwardFilter("all"); setSelectedHex(null); setSelectedMatch(null); document.getElementById("matches")?.scrollIntoView({ behavior: "smooth" }); }}>查看当前对象的持有对局 ↗</button></section></div>}
  </main></RatingRulesContext.Provider>;
}
