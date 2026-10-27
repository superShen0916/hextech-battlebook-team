"""Read saved summaries, raw payloads and local databases; cache public Riot artwork.

头像来自历史摘要文件、source_payloads 完整对局原始数据与唯一项目数据库；
participants.payload 为裁剪字段，只作兜底。
"""
from pathlib import Path
import json, urllib.request, concurrent.futures, hashlib, os, sqlite3, sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
sys.path.insert(0,str(PROJECT/'app'))
from project_paths import DATABASE, DATA
snapshot = json.loads((ROOT / 'public/api/snapshot.json').read_text(encoding='utf-8'))
profiles = [*snapshot['players'],
            *[dict(c, id='shared-' + c['id']) for c in snapshot['companions']
              if c['name'] not in {p['name'] for p in snapshot['players']}]]

# 档案 id -> 明确 puuid：同名的不同账号不该互相抢头像
declared = {}
config = PROJECT / 'data/public-profiles.json'
if config.is_file():
    for row in json.loads(config.read_text(encoding='utf-8-sig')):
        if row.get('id') and row.get('expected_puuid'):
            declared[row['id']] = row['expected_puuid']

identities: dict[str, set] = {}
observations: dict[str, dict] = {}


def observe(identity, name, icon, observed_ms):
    if not identity or not name:
        return
    identities.setdefault(name, set()).add(identity)
    if isinstance(icon, int) and icon >= 0 and observed_ms > observations.get(identity, {}).get('observed_ms', -1):
        observations[identity] = {'icon_id': icon, 'observed_ms': observed_ms}


def payload_fields(raw):
    name = raw.get('riotIdGameName') or raw.get('game_name') or raw.get('summonerName')
    icon = raw.get('profileIcon')
    if icon is None:
        icon = raw.get('profileIconId')
    if icon is None:
        icon = raw.get('profile_icon')
    return raw.get('puuid'), name, icon


for directory in [DATA / 'raw']:
    if not directory.is_dir():
        continue
    for file in directory.glob('*.json'):
        try:
            raw = json.loads(file.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        if raw.get('queueId') != 2400 or raw.get('gameMode') != 'KIWI':
            continue
        timestamp = raw.get('gameStartTimestamp') or raw.get('gameCreation') or 0
        for participant in raw.get('participants', []):
            obtain, name, icon = payload_fields(participant)
            observe(obtain, name, icon, timestamp)

for db in [DATABASE]:
    if not db.is_file():
        continue
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    try:
        rows = connection.execute(
            'SELECT p.payload, m.started_ms FROM participants p JOIN matches m USING(match_key)')
        for payload, started in rows:
            try:
                raw = json.loads(payload)
            except ValueError:
                continue
            obtain, name, icon = payload_fields(raw)
            observe(obtain, name, icon, started or 0)
        # participants.payload 是归一化后的裁剪字段，不含 profileIcon；
        # source_payloads 保留完整对局原始数据，是头像唯一可靠来源，
        # 也覆盖采样快照之后新入队的玩家。
        try:
            rows = connection.execute(
                "SELECT payload FROM source_payloads WHERE kind = 'summary'")
        except sqlite3.OperationalError:
            rows = ()
        for (payload,) in rows:
            try:
                raw = json.loads(payload)
            except ValueError:
                continue
            stamp = raw.get('gameStartTimestamp') or raw.get('gameCreation') or 0
            for participant in raw.get('participants') or []:
                obtain, name, icon = payload_fields(participant)
                observe(obtain, name, icon, stamp)
    finally:
        connection.close()

proxy = os.environ.get('BATTLEBOOK_ASSET_PROXY', 'http://127.0.0.1:7897')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy} if proxy else {}))


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'HextechBattlebook-local-preview/1.0'})
    with opener.open(req, timeout=35) as response:
        return response.read()


version = '16.21.1'
try:
    champion_data = json.loads(get(f'https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json'))['data']
    champion_ids = {int(c['key']): c['id'] for c in champion_data.values()}
except Exception:
    champion_ids = {h['champion_id']: h.get('champion_name', '') for p in profiles for h in p.get('champions', [])}

manifest = ROOT / 'visual-assets-manifest.json'
public = {}
jobs = []
records = json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else []
missing_avatar = []
for p in profiles:
    hero = next(iter(p.get('champions', [])), {})
    cid = champion_ids.get(hero.get('champion_id'), '')
    data = {'name': p['name'], 'hero_id': hero.get('champion_id'), 'splash_url': None,
            'avatar_url': None, 'avatar_observed_ms': None}
    if cid and cid.isalpha():
        filename = f'splashes/{cid}.jpg'
        data['splash_url'] = '/assets/' + filename
        jobs.append((filename, f'https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{cid}_0.jpg'))
    if p['id'] in declared:
        observed = observations.get(declared[p['id']])
    else:
        candidates = identities.get(p['name'], set())
        observed = observations.get(next(iter(candidates))) if len(candidates) == 1 else None
    if observed:
        filename = f'profileicons/{observed["icon_id"]}.png'
        data.update(avatar_url='/assets/' + filename, avatar_icon_id=observed['icon_id'],
                    avatar_observed_ms=observed['observed_ms'])
        jobs.append((filename, f'https://ddragon.leagueoflegends.com/cdn/{version}/img/profileicon/{observed["icon_id"]}.png'))
    else:
        missing_avatar.append(p['name'])
    public[p['id']] = data


def cache(job):
    filename, url = job
    target = ROOT / 'public/assets' / filename
    if target.is_file():
        return filename, True
    try:
        payload = get(url)
        if not (payload.startswith(b'\x89PNG') or payload.startswith(b'\xff\xd8')):
            return filename, False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        records.append({'asset': filename, 'source': url, 'sha256': hashlib.sha256(payload).hexdigest()})
        return filename, True
    except Exception:
        return filename, False


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = dict(pool.map(cache, list(dict.fromkeys(jobs))))
for d in public.values():
    for key in ['splash_url', 'avatar_url']:
        if d.get(key) and not results.get(d[key].removeprefix('/assets/')):
            d[key] = None
(ROOT / 'public/visuals.json').write_text(json.dumps(public, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
manifest.write_text(json.dumps(list({r['asset']: r for r in records}.values()), ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'players': len(public),
                  'game_avatars': sum(bool(d['avatar_url']) for d in public.values()),
                  'hero_art': sum(bool(d['splash_url']) for d in public.values()),
                  'missing_avatar': missing_avatar}, ensure_ascii=False))
if not all(results.values()):
    sys.exit(4)
