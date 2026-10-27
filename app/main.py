from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from core import SourceError, utc_now
from store import Store, metrics
from sync import run_sync
from recover import run_recovery
from insights import build_insights
from review import timeline_review
from enrichment import enrich_matches
from companions import build_companions, companion_detail
from hexdata import load_ratings, rating_for
from project_paths import DATA

APP = Path(__file__).resolve().parent
DEFAULT_DATA = DATA


def load_static():
    result = {}
    for name in ('champions', 'augments', 'items'):
        path = APP / 'static' / (name + '.json')
        result[name] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return result


def icon_asset(relative):
    """Select an existing icon; never construct a filesystem path from a URL."""
    parts = relative.split('/')
    if len(parts) != 2 or parts[0] not in ('champions', 'items', 'augments'):
        return None
    directory = APP / 'static' / 'icons'
    folders = {name: directory/name for name in ('champions', 'items', 'augments')}
    folder = folders[parts[0]]
    if not folder.is_dir():
        return None
    for candidate in folder.iterdir():
        if (candidate.name == parts[1] and not candidate.is_symlink() and
                candidate.suffix in ('.png', '.webp', '.jpg', '.jpeg') and candidate.is_file()):
            return candidate
    return None


def overview(store, days=0, champion=0, patch=''):
    account = store.account()
    records = enrich_matches(store, store.all_matches(days, champion, patch))
    data = metrics(records)
    data['insights'] = build_insights(records)
    data['account'] = {k: account[k] for k in ('platform', 'game_name', 'tag_line')} if account else None
    data['rating'] = rating_for(account, load_ratings(store.directory))
    data['coverage'] = store.counts()
    data['sync'] = store.get('sync_status', {})
    data['recovery'] = store.get('recovery_status', {})
    with store.connect() as db:
        timeline_ids = {row[0] for row in db.execute('''SELECT t.match_key FROM timelines t JOIN account_matches am USING(match_key)
            WHERE am.account_key=?''', (account['account_key'] if account else '',))}
    data['timeline_coverage'] = len(timeline_ids)
    data['filtered_timeline_coverage'] = sum(m['match_key'] in timeline_ids for m in records)
    all_records = store.all_matches()
    data['patch_options'] = sorted({'.'.join(m['patch'].split('.')[:2]) for m in all_records}, reverse=True)
    data['champion_options'] = sorted({p['champion_id']: {'champion_id': p['champion_id'],
        'champion_name': p['champion_name']} for p in (m['self'] for m in all_records)}.values(), key=lambda p: p['champion_id'])
    data['range'] = {'oldest_ms': min((m['started_ms'] for m in records), default=None),
                     'newest_ms': max((m['started_ms'] for m in records), default=None)}
    data['recent'] = []
    for match in records:
        player = {k: v for k, v in match['self'].items() if k not in ('puuid', 'game_name', 'tag_line')}
        data['recent'].append({k: match[k] for k in ('match_key', 'patch', 'started_ms', 'duration', 'stats_eligible', 'augment_complete')} | {'player': player, 'timeline_available': match['match_key'] in timeline_ids})
    return data



class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, store):
        super().__init__(address, Handler)
        self.store = store
        self.nonce = secrets.token_urlsafe(32)
        self.job_lock = threading.Lock()
        self.job = None
        self.static_data = load_static()


