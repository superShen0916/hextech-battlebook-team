"""Read-only Windows LCU feasibility probe. Python 3.10+, standard library only.

Credentials stay in memory. Requests only go to HTTPS 127.0.0.1, without proxies
or redirects. Default reports contain field names and counts, not player IDs.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class ProbeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def processes():
    if os.name != 'nt':
        raise ProbeError('windows_required')
    command = ("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
               "@(Get-CimInstance Win32_Process -ErrorAction Stop | "
               "Where-Object {$_.Name -in @('LeagueClient.exe','LeagueClientUx.exe')} | "
               "Select-Object Name,ProcessId,ExecutablePath,CommandLine) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, encoding='utf-8', timeout=20, check=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        data = json.loads(result.stdout.lstrip('\ufeff') or '[]')
        return data if isinstance(data, list) else [data]
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ProbeError('process_inventory_unavailable') from None


def parse_lockfile(text):
    parts = text.strip().split(':')
    if len(parts) != 5 or parts[0].lower() != 'leagueclient' or parts[4] != 'https':
        raise ProbeError('invalid_lcu_lockfile')
    try:
        pid, port = int(parts[1]), int(parts[2])
    except ValueError:
        raise ProbeError('invalid_lcu_lockfile') from None
    if not (1 <= port <= 65535) or pid <= 0 or not parts[3]:
        raise ProbeError('invalid_lcu_lockfile')
    return pid, port, parts[3]


def discover(rows, explicit=None, log_dir=None, diagnostics=None):
    client_rows = [r for r in rows if str(r.get('Name', '')).lower() == 'leagueclient.exe']
    if not client_rows:
        raise ProbeError('client_not_running')
    live_pids = {int(r['ProcessId']) for r in client_rows}
    ux_pids = {int(r['ProcessId']) for r in rows if str(r.get('Name', '')).lower() == 'leagueclientux.exe'}
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    else:
        for row in rows:
            if row.get('ExecutablePath'):
                candidates.append(Path(row['ExecutablePath']).parent / 'lockfile')
        # Bounded well-known install folders; no drive-wide recursive search.
        for root in ('C:/', 'D:/'):
            for suffix in ('WeGameApps/英雄联盟/LeagueClient', 'Riot Games/League of Legends',
                           'Program Files/Tencent/英雄联盟/LeagueClient',
                           'Program Files (x86)/Tencent/英雄联盟/LeagueClient'):
                candidates.append(Path(root) / suffix / 'lockfile')
    found = {}
    if diagnostics is not None:
        diagnostics['process_command_line_readable'] = any(bool(r.get('CommandLine')) for r in rows)
        diagnostics['empty_lockfiles'] = 0
    for path in dict.fromkeys(candidates):
        try:
            text = path.read_text(encoding='utf-8-sig')
            if not text.strip() and diagnostics is not None:
                diagnostics['empty_lockfiles'] += 1
            pid, port, token = parse_lockfile(text)
        except (OSError, UnicodeError, ProbeError):
            continue
        if pid in live_pids:
            found[port] = (port, token, 'lockfile')
    if not explicit:
        for row in rows:
            command = row.get('CommandLine') or ''
            port_match = re.search(r'--app-port(?:=|\s+)["\x27]?(\d+)', command)
            token_match = re.search(r'--remoting-auth-token(?:=|\s+)["\x27]?([^\s"\x27]+)', command)
            if port_match and token_match:
                port = int(port_match[1])
                if 1 <= port <= 65535:
                    # Prefer the running client's lockfile when it is readable.
                    found.setdefault(port, (port, token_match[1], 'process'))
    if not found:
        # Tencent may leave lockfile empty. Read only Ux startup logs whose
        # filenames identify BOTH currently running backend and Ux PIDs.
        # Never print log lines or save discovered credentials.
        folders = [Path(log_dir)] if log_dir else list(dict.fromkeys(p.parent for p in candidates))
        for folder in folders:
            for pid in live_pids:
                for ux_pid in ux_pids:
                    for logfile in folder.glob(f'*_{pid}_{ux_pid}_LeagueClientUx.log'):
                        try:
                            with logfile.open(encoding='utf-8', errors='replace') as handle:
                                startup = handle.read(512 * 1024)
                        except OSError:
                            continue
                        port_match = re.search(r'--app-port(?:=|\s+)["\x27]?(\d+)', startup)
                        token_match = re.search(r'--remoting-auth-token(?:=|\s+)["\x27]?([^\s"\x27]+)', startup)
                        if port_match and token_match and 1 <= int(port_match[1]) <= 65535:
                            port = int(port_match[1])
                            found[port] = (port, token_match[1], 'current_pid_ux_startup_log')
    if not found:
        raise ProbeError('credentials_unavailable_or_stale_lockfile')
    if len(found) != 1:
        raise ProbeError('multiple_clients_use_explicit_lockfile')
    return next(iter(found.values()))


def allowed_path(path):
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or '\\' in path:
        return False
    routes = (r'/lol-summoner/v1/current-summoner', r'/riotclient/region-locale',
              r'/lol-patch/v1/game-version', r'/lol-game-queues/v1/queues',
              r'/lol-summoner/v1/alias/lookup',
              r'/lol-match-history/v1/products/lol/(?:current-summoner|[A-Za-z0-9_-]+)/matches',
              r'/lol-match-history/v1/(?:games|game-timelines)/[0-9]+')
    return any(re.fullmatch(route, parsed.path) for route in routes)


class Client:
    def __init__(self, port, token, report, raw_dir=None):
        self.base = f'https://127.0.0.1:{port}'
        self.authorization = 'Basic ' + base64.b64encode(('riot:' + token).encode()).decode()
        # Only this loopback HTTPS connection skips the client's self-signed cert.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                  urllib.request.HTTPSHandler(context=context))
        self.report = report
        self.raw_dir = raw_dir

    def get(self, label, path, template=None, lookup_body=None):
        method = 'POST' if lookup_body is not None else 'GET'
        readonly_alias_lookup = path == '/lol-summoner/v1/summoners/aliases' and lookup_body is not None
        if not allowed_path(path) and not readonly_alias_lookup:
            raise ProbeError('path_not_allowlisted')
        if lookup_body is not None and not readonly_alias_lookup:
            raise ProbeError('post_only_allowed_for_alias_lookup')
        entry = {'label': label, 'method': method, 'path': template or path.split('?')[0]}
        self.report['endpoints'].append(entry)
        start = time.monotonic()
        try:
            request = urllib.request.Request(self.base + path,
                data=json.dumps(lookup_body).encode() if lookup_body is not None else None,
                headers={'Authorization': self.authorization, 'Accept': 'application/json',
                         'Content-Type': 'application/json'}, method=method)
            with self.opener.open(request, timeout=12) as response:
                entry['status'] = response.status
                body = response.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                entry['error'] = 'response_too_large'
                return None
            data = json.loads(body)
            entry['json_type'] = type(data).__name__
            if isinstance(data, dict):
                entry['top_level_keys'] = sorted(data)
            if self.raw_dir:
                self.raw_dir.mkdir(parents=True, exist_ok=True)
                (self.raw_dir / (label + '.json')).write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            return data
        except urllib.error.HTTPError as error:
            entry['status'] = error.code
            entry['error'] = 'http_error_body_omitted'
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            # Exception messages can contain request URLs or credentials: omit them.
            entry['error'] = type(error).__name__
        finally:
            entry['elapsed_ms'] = round((time.monotonic() - start) * 1000)
            time.sleep(0.15)
        return None


def history_games(data):
    if not isinstance(data, dict):
        return []
    games = data.get('games', {})
    games = games.get('games', []) if isinstance(games, dict) else games
    return [g for g in games if isinstance(g, dict)] if isinstance(games, list) else []


def augment_fields(data, prefix=''):
    result = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f'{prefix}.{key}' if prefix else key
            if 'augment' in key.lower():
                # Return only numeric IDs, never arbitrary strings or player names.
                if isinstance(value, int) and not isinstance(value, bool):
                    result[path] = value
                elif isinstance(value, list):
                    result[path] = [v for v in value if isinstance(v, int) and not isinstance(v, bool)]
                else:
                    result[path] = {'present': True, 'type': type(value).__name__}
            elif isinstance(value, (dict, list)):
                result.update(augment_fields(value, path))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            result.update(augment_fields(value, f'{prefix}[{index}]'))
    return result


def detail_summary(data):
    participants = data.get('participants', [])
    participants = participants if isinstance(participants, list) else []
    stats_keys = set()
    members = []
    for index, participant in enumerate(participants):
        if not isinstance(participant, dict):
            continue
        stats = participant.get('stats', {})
        stats = stats if isinstance(stats, dict) else {}
        stats_keys.update(stats)
        members.append({'slot': index + 1, 'championId': participant.get('championId'),
                        'teamId': participant.get('teamId'),
                        'basic_fields_present': [k for k in ('win', 'kills', 'deaths', 'assists',
                            'totalDamageDealtToChampions', 'totalDamageTaken', 'goldEarned') if k in stats],
                        'augments': augment_fields(participant)})
    return {'queueId': data.get('queueId'), 'gameMode': data.get('gameMode'),
            'gameVersion': data.get('gameVersion'), 'gameDuration': data.get('gameDuration'),
            'participant_count': len(participants),
            'identity_count': len(data.get('participantIdentities', [])),
            'stat_keys': sorted(stats_keys), 'participants': members}


def run(args):
    report = {'schema_version': 1, 'checked_at': dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
              'scope': 'read_only_lcu_probe_not_full_history_import', 'endpoints': [],
              'privacy': 'no_auth_tokens_player_ids_or_names_in_this_report'}
    try:
        rows = processes()
        report['client_process_count'] = len(rows)
        report['discovery_diagnostics'] = {}
        port, token, method = discover(rows, args.lockfile, args.log_dir, report['discovery_diagnostics'])
        report['connection'] = {'host': '127.0.0.1', 'discovery': method, 'client_detected': True}
        client = Client(port, token, report, Path(args.save_raw) if args.save_raw else None)
        account = client.get('current_summoner', '/lol-summoner/v1/current-summoner')
        report['account_fields_present'] = sorted(account) if isinstance(account, dict) else []
        region = client.get('region', '/riotclient/region-locale')
        report['region'] = {k: region[k] for k in ('region', 'locale') if k in region} if isinstance(region, dict) else None
        version = client.get('version', '/lol-patch/v1/game-version')
        report['client_game_version'] = version if isinstance(version, str) else None
        queues = client.get('queues', '/lol-game-queues/v1/queues')
        queue_values = queues if isinstance(queues, list) else list(queues.values()) if isinstance(queues, dict) else []
        report['queue_candidates'] = [{k: q[k] for k in ('id', 'name', 'type', 'gameMode', 'description') if k in q}
            for q in queue_values if isinstance(q, dict) and (q.get('id') in args.queue_id or
                re.search(r'mayhem|海克斯', str(q.get('name', '')), re.I))]
        collected = {}
        history_success = False
        page_fingerprints = set()
        for page in range(args.pages):
            start = page * 20
            data = client.get(f'history_{page}',
                f'/lol-match-history/v1/products/lol/current-summoner/matches?begIndex={start}&endIndex={start+19}')
            history_success = history_success or (isinstance(data, dict) and 'games' in data)
            games = history_games(data)
            fingerprint = tuple(sorted(str(g.get('gameId')) for g in games))
            if fingerprint and fingerprint in page_fingerprints:
                report['pagination_warning'] = 'repeated_page_backend_may_ignore_indices'
                break
            page_fingerprints.add(fingerprint)
            for game in games:
                if str(game.get('gameId', '')).isdigit():
                    collected[str(game['gameId'])] = game
            if not games:
                break
        report['history_read_success'] = history_success
        report['history_unique_games'] = len(collected) if history_success else None
        report['history_queues'] = dict(collections.Counter(str(g.get('queueId')) for g in collected.values())) if history_success else None
        if isinstance(account, dict) and account.get('puuid'):
            puuid = urllib.parse.quote(str(account['puuid']), safe='')
            generic = client.get('puuid_history_self',
                f'/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=19',
                '/lol-match-history/v1/products/lol/{self_puuid}/matches')
            report['puuid_history_self_games'] = len(history_games(generic)) if isinstance(generic, dict) and 'games' in generic else None
            if not history_success and isinstance(generic, dict) and 'games' in generic:
                history_success = True
                report['history_fallback'] = 'self_puuid_first_page_only'
                for game in history_games(generic):
                    if str(game.get('gameId', '')).isdigit():
                        collected[str(game['gameId'])] = game
                report['history_read_success'] = True
                report['history_unique_games'] = len(collected)
                report['history_queues'] = dict(collections.Counter(str(g.get('queueId')) for g in collected.values()))
            if account.get('gameName') and account.get('tagLine'):
                alias = client.get('alias_lookup_self', '/lol-summoner/v1/summoners/aliases',
                    lookup_body=[{'gameName': account['gameName'], 'tagLine': account['tagLine']}])
                report['alias_self_matches_puuid'] = isinstance(alias, list) and bool(alias) and isinstance(alias[0], dict) and alias[0].get('puuid') == account['puuid']
        if args.friend_puuid:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', args.friend_puuid):
                raise ProbeError('invalid_friend_puuid_format')
            other = client.get('consenting_friend_history',
                f'/lol-match-history/v1/products/lol/{args.friend_puuid}/matches?begIndex=0&endIndex=19',
                '/lol-match-history/v1/products/lol/{consenting_friend_puuid}/matches')
            report['consenting_friend_history_games'] = len(history_games(other)) if isinstance(other, dict) and 'games' in other else None
        else:
            report['friend_validation'] = 'not_tested_no_consented_friend_supplied'
        report['samples'] = []
        candidates = [(gid, g) for gid, g in collected.items() if g.get('queueId') in args.queue_id]
        for index, (gid, _) in enumerate(candidates[:args.details]):
            detail = client.get(f'game_{index+1}', '/lol-match-history/v1/games/' + gid,
                                '/lol-match-history/v1/games/{gameId}')
            if isinstance(detail, dict):
                report['samples'].append(detail_summary(detail))
                timeline = client.get(f'timeline_{index+1}', '/lol-match-history/v1/game-timelines/' + gid,
                                      '/lol-match-history/v1/game-timelines/{gameId}')
                if isinstance(timeline, dict):
                    frames = timeline.get('frames', [])
                    report['samples'][-1]['timeline_frame_count'] = len(frames) if isinstance(frames, list) else 0
                    report['samples'][-1]['timeline_augment_fields'] = augment_fields(timeline)
        if not isinstance(account, dict) or not account.get('puuid'):
            report['result'], code = 'account_not_ready', 3
        elif not history_success:
            report['result'], code = 'history_unavailable', 4
        else:
            report['result'], code = 'history_readable', 0
    except ProbeError as error:
        report['result'] = str(error)
        code = 2
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': report['result'], 'report': str(target.resolve())}, ensure_ascii=False))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lockfile', help='Explicit LeagueClient lockfile path; never pass its contents.')
    parser.add_argument('--log-dir', help='Optional LeagueClientUx startup-log folder, checked against current process IDs.')
    parser.add_argument('--output', default='probe-report.json')
    parser.add_argument('--save-raw', metavar='PRIVATE_LOCAL_DIR', help='Optional unredacted game data; keep private.')
    parser.add_argument('--pages', type=int, choices=range(1, 6), default=3, metavar='1..5')
    parser.add_argument('--details', type=int, choices=range(0, 6), default=2, metavar='0..5')
    parser.add_argument('--queue-id', type=int, action='append', default=None,
                        help='Candidate queue to inspect, repeatable; default 2400, verify against live metadata.')
    parser.add_argument('--friend-puuid', help='Only a friend who has agreed to participate; omitted by default.')
    args = parser.parse_args()
    args.queue_id = args.queue_id or [2400]
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
