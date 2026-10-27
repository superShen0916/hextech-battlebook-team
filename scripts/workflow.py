"""Shared maintenance entry. Run Workflow.cmd --help; hosting remains an external action."""
from __future__ import annotations

import argparse
from contextlib import closing, ExitStack
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'scripts')]
from project_paths import FRONTEND as FRONT, RELEASE
from snapshot_io import write_json
from node_runtime import resolve_node, node_environment
from release_files import file_hash, tree_hash, inspect_tree
from release_inputs import (data_inputs, frontend_inputs, rating_week,
                            validation_code_inputs, validation_inputs)
from release_reuse import read_state, can_reuse_frontend
from sync_release import synchronize_release
from release_checks import frontend_commands
from public_site import _exclusive_lock

BUILD = ROOT / 'work/build'
RECEIPT = BUILD / 'workflow-receipt.json'
ONLINE = 'https://hextech-battlebook.app.workbuddy.host/?sharecode=7ZFAIH5YHV'
SCOPES = {'docs': 0, 'frontend': 1, 'data': 2, 'pipeline': 3}
FRONT_REL = FRONT.relative_to(ROOT).as_posix() + '/'


def normalize_file(value, root=ROOT):
    path = (Path(root) / value).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        raise ValueError('file_outside_project:' + value)


def changed_files():
    tracked = subprocess.check_output(['git', '-c', 'core.safecrlf=false', 'diff', '--name-only', '-z', 'HEAD'], cwd=ROOT)
    others = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    return sorted(set(p.decode('utf-8') for p in (tracked + others).split(b'\0') if p))


def classify(files):
    groups = {key: [] for key in SCOPES}
    for name in files:
        if name.endswith(('.md', '.txt')) or name.startswith('docs/'):
            group = 'docs'
        elif name.startswith(FRONT_REL + ('src/')) or name.startswith(FRONT_REL + 'lib/'):
            group = 'frontend'
        elif name.startswith(FRONT_REL) and not Path(name).name.startswith('prepare-'):
            group = 'frontend'
        elif name in ('data/public-profiles.json', 'data/stat-exclusions.json') or name.startswith('app/static/'):
            group = 'data'
        else:
            group = 'pipeline'  # unknown runtime changes must receive the wider checks
        groups[group].append(name)
    scope = max((key for key, rows in groups.items() if rows), key=SCOPES.get, default='docs')
    return scope, groups


def make_plan(files, requested='auto'):
    inferred, groups = classify(files)
    # Explicit lists scope this task; --scope may widen, never silently narrow it.
    if requested != 'auto' and SCOPES[requested] < SCOPES[inferred]:
        raise ValueError(f'scope_too_narrow:{requested}; detected {inferred}; use --files for this task')
    scope = inferred if requested == 'auto' else requested
    return {'scope': scope, 'files': files, 'groups': groups,
            'build_mode': None if scope == 'docs' else '--data-only',
            'python_tests': scope == 'pipeline',
            'checks': ['check_state'] if scope == 'docs' else [
                *(['python_suite'] if scope == 'pipeline' else []),
                'data_privacy_rating_gates', 'typescript', 'seven_frontend_checks',
                'browser_1440_390_320', 'sha256_sync_after_browser'],
            'note': 'No collection. Data fingerprints detect drift and week changes; unchanged data is reused.'}


def code_identity(node_version):
    return validation_code_inputs(ROOT, FRONT, node_version)


def source_identity(node_version, data_key=None):
    return validation_inputs(ROOT, FRONT, node_version, data_key)


def stop_process_tree(child):
    """Terminate only the process group/tree this workflow started."""
    if child.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=15, check=True)
    else:
        os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=15)


