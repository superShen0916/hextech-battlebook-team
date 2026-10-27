"""Refresh pinned public game assets. Run with Run-Python.cmd scripts/update_assets.py.

Only public, numeric game IDs are used in URLs. The optional local database is
opened read-only to collect item IDs; no identity or match record is uploaded.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import struct
import urllib.parse
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
PATCH = '16.21'
DD_VERSION = '16.21.1'
CD = f'https://raw.communitydragon.org/{PATCH}'
DD = f'https://ddragon.leagueoflegends.com/cdn/{DD_VERSION}'
TENCENT = 'https://game.gtimg.cn/images/lol/act/img/js/kiwi/kiwi_augments.json'
HOSTS = {'raw.communitydragon.org', 'ddragon.leagueoflegends.com', 'game.gtimg.cn'}
USER_AGENT = 'HextechLocalAssets/1.0'
# 2026-10-23: KIWI 4.0 上线（Last-Modified Thu, 22 Oct 2026 08:14:14 GMT），
# 新增 40 个 isNew=1 的海克斯；旧值 3b6317… 对应 Thu, 14 Oct 2026 07:41:31 GMT。
TENCENT_SHA256 = 'd6e586312267ef07d8e5957b29c0455e8119bf4914ef6926d252920d18ea33f6'


def fetch(url, maximum=40_000_000):
    if urllib.parse.urlsplit(url).scheme != 'https' or urllib.parse.urlsplit(url).hostname not in HOSTS:
        raise ValueError('unsupported public asset source')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=12) as response:
        if urllib.parse.urlsplit(response.url).hostname not in HOSTS:
            raise ValueError('unexpected asset redirect')
        body = response.read(maximum + 1)
        if len(body) > maximum:
            raise ValueError('asset too large')
        return body, dict(response.headers)


def source_json(url, cache_name, manifest):
    cache = ROOT / 'work' / cache_name
    if cache.exists():
        body = cache.read_bytes()
        headers = {}
    else:
        body, headers = fetch(url)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    if url == TENCENT and digest != TENCENT_SHA256:
        raise ValueError('Tencent dictionary changed; verify its patch before updating the pinned SHA-256')
    manifest['sources'].append({'url': url, 'sha256': digest,
        'last_modified': headers.get('Last-Modified', 'Wed, 14 Oct 2026 07:41:31 GMT' if url == TENCENT else '')})
    return json.loads(body)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('br', 'p', 'div'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    value = html.unescape(value)
    value = re.sub(r'<\s*(/?)\s*([A-Za-z][A-Za-z0-9_-]*)([^>]*)>', r'<\1\2\3>', value)
    parser = PlainText()
    parser.feed(value)
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def render_description(value, constants, terms=None):
    unresolved = set()
    constants = {key.lower(): val for key, val in constants.items()}

    # Tooltip counters describe live in-game state, not a static effect or a
    # measured contribution in the match history. Omit their entire lines.
    lines = re.split(r'<br\s*/?>', value or '', flags=re.I)
    value = ' '.join(line for line in lines if not re.match(
        r'^(?:已[^：:]*|当前转化|命中的敌人|.*命中的敌人数量|.*获得的技能急速)[：:]', plain_text(line)))

    def replace(match):
        token = match.group(1)
        if token.lower() == 'spellname':
            return '对应技能'
        parsed = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)(?:\*(100))?', token)
        if parsed and parsed.group(1).lower() in constants:
            number = constants[parsed.group(1).lower()] * (100 if parsed.group(2) else 1)
            return f'{number:.5g}'
        unresolved.add(token)
        return '〔动态值〕'

    value = re.sub(r'@([^@]+)@', replace, value)
    value = re.sub(r'%i:[^%]+%', '', value)
    def term(match):
        key = match.group(1).strip().lower()
        if key == 'spellname':
            return '对应技能'
        return (terms or {}).get(key, '〔动态效果〕')
    value = re.sub(r'\{\{([^}]+)\}\}', term, value)
    text = plain_text(value)
    if unresolved:
        text += '（动态值以游戏内实际效果为准。）'
    return text, sorted(unresolved)


def valid_png(body):
    """Validate PNG framing, dimensions and CRCs; reject HTML/SVG/trailing data."""
    if not body.startswith(b'\x89PNG\r\n\x1a\n'):
        return False
    offset, first = 8, True
    while offset + 12 <= len(body):
        length = int.from_bytes(body[offset:offset + 4], 'big')
        end = offset + length + 12
        if end > len(body):
            return False
        kind, content = body[offset + 4:offset + 8], body[offset + 8:end - 4]
        crc = int.from_bytes(body[end - 4:end], 'big')
        if zlib.crc32(kind + content) & 0xffffffff != crc:
            return False
        if first:
            if kind != b'IHDR' or length != 13:
                return False
            width, height = struct.unpack('>II', content[:8])
            if not (1 <= width <= 1024 and 1 <= height <= 1024):
                return False
            first = False
        if kind == b'IEND':
            return length == 0 and end == len(body)
        offset = end
    return False


def used_item_ids():
    database = ROOT / 'data' / 'mayhem.sqlite'
    if not database.exists():
        return set()
    ids = set()
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        for (payload,) in connection.execute('SELECT payload FROM participants'):
            ids.update(str(value) for value in json.loads(payload).get('items', [])
                       if type(value) is int and value > 0)
    return ids


def download_icon(task):
    category, identifier, url = task
    if category not in ('champions', 'items', 'augments') or not re.fullmatch(r'\d+', identifier):
        return category, identifier, '', 'invalid asset path'
    path = STATIC / 'icons' / category / (identifier + '.png')
    try:
        body = path.read_bytes() if path.exists() else fetch(url, maximum=2_000_000)[0]
        if not valid_png(body):
            raise ValueError('invalid PNG')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return category, identifier, '/assets/' + category + '/' + identifier + '.png', ''
    except Exception as error:
        return category, identifier, '', type(error).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-items', action='store_true', help='download every dictionary item icon')
    parser.add_argument('--workers', type=int, default=10)
    args = parser.parse_args()
    manifest = {'patch': PATCH, 'ddragon_version': DD_VERSION, 'verified_date': '2026-10-23',
                'sources': [], 'failures': [], 'description_missing': [],
                'description_dynamic_ids': [], 'description_scope': 'KIWI, exact numeric ID and API name'}
    dictionaries = {kind: json.loads((STATIC / (kind + '.json')).read_text(encoding='utf-8'))
                    for kind in ('champions', 'items', 'augments')}
    champions = source_json(DD + '/data/zh_CN/champion.json', 'assets-dd-champions.json', manifest)['data']
    items = source_json(DD + '/data/zh_CN/item.json', 'assets-dd-items.json', manifest)['data']
    public = source_json(TENCENT, 'assets-tencent-kiwi.json', manifest)
    cherry = source_json(CD + '/plugins/rcp-be-lol-game-data/global/zh_cn/v1/cherry-augments.json',
                         'assets-source-cherry.json', manifest)
    kiwi = source_json(CD + '/game/maps/modespecificdata/kiwi.bin.json', 'assets-kiwi.json', manifest)
    strings = source_json(CD + '/game/en_us/data/menu/en_us/lol.stringtable.json',
                           'assets-strings-en_us.json', manifest)['entries']
    # Resolve the exact localization reference, not an Arena same-name effect.
    # The Chinese term also occurs literally in Tencent KIWI augment 2016.
    terms = {}
    if plain_text(strings.get('item_keyword_onhit', '')).endswith('On-Hit'):
        terms['item_keyword_onhit'] = '攻击特效（On-Hit）'
    manifest['term_expansions'] = terms
    mode_entries = {str(value['AugmentPlatformId']): value for value in kiwi.values()
                    if isinstance(value, dict) and value.get('__type') == 'AugmentData'
                    and 'AugmentPlatformId' in value}
    public_by_id = {str(value['augmentID']): value for value in public}
    icon_by_id = {str(value['id']): value for value in cherry}
    item_ids = set(dictionaries['items']) if args.all_items else used_item_ids()
    # An installation with no saved matches still gets the whole dictionary.
    if not item_ids:
        item_ids = set(dictionaries['items'])
    tasks = []
    for value in champions.values():
        identifier = str(value['key'])
        if identifier in dictionaries['champions']:
            tasks.append(('champions', identifier, DD + '/img/champion/' + value['image']['full']))
    for identifier in item_ids:
        if identifier in items and identifier in dictionaries['items']:
            tasks.append(('items', identifier, DD + '/img/item/' + items[identifier]['image']['full']))
    for identifier, entry in dictionaries['augments'].items():
        mode = mode_entries.get(identifier)
        official = public_by_id.get(identifier)
        if mode and official and 'KIWI' in {x.strip() for x in official.get('mode', '').split(',')} \
                and mode.get('AugmentNameId') == official.get('name_en'):
            spell = kiwi.get(mode.get('RootSpell'), {}).get('mSpell', {})
            constants = {}
            for value in spell.get('DataValues', []):
                values = value.get('values', [])
                if values and all(isinstance(x, (int, float)) and abs(x - values[0]) < 1e-6 for x in values):
                    constants[value['name']] = values[0]
            entry['description'], unresolved = render_description(official.get('desc') or official.get('tooltip'), constants, terms)
            entry['description_source'] = TENCENT
            entry['description_patch'] = PATCH
            entry['description_dynamic'] = bool(unresolved)
            if unresolved:
                manifest['description_dynamic_ids'].append(identifier)
        # 已退役/本轮下架的海克斯在上游解析不到：保留上一次有效描述，
        # 不要清空，否则历史对局里的海克斯会退化成空文本。
        if not entry.get('description'):
            manifest['description_missing'].append(identifier)
        icon = icon_by_id.get(identifier)
        if mode and icon and icon.get('augmentNameId') == mode.get('AugmentNameId'):
            asset = icon['augmentSmallIconPath'].removeprefix('/lol-game-data/assets/').lower()
            tasks.append(('augments', identifier, CD + '/plugins/rcp-be-lol-game-data/global/default/' + asset))
        elif (STATIC / 'icons' / 'augments' / (identifier + '.png')).is_file():
            # 本地已缓存过该图标：上游原始资料不再提供也继续可用。
            entry['icon_url'] = '/assets/augments/' + identifier + '.png'
    refreshed = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(12, args.workers))) as executor:
        for category, identifier, local_url, error in executor.map(download_icon, tasks):
            if local_url:
                dictionaries[category][identifier]['icon_url'] = local_url
                refreshed.add((category, identifier))
            if error:
                # 下载失败不清空已有图标，只记录，避免线上图片变 404。
                manifest['failures'].append({'kind': category, 'id': identifier, 'error': error})
    # All entries, including undiscovered items, have explicit text-only fallback.
    for category, dictionary in dictionaries.items():
        for identifier, entry in dictionary.items():
            entry.setdefault('icon_url', '')
            if (category, identifier) in refreshed or 'asset_patch' not in entry:
                entry['asset_patch'] = PATCH
        (STATIC / (category + '.json')).write_text(json.dumps(dictionary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest['coverage'] = {category: {'dictionary': len(dictionary),
        'icons': sum(bool(value.get('icon_url')) for value in dictionary.values())}
        for category, dictionary in dictionaries.items()}
    manifest['coverage']['augments']['descriptions'] = sum(bool(value['description']) for value in dictionaries['augments'].values())
    (STATIC / 'assets.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'coverage': manifest['coverage'], 'failures': len(manifest['failures']),
                      'description_missing': manifest['description_missing'],
                      'description_dynamic': len(manifest['description_dynamic_ids'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
