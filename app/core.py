"""Tencent standard-Mayhem source adapter. No third-party packages required."""
from __future__ import annotations
import base64
import datetime as dt
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import lcu_probe

LOCAL_ROUTES = {'/lol-summoner/v1/current-summoner', '/lol-chat/v1/me',
                '/client-config/v2/namespace/lol.client_settings', '/entitlements/v1/token'}
MATCH_ID = re.compile(r'[A-Z0-9]+_[0-9]+\Z')
BATCH_LIMIT = 100


class SourceError(Exception):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(f'{code}' + (f' (HTTP {status})' if status else ''))


def error_excerpt(body, secrets=()):
    """Keep only diagnostic fields, never arbitrary response data or headers."""
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            return 'non_json_error_body'
        status = data.get('status')
        if isinstance(status, dict):
            data = status
        clean = {k: data[k] for k in ('message', 'errorCode', 'status_code', 'httpStatus')
                 if k in data and isinstance(data[k], (str, int))}
        text = json.dumps(clean, ensure_ascii=False)
        for value in secrets:
            if isinstance(value, str) and value:
                text = text.replace(value, '[redacted]')
        text = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[jwt]', text)
        text = re.sub(r'[A-Z0-9]+_\d{5,}', '[match]', text)
        text = re.sub(r'\b\d{7,}\b', '[number]', text)
        return text[:1200]
    except (ValueError, TypeError, UnicodeError):
        return 'non_json_error_body'


class NotStandardMayhem(SourceError):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def scrub(data):
    if isinstance(data, dict):
        return {k: scrub(v) for k, v in data.items()
                if k.lower() not in ('token', 'accesstoken', 'authorization', 'password', 'spectatorkey')}
    if isinstance(data, list):
        return [scrub(v) for v in data]
    return data


def approved_origin(value):
    if not isinstance(value, str):
        raise SourceError('missing_tencent_endpoint')
    parts = urllib.parse.urlsplit(value)
    if (parts.scheme != 'https' or not (parts.hostname or '').endswith('.lol.qq.com')
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ('', '/')):
        raise SourceError('unapproved_tencent_endpoint')
    return f'https://{parts.netloc}'


