"""Roster of everyone who has actually queued WITH the owner, plus crawl status per person.

"With" means the same team_id in the same HEX/KIWI match - not merely the same match.
Random teammates and opponents show up in the archive all the time, so same-match counts
overstate who is really a friend; this report keeps the two apart.

Read-only. Writes one JSON + a printed table.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE, client_account
import argparse, json, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1].parents[1]
PILOT = ROOT / 'work/gopher-pilot-20261021'
ap = argparse.ArgumentParser()
ap.add_argument('--out', default=str(PILOT / 'owner-roster.json'))
args = ap.parse_args()

pilot = sqlite3.connect('file:' + str(DATABASE) + '?mode=ro', uri=True)
pilot.row_factory = sqlite3.Row
main = sqlite3.connect('file:' + str(DATABASE) + '?mode=ro', uri=True)
main.row_factory = sqlite3.Row

settings = dict(pilot.execute('SELECT key,value FROM settings'))
origin = json.loads(settings.get('pilot_origin', '{}')) or {}
gopher = origin.get('target_puuid')
main_key = client_account(main)['account_key']
main_puuid = main.execute('SELECT puuid FROM accounts WHERE account_key=?', (main_key,)).fetchone()[0]
owners = {main_puuid: '间客丿(主号)', gopher: 'gopher(主号)'}
print('owner accounts: %s' % ', '.join(owners.values()))

names, teams = {}, {}
for row in pilot.execute('SELECT match_key,puuid,team_id,payload FROM participants'):
    names.setdefault(row['puuid'], json.loads(row['payload']).get('game_name') or '?')
    teams.setdefault(row['match_key'], []).append((row['puuid'], row['team_id'], row['payload']))

with_owner, same_match = {}, {}
for mid, roster in teams.items():
    owner_teams = {t for p, t, _ in roster if p in owners}
    for puuid, team, payload in roster:
        if puuid in owners:
            continue
        same_match[puuid] = same_match.get(puuid, 0) + 1
        if team in owner_teams:
            with_owner[puuid] = with_owner.get(puuid, 0) + 1

accounts = {r['puuid']: dict(r) for r in pilot.execute('SELECT account_key,puuid,game_name,tag_line FROM accounts')}
archived = dict(pilot.execute('SELECT account_key,COUNT(*) FROM account_matches GROUP BY account_key'))
listings = {t['puuid']: t for t in json.loads((PILOT / 'teammate-id-listing.json').read_text(encoding='utf-8'))['teammates']}
crawl = json.loads((PILOT / 'deep-listing-crawl.json').read_text(encoding='utf-8'))['accounts']

rows = []
for puuid, together in with_owner.items():
    account = accounts.get(puuid)
    listed = listings.get(puuid) or {}
    window = listed.get('window') or {}
    crawled = crawl.get(puuid) or {}
    rows.append({
        'puuid': puuid,
        'player': names.get(puuid, '?'),
        'tag_line': (account or {}).get('tag_line') or (listed.get('tag_line') or ''),
        'games_with_owner': together,
        'games_same_match': same_match.get(puuid, 0),
        'registered': bool(account),
        'listing_crawled': bool(listed) or bool(crawled),
        'listed_ids': len(listed.get('ids') or crawled.get('ids') or []),
        'archived': archived.get((account or {}).get('account_key'), 0),
        'pending_details': max(0, len(listed.get('ids') or []) - archived.get((account or {}).get('account_key'), 0)),
        'window_status': window.get('status') or ('crawled_depth_only' if crawled else None),
        'recovered_beyond_window': window.get('archived_beyond_window'),
    })
rows.sort(key=lambda r: -r['games_with_owner'])

print('\n%-16s %-8s %-6s %-6s %-7s %-7s %-6s %s' % ('player', 'with', 'same', 'reg', 'listed', 'archived', 'pend', 'window'))
for r in rows:
    if r['games_with_owner'] < 2:
        continue
    print('%-16s %-8d %-6d %-6s %-7d %-7d %-6d %s' % (
        r['player'][:16], r['games_with_owner'], r['games_same_match'], 'Y' if r['registered'] else '-',
        r['listed_ids'], r['archived'], r['pending_details'], r['window_status'] or ''))

Path(args.out).write_text(json.dumps({'owners': owners, 'roster': rows,
                                      'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds')},
                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('\nplayers who queued with the owner at least twice: %d' % sum(1 for r in rows if r['games_with_owner'] >= 2))
print('of those registered in the archive: %d' % sum(1 for r in rows if r['games_with_owner'] >= 2 and r['registered']))
print('written', args.out)
