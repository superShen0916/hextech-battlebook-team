"""Incremental sync of new HEXFALL matches, assembled from the existing collectors.

This script fetches nothing by itself. It only decides WHAT the existing
collectors should fetch, then runs them:

  1. list_teammates_pilot.py --registered-only
     Refresh every named account's match-ID listing. The upstream endpoint only
     serves the most recent ~1000 IDs and ignores every time parameter (measured
     2026-10-23, documented in app/listing.py), so new matches are always at the
     TOP of a player's listing.
  2. collect_gopher_pilot.py
     The owner's own account. pilot_listing.complete is reset first so it
     re-lists, then it fetches only what it does not already hold.
  3. Queue arithmetic (here, zero network): for every other named account the
     fetch queue is the not-yet-archived IDs ABOVE that account's newest archived
     match - strictly newer than everything the archive already holds for them.
     Older pending IDs are marked 'deferred_backfill' so a plain collector run can
     never accidentally pull thousands of old games (--full-backfill re-enables
     them). An account whose backlog is larger than --threshold contributes only
     its --cap most recent IDs.
  4. collect_account_pilot.py --account-key ...
     One subprocess per account: the same audited fetch loop the pilot always used
     (4 s pacing, payload reuse, per-match error handling).
  5. fix_all_attribution.py --apply --named-only
     Link every held match to every named player who appeared in it, so nobody's
     count depends on whose listing was walked.
  6. owner_roster.py
     Refreshed roster with per-person crawl status.

Writes only the single project database data/mayhem.sqlite. Client identity
is selected explicitly from the registry; this script does not publish a site.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0,str(_Path(__file__).resolve().parents[3]/'app'))
from project_paths import DATABASE
import argparse, json, shutil, sqlite3, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PILOT = ROOT / 'work/gopher-pilot-20261021'
SCRIPTS = PILOT / 'scripts'
PY = sys.executable
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'app')]
from workflow_guard import check_database_routes, collector_result, sync_exit_code
from public_site import _exclusive_lock
from collection_scope import excluded_puuids

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--interval', type=float, default=4.0, help='minimum seconds between requests')
ap.add_argument('--cap', type=int, default=40, help='max queued IDs for an account carrying a backlog')
ap.add_argument('--threshold', type=int, default=100, help='backlog size above which the cap applies')
ap.add_argument('--full-backfill', action='store_true',
                help='queue every pending ID instead of only the not-yet-pulled tail')
ap.add_argument('--skip-listing', action='store_true', help='reuse the existing teammate-id-listing.json')
ap.add_argument('--yes', action='store_true', help='actually fetch; without it the run stops after the plan')
ap.add_argument('--report', default=str(ROOT / 'outputs' / ('增量同步_%s.json'
                % datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d'))))
args = ap.parse_args()


def now():
    return datetime.now(timezone.utc).isoformat()


def run(script, *script_args):
    print('\n$ python %s %s' % (script, ' '.join(script_args)), flush=True)
    result = subprocess.run([PY, str(SCRIPTS / script), *script_args], cwd=str(ROOT),
                            capture_output=True, text=True, timeout=7200)
    tail = [line for line in result.stdout.strip().splitlines() if line.strip()][-6:]
    for line in tail:
        print('  ' + line[:400], flush=True)
    if result.returncode != 0:
        print('  exit=%d stderr=%s' % (result.returncode, result.stderr[-1500:]), flush=True)
    return result


def ro():
    db = sqlite3.connect('file:' + str(DATABASE) + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def main():
    print('DATABASE_ROUTES_OK', json.dumps(check_database_routes(ROOT)), flush=True)
    report = {'started_at': now(), 'scope': {'interval': args.interval, 'cap': args.cap,
              'threshold': args.threshold, 'full_backfill': args.full_backfill}, 'steps': []}

    # ---------------------------------------------------------------- 1. listings
    if args.skip_listing:
        print('\n== step 1: reuse existing teammate-id-listing.json', flush=True)
    else:
        listing_file = PILOT / 'teammate-id-listing.json'
        backup = PILOT / ('teammate-id-listing.before-sync-%s.json'
                          % datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M'))
        shutil.copy2(listing_file, backup)
        print('\n== step 1: refresh listings (backup: %s)' % backup.name, flush=True)
        result = run('list_teammates_pilot.py', '--registered-only', '--interval', str(args.interval))
        if result.returncode != 0:
            raise SystemExit('listing step failed')
        report['steps'].append({'step': 'listings', 'backup': str(backup)})

    listing = json.loads((PILOT / 'teammate-id-listing.json').read_text(encoding='utf-8'))
    gopher = listing.get('gopher_puuid')
    db = ro()
    archive = {r[0] for r in db.execute('SELECT match_key FROM matches')}
    # data/collection-exclusions.json: archived but no longer crawled by name.
    skip = excluded_puuids()
    accounts = {r['puuid']: dict(r) for r in db.execute(
        'SELECT account_key,puuid,game_name FROM accounts')
        if r['game_name'] and r['puuid'] not in skip}
    db.close()

    # ------------------------------------------------- 3a. queue plan (no network)
    plan = []
    for entry in listing['teammates']:
        acct = accounts.get(entry['puuid'])
        if not acct or entry['puuid'] == gopher:
            continue
        ids = entry['ids']
        positions = [i for i, m in enumerate(ids) if m in archive]
        if args.full_backfill:
            region = [m for m in ids if m not in archive]
        elif positions:
            # Everything above the newest archived match is newer than anything we
            # hold for this player, so none of it can have been pulled before.
            region = ids[:min(positions)]
        else:
            region = [m for m in ids if m not in archive]
        queue = region if (args.full_backfill or len(region) <= args.threshold) else region[:args.cap]
        plan.append({'account_key': acct['account_key'], 'player': acct['game_name'],
                     'listed': len(ids), 'archived_in_listing': len(positions),
                     'region': len(region), 'queue': len(queue), 'ids': queue})
    plan.sort(key=lambda row: -row['queue'])

    print('\n== step 3: queue plan (fetches happen only with --yes)', flush=True)
    print('%-16s %7s %7s %7s %7s' % ('player', 'listed', 'inarch', 'region', 'queue'))
    for row in plan:
        print('%-16s %7d %7d %7d %7d' % (row['player'][:16], row['listed'],
              row['archived_in_listing'], row['region'], row['queue']))
    print('accounts: %d, total queue: %d' % (len(plan), sum(r['queue'] for r in plan)))

    if not args.yes:
        (Path(args.report).parent / 'queue-plan.json').write_text(
            json.dumps({'generated_at': now(), 'plan': [{k: v for k, v in r.items() if k != 'ids'}
                        for r in plan]}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('\nplan only; no match details fetched (listings may have refreshed). queue-plan.json written.')
        raise SystemExit(0)

    # --------------------------------------------------------- 2. the owner first
    print('\n== step 2: owner account (gopher) re-lists and fetches its new tail', flush=True)
    db = sqlite3.connect(str(DATABASE), timeout=15)
    row = db.execute("SELECT value FROM settings WHERE key='pilot_listing'").fetchone()
    listing_setting = json.loads(row[0]) if row else {}
    listing_setting['complete'] = False
    db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               ('pilot_listing', json.dumps(listing_setting, ensure_ascii=False)))
    db.commit()
    db.close()
    result = run('collect_gopher_pilot.py')
    gopher_status = collector_result(result.stdout, result.returncode)
    gopher_out = {'exit': result.returncode, **gopher_status['summary']}
    report['steps'].append({'step': 'gopher', 'exit': result.returncode,
                            'ok': gopher_status['ok'], 'reasons': gopher_status['reasons']})
    report['gopher'] = gopher_out

    # ------------------------------------------- 3b. write the queues into discovered
    db = sqlite3.connect(str(DATABASE), timeout=15)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('BEGIN')
    deferred_total = 0
    for row in plan:
        key, queue = row['account_key'], row['ids']
        if not args.full_backfill:
            # Older pending work waits for an explicit backfill decision.
            placeholders = ','.join('?' * len(queue)) if queue else "''"
            cursor = db.execute('''UPDATE discovered SET status='skipped',
                    last_error='deferred_backfill_pending_owner_decision', updated_at=?
                    WHERE account_key=? AND status IN ('pending','failed') AND match_key NOT IN (%s)'''
                    % placeholders, (now(), key, *queue))
            deferred_total += cursor.rowcount if cursor.rowcount > 0 else 0
        for mid in queue:
            db.execute('''INSERT INTO discovered(account_key,match_key,status,updated_at) VALUES(?,?,'pending',?)
                ON CONFLICT(account_key,match_key) DO NOTHING''', (key, mid, now()))
            # 'skipped' rows are non-2400 games; keep them skipped, revive everything else.
            db.execute("""UPDATE discovered SET status='pending', updated_at=?
                          WHERE account_key=? AND match_key=? AND status!='skipped'""", (now(), key, mid))
    db.execute('COMMIT')
    db.close()
    print('\n== step 3b: queues written; %d older pending IDs deferred (skipped, reversible)' % deferred_total,
          flush=True)
    report['deferred_ids'] = deferred_total

    # --------------------------------------------------- 4. fetch, account by account
    print('\n== step 4: fetching with collect_account_pilot.py (one subprocess per account)', flush=True)
    fetched_total = reused_total = 0
    stopped = 'gopher' if gopher_status['stopped'] else None
    for row in plan:
        if stopped:
            break
        if not row['queue']:
            continue
        result = run('collect_account_pilot.py', '--account-key', row['account_key'],
                     '--interval', str(args.interval))
        status = collector_result(result.stdout, result.returncode)
        summary = status['summary']
        if status['stopped']:
            stopped = row['player']
            report['steps'].append({'step': 'fetch', 'player': row['player'], 'stopped': True,
                                    'exit': result.returncode, 'ok': False, 'reasons': status['reasons']})
            break
        fetched_total += summary.get('fetched', 0)
        reused_total += summary.get('reused', 0)
        report['steps'].append({'step': 'fetch', 'player': row['player'], 'queue': row['queue'],
                                'exit': result.returncode, 'ok': status['ok'], 'reasons': status['reasons'],
                                'fetched': summary.get('fetched', 0), 'reused': summary.get('reused', 0),
                                'http': summary.get('http'), 'coverage': summary.get('coverage')})
    report['fetch_totals'] = {'fetched': fetched_total, 'reused': reused_total, 'stopped_at': stopped}

    # ------------------------------------------------------------ 5. attribution
    print('\n== step 5: attribution (named accounts only)', flush=True)
    result = run('fix_all_attribution.py', '--apply', '--named-only')
    attribution = {}
    for line in result.stdout.splitlines():
        if line.strip().startswith('inserted'):
            attribution['inserted'] = line.strip()
    report['steps'].append({'step': 'attribution', 'exit': result.returncode})
    report['attribution'] = attribution

    # ------------------------------------------------------------------ 6. roster
    print('\n== step 6: roster + coverage', flush=True)
    result = run('owner_roster.py')
    report['steps'].append({'step': 'roster', 'exit': result.returncode})

    # ------------------------------------------------------------- post-sync state
    db = ro()
    per_player = []
    for acct in accounts.values():
        newest = db.execute('''SELECT max(m.started_ms) FROM matches m JOIN participants p USING(match_key)
                               WHERE p.puuid=?''', (acct['puuid'],)).fetchone()[0]
        held = db.execute('''SELECT count(*) FROM matches m JOIN participants p USING(match_key)
                             WHERE p.puuid=?''', (acct['puuid'],)).fetchone()[0]
        per_player.append({'player': acct['game_name'], 'held_matches': held, 'newest_held_ms': newest})
    db.close()
    per_player.sort(key=lambda r: -(r['newest_held_ms'] or 0))


    def fmt(ms):
        if not ms:
            return '-'
        return datetime.fromtimestamp(ms / 1000, timezone(timedelta(hours=8))).strftime('%m-%d %H:%M')


    print('\n== held matches per player after sync', flush=True)
    print('%-16s %8s %s' % ('player', 'held', 'newest held'))
    for row in per_player:
        print('%-16s %8d %s' % (row['player'][:16], row['held_matches'], fmt(row['newest_held_ms'])))

    report['finished_at'] = now()
    report['per_player_after'] = per_player
    exit_code = sync_exit_code(report)
    report['status'] = 'complete' if exit_code == 0 else 'incomplete'
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('\nreport:', args.report)
    raise SystemExit(exit_code)


if __name__ == '__main__':
    lock_dir = ROOT / 'work/build'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(lock_dir / 'sync.lock') as acquired:
        if not acquired:
            raise SystemExit('sync_already_running; wait for the existing sync')
        main()
