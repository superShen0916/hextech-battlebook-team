"""把 `data/ranked-bounds.json` 的排位下界注入完整快照的每个玩家视图。

只写 `rank` 一个字段，不碰评分、对局与搭档；字段按白名单投影，
不含 puuid、原始 SGP 响应或赛季编号。前端据此在卡片悬浮框里说明
"海斗分不参考排位，历史段位至少达到 X"。

注入后结构：
    rank = {checked_at, solo|flex = {current, lp, at_least, tier, basis}}
两个队列都没有证据的玩家不加 rank 字段（前端按"暂无可靠记录"处理）。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDS = ROOT / 'data/ranked-bounds.json'
SNAPSHOT = ROOT / 'work/build/snapshot.full.json'
_TIERS = {'IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND',
          'MASTER', 'GRANDMASTER', 'CHALLENGER'}
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def public_queue(value):
    """Only the fields the tooltip renders; unknown values become null."""
    if not isinstance(value, dict):
        return None
    current = value.get('current') if isinstance(value.get('current'), str) else None
    bound = value.get('lower_bound') if isinstance(value.get('lower_bound'), str) else None
    if not current and not bound:
        return None
    lp = value.get('current_lp')
    tier = value.get('lower_bound_tier')
    basis = value.get('lower_bound_source')
    return {'current': current[:24] if current else None,
            'lp': lp if type(lp) is int and 0 <= lp <= 100 else None,
            'at_least': bound[:24] if bound else None,
            'tier': tier if tier in _TIERS else None,
            'basis': basis[:40] if isinstance(basis, str) else None}


def public_rank(row):
    if not isinstance(row, dict):
        return None
    checked = row.get('checked_at')
    result = {'checked_at': checked if isinstance(checked, str) and _DATE.fullmatch(checked) else None}
    found = False
    for key in ('solo', 'flex'):
        queue = public_queue(row.get(key))
        result[key] = queue
        found = found or queue is not None
    return result if found else None


def load_bounds(path=BOUNDS):
    path = Path(path)
    # 这份文件是本地调研产物，只随私有数据包分发；团队仓库/CI 拉下来的源码里没有它。
    # 缺文件等于"没有任何段位证据"，跳过注入照样能构建；文件在但格式不对仍算错误。
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('players'), dict):
        raise ValueError('invalid_ranked_bounds')
    return data['players']


def inject(path=SNAPSHOT, players=None):
    path = Path(path)
    players = load_bounds() if players is None else players
    snapshot = json.loads(path.read_text(encoding='utf-8'))
    hit, unknown = 0, []
    for view in snapshot.get('players') or []:
        rank = public_rank(players.get(view.get('id')))
        if rank:
            view['rank'] = rank
            hit += 1
        else:
            view.pop('rank', None)
            unknown.append(view.get('id'))
    path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return {'injected': hit, 'players': len(snapshot.get('players') or []), 'without_rank': unknown}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bounds', type=Path, default=BOUNDS)
    ap.add_argument('--snapshot', type=Path, default=SNAPSHOT)
    args = ap.parse_args()
    bounds = load_bounds(args.bounds)
    report = inject(args.snapshot, bounds)
    report['bounds'] = 'loaded' if Path(args.bounds).is_file() else 'missing'
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
