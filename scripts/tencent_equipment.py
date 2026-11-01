"""Tencent's public KIWI equipment aggregates and augment tiers/pick rates.

Imported by sync_version_intel.py. Percentages are kept as supplied by Tencent;
the endpoint publishes neither sample counts nor a patch/window/region scope.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
import re
import time
import urllib.error
import urllib.request

SOURCE = 'https://mlol.qt.qq.com/go/battle_info/odp_proxy/fuwen_hero_rank'
LIMIT = 2 * 1024 * 1024
GROUPS = ('items', 'core', 'boots', 'starting', 'full')


def number(value, scale=1):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('invalid_equipment_rate')
    result = float(value) / scale
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError('invalid_equipment_rate')
    return result


def option(ids, pick, win, separator, scale=1):
    if not isinstance(ids, str) or not re.fullmatch(r'[1-9][0-9]*(?:' + re.escape(separator) + r'[1-9][0-9]*)*', ids):
        raise ValueError('invalid_equipment_ids')
    return {'items': ids.split(separator), 'pick_rate': number(pick, scale), 'win_rate': number(win, scale)}


def payload(body):
    if not isinstance(body, dict) or type(body.get('code')) is not int or body['code'] != 0:
        raise ValueError('tencent_equipment_upstream_error')
    data = body.get('data')
    fields = data.get('_fieldValues') if isinstance(data, dict) else None
    if not isinstance(fields, dict) or len(fields) != 1:
        raise ValueError('unexpected_equipment_envelope')
    raw = next(iter(fields.values()))
    if not isinstance(raw, str):
        raise ValueError('unexpected_equipment_payload')
    if raw == '':
        return None  # Explicit upstream "no data", distinct from a failed request.
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('unexpected_equipment_payload')
    return result


def text(source, key):
    value = source.get(key)
    if not isinstance(value, str):
        raise ValueError('missing_equipment_field:' + key)
    return value


def project_hero(body, identifier, identity):
    source = payload(body)
    result = {'id': identifier, 'name': identity['title'], 'title': identity['name'],
              'stats_date': None, 'available': False, **{key: [] for key in GROUPS}}
    if source is None:
        return result
    day = source.get('dtstatdate')
    if not isinstance(day, str) or not re.fullmatch(r'\d{8}', day):
        raise ValueError('missing_equipment_date')
    result['stats_date'] = datetime.strptime(day, '%Y%m%d').date().isoformat()
    for target, key, item_key in (('items', 'itemone_json', 'itemone'), ('core', 'itemcore_json', 'itemcore')):
        rows = json.loads(text(source, key) or '{}')
        if not isinstance(rows, dict) or any(not re.fullmatch(r'[1-9][0-9]*', rank) for rank in rows):
            raise ValueError('invalid_equipment_rows')
        result[target] = [option(row[item_key], row['showrate'], row['winrate'], '&', 10000)
                          for _, row in sorted(rows.items(), key=lambda pair: int(pair[0]))]
    for target, key in (('boots', 'itemshoes'), ('starting', 'itemout')):
        for row in text(source, key).split('#'):
            if row:
                ids, pick, win = row.split('$')
                result[target].append(option(ids, pick, win, ','))
    for row in text(source, 'itemover_rec').split(';'):
        if row:
            rank, ids, pick, win = row.split('_')
            if not rank.isdigit():
                raise ValueError('invalid_equipment_rank')
            result['full'].append(option(ids, pick, win, ','))
    for key in GROUPS:
        if len({tuple(row['items']) for row in result[key]}) != len(result[key]):
            raise ValueError('duplicate_equipment_option')
    result['available'] = any(result[key] for key in GROUPS)
    return result


def project_augments(raw, equipment, catalog, icon_exists):
    """Keep source tiers/pick rates; never manufacture missing win rates/counts."""
    rarity_codes = {'kSilver': 'silver', 'kGold': 'gold', 'kPrismatic': 'prismatic'}
    heroes = []
    used = set()
    for identity in equipment['heroes']:
        hid = identity['id']
        source = payload(raw['heroes'][hid])
        rows = []
        if source is not None:
            encoded = text(source, 'augment_json_irank')
            segments = {}
            for segment in encoded.split('&') if encoded else []:
                key, delimiter, value = segment.partition(':')
                if not delimiter or key in segments or key not in ('255', *rarity_codes):
                    raise ValueError('invalid_augment_segments')
                parsed = {}
                for record in value.split('#') if value else []:
                    parts = record.split('|')
                    if (len(parts) != 6 or parts[1] != hid or parts[3] != key
                            or not re.fullmatch(r'[1-9][0-9]*', parts[0])
                            or not re.fullmatch(r'[1-9][0-9]*', parts[2])
                            or parts[5] not in ('S', 'A', 'B', 'C') or parts[2] in parsed):
                        raise ValueError('invalid_augment_record')
                    parsed[parts[2]] = {'id': parts[2], 'source_rank': int(parts[0]),
                                        'pick_rate': number(parts[4]), 'tier': parts[5]}
                segments[key] = parsed
            if encoded:
                if set(segments) != {'255', *rarity_codes}:
                    raise ValueError('incomplete_augment_segments')
                classified = {}
                for key, rarity in rarity_codes.items():
                    for aid, row in segments[key].items():
                        if aid in classified:
                            raise ValueError('duplicate_augment_rarity')
                        all_row = segments['255'].get(aid)
                        if (not all_row
                                or not math.isclose(row['pick_rate'], all_row['pick_rate'], abs_tol=1e-9)):
                            raise ValueError('inconsistent_augment_segments')
                        classified[aid] = {**all_row, 'rarity': rarity,
                                           'rarity_tier': row['tier'], 'rarity_rank': row['source_rank']}
                if set(classified) != set(segments['255']):
                    raise ValueError('incomplete_augment_rarities')
                rows = sorted(classified.values(), key=lambda row: row['source_rank'])
        used.update(row['id'] for row in rows)
        heroes.append({key: identity[key] for key in ('id', 'name', 'title', 'stats_date')} | {'augments': rows})
    if not used:
        raise ValueError('empty_augment_dataset')
    dictionary = {}
    for aid in sorted(used, key=int):
        entry = catalog.get(aid, {})
        dictionary[aid] = {'name': entry.get('name') or '海克斯 #' + aid,
                           'description': entry.get('description', ''),
                           'description_patch': entry.get('description_patch'),
                           'icon_url': '/assets/augments/' + aid + '.png' if icon_exists(aid) else None}
    digest = hashlib.sha256(json.dumps(heroes, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {key: equipment[key] for key in ('source', 'source_url', 'mode', 'queue_id', 'patch',
                                            'sample_size', 'sample_scope', 'window', 'regions',
                                            'retrieved_at', 'stats_date_min', 'stats_date_max')} | {
        'schema_version': 1, 'win_rate': None, 'metric': 'source_tier_and_pick_rate',
        'snapshot_id': digest, 'heroes': heroes, 'dictionary': dictionary}


def fetch(identifier):
    if not re.fullmatch(r'[1-9][0-9]*', identifier):
        raise ValueError('invalid_equipment_hero')
    request = urllib.request.Request(SOURCE + '?championid=' + identifier,
                                    headers={'Accept': 'application/json', 'Accept-Encoding': 'gzip',
                                             'User-Agent': 'HextechBattlebook/1.0'})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.url != request.full_url:
                    raise ValueError('unexpected_equipment_redirect')
                raw = response.read(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError('equipment_response_too_large')
                if response.headers.get('Content-Encoding') == 'gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                        raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('equipment_response_too_large')
            return json.loads(raw)
        except (OSError, urllib.error.URLError):
            if attempt:
                raise
            time.sleep(1)


def project(raw, champions, items, icon_exists):
    bodies = raw['heroes']
    if set(bodies) != set(champions):
        raise ValueError('incomplete_equipment_heroes')
    heroes = [project_hero(bodies[hid], hid, champions[hid]) for hid in sorted(champions, key=int)]
    dates = sorted({hero['stats_date'] for hero in heroes if hero['available']})
    if not dates:
        raise ValueError('empty_equipment_dataset')
    used = {iid for hero in heroes for group in GROUPS for row in hero[group] for iid in row['items']}
    dictionary = {}
    for iid in sorted(used, key=int):
        entry = items.get(iid, {})
        dictionary[iid] = {'name': entry.get('name') or '装备 #' + iid,
                           'icon_url': '/assets/items/' + iid + '.png' if icon_exists(iid) else None}
    content = json.dumps(heroes, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'schema_version': 1, 'source': 'Tencent', 'source_url': SOURCE,
            'mode': 'KIWI', 'queue_id': 2400, 'patch': None, 'sample_size': None,
            'sample_scope': 'undisclosed', 'window': None, 'regions': None,
            'retrieved_at': raw['retrieved_at'], 'stats_date_min': dates[0], 'stats_date_max': dates[-1],
            'snapshot_id': hashlib.sha256(content).hexdigest(), 'heroes': heroes, 'items': dictionary}


def refresh(cache, output, static, public, *, offline=False):
    """Validate the full response set before atomically replacing one public snapshot."""
    from snapshot_io import write_json
    champions = json.loads((static / 'champions.json').read_text(encoding='utf-8'))
    items = json.loads((static / 'items.json').read_text(encoding='utf-8'))
    catalog = json.loads((static / 'augments.json').read_text(encoding='utf-8'))
    path = cache / 'tencent-equipment.json'
    if offline:
        raw = json.loads(path.read_bytes())
    else:
        ids = sorted(champions, key=int)
        pool = ThreadPoolExecutor(max_workers=3)
        try:
            bodies = dict(zip(ids, pool.map(fetch, ids), strict=True))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        raw = {'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'heroes': bodies}
    data = project(raw, champions, items, lambda iid: (public / 'assets/items' / (iid + '.png')).is_file())
    augments = project_augments(raw, data, catalog, lambda aid: (public / 'assets/augments' / (aid + '.png')).is_file())
    if not offline:
        write_json(path, raw)
    write_json(output / 'tencent-equipment.json', data)
    write_json(output / 'tencent-augments.json', augments)
    return {'ok': True, 'source': 'Tencent', 'heroes': len(data['heroes']),
            'available': sum(hero['available'] for hero in data['heroes']),
            'augment_pairs': sum(len(hero['augments']) for hero in augments['heroes']),
            'stats_date_min': data['stats_date_min'], 'stats_date_max': data['stats_date_max'],
            'snapshot_id': data['snapshot_id']}
