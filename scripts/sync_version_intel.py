r"""Import licensed AramHex aggregates, independently of personal battle records.

PowerShell: .\Run-Python.cmd scripts\sync_version_intel.py
Offline rebuild: add --offline. No client login, SQLite, or personal snapshot writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://github.com/czgreat/aramhex-data'
RAW = 'https://raw.githubusercontent.com/czgreat/aramhex-data/'
FILES = ('meta.json', 'heroes.json', 'hero_augments.json', 'augments.json')


def download(path):
    request = urllib.request.Request(RAW + path, headers={'User-Agent': 'HextechBattlebook/1.0'})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(raw)
    temporary.replace(path)


def counts(row):
    games, wins = row['games'], row['wins']
    if type(games) is not int or type(wins) is not int or not 0 <= wins <= games or games <= 0:
        raise ValueError('Invalid observation counts')
    if abs(row.get('win_rate', wins / games) - wins / games) > 0.000002:
        raise ValueError('Win rate does not match counts')
    return {'games': games, 'wins': wins, 'win_rate': wins / games}


def project(bundle, dataset, seq):
    meta, heroes, pairs, augments = (bundle[name] for name in FILES)
    patch = dataset['patch']
    if (meta['patch'] != patch or meta['mode'] != 'normal'
            or dataset['path'] != f'patches/{patch}/normal'):
        raise ValueError('Only exact live normal-patch datasets are supported')
    if sum(counts(h)['games'] for h in heroes.values()) != meta['matches']['valid'] * 10:
        raise ValueError('Hero participations do not equal valid matches times ten')
    if sum(h['wins'] for h in heroes.values()) != meta['matches']['valid'] * 5:
        raise ValueError('Win participations do not equal valid matches times five')
    provisional = set(meta.get('provisional_augments', {}))
    excluded = set(meta.get('excluded_augments', {}))
    totals, details = {}, {}
    for hero_id, rows in pairs.items():
        if hero_id not in heroes:
            raise ValueError('Unknown hero in pairs')
        projected = []
        for augment_id, row in rows.items():
            if augment_id in excluded:
                continue
            stat = counts(row)
            is_pbe = augment_id in provisional
            if not is_pbe and (stat['games'] > heroes[hero_id]['games']
                               or stat['wins'] > heroes[hero_id]['wins']
                               or stat['games'] - stat['wins'] > heroes[hero_id]['games'] - heroes[hero_id]['wins']):
                raise ValueError('Live pair counts exceed corresponding hero counts')
            if augment_id not in augments:
                raise ValueError('Unknown augment in pairs')
            projected.append({'id': augment_id, **stat, 'low_sample': bool(row.get('low_sample')),
                              'source': 'pbe' if is_pbe else 'live'})
            if not is_pbe:
                total = totals.setdefault(augment_id, {'games': 0, 'wins': 0, 'heroes': 0})
                total['games'] += stat['games']
                total['wins'] += stat['wins']
                total['heroes'] += 1
        details[hero_id] = {'schema_version': 1, 'patch': patch, 'hero_id': hero_id,
                            'snapshot_at': meta['snapshot_at'], 'pairs': projected}
    hero_rows = [{'id': hero_id, 'name': row['name'], 'title': row['title'], **counts(row)}
                 for hero_id, row in heroes.items()]
    augment_rows = [{'id': aid, **augments[aid], **value,
                     'win_rate': value['wins'] / value['games']}
                    for aid, value in totals.items()]
    return {'schema_version': 1, 'patch': patch, 'rule': meta['mode'], 'seq': seq,
            'snapshot_at': meta['snapshot_at'], 'window': meta['window'],
            'matches': meta['matches'], 'regions': meta['regions'],
            'source_url': SOURCE, 'license': 'CC BY-NC 4.0',
            'heroes': hero_rows, 'augments': augment_rows, 'augment_dictionary': augments,
            'provisional_augments': meta.get('provisional_augments', {}),
            'excluded_augments': meta.get('excluded_augments', {}),
            'global_augment_method': 'Across heroes, sum live final-holder wins and games, then divide; PBE excluded.'}, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'work/version-intel-cache')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/players-preview-20261022/public/api/version-intel')
    args = parser.parse_args()
    cache, output = args.cache_dir, args.output_dir
    for name in ('latest.json', 'index.json'):
        if not args.offline:
            write(cache / name, download('main/' + name))
    latest = json.loads((cache / 'latest.json').read_bytes())
    index = json.loads((cache / 'index.json').read_bytes())
    seq = latest['seq']
    datasets, pending = [], []
    for patch in (latest['patch'], '16.20'):
        dataset = next(d for d in index['datasets'] if d['path'] == f'patches/{patch}/normal')
        bundle = {}
        for name in FILES:
            file = cache / patch / name
            if not args.offline:
                write(file, download(f'data-v{seq}/{dataset["path"]}/{name}'))
            raw = file.read_bytes()
            spec = dataset['files'][name]
            if len(raw) != spec['size'] or hashlib.sha256(raw).hexdigest() != spec['sha256']:
                raise ValueError(f'Hash or size mismatch: {patch}/{name}')
            bundle[name] = json.loads(raw)
        overview, details = project(bundle, dataset, seq)
        pending.append((output / patch / 'overview.json', encode(overview)))
        pending.extend((output / patch / 'heroes' / (hid + '.json'), encode(detail)) for hid, detail in details.items())
        datasets.append({'patch': patch, 'snapshot_at': overview['snapshot_at'],
                         'matches': overview['matches']['valid'], 'heroes': len(overview['heroes']),
                         'augments': len(overview['augments']), 'pbe_augments': len(overview['provisional_augments'])})
    # No output changes occur until both complete datasets pass validation.
    for file, raw in pending:
        write(file, raw)
    write(output / 'index.json', encode({'schema_version': 1, 'seq': seq, 'default_patch': latest['patch'],
                                       'source_url': SOURCE, 'license': 'CC BY-NC 4.0', 'datasets': datasets}))
    print(json.dumps({'ok': True, 'datasets': datasets, 'files': len(pending) + 1,
                      'bytes': sum(len(raw) for _, raw in pending)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
