"""Bounded recovery and read-only route diagnostics for the current account."""
import json
import time
import urllib.error
import urllib.request
from core import TencentSource, SourceError, normalize, scrub, utc_now, error_excerpt
from store import Store
from sync import sync_lock

SUMMARY_ROUTES = {
    'sgp_v3_summary': '/match-history-query/v3/product/lol/matchId/{match}/infoType/summary',
    'sgp_v3_short_summary': '/match-history-query/v3/product/lol/matchId/{match}/summary',
    'sgp_v1_summary': '/match-history-query/v1/products/lol/{match}/SUMMARY',
}
TIMELINE_ROUTES = {
    'sgp_v3_details': '/match-history-query/v3/product/lol/matchId/{match}/infoType/details',
    'sgp_v3_short_details': '/match-history-query/v3/product/lol/matchId/{match}/details',
    'sgp_v1_details': '/match-history-query/v1/products/lol/{match}/DETAILS',
}


def unwrap(data):
    return data.get('json', data) if isinstance(data, dict) else data


def validate_timeline(raw, match_key, expected_puuids=None):
    if not isinstance(raw, dict):
        raise SourceError('unexpected_timeline_schema')
    metadata = raw.get('metadata', {})
    if metadata.get('match_id', metadata.get('matchId', match_key)) != match_key:
        raise SourceError('timeline_identity_mismatch')
    data = unwrap(raw)
    if not isinstance(data, dict):
        raise SourceError('unexpected_timeline_schema')
    if 'gameId' in data and str(data['gameId']) != match_key.split('_')[1]:
        raise SourceError('timeline_identity_mismatch')
    frames = data.get('frames')
    if not isinstance(frames, list) or not frames:
        raise SourceError('missing_timeline_frames')
    participants = data.get('participants', [])
    observed = {p.get('puuid') for p in participants if isinstance(p, dict) and p.get('puuid')}
    if observed and expected_puuids and observed != set(expected_puuids):
        raise SourceError('timeline_participant_mismatch')
    previous = -1
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get('timestamp'), int) or frame['timestamp'] < previous:
            raise SourceError('invalid_timeline_frame')
        previous = frame['timestamp']
        if not isinstance(frame.get('events', []), list) or any(not isinstance(e, dict) for e in frame.get('events', [])):
            raise SourceError('invalid_timeline_events')
        if not isinstance(frame.get('participantFrames', {}), dict):
            raise SourceError('invalid_timeline_participant_frames')
    return data


def import_raw(store):
    """Migrate existing validated raw summaries into SQLite without network requests."""
    account = store.account()
    if not account:
        return 0
    count = 0
    for path in (store.directory / 'raw').glob('*.json'):
        if not store.has(account['account_key'], path.stem):
            continue
        raw = json.loads(path.read_text(encoding='utf-8'))
        normalize(raw, account['puuid'], path.stem)
        store.save_payload(path.stem, 'summary', 'sgp_v3_summary', raw)
        count += 1
    return count


