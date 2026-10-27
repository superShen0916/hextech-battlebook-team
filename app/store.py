from __future__ import annotations
import collections
import contextlib
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from core import SourceError, scrub, utc_now
from match_policy import apply_policy


class Store:
    def __init__(self, directory, account_key=None):
        self.directory = Path(directory)
        self.account_key = account_key
        from project_paths import RETIRED_DATABASE
        if (self.directory / 'mayhem.sqlite').resolve() == RETIRED_DATABASE:
            raise ValueError('retired_database_path: use data/mayhem.sqlite via project_paths')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'mayhem.sqlite'
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS accounts(account_key TEXT PRIMARY KEY, platform TEXT, puuid TEXT,
              game_name TEXT, tag_line TEXT, last_seen TEXT);
            CREATE TABLE IF NOT EXISTS matches(match_key TEXT PRIMARY KEY, queue_id INTEGER NOT NULL CHECK(queue_id=2400),
              game_mode TEXT NOT NULL CHECK(game_mode='KIWI'), started_ms INTEGER, patch TEXT,
              stats_eligible INTEGER, augment_complete INTEGER, payload TEXT NOT NULL, fetched_at TEXT, payload_hash TEXT);
            CREATE TABLE IF NOT EXISTS participants(match_key TEXT REFERENCES matches(match_key),
              participant_id INTEGER, puuid TEXT, team_id INTEGER, champion_id INTEGER, win INTEGER,
              kills INTEGER, deaths INTEGER, assists INTEGER, payload TEXT NOT NULL,
              PRIMARY KEY(match_key,participant_id));
            CREATE INDEX IF NOT EXISTS participant_puuid ON participants(puuid,match_key);
            CREATE TABLE IF NOT EXISTS account_matches(account_key TEXT REFERENCES accounts(account_key),
              match_key TEXT REFERENCES matches(match_key), PRIMARY KEY(account_key,match_key));
            CREATE TABLE IF NOT EXISTS discovered(account_key TEXT REFERENCES accounts(account_key),
              match_key TEXT, status TEXT, attempts INTEGER DEFAULT 0, last_error TEXT, updated_at TEXT,
              PRIMARY KEY(account_key,match_key));
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS source_payloads(match_key TEXT NOT NULL, kind TEXT NOT NULL,
              route TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL, fetched_at TEXT NOT NULL,
              PRIMARY KEY(match_key,kind,route));
            CREATE TABLE IF NOT EXISTS request_log(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
              match_key TEXT, route TEXT NOT NULL, attempt INTEGER, status INTEGER, elapsed_ms INTEGER,
              error TEXT, message TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS timelines(match_key TEXT PRIMARY KEY REFERENCES matches(match_key),
              route TEXT NOT NULL, frame_count INTEGER, event_count INTEGER, payload TEXT NOT NULL, fetched_at TEXT);
            CREATE TABLE IF NOT EXISTS timeline_frames(match_key TEXT REFERENCES timelines(match_key),
              frame_index INTEGER, timestamp_ms INTEGER, payload TEXT NOT NULL, PRIMARY KEY(match_key,frame_index));
            CREATE TABLE IF NOT EXISTS timeline_events(match_key TEXT REFERENCES timelines(match_key),
              frame_index INTEGER, event_index INTEGER, timestamp_ms INTEGER, event_type TEXT, payload TEXT NOT NULL,
              PRIMARY KEY(match_key,frame_index,event_index));
            ''')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def set(self, key, value):
        with self.connect() as db:
            db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, json.dumps(value, ensure_ascii=False)))

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    def account(self):
        key = getattr(self, 'account_key', None) or self.get('active_account')
        with self.connect() as db:
            row = db.execute('SELECT * FROM accounts WHERE account_key=?', (key,)).fetchone()
        return dict(row) if row else None

    def register(self, source, activate=True):
        account = source.account
        with self.connect() as db:
            db.execute('''INSERT INTO accounts VALUES(?,?,?,?,?,?) ON CONFLICT(account_key) DO UPDATE SET
                game_name=excluded.game_name,tag_line=excluded.tag_line,last_seen=excluded.last_seen''',
                (source.account_key, source.platform, account['puuid'], account.get('gameName', ''),
                 account.get('tagLine', ''), utc_now()))
        if activate:
            self.set('active_account', source.account_key)
        with self.connect() as db:
            row = db.execute('SELECT * FROM accounts WHERE account_key=?', (source.account_key,)).fetchone()
        return dict(row)

    def discover(self, account_key, ids):
        with self.connect() as db:
            db.executemany('''INSERT INTO discovered(account_key,match_key,status,updated_at) VALUES(?,?,'pending',?)
                ON CONFLICT(account_key,match_key) DO NOTHING''', [(account_key, mid, utc_now()) for mid in ids])

    def discovery_status(self, account_key, match_key, status, error=None):
        """Record a discovery outcome; a lost write lock must not end a collector run."""
        for attempt in range(6):
            try:
                with self.connect() as db:
                    db.execute('''UPDATE discovered SET status=?,attempts=attempts+1,last_error=?,updated_at=?
                        WHERE account_key=? AND match_key=?''', (status, error, utc_now(), account_key, match_key))
                return
            except sqlite3.Error:
                if attempt == 5:
                    raise
                time.sleep(2 * (attempt + 1))

    def has(self, account_key, match_key):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM account_matches WHERE account_key=? AND match_key=?',
                                   (account_key, match_key)).fetchone())

    def save_payload(self, match_key, kind, route, payload):
        text = json.dumps(scrub(payload), ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute('''INSERT INTO source_payloads VALUES(?,?,?,?,?,?)
              ON CONFLICT(match_key,kind,route) DO UPDATE SET payload=excluded.payload,
              payload_hash=excluded.payload_hash,fetched_at=excluded.fetched_at''',
              (match_key, kind, route, text, hashlib.sha256(text.encode()).hexdigest(), utc_now()))

    def log_request(self, run_id, match_key, route, record):
        with self.connect() as db:
            db.execute('''INSERT INTO request_log(run_id,match_key,route,attempt,status,elapsed_ms,error,message,created_at)
              VALUES(?,?,?,?,?,?,?,?,?)''', (run_id, match_key, route, record.get('attempt'), record.get('status'),
              record.get('elapsed_ms'), record.get('error'), record.get('message'), utc_now()))

    def put_timeline(self, match_key, route, payload):
        # validate_timeline must run first. Replace children atomically; re-runs cannot duplicate events.
        frames = payload['frames']
        with self.connect() as db:
            db.execute('DELETE FROM timeline_events WHERE match_key=?', (match_key,))
            db.execute('DELETE FROM timeline_frames WHERE match_key=?', (match_key,))
            db.execute('''INSERT INTO timelines VALUES(?,?,?,?,?,?) ON CONFLICT(match_key) DO UPDATE SET
              route=excluded.route,frame_count=excluded.frame_count,event_count=excluded.event_count,
              payload=excluded.payload,fetched_at=excluded.fetched_at''',
              (match_key, route, len(frames), sum(len(f.get('events', [])) for f in frames),
               json.dumps(scrub(payload), ensure_ascii=False), utc_now()))
            for i, frame in enumerate(frames):
                db.execute('INSERT INTO timeline_frames VALUES(?,?,?,?)',
                           (match_key, i, frame.get('timestamp'), json.dumps(scrub(frame), ensure_ascii=False)))
                for j, event in enumerate(frame.get('events', [])):
                    db.execute('INSERT INTO timeline_events VALUES(?,?,?,?,?,?)',
                      (match_key, i, j, event.get('timestamp'), event.get('type'), json.dumps(scrub(event), ensure_ascii=False)))

    def put(self, account_key, match):
        if match['queue_id'] != 2400 or match['game_mode'] != 'KIWI' or len(match['participants']) != 10:
            raise SourceError('store_rejected_non_target_or_incomplete_match')
        apply_policy(match)
        payload = json.dumps(match, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute('''INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_key) DO UPDATE SET
              started_ms=excluded.started_ms,patch=excluded.patch,stats_eligible=excluded.stats_eligible,
              augment_complete=excluded.augment_complete,payload=excluded.payload,fetched_at=excluded.fetched_at,
              payload_hash=excluded.payload_hash''',
              (match['match_key'], 2400, 'KIWI', match['started_ms'], match['patch'], int(match['stats_eligible']),
               int(match['augment_complete']), payload, utc_now(), hashlib.sha256(payload.encode()).hexdigest()))
            for player in match['participants']:
                db.execute('''INSERT INTO participants VALUES(?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(match_key,participant_id) DO UPDATE SET puuid=excluded.puuid,team_id=excluded.team_id,
                  champion_id=excluded.champion_id,win=excluded.win,kills=excluded.kills,deaths=excluded.deaths,
                  assists=excluded.assists,payload=excluded.payload''',
                  (match['match_key'], player['participant_id'], player['puuid'], player['team_id'], player['champion_id'],
                   int(player['win']), player['kills'], player['deaths'], player['assists'], json.dumps(player, ensure_ascii=False)))
            db.execute('INSERT OR IGNORE INTO account_matches VALUES(?,?)', (account_key, match['match_key']))
            db.execute('''INSERT INTO discovered(account_key,match_key,status,attempts,updated_at) VALUES(?,?,'complete',1,?)
                ON CONFLICT(account_key,match_key) DO UPDATE SET status='complete',last_error=NULL,updated_at=excluded.updated_at''',
                (account_key, match['match_key'], utc_now()))

    def all_matches(self, days=0, champion=0, patch=''):
        account = self.account()
        if not account:
            return []
        cutoff = int((dt.datetime.now(dt.timezone.utc).timestamp() - days * 86400) * 1000) if days else 0
        query = '''SELECT m.payload FROM matches m JOIN account_matches am USING(match_key)
                   WHERE am.account_key=? AND m.queue_id=2400 AND m.game_mode='KIWI' AND m.started_ms>=?
                   ORDER BY m.started_ms DESC'''
        with self.connect() as db:
            records = [json.loads(row['payload']) for row in db.execute(query, (account['account_key'], cutoff))]
        for match in records:
            apply_policy(match)
            match['self'] = next(p for p in match['participants'] if p['puuid'] == account['puuid'])
        return [m for m in records if (not champion or m['self']['champion_id'] == champion)
                and (not patch or '.'.join(m['patch'].split('.')[:2]) == patch)]

    def counts(self):
        account = self.account()
        if not account:
            return {}
        with self.connect() as db:
            return dict((row['status'], row['n']) for row in db.execute(
                'SELECT status,count(*) n FROM discovered WHERE account_key=? GROUP BY status', (account['account_key'],)))

    def detail(self, match_key):
        account = self.account()
        if not account:
            return None
        with self.connect() as db:
            row = db.execute('''SELECT m.payload FROM matches m JOIN account_matches am USING(match_key)
                  WHERE am.account_key=? AND m.match_key=?''', (account['account_key'], match_key)).fetchone()
        if not row:
            return None
        match = json.loads(row['payload'])
        for player in match['participants']:
            player['is_self'] = player['puuid'] == account['puuid']
            player.pop('puuid', None)
        return match


def metrics(matches):
    eligible = [m for m in matches if m['stats_eligible']]
    wins = sum(m['self']['win'] for m in eligible)
    totals = {k: sum(m['self'][k] for m in eligible) for k in ('kills', 'deaths', 'assists')}
    dpm, shares, kp = [], [], []
    champions, augments, daily = {}, collections.Counter(), {}
    for match in eligible:
        p = match['self']
        team = [x for x in match['participants'] if x['team_id'] == p['team_id']]
        team_kills = sum(x['kills'] for x in team)
        damage_known = all(isinstance(x['damage'], (int, float)) for x in team)
        team_damage = sum(x['damage'] for x in team) if damage_known else None
        if team_kills:
            kp.append((p['kills'] + p['assists']) / team_kills)
        if p['damage'] is not None and match['duration']:
            dpm.append(p['damage'] / (match['duration'] / 60))
        if team_damage:
            shares.append(p['damage'] / team_damage)
        for augment in set(p['augment_slots']):
            if isinstance(augment, int) and augment > 0:
                augments[augment] += 1
        cid = p['champion_id']
        hero = champions.setdefault(cid, {'champion_id': cid, 'champion_name': p['champion_name'],
                                        'games': 0, 'wins': 0, 'kills': 0, 'deaths': 0, 'assists': 0})
        hero['games'] += 1
        hero['wins'] += int(p['win'])
        for key in totals:
            hero[key] += p[key]
        day = dt.datetime.fromtimestamp(match['started_ms'] / 1000, dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        day_data = daily.setdefault(day, {'day': day, 'games': 0, 'wins': 0})
        day_data['games'] += 1
        day_data['wins'] += int(p['win'])
    mean = lambda values: sum(values) / len(values) if values else None
    return {'stored': len(matches), 'games': len(eligible), 'wins': wins,
        'win_rate': wins / len(eligible) if eligible else None,
        'kda': (totals['kills'] + totals['assists']) / totals['deaths'] if totals['deaths'] else None,
        'dpm': mean(dpm), 'damage_share': mean(shares), 'kill_participation': mean(kp),
        'augment_complete_games': sum(m['augment_complete'] for m in matches),
        'champions': sorted(champions.values(), key=lambda h: h['games'], reverse=True),
        'augments': [{'id': aid, 'uses': n} for aid, n in augments.most_common()],
        'daily': sorted(daily.values(), key=lambda d: d['day'])}
