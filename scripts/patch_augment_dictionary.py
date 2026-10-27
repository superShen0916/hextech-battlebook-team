"""Fill augment entries that appear in saved matches but are missing from the dictionary.

`update_assets.py` only refreshes entries that already exist, so any augment that
was absent when the dictionary was first built stays absent forever and renders
as "海克斯 #1234". This script adds those missing entries from the two public
sources the project already trusts:

  * Tencent KIWI augment list  -> Chinese name, description, small icon
  * CommunityDragon cherry     -> Chinese name, rarity, small icon

Only numeric game IDs already observed in the local database are added; nothing
about players or matches leaves the machine. Icons are written to
`app/static/icons/augments/` and mirrored into `site/public/assets/augments/`.

Run: Run-Python.cmd scripts/patch_augment_dictionary.py [--all]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
from pathlib import Path
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from update_assets import render_description

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
DATABASE = ROOT / 'data' / 'mayhem.sqlite'
PREVIEW_ICONS = ROOT / 'work' / 'players-preview-20261022' / 'public' / 'assets' / 'augments'
DICTIONARY = STATIC / 'augments.json'

PATCH = '16.21'
CD = f'https://raw.communitydragon.org/{PATCH}'
TENCENT = 'https://game.gtimg.cn/images/lol/act/img/js/kiwi/kiwi_augments.json'
CHERRY = CD + '/plugins/rcp-be-lol-game-data/global/zh_cn/v1/cherry-augments.json'
HOSTS = {'raw.communitydragon.org', 'game.gtimg.cn'}
USER_AGENT = 'HextechLocalAssets/1.0'
RARITY = {'kGold': 'gold', 'kSilver': 'silver', 'kPrismatic': 'prismatic', 'kBronze': 'silver'}


def fetch(url, maximum=8_000_000):
    if urllib.parse.urlsplit(url).scheme != 'https' or urllib.parse.urlsplit(url).hostname not in HOSTS:
        raise ValueError('host_not_allowed')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        if urllib.parse.urlsplit(response.url).hostname not in HOSTS:
            raise ValueError('redirect_rejected')
        return response.read(maximum)


def valid_png(body):
    return len(body) > 64 and body[:8] == b'\x89PNG\r\n\x1a\n'


def clean_description(text):
    """Use the same tooltip sanitizer as regular asset refreshes."""
    rendered, unresolved = render_description(text or '', {})
    return rendered, bool(unresolved)


def seen_augment_ids():
    if not DATABASE.is_file():
        return {}
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    counts = {}
    try:
        for row in connection.execute('SELECT payload FROM matches'):
            ids = set()

            def walk(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if 'augment' in key.lower() and isinstance(value, list):
                            ids.update(item for item in value if type(item) is int and item > 0)
                        walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(json.loads(row['payload']))
            for identifier in ids:
                counts[str(identifier)] = counts.get(str(identifier), 0) + 1
    finally:
        connection.close()
    return counts


def download(task):
    identifier, url = task
    target = STATIC / 'icons' / 'augments' / f'{identifier}.png'
    try:
        body = target.read_bytes() if target.exists() else fetch(url, maximum=2_000_000)
        if not valid_png(body):
            raise ValueError('invalid_png')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        for mirror in (PREVIEW_ICONS,):
            mirror.mkdir(parents=True, exist_ok=True)
            (mirror / f'{identifier}.png').write_bytes(body)
        return identifier, '/assets/augments/' + identifier + '.png', ''
    except Exception as error:  # noqa: BLE001 - report, never abort the batch
        return identifier, '', type(error).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='add every named KIWI augment, not only observed ones')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--offline-cache', type=Path, default=None, help='directory holding kiwi.json and cherry.json')
    args = parser.parse_args()

    dictionary = json.loads(DICTIONARY.read_text(encoding='utf-8'))
    if args.offline_cache:
        kiwi_rows = json.loads((args.offline_cache / 'kiwi.json').read_text(encoding='utf-8'))
        cherry_rows = json.loads((args.offline_cache / 'cherry.json').read_text(encoding='utf-8'))
    else:
        kiwi_rows = json.loads(fetch(TENCENT).decode('utf-8'))
        cherry_rows = json.loads(fetch(CHERRY).decode('utf-8'))

    kiwi = {str(row['augmentID']): row for row in kiwi_rows if row.get('augmentID')}
    cherry = {str(row['id']): row for row in cherry_rows if row.get('id')}
    observed = seen_augment_ids()

    targets = {identifier for identifier in observed if identifier not in dictionary}
    if args.all:
        targets |= {identifier for identifier, row in kiwi.items()
                    if 'KIWI' in str(row.get('mode', '')) and identifier not in dictionary}
    targets = {identifier for identifier in targets
               if identifier in kiwi or identifier in cherry}

    added, no_description, failures = [], [], []
    tasks = []
    for identifier in sorted(targets, key=lambda value: -observed.get(value, 0)):
        kiwi_row, cherry_row = kiwi.get(identifier, {}), cherry.get(identifier, {})
        name = (kiwi_row.get('name_cn') or cherry_row.get('nameTRA') or '').strip()
        if not name:
            continue
        description, dynamic = clean_description(kiwi_row.get('desc') or kiwi_row.get('tooltip') or '')
        entry = {
            'name': name,
            'rarity': RARITY.get(kiwi_row.get('level') or cherry_row.get('rarity') or '', ''),
            'description': description,
            'description_patch': PATCH,
            'icon_url': '',
            'description_source': TENCENT if description else '',
            'description_dynamic': dynamic,
            'asset_patch': PATCH,
            'dictionary_source': 'tencent_kiwi' if kiwi_row else 'cdragon_cherry',
        }
        if not description:
            no_description.append(identifier)
        dictionary[identifier] = entry
        added.append((identifier, name, observed.get(identifier, 0)))

        icon_url = kiwi_row.get('small_Icon') or ''
        if not icon_url and cherry_row.get('augmentSmallIconPath'):
            asset = cherry_row['augmentSmallIconPath'].removeprefix('/lol-game-data/assets/').lower()
            icon_url = CD + '/plugins/rcp-be-lol-game-data/global/default/' + asset
        if icon_url:
            tasks.append((identifier, icon_url))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(12, args.workers))) as executor:
        for identifier, public_url, error in executor.map(download, tasks):
            if public_url:
                dictionary[identifier]['icon_url'] = public_url
            if error:
                failures.append({'id': identifier, 'error': error})

    DICTIONARY.write_text(json.dumps(dictionary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'status': 'ok',
        'added': len(added),
        'dictionary_size': len(dictionary),
        'with_icon': sum(bool(dictionary[i]['icon_url']) for i, _, _ in added),
        'without_description': len(no_description),
        'icon_failures': failures,
        'top_added': [{'id': i, 'name': n, 'matches': m} for i, n, m in added[:15]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
