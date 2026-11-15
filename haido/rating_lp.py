# -*- coding: utf-8 -*-
"""海斗分5.1：统一历史基准，胜负优先的温和周涨跌。

唯一评分入口；总分=冻结基准+历周累计+本周分。历史基准于用户确认后
按当前v0.5和固定标尺重算一次并重新冻结。周内前12局满权，其后平方根
递减；常规胜负与表现采用方案B×0.85，每次五杀独立+2、战斗之夜+3。
同周逐局贡献相加等于周分。普通构建不重建已有基准，不自动重校准。

规则按周起始时间选择：2026-11-09（北京时间）之前的周固定使用5.1参数，
之后使用5.2参数。历史周分数不因后续规则调整而改变。
"""
from __future__ import annotations

import json, math, statistics, datetime, collections, argparse, sys, hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCHES = ROOT / 'work' / 'players-preview-20261022' / 'public' / 'matches'
SNAPSHOT = ROOT / 'work/build/snapshot.full.json'
OUT = ROOT / 'haido' / 'haido_scores_lp.json'   # 与现役产物同路径，注入脚本与 build 链无需改名
BASELINE = ROOT / 'data/haido-baseline-v4.json'
WEEKLY_CALIBRATION = ROOT / 'data/haido-weekly-calibration-v04.json'
VERSION = '5.2'
LEGACY_VERSION = '5.1'
BASELINE_VERSION = '4.0'  # Formula identity; explicit reviewed migrations are recorded separately.
BEIJING = datetime.timezone(datetime.timedelta(hours=8))

# ── 基准分：沿用 LP 公式，公式本身不变 ──
BASE_LP = 1000.0
EDGE_WIN, EDGE_LOSS = 1.0, 0.6
W_EDGE, W_Z, DECAY, LOSS_DAMPING, PENTA_BONUS = 4.0, 1.5, 800.0, 0.4, 3.0

# ── 周维度（4.0 新增）；以下模块常量为5.1默认，历史周固定使用 ──
CUTOFF = int(datetime.datetime(2026, 10, 22, tzinfo=BEIJING).timestamp() * 1000)
WEEK_MS = 7 * 86400 * 1000
WEEK0 = int(datetime.datetime(2026, 10, 19, tzinfo=BEIJING).timestamp() * 1000)
WEEK_EDGE_LOSS = 0.95          # B方案：未加权胜负项零点0.95/1.95≈48.7%胜率
WEEK_CONF_K = 3.0              # B方案减轻少场折扣：9场0.75、38场约0.927
WEEK_VOLUME_FULL_GAMES = 12    # 4.9：满权局由9提至12，之后按sqrt(12/k)逐局递减（治"20局被砍到2/3"体感）
WEEK_VOLUME_POWER = 0.5       # 累计常规收益次线性增长，周总分不设硬上限
WEEK_VOLUME_FLOOR = None       # 5.1 无场次系数下限；5.2 起为0.65
WEEK_VOLATILITY = 0.85         # 用户要求在B方案基础上整体降15%，包括负分与五杀
WEEK_W = 7.0 * WEEK_VOLATILITY       # 有效胜负分+5.95/−5.6525
WEEK_Z_POS = 1.2 * WEEK_VOLATILITY   # 正表现有效系数1.02
WEEK_Z_NEG = 0.8 * WEEK_VOLATILITY   # 输局负表现有效系数0.68；赢局归零
WEEK_Z = WEEK_Z_POS            # 兼容旧字段名（public_rules 的 z_weight 仍指向正向系数）
WEEK_Z_LIMIT = 2.0             # 只限制单局异常信号；周分及历周累计均不封顶
WEEK_PENTA_BONUS = 2.0         # 每次五杀+2，战斗之夜+3；不乘场次、conf或0.85缩幅
WEEK_CAP = None                # 4.5 起取消单周上下限（4.2–4.4 为 ±100）：战绩越好就涨得越多，不做截断

# ── 4.4 战斗之夜：周五 20:00 起、周六 02:00 前（北京时间）的对局权重 ×1.5 ──
# 窗口来自实际开黑分布：上周该 6 小时占我方全部可评分对局的 40%，是唯一的高密度时段。
BATTLE_NIGHT_WEEKDAY = 4        # datetime.weekday()：周一=0，周五=4
BATTLE_NIGHT_START_HOUR = 20    # 含 20:00
BATTLE_NIGHT_END_HOUR = 2       # 不含 02:00（次日周六）
BATTLE_NIGHT_MULT = 1.5         # 该时段每局对周分的贡献倍数

CHAMPIONSHIP_START_MS = int(datetime.datetime(2026, 11, 16, tzinfo=BEIJING).timestamp() * 1000)
CHAMPIONSHIP_END_MS = CHAMPIONSHIP_START_MS + WEEK_MS
CHAMPIONSHIP_MULT = 2.0


