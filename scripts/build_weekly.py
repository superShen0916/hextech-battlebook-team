"""Publish reproducible weekly reports using the existing v4 scorer, read-only baseline."""
import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from snapshot_io import ROOT, FULL, API, load_full, write_json
from detail_bundle import load_bundle

sys.path.insert(0, str(ROOT))
from haido.rating_lp import period_score, week_start_ms, WEEK_MS, CUTOFF, VERSION, load_weekly_calibration


def ranks(values):
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    return {pid: 1 + sum(other > value for other in values.values()) for pid, value in ordered}


def reports(snapshot, details, baseline, as_of_ms, weekly_pool=None):
    rows = defaultdict(list)
    known = {p['id']: p for p in snapshot['players']}
    for detail in details:
        ts = detail.get('started_ms') or 0
        if ts >= as_of_ms:
            continue
        for p in detail.get('players', []):
            score = (p.get('performance') or {}).get('score')
            if p.get('profile_id') in known and isinstance(score, (int, float)) and math.isfinite(score):
                rows[p['profile_id']].append((ts, score, bool(p.get('win')), p.get('penta_kills') or 0))
    pool = weekly_pool if weekly_pool is not None else baseline['pool']
    bases = {pid: round(baseline['players'][pid]['base'], 1) for pid in known}
    current = week_start_ms(as_of_ms)
    output = []
    for start in range(week_start_ms(CUTOFF), current + 1, WEEK_MS):
        through = min(as_of_ms, start + WEEK_MS)
        # Keep [start,end) inclusive of the last millisecond, even at Monday's reset.
        periods = {pid: period_score(rows[pid], baseline['players'][pid]['base'],
                    pool['mu'], pool['sigma'], through, start) for pid in known}
        counts = {pid: sum(r[0] < through for r in rows[pid]) for pid in known}
        start_counts = {pid: sum(r[0] < start for r in rows[pid]) for pid in known}
        scores = {pid: periods[pid]['score'] for pid in known}
        before = ranks({pid: periods[pid]['week_start_score'] for pid in known if start_counts[pid] >= 5})
        after = ranks({pid: scores[pid] for pid in known if counts[pid] >= 5})
        players = []
        for pid in known:
            week = periods[pid]['this_week']
            players.append(dict(id=pid, name=known[pid]['name'], games=week.get('n', 0),
                wins=week.get('wins', 0), delta=week.get('score', 0), base=bases[pid], score=scores[pid],
                settled_delta=periods[pid]['settled_delta'], week_start_score=periods[pid]['week_start_score'],
                tier='stable' if counts[pid] >= 100 else 'provisional' if counts[pid] >= 5 else 'unrated',
                rank=after.get(pid), start_rank=before.get(pid),
                rank_change=before[pid]-after[pid] if pid in before and pid in after else None))
        players.sort(key=lambda p: (not (p['games'] and p['tier'] != 'unrated'), -p['delta'], -p['games'], p['id']))
        for i, p in enumerate(players, 1):
            p['place'] = i
        output.append(dict(start_ms=start, end_ms=start+WEEK_MS, through_ms=through,
            complete=start+WEEK_MS <= as_of_ms, players=players))
    return dict(build_id=snapshot['build_id'], as_of_ms=as_of_ms,
        generated_at=datetime.fromtimestamp(as_of_ms/1000, timezone.utc).isoformat(),
        version=VERSION, reports=list(reversed(output)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=str, required=True)
    ap.add_argument('--as-of-ms', type=int, required=True)
    args = ap.parse_args()
    snapshot = load_full(FULL)
    baseline = json.loads((ROOT / 'data/haido-baseline-v4.json').read_text(encoding='utf-8'))
    data = reports(snapshot, load_bundle(args.bundle, snapshot['build_id']).values(), baseline, args.as_of_ms,
                   load_weekly_calibration()['pool'])
    write_json(API / 'weekly.json', data)
    print(json.dumps(dict(weekly_reports=len(data['reports']), players=len(snapshot['players']))))


if __name__ == '__main__':
    main()
