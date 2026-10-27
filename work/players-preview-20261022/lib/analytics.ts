// 访问打点：只写不读，且默认关闭。
// 源码里不写任何云应用凭据：没有配置 VITE_ANALYTICS_ENDPOINT / VITE_ANALYTICS_KEY 时，
// track() 直接返回，不发任何请求，也就不记录任何访客信息。
// 需要统计的部署方自行在 .env.local（不入库）里填自己的 endpoint 与 publishable key，
// 填好后数据落在自己云数据库的 `visits` 表；该表只对匿名角色开放 INSERT，
// 前端读不到任何一行，所以不存在「站点能读出别人访问记录」的可能。查询见 docs/ANALYTICS.md。
import {createWorkBuddyCloud} from '@tencent-ai/workbuddy-cloud-sdk';

type AnalyticsEnv = {
  VITE_ANALYTICS_ENDPOINT?: string;
  VITE_ANALYTICS_KEY?: string;
};

// 构建期由 Vite 注入；未配置时为空字符串。
const ENV: AnalyticsEnv = (import.meta as unknown as {env?: AnalyticsEnv}).env ?? {};

const CONFIG = {
  endpoint: ENV.VITE_ANALYTICS_ENDPOINT ?? '',
  publishableKey: ENV.VITE_ANALYTICS_KEY ?? '',
};

// 缺任一项就视为未启用统计，整套打点变成空操作。
const ENABLED = Boolean(CONFIG.endpoint && CONFIG.publishableKey);

let client: ReturnType<typeof createWorkBuddyCloud> | null = null;
function cloud() {
  if (!client) client = createWorkBuddyCloud(CONFIG);
  return client;
}

// visits 表没有生成 schema 类型，这里放宽 insert 的入参；运行时行为不受影响
type AnyRow = Record<string, string | null>;
type VisitWriter = {insert(row: AnyRow): Promise<unknown>};
function visits() {
  return cloud().database.from('visits') as unknown as VisitWriter;
}

// 同一事件在同一毫秒级的重复触发合并，避免 scroll 之类把表刷爆
const recent = new Map<string, number>();

function visitorId(): string {
  try {
    const key = 'hextech.visitor-v2';
    const saved = localStorage.getItem(key);
    if (saved) return saved;
    const fresh =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `v-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(key, fresh);
    return fresh;
  } catch {
    // 隐私模式 / 禁用存储：退化成一次性 ID，不阻断打点
    return 'unknown';
  }
}

/**
 * 现行事件白名单。分三层：
 * - 页面级：打开、切人、会话结束
 * - 站点级（这几天新增的功能）：大厅分区、周榜、回顾、并肩、成就、规则、氛围、版本情报
 * - 个人页交互：筛选、翻页、单局战报、海克斯说明、分享
 * 只保留对判断"没人用 / 有人用"有意义的事件，不逐按钮铺点。
 */
export type VisitEvent =
  // 页面级
  | 'page_view'
  | 'subject_view'
  | 'session_end'
  // 大厅与导航
  | 'nav_jump'
  | 'lobby_sort'
  | 'lobby_star'
  | 'lobby_shuffle'
  | 'weekly_hall_view'
  | 'weekly_week'
  | 'weekly_open'
  | 'weekly_copy'
  // 当晚 / 多人回顾
  | 'recap_mode'
  | 'recap_scope'
  | 'recap_share'
  | 'recap_copy'
  // 并肩档案
  | 'pair_select'
  | 'pair_poster'
  | 'pair_link'
  // 朋友成就馆
  | 'achievement_pick'
  | 'achievement_filter'
  // 评分规则
  | 'rating_rules'
  // 皮肤 / BGM
  | 'skin_pick'
  | 'bgm_toggle'
  // 版本情报
  | 'intel_tab'
  | 'intel_patch'
  | 'intel_detail'
  // 个人页交互
  | 'hero_filter'
  | 'hero_expand'
  | 'chart_tap'
  | 'refresh_click'
  | 'match_open'
  | 'match_filter'
  | 'match_search'
  | 'companion_sort'
  | 'hex_open'
  | 'share_click';

type Extra = {
  detail?: string | null;
  subject_id?: string | null;
  subject_name?: string | null;
};

/**
 * 记录一次访问事件。
 * 全程吞异常：统计失败绝不能影响页面本身。
 * @param minGapMs 同一事件的最小间隔，0 表示不去重
 */
export function track(event: VisitEvent, extra: Extra = {}, minGapMs = 0): void {
  if (!ENABLED) return;
  try {
    if (minGapMs > 0) {
      const fingerprint = `${event}|${extra.detail ?? ''}`;
      const now = Date.now();
      const last = recent.get(fingerprint) ?? 0;
      if (now - last < minGapMs) return;
      recent.set(fingerprint, now);
    }
    const row = {
      visitor_id: visitorId(),
      event,
      detail: extra.detail ?? null,
      subject_id: extra.subject_id ?? null,
      subject_name: extra.subject_name ?? null,
      path: window.location.pathname || null,
      referrer: document.referrer || null,
      user_agent: navigator.userAgent || null,
    };
    // 不 await：打点不该拖慢任何交互
    void visits()
      .insert(row)
      .then(
        () => {},
        () => {},
      );
  } catch {
    /* 统计失败一律沉默 */
  }
}

/** 切换当前分析对象 */
export function trackSubject(id: string, name: string | null): void {
  track('subject_view', { subject_id: id, subject_name: name });
}

/**
 * 会话结束：上报停留秒数与最大滚动深度。
 * 用 visibilitychange + pagehide 双保险；直接杀进程会漏，属已知口径。
 */
export function trackSession(onEnd?: (seconds: number) => void): () => void {
  const startedAt = Date.now();
  let maxDepth = 0;
  let reported = false;

  const measure = () => {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const ratio = scrollable > 80 ? window.scrollY / scrollable : 1;
    maxDepth = Math.max(maxDepth, Math.min(1, Math.max(0, ratio)));
  };
  const flush = () => {
    if (reported) return;
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    // 3 秒以内的多半是误触或跳转，不算一次会话
    if (seconds < 3) return;
    reported = true;
    measure();
    track('session_end', {
      detail: JSON.stringify({seconds, depth: Number(maxDepth.toFixed(2))}),
    });
    onEnd?.(seconds);
  };

  window.addEventListener('scroll', measure, {passive: true});
  const onVisibility = () => {
    if (document.visibilityState === 'hidden') {
      measure();
      flush();
    }
  };
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('pagehide', flush);

  return () => {
    window.removeEventListener('scroll', measure);
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('pagehide', flush);
  };
}
