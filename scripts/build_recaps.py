"""Build lazy night/team recaps, with Shanghai 06:00 boundary and exact teams."""
import json
import sys
import argparse
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from snapshot_io import FULL, API, ROOT, load_full, write_json
from project_paths import FRONTEND

sys.path.insert(0, str(ROOT))
from haido.rating_lp import week_start_ms, WEEK_MS
from weekly_award import most_roided

TZ = timezone(timedelta(hours=8))
MATCHES = FRONTEND / 'public/matches'


def night_key(started_ms):
    value = datetime.fromtimestamp(started_ms / 1000, TZ)
    if 6 <= value.hour < 18:
        return None
    return (value - timedelta(hours=6)).strftime('%Y-%m-%d')


def eligible_matches(snapshot):
    """这次构建要读明细的对局：任一已建档玩家近况里 stats_eligible 为真。"""
    return {m['id'] for p in snapshot['players'] for m in p.get('recent', []) if m.get('stats_eligible')}


def match_details(snapshot, details=None, match_dir=MATCHES):
    """对局 id → 明细；已有 bundle 时只挑这次需要的，不再重复读盘。"""
    if details is not None:
        return {mid: details[mid] for mid in sorted(eligible_matches(snapshot))}
    return {mid: json.loads((Path(match_dir) / (mid + '.json')).read_text(encoding='utf-8'))
            for mid in sorted(eligible_matches(snapshot))}


def snapshot_as_of(snapshot):
    """快照自带的统计时刻（毫秒）：先看毫秒字段，再看 public_site 写的 UTC ISO 字段。"""
    for key in ('as_of_ms', 'updated_ms'):
        value = snapshot.get(key)
        if type(value) is int and value > 0:
            return value
    for key in ('updated_at', 'generated_at'):
        value = snapshot.get(key)
        if isinstance(value, str):
            try:
                return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
            except ValueError:
                continue
    return None


def week_roided(snapshot, details, as_of_ms):
    """本周（北京时间周一 00:00 起）单局伤害占比最高的已建档玩家；无候选为 None。

    候选只从快照里的已建档名册（`snapshot['players']` 的 id）里选，路人即使占比更高也不进榜。
    """
    known = {p['id'] for p in snapshot['players']}
    start = week_start_ms(as_of_ms)
    # 进行中的周截到本次构建的 as_of；跨过下周一则截到周界，保证只算一个自然周。
    through = min(start + WEEK_MS, as_of_ms)
    pick = most_roided(details.values(), start, through, allowed_ids=known)
    if pick is None:
        return None
    # most_roided 只带回明细自己的 match_key/id；补一条 public match_id 方便前端跳战报。
    key = pick.get('match_key')
    for mid, detail in details.items():
        if key and isinstance(detail, dict) and key in (detail.get('match_key'), detail.get('id')):
            pick['match_id'] = mid
            break
    return pick


def recap_rows(snapshot, match_dir=MATCHES, details=None):
    eligible = eligible_matches(snapshot)
    known = {p['id'] for p in snapshot['players']}
    rows = []
    for mid in sorted(eligible):
        detail = details[mid] if details is not None else json.loads((Path(match_dir) / (mid + '.json')).read_text(encoding='utf-8'))
        # One row per team: friends facing each other must never become teammates.
        for team in (100, 200):
            members = [p for p in detail['players'] if p.get('profile_id') in known and p['team'] == team]
            if len(members) < 2:
                continue
            if len({p['win'] for p in members}) != 1:
                raise ValueError('mixed_team_results')
            people = [{k: p.get(k) for k in ('profile_id', 'champion_id', 'kills', 'deaths', 'assists', 'damage', 'taken', 'heal', 'penta_kills', 'performance')} for p in members]
            rows.append({'id': mid + '-' + str(team), 'match_id': mid, 'started_ms': detail['started_ms'],
                         'duration': detail['duration'], 'win': members[0]['win'], 'members': people})
    return sorted(rows, key=lambda r: (r['started_ms'], r['id']), reverse=True)


def night_entry(key, games):
    """index.json 里的一晚：人数、场次与起止时刻，仍只算已建档成员。"""
    people = sorted({p['profile_id'] for r in games for p in r['members']})
    return {'date': key, 'friday': datetime.fromisoformat(key).weekday() == 4,
            'games': len({r['match_id'] for r in games}), 'players': people,
            'player_games': dict(Counter(p['profile_id'] for r in games for p in r['members'])),
            'started_ms': min(r['started_ms'] for r in games),
            'ended_ms': max(r['started_ms'] + r['duration'] * 1000 for r in games)}


def recap_index(snapshot, nights, rows, roided=None):
    """index.json 的内容：不写盘，测试可以直接核对字段。"""
    return {'build_id': snapshot['build_id'], 'timezone': 'Asia/Shanghai',
            'night_start_hour': 18, 'night_end_hour': 6,
            'nights': [night_entry(key, games) for key, games in sorted(nights.items(), reverse=True)],
            'players': sorted({p['profile_id'] for r in rows for p in r['members']}),
            'team_games': len(rows), 'roided': roided}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=Path)
    ap.add_argument('--as-of-ms', type=int, help='本次构建的统计截止时刻（毫秒）；缺省退回快照时间')
    args = ap.parse_args()
    data = load_full(FULL)
    if args.bundle:
        from detail_bundle import load_bundle
        details = match_details(data, load_bundle(args.bundle, data['build_id']))
    else:
        details = match_details(data)
    rows = recap_rows(data, details=details)
    # 「本周最胡」的截止时刻：优先构建链传入的 as_of，其次用快照自带的更新时间。
    as_of_ms = args.as_of_ms or snapshot_as_of(data)
    if as_of_ms is None:
        # 两者都拿不到时退回最近一局的结束时刻：窗口仍可复现，不读当前时钟。
        as_of_ms = max((r['started_ms'] + r['duration'] * 1000 for r in rows), default=None)
    roided = week_roided(data, details, as_of_ms) if as_of_ms is not None else None
    nights = defaultdict(list)
    by_player = defaultdict(list)
    for row in rows:
        key = night_key(row['started_ms'])
        if key:
            nights[key].append(row)
        for person in row['members']:
            by_player[person['profile_id']].append(row)
    dest = API / 'recaps'
    for key, games in sorted(nights.items(), reverse=True):
        write_json(dest / 'nights' / (key + '.json'), {'build_id': data['build_id'], 'games': games})
    for pid, games in by_player.items():
        write_json(dest / 'players' / (pid + '.json'), {'build_id': data['build_id'], 'games': games})
    write_json(dest / 'index.json', recap_index(data, nights, rows, roided))
    print(json.dumps({'nights': len(nights), 'team_games': len(rows), 'player_shards': len(by_player),
                      'roided': bool(roided)}))


if __name__ == '__main__':
    main()