def checked_receipt(receipt, source, dist_hash, release_hash, scope='frontend'):
    if not receipt.get('ok') or not receipt.get('ready'):
        raise RuntimeError('no_successful_preparation; run Workflow.cmd prepare')
    if SCOPES.get(receipt.get('scope'), -1) < SCOPES[scope]:
        raise RuntimeError('receipt_scope_too_narrow; run prepare for this scope')
    if receipt.get('source_sha256') != source:
        raise RuntimeError('source_changed_after_validation; run prepare again')
    if receipt.get('dist_sha256') != dist_hash or receipt.get('release_sha256') != release_hash:
        raise RuntimeError('artifact_changed_after_validation; run prepare again')
    if dist_hash != release_hash:
        raise RuntimeError('dist_release_mismatch')
    return receipt


def run_step(command, cwd, output, name, stages, env=None, timeout=1800):
    started = time.perf_counter()
    log = output / (name + '.log')
    print('STEP', name, str(log), flush=True)
    group = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
             if os.name == 'nt' else {'start_new_session': True})
    with log.open('w', encoding='utf-8') as stream:
        with subprocess.Popen(list(map(str, command)), cwd=cwd, env=env,
                              stdout=stream, stderr=subprocess.STDOUT, **group) as child:
            try:
                code = child.wait(timeout=timeout)
            except BaseException as exc:
                stop_process_tree(child)
                if isinstance(exc, subprocess.TimeoutExpired):
                    raise RuntimeError(f'step_timeout:{name}; log={log}') from exc
                raise
    stages.append({'name': name, 'seconds': round(time.perf_counter()-started, 3), 'log': str(log)})
    if code:
        tail = '\n'.join(log.read_text(encoding='utf-8', errors='replace').splitlines()[-12:])
        raise RuntimeError(f'step_failed:{name}:{code}\n{tail}\nlog={log}')
    print('PASS', name, stages[-1]['seconds'], 'seconds', flush=True)
    return log


def browser_command(node, out, url=None):
    return [node, ROOT / 'tests/browser/smoke.mjs', '--out', out,
            *(['--url', url] if url else ['--root', FRONT / 'dist'])]


def online_paths(base):
    """Published entry chunks plus representative full data, never just build_id."""
    paths = {'index.html', 'intel.html', 'share/index.html', 'api/manifest.json',
             'api/snapshot.json', 'api/weekly.json', 'api/recaps/index.json', 'matches/index.json'}
    for rel in ('index.html', 'intel.html', 'share/index.html'):
        text = (base / rel).read_text(encoding='utf-8')
        paths.update(re.findall(r'[/]?assets/[A-Za-z0-9_.-]+\.(?:js|css)', text))
    # Include split/lazy assets, so identical data IDs cannot hide an old frontend.
    paths.update(p.relative_to(base).as_posix() for p in (base / 'assets').rglob('*')
                 if p.is_file() and p.suffix in ('.js', '.css'))
    snap = json.loads((base / 'api/snapshot.json').read_text(encoding='utf-8'))
    profile = max(snap['players'], key=lambda p: p.get('summary', {}).get('games', 0))
    paths.add(profile['detail_url'].lstrip('/'))
    paths.add(snap['achievements_url'].lstrip('/'))
    full = json.loads((base / profile['detail_url'].lstrip('/')).read_text(encoding='utf-8'))
    if full.get('recent'):
        paths.add('matches/' + full['recent'][0]['id'] + '.json')
    recap = json.loads((base / 'api/recaps/index.json').read_text(encoding='utf-8'))
    if recap['nights']:
        paths.add('api/recaps/nights/' + recap['nights'][0]['date'] + '.json')
    return sorted({p.lstrip('/') for p in paths})


