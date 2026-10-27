"""Versioned full team data bundles; GitHub Releases, never Git source history.

Archives contain game identities and battle history authorized for public sharing.
Public distribution is restricted to the canonical project repository.
The live SQLite is read using its backup API while both project locks are held.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'scripts')]
from project_paths import RELATIVE_PATHS
from public_site import _exclusive_lock
from release_files import file_hash, inspect_tree

FRONT = RELATIVE_PATHS['frontend']
NAME = 'battlebook-data.zip'
REPOSITORY = 'superShen0916/hextech-battlebook-team'
CONFIGS = ('public-profiles.json', 'collection.json', 'stat-exclusions.json',
           'collection-exclusions.json', 'haido-baseline-v4.json',
           'haido-weekly-calibration-v04.json', 'hexdata-ratings.json', 'champion-key-to-id.json')
REQUIRED = ('data/mayhem.sqlite', 'data/public-profiles.json', 'data/collection.json',
            'data/stat-exclusions.json', 'data/haido-baseline-v4.json',
            'data/haido-weekly-calibration-v04.json', 'work/build/snapshot.full.json',
            FRONT+'/public/api/manifest.json', FRONT+'/public/api/snapshot.json')


def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(temporary, path)


def project_locks(root):
    stack = ExitStack()
    try:
        for name in ('sync.lock', 'release.lock'):
            path = Path(root)/'work/build'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not stack.enter_context(_exclusive_lock(path)):
                raise RuntimeError('project_busy:'+name)
        return stack
    except BaseException:
        stack.close()
        raise


def database_backup(source, target):
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('backup_integrity_failed')
            if list(dst.execute('PRAGMA foreign_key_check')):
                raise RuntimeError('backup_foreign_keys_failed')
            return dst.execute('SELECT count(*) FROM matches').fetchone()[0]


def allowed_member(name):
    p = PurePosixPath(name)
    if '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or p.as_posix() != name:
        return False
    return (name in ('data/mayhem.sqlite', 'work/build/snapshot.full.json',
                     'work/build/cache/details.bundle.json', 'haido/haido_scores_lp.json') or
            name in {'data/'+x for x in CONFIGS} or
            (name.startswith('data/raw/') and p.suffix == '.json') or
            name.startswith(FRONT+'/public/'))


def pack(root=ROOT, output=None):
    root = Path(root).resolve()
    output = Path(output or root/'outputs/team'/NAME).resolve()
    if root not in output.parents or output == root/'data/mayhem.sqlite':
        raise ValueError('bundle_output_must_be_inside_project')
    output.parent.mkdir(parents=True, exist_ok=True)
    with project_locks(root), tempfile.TemporaryDirectory(prefix='team-pack-', dir=output.parent) as folder:
        from release_inputs import data_inputs
        data_identity = data_inputs(root)
        if json_read(root/'work/build/data-state.json').get('inputs') != data_identity:
            raise RuntimeError('data_inputs_not_built: run the maintained build before packaging')
        manifest = json_read(root/FRONT/'public/api/manifest.json')
        full = json_read(root/'work/build/snapshot.full.json')
        baseline = json_read(root/'data/haido-baseline-v4.json')
        if full.get('snapshot_kind') != 'full' or full.get('build_id') != manifest.get('build_id'):
            raise RuntimeError('data_generation_mismatch')
        database = Path(folder)/'mayhem.sqlite'
        count = database_backup(root/'data/mayhem.sqlite', database)
        if count != manifest.get('database_matches'):
            raise RuntimeError('database_not_built: run the maintained build before packaging')
        paths = {'data/mayhem.sqlite': database}
        for name in CONFIGS:
            path = root/'data'/name
            if path.is_file():
                paths['data/'+name] = path
        for relative in ('data/raw', FRONT+'/public'):
            directory = root/relative
            if directory.exists():
                inventory = inspect_tree(directory)
                for name in inventory.files:
                    relative_name = relative+'/'+name
                    if not allowed_member(relative_name):
                        raise ValueError('unexpected_bundle_file:'+relative_name)
                    paths[relative_name] = directory/name
        for name in ('work/build/snapshot.full.json', 'work/build/cache/details.bundle.json', 'haido/haido_scores_lp.json'):
            if (root/name).is_file():
                paths[name] = root/name
        if set(REQUIRED)-paths.keys():
            raise RuntimeError('required_bundle_files_missing')
        hashes = {name: file_hash(path) for name, path in sorted(paths.items())}
        metadata = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'build_id': manifest['build_id'], 'rating_version': manifest['rating_version'],
                    'database_matches': count, 'players': manifest['players'],
                    'baseline_sha256': hashes['data/haido-baseline-v4.json'],
                    'baseline_players': len(baseline['players']), 'files': hashes}
        temporary = Path(folder)/NAME
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr('bundle.json', json.dumps(metadata, ensure_ascii=False))
            for name, path in sorted(paths.items()):
                archive.write(path, name)
        # Read every decompressed member again; do not accept a CRC-only success.
        verify_archive(temporary)
        if data_inputs(root) != data_identity:
            raise RuntimeError('data_changed_during_packaging')
        os.replace(temporary, output)
        digest = file_hash(output)
        output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n', encoding='ascii')
        return {'ok': True, 'archive': str(output), 'sha256': digest, 'bytes': output.stat().st_size,
                'artifact_sha256': json_read(root/'work/build/release-result.json').get('artifact_sha256'),
                'build_id': metadata['build_id'], 'database_matches': count, 'files': len(hashes)}


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or 'bundle.json' not in names:
            raise ValueError('invalid_archive_members')
        info = json.loads(archive.read('bundle.json'))
        if info.get('format') != 1 or set(names) != {'bundle.json', *info['files']}:
            raise ValueError('invalid_archive_inventory')
        if set(REQUIRED)-info['files'].keys():
            raise ValueError('required_bundle_files_missing')
        if sum(x.file_size for x in archive.infolist()) > 16*1024**3:
            raise ValueError('bundle_too_large')
        for name, expected in info['files'].items():
            member = archive.getinfo(name)
            if not allowed_member(name) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('unsafe_bundle_member:'+name)
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError('bundle_hash_mismatch:'+name)
        return info


def install(path, root=ROOT, replace=False):
    root = Path(root).resolve()
    if (root/'.workbuddy/applications.yaml').exists() or any(root.glob('.wbapp_*.genie')):
        raise RuntimeError('refuse_install_on_publisher: this command is for collaborator checkouts')
    info = verify_archive(path)
    if (root/'data/mayhem.sqlite').exists() and not replace:
        raise RuntimeError('existing_data: pass --replace to back up and update your development copy')
    if any((root/('data/mayhem.sqlite'+suffix)).exists() for suffix in ('-wal','-shm')):
        raise RuntimeError('database_sidecars_present: close all database users before installing')
    staging = root/'outputs/team-import'
    staging.mkdir(parents=True, exist_ok=True)
    with project_locks(root), tempfile.TemporaryDirectory(prefix='stage-', dir=staging) as directory:
        stage = Path(directory)
        with zipfile.ZipFile(path) as archive:
            for name in info['files']:
                target = stage/name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
        from workflow_guard import check_database_routes
        check_database_routes(stage)
        with closing(sqlite3.connect((stage/'data/mayhem.sqlite').as_uri()+'?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(db.execute('PRAGMA foreign_key_check')):
                raise ValueError('download_database_invalid')
            if db.execute('SELECT count(*) FROM matches').fetchone()[0] != info['database_matches']:
                raise ValueError('download_database_count_mismatch')
        for name in info['files']:
            target = root/name
            if root not in target.resolve().parents or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [target, *target.parents] if p != root and root in p.parents):
                raise ValueError('linked_install_target:'+name)
        # Back up every overwritten file before the first replacement. It doubles
        # as rollback material if a later replacement fails.
        rollback = staging/'previous-data.zip'
        with zipfile.ZipFile(rollback.with_suffix('.tmp'), 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in info['files']:
                if (root/name).is_file():
                    archive.write(root/name, name)
        os.replace(rollback.with_suffix('.tmp'), rollback)
        changed = []
        try:
            for name in info['files']:
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage/name, target)
                changed.append(name)
        except BaseException:
            with zipfile.ZipFile(rollback) as archive:
                old = set(archive.namelist())
                for name in reversed(changed):
                    target = root/name
                    if name in old:
                        with archive.open(name) as src, target.open('wb') as dst:
                            shutil.copyfileobj(src, dst)
                    else:
                        target.unlink()
            raise
        json_write(root/'work/build/team-data.json', {k:v for k,v in info.items() if k != 'files'})
        return {'ok': True, 'build_id': info['build_id'], 'database_matches': info['database_matches'],
                'rollback': str(rollback)}


def gh(*args, capture=True):
    executable = shutil.which('gh')
    if not executable:
        raise RuntimeError('github_cli_missing: install gh and run gh auth login')
    result = subprocess.run([executable, *map(str,args)], check=True, text=True,
                            encoding='utf-8', capture_output=capture, timeout=900)
    return result.stdout.strip() if capture else ''


def check_repository(repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('invalid_repository')
    info = json.loads(gh('repo','view',repository,'--json','nameWithOwner,isPrivate'))
    if not info['isPrivate'] and info['nameWithOwner'].casefold() != REPOSITORY.casefold():
        raise ValueError('public_data_repository_not_authorized')


def publish(root=ROOT, repository=REPOSITORY):
    root = Path(root)
    check_repository(repository)
    result = pack(root)
    tag = datetime.now(timezone.utc).strftime('data-%Y%m%dT%H%M%SZ')
    archive = Path(result['archive'])
    notes = archive.parent/'release-notes.txt'
    notes.write_text('完整团队开发数据；安装前先更新 main 源码。\n'
                     f"build_id: {result['build_id']}\n数据库对局数: {result['database_matches']}\n"
                     '含已获准公开的游戏身份与完整战绩；不含访客统计和登录、发布凭据。\n'
                     '数据Release不是网站发布，也不是GitHub Pages。\n', encoding='utf-8')
    gh('release','create',tag,archive,archive.with_name(archive.name+'.sha256'),
       '--repo',repository,'--target','main','--title',tag,'--notes-file',notes,'--latest')
    remote = json.loads(gh('release','view',tag,'--repo',repository,'--json','assets,url'))
    sizes = {x['name']:x['size'] for x in remote['assets']}
    if sizes.get(NAME) != result['bytes']:
        raise RuntimeError('release_upload_not_verified')
    result.update({'tag':tag,'url':remote['url'],'repository':repository})
    json_write(root/'work/build/team-upload.json', result)
    return result


def download(root=ROOT, repository=REPOSITORY, tag=None, replace=False):
    root = Path(root)
    if (root/'.workbuddy/applications.yaml').exists() or any(root.glob('.wbapp_*.genie')):
        raise RuntimeError('refuse_download_on_publisher')
    check_repository(repository)
    if tag is None:
        tag = json.loads(gh('release','view','--repo',repository,'--json','tagName'))['tagName']
    directory = root/'outputs/team-download'
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='download-', dir=directory) as folder:
        gh('release','download',tag,'--repo',repository,'--pattern',NAME,'--pattern',NAME+'.sha256','--dir',folder)
        archive = Path(folder)/NAME
        expected = (Path(folder)/(NAME+'.sha256')).read_text(encoding='ascii').split()[0]
        if not re.fullmatch('[a-f0-9]{64}',expected) or file_hash(archive) != expected:
            raise ValueError('download_checksum_failed')
        result = install(archive, root, replace)
        result.update({'tag':tag,'repository':repository})
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('pack','install','publish','download'))
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--repo', default=REPOSITORY)
    parser.add_argument('--tag')
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'pack':
        result = pack(output=args.archive)
    elif args.command == 'install':
        if not args.archive:
            parser.error('install requires --archive')
        result = install(args.archive, replace=args.replace)
    elif args.command == 'publish':
        result = publish(repository=args.repo)
    else:
        result = download(repository=args.repo, tag=args.tag, replace=args.replace)
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
