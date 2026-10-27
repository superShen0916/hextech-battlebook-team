"""Build lazy night/team recaps, with Shanghai 06:00 boundary and exact teams."""
import json
import argparse
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from snapshot_io import FULL, API, ROOT, load_full, write_json
from project_paths import FRONTEND

TZ = timezone(timedelta(hours=8))
MATCHES = FRONTEND / 'public/matches'


def night_key(started_ms):
    value = datetime.fromtimestamp(started_ms / 1000, TZ)
    if 6 <= value.hour < 18:
        return None
    return (value - timedelta(hours=6)).strftime('%Y-%m-%d')


def recap_rows(snapshot, match_dir=MATCHES, details=None):
    eligible = {m['id'] for p in snapshot['players'] for m in p.get('recent', []) if m.get('stats_eligible')}
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=Path)
    args = ap.parse_args()
    data = load_full(FULL)
    if args.bundle:
        from detail_bundle import load_bundle
        details = load_bundle(args.bundle, data['build_id'])
    else:
        details = None
    rows = recap_rows(data, details=details)
    nights = defaultdict(list)
    by_player = defaultdict(list)
    for row in rows:
        key = night_key(row['started_ms'])
        if key:
            nights[key].append(row)
        for person in row['members']:
            by_player[person['profile_id']].append(row)
    dest = API / 'recaps'
    index = []
    for key, games in sorted(nights.items(), reverse=True):
        write_json(dest / 'nights' / (key + '.json'), {'build_id': data['build_id'], 'games': games})
        people = sorted({p['profile_id'] for r in games for p in r['members']})
        index.append({'date': key, 'friday': datetime.fromisoformat(key).weekday() == 4,
                      'games': len({r['match_id'] for r in games}), 'players': people,
                      'player_games': dict(Counter(p['profile_id'] for r in games for p in r['members'])),
                      'started_ms': min(r['started_ms'] for r in games),
                      'ended_ms': max(r['started_ms'] + r['duration'] * 1000 for r in games)})
    for pid, games in by_player.items():
        write_json(dest / 'players' / (pid + '.json'), {'build_id': data['build_id'], 'games': games})
    write_json(dest / 'index.json', {'build_id': data['build_id'], 'timezone': 'Asia/Shanghai',
        'night_start_hour': 18, 'night_end_hour': 6, 'nights': index,
        'players': sorted(by_player), 'team_games': len(rows)})
    print(json.dumps({'nights': len(index), 'team_games': len(rows), 'player_shards': len(by_player)}))


if __name__ == '__main__':
    main()
