"""One reviewed maintenance cleanup. Exact inventory, verified restore points first.

No broad work/data deletion; fixed build slots, the running DB and release stay.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile

from team_data import ROOT, CONFIGS, database_backup, project_locks, json_write
from release_files import file_hash, inspect_tree


def checked(root, path):
    root=Path(root).resolve(); path=Path(path)
    if root not in path.resolve().parents:
        raise ValueError('cleanup_outside_project:'+str(path))
    for parent in [path,*path.parents]:
        if parent==root:break
        if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():
            raise ValueError('cleanup_link:'+str(parent))
    return path.resolve()


def archive_history(root=ROOT):
    root=Path(root).resolve(); destination=root/'backups/restore-point/legacy-audit.zip'
    if destination.exists():
        return {'archive':str(destination),'sha256':file_hash(destination),'already_exists':True}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='audit-',dir=destination.parent) as directory:
        bundle=Path(directory)/'history.bundle'
        subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=root,check=True,capture_output=True)
        subprocess.run(['git','bundle','verify',str(bundle)],cwd=root,check=True,capture_output=True)
        temporary=Path(directory)/destination.name
        members={}
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as output:
            output.write(bundle,'history.bundle');members['history.bundle']=file_hash(bundle)
            tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
            for name in tracked:
                path=root/name
                if path.is_file() and (name.startswith('docs/') or name in ('AGENTS.md','README.md','WORKBUDDY-HANDOFF.txt') or '/_archive/' in name):
                    output.write(path,name);members[name]=file_hash(path)
            for path in (root/'backups').glob('*.zip'):
                if path.name!='rating-5.1-before.zip':
                    name='old-recovery/'+path.name;output.write(path,name);members[name]=file_hash(path)
            output.writestr('audit-inventory.json',json.dumps(members,ensure_ascii=False))
        verify_zip(temporary,members)
        os.replace(temporary,destination)
    return {'archive':str(destination),'sha256':file_hash(destination),'files':len(members)}


def verify_zip(path, expected):
    import hashlib
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:raise RuntimeError('zip_crc_failed')
        for name, checksum in expected.items():
            digest=hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda:stream.read(1<<20),b''):digest.update(chunk)
            if digest.hexdigest()!=checksum:raise RuntimeError('backup_stream_hash_failed:'+name)


def restore_points(root=ROOT):
    root=Path(root).resolve();target=root/'backups/restore-point';target.mkdir(parents=True,exist_ok=True)
    with project_locks(root),tempfile.TemporaryDirectory(prefix='restore-',dir=target) as directory:
        stage=Path(directory);db=stage/'database.sqlite'
        count=database_backup(root/'data/mayhem.sqlite',db)
        source=stage/'source.zip'
        tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
        new=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
        with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(set(tracked+new)):
                path=root/name
                if name and path.is_file() and not name.startswith(('data/','haido/haido_scores')):
                    archive.write(path,name)
        members={'database.sqlite':db,'source.zip':source}
        for name in CONFIGS:
            path=root/'data'/name
            if path.is_file():members[name]=path
        # Preserve raw summaries used for avatar/source reconstruction as well.
        for name in inspect_tree(root/'data/raw',missing_ok=True).files:
            members['raw/'+name]=root/'data/raw'/name
        hashes={name:file_hash(path) for name,path in members.items()}
        temporary=stage/'database.zip'
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,path in members.items():archive.write(path,name)
        verify_zip(temporary,hashes)
        # Exercise the restore path with an extracted DB, not only the source copy.
        restored=stage/'restored.sqlite'
        with zipfile.ZipFile(temporary) as archive,archive.open('database.sqlite') as src,restored.open('wb') as dst:
            shutil.copyfileobj(src,dst)
        with closing(sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True)) as check:
            if check.execute('pragma integrity_check').fetchone()[0]!='ok' or list(check.execute('pragma foreign_key_check')):
                raise RuntimeError('restore_test_failed')
        release=root/'outputs/public-site-20261022b';inventory=inspect_tree(release)
        website=stage/'website.zip'
        with zipfile.ZipFile(website,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in inventory.files:archive.write(release/name,name)
        verify_zip(website,inventory.files)
        os.replace(temporary,target/'database.zip');os.replace(website,target/'website.zip')
        manifest={'database':'data/mayhem.sqlite','counts':{'matches':count},
                  'created_at':datetime.now(timezone.utc).isoformat(),
                  'archive_sha256':file_hash(target/'database.zip'),'archive_bytes':(target/'database.zip').stat().st_size,
                  'members_sha256':hashes,'sqlite_integrity':'ok','foreign_key_errors':0,
                  'zip_crc_and_stream_sha256':'ok','restore_extraction_test':'ok',
                  'website_archive':'website.zip','website_sha256':file_hash(target/'website.zip'),
                  'website_build_id':json.loads((release/'api/manifest.json').read_text())['build_id'],
                  'website_files':len(inventory.files),'website_artifact_sha256':inventory.digest}
        json_write(target/'manifest.json',manifest)
        return manifest


OLD_OUTPUTS=('analytics-qa-20261024','arena-qa-20261024','compact-podium-qa-20261024',
    'damage40-release-20261026','published-audit-20261024','qa-42-20261026','qa-44-20261026',
    'rating-41-qa-20261024','rating-46-20261026','rating-47-20261026','rating-48-20261026',
    'rating-49-20261026','rating-scope-note-20261026','rating-win-priority-20261027',
    'recent10-qa-20261025','share-cap-40-20261026','weekly-qa-20261024',
    'workflow-online-baseline','workflow-smoke-development')


def plan(root=ROOT):
    root=Path(root).resolve();targets=[]
    targets+=list((root/'backups').glob('legacy-before-maintenance-*.sqlite'))
    targets += [p for p in (root/'backups').glob('*.zip') if p.name!='rating-5.1-before.zip']
    targets += [root/'backups'/name for name in ('database-backup-manifest.json','public-profiles-20261027-before-drop6.json',
               'public-profiles-20261027-before16.json','queue-adjust-20261026','recap-sharing-20261024',
               'single-database-20261024T093205Z','test-residue-20261026','workflow-audit-20261024','maintenance-20261024-v4')]
    targets += [root/'outputs'/name for name in OLD_OUTPUTS]
    targets += [root/'work/players-preview-20261022/_archive']
    targets += [p for p in (root/'docs/history').iterdir() if p.name!='CHANGELOG.md']
    targets += [root/'docs'/name for name in ('DEPLOYMENT-HANDOFF.md','WORKBUDDY-HANDOFF-20261023.txt',
               '交接_海斗分4.0.md','PERSONAL-PROFILES.md','DESIGN-EXPERIENCE.md','MVP.md','PRODUCT.md')]
    for path in sorted(root.glob('scripts/*.bak-*')):targets.append(path)
    rows=[]
    for path in targets:
        if not path.exists():continue
        absolute=checked(root,path)
        if path.is_dir():
            tree=inspect_tree(path);size=sum((path/name).stat().st_size for name in tree.files);digest=tree.digest;count=len(tree.files)
        else:size=path.stat().st_size;digest=file_hash(path);count=1
        rows.append({'path':str(absolute),'relative':path.relative_to(root).as_posix(),'bytes':size,'sha256':digest,'files':count})
    return rows


def apply(root=ROOT):
    root=Path(root).resolve();record=root/'backups/restore-point/records/team-cleanup.json'
    manifest=json.loads((root/'backups/restore-point/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('restore_extraction_test')!='ok':raise RuntimeError('fresh_restore_test_required')
    for name,key in [('database.zip','archive_sha256'),('website.zip','website_sha256')]:
        if file_hash(root/'backups/restore-point'/name)!=manifest[key]:raise RuntimeError('restore_point_changed')
    if not (root/'backups/restore-point/legacy-audit.zip').is_file():raise RuntimeError('history_archive_required')
    with project_locks(root):
        rows=plan(root);baseline=file_hash(root/'data/haido-baseline-v4.json')
        report={'status':'planned','items':rows,'deleted':[],'bytes_removed':0}
        json_write(record,report)
        for row in rows:
            path=checked(root,row['path'])
            current=inspect_tree(path).digest if path.is_dir() else file_hash(path)
            if current!=row['sha256']:raise RuntimeError('cleanup_target_changed:'+row['relative'])
            try:
                if path.is_dir():shutil.rmtree(path)
                else:path.unlink()
            except OSError as error:
                report.update(status='stopped',error=str(error));json_write(record,report);raise
            report['deleted'].append(row['relative']);report['bytes_removed']+=row['bytes'];json_write(record,report)
        if file_hash(root/'data/haido-baseline-v4.json')!=baseline:raise RuntimeError('protected_baseline_changed')
        report['status']='complete';json_write(record,report);return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('archive','backup','plan','apply'))
    args=parser.parse_args()
    result={'archive':archive_history,'backup':restore_points,'plan':plan,'apply':apply}[args.action]()
    if args.action=='backup':
        result={key:value for key,value in result.items() if key!='members_sha256'}
    print(json.dumps(result,ensure_ascii=False))