# ── 按自然周分段的周分规则 ──
# namedtuple 而非 dataclass：构建链会以 module_from_spec 动态加载本文件，
# dataclass 解析字符串注解时需要 sys.modules[__module__]，该场景会失败。
# 一周计分所需的全部周分系数；基准与表现标尺不在此表内。
WeekRules = collections.namedtuple(
    'WeekRules',
    'version w edge_loss z_pos z_neg z_limit conf_k volume_full volume_power '
    'volume_floor penta_bonus cap')


# 5.2 自 2026-11-09 00:00（北京时间，WEEK0 起第 3 个自然周）生效。
RULE_52_START_MS = WEEK0 + 3 * WEEK_MS
CURRENT_RULES = WeekRules(
    version=VERSION, w=6.30, edge_loss=0.88, z_pos=1.10, z_neg=0.62,
    z_limit=WEEK_Z_LIMIT, conf_k=WEEK_CONF_K, volume_full=WEEK_VOLUME_FULL_GAMES,
    volume_power=WEEK_VOLUME_POWER, volume_floor=0.65,
    penta_bonus=WEEK_PENTA_BONUS, cap=WEEK_CAP)


def _legacy_rules():
    """历史周默认：动态读取模块常量，保持5.1行为及既有patch语义。"""
    return WeekRules(
        version=LEGACY_VERSION, w=WEEK_W, edge_loss=WEEK_EDGE_LOSS,
        z_pos=WEEK_Z_POS, z_neg=WEEK_Z_NEG, z_limit=WEEK_Z_LIMIT,
        conf_k=WEEK_CONF_K, volume_full=WEEK_VOLUME_FULL_GAMES,
        volume_power=WEEK_VOLUME_POWER, volume_floor=WEEK_VOLUME_FLOOR,
        penta_bonus=WEEK_PENTA_BONUS, cap=WEEK_CAP)


def rules_for(start_ms):
    """按周起始时间选规则；历史周固定5.1，生效周及以后用当前版本。"""
    return CURRENT_RULES if start_ms >= RULE_52_START_MS else _legacy_rules()


def week_start_ms(as_of_ms=None):
    if as_of_ms is None:
        as_of_ms = datetime.datetime.now(BEIJING).timestamp() * 1000
    day = datetime.datetime.fromtimestamp(as_of_ms / 1000, BEIJING)
    monday = day.replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=day.weekday())
    return int(monday.timestamp() * 1000)