def audit_online(base=RELEASE):
    rows = []
    for rel in online_paths(base):
        request = urllib.request.Request(urllib.parse.urljoin(ONLINE, rel) +
            '?sharecode=7ZFAIH5YHV&workflow=' + uuid.uuid4().hex,
            headers={'User-Agent': 'BattlebookWorkflow', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=30) as response:
            digest = hashlib.sha256(response.read()).hexdigest()
        rows.append({'path': rel, 'sha256': digest, 'ok': digest == file_hash(base / rel)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'doctor', 'check', 'prepare', 'ready', 'online'))
    parser.add_argument('--scope', choices=('auto', *SCOPES), default='auto')
    parser.add_argument('--files', nargs='+', help='explicit project-relative files for this task; other edits are untouched')
    args = parser.parse_args()
    files = [normalize_file(p) for p in args.files] if args.files else changed_files()
    plan = make_plan(files, args.scope)
    if args.action == 'plan':
        print(json.dumps(plan, ensure_ascii=False, indent=2)); return 0
    node, version = resolve_node()
    env = node_environment(node)
    BUILD.mkdir(parents=True, exist_ok=True)
    if args.action == 'doctor':
        subprocess.run([node, ROOT / 'tests/browser/smoke.mjs', '--doctor'], env=env, check=True)
        print('DOCTOR_OK', version); return 0
    run_id = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    output = ROOT / 'outputs/workflow' / run_id
    output.mkdir(parents=True)
    report = {'ok': False, 'ready': False, 'action': args.action, 'run_id': run_id,
              'scope': plan['scope'], 'plan': plan, 'output': str(output), 'stages': []}
    step = lambda cmd, cwd, name, timeout=1800: run_step(cmd, cwd, output, name, report['stages'], env, timeout)
    try:
        with _exclusive_lock(BUILD / 'workflow.lock') as acquired:
            if not acquired:
                raise RuntimeError('workflow_already_running; wait; do not remove locks')
            if args.action in ('prepare', 'check'):
                if plan['scope'] != 'docs':
                    write_json(RECEIPT, report)  # a failed attempt never leaves a stale READY receipt
                if plan['scope'] == 'docs':
                    step([sys.executable, ROOT / 'scripts/check_state.py'], ROOT, 'state')
                else:
                    code_before = code_identity(version)
                    week_before = rating_week()
                    step([node, ROOT / 'tests/browser/smoke.mjs', '--doctor'], ROOT, 'browser-environment', 60)
                    if plan['python_tests']:
                        step([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'], ROOT, 'python')
                    if args.action == 'prepare':
                        log = step([sys.executable, ROOT / 'scripts/build_release.py', '--data-only'], ROOT, 'build')
                        fresh = [line[len('RELEASE_READY '):] for line in log.read_text(encoding='utf-8').splitlines()
                                 if line.startswith('RELEASE_READY ')]
                        if not fresh or json.loads(fresh[-1]) != read_state(BUILD / 'release-result.json'):
                            raise RuntimeError('missing_or_stale_build_receipt')
                    # Hold the build lock during browser checks and synchronization.
                    # Another build may have run between the child exiting and this acquisition;
                    # the matching frontend receipt and data gates below reject stale shells.
                    with _exclusive_lock(BUILD / 'release.lock') as build_acquired, ExitStack() as resources:
                        if not build_acquired:
                            raise RuntimeError('release_already_running; retry after it finishes')
                        # Persistent read-only connection detects any concurrent SQLite
                        # commit. Hash DB content once; do not rescan it after each step.
                        monitor = resources.enter_context(closing(sqlite3.connect(
                            (ROOT / 'data/mayhem.sqlite').as_uri() + '?mode=ro', uri=True)))
                        observed_version = monitor.execute('PRAGMA data_version').fetchone()[0]
                        data_key = data_inputs(ROOT)
                        if data_key != read_state(BUILD / 'data-state.json').get('inputs'):
                            raise RuntimeError('data_source_changed_since_build; run prepare')
                        source = source_identity(version, data_key)
                        if code_identity(version) != code_before:
                            raise RuntimeError('code_changed_during_tests_or_build; run prepare again')
                        if not can_reuse_frontend(read_state(BUILD / 'frontend-receipt.json'),
                                                  frontend_inputs(FRONT, version), FRONT / 'dist'):
                            raise RuntimeError('frontend_source_or_dist_changed; run prepare')
                        if args.action == 'check':
                            step([sys.executable, ROOT / 'scripts/verify_release.py', '--api', FRONT / 'dist/api'], ROOT, 'data-gates')
                            for index, (cmd, cwd) in enumerate(frontend_commands(node, FRONT)):
                                step(cmd, cwd, 'frontend-' + str(index))
                        before = tree_hash(FRONT / 'dist')
                        step(browser_command(node, output / 'browser'), ROOT, 'browser', 240)
                        def stable_inputs():
                            return (code_identity(version) == code_before and rating_week() == week_before and
                                    monitor.execute('PRAGMA data_version').fetchone()[0] == observed_version)
                        verified = inspect_tree(FRONT / 'dist')
                        if not stable_inputs() or verified.digest != before:
                            raise RuntimeError('inputs_changed_during_validation; retry after other work finishes')
                        report.update(source_sha256=source, dist_sha256=before,
                                      build_id=read_state(BUILD / 'release-result.json').get('build_id'))
                        if args.action == 'prepare':
                            # Use the bytes just verified after browser checks. The
                            # shared synchronizer fully verifies the destination.
                            sync_started = time.perf_counter()
                            print('STEP sync', str(output / 'sync.json'), flush=True)
                            try:
                                sync = synchronize_release(verified)
                                write_json(output / 'sync.json', sync)
                            except Exception as error:
                                write_json(output / 'sync.json', {'ok': False, 'error': str(error)})
                                raise
                            finally:
                                report['stages'].append({'name': 'sync', 'seconds': round(time.perf_counter()-sync_started, 3),
                                                         'log': str(output / 'sync.json')})
                            print('PASS sync (full content verified)', report['stages'][-1]['seconds'], flush=True)
                            report['release_sha256'] = sync['artifact_sha256']
                            if report['release_sha256'] != before or not stable_inputs():
                                raise RuntimeError('release_or_source_changed_during_sync')
                            report['ready'] = True
                            result = read_state(BUILD / 'release-result.json')
                            result['release_directory_synced'] = True
                            write_json(BUILD / 'release-result.json', result)
            else:
                with _exclusive_lock(BUILD / 'release.lock') as build_acquired:
                    if not build_acquired:
                        raise RuntimeError('release_already_running')
                    saved = checked_receipt(read_state(RECEIPT), source_identity(version),
                                            tree_hash(FRONT / 'dist'), tree_hash(RELEASE), plan['scope'])
                    report['validated_run_id'] = saved['run_id']
                    if args.action == 'online':
                        hashes = audit_online()
                        write_json(output / 'online-hashes.json', hashes)
                        if not all(row['ok'] for row in hashes):
                            raise RuntimeError('online_resource_mismatch; see online-hashes.json')
                        step(browser_command(node, output / 'browser', ONLINE), ROOT, 'online-browser', 300)
                        checked_receipt(saved, source_identity(version), tree_hash(FRONT / 'dist'), tree_hash(RELEASE), plan['scope'])
                    report['ready'] = True
            report['ok'] = True
            if args.action in ('prepare', 'check') and plan['scope'] != 'docs':
                write_json(RECEIPT, report)
    except (Exception, KeyboardInterrupt) as exc:
        report['ready'] = False
        report['error'] = str(exc)
        # Only overwrite the attempt we own; a lock conflict must not destroy another run.
        if read_state(RECEIPT).get('run_id') == run_id:
            write_json(RECEIPT, report)
        print('WORKFLOW_FAILED', str(exc), flush=True)
    finally:
        write_json(output / 'result.json', report)
        write_json(BUILD / 'workflow-latest.json', report)
    print(('WORKFLOW_READY' if report['ready'] else 'WORKFLOW_OK') if report['ok'] else 'WORKFLOW_NOT_READY',
          str(output / 'result.json'), flush=True)
    if report['ready'] and args.action != 'online':
        print('Hosting still requires publishing the existing WorkBuddy app; then run Workflow.cmd online.', flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