class Handler(BaseHTTPRequestHandler):
    server_version = 'MayhemLocal/0.3'

    def log_message(self, *args):
        pass

    def allowed_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def send(self, status, data, content_type='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403, {'error': 'invalid_host'})
        url = urllib.parse.urlsplit(self.path)
        try:
            if url.path == '/':
                return self.send(200, (APP / 'dashboard.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path in ('/share', '/share.html'):
                return self.send(200, (APP / 'share.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/share-report':
                params = urllib.parse.parse_qs(url.query)
                minimum = int(params.get('minimum', ['20'])[0])
                days = int(params.get('days', ['0'])[0])
                if minimum not in (20, 30) or days not in (0, 30, 90, 365):
                    return self.send(400, {'error': 'invalid_share_filter'})
                from share_report import load_share_report
                return self.send(200, load_share_report(self.server.store.path,
                    minimum_award_games=minimum, days=days))
            if url.path.startswith('/assets/'):
                relative = urllib.parse.unquote(url.path[len('/assets/'):])
                if not re.fullmatch(r'(champions|items|augments)/[A-Za-z0-9_-]+\.(png|webp|jpg|jpeg)', relative):
                    return self.send(404, {'error': 'asset_not_found'})
                asset = icon_asset(relative)
                if asset is None:
                    return self.send(404, {'error': 'asset_not_found'})
                mime = {'.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}[asset.suffix]
                return self.send(200, asset.read_bytes(), mime)
            if url.path == '/api/bootstrap':
                return self.send(200, {'csrf': self.server.nonce, 'static': self.server.static_data})
            if url.path == '/api/health':
                return self.send(200, {'ok': True, 'mode': 'standard_mayhem_only', 'dashboard_version': 3, 'sharing_version': 3})
            if url.path == '/api/companions':
                records = enrich_matches(self.server.store, self.server.store.all_matches())
                return self.send(200, {'companions': build_companions(records, ratings=load_ratings(self.server.store.directory)), 'minimum_shared_games': 3,
                                      'scope': 'shared_matches_only'})
            if url.path.startswith('/api/companion/'):
                ref = urllib.parse.unquote(url.path[len('/api/companion/'):])
                params = urllib.parse.parse_qs(url.query)
                days = int(params.get('days', ['0'])[0])
                champion = int(params.get('champion', ['0'])[0])
                patch = params.get('patch', [''])[0]
                if (not re.fullmatch(r'[0-9a-f]{24}', ref) or days not in (0, 7, 30, 90, 365)
                        or champion < 0 or (patch and patch != 'unknown' and not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}', patch))):
                    return self.send(400, {'error': 'invalid_companion_filter'})
                records = enrich_matches(self.server.store, self.server.store.all_matches())
                record = companion_detail(records, ref, days=days, champion=champion, patch=patch,
                                          ratings=load_ratings(self.server.store.directory))
                return self.send(200 if record else 404, record or {'error': 'companion_not_found'})
            if url.path == '/api/overview':
                params = urllib.parse.parse_qs(url.query)
                days = int(params.get('days', ['0'])[0])
                champion = int(params.get('champion', ['0'])[0])
                patch = params.get('patch', [''])[0]
                if days not in (0, 7, 30, 90, 365) or champion < 0 or (patch and patch != 'unknown' and not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}', patch)):
                    return self.send(400, {'error': 'invalid_filter'})
                return self.send(200, overview(self.server.store, days, champion, patch))
            if url.path.startswith('/api/timeline/'):
                key = urllib.parse.unquote(url.path[len('/api/timeline/'):])
                if not re.fullmatch(r'[A-Za-z0-9]{1,12}_[0-9]{1,32}', key):
                    return self.send(400, {'error': 'invalid_match'})
                record = timeline_review(self.server.store, key)
                return self.send(200 if record else 404, record or {'error': 'match_not_found'})
            if url.path.startswith('/api/match/'):
                key = urllib.parse.unquote(url.path[len('/api/match/'):])
                if len(key) > 80:
                    return self.send(400, {'error': 'invalid_match'})
                params = urllib.parse.parse_qs(url.query)
                focus_ref = params.get('companion', [''])[0]
                focus = None
                if focus_ref:
                    if not re.fullmatch(r'[0-9a-f]{24}', focus_ref):
                        return self.send(400, {'error': 'invalid_companion'})
                    records = enrich_matches(self.server.store, self.server.store.all_matches())
                    companion = companion_detail(records, focus_ref)
                    focus = next((m for m in companion['recent'] if m['match_key'] == key), None) if companion else None
                    if not focus:
                        return self.send(404, {'error': 'companion_match_not_found'})
                record = self.server.store.detail(key)
                if record:
                    # detail() removes identities before responding. Enrich the
                    # account-scoped normalized record, then select public fields.
                    account = self.server.store.account()
                    with self.server.store.connect() as db:
                        row = db.execute('''SELECT m.payload FROM matches m JOIN account_matches am USING(match_key)
                            WHERE am.account_key=? AND m.match_key=?''', (account['account_key'], key)).fetchone()
                    if row:
                        private = json.loads(row['payload'])
                        enrich_matches(self.server.store, [private])
                        for public, enriched in zip(record['participants'], private['participants']):
                            public.update({k: enriched[k] for k in ('double_kills', 'triple_kills', 'quadra_kills',
                                'penta_kills', 'largest_multi_kill', 'largest_killing_spree', 'damage_share', 'damage_rank', 'performance')})
                        record['performance'] = private['performance']
                    if focus:
                        for player in record['participants']:
                            player['is_focus'] = player['participant_id'] == focus['focus_participant_id']
                        record['focus'] = {'ref': focus_ref, 'participant_id': focus['focus_participant_id'],
                                           'game_name': focus['player'].get('game_name', '')}
                return self.send(200 if record else 404, record or {'error': 'match_not_found'})
            if url.path == '/api/sync-status':
                return self.send(200, self.server.store.get('sync_status', {}))
            return self.send(404, {'error': 'not_found'})
        except (ValueError, TypeError):
            return self.send(400, {'error': 'invalid_request'})
        except Exception:
            return self.send(500, {'error': 'local_read_failed'})

    def do_POST(self):
        if not self.allowed_host():
            return self.send(403, {'error': 'invalid_host'})
        origin = self.headers.get('Origin')
        valid_origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if origin not in valid_origins or self.headers.get('X-Mayhem-CSRF') != self.server.nonce:
            return self.send(403, {'error': 'invalid_origin_or_csrf'})
        if self.path != '/api/sync':
            return self.send(404, {'error': 'not_found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024:
                return self.send(400, {'error': 'invalid_body_size'})
            body = json.loads(self.rfile.read(size))
            limit = int(body.get('limit', 200))
            if limit not in (20, 50, 200, 1000):
                return self.send(400, {'error': 'invalid_limit'})
        except (ValueError, TypeError, AttributeError):
            return self.send(400, {'error': 'invalid_json'})
        with self.server.job_lock:
            if self.server.job and self.server.job.is_alive():
                return self.send(409, {'error': 'sync_already_running'})
            def job():
                try:
                    run_sync(self.server.store.directory, limit)
                except SourceError:
                    pass
            self.server.job = threading.Thread(target=job, daemon=True)
            self.server.job.start()
        self.send(202, {'started': True})


def main():
    parser = argparse.ArgumentParser(description='Standard ARAM Mayhem local collector and dashboard')
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA))
    sub = parser.add_subparsers(dest='command', required=True)
    sync_parser = sub.add_parser('sync')
    sync_parser.add_argument('--limit', type=int, default=200)
    recovery_parser = sub.add_parser('recover', help='Retry saved missing matches (summaries only)')
    recovery_parser.add_argument('--rounds', type=int, default=2)
    recovery_parser.add_argument('--skip-timelines', action='store_true', help=argparse.SUPPRESS)
    recovery_parser.add_argument('--timeline-rounds', type=int, default=2, help=argparse.SUPPRESS)
    serve_parser = sub.add_parser('serve')
    serve_parser.add_argument('--port', type=int, default=8765)
    serve_parser.add_argument('--open', action='store_true')
    serve_parser.add_argument('--page', choices=('/', '/share'), default='/')
    sub.add_parser('status')
    args = parser.parse_args()
    store = Store(args.data_dir)
    if args.command == 'recover':
        try:
            state = run_recovery(args.data_dir, args.rounds, timelines=False,
                progress=lambda s: print(json.dumps(s, ensure_ascii=False), flush=True), timeline_rounds=args.timeline_rounds)
            return 0 if state.get('outcome') == 'completed' else 4
        except SourceError as error:
            print(str(error))
            return 2
    if args.command == 'sync':
        try:
            state = run_sync(args.data_dir, args.limit, progress=lambda s: print(json.dumps({
                k: s.get(k) for k in ('running', 'scanned', 'processed', 'completed', 'cached', 'failed', 'outcome')}, ensure_ascii=False), flush=True))
            return 0 if state.get('outcome') == 'completed_requested_window' else 4
        except SourceError as error:
            print(str(error))
            return 2
    if args.command == 'status':
        print(json.dumps({'coverage': store.counts(), 'sync': store.get('sync_status', {}),
                          'recovery': store.get('recovery_status', {})}, ensure_ascii=False))
    elif args.command == 'serve':
        try:
            server = LocalServer(('127.0.0.1', args.port), store)
        except OSError:
            existing = f'http://127.0.0.1:{args.port}'
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(existing + '/api/health', timeout=2) as response:
                    health = json.load(response)
                if health.get('ok') is True and health.get('mode') == 'standard_mayhem_only':
                    if health.get('dashboard_version') != 3 or health.get('sharing_version') != 3:
                        print('An older dashboard is running. After its sync finishes, close its dashboard window and run Start-Dashboard.cmd again.', flush=True)
                        return 2
                    print(existing + ' (already running)', flush=True)
                    if args.open:
                        webbrowser.open(existing + args.page)
                    return 0
            except Exception:
                pass
            print('Port unavailable. Use --port to choose another local port.')
            return 2
        url = f'http://127.0.0.1:{server.server_port}' + args.page
        print(url, flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