def frozen_baseline(path, games):
    """Persist calibration and each player's base once; backfills never rewrite them."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    from snapshot_io import write_json
    spec = dict(version=BASELINE_VERSION, cutoff_ms=CUTOFF, week0_ms=WEEK0,
                weights=[BASE_LP, EDGE_WIN, EDGE_LOSS, W_EDGE, W_Z, DECAY, LOSS_DAMPING, PENTA_BONUS])
    path = Path(path)
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('spec') != spec:
            raise ValueError('baseline_rules_changed: explicit reviewed migration required')
    else:
        pool = [p for rows in games.values() for ts, p, _, _ in rows if ts < CUTOFF]
        if not pool:
            raise ValueError('empty_historical_pool: cannot establish baseline calibration')
        state = dict(spec=spec, pool=dict(mu=statistics.fmean(pool),
                     sigma=statistics.pstdev(pool) or 1.0, n=len(pool)), players={})
    mu, sigma = state['pool']['mu'], state['pool']['sigma']
    if not math.isfinite(mu) or not math.isfinite(sigma) or sigma <= 0:
        raise ValueError('invalid_baseline_calibration')
    for pid, rows in games.items():
        if pid not in state['players']:
            pre = [r for r in rows if r[0] < CUTOFF]
            base, wins = lp_base(pre, mu, sigma)
            state['players'][pid] = dict(base=base, n=len(pre), wins=wins)
    for entry in state['players'].values():
        if not math.isfinite(entry['base']) or entry['n'] < 0:
            raise ValueError('invalid_frozen_base')
    # Atomic writes; unchanged state preserves its mtime. No automatic rebasing.
    encoded = json.dumps(state, ensure_ascii=False, separators=(',', ':'))
    if not path.exists() or path.read_text(encoding='utf-8') != encoded:
        write_json(path, state)
    return state


def lp_base(rows, mu, sigma):
    n = len(rows)
    if n == 0:
        return BASE_LP, 0
    total_z = sum((p - mu) / sigma for _, p, _, _ in rows)
    edge = sum(EDGE_WIN if w else -EDGE_LOSS for _, _, w, _ in rows)
    penta = sum(1 for *_, pk in rows if pk > 0)
    damped = total_z if total_z >= 0 else total_z * LOSS_DAMPING
    lp = BASE_LP + (W_EDGE * edge + W_Z * damped) / (1 + n / DECAY) + PENTA_BONUS * penta
    return lp, sum(1 for _, _, w, _ in rows if w)


def rebuild_reviewed_baseline(path, games, calibration, preview, backup, build_id):
    """Explicit one-time migration; ordinary scoring never calls this path."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    from snapshot_io import write_json
    path = Path(path)
    original = path.read_bytes()
    previous_sha = hashlib.sha256(original).hexdigest()
    approved = json.loads(Path(preview).read_text(encoding='utf-8'))
    if approved.get('unchanged_private_sha256', {}).get('data/haido-baseline-v4.json') != previous_sha:
        raise ValueError('baseline_changed_since_review')
    if approved.get('sample_build_id') != build_id or approved.get('calibration') != calibration:
        raise ValueError('reviewed_baseline_inputs_changed')
    with zipfile.ZipFile(backup) as package:
        if package.testzip() is not None or package.read('data/haido-baseline-v4.json') != original:
            raise ValueError('baseline_backup_not_verified')
    old = json.loads(original)
    reviewed = {p['id']: p for p in approved['players']}
    if set(reviewed) != set(old['players']) or set(games) != set(reviewed):
        raise ValueError('reviewed_baseline_players_changed')
    players = {}
    for pid, rows in games.items():
        pre = [r for r in rows if r[0] < CUTOFF]
        base, wins = lp_base(pre, calibration['mu'], calibration['sigma'])
        entry = reviewed[pid]
        if (len(pre) != entry['history_games'] or wins != entry['history_wins'] or
                abs(base-entry['base_options']['full_refresh']) > 1e-8):
            raise ValueError('reviewed_baseline_sample_changed:' + pid)
        players[pid] = dict(base=base, n=len(pre), wins=wins)
    state = dict(spec=old['spec'], pool=calibration, players=players,
        migration=dict(version=VERSION, performance_version='0.5', method='full_refresh',
            sample_build_id=build_id, previous_sha256=previous_sha,
            reviewed_preview_sha256=hashlib.sha256(Path(preview).read_bytes()).hexdigest(),
            migrated_at=datetime.datetime.now(BEIJING).isoformat()))
    write_json(path, state)
    return state


def load_weekly_calibration(path=WEEKLY_CALIBRATION):
    """New award weights use their own frozen scale; never rebase existing players."""
    sys.path.insert(0, str(ROOT))
    from app.awards import VERSION as award_version, WEIGHTS, SHARE_CAPS
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    if (state.get('performance_version') != award_version or
            state.get('performance_weights') != WEIGHTS or
            state.get('performance_share_caps') != SHARE_CAPS or state.get('cutoff_ms') != CUTOFF):
        raise ValueError('weekly_calibration_rules_changed: explicit calibration required')
    pool = state.get('pool') or {}
    if (type(pool.get('n')) is not int or pool['n'] < 2 or
            any(type(pool.get(k)) not in (int, float) or not math.isfinite(pool[k]) for k in ('mu', 'sigma')) or
            pool['sigma'] <= 0):
        raise ValueError('invalid_weekly_calibration')
    return state


def battle_night_weight(ts_ms):
    """该对局计入周分时的权重：战斗之夜窗口内 ×BATTLE_NIGHT_MULT，其余 1.0。

    窗口按北京时间判断：周五 20:00（含）到周六 02:00（不含）。跨零点部分靠「周五 20 点后」
    与「周六 2 点前」两支拼起来，所以窗口固定 6 小时，不受跨周影响（周五到周六不会跨自然周）。
    """
    if not ts_ms:
        return 1.0
    moment = datetime.datetime.fromtimestamp(ts_ms / 1000, BEIJING)
    week_day, hour = moment.weekday(), moment.hour
    if week_day == BATTLE_NIGHT_WEEKDAY and hour >= BATTLE_NIGHT_START_HOUR:
        return BATTLE_NIGHT_MULT
    if week_day == (BATTLE_NIGHT_WEEKDAY + 1) % 7 and hour < BATTLE_NIGHT_END_HOUR:
        return BATTLE_NIGHT_MULT
    return 1.0


def championship_weight(ts_ms):
    """BLG 夺冠周按开局时间生效，补录时沿用原对局日期。"""
    return CHAMPIONSHIP_MULT if CHAMPIONSHIP_START_MS <= ts_ms < CHAMPIONSHIP_END_MS else 1.0


def weekly_performance_z(performance, mu, sigma, params=None):
    """Only the weekly signal is bounded; frozen-base z and match awards stay intact."""
    rule = params or _legacy_rules()
    return max(-rule.z_limit, min(rule.z_limit, (performance - mu) / sigma))