def run_recovery(directory, rounds=2, timelines=False, progress=None, source_factory=TencentSource, timeline_rounds=2):
    # Legacy timeline diagnostics remain testable, but are retired for the live project.
    from pathlib import Path
    from project_paths import DATA
    if timelines and Path(directory).resolve() == DATA.resolve():
        raise SourceError('timeline_collection_retired_for_project')
    if not 1 <= rounds <= 5 or not 1 <= timeline_rounds <= 5:
        raise SourceError('invalid_recovery_rounds')
    store = Store(directory)
    state = {'run_id': utc_now(), 'running': True, 'started_at': utc_now(), 'phase': 'initializing',
             'recovered': 0, 'timeline_saved': 0, 'timeline_failed': 0, 'processed': 0}
    def update():
        store.set('recovery_status', state)
        if progress:
            progress(dict(state))
    with sync_lock(directory):
        update()
        try:
            account = store.account()
            if not account:
                raise SourceError('no_existing_account')
            source = source_factory()
            if source.account_key != account['account_key']:
                raise SourceError('logged_in_account_differs_from_recovery_account')
            store.register(source)
            state['raw_imported'] = import_raw(store)
            with store.connect() as db:
                missing = [r[0] for r in db.execute("SELECT match_key FROM discovered WHERE account_key=? AND status IN ('failed','pending') ORDER BY match_key DESC", (account['account_key'],))]
            state['initial_missing'] = len(missing)
            # Freeze the initial gap list so a moving history window cannot lose old failures.
            store.set('recovery_targets:' + state['run_id'], missing)
            def remote(label, route, mid=None):
                return source.get(route, retries=0, diagnostic=lambda r: store.log_request(state['run_id'], mid, label, r))
            def local(label, route, mid=None):
                started = time.monotonic()
                record = {'attempt': 1, 'status': None}
                try:
                    request = urllib.request.Request(source._local.base + route, headers={
                        'Authorization': source._local.authorization, 'Accept': 'application/json'})
                    with source._local.opener.open(request, timeout=15) as response:
                        record['status'] = response.status
                        data = json.load(response)
                    return data
                except urllib.error.HTTPError as error:
                    record.update(status=error.code, error='http_error', message=error_excerpt(error.read(8192),
                        (source._token, source._local.authorization, account['puuid'], account['game_name'], account['tag_line'])))
                    raise SourceError('local_diagnostic_failed', error.code) from None
                except (OSError, ValueError, urllib.error.URLError):
                    record['error'] = 'transport_or_json_error'
                    raise SourceError('local_diagnostic_connection_failed') from None
                finally:
                    record['elapsed_ms'] = round((time.monotonic() - started) * 1000)
                    store.log_request(state['run_id'], mid, label, record)
                    time.sleep(0.25)
            # Same account / same session controls distinguish history-service failures from login failure.
            state['phase'] = 'diagnostic_controls'
            update()
            for label, route in (
                ('lcu_history', '/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=1'),
            ):
                try:
                    data = local(label, route)
                    store.save_payload(account['account_key'], 'history_control', label, data)
                except SourceError:
                    pass
            ids_route = '/match-history-query/v1/products/lol/player/' + account['puuid'] + '?startIndex=0&count=1&tag=q_2400'
            try:
                data = remote('sgp_id_list', ids_route)
                store.save_payload(account['account_key'], 'history_control', 'sgp_id_list', data)
            except SourceError:
                pass
            try:
                data = remote('sgp_v1_history_summary', ids_route.split('?')[0] + '/SUMMARY?startIndex=0&count=1')
                store.save_payload(account['account_key'], 'history_control', 'sgp_v1_history_summary', data)
            except SourceError:
                pass
            state['phase'] = 'recover_summaries'
            preferred = 'sgp_v3_summary'
            for round_index in range(rounds):
                state['round'] = round_index + 1
                todo = [m for m in missing if not store.has(account['account_key'], m)]
                if not todo:
                    break
                if round_index:
                    time.sleep(5)
                    source.refresh_token()
                for i, mid in enumerate(todo):
                    labels = [preferred]
                    # Test documented alternatives on three failures each round; use a working alternative for the rest.
                    if i < 3:
                        labels += [label for label in SUMMARY_ROUTES if label != preferred]
                    for label in labels:
                        try:
                            raw = remote(label, SUMMARY_ROUTES[label].format(match=mid), mid)
                            match = normalize(unwrap(raw), account['puuid'], mid)
                            store.save_payload(mid, 'summary', label, raw)
                            store.put(account['account_key'], match)
                            raw_dir = store.directory / 'raw'
                            raw_dir.mkdir(exist_ok=True)
                            (raw_dir / (mid + '.json')).write_text(json.dumps(scrub(unwrap(raw)), ensure_ascii=False), encoding='utf-8')
                            state['recovered'] += 1
                            preferred = label
                            break
                        except SourceError as error:
                            store.discovery_status(account['account_key'], mid, 'failed', str(error))
                            state['last_error'] = str(error)
                    state['processed'] += 1
                    update()
            state['remaining'] = store.counts().get('failed', 0) + store.counts().get('pending', 0)
            if timelines:
                state['phase'] = 'timeline_route_validation'
                update()
                matches = store.all_matches()
                preferred_timeline = None
                def save_timeline(mid, label, raw, match):
                    # Keep successful source data even if a future schema cannot yet be indexed.
                    store.save_payload(mid, 'timeline', label, raw)
                    data = validate_timeline(raw, mid, [p['puuid'] for p in match['participants']])
                    with store.connect() as db:
                        existed = db.execute('SELECT 1 FROM timelines WHERE match_key=?', (mid,)).fetchone()
                    store.put_timeline(mid, label, data)
                    state['timeline_saved'] += int(not existed)
                # Compare LCU and all documented SGP variants on three known valid games.
                for match in matches[:3]:
                    mid = match['match_key']
                    for label, template in TIMELINE_ROUTES.items():
                        try:
                            raw = remote(label, template.format(match=mid), mid)
                            save_timeline(mid, label, raw, match)
                            preferred_timeline = preferred_timeline or label
                        except SourceError as error:
                            state['last_timeline_error'] = str(error)
                    for label, route in (
                        ('lcu_game_detail', '/lol-match-history/v1/games/' + mid.split('_')[1]),
                        ('lcu_timeline', '/lol-match-history/v1/game-timelines/' + mid.split('_')[1]),
                    ):
                        try:
                            raw = local(label, route, mid)
                            if label == 'lcu_timeline':
                                save_timeline(mid, label, raw, match)
                                preferred_timeline = preferred_timeline or label
                            else:
                                store.save_payload(mid, 'lcu_summary', label, raw)
                        except SourceError as error:
                            state['last_timeline_error'] = str(error)
                    update()
                state['timeline_route'] = preferred_timeline
                # Probe every known target game on the documented V3 candidate even if
                # the first three samples fail; a service outage is not proof of no data.
                candidate = preferred_timeline or 'sgp_v3_details'
                state['timeline_candidate_route'] = candidate
                if matches:
                    state['phase'] = 'capture_timelines'
                    for timeline_round in range(timeline_rounds):
                        state['timeline_round'] = timeline_round + 1
                        with store.connect() as db:
                            saved = {r[0] for r in db.execute('SELECT match_key FROM timelines')}
                        todo = [m for m in matches if m['match_key'] not in saved]
                        if not todo:
                            break
                        if timeline_round:
                            time.sleep(5)
                        for match in todo:
                            mid = match['match_key']
                            try:
                                if candidate == 'lcu_timeline':
                                    raw = local(candidate, '/lol-match-history/v1/game-timelines/' + mid.split('_')[1], mid)
                                else:
                                    raw = remote(candidate, TIMELINE_ROUTES[candidate].format(match=mid), mid)
                                save_timeline(mid, candidate, raw, match)
                                state['timeline_route'] = candidate
                            except SourceError as error:
                                state['timeline_failed'] += 1
                                state['last_timeline_error'] = str(error)
                            update()
                state['timeline_outcome'] = 'captured_available' if state['timeline_saved'] else 'no_usable_timeline_in_tested_window'
            state['outcome'] = 'completed' if not state['remaining'] else 'completed_with_gaps'
        except SourceError as error:
            state.update(outcome='source_unavailable', last_error=str(error))
        except Exception as error:
            state.update(outcome='local_error', last_error=type(error).__name__)
        finally:
            with store.connect() as db:
                active = store.account()
                state['timeline_total'] = db.execute('''SELECT count(*) FROM timelines t JOIN account_matches am USING(match_key)
                  WHERE am.account_key=?''', (active['account_key'] if active else '',)).fetchone()[0]
                if timelines:
                    state['timeline_remaining'] = db.execute('SELECT count(*) FROM account_matches WHERE account_key=?',
                        (active['account_key'] if active else '',)).fetchone()[0] - state['timeline_total']
                    if state.get('outcome') == 'completed' and state['timeline_remaining']:
                        state['outcome'] = 'completed_with_timeline_gaps'
            state.update(running=False, finished_at=utc_now(), phase='finished')
            update()
            store.set('recovery_run:' + state['run_id'], state)
        try:
            from public_site import push_public_snapshot
            push_public_snapshot(directory)
        except Exception:
            pass  # Public delivery must never change the recovery result.
    return state
