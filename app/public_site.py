"""Whitelist-only public snapshots and bounded, optional post-sync delivery.

Configuration and delivery status stay in the ignored local data directory.
No network or local writes occur when public-site.json is absent.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from companions import _context
from core import SourceError, utc_now
from enrichment import enrich_matches
from insights import build_insights
from share_report import _SnapshotStore, _clean_records, build_share_report
from hexdata import load_ratings, public_rating, rating_for
from verdicts import verdict_for


APP = Path(__file__).resolve().parent
_PUSH_LOCK = threading.Lock()
_INSIGHT_FIELDS = ('summary', 'champions', 'hextech', 'highlights', 'awards', 'preferences')
_NUMERIC_FIELDS = ('champion_id', 'kills', 'deaths', 'assists', 'damage', 'taken', 'heal',
                   'damage_share', 'damage_rank', 'double_kills', 'triple_kills', 'quadra_kills', 'penta_kills')
_SUMMARY_FIELDS = ('games', 'wins', 'win_rate', 'kda', 'dpm', 'damage_share', 'kill_participation',
                   'taken', 'heal', 'triple_kills', 'quadra_kills', 'penta_kills',
                   'largest_killing_spree', 'totals')
_CHAMPION_FIELDS = ('champion_id', 'champion_name', 'games', 'wins', 'win_rate', 'kda',
                    'dpm', 'damage_share', 'kill_participation')


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _public_verdict(value):
    """Short praise line: plain text plus a closing line, nothing executable."""
    if not isinstance(value, dict):
        return None
    text = value.get('text')
    punch = value.get('punch')
    if not isinstance(text, str) or not text.strip():
        return None
    result = {'text': text.strip()[:300],
              'punch': punch.strip()[:80] if isinstance(punch, str) else ''}
    pro = value.get('pro')
    if isinstance(pro, dict):
        pro_name = pro.get('pro')
        pro_tag = pro.get('tag')
        pro_text = pro.get('text')
        if isinstance(pro_name, str) and pro_name.strip():
            result['pro'] = {
                'pro': pro_name.strip()[:40],
                'tag': pro_tag.strip()[:24] if isinstance(pro_tag, str) else '',
                'text': pro_text.strip()[:160] if isinstance(pro_text, str) else '',
            }
    return result


def _public_performance(value):
    if not isinstance(value, dict):
        return None
    result = {'version': value.get('version') if isinstance(value.get('version'), str) else None,
              'score': _number(value.get('score')), 'team_rank': _number(value.get('team_rank')),
              'award': value.get('award') if value.get('award') in ('MVP', 'ACE') else None,
              'tied': value.get('tied') is True}
    return result


def _public_player(player):
    result = {key: _number(player.get(key)) for key in _NUMERIC_FIELDS}
    result.update(champion_name=player.get('champion_name') if isinstance(player.get('champion_name'), str) else '',
                  win=player.get('win') if type(player.get('win')) is bool else None,
                  performance=_public_performance(player.get('performance')))
    for key, count in (('items', 7), ('augment_slots', 6)):
        raw = player.get(key)
        result[key] = [_number(v) for v in raw[:count]] if isinstance(raw, list) else [None] * count
    return result


def _public_preferences(value):
    """Keep aggregate holdings only, including per-champion projections."""
    if not isinstance(value, dict):
        return None
    result = {'games': _number(value.get('games'))}
    for kind in ('augments', 'items'):
        rows = value.get(kind, {})
        if not isinstance(rows, dict):
            rows = {}
        result[kind] = {key: _number(rows.get(key)) for key in
                        ('games', 'observed_games', 'complete_games', 'missing_slot_games')}
        result[kind]['top3'] = [{key: _number(row.get(key)) for key in
                                ('id', 'uses', 'games', 'frequency')}
                               for row in (rows.get('top3') or [])[:3] if isinstance(row, dict)]
    return result


def _lean_insights(insights, include_champions=True):
    raw_summary = insights.get('summary', {})
    summary = {key: raw_summary[key] for key in _SUMMARY_FIELDS if key in raw_summary}
    summary['samples'] = {key: value for key, value in raw_summary.get('samples', {}).items()
                          if key in _SUMMARY_FIELDS or key == 'wins'}
    hextech = insights.get('hextech', {})
    result = {'summary': summary,
              'hextech': {key: hextech[key] for key in ('games', 'complete_games', 'missing_slot_games') if key in hextech},
              **{key: insights[key] for key in ('awards',) if key in insights}}
    preferences = _public_preferences(insights.get('preferences'))
    if preferences is not None:
        result['preferences'] = preferences
    if 'highlights' in insights:
        result['highlights'] = {key: value for key, value in insights['highlights'].items()
                                if key not in ('games_with', 'largest_multi_kill')}
    result['hextech']['augments'] = [{key: row[key] for key in ('id', 'uses', 'frequency') if key in row}
                                    for row in hextech.get('augments', [])]
    if include_champions:
        result['champions'] = [{**{key: row[key] for key in _CHAMPION_FIELDS if key in row},
                                 'preferences': _public_preferences(row.get('preferences'))}
                                for row in insights.get('champions', [])]
    return result


def _round_public(value):
    """Rounding is confined to the public projection, after all calculations."""
    if type(value) is float:
        rounded = round(value, 6)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, dict):
        return {key: _round_public(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_public(item) for item in value]
    return value


def compact_public_snapshot(snapshot):
    """Compact an existing safe snapshot without re-reading the database."""
    result = {key: value for key, value in snapshot.items() if key not in ('personal', 'companions')}
    def compact_view(view):
        lean = _lean_insights(view)
        verdict = _public_verdict(view.get('verdict'))
        if verdict:
            lean['verdict'] = verdict
        if 'rating' in view:
            lean['rating'] = public_rating(view['rating'])
        lean['recent'] = [{key: value for key, value in row.items() if key != 'player'} |
                          {'player': _public_player(row.get('player', {}))} for row in view.get('recent', [])]
        lean['by_champion'] = {key: _lean_insights(value, include_champions=False)
                               for key, value in view.get('by_champion', {}).items()}
        if 'reports' in view:
            lean['reports'] = view['reports']
        if 'teammates' in view:
            lean['teammates'] = [{**{key: row[key] for key in
                                    ('id', 'name', 'shared_games', 'games', 'wins', 'win_rate') if key in row},
                                  'rating': public_rating(row.get('rating')),
                                  **_lean_insights(row)} for row in view['teammates']]
        return lean
    result['personal'] = compact_view(snapshot.get('personal', {}))
    result['companions'] = [{**{key: row[key] for key in ('id', 'name', 'shared_games', 'games', 'wins', 'win_rate') if key in row},
                             **compact_view(row)} for row in snapshot.get('companions', [])]
    return _round_public(result)


def _view(records, ids):
    insights = build_insights(records)
    result = {key: insights[key] for key in _INSIGHT_FIELDS if key in insights}
    result['recent'] = [{
        'id': ids[m['match_key']], 'started_ms': _number(m.get('started_ms')),
        'patch': m.get('patch') if isinstance(m.get('patch'), str) else '',
        'duration': _number(m.get('duration')), 'stats_eligible': m.get('stats_eligible') is True,
        'player': _public_player(m['self']),
    } for m in records]
    result['by_champion'] = {}
    for cid in sorted({m['self']['champion_id'] for m in records}):
        subset = build_insights([m for m in records if m['self']['champion_id'] == cid])
        result['by_champion'][str(cid)] = {key: subset[key] for key in _INSIGHT_FIELDS if key in subset}
    return result


def _static_dictionary(static_data):
    result = {}
    for kind in ('champions', 'items', 'augments'):
        rows = static_data.get(kind, {})
        result[kind] = {}
        for key, row in rows.items() if isinstance(rows, dict) else []:
            if not str(key).isdigit() or not isinstance(row, dict):
                continue
            icon = row.get('icon_url')
            safe = {'name': row.get('name') if isinstance(row.get('name'), str) else str(key),
                    'icon_url': icon if isinstance(icon, str) and re.fullmatch(
                        r'/assets/' + kind + r'/[A-Za-z0-9_-]+\.(png|jpg|jpeg|webp)', icon) else ''}
            if kind == 'augments':
                safe['description'] = row.get('description') if isinstance(row.get('description'), str) else ''
                safe['rarity'] = row.get('rarity') if row.get('rarity') in ('silver', 'gold', 'prismatic') else ''
            result[kind][str(key)] = safe
    return result


def _reports_for(records):
    return {str(minimum): {key: report[key] for key in
                           ('overview', 'awards', 'leaderboard', 'minimum_award_games', 'notes')}
            for minimum in (20, 30)
            for report in [build_share_report(records, minimum_award_games=minimum)]}


def _teammates_for(records, public_ids, ratings=None):
    _, groups = _context(records)
    result = []
    for identity, games in groups.items():
        insights = build_insights(games)
        summary = insights['summary']
        if summary['games'] < 10:
            continue
        result.append({'id': public_ids[identity],
                       'rating': rating_for(games[0]['self'], ratings),
                       'name': games[0]['self'].get('game_name') or '未命名队友',
                       'shared_games': len(games), 'games': summary['games'],
                       'wins': summary['wins'], 'win_rate': summary['win_rate'],
                       'summary': summary, 'awards': insights['awards'],
                       'champions': insights['champions'][:3]})
    return sorted(result, key=lambda row: (-row['games'], row['id']))


def build_public_snapshot(records, account_public=None, static_data=None, ratings=None):
    """Pure public projection: never serialize source matches or identities."""
    records = sorted(_clean_records(records), key=lambda m: (m.get('started_ms') or 0, m['match_key']), reverse=True)
    owner, groups = _context(records)
    ids = {m['match_key']: f'm{index + 1}' for index, m in enumerate(records)}
    personal = _view(records, ids)
    personal['rating'] = rating_for({'puuid': owner}, ratings)
    candidates = [(identity, games) for identity, games in groups.items()
                  if sum(bool(m.get('stats_eligible')) for m in games) >= 10]
    candidates.sort(key=lambda item: (-sum(bool(m.get('stats_eligible')) for m in item[1]), item[0]))
    public_ids = {owner: 'personal', **{identity: f'c{index + 1}'
                                      for index, (identity, _) in enumerate(candidates)}}
    companions = []
    for index, (_, games) in enumerate(candidates):
        view = _view(games, ids)
        view['rating'] = rating_for(games[0]['self'], ratings)
        view['verdict'] = verdict_for(games[0]['self'].get('game_name'), view.get('summary'),
                                      view.get('awards'), view.get('rating'), view.get('champions'))
        view['reports'] = _reports_for(games)
        view['teammates'] = _teammates_for(games, public_ids, ratings)
        summary = view['summary']
        companions.append({'id': f'c{index + 1}', 'name': games[0]['self'].get('game_name') or '未命名队友',
                           'shared_games': len(games), 'games': summary['games'], 'wins': summary['wins'],
                           'win_rate': summary['win_rate'], **view})
    reports = _reports_for(records)
    first = reports['20']['overview']
    name = account_public.get('game_name') or account_public.get('name') if isinstance(account_public, dict) else ''
    personal['verdict'] = verdict_for(name if isinstance(name, str) else '', personal.get('summary'),
                                      personal.get('awards'), personal.get('rating'),
                                      personal.get('champions'))
    updated = utc_now()
    return compact_public_snapshot({'schema_version': 1, 'projection_version': 3,
            'updated_at': updated, 'generated_at': updated,
            'owner': {'name': name if isinstance(name, str) else ''},
            'scope': 'owner_and_saved_same_team_matches',
            'overview': {**{key: first[key] for key in ('saved', 'eligible', 'wins', 'win_rate', 'time_range')},
                         'companions': len(companions)},
            'personal': personal, 'companions': companions, 'reports': reports,
            'static': _static_dictionary(static_data or {})})


def load_public_snapshot(database_path, static_directory=None, cache=None, owner_puuid=None):
    """Reuse one mode=ro transaction for account, summaries and enrichment."""
    path = Path(database_path).resolve()
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        account = None
        if owner_puuid is not None:
            row = connection.execute('SELECT * FROM accounts WHERE puuid=?', (owner_puuid,)).fetchone()
            if row is None:
                raise ValueError('snapshot_owner_identity_missing')
            account = dict(row)
        store = _SnapshotStore(path, connection, account)
        account = store.account()
        records = enrich_matches(store, store.all_matches())
        directory = Path(static_directory) if static_directory else APP / 'static'
        static = {}
        for kind in ('champions', 'items', 'augments'):
            source = directory / (kind + '.json')
            static[kind] = json.loads(source.read_text(encoding='utf-8')) if source.exists() else {}
        ratings = load_ratings(path.parent)
        compute = lambda: build_public_snapshot(records, account, static, ratings)
        snapshot = (cache.get_or_compute('legacy-base', [records, account, static, ratings], compute)
                    if cache else compute())
        # Cached timestamps describe the old projection, not this export.
        snapshot = {**snapshot, 'updated_at': utc_now(), 'generated_at': utc_now()}
        from personal_profiles import attach_personal_profiles
        return attach_personal_profiles(snapshot, path.parent, records, ratings, cache=cache)
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect_rejected', headers, fp)


def _write_status(path, status):
    handle, temporary = tempfile.mkstemp(prefix='public-site-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(status, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _exclusive_lock(path):
    """Nonblocking process lock, automatically released even after crashes."""
    handle = path.open('a+b')
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        yield False
        return
    try:
        yield True
    finally:
        handle.close()


def push_public_snapshot(directory, force=False, timeout=30):
    """Never fail collection because a public site or local delivery is down."""
    directory = Path(directory)
    config_path = directory / 'public-site.json'
    if not config_path.is_file():
        return {'status': 'not_configured'}
    with _PUSH_LOCK, _exclusive_lock(directory / 'public-site-push.lock') as acquired:
        if not acquired:
            return {'status': 'busy'}
        # Keep a still-running legacy publisher's status separate during rollout.
        status_path = directory / ('public-site-profiles-status.json'
                                  if (directory / 'public-profiles.json').is_file()
                                  else 'public-site-status.json')
        previous, status = {}, {'status': 'failed', 'attempted_at': utc_now()}
        try:
            try:
                previous = json.loads(status_path.read_text(encoding='utf-8'))
                if not isinstance(previous, dict):
                    previous = {}
            except (OSError, ValueError):
                pass
            config = json.loads(config_path.read_text(encoding='utf-8-sig'))
            if config.get('enabled', True) is False:
                return {'status': 'disabled'}
            target, token = config['url'], config['token']
            parsed = urllib.parse.urlsplit(target)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.path not in ('', '/', '/api/snapshot')
                    or not isinstance(token, str) or not token or any(ord(c) < 32 for c in token)):
                raise ValueError('invalid_public_site_configuration')
            endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '/api/snapshot', '', ''))
            destination = hashlib.sha256((endpoint + '\0' + token).encode()).hexdigest()
            status['destination_hash'] = destination
            if previous.get('destination_hash') == destination:
                for key in ('last_success_hash', 'uploaded_at'):
                    if key in previous:
                        status[key] = previous[key]
            snapshot = load_public_snapshot(directory / 'mayhem.sqlite')
            stable = {key: value for key, value in snapshot.items() if key not in ('updated_at', 'generated_at')}
            encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            digest = hashlib.sha256(encoded).hexdigest()
            status['content_hash'] = digest
            if not force and status.get('last_success_hash') == digest:
                status['status'] = 'unchanged'
            else:
                payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
                request = urllib.request.Request(endpoint, data=payload, method='POST', headers={
                    'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json; charset=utf-8',
                    'User-Agent': 'HextechBattlebook/1.0', 'Accept': 'application/json',
                    'X-Snapshot-Hash': digest})
                opener = urllib.request.build_opener(_NoRedirect())
                with opener.open(request, timeout=max(1, min(30, timeout))) as response:
                    code = response.status
                    if not 200 <= code < 300:
                        raise urllib.error.HTTPError(endpoint, code, 'upload_rejected', {}, None)
                    response.read(4096)
                status.update(status='uploaded', uploaded_at=utc_now(), last_success_hash=digest, http_status=code)
        except Exception as error:
            status['error'] = type(error).__name__
            if isinstance(error, urllib.error.HTTPError):
                status['http_status'] = error.code
        try:
            _write_status(status_path, status)
        except OSError:
            pass
        return status


def _source_signature(directory):
    result = []
    for name in ('mayhem.sqlite', 'mayhem.sqlite-wal', 'public-site.json', 'hexdata-ratings.json', 'public-profiles.json'):
        try:
            stat = (directory / name).stat()
            result.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            result.append(None)
    from personal_profiles import profile_sources
    for source in profile_sources(directory):
        for path in (source['path'], Path(str(source['path']) + '-wal')):
            try:
                stat = path.stat()
                result.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                result.append(None)
    return tuple(result)


def watch_public_site(directory, interval=25, force=False, stop=None, max_iterations=None):
    """Watch cheap file signatures; only build after a completed collection.

    ``stop`` and ``max_iterations`` enable bounded embedding and offline tests.
    Pending failures retry with capped exponential backoff without a new sync.
    """
    from sync import sync_lock  # Avoid an import cycle with the optional sync hook.
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    interval = max(1, min(30, interval))
    lock_name = ('public-site-profiles-watch.lock' if (directory / 'public-profiles.json').is_file()
                 else 'public-site-watch.lock')
    with _exclusive_lock(directory / lock_name) as acquired:
        if not acquired:
            return {'status': 'already_watching'}
        completed_signature, retry_at, failures, iterations = None, 0, 0, 0
        last_status = None
        while (max_iterations is None or iterations < max_iterations) and not (stop and stop()):
            iterations += 1
            try:
                config_exists = (directory / 'public-site.json').is_file()
                signature = _source_signature(directory) if config_exists else None
                if (config_exists and (directory / 'mayhem.sqlite').is_file()
                        and signature != completed_signature and time.monotonic() >= retry_at):
                    try:
                        with sync_lock(directory):
                            result = push_public_snapshot(directory, force=force)
                    except SourceError as error:
                        if error.code != 'sync_already_running':
                            raise
                    else:
                        last_status = result.get('status')
                        if last_status in ('uploaded', 'unchanged'):
                            completed_signature = signature
                            retry_at, failures, force = 0, 0, False
                        elif last_status == 'failed':
                            failures += 1
                            retry_at = time.monotonic() + min(300, interval * (2 ** min(failures - 1, 8)))
            except (OSError, ValueError):
                # An unavailable disk/configuration can recover on a later tick.
                pass
            if max_iterations is None or iterations < max_iterations:
                time.sleep(interval)
        return {'status': 'stopped', 'iterations': iterations, 'last_status': last_status}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Push the safe public site snapshot')
    parser.add_argument('--data-dir', default=str(APP.parent / 'data'))
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    result = watch_public_site(args.data_dir, force=args.force) if args.watch else push_public_snapshot(args.data_dir, force=args.force)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result['status'] == 'failed' else 0)