def match_performance_signal(z, win, params=None):
    """单局表现项系数（未乘场次与收敛）。

    5.0 起正负分离：发挥好就按 z_pos 加；发挥差时赢局归零（赢了不反扣，
    只是少加），输局才按 z_neg 缩扣。这样「赢 + 躺平」永远不小于纯胜负分。
    """
    rule = params or _legacy_rules()
    if z >= 0:
        return rule.z_pos * z
    return 0.0 if win else rule.z_neg * z


def volume_multiplier(game_index, params=None):
    """One-based chronological index within a calendar week, excluding baseline games.

    5.2 起给场次系数设下限，打得多也不会一路衰减到接近 0。
    """
    if type(game_index) is not int or game_index < 1:
        raise ValueError('invalid_week_game_index')
    rule = params or _legacy_rules()
    value = min(1.0, (rule.volume_full / game_index) ** rule.volume_power)
    return max(rule.volume_floor, value) if rule.volume_floor is not None else value


def week_terms(items, mu, sigma, params=None):
    """一周的胜负项、表现项与周分（唯一实现，周榜与每局分项共用）。

    常规胜负与表现同时乘周内场次系数d(k)，前12局为1，之后sqrt(12/k)。
    表现项正负分离（5.0）：z≥0 按 z_pos 加，z<0 时赢局归零、输局按 z_neg 缩扣。
    每次五杀独立+2并乘战斗之夜权重，不乘场次系数与conf；周分不封顶。
    内部排序让快照倒序、输入打乱和不同构建入口得到相同结果。
    params 由 week_scores 按周起始时间选择，历史周固定5.1，生效周起用5.2。
    """
    rule = params or _legacy_rules()
    items = sorted(items)
    n = len(items)
    night_weights = [battle_night_weight(ts) for ts, _, _, _ in items]
    weights = [night * championship_weight(ts) for night, (ts, _, _, _) in zip(night_weights, items)]
    volumes = [volume_multiplier(i+1, rule) for i in range(n)]
    regular_weights = [w*d for w, d in zip(weights, volumes)]
    wins = sum(1 for _, _, w, _ in items if w)
    loss = n - wins
    raw_edge = wins - rule.edge_loss * loss
    weighted_wins = math.fsum(w for w, (_, _, win, _) in zip(regular_weights, items) if win)
    weighted_losses = math.fsum(w for w, (_, _, win, _) in zip(regular_weights, items) if not win)
    edge = weighted_wins - rule.edge_loss * weighted_losses
    conf = n / (n + rule.conf_k)
    avg_z = math.fsum(w * (p - mu) / sigma
                      for w, (_, p, _, _) in zip(night_weights, items)) / n if n else 0.0
    battle = [row for w, row in zip(night_weights, items) if w > 1.0]
    win_part = rule.w * edge * conf
    signals = [(w, weekly_performance_z(p, mu, sigma, rule), bool(win))
               for w, (_, p, win, _) in zip(regular_weights, items)]
    sum_z = math.fsum(w * z for w, z, _ in signals)                      # 全部局的原始 z（含赢局负 z）
    sum_z_pos = math.fsum(w * z for w, z, _ in signals if z >= 0)        # 正向端
    sum_z_neg = math.fsum(w * z for w, z, win in signals if z < 0 and not win)  # 负向端：只含输局
    perf_raw = math.fsum(w * match_performance_signal(z, win, rule) for w, z, win in signals) * conf
    # 每局的发挥都参与，不因其它局的输赢取消本局表现收益。
    perf_part = perf_raw
    penta_games = sum(pk > 0 for _, _, _, pk in items)
    penta_count = sum(pk for _, _, _, pk in items)
    penta_part = math.fsum(w * rule.penta_bonus * pk for w, (_, _, _, pk) in zip(weights, items) if pk > 0)
    raw = win_part + perf_part + penta_part
    clamped = raw if rule.cap is None else max(-rule.cap, min(rule.cap, raw))
    return dict(week_items=items, weights=weights, volumes=volumes,
                regular_weights=regular_weights, volume_average=math.fsum(volumes)/n if n else 0,
                weighted_wins=weighted_wins, weighted_losses=weighted_losses,
                n=n, wins=wins, loss=loss,
                edge=edge, raw_edge=raw_edge, conf=conf,
                avg_z=avg_z, performance_sum_z=sum_z,
                performance_sum_pos=sum_z_pos, performance_sum_neg=sum_z_neg,
                performance_sum_effective=rule.z_pos*sum_z_pos + rule.z_neg*sum_z_neg,
                win_part=win_part, perf_raw=perf_raw, perf_part=perf_part,
                penta_games=penta_games, penta_count=penta_count, penta_part=penta_part,
                battle_night_games=len(battle),
                battle_night_wins=sum(1 for _, _, win, _ in battle if win),
                raw=raw, clamped=clamped, score=round(clamped, 1))