class TencentSource:
    def __init__(self):
        try:
            port, password, _ = lcu_probe.discover(lcu_probe.processes())
        except lcu_probe.ProbeError as error:
            raise SourceError(str(error)) from None
        self._local = lcu_probe.Client(port, password, {'endpoints': []})
        self.account = self.local_get('/lol-summoner/v1/current-summoner')
        chat = self.local_get('/lol-chat/v1/me')
        self.platform = chat.get('platformId')
        if not isinstance(self.platform, str) or not re.fullmatch('[A-Z0-9]+', self.platform):
            raise SourceError('invalid_current_platform')
        if not isinstance(self.account.get('puuid'), str) or not self.account['puuid']:
            raise SourceError('account_not_ready')
        config = self.local_get('/client-config/v2/namespace/lol.client_settings')
        self.origin = approved_origin(config.get('lol.client_settings.account_verification_edge.url')
                                      or config.get('lol.client_settings.league_edge.url'))
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), lcu_probe.NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._token, self._expires = '', 0
        self.request_count = 0
        self.refresh_token()

    @property
    def account_key(self):
        return self.platform + ':' + self.account['puuid']

    def local_get(self, path):
        if path not in LOCAL_ROUTES:
            raise SourceError('local_route_not_allowed')
        request = urllib.request.Request(self._local.base + path, headers={
            'Authorization': self._local.authorization, 'Accept': 'application/json'})
        try:
            with self._local.opener.open(request, timeout=12) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise SourceError('local_request_failed', error.code) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise SourceError('local_connection_failed') from None

    def refresh_token(self):
        credentials = self.local_get('/entitlements/v1/token')
        token = credentials.get('accessToken')
        if not isinstance(token, str) or not token:
            raise SourceError('login_token_unavailable')
        self._token, self._expires = token, time.time() + 120
        try:
            part = token.split('.')[1]
            self._expires = float(json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['exp'])
        except (ValueError, KeyError, IndexError, TypeError):
            pass

    def get(self, path, retries=1, diagnostic=None, timeout=15):
        # The caller can read only self-history and match IDs it obtained from it.
        if not path.startswith('/match-history-query/') or '\\' in path or urllib.parse.urlsplit(path).netloc:
            raise SourceError('remote_route_not_allowed')
        last = SourceError('remote_unavailable')
        for attempt in range(retries + 1):
            if time.time() >= self._expires - 45:
                self.refresh_token()
            if attempt:
                time.sleep(min(2 ** attempt, 8))
            started = time.monotonic()
            record = {'attempt': attempt + 1, 'status': None, 'error': None, 'message': None}
            try:
                request = urllib.request.Request(self.origin + path, headers={
                    'Authorization': 'Bearer ' + self._token, 'Accept': 'application/json'})
                self.request_count += 1
                with self._opener.open(request, timeout=timeout) as response:
                    record['status'] = response.status
                    body = response.read(16 * 1024 * 1024 + 1)
                if len(body) > 16 * 1024 * 1024:
                    raise SourceError('response_too_large')
                return json.loads(body)
            except urllib.error.HTTPError as error:
                record['status'] = error.code
                account = getattr(self, 'account', {})
                record['message'] = error_excerpt(error.read(8192), (self._token, account.get('puuid'),
                    account.get('gameName'), account.get('tagLine')))
                record['error'] = 'http_error'
                last = SourceError('upstream_unavailable', error.code)
                if error.code == 401 and attempt < retries:
                    self.refresh_token()
                elif error.code not in (429, 500, 502, 503, 504):
                    raise last from None
            except (OSError, ValueError, urllib.error.URLError):
                record['error'] = 'transport_or_json_error'
                last = SourceError('remote_connection_failed')
            finally:
                record['elapsed_ms'] = round((time.monotonic() - started) * 1000)
                if diagnostic:
                    diagnostic(record)
                time.sleep(0.25)
        raise last from None

    def list_ids(self, start, count):
        query = urllib.parse.urlencode({'startIndex': start, 'count': count, 'tag': 'q_2400'})
        puuid = urllib.parse.quote(self.account['puuid'], safe='')
        result = self.get(f'/match-history-query/v1/products/lol/player/{puuid}?{query}')
        if not isinstance(result, list) or not all(isinstance(v, str) and MATCH_ID.fullmatch(v) for v in result):
            raise SourceError('unexpected_history_schema')
        return result

    def summary(self, match_id):
        if not MATCH_ID.fullmatch(match_id):
            raise SourceError('invalid_match_id')
        result = self.get(f'/match-history-query/v3/product/lol/matchId/{match_id}/infoType/summary')
        if not isinstance(result, dict):
            raise SourceError('unexpected_match_schema')
        return result

    def summary_page(self, puuid, start, count, tag='q_2400'):
        """One page of full match summaries for any puuid, newest first."""
        result = self.get(summary_page_path(puuid, start, count, tag), timeout=60)
        return parse_summary_page(result)


def summary_page_path(puuid, start, count, tag='q_2400'):
    """Route for the paged SUMMARY listing; same payload as summary(match_id)."""
    if not isinstance(puuid, str) or not puuid or '\\' in puuid or '/' in puuid:
        raise SourceError('invalid_puuid')
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        raise SourceError('invalid_batch_window')
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= BATCH_LIMIT:
        raise SourceError('invalid_batch_window')
    if not isinstance(tag, str) or not re.fullmatch(r'q_[0-9]+', tag):
        raise SourceError('invalid_batch_queue')
    query = urllib.parse.urlencode({'startIndex': start, 'count': count, 'tag': tag})
    return f'/match-history-query/v1/products/lol/player/{urllib.parse.quote(puuid, safe="")}/SUMMARY?{query}'


