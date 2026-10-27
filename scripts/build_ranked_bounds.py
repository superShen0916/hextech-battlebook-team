"""把排位调查产物折成构建可用的 `data/ranked-bounds.json`。

输入是 `outputs/sgp-ranked-research-20261028/combined-ranks-43.json`（一次性调查：
SGP 排位接口 + 排位攀登挑战 210004）与 `data/public-profiles.json`（上站名单）。
输出只保留下界口径，不写 puuid、不写原始 SGP 响应，供
`scripts/inject_ranked_bounds.py` 在构建时注入公开快照。

口径：`known_achieved_lower_bound` 只证明"至少达到过"，不保证覆盖账号全部年代；
原值 4 在国服当前映射为翡翠、旧字典为铂金，调查表取保守下界，这里原样沿用。
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/sgp-ranked-research-20261028/combined-ranks-43.json'
PROFILES = ROOT / 'data/public-profiles.json'
TARGET = ROOT / 'data/ranked-bounds.json'
QUEUES = (('solo', 'RANKED_SOLO_5x5'), ('flex', 'RANKED_FLEX_SR'))


def queue_summary(queue):
    if not isinstance(queue, dict):
        return None
    current = queue.get('current') or {}
    bound = queue.get('known_achieved_lower_bound') or {}
    lp = queue.get('current_lp')
    return {'current': current.get('display') if isinstance(current.get('display'), str) else None,
            'current_lp': lp if type(lp) is int and lp >= 0 else None,
            'lower_bound': bound.get('display') if isinstance(bound.get('display'), str) else None,
            'lower_bound_tier': bound.get('tier') if isinstance(bound.get('tier'), str) else None,
            'lower_bound_source': bound.get('source') if isinstance(bound.get('source'), str) else None}


def build(source=SOURCE, profiles=PROFILES, target=TARGET, checked_at=None):
    report = json.loads(Path(source).read_text(encoding='utf-8'))
    site = {row['expected_puuid']: row['id'] for row in
            json.loads(Path(profiles).read_text(encoding='utf-8-sig'))}
    players, unmatched = {}, []
    for row in report.get('players') or []:
        profile_id = site.get(row.get('puuid'))
        if not profile_id:
            unmatched.append(row.get('name'))
            continue
        entry = {'name': row.get('name'),
                 'checked_at': (row.get('ranked_checked_at') or '')[:10] or None}
        for key, queue in QUEUES:
            entry[key] = queue_summary((row.get('queues') or {}).get(queue))
        players[profile_id] = entry
    now = checked_at or datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
    payload = {'schema_version': 1, 'generated_at': now,
               'source': 'outputs/sgp-ranked-research-20261028/combined-ranks-43.json',
               'policy': 'known_achieved_lower_bound_only; 只证明至少达到过，不是完整生涯最高；'
                         '未返回段位不等于从未排位。',
               'players': dict(sorted(players.items()))}
    target = Path(target)
    encoded = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    if not target.exists() or target.read_text(encoding='utf-8') != encoded:
        target.write_text(encoded, encoding='utf-8')
    solo = sum(1 for row in players.values() if (row['solo'] or {}).get('lower_bound'))
    flex = sum(1 for row in players.values() if (row['flex'] or {}).get('lower_bound'))
    missing = [pid for pid in site.values() if pid not in players]
    return {'status': 'ok', 'path': str(target), 'players': len(players),
            'solo_lower_bound': solo, 'flex_lower_bound': flex,
            'not_on_site': sorted(name for name in unmatched if name),
            'site_without_bound': sorted(missing)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=SOURCE)
    ap.add_argument('--profiles', type=Path, default=PROFILES)
    ap.add_argument('--target', type=Path, default=TARGET)
    args = ap.parse_args()
    print(json.dumps(build(args.source, args.profiles, args.target), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