def week_scores(rows, mu, sigma):
    """按自然周汇总 10.22 之后的战绩 → {week_index: {...}}"""
    buckets = collections.defaultdict(list)
    for r in rows:
        if r[0] < CUTOFF:
            continue
        buckets[int((r[0] - WEEK0) // WEEK_MS)].append(r)
    out = {}
    for idx, items in buckets.items():
        t = week_terms(items, mu, sigma, rules_for(WEEK0 + idx * WEEK_MS))
        out[idx] = dict(week=idx, n=t['n'], wins=t['wins'], loss=t['loss'],
                        win_rate=round(t['wins'] / t['n'], 3) if t['n'] else None,
                        edge=round(t['edge'], 2), raw_edge=round(t['raw_edge'], 2),
                        battle_night_games=t['battle_night_games'],
                        battle_night_wins=t['battle_night_wins'],
                        conf=round(t['conf'], 3),
                        avg_z=round(t['avg_z'], 2),
                        win_part=round(t['win_part'], 1), perf_part=round(t['perf_part'], 1),
                        confidence_raw=t['conf'], avg_z_raw=t['avg_z'],
                        volume_average=t['volume_average'], weighted_wins=t['weighted_wins'],
                        weighted_losses=t['weighted_losses'],
                        performance_sum_z=t['performance_sum_z'],
                        performance_sum_pos=round(t['performance_sum_pos'], 6),
                        performance_sum_neg=round(t['performance_sum_neg'], 6),
                        performance_sum_effective=round(t['performance_sum_effective'], 6),
                        penta_games=t['penta_games'], penta_count=t['penta_count'], penta_part=t['penta_part'],
                        edge_raw=t['edge'],
                        win_part_raw=t['win_part'], perf_part_raw=t['perf_part'],
                        raw_score=round(t['raw'], 6),
                        score=t['score'])
    return out


def match_contributions(rows, ids, mu, sigma, *, with_details=False):
    """每局对所在自然周周分的贡献 → {match_id: delta}

    同一周内按周公式的线性分项拆到每一局：胜负项按每局胜/负直接取，表现项取
    conf×d(k)×match_performance_signal(z_i, 胜否)（正负分离：赢局负 z 归零、输局按 0.8 缩扣），
    胜负与表现同比递减，不受周胜率屏蔽；战斗之夜的对局整项再乘 1.5。分项之和直接就是周分，
    同周各局相加即等于该周周分。
    """
    buckets = collections.defaultdict(list)
    for row, mid in zip(rows, ids):
        if row[0] < CUTOFF:
            continue
        buckets[int((row[0] - WEEK0) // WEEK_MS)].append((row, mid))
    out, volumes, indices = {}, {}, {}
    for week_index, items in sorted(buckets.items()):
        items.sort(key=lambda item: (item[0], item[1]))
        rule = rules_for(WEEK0 + week_index * WEEK_MS)
        terms = week_terms([row for row, _ in items], mu, sigma, rule)
        parts = []
        for index, ((row, mid), weight, volume) in enumerate(zip(items, terms['weights'], terms['volumes']), 1):
            win_i = rule.w * (1.0 if row[2] else -rule.edge_loss) * terms['conf']
            perf_i = match_performance_signal(weekly_performance_z(row[1], mu, sigma, rule), bool(row[2]), rule) * terms['conf']
            penta_i = rule.penta_bonus * row[3]
            parts.append([mid, ((win_i + perf_i) * volume + penta_i) * weight])
            volumes[mid], indices[mid] = volume, index
        total = math.fsum(value for _, value in parts)
        capped = rule.cap is not None and total and abs(total) > rule.cap
        scale = terms['clamped'] / total if capped else 1.0
        exact = [value * scale for _, value in parts]
        for part, value in zip(parts, exact):
            part[1] = round(value, 1)
        if parts:
            residual = int(round((terms['score'] - math.fsum(value for _, value in parts)) * 10))
            # 分散十分位舍入差，每局与精确贡献相差不到0.1，避免大周把残差全塞给一局。
            order = sorted(range(len(parts)), key=lambda i: (exact[i] - parts[i][1], parts[i][0]),
                           reverse=residual > 0)
            step = 0.1 if residual > 0 else -0.1
            for i in order[:abs(residual)]:
                parts[i][1] = round(parts[i][1] + step, 1)
        out.update({mid: value for mid, value in parts})
    return (out, volumes, indices) if with_details else out


def period_score(rows, base, mu, sigma, as_of_ms, start_ms=None):
    """Reconstruct each calendar week once; no mutable += ledger or duplicate settlement."""
    rows = [r for r in rows if r[0] < as_of_ms]
    start = week_start_ms(as_of_ms) if start_ms is None else start_ms
    current = (start - WEEK0) // WEEK_MS
    weeks = week_scores(rows, mu, sigma)
    past = [dict(start_ms=WEEK0+i*WEEK_MS, end_ms=WEEK0+(i+1)*WEEK_MS,
                 games=w['n'], wins=w['wins'], delta=w['score'],
                 battle_night_games=w.get('battle_night_games', 0),
                 penta_games=w.get('penta_games', 0), penta_count=w.get('penta_count', 0), penta_part=w.get('penta_part', 0))
            for i, w in sorted(weeks.items()) if i < current]
    settled = round(math.fsum(w['delta'] for w in past), 1)
    week = weeks.get(current) or {}
    delta = week.get('score', 0)
    return dict(base=round(base, 1), settled_delta=settled, settled_weeks=past,
                week_start_score=round(base+settled, 1), week_delta=delta,
                score=round(base+settled+delta, 1), this_week=week,
                week_start_ms=start, week_end_ms=start+WEEK_MS)


def public_rules():
    """前端展示当前生效规则；历史周参数不随规则升级变化，不另设 UI 公式。"""
    sys.path.insert(0, str(ROOT))
    from app.awards import VERSION as award_version, WEIGHTS, SHARE_CAPS
    rule = CURRENT_RULES
    return dict(version=VERSION, total_policy='cumulative_calendar_weeks', cutoff_ms=CUTOFF,
        rule_effective_from_ms=RULE_52_START_MS, legacy_version=LEGACY_VERSION,
        base=dict(origin=BASE_LP, loss_ratio=EDGE_LOSS, edge_weight=W_EDGE, z_weight=W_Z,
                  decay=DECAY, loss_damping=LOSS_DAMPING, penta_bonus=PENTA_BONUS),
        week=dict(win_weight=rule.w, loss_ratio=rule.edge_loss, z_weight=rule.z_pos,
                  z_weight_neg=rule.z_neg, z_weight_win_neg=0.0,
                  win_zero_rate=round(100*rule.edge_loss/(1+rule.edge_loss), 1),
                  confidence_k=rule.conf_k, z_limit=rule.z_limit,
                  volume_full_games=rule.volume_full, volume_power=rule.volume_power,
                  volume_floor=rule.volume_floor,
                  penta_bonus=rule.penta_bonus, penta_unit='occurrence',
                  performance_aggregation='per_match_sum', cap=rule.cap,
                  championship=dict(start_ms=CHAMPIONSHIP_START_MS, end_ms=CHAMPIONSHIP_END_MS,
                                    mult=CHAMPIONSHIP_MULT),
                  battle_night=dict(weekday=BATTLE_NIGHT_WEEKDAY, start_hour=BATTLE_NIGHT_START_HOUR,
                                    end_hour=BATTLE_NIGHT_END_HOUR, mult=BATTLE_NIGHT_MULT)),
        performance_version=award_version, performance_share_caps=SHARE_CAPS,
        performance_weights=WEIGHTS)


def main() -> int:
    global CUTOFF, WEEK0
    ap = argparse.ArgumentParser()
    ap.add_argument('--matches', type=Path, default=MATCHES)
    ap.add_argument('--snapshot', type=Path, default=SNAPSHOT)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--bundle', type=Path, help='构建链产物：work/build/cache/details.bundle.json')
    ap.add_argument('--baseline', type=Path, help='私有冻结基准；正式默认data/haido-baseline-v4.json')
    ap.add_argument('--weekly-calibration', type=Path, default=WEEKLY_CALIBRATION,
                    help='周分专用冻结标尺，与原历史基准标尺分开')
    ap.add_argument('--init-baseline', action='store_true', help='仅首次获授权建立正式冻结基准；不覆盖已有文件')
    ap.add_argument('--rebuild-baseline-from-preview', type=Path,
                    help='仅明确授权迁移时：核对已审阅全量重算试算，写入一次并重新冻结')
    ap.add_argument('--baseline-backup', type=Path, help='迁移前已验证的恢复ZIP')
    ap.add_argument('--as-of-ms', type=int, help='计分时刻，默认当前北京时间；回放测试显式传入')
    ap.add_argument('--cutoff', type=int, default=CUTOFF)
    ap.add_argument('--week0', type=int, default=WEEK0)
    ap.add_argument('--window', type=int, choices=[1], default=1, help='兼容旧参数；4.1总分累计所有已结束周')
    args = ap.parse_args()
    CUTOFF, WEEK0 = args.cutoff, args.week0
    as_of_ms = args.as_of_ms if args.as_of_ms is not None else int(datetime.datetime.now(BEIJING).timestamp()*1000)

    snap = json.loads(args.snapshot.read_text(encoding='utf-8'))
    names = {p['id']: p['name'] for p in snap.get('players') or []}

    if args.bundle:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from detail_bundle import load_bundle
        details = load_bundle(args.bundle, snap['build_id']).values()
    else:
        details = (json.loads(path.read_text(encoding='utf-8'))
                   for path in sorted(args.matches.glob('m-*.json')))

    games = collections.defaultdict(list)
    match_ids = collections.defaultdict(list)
    for pid in names:
        games[pid] = []
    for detail in details:
        ts = detail.get('started_ms') or 0
        if ts >= as_of_ms:
            continue
        for p in detail.get('players') or []:
            pid = p.get('profile_id')
            perf = (p.get('performance') or {}).get('score')
            if not pid or not isinstance(perf, (int, float)):
                continue
            pk = p.get('penta_kills') or 0
            games[pid].append((ts, float(perf), bool(p.get('win')),
                               int(pk) if isinstance(pk, (int, float)) else 0))
            match_ids[pid].append(str(detail.get('id') or ''))

    baseline_path = args.baseline or (BASELINE if args.snapshot.resolve() == SNAPSHOT.resolve()
                                     else args.out.with_suffix('.baseline.json'))
    if args.init_baseline and baseline_path.exists():
        raise ValueError('baseline_already_exists: refusing to overwrite frozen state')
    if baseline_path.resolve() == BASELINE.resolve() and not baseline_path.exists() and not args.init_baseline:
        raise ValueError('missing_frozen_baseline: restore backup; first migration requires --init-baseline')
    weekly_calibration = load_weekly_calibration(args.weekly_calibration)
    weekly_pool = weekly_calibration['pool']
    if args.rebuild_baseline_from_preview:
        if args.init_baseline or not args.baseline_backup:
            raise ValueError('reviewed_baseline_requires_verified_backup')
        sys.path.insert(0, str(ROOT / 'app'))
        from public_site import _exclusive_lock
        with _exclusive_lock(ROOT / 'work/build/release.lock') as acquired:
            if not acquired:
                raise RuntimeError('release_lock_busy')
            baseline = rebuild_reviewed_baseline(baseline_path, games, weekly_pool,
                args.rebuild_baseline_from_preview, args.baseline_backup, snap['build_id'])
    else:
        baseline = frozen_baseline(baseline_path, games)
    mu, sigma = weekly_pool['mu'], weekly_pool['sigma']
    print(f"周分冻结标尺：{weekly_pool['n']} 人次，均值 {mu:.2f}，σ {sigma:.2f}；读取当前冻结历史基准")
    start_ms = week_start_ms(as_of_ms)
    current_rule = rules_for(start_ms)
    cur_week = int((start_ms - WEEK0) // WEEK_MS)
    print(f'当前周序号 {cur_week}（0 = 10.19 那一周）；当周规则 {current_rule.version}'
          f'（历史周固定 {LEGACY_VERSION}）')

    result = []
    for pid, rows in games.items():
        pairs = sorted(zip(rows, match_ids[pid]), key=lambda pair: pair[0])
        rows = [row for row, _ in pairs]
        ids = [mid for _, mid in pairs]
        frozen = baseline['players'][pid]
        base = frozen['base']
        period = period_score(rows, base, mu, sigma, as_of_ms)
        adj, total, this_week = period['week_delta'], period['score'], period['this_week']
        n_all = len(rows)
        wins_all = sum(1 for _, _, w, _ in rows if w)
        deltas, volumes, indices = match_contributions(rows, ids, mu, sigma, with_details=True)
        result.append(dict(
            id=pid, name=names.get(pid, pid),
            n=n_all, n_base=frozen['n'],
            base=round(base, 1),
            week_adj=round(adj, 1),
            score=round(total, 1),
            this_week=this_week,
            match_deltas=dict(sorted(deltas.items())),
            match_volume_multipliers=volumes, match_week_indices=indices,
            match_weights={mid: battle_night_weight(row[0]) for row, mid in zip(rows, ids)
                           if row[0] >= CUTOFF},
            match_championship_multipliers={mid: weight for row, mid in zip(rows, ids)
                                           if (weight := championship_weight(row[0])) > 1},
            match_penta_bonuses={mid: WEEK_PENTA_BONUS * row[3] * battle_night_weight(row[0]) * championship_weight(row[0])
                                for row, mid in zip(rows, ids) if row[0] >= CUTOFF and row[3] > 0},
            settled_delta=period['settled_delta'], settled_weeks=period['settled_weeks'],
            calculation=dict(confidence=this_week.get('confidence_raw', 0), avg_z=this_week.get('avg_z_raw'),
                performance_sum_z=this_week.get('performance_sum_z', 0),
                performance_sum_pos=this_week.get('performance_sum_pos', 0),
                performance_sum_neg=this_week.get('performance_sum_neg', 0),
                performance_sum_effective=this_week.get('performance_sum_effective', 0),
                volume_average=this_week.get('volume_average', 0),
                weighted_wins=this_week.get('weighted_wins', 0), weighted_losses=this_week.get('weighted_losses', 0),
                penta_games=this_week.get('penta_games', 0), penta_count=this_week.get('penta_count', 0), penta_part=this_week.get('penta_part', 0),
                win_part=this_week.get('win_part_raw', 0), performance_part=this_week.get('perf_part_raw', 0),
                raw_delta=this_week.get('win_part_raw', 0)+this_week.get('perf_part_raw', 0)+this_week.get('penta_part', 0), cap=WEEK_CAP,
                loss_ratio=current_rule.edge_loss,
                zero_win_rate=round(100*current_rule.edge_loss/(1+current_rule.edge_loss), 1),
                effective_edge=this_week.get('edge_raw', 0),
                battle_night_games=this_week.get('battle_night_games', 0),
                battle_night_wins=this_week.get('battle_night_wins', 0),
                battle_night_mult=BATTLE_NIGHT_MULT,
                calibration=dict(mean=mu, sigma=sigma)),
            tier='stable' if n_all >= 100 else ('provisional' if n_all >= 5 else 'unrated'),
            # ── 以下字段为兼容注入脚本 / 现役产物结构而保留 ──
            haido=round(total, 1),
            lp=round(total, 1),
            avg_p=round(statistics.fmean(p for _, p, _, _ in rows), 1) if rows else None,
            win_rate=round(wins_all / n_all, 3) if n_all else None,
            ci=round(200 / math.sqrt(n_all)) if n_all else None,
            carry=None,
            week_games=this_week.get('n', 0),
            week_wins=this_week.get('wins', 0),
            week_win_rate=this_week.get('win_rate'),
            week_delta=round(adj, 1),
            lp_prev=period['week_start_score'],
            week_start_ms=start_ms, week_end_ms=start_ms + WEEK_MS,
        ))
    result.sort(key=lambda r: -r['score'])

    print(f"\n{'#':<3}{'玩家':<14}{'基准':>7}{'周分':>7}{'显示':>7}{'本周场':>6}{'本周胜率':>8}{'本周分':>7}")
    for i, r in enumerate(result, 1):
        tw = r['this_week'] or {}
        wr = f"{tw['win_rate']*100:.0f}%" if tw.get('win_rate') is not None else '—'
        print(f"{i:<3}{r['name'][:12]:<14}{r['base']:>7.0f}{r['week_adj']:>+7.1f}{r['score']:>7.0f}"
              f"{tw.get('n', 0):>6}{wr:>8}{tw.get('score', 0):>+7.1f}")

    args.out.write_text(json.dumps({
        'version': VERSION, 'cutoff_ms': CUTOFF, 'week0_ms': WEEK0,
        'week_start_ms': start_ms, 'week_end_ms': start_ms + WEEK_MS, 'baseline_policy': 'frozen',
        'as_of_ms': as_of_ms, 'total_policy': 'cumulative_calendar_weeks', 'rules': public_rules(),
        'params': {'week_edge_loss': current_rule.edge_loss, 'week_conf_k': current_rule.conf_k,
                   'week_w': current_rule.w, 'week_z': current_rule.z_pos, 'week_z_neg': current_rule.z_neg,
                   'week_z_win_neg': 0.0,
                   'week_z_limit': current_rule.z_limit, 'week_cap': current_rule.cap,
                   'week_penta_bonus': current_rule.penta_bonus,
                   'week_volume_full_games': current_rule.volume_full,
                   'week_volume_power': current_rule.volume_power,
                   'week_volume_floor': current_rule.volume_floor,
                   'rule_effective_from_ms': RULE_52_START_MS, 'legacy_version': LEGACY_VERSION,
                   'battle_night_mult': BATTLE_NIGHT_MULT,
                   'battle_night_window': [BATTLE_NIGHT_WEEKDAY, BATTLE_NIGHT_START_HOUR,
                                           BATTLE_NIGHT_END_HOUR],
                   'base_w_z': W_Z, 'base_loss_damping': LOSS_DAMPING},
        'pool': {'mu': round(mu, 3), 'sigma': round(sigma, 3), 'n': weekly_pool['n']},
        'players': result}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'\n写出 {args.out.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
