"""One maintained build entry. Checks pass before replacing dist or release files.

--sync mirrors the verified build to the existing WorkBuddy publish directory.
Hosting publication remains a separate WorkBuddy action. No Sites upload occurs.
"""
import argparse
from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import sys
import zipfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from project_paths import FRONTEND as FRONT
from node_runtime import resolve_node, node_environment
from release_checks import frontend_commands
from release_files import inspect_tree, FileTree
from release_inputs import data_inputs, data_outputs, frontend_inputs, validation_code_inputs
from sync_release import synchronize_release
NODE = None
TIMINGS = []


@contextmanager
def stage(name, kind='internal'):
    started = time.perf_counter()
    try:
        yield
    finally:
        TIMINGS.append({'command': name, 'kind': kind, 'seconds': round(time.perf_counter() - started, 3)})
        print('STAGE_SECONDS', json.dumps(TIMINGS[-1]), flush=True)


def command(args, cwd=ROOT):
    print('RUN', ' '.join(map(str, args)), flush=True)
    with stage(Path(str(args[1])).name if len(args) > 1 else str(args[0]), 'process'):
        subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def main():
    global NODE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sync', action='store_true')
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument('--full', action='store_true', help='force the complete uncached data/frontend build (also the default)')
    modes.add_argument('--reuse-full', action='store_true', help='keep the last full archive; still regenerate dependent files')
    modes.add_argument('--frontend-only', action='store_true', help='validate existing data and rebuild page source only')
    modes.add_argument('--data-only', action='store_true', help='reuse unchanged projections/details and a verified frontend; run every gate')
    ap.add_argument('--force-data', action='store_true', help='diagnostic: regenerate dependent data even when inputs are unchanged')
    args = ap.parse_args()
    if args.force_data and not args.data_only:
        ap.error('--force-data requires --data-only')
    sys.path.insert(0, str(ROOT / 'app'))
    from public_site import _exclusive_lock
    from verify_release import verify
    from snapshot_io import write_json
    from release_reuse import (read_state, can_reuse_frontend,
                               tree_hash, is_dataset, assemble_data_release, assemble_frontend_release, promote)
    build = ROOT / 'work/build'
    build.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(build / 'release.lock') as acquired:
        if not acquired:
            raise RuntimeError('release_already_running; wait for the existing build')
        NODE, node_version = resolve_node()
        os.environ.update(node_environment(NODE))
        print('PINNED_NODE', NODE, node_version, flush=True)
        from workflow_guard import check_database_routes
        print('DATABASE_ROUTES_OK', json.dumps(check_database_routes(ROOT)), flush=True)
        started = time.perf_counter()
        rating_as_of_ms = int(time.time() * 1000)
        with stage('pipeline-inputs'):
            pipeline_key = validation_code_inputs(ROOT, FRONT, node_version)
        state = read_state(build / 'data-state.json')
        receipt = read_state(build / 'frontend-receipt.json')
        initial_inputs = None
        unchanged = False
        if not args.reuse_full and not args.frontend_only:
            command([sys.executable, ROOT / 'scripts/reconcile_archives.py', '--apply'])
            with stage('data-inputs-and-cache'):
                initial_inputs = data_inputs(ROOT, rating_as_of_ms)
                if args.data_only and not args.force_data and state.get('inputs') == initial_inputs:
                    try:
                        unchanged = state.get('outputs') == data_outputs(ROOT)
                    except OSError:
                        pass
            if not unchanged:
                command([sys.executable, ROOT / 'scripts/export_public_snapshot.py', *(['--incremental'] if args.data_only else [])])
        if not args.frontend_only and not unchanged:
            command([sys.executable, FRONT / 'prepare-match-details.py', *(['--incremental'] if args.data_only else [])])
            command([sys.executable, ROOT / 'haido/rating_lp.py', '--bundle', build / 'cache/details.bundle.json',
                     '--as-of-ms', rating_as_of_ms,
                     '--out', ROOT / 'haido/haido_scores_lp.json'])
            command([sys.executable, ROOT / 'scripts/inject_haido_ratings.py', '--scores', ROOT / 'haido/haido_scores_lp.json', '--snapshot', build / 'snapshot.full.json'])
            command([sys.executable, ROOT / 'scripts/inject_ranked_bounds.py', '--snapshot', build / 'snapshot.full.json'])
            command([sys.executable, ROOT / 'scripts/build_recaps.py', '--bundle', build / 'cache/details.bundle.json'])
            command([sys.executable, ROOT / 'scripts/build_weekly.py', '--bundle', build / 'cache/details.bundle.json', '--as-of-ms', rating_as_of_ms])
            command([NODE, 'prepare-achievements.mjs'], FRONT)
            command([sys.executable, ROOT / 'scripts/split_snapshot.py'])
        if unchanged:
            print('DATA_UNCHANGED: complete input and output fingerprints match; all release checks still run.', flush=True)
        with stage('verify-public-data'):
            report = verify(write_manifest=True, expected_week_ms=rating_as_of_ms)
        for check, cwd in frontend_commands(NODE, FRONT):
            command(check, cwd)
        dist = FRONT / 'dist'
        with stage('frontend-inputs-and-cache'):
            front_key = frontend_inputs(FRONT, node_version)
            reuse_front = args.data_only and can_reuse_frontend(receipt, front_key, dist)
        next_dist = build / 'candidate'
        rotation = build / 'rotation-previous'
        if rotation.exists():
            if next_dist.exists():
                raise RuntimeError('unfinished_slot_rotation; inspect rotation-previous')
            os.replace(rotation, next_dist)
        assembled = {}
        dist_current = False
        if reuse_front:
            print('FRONTEND_REUSED: source, dependencies, runtime and built shell match the verified receipt.', flush=True)
            if unchanged:
                with stage('existing-data-content'):
                    dist_current = (tree_hash(dist / 'api') == tree_hash(FRONT / 'public/api') and
                                    tree_hash(dist / 'matches') == tree_hash(FRONT / 'public/matches'))
            if not dist_current:
                with stage('assemble-candidate'):
                    assembled = assemble_data_release(dist, FRONT / 'public', next_dist)
                print('DATA_ASSEMBLED', json.dumps(assembled), flush=True)
        else:
            if args.data_only:
                print('FRONTEND_BASELINE_REQUIRED: no matching verified receipt; building once, then future data updates reuse it.', flush=True)
            command([NODE, 'build-shell.mjs', str(next_dist)], FRONT)
            generated = json.loads((build / 'frontend-outputs.json').read_text(encoding='utf-8'))
            with stage('assemble-candidate'):
                assemble_frontend_release(FRONT / 'public', next_dist, generated)
        candidate = dist if dist_current else next_dist
        with stage('verify-candidate-data'):
            verify(candidate / 'api', expected_week_ms=rating_as_of_ms)
        with stage('candidate-content'):
            artifact = inspect_tree(candidate)
        with stage('verify-inputs-stable'):
            if initial_inputs is not None and data_inputs(ROOT) != initial_inputs:
                raise RuntimeError('inputs_changed_during_build; previous dist/release preserved; retry after collection completes')
            if validation_code_inputs(ROOT, FRONT, node_version) != pipeline_key:
                raise RuntimeError('pipeline_changed_during_build; previous dist/release preserved')
        backup = ROOT / 'backups/release-before-maintenance.zip'
        if dist.is_dir() and not backup.exists():
            backup.parent.mkdir(exist_ok=True)
            with stage('create-initial-rollback'), zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                for path in dist.rglob('*'):
                    if path.is_file():
                        archive.write(path, path.relative_to(dist))
            with zipfile.ZipFile(backup) as archive:
                if archive.testzip():
                    raise RuntimeError('rollback_archive_invalid')
        if not dist_current:
            with stage('promote-candidate'):
                retired = promote(next_dist, dist, build / 'dist-previous', build)
            # Promotion only renames this verified tree, under release.lock.
            artifact = FileTree(dist.resolve(), artifact.files)
        else:
            retired = None
        write_json(build / 'frontend-receipt.json', {'inputs': front_key,
                   'shell': artifact.digest_for(lambda p: not is_dataset(p)), 'node': node_version})
        if initial_inputs is not None:
            with stage('record-data-cache'):
                write_json(build / 'data-state.json', {'inputs': initial_inputs, 'outputs': data_outputs(ROOT)})
        if args.sync:
            with stage('sync-and-verify'):
                sync = synchronize_release(artifact)
            print('SYNC_DONE', json.dumps(sync, ensure_ascii=False), flush=True)
            print('SYNC_OK full content verified', flush=True)
        report['release_directory_synced'] = args.sync
        report['hosting_published'] = False
        report.update(mode='data-only' if args.data_only else 'frontend-only' if args.frontend_only else 'reuse-full' if args.reuse_full else 'full',
                      data_unchanged=unchanged, frontend_reused=bool(reuse_front),
                      retired_previous=retired.name if retired else None,
                      retention_policy='one_previous_one_reusable_candidate', node_version=node_version,
                      artifact_sha256=artifact.digest,
                      total_seconds=round(time.perf_counter() - started, 3), stages=TIMINGS, **assembled)
        write_json(build / 'release-result.json', report)
        print('RELEASE_READY', json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