def parse_summary_page(result):
    """[(match_id, raw_summary), ...] from a paged SUMMARY response.

    Upstream wraps each match as {"metadata": ..., "json": <summary>}; the inner
    object is byte-for-byte the shape of the single-match endpoint, so every
    downstream validator (normalize) can treat both sources identically.
    """
    games = result.get('games') if isinstance(result, dict) else None
    if not isinstance(games, list):
        raise SourceError('unexpected_history_schema')
    page = []
    for item in games:
        raw = item.get('json') if isinstance(item, dict) else None
        if not isinstance(raw, dict):
            raise SourceError('unexpected_history_schema')
        match_id = f'{raw.get("platformId")}_{raw.get("gameId")}'
        if not MATCH_ID.fullmatch(match_id):
            raise SourceError('unexpected_history_schema')
        page.append((match_id, raw))
    return page


def normalize(raw, self_puuid, expected_id=None):
    if raw.get('queueId') != 2400 or raw.get('gameMode') != 'KIWI':
        raise NotStandardMayhem('non_standard_queue')
    platform, game_id = raw.get('platformId'), raw.get('gameId')
    match_id = f'{platform}_{game_id}'
    if not MATCH_ID.fullmatch(match_id) or (expected_id and expected_id != match_id):
        raise SourceError('match_identity_mismatch')
    participants = raw.get('participants')
    if not isinstance(participants, list) or len(participants) != 10:
        raise SourceError('incomplete_ten_player_detail')
    if len({p.get('participantId') for p in participants}) != 10 or len({p.get('puuid') for p in participants}) != 10:
        raise SourceError('duplicate_or_missing_player_identity')
    if sum(p.get('puuid') == self_puuid for p in participants) != 1:
        raise SourceError('self_not_in_match')
    if any(sum(p.get('teamId') == team for p in participants) != 5 for team in (100, 200)):
        raise SourceError('unexpected_team_composition')
    members = []
    for p in participants:
        if not isinstance(p.get('puuid'), str) or not p['puuid'] or not isinstance(p.get('win'), bool):
            raise SourceError('missing_player_result')
        if any(type(p.get(k)) is not int or p[k] < 0 for k in ('championId', 'kills', 'deaths', 'assists')):
            raise SourceError('missing_core_stats')
        slots = [p.get(f'playerAugment{s}') for s in range(1, 7)]
        if any(v is not None and (type(v) is not int or v < 0) for v in slots):
            raise SourceError('invalid_augment_schema')
        members.append({'participant_id': p['participantId'], 'puuid': p['puuid'],
            'game_name': p.get('riotIdGameName') or p.get('summonerName') or '',
            'tag_line': p.get('riotIdTagline') or '', 'team_id': p['teamId'],
            'champion_id': p['championId'], 'champion_name': p.get('championName') or str(p['championId']),
            'win': p['win'], 'kills': p['kills'], 'deaths': p['deaths'], 'assists': p['assists'],
            'damage': p.get('totalDamageDealtToChampions'), 'taken': p.get('totalDamageTaken'),
            'gold': p.get('goldEarned'), 'heal': p.get('totalHealsOnTeammates'),
            'items': [p.get(f'item{s}') for s in range(7)], 'augment_slots': slots,
            'augment_complete': all(v is not None for v in slots)})
    if sum(p['win'] for p in members) != 5:
        raise SourceError('inconsistent_win_results')
    duration = raw.get('gameDuration')
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise SourceError('invalid_duration')
    return {'match_key': match_id, 'platform': platform, 'game_id': str(game_id),
        'queue_id': 2400, 'game_mode': 'KIWI', 'patch': raw.get('gameVersion') or 'unknown',
        'started_ms': raw.get('gameStartTimestamp') or raw.get('gameCreation'),
        'duration': duration, 'end_result': raw.get('endOfGameResult'),
        'mutators': raw.get('gameModeMutators'),
        'stats_eligible': raw.get('endOfGameResult') == 'GameComplete' and
                          not any(p.get('gameEndedInEarlySurrender') for p in participants),
        'augment_complete': all(p['augment_complete'] for p in members), 'participants': members}
